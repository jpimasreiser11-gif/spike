"""Desktop actions (A19) through the app: the setting, the routes that start, answer, stop and show a task, the chat record
and the proof package. The task runs on a fake screen with a fake provider that answers from fixture JSON; the
streaming routes are exercised with the request in a worker thread and the approvals posted from the test."""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from spike.desktop.driver import Availability
from spike.desktop.settings import DEFAULTS
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider
from tests.helpers_desktop import FakeDriver, FakeInner, click_reply, instant, reply

LOCAL = ("127.0.0.1", 50_000)  # a request from this computer; the test client's own name is not one
PNG_START = "iVBORw0KGgo"  # every PNG, as base64


class Env:
    def __init__(self, state, client, remote, inners):
        self.state, self.client, self.remote, self.inners = state, client, remote, inners
        self.driver: FakeDriver = state.desktop.driver

    @property
    def inner(self) -> FakeInner:
        return self.inners["anthropic"]

    def enable(self, **settings):
        r = self.client.put("/api/settings", json={"desktop": {"enabled": True, "provider_id": "anthropic", **settings}})
        assert r.status_code == 200, r.text
        return r.json()["desktop"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    inners: dict[str, FakeInner] = {}
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        if cfg.kind == "anthropic":
            inner = inners.setdefault(cfg.id, FakeInner(cfg, []))
            inner.config = cfg
            return inner
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    state.desktop.driver, state.desktop.availability = FakeDriver(), Availability(True, "fake")
    state.desktop.task_options = {"sleep": instant, "settle_s": 0.0}
    app = create_app(state)
    with TestClient(app, client=LOCAL) as client:
        r = client.post("/api/providers", json={"preset": "anthropic", "api_key": "sk-ant-test",
                                                "model": "claude-sonnet-5-5", "allow_paid": True, "share_files": True})
        assert r.status_code == 200, r.text
        client.get("/api/providers")
        yield Env(state, client, TestClient(app), inners)


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


class Run:
    """A task started through the API in a worker thread: the response only ends when the task does."""

    def __init__(self, env: Env, **body):
        self.env, self.result = env, {}
        self.thread = threading.Thread(target=self._go, args=({"goal": "open the calculator", **body},), daemon=True)
        self.thread.start()

    def _go(self, body):
        r = self.env.client.post("/api/desktop/run", json=body)
        self.result.update(status=r.status_code, text=r.text)
        if r.status_code == 200:
            self.result["events"] = events_of(r)

    def card(self, timeout=10.0) -> str:
        """The id of the card the task is waiting on."""
        pending = self.env.state.desktop.broker.pending
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pending:
                return next(iter(list(pending)))
            time.sleep(0.01)
        raise AssertionError("the task never asked for approval")

    def answer(self, decision="approve", **extra):
        return self.env.client.post(f"/api/desktop/actions/{self.card()}", json={"decision": decision, **extra})

    def finish(self, timeout=10.0) -> list[dict]:
        self.thread.join(timeout)
        assert not self.thread.is_alive(), "the task did not end"
        assert self.result["status"] == 200, self.result
        return self.result["events"]


# ---------------------------------------------------------------- the setting
def test_the_setting_is_off_by_default_and_only_this_computer_can_change_it(env):
    assert env.client.get("/api/settings").json()["desktop"] == DEFAULTS and DEFAULTS["enabled"] is False
    refused = env.remote.put("/api/settings", json={"desktop": {"enabled": True}})
    assert refused.status_code == 403 and env.client.get("/api/settings").json()["desktop"]["enabled"] is False
    assert env.enable(max_steps=7)["enabled"] is True
    assert env.client.get("/api/settings").json()["desktop"]["max_steps"] == 7
    assert env.state.settings()["desktop"]["provider_id"] == "anthropic"


@pytest.mark.parametrize("bad", [{"max_steps": 500}, {"max_steps": 0}, {"tool": "invented"}, {"enabled": "yes"},
                                 {"colour": "red"}])
def test_bad_desktop_settings_are_refused(env, bad):
    assert env.client.put("/api/settings", json={"desktop": bad}).status_code == 400
    assert env.client.put("/api/settings", json={"desktop": "on"}).status_code == 400
    assert env.client.get("/api/settings").json()["desktop"] == DEFAULTS


def test_the_status_page_says_what_this_computer_can_do_and_which_providers_could(env):
    status = env.client.get("/api/desktop").json()
    assert status["settings"]["enabled"] is False and status["driver"]["available"] and status["running"] is False
    providers = {p["id"]: p for p in status["providers"]}
    assert providers["anthropic"]["ok"] and providers["anthropic"]["code"] == ""
    assert not providers["spike-local"]["ok"] and providers["spike-local"]["code"] == "local"
    assert env.remote.get("/api/desktop").status_code == 200  # it holds nothing private


def test_a_computer_that_cannot_be_driven_says_why(env):
    env.state.desktop.driver = None
    env.state.desktop.availability = Availability(False, "none", "this is a Wayland session", "wayland")
    status = env.client.get("/api/desktop").json()
    assert status["driver"]["available"] is False and status["driver"]["code"] == "wayland"
    env.enable()
    r = env.client.post("/api/desktop/run", json={"goal": "x"})
    assert r.status_code == 400 and "Wayland" in r.json()["detail"]


# ---------------------------------------------------------------- nothing starts that should not
def test_nothing_starts_while_the_setting_is_off(env):
    for path, body in (("/api/desktop/run", {"goal": "open the calculator"}), ("/api/desktop/estimate", {})):
        r = env.client.post(path, json=body)
        assert r.status_code == 400 and "off" in r.json()["detail"]
    assert env.driver.captures == 0 and env.inner.payloads == [] and env.client.get("/api/conversations").json() == []


@pytest.mark.parametrize("path, body", [
    ("/api/desktop/run", {"goal": "x"}), ("/api/desktop/estimate", {}), ("/api/desktop/actions/dsk_x_1", {"decision": "approve"}),
    ("/api/desktop/stop", None),
])
def test_only_this_computer_starts_answers_or_stops_a_task(env, path, body):
    env.enable()
    assert env.remote.post(path, json=body).status_code == 403
    assert env.remote.get("/api/desktop/shots/dsk_x/1").status_code == 403
    assert env.driver.captures == 0 and env.inner.payloads == []


def test_another_web_site_cannot_drive_the_page_either(env):
    env.enable()
    r = env.client.post("/api/desktop/run", json={"goal": "x"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and env.driver.captures == 0


@pytest.mark.parametrize("change, message", [
    ({"provider_id": "spike-local"}, "local model"),
    ({"allow_paid": False}, "may bill your account"),
    ({"share_files": False}, "not allowed to receive your files"),
])
def test_the_guard_and_the_privacy_setting_apply_to_a_desktop_task(env, change, message):
    env.enable()
    body = {}
    if "provider_id" in change:
        body["provider_id"] = change["provider_id"]
    else:
        assert env.client.patch("/api/providers/anthropic", json=change).status_code == 200
    for path in ("/api/desktop/run", "/api/desktop/estimate"):
        r = env.client.post(path, json={"goal": "open the calculator", **body})
        assert r.status_code == 400 and message in r.json()["detail"]
    assert env.driver.captures == 0 and env.inner.payloads == [] and env.driver.calls == []
    assert env.client.get("/api/conversations").json() == []


def test_the_estimate_is_shown_before_anything_is_sent(env):
    env.client.patch("/api/providers/anthropic", json={"limits": {"price_in": 3.0, "price_out": 15.0}})
    env.enable(max_steps=10)
    est = env.client.post("/api/desktop/estimate", json={}).json()
    assert est["calls"] == 11 and est["priced"] and est["cost"] > 0 and est["provider"] == "Anthropic"
    assert env.client.post("/api/desktop/estimate", json={"max_steps": 3}).json()["calls"] == 4
    assert env.client.post("/api/desktop/estimate", json={"max_steps": 0}).status_code == 422
    assert env.driver.captures == 0 and env.inner.payloads == []


# ---------------------------------------------------------------- a task
def test_a_task_waits_for_the_users_approval_and_everything_is_recorded(env):
    env.enable()
    env.inner.script = [reply("toolset_click"), reply("toolset_done")]
    run = Run(env)
    card = run.card()
    assert env.driver.calls == []  # a card is waiting; nothing was done
    task = env.state.desktop.task
    assert card.startswith(task.id + "_") and env.state.desktop.busy()
    assert env.client.post("/api/desktop/run", json={"goal": "again"}).status_code == 409  # one task at a time
    shot = env.client.get(f"/api/desktop/shots/{task.id}/1")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/png"
    assert shot.headers["cache-control"] == "no-store" and shot.content.startswith(b"\x89PNG")
    assert env.remote.get(f"/api/desktop/shots/{task.id}/1").status_code == 403
    assert env.client.get(f"/api/desktop/shots/{task.id}/99").status_code == 404
    assert env.client.post("/api/desktop/actions/not_a_card", json={"decision": "approve"}).status_code == 404
    assert env.client.post(f"/api/desktop/actions/{card}", json={"decision": "always_allow"}).status_code == 422
    assert env.client.post(f"/api/desktop/actions/{card}", json={"decision": "approve_batch", "n": 0}).status_code == 422
    answer = run.answer()
    assert answer.status_code == 200 and answer.json() == {"ok": True, "decision": "approve", "n": 1}
    events = run.finish()
    assert [e["type"] for e in events][0] == "desktop_conversation" and events[-1]["type"] == "desktop_done"
    assert events[-1]["reason"] == "finished" and env.driver.calls == [("click", 512, 742, "left", 1, ())]
    assert PNG_START not in run.result["text"] and not env.state.desktop.busy()
    assert env.client.post(f"/api/desktop/actions/{card}", json={"decision": "approve"}).status_code == 404  # gone

    cid = events[0]["id"]
    user, assistant = env.state.store.messages(cid)
    assert user["content"] == "open the calculator" and user["meta"] == {"desktop": True}
    record = assistant["meta"]["desktop"]
    assert [(a["action"], a["decision"], a["ok"]) for a in record["actions"]] == [("left_click", "approve", True)]
    assert assistant["content"] == "Done: the calculator shows 42." and record["reason"] == "finished"
    assert PNG_START not in json.dumps(assistant)
    rows = env.state.store.calls_for(cid)  # each step is in the call log, for this chat
    assert [(r["detail"], r["status"], r["tokens_in"]) for r in rows] == [("desktop step", "ok", 5200),
                                                                          ("desktop step", "ok", 7000)]
    assert env.inner.betas == [[], []]


def test_the_proof_package_lists_every_action_and_has_no_screenshots_unless_asked(env):
    env.enable()
    env.inner.script = [reply("toolset_click"), reply("toolset_done")]
    run = Run(env)
    run.answer()
    cid = run.finish()[0]["id"]
    zf = zipfile.ZipFile(io.BytesIO(env.client.get(f"/api/conversations/{cid}/proof").content))
    assert not [n for n in zf.namelist() if n.startswith("desktop/")]
    chat = zf.read("chat.md").decode("utf-8")
    assert "Desktop task with Anthropic (claude-sonnet-5-5): 1 of at most 20 steps, ended: finished; screenshots not kept" in chat
    assert "step 1: left_click x 512, y 742 · approve · ok" in chat
    assert PNG_START not in zf.read("chat.json").decode("utf-8")
    assert json.loads(zf.read("manifest.json"))["settings"]["desktop"]["enabled"] is True
    assert "desktop/" in zf.read("README.txt").decode("utf-8")


def test_screenshots_the_user_asked_to_keep_go_in_the_proof_and_leave_with_the_chat(env):
    env.enable()
    env.inner.script = [reply("toolset_click"), reply("toolset_done")]
    run = Run(env, keep_screenshots=True)
    run.answer()
    events = run.finish()
    cid = events[0]["id"]
    zf = zipfile.ZipFile(io.BytesIO(env.client.get(f"/api/conversations/{cid}/proof").content))
    shots = sorted(n for n in zf.namelist() if n.startswith("desktop/"))
    assert [n.rsplit("/", 1)[1] for n in shots] == ["shot-001.png", "shot-002.png"]
    assert zf.read(shots[0]).startswith(b"\x89PNG") and "screenshots kept" in zf.read("chat.md").decode("utf-8")
    sums = zf.read("SHA256SUMS").decode("utf-8")
    assert all(f"  {n}\n" in sums for n in shots)
    folder = env.state.home / "desktop" / cid
    assert folder.is_dir()
    assert env.client.delete(f"/api/conversations/{cid}").status_code == 200
    assert not folder.exists()


def test_the_stop_button_ends_the_task_and_nothing_is_done(env):
    env.enable()
    env.inner.script = [reply("toolset_click"), reply("toolset_done")]
    assert env.client.post("/api/desktop/stop").json() == {"ok": False}  # nothing to stop
    run = Run(env)
    run.card()
    stopped = env.client.post("/api/desktop/stop").json()
    assert stopped["ok"] is True and stopped["task"] == env.state.desktop.task.id
    events = run.finish()
    assert events[-1]["reason"] == "stopped" and env.driver.calls == [] and len(env.inner.payloads) == 1
    assistant = env.state.store.messages(events[0]["id"])[-1]
    assert assistant["meta"]["desktop"]["reason"] == "stopped" and assistant["content"] == ""


def test_the_stop_decision_on_a_card_ends_the_task_too(env):
    env.enable()
    env.inner.script = [reply("toolset_click")]
    run = Run(env)
    assert run.answer("stop").json()["decision"] == "stop"
    assert run.finish()[-1]["reason"] == "stopped" and env.driver.calls == []


def test_turning_the_setting_off_stops_a_running_task_at_once(env):
    env.enable()
    env.inner.script = [reply("toolset_click"), reply("toolset_done")]
    run = Run(env)
    run.card()
    assert env.client.put("/api/settings", json={"desktop": {"enabled": False}}).status_code == 200
    events = run.finish()
    assert events[-1]["reason"] == "stopped" and env.driver.calls == []
    assert env.client.post("/api/desktop/run", json={"goal": "again"}).status_code == 400


def test_approving_the_next_actions_over_the_api_is_capped_at_five(env):
    env.enable()
    env.inner.script = [click_reply(n) for n in range(1, 9)] + [reply("toolset_done")]
    run = Run(env)
    answered = run.answer("approve_batch", n=100)
    assert answered.status_code == 200 and answered.json() == {"ok": True, "decision": "batch", "n": 5}
    deadline = time.time() + 10
    while len(env.driver.calls) < 5 and time.time() < deadline:
        time.sleep(0.01)
    card = run.card()  # the sixth card
    assert len(env.driver.calls) == 5 and card.endswith("_6")
    env.client.post("/api/desktop/stop")
    assert run.finish()[-1]["reason"] == "stopped" and len(env.driver.calls) == 5


def test_a_conversation_that_does_not_exist_starts_nothing(env):
    env.enable()
    r = env.client.post("/api/desktop/run", json={"goal": "x", "conversation_id": "conv_nope"})
    assert r.status_code == 404 and not env.state.desktop.busy() and env.driver.captures == 0
    assert env.client.post("/api/desktop/run", json={"goal": "  "}).status_code in (400, 422)
