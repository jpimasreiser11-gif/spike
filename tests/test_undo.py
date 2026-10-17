"""Undo: a copy of each file is kept before a tool changes it, and every step of an answer can be put back."""

import json

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from spike.store.checkpoints import CheckpointError, Checkpoints
from spike.store.db import Store
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
    client.put("/api/settings", json={"tool_policies": {"write_file": "allow", "create_docx": "allow"}})
    return client, state, scripts["spike-local"], tmp_path / "ws"


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def chat(client, message="Escribe las notas", cid=None):
    body = {"message": message, "mode": "core", **({"conversation_id": cid} if cid else {})}
    return events_of(client.post("/api/chat", json=body))


def test_each_write_can_be_undone_back_to_the_start(env):
    client, state, local, ws = env
    local._script = [call("write_file", {"path": "notas.md", "content": "uno"}, "c1"),
                     call("write_file", {"path": "notas.md", "content": "dos"}, "c2"), text("Hecho")]
    evs = chat(client)
    results = [e for e in evs if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [True, True] and all(r.get("checkpoint") for r in results)
    assert (ws / "notas.md").read_text() == "dos"

    second, first = results[1]["checkpoint"], results[0]["checkpoint"]
    assert client.post(f"/api/checkpoints/{second}/undo", json={}).json()["ok"]
    assert (ws / "notas.md").read_text() == "uno"
    assert client.post(f"/api/checkpoints/{second}/undo", json={}).status_code == 400  # already undone
    assert client.post(f"/api/checkpoints/{first}/undo", json={}).json()["ok"]
    assert not (ws / "notas.md").exists()  # the file did not exist before the answer

    cid = next(e["id"] for e in evs if e["type"] == "conversation")
    stored = [m for m in state.store.messages(cid) if m["role"] == "assistant"][0]["meta"]
    assert all(ev.get("undone") for ev in stored["tools"] if ev["type"] == "tool_result")
    assert all(ev.get("undone") for ev in stored["events"] if ev["type"] == "tool_result")


def test_a_file_changed_later_is_only_overwritten_when_asked(env):
    client, _, local, ws = env
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "plan.md").write_text("mío")
    local._script = [call("write_file", {"path": "plan.md", "content": "del modelo"}), text("Hecho")]
    cp = next(e for e in chat(client) if e["type"] == "tool_result")["checkpoint"]
    (ws / "plan.md").write_text("editado después por el usuario")
    r = client.post(f"/api/checkpoints/{cp}/undo", json={})
    assert r.status_code == 409 and r.json()["detail"]["changed"] == [str(ws / "plan.md")]
    assert (ws / "plan.md").read_text() == "editado después por el usuario"
    assert client.post(f"/api/checkpoints/{cp}/undo", json={"force": True}).json()["ok"]
    assert (ws / "plan.md").read_text() == "mío"


def test_document_tools_keep_a_copy_and_failed_calls_offer_no_undo(env):
    client, _, local, ws = env
    local._script = [call("create_docx", {"path": "informe.docx", "content": "# Informe"}, "c1"),
                     call("write_file", {"path": "../fuera.txt", "content": "x"}, "c2"), text("Hecho")]
    results = [e for e in chat(client) if e["type"] == "tool_result"]
    assert results[0]["ok"] and results[0]["checkpoint"] and (ws / "informe.docx").exists()
    assert not results[1]["ok"] and "checkpoint" not in results[1]
    assert client.post(f"/api/checkpoints/{results[0]['checkpoint']}/undo", json={}).json()["ok"]
    assert not (ws / "informe.docx").exists()
    assert client.post("/api/checkpoints/nope/undo", json={}).status_code == 404


def test_deleting_a_chat_deletes_its_copies(env):
    client, state, local, ws = env
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "a.txt").write_text("antes")
    local._script = [call("write_file", {"path": "a.txt", "content": "después"}), text("ok")]
    evs = chat(client)
    cid = next(e["id"] for e in evs if e["type"] == "conversation")
    cp = next(e for e in evs if e["type"] == "tool_result")["checkpoint"]
    assert (state.home / "checkpoints" / cp / "0.bin").read_text() == "antes"
    client.delete(f"/api/conversations/{cid}")
    assert not (state.home / "checkpoints" / cp).exists() and state.store.get_checkpoint(cp) is None


def test_the_run_is_kept_for_the_step_by_step_view(env):
    client, state, local, _ = env
    local._script = [call("write_file", {"path": "n.md", "content": "x"}), text("Lo ", "he ", "escrito.")]
    evs = chat(client)
    cid = next(e["id"] for e in evs if e["type"] == "conversation")
    stored = [m for m in state.store.messages(cid) if m["role"] == "assistant"][0]["meta"]["events"]
    kinds = [e["type"] for e in stored]
    assert kinds[0] == "route" and kinds[-1] == "done" and "tool_call" in kinds and "tool_result" in kinds
    assert [e["text"] for e in stored if e["type"] == "delta"] == ["Lo he escrito."]  # pieces merged
    assert all(isinstance(e["t"], float) for e in stored) and stored == sorted(stored, key=lambda e: e["t"])


def test_old_copies_and_copies_of_deleted_chats_are_pruned(tmp_path):
    store = Store(tmp_path / "s.db")
    cps = Checkpoints(store, tmp_path / "cp")
    conv = store.create_conversation()
    (tmp_path / "f.txt").write_text("x")
    keep = cps.before(conv["id"], "c1", "write_file", [tmp_path / "f.txt"])
    orphan = cps.before("gone", "c2", "write_file", [tmp_path / "f.txt"])
    cps.prune()
    assert store.get_checkpoint(keep) and store.get_checkpoint(orphan) is None
    assert not (tmp_path / "cp" / orphan).exists()
    cps.prune(days=-1)
    assert store.get_checkpoint(keep) is None
    with pytest.raises(CheckpointError):
        cps.undo(keep)
