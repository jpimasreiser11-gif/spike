"""A21 Device Lab: a local web app is opened in phone, tablet and desktop profiles in the headless Chromium SPIKE
already drives, and each profile reports its screenshot, console errors, failed requests, horizontal overflow, small
tap targets and small text, with a pass or fail and the reason.

Proved here: the host rule (this computer only, unless the user names the host), the profiles and the user's own,
the permission card of the tool and the approvals of the routes, the optional Android path with a FAKE `adb` (nothing
real is started: its calls are recorded), and, in a real headless Chromium, each planted problem on the profiles where it
belongs plus a clean page that passes. The browser tests use SPIKE_CHROMIUM (or Playwright's / an installed Chrome) and
skip when there is none; nothing is downloaded and the pages never leave 127.0.0.1. NOT proved: that a real phone or
tablet behaves like its emulated profile, or anything about a real Android device (the fake adb only shows the calls)."""

from __future__ import annotations

import asyncio
import base64
import http.server
import json
import os
import re
import shlex
import struct
import threading
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from spike.agent.loop import AgentRun, run_agent
from spike.core.types import Message
from spike.dev import device_lab as lab
from spike.dev.device_lab import (
    AndroidRequest,
    DeviceLab,
    DeviceLabError,
    check_target,
    parse_custom,
    pick_profiles,
)
from spike.dev.diagnostics import diagnostic_tools
from spike.dev.tools import dev_tools
from spike.server.app import create_app
from spike.skills.validation import known_tools
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Workspace
from tests import helpers_programs as fakes
from tests.helpers import ScriptedProvider, call, text
from tests.test_server import env as env

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PHONES = {"small-phone", "large-phone"}
ALL = [p.id for p in lab.PROFILES]


# ================================================================== profiles and the host rule (no browser)
def test_the_built_in_profiles_are_six_generic_device_classes():
    assert ALL == ["small-phone", "large-phone", "tablet-portrait", "tablet-landscape", "laptop", "desktop"]
    by = {p.id: p for p in lab.PROFILES}
    assert (by["small-phone"].width, by["small-phone"].height) == (360, 640)
    assert (by["tablet-portrait"].width, by["tablet-portrait"].height) == (768, 1024)
    assert (by["tablet-landscape"].width, by["tablet-landscape"].height) == (1024, 768)
    assert by["desktop"].width == 1920 and by["laptop"].width == 1366
    assert all(by[i].touch and by[i].mobile and by[i].scale > 1 for i in ("small-phone", "large-phone", "tablet-portrait"))
    assert not any(by[i].touch or by[i].mobile for i in ("laptop", "desktop"))
    assert "Mobile" in by["small-phone"].user_agent and "Tablet" in by["tablet-portrait"].user_agent
    # a generic class of device: no vendor, browser or system brand in anything shipped for the profiles
    shipped = " ".join(f"{p.id} {p.name} {p.user_agent}" for p in lab.PROFILES).lower() + lab.CHECKS.lower()
    for brand in ("mozilla", "chrome", "safari", "android", "iphone", "ipad", "apple", "samsung", "google", "windows",
                  "macintosh", "firefox", "webkit", "galaxy", "huawei", "xiaomi", "microsoft"):
        assert re.search(rf"\b{brand}\b", shipped) is None, brand


def test_a_custom_profile_is_validated_and_gets_its_own_id():
    custom = parse_custom({"name": "Folding phone", "width": 280, "height": 653, "scale": 2.5, "touch": True}, set())
    assert (custom.id, custom.kind, custom.width, custom.height, custom.scale) == ("custom-folding-phone", "custom", 280, 653, 2.5)
    assert custom.touch and custom.mobile and not custom.builtin and custom.user_agent.startswith("SpikeDeviceLab/")
    assert parse_custom({"name": "Folding phone", "width": 280, "height": 653}, {custom.id}).id == "custom-folding-phone-2"
    assert parse_custom({"name": "tv", "width": 1280, "height": 720, "mobile": False, "touch": True}, set()).mobile is False
    chosen = pick_profiles(["laptop", "laptop"], [{"name": "Narrow", "width": 320, "height": 480}])
    assert [p.id for p in chosen] == ["laptop", "custom-narrow"]
    assert [p.id for p in pick_profiles(None, None)] == ALL
    assert [p.id for p in pick_profiles(None, [{"name": "Only", "width": 300, "height": 300}])] == ["custom-only"]
    for bad in ("x", {"width": 300, "height": 300}, {"name": "", "width": 300, "height": 300},
                {"name": "a", "width": 50, "height": 300}, {"name": "a", "width": 300, "height": 9000},
                {"name": "a", "width": "300", "height": 300}, {"name": "a", "width": True, "height": 300},
                {"name": "a", "width": 300.5, "height": 300}, {"name": "a", "width": 300, "height": 300, "scale": 9},
                {"name": "a", "width": 300, "height": 300, "touch": "yes"},
                {"name": "a", "width": 300, "height": 300, "user_agent": "café"},
                {"name": "a", "width": 300, "height": 300, "user_agent": "x" * 301}, {"name": "x" * 41, "width": 300, "height": 300}):
        with pytest.raises(DeviceLabError) as err:
            parse_custom(bad, set())
        assert err.value.code == "device_lab_custom", bad
    for bad_ids in (["nope"], "small-phone", [3]):
        with pytest.raises(DeviceLabError) as err:
            pick_profiles(bad_ids, None)
        assert err.value.code == "device_lab_profile"
    with pytest.raises(DeviceLabError):
        pick_profiles([], [{"name": f"p{i}", "width": 300, "height": 300} for i in range(lab.MAX_CUSTOM + 1)])


