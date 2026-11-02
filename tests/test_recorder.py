"""Browser recorder and replay for Spike View (A16).

The recorder watches the calls the Playwright connector really ran and keeps them as a JSON script; the replayer runs
a script one step at a time and asks before anything that submits or opens a domain the browser settings do not allow.
Both are tested here against a fake browser backend (results copied from what the real Playwright MCP returns); the
last test drives the real server and Chromium when SPIKE_PLAYWRIGHT_MCP and SPIKE_CHROMIUM point to them."""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import re
import socket
import threading
from pathlib import Path

import pytest

from spike.connectors import recorder, replay
from spike.connectors.manager import ConnectorDef, ConnectorManager, McpTool
from spike.connectors.mcp import CallResult
from spike.connectors.recorder import MAX_STEPS, Recorder, RecorderError, code_targets, looks_secret
from spike.connectors.replay import Replayer, ReplayError
from spike.connectors.scripts import ScriptError, ScriptStore, selector_of, validate
from spike.store.db import Store
from spike.store.secrets import SecretStore
from tests.helpers_view import FakeBackend


# ---------------------------------------------------------------- results as the real Playwright MCP writes them
def ran(code: str, url: str = "https://shop.test/pedido", title: str = "Pedido") -> str:
    return (f"### Ran Playwright code\n```js\n{code}\n```\n### Page\n- Page URL: {url}\n- Page Title: {title}\n"
            "### Snapshot\n- [Snapshot](.playwright-mcp/page-2026-11-02T02-13-03-353Z.yml)\n")


def goto(url: str) -> str:
    return ran(f"await page.goto('{url}');", url)


def role(kind: str, name: str, exact: bool = False) -> dict:
    return {"by": "role", "role": kind, "name": name, "exact": exact}


@pytest.fixture
def store(tmp_path):
    return ScriptStore(tmp_path / "scripts")


@pytest.fixture
def rec(store):
    return Recorder(store)


def feed(rec: Recorder, remote: str, args: dict, text: str = "ok", error: bool = False, connector: str = "playwright"):
    rec.observe(connector, remote, args, text, error)


def steps_of(rec: Recorder) -> list[dict]:
    return rec.stop()["script"]["steps"]


# ---------------------------------------------------------------- reading the code Playwright says it ran
@pytest.mark.parametrize("line,expected", [
    ("await page.getByRole('textbox', { name: 'Nombre' }).fill('Ana');", role("textbox", "Nombre")),
    ("await page.getByRole('button', { name: 'Enviar pedido', exact: true }).click();",
     role("button", "Enviar pedido", True)),
    ("await page.getByRole('button').click();", {"by": "role", "role": "button", "name": "", "exact": False}),
    ("await page.getByLabel('Ciudad MadridBarcelona').selectOption('Barcelona');",
     {"by": "label", "value": "Ciudad MadridBarcelona", "exact": False}),
    ("await page.getByPlaceholder('Buscar').fill('x');", {"by": "placeholder", "value": "Buscar", "exact": False}),
    ("await page.getByText('Más detalles').click();", {"by": "text", "value": "Más detalles", "exact": False}),
    ("await page.getByTestId('buy').click();", {"by": "testid", "value": "buy", "exact": True}),
    ("await page.getByTitle('Cerrar').click();", {"by": "title", "value": "Cerrar", "exact": False}),
    ("await page.getByAltText('Logo').click();", {"by": "alt", "value": "Logo", "exact": False}),
    ("await page.locator('#buy').click();", {"by": "css", "selector": "#buy"}),
    ("await page.locator('input[name=nombre]').fill('Luis');", {"by": "css", "selector": "input[name=nombre]"}),
    ("await page.getByRole('link', { name: 'Ayuda' }).first().click();", {**role("link", "Ayuda"), "nth": 0}),
    ("await page.getByRole('link', { name: 'Ayuda' }).nth(2).click();", {**role("link", "Ayuda"), "nth": 2}),
    ("await page.getByRole('link', { name: 'Ayuda' }).last().click();", {**role("link", "Ayuda"), "nth": -1}),
    (r"await page.getByRole('button', { name: 'It\'s \"ok\" \\ done' }).click();", role("button", 'It\'s "ok" \\ done')),
    ("await page.getByRole('checkbox', { name: 'Acepto' }).check();", role("checkbox", "Acepto")),
    ("await page.getByRole('button', { name: 'Más' }).dblclick();", role("button", "Más")),
])
def test_the_code_playwright_ran_becomes_a_target(line, expected):
    assert code_targets(ran(line)) == [expected]


def test_what_cannot_be_a_single_robust_target_is_marked_so():
    chained = "await page.getByRole('row', { name: 'Ana' }).getByRole('button', { name: 'Borrar' }).click();"
    filtered = "await page.getByRole('row').filter({ hasText: 'Ana' }).getByRole('button').click();"
    by_ref = "await page.locator('aria-ref=e4').click();"
    regex = "await page.getByRole('button', { name: /Enviar/i }).click();"
    for line in (chained, filtered, by_ref, regex):
        assert code_targets(ran(line)) == [{"by": "none"}], line


def test_lines_that_do_not_act_on_an_element_have_no_target():
    text = ran("// Press Tab\nawait page.keyboard.press('Tab');")
    assert code_targets(text) == []
    assert code_targets(goto("https://shop.test/")) == []
    assert code_targets("Error: nothing matched") == []
    assert code_targets("") == []
    two = ran("await page.getByRole('textbox', { name: 'A' }).fill('1');\nawait page.getByLabel('B').fill('2');")
    assert [t["by"] for t in code_targets(two)] == ["role", "label"]


