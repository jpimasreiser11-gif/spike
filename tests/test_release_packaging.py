"""I2: wrappers and release evidence, with fake native tools and HTTP; no downloads or inference."""

import hashlib
import json
import runpy
import sys
from pathlib import Path

import httpx
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
SHA = "a" * 40
TARGETS = {"Darwin-arm64": "dmg", "Windows-AMD64": "exe", "Linux-x86_64": "AppImage"}


def helper():
    return runpy.run_path(str(ROOT / "packaging/release.py"))


def evidence(folder, target, **changes):
    ext = TARGETS[target]
    name = f"SPIKE-0.1.0-{target}.{ext}"
    (folder / name).write_bytes(b"fake installer")
    data = {"version": "0.1.0", "commit": SHA, "target": target, "artifact": name,
            "sha256": hashlib.sha256(b"fake installer").hexdigest(),
            "smoke": {"ok": True, "frozen": True, "health": True, "ui": True, "catalog": True,
                      "skills": True, "inference": True, "runtime_stopped": True,
                      "fixture_sha256": "b" * 64, "quality_measured": False}}
    data.update(changes)
    (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return name


def test_assemble_requires_all_platforms_and_same_source(tmp_path):
    mod = helper()
    evidence(tmp_path, "Darwin-arm64")
    with pytest.raises(ValueError, match="platform"):
        mod["assemble"](tmp_path, "0.1.0", SHA)
    evidence(tmp_path, "Windows-AMD64")
    evidence(tmp_path, "Linux-x86_64", commit="c" * 40)
    with pytest.raises(ValueError, match="source"):
        mod["assemble"](tmp_path, "0.1.0", SHA)
    evidence(tmp_path, "Linux-x86_64")
    mod["assemble"](tmp_path, "0.1.0", SHA)
    lines = (tmp_path / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 6 and lines == sorted(lines, key=lambda x: x.split("  ")[1])


@pytest.mark.parametrize("flag", ["ok", "frozen", "health", "ui", "catalog", "skills", "inference", "runtime_stopped"])
def test_release_rejects_failed_or_unfrozen_smoke(tmp_path, flag):
    mod = helper()
    for target in TARGETS:
        name = evidence(tmp_path, target)
    path = tmp_path / f"{name}.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["smoke"][flag] = False
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="smoke"):
        mod["assemble"](tmp_path, "0.1.0", SHA)
    assert not (tmp_path / "SHA256SUMS").exists()


@pytest.mark.parametrize("damage", ["tamper", "extra", "escape", "quality", "wrong_fixture"])
def test_release_rejects_corrupt_ambiguous_or_misleading_evidence(tmp_path, damage):
    mod = helper()
    for target in TARGETS:
        name = evidence(tmp_path, target)
    path = tmp_path / f"{name}.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    if damage == "tamper":
        (tmp_path / name).write_bytes(b"changed")
    elif damage == "extra":
        (tmp_path / "unknown.exe").write_bytes(b"unknown")
    elif damage == "escape":
        report["artifact"] = "../outside.exe"
    elif damage == "quality":
        report["smoke"]["quality_measured"] = True
    else:
        report["smoke"]["fixture_sha256"] = "d" * 64
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError):
        mod["assemble"](tmp_path, "0.1.0", SHA)


@pytest.mark.parametrize("version", ["../0.1.0", "v0.1.0", "0.1", "1.2.3\n", "1.2.3;echo nope"])
def test_versions_cannot_escape_paths_or_shell_arguments(version):
    with pytest.raises(ValueError):
        helper()["validate_version"](version)


def test_missing_native_tool_fails_clearly(monkeypatch):
    import release
    monkeypatch.setattr(release.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="missing-tool"):
        release.tool("missing-tool")


