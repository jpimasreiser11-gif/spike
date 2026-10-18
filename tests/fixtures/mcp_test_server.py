"""An MCP server built with the official Python SDK (dev dependency), used to test SPIKE's client against it.

Usage: python mcp_test_server.py [stdio | http PORT]
"""

import os
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("spike-test")


@server.tool()
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@server.tool()
def shout(text: str) -> str:
    """Upper-case a text."""
    return text.upper()


@server.tool()
def env(name: str) -> str:
    """Read an environment variable of the server process."""
    return os.environ.get(name, "")


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("boom")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run("stdio")
