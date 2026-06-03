import asyncio
from datetime import datetime
import inspect
import json
import subprocess
import time
import traceback
import warnings
from typing import Any, Literal, TypedDict

import anyio
import ollama
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph

import config
from src.client import connect_all_mcp_servers
from src.logger import append_log, log_llm_call, log_tool_call, tool_result_to_text
from src.message import (
    append_assistant_message,
    append_tool_message,
    build_dynamic_warning,
    build_turn_summary,
    dedupe_consecutive_messages,
    extract_tool_call_from_content,
)
from src.memory import append_memory_summary
from src.prompt import build_final_answer_prompt, build_system_prompt, normalize_chat_response
from src.stream import is_shell_noise_input, print_streaming

warnings.filterwarnings("ignore", category=DeprecationWarning)

def start_ollama():
    try:
        # 在背景啟動 Ollama 服務（避免阻塞 Python 程式）
        print("正在啟動 Ollama 服務...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 等待 3 秒讓服務完全初始化
        time.sleep(3)
        #subprocess.run(["ollama", "run", model])
               
    except FileNotFoundError:
        print("錯誤：找不到 ollama 指令。請確認已安裝 Ollama 並已加入系統環境變數 (PATH)。")

async def run_agent():
    while True:
        try:
            async with connect_all_mcp_servers() as mcp_bundle:
                all_ollama_tools = mcp_bundle.all_ollama_tools
                available_tool_names = mcp_bundle.available_tool_names

                if len(all_ollama_tools) > 0:
                    print(">>>>>>> MCP Servers:", len(all_ollama_tools), "Tools successfully initialized. \n")

                system_prompt = build_system_prompt()

                class State(TypedDict, total=False):
                    messages: list[dict[str, Any]]
                    executed_tool_calls: set[str]
                    failed_tools: set[str]
                    successful_tool_result_text: str
                    last_tool_text: str
                    observation_available: bool
                    llm_failed: bool
                    turn_iterations: int
                    user_input: str

                def _serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
                    serialized: list[dict[str, Any]] = []
                    for message in messages:
                        payload = dict(message)
                        payload.pop("tool_call_id", None)
                        serialized.append(payload)
                    return serialized

                # Minimal node logger using existing append_log to write structured JSON logs
                def node_logger(node_name: str):
                    def decorator(fn):
                        async def wrapper(state: State):
                            t0 = time.perf_counter()
                            try:
                                append_log({
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "event": "node.start",
                                    "node": node_name,
                                    "turn": state.get("turn_iterations"),
                                    "user_input": state.get("user_input"),
                                    "messages": _serialize_messages(state.get("messages", [])),
                                })
                            except Exception:
                                pass
                            try:
                                result = await fn(state)
                            except Exception as e:
                                dur = time.perf_counter() - t0
                                try:
                                    append_log({
                                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        "event": "node.error",
                                        "node": node_name,
                                        "duration_seconds": float(f"{dur:.4f}"),
                                        "error": str(e),
                                    })
                                except Exception:
                                    pass
                                raise
                            dur = time.perf_counter() - t0
                            # Summarize a few useful fields for downstream analysis
                            try:
                                summary = {
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "event": "node.end",
                                    "node": node_name,
                                    "duration_seconds": float(f"{dur:.4f}"),
                                    "turn": state.get("turn_iterations"),
                                    "user_input": state.get("user_input"),
                                    "messages": _serialize_messages(state.get("messages", [])),
                                }
                                # add a small snapshot of last_tool_text or last message
                                last_tool_text = None
                                try:
                                    last_tool_text = result.get("last_tool_text") if isinstance(result, dict) else None
                                except Exception:
                                    last_tool_text = None
                                if last_tool_text:
                                    summary["last_tool_text_snippet"] = str(last_tool_text)[:300]
                                append_log(summary)
                            except Exception:
                                pass
                            return result
                        return wrapper
                    return decorator

                @node_logger("agent")
                async def agent_node(state: State):
                    messages = list(state.get("messages", []))
                    messages = dedupe_consecutive_messages(messages)

                    warning = build_dynamic_warning(
                        state.get("executed_tool_calls", set()),
                        state.get("failed_tools", set()),
                        available_tool_names,
                    )
                    messages_for_llm = list(messages)
                    if warning:
                        messages_for_llm.append({"role": "system", "content": warning})

                    request_payload = {
                        "model": config.MODEL,
                        "messages": _serialize_messages(messages_for_llm),
                        "tools": "ollama_tools_summary",
                    }
                    start = time.perf_counter()
                    try:
                        if state.get("observation_available") or state.get("turn_iterations", 0) >= config.MAX_TOOL_LOOPS:
                            messages_for_llm.append(
                                {"role": "system", "content": build_final_answer_prompt(state.get("successful_tool_result_text", ""))}
                            )
                            request_payload["messages"] = _serialize_messages(messages_for_llm)
                            raw_response = ollama.chat(
                                model=config.MODEL,
                                messages=messages_for_llm,
                            )
                        else:
                            raw_response = ollama.chat(
                                model=config.MODEL,
                                messages=messages_for_llm,
                                tools=all_ollama_tools,
                                options={"temperature": 0.1},
                                format="json",
                            )
                        if inspect.isawaitable(raw_response):
                            raw_response = await raw_response
                        end = time.perf_counter()
                        log_llm_call(request_payload, response=raw_response, start=start, end=end)
                        response = normalize_chat_response(raw_response)
                    except Exception as e:
                        end = time.perf_counter()
                        log_llm_call(request_payload, response=None, error=e, start=start, end=end)
                        msg = str(e).lower()
                        if "model" in msg and "not found" in msg:
                            print(f"LLM error: {e}. Please check MODEL setting: {config.MODEL}")
                            return {"llm_failed": True}
                        raise

                    assistant_message = append_assistant_message(messages, response)
                    model_thought = assistant_message.get("content", "")
                    if model_thought:
                        print(f"> 模型思考: {model_thought}")

                    tool_calls = response.get("message", {}).get("tool_calls", [])
                    if not tool_calls:
                        content = assistant_message.get("content")
                        parsed_tool_call = extract_tool_call_from_content(content)
                        if parsed_tool_call is not None:
                            tool_calls = [parsed_tool_call]
                            assistant_message["tool_calls"] = tool_calls
                            messages[-1] = assistant_message

                    update: dict[str, Any] = {"messages": messages}
                    if tool_calls:
                        update["turn_iterations"] = state.get("turn_iterations", 0) + 1
                    else:
                        update["observation_available"] = False
                    return update

                @node_logger("tools")
                async def tool_node(state: State):
                    messages = list(state.get("messages", []))
                    last_message = messages[-1]
                    tool_calls = last_message.get("tool_calls", [])
                    print(f"> 模型回覆解析後的工具呼叫: {tool_calls}")

                    executed_tool_calls = set(state.get("executed_tool_calls", set()))
                    failed_tools = set(state.get("failed_tools", set()))
                    successful_tool_result_text = state.get("successful_tool_result_text", "")
                    last_tool_text = state.get("last_tool_text", "")
                    has_successful_execution = False

                    for call in tool_calls:
                        function = call.get("function") or {}
                        tool_name = function.get("name")
                        tool_args = function.get("arguments") or {}

                        if not tool_name:
                            continue

                        if tool_name not in available_tool_names:
                            tool_text = f"ERROR: Tool '{tool_name}' does not exist. Available tools: {', '.join(sorted(available_tool_names))}"
                            print(f"> 工具不存在: {tool_name}")
                            log_tool_call(tool_name, tool_args, result=tool_text, error="Tool does not exist")
                            append_tool_message(messages, call, tool_text)
                            last_tool_text = tool_text
                            continue

                        if tool_name in failed_tools:
                            tool_text = f"SKIP: Tool '{tool_name}' previously failed. Do not retry."
                            print(f"> 跳過已失敗的工具: {tool_name}")
                            log_tool_call(tool_name, tool_args, result=tool_text, error="Tool already failed")
                            append_tool_message(messages, call, tool_text)
                            last_tool_text = tool_text
                            continue

                        tool_call_key = f"{tool_name}({json.dumps(tool_args, sort_keys=True)})"
                        if tool_call_key in executed_tool_calls:
                            tool_text = f"SKIP: Tool '{tool_name}' with identical arguments already executed. Do not repeat the exact same call."
                            print(f"> 跳過完全相同的工具調用: {tool_name}")
                            log_tool_call(tool_name, tool_args, result=tool_text, error="Identical tool call already executed")
                            append_tool_message(messages, call, tool_text)
                            last_tool_text = tool_text
                            continue

                        executed_tool_calls.add(tool_call_key)
                        print(f"> 正在執行工具: {tool_name}...")

                        try:
                            session = mcp_bundle.session_for_tool(tool_name)
                            if session is None:
                                tool_text = f"ERROR: Tool '{tool_name}' is not registered by any configured MCP server."
                                print(f"> {tool_text}")
                                log_tool_call(tool_name, tool_args, result=tool_text, error="Tool not registered")
                                append_tool_message(messages, call, tool_text)
                                last_tool_text = tool_text
                                continue

                            max_cancel_retries = 3
                            cancel_attempt = 0
                            result = None
                            while True:
                                try:
                                    result = await asyncio.wait_for(
                                        session.call_tool(
                                            tool_name,
                                            arguments=tool_args,
                                        ),
                                        timeout=60,
                                    )
                                    break
                                except Exception as e:
                                    cancel_attempt += 1
                                    tb = traceback.format_exc()
                                    tool_text = f"Tool call cancelled (attempt {cancel_attempt}/{max_cancel_retries}): {type(e).__name__}: {e}"
                                    print(f"> {tool_text}")
                                    log_tool_call(tool_name, tool_args, result=tool_text, error=tb)
                                    if cancel_attempt >= max_cancel_retries:
                                        raise anyio.BrokenResourceError(f"call_tool cancelled repeatedly: {e}")
                                    await asyncio.sleep(0.5)

                            tool_text = tool_result_to_text(result)
                            log_tool_call(tool_name, tool_args, result=result)
                            if tool_text:
                                print(f"> 工具結果: {tool_text}")
                            has_successful_execution = True
                        except asyncio.TimeoutError:
                            tool_text = f"Tool execution timeout (60s): {tool_name}"
                            print(f"> {tool_text}")
                            log_tool_call(tool_name, tool_args, result=tool_text, error="Timeout")
                            failed_tools.add(tool_name)
                        except anyio.BrokenResourceError as e:
                            tool_text = f"Tool execution failed due to broken MCP connection: {e}"
                            log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                            failed_tools.add(tool_name)
                            print("> MCP 連接已斷開，將重新連接...")
                            raise
                        except Exception as e:
                            tool_text = f"Tool execution failed: {type(e).__name__}: {e}"
                            print(f"> 工具執行失敗: {tool_text}")
                            log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                            failed_tools.add(tool_name)

                        append_tool_message(messages, call, tool_text)
                        last_tool_text = tool_text

                    observation_available = False
                    if has_successful_execution:
                        if "全部執行完成" in last_tool_text or "不須再呼叫工具" in last_tool_text:
                            tool_needed = False
                        else:
                            tool_needed = True
                            successful_tool_result_text = last_tool_text

                        print(f"> [Debug] 成功的工具結果: {successful_tool_result_text}")
                        print(f"> [Debug] 需要工具: {tool_needed}")
                        if not tool_needed:
                            observation_available = True
                        else:
                            observation_available = False

                    return {
                        "messages": messages,
                        "executed_tool_calls": executed_tool_calls,
                        "failed_tools": failed_tools,
                        "successful_tool_result_text": successful_tool_result_text,
                        "last_tool_text": last_tool_text,
                        "observation_available": observation_available,
                    }

                def should_continue(state: State) -> Literal["tools", "__end__"]:
                    if state.get("llm_failed"):
                        return "__end__"

                    messages = state.get("messages", [])
                    if not messages:
                        return "__end__"

                    if state.get("turn_iterations", 0) >= config.MAX_TOOL_LOOPS:
                        return "__end__"

                    tool_calls = messages[-1].get("tool_calls", [])
                    if not tool_calls:
                        return "__end__"

                    return "tools"

                workflow = StateGraph(State)
                workflow.add_node("agent", agent_node)
                workflow.add_node("tools", tool_node)

                workflow.add_edge(START, "agent")
                workflow.add_conditional_edges("agent", should_continue)
                workflow.add_edge("tools", "agent")

                app = workflow.compile(checkpointer=MemorySaver())

                print("Agent started. Type 'exit' to quit.\n")
                input_eof_retries = 0
                max_input_eof_retries = 3
                input_eof_retry_delay_seconds = 0.5
                turn_index = 0

                # 保留跨回合的 messages（不在每次輸入時重置）
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": system_prompt},
                ]

                while True:
                    try:
                        user_input = input("You > ")
                    except EOFError:
                        input_eof_retries += 1
                        if input_eof_retries < max_input_eof_retries:
                            print("Loading...")
                            time.sleep(input_eof_retry_delay_seconds)
                            continue
                        print("> Error: Terminal input repeatedly, exiting.")
                        return
                    except KeyboardInterrupt:
                        print("\n> Interrupted by user, exiting.")
                        return
                    except Exception as e:
                        print(f"> Error reading input: {e}")
                        append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"input error: {e}"})
                        return

                    input_eof_retries = 0

                    if is_shell_noise_input(user_input):
                        continue

                    if user_input.strip().lower() == "exit":
                        return

                    turn_index += 1
                    # 在既有 messages 上追加本回合的 user 訊息
                    messages.append({"role": "user", "content": "It's " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " now. " + user_input})

                    initial_state: State = {
                        "messages": list(messages),
                        "executed_tool_calls": set(),
                        "failed_tools": set(),
                        "successful_tool_result_text": "",
                        "last_tool_text": "",
                        "observation_available": False,
                        "llm_failed": False,
                        "turn_iterations": 0,
                        "user_input": user_input,
                    }

                    try:
                        result = await app.ainvoke(
                            initial_state,
                            config={"configurable": {"thread_id": f"pure_react_{turn_index}"}},
                        )
                    except anyio.BrokenResourceError as e:
                        print("MCP connection broken, reconnecting in 2s...", e)
                        try:
                            append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": str(e)})
                        except Exception:
                            pass
                        break
                    except KeyboardInterrupt:
                        print("> Agent stopped by user.")
                        return
                    except (asyncio.CancelledError, EOFError) as e:
                        print(f"> Agent stopped: {type(e).__name__}")
                        try:
                            append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"agent stop: {type(e).__name__}: {str(e)}"})
                        except Exception:
                            pass
                        return
                    except Exception as e:
                        print(f"> Agent crashed: {type(e).__name__}: {e}")
                        try:
                            append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"agent crash: {type(e).__name__}: {e}"})
                        except Exception:
                            pass
                        return

                    if result.get("llm_failed"):
                        # LLM 呼叫失敗，不更新 messages，下一回合可重試或輸入新內容
                        continue

                    # 使用 agent 回傳的 messages 更新外部 messages，確保跨回合歷史被保留
                    try:
                        messages = result.get("messages", list(messages))
                    except Exception:
                        pass

                    final_message = result["messages"][-1]
                    final_text = str(final_message.get("content", "")).strip()
                    tool_text = result.get("successful_tool_result_text", "") or result.get("last_tool_text", "")

                    if final_text.startswith("{") and final_text.endswith("}"):
                        final_text = tool_text or final_text

                    if not final_text:
                        final_text = tool_text

                    print_streaming(final_text)
                    append_memory_summary(
                        config.MEMORY_PATH,
                        build_turn_summary(
                            user_input=user_input,
                            assistant_text=final_text,
                            tool_text=tool_text,
                        ),
                    )

        except anyio.BrokenResourceError as e:
            print("MCP connection broken, reconnecting in 2s...", e)
            try:
                append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": str(e)})
            except Exception:
                pass
            await asyncio.sleep(2)
            continue
        except KeyboardInterrupt:
            print("> Agent stopped by user.")
            return
        except (asyncio.CancelledError, EOFError) as e:
            print(f"> Agent stopped: {type(e).__name__}")
            try:
                append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"agent stop: {type(e).__name__}: {str(e)}"})
            except Exception:
                pass
            return
        except Exception as e:
            print(f"> Agent crashed: {type(e).__name__}: {e}")
            try:
                append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"agent crash: {type(e).__name__}: {e}"})
            except Exception:
                pass
            return


if __name__ == "__main__":
    start_ollama()
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # pyright: ignore[reportAttributeAccessIssue]
    except Exception:
        pass
    asyncio.run(run_agent())
