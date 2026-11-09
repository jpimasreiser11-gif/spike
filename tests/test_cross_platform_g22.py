"""G22 — Windows & Linux cross-platform audit and tests."""

from __future__ import annotations

import ast
import io
import os
import stat
import sys
import types
import zipfile
from pathlib import Path, PosixPath
from types import SimpleNamespace

import pytest

from spike.dev.tools import _kill
from spike.forge import evaluate as forge_eval
from spike.launcher.app import Instance
from spike.packs import install_skills
from spike.runtime import hardware
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig

ROOT = Path(__file__).resolve().parent.parent


def test_no_missing_utf8_encoding_in_read_or_write_text() -> None:
    offenders: list[str] = []
    for folder in ("spike", "evals", "scripts"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in ("read_text", "write_text"):
                        kw = {k.arg for k in node.keywords}
                        if "encoding" not in kw:
                            rel = path.relative_to(ROOT).as_posix()
                            offenders.append(f"{rel}:{node.lineno} {node.func.attr}()")
                    elif (
                        node.func.attr in ("run", "Popen", "check_output")
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "subprocess"
                        and folder == "spike"
                    ):
                        kw = {k.arg for k in node.keywords}
                        if "text" in kw and "encoding" not in kw:
                            rel = path.relative_to(ROOT).as_posix()
                            offenders.append(f"{rel}:{node.lineno} subprocess.{node.func.attr}(text=True)")
    assert not offenders, f"Missing encoding='utf-8' in: {offenders}"


def test_linux_cpuinfo_non_ascii_under_ascii_locale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_bytes(
        "model name\t: Intel® Core™ i7-12700H\nflags\t\t: fpu avx2 fma\n".encode()
    )
    monkeypatch.setattr(hardware.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hardware.platform, "processor", lambda: "")

    orig_read_text = Path.read_text

    def strict_ascii_read_text(self: Path, encoding: str | None = None, errors: str | None = None) -> str:
        target = cpuinfo if str(self) == "/proc/cpuinfo" else self
        if encoding is None:
            return target.read_bytes().decode("ascii")
        return orig_read_text(target, encoding=encoding, errors=errors or "strict")

    monkeypatch.setattr(Path, "read_text", strict_ascii_read_text)
    model, flags = hardware._cpu_model_and_flags()
    assert "Intel® Core™" in model
    assert flags == ["avx2", "fma"]


def test_forge_evaluate_preserves_windows_env_and_utf8_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok, msg = forge_eval._python(
        'import sys; sys.stderr.write("falló validación: línea ≠ esperada\\n"); raise SystemExit(1)',
        tmp_path,
    )
    assert ok is False
    assert "falló validación: línea ≠ esperada" in msg

    import subprocess

    captured_env: dict[str, str] = {}
    monkeypatch.setenv("SYSTEMROOT", r"C:\Windows")
    monkeypatch.setenv("TEMP", str(tmp_path))

    def fake_run(argv, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(forge_eval, "Path", PosixPath)
    monkeypatch.setattr(forge_eval.os, "name", "nt")
    ok2, _ = forge_eval._python("assert 1 + 1 == 2", tmp_path)
    assert ok2 is True
    assert captured_env.get("SYSTEMROOT") == r"C:\Windows"


def test_packs_install_skills_replaces_readonly_existing_skill_and_single_name(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    existing = skills_dir / "single-skill"
    existing.mkdir(parents=True)
    ro_file = existing / "SKILL.md"
    ro_file.write_text("---\nname: single-skill\ndescription: old\n---\nOld\n", encoding="utf-8")
    ro_file.chmod(stat.S_IRUSR)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "SKILL.md",
            "---\nname: single-skill\ndescription: Single skill with CRLF\r\n---\r\nBody text\r\n",
        )
    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        installed = install_skills(zf, skills_dir)
    assert installed == ["single-skill"]
    assert (skills_dir / "single-skill" / "SKILL.md").is_file()


def test_launcher_instance_lock_on_windows_monkeypatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[int, int, int]] = []
    fake_msvcrt = types.ModuleType("msvcrt")
    fake_msvcrt.LK_NBLCK = 2  # type: ignore[attr-defined]
    fake_msvcrt.LK_UNLCK = 0  # type: ignore[attr-defined]
    fake_msvcrt.locking = lambda fd, mode, nbytes: calls.append((fd, mode, nbytes))  # type: ignore[attr-defined]

    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

    with Instance(tmp_path):
        assert len(calls) == 1 and calls[0][1] == 2
    assert len(calls) == 2 and calls[1][1] == 0


async def test_windows_process_kill_and_llamacpp_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    srv = LlamaServer(ServerConfig(model=tmp_path / "m.gguf"))
    monkeypatch.setattr(os, "name", "nt")
    taskkill_calls: list[list[str]] = []
    monkeypatch.setattr(
        "spike.dev.tools.subprocess.run",
        lambda argv, **kw: (taskkill_calls.append(list(argv)), SimpleNamespace(returncode=0))[1],
    )
    killed: list[str] = []
    proc = SimpleNamespace(returncode=None, pid=4242, kill=lambda: killed.append("killed"))
    _kill(proc)  # type: ignore[arg-type]
    assert taskkill_calls == [["taskkill", "/F", "/T", "/PID", "4242"]]
    assert not killed

    terminated: list[str] = []
    srv.process = SimpleNamespace(  # type: ignore[assignment]
        pid=9999,
        poll=lambda: None,
        terminate=lambda: terminated.append("term"),
        wait=lambda timeout=None: 0,
        kill=lambda: terminated.append("kill"),
    )
    await srv.stop(timeout_s=0.1)
    assert terminated == ["term"]
