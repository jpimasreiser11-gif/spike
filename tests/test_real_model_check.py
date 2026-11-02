"""I3: the real-model installer check, with a fake app (a separate process speaking the app's HTTP API) and a fake
download. No network, no model, no native installer: what is tested is the driver's logic, not the product's speed."""

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import psutil
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import real_model_check as rmc  # noqa: E402

SHA = "a" * 40
PAYLOAD = b"GGUF" + bytes(range(256)) * 64
FILENAME = "Qwen3.5-4B-Q4_K_M.gguf"
EXPECTED = rmc.Expected("qwen3.5-4b", "unsloth/Qwen3.5-4B-GGUF", FILENAME, hashlib.sha256(PAYLOAD).hexdigest(),
                        len(PAYLOAD), "apache-2.0")
SECRET = "s3cr3t-token-value-123"

# A stand-in for the installed app: the endpoints the check uses, behaving like the launcher's (same-origin JSON for
# mutations), with a "download" that writes PAYLOAD into SPIKE_HOME/models. FAKE_MODE picks what goes wrong.
FAKE_APP = r'''
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODE = os.environ.get("FAKE_MODE", "good")
HOME = Path(os.environ.get("SPIKE_HOME") or Path.home() / ".spike")
PAYLOAD = b"GGUF" + bytes(range(256)) * 64
GIB = 1024 ** 3
if os.environ.get("FAKE_PID_FILE"):
    Path(os.environ["FAKE_PID_FILE"]).write_text(str(os.getpid()), encoding="utf-8")
if MODE == "exit":
    sys.exit(3)
if MODE == "silent":
    time.sleep(120)
JOB = {"status": "idle", "file": "", "done": 0, "total": 0}
STATE = {"complete": False, "settings": {"local_runtime": {"model": ""}}}


def install():
    JOB.update(status="running", done=0, total=len(PAYLOAD))
    if MODE == "stall":
        return
    time.sleep(0.3)
    if MODE == "job_failed":
        JOB["status"] = "failed"
        return
    dest = HOME / "models" / "Qwen3.5-4B-Q4_K_M.gguf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(PAYLOAD + (b"tampered" if MODE == "bad" else b""))
    (HOME / "setup.json").write_text(json.dumps({"files": [dest.as_posix()]}), encoding="utf-8")
    STATE["settings"]["local_runtime"]["model"] = dest.as_posix()
    STATE["complete"] = True
    JOB.update(status="done", done=len(PAYLOAD))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def note(self):
        if os.environ.get("FAKE_REQUEST_LOG"):
            with open(os.environ["FAKE_REQUEST_LOG"], "a", encoding="utf-8") as log:
                log.write(f"{self.command} {self.path}\n")

    def reply(self, body, status=200):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def json_post(self):
        if (self.headers.get("Content-Type", "").split(";")[0] != "application/json" or self.headers.get("Origin")):
            self.reply({"detail": "Local same-origin JSON request required"}, 403)
            return None
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")

    def do_GET(self):
        self.note()
        ram = (7 if MODE == "refuse" else 16) * GIB
        routes = {
            "/api/health": {"ok": True},
            "/api/specialists": [{"id": "core"}], "/api/skills": [{"id": "skill"}],
            "/api/settings": STATE["settings"],
            "/api/setup": {"enabled": True, "complete": STATE["complete"], "job": JOB, "disk_free": 100 * GIB,
                           "ram_total": ram, "ram_available": ram // 2, "required_disk": 6 * GIB,
                           "required_ram": 8 * GIB, "can_download": ram >= 8 * GIB, "specialists": []},
        }
        if self.path == "/":
            self.reply(b'<div id="root"></div><script src="/assets/app.js"></script>')
        elif self.path == "/assets/app.js":
            self.reply(b"console.log(1)")
        elif self.path == "/metrics":
            self.reply(b"# HELP x\nllamacpp:prompt_tokens_seconds 100.5\nllamacpp:predicted_tokens_seconds 7.25\n")
        elif self.path in routes:
            self.reply(routes[self.path])
        else:
            self.reply({"detail": "not found"}, 404)

    def do_POST(self):
        self.note()
        body = self.json_post()
        if body is None:
            return
        if self.path == "/api/setup/download":
            threading.Thread(target=install, daemon=True).start()
            JOB.update(status="running", done=0, total=0)
            self.reply(JOB)
        elif self.path == "/api/runtime/start":
            if MODE == "slow_runtime":
                time.sleep(4)
            self.reply({"running": True, "pid": os.getpid(), "base_url": f"http://127.0.0.1:{PORT}",
                        "load_seconds": 0.5, "context": 4096})
        elif self.path == "/api/setup/quit":
            self.reply({"ok": True})
            if MODE != "hang_on_quit":
                threading.Thread(target=server.shutdown, daemon=True).start()
        elif self.path == "/v1/chat/completions":
            self.chat()
        else:
            self.reply({"detail": "not found"}, 404)

    def chat(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(event):
            self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
            self.wfile.flush()

        send({"choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]})
        time.sleep(0.3)
        if MODE == "chat_error":
            send({"error": {"message": "backend exploded"}})
            return
        key = "reasoning_content" if MODE == "reasoning_only" else "content"
        words = ["Paris", " is", " the", " capital", " of", " France", "."]
        for word in words:
            send({"choices": [{"index": 0, "delta": {key: word}, "finish_reason": None}]})
            time.sleep(0.05)
        send({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        send({"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": len(words)}})
        self.wfile.write(b"data: [DONE]\n\n")


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
server.daemon_threads = True
PORT = server.server_address[1]
server.serve_forever()
if MODE != "hang_on_quit":
    time.sleep(0.2)
'''


