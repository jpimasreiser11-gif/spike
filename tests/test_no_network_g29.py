"""G29 — No-network guarantee test.

Verifies that SPIKE never initiates outbound connections to non-loopback addresses
(`127.0.0.1`, `::1`, `localhost`) across all main API flows unless explicitly requested
by the user (e.g., model download, remote provider test/call, `web_fetch` tool).
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from spike.tools.builtin import WebFetch
from tests.helpers import ScriptedProvider, text

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


class ExternalNetworkBlockedError(RuntimeError):
    """Raised whenever code under test attempts a non-loopback network connection."""


def _extract_host(address: Any) -> str | None:
    if isinstance(address, tuple) and len(address) >= 1 and isinstance(address[0], str):
        return address[0]
    return None


def _is_loopback_address(address: Any) -> bool:
    # Allow UNIX domain sockets (str / bytes / Path)
    if isinstance(address, (str, bytes, Path)):
        return True
    host = _extract_host(address)
    if host is None:
        return True
    normalized = host.strip().lower().strip("[]")
    return normalized in LOOPBACK_HOSTS or normalized.startswith("127.")


@pytest.fixture
def block_external_network(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """Block any socket connection or DNS resolution not targeting 127.0.0.1 / ::1 / localhost."""
    # A proxy on loopback (common in sandboxes) would turn an external request into an allowed local one.
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_create_connection = socket.create_connection
    orig_getaddrinfo = socket.getaddrinfo
    attempts: list[tuple[str, Any]] = []

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not _is_loopback_address(address):
            attempts.append(("socket.connect", address))
            raise ExternalNetworkBlockedError(f"Blocked external socket.connect to {address!r}")
        return orig_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        if not _is_loopback_address(address):
            attempts.append(("socket.connect_ex", address))
            raise ExternalNetworkBlockedError(f"Blocked external socket.connect_ex to {address!r}")
        return orig_connect_ex(self, address)

    def guarded_create_connection(address: Any, *args: Any, **kwargs: Any) -> socket.socket:
        if not _is_loopback_address(address):
            attempts.append(("socket.create_connection", address))
            raise ExternalNetworkBlockedError(f"Blocked external socket.create_connection to {address!r}")
        return orig_create_connection(address, *args, **kwargs)

    def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        host_str = host.decode("utf-8", errors="replace") if isinstance(host, bytes) else str(host or "")
        normalized = host_str.strip().lower().strip("[]")
        if normalized and normalized not in LOOPBACK_HOSTS and not normalized.startswith("127."):
            attempts.append(("socket.getaddrinfo", (host, port)))
            raise ExternalNetworkBlockedError(f"Blocked external DNS resolution for {host!r}:{port!r}")
        return orig_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    return attempts


def _events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_socket_guard_blocks_external_connections_and_allows_loopback(
    block_external_network: list[tuple[str, Any]]
) -> None:
    """Verify the socket guard itself blocks external IPs/domains and permits 127.0.0.1."""
    with pytest.raises(ExternalNetworkBlockedError):
        socket.create_connection(("93.184.216.34", 80), timeout=0.1)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(ExternalNetworkBlockedError):
            s.connect(("8.8.8.8", 53))
        with pytest.raises(ExternalNetworkBlockedError):
            s.connect_ex(("1.1.1.1", 443))

    with pytest.raises(ExternalNetworkBlockedError):
        httpx.get("https://example.com", timeout=0.5)

    assert len(block_external_network) == 4

    # Loopback bind + connect must remain allowed
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as cli:
            conn, _ = srv.accept()
            conn.close()
            cli.close()


def test_main_api_flows_make_zero_external_network_connections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    block_external_network: list[tuple[str, Any]],
) -> None:
    """Start the app with the scripted provider and exercise all main API flows with external sockets blocked."""
    home = tmp_path / "spike-home"
    ws = tmp_path / "workspace"
    home.mkdir()
    ws.mkdir()
    monkeypatch.setenv("SPIKE_HOME", str(home))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(ws))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")

    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=home, provider_factory=factory)
    app = create_app(state)
    # Enable launcher setup status endpoint to verify first-run wizard status makes zero external requests
    app.state.launcher_enabled = True
    client = TestClient(app, client=("127.0.0.1", 50000))

    # 1. Health, system, and first-run setup wizard status (without downloading)
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/api/system").status_code == 200
    setup_status = client.get("/api/setup").json()
    assert setup_status["enabled"] is True
    assert setup_status["complete"] is False
    assert setup_status["job"]["status"] == "idle"
    assert isinstance(setup_status["specialists"], list)

    # 2. Providers, specialists, and skills
    providers = client.get("/api/providers").json()
    assert any(p["id"] == "spike-local" for p in providers)
    specialists = client.get("/api/specialists").json()
    assert {s["id"] for s in specialists} >= {"core", "code", "finance", "medicine"}
    assert any(s["id"] == "medicine" and "adapter_accepted" in s and "active_mode" in s for s in specialists)
    skills = client.get("/api/skills").json()
    assert len(skills) > 0
    first_skill = skills[0]["name"]
    assert client.get(f"/api/skills/{first_skill}").status_code == 200
    assert client.put(f"/api/skills/{first_skill}", json={"enabled": True}).status_code == 200

    # 3. Settings, runtime status, calls/usage, evolution, design systems
    settings = client.get("/api/settings").json()
    assert "tool_policies" in settings
    assert client.put("/api/settings", json={"sandbox": "auto"}).status_code == 200
    assert client.get("/api/runtime").status_code == 200
    assert client.get("/api/calls").status_code == 200
    assert client.get("/api/usage").status_code == 200
    assert client.get("/api/evolution").status_code == 200
    assert client.get("/api/design-systems").status_code == 200
    assert client.get("/api/design-systems/spike").status_code == 200

    # 4. Unconfigured / disabled connectors & browser domain rules
    initial_connectors = client.get("/api/connectors").json()
    assert isinstance(initial_connectors, list)
    assert all(not c.get("enabled") for c in initial_connectors)
    conn_res = client.post(
        "/api/connectors",
        json={
            "id": "remote-example",
            "name": "Remote Example",
            "transport": "http",
            "url": "https://example.com/mcp",
        },
    )
    assert conn_res.status_code == 200
    assert any(c["id"] == "remote-example" and not c.get("enabled") for c in client.get("/api/connectors").json())
    assert "domains" in client.get("/api/browser").json()
    assert client.get("/api/browser/recorder").status_code == 200

    # 5. Projects & workspace files
    proj = client.post("/api/projects", json={"name": "Offline Project", "specialist": "code"}).json()
    pid = proj["id"]
    assert client.get("/api/projects").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 200
    assert (
        client.put(
            f"/api/projects/{pid}/files/notes.md",
            content=b"# Offline Notes\nEverything stays local.\n",
        ).status_code
        == 200
    )
    assert client.get(f"/api/projects/{pid}/files/notes.md").status_code == 200
    assert client.get(f"/api/projects/{pid}/export").status_code == 200
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "report.txt").write_text("hola", encoding="utf-8")
    assert client.get("/api/workspace/files/report.txt").content == b"hola"

    # 6. Memory, folders, glossary, tutor, and memory graph
    mem_item = client.post(
        "/api/memory",
        json={"text": "El servidor local nunca sale a internet sin permiso.", "kind": "fact", "scope": "global"},
    ).json()
    assert mem_item["id"]
    assert client.get("/api/memory?q=internet").status_code == 200
    assert client.get("/api/memory-status").status_code == 200
    assert client.get("/api/memory-export").status_code == 200
    assert client.get("/api/memory-folders").status_code == 200
    g_item = client.post(
        "/api/glossary",
        json={"term": "presupuesto", "translation": "budget", "lang": "en", "scope": "global"},
    )
    assert g_item.status_code == 200
    assert client.get("/api/glossary").status_code == 200
    assert client.get("/api/tutor").status_code == 200
    assert client.get("/api/memory-graph").status_code == 200

    # 7. Chat (SSE streaming with scripted provider), conversations, proof, and history search
    scripts["spike-local"]._script = [text("Respuesta 100% local sin red externa.")]
    chat_res = client.post("/api/chat", json={"message": "Comprueba el presupuesto offline", "project_id": pid})
    assert chat_res.status_code == 200
    evs = _events_of(chat_res)
    assert any(e.get("type") == "done" for e in evs)
    convs = client.get(f"/api/conversations?project_id={pid}").json()
    assert len(convs) == 1
    cid = convs[0]["id"]
    assert client.get(f"/api/conversations/{cid}").status_code == 200
    assert client.get(f"/api/conversations/{cid}/proof").status_code == 200
    search_res = client.post("/api/history/search", json={"query": "presupuesto", "scope": "all"})
    assert search_res.status_code == 200
    assert len(search_res.json()["results"]) >= 1

    # 8. OpenAI-compatible local endpoint (/v1/models and /v1/chat/completions)
    assert client.get("/v1/models").status_code == 200
    scripts["spike-local"]._script = [text("OK desde /v1")]
    v1_res = client.post(
        "/v1/chat/completions",
        json={"model": "spike-core", "messages": [{"role": "user", "content": "Hola"}]},
    )
    assert v1_res.status_code == 200

    # 9. Workflows, Creator templates, and Finance simulated paper account
    assert client.get("/api/workflows").status_code == 200
    assert client.get("/api/creator/templates").status_code == 200
    assert client.get("/api/finance").status_code == 200
    assert client.get("/api/finance/paper").status_code == 200
    paper_reset = client.post("/api/finance/paper/reset", json={"cash": 10000.0, "quote": "USDT"})
    assert paper_reset.status_code == 200

    # Zero external socket or DNS attempts across all flows
    assert block_external_network == [], f"Unexpected external network attempts: {block_external_network}"


@pytest.mark.asyncio
async def test_opt_in_external_features_are_caught_by_socket_guard_when_invoked(
    block_external_network: list[tuple[str, Any]]
) -> None:
    """Confirm that `web_fetch` attempts external DNS/socket access only when explicitly executed,
    and is blocked by the no-network guard."""
    tool = WebFetch()
    with pytest.raises(ExternalNetworkBlockedError):
        await tool.run({"url": "https://example.com"})
    assert len(block_external_network) >= 1
