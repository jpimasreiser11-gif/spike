"""Dev planning and explicit skills reuse the existing agent, read-only gate and skill settings; no providers run."""

from __future__ import annotations

import asyncio
import io

import pytest

from spike.dev import terminal
from spike.dev.session import DevSession
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "app"))
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path / "home", provider_factory=factory)
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "calc.py").write_text("x = 1\n", encoding="utf-8")
    return state, local, folder


async def test_plan_reads_but_cannot_write_even_with_accept_edits(workflow):
    state, model, folder = workflow
    session = DevSession(state, folder, accept_edits=True, plan=True)
    model._script = [call("read_file", {"path": "calc.py"}),
                     call("write_file", {"path": "calc.py", "content": "changed"}, "w"), text("Review this plan.")]
    events = [ev async for ev in session.turn("plan the change")]
    offered = {t.name for t in model.requests[0].tools}
    assert {"read_file", "search", "find_files"} <= offered
    assert not {"write_file", "edit_file", "run_command", "run_python"} & offered
    assert any(ev["type"] == "tool_result" and ev["id"] == "w" and not ev["ok"] for ev in events)
    assert (folder / "calc.py").read_text(encoding="utf-8") == "x = 1\n"
    assert session.changes() == []
    assert "planning" in model.requests[0].messages[0].content.lower()
    assert session.store.messages(session.conversation_id)[0]["meta"]["dev_mode"] == "plan"
    assert DevSession(state, folder, resume=True).plan_mode
    await state.close()


async def test_returning_to_act_still_asks_and_keeps_undo(workflow):
    state, model, folder = workflow
    asked = []
    session = DevSession(state, folder, plan=True, decide=lambda ev: asked.append(ev["tool"]) or "allow_once")
    session.plan_mode = False
    model._script = [call("edit_file", {"path": "calc.py", "old": "1", "new": "2"}), text("Changed.")]
    _ = [ev async for ev in session.turn("apply the reviewed change")]
    assert asked == ["edit_file"]
    assert (folder / "calc.py").read_text(encoding="utf-8") == "x = 2\n"
    session.undo_last()
    assert (folder / "calc.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not DevSession(state, folder, resume=True).plan_mode
    await state.close()


async def test_explicit_skill_applies_only_to_this_turn_and_obeys_disabled(workflow):
    state, model, folder = workflow
    session = DevSession(state, folder)
    model._script = [text("A plan."), text("Another answer.")]
    events = [ev async for ev in session.turn("outline this", skills=["writing-plans"])]
    assert any(ev["type"] == "skill" and ev["mode"] == "chosen" and ev["names"] == ["writing-plans"] for ev in events)
    assert session.store.messages(session.conversation_id)[0]["meta"]["skills"] == ["writing-plans"]
    _ = [ev async for ev in session.turn("hello")]
    assert "# Skill: writing-plans" not in model.requests[-1].messages[0].content
    state.update_settings({"disabled_skills": ["writing-plans"]})
    with pytest.raises(ValueError, match="disabled|desactivada"):
        _ = [ev async for ev in session.turn("outline", skills=["writing-plans"])]
    with pytest.raises(ValueError, match="unknown|desconocida"):
        _ = [ev async for ev in session.turn("outline", skills=["missing-skill"])]
    state.update_settings({"disabled_skills": [], "skill_mode": "off"})
    with pytest.raises(ValueError, match="disabled|desactivada"):
        _ = [ev async for ev in session.turn("outline", skills=["writing-plans"])]
    assert len(model.requests) == 2 and len(session.history) == 4
    await state.close()


def test_terminal_plan_skill_and_act_are_explicit_and_do_not_auto_execute(workflow):
    state, model, folder = workflow
    session = DevSession(state, folder)
    model._script = [text("Plan only."), text("Skill plan.")]
    lines = iter(["/skills", "/PLAN\texplain calc.py", "/skill writing-plans outline", "/act", "/skill missing task", "/exit"])
    stream = io.StringIO()
    loop = asyncio.new_event_loop()
    try:
        assert terminal.repl(loop, session, terminal.Out(stream), lambda _: next(lines)) == 0
        assert len(model.requests) == 2
        assert model.requests[0].messages[-1].content == "explain calc.py"
        assert all("run_command" not in {t.name for t in req.tools} for req in model.requests)
        assert "writing-plans" in stream.getvalue() and "missing" in stream.getvalue()
        assert not session.plan_mode
        loop.run_until_complete(state.close())
    finally:
        loop.close()


def test_cli_plan_is_explicitly_passed_and_does_not_start_runtime(tmp_path, monkeypatch):
    from spike.cli import main as cli

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")

    async def no_adapters(self, provider_id):
        return None

    def run(session, loop, prompt=None):
        assert session.plan_mode and session.options().read_only
        assert prompt == "inspect only"
        return 0

    monkeypatch.setattr(AppState, "refresh_adapters", no_adapters)
    monkeypatch.setattr(AppState, "start_runtime", lambda self: pytest.fail("started runtime"))
    monkeypatch.setattr(terminal, "main", run)
    assert cli(["dev", str(tmp_path), "--plan", "-p", "inspect only"]) == 0


def test_cli_plan_cannot_be_combined_with_history_listing(tmp_path, monkeypatch):
    from spike.cli import main as cli

    monkeypatch.setattr(AppState, "__init__", lambda *a, **k: pytest.fail("listing initialized application"))
    assert cli(["dev", str(tmp_path), "--plan", "--sessions"]) == 2
