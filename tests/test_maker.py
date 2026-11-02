"""A18: 3D with Blender and games with Godot 4. The programs are the user's own, so the tests run fake `blender` and
`godot` scripts on a temporary PATH: they record their argv and write what the real ones would. Nothing real is started.
What is proved here: a missing program is reported with where to get it (and nothing is asked or written), a denied
call runs nothing, an approved one saves the script, runs the program inside the workspace with SPIKE's own command
line and returns the preview or the check, a script cannot leave the workspace or choose the preview's path, a hanging
program is stopped, and the Godot scaffold writes the files a Godot 4 project needs. What is NOT proved: that real
Blender or real Godot accept these scripts and flags."""

from __future__ import annotations

import ast
import asyncio
import math
import os
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from spike.agent.loop import AgentRun, run_agent
from spike.core.types import Message
from spike.maker import blender, godot, starters
from spike.maker.blender import BlenderError
from spike.maker.program import BLENDER, GODOT, command_line, tail
from spike.maker.starters import StarterError
from spike.maker.tools import BlenderRender, GodotCheck, GodotScaffold, maker_tools
from spike.orchestrator.router import LexicalRouter
from spike.server.app import create_app
from spike.server.state import AppState
from spike.skills.validation import known_tools
from spike.specialists.catalog import load_catalog
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Workspace
from spike.tools.sandbox import NOTE, Sandbox
from tests import helpers_programs as fakes
from tests.helpers import ScriptedProvider, call, text

OFF = Sandbox("off")  # no bwrap probing: these tests are about the tools, not the sandbox
SCRIPT = "import bpy\nbpy.ops.mesh.primitive_cube_add()\n"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    return Workspace(root)


@pytest.fixture
def bin_dir(tmp_path, monkeypatch):
    """A PATH with a fake blender and a fake godot (Godot 4.2.1) in front of whatever else is there."""
    folder = tmp_path / "bin"
    fakes.install(folder, "blender", fakes.BLENDER)
    fakes.install(folder, "godot", fakes.GODOT)
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ.get('PATH', '')}")
    return folder


