"""The tools of A18: `blender_render` (a bpy script, or a starter, becomes a rendered preview), `godot_scaffold` (a plan
becomes a minimal Godot 4 project) and `godot_check` (Godot, headless, parses its scripts and loads its scene). Blender
and Godot are the user's own programs, found on the PATH and never downloaded. Running either asks the user first (the
model's script or the project's GDScript runs on the computer), stays in the workspace, has a timeout and follows the
`sandbox` setting like `run_command`; the preview and the check show in the artifacts panel."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from spike.dev.tools import RunCommand
from spike.maker import blender, godot, starters
from spike.maker.blender import BlenderError
from spike.maker.godot import PlanError
from spike.maker.program import (
    BLENDER,
    DEFAULT_TIMEOUT_S,
    GODOT,
    MAX_TIMEOUT_S,
    Program,
    Ran,
    run_program,
    tail,
)
from spike.tools.base import Review, Tool, ToolResult
from spike.tools.builtin import Workspace
from spike.tools.sandbox import Sandbox

TIMEOUT = {"type": "integer", "description": f"seconds before the program is stopped; default {DEFAULT_TIMEOUT_S}, "
                                             f"at most {MAX_TIMEOUT_S}"}


def seconds(args: dict[str, Any]) -> int:
    """The timeout of a call, clamped; a value that is not a number means the default."""
    try:
        return max(1, min(int(args.get("timeout_s") or DEFAULT_TIMEOUT_S), MAX_TIMEOUT_S))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S


def failed(what: str, ran: Ran, why: str = "") -> ToolResult:
    """A program that did not finish well: why, then the end of what it printed and whether it was isolated."""
    why = why or ran.problem or f"it stopped with exit code {ran.code}"
    text = f"error: {what}: {why}" + (f"\n{tail(ran.output)}" if ran.output.strip() else "")
    return ToolResult(ok=False, content=f"{text}\n{ran.note}" if ran.note else text,
                      data={"isolation": ran.isolation} if ran.isolation else {})


class StartsProgram:
    """What the tools that start a program share: asking the user every time, refusing before anyone is asked when
    the program is missing (or the `sandbox` setting is `required` and the computer has none), and the isolation
    line."""

    program: Program
    reason: str
    name: str

    def __init__(self, workspace: Workspace, sandbox: Sandbox | None = None):
        self.workspace = workspace
        self.runner = RunCommand(workspace, sandbox)

    def review(self, args: dict[str, Any]) -> Review:
        if not self.program.found():
            return Review("deny", self.program.missing(), code=f"{self.program.id}_missing")
        return self.runner.review(args) or Review("ask", self.reason, code=self.name)

    def isolation(self, args: dict[str, Any]) -> dict[str, Any] | None:
        return self.runner.isolation(args)


class BlenderRender(StartsProgram, Tool):
    name = "blender_render"
    description = ("Render a 3D scene with Blender, which the user must have installed (SPIKE never downloads it). "
                   "Give `script`, a Blender Python (bpy) script that builds the scene, or `starter`, a ready-made "
                   "script, with optional `params`. SPIKE saves the script in the workspace (default "
                   "blender/scene.py), asks the user, runs it with `blender --background --factory-startup` and "
                   "renders a small PNG preview next to it, which opens in the artifacts panel. Blender starts from "
                   "its default scene (a cube, a camera and a light): clear it first if you do not want them. "
                   "Without a camera or a light SPIKE adds a simple one. Use only bpy and the standard library; the "
                   "script cannot choose where the preview goes.")
    parameters = {"type": "object", "properties": {
        "script": {"type": "string", "description": "the bpy script (or use `starter`)"},
        "starter": {"type": "string", "description": "a ready-made script to render (or use `script`)"},
        "params": {"type": "object", "additionalProperties": {"type": "number"},
                   "description": "numbers for the starter, e.g. {\"height\": 3}; the rest keep their defaults"},
        "path": {"type": "string", "description": "where to save the script in the workspace, ending in .py"},
        "timeout_s": TIMEOUT}}
    risk = "execute"
    default_policy = "ask"
    program = BLENDER
    reason = "It will run Blender with this script on your computer and save a preview in the workspace folder."

    def __init__(self, workspace: Workspace, sandbox: Sandbox | None = None):
        super().__init__(workspace, sandbox)
        props = self.parameters["properties"]
        self.parameters = {**self.parameters, "properties": {**props, "starter": {
            **props["starter"], "enum": list(starters.starters())}}}
        self.description = (f"{self.description}\n\nStarters, with their numbers as name range (default):\n"
                            f"{starters.catalog()}")

    def targets(self, args: dict[str, Any]) -> list[Path]:
        try:
            job = blender.plan(self.workspace, args)
        except BlenderError:
            return []
        return [job.script, job.driver, job.preview]

    async def run(self, args: dict[str, Any]) -> ToolResult:
        exe = BLENDER.find()
        if exe is None:
            return ToolResult(ok=False, content=f"error: {BLENDER.missing()}")
        try:
            job = blender.plan(self.workspace, args)
            blender.prepare(job)
        except (BlenderError, OSError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        ran = await run_program(self.runner, blender.command(exe, job), seconds(args))
        if not ran.ok:
            return failed("Blender", ran)
        size = blender.preview_size(job.preview)
        if size is None:
            return failed("Blender", ran, "it finished but wrote no preview image")
        root = self.workspace.root
        script, preview = job.script.relative_to(root).as_posix(), job.preview.relative_to(root).as_posix()
        version = blender.blender_version(ran.output)
        ui = {"kind": "blender_render", "script": script, "preview": preview, "width": size[0], "height": size[1],
              "engine": "Cycles (CPU)", "samples": blender.SAMPLES, "seconds": round(ran.seconds, 1),
              "bytes": job.preview.stat().st_size, "version": version, "log": tail(ran.output, 1500)}
        lines = [f"rendered {preview} from {script}: {size[0]}x{size[1]}, Cycles on the CPU, {blender.SAMPLES} "
                 f"samples, {ran.seconds:.1f} s" + (f" (Blender {version})" if version else ""),
                 f"The script is saved at {script}: change it with edit_file and render again, or open it in Blender."]
        if ran.note:
            lines.append(ran.note)
        return ToolResult(ok=True, content="\n".join(lines),
                          data={"file": preview, "ui": ui, "isolation": ran.isolation})


class GodotScaffold(Tool):
    name = "godot_scaffold"
    description = ("Create a minimal Godot 4 project (GDScript) in a workspace folder from your plan: project.godot, "
                   "a main scene main.tscn built from `nodes`, and the .gd files in `scripts`. With no scripts it "
                   "writes a main.gd that prints a greeting. It does not run anything; check the project with "
                   "godot_check. Node properties take numbers, true/false, text, or text starting with = for a Godot "
                   "expression, e.g. {\"position\": \"=Vector2(100, 50)\"}. List nodes parents first.")
    parameters = {"type": "object", "properties": {
        "folder": {"type": "string", "description": "project folder in the workspace, e.g. games/runner"},
        "name": {"type": "string", "description": "the game's title"},
        "root_type": {"type": "string", "description": "class of the root node: Node2D (default), Node3D, Control"},
        "root_name": {"type": "string", "description": "name of the root node, default Main"},
        "root_script": {"type": "string", "description": "a path from `scripts` to attach to the root"},
        "nodes": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "type": {"type": "string", "description": "Godot class, e.g. Sprite2D"},
            "parent": {"type": "string", "description": "\".\" for the root (default) or the path of an earlier node"},
            "script": {"type": "string", "description": "a path from `scripts`"},
            "properties": {"type": "object"}}, "required": ["name", "type"]}},
        "scripts": {"type": "array", "items": {"type": "object", "properties": {
            "path": {"type": "string", "description": "relative to the project, ending in .gd"},
            "code": {"type": "string", "description": "the GDScript"}}, "required": ["path", "code"]}},
        "width": {"type": "integer", "description": "window width in pixels, default 1152"},
        "height": {"type": "integer", "description": "window height in pixels, default 648"},
        "replace": {"type": "boolean", "description": "overwrite a project that already exists in the folder"}},
        "required": ["folder"]}
    risk = "write"
    default_policy = "ask"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def _files(self, args: dict[str, Any]) -> tuple[Path, dict[str, str]]:
        """(the project folder, its files by relative path); `PlanError` when the folder or the plan is not valid."""
        if not str(args.get("folder") or "").strip():
            raise PlanError("`folder` is required: the project folder in the workspace, e.g. games/runner")
        try:
            folder = self.workspace.resolve(str(args["folder"]))
        except PermissionError as exc:
            raise PlanError(str(exc)) from exc
        return folder, godot.files(godot.parse(args))

    def targets(self, args: dict[str, Any]) -> list[Path]:
        try:
            folder, written = self._files(args)
        except PlanError:
            return []
        return [folder / name for name in written]

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            folder, written = self._files(args)
            if folder.is_file():
                raise PlanError(f"{args['folder']} is a file, not a folder")
            if (folder / "project.godot").exists() and not args.get("replace"):
                raise PlanError(f"{args['folder']} already has a project.godot: choose another folder, or set "
                                "`replace` to overwrite that project")
            inside = Workspace(folder)
            for name, text in written.items():
                target = inside.resolve(name)  # a symlink inside the project cannot lead a write elsewhere
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
        except (PlanError, PermissionError, OSError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        rel = folder.relative_to(self.workspace.root).as_posix()
        return ToolResult(ok=True, content=f"created the Godot 4 project {rel} ({len(written)} files: "
                                           f"{', '.join(written)}). Check it with godot_check (folder \"{rel}\").",
                          data={"file": f"{rel}/project.godot" if rel != "." else "project.godot"})


class GodotCheck(StartsProgram, Tool):
    name = "godot_check"
    description = ("Check a Godot 4 project in the workspace without a window, with the user's own `godot` (SPIKE "
                   "never downloads it): every .gd script is parsed with `--check-only` and the project is started "
                   "for one frame so its main scene loads. The user approves each run, because the project's "
                   "GDScript really runs. The result says what passed and prints the errors Godot reported, so fix "
                   "them and check again.")
    parameters = {"type": "object", "properties": {
        "folder": {"type": "string", "description": "the project folder in the workspace (it holds project.godot)"},
        "timeout_s": TIMEOUT}, "required": ["folder"]}
    risk = "execute"
    default_policy = "ask"
    program = GODOT
    reason = "It will run Godot without a window on this project; the project's GDScript code runs on your computer."

    async def find_godot4(self, budget: float) -> tuple[str, str, list[str]]:
        """(program, its version, what was tried) for the first `godot` that says it is version 4 or newer."""
        tried: list[str] = []
        for candidate in GODOT.found():  # `godot` may be Godot 3 on a computer that also has `godot4`
            ran = await run_program(self.runner, godot.version_command(candidate), budget)
            found = godot.major_version(ran.output) if ran.ok else None
            said = found[1] if found else ran.problem or tail(ran.output, 200) or "no version"
            tried.append(f"{candidate}: {said}")
            if found and found[0] >= 4:
                return candidate, found[1], tried
        return "", "", tried

    async def run(self, args: dict[str, Any]) -> ToolResult:
        if not GODOT.found():
            return ToolResult(ok=False, content=f"error: {GODOT.missing()}")
        try:
            project = self.workspace.resolve(str(args.get("folder") or ""))
        except PermissionError as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        if not (project / "project.godot").is_file():
            return ToolResult(ok=False, content=f"error: {args.get('folder')} has no project.godot: create the "
                                                "project with godot_scaffold first")
        started = time.monotonic()
        deadline = started + seconds(args)
        exe, version, tried = await self.find_godot4(deadline - time.monotonic())
        if not exe:
            return ToolResult(ok=False, content="error: Godot 4 is needed but this was found: " + "; ".join(tried)
                              + f". Get Godot 4 free at {GODOT.url} / Se necesita Godot 4 pero se encontró: "
                              + "; ".join(tried) + f". Descarga Godot 4 gratis en {GODOT.url}")
        scripts = godot.scripts_in(project)
        runs = [("script", name, godot.check_command(exe, project, name)) for name in scripts[:godot.CHECKED_SCRIPTS]]
        runs.append(("scene", godot.MAIN_SCENE, godot.load_command(exe, project)))
        checks: list[dict[str, Any]] = []
        note = ""
        for kind, name, argv in runs:
            if deadline - time.monotonic() <= 0:
                checks.append({"kind": kind, "name": name, "ok": False, "problems": ["no time left: raise timeout_s"]})
                continue
            ran = await run_program(self.runner, argv, deadline - time.monotonic())
            note = ran.note or note
            found = godot.problems(ran.output)
            if ran.problem:
                found = [ran.problem, *found]
            elif ran.code != 0 and not found:
                said = f": {tail(ran.output, 300)}" if ran.output.strip() else ""
                found = [f"Godot exited with code {ran.code}{said}"]
            checks.append({"kind": kind, "name": name, "ok": ran.ok and not found, "problems": found})
        rel = project.relative_to(self.workspace.root).as_posix()
        bad = [c for c in checks if not c["ok"]]
        left_out = max(0, len(scripts) - godot.CHECKED_SCRIPTS)
        head = (f"godot check passed ({len(scripts)} scripts parsed, the main scene loaded)" if not bad else
                f"godot check FAILED ({len(bad)} of {len(checks)} checks)") + f" in {rel} with Godot {version}"
        lines = [head, *(f"- {c['name']}: " + "; ".join(c["problems"]) for c in bad)]
        if left_out:
            lines.append(f"note: {left_out} more scripts were not checked (the limit is {godot.CHECKED_SCRIPTS})")
        if note:
            lines.append(note)
        ui = {"kind": "godot_check", "project": rel, "passed": not bad, "version": version, "checks": checks,
              "scripts": len(scripts), "not_checked": left_out, "seconds": round(time.monotonic() - started, 1)}
        return ToolResult(ok=True, content="\n".join(lines), data={"ui": ui, "passed": not bad})


def maker_tools(workspace: Workspace, sandbox: Sandbox | None = None) -> list[Tool]:
    return [BlenderRender(workspace, sandbox), GodotScaffold(workspace), GodotCheck(workspace, sandbox)]