@pytest.mark.parametrize("target,selector", [
    (role("button", "Enviar pedido", True), 'internal:role=button[name="Enviar pedido"s]'),
    (role("textbox", "Nombre"), 'internal:role=textbox[name="Nombre"i]'),
    ({"by": "role", "role": "button", "name": "", "exact": False}, "internal:role=button"),
    ({"by": "label", "value": "Ciudad", "exact": False}, 'internal:label="Ciudad"i'),
    ({"by": "text", "value": "Más", "exact": True}, 'internal:text="Más"s'),
    ({"by": "placeholder", "value": "Buscar", "exact": False}, 'internal:attr=[placeholder="Buscar"i]'),
    ({"by": "title", "value": "Cerrar", "exact": False}, 'internal:attr=[title="Cerrar"i]'),
    ({"by": "alt", "value": "Logo", "exact": True}, 'internal:attr=[alt="Logo"s]'),
    ({"by": "testid", "value": "buy", "exact": True}, 'internal:testid=[data-testid="buy"s]'),
    ({"by": "css", "selector": "#buy"}, "#buy"),
    ({**role("link", "Ayuda"), "nth": 2}, 'internal:role=link[name="Ayuda"i] >> nth=2'),
    ({**role("link", "Ayuda"), "nth": -1}, 'internal:role=link[name="Ayuda"i] >> nth=-1'),
    (role("button", 'say "hi" \\ now'), 'internal:role=button[name="say \\"hi\\" \\\\ now"i]'),
    ({"by": "none"}, None),
])
def test_a_target_is_replayed_with_the_selector_the_browser_tools_understand(target, selector):
    assert selector_of(target) == selector


# ---------------------------------------------------------------- recording
def test_a_form_is_recorded_as_a_script_with_robust_targets(rec):
    rec.start("Pedido")
    feed(rec, "browser_navigate", {"url": "https://shop.test/pedido"}, goto("https://shop.test/pedido"))
    feed(rec, "browser_type", {"element": "Nombre textbox", "target": "e4", "text": "Ana"},
         ran("await page.getByRole('textbox', { name: 'Nombre' }).fill('Ana');"))
    feed(rec, "browser_click", {"element": "Más detalles", "target": "e11"},
         ran("await page.getByRole('button', { name: 'Más detalles' }).click();"))
    feed(rec, "browser_select_option", {"element": "Ciudad", "target": "e8", "values": ["Barcelona"]},
         ran("await page.getByLabel('Ciudad MadridBarcelona').selectOption('Barcelona');"))
    feed(rec, "browser_press_key", {"key": "Tab"}, ran("// Press Tab\nawait page.keyboard.press('Tab');"))
    steps = steps_of(rec)
    assert [s["action"] for s in steps] == ["navigate", "type", "click", "select", "press"]
    assert steps[0]["url"] == "https://shop.test/pedido"
    assert steps[1]["target"] == role("textbox", "Nombre") and steps[1]["text"] == "Ana"
    assert steps[1]["element"] == "Nombre textbox" and "submits" not in steps[1]
    assert steps[2]["target"] == role("button", "Más detalles") and "submits" not in steps[2]
    assert steps[3]["target"]["by"] == "label" and steps[3]["values"] == ["Barcelona"]
    assert steps[4]["key"] == "Tab"


def test_a_selector_the_model_gave_is_kept_when_it_is_not_a_snapshot_reference(rec):
    rec.start("x")
    feed(rec, "browser_click", {"element": "buy", "target": "#buy"}, ran("await page.locator('#buy').click();"))
    feed(rec, "browser_click", {"element": "ref only", "target": "e12"}, "ok")  # no code in the result: no target
    steps = steps_of(rec)
    assert steps[0]["target"] == {"by": "css", "selector": "#buy"}
    assert steps[1]["target"] == {"by": "none"} and steps[1]["element"] == "ref only"


def test_each_submitting_action_is_marked_in_the_script(rec):
    rec.start("x")
    feed(rec, "browser_type", {"element": "Nombre", "target": "e4", "text": "Ana", "submit": True},
         ran("await page.getByRole('textbox', { name: 'Nombre' }).fill('Ana');\nawait page.keyboard.press('Enter');"))
    feed(rec, "browser_press_key", {"key": "Enter"}, ran("await page.keyboard.press('Enter');"))
    feed(rec, "browser_click", {"element": "Enviar pedido button", "target": "e12"},
         ran("await page.getByRole('button', { name: 'Enviar pedido' }).click();"))
    feed(rec, "browser_click", {"target": "e12"}, ran("await page.getByRole('button', { name: 'Siguiente' }).click();"))
    feed(rec, "browser_click", {"element": "Más detalles", "target": "e11"},
         ran("await page.getByRole('button', { name: 'Más detalles' }).click();"))
    assert [bool(s.get("submits")) for s in steps_of(rec)] == [True, True, True, True, False]


