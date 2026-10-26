"""Proof package: a chat with its steps, model calls and file checksums, verifiable with SHA256SUMS."""

import hashlib
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")
    client.put("/api/settings", json={"tool_policies": {"write_file": "allow"}})
    return client, state, scripts["spike-local"], tmp_path / "ws"


def chat(client, local, message, script, cid=None):
    local._script = script
    body = {"message": message, "mode": "core", **({"conversation_id": cid} if cid else {})}
    lines = client.post("/api/chat", json=body).text.splitlines()
    return next(json.loads(x[6:]) for x in lines if x.startswith("data: ") and '"conversation"' in x)["id"]


def test_the_package_is_complete_consistent_and_keeps_secrets_out(env):
    client, state, local, ws = env
    r = client.post("/api/providers", json={"preset": "deepseek", "api_key": "sk-proof-secret-0042"})
    assert r.status_code == 200, r.text
    cid = chat(client, local, "Escribe las notas", [call("write_file", {"path": "notas.md", "content": "hola"}),
                                                   text("Hecho.")])
    other = chat(client, local, "Otra cosa", [text("Vale.")])
    assert other != cid

    r = client.get(f"/api/conversations/{cid}/proof")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="spike-proof-escribe-las-notas-' in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert names == {"README.txt", "manifest.json", "chat.json", "calls.json", "file-changes.json", "chat.md",
                     "SHA256SUMS", "environment.json"}
    for line in zf.read("SHA256SUMS").decode().splitlines():  # what `sha256sum -c SHA256SUMS` checks
        digest, name = line.split("  ")
        assert hashlib.sha256(zf.read(name)).hexdigest() == digest
    assert b"sk-proof-secret-0042" not in r.content

    calls = json.loads(zf.read("calls.json"))
    assert len(calls) == 2 and {c["conversation_id"] for c in calls} == {cid}  # not the other chat's call
    [change] = json.loads(zf.read("file-changes.json"))
    assert change["tool"] == "write_file" and change["files"][0]["before"] is None
    assert change["files"][0]["after"] == hashlib.sha256((ws / "notas.md").read_bytes()).hexdigest()
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["format"] == "spike-proof" and manifest["chat"]["id"] == cid
    assert [p["id"] for p in manifest["providers"]] == ["spike-local"]  # only the providers this chat used
    md = zf.read("chat.md").decode()
    assert "## You" in md and "Escribe las notas" in md and "Tool `write_file`" in md and "notas.md" in md
    assert "| spike-local |" in md or "Model calls" in md
    assert client.get("/api/conversations/nope/proof").status_code == 404


def test_api_can_select_only_environment_and_rejects_unknown_sections(env):
    client, state, local, _ = env
    cid = chat(client, local, "Private conversation", [text("Private answer")])
    response = client.get(f"/api/conversations/{cid}/proof?include=environment")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert 'chat.json' not in archive.namelist()
        assert 'calls.json' not in archive.namelist()
        assert b'Private' not in b''.join(archive.read(n) for n in archive.namelist())
    assert client.get(f"/api/conversations/{cid}/proof?include=invalid").status_code == 400
    response = client.get(f"/api/conversations/{cid}/proof?include=")
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == {'README.txt', 'manifest.json', 'SHA256SUMS'}
