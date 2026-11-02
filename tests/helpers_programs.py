"""Fake `blender` and `godot` programs for the tests (and the browser test): small Python scripts on a temporary PATH
that record their argv and write what the real program would. No real Blender or Godot is ever started.

The fake Blender takes SPIKE's command line, finds the script and the preview path after the `--`, and writes a real
(tiny) PNG there, or misbehaves as `FAKE_MODE` says: `crash` (a traceback and exit code 1), `nopng` (exit code 0, no
file) or `hang` (never returns). The fake Godot answers `--version` with the `version` it was installed with, fails
`--check-only` on a script that contains FAKE_PARSE_ERROR, and fails the `--quit` run on a main scene that contains
FAKE_LOAD_ERROR (it prints an error line but exits with code 0, so the tests show the output is read as well as the
exit code). Each call is appended to `<name>.calls` beside the fake, one JSON object per line."""

from __future__ import annotations

import json
import os
import struct
import sys
import zlib
from pathlib import Path


def png(width: int = 64, height: int = 36, rgb: tuple[int, int, int] = (200, 90, 40)) -> bytes:
    """A real PNG of one colour."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


COMMON = r"""
import json, os, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ARGV = sys.argv[1:]
with (HERE / (NAME + ".calls")).open("a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": ARGV, "cwd": os.getcwd()}) + "\n")
MODE = os.environ.get("FAKE_MODE", "")
"""

BLENDER = COMMON + r"""
print("Blender 4.2.0 (fake)")
if "--" not in ARGV:
    sys.exit(0)
script, preview = ARGV[ARGV.index("--") + 1:][:2]
Path(script).read_text(encoding="utf-8")
if MODE == "hang":
    time.sleep(60)
if MODE == "crash":
    print("Traceback (most recent call last):\n  File \"scene.py\", line 3, in <module>\n"
          "NameError: name 'oops' is not defined", file=sys.stderr)
    sys.exit(1)
if MODE == "nopng":
    sys.exit(0)
Path(preview).write_bytes(PNG)
print("Saved: " + preview)
"""

GODOT = COMMON + r"""
if "--version" in ARGV:
    print(VERSION)
    sys.exit(0)
if MODE == "hang":
    time.sleep(60)
project = Path(ARGV[ARGV.index("--path") + 1])
if "--check-only" in ARGV:
    script = ARGV[ARGV.index("--script") + 1]
    if "FAKE_PARSE_ERROR" in (project / script.removeprefix("res://")).read_text(encoding="utf-8"):
        print('SCRIPT ERROR: Parse Error: Identifier "oops" not declared in the current scope.')
        print("          at: GDScript::reload (" + script + ":3)")
        print('ERROR: Failed to load script "' + script + '" with error "Parse error".')
        sys.exit(1)
    sys.exit(0)
if "--quit" in ARGV:
    if "FAKE_LOAD_ERROR" in (project / "main.tscn").read_text(encoding="utf-8"):
        print("ERROR: Failed to load scene 'res://main.tscn'.")
    else:
        print("Godot Engine v4.2.1.stable.fake")
        print("ERROR: 2 resources still in use at exit (run with --verbose for details).")
"""


def install(folder: Path, name: str, source: str, version: str = "4.2.1.stable.fake") -> Path:
    """Put a fake program called `name` in `folder` (a script with a shebang, or a .cmd file on Windows)."""
    folder.mkdir(parents=True, exist_ok=True)
    body = f"NAME = {name!r}\nPNG = {png()!r}\nVERSION = {version!r}\n" + source
    if os.name == "nt":
        (folder / f"{name}.py").write_text(body, encoding="utf-8")
        program = folder / f"{name}.cmd"
        program.write_text(f'@"{sys.executable}" "{folder / (name + ".py")}" %*\n', encoding="utf-8")
        return program
    program = folder / name
    program.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    program.chmod(0o755)
    return program


def calls(folder: Path, name: str) -> list[dict]:
    """What the fake `name` in `folder` was asked to do, oldest first."""
    log = folder / f"{name}.calls"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
