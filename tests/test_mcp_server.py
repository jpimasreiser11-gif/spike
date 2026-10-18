"""SPIKE as an MCP server: JSON-RPC handling, Streamable HTTP on `/mcp` and stdio (`spike mcp`), checked with SPIKE's
own MCP client and with the official MCP Python SDK."""

import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from spike.connectors.mcp import HttpTransport, McpClient, McpError
from spike.runtime.llamacpp_server import find_binary
from spike.server.app import create_app
from spike.server.mcp_server import CALLER_NOTE, SpikeMcp
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    monkeypatch.delenv("SPIKE_API_TOKEN", raising=False)
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    return AppState(home=tmp_path, provider_factory=factory), local


@pytest.fixture
def served(env):
    """The app on a real port, as `spike serve` runs it."""
    state, local = env
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp", state, local
    server.should_exit = True
    thread.join(timeout=5)


async def test_tools_are_ask_spike_and_one_per_specialist(env):
    state, _ = env
    tools = {t["name"]: t for t in SpikeMcp(state).tools()}
    specialists = [s for s in state.catalog.specialists if s != "core"]
    assert set(tools) == {"ask_spike", *[f"spike_{s}" for s in specialists]}
    ask = tools["ask_spike"]
    assert ask["inputSchema"]["required"] == ["question"]
    assert ask["inputSchema"]["properties"]["specialist"]["enum"] == ["auto", *specialists]
    assert all(t["annotations"]["readOnlyHint"] and t["outputSchema"]["required"] == ["answer", "specialists"]
               for t in tools.values())


async def test_spike_answers_through_its_own_mcp_client_over_http(served):
    url, _, local = served
    local._script = [text("Hola ", "desde SPIKE"), text("El EBITDA es el resultado operativo.")]
    client = McpClient(HttpTransport(url))
    try:
        info = await client.start()
        assert info["serverInfo"]["name"] == "spike" and info["capabilities"]["tools"]
        assert "spike_medicine" in {t["name"] for t in await client.list_tools()}

        result = await client.call_tool("ask_spike", {"question": "Hola"})
        assert result == type(result)(text="Hola desde SPIKE", is_error=False)
        system = local.requests[-1].messages[0].content
        assert "Spike Core" in system and CALLER_NOTE in system

        result = await client.call_tool("spike_finance", {"question": "¿Qué es el EBITDA?", "context": "Ventas 10"})
        assert result.text == "El EBITDA es el resultado operativo." and not result.is_error
        request = local.requests[-1]
        assert "Spike Finance" in request.messages[0].content
        assert request.messages[-1].content == "¿Qué es el EBITDA?\n\n# Material\nVentas 10"

        with pytest.raises(McpError, match="unknown tool"):
            await client.call_tool("spike_core", {"question": "x"})
        assert (await client.call_tool("ask_spike", {"question": " "})).is_error
        bad = await client.call_tool("ask_spike", {"question": "x", "specialist": "astrology"})
        assert bad.is_error and "unknown specialist" in bad.text
    finally:
        await client.close()


async def test_the_official_sdk_talks_to_the_http_endpoint(served):
    url, _, local = served
    local._script = [text("Respuesta de Medicine.")]
    async with streamable_http_client(url) as (read, write), ClientSession(read, write) as session:
        init = await session.initialize()
        assert init.server_info.name == "spike"
        names = {t.name for t in (await session.list_tools()).tools}
        assert {"ask_spike", "spike_medicine"} <= names and "spike_core" not in names
        result = await session.call_tool("spike_medicine", {"question": "¿Qué es la HbA1c?"})
        assert not result.is_error and result.content[0].text == "Respuesta de Medicine."
        assert result.structured_content == {"answer": "Respuesta de Medicine.", "specialists": ["medicine"]}


