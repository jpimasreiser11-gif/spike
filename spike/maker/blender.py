"""The Blender side of `blender_render`: which files a call writes, the command line, and the preview it must produce.
The model's script is saved as it is next to a copy of `render_driver.py` (SPIKE's wrapper that runs it and renders);
the preview goes to a path SPIKE builds from the script's name, never to one the model gave."""

from __future__ import annotations

import ast
import re
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from spike.maker import starters
from spike.maker.starters import StarterError
from spike.tools.builtin import Workspace

DRIVER = starters.SCRIPTS / "render_driver.py"
PREVIEW_SIZE = (640, 360)  # a small preview: a render for looking at, not a final image
SAMPLES = 32
MAX_SCRIPT = 200_000
PNG = b"\x89PNG\r\n\x1a\n"


class BlenderError(ValueError):
    pass


@dataclass
class Job:
    """What one call will write: the model's script, SPIKE's wrapper beside it, and the preview."""

    script: Path
    driver: Path
    preview: Path
    text: str


def paths(workspace: Workspace, path: str) -> tuple[Path, Path, Path]:
    """(script, wrapper, preview) for a script path inside the workspace; the other two sit beside the script."""
    if not path.lower().endswith(".py"):
        raise BlenderError(f"the script path must end in .py, not '{path}'")
    try:
        script = workspace.resolve(path)
    except PermissionError as exc:
        raise BlenderError(str(exc)) from exc
    if script.is_dir():
        raise BlenderError(f"'{path}' is a folder, not a script")
    return script, script.with_name(f"{script.stem}.render.py"), script.with_name(f"{script.stem}.preview.png")


def plan(workspace: Workspace, args: dict[str, Any]) -> Job:
    """Check a call's arguments and say what it would write. Nothing is written or run."""
    script, starter = str(args.get("script") or ""), str(args.get("starter") or "")
    if bool(script.strip()) == bool(starter):
        raise BlenderError("give either `script` (your bpy code) or `starter` (a ready-made script), not both and "
                           "not neither")
    if starter:
        try:
            script = starters.build(starter, args.get("params"))
        except StarterError as exc:
            raise BlenderError(str(exc)) from exc
    if len(script) > MAX_SCRIPT:
        raise BlenderError(f"the script is too long ({len(script)} characters, at most {MAX_SCRIPT})")
    try:
        ast.parse(script)
    except SyntaxError as exc:
        raise BlenderError(f"the script is not valid Python (line {exc.lineno}: {exc.msg}); Blender was not "
                           "started") from exc
    where = str(args.get("path") or f"blender/{starter or 'scene'}.py")
    return Job(*paths(workspace, where), script if script.endswith("\n") else script + "\n")


def prepare(job: Job) -> None:
    """Save the script and the wrapper; an older preview is removed so a failed run cannot show a stale one."""
    job.script.parent.mkdir(parents=True, exist_ok=True)
    job.script.write_text(job.text, encoding="utf-8")
    job.driver.write_text(DRIVER.read_text(encoding="utf-8"), encoding="utf-8")
    job.preview.unlink(missing_ok=True)


def command(exe: str, job: Job) -> list[str]:
    """`blender --background --factory-startup --python <wrapper> -- <script> <preview> <width> <height> <samples>`.
    `--python-exit-code 1` makes a script that raises end Blender with an error instead of exit code 0."""
    return [exe, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(job.driver), "--",
            str(job.script), str(job.preview), str(PREVIEW_SIZE[0]), str(PREVIEW_SIZE[1]), str(SAMPLES)]


def preview_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of the PNG at `path`, or None when it is missing or not a PNG."""
    try:
        with path.open("rb") as f:
            head = f.read(24)
    except OSError:
        return None
    if len(head) < 24 or not head.startswith(PNG) or head[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", head[16:24])
    return (width, height) if width and height else None


def blender_version(output: str) -> str:
    """The version Blender printed when it started ("Blender 4.2.0 ..."), if any."""
    found = re.search(r"^Blender (\d+\.\d+(?:\.\d+)?)", output, re.MULTILINE)
    return found[1] if found else ""