@pytest.fixture
def no_programs(tmp_path, monkeypatch):
    """A PATH with neither program."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


async def drive(tools, tool_call, decision="allow_once", policies=None):
    """One model turn that calls a tool, through the real agent loop and a broker that answers with `decision`."""
    broker = PermissionBroker(policies or {})
    events = []
    provider = ScriptedProvider([tool_call, text("done")])
    async for ev in run_agent(provider, [Message(role="user", content="x")], tools=tools, broker=broker,
                              run=AgentRun()):
        events.append(ev)
        if ev["type"] == "permission_request":
            asyncio.get_running_loop().call_soon(broker.resolve, ev["id"], decision)
    return events


def result_of(events):
    return next(e for e in events if e["type"] == "tool_result")


def asked(events):
    return [e for e in events if e["type"] == "permission_request"]


def files_under(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


# ---------------------------------------------------------------- Blender: the program is missing
async def test_a_missing_blender_is_refused_before_anyone_is_asked_and_says_how_to_get_it(ws, no_programs):
    tool = BlenderRender(ws, OFF)
    review = tool.review({"script": SCRIPT})
    assert review.policy == "deny" and review.code == "blender_missing"
    for part in ("https://www.blender.org/download/", "SPIKE never downloads", "no está instalado", "nunca lo descarga"):
        assert part in review.reason
    events = await drive([tool], call("blender_render", {"script": SCRIPT}), policies={"blender_render": "allow"})
    assert not asked(events)
    result = result_of(events)
    assert not result["ok"] and "https://www.blender.org/download/" in result["content"]
    assert files_under(ws.root) == []  # not even the script was written
    direct = await tool.run({"script": SCRIPT})  # the tool says so on its own as well
    assert not direct.ok and "is not installed" in direct.content


# ---------------------------------------------------------------- Blender: permission
async def test_a_denied_blender_call_runs_nothing_and_writes_nothing(ws, bin_dir):
    events = await drive([BlenderRender(ws, OFF)], call("blender_render", {"script": SCRIPT}), "deny")
    ask = asked(events)[0]
    assert ask["tool"] == "blender_render" and ask["risk"] == "execute" and ask["code"] == "blender_render"
    assert ask["arguments"]["script"] == SCRIPT  # the user sees the code that would run
    assert ask["isolation"]["isolated"] is False
    result = result_of(events)
    assert not result["ok"] and "denied" in result["content"]
    assert fakes.calls(bin_dir, "blender") == [] and files_under(ws.root) == []


async def test_blender_asks_even_when_the_user_never_changed_its_policy(ws, bin_dir):
    tool = BlenderRender(ws, OFF)
    assert tool.risk == "execute" and tool.default_policy == "ask"
    assert PermissionBroker().policy_for_call(tool, {"script": SCRIPT})[0] == "ask"


async def test_the_sandbox_setting_required_refuses_blender_when_the_computer_has_no_sandbox(ws, bin_dir):
    tool = BlenderRender(ws, Sandbox("required", platform="win32"))
    events = await drive([tool], call("blender_render", {"script": SCRIPT}), policies={"blender_render": "allow"})
    assert not asked(events)
    assert not result_of(events)["ok"] and "sandbox is required" in result_of(events)["content"]
    assert fakes.calls(bin_dir, "blender") == []
    auto = BlenderRender(ws, Sandbox("auto", platform="win32"))
    assert auto.isolation({})["code"] == "approved_command"  # an approved program is not wrapped under auto, and says so


# ---------------------------------------------------------------- Blender: an approved run
async def test_an_approved_run_saves_the_script_runs_blender_in_the_workspace_and_returns_the_preview(ws, bin_dir):
    events = await drive([BlenderRender(ws, OFF)], call("blender_render", {"script": SCRIPT}))
    assert len(asked(events)) == 1
    result = result_of(events)
    assert result["ok"], result["content"]
    script, driver = ws.root / "blender" / "scene.py", ws.root / "blender" / "scene.render.py"
    preview = ws.root / "blender" / "scene.preview.png"
    assert script.read_text(encoding="utf-8") == SCRIPT
    assert driver.read_text(encoding="utf-8") == blender.DRIVER.read_text(encoding="utf-8")
    assert preview.read_bytes().startswith(PNG_SIGNATURE)
    (run,) = fakes.calls(bin_dir, "blender")
    assert run["argv"] == ["--background", "--factory-startup", "--python-exit-code", "1", "--python", str(driver), "--",
                           str(script), str(preview), "640", "360", "32"]
    assert Path(run["cwd"]).resolve() == ws.root  # started inside the workspace
    assert result["file"] == "blender/scene.preview.png"
    ui = result["ui"]
    assert ui["kind"] == "blender_render" and ui["script"] == "blender/scene.py"
    assert (ui["preview"], ui["width"], ui["height"]) == ("blender/scene.preview.png", 64, 36)  # the PNG's own size
    assert ui["engine"] == "Cycles (CPU)" and ui["samples"] == 32 and ui["version"] == "4.2.0"
    assert "Blender 4.2.0 (fake)" in ui["log"] and ui["bytes"] == preview.stat().st_size
    lines = result["content"].splitlines()
    assert lines[0].startswith("rendered blender/scene.preview.png from blender/scene.py") and "(Blender 4.2.0)" in lines[0]
    assert lines[-1].startswith(NOTE)  # the last line says whether the run was isolated, like the other code runners


async def test_the_preview_path_is_chosen_by_spike_not_by_the_model(ws, bin_dir, tmp_path):
    tool = BlenderRender(ws, OFF)
    assert not {"output", "preview", "preview_path", "render_path"} & set(tool.parameters["properties"])
    stray = {"script": SCRIPT, "path": "models/vase.py", "preview": str(tmp_path / "evil.png"),
             "output": "../../evil.png", "filepath": "/tmp/evil.png"}
    result = await tool.run(stray)
    assert result.ok and result.data["ui"]["preview"] == "models/vase.preview.png"
    assert (ws.root / "models" / "vase.preview.png").is_file() and not (tmp_path / "evil.png").exists()
    argv = fakes.calls(bin_dir, "blender")[0]["argv"]
    assert argv[-5:-3] == [str(ws.root / "models" / "vase.py"), str(ws.root / "models" / "vase.preview.png")]
    assert "evil" not in " ".join(argv)


async def test_a_new_render_replaces_the_old_preview_and_a_failed_one_leaves_none(ws, bin_dir, monkeypatch):
    tool = BlenderRender(ws, OFF)
    assert (await tool.run({"script": SCRIPT})).ok
    preview = ws.root / "blender" / "scene.preview.png"
    preview.write_bytes(b"stale")
    monkeypatch.setenv("FAKE_MODE", "crash")
    failed = await tool.run({"script": SCRIPT})
    assert not failed.ok and not preview.exists()  # the stale preview is not mistaken for a new one
    assert "exit code 1" in failed.content and "NameError: name 'oops' is not defined" in failed.content
    assert "ui" not in failed.data and "file" not in failed.data


async def test_blender_that_exits_cleanly_without_a_preview_is_an_error(ws, bin_dir, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "nopng")
    result = await BlenderRender(ws, OFF).run({"script": SCRIPT})
    assert not result.ok and "wrote no preview image" in result.content


async def test_a_hanging_blender_is_stopped_at_the_timeout(ws, bin_dir, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "hang")
    result = await asyncio.wait_for(BlenderRender(ws, OFF).run({"script": SCRIPT, "timeout_s": 1}), 30)
    assert not result.ok and "timed out after 1 s" in result.content
    assert not (ws.root / "blender" / "scene.preview.png").exists() and "ui" not in result.data


# ---------------------------------------------------------------- Blender: the script stays in the workspace
@pytest.mark.parametrize("path", ["../escape.py", "blender/../../escape.py", "/tmp/spike-a18-escape.py", "notes.txt",
                                  "blender"])
async def test_a_script_path_outside_the_workspace_or_not_python_is_refused(ws, bin_dir, tmp_path, path):
    (ws.root / "blender").mkdir()
    tool = BlenderRender(ws, OFF)
    result = await tool.run({"script": SCRIPT, "path": path})
    assert not result.ok and result.content.startswith("error:")
    assert tool.targets({"script": SCRIPT, "path": path}) == []
    assert not (tmp_path / "escape.py").exists() and not Path("/tmp/spike-a18-escape.py").exists()
    assert fakes.calls(bin_dir, "blender") == []


async def test_a_symlink_cannot_lead_the_script_out_of_the_workspace(ws, bin_dir, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (ws.root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")
    result = await BlenderRender(ws, OFF).run({"script": SCRIPT, "path": "link/scene.py"})
    assert not result.ok and "outside the workspace" in result.content
    assert list(outside.iterdir()) == [] and fakes.calls(bin_dir, "blender") == []


async def test_a_script_that_is_not_python_never_starts_blender(ws, bin_dir):
    result = await BlenderRender(ws, OFF).run({"script": "import bpy\nfor x in:\n"})
    assert not result.ok and "not valid Python (line 2" in result.content and "Blender was not started" in result.content
    assert fakes.calls(bin_dir, "blender") == [] and files_under(ws.root) == []


@pytest.mark.parametrize("args, expected", [
    ({}, "either `script`"), ({"script": SCRIPT, "starter": "vase"}, "either `script`"),
    ({"starter": "teapot"}, "unknown starter 'teapot'"), ({"starter": "vase", "params": {"height": 99}}, "between 0.2 and 10"),
    ({"script": "x" * (blender.MAX_SCRIPT + 1)}, "too long")])
async def test_blender_arguments_are_checked_before_anything_is_written(ws, bin_dir, args, expected):
    result = await BlenderRender(ws, OFF).run(args)
    assert not result.ok and expected in result.content
    assert fakes.calls(bin_dir, "blender") == [] and files_under(ws.root) == []


def test_checkpoints_cover_everything_a_render_writes(ws):
    tool = BlenderRender(ws, OFF)
    got = tool.targets({"starter": "vase"})
    assert [p.relative_to(ws.root).as_posix() for p in got] == ["blender/vase.py", "blender/vase.render.py",
                                                                "blender/vase.preview.png"]


async def test_a_starter_renders_through_the_same_path(ws, bin_dir):
    result = await BlenderRender(ws, OFF).run({"starter": "vase", "params": {"height": 3, "segments": 16}})
    assert result.ok and result.data["ui"]["script"] == "blender/vase.py"
    saved = (ws.root / "blender" / "vase.py").read_text(encoding="utf-8")
    assert "HEIGHT = 3.0  # 0.2..10 total height" in saved and "SEGMENTS = 16  # 8..128" in saved


def test_the_tool_description_lists_the_starters_and_their_numbers():
    spec = BlenderRender(Workspace(Path.cwd()), OFF).spec()
    assert set(spec.parameters["properties"]["starter"]["enum"]) == {"vase", "studio_scene", "staircase"}
    for fragment in ("vase: A vase: a surface of revolution. Numbers: height 0.2-10 (2), radius", "studio_scene:",
                     "staircase:", "steps 2-60 (10)"):
        assert fragment in spec.description


# ---------------------------------------------------------------- starters and SPIKE's wrapper (against a stand-in bpy)
def test_every_starter_is_valid_python_with_numbers_in_range():
    assert set(starters.starters()) == {"vase", "studio_scene", "staircase"}
    for found in starters.starters().values():
        assert found.summary and found.params
        ast.parse(starters.build(found.id))
        for p in found.params:
            assert p.low <= p.default <= p.high, (found.id, p.key)


def test_starter_numbers_are_validated_and_written_into_the_script():
    script = starters.build("staircase", {"steps": 4, "rise": 0.25})
    assert "STEPS = 4  # 2..60" in script and "RISE = 0.25  # 0.05..0.5" in script and "RUN = 0.28  #" in script
    assert starters.build("staircase") == starters.starters()["staircase"].source
    for bad, why in (({"steps": 4.5}, "whole number"), ({"steps": 1}, "between 2 and 60"), ({"rise": True}, "must be a number"),
                     ({"rise": "tall"}, "must be a number"), ({"rise": float("nan")}, "must be a number"),
                     ({"colour": 1}, "no number named colour"), ("steps=4", "object of numbers")):
        with pytest.raises(StarterError, match=why):
            starters.build("staircase", bad)


def stand_in_bpy(monkeypatch):
    """A bpy that records what a script builds: meshes keep their from_pydata arguments, objects keep what is set."""
    bpy = MagicMock()
    made = SimpleNamespace(meshes=[], objects=[])

    def new_mesh(name):
        mesh = MagicMock()
        made.meshes.append(mesh)
        return mesh

    def new_object(name, data):
        obj = SimpleNamespace(name=name, data=data, location=None, rotation_euler=None, modifiers=MagicMock())
        made.objects.append(obj)
        return obj

    bpy.data.meshes.new.side_effect = new_mesh
    bpy.data.objects.new.side_effect = new_object
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    return bpy, made


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def facing(verts, face):
    """(unit normal of the face from its first three corners, the face's middle) for a face wound counter-clockwise."""
    a, b, c = (np.array(verts[i], dtype=float) for i in face[:3])
    normal = np.cross(b - a, c - b)
    return normal / np.linalg.norm(normal), np.mean([verts[i] for i in face], axis=0)


def test_the_vase_is_a_closed_well_wound_surface_of_revolution(monkeypatch):
    bpy, made = stand_in_bpy(monkeypatch)
    runpy.run_path(str(starters.SCRIPTS / "vase.py"), run_name="__main__")
    verts, _, faces = made.meshes[0].from_pydata.call_args.args
    segments, rings = 48, 24
    assert len(verts) == 1 + (rings + 1) * segments and len(faces) == segments + rings * segments
    assert all(len(set(f)) == len(f) and all(0 <= i < len(verts) for i in f) for f in faces)
    base = [facing(verts, f) for f in faces[:segments]]
    assert all(n[2] < -0.5 for n, _ in base)  # the base faces down
    for n, middle in (facing(verts, f) for f in faces[segments:]):
        assert np.dot(n, [middle[0], middle[1], 0.0]) > 0  # the wall faces away from the axis
    assert max(v[2] for v in verts) == pytest.approx(2.0) and max(math.hypot(v[0], v[1]) for v in verts) == pytest.approx(0.7)
    assert bpy.data.materials.new.call_args.args == ("VaseMaterial",)


def test_the_staircase_has_one_closed_box_per_step(monkeypatch):
    stand_in_bpy(monkeypatch)
    names = runpy.run_path(str(starters.SCRIPTS / "staircase.py"), run_name="__main__")
    verts, faces = names["staircase_mesh"]()
    assert (len(verts), len(faces)) == (8 * names["STEPS"], 6 * names["STEPS"])
    for i in range(names["STEPS"]):
        box = verts[8 * i:8 * i + 8]
        centre = np.mean(box, axis=0)
        for face in faces[6 * i:6 * i + 6]:
            n, middle = facing(verts, face)
            assert np.dot(n, middle - centre) > 0, (i, face)  # every face of every box looks outward
    assert max(v[2] for v in verts) == pytest.approx(names["STEPS"] * names["RISE"])


def forward(euler):
    """Where a Blender camera with these Euler angles (XYZ order) looks: its -Z axis, turned by Rz @ Ry @ Rx."""
    rx, ry, rz = euler
    x = np.array([[1, 0, 0], [0, math.cos(rx), -math.sin(rx)], [0, math.sin(rx), math.cos(rx)]])
    y = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    z = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    return z @ y @ x @ np.array([0.0, 0.0, -1.0])


def test_the_studio_scene_points_its_camera_at_the_objects_under_a_sun(monkeypatch):
    bpy, made = stand_in_bpy(monkeypatch)
    bpy.data.lights.new.return_value = SimpleNamespace(energy=0)
    names = runpy.run_path(str(starters.SCRIPTS / "studio_scene.py"), run_name="__main__")
    camera = next(o for o in made.objects if o.name == "Camera")
    aim = np.array([0.0, 0.0, 0.8]) - np.array(camera.location)
    assert forward(camera.rotation_euler) == pytest.approx(aim / np.linalg.norm(aim), abs=1e-9)
    assert bpy.context.scene.camera is camera and bpy.data.lights.new.call_args.args == ("Sun", "SUN")
    assert bpy.data.lights.new.return_value.energy == names["SUN_STRENGTH"]
    for height in (-5.0, 0.0, 5.0):  # straight down, level and up: the formula holds at the edges as well
        target = np.array([1.0, 2.0, height])
        euler = names["look_at"]((0.0, 0.0, 0.0), tuple(target))
        assert forward(euler) == pytest.approx(target / np.linalg.norm(target), abs=1e-9)


def run_driver(monkeypatch, tmp_path, scene, user_script="pass\n"):
    """Run SPIKE's wrapper against a stand-in bpy whose scene is `scene`; returns (stand-in bpy, preview path)."""
    linked, rendered = [], []
    scene.objects = list(scene.objects)
    scene.collection = SimpleNamespace(objects=SimpleNamespace(link=lambda o: (linked.append(o), scene.objects.append(o))))
    scene.render = SimpleNamespace(image_settings=SimpleNamespace())
    scene.cycles = SimpleNamespace()

    def new_object(name, data):
        return SimpleNamespace(name=name, data=data, type=data.kind, location=None, rotation_euler=None)

    bpy = SimpleNamespace(
        context=SimpleNamespace(scene=scene),
        data=SimpleNamespace(cameras=SimpleNamespace(new=lambda name: SimpleNamespace(kind="CAMERA", clip_end=0)),
                             lights=SimpleNamespace(new=lambda name, kind: SimpleNamespace(kind="LIGHT", energy=0)),
                             objects=SimpleNamespace(new=new_object)),
        ops=SimpleNamespace(render=SimpleNamespace(render=lambda **kw: rendered.append(kw))),
        linked=linked, rendered=rendered)
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    script = tmp_path / "user.py"
    script.write_text(user_script, encoding="utf-8")
    preview = tmp_path / "out.preview.png"
    monkeypatch.setattr(sys, "argv", ["blender", "--background", "--", str(script), str(preview), "640", "360", "32"])
    runpy.run_path(str(blender.DRIVER), run_name="__main__")
    return bpy, preview


def cube(location=(0.0, 0.0, 0.0), size=2.0):
    return SimpleNamespace(type="MESH", location=location, dimensions=(size, size, size), hide_render=False)


def test_the_wrapper_adds_a_camera_and_a_light_aimed_at_the_scene_and_renders_to_the_chosen_path(monkeypatch, tmp_path):
    scene = SimpleNamespace(objects=[cube((4.0, 1.0, 2.0)), cube((6.0, 1.0, 2.0))], camera=None)
    bpy, preview = run_driver(monkeypatch, tmp_path, scene)
    camera, light = bpy.linked
    assert scene.camera is camera and camera.type == "CAMERA" and light.type == "LIGHT"
    aim = np.array([5.0, 1.0, 2.0]) - np.array(camera.location)  # the middle of the two boxes
    assert forward(camera.rotation_euler) == pytest.approx(aim / np.linalg.norm(aim), abs=1e-9)
    assert np.linalg.norm(aim) > 3 * math.sqrt(3)  # far enough to see both boxes
    assert scene.render.engine == "CYCLES" and scene.cycles.device == "CPU" and scene.cycles.samples == 32
    assert (scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage) == (640, 360, 100)
    assert scene.render.image_settings.file_format == "PNG" and scene.render.use_file_extension is False
    assert scene.render.filepath == str(preview) and bpy.rendered == [{"write_still": True}]


def test_a_script_cannot_change_where_or_how_the_preview_is_rendered(monkeypatch, tmp_path):
    evil = ("import bpy\nr = bpy.context.scene.render\nr.filepath = '/tmp/evil.png'\nr.engine = 'OTHER'\n"
            "r.resolution_x = 99999\nbpy.context.scene.cycles.samples = 100000\n")
    scene = SimpleNamespace(objects=[cube()], camera=SimpleNamespace(type="CAMERA"))
    bpy, preview = run_driver(monkeypatch, tmp_path, scene, evil)
    assert scene.render.filepath == str(preview) and scene.render.engine == "CYCLES"
    assert (scene.render.resolution_x, scene.cycles.samples) == (640, 32)
    assert bpy.linked[0].type == "LIGHT" and len(bpy.linked) == 1  # it had a camera: only the light was added


def test_the_wrapper_adds_nothing_when_the_script_made_a_camera_and_a_light(monkeypatch, tmp_path):
    scene = SimpleNamespace(objects=[cube(), SimpleNamespace(type="LIGHT")], camera=SimpleNamespace(type="CAMERA"))
    bpy, _ = run_driver(monkeypatch, tmp_path, scene)
    assert bpy.linked == [] and len(bpy.rendered) == 1


def test_a_script_that_raises_is_never_followed_by_a_render(monkeypatch, tmp_path):
    scene = SimpleNamespace(objects=[cube()], camera=None)
    holder = {}
    with pytest.raises(RuntimeError, match="boom"):
        try:
            run_driver(monkeypatch, tmp_path, scene, "raise RuntimeError('boom')\n")
        finally:
            holder["bpy"] = sys.modules["bpy"]
    assert holder["bpy"].rendered == [] and holder["bpy"].linked == []


# ---------------------------------------------------------------- Godot: the scaffold
PLAN = {
    "folder": "games/runner", "name": "Runner", "root_type": "Node2D", "root_script": "main.gd",
    "scripts": [{"path": "main.gd", "code": "extends Node2D\n\n\nfunc _ready() -> void:\n\tprint(\"go\")"},
                {"path": "scripts/player.gd", "code": "extends CharacterBody2D\n"}],
    "nodes": [{"name": "Player", "type": "CharacterBody2D", "script": "scripts/player.gd",
               "properties": {"position": "=Vector2(100, 50)", "visible": True}},
              {"name": "Sprite", "type": "Sprite2D", "parent": "Player", "properties": {"scale": "=Vector2(2, 2)"}},
              {"name": "Score", "type": "Label", "parent": "Main", "properties": {"text": "Score: \"0\"", "z_index": 3}}],
}

MAIN_TSCN = """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://main.gd" id="1"]
[ext_resource type="Script" path="res://scripts/player.gd" id="2"]

[node name="Main" type="Node2D"]
script = ExtResource("1")

[node name="Player" type="CharacterBody2D" parent="."]
script = ExtResource("2")
position = Vector2(100, 50)
visible = true

[node name="Sprite" type="Sprite2D" parent="Player"]
scale = Vector2(2, 2)

[node name="Score" type="Label" parent="."]
text = "Score: \\"0\\""
z_index = 3
"""


async def test_the_scaffold_writes_the_files_a_godot_4_project_needs(ws):
    result = await GodotScaffold(ws).run(PLAN)
    assert result.ok, result.content
    root = ws.root / "games" / "runner"
    assert files_under(root) == ["main.gd", "main.tscn", "project.godot", "scripts", "scripts/player.gd"]
    assert (root / "project.godot").read_text(encoding="utf-8") == (
        "; Engine configuration file, written by SPIKE. Edit it in Godot (Project > Project Settings) or by hand.\n\n"
        'config_version=5\n\n[application]\n\nconfig/name="Runner"\nrun/main_scene="res://main.tscn"\n'
        'config/features=PackedStringArray("4.0")\n\n[display]\n\nwindow/size/viewport_width=1152\n'
        "window/size/viewport_height=648\n")
    assert (root / "main.tscn").read_text(encoding="utf-8") == MAIN_TSCN
    assert (root / "main.gd").read_text(encoding="utf-8").endswith('print("go")\n')
    assert (root / "scripts" / "player.gd").read_text(encoding="utf-8") == "extends CharacterBody2D\n"
    assert result.data["file"] == "games/runner/project.godot"
    assert "godot_check" in result.content and "games/runner" in result.content


async def test_a_plan_without_scripts_gets_a_main_script_that_runs_when_the_game_starts(ws):
    result = await GodotScaffold(ws).run({"folder": "hello", "root_type": "Node3D", "name": 'He said "hi"'})
    assert result.ok
    root = ws.root / "hello"
    assert (root / "main.gd").read_text(encoding="utf-8") == (
        'extends Node3D\n\n\nfunc _ready() -> void:\n\tprint("Hello from SPIKE")\n')
    assert (root / "main.tscn").read_text(encoding="utf-8") == (
        '[gd_scene load_steps=2 format=3]\n\n[ext_resource type="Script" path="res://main.gd" id="1"]\n\n'
        '[node name="Main" type="Node3D"]\nscript = ExtResource("1")\n')
    assert 'config/name="He said \\"hi\\""' in (root / "project.godot").read_text(encoding="utf-8")
    bare = await GodotScaffold(ws).run({"folder": "bare", "scripts": [{"path": "x.gd", "code": "extends Node"}]})
    assert bare.ok and (ws.root / "bare" / "main.tscn").read_text(encoding="utf-8") == (
        '[gd_scene format=3]\n\n[node name="Main" type="Node2D"]\n')


@pytest.mark.parametrize("change, expected", [
    ({"folder": "../outside"}, "outside the workspace"), ({"folder": "/tmp/spike-a18-game"}, "outside the workspace"),
    ({"folder": ""}, "`folder` is required"),
    ({"nodes": [{"name": "Bad Name", "type": "Node"}]}, "plain name"), ({"nodes": [{"name": "A", "type": "node"}]}, "Godot class"),
    ({"nodes": [{"name": "A", "type": "Node", "parent": "Nowhere"}]}, "not the root"),
    ({"nodes": [{"name": "A", "type": "Node"}, {"name": "A", "type": "Node"}]}, "two nodes would have the path A"),
    ({"nodes": [{"name": "A", "type": "Node", "script": "ghost.gd"}]}, "not in `scripts`"),
    ({"nodes": [{"name": "A", "type": "Node", "properties": {"bad key": 1}}]}, "Godot properties"),
    ({"nodes": [{"name": "A", "type": "Node", "properties": {"x": [1, 2]}}]}, "must be a number"),
    ({"nodes": [{"name": "A", "type": "Node", "properties": {"x": "=1\n[node name=\"Evil\"]"}}]}, "one line"),
    ({"nodes": [{"name": "A", "type": "Node", "properties": {"x": float("inf")}}]}, "finite"),
    ({"nodes": ["A"]}, "must be an object"), ({"nodes": [{"name": f"N{i}", "type": "Node"} for i in range(201)]}, "at most 200"),
    ({"scripts": [{"path": "../up.gd", "code": "x"}]}, "relative .gd path"),
    ({"scripts": [{"path": "/etc/x.gd", "code": "x"}]}, "relative .gd path"),
    ({"scripts": [{"path": "a.txt", "code": "x"}]}, "relative .gd path"),
    ({"scripts": [{"path": "a b.gd", "code": "x"}]}, "relative .gd path"),
    ({"scripts": [{"path": "a.gd", "code": "x"}, {"path": "a.gd", "code": "y"}]}, "listed twice"),
    ({"scripts": [{"path": "a.gd", "code": 5}]}, "`code` must be text"), ({"scripts": "main.gd"}, "must be a list"),
    ({"root_type": "node2d"}, "Godot class"), ({"root_script": "ghost.gd"}, "not in `scripts`"),
    ({"width": 10}, "between 128 and 7680"), ({"height": True}, "between 128 and 7680")])
async def test_a_scaffold_plan_that_would_escape_or_break_the_scene_is_refused_and_nothing_is_written(ws, change, expected):
    tool = GodotScaffold(ws)
    plan = {"folder": "game", **change}
    result = await tool.run(plan)
    assert not result.ok and expected in result.content
    assert files_under(ws.root) == [] and tool.targets(plan) == []
    assert not Path("/tmp/spike-a18-game").exists()


async def test_the_scaffold_does_not_overwrite_a_project_unless_asked(ws):
    tool = GodotScaffold(ws)
    assert (await tool.run({"folder": "g", "name": "One"})).ok
    again = await tool.run({"folder": "g", "name": "Two"})
    assert not again.ok and "already has a project.godot" in again.content
    assert 'config/name="One"' in (ws.root / "g" / "project.godot").read_text(encoding="utf-8")
    assert (await tool.run({"folder": "g", "name": "Two", "replace": True})).ok
    assert 'config/name="Two"' in (ws.root / "g" / "project.godot").read_text(encoding="utf-8")
    (ws.root / "file").write_text("x", encoding="utf-8")
    assert "is a file" in (await tool.run({"folder": "file"})).content


async def test_a_symlink_inside_the_project_cannot_lead_a_scaffold_write_elsewhere(ws, tmp_path):
    outside = tmp_path / "outside.gd"
    outside.write_text("keep me\n", encoding="utf-8")
    (ws.root / "g").mkdir()
    try:
        (ws.root / "g" / "main.gd").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")
    result = await GodotScaffold(ws).run({"folder": "g", "scripts": [{"path": "main.gd", "code": "extends Node"}]})
    assert not result.ok and "outside the workspace" in result.content
    assert outside.read_text(encoding="utf-8") == "keep me\n"


async def test_the_scaffold_asks_like_write_file_and_lists_what_it_would_write_for_undo(ws, bin_dir):
    tool = GodotScaffold(ws)
    assert tool.risk == "write" and tool.default_policy == "ask"
    events = await drive([tool], call("godot_scaffold", {"folder": "g"}), "deny")
    assert asked(events) and not result_of(events)["ok"] and files_under(ws.root) == []
    assert [p.relative_to(ws.root).as_posix() for p in tool.targets({"folder": "g"})] == [
        "g/project.godot", "g/main.tscn", "g/main.gd"]


# ---------------------------------------------------------------- Godot: the headless check
async def scaffold(ws, **change):
    result = await GodotScaffold(ws).run({**PLAN, **change})
    assert result.ok, result.content
    return ws.root / PLAN["folder"]


async def test_a_passing_check_parses_every_script_and_loads_the_main_scene(ws, bin_dir):
    project = await scaffold(ws)
    result = await GodotCheck(ws, OFF).run({"folder": "games/runner"})
    assert result.ok and result.data["passed"] is True, result.content
    assert result.content.splitlines()[0] == ("godot check passed (2 scripts parsed, the main scene loaded) in "
                                              "games/runner with Godot 4.2.1.stable.fake")
    argvs = [c["argv"] for c in fakes.calls(bin_dir, "godot")]
    assert argvs == [
        ["--version"],
        ["--headless", "--path", str(project), "--check-only", "--script", "res://main.gd"],
        ["--headless", "--path", str(project), "--check-only", "--script", "res://scripts/player.gd"],
        ["--headless", "--path", str(project), "--quit"]]
    assert all(Path(c["cwd"]).resolve() == ws.root for c in fakes.calls(bin_dir, "godot"))
    ui = result.data["ui"]
    assert ui["kind"] == "godot_check" and ui["passed"] is True and ui["project"] == "games/runner"
    assert ui["version"] == "4.2.1.stable.fake" and ui["scripts"] == 2
    assert [(c["kind"], c["name"], c["ok"]) for c in ui["checks"]] == [
        ("script", "main.gd", True), ("script", "scripts/player.gd", True), ("scene", "main.tscn", True)]
    assert result.content.splitlines()[-1].startswith(NOTE)


async def test_a_script_with_a_parse_error_fails_the_check_and_the_errors_come_back(ws, bin_dir):
    plan = {**PLAN, "scripts": [PLAN["scripts"][0], {"path": "scripts/player.gd", "code": "extends Node  # FAKE_PARSE_ERROR"}]}
    await GodotScaffold(ws).run(plan)
    result = await GodotCheck(ws, OFF).run({"folder": "games/runner"})
    assert result.ok and result.data["passed"] is False  # the tool ran; its verdict is in the result
    first = result.content.splitlines()[0]
    assert first == "godot check FAILED (1 of 3 checks) in games/runner with Godot 4.2.1.stable.fake"
    assert '- scripts/player.gd: SCRIPT ERROR: Parse Error: Identifier "oops" not declared' in result.content
    checks = {c["name"]: c for c in result.data["ui"]["checks"]}
    assert checks["main.gd"]["ok"] and not checks["scripts/player.gd"]["ok"] and checks["main.tscn"]["ok"]
    assert any("Failed to load script" in p for p in checks["scripts/player.gd"]["problems"])


async def test_a_scene_that_prints_an_error_fails_the_check_even_when_godot_exits_with_zero(ws, bin_dir):
    plan = {**PLAN, "nodes": [{"name": "Label", "type": "Label", "properties": {"text": "FAKE_LOAD_ERROR"}}]}
    await GodotScaffold(ws).run(plan)
    result = await GodotCheck(ws, OFF).run({"folder": "games/runner"})
    assert result.data["passed"] is False and "- main.tscn: ERROR: Failed to load scene" in result.content
    assert [c["ok"] for c in result.data["ui"]["checks"]] == [True, True, False]


async def test_the_harmless_leak_notice_at_exit_is_not_an_error():
    assert godot.problems("ERROR: 2 resources still in use at exit (run with --verbose)\nWARNING: x\n") == []
    assert godot.problems("ok\n  SCRIPT ERROR: Parse Error: x\nERROR: y\nParse Error: z\nnot ERROR: w\n") == [
        "SCRIPT ERROR: Parse Error: x", "ERROR: y", "Parse Error: z"]


async def test_a_missing_godot_is_reported_with_where_to_get_it_and_nothing_is_asked(ws, no_programs):
    await scaffold(ws)
    tool = GodotCheck(ws, OFF)
    assert tool.review({"folder": "games/runner"}).policy == "deny"
    events = await drive([tool], call("godot_check", {"folder": "games/runner"}), policies={"godot_check": "allow"})
    assert not asked(events)
    content = result_of(events)["content"]
    assert not result_of(events)["ok"] and "https://godotengine.org/download/" in content and "`godot` or `godot4`" in content
    assert "SPIKE never downloads" in content and "nunca lo descarga" in content
    assert "is not installed" in (await tool.run({"folder": "games/runner"})).content


async def test_godot_3_is_not_used_but_godot4_on_the_path_is(ws, bin_dir, tmp_path):
    await scaffold(ws)
    fakes.install(bin_dir, "godot", fakes.GODOT, version="3.5.3.stable.fake")
    refused = await GodotCheck(ws, OFF).run({"folder": "games/runner"})
    assert not refused.ok and "Godot 4 is needed" in refused.content and "3.5.3.stable.fake" in refused.content
    assert [c["argv"] for c in fakes.calls(bin_dir, "godot")][-1] == ["--version"]  # nothing else was started
    fakes.install(bin_dir, "godot4", fakes.GODOT, version="4.3.0.stable.fake")
    used = await GodotCheck(ws, OFF).run({"folder": "games/runner"})
    assert used.data["passed"] and used.data["ui"]["version"] == "4.3.0.stable.fake"
    assert fakes.calls(bin_dir, "godot4")[1]["argv"][:2] == ["--headless", "--path"]


async def test_a_denied_godot_check_runs_nothing(ws, bin_dir):
    await scaffold(ws)
    events = await drive([GodotCheck(ws, OFF)], call("godot_check", {"folder": "games/runner"}), "deny")
    ask = asked(events)[0]
    assert ask["tool"] == "godot_check" and ask["risk"] == "execute" and ask["code"] == "godot_check"
    assert ask["arguments"] == {"folder": "games/runner"} and not result_of(events)["ok"]
    assert fakes.calls(bin_dir, "godot") == []


async def test_a_godot_check_that_is_approved_through_the_loop_returns_the_card_data(ws, bin_dir):
    await scaffold(ws)
    events = await drive([GodotCheck(ws, OFF)], call("godot_check", {"folder": "games/runner"}))
    result = result_of(events)
    assert len(asked(events)) == 1 and result["ok"] and result["ui"]["passed"] is True
    assert "file" not in result


async def test_godot_check_stays_inside_the_workspace_and_needs_a_project(ws, bin_dir):
    tool = GodotCheck(ws, OFF)
    outside = await tool.run({"folder": "../elsewhere"})
    assert not outside.ok and "outside the workspace" in outside.content
    (ws.root / "empty").mkdir()
    none = await tool.run({"folder": "empty"})
    assert not none.ok and "has no project.godot" in none.content and "godot_scaffold" in none.content
    assert fakes.calls(bin_dir, "godot") == []


async def test_a_godot_check_that_hangs_is_stopped_and_the_rest_is_reported_as_out_of_time(ws, bin_dir, monkeypatch):
    await scaffold(ws)
    monkeypatch.setenv("FAKE_MODE", "hang")
    result = await asyncio.wait_for(GodotCheck(ws, OFF).run({"folder": "games/runner", "timeout_s": 1}), 60)
    assert result.ok and result.data["passed"] is False
    problems = [c["problems"][0] for c in result.data["ui"]["checks"]]
    assert problems[0].startswith("timed out after 1 s") and problems[1:] == ["no time left: raise timeout_s"] * 2


async def test_only_the_first_scripts_are_checked_and_the_result_says_so(ws, bin_dir, monkeypatch):
    monkeypatch.setattr(godot, "CHECKED_SCRIPTS", 2)
    await scaffold(ws, scripts=[{"path": f"s{i}.gd", "code": "extends Node"} for i in range(4)], root_script="s0.gd", nodes=[])
    result = await GodotCheck(ws, OFF).run({"folder": "games/runner"})
    assert "note: 2 more scripts were not checked (the limit is 2)" in result.content
    assert [c["name"] for c in result.data["ui"]["checks"]] == ["s0.gd", "s1.gd", "main.tscn"]
    assert result.data["ui"]["not_checked"] == 2


def test_the_godot_cache_folder_is_not_searched_for_scripts(tmp_path):
    (tmp_path / ".godot").mkdir()
    (tmp_path / ".godot" / "cache.gd").write_text("x", encoding="utf-8")
    (tmp_path / "b.gd").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.gd").write_text("x", encoding="utf-8")
    assert godot.scripts_in(tmp_path) == ["b.gd", "sub/a.gd"]


# ---------------------------------------------------------------- pure helpers
def test_the_command_line_quotes_every_argument_for_the_shell():
    line = command_line(["/opt/my blender/blender", "--python", "a b.py", "it's"])
    assert "my blender" in line and line != " ".join(["/opt/my blender/blender", "--python", "a b.py", "it's"])
    assert tail("x" * 10, 5) == "[… 5 chars cut …]\nxxxxx" and tail("short") == "short"


def test_a_png_is_read_for_its_size_and_anything_else_is_not(tmp_path):
    good = tmp_path / "a.png"
    good.write_bytes(fakes.png(7, 5))
    assert blender.preview_size(good) == (7, 5)
    bad = tmp_path / "b.png"
    bad.write_bytes(b"not a png at all, just text")
    assert blender.preview_size(bad) is None and blender.preview_size(tmp_path / "missing.png") is None
    with pytest.raises(BlenderError):
        blender.paths(Workspace(tmp_path), "../x.py")


def test_the_program_helpers_find_the_first_of_their_names(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert BLENDER.find() is None and GODOT.found() == []
    fakes.install(tmp_path, "godot4", fakes.GODOT)
    assert [Path(p).stem for p in GODOT.found()] == ["godot4"] and BLENDER.find() is None


# ---------------------------------------------------------------- wiring
def test_the_tools_are_registered_in_every_workspace_and_ask_by_default(tmp_path, monkeypatch):
    for name, value in (("SPIKE_HOME", tmp_path / "home"), ("SPIKE_WORKSPACE", tmp_path / "app-ws"),
                        ("SPIKE_NO_KEYRING", "1")):
        monkeypatch.setenv(name, str(value))
    state = AppState(home=tmp_path / "home", provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    names = {"blender_render", "godot_scaffold", "godot_check"}
    assert names <= set(state.tools.names()) and names <= set(state.tools_in(tmp_path / "other").names())
    assert names <= known_tools()
    client = TestClient(create_app(state, allowed_hosts={"testserver"}))
    listed = {t["name"]: t for t in client.get("/api/tools").json() if t["name"] in names}
    assert {n: (t["risk"], t["default_policy"], t["policy"]) for n, t in listed.items()} == {
        "blender_render": ("execute", "ask", "ask"), "godot_scaffold": ("write", "ask", "ask"),
        "godot_check": ("execute", "ask", "ask")}
    assert [t.name for t in maker_tools(Workspace(tmp_path), OFF)] == ["blender_render", "godot_scaffold", "godot_check"]
    assert state.tools.get("blender_render").runner.sandbox is state.sandbox  # the app's sandbox setting applies


def test_the_code_specialist_has_the_tools_and_blender_and_godot_requests_reach_it():
    catalog = load_catalog()
    assert {"blender_render", "godot_scaffold", "godot_check"} <= set(catalog.specialists["code"].tools)
    router = LexicalRouter(catalog)
    for question in ("Make me a vase in Blender and render it", "Crea un juego sencillo en Godot con GDScript",
                     "Write a GDScript for a player that jumps"):
        assert router.route(question).specialists == ["code"], question