def test_a_button_that_changes_the_address_is_treated_as_submitting(rec):
    rec.start("x")
    feed(rec, "browser_navigate", {"url": "https://shop.test/pedido"}, goto("https://shop.test/pedido"))
    feed(rec, "browser_click", {"element": "Siguiente", "target": "e5"},
         ran("await page.getByRole('button', { name: 'Siguiente' }).click();", url="https://shop.test/paso2"))
    feed(rec, "browser_click", {"element": "Ayuda", "target": "e6"},  # a link goes somewhere: that is what it is for
         ran("await page.getByRole('link', { name: 'Ayuda' }).click();", url="https://shop.test/ayuda"))
    feed(rec, "browser_click", {"element": "Más", "target": "e7"},  # only the fragment changes
         ran("await page.getByRole('button', { name: 'Más' }).click();", url="https://shop.test/ayuda#mas"))
    steps = steps_of(rec)
    assert [bool(s.get("submits")) for s in steps] == [False, True, False, False]


@pytest.mark.parametrize("name", ["Password", "Contraseña", "Clave", "PIN", "CVV", "Código de seguridad",
                                  "Security code", "OTP", "API token", "Repite la contraseña", "Número de tarjeta"])
def test_fields_named_like_a_secret_are_recognised(name):
    assert looks_secret(name)


@pytest.mark.parametrize("name", ["Nombre", "Passenger name", "Compass", "Email", "Dirección", "Ciudad", "Pinned posts",
                                  "Buscar", ""])
def test_ordinary_fields_are_not_taken_for_secrets(name):
    assert not looks_secret(name)


def test_what_is_typed_in_a_password_field_is_never_stored(rec, store):
    rec.start("Entrar")
    feed(rec, "browser_type", {"element": "Usuario textbox", "target": "e3", "text": "ana@example.com"},
         ran("await page.getByRole('textbox', { name: 'Usuario' }).fill('ana@example.com');"))
    feed(rec, "browser_type", {"element": "Contraseña textbox", "target": "e4", "text": "hunter2-secreto"},
         ran("await page.getByRole('textbox', { name: 'Contraseña' }).fill('hunter2-secreto');"))
    feed(rec, "browser_type", {"element": "campo", "target": "input[type=password]", "text": "otro-secreto-2"},
         ran("await page.locator('input[type=password]').fill('otro-secreto-2');"))
    feed(rec, "browser_fill_form", {"fields": [
        {"name": "Usuario", "type": "textbox", "target": "e3", "value": "luis"},
        {"name": "Password", "type": "textbox", "target": "e4", "value": "tercer-secreto"}]},
        ran("await page.getByRole('textbox', { name: 'Usuario' }).fill('luis');\n"
            "await page.getByRole('textbox', { name: 'Password' }).fill('tercer-secreto');"))
    during = json.dumps(rec.status(), ensure_ascii=False)
    done = rec.stop()
    steps = done["script"]["steps"]
    assert [s["action"] for s in steps] == ["type"] * 5
    assert [bool(s.get("secret")) for s in steps] == [False, True, True, False, True]
    assert all("text" not in s for s in steps if s.get("secret"))
    assert steps[0]["text"] == "ana@example.com" and steps[3]["text"] == "luis"
    saved = (store.folder / f"{done['id']}.json").read_text(encoding="utf-8")
    for secret in ("hunter2-secreto", "otro-secreto-2", "tercer-secreto"):
        assert secret not in saved and secret not in during and secret not in json.dumps(done, ensure_ascii=False)


def test_keys_pressed_one_by_one_are_not_recorded_so_a_password_typed_that_way_leaks_nothing(rec):
    rec.start("x")
    for key in "hunter2":
        feed(rec, "browser_press_key", {"key": key}, ran(f"await page.keyboard.press('{key}');"))
    feed(rec, "browser_press_key", {"key": "Enter"}, ran("await page.keyboard.press('Enter');"))
    feed(rec, "browser_press_key", {"key": "ArrowDown"}, ran("await page.keyboard.press('ArrowDown');"))
    feed(rec, "browser_press_key", {"key": "Control+a"}, ran("await page.keyboard.press('Control+a');"))
    steps = steps_of(rec)
    assert [s["key"] for s in steps] == ["Enter", "ArrowDown"]  # a shortcut with a modifier may type nothing, but is not kept
    assert not any(s.get("key") == "h" for s in steps)


def test_failed_calls_other_tools_and_other_connectors_are_not_recorded(rec):
    rec.start("x")
    feed(rec, "browser_click", {"element": "x", "target": "e1"}, "### Error\nRef e1 not found", error=True)
    feed(rec, "browser_snapshot", {})
    feed(rec, "browser_take_screenshot", {})
    feed(rec, "browser_hover", {"element": "x", "target": "e2"})
    feed(rec, "browser_evaluate", {"function": "() => document.cookie"})
    feed(rec, "browser_file_upload", {"paths": ["/home/ana/secreto.pdf"]})
    feed(rec, "browser_navigate", {"url": "https://shop.test/"}, goto("https://shop.test/"), connector="memory")
    feed(rec, "browser_navigate", {"url": "javascript:alert(1)"}, "ok")
    feed(rec, "browser_navigate", {"url": "file:///etc/passwd"}, "ok")
    feed(rec, "browser_navigate", {"url": "about:blank"}, "ok")
    status = rec.status()
    assert status["steps"] == []
    assert status["ignored"] == {"browser_hover": 1, "browser_evaluate": 1, "browser_file_upload": 1}


def test_nothing_is_recorded_unless_recording(rec):
    feed(rec, "browser_navigate", {"url": "https://shop.test/"}, goto("https://shop.test/"))
    assert rec.status()["recording"] is False and rec.status()["steps"] == []
    with pytest.raises(RecorderError):
        rec.stop()


