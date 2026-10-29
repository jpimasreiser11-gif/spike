"""I2 native wrappers. Build, install and probe only on the matching runner; publication is a separate draft job."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import runpy
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {"Darwin-arm64": "dmg", "Windows-AMD64": "exe", "Linux-x86_64": "AppImage"}
CHECKS = ("ok", "frozen", "health", "ui", "catalog", "skills", "inference", "runtime_stopped")
TOOLS = {
    "appimagetool": ("https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
                     "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"),
    # Asset id is immutable; never follow the moving continuous tag without a matching checksum.
    "runtime-x86_64": ("https://api.github.com/repos/AppImage/type2-runtime/releases/assets/657374641",
                       "617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46"),
}


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_version(version: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", version):
        raise ValueError("Use a numeric release version, optionally with a prerelease suffix")
    return version


def tool(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"Missing build tool / Falta herramienta de construcción: {name}")
    return found


def command(args, *, cwd=None, env=None, timeout=600):
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True, timeout=timeout)


def download(url: str, dest: Path, checksum: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and digest(dest) == checksum:
        return
    partial = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/octet-stream", "User-Agent": "SPIKE-build"})
        with urllib.request.urlopen(req, timeout=60) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        if digest(partial) != checksum:
            raise ValueError(f"Download checksum mismatch: {dest.name}")
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)


def fetch(target: str, folder: Path) -> None:
    mod = runpy.run_path(str(ROOT / "packaging/stage_llama.py"))
    asset = mod["ASSETS"][target]
    archive = folder / asset["name"]
    download(f"https://github.com/ggml-org/llama.cpp/releases/download/{mod['TAG']}/{asset['name']}",
             archive, asset["sha256"])
    # This reviewed license is already included in source, independent of a moving remote branch.
    mod["stage_archive"](archive, folder / "llama", target, asset["sha256"], ROOT / "packaging/licenses/llama.txt")
    if target.startswith("Linux"):
        for name, (url, sha) in TOOLS.items():
            dest = folder / name
            download(url, dest, sha)
            dest.chmod(0o755)


def appdir(source: Path, dest: Path, icon: Path) -> None:
    shutil.copytree(source, dest / "usr/lib/SPIKE", symlinks=True)
    (dest / "AppRun").write_text('#!/bin/sh\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                                'exec "$HERE/usr/lib/SPIKE/SPIKE" "$@"\n', encoding="utf-8")
    (dest / "AppRun").chmod(0o755)
    (dest / "SPIKE.desktop").write_text("[Desktop Entry]\nType=Application\nName=SPIKE\nExec=AppRun\n"
                                        "Icon=SPIKE\nCategories=Development;\nTerminal=false\n", encoding="utf-8")
    shutil.copyfile(icon, dest / "SPIKE.png")


def build(target: str, version: str, commit: str, output: Path, vendor: Path, model: Path) -> Path:
    validate_version(version)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Use the full source commit")
    if target.split("-")[0] != platform.system():
        raise ValueError("Build on the matching OS runner")
    output.mkdir(parents=True, exist_ok=True)
    artifact = output / f"SPIKE-{version}-{target}.{TARGETS[target]}"
    smoke = output / f"{target}-smoke.json"
    with tempfile.TemporaryDirectory(prefix="spike-install-") as folder:
        work = Path(folder)
        if target.startswith("Darwin"):
            staged = work / "image"
            staged.mkdir()
            shutil.copytree(ROOT / "dist/SPIKE.app", staged / "SPIKE.app", symlinks=True)
            (staged / "Applications").symlink_to("/Applications")
            command([tool("codesign"), "--verify", "--deep", "--strict", staged / "SPIKE.app"])
            command([tool("hdiutil"), "create", "-volname", "SPIKE", "-srcfolder", staged,
                     "-format", "UDZO", artifact])
            mount = work / "mounted"
            command([tool("hdiutil"), "attach", artifact, "-nobrowse", "-readonly", "-mountpoint", mount])
            try:
                installed = work / "installed/SPIKE.app"
                shutil.copytree(mount / "SPIKE.app", installed, symlinks=True)
            finally:
                command([tool("hdiutil"), "detach", mount])
            launch = [installed / "Contents/MacOS/SPIKE"]
        elif target.startswith("Windows"):
            compiler = shutil.which("ISCC") or str(Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)"))
                                                  / "Inno Setup 6/ISCC.exe")
            if not Path(compiler).is_file():
                raise RuntimeError("Inno Setup 6 is required / Hace falta Inno Setup 6")
            command([compiler, f"/DSourceDir={ROOT / 'dist/SPIKE'}", f"/DOutputDir={output}",
                     f"/DVersion={version}", ROOT / "packaging/windows.iss"])
            installed = work / "installed"
            command([artifact, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={installed}"])
            launch = [installed / "SPIKE.exe"]
        else:
            dest = work / "SPIKE.AppDir"
            appdir(ROOT / "dist/SPIKE", dest, ROOT / "web/public/icon-512.png")
            for name, (_, sha) in TOOLS.items():
                if digest(vendor / name) != sha:
                    raise ValueError(f"Build tool checksum mismatch: {name}")
            env = {**os.environ, "ARCH": "x86_64", "APPIMAGE_EXTRACT_AND_RUN": "1"}
            command([vendor / "appimagetool", "--runtime-file", vendor / "runtime-x86_64", dest, artifact], env=env)
            artifact.chmod(0o755)
            launch = [artifact, "--appimage-extract-and-run"]
        try:
            command([*launch, "--package-smoke", model, "--report", smoke], timeout=180)
        finally:
            if target.startswith("Windows"):
                command([installed / "unins000.exe", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
    result = json.loads(smoke.read_text(encoding="utf-8"))
    validate_smoke(result)
    record = {"version": version, "commit": commit, "target": target, "artifact": artifact.name,
              "sha256": digest(artifact), "smoke": result}
    (output / f"{artifact.name}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return artifact


def validate_smoke(result: dict) -> None:
    if (any(result.get(key) is not True for key in CHECKS) or result.get("quality_measured") is not False
            or not re.fullmatch(r"[0-9a-f]{64}", result.get("fixture_sha256", ""))):
        raise ValueError("Incomplete packaged smoke evidence (never a model quality benchmark)")


def assemble(folder: Path, version: str, commit: str) -> None:
    validate_version(version)
    seen, files, fixtures = set(), [], set()
    for path in sorted(folder.glob("SPIKE-*.json")):
        if path.is_symlink():
            raise ValueError("Release evidence must not be a symlink")
        record = json.loads(path.read_text(encoding="utf-8"))
        target = record["target"]
        if target not in TARGETS or target in seen:
            raise ValueError("Unknown or duplicate platform")
        if record["version"] != version or record["commit"] != commit:
            raise ValueError("Mixed release source or version")
        expected = f"SPIKE-{version}-{target}.{TARGETS[target]}"
        if record["artifact"] != expected or path.name != expected + ".json":
            raise ValueError("Unexpected artifact name")
        artifact = folder / expected
        if artifact.is_symlink() or digest(artifact) != record["sha256"]:
            raise ValueError("Artifact checksum mismatch")
        validate_smoke(record["smoke"])
        seen.add(target)
        fixtures.add(record["smoke"]["fixture_sha256"])
        files.extend([artifact, path])
    if seen != set(TARGETS):
        raise ValueError("Missing platform evidence")
    if len(fixtures) != 1:
        raise ValueError("Mixed model fixtures")
    actual = {p.name for p in folder.iterdir() if p.suffix in {".exe", ".dmg", ".AppImage"}}
    if actual != {p.name for p in files if p.suffix != ".json"}:
        raise ValueError("Unexpected installer")
    (folder / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in sorted(files)), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    get = sub.add_parser("fetch")
    get.add_argument("--target", choices=TARGETS, required=True)
    get.add_argument("--vendor", type=Path, required=True)
    wrap = sub.add_parser("build")
    wrap.add_argument("--target", choices=TARGETS, required=True)
    wrap.add_argument("--vendor", type=Path, required=True)
    wrap.add_argument("--model", type=Path, required=True)
    for p in (wrap, sub.add_parser("assemble")):
        p.add_argument("--version", required=True)
        p.add_argument("--commit", required=True)
        p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == "fetch":
        fetch(args.target, args.vendor.resolve())
    elif args.cmd == "build":
        print(build(args.target, args.version, args.commit, args.output.resolve(), args.vendor.resolve(),
                    args.model.resolve()))
    else:
        assemble(args.output.resolve(), args.version, args.commit)


if __name__ == "__main__":
    main()
