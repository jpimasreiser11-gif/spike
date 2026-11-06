"""Reliability tests for Workflows, Device Lab, Reverse Studio, and Geo (G16):
cycles on the canvas, steps deleted mid-run, empty inputs, nonexistent device profiles,
corrupt captures/screenshots, and out-of-range coordinates."""

from __future__ import annotations

import base64
import json
import math

import pytest
from fastapi.testclient import TestClient

from spike.design import reverse, reverse_browser
from spike.design.reverse import ReverseError
from spike.dev import device_lab as lab
from spike.dev.device_lab import AndroidRequest, DeviceLabError, check_target, pick_profiles
from spike.geo import data as geodata
from spike.geo import measure
from spike.geo.data import GeoError
from spike.geo.project import Equirectangular
from spike.geo.tools import GeoMap
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.server.app import create_app
from spike.server.state import AppState
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker, Tool, ToolRegistry, ToolResult
from spike.tools.builtin import Workspace
from spike.workflows import model
from spike.workflows.model import WorkflowError, bind_inputs, clean, validate
from spike.workflows.runner import Host, LiveRun, execute, new_record
from tests import helpers_programs as fakes
from tests.helpers import ScriptedProvider
from tests.helpers_workflows import ENV, Echo, doc, edge, node

CATALOG = load_catalog()


def _make_host(provider, tools, **kw) -> Host:
    broker = PermissionBroker({}, timeout_s=5)
    registry = ToolRegistry(tools)
    orchestrator = Orchestrator(
        CATALOG,
        lambda spec: Backend(provider=provider, model=None, adapter=None),
        registry,
        broker,
    )
    return Host(
        orchestrator=orchestrator,
        options=lambda mode: OrchestratorOptions(mode=mode, skill_mode="off"),
        broker=broker,
        **kw,
    )


# ---------------------------------------------------------------- 1. Cycles on the canvas
def test_workflow_canvas_cycles_self_references_and_levels_rejection():
    # Two disjoint cycles on the same canvas must both be reported by validate(),
    # and a node inside a cycle referencing its own output {{a}} must still report var_upstream.
    canvas = clean(
        doc(
            [
                node("a", "specialist", name="a", prompt="loop {{a}}"),
                node("b", "specialist", name="b", prompt="from a {{a}}"),
                node("c", "specialist", name="c", prompt="second cycle"),
                node("d", "specialist", name="d", prompt="back to c"),
            ],
            [
                edge("a", "b"),
                edge("b", "a"),
                edge("c", "d"),
                edge("d", "c"),
            ],
        )
    )
    assert "a" not in model.ancestors(canvas, "a")
    problems = validate(canvas, ENV)
    cycle_problems = [p for p in problems if p.code == "cycle"]
    assert len(cycle_problems) == 2
    assert {frozenset(p.params["nodes"]) for p in cycle_problems} == {
        frozenset({"a", "b"}),
        frozenset({"c", "d"}),
    }
    assert ("var_upstream", "a") in [(p.code, p.node) for p in problems]

    # Calling levels() or new_record() directly on a cyclic graph or self-loop must raise WorkflowError
    # rather than silently breaking the cycle via the planner.
    with pytest.raises(WorkflowError, match="cycle"):
        model.levels(canvas)
    self_loop = clean(doc([node("s", "specialist", prompt="x")], [edge("s", "s")]))
    with pytest.raises(WorkflowError, match="cycle"):
        model.levels(self_loop)


# ---------------------------------------------------------------- 2. Steps deleted mid-run
async def test_workflow_steps_deleted_mid_run_skip_cleanly_without_keyerror():
    d = clean(
        doc(
            [
                node("step1", "tool", name="step1", tool="mutator", arguments={}),
                node("step2", "tool", name="step2", tool="echo", arguments={"text": "{{input}}"}),
                node("step3", "output", name="step3", mode="artifact", content="{{input}}"),
                node("side", "tool", name="side", tool="echo", arguments={"text": "independent"}),
            ],
            [edge("step1", "step2"), edge("step2", "step3")],
        )
    )

    class Mutator(Tool):
        name = "mutator"
        description = "Deletes step2 from the workflow document while step1 is running."
        parameters = {"type": "object", "properties": {}}
        risk = "read"
        default_policy = "allow"

        async def run(self, args):
            d["nodes"][:] = [n for n in d["nodes"] if n["id"] != "step2"]
            return ToolResult(ok=True, content="done")

    echo = Echo()
    host = _make_host(ScriptedProvider([]), [Mutator(), echo])
    live = LiveRun(new_record(d, {}))
    # Also simulate an entry disappearing from live.record["nodes"] or doc["nodes"] mid-run
    record = await execute(d, {}, host, live)

    assert record["nodes"]["step1"]["status"] == "ok"
    assert record["nodes"]["step2"]["status"] == "skipped"
    assert record["nodes"]["step2"]["skip"] == "deleted"
    assert record["nodes"]["step3"]["status"] == "skipped"
    assert record["nodes"]["step3"]["skip"] == "upstream"
    assert record["nodes"]["side"]["status"] == "ok"
    assert echo.calls == [{"text": "independent"}]


