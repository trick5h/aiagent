import asyncio
import subprocess
import time
import traceback
import warnings
import anyio
import inspect
import json


import config
from src.logger import *
from src.memory import *
from src.message import *
from src.prompt import *
from src.stream import *
from src.client import connect_all_mcp_servers

warnings.filterwarnings("ignore", category=DeprecationWarning)


def start_ollama():
import ollama
    try:
        # 在背景啟動 Ollama 服務（避免阻塞 Python 程式）
        print("正在啟動 Ollama 服務...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # 等待 3 秒讓服務完全初始化
        time.sleep(3)
        #subprocess.run(["ollama", "run", model])
               
    except FileNotFoundError:
        print("錯誤：找不到 ollama 指令。請確認已安裝 Ollama 並已加入系統環境變數 (PATH)。")


# ===========================================================================
###############################################################################
#                                                                             #
#                          START OF MAIN EXECUTION                            #
#                                                                             #
###############################################################################
# =========================
# Main Agent
# =========================


async def run_mcp_agent(): 
    # A. 建立連線 (auto-reconnect on broken resource)
    while True:
        try:
            async with connect_all_mcp_servers() as mcp_bundle:
                all_ollama_tools = mcp_bundle.all_ollama_tools
                available_tool_names = mcp_bundle.available_tool_names

                if len(all_ollama_tools) > 0:
                    print(">>>>>>> MCP Servers:", len(all_ollama_tools), "Tools successfully initialized. \n")

                # 2. 獲取memory與System Prompt
                system_prompt = build_system_prompt()

                messages = [{"role": "system", "content": system_prompt}]

                # 3. 開始迴圈 
                print("Agent started. Type 'exit' to quit.\n")
                input_eof_retries = 0
                max_input_eof_retries = 3
                input_eof_retry_delay_seconds = 0.5

                while True:
                    try:
                        user_input = input("You > ")
                    except EOFError:
                        input_eof_retries += 1
                        if input_eof_retries < max_input_eof_retries:
                            print(f"Loading...")
                            time.sleep(input_eof_retry_delay_seconds)
                            continue
                        print("> Error: Terminal input repeatedly, exiting.")
                        break
                    except KeyboardInterrupt:
                        print("\n> Interrupted by user, exiting.")
                        break
                    except Exception as e:
                        print(f"> Error reading input: {e}")
                        append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"input error: {e}"})
                        break

                    input_eof_retries = 0

                    if is_shell_noise_input(user_input):
                        continue

                    if user_input.strip().lower() == "exit":
                        return

                    user_message = {"role": "user", "content": "It's " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " now. " + user_input}
                    messages.append(user_message)
                    # Quick heuristic: decide whether this user input needs tools
                    #needs_tools = await is_user_query_needs_tools(user_input, tool_result='') # Warning: It's not accurate enough
                    needs_tools = True

                    # 開始 ReAct 迴圈 
                    # 初始化本輪的執行歷史
                    executed_tool_calls: set[str] = set()  # 記錄「工具名+參數」組合，防止完全重複的調用
                    failed_tools: set[str] = set()
                    llm_failed = False
                    successful_tool_result_text = ""
                    all_tool_results: list[str] = []  # 收集所有成功的工具執行結果
                    observation_available = False  # 當有工具結果可用時，下一輪引導模型直接回答

                    for _ in range(config.MAX_TOOL_LOOPS):

                        # A. 執行階段：強制調用工具
                        # 構建傳給 LLM 的訊息，包含動態警告
                        messages_for_llm = dedupe_consecutive_messages(messages)
                        warning = build_dynamic_warning(executed_tool_calls, failed_tools, available_tool_names)
                        if warning:
                            messages_for_llm.append({"role": "system", "content": warning})

                        # Call ollama.chat (support sync or async implementations) and log request/response
                        print(f"> 思考中...")
                        request_payload = {
                            "model": config.MODEL,
                            "messages": messages_for_llm,
                            "tools": "ollama_tools_summary"
                        }
                        start = time.perf_counter()
                        try:
                            # 如果已有可觀察到的工具結果，禁用工具強制模型直接回答
                            if observation_available:
                                messages_for_llm.append({"role": "system", "content": build_final_answer_prompt(successful_tool_result_text)})
                                # 禁用工具，強制基於現有觀察直接回答
                                final_report = ollama.chat(
                                    model=config.MODEL,
                                    messages=messages_for_llm,
                                )
                                break
                            else:
                                # 沒有觀察結果，保持工具啟用以允許鏈式調用
                                raw_response = ollama.chat(
                                    model=config.MODEL,
                                    messages=messages_for_llm,
                                    tools=all_ollama_tools,
                                    options={"temperature": 0.1},
                                    format='json',
                                )
                            if inspect.isawaitable(raw_response):
                                raw_response = await raw_response
                            end = time.perf_counter()
                            # log the call (raw_response may be a ChatResponse object)
                            log_llm_call(request_payload, response=raw_response, start=start, end=end)
                            # Normalize response to a dict-like shape for downstream code
                            response = normalize_chat_response(raw_response)
                            # observation_available 會在後續解析回應內容後（若無 tool_calls）被清除。
                        except Exception as e:
                            end = time.perf_counter()
                            log_llm_call(request_payload, response=None, error=e, start=start, end=end)
                            # Handle common Ollama errors gracefully (e.g., model not found)
                            msg = str(e).lower()
                            if "model" in msg and "not found" in msg:
                                print(f"LLM error: {e}. Please check MODEL setting: {config.MODEL}")
                                llm_failed = True
                                break
                            raise

                        # B. 解析模型輸出並透過 MCP 執行
                        assistant_message = append_assistant_message(messages, response)
                        model_thought = assistant_message.get('content', '')
                        if model_thought:
                            print(f"> 模型思考: {model_thought}")
                        tool_calls = response.get('message', {}).get('tool_calls', []) 
                        if not tool_calls:
                            content = assistant_message.get("content")
                            parsed_tool_call = extract_tool_call_from_content(content)
                            if parsed_tool_call is not None:
                                tool_calls = [parsed_tool_call]
                                assistant_message["tool_calls"] = tool_calls
                                messages[-1] = assistant_message

                        if tool_calls: 
                            last_tool_text = ""
                            last_tool_name = ""  # Track last executed tool
                            has_successful_execution = False
                            for call in tool_calls: 
                                tool_name = call['function']['name'] 
                                tool_args = call['function']['arguments'] 

                                # 檢查工具是否存在
                                if tool_name not in available_tool_names:
                                    tool_text = f"ERROR: Tool '{tool_name}' does not exist. Available tools: {', '.join(sorted(available_tool_names))}"
                                    print(f"> 工具不存在: {tool_name}")
                                    log_tool_call(tool_name, tool_args, result=tool_text, error="Tool does not exist")
                                    append_tool_message(messages, call, tool_text)
                                    # 不記錄無效工具
                                    last_tool_text = tool_text
                                    continue

                                # 檢查工具是否已失敗
                                if tool_name in failed_tools:
                                    tool_text = f"SKIP: Tool '{tool_name}' previously failed. Do not retry."
                                    print(f"> 跳過已失敗的工具: {tool_name}")
                                    log_tool_call(tool_name, tool_args, result=tool_text, error="Tool already failed")
                                    append_tool_message(messages, call, tool_text)
                                    # 不記錄已失敗的工具
                                    last_tool_text = tool_text
                                    continue


                                # 檢查是否已用相同參數執行過此工具 (防止完全相同的調用)
                                tool_call_key = f"{tool_name}({json.dumps(tool_args, sort_keys=True)})"
                                if tool_call_key in executed_tool_calls:
                                    tool_text = f"SKIP: Tool '{tool_name}' with identical arguments already executed. Do not repeat the exact same call."
                                    print(f"> 跳過完全相同的工具調用: {tool_name}")
                                    log_tool_call(tool_name, tool_args, result=tool_text, error="Identical tool call already executed")
                                    append_tool_message(messages, call, tool_text)
                                    last_tool_text = tool_text
                                    continue

                                # 記錄執行此工具呼叫組合
                                executed_tool_calls.add(tool_call_key)

                                print(f"> 正在執行工具: {tool_name}...") 

                                # 透過 MCP Session 執行 (with timeout protection)
                                try:
                                    session = mcp_bundle.session_for_tool(tool_name)
                                    if session is None:
                                        tool_text = f"ERROR: Tool '{tool_name}' is not registered by any configured MCP server."
                                        print(f"> {tool_text}")
                                        log_tool_call(tool_name, tool_args, result=tool_text, error="Tool not registered")
                                        append_tool_message(messages, call, tool_text)
                                        last_tool_text = tool_text
                                        continue

                                    # 若遇到 asyncio.CancelledError，代表底層會話或子程序可能在啟動階段被取消
                                    # 我們嘗試重試幾次，以降低因 race condition 導致的單次失敗
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
                                                timeout=60  # 60 second timeout per tool
                                            )
                                            break
                                        except Exception as e:
                                            cancel_attempt += 1
                                            tb = traceback.format_exc()
                                            tool_text = f"Tool call cancelled (attempt {cancel_attempt}/{max_cancel_retries}): {type(e).__name__}: {e}"
                                            print(f"> {tool_text}")
                                            log_tool_call(tool_name, tool_args, result=tool_text, error=tb)
                                            if cancel_attempt >= max_cancel_retries:
                                                # 轉為 BrokenResourceError，觸發外層重連機制
                                                raise anyio.BrokenResourceError(f"call_tool cancelled repeatedly: {e}")
                                            await asyncio.sleep(0.5)

                                    tool_text = tool_result_to_text(result)
                                    log_tool_call(tool_name, tool_args, result=result)
                                    if tool_text:
                                        print(f"> 工具結果: {tool_text}")
                                    has_successful_execution = True
                                    last_tool_name = tool_name  # Record which tool succeeded
                                except asyncio.TimeoutError:
                                    tool_text = f"Tool execution timeout (60s): {tool_name}"
                                    print(f"> {tool_text}")
                                    log_tool_call(tool_name, tool_args, result=tool_text, error="Timeout")
                                    failed_tools.add(tool_name)
                                except anyio.BrokenResourceError as e:
                                    tool_text = f"Tool execution failed due to broken MCP connection: {e}"
                                    log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                                    failed_tools.add(tool_name)
                                    print(f"> MCP 連接已斷開，將重新連接...")
                                    raise  # Re-raise to trigger outer reconnection logic
                                except Exception as e:
                                    tool_text = f"Tool execution failed: {type(e).__name__}: {e}"
                                    print(f"> 工具執行失敗: {tool_text}")
                                    log_tool_call(tool_name, tool_args, result=tool_text, error=e)
                                    failed_tools.add(tool_name)
                                append_tool_message(messages, call, tool_text)
                                last_tool_text = tool_text

                            # 只有在執行擁有足夠資訊的工具時，才標記 observation 可用
                            if has_successful_execution:
                                if "All tasks completed;" in last_tool_text or "no further tools required." in last_tool_text:
                                    tool_needed = False
                                else:
                                    tool_needed = True                                  
                                    successful_tool_result_text = last_tool_text

                                all_tool_results.append(last_tool_text)  # 將成功的工具結果加入列表
                                print(f"> [Debug] 成功的工具結果: {successful_tool_result_text}")
                                # 判斷此工具數據是否需要下一輪工具調用
                                #tool_needed = await is_user_query_needs_tools(user_input, successful_tool_result_text) # Warning: It's not accurate enough
                                
                                
                                print(f"> [Debug] 需要工具: {tool_needed}")
                                if not tool_needed:
                                    observation_available = True
                                else:
                                    observation_available = False

                        else: 
                            direct_text = str(assistant_message.get('content', ''))
                            print_streaming(direct_text)
                            append_memory_summary(
                                MEMORY_PATH,
                                build_turn_summary(
                                    user_input=user_input,
                                    assistant_text=direct_text,
                                ),
                            )
                            # 已收到最終自然語言回答，清除 observation 標記
                            observation_available = False
                            break
                    else:
                        print("> Agent 已達工具呼叫上限，為避免無限迴圈而停止。")
                        # 達到迴圈限制，強制進行最終答案生成（如果有成功的工具結果）
                        messages_for_llm.append({"role": "system", "content": build_final_answer_prompt(successful_tool_result_text)})
                        # 禁用工具，強制基於現有觀察直接回答
                        final_report = ollama.chat(
                            model=config.MODEL,
                            messages=messages_for_llm,
                        )

                    if llm_failed:
                        # 回到使用者輸入循環，讓使用者修正模型設定或重試
                        continue

                    
                    # 為最終答案生成構建乾淨的訊息歷史（移除工具相關內容，只保留用戶和所有工具的觀察結果）
                    combined_tool_results = "\n".join([f"[工具執行結果 {i+1}]\n{result}" for i, result in enumerate(all_tool_results)])
                    final_request = {
                        "model": config.MODEL,
                        "messages": messages_for_llm,
                    }
                    start_final = time.perf_counter()
                    try:
                        if inspect.isawaitable(final_report):
                            final_report = await final_report
                        end_final = time.perf_counter()
                        log_llm_call(final_request, response=final_report, start=start_final, end=end_final)
                        final_report = normalize_chat_response(final_report)
                        final_text = str(final_report.get('message', {}).get('content', '')).strip()

                        # 如果模型仍然輸出JSON，使用工具結果代替
                        if final_text.startswith('{') and final_text.endswith('}'):
                            final_text = successful_tool_result_text

                        print_streaming(final_text)
                        append_memory_summary(
                            MEMORY_PATH,
                            build_turn_summary(
                                user_input=user_input,
                                assistant_text=final_text,
                                tool_text=successful_tool_result_text,
                            ),
                        )
                    except Exception as e:
                        end_final = time.perf_counter()
                        log_llm_call(final_request, response=None, error=e, start=start_final, end=end_final)
                        print(f"> 最終回答生成失敗: {type(e).__name__}: {e}")
                        print_streaming(successful_tool_result_text)
                        append_memory_summary(
                            MEMORY_PATH,
                            build_turn_summary(
                                user_input=user_input,
                                assistant_text=successful_tool_result_text,
                                tool_text=successful_tool_result_text,
                            ),
                        )
                    continue
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
        except ExceptionGroup as eg:
            # 捕捉 TaskGroup 中未處理的多重例外，逐一記錄細節但讓 agent 繼續重啟循環
            try:
                print(f"> Agent encountered ExceptionGroup")
                # 額外輸出 ExceptionGroup 的 repr 與完整 traceback 以利偵錯
                try:
                    print(repr(eg))
                    traceback.print_exception(type(eg), eg, getattr(eg, '__traceback__', None))
                except Exception:
                    pass
                for i, ex in enumerate(eg.exceptions):
                    print(f"錯誤類型: {type(ex).__name__}")
                    print(f"錯誤訊息: {ex}")
                raise eg
            except Exception as e:
                print(f"> Agent encountered ExceptionGroup {type(e).__name__}: {e}; logging and continuing...")
            try:
                details = []
                for idx, sub in enumerate(eg.exceptions, start=1):
                    tb = "".join(traceback.format_exception(type(sub), sub, getattr(sub, '__traceback__', None)))
                    details.append({
                        "index": idx,
                        "type": type(sub).__name__,
                        "error": str(sub),
                        "traceback": tb,
                    })
                append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "exception_group", "count": len(eg.exceptions), "sub_exceptions": details})
            except Exception as e2:
                try:
                    append_log({"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "type": "error", "error": f"failed logging ExceptionGroup: {e2}"})
                except Exception:
                    pass
            # 等待並繼續外層重連循環
            await asyncio.sleep(2)
            continue
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
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore # For Windows compatibility
    except Exception as e:
        print(f"> Failed to set event loop policy: {e}")
    asyncio.run(run_mcp_agent())