@pytest.mark.parametrize("url,host", [
    ("http://localhost:3000", "localhost"), ("http://127.0.0.1:8000/a?b=1#c", "127.0.0.1"),
    ("https://[::1]:5173/", "::1"), ("http://127.0.0.2/", "127.0.0.2"), ("http://app.localhost:8080/", "app.localhost"),
    ("HTTP://LOCALHOST./x", "localhost"), ("  http://localhost/  ", "localhost")])
def test_this_computer_is_accepted(url, host):
    target = check_target(url)
    assert target.host == host and not any(c in target.shown for c in "?#")


@pytest.mark.parametrize("url", [
    "http://example.com", "https://example.com:3000/", "http://192.168.1.5:3000", "http://10.0.0.1/", "http://169.254.169.254/latest",
    "http://0.0.0.0:8000", "http://localhost.evil.test/", "http://127.0.0.1.evil.test/", "http://evil.test/localhost",
    "http://localhost@evil.test/", "http://user:pass@localhost/", "http://2130706433/", "http://[::ffff:8.8.8.8]/",
    "file:///etc/passwd", "javascript:alert(1)", "data:text/html,hi", "ftp://localhost/", "chrome://settings", "localhost:3000",
    "//localhost/", "", "   ", "http://", "http://local host/", "http://localhost/\nHost: evil.test", "http://localhost:99999/", None, 5])
def test_every_other_address_is_refused(url):
    with pytest.raises(DeviceLabError) as err:
        check_target(url)
    assert err.value.code in {"device_lab_url", "device_lab_host"}


def test_the_user_can_name_a_host_for_one_run_and_only_that_host():
    target = check_target("http://staging.example.test:8080/x?token=1", ["Staging.Example.test"])
    assert target.host == "staging.example.test" and "token" not in target.shown
    assert target.shown == "http://staging.example.test:8080/x"
    for other in ("http://sub.staging.example.test/", "http://example.test/", "http://other.test/"):
        with pytest.raises(DeviceLabError) as err:
            check_target(other, ["staging.example.test"])
        assert err.value.code == "device_lab_host" and "no está en este ordenador" in err.value.message
    for bad in (["*.example.test"], ["https://x.test"], ["x.test:80"], ["x.test/path"], ["a b"], [""], "x.test", [5],
                [f"h{i}.test" for i in range(lab.MAX_ALLOW + 1)]):
        with pytest.raises(DeviceLabError) as err:
            check_target("http://localhost/", bad)
        assert err.value.code == "device_lab_hosts", bad
    assert lab.parse_allow_hosts(["10.1.2.3", "[::1]", "10.1.2.3"]) == ("10.1.2.3", "::1")


def test_the_browser_may_reach_only_this_computer_and_the_named_hosts():
    allowed = frozenset({"app.test"})
    for url in ("http://localhost:4000/api", "http://127.0.0.1:9/x", "ws://[::1]:5173/", "http://app.test/x", "data:image/png;base64,AA",
                "blob:http://localhost/1", "about:blank"):
        assert lab.reachable(url, allowed), url
    for url in ("http://other.test/x", "https://fonts.example.test/a.css", "http://192.168.0.1/", "http://169.254.169.254/",
                "wss://other.test/socket", "http://localhost.other.test/"):
        assert not lab.reachable(url, allowed), url
    assert lab.public_url("https://user:pw@host.test:8443/a/b?token=SECRET#frag") == "https://host.test:8443/a/b"


# ================================================================== the tool: permissions and registration
def test_the_tool_always_asks_once_and_refuses_other_hosts_before_asking(monkeypatch):
    monkeypatch.setattr(lab, "playwright_missing", lambda: False)
    tool = DeviceLab()
    assert tool.name == "device_lab" and tool.risk == "execute" and tool.default_policy == "ask"
    review = tool.review({"url": "http://localhost:5173/"})
    assert (review.policy, review.once, review.code) == ("ask", True, "device_lab")
    policy, again = PermissionBroker({"device_lab": "allow"}).policy_for_call(tool, {"url": "http://localhost:5173/"})
    assert policy == "ask" and again.once  # an "allow" policy never skips the question
    refused = tool.review({"url": "https://example.com/"})
    assert refused.policy == "deny" and refused.code == "device_lab_host" and "example.com" in refused.reason
    assert tool.review({"url": "ftp://localhost/"}).policy == "deny"
    assert tool.review({"url": "http://localhost/", "profiles": ["watch"]}).policy == "deny"
    named = tool.review({"url": "https://staging.example.test/", "allow_hosts": ["staging.example.test"]})
    assert (named.policy, named.code, named.once) == ("ask", "device_lab_host", True)
    phone = tool.review({"url": "http://localhost/", "android": True})
    assert (phone.policy, phone.code, phone.once) == ("ask", "device_lab_android", True) and "adb" in phone.reason
    assert tool.review({"url": "http://localhost/", "android": True, "android_serial": "a b; rm"}).policy == "deny"
    monkeypatch.setattr(lab, "playwright_missing", lambda: True)
    assert (tool.review({"url": "http://localhost/"}).policy, tool.review({"url": "http://localhost/"}).code) == (
        "deny", "device_lab_browser")


def test_the_tool_is_registered_for_the_dev_specialist_and_the_dev_terminal(tmp_path):
    ws = Workspace(tmp_path)
    assert "device_lab" in {t.name for t in diagnostic_tools(ws)} and "device_lab" in {t.name for t in dev_tools(ws)}
    assert "device_lab" in known_tools()
    catalog = load_catalog()
    assert "device_lab" in catalog.specialists["code"].tools and "device_lab" in catalog.specialists["core"].tools
    queue = object()
    assert next(t for t in diagnostic_tools(ws, jobs=queue) if t.name == "device_lab").job_queue is queue