async def test_tools_that_need_approval_are_refused(served):
    url, state, local = served
    ws = Path(os.environ["SPIKE_WORKSPACE"])
    local._script = [call("write_file", {"path": "notas.md", "content": "x"}), text("No he podido escribirlo.")]
    client = McpClient(HttpTransport(url))
    try:
        await client.start()
        result = await client.call_tool("ask_spike", {"question": "Escribe notas.md", "specialist": "core"})
    finally:
        await client.close()
    assert result.text == "No he podido escribirlo." and not (ws / "notas.md").exists()
    tool_message = local.requests[-1].messages[-1]
    assert tool_message.role == "tool" and "needs the user's approval" in tool_message.content
    assert state.store.list_conversations() == []  # nothing is kept: MCP calls are not chats


def test_http_endpoint_rules(served):
    client = httpx.Client(base_url=served[0].removesuffix("/mcp"))
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert client.post("/mcp", json=ping).json() == {"jsonrpc": "2.0", "id": 1, "result": {}}
    assert client.post("/mcp", json=ping, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert client.get("/mcp").status_code == 405
    bad = client.post("/mcp", content=b"{nope", headers={"Content-Type": "application/json"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
    assert client.post("/mcp", json=[ping]).json()["error"]["code"] == -32600
    missing = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "resources/list"}).json()
    assert missing["id"] == 2 and missing["error"]["code"] == -32601
    init = client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "initialize",
                                     "params": {"protocolVersion": "2025-06-18", "capabilities": {}}}).json()
    assert init["result"]["protocolVersion"] == "2025-06-18"
    newer = client.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "initialize",
                                      "params": {"protocolVersion": "2099-01-01", "capabilities": {}}}).json()
    assert newer["result"]["protocolVersion"] == "2025-11-25"


def test_http_endpoint_needs_the_token_when_one_is_set(env, monkeypatch):
    state, _ = env
    monkeypatch.setenv("SPIKE_API_TOKEN", "s3cret")
    client = TestClient(create_app(state))  # with a token, programs on other computers may call it too
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert client.post("/mcp", json=ping).status_code == 401
    assert client.post("/mcp", json=ping, headers={"Authorization": "Bearer s3cret"}).json()["result"] == {}


def stdio_params(home: Path, *extra: str) -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "spike.cli", "mcp", *extra],
                                 env={**os.environ, "SPIKE_HOME": str(home), "SPIKE_NO_KEYRING": "1"},
                                 cwd=str(Path(__file__).parent.parent))


def configure_local(home: Path, **runtime) -> None:
    state = AppState(home=home)
    state.update_settings({"local_runtime": {**state.settings()["local_runtime"], **runtime}})
    local = state.provider_config("spike-local")
    local["base_url"] = f"http://127.0.0.1:{runtime['port']}/v1"
    state.store.save_provider(local)


async def test_stdio_server_with_the_official_sdk_explains_a_missing_engine(tmp_path):
    configure_local(tmp_path, port=free_port())  # nothing listens there
    async with stdio_client(stdio_params(tmp_path)) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        assert "ask_spike" in names and "spike_finance" in names
        result = await session.call_tool("spike_medicine", {"question": "hola"})
        assert result.is_error and "spike serve" in result.content[0].text and "--start-local" in result.content[0].text
        await session.send_ping()


@pytest.mark.skipif(find_binary() is None, reason="llama-server not installed")
async def test_stdio_server_starts_the_local_engine_and_answers(tmp_path):
    out = tmp_path / "model"
    subprocess.run([sys.executable, "tests/fixtures/make_tiny_gguf.py", str(out)], check=True, capture_output=True)
    home = tmp_path / "home"
    configure_local(home, model=str(out / "spike-tiny.gguf"), context=2048, kv_cache_type="f16", port=free_port())
    AppState(home=home).update_settings({"max_tokens": 24})  # the tiny model's words mean nothing: keep them few
    async with stdio_client(stdio_params(home, "--start-local")) as (read, write), \
            ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("ask_spike", {"question": "hola", "specialist": "core"},
                                         read_timeout_seconds=300)
        assert not result.is_error, result.content[0].text
        assert result.structured_content["specialists"] == ["core"]
