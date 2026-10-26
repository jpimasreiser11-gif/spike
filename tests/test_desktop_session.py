"""Desktop actions (A19): the task loop and the rules around it, with a fake driver and a fake provider that answers from
fixture JSON (written from the provider's documentation). Nothing here touches a screen or the network."""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from spike.core.types import ProviderError
from spike.desktop.driver import fit_size, png_size
from spike.desktop.service import points_at_this_computer
from spike.desktop.session import MAX_BATCH, Decision, DesktopBroker, Refused
from spike.desktop.settings import DEFAULTS, HARD_MAX_STEPS, clean
from spike.providers.guard import call_cost
from tests.helpers_desktop import FakeDriver, Rig, action_reply, click_reply, of_type, play, reply


def done_reply(text="Done."):
    return {"id": "msg_done", "type": "message", "role": "assistant", "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 100, "output_tokens": 10}}


BATCH_IDS = [b["id"] for b in reply("toolset_batch")["content"] if b["type"] == "tool_use"]


def untouched(rig: Rig) -> bool:
    """Nothing was sent to the provider, no screenshot was taken and nothing was done on the screen."""
    return rig.inner.payloads == [] and rig.driver.captures == 0 and rig.driver.calls == []


# ---------------------------------------------------------------- off by default, and who may do it
def test_desktop_actions_are_off_by_default():
    assert DEFAULTS["enabled"] is False and clean({})["enabled"] is False
    assert clean({"enabled": True, "max_steps": 7}) == {**DEFAULTS, "enabled": True, "max_steps": 7}


def test_the_settings_are_validated():
    for bad in ({"max_steps": 0}, {"max_steps": HARD_MAX_STEPS + 1}, {"max_steps": True}, {"max_steps": 2.5},
                {"enabled": "yes"}, {"tool": "invented"}, {"provider_id": 5}, {"surprise": 1}, "on"):
        with pytest.raises(ValueError):
            clean(bad)


def test_nothing_runs_when_desktop_actions_are_off(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click")], enabled=False)
    for call in (lambda: rig.service.start("open the calculator"), lambda: rig.service.estimate()):
        with pytest.raises(Refused) as err:
            call()
        assert err.value.code == "off" and "Settings" in str(err.value)
    assert untouched(rig) and rig.service.task is None and rig.driver.captures == 0


@pytest.mark.parametrize("config", [
    {"local": True, "paid": False},
    {"base_url": "http://localhost:8080/v1"},
    {"base_url": "http://127.0.0.1:1234/v1"},
    {"base_url": "http://[::1]:8000/v1"},
    {"base_url": "http://0.0.0.0:11434/v1"},
    {"local": True, "api_key": None},  # whatever else is wrong, a local model is what is said
])
def test_a_local_model_is_refused_before_anything_else(tmp_path, config):
    rig = Rig(tmp_path, [reply("toolset_click")], **config)
    for call in (lambda: rig.service.start("x"), lambda: rig.service.estimate()):
        with pytest.raises(Refused) as err:
            call()
        assert err.value.code == "local" and "local model" in str(err.value)
    state = rig.service.status()["providers"][0]
    assert not state["ok"] and state["code"] == "local"
    assert untouched(rig)


def test_the_loopback_check_reads_the_host_not_the_text():
    assert points_at_this_computer("http://127.0.0.2:9/v1") and points_at_this_computer("http://LOCALHOST/v1")
    assert not points_at_this_computer("https://api.anthropic.com/v1")
    assert not points_at_this_computer("https://localhost.example.com/v1")
    assert not points_at_this_computer("https://api.example.com/127.0.0.1")


async def test_a_task_started_as_remote_stops_if_the_provider_turns_into_a_local_one(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), click_reply(2), done_reply()])
    task, events = await play(rig, answers=[lambda task, card: setattr(rig.cfg, "local", True) or "approve"])
    assert task.reason == "error" and "local model never does desktop actions" in task.error
    assert len(rig.inner.payloads) == 1  # the second request was never sent


def test_a_provider_with_no_computer_use_tool_is_refused(tmp_path):
    rig = Rig(tmp_path, [])
    rig.inner.computer_use_adapter = None  # every OpenAI-compatible API, for instance
    with pytest.raises(Refused) as err:
        rig.service.start("x")
    assert err.value.code == "unsupported" and "computer-use tool" in str(err.value)
    assert untouched(rig)


