import asyncio
import inspect
from src.client import connect_all_mcp_servers

async def main():
    async with connect_all_mcp_servers() as mcp_bundle:
        print('available_tool_names:', getattr(mcp_bundle, 'available_tool_names', None))
        print('tool_to_server keys:', list(getattr(mcp_bundle, 'tool_to_server', {}).keys())[:200])
        print('server_sessions keys:', list(getattr(mcp_bundle, 'server_sessions', {}).keys()))
        for server, sess in mcp_bundle.server_sessions.items():
            print('\n--- Server:', server)
            try:
                print('session type:', type(sess))
                print('dir(session):')
                for name in sorted(dir(sess)):
                    print(' ', name)
                # print call_tool signature if present
                fn = getattr(sess, 'call_tool', None)
                if fn:
                    try:
                        print('call_tool signature:', inspect.signature(fn))
                    except Exception as e:
                        print('call_tool signature error:', e)
                # try list_tools
                try:
                    tools = await sess.list_tools()
                    print('list_tools -> tools count:', len(getattr(tools, 'tools', [])))
                    for t in getattr(tools, 'tools', [])[:20]:
                        print('  -', getattr(t, 'name', t))
                except Exception as e:
                    print('list_tools() failed:', e)
            except Exception as e:
                print('error inspecting session:', e)

if __name__ == '__main__':
    asyncio.run(main())
