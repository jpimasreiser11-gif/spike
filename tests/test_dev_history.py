"""Saved Dev sessions stay local and folder-scoped, including after the global chat list exceeds 200 rows."""

from __future__ import annotations

import asyncio
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from spike.cli import main as cli
from spike.dev.history import find_session, list_sessions
from spike.dev.session import DevSession
from spike.dev.terminal import Out, sessions_text
from spike.server.state import AppState
from spike.store.db import Store
from tests.helpers import ScriptedProvider, text


@pytest.fixture
def saved(tmp_path, monkeypatch):
    home, root = tmp_path / "home", tmp_path / "proyecto ñ"
    root.mkdir()
    monkeypatch.setenv("SPIKE_HOME", str(home))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "workspace"))
    path = home / "dev" / "sessions.db"
    store = Store(path)
    yield home, root, path, store
    store._conn.close()


def seed(store, root, question="Revisar cálculo", **kwargs):
    row = store.create_conversation(title=f"dev:{root.as_posix()}", **kwargs)
    store.add_message(row["id"], "user", question, created=10)
    store.add_message(row["id"], "assistant", "Respuesta privada", {"private": True}, created=11)
    return row["id"]


def test_lists_only_this_folder_and_pages_in_stable_order(saved):
    _, root, path, store = saved
    old = seed(store, root, updated=1)
    first = seed(store, root, updated=2)
    second = seed(store, root, updated=2)
    seed(store, root / "other", updated=3)
    rows = list_sessions(path, root, limit=1, offset=0)
    assert rows[0]["id"] == max(first, second)
    assert rows[0]["preview"] == "Revisar cálculo" and rows[0]["messages"] == 2
    assert list_sessions(path, root, limit=1, offset=2)[0]["id"] == old
    assert list_sessions(path, root, offset=3) == []


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing" / "sessions.db"
    assert list_sessions(path, tmp_path) == []
    assert find_session(path, tmp_path, "unknown") is None
    assert not path.parent.exists()


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (101, 0), (2, -1)])
def test_invalid_page_rejected(saved, limit, offset):
    _, root, path, _ = saved
    with pytest.raises(ValueError):
        list_sessions(path, root, limit=limit, offset=offset)


def test_lookup_is_exact_and_cannot_open_another_folder(saved):
    _, root, path, store = saved
    cid = seed(store, root)
    other = seed(store, root / "other")
    assert find_session(path, root, cid)["id"] == cid
    for invalid in (other, cid[:8], "' OR 1=1 --", "missing"):
        assert find_session(path, root, invalid) is None


def test_list_does_not_modify_database_or_include_answers(saved):
    _, root, path, store = saved
    cid = seed(store, root, "x" * 300)
    before = list(store._conn.iterdump())
    rows = list_sessions(path, root)
    assert len(rows[0]["preview"]) <= 120
    assert "Respuesta privada" not in str(rows)
    assert list(store._conn.iterdump()) == before
    assert store.get_conversation(cid)["title"] == f"dev:{root.as_posix()}"


@pytest.fixture
def runtime(saved):
    home, root, _, _ = saved
    provider = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        provider.config = cfg
        return provider

    state = AppState(home=home, provider_factory=factory)
    yield state, provider, root
    asyncio.run(state.close())


def test_continue_finds_old_folder_after_200_other_conversations(saved, runtime):
    _, root, _, store = saved
    cid = seed(store, root, updated=1)
    for i in range(205):
        seed(store, root / str(i), updated=i + 2)
    state, _, _ = runtime
    session = DevSession(state, root, resume=True)
    assert session.conversation_id == cid
    assert session.history[-1].private == ["Respuesta privada"]


async def test_resume_exact_session_continues_history_and_keeps_permissions(saved, runtime):
    _, root, _, store = saved
    cid = seed(store, root, "Anterior", updated=1)
    seed(store, root, "Más reciente", updated=2)
    state, provider, _ = runtime
    session = DevSession(state, root, resume_id=cid)
    assert session.conversation_id == cid
    assert session.broker.policies.get("edit_file", "ask") != "allow"
    provider._script = [text("Continuación")]
    events = [ev async for ev in session.turn("Sigue")]
    assert events[-1]["type"] == "done"
    seen = [m.content for m in provider.requests[0].messages]
    assert "Anterior" in seen and "Más reciente" not in seen
    assert [m["content"] for m in store.messages(cid)][-2:] == ["Sigue", "Continuación"]


def test_bad_resume_does_not_create_session(saved, runtime):
    _, root, _, store = saved
    cid = seed(store, root / "other")
    state, _, _ = runtime
    before = len(store.list_conversations())
    with pytest.raises(ValueError, match="session"):
        DevSession(state, root, resume_id=cid)
    assert len(store.list_conversations()) == before


