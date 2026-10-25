"""python -m mcp：启动 MCP 服务。"""
from showly_mcp.server import main

if __name__ == "__main__":
    import sys
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8800
    main(port=port)