def test_a_provider_with_no_key_is_refused(tmp_path):
    rig = Rig(tmp_path, [], api_key=None)
    with pytest.raises(Refused) as err:
        rig.service.start("x")
    assert err.value.code == "no_key" and untouched(rig)
    with pytest.raises(Refused) as err:
        rig.service.start("x", provider_id="ghost")
    assert err.value.code == "no_provider"


# ---------------------------------------------------------------- the paid-call guard, spending limits, privacy
async def test_the_guard_refuses_when_paid_requests_are_not_allowed(tmp_path):
    rig = Rig(tmp_path, [click_reply(1)], allow_paid=False)
    with pytest.raises(Refused) as err:
        rig.service.start("x")
    assert err.value.code == "paid" and "may bill your account" in str(err.value) and untouched(rig)
    with pytest.raises(ProviderError, match="may bill your account"):  # the guard itself, whoever asks
        await rig.guard.send_raw({"model": "m"})
    assert rig.inner.payloads == []
    assert [c["status"] for c in rig.store.calls()] == ["blocked"]


async def test_screenshots_are_not_sent_when_the_privacy_setting_forbids_it(tmp_path):
    rig = Rig(tmp_path, [click_reply(1)], share_files=False)
    with pytest.raises(Refused) as err:
        rig.service.start("x")
    assert err.value.code == "privacy" and "not allowed to receive your files" in str(err.value)
    assert "screenshots" in str(err.value) and untouched(rig)
    with pytest.raises(ProviderError, match="screenshots"):
        await rig.guard.send_raw({"model": "m", "messages": [{"role": "user", "content": "an image"}]})
    assert rig.inner.payloads == [] and rig.store.calls()[0]["status"] == "blocked"


def test_the_monthly_limit_is_respected(tmp_path):
    rig = Rig(tmp_path, [], limits={"monthly_tokens": 100})
    rig.store.log_call(provider_id="claude", provider="Claude", status="ok", tokens_in=500)
    with pytest.raises(Refused) as err:
        rig.service.start("x")
    assert err.value.code == "limit" and "monthly limit is reached" in str(err.value) and untouched(rig)


@pytest.mark.parametrize("change, message", [
    (lambda rig: setattr(rig.cfg, "share_files", False), "not allowed to receive your files"),
    (lambda rig: setattr(rig.cfg, "allow_paid", False), "may bill your account"),
    (lambda rig: rig.settings.update(enabled=False), "turned off in Settings"),
])
async def test_the_rules_are_checked_at_every_step_not_only_at_the_start(tmp_path, change, message):
    rig = Rig(tmp_path, [click_reply(1), click_reply(2), done_reply()])
    task, events = await play(rig, answers=[lambda task, card: change(rig) or "approve"])
    assert task.reason == "error" and message in task.error and message in of_type(events, "desktop_error")[0]["message"]
    assert len(rig.inner.payloads) == 1 and len(rig.driver.calls) == 1  # the approved click happened, nothing after it
    assert events[-1]["type"] == "desktop_done" and events[-1]["reason"] == "error"


# ---------------------------------------------------------------- cost estimate before starting
def test_the_cost_is_estimated_before_anything_is_sent(tmp_path):
    rig = Rig(tmp_path, [], max_steps=10, limits={"price_in": 3.0, "price_out": 15.0})
    est = rig.service.estimate()
    assert est["calls"] == 11 and est["max_steps"] == 10 and est["provider"] == "Claude" and est["priced"]
    assert est["tool"] == "computer_toolset_20260801" and est["overhead_tokens"] == 4500
    assert est["cost"] == pytest.approx(call_cost(rig.limits, est["tokens_in"], est["tokens_out"]))
    assert est["tokens_in"] > 11 * 4500  # every request carries the tool definition and all screenshots so far
    assert rig.service.estimate(max_steps=3)["tokens_in"] < est["tokens_in"]
    assert rig.service.estimate(max_steps=50)["max_steps"] == 10  # the setting is the ceiling
    assert untouched(rig)


def test_an_estimate_without_prices_says_so_instead_of_inventing_a_cost(tmp_path):
    est = Rig(tmp_path, []).service.estimate()
    assert est["cost"] is None and est["priced"] is False and est["tokens_in"] > 0