def test_credentials_in_an_address_are_dropped(rec):
    rec.start("x")
    feed(rec, "browser_navigate", {"url": "https://ana:clave-secreta@shop.test/x?a=1"}, "ok")
    step = steps_of(rec)[0]
    assert step["url"] == "https://shop.test/x?a=1"


def test_the_recording_has_a_limit_and_says_so(rec, monkeypatch):
    monkeypatch.setattr(recorder, "MAX_STEPS", 3)
    rec.start("x")
    for i in range(5):
        feed(rec, "browser_navigate", {"url": f"https://shop.test/{i}"}, "ok")
    status = rec.status()
    assert len(status["steps"]) == 3 and status["truncated"] is True
    done = rec.stop()
    assert len(done["script"]["steps"]) == 3 and done["truncated"] is True
    assert MAX_STEPS >= 100


def test_one_recording_at_a_time_and_cancel_keeps_nothing(rec, store):
    rec.start("uno")
    with pytest.raises(RecorderError):
        rec.start("dos")
    feed(rec, "browser_navigate", {"url": "https://shop.test/"}, "ok")
    rec.cancel()
    assert rec.status()["recording"] is False and store.list() == []
    rec.start("tres")
    done = rec.stop()  # nothing recorded: nothing saved
    assert done["id"] is None and store.list() == []


def test_stopping_saves_the_script_where_the_user_can_find_it(rec, store):
    rec.start("Mi pedido")
    feed(rec, "browser_navigate", {"url": "https://shop.test/"}, goto("https://shop.test/"))
    done = rec.stop()
    assert done["id"] == "mi-pedido" and done["name"] == "Mi pedido"
    assert [s["id"] for s in store.list()] == ["mi-pedido"]
    assert store.get("mi-pedido")["steps"][0]["url"] == "https://shop.test/"
    assert rec.status()["recording"] is False