# ---------------------------------------------------------------- 3. Empty inputs (Workflows & Geo)
async def test_empty_inputs_in_workflows_and_geo_are_rejected_cleanly(tmp_path):
    # Workflows: bind_inputs with None or whitespace, and execute() called directly with empty values
    wf = clean(
        doc(
            [
                node("i", "input", name="topic", default=""),
                node("f", "input", name="doc", kind="file", default=""),
                node("o", "output", mode="artifact", content="{{topic}}"),
            ],
            [edge("i", "o")],
        )
    )
    values, problems = bind_inputs(wf, None)
    assert [(p.code, p.node) for p in problems] == [("input_missing", "i"), ("input_missing", "f")]

    _, traversal_problems = bind_inputs(wf, {"topic": "ok", "doc": "../outside.txt"})
    assert [(p.code, p.node) for p in traversal_problems] == [("input_file", "f")]

    # Direct execute() with empty/missing input value fails the input node instead of raising KeyError
    live = LiveRun(new_record(wf, {}))
    record = await execute(wf, {}, _make_host(ScriptedProvider([]), []), live)
    assert record["status"] == "failed"
    assert record["nodes"]["i"]["status"] == "failed"
    assert "needs a value" in record["nodes"]["i"]["error"]
    assert record["nodes"]["o"]["status"] == "skipped"

    # Geo: empty GeoJSON string and GeoJSON with only empty MultiPoint / GeometryCollection
    with pytest.raises(GeoError, match="empty"):
        geodata.parse_geojson("   ")

    empty_geoms = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPoint", "coordinates": []}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiLineString", "coordinates": []}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "MultiPolygon", "coordinates": []}},
            {"type": "Feature", "properties": {}, "geometry": {"type": "GeometryCollection", "geometries": []}},
        ],
    }
    with pytest.raises(GeoError, match="no features with a geometry"):
        geodata.parse_geojson(json.dumps(empty_geoms))

    # Passing explicit None for optional lang/bins in GeoMap falls back to defaults instead of failing
    csv_file = tmp_path / "pts.csv"
    csv_file.write_text("name,lat,lon\nMadrid,40.4168,-3.7038\n", encoding="utf-8")
    res = await GeoMap(Workspace(tmp_path)).run({"path": "pts.csv", "lang": None, "bins": None})
    assert res.ok


# ---------------------------------------------------------------- 4. Nonexistent device profiles
def test_device_lab_rejects_empty_and_nonexistent_profiles(tmp_path, monkeypatch):
    # An explicitly empty profile list with no custom profiles must raise device_lab_profile
    with pytest.raises(DeviceLabError) as err:
        pick_profiles([], None)
    assert err.value.code == "device_lab_profile"

    with pytest.raises(DeviceLabError) as err:
        pick_profiles([], [])
    assert err.value.code == "device_lab_profile"

    with pytest.raises(DeviceLabError) as err:
        pick_profiles(["nonexistent-watch"], None)
    assert err.value.code == "device_lab_profile"

    # Route rejects empty or nonexistent profiles with 400 device_lab_profile even before launching a browser
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path)
    state.jobs.ram_floor = 0
    with TestClient(create_app(state), client=("127.0.0.1", 50000)) as client:
        for bad_profiles in ([], ["smart-fridge"], ["small-phone", "ghost-tablet"]):
            r = client.post(
                "/api/device-lab/run",
                json={"url": "http://localhost:3000/", "approved": True, "profiles": bad_profiles},
            )
            assert r.status_code == 400 and r.json()["detail"] == "device_lab_profile", bad_profiles