# ---------------------------------------------------------------- approval
async def test_every_action_waits_for_the_users_approval(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")])
    seen = []

    def check(task, card):
        seen.append(list(rig.driver.calls))  # what was done when the card appeared
        assert card["action"] == {"name": "left_click", "x": 512, "y": 742}
        assert card["summary"] == "left click at (512, 742)" and card["step"] == 1
        assert card["region"]["points"] == [{"x": 512, "y": 742}] and card["shot"] == 1
        assert card["auto"] is False and card["sensitive"] is None and card["masked"] is False
        assert card["note"] == "I will click the search box." and card["id"] in rig.broker.pending
        return "approve"

    task, events = await play(rig, answers=[check])
    assert seen == [[]]  # nothing had happened yet
    assert rig.driver.calls == [("click", 512, 742, "left", 1, ())]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "desktop_start" and kinds[-1] == "desktop_done"
    assert kinds.index("desktop_action") < kinds.index("desktop_resolved") < kinds.index("desktop_result")
    done = events[-1]
    assert (done["reason"], done["steps"], done["text"]) == ("finished", 1, "Done: the calculator shows 42.")
    assert done["usage"] == {"input": 12200, "output": 120, "calls": 2} and done["cost"] is None
    assert rig.broker.pending == {} and rig.driver.closed and not task.running


async def test_a_card_nobody_answers_ends_the_task_and_does_nothing(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")])
    rig.broker.timeout_s = 0.05
    task, events = await play(rig, answers=[lambda task, card: None])
    assert task.reason == "timeout" and rig.driver.calls == [] and len(rig.inner.payloads) == 1
    assert of_type(events, "desktop_resolved")[0]["decision"] == "timeout"
    assert task.actions[0]["decision"] == "timeout" and task.actions[0]["ok"] is False


async def test_a_denied_action_is_not_done_and_the_model_is_told(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")])
    task, events = await play(rig, answers=["deny"])
    assert rig.driver.calls == [] and task.reason == "finished"
    assert of_type(events, "desktop_result")[0] == {"type": "desktop_result", "id": events[2]["id"], "ok": False,
                                                    "message": "denied"}
    block = rig.inner.payloads[1]["messages"][-1]["content"][0]
    assert block["is_error"] is True and "did not approve" in block["content"][0]["text"]
    assert task.actions[0]["decision"] == "deny"


async def test_the_model_reads_its_own_screen_after_each_action(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")])
    await play(rig)
    first, second = rig.inner.payloads
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    block = second["messages"][-1]["content"][0]
    assert block["tool_use_id"] == "toolu_01WkoTUvSHDzTBu2xnGk8Ep8" and block["toolset_name"] == "computer"
    assert [b["type"] for b in block["content"]] == ["text", "image"] and "is_error" not in block
    assert rig.driver.captures == 2  # before the task and after the click
    assert first["messages"] == second["messages"][:1]  # the history only grows


# ---------------------------------------------------------------- "approve the next N actions"
async def test_a_batch_is_capped_at_five():
    broker = DesktopBroker()
    pending = broker.open("t", "t_1")
    assert broker.resolve("ghost", "approve") is None
    assert broker.resolve("t_1", "approve_batch", 999) == Decision("batch", MAX_BATCH) and MAX_BATCH == 5
    assert await broker.wait(pending) == Decision("batch", 5)
    assert broker.resolve("t_1", "approve") is None  # answered once, gone
    broker.open("t", "t_2")
    assert broker.resolve("t_2", "approve_batch", 1) == Decision("approve")  # a batch of one is an approval
    broker.open("t", "t_3")
    with pytest.raises(ValueError):
        broker.resolve("t_3", "always_allow")  # there is no "always allow" for the desktop
    slow = DesktopBroker(timeout_s=0.01)
    assert await slow.wait(slow.open("t", "t_4")) == Decision("timeout")
    broker.cancel("t")
    assert broker.pending == {}


async def test_approving_the_next_actions_covers_five_and_then_asks_again(tmp_path):
    rig = Rig(tmp_path, [click_reply(n) for n in range(1, 9)] + [done_reply()])
    task, events = await play(rig, answers=[("approve_batch", 99), "approve", "approve", "approve"])
    cards = of_type(events, "desktop_action")
    assert [c["auto"] for c in cards] == [False, True, True, True, True, False, False, False]
    assert of_type(events, "desktop_resolved")[0] == {"type": "desktop_resolved", "id": cards[0]["id"],
                                                      "decision": "batch", "n": 5, "left": 4}
    assert [r["decision"] for r in of_type(events, "desktop_resolved")][1:5] == ["auto"] * 4
    assert len(rig.driver.calls) == 8 and task.reason == "finished"
    assert [a["decision"] for a in task.actions] == ["batch", "auto", "auto", "auto", "auto", "approve", "approve",
                                                     "approve"]
    assert all(a["ok"] for a in task.actions)


@pytest.mark.parametrize("second, kind", [
    ("toolset_sensitive_send", "send"),  # the model tagged it
    ("toolset_spanish_words", "delete"),  # SPIKE read "Eliminar" / "borrar" itself
    ("toolset_type_password", "password"),
    ("toolset_enter", "submit"),
])
async def test_sensitive_actions_always_ask_even_inside_a_batch(tmp_path, second, kind):
    rig = Rig(tmp_path, [click_reply(1), reply(second), click_reply(3), click_reply(4), done_reply()])
    task, events = await play(rig, answers=[("approve_batch", 5), "approve", "approve", "approve"])
    cards = of_type(events, "desktop_action")
    assert [c["auto"] for c in cards] == [False, False, False, False]
    assert cards[1]["sensitive"]["kind"] == kind and cards[1]["sensitive"]["reason"]
    assert cards[0]["sensitive"] is None and cards[2]["sensitive"] is None
    assert [r["left"] for r in of_type(events, "desktop_resolved")][:2] == [4, 0]  # a card that asks ends the batch
    assert len(rig.driver.calls) == 4 and task.actions[1]["sensitive"] == kind


async def test_a_batch_approval_given_to_a_sensitive_action_covers_only_that_action(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_sensitive_send"), click_reply(2), click_reply(3), done_reply()])
    task, events = await play(rig, answers=[("approve_batch", 5)])
    assert [c["auto"] for c in of_type(events, "desktop_action")] == [False, False, False]
    assert of_type(events, "desktop_resolved")[0]["decision"] == "approve"


async def test_a_password_is_masked_everywhere_but_the_keyboard(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_type_password"), done_reply()])
    task, events = await play(rig)
    card = of_type(events, "desktop_action")[0]
    assert card["masked"] is True and card["sensitive"]["kind"] == "password" and card["action"]["chars"] == 14
    assert "text" not in card["action"] and "hunter2" not in card["summary"]
    assert rig.driver.calls == [("type", "hunter2-secret")]  # approved, so it is typed
    kept = json.dumps([events, task.record()])
    assert "hunter2" not in kept


async def test_a_password_field_the_driver_can_see_always_asks(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), action_reply(2, "type", "I will write the greeting.", text="hola"), done_reply()],
              driver=FakeDriver(secure=True))
    task, events = await play(rig, answers=[("approve_batch", 5)])
    cards = of_type(events, "desktop_action")
    assert cards[1]["auto"] is False and cards[1]["masked"] and cards[1]["sensitive"]["kind"] == "password"
    assert "hola" not in json.dumps([events, task.record()]) and rig.driver.calls[-1] == ("type", "hola")
    (tmp_path / "plain").mkdir()
    plain = Rig(tmp_path / "plain", [action_reply(1, "type", "I will write the greeting.", text="hola"), done_reply()],
                driver=FakeDriver(secure=False))
    cards = of_type((await play(plain))[1], "desktop_action")
    assert cards[0]["sensitive"] is None and cards[0]["action"]["text"] == "hola"


# ---------------------------------------------------------------- stop
async def test_stop_while_a_card_waits_does_nothing_on_the_screen(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")])
    task, events = await play(rig, answers=[lambda task, card: task.stop()])
    assert task.reason == "stopped" and events[-1]["reason"] == "stopped"
    assert rig.driver.calls == [] and len(rig.inner.payloads) == 1 and rig.broker.pending == {}


async def test_the_stop_button_on_a_card_ends_the_task(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")])
    task, events = await play(rig, answers=["stop"])
    assert task.reason == "stopped" and rig.driver.calls == [] and task.actions[0]["decision"] == "stop"


async def test_stop_while_the_provider_is_still_answering(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click")])
    rig.inner.gate = asyncio.Event()  # the request is in flight and never finishes
    task, events = rig.service.start("open the calculator"), []

    async def drive():
        async for ev in task.run():
            events.append(ev)

    runner = asyncio.create_task(drive())
    await asyncio.wait_for(rig.inner.arrived.wait(), 5)
    task.stop()
    await asyncio.wait_for(runner, 5)
    assert events[-1]["reason"] == "stopped" and rig.inner.cancelled and rig.driver.calls == []


async def test_stop_between_two_steps_sends_no_further_request(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), click_reply(2), done_reply()])
    task, events = rig.service.start("x"), []
    async for ev in task.run():
        events.append(ev)
        if ev["type"] == "desktop_action":
            rig.broker.resolve(ev["id"], "approve")
        elif ev["type"] == "desktop_result":
            task.stop()
    assert events[-1]["reason"] == "stopped" and len(rig.driver.calls) == 1 and len(rig.inner.payloads) == 1


async def test_a_page_that_goes_away_leaves_nothing_running(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), done_reply()])
    task = rig.service.start("x")
    stream = task.run()
    async for ev in stream:
        if ev["type"] == "desktop_action":
            break
    await stream.aclose()  # the browser closed the connection while the card was waiting
    assert not task.running and rig.broker.pending == {} and rig.driver.closed and rig.driver.calls == []
    assert not rig.service.busy()


# ---------------------------------------------------------------- limits of a task
async def test_a_task_never_takes_more_steps_than_its_cap(tmp_path):
    rig = Rig(tmp_path, [click_reply(n) for n in range(1, 8)], max_steps=3)
    task, events = await play(rig)
    assert task.steps == 3 and task.reason == "step_limit" and events[-1]["reason"] == "step_limit"
    assert len(rig.driver.calls) == 3 and len(rig.inner.payloads) == 3  # no request after the last step


async def test_the_hard_cap_holds_whatever_the_setting_says(tmp_path):
    rig = Rig(tmp_path, [])
    rig.settings["max_steps"] = 10_000  # not reachable through the API; the loop does not trust it
    assert rig.service.start("x").max_steps == HARD_MAX_STEPS == 50


async def test_the_cap_is_kept_inside_one_turn_with_several_actions(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_batch")], max_steps=2)
    task, events = await play(rig)
    assert task.steps == 2 and task.reason == "step_limit"
    assert [call[0] for call in rig.driver.calls] == ["click", "type"]  # the third call (a screenshot) did not run


async def test_screenshots_the_model_asks_for_need_no_card_but_count(tmp_path):
    rig = Rig(tmp_path, [action_reply(1, "screenshot"), action_reply(2, "cursor_position"),
                         action_reply(3, "wait", duration=2), action_reply(4, "screenshot")], max_steps=4)
    task, events = await play(rig)
    assert of_type(events, "desktop_action") == [] and len(of_type(events, "desktop_step")) == 4
    assert task.steps == 4 and task.reason == "step_limit" and rig.driver.calls == []
    texts = [b["content"][0].get("text") for p in rig.inner.payloads[1:] for b in p["messages"][-1]["content"]]
    assert "X=10,Y=20" in texts and "OK" in texts


async def test_only_one_task_runs_at_a_time(tmp_path):
    rig = Rig(tmp_path, [click_reply(1)])
    first = rig.service.start("a")
    with pytest.raises(Refused) as err:
        rig.service.start("b")
    assert err.value.code == "busy" and rig.service.status()["running"] and rig.service.status()["task"] == first.id
    first.started -= 3600  # a task whose events nobody ever read does not hold the place for ever
    assert not rig.service.busy() and rig.service.start("c").goal == "c"


# ---------------------------------------------------------------- what is sent and what is done
async def test_what_the_model_is_sent_follows_the_documented_shape(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_done")])
    await play(rig, goal="open the calculator")
    payload, = rig.inner.payloads
    assert payload["tools"][0]["type"] == "computer_toolset_20260801" and "name" not in payload["tools"][0]
    assert rig.inner.betas == [[]] and payload["tool_choice"]["disable_parallel_tool_use"] is True
    first = payload["messages"][0]
    assert [b["type"] for b in first["content"]] == ["image", "text"] and first["content"][1]["text"] == "open the calculator"
    assert png_size(base64.b64decode(first["content"][0]["source"]["data"])) == (1024, 768)


async def test_older_models_get_the_older_tool_with_its_beta_header(tmp_path):
    rig = Rig(tmp_path, [reply("legacy_click"), done_reply()], model="claude-opus-4-8")
    await play(rig)
    tool = rig.inner.payloads[0]["tools"][0]
    assert tool == {"type": "computer_20251124", "name": "computer", "display_width_px": 1024, "display_height_px": 768}
    assert rig.inner.betas == [["computer-use-2025-11-24"]] * 2
    assert rig.driver.calls == [("click", 500, 300, "left", 1, ())]
    assert "toolset_name" not in rig.inner.payloads[1]["messages"][-1]["content"][0]


async def test_the_models_points_become_screen_points_and_modifiers_are_held(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_thinking_and_text"), done_reply()], driver=FakeDriver(screen=(2048, 1536)))
    await play(rig)
    width, height = fit_size(2048, 1536)
    sent = base64.b64decode(rig.inner.payloads[0]["messages"][0]["content"][0]["source"]["data"])
    assert png_size(sent) == (width, height) and (width, height) != (2048, 1536)  # the model sees the shrunk screen
    assert rig.driver.calls == [("click", round(500 * 2048 / width), round(300 * 1536 / height), "left", 1, ("shift",))]


async def test_the_history_is_kept_exactly_as_the_provider_sent_it(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_thinking_and_text"), done_reply()])
    await play(rig)
    assistant = rig.inner.payloads[1]["messages"][1]
    assert assistant == {"role": "assistant", "content": reply("toolset_thinking_and_text")["content"]}
    assert assistant["content"][0]["signature"] == "EqQBCkYIBBgCKkDexample"


@pytest.mark.parametrize("answer", ["deny", "fail"])
async def test_every_action_of_a_turn_is_answered_and_the_rest_are_not_run(tmp_path, answer):
    driver = FakeDriver(fail={"click": "the click failed (xdotool): BadWindow"} if answer == "fail" else None)
    rig = Rig(tmp_path, [reply("toolset_batch"), done_reply()], driver=driver)
    task, events = await play(rig, answers=["deny" if answer == "deny" else "approve"])
    results = rig.inner.payloads[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == BATCH_IDS and all(r["toolset_name"] == "computer" for r in results)
    assert all(r["is_error"] for r in results)
    assert "BadWindow" in results[0]["content"][0]["text"] or "did not approve" in results[0]["content"][0]["text"]
    assert [r["content"][0]["text"] for r in results[1:]] == [
        "Not executed: an earlier computer action in this turn failed."] * 2
    assert [c[0] for c in rig.driver.calls] == []  # nothing after the first action ran
    assert len(of_type(events, "desktop_action")) == 1  # and no card was shown for what did not run


async def test_actions_the_driver_cannot_do_come_back_as_a_message_not_as_a_guess(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_zoom"), action_reply(2, "frobnicate"), action_reply(3, "left_click"),
                         done_reply()])
    task, events = await play(rig)
    assert of_type(events, "desktop_action")[0]["action"] == {"name": "left_click"}  # a click where the mouse is
    texts = [p["messages"][-1]["content"][0]["content"][0]["text"] for p in rig.inner.payloads[1:3]]
    assert "'zoom' is not available on this computer" in texts[0] and "unknown action 'frobnicate'" in texts[1]
    assert [a["decision"] for a in task.actions] == ["refused", "refused", "approve"]


async def test_scrolling_and_dragging_reach_the_driver(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_scroll"), action_reply(2, "left_click_drag", start_coordinate=[10, 20],
                                                              coordinate=[30, 40]), done_reply()])
    await play(rig)
    assert rig.driver.calls == [("scroll", 500, 400, "down", 3, ()), ("drag", 10, 20, 30, 40, ())]


async def test_a_driver_error_goes_back_to_the_model_and_the_task_goes_on(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), done_reply()], driver=FakeDriver(fail={"click": "the click failed (xdotool): x"}))
    task, events = await play(rig)
    assert of_type(events, "desktop_result")[0]["ok"] is False and task.reason == "finished"
    assert task.actions[0]["ok"] is False and "failed" in task.actions[0]["result"]


# ---------------------------------------------------------------- how a task ends
@pytest.mark.parametrize("script, reason", [
    ([reply("toolset_refusal")], "refused"),
    ([{**done_reply("cut"), "stop_reason": "max_tokens"}], "cut"),
    ([done_reply("All done.")], "finished"),
])
async def test_the_reasons_a_task_ends(tmp_path, script, reason):
    task, events = await play(Rig(tmp_path, script))
    assert task.reason == reason == events[-1]["reason"] and events[-1]["steps"] == 0


async def test_a_provider_that_fails_ends_the_task_with_its_message(tmp_path):
    rig = Rig(tmp_path, [])  # the fake has no answer left: a connection that fails
    task, events = await play(rig)
    assert task.reason == "error" and "no more answers" in task.error
    assert events[-1]["error"] == task.error and of_type(events, "desktop_error")
    assert [c["status"] for c in rig.store.calls()] == ["error"]
    (tmp_path / "bad").mkdir()
    bad = Rig(tmp_path / "bad", [reply("error")])
    assert "does not support tool types" in (await play(bad))[0].error


async def test_a_screen_that_cannot_be_captured_ends_before_asking_the_provider(tmp_path):
    class Blind(FakeDriver):
        def capture(self, width, height):
            return b"not a png"

    rig = Rig(tmp_path, [click_reply(1)], driver=Blind())
    task, events = await play(rig)
    assert task.reason == "error" and "could not be captured" in task.error and rig.inner.payloads == []


# ---------------------------------------------------------------- what is kept
async def test_the_record_has_every_action_and_decision_but_no_images(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), action_reply(2, "key", text="Return"), click_reply(3), done_reply("All done.")])
    task, events = await play(rig, answers=["approve", "approve", "deny"])
    record = task.record()
    assert [(a["action"], a["decision"], a["ok"]) for a in record["actions"]] == [
        ("left_click", "approve", True), ("key", "approve", True), ("left_click", "deny", False)]
    assert record["actions"][1]["sensitive"] == "submit" and record["actions"][1]["key"] == "Return"
    assert record["reason"] == "finished" and record["final"] == "All done." and record["screenshots"] == "not kept"
    assert record["screen"] == {"width": 1024, "height": 768} and record["provider"] == "Claude"
    assert "iVBORw0KGgo" not in json.dumps([record, events])  # the start of every PNG, as base64
    assert not (tmp_path / "desktop").exists() and task.kept == []


async def test_screenshots_stay_in_memory_and_only_the_last_few(tmp_path):
    rig = Rig(tmp_path, [click_reply(n) for n in range(1, 16)] + [done_reply()])
    task, _ = await play(rig, answers=[("approve_batch", 5)] * 3)
    assert task.shot_count == 16 and len(task.shots) == 12 and max(task.shots) == 16


async def test_screenshots_are_written_only_when_the_user_asked_and_go_with_the_chat(tmp_path):
    rig = Rig(tmp_path, [click_reply(1), done_reply()])
    task, events = await play(rig, keep_shots=True, conversation_id="chat1")
    folder = tmp_path / "desktop" / "chat1" / task.id
    assert sorted(p.name for p in folder.iterdir()) == ["shot-001.png", "shot-002.png"]
    assert png_size((folder / "shot-001.png").read_bytes()) == (1024, 768)
    assert events[-1]["shots"] == ["shot-001.png", "shot-002.png"] and task.record()["screenshots"] == "kept"
    kept = rig.service.kept_files("chat1")
    assert sorted(kept) == [f"desktop/{task.id}/shot-001.png", f"desktop/{task.id}/shot-002.png"]
    assert rig.service.kept_files("other") == {}
    rig.service.forget("chat1")
    assert not (tmp_path / "desktop" / "chat1").exists() and rig.service.kept_files("chat1") == {}


async def test_usage_is_counted_and_every_step_is_in_the_call_log(tmp_path):
    rig = Rig(tmp_path, [reply("toolset_click"), reply("toolset_done")], limits={"price_in": 3.0, "price_out": 15.0})
    task, events = await play(rig)
    rows = sorted(rig.store.calls(), key=lambda c: c["id"])
    assert [(c["status"], c["detail"], c["tokens_in"], c["tokens_out"], c["local"]) for c in rows] == [
        ("ok", "desktop step", 5200, 90, False), ("ok", "desktop step", 7000, 30, False)]
    assert events[-1]["cost"] == pytest.approx(call_cost(rig.limits, 12200, 120))
    assert sum(c["cost"] for c in rows) == pytest.approx(events[-1]["cost"])


def test_the_status_page_lists_every_provider_with_why_not(tmp_path):
    rig = Rig(tmp_path, [], share_files=False)
    status = rig.service.status()
    assert status["settings"]["enabled"] and status["driver"]["available"] and status["hard_max_steps"] == 50
    assert status["providers"][0]["code"] == "privacy" and not status["providers"][0]["ok"]
    assert status["running"] is False and status["task"] is None