def test_windows_installer_has_per_user_scope_no_data_removal():
    text = (ROOT / "packaging/windows.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text and "{localappdata}" in text
    assert "english" in text and "spanish" in text
    assert "[UninstallDelete]" not in text and ".spike" not in text


def test_linux_appdir_preserves_spaces_and_launch_arguments(tmp_path):
    mod = helper()
    source = tmp_path / "dist space" / "SPIKE"
    source.mkdir(parents=True)
    (source / "SPIKE").write_bytes(b"fake")
    dest = tmp_path / "app dir"
    mod["appdir"](source, dest, ROOT / "web/public/icon-512.png")
    assert (dest / "usr/lib/SPIKE/SPIKE").read_bytes() == b"fake"
    assert '"$@"' in (dest / "AppRun").read_text(encoding="utf-8")
    assert "Exec=AppRun" in (dest / "SPIKE.desktop").read_text(encoding="utf-8")
    assert (dest / "SPIKE.png").is_file()


def test_workflow_tests_installed_artifacts_before_any_draft():
    doc = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))
    assert set(triggers) == {"push", "workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["create_draft"]["default"] is False
    matrix = doc["jobs"]["build"]["strategy"]["matrix"]["include"]
    assert {item["target"] for item in matrix} == set(TARGETS)
    assert doc["permissions"] == {"contents": "read"}
    draft = doc["jobs"]["draft"]
    assert "build" in draft["needs"] and "pull_request" in draft["if"]
    assert "--draft" in str(draft) and "--verify-tag" in str(draft)
    assert "package_smoke" not in str(matrix)  # no mock smoke injected through matrix


def test_smoke_checks_ui_assets_bundled_data_inference_and_stop(tmp_path):
    import package_smoke
    seen = []

    def handle(request):
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/":
            return httpx.Response(200, text='<html><div id="root"></div><script src="/assets/test.js"></script></html>')
        if path == "/assets/test.js":
            return httpx.Response(200, text="fixture script")
        if path in {"/api/specialists", "/api/skills"}:
            return httpx.Response(200, json=[{"id": "core"}])
        if path == "/api/runtime/start":
            return httpx.Response(200, json={"running": True, "base_url": "http://127.0.0.1:8737"})
        if path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": [{"message": {"content": "random"}}]})
        if path == "/api/runtime/stop":
            return httpx.Response(200, json={"running": False})
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1:8740") as client:
        result = package_smoke.probe(client, tmp_path / "tiny.gguf", 8737)
    assert all(result[key] for key in ("health", "ui", "catalog", "skills", "inference", "runtime_stopped"))
    assert ("GET", "/assets/test.js") in seen and ("POST", "/v1/chat/completions") in seen
    assert seen[-1] == ("POST", "/api/runtime/stop")


def test_smoke_failure_still_requests_runtime_stop(tmp_path):
    import package_smoke
    seen = []

    def fail(request):
        seen.append(request.url.path)
        return httpx.Response(500)

    with (httpx.Client(transport=httpx.MockTransport(fail), base_url="http://127.0.0.1:8740") as client,
          pytest.raises(httpx.HTTPStatusError)):
        package_smoke.probe(client, tmp_path / "tiny.gguf", 8737)
    assert seen[-1] == "/api/runtime/stop"


def test_download_checks_bytes_preserves_good_destination_and_removes_bad_partial(tmp_path, monkeypatch):
    import io

    import release

    dest = tmp_path / "tool"
    dest.write_bytes(b"old")
    requests = []

    def open_fixture(request, **kwargs):
        requests.append(request.full_url)
        return io.BytesIO(b"verified")

    monkeypatch.setattr(release.urllib.request, "urlopen", open_fixture)
    with pytest.raises(ValueError, match="checksum"):
        release.download("https://fixture.test/tool", dest, "0" * 64)
    assert dest.read_bytes() == b"old" and not dest.with_suffix(".part").exists()
    checksum = hashlib.sha256(b"verified").hexdigest()
    release.download("https://fixture.test/tool", dest, checksum)
    release.download("https://fixture.test/tool", dest, checksum)
    assert dest.read_bytes() == b"verified" and len(requests) == 2


def test_smoke_refuses_nonfrozen_and_external_runtime_before_launch(tmp_path, monkeypatch):
    import package_smoke

    monkeypatch.setattr("spike.launcher.app.launch", lambda *a, **kw: pytest.fail("must not start anything"))
    report = tmp_path / "report.json"
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert package_smoke.run(tmp_path / "absent.gguf", report) == 1
    assert "frozen" in json.loads(report.read_text(encoding="utf-8"))["error"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    tiny = tmp_path / "tiny.gguf"
    tiny.write_bytes(b"GGUFfixture")
    assert package_smoke.run(tiny, report) == 1
    assert "Bundled llama-server missing" in json.loads(report.read_text(encoding="utf-8"))["error"]


def test_smoke_uses_disposable_home_and_restores_environment_on_failure(tmp_path, monkeypatch):
    import os

    import package_smoke

    original = tmp_path / "original-user-home"
    monkeypatch.setenv("SPIKE_HOME", str(original))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    (tmp_path / "llama").mkdir()
    (tmp_path / "llama" / ("llama-server.exe" if os.name == "nt" else "llama-server")).write_bytes(b"fake")
    tiny = tmp_path / "tiny.gguf"
    tiny.write_bytes(b"GGUFfixture")
    report = tmp_path / "report.json"

    def fail(home, **kwargs):
        assert home != original and os.environ["SPIKE_HOME"] == str(home)
        assert os.environ["SPIKE_NO_KEYRING"] == "1"
        raise RuntimeError("fixture failure")

    monkeypatch.setattr("spike.launcher.app.launch", fail)
    assert package_smoke.run(tiny, report) == 1
    assert os.environ["SPIKE_HOME"] == str(original) and not original.exists()
    assert json.loads(report.read_text(encoding="utf-8"))["ok"] is False


@pytest.mark.parametrize("missing", ["ui", "catalog", "skills", "inference"])
def test_smoke_rejects_incomplete_packaged_outputs(tmp_path, missing):
    import package_smoke

    def handle(request):
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(200, json={"ok": True})
        if path == "/":
            html = '<div id="root"></div><script src="/assets/a.js"></script>' if missing != "ui" else "Not found"
            return httpx.Response(200, text=html)
        if path == "/assets/a.js":
            return httpx.Response(200, text="fixture")
        if path in {"/api/specialists", "/api/skills"}:
            key = "catalog" if "specialists" in path else "skills"
            return httpx.Response(200, json=[] if missing == key else [{"id": "core"}])
        if path == "/api/runtime/start":
            return httpx.Response(200, json={"running": True, "base_url": "http://127.0.0.1:8737"})
        if path == "/v1/chat/completions":
            return httpx.Response(200, json={"choices": []})
        if path == "/api/runtime/stop":
            return httpx.Response(200, json={"running": False})
        return httpx.Response(200, json={})

    with (httpx.Client(transport=httpx.MockTransport(handle), base_url="http://127.0.0.1:8740") as client,
          pytest.raises(ValueError)):
        package_smoke.probe(client, tmp_path / "tiny.gguf", 8737)