# ---------------------------------------------------------------- the script file
def test_scripts_are_plain_utf8_json_files_named_from_their_title(store):
    script = {"name": "Pedido ñandú / ../../etc", "steps": [{"action": "navigate", "url": "https://shop.test/"},
                                                           {"action": "click", "target": role("button", "Más"),
                                                            "element": "Más"}]}
    sid = store.save(script)
    assert sid == "pedido-nandu-etc"
    raw = (store.folder / f"{sid}.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["format"] == "spike-view-script" and data["version"] == 1 and "Más" in raw  # not \u escaped
    assert store.save({**script, "name": "Pedido ñandú / ../../etc"}) == "pedido-nandu-etc-2"
    assert store.save({**script, "name": ""}) == "guion"
    assert {p.name for p in store.folder.iterdir()} == {"pedido-nandu-etc.json", "pedido-nandu-etc-2.json", "guion.json"}
    assert [s["id"] for s in store.list()] == sorted(s["id"] for s in store.list())
    assert store.list()[0]["steps"] == 2


def test_a_script_id_cannot_leave_the_folder(store):
    store.save({"name": "ok", "steps": [{"action": "navigate", "url": "https://shop.test/"}]})
    (store.folder.parent / "outside.json").write_text("{}", encoding="utf-8")
    for bad in ("../outside", "..", "a/b", "/etc/passwd", "ok.json", "", "A B", "x" * 200):
        with pytest.raises(ScriptError):
            store.get(bad)
        assert store.delete(bad) is False
    assert store.get("ok")["name"] == "ok"
    assert store.delete("ok") is True and store.delete("ok") is False


def test_a_broken_or_edited_script_is_reported_not_trusted(store):
    store.folder.mkdir(parents=True)
    (store.folder / "roto.json").write_text("{not json", encoding="utf-8")
    (store.folder / "raro.json").write_text(json.dumps({"format": "spike-view-script", "version": 1, "name": "raro",
                                                        "steps": [{"action": "evaluate", "code": "x"}]}),
                                            encoding="utf-8")
    listing = {s["id"]: s for s in store.list()}
    assert listing["roto"]["error"] and listing["raro"]["error"]
    for sid in ("roto", "raro"):
        with pytest.raises(ScriptError):
            store.get(sid)


@pytest.mark.parametrize("step", [
    {"action": "evaluate", "code": "alert(1)"},
    {"action": "navigate"},
    {"action": "navigate", "url": "file:///etc/passwd"},
    {"action": "click"},
    {"action": "click", "target": {"by": "role", "role": "button; drop", "name": "x"}},
    {"action": "click", "target": {"by": "regex", "value": "x"}},
    {"action": "type", "target": role("textbox", "x"), "text": 5},
    {"action": "type", "target": role("textbox", "x"), "secret": True, "text": "no"},
    {"action": "select", "target": role("combobox", "x"), "values": "Madrid"},
    {"action": "press", "key": "a"},
    {"action": "press", "key": "Enter" * 20},
    "click",
])
def test_a_step_that_is_not_a_known_safe_action_is_refused(step):
    with pytest.raises(ScriptError):
        validate({"name": "x", "steps": [step]})


def test_a_script_has_limits():
    with pytest.raises(ScriptError):
        validate({"name": "x", "steps": [{"action": "navigate", "url": "https://shop.test/"}] * (MAX_STEPS + 1)})
    with pytest.raises(ScriptError):
        validate({"name": "x", "steps": []})
    with pytest.raises(ScriptError):
        validate({"name": "x" * 500, "steps": [{"action": "navigate", "url": "https://a.test/"}]})
    with pytest.raises(ScriptError):
        validate({"name": "x", "format": "other", "steps": [{"action": "navigate", "url": "https://a.test/"}]})
    with pytest.raises(ScriptError):
        validate([])


def test_a_step_can_be_turned_into_one_that_asks_for_its_text(store):
    sid = store.save({"name": "x", "steps": [{"action": "type", "target": role("textbox", "Código"), "text": "1234"},
                                             {"action": "click", "target": role("button", "Ok")}]})
    changed = store.make_secret(sid, 0)
    assert changed["steps"][0]["secret"] is True and "text" not in changed["steps"][0]
    assert "1234" not in (store.folder / f"{sid}.json").read_text(encoding="utf-8")
    for bad in (1, 7, -1):
        with pytest.raises(ScriptError):
            store.make_secret(sid, bad)  # a click has no text; the others do not exist


# ---------------------------------------------------------------- the connector hook
class FakeClient:
    def __init__(self, text="ok", error=False):
        self.text, self.error = text, error
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return CallResult(text=self.text, is_error=self.error, raw={})


def connector(cid="playwright"):
    return ConnectorDef(id=cid, name="Playwright", transport="stdio", command="x")


async def test_a_connector_tool_tells_its_observers_what_it_ran():
    seen = []

    def observer(*args):
        seen.append(args)

    def broken(*args):
        raise RuntimeError("boom")

    client = FakeClient(goto("https://shop.test/"))
    tool = McpTool(connector(), client, {"name": "browser_navigate", "inputSchema": {"type": "object"}},
                   "mcp__playwright__browser_navigate", "allow", observers=[broken, observer])
    result = await tool.run({"url": "https://shop.test/"})
    assert result.ok and seen == [("playwright", "browser_navigate", {"url": "https://shop.test/"},
                                   client.text, False)]
    failing = McpTool(connector(), FakeClient("### Error", error=True), {"name": "browser_click"},
                      "mcp__playwright__browser_click", "allow", observers=[observer])
    assert (await failing.run({"target": "e1"})).ok is False and seen[-1][4] is True


async def test_the_recorder_sees_a_real_tool_call_through_the_hook(rec):
    rec.start("x")
    client = FakeClient(goto("https://shop.test/"))
    tool = McpTool(connector(), client, {"name": "browser_navigate"}, "mcp__playwright__browser_navigate", "allow",
                   observers=[rec.observe])
    await tool.run({"url": "https://shop.test/"})
    assert steps_of(rec) == [{"action": "navigate", "url": "https://shop.test/"}]


def test_the_manager_hands_its_observers_to_the_tools_it_starts(tmp_path):
    manager = ConnectorManager(Store(tmp_path / "s.db"), SecretStore(tmp_path / "k.json"), tmp_path, tmp_path / "c",
                               catalog=[connector()])
    assert manager.observers == []
    tool = manager.make_tool(connector(), FakeClient(), {"name": "browser_click"}, "mcp__playwright__browser_click",
                             "ask")
    assert tool.observers is manager.observers


# ---------------------------------------------------------------- replay (the fake browser is tests/helpers_view.py)
def make_script(store, steps, name="demo"):
    return store.save({"name": name, "steps": steps})


NAV = {"action": "navigate", "url": "https://shop.test/pedido"}
TYPE = {"action": "type", "target": role("textbox", "Nombre"), "element": "Nombre textbox", "text": "Ana"}
MORE = {"action": "click", "target": role("button", "Más detalles"), "element": "Más detalles"}
SEND = {"action": "click", "target": role("button", "Enviar pedido"), "element": "Enviar pedido button", "submits": True}


async def drive(replayer: Replayer, answers=(), timeout=5.0):
    """Answer each question in turn (a decision, or (decision, value)); return the questions seen and the last status."""
    answers, seen = list(answers), []

    async def loop():
        while True:
            status = replayer.status()
            if status["state"] in ("done", "stopped", "error"):
                return status
            q = status["question"]
            if q and q["id"] not in [s["id"] for s in seen]:
                seen.append(q)
                decision = answers.pop(0)
                decision, value = decision if isinstance(decision, tuple) else (decision, None)
                if decision == "stop":
                    assert replayer.stop()
                else:
                    assert replayer.answer(q["id"], decision, value)
            await asyncio.sleep(0.001)

    return seen, await asyncio.wait_for(loop(), timeout)


@pytest.fixture
def backend():
    return FakeBackend(domains={"shop.test": "allow"})


def replayer_for(backend, store):
    return Replayer(backend, store)


# ---------------------------------------------------------------- replay
async def test_a_script_replays_step_by_step_without_asking_for_what_cannot_submit(backend, store):
    sid = make_script(store, [NAV, TYPE, MORE, {"action": "select", "target": {"by": "label", "value": "Ciudad",
                                                                                "exact": False},
                                                "element": "Ciudad", "values": ["Barcelona"]},
                              {"action": "press", "key": "Tab"}])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer)
    assert seen == [] and status["state"] == "done"
    assert backend.calls == [
        ("browser_navigate", {"url": "https://shop.test/pedido"}),
        ("browser_type", {"element": "Nombre textbox", "target": 'internal:role=textbox[name="Nombre"i]',
                          "text": "Ana"}),
        ("browser_click", {"element": "Más detalles", "target": 'internal:role=button[name="Más detalles"i]'}),
        ("browser_select_option", {"element": "Ciudad", "target": 'internal:label="Ciudad"i',
                                   "values": ["Barcelona"]}),
        ("browser_press_key", {"key": "Tab"})]
    assert [s["status"] for s in status["steps"]] == ["done"] * 5 and status["index"] == 5 and status["total"] == 5


