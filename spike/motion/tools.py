"""The render_video tool: an HTML or SVG scene in the workspace becomes an MP4, WebM or GIF next to it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spike.motion.render import FORMATS, MAX_FPS, MAX_SECONDS, SIZES, MotionError, render, scene_html
from spike.tools.base import Tool, ToolResult
from spike.tools.builtin import Workspace

SCENES = (".html", ".htm", ".svg")


class RenderVideo(Tool):
    name = "render_video"
    description = ("Turn an animated scene file in the workspace (HTML with CSS animations, SVG, canvas or JavaScript) "
                   "into a video: SPIKE plays it frame by frame on an exact clock and encodes MP4, WebM or GIF. Write "
                   "the scene with write_file first; the result lists any JavaScript errors to fix.")
    parameters = {"type": "object", "properties": {
        "scene": {"type": "string", "description": "the scene file, e.g. escena.html"},
        "output": {"type": "string", "description": "the video to write: .mp4 (plays everywhere), .webm or .gif"},
        "size": {"type": "string", "description": f"{', '.join(f'{k} ({w}x{h})' for k, (w, h) in SIZES.items())} "
                                                  "or WIDTHxHEIGHT; default 16:9"},
        "fps": {"type": "integer", "minimum": 1, "maximum": MAX_FPS, "description": "frames per second, default 30"},
        "seconds": {"type": "number", "description": f"length, at most {MAX_SECONDS}; default: the scene's "
                                                     '<meta name="spike-duration"> or when its last animation ends'}},
        "required": ["scene", "output"]}
    risk = "write"
    default_policy = "ask"

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def targets(self, args: dict[str, Any]) -> list[Path]:
        try:
            return [self.workspace.resolve(str(args["output"]))]
        except (PermissionError, KeyError):
            return []

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            scene = self.workspace.resolve(str(args.get("scene") or ""))
            out = self.workspace.resolve(str(args.get("output") or ""))
            if scene.suffix.lower() not in SCENES:
                raise MotionError(f"the scene must be {', '.join(SCENES)}, not {scene.name}")
            if out.suffix.lower() not in FORMATS:
                raise MotionError(f"the video must be {', '.join(FORMATS)}, not {out.name}")
            if not scene.is_file():
                raise MotionError(f"{args.get('scene')} does not exist: write the scene first")
            fps = args.get("fps")
            seconds = args.get("seconds")
            html = scene_html(scene.read_text(encoding="utf-8", errors="replace"), scene.suffix.lower())
            done = await render(html, out, size=args.get("size"), fps=30 if fps in (None, "") else int(fps),
                                seconds=None if seconds in (None, "") else float(seconds))
        except (MotionError, PermissionError, ValueError, TypeError) as exc:
            return ToolResult(ok=False, content=f"error: {exc}")
        root = self.workspace.root
        rel, scene_rel = out.relative_to(root).as_posix(), scene.relative_to(root).as_posix()
        lines = [f"rendered {rel}: {done.width}x{done.height}, {done.fps} fps, {done.seconds:g} s, {done.frames} frames, "
                 f"{done.codec}, {done.bytes // 1024} KB (length from {done.duration_from})"]
        lines += [f"note: {n}" for n in done.notes]
        if done.errors:
            lines.append("JavaScript errors in the scene (fix them and render again):\n" + "\n".join(
                f"- {e}" for e in done.errors))
        if done.blocked:
            lines.append("blocked (scenes render offline: put images and fonts inline as data: URLs): "
                         + ", ".join(done.blocked))
        ui = {"kind": "video", "path": rel, "scene": scene_rel, **{k: getattr(done, k) for k in (
            "format", "codec", "width", "height", "fps", "seconds", "frames", "bytes")}}
        return ToolResult(ok=True, content="\n".join(lines), data={"file": rel, "ui": ui})


def motion_tools(workspace: Workspace) -> list[Tool]:
    return [RenderVideo(workspace)]
