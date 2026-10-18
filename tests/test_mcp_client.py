"""SPIKE's MCP client against a server built with the official MCP Python SDK, over stdio and Streamable HTTP."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from spike.connectors.mcp import HttpTransport, McpClient, McpError, StdioTransport

pytest.importorskip("mcp.server.mcpserver", reason="the official MCP SDK (dev dependency) builds the test server")
SERVER = str(Path(__file__).parent / "fixtures" / "mcp_test_server.py")


async def exercise(client: McpClient) -> None:
    info = await client.start()
    assert info["serverInfo"]["name"] == "spike-test" and info["protocolVersion"]
    tools = {t["name"]: t for t in await client.list_tools()}
    assert set(tools) == {"add", "shout", "env", "fail"}
    assert tools["add"]["inputSchema"]["properties"].keys() == {"a", "b"}
    assert (await client.call_tool("add", {"a": 2, "b": 3})).text == "5"
    assert (await client.call_tool("shout", {"text": "hola"})).text == "HOLA"
    failed = await client.call_tool("fail", {})
    assert failed.is_error and "fail" in failed.text  # the SDK hides exception details from clients
    await client.close()


async def test_stdio():
    await exercise(McpClient(StdioTransport(sys.executable, [SERVER]), timeout_s=30))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_streamable_http():
    port = free_port()
    proc = subprocess.Popen([sys.executable, SERVER, "http", str(port)], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        transport = HttpTransport(f"http://127.0.0.1:{port}/mcp")
        await exercise(McpClient(transport, timeout_s=30))
        assert transport.session_id  # the SDK server runs stateful sessions by default
    finally:
        proc.terminate()
        proc.wait(timeout=5)


async def test_a_server_that_cannot_start_is_a_clear_error():
    with pytest.raises(McpError, match="cannot start"):
        await McpClient(StdioTransport("spike-no-such-command-xyz", [])).start()


async def test_a_server_that_exits_reports_its_stderr(tmp_path):
    script = tmp_path / "crash.py"
    script.write_text("import sys; print('missing API key', file=sys.stderr); sys.exit(1)")
    client = McpClient(StdioTransport(sys.executable, [str(script)]), timeout_s=30)
    started = time.monotonic()
    with pytest.raises(McpError, match="missing API key"):
        await client.start()
    assert time.monotonic() - started < 10  # the exit is noticed, not waited out
    await client.close()


def test_the_server_process_gets_no_spike_secrets(monkeypatch):
    monkeypatch.setenv("SPIKE_API_TOKEN", "t0ken")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    env = StdioTransport("x", [], env={"GITHUB_TOKEN": "given"}).env
    assert "SPIKE_API_TOKEN" not in env and "OPENAI_API_KEY" not in env and env["GITHUB_TOKEN"] == "given"