async def test_a_refused_address_never_starts_a_browser(monkeypatch):
    def no_browser(*a, **k):
        raise AssertionError("a browser was started")

    monkeypatch.setattr("spike.motion.render.launch", no_browser)
    for args in ({"url": "https://example.com/"}, {"url": "http://localhost/", "profiles": ["watch"]}, {"url": ""}):
        result = await DeviceLab().run(args)
        assert not result.ok and result.content.startswith("error:")
    with pytest.raises(DeviceLabError):
        await lab.run_device_lab("http://169.254.169.254/")


async def test_no_browser_is_said_plainly_and_nothing_is_downloaded(monkeypatch):
    monkeypatch.setattr(lab, "playwright_missing", lambda: True)
    with pytest.raises(DeviceLabError) as err:
        await lab.run_device_lab("http://localhost:3000/")
    assert err.value.code == "device_lab_browser" and "SPIKE_CHROMIUM" in err.value.message
    result = await DeviceLab().run({"url": "http://localhost:3000/"})
    assert not result.ok and "playwright install chromium" in result.content


async def test_a_browser_that_cannot_start_is_a_clear_refusal_not_a_crash(monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setenv("SPIKE_CHROMIUM", "/nonexistent/spike-test-chromium")
    with pytest.raises(DeviceLabError) as err:
        await lab.run_device_lab("http://localhost:3000/", profiles=["desktop"])
    assert err.value.code == "device_lab_browser" and "spike-test-chromium" in err.value.message
    result = await DeviceLab().run({"url": "http://localhost:3000/", "profiles": ["desktop"]})
    assert not result.ok and result.content.startswith("error:")


async def drive(tool_call, decision="allow_once", tools=None):
    """One model turn that calls the tool, through the real agent loop and a broker that answers with `decision`."""
    broker = PermissionBroker({})
    events = []
    async for ev in run_agent(ScriptedProvider([tool_call, text("done")]), [Message(role="user", content="run Device Lab")],
                              tools=tools or [DeviceLab()], broker=broker, run=AgentRun()):
        events.append(ev)
        if ev["type"] == "permission_request":
            asyncio.get_running_loop().call_soon(broker.resolve, ev["id"], decision)
    return events


async def test_a_denied_call_runs_nothing_and_the_card_names_the_reason(monkeypatch):
    monkeypatch.setattr("spike.motion.render.launch", lambda *a, **k: pytest.fail("a browser was started"))
    events = await drive(call("device_lab", {"url": "http://localhost:5173/"}), "deny")
    ask = next(e for e in events if e["type"] == "permission_request")
    assert ask["tool"] == "device_lab" and ask["risk"] == "execute" and ask["code"] == "device_lab" and ask["once"]
    assert ask["arguments"] == {"url": "http://localhost:5173/"}
    result = next(e for e in events if e["type"] == "tool_result")
    assert not result["ok"] and "denied" in result["content"]


# ================================================================== Android with a fake adb (no browser)
ADB = fakes.COMMON + r"""
mode = MODE
args = list(ARGV)
serial = ""
if args[:1] == ["-s"]:
    serial, args = args[1], args[2:]
if args[:1] == ["devices"]:
    print("* daemon not running; starting now at tcp:5037")
    print("* daemon started successfully")
    print("List of devices attached")
    if mode != "none":
        if mode != "unauthorized":
            print("emulator-5554          device product:sdk_x86 model:Test_Emulator device:emu transport_id:1")
        print("R58M12ABCDE            unauthorized usb:1-1 transport_id:2")
        print("0123456789ABCDEF       offline transport_id:3")
    sys.exit(0)
if args[:1] == ["reverse"]:
    sys.exit(1 if mode == "noreverse" else 0)
if args[:1] == ["shell"]:
    print("Starting: Intent { act=android.intent.action.VIEW }")
    sys.exit(1 if mode == "noopen" else 0)
if args[:2] == ["exec-out", "screencap"]:
    sys.stdout.buffer.write(b"not a picture" if mode == "badshot" else PNG)
    sys.stdout.flush()
    sys.exit(0)
sys.exit(2)
"""


@pytest.fixture
def adb(tmp_path, monkeypatch):
    """A PATH with a fake adb in front: it lists an emulator, an unauthorized phone and an offline one."""
    folder = tmp_path / "adb-bin"
    fakes.install(folder, "adb", ADB)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    return folder


@pytest.fixture
def no_adb(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


def steps(report):
    return [(s["step"], s["ok"]) for s in report["steps"]]


async def test_without_adb_nothing_is_listed_and_nothing_runs(no_adb):
    assert await lab.list_android() == {"found": False, "devices": [], "error": ""}
    shot = await lab.android_shot(AndroidRequest(), check_target("http://localhost:3000/"))
    assert shot["status"] == "no_adb" and shot["screenshot"] == "" and shot["steps"] == []


async def test_a_device_in_adb_devices_is_shown_without_any_screenshot(adb):
    listing = await lab.list_android()
    assert listing["found"] and listing["error"] == ""
    assert [(d["serial"], d["state"], d["usable"], d["kind"]) for d in listing["devices"]] == [
        ("emulator-5554", "device", True, "emulator"), ("R58M12ABCDE", "unauthorized", False, "device"),
        ("0123456789ABCDEF", "offline", False, "device")]
    assert listing["devices"][0]["model"] == "Test_Emulator"
    assert [c["argv"] for c in fakes.calls(adb, "adb")] == [["devices", "-l"]]  # looking is all it did


async def test_android_screenshot_opens_the_url_after_reversing_the_port_and_cleans_up(adb):
    # on Windows the fake is a .cmd file, where & is a command separator: the quoting test uses what cmd.exe leaves alone
    url = "http://localhost:3000/a_b" if os.name == "nt" else "http://localhost:3000/a;b?x=1&y=$(id)"
    shot = await lab.android_shot(AndroidRequest(wait_s=0), check_target(url))
    assert shot["status"] == "ok" and shot["serial"] == "emulator-5554" and shot["opened"] and shot["kind"] == "emulator"
    assert base64.b64decode(shot["screenshot"].split(",", 1)[1]).startswith(PNG_SIGNATURE)
    assert steps(shot) == [("reverse", True), ("open", True), ("screenshot", True), ("unreverse", True)]
    argv = [c["argv"] for c in fakes.calls(adb, "adb")]
    assert argv[1:] == [
        ["-s", "emulator-5554", "reverse", "tcp:3000", "tcp:3000"],
        ["-s", "emulator-5554", "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
         shlex.quote(url)],  # quoted for the device's shell: nothing in the URL can run there
        ["-s", "emulator-5554", "exec-out", "screencap", "-p"],
        ["-s", "emulator-5554", "reverse", "--remove", "tcp:3000"]]


async def test_android_without_opening_only_takes_the_screenshot_and_other_serials_are_left_alone(adb):
    shot = await lab.android_shot(AndroidRequest(open_url=False), check_target("http://localhost/"))
    assert shot["status"] == "ok" and not shot["opened"] and steps(shot) == [("screenshot", True)]
    assert [c["argv"][-3:] for c in fakes.calls(adb, "adb")[1:]] == [["exec-out", "screencap", "-p"]]
    other = await lab.android_shot(AndroidRequest(serial="R58M12ABCDE"), check_target("http://localhost/"))
    assert other["status"] == "no_device"  # unauthorized: not usable, nothing was sent to it
    assert not any("R58M12ABCDE" in c["argv"] for c in fakes.calls(adb, "adb"))


@pytest.mark.parametrize("mode,status,error", [("none", "no_device", ""), ("unauthorized", "no_device", ""),
                                               ("badshot", "error", "no_screenshot")])
async def test_android_problems_are_reported_not_hidden(adb, monkeypatch, mode, status, error):
    monkeypatch.setenv("FAKE_MODE", mode)
    shot = await lab.android_shot(AndroidRequest(wait_s=0), check_target("http://127.0.0.1:8000/"))
    assert shot["status"] == status and shot["error"] == error and shot["screenshot"] == ""


async def test_failed_steps_are_listed_and_the_port_is_still_released(adb, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "noopen")
    shot = await lab.android_shot(AndroidRequest(wait_s=0), check_target("http://localhost:3000/"))
    assert shot["status"] == "ok" and not shot["opened"]
    assert steps(shot) == [("reverse", True), ("open", False), ("screenshot", True), ("unreverse", True)]
    monkeypatch.setenv("FAKE_MODE", "noreverse")
    assert ("reverse", False) in steps(await lab.android_shot(AndroidRequest(wait_s=0), check_target("http://localhost:3000/")))
    # a page on another host needs no reverse of this computer's ports
    away = await lab.android_shot(AndroidRequest(wait_s=0), check_target("https://stage.example.test/", ["stage.example.test"]))
    assert [s for s, _ in steps(away) if "reverse" in s] == []


def test_android_serials_cannot_carry_arguments():
    assert lab.SERIAL.fullmatch("emulator-5554") and lab.SERIAL.fullmatch("192.168.1.9:5555")
    for bad in ("a b", "x;rm", "$(id)", "-s", "-e", "", "a" * 81, "\u00fcn\u00ef"):
        assert not lab.SERIAL.fullmatch(bad), bad


async def test_the_tool_asks_before_any_adb_step_and_a_denial_runs_no_adb(adb, monkeypatch):
    monkeypatch.setattr("spike.motion.render.launch", lambda *a, **k: pytest.fail("a browser was started"))
    events = await drive(call("device_lab", {"url": "http://localhost:3000/", "android": True}), "deny")
    ask = next(e for e in events if e["type"] == "permission_request")
    assert ask["code"] == "device_lab_android" and ask["arguments"]["android"] is True
    assert fakes.calls(adb, "adb") == []  # not even `adb devices`


# ================================================================== the routes (no browser)
@pytest.fixture
def client(env):
    _, state, _ = env
    state.jobs.ram_floor = 0  # the tests are not about how much memory is free
    return TestClient(create_app(state), client=("127.0.0.1", 50000))


@pytest.fixture
def stub_run(monkeypatch):
    """The run replaced by a stub that records its arguments: the routes' rules are tested without a browser."""
    seen = []

    async def fake(url, **kwargs):
        seen.append((url, kwargs))
        return {"kind": "device_lab", "url": url, "profiles": [], "android": None}

    monkeypatch.setattr(lab, "run_device_lab", fake)
    return seen


def test_status_lists_the_profiles_and_runs_no_program(client, monkeypatch, adb):
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("a program was run"))
    monkeypatch.setattr("asyncio.create_subprocess_exec", lambda *a, **k: pytest.fail("a program was run"))
    status = client.get("/api/device-lab").json()
    assert [p["id"] for p in status["profiles"]] == ALL and status["adb"] is True
    assert status["limits"] == {"min_tap": 24, "min_font": 12, "custom": lab.MAX_CUSTOM}
    assert fakes.calls(adb, "adb") == []


def test_listing_android_devices_runs_adb_devices_and_nothing_else(client, adb):
    listing = client.get("/api/device-lab/android").json()
    assert listing["found"] and listing["devices"][0]["serial"] == "emulator-5554"
    assert [c["argv"] for c in fakes.calls(adb, "adb")] == [["devices", "-l"]]


def test_the_routes_work_only_from_this_computer_and_this_page(env, stub_run):
    _, state, _ = env
    body = {"url": "http://localhost:3000/", "approved": True}
    elsewhere = TestClient(create_app(state), client=("192.0.2.1", 50000))
    for method, path in (("get", "/api/device-lab"), ("get", "/api/device-lab/android")):
        assert getattr(elsewhere, method)(path).status_code == 403
    assert elsewhere.post("/api/device-lab/run", json=body).status_code == 403
    here = TestClient(create_app(state), client=("127.0.0.1", 50000))
    assert here.post("/api/device-lab/run", json=body, headers={"origin": "https://evil.test"}).status_code == 403
    assert stub_run == []


def test_a_run_needs_approval_and_so_does_android(client, stub_run):
    body = {"url": "http://localhost:3000/"}
    denied = client.post("/api/device-lab/run", json=body)
    assert denied.status_code == 403 and denied.json()["detail"] == "device_lab_approval"
    phone = {"serial": "", "open_url": True, "approved": False}
    denied = client.post("/api/device-lab/run", json={**body, "approved": True, "android": phone})
    assert denied.status_code == 403 and denied.json()["detail"] == "device_lab_android_approval"
    only = client.post("/api/device-lab/android", json={**body, "approved": False})
    assert only.status_code == 403 and only.json()["detail"] == "device_lab_android_approval"
    assert stub_run == []  # nothing started without a yes


def test_an_approved_run_passes_the_choices_on_and_android_only_when_approved(client, stub_run):
    custom = [{"name": "Narrow", "width": 320, "height": 480}]
    answer = client.post("/api/device-lab/run", json={
        "url": "http://localhost:3000/", "approved": True, "profiles": ["small-phone"], "custom": custom,
        "allow_hosts": ["api.example.test"], "android": {"serial": "emulator-5554", "open_url": False, "approved": True}})
    assert answer.status_code == 200 and answer.json()["kind"] == "device_lab"
    (url, kwargs), = stub_run
    assert url == "http://localhost:3000/" and kwargs["profiles"] == ["small-phone"] and kwargs["custom"] == custom
    assert kwargs["allow_hosts"] == ["api.example.test"]
    assert kwargs["android"] == AndroidRequest(serial="emulator-5554", open_url=False)
    client.post("/api/device-lab/run", json={"url": "http://localhost:3000/", "approved": True})
    assert stub_run[1][1]["android"] is None
    bad = client.post("/api/device-lab/run", json={"url": "http://localhost/", "approved": True, "android": {
        "serial": "a;b", "approved": True}})
    assert bad.status_code == 400 and bad.json()["detail"] == "device_lab_android"


def test_the_routes_refuse_other_hosts_and_bad_profiles_with_codes_the_app_can_translate(client, monkeypatch):
    monkeypatch.setattr("spike.motion.render.launch", lambda *a, **k: pytest.fail("a browser was started"))
    ask = {"approved": True}
    assert client.post("/api/device-lab/run", json={"url": "https://example.com/", **ask}).json()["detail"] == "device_lab_host"
    assert client.post("/api/device-lab/run", json={"url": "https://example.com/", **ask}).status_code == 403
    assert client.post("/api/device-lab/run", json={"url": "file:///etc/passwd", **ask}).json()["detail"] == "device_lab_url"
    assert client.post("/api/device-lab/run", json={"url": "http://localhost/", "profiles": ["watch"], **ask}).json()[
        "detail"] == "device_lab_profile"
    assert client.post("/api/device-lab/run", json={"url": "http://localhost/", "custom": [{"name": "x"}], **ask}).json()[
        "detail"] == "device_lab_custom"
    assert client.post("/api/device-lab/run", json={"url": "http://localhost/", "allow_hosts": ["*.x.test"], **ask}).json()[
        "detail"] == "device_lab_hosts"
    assert client.post("/api/device-lab/android", json={"url": "https://example.com/", "approved": True}).status_code == 403


def test_a_missing_browser_is_a_translatable_code_on_the_route(client, monkeypatch):
    monkeypatch.setattr(lab, "playwright_missing", lambda: True)
    answer = client.post("/api/device-lab/run", json={"url": "http://localhost:3000/", "approved": True})
    assert answer.status_code == 400 and answer.json()["detail"] == "device_lab_browser"


def test_android_only_route_screenshots_with_approval(client, adb):
    answer = client.post("/api/device-lab/android", json={"url": "http://localhost:3000/", "approved": True, "open_url": False})
    shot = answer.json()["android"]
    assert answer.status_code == 200 and shot["status"] == "ok" and shot["screenshot"].startswith("data:image/png;base64,")


def test_two_runs_at_once_are_refused(client, monkeypatch):
    gate = threading.Event()
    started = threading.Event()

    async def slow(url, **kwargs):
        started.set()
        while not gate.is_set():
            await asyncio.sleep(0.01)
        return {"kind": "device_lab"}

    monkeypatch.setattr(lab, "run_device_lab", slow)
    first = {}
    body = {"url": "http://localhost/", "approved": True}
    thread = threading.Thread(target=lambda: first.update(r=client.post("/api/device-lab/run", json=body)))
    thread.start()
    assert started.wait(10)
    busy = client.post("/api/device-lab/run", json=body)
    gate.set()
    thread.join(10)
    assert busy.status_code == 409 and busy.json()["detail"] == "device_lab_busy" and first["r"].status_code == 200


# ================================================================== the browser (skipped when there is none)
def page(body: str, head: str = "", viewport: bool = True) -> bytes:
    meta = '<meta name="viewport" content="width=device-width, initial-scale=1">' if viewport else ""
    return (f'<!doctype html><html><head><meta charset="utf-8">{meta}<title>Fixture</title>{head}</head>'
            f'<body style="margin:0;font:16px/1.4 sans-serif">{body}</body></html>').encode()


OK_BUTTON = '<button style="width:48px;height:48px">OK</button>'
PAGES = {
    # a 700 px block (overflow on the two phones only), a 16 px button, 10 px text, a console error and a 404 image
    "/problem": page('<h1>Problem</h1><div id="wide" style="width:700px;height:40px;background:#cde">wide</div>'
                     '<button id="tiny" style="width:16px;height:16px;padding:0">x</button>'
                     '<p id="small" style="font-size:10px;margin:0">Tiny print</p>'
                     '<img src="/missing.png" width="10" height="10"><script>console.error("boom")</script>'),
    "/clean": page(f'<h1>Clean</h1><p>Read <a href="/docs">the docs</a> today.</p>{OK_BUTTON}'),
    "/carousel": page('<div id="strip" style="overflow-x:auto;width:100%"><div style="width:1500px;height:30px;background:#eee">'
                      f'strip</div></div><div style="overflow:hidden"><div style="width:900px">clipped</div></div>{OK_BUTTON}'),
    "/longword": page(f'<p id="word" style="margin:0;font-family:monospace">{"w" * 120}</p>{OK_BUTTON}'),
    "/nometa": page(f"<p>no viewport</p>{OK_BUTTON}", viewport=False),
    "/controls": page(
        '<p>Read <a id="inline" href="/x">the docs</a> now.</p>'
        '<nav><a id="block" href="/y" style="display:inline-block;width:20px;height:20px">y</a></nav>'
        '<input id="boxed" type="checkbox"><label for="boxed" style="display:inline-block;width:100px;height:30px">Yes</label>'
        '<input id="bare" type="checkbox" style="width:13px;height:13px">'
        '<button id="off" disabled style="width:10px;height:10px"></button>'
        '<div hidden><button id="gone" style="width:10px;height:10px"></button></div>'
        '<button id="sronly" style="position:absolute;width:1px;height:1px;padding:0;border:0;overflow:hidden">skip</button>'
        '<button id="exact" style="width:24px;height:24px;padding:0">k</button>'),
    "/external": page('<img id="ext" src="http://blocked.test/pic.png" width="10" height="10">'
                      '<script>fetch("http://blocked.test/api").catch(function(){});</script>' + OK_BUTTON),
    "/imgredirect": page(f'<img id="r" src="/redirect" width="10" height="10">{OK_BUTTON}'),
    "/crash": page(f'<script>setTimeout(function(){{ throw new Error("late crash"); }}, 50)</script>{OK_BUTTON}'),
    "/agent": page(f'<script>document.title = [navigator.userAgent, devicePixelRatio, navigator.maxTouchPoints, innerWidth].join("|")'
                   f'</script>{OK_BUTTON}'),
}


REDIRECTS = {"/redirect": "http://evil.test/landing", "/redirect-ip": "http://169.254.169.254/latest/meta-data",
             "/hop": "/redirect"}  # the last one: this computer first, another host second


class Fixture:
    def __init__(self):
        self.hits: list[tuple[str, str]] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                outer.hits.append((self.path, self.headers.get("Host", "")))
                path = self.path.split("?")[0]
                if path in REDIRECTS:
                    self.send_response(302)
                    self.send_header("Location", REDIRECTS[path])
                    self.end_headers()
                elif path == "/favicon.ico":
                    self.send_response(204)
                    self.end_headers()
                elif path in PAGES:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(PAGES[path])
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(scope="module")
def chromium():
    pytest.importorskip("playwright")
    from spike.motion.render import launch

    async def probe():
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            await (await launch(pw)).close()

    try:
        asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001 - no browser here, or SPIKE_CHROMIUM points nowhere: skip, never download
        pytest.skip(f"needs a Chromium (set SPIKE_CHROMIUM): {str(exc).splitlines()[0][:120] if str(exc) else exc}")


@pytest.fixture(scope="module")
def site(chromium):
    fixture = Fixture()
    yield fixture
    fixture.stop()


def run(site, path, **kwargs):
    return asyncio.run(lab.run_device_lab(site.base + path, **kwargs))


@pytest.fixture(scope="module")
def problem(site):
    return run(site, "/problem")


@pytest.fixture(scope="module")
def clean(site):
    return run(site, "/clean")


def profiles(report):
    return {p["id"]: p for p in report["profiles"]}


def with_issue(report, key):
    return {i for i, p in profiles(report).items() if p[key]["total"]}


def png_size(data_url):
    raw = base64.b64decode(data_url.split(",", 1)[1])
    assert raw.startswith(PNG_SIGNATURE)
    return struct.unpack(">II", raw[16:24])


def test_the_planted_problems_are_found_on_the_profiles_where_they_belong(problem):
    by = profiles(problem)
    assert list(by) == ALL
    overflowing = {i for i, p in by.items() if p["overflow"]["px"]}
    assert overflowing == PHONES  # a 700 px block fits the tablets (768 and 1024) and the computers
    assert by["small-phone"]["overflow"]["px"] == 340 and by["large-phone"]["overflow"]["px"] == 286
    for i in PHONES:
        (culprit,) = by[i]["overflow"]["items"]
        assert culprit["selector"] == "#wide" and culprit["width"] == 700 and culprit["right"] == 700
    assert with_issue(problem, "tap_targets") == set(ALL)  # a 16 px button is too small wherever it is
    assert with_issue(problem, "small_text") == set(ALL)
    for p in by.values():
        (tap,) = p["tap_targets"]["items"]
        assert (tap["selector"], tap["width"], tap["height"], tap["label"]) == ("#tiny", 16, 16, "x")
        (small,) = p["small_text"]["items"]
        assert (small["selector"], small["font_size"], small["text"]) == ("#small", 10, "Tiny print")
        assert p["layout"]["viewport_width"] == p["viewport"]["width"]


def test_console_errors_and_failed_requests_are_listed_per_profile(problem):
    for p in problem["profiles"]:
        assert p["console_errors"]["total"] == 1 and p["console_errors"]["items"][0]["text"] == "boom"
        assert p["console_errors"]["items"][0]["kind"] == "console"
        (bad,) = p["failed_requests"]["items"]
        assert bad["status"] == 404 and bad["url"].endswith("/missing.png") and bad["type"] == "image"
        assert p["http_status"] == 200 and p["title"] == "Fixture"


def test_each_profile_has_a_verdict_and_the_reasons_in_order(problem):
    by = profiles(problem)
    assert by["small-phone"]["status"] == "fail"
    assert by["small-phone"]["reasons"] == ["overflow", "tap_targets", "small_text", "console_errors", "failed_requests"]
    assert by["desktop"]["reasons"] == ["tap_targets", "small_text", "console_errors", "failed_requests"]
    assert by["small-phone"]["reason"] == ("the page is 340 px wider than the screen; 1 tap target under 24 px; "
                                           "1 text under 12 px; 1 console error; 1 failed request")
    assert problem["summary"] == {"profiles": 6, "pass": 0, "fail": 6, "error": 0}


def test_a_clean_page_passes_every_profile(clean):
    assert clean["summary"] == {"profiles": 6, "pass": 6, "fail": 0, "error": 0}
    for p in clean["profiles"]:
        assert p["status"] == "pass" and p["reasons"] == [] and p["reason"] == "no problems found"
        assert p["overflow"]["px"] == 0 and p["layout"]["document_width"] == p["layout"]["viewport_width"]
        assert not any(p[k]["total"] for k in ("tap_targets", "small_text", "console_errors", "failed_requests",
                                               "blocked_requests"))  # the inline link in the text is exempt


def test_the_report_has_one_shape_and_is_json(problem, clean):
    for report in (problem, clean):
        text = json.dumps(report)  # everything is plain JSON
        assert report["kind"] == "device_lab" and report["version"] == 1 and report["emulated"] is True
        assert report["browser"].startswith("Chromium ") and report["limits"] == {"min_tap": 24, "min_font": 12}
        assert report["android"] is None and report["allow_hosts"] == [] and report["seconds"] > 0
        assert report["url"].startswith("http://127.0.0.1:") and "?" not in report["url"]
        assert set(report) == {"kind", "version", "url", "started", "seconds", "browser", "emulated", "allow_hosts",
                               "limits", "summary", "profiles", "android"}
        for p in report["profiles"]:
            assert set(p) == {"id", "name", "kind", "builtin", "viewport", "scale", "touch", "mobile", "user_agent", "status",
                              "reasons", "reason", "http_status", "title", "notes", "layout", "overflow", "tap_targets",
                              "small_text", "console_errors", "failed_requests", "blocked_requests", "screenshot", "seconds"}
            assert p["status"] in {"pass", "fail", "error"} and p["reason"]
            for key in ("tap_targets", "small_text", "console_errors", "failed_requests", "blocked_requests", "overflow"):
                assert set(p[key]) >= {"total", "items"} and len(p[key]["items"]) <= lab.LIST_LIMIT
        assert "data:image/png" in text


def test_every_profile_has_a_screenshot_of_the_whole_page_at_css_size(problem):
    by = profiles(problem)
    for p in by.values():
        width, height = png_size(p["screenshot"])
        assert width == max(p["viewport"]["width"], p["layout"]["document_width"])  # the overflow shows in the picture
        assert height == p["layout"]["document_height"]
    assert png_size(by["small-phone"]["screenshot"])[0] == 700


def test_what_the_model_reads_has_no_pictures_and_is_short(problem):
    content = lab.for_model(problem)
    assert "data:image" not in content and "screenshot" not in content and len(content) < 12_000
    seen = json.loads(content)
    assert seen["summary"]["fail"] == 6 and [p["id"] for p in seen["profiles"]] == ALL  # every profile, whatever the cut
    many = {"profiles": [{"id": str(i), "tap_targets": {"total": 9, "items": [{"n": n} for n in range(9)]}} for i in range(8)]}
    cut = json.loads(lab.for_model(many, keep=3))
    assert len(cut["profiles"]) == 8 and all(len(p["tap_targets"]["items"]) == 3 and p["tap_targets"]["total"] == 9 for p in cut["profiles"])


def test_the_emulation_is_applied_to_the_page(site):
    custom = [{"name": "Tiny kiosk", "width": 320, "height": 480, "scale": 3, "touch": True, "user_agent": "KioskTest/2 (Mobile)"}]
    report = run(site, "/agent", profiles=["laptop", "small-phone"], custom=custom)
    by = profiles(report)
    assert list(by) == ["laptop", "small-phone", "custom-tiny-kiosk"]
    assert by["small-phone"]["title"] == "SpikeDeviceLab/1.0 (Mobile; phone; touch)|2|1|360"
    assert by["laptop"]["title"] == "SpikeDeviceLab/1.0 (Laptop; desktop)|1|0|1366"
    assert by["custom-tiny-kiosk"]["title"] == "KioskTest/2 (Mobile)|3|1|320"
    assert by["custom-tiny-kiosk"]["layout"]["touch_points"] == 1 and by["custom-tiny-kiosk"]["builtin"] is False
    assert {p["status"] for p in report["profiles"]} == {"pass"}


def test_a_scrolling_strip_is_not_an_overflow_but_a_long_word_is(site):
    strip = profiles(run(site, "/carousel", profiles=["small-phone", "desktop"]))
    assert all(p["status"] == "pass" and p["overflow"]["px"] == 0 for p in strip.values())  # clipped by a box that fits
    word = profiles(run(site, "/longword", profiles=["small-phone", "desktop"]))
    assert word["desktop"]["status"] == "pass"
    assert word["small-phone"]["reasons"] == ["overflow"] and word["small-phone"]["overflow"]["px"] > 500
    (culprit,) = word["small-phone"]["overflow"]["items"]
    assert culprit["selector"] == "#word" and culprit["kind"] == "content"  # the text spills out of a box that fits


def test_tap_target_rules_inline_links_labels_disabled_and_hidden_controls(site):
    for p in run(site, "/controls", profiles=["small-phone", "desktop"])["profiles"]:
        flagged = {i["selector"] for i in p["tap_targets"]["items"]}
        assert flagged == {"#block", "#bare"}, p["id"]  # inline link, labelled checkbox, disabled, hidden, 1 px, 24 px: fine
        assert p["status"] == "fail" and p["reasons"] == ["tap_targets"]


def test_a_page_without_a_viewport_tag_is_laid_out_wide_on_phones_and_says_so(site):
    by = profiles(run(site, "/nometa", profiles=["small-phone", "desktop"]))
    assert by["small-phone"]["layout"]["viewport_width"] == 980 and by["small-phone"]["notes"] == ["no_viewport_meta"]
    assert by["desktop"]["notes"] == [] and by["small-phone"]["status"] == "pass"


def test_uncaught_exceptions_are_console_errors(site):
    p = run(site, "/crash", profiles=["desktop"])["profiles"][0]
    assert p["status"] == "fail" and p["reasons"] == ["console_errors"]
    assert p["console_errors"]["items"][0]["kind"] == "exception" and "late crash" in p["console_errors"]["items"][0]["text"]


def test_other_hosts_are_blocked_listed_and_never_requested(site):
    p = run(site, "/external", profiles=["desktop"])["profiles"][0]
    urls = {b["url"] for b in p["blocked_requests"]["items"]}
    assert urls == {"http://blocked.test/pic.png", "http://blocked.test/api"}
    assert p["status"] == "pass" and p["failed_requests"]["total"] == 0 and p["console_errors"]["total"] == 0


@pytest.mark.parametrize("path,away", [("/redirect", "evil.test"), ("/redirect-ip", "169.254.169.254"), ("/hop", "evil.test")])
def test_a_redirect_to_another_host_is_stopped_and_the_profile_is_an_error_with_the_reason(site, path, away):
    # a redirect is followed inside the browser, where Playwright's routes do not see it: the dead-end proxy stops it
    report = run(site, path, profiles=["small-phone", "desktop"])
    assert report["summary"] == {"profiles": 2, "pass": 0, "fail": 0, "error": 2}
    for p in report["profiles"]:
        assert p["status"] == "error" and p["reasons"] == ["navigation"] and p["screenshot"] == ""
        assert p["reason"] == f"the page leads to {away}, which is not allowed for this run"
        assert [urlsplit(b["url"]).netloc for b in p["blocked_requests"]["items"]] == [away]
        assert p["failed_requests"]["total"] == 0


def test_a_redirect_of_an_image_to_another_host_is_blocked_too_but_the_page_is_still_checked(site):
    p = run(site, "/imgredirect", profiles=["desktop"])["profiles"][0]
    assert [b["url"] for b in p["blocked_requests"]["items"]] == ["http://evil.test/landing"]
    assert p["status"] == "pass" and p["failed_requests"]["total"] == 0


def test_the_browser_is_started_with_a_dead_end_proxy_and_this_computer_bypasses_it():
    assert lab.bypass_rules(frozenset({"localhost", "127.0.0.1", "staging.example.test", "2001:db8::1"})) == (
        "<-loopback>;localhost;*.localhost;127.0.0.0/8;[::1];[2001:db8::1];staging.example.test")


def test_a_page_that_is_not_running_is_an_error_not_a_crash(site):
    closed = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    port = closed.server_port
    closed.server_close()  # nothing listens here now
    report = asyncio.run(lab.run_device_lab(f"http://127.0.0.1:{port}/", profiles=["desktop"]))
    p = report["profiles"][0]
    assert p["status"] == "error" and p["reasons"] == ["navigation"] and "ERR_CONNECTION_REFUSED" in p["reason"]


async def test_the_tool_returns_the_report_for_the_card_and_a_short_text_for_the_model(site):
    events = await drive(call("device_lab", {"url": site.base + "/problem", "profiles": ["small-phone", "desktop"]}))
    ask = next(e for e in events if e["type"] == "permission_request")
    assert ask["code"] == "device_lab" and ask["once"]
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["ok"], result["content"]
    assert result["ui"]["kind"] == "device_lab" and result["ui"]["summary"] == {"profiles": 2, "pass": 0, "fail": 2, "error": 0}
    assert result["ui"]["profiles"][0]["screenshot"].startswith("data:image/png;base64,")
    assert "data:image" not in result["content"] and json.loads(result["content"])["summary"]["fail"] == 2


async def test_the_tool_waits_in_the_job_queue_when_the_app_has_one(site):
    from spike.jobs import JobQueue

    queue = JobQueue(ram_floor=0)
    result = await DeviceLab(queue).run({"url": site.base + "/clean", "profiles": ["desktop"]})
    assert result.ok and [j["status"] for j in queue.list()] == ["completed"]


def test_android_is_added_to_the_report_only_when_asked_for(site, adb):
    plain = run(site, "/clean", profiles=["desktop"])
    assert plain["android"] is None and fakes.calls(adb, "adb") == []  # adb was on the PATH and was not touched
    both = run(site, "/clean", profiles=["desktop"], android=AndroidRequest(wait_s=0))
    assert both["android"]["status"] == "ok" and both["android"]["serial"] == "emulator-5554"
    assert both["android"]["screenshot"].startswith("data:image/png;base64,") and both["profiles"][0]["status"] == "pass"
    assert "reverse" in [c["argv"][2] for c in fakes.calls(adb, "adb") if len(c["argv"]) > 2]


def test_the_whole_thing_through_the_route(client, site):
    answer = client.post("/api/device-lab/run", json={"url": site.base + "/problem", "approved": True, "profiles": ["small-phone"]})
    assert answer.status_code == 200, answer.text
    report = answer.json()
    assert report["summary"]["fail"] == 1 and report["profiles"][0]["screenshot"].startswith("data:image/png")