async def test_every_submitting_action_asks_first_and_runs_only_when_allowed(backend, store):
    submit_type = {**TYPE, "submit": True, "submits": True}
    enter = {"action": "press", "key": "Enter", "submits": True}
    sid = make_script(store, [NAV, submit_type, enter, SEND])
    replayer = replayer_for(backend, store)
    asked_with = []

    original = replayer.status

    def spy():
        status = original()
        if status["question"]:
            asked_with.append((status["question"]["id"], len(backend.calls)))
        return status

    replayer.status = spy
    replayer.start(sid)
    seen, status = await drive(replayer, ["allow_once", "allow_once", "skip"])
    assert [q["code"] for q in seen] == ["type_submit", "enter", "click_submit"]
    assert [q["step"] for q in seen] == [1, 2, 3]
    assert all(q["kind"] == "submit" and q["options"] == ["allow_once", "skip", "stop"] for q in seen)
    assert [n for _, n in asked_with[:1]] == [1]  # the first question came with only the navigation done
    assert [c[0] for c in backend.calls] == ["browser_navigate", "browser_type", "browser_press_key"]  # not the skipped one
    assert [s["status"] for s in status["steps"]] == ["done", "done", "done", "skipped"]


async def test_a_submit_is_asked_even_when_the_recording_did_not_flag_it(backend, store):
    """An edited script, or one recorded by an older version, still goes through the guard's own rules."""
    plain = {"action": "click", "target": role("button", "Pagar"), "element": "Pagar"}
    sid = make_script(store, [plain, {"action": "press", "key": "Enter"}])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, ["allow_once", "allow_once"])
    assert [q["code"] for q in seen] == ["click_submit", "enter"] and status["state"] == "done"


async def test_a_submit_can_never_be_allowed_for_good(backend, store):
    sid = make_script(store, [SEND])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    status = await wait_for_question(replayer)
    q = status["question"]
    assert "allow_always" not in q["options"] and "allow_domain" not in q["options"]
    assert replayer.answer(q["id"], "allow_always") is False
    assert replayer.answer(q["id"], "allow_domain") is False
    assert backend.calls == []
    assert replayer.answer(q["id"], "stop") is True


async def wait_for_question(replayer, timeout=5.0):
    async def loop():
        while True:
            status = replayer.status()
            if status["question"] or status["state"] in ("done", "stopped", "error"):
                return status
            await asyncio.sleep(0.001)

    return await asyncio.wait_for(loop(), timeout)


async def test_a_domain_the_browser_settings_do_not_allow_is_asked_about_first(store):
    backend = FakeBackend(domains={"shop.test": "allow", "bloqueado.test": "deny"})
    other = {"action": "navigate", "url": "https://www.nuevo.test/a"}
    again = {"action": "navigate", "url": "https://nuevo.test/b"}
    blocked = {"action": "navigate", "url": "https://sub.bloqueado.test/x"}
    sid = make_script(store, [NAV, other, again, blocked, {"action": "navigate", "url": "https://shop.test/fin"}])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, ["allow_domain", "skip"])
    assert [(q["kind"], q["code"], q["domain"]) for q in seen] == [("domain", "open", "nuevo.test"),
                                                                    ("blocked", "blocked", "bloqueado.test")]
    assert seen[0]["options"] == ["allow_once", "allow_domain", "skip", "stop"]
    assert seen[1]["options"] == ["skip", "stop"]  # a blocked domain is never opened from here
    assert backend.allowed == ["nuevo.test"]
    urls = [a["url"] for _, a in backend.calls]
    assert urls == ["https://shop.test/pedido", "https://www.nuevo.test/a", "https://nuevo.test/b",
                    "https://shop.test/fin"]
    assert status["state"] == "done"


async def test_allowing_a_domain_once_asks_again_the_next_time(store):
    backend = FakeBackend()
    sid = make_script(store, [{"action": "navigate", "url": "https://nuevo.test/a"},
                              {"action": "navigate", "url": "https://nuevo.test/b"}])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, ["allow_once", "allow_once"])
    assert len(seen) == 2 and backend.allowed == [] and len(backend.calls) == 2


async def test_an_unknown_domain_opens_without_asking_when_the_user_chose_so(store):
    backend = FakeBackend(unknown="allow")
    sid = make_script(store, [{"action": "navigate", "url": "https://nuevo.test/a"}])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer)
    assert seen == [] and status["state"] == "done"


async def test_only_web_pages_can_be_opened_by_a_script(backend, store):
    store.folder.mkdir(parents=True)
    (store.folder / "mala.json").write_text(json.dumps({"format": "spike-view-script", "version": 1, "name": "mala",
                                                        "steps": [{"action": "navigate", "url": "file:///etc/passwd"}]}),
                                            encoding="utf-8")
    replayer = replayer_for(backend, store)
    with pytest.raises(ReplayError):  # refused when loading it, before any step runs
        replayer.start("mala")
    assert backend.calls == []


async def test_stop_ends_the_replay_while_it_waits_for_an_answer(backend, store):
    sid = make_script(store, [NAV, SEND, MORE])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    status = await wait_for_question(replayer)
    assert status["state"] == "waiting" and status["question"]["step"] == 1
    assert replayer.stop() is True
    await asyncio.sleep(0.02)
    status = replayer.status()
    assert status["state"] == "stopped" and status["question"] is None
    assert [c[0] for c in backend.calls] == ["browser_navigate"]
    assert [s["status"] for s in status["steps"]] == ["done", "pending", "pending"]
    assert replayer.stop() is False  # nothing is running now