def write_evidence(folder: Path, target="Linux-x86_64", payload=b"fake installer", **changes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    name = f"SPIKE-0.1.0-{target}.{rmc.release.TARGETS[target]}"
    (folder / name).write_bytes(payload)
    data = {"version": "0.1.0", "commit": SHA, "target": target, "artifact": name,
            "sha256": hashlib.sha256(b"fake installer").hexdigest(),
            "smoke": {"ok": True, "frozen": True, "health": True, "ui": True, "catalog": True, "skills": True,
                      "inference": True, "runtime_stopped": True, "fixture_sha256": "b" * 64, "quality_measured": False}}
    data.update(changes)
    (folder / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return folder / name


class World:
    """Everything one run needs: evidence folder, the fake app as the 'installed program', a config."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.monkeypatch = monkeypatch
        self.script = tmp_path / "fake_spike.py"
        self.script.write_text(FAKE_APP, encoding="utf-8")
        self.artifacts = tmp_path / "artifacts"
        write_evidence(self.artifacts)
        self.requests = tmp_path / "requests.log"
        self.pids = tmp_path / "app.pid"
        self.installs: list[Path] = []
        monkeypatch.setenv("FAKE_REQUEST_LOG", str(self.requests))
        monkeypatch.setenv("FAKE_PID_FILE", str(self.pids))

    def mode(self, mode: str) -> None:
        self.monkeypatch.setenv("FAKE_MODE", mode)

    def install(self, target, artifact, root):
        marker = root / "program"
        root.mkdir(parents=True)
        marker.write_text("installed", encoding="utf-8")
        self.installs.append(marker)
        return rmc.Installed("fake", [sys.executable, str(self.script)], marker.unlink, lambda: not marker.exists())

    def config(self, **changes) -> rmc.Config:
        values = dict(target="Linux-x86_64", artifacts=self.artifacts, work=self.tmp / "work",
                      out=self.tmp / "out" / "result.json", source_run="123", start_timeout=30, download_timeout=30,
                      stall_timeout=0.6, runtime_timeout=30, chat_timeout=30, quit_timeout=15, poll_seconds=0.05)
        values.update(changes)
        return rmc.Config(**values)

    def run(self, expected=EXPECTED, **changes) -> dict:
        return rmc.run_check(self.config(**changes), expected_model=lambda: expected, install=self.install)

    def requested(self) -> list[str]:
        return self.requests.read_text(encoding="utf-8").splitlines() if self.requests.exists() else []

    def assert_app_gone(self) -> None:
        pid = int(self.pids.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 10
        while psutil.pid_exists(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not psutil.pid_exists(pid)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


# ---------------------------------------------------------------------- the whole run against the fake app
def test_full_run_records_the_measurements_and_keeps_the_profile(world, capsys):
    result = world.run()
    assert result["ok"] is True and result["outcome"] == "ok" and result["failed_stage"] is None, result
    assert [p["name"] for p in result["phases"]] == ["prepare", "verify", "install", "start", "ui", "setup", "model",
                                                     "runtime", "chat", "quit", "uninstall"]
    assert all(p["ok"] for p in result["phases"])
    assert result["schema"] == 1 and result["target"] == "Linux-x86_64" and result["source_run"] == "123"
    assert set(result["runner"]) == {"os", "machine", "cpu", "logical_cpus", "physical_cpus", "ram_gib", "python"}
    assert result["artifact"]["sha256_verified"] is True and result["artifact"]["commit"] == SHA
    model = result["model"]
    assert model["hash_match"] is True and model["bytes"] == len(PAYLOAD) == model["expected_bytes"]
    assert model["sha256"] == model["expected_sha256"] == EXPECTED.sha256
    assert model["path"] == "models/" + FILENAME  # relative to the profile, never an absolute path
    assert model["download_seconds"] > 0 and model["download_mib_per_s"] > 0 and model["partial_files_left"] == 0
    chat = result["chat"]
    assert chat["answer"] == "Paris is the capital of France." and chat["completion_tokens"] == 7
    assert 0.25 < chat["ttft_seconds"] < chat["total_seconds"]
    assert chat["tokens_per_second"] > 0 and chat["finish_reason"] == "stop"
    runtime = result["runtime"]
    assert runtime["peak_rss_mib"] > 0 and runtime["peak_rss_source"] in {"VmHWM", "peak_wset", "sampled"}
    assert runtime["stopped_with_app"] is True and runtime["context"] == 4096
    assert result["llama_metrics"] == {"prompt_tokens_per_second": 100.5, "generation_tokens_per_second": 7.25}
    assert result["app"]["health"] and result["app"]["ui"] and result["app"]["catalog"] and result["app"]["skills"]
    assert result["app"]["exit_code"] == 0
    assert result["uninstall"]["profile_kept"] is True and result["uninstall"]["model_intact"] is True
    assert result["uninstall"]["program_removed"] is True and not world.installs[0].exists()
    assert result["wall_seconds"] >= sum(p["seconds"] for p in result["phases"]) - 0.1
    # the same JSON is printed in the log and written to the file
    printed = capsys.readouterr().out
    saved = (world.tmp / "out" / "result.json").read_text(encoding="utf-8")
    assert json.loads(saved) == json.loads(printed[printed.index("{\n"):]) == result
    # what the wizard sends: the setup status, a same-origin JSON download, then the runtime and the chat
    seen = world.requested()
    assert seen.index("GET /api/setup") < seen.index("POST /api/setup/download") < seen.index("POST /api/runtime/start")
    assert seen.index("POST /api/runtime/start") < seen.index("POST /v1/chat/completions") < seen.index("POST /api/setup/quit")


def test_hash_mismatch_is_refused_before_the_model_is_run(world):
    world.mode("bad")
    result = world.run()
    assert result["ok"] is False and result["failed_stage"] == "model"
    assert "differs from the Hub" in result["error"] and result["model"]["hash_match"] is False
    assert "POST /api/runtime/start" not in world.requested()
    assert not any("/v1/chat" in line for line in world.requested())
    assert result["uninstall"] == {"after_failure": True, "program_removed": True}  # still cleaned up
    world.assert_app_gone()


def test_a_different_file_name_than_the_catalog_is_reported(world):
    result = world.run(expected=rmc.Expected("qwen3.5-4b", "o/r", "Other-Q5.gguf", EXPECTED.sha256, EXPECTED.size, "mit"))
    assert result["failed_stage"] == "model" and "Other-Q5.gguf" in result["error"]


def test_installer_that_differs_from_its_evidence_is_never_installed(world):
    write_evidence(world.artifacts, payload=b"tampered installer")
    result = world.run()
    assert result["failed_stage"] == "verify" and "differs from the build evidence" in result["error"]
    assert world.installs == [] and not world.requested()


def test_app_that_never_answers_health_times_out_and_is_stopped(world):
    world.mode("silent")
    started = time.monotonic()
    result = world.run(start_timeout=1.5)
    assert result["failed_stage"] == "start" and "did not answer /api/health within" in result["error"]
    assert time.monotonic() - started < 20
    assert result["app"]["killed"] is True
    assert result["uninstall"]["after_failure"] is True
    world.assert_app_gone()


def test_app_that_exits_early_is_reported_with_its_exit_code(world):
    world.mode("exit")
    result = world.run()
    assert result["failed_stage"] == "start" and "exited with code 3" in result["error"]


def test_runtime_that_does_not_start_in_time_fails_that_stage(world):
    world.mode("slow_runtime")
    result = world.run(runtime_timeout=1)
    assert result["failed_stage"] == "runtime" and "did not start within 1 s" in result["error"]
    assert result["model"]["hash_match"] is True  # the download had been checked before
    world.assert_app_gone()


def test_the_apps_resource_guard_is_reported_and_not_bypassed(world):
    world.mode("refuse")
    result = world.run()
    assert result["outcome"] == "refused_resources" and result["ok"] is False and result["failed_stage"] == "setup"
    assert "resource guard" in result["error"] and result["setup"]["can_download"] is False
    assert result["setup"]["ram_total_gib"] == 7.0 and result["setup"]["required_ram_gib"] == 8.0
    assert "POST /api/setup/download" not in world.requested()


def test_a_failed_job_a_stalled_download_and_a_chat_error_each_name_their_stage(world):
    world.mode("job_failed")
    assert world.run()["error"].startswith("the app reported the model installation as failed")
    world.mode("stall")
    stalled = world.run(work=world.tmp / "w2", out=world.tmp / "o2.json")
    assert stalled["failed_stage"] == "setup" and "stalled" in stalled["error"]
    world.mode("chat_error")
    chat = world.run(work=world.tmp / "w3", out=world.tmp / "o3.json")
    assert chat["failed_stage"] == "chat" and "backend exploded" in chat["error"]
    world.mode("reasoning_only")
    thinking = world.run(work=world.tmp / "w4", out=world.tmp / "o4.json")
    assert thinking["failed_stage"] == "chat" and "no answer text" in thinking["error"]
    assert thinking["chat"]["reasoning_chars"] > 0


def test_app_that_ignores_quit_is_killed_and_reported(world):
    world.mode("hang_on_quit")
    result = world.run(quit_timeout=1)
    assert result["failed_stage"] == "quit" and "still running" in result["error"]
    assert result["app"]["killed"] is True and result["uninstall"]["program_removed"] is True
    world.assert_app_gone()


def test_default_profile_is_only_used_on_a_machine_that_has_none(world, tmp_path, monkeypatch):
    home = tmp_path / "home"
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    (home / ".spike").mkdir(parents=True)
    refused = world.run(default_profile=True)
    assert refused["failed_stage"] == "prepare" and "not a clean machine" in refused["error"]
    assert world.installs == []
    (home / ".spike").rmdir()
    result = world.run(default_profile=True, work=tmp_path / "w2", out=tmp_path / "o2.json")
    assert result["ok"] is True and result["profile"].startswith("default")
    assert (home / ".spike" / "models" / FILENAME).is_file()  # kept after the uninstall
    assert result["model"]["path"] == "models/" + FILENAME


def test_work_directory_must_be_new(world):
    (world.tmp / "work").mkdir()
    (world.tmp / "work" / "old").write_text("x", encoding="utf-8")
    assert world.run()["failed_stage"] == "prepare"


def test_output_never_carries_secrets_or_paths_outside_the_work_directory(world, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home-of-alice"
    for variable in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(variable, str(home))
    monkeypatch.setenv("FAKE_API_TOKEN", SECRET)
    monkeypatch.setattr(rmc.getpass, "getuser", lambda: "alicetester")
    leaked = f"cannot write {home}/.spike/x with {SECRET} in {home.as_posix()}/y and /Users/alicetester/Documents"

    def broken(target, artifact, root):
        raise RuntimeError(leaked + f" under {root}")

    result = rmc.run_check(world.config(), expected_model=lambda: EXPECTED, install=broken)
    assert result["failed_stage"] == "install"
    shown = capsys.readouterr()
    saved = (tmp_path / "out" / "result.json").read_text(encoding="utf-8")
    for text in (shown.out, shown.err, saved, json.dumps(result)):
        assert SECRET not in text and "alicetester" not in text and str(home) not in text and home.as_posix() not in text
    assert "<work>/install" in saved and "~/.spike/x" in saved and "***" in saved
    # and a successful default-profile run prints only profile-relative model paths
    world.run(default_profile=True, work=tmp_path / "w2", out=tmp_path / "o2.json")
    again = capsys.readouterr().out + (tmp_path / "o2.json").read_text(encoding="utf-8")
    assert str(home) not in again and SECRET not in again and "alicetester" not in again


def test_the_launched_app_does_not_inherit_secrets_or_spike_settings(monkeypatch, tmp_path):
    for name, value in (("GITHUB_TOKEN", SECRET), ("SPIKE_API_TOKEN", "x" * 20), ("HF_TOKEN", "y" * 20), ("PATH", "p")):
        monkeypatch.setenv(name, value)
    env = rmc.app_env(tmp_path)
    assert "GITHUB_TOKEN" not in env and "SPIKE_API_TOKEN" not in env and "HF_TOKEN" not in env
    assert env["SPIKE_HOME"] == str(tmp_path) and env["SPIKE_NO_KEYRING"] == "1" and env["PATH"] == "p"
    assert "SPIKE_HOME" not in rmc.app_env(None)  # the default profile: the app picks ~/.spike itself


# ---------------------------------------------------------------------- pieces
def test_redactor_replaces_work_home_user_and_secrets(tmp_path):
    work, home = tmp_path / "home" / "runner" / "work", tmp_path / "home" / "runner"
    redact = rmc.Redactor(work, home=home, user="runner", env={"X_API_KEY": SECRET, "PLAIN": "visible-value"})
    text = f"{work}/a {home}/b /home/runner/c {SECRET} visible-value runner"
    assert redact(text) == "<work>/a ~/b /home/<user>/c *** visible-value runner"  # a bare word is not a path
    assert redact.scrub({"a": [f"{work}/z"], "n": 3}) == {"a": ["<work>/z"], "n": 3}


def test_verify_artifact_checks_hash_target_name_and_smoke(tmp_path):
    folder = tmp_path / "ok"
    artifact = write_evidence(folder)
    assert rmc.verify_artifact(folder, "Linux-x86_64")[0] == artifact
    with pytest.raises(ValueError, match="describe this target"):
        rmc.verify_artifact(folder, "Windows-AMD64")
    with pytest.raises(ValueError, match="Unknown target"):
        rmc.verify_artifact(folder, "Plan9-mips")
    bad = tmp_path / "hash"
    write_evidence(bad, payload=b"other bytes")
    with pytest.raises(ValueError, match="differs from the build evidence"):
        rmc.verify_artifact(bad, "Linux-x86_64")
    escape = tmp_path / "escape"
    write_evidence(escape, artifact="../outside.AppImage")
    with pytest.raises(ValueError, match="describe this target"):
        rmc.verify_artifact(escape, "Linux-x86_64")
    unsound = tmp_path / "smoke"
    write_evidence(unsound, smoke={"ok": False})
    with pytest.raises(ValueError, match="smoke"):
        rmc.verify_artifact(unsound, "Linux-x86_64")
    two = tmp_path / "two"
    write_evidence(two)
    (two / "SPIKE-0.1.0-Other.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        rmc.verify_artifact(two, "Linux-x86_64")


def test_dmg_is_mounted_read_only_copied_and_always_detached(tmp_path, monkeypatch):
    calls = []

    def command(args, **kwargs):
        args = [str(a) for a in args]
        calls.append(args)
        if args[1] == "attach":
            app = Path(args[args.index("-mountpoint") + 1]) / "SPIKE.app/Contents/MacOS"
            app.mkdir(parents=True)
            (app / "SPIKE").write_text("binary", encoding="utf-8")

    monkeypatch.setattr(rmc.release, "command", command)
    monkeypatch.setattr(rmc.release, "tool", lambda name: name)
    installed = rmc.install_dmg(tmp_path / "SPIKE.dmg", tmp_path / "root")
    assert calls[0][:2] == ["hdiutil", "attach"] and "-readonly" in calls[0] and "-nobrowse" in calls[0]
    assert calls[-1][:2] == ["hdiutil", "detach"]
    assert installed.argv[0].endswith("SPIKE.app/Contents/MacOS/SPIKE") and not installed.removed()
    installed.remove()
    assert installed.removed()
    # an image without the app is an error, and the volume is still ejected
    calls.clear()
    monkeypatch.setattr(rmc.release, "command", lambda args, **kw: calls.append([str(a) for a in args]))
    with pytest.raises(RuntimeError, match="no SPIKE.app"):
        rmc.install_dmg(tmp_path / "SPIKE.dmg", tmp_path / "root2")
    assert calls[-1][:2] == ["hdiutil", "detach"]


def test_inno_installer_runs_silently_into_the_chosen_folder_and_uninstalls_silently(tmp_path, monkeypatch):
    calls = []

    def command(args, **kwargs):
        args = [str(a) for a in args]
        calls.append(args)
        if args[0].endswith("setup.exe"):
            dest = Path(next(a for a in args if a.startswith("/DIR="))[5:])
            dest.mkdir(parents=True)
            (dest / "SPIKE.exe").write_text("app", encoding="utf-8")
            (dest / "unins000.exe").write_text("uninstaller", encoding="utf-8")
        else:
            (Path(args[0]).parent / "SPIKE.exe").unlink()

    monkeypatch.setattr(rmc.release, "command", command)
    installed = rmc.install_inno(tmp_path / "setup.exe", tmp_path / "root")
    for flag in ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"):
        assert flag in calls[0]
    assert f"/DIR={tmp_path / 'root' / 'SPIKE'}" in calls[0] and installed.argv[0].endswith("SPIKE.exe")
    assert not installed.removed()
    installed.remove()
    assert calls[1][0].endswith("unins000.exe") and "/VERYSILENT" in calls[1] and installed.removed()
    monkeypatch.setattr(rmc.release, "command", lambda args, **kw: None)  # an installer that installs nothing
    with pytest.raises(RuntimeError, match="did not leave SPIKE.exe"):
        rmc.install_inno(tmp_path / "setup.exe", tmp_path / "root2")


@pytest.mark.parametrize("fuse", [True, False])
def test_appimage_is_made_executable_and_uses_extract_and_run_without_fuse(tmp_path, fuse):
    source = tmp_path / "SPIKE.AppImage"
    source.write_bytes(b"image")
    installed = rmc.install_appimage(source, tmp_path / "root", fuse=fuse)
    dest = tmp_path / "root" / "SPIKE.AppImage"
    if os.name != "nt":
        assert os.access(dest, os.X_OK)
    assert installed.argv == ([str(dest)] if fuse else [str(dest), "--appimage-extract-and-run"])
    assert installed.method == ("appimage" if fuse else "appimage-extract-and-run")
    installed.remove()
    assert installed.removed() and source.exists()


def test_hub_expectation_comes_from_the_apps_catalog_and_refuses_a_missing_hash(monkeypatch):
    from spike.runtime import models

    async def info(client, repo, filename):
        info.seen = (repo, filename)
        return {"size": 123, "sha256": "c" * 64, "license": "apache-2.0"}

    monkeypatch.setattr(models, "remote_file_info", info)
    expected = rmc.hub_expectation()
    assert info.seen == (models.MODELS["qwen3.5-4b"].repo, FILENAME) and expected.filename == FILENAME
    assert (expected.sha256, expected.size, expected.license) == ("c" * 64, 123, "apache-2.0")

    async def unhashed(client, repo, filename):
        return {"size": 123, "sha256": None, "license": "mit"}

    monkeypatch.setattr(models, "remote_file_info", unhashed)
    with pytest.raises(ValueError, match="no SHA-256"):
        rmc.hub_expectation()


def test_install_refuses_a_target_for_another_operating_system(tmp_path):
    other = "Windows-AMD64" if platform.system() != "Windows" else "Linux-x86_64"
    with pytest.raises(ValueError, match="matching OS"):
        rmc.install_artifact(other, tmp_path / "x", tmp_path / "root")


def test_listening_ports_and_peak_rss_are_measured_for_real_processes():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        assert sock.getsockname()[1] in rmc.listening_ports(os.getpid())
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        name = psutil.Process(child.pid).name().lower()
        meter = rmc.PeakRss(os.getpid(), name=name, interval=0.05)
        meter.start()
        time.sleep(0.4)
        peak = meter.stop()
        assert peak["peak_rss_mib"] > 1 and peak["peak_rss_source"] in {"VmHWM", "peak_wset", "sampled"}
    finally:
        child.kill()
        child.wait()
    assert rmc.PeakRss(os.getpid(), name="no-such-process").stop() == {"peak_rss_mib": None, "peak_rss_source": None}


def test_parse_metrics_reads_llama_servers_gauges():
    text = "# HELP a b\nllamacpp:prompt_tokens_seconds 12.5\nllamacpp:predicted_tokens_seconds 3\nother 1\n"
    assert rmc.parse_metrics(text) == {"prompt_tokens_per_second": 12.5, "generation_tokens_per_second": 3.0}
    assert rmc.parse_metrics("") == {"prompt_tokens_per_second": None, "generation_tokens_per_second": None}


def test_profile_snapshot_lists_every_file_with_its_size(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "m.gguf").write_bytes(b"1234")
    (tmp_path / "setup.json").write_text("{}", encoding="utf-8")
    assert rmc.profile_snapshot(tmp_path) == {"models/m.gguf": 4, "setup.json": 2}
    assert rmc.profile_snapshot(tmp_path / "absent") == {}


def test_uninstall_that_damages_the_profile_is_reported(world):
    home = world.tmp / "work" / "spike-home"

    def install(target, artifact, root):
        installed = world.install(target, artifact, root)

        def remove():
            installed.remove()
            (home / "models" / FILENAME).write_bytes(b"cut")  # an uninstaller that eats the user's model

        return rmc.Installed("fake", installed.argv, remove, installed.removed)

    result = rmc.run_check(world.config(), expected_model=lambda: EXPECTED, install=install)
    assert result["failed_stage"] == "uninstall" and "changed the user's profile" in result["error"]


def test_source_run_must_be_a_successful_native_installers_run_with_live_artifacts():
    run = {"name": "Native installers", "path": ".github/workflows/release.yml", "status": "completed",
           "conclusion": "success", "head_sha": SHA, "run_number": 7, "created_at": "2026-11-02T10:00:00Z"}
    artifacts = {"artifacts": [{"name": f"native-{t}", "expired": False} for t in rmc.release.TARGETS]}
    assert rmc.check_source_run(run, artifacts) == {"head_sha": SHA, "run_number": 7, "created_at": "2026-11-02T10:00:00Z"}
    tagged = {**run, "path": ".github/workflows/release.yml@refs/tags/v0.1.0"}
    assert rmc.check_source_run(tagged, artifacts)["run_number"] == 7
    for change, message in (({"name": "CI"}, "not a"), ({"path": ".github/workflows/ci.yml"}, "not a"),
                            ({"conclusion": "failure"}, "did not succeed"), ({"status": "in_progress"}, "did not succeed"),
                            ({"head_sha": "short"}, "source commit")):
        with pytest.raises(ValueError, match=message):
            rmc.check_source_run({**run, **change}, artifacts)
    with pytest.raises(ValueError, match="expired"):
        rmc.check_source_run(run, {"artifacts": [{"name": f"native-{t}", "expired": t.startswith("Win")}
                                                 for t in rmc.release.TARGETS]})
    with pytest.raises(ValueError, match="no native-Linux-x86_64"):
        rmc.check_source_run(run, {"artifacts": artifacts["artifacts"][:2]})


def test_source_command_reads_the_json_and_writes_github_outputs(tmp_path, monkeypatch, capsys):
    run = {"name": "Native installers", "path": ".github/workflows/release.yml", "status": "completed",
           "conclusion": "success", "head_sha": SHA, "run_number": 9, "created_at": "2026-11-02T10:00:00Z"}
    (tmp_path / "run.json").write_text(json.dumps(run), encoding="utf-8")
    (tmp_path / "artifacts.json").write_text(json.dumps(
        {"artifacts": [{"name": f"native-{t}", "expired": False} for t in rmc.release.TARGETS]}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out.txt"))
    assert rmc.main(["source", "--run", str(tmp_path / "run.json"), "--artifacts", str(tmp_path / "artifacts.json")]) == 0
    assert "run #9" in capsys.readouterr().out
    assert (tmp_path / "out.txt").read_text(encoding="utf-8").splitlines()[0] == f"head_sha={SHA}"


def test_chat_stream_without_a_usage_report_leaves_the_rate_unknown_instead_of_guessing(tmp_path):
    body = ("data: " + json.dumps({"choices": [{"delta": {"content": "Hi"}}]}) + "\n\n"
            "data: " + json.dumps({"choices": [{"delta": {"content": " there"}, "finish_reason": "stop"}]}) + "\n\n"
            "data: [DONE]\n\n")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=body.encode(),
                                                                   headers={"content-type": "text/event-stream"}))
    check = rmc.Check(rmc.Config(target="Linux-x86_64", artifacts=tmp_path, work=tmp_path / "w", out=tmp_path / "o.json"))
    check.client = httpx.Client(transport=transport, base_url="http://127.0.0.1:1")
    check.sampler = rmc.PeakRss(os.getpid())
    check.base_url = "http://example.invalid"  # not loopback: /metrics must not be requested
    check.ask()
    chat = check.result["chat"]
    assert chat["answer"] == "Hi there" and chat["completion_tokens"] is None and chat["tokens_per_second"] is None
    assert chat["stream_chunks"] == 2 and check.result["llama_metrics"] == {}


# ---------------------------------------------------------------------- the workflow
def test_workflow_is_manual_read_only_clean_machine_per_os_and_pins_its_tools():
    text = (ROOT / ".github/workflows/installers-real-model.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    triggers = doc.get("on", doc.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    assert triggers["workflow_dispatch"]["inputs"]["run_id"]["required"] is True
    assert doc["permissions"] == {"contents": "read", "actions": "read"}
    check = doc["jobs"]["check"]
    assert {m["target"]: m["os"] for m in check["strategy"]["matrix"]["include"]} == {
        "Darwin-arm64": "macos-latest", "Windows-AMD64": "windows-2022", "Linux-x86_64": "ubuntu-24.04"}
    assert set(check["strategy"]["matrix"]["include"][0]) == {"os", "target"} and check["strategy"]["fail-fast"] is False
    assert check["timeout-minutes"] >= 90 and set(check["needs"]) == {"lint", "source"}
    download = next(s for s in check["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact@v4"))
    assert download["with"]["run-id"] == "${{ inputs.run_id }}" and download["with"]["github-token"] == "${{ github.token }}"
    assert download["with"]["name"] == "native-${{ matrix.target }}"
    assert "--default-profile" in text and "packaging/real_model_check.py run" in text
    for job in doc["jobs"].values():  # a clean machine: nothing is restored between runs
        for step in job["steps"]:
            assert "actions/cache" not in str(step.get("uses")) and not any("cache" in k for k in step.get("with", {}))
    for job in doc["jobs"].values():  # the run id is only ever data (env or with:), never spliced into a script
        for step in job["steps"]:
            assert "${{ inputs" not in step.get("run", "") and "${{ github" not in step.get("run", "")
            assert "@" not in str(step.get("uses", "x@")).split("@", 1)[0]
    pinned = [s["run"] for s in check["steps"] if "pip install" in s.get("run", "")]
    assert pinned and all("httpx==" in p and "psutil==" in p for p in pinned)
    printed = [s for s in check["steps"] if "cat " in s.get("run", "")]
    assert printed and printed[0]["if"] == "always()"
    upload = next(s for s in check["steps"] if str(s.get("uses", "")).startswith("actions/upload-artifact@v4"))
    assert upload["if"] == "always()"
    assert set(m["target"] for m in check["strategy"]["matrix"]["include"]) == set(rmc.release.TARGETS)
