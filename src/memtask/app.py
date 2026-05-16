from __future__ import annotations

import argparse
from typing import Any

from .api import SERVER_INSTRUCTIONS, register


def _load_mcp() -> Any:
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: 'mcp'. Install it in the active Python environment "
            "(for example: pip install mcp) before running this server."
        ) from exc


def create_mcp(server_name: str = "Mini Demo Server") -> Any:
    FastMCP = _load_mcp()
    mcp = FastMCP(name=server_name, instructions=SERVER_INSTRUCTIONS)
    return register(mcp)


def run_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    server_name: str = "Mini Demo Server",
) -> None:
    mcp = create_mcp(server_name=server_name)

    if transport == "stdio":
        mcp.run()
        return

    if transport != "streamable-http":
        raise ValueError(f"Unsupported transport: {transport}")

    mcp.settings.host = host
    mcp.settings.port = port
    mcp.settings.json_response = True
    mcp.run(transport="streamable-http")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--server-name",
        default="Mini Demo Server",
        help="Override the MCP server name",
    )
    args = parser.parse_args()

    run_server(
        transport=args.transport,
        host=args.host,
        port=args.port,
        server_name=args.server_name,
    )


if __name__ == "__main__":
    main()
