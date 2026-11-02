"""Programs SPIKE drives only when the user already has them: Blender and Godot 4. Each is looked up on the PATH with
`shutil.which`; SPIKE never downloads or installs one, and says where to get it when it is missing. A run goes through
`run_command`'s machinery, so it happens in the workspace, with a timeout that kills the whole process group, under the
`sandbox` setting (`required` isolates it; under `auto` the user's approval of the call is what stands, as for
`run_command`) and with its output capped."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from spike.dev.tools import RunCommand
from spike.tools.sandbox import NOTE, strip_note

DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600  # what run_command allows
TAIL = 3000  # characters of a program's output kept for the model


@dataclass(frozen=True)
class Program:
    id: str
    label: str
    names: tuple[str, ...]  # what to look for on the PATH, in this order
    url: str
    en: str  # what to do when it is installed but not on the PATH
    es: str

    def find(self) -> str | None:
        return next(iter(self.found()), None)

    def found(self) -> list[str]:
        """Every executable of this program on the PATH, in order, without repeats."""
        out: list[str] = []
        for name in self.names:
            path = shutil.which(name)
            if path and path not in out:
                out.append(path)
        return out

    def missing(self) -> str:
        """Why nothing was run and how to get the program, in English and Spanish (the model answers in the user's)."""
        names = " or ".join(f"`{n}`" for n in self.names)
        return (f"{self.label} is not installed (no {names} on the PATH), so nothing was run. Get it free at "
                f"{self.url} or with your package manager, then try again. {self.en} SPIKE never downloads or "
                f"installs it. / {self.label} no está instalado (no hay {names} en el PATH), así que no se ejecutó "
                f"nada. Descárgalo gratis en {self.url} o con tu gestor de paquetes y vuelve a intentarlo. {self.es} "
                "SPIKE nunca lo descarga ni lo instala.")


BLENDER = Program(
    "blender", "Blender", ("blender",), "https://www.blender.org/download/",
    "If it is installed but not on the PATH, add its folder to the PATH (on macOS: ln -s "
    "/Applications/Blender.app/Contents/MacOS/Blender /usr/local/bin/blender).",
    "Si ya está instalado pero no está en el PATH, añade su carpeta al PATH (en macOS: ln -s "
    "/Applications/Blender.app/Contents/MacOS/Blender /usr/local/bin/blender).")
GODOT = Program(
    "godot", "Godot 4", ("godot", "godot4"), "https://godotengine.org/download/",
    "If it is installed but not on the PATH, add its folder to the PATH (on macOS: ln -s "
    "/Applications/Godot.app/Contents/MacOS/Godot /usr/local/bin/godot).",
    "Si ya está instalado pero no está en el PATH, añade su carpeta al PATH (en macOS: ln -s "
    "/Applications/Godot.app/Contents/MacOS/Godot /usr/local/bin/godot).")


@dataclass
class Ran:
    """One run of a program: its exit code and output, or why it did not finish (a timeout, a required sandbox)."""

    code: int | None = None
    output: str = ""
    problem: str = ""
    seconds: float = 0.0
    note: str = ""  # the last line of run_command's result: whether the run was isolated
    isolation: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.problem


def command_line(argv: Sequence[str]) -> str:
    """The shell line run_command takes for a list of arguments, quoted for this system's shell."""
    return subprocess.list2cmdline(list(argv)) if os.name == "nt" else shlex.join(argv)


def tail(text: str, size: int = TAIL) -> str:
    text = text.strip()
    return text if len(text) <= size else f"[… {len(text) - size} chars cut …]\n{text[-size:]}"


async def run_program(runner: RunCommand, argv: Sequence[str], timeout_s: float) -> Ran:
    """Run `argv` in the workspace the way `run_command` does (its sandbox, timeout and output cap)."""
    started = time.monotonic()
    result = await runner.run({"command": command_line(argv), "timeout_s": max(1, int(timeout_s))})
    last = result.content.rpartition("\n")[2]
    ran = Ran(seconds=time.monotonic() - started, note=last if last.startswith(NOTE) else "",
              isolation=result.data.get("isolation") or {})
    body = strip_note(result.content)
    done = re.match(r"exit code (-?\d+)(?:\n|$)", body)
    if done:
        ran.code, ran.output = int(done[1]), body[done.end():]
    else:
        ran.problem = body.removeprefix("error: ")
    return ran