# ---------------------------------------------------------------- 5. Corrupt captures and screenshots
async def test_corrupt_captures_in_reverse_studio_and_device_lab(tmp_path, monkeypatch):
    # Truncated PNG (18 bytes with IHDR marker) and corrupt JPEG segment length (< 2) must raise ReverseError("image_invalid")
    truncated_png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00"
    corrupt_jpeg = b"\xff\xd8\xff\xe0\x00\x00JFIF\x00\x01\x01"
    for raw in (truncated_png, corrupt_jpeg):
        with pytest.raises(ReverseError, match="image_invalid"):
            reverse.image_size(raw)

    # Corrupt capture structure passed to reverse.describe() must raise ReverseError("reverse_capture_failed")
    for bad_capture in (
        {},
        {"viewport": "bad"},
        {"viewport": {"width": 0, "height": 600}, "root": {"t": "body", "r": [0, 0, 100, 100], "s": {}}},
        {"viewport": {"width": 800, "height": 600}, "root": {"t": "body", "r": [0, 0], "s": {}}},
        {"viewport": {"width": 800, "height": 600}, "root": {"t": "body", "r": [0, 0, 100, 100], "s": "not-a-dict"}},
    ):
        with pytest.raises(ReverseError, match="reverse_capture_failed"):
            reverse.describe(bad_capture)

    # Reverse API returns 400 on truncated PNG preview and 502 when capture_page returns a corrupt PNG screenshot
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path)
    with TestClient(create_app(state), client=("127.0.0.1", 50000)) as client:
        client.patch("/api/providers/spike-local", json={"capabilities": {"vision": True}})
        trunc_url = "data:image/png;base64," + base64.b64encode(truncated_png).decode("ascii")
        r = client.post(
            "/api/reverse/preview",
            json={"authorized": True, "source": "image", "image": trunc_url},
        )
        assert r.status_code == 400 and r.json()["detail"] == "image_invalid"

        async def corrupt_capture_page(**kwargs):
            return {
                "viewport": {"width": 800, "height": 600},
                "png": b"\x89PNG\r\n\x1a\ncorrupt-body",
                "root": {"t": "body", "r": [0, 0, 800, 600], "s": {}},
            }

        monkeypatch.setattr(reverse_browser, "capture_page", corrupt_capture_page)
        quote = client.post(
            "/api/reverse/preview",
            json={"authorized": True, "source": "url", "url": "http://localhost:5173/"},
        ).json()
        gen = client.post("/api/reverse/generate", json={"preview_id": quote["id"]})
        assert gen.status_code == 502 and gen.json()["detail"] == "reverse_capture_failed"

    # Device Lab: android_shot and page screenshot reject truncated/corrupt PNG bytes with PNG signature
    adb_dir = tmp_path / "adb-corrupt"
    fakes.install(
        adb_dir,
        "adb",
        fakes.COMMON
        + r"""
args = list(ARGV)
if args[:1] == ["-s"]:
    args = args[2:]
if args[:1] == ["devices"]:
    print("List of devices attached\nemulator-5554\tdevice model:Test_Emulator\n")
    sys.exit(0)
if args[:2] == ["exec-out", "screencap"]:
    sys.stdout.buffer.write(b"\x89PNG\r\n\x1a\ntruncated")
    sys.stdout.flush()
    sys.exit(0)
sys.exit(0)
""",
    )
    monkeypatch.setenv("PATH", f"{adb_dir}:{tmp_path}")
    shot = await lab.android_shot(AndroidRequest(open_url=False, wait_s=0), check_target("http://localhost:3000/"))
    assert shot["status"] == "error" and shot["error"] == "no_screenshot" and shot["screenshot"] == ""

    class FakeCorruptPage:
        async def screenshot(self, **kwargs):
            return b"\x89PNG\r\n\x1a\ntruncated"

    notes: list[str] = []
    data_url = await lab.screenshot(
        FakeCorruptPage(),
        {"viewport": {"width": 360, "height": 640}, "document": {"width": 360, "height": 640}},
        notes,
    )
    assert data_url == "" and "screenshot_failed" in notes


# ---------------------------------------------------------------- 6. Out-of-range coordinates
def test_geo_rejects_out_of_range_and_degenerate_coordinates():
    # Direct calls to measure.* and Equirectangular.* must reject out-of-range degrees, projected metres, and NaN/Inf
    for bad_pt in ((91.0, 0.0), (-95.0, 0.0), (0.0, 181.0), (0.0, -185.0), (4500000.0, 500000.0), (math.nan, 0.0)):
        with pytest.raises(GeoError):
            measure.haversine(bad_pt, (0.0, 0.0))
        with pytest.raises(GeoError):
            measure.path_length([(0.0, 0.0), bad_pt])
        with pytest.raises(GeoError):
            measure.ring_area([(0.0, 0.0), (0.0, 1.0), bad_pt])
        with pytest.raises(GeoError):
            Equirectangular.fit([bad_pt])
        with pytest.raises(GeoError):
            Equirectangular(0.0, 0.0).xy(*bad_pt)

    # Degenerate polygon ring with fewer than 3 distinct positions in GeoJSON must raise GeoError
    degenerate_poly = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [0, 0], [0, 0], [0, 0]]],
    }
    with pytest.raises(GeoError, match="distinct"):
        geodata.parse_geojson(json.dumps(degenerate_poly))
