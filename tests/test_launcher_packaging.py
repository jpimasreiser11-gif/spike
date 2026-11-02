"""Packaging validates staged binaries without PyInstaller, upstream downloads or executable code."""

import hashlib
import runpy
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def helper():
    return runpy.run_path(str(ROOT / "packaging" / "stage_llama.py"))


def test_pinned_platform_assets():
    assets = helper()["ASSETS"]
    assert len(assets) == 6
    assert all("b11709" in a["name"] and len(a["sha256"]) == 64 for a in assets.values())
    assert assets["Linux-x86_64"]["sha256"] in (ROOT / "scripts/install.sh").read_text(encoding="utf-8")


def test_stage_checks_archive_and_detects_tampering(tmp_path):
    mod = helper()
    archive = tmp_path / mod["ASSETS"]["Windows-AMD64"]["name"]
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("bin/llama-server.exe", b"fake executable")
        z.writestr("bin/ggml.dll", b"fake library")
    license_file = tmp_path / "LICENSE"
    license_file.write_text("MIT license fixture", encoding="utf-8")
    stage = tmp_path / "stage"
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    mod["ASSETS"]["Windows-AMD64"]["sha256"] = digest
    mod["stage_archive"](archive, stage, "Windows-AMD64", digest, license_file)
    assert (stage / "llama-server.exe").is_file() and (stage / "ggml.dll").is_file()
    assert mod["validate_stage"](stage, "Windows-AMD64") == stage
    (stage / "ggml.dll").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        mod["validate_stage"](stage, "Windows-AMD64")


def test_stage_rejects_bad_hash_and_traversal(tmp_path):
    mod = helper()
    archive = tmp_path / mod["ASSETS"]["Windows-AMD64"]["name"]
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../escape", b"bad")
    license_file = tmp_path / "LICENSE"
    license_file.write_text("MIT fixture", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        mod["stage_archive"](archive, tmp_path / "stage", "Windows-AMD64", "0" * 64, license_file)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    mod["ASSETS"]["Windows-AMD64"]["sha256"] = digest
    with pytest.raises(ValueError, match="Unsafe"):
        mod["stage_archive"](archive, tmp_path / "stage", "Windows-AMD64", digest, license_file)
    assert not (tmp_path / "escape").exists()


def test_tar_stage_preserves_safe_library_aliases_and_refuses_escaping_links(tmp_path):
    import io
    import tarfile

    mod = helper()
    archive = tmp_path / mod["ASSETS"]["Darwin-arm64"]["name"]
    with tarfile.open(archive, "w:gz") as tar:
        for name, body in (("bin/llama-server", b"fake"), ("bin/libggml.0.dylib", b"library")):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(body))
        info = tarfile.TarInfo("bin/libggml.dylib")
        info.type = tarfile.SYMTYPE
        info.linkname = "libggml.0.dylib"
        tar.addfile(info)
    mod["ASSETS"]["Darwin-arm64"]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    license_file = tmp_path / "LICENSE"
    license_file.write_text("MIT fixture", encoding="utf-8")
    stage = tmp_path / "stage"
    mod["stage_archive"](archive, stage, "Darwin-arm64", "", license_file)
    assert (stage / "libggml.dylib").read_bytes() == b"library"
    assert not (stage / "libggml.dylib").is_symlink()
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("bin/escape")
        info.type = tarfile.SYMTYPE
        info.linkname = "../../outside"
        tar.addfile(info)
    mod["ASSETS"]["Darwin-arm64"]["sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Unsafe"):
        mod["stage_archive"](archive, tmp_path / "unsafe", "Darwin-arm64", "", license_file)