async def test_stop_ends_the_replay_between_steps_and_during_one(store):
    backend = FakeBackend(domains={"shop.test": "allow"}, delay=0.05)
    sid = make_script(store, [NAV, MORE, MORE, MORE, MORE])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    await asyncio.sleep(0.07)
    assert replayer.stop() is True
    await asyncio.sleep(0.2)
    status = replayer.status()
    assert status["state"] == "stopped" and len(backend.calls) < 5
    assert "running" not in [s["status"] for s in status["steps"]]


async def test_step_mode_waits_for_the_user_before_each_step(backend, store):
    sid = make_script(store, [NAV, MORE])
    replayer = replayer_for(backend, store)
    replayer.start(sid, mode="step")
    seen, status = await drive(replayer, ["next", "next"])
    assert [(q["kind"], q["step"], q["options"]) for q in seen] == [("step", 0, ["next", "stop"]),
                                                                    ("step", 1, ["next", "stop"])]
    assert status["state"] == "done" and len(backend.calls) == 2
    replayer.start(sid, mode="step")
    seen, status = await drive(replayer, ["next", "stop"])
    assert status["state"] == "stopped" and len(backend.calls) == 3


async def test_a_secret_step_asks_for_its_text_and_keeps_it_nowhere(backend, store):
    secret = {"action": "type", "target": role("textbox", "Contraseña"), "element": "Contraseña", "secret": True}
    sid = make_script(store, [secret, {**secret, "submit": True, "submits": True}, secret])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, [("provide", "mi-clave-privada"), ("provide", "otra-clave"),
                                          "allow_once", ("provide", "")])
    assert [(q["kind"], q["step"]) for q in seen] == [("secret", 0), ("secret", 1), ("submit", 1), ("secret", 2)]
    assert seen[0]["options"] == ["provide", "skip", "stop"]
    assert backend.calls[0][1]["text"] == "mi-clave-privada" and backend.calls[1][1]["text"] == "otra-clave"
    assert len(backend.calls) == 2 and [s["status"] for s in status["steps"]] == ["done", "done", "skipped"]  # empty: skipped
    dump = json.dumps(status) + json.dumps(seen) + repr(vars(replayer)) + repr(replayer.status())
    assert "mi-clave-privada" not in dump and "otra-clave" not in dump


async def test_a_secret_cannot_be_provided_in_a_question_that_does_not_ask_for_one(backend, store):
    sid = make_script(store, [SEND])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    q = (await wait_for_question(replayer))["question"]
    assert replayer.answer(q["id"], "provide", "x") is False and replayer.answer("nope", "allow_once") is False
    assert replayer.answer(q["id"], "banana") is False
    replayer.stop()


async def test_a_failed_step_offers_retry_skip_or_stop(store):
    backend = FakeBackend(domains={"shop.test": "allow"})
    sid = make_script(store, [MORE, MORE, MORE])
    outcomes = iter([(False, "Error: role=button does not match any elements"), (True, "ok"), (False, "Error: again"),
                     (True, "ok")])

    async def flaky(remote, args):
        backend.calls.append((remote, args))
        return next(outcomes)

    backend.call = flaky
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, ["retry", "skip"])
    assert [(q["kind"], q["step"], q["options"]) for q in seen] == [("failed", 0, ["retry", "skip", "stop"]),
                                                                    ("failed", 1, ["retry", "skip", "stop"])]
    assert "does not match" in seen[0]["detail"] and status["state"] == "done"
    assert [s["status"] for s in status["steps"]] == ["done", "skipped", "done"] and len(backend.calls) == 4


async def test_a_target_that_could_not_be_recorded_cannot_be_replayed(backend, store):
    sid = make_script(store, [{"action": "click", "target": {"by": "none"}, "element": "algo raro"}])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, ["skip"])
    assert seen[0]["kind"] == "failed" and seen[0]["code"] == "no_target" and seen[0]["options"] == ["skip", "stop"]
    assert backend.calls == []


async def test_a_tool_the_user_turned_off_is_not_used_by_a_replay(store):
    backend = FakeBackend(domains={"shop.test": "allow"}, blocked={"browser_click"})
    sid = make_script(store, [NAV, MORE])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    seen, status = await drive(replayer, ["skip"])
    assert [(q["kind"], q["code"]) for q in seen] == [("blocked", "tool_blocked")]
    assert [c[0] for c in backend.calls] == ["browser_navigate"]


async def test_one_replay_at_a_time_and_only_when_the_browser_runs(backend, store):
    sid = make_script(store, [NAV, SEND])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    with pytest.raises(ReplayError) as busy:
        replayer.start(sid)
    assert busy.value.code == "busy"
    replayer.stop()
    await asyncio.sleep(0.01)
    with pytest.raises(ReplayError) as missing:
        replayer.start("nada")
    assert missing.value.code == "not_found"
    off = Replayer(FakeBackend(running=False), store)
    with pytest.raises(ReplayError) as not_running:
        off.start(sid)
    assert not_running.value.code == "off"
    with pytest.raises(ReplayError):
        replayer.start(sid, mode="turbo")


async def test_a_question_nobody_answers_ends_the_replay(backend, store, monkeypatch):
    monkeypatch.setattr(replay, "ANSWER_TIMEOUT_S", 0.05)
    sid = make_script(store, [NAV, SEND])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    await asyncio.sleep(0.3)
    status = replayer.status()
    assert status["state"] == "stopped" and status["reason"] == "no_answer" and len(backend.calls) == 1