def test_session_list_cli_never_initializes_application(saved, monkeypatch, capsys):
    _, root, _, store = saved
    cid = seed(store, root)
    monkeypatch.setattr(AppState, "__init__", lambda *a, **k: pytest.fail("listing initialized the application"))
    assert cli(["dev", str(root), "--sessions"]) == 0
    shown = capsys.readouterr().out
    assert cid in shown and "Revisar cálculo" in shown and "--resume" in shown
    assert cli(["dev", str(root), "--sessions", "--offset", "1"]) == 0
    assert cid not in capsys.readouterr().out


def test_session_cli_invalid_id_never_starts_runtime(saved, monkeypatch, capsys):
    _, root, _, store = saved
    other = seed(store, root / "other")
    monkeypatch.setattr(AppState, "__init__", lambda *a, **k: pytest.fail("invalid resume initialized application"))
    assert cli(["dev", str(root), "--resume", other, "--start-local"]) == 2
    assert "session" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
    ["--sessions", "--start-local"], ["--sessions", "--print", "send"],
    ["--sessions", "--limit", "0"], ["--sessions", "--offset", "-1"], ["--offset", "1"],
])
def test_cli_rejects_ambiguous_or_invalid_listing_options(saved, monkeypatch, capsys, args):
    _, root, _, _ = saved
    monkeypatch.setattr(AppState, "__init__", lambda *a, **k: pytest.fail("invalid options initialized application"))
    assert cli(["dev", str(root), *args]) == 2
    assert capsys.readouterr().err


def test_cli_rejects_resume_and_continue_together(saved):
    _, root, _, _ = saved
    with pytest.raises(SystemExit) as exc:
        cli(["dev", str(root), "--continue", "--resume", "id"])
    assert exc.value.code == 2


def test_terminal_listing_neutralizes_escape_sequences_and_handles_empty(saved):
    _, root, path, store = saved
    seed(store, root, "hello\x1b[31m\nnext\u202eevil")
    shown = "\n".join(sessions_text(list_sessions(path, root)))
    assert "\x1b" not in shown and "\u202e" not in shown
    assert "hello" in shown
    empty = "\n".join(sessions_text([]))
    assert "No saved sessions" in empty and "sesiones" in empty
    stream = io.StringIO()
    Out(stream)(shown)
    assert "hello" in stream.getvalue()


def test_repl_sessions_lists_without_requesting_a_model(saved, runtime):
    from spike.dev.terminal import repl

    _, root, _, store = saved
    cid = seed(store, root)
    state, provider, _ = runtime
    session = DevSession(state, root, resume_id=cid)
    lines = iter(["/sessions", "/exit"])
    stream = io.StringIO()
    loop = asyncio.new_event_loop()
    try:
        assert repl(loop, session, Out(stream), lambda _: next(lines)) == 0
    finally:
        loop.close()
    assert cid in stream.getvalue() and "Revisar cálculo" in stream.getvalue()
    assert provider.requests == []


def test_cli_reopens_selected_session_and_writes_to_it(saved, runtime, monkeypatch, capsys):
    _, root, _, store = saved
    cid = seed(store, root, "Anterior", updated=1)
    other = seed(store, root, "Más reciente", updated=2)
    state, provider, _ = runtime
    provider._script = [text("Continuado desde terminal")]

    async def refresh(pid):
        return None  # no HTTP request to the local server either

    async def close():
        return None  # the fixture owns this state

    monkeypatch.setattr("spike.server.state.AppState", lambda: state)
    monkeypatch.setattr(state, "refresh_adapters", refresh)
    monkeypatch.setattr(state, "close", close)
    assert cli(["dev", str(root), "--resume", cid, "--print", "Sigue aquí"]) == 0
    assert "Continuado desde terminal" in capsys.readouterr().out
    assert store.messages(cid)[-1]["content"] == "Continuado desde terminal"
    assert len(store.messages(other)) == 2


def test_read_error_is_actionable_cli_error(saved, capsys):
    _, root, path, store = saved
    store._exec("DROP TABLE messages")
    assert cli(["dev", str(root), "--sessions"]) == 2
    assert "sessions" in capsys.readouterr().err
    assert path.exists()


def test_real_cli_process_lists_saved_unicode_history_without_creating_app_state(saved):
    home, root, _, store = saved
    cid = seed(store, root, "Revisar cálculo español")
    process = subprocess.run([sys.executable, "-m", "spike.cli", "dev", str(root), "--sessions"],
                             cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHONUTF8": "1"},
                             capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert process.returncode == 0, process.stderr
    assert cid in process.stdout and "Revisar cálculo español" in process.stdout
    assert not (home / "spike.db").exists()
    assert not (home / "secrets.json").exists()
