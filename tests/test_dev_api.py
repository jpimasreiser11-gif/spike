"""O1: Dev sessions over HTTP. The same DevSession as `spike dev`, driven by a scripted provider; no model, no network.
Streaming tests use tests/helpers_dev_api.py so a turn can wait on a permission card while the test answers it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text
from tests.helpers_dev_api import Asgi


class Env:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.model = ScriptedProvider([], name="spike-local")

        def factory(cfg):
            self.model.config = cfg
            return self.model

        self.factory = factory
        self.folder = tmp_path / "project"
        self.folder.mkdir()
        (self.folder / "calc.py").write_text("x = 1\n", encoding="utf-8")
        self.boot()

    def boot(self):
        """A fresh app on the same home: what a restart of the server does."""
        self.state = AppState(home=self.tmp / "home", provider_factory=self.factory)
        self.app = create_app(self.state)
        self.api = Asgi(self.app)

    def other_machine(self) -> Asgi:
        return Asgi(self.app, client=("192.168.1.20", 41000))

    async def open(self, **extra) -> dict:
        r = await self.api.post("/api/dev/sessions", {"folder": str(self.folder), **extra})
        assert r.status == 200, r.body
        return r.json()

    def turn(self, sid: str, message: str, **extra):
        return self.api.start("POST", f"/api/dev/sessions/{sid}/turn", {"message": message, **extra})

    def calc(self) -> str:
        return (self.folder / "calc.py").read_text(encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "app"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "fake-home"))
    (tmp_path / "fake-home").mkdir()
    return Env(tmp_path)


EDIT = {"path": "calc.py", "old": "1", "new": "2"}


async def test_open_reports_the_session_and_lists_it(env):
    info = await env.open()
    assert info["folder"] == str(env.folder.resolve()) and info["plan"] is False and info["history"] == 0
    assert info["provider"] and "sandbox" in info
    listing = (await env.api.get("/api/dev/sessions")).json()
    assert [s["id"] for s in listing["active"]] == [info["id"]]
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}")).json()["running"] is False
    await env.state.close()


async def test_one_session_per_folder_and_closing_frees_it(env):
    first = await env.open()
    again = await env.api.post("/api/dev/sessions", {"folder": str(env.folder)})
    assert again.status == 409 and again.json()["detail"] == "dev_session_open"
    assert (await env.api.delete(f"/api/dev/sessions/{first['id']}")).status == 200
    assert (await env.api.get("/api/dev/sessions")).json()["active"] == []
    second = await env.open()
    assert second["id"] != first["id"]
    assert (await env.api.get(f"/api/dev/sessions/{first['id']}")).status == 404
    await env.state.close()


@pytest.mark.parametrize("folder,status,code", [
    ("project", 400, "dev_folder_relative"),
    ("{tmp}/missing", 400, "dev_folder_missing"),
    ("{tmp}/project/calc.py", 400, "dev_folder_not_dir"),
    ("{tmp}/home", 403, "dev_folder_forbidden"),  # SPIKE's own data folder, never offered to a model
    ("{tmp}/home/dev", 403, "dev_folder_forbidden"),
    ("", 400, "dev_folder_relative"),
])
async def test_folders_that_are_not_a_chosen_project_folder_are_refused(env, folder, status, code):
    env.state.home.mkdir(parents=True, exist_ok=True)
    (env.state.home / "dev").mkdir(parents=True, exist_ok=True)
    r = await env.api.post("/api/dev/sessions", {"folder": folder.replace("{tmp}", str(env.tmp))})
    assert r.status == status and r.json()["detail"] == code
    assert (await env.api.get("/api/dev/sessions")).json()["active"] == []
    await env.state.close()


async def test_home_and_disk_root_need_an_explicit_confirmation(env):
    home = Path.home()
    assert home == env.tmp / "fake-home"
    for folder in (str(home), str(Path(home.anchor))):
        r = await env.api.post("/api/dev/sessions", {"folder": folder})
        assert r.status == 409 and r.json()["detail"] == "dev_folder_broad"
        r = await env.api.post("/api/dev/sessions", {"folder": folder, "confirm_broad": False})
        assert r.status == 409
    assert (await env.api.get("/api/dev/sessions")).json()["active"] == []
    ok = await env.api.post("/api/dev/sessions", {"folder": str(home), "confirm_broad": True})
    assert ok.status == 200 and ok.json()["broad"] is True
    # the confirmation does not open SPIKE's own data folder, which sits inside the home folder
    env.state.home.mkdir(parents=True, exist_ok=True)
    again = await env.api.post("/api/dev/sessions", {"folder": str(env.state.home), "confirm_broad": True})
    assert again.status == 403
    await env.state.close()


ROUTES = [("GET", "/api/dev/sessions"), ("GET", "/api/dev/history?folder=/tmp"), ("GET", "/api/dev/skills"),
          ("POST", "/api/dev/sessions"), ("GET", "/api/dev/sessions/x"), ("DELETE", "/api/dev/sessions/x"),
          ("POST", "/api/dev/sessions/x/turn"), ("POST", "/api/dev/sessions/x/cancel"),
          ("POST", "/api/dev/sessions/x/mode"), ("GET", "/api/dev/sessions/x/changes"),
          ("POST", "/api/dev/sessions/x/undo"), ("GET", "/api/dev/sessions/x/messages"),
          ("GET", "/api/dev/sessions/x/files/calc.py"), ("POST", "/api/dev/permissions/x"),
          ("POST", "/api/dev/questions/x")]


@pytest.mark.parametrize("method,path", ROUTES)
async def test_requests_from_another_machine_are_refused(env, method, path):
    r = await env.other_machine().request(method, path, {} if method == "POST" else None)
    assert r.status == 403
    r = await env.api.request(method, path, {} if method == "POST" else None,
                              headers={"origin": "https://evil.example"})
    assert r.status == 403
    await env.state.close()


async def test_a_session_opened_here_cannot_be_driven_from_another_machine(env):
    info = await env.open()
    env.model._script = [text("hello")]
    stranger = env.other_machine()
    r = await stranger.post(f"/api/dev/sessions/{info['id']}/turn", {"message": "hi"})
    assert r.status == 403 and env.model.requests == []
    assert (await stranger.post(f"/api/dev/sessions/{info['id']}/mode", {"plan": True})).status == 403
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}")).json()["plan"] is False
    await env.state.close()


async def test_a_turn_streams_events_and_is_saved_in_the_history(env):
    info = await env.open()
    env.model._script = [call("read_file", {"path": "calc.py"}), text("The file sets ", "x to 1.")]
    live = env.turn(info["id"], "what does calc.py do?")
    events = await live.rest()
    assert live.status == 200 and live.headers["content-type"].startswith("text/event-stream")
    kinds = [e["type"] for e in events]
    assert "tool_call" in kinds and "tool_result" in kinds and kinds[-1] == "done"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "The file sets x to 1."
    messages = (await env.api.get(f"/api/dev/sessions/{info['id']}/messages")).json()["messages"]
    assert [(m["role"], m["content"]) for m in messages] == [("user", "what does calc.py do?"),
                                                              ("assistant", "The file sets x to 1.")]
    await env.state.close()


async def test_plan_mode_cannot_write_or_run_even_when_the_model_tries(env):
    info = await env.open(plan=True)
    assert info["plan"] is True
    env.model._script = [call("write_file", {"path": "calc.py", "content": "changed"}, "w"),
                         call("run_command", {"command": "touch ran.txt"}, "r"), text("Here is the plan.")]
    events = await env.turn(info["id"], "plan the change").rest()
    offered = {t.name for t in env.model.requests[0].tools}
    assert {"read_file", "search", "find_files"} <= offered
    assert not {"write_file", "edit_file", "run_command", "run_python"} & offered
    assert not any(e["type"] == "permission_request" for e in events)
    assert [e["ok"] for e in events if e["type"] == "tool_result"] == [False, False]
    assert env.calc() == "x = 1\n" and not (env.folder / "ran.txt").exists()
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/changes")).json()["changes"] == []
    await env.state.close()


async def test_act_mode_asks_before_editing_and_nothing_runs_until_answered(env):
    info = await env.open(plan=True)
    assert (await env.api.post(f"/api/dev/sessions/{info['id']}/mode", {"plan": False})).json()["plan"] is False
    env.model._script = [call("edit_file", EDIT, "e"), text("Changed x to 2.")]
    live = env.turn(info["id"], "set x to 2")
    ask = await live.until("permission_request")
    assert ask["tool"] == "edit_file" and ask["arguments"]["path"] == "calc.py"
    await asyncio.sleep(0.2)
    assert env.calc() == "x = 1\n"  # asked, not answered: nothing happened
    assert len(env.model.requests) == 1
    r = await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_once"})
    assert r.status == 200
    rest = await live.rest()
    assert any(e["type"] == "tool_result" and e["ok"] for e in rest)
    assert env.calc() == "x = 2\n"
    changes = (await env.api.get(f"/api/dev/sessions/{info['id']}/changes")).json()["changes"]
    assert [(c["tool"], c["files"], c["undone"]) for c in changes] == [("edit_file", ["calc.py"], False)]
    assert (await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_once"})).status == 404
    undone = await env.api.post(f"/api/dev/sessions/{info['id']}/undo", {})
    assert undone.status == 200 and undone.json()["files"] == ["calc.py"]
    assert env.calc() == "x = 1\n"
    assert (await env.api.post(f"/api/dev/sessions/{info['id']}/undo", {})).status == 400  # nothing left
    await env.state.close()


async def test_a_denied_permission_stops_the_action(env):
    info = await env.open()
    env.model._script = [call("edit_file", EDIT, "e"), text("I could not change it.")]
    live = env.turn(info["id"], "set x to 2")
    ask = await live.until("permission_request")
    assert (await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "deny"})).status == 200
    rest = await live.rest()
    assert [e["ok"] for e in rest if e["type"] == "tool_result"] == [False]
    assert env.calc() == "x = 1\n"
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/changes")).json()["changes"] == []
    await env.state.close()


async def test_there_is_no_accept_everything_switch_and_other_decisions_are_refused(env):
    info = await env.open(accept_edits=True)  # not an option of the API: ignored, edits still ask
    env.model._script = [call("edit_file", EDIT, "e"), text("done")]
    live = env.turn(info["id"], "set x to 2")
    ask = await live.until("permission_request")
    bad = await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_domain"})
    assert bad.status == 422 and env.calc() == "x = 1\n"
    await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "deny"})
    await live.rest()
    await env.state.close()


async def test_ask_user_reaches_the_ui_and_the_answer_goes_back_to_the_model(env):
    info = await env.open()
    env.model._script = [call("ask_user", {"question": "Which file?", "options": ["calc.py", "other.py"]}, "q"),
                         text("Using the file you chose.")]
    live = env.turn(info["id"], "change the file")
    ask = await live.until("question")
    assert ask["question"] == "Which file?" and ask["options"] == ["calc.py", "other.py"]
    assert (await env.api.post(f"/api/dev/questions/{ask['id']}", {"answer": "calc.py"})).status == 200
    rest = await live.rest()
    assert any(e["type"] == "answered" and e["answer"] == "calc.py" for e in rest)
    assert "calc.py" in env.model.requests[1].messages[-1].content
    assert (await env.api.post(f"/api/dev/questions/{ask['id']}", {"answer": "again"})).status == 404
    await env.state.close()


def alive(pid: int) -> bool:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return False
    return "\nState:\tZ" not in status


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc to see the process")
async def test_cancelling_a_turn_stops_the_running_command(env):
    info = await env.open()
    pid_file = env.folder / "pid.txt"
    env.model._script = [call("run_command", {"command": f"echo $$ > {pid_file.name}; exec sleep 60"}, "r"),
                         text("never")]
    live = env.turn(info["id"], "run the slow thing")
    ask = await live.until("permission_request")
    await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_once"})
    for _ in range(100):
        if pid_file.exists() and pid_file.read_text(encoding="utf-8").strip():
            break
        await asyncio.sleep(0.05)
    pid = int(pid_file.read_text(encoding="utf-8").strip())
    assert alive(pid)
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}")).json()["running"] is True
    busy = await env.api.post(f"/api/dev/sessions/{info['id']}/turn", {"message": "second"})
    assert busy.status == 409 and busy.json()["detail"] == "dev_turn_running"
    cancelled = await env.api.post(f"/api/dev/sessions/{info['id']}/cancel")
    assert cancelled.status == 200 and cancelled.json()["cancelled"] is True
    rest = await live.rest()
    assert rest[-1]["type"] == "stopped"
    for _ in range(100):
        if not alive(pid):
            break
        await asyncio.sleep(0.05)
    assert not alive(pid)
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}")).json()["running"] is False
    saved = (await env.api.get(f"/api/dev/sessions/{info['id']}/messages")).json()["messages"]
    assert saved[-1]["role"] == "assistant" and saved[-1]["meta"]["stopped"] is True
    # and the session is usable again
    env.model._script = [text("back")]
    assert (await env.turn(info["id"], "hello").rest())[-1]["type"] == "done"
    assert (await env.api.post(f"/api/dev/sessions/{info['id']}/cancel")).json()["cancelled"] is False
    await env.state.close()


async def test_closing_the_browser_stops_the_turn_like_cancelling(env):
    info = await env.open()
    env.model._script = [call("edit_file", EDIT, "e"), text("never")]
    live = env.turn(info["id"], "set x to 2")
    await live.until("permission_request")
    await live.drop()
    for _ in range(100):
        if not (await env.api.get(f"/api/dev/sessions/{info['id']}")).json()["running"]:
            break
        await asyncio.sleep(0.05)
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}")).json()["running"] is False
    assert env.calc() == "x = 1\n"
    await env.state.close()


async def test_a_turn_stops_after_the_step_limit_of_the_terminal(env):
    from spike.dev.session import MAX_STEPS

    info = await env.open(plan=True)
    env.model._script = lambda request: call("read_file", {"path": "calc.py"}, f"c{len(env.model.requests)}")
    events = await env.turn(info["id"], "loop forever").rest(timeout=60)
    assert events[-1]["type"] == "done" and len(env.model.requests) <= MAX_STEPS + 1
    await env.state.close()


async def test_skills_are_chosen_per_turn_and_unknown_ones_are_refused_before_the_model(env):
    info = await env.open()
    skills = (await env.api.get("/api/dev/skills")).json()["skills"]
    assert "writing-plans" in {s["name"] for s in skills}
    env.model._script = [text("A plan."), text("Another answer.")]
    events = await env.turn(info["id"], "outline this", skills=["writing-plans"]).rest()
    assert any(e["type"] == "skill" and e["names"] == ["writing-plans"] for e in events)
    await env.turn(info["id"], "hello").rest()
    assert "# Skill: writing-plans" not in env.model.requests[-1].messages[0].content
    before = len(env.model.requests)
    bad = await env.api.post(f"/api/dev/sessions/{info['id']}/turn", {"message": "x", "skills": ["nope"]})
    assert bad.status == 400 and "nope" in bad.json()["detail"]
    env.state.update_settings({"disabled_skills": ["writing-plans"]})
    off = await env.api.post(f"/api/dev/sessions/{info['id']}/turn", {"message": "x", "skills": ["writing-plans"]})
    assert off.status == 400
    assert len(env.model.requests) == before
    assert len((await env.api.get(f"/api/dev/sessions/{info['id']}/messages")).json()["messages"]) == 4
    await env.state.close()


async def test_resume_after_a_restart_shows_the_history_and_repeats_nothing(env):
    info = await env.open()
    env.model._script = [call("edit_file", EDIT, "e"), text("Changed x to 2.")]
    live = env.turn(info["id"], "set x to 2")
    ask = await live.until("permission_request")
    await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_once"})
    await live.rest()
    assert env.calc() == "x = 2\n"
    saved_id = info["conversation_id"]
    await env.state.close()

    env.boot()  # the server restarts: no session is open, nothing runs by itself
    env.model.requests.clear()
    env.model._script = []
    assert (await env.api.get("/api/dev/sessions")).json()["active"] == []
    history = (await env.api.get("/api/dev/history", )).status  # folder is required
    assert history == 422
    rows = (await env.api.get(f"/api/dev/history?folder={env.folder}")).json()["sessions"]
    assert [r["id"] for r in rows] == [saved_id] and rows[0]["preview"] == "set x to 2"
    back = await env.open(resume_id=saved_id)
    assert back["conversation_id"] == saved_id and back["history"] == 2
    messages = (await env.api.get(f"/api/dev/sessions/{back['id']}/messages")).json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"] and messages[1]["content"] == "Changed x to 2."
    assert env.model.requests == [] and env.calc() == "x = 2\n"  # nothing was sent and nothing was redone
    changes = (await env.api.get(f"/api/dev/sessions/{back['id']}/changes")).json()["changes"]
    assert len(changes) == 1 and changes[0]["undone"] is False
    assert (await env.api.post(f"/api/dev/sessions/{back['id']}/undo", {})).status == 200  # still undoable
    assert env.calc() == "x = 1\n"
    # an id from another folder or a made-up id is an error, never a new conversation
    await env.api.delete(f"/api/dev/sessions/{back['id']}")
    other = env.tmp / "other"
    other.mkdir()
    r = await env.api.post("/api/dev/sessions", {"folder": str(other), "resume_id": saved_id})
    assert r.status == 404 and r.json()["detail"] == "dev_resume_unknown"
    await env.state.close()


async def test_resume_restores_the_plan_mode_of_the_last_turn(env):
    info = await env.open(plan=True)
    env.model._script = [text("A plan.")]
    await env.turn(info["id"], "plan it").rest()
    await env.api.delete(f"/api/dev/sessions/{info['id']}")
    assert (await env.open(resume=True))["plan"] is True
    await env.state.close()


async def test_changes_conflict_needs_force_to_undo(env):
    info = await env.open()
    env.model._script = [call("edit_file", EDIT, "e"), text("ok")]
    live = env.turn(info["id"], "edit")
    ask = await live.until("permission_request")
    await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_once"})
    await live.rest()
    (env.folder / "calc.py").write_text("x = 99\n", encoding="utf-8")
    r = await env.api.post(f"/api/dev/sessions/{info['id']}/undo", {})
    assert r.status == 409 and r.json()["detail"] == "dev_undo_conflict" and r.json()["changed"] == ["calc.py"]
    assert env.calc() == "x = 99\n"
    assert (await env.api.post(f"/api/dev/sessions/{info['id']}/undo", {"force": True})).status == 200
    assert env.calc() == "x = 1\n"
    await env.state.close()


async def test_files_of_the_folder_are_served_only_from_inside_it(env):
    info = await env.open()
    (env.folder / "sub").mkdir()
    (env.folder / "sub" / "page.html").write_text("<h1>hi</h1>", encoding="utf-8")
    (env.tmp / "secret.txt").write_text("nope", encoding="utf-8")
    r = await env.api.get(f"/api/dev/sessions/{info['id']}/files/sub/page.html")
    assert r.status == 200 and r.body == b"<h1>hi</h1>" and "attachment" in r.headers["content-disposition"]
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/files/..%2Fsecret.txt")).status in (400, 404)
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/files/sub/../../secret.txt")).status == 400
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/files/missing.txt")).status == 404
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/files/sub")).status == 404
    await env.state.close()


async def test_clear_starts_a_new_conversation_and_keeps_the_changes(env):
    info = await env.open()
    env.model._script = [call("edit_file", EDIT, "e"), text("ok")]
    live = env.turn(info["id"], "edit")
    ask = await live.until("permission_request")
    await env.api.post(f"/api/dev/permissions/{ask['id']}", {"decision": "allow_once"})
    await live.rest()
    cleared = (await env.api.post(f"/api/dev/sessions/{info['id']}/clear")).json()
    assert cleared["conversation_id"] != info["conversation_id"]
    assert (await env.api.get(f"/api/dev/sessions/{info['id']}/messages")).json()["messages"] == []
    assert len((await env.api.get(f"/api/dev/sessions/{info['id']}/changes")).json()["changes"]) == 1
    await env.state.close()