async def test_a_step_that_raises_stops_the_replay_with_a_reason(backend, store):
    async def boom(remote, args):
        raise RuntimeError("the browser went away")

    backend.call = boom
    sid = make_script(store, [NAV])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    _, status = await drive(replayer, ["stop"])  # it asks first: retry, skip or stop
    assert status["state"] == "stopped"


async def test_the_status_shows_each_step_in_a_fixed_shape(backend, store):
    sid = make_script(store, [NAV, TYPE])
    replayer = replayer_for(backend, store)
    replayer.start(sid)
    _, status = await drive(replayer)
    row = status["steps"][1]
    assert row == {"n": 1, "action": "type", "name": "Nombre", "text": "Ana", "status": "done"}
    assert set(status) == {"state", "reason", "mode", "script", "index", "total", "steps", "question"}


# ---------------------------------------------------------------- the real Playwright MCP server and Chromium
PLAYWRIGHT = os.environ.get("SPIKE_PLAYWRIGHT_MCP")
CHROMIUM = os.environ.get("SPIKE_CHROMIUM")


class Shop(http.server.BaseHTTPRequestHandler):
    posts: list[str] = []
    page = """<!doctype html><html><head><title>Pedido</title></head><body>
<form method="post" action="/enviar"><label>Nombre <input name="nombre"></label>
<label>Clave <input type="password" name="clave"></label>
<label>Ciudad <select name="ciudad"><option value="m">Madrid</option><option value="b">Barcelona</option></select></label>
<button type="button">Más detalles</button><button>Enviar pedido</button></form></body></html>"""

    def do_GET(self):
        body = self.page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        Shop.posts.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"<p>Gracias</p>")

    def log_message(self, *args):
        pass


@pytest.mark.skipif(not (PLAYWRIGHT and CHROMIUM and Path(PLAYWRIGHT).exists() and Path(CHROMIUM).exists()),
                    reason="needs SPIKE_PLAYWRIGHT_MCP and SPIKE_CHROMIUM")
async def test_a_real_browser_session_is_recorded_and_replayed_asking_before_the_submit(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Shop)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    Shop.posts = []
    definition = ConnectorDef(id="playwright", name="Playwright browser", description="", transport="stdio",
                              command=PLAYWRIGHT, args=["--headless", "--isolated", "--no-sandbox",
                                                        "--executable-path", CHROMIUM])
    (tmp_path / "ws").mkdir()
    manager = ConnectorManager(Store(tmp_path / "spike.db"), SecretStore(tmp_path / "s.json"), tmp_path / "ws",
                               tmp_path / "c", catalog=[definition])
    manager.set_domain("127.0.0.1", "allow")
    manager._save_config("playwright", policy="allow")
    recorder_ = Recorder(ScriptStore(tmp_path / "scripts"))
    manager.observers.append(recorder_.observe)
    conn = await manager.start("playwright")
    assert conn.status == "running", conn.error
    url = f"http://127.0.0.1:{port}/"
    try:
        recorder_.start("Pedido real")
        tools = conn.by_remote
        await tools["browser_navigate"].run({"url": url})
        snap = await tools["browser_snapshot"].run({})
        by_ref = {m.group(1): m.group(2) for m in re.finditer(r'(?:textbox|combobox|button) "([^"]+)"[^\n]*\[ref=(\w+)\]',
                                                              snap.content)}
        await tools["browser_type"].run({"element": "Nombre", "target": by_ref["Nombre"], "text": "Ana"})
        await tools["browser_type"].run({"element": "Clave", "target": by_ref["Clave"], "text": "secreto-real"})
        await tools["browser_select_option"].run({"element": "Ciudad", "target": by_ref["Ciudad"],
                                                  "values": ["Barcelona"]})
        await tools["browser_click"].run({"element": "Más detalles", "target": by_ref["Más detalles"]})
        done = recorder_.stop()
        script = done["script"]
        assert [s["action"] for s in script["steps"]] == ["navigate", "type", "type", "select", "click"]
        assert script["steps"][2].get("secret") is True and "secreto-real" not in json.dumps(script)
        assert all(s["target"]["by"] != "none" for s in script["steps"][1:]), script
        # a submitting step is added by hand, as an edited script would have it
        edited = {**script, "steps": [*script["steps"], {"action": "click", "target": role("button", "Enviar pedido"),
                                                         "element": "Enviar pedido"}]}
        sid = recorder_.store.save({**edited, "name": "real"})

        class Live(FakeBackend):
            async def call(self, remote, args):
                result = await conn.by_remote[remote].client.call_tool(remote, args)
                return (not result.is_error), result.text

        live = Live(domains={"127.0.0.1": "allow"})
        replayer = Replayer(live, recorder_.store)
        replayer.start(sid)
        seen, status = await drive(replayer, [("provide", "clave-de-replay"), "allow_once"], timeout=60)
        assert [q["kind"] for q in seen] == ["secret", "submit"] and status["state"] == "done", status
        assert Shop.posts == ["nombre=Ana&clave=clave-de-replay&ciudad=b"]
        replayer.start(sid)  # again, and this time the user refuses the submit
        seen, status = await drive(replayer, [("provide", "otra"), "skip"], timeout=60)
        assert status["state"] == "done" and len(Shop.posts) == 1
    finally:
        await manager.close_all()
        server.shutdown()
