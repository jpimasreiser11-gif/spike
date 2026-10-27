"""Offline staging for the b11709 CPU binaries. No download or executable is run by the build.

Archive SHA-256 pins come from the upstream b11709 attestation (56945604); Linux matches the existing installer.
The build verifies every staged file again. This does not assert real binary compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

TAG = "b11709"
ASSETS = {
    "Linux-x86_64": {"name": f"llama-{TAG}-bin-ubuntu-x64.tar.gz",
                     "sha256": "092e1ac34609acabc116be143e42c6f410fa39b7787c597f89687692dea4c982"},
    "Linux-arm64": {"name": f"llama-{TAG}-bin-ubuntu-arm64.tar.gz",
                    "sha256": "b8dbdb3191785edd653860a1b004af78c31050e66f4715e861661fda85e239f1"},
    "Darwin-x86_64": {"name": f"llama-{TAG}-bin-macos-x64.tar.gz",
                       "sha256": "873fd46e3d82c12243633ec954e494ddccf5650a5c4309a472cf0bfb69d245a5"},
    "Darwin-arm64": {"name": f"llama-{TAG}-bin-macos-arm64.tar.gz",
                       "sha256": "d53becb535c45791eaa6fea9598ad4635765db13d6b65320371273e11a5e00ba"},
    "Windows-AMD64": {"name": f"llama-{TAG}-bin-win-cpu-x64.zip",
                       "sha256": "d52eb91b2c9cfa7ad5e1e1bbde38e47563b08c2ade82a840df03ca6946a2f16e"},
    "Windows-arm64": {"name": f"llama-{TAG}-bin-win-cpu-arm64.zip",
                       "sha256": "394ddb380c3f6eabed2219b6d43e90be3748bb8e2e82c3b7b0e7a5dbb8db4287"},
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def safe_name(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name:
        raise ValueError("Unsafe archive path")
    return path.name


def stage_archive(archive: Path, dest: Path, target: str, sha256: str, license_file: Path) -> None:
    asset = ASSETS[target]
    if archive.name != asset["name"]:
        raise ValueError("Expected the pinned release asset")
    expected = asset["sha256"]
    if sha256 and sha256 != expected:
        raise ValueError("Archive checksum differs from pinned release")
    if not re.fullmatch(r"[0-9a-f]{64}", expected or "") or digest(archive) != expected:
        raise ValueError("Archive checksum mismatch")
    if dest.exists():
        raise ValueError("Use a new staging directory")
    entries = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name = safe_name(info.filename)
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Unsafe archive link")
                if not info.is_dir():
                    entries.append((name, z.read(info), 0o644))
    else:
        with tarfile.open(archive, "r:gz") as tar:
            members = {m.name: m for m in tar.getmembers()}

            def regular(info, seen):
                if info.name in seen:
                    raise ValueError("Unsafe archive link cycle")
                if info.isfile():
                    return info
                if not (info.issym() or info.islnk()):
                    raise ValueError("Unsafe archive special file")
                safe_name(info.linkname)
                target = str(PurePosixPath(info.name).parent / info.linkname) if info.issym() else info.linkname
                safe_name(target)
                if target not in members:
                    raise ValueError("Unsafe archive link target")
                return regular(members[target], seen | {info.name})

            for info in tar.getmembers():
                name = safe_name(info.name)
                if info.isdir():
                    continue
                source = regular(info, set())
                with tar.extractfile(source) as stream:
                    entries.append((name, stream.read(), source.mode & 0o777))
    names = [name for name, _, _ in entries]
    binary = "llama-server.exe" if target.startswith("Windows") else "llama-server"
    if binary not in names or len(names) != len(set(names)) or {"LICENSE", "manifest.json"} & set(names):
        raise ValueError("Missing server or conflicting archive paths")
    license_text = license_file.read_text(encoding="utf-8")
    dest.mkdir(parents=True)
    for name, data, mode in entries:
        path = dest / name
        path.write_bytes(data)
        path.chmod(mode)
    (dest / "LICENSE").write_text(license_text, encoding="utf-8")
    files = {p.name: digest(p) for p in dest.iterdir()}
    (dest / "manifest.json").write_text(json.dumps({"tag": TAG, "target": target, "asset": archive.name,
        "archive_sha256": expected, "files": files}, indent=2), encoding="utf-8")


def validate_stage(dest: Path, target: str) -> Path:
    manifest = json.loads((dest / "manifest.json").read_text(encoding="utf-8"))
    asset = ASSETS[target]
    if manifest["tag"] != TAG or manifest["target"] != target or manifest["asset"] != asset["name"]:
        raise ValueError("Staged release does not match this platform")
    if asset["sha256"] and manifest["archive_sha256"] != asset["sha256"]:
        raise ValueError("Staged archive checksum mismatch")
    files = manifest["files"]
    binary = "llama-server.exe" if target.startswith("Windows") else "llama-server"
    if not {binary, "LICENSE"} <= files.keys():
        raise ValueError("Missing server or license")
    if {p.name for p in dest.iterdir()} != {*files, "manifest.json"}:
        raise ValueError("Unexpected staged files")
    for name, expected in files.items():
        path = dest / name
        if safe_name(name) != name or path.is_symlink() or not path.is_file() or digest(path) != expected:
            raise ValueError("Staged file checksum mismatch")
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--target", required=True, choices=ASSETS)
    parser.add_argument("--sha256", default="")
    parser.add_argument("--license-file", required=True, type=Path)
    args = parser.parse_args()
    stage_archive(args.archive, args.dest, args.target, args.sha256, args.license_file)


if __name__ == "__main__":
    main()
