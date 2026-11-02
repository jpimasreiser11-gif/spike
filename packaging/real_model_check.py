"""I3: a native installer on a clean machine with the real model, driven only through the app's own interfaces.

`run` verifies the downloaded installer against its SPIKE-*.json evidence, installs it the way a user does (mount the
dmg and copy the .app, run the Inno Setup installer silently, chmod +x the AppImage), starts the installed program
without a window, and drives the first-run setup through `/api/setup` exactly as the wizard does, so the real
download, SHA-256 check and placement happen. It then checks the placed file against the Hub's hash itself, starts the
runtime, asks one question through the OpenAI-compatible API, quits, uninstalls and checks that the profile was kept.
Every number in the result is measured on the machine that ran it; nothing is estimated or carried over.

`source` checks that a workflow run id names a successful "Native installers" run whose installers are still
downloadable. The installed program is the one the build produced: package_smoke needs a frozen tiny fixture and cannot
carry a multi-GB model, so only its UI/catalog checks are shared (`package_smoke.check_app`). Text that is printed or
saved is scrubbed first: the work directory shows as <work>, the home directory as ~, secrets never appear.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import package_smoke
import psutil
import release

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1
QUESTION = "What is the capital of France? Answer in one short sentence."
GIB, MIB = 1024**3, 1024**2
LOOPBACK = {"127.0.0.1", "::1"}
SECRET_NAME = re.compile(r"TOKEN|SECRET|PASSW|CREDENTIAL|API_?KEY|PRIVATE|AUTH", re.I)
METRICS = {"prompt_tokens_per_second": "llamacpp:prompt_tokens_seconds",
           "generation_tokens_per_second": "llamacpp:predicted_tokens_seconds"}


class CheckFailed(Exception):
    """One stage failed; outcome is 'refused_resources' when the app itself declined to download the model."""

    def __init__(self, stage: str, message: str, outcome: str = "failed"):
        super().__init__(message)
        self.stage, self.outcome = stage, outcome


# ---------------------------------------------------------------------- printing without leaking
class Redactor:
    """Scrubs text before it is printed or saved: work dir -> <work>, home -> ~, user name in a path, secret values."""

    def __init__(self, work: Path, *, home: Path | None = None, user: str | None = None, env=None):
        env = os.environ if env is None else env
        secrets = {v for k, v in env.items() if SECRET_NAME.search(k) and len(v) >= 6}
        self.secrets = sorted(secrets, key=len, reverse=True)
        self.flags = re.IGNORECASE if os.name == "nt" else 0
        self.paths: list[tuple[str, str]] = []
        if home is None:
            with suppress(RuntimeError):
                home = Path.home()
        for path, label in ((work, "<work>"), (home, "~")):
            if path is None:
                continue
            forms = {str(path), path.as_posix()}
            with suppress(OSError):
                forms |= {str(path.resolve()), path.resolve().as_posix()}
            self.paths += [(form, label) for form in sorted(forms, key=len, reverse=True) if len(form) > 1]
        if user is None:
            with suppress(Exception):
                user = getpass.getuser()
        self.user = user if user and len(user) >= 3 else ""

    def __call__(self, text) -> str:
        text = str(text)
        for secret in self.secrets:
            text = text.replace(secret, "***")
        for needle, label in self.paths:
            text = re.sub(re.escape(needle), lambda _, label=label: label, text, flags=self.flags)
        if self.user:  # a user name is only removed where it is a path component
            text = re.sub(rf"(?<=[\\/]){re.escape(self.user)}(?![\w.-])", "<user>", text, flags=self.flags)
        return text

    def scrub(self, value):
        """The same, through nested JSON-like data (strings only; keys are ours)."""
        if isinstance(value, str):
            return self(value)
        if isinstance(value, dict):
            return {k: self.scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub(v) for v in value]
        return value


# ---------------------------------------------------------------------- evidence of the installer and of the source run
def verify_artifact(folder: Path, target: str) -> tuple[Path, dict]:
    """The downloaded installer must be exactly what the build recorded: its SHA-256 equals the SPIKE-*.json evidence."""
    if target not in release.TARGETS:
        raise ValueError(f"Unknown target {target}")
    records = sorted(folder.glob("SPIKE-*.json"))
    if len(records) != 1 or records[0].is_symlink():
        raise ValueError("Expected exactly one SPIKE-*.json evidence file next to the installer")
    record = json.loads(records[0].read_text(encoding="utf-8"))
    name, version = record.get("artifact"), release.validate_version(str(record.get("version")))
    if (record.get("target") != target or name != f"SPIKE-{version}-{target}.{release.TARGETS[target]}"
            or records[0].name != name + ".json"):
        raise ValueError("The evidence does not describe this target's installer")
    artifact = folder / name
    if artifact.is_symlink() or not artifact.is_file():
        raise ValueError("The installer named by the evidence is missing")
    release.validate_smoke(record["smoke"])
    actual = release.digest(artifact)
    if actual != record.get("sha256"):
        raise ValueError(f"Installer SHA-256 {actual} differs from the build evidence {record.get('sha256')}")
    return artifact, record


def from_main_or_a_tag_push(run: dict) -> bool:
    """Whether the run builds code that reached main or was tagged as a release. A branch that is not main can hold
    anything its author pushed, and the installers of its run would be tested and reported as SPIKE's. A tag push is
    the one event that names a tag in `head_branch`; release.yml only starts on `v*` tags, and the tag must be a
    version (a run started by hand on a tag is not accepted: start it on main, or push the tag)."""
    branch = run.get("head_branch")
    if branch == "main" and run.get("event") != "pull_request":
        return True
    if run.get("event") != "push" or not isinstance(branch, str) or not branch.startswith("v"):
        return False
    try:
        release.validate_version(branch[1:])
    except ValueError:
        return False
    return True


def check_source_run(run: dict, artifacts: dict) -> dict:
    """Only a completed, successful "Native installers" run of main or of a version tag push, with all three native-*
    artifacts unexpired, qualifies."""
    if run.get("name") != "Native installers" or not str(run.get("path", "")).split("@")[0].endswith("/release.yml"):
        raise ValueError('The run is not a "Native installers" run')
    repository, head = (run.get(k) or {} for k in ("repository", "head_repository"))
    if repository.get("full_name") and head.get("full_name") and repository["full_name"] != head["full_name"]:
        raise ValueError("The run comes from another repository (a fork); use a run of this repository")
    if not from_main_or_a_tag_push(run):
        raise ValueError(f"The run is from {run.get('head_branch')!r} ({run.get('event')}), not from main or a version "
                         "tag push; run Native installers on main, or push the release tag, and use that run")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ValueError(f"The run did not succeed (status {run.get('status')}, conclusion {run.get('conclusion')})")
    found = {a.get("name"): a for a in artifacts.get("artifacts", []) if isinstance(a, dict)}
    for target in release.TARGETS:
        artifact = found.get(f"native-{target}")
        if artifact is None:
            raise ValueError(f"The run has no native-{target} artifact")
        if artifact.get("expired"):
            raise ValueError(f"native-{target} has expired (artifacts are kept 7 days); run Native installers again")
    if not re.fullmatch(r"[0-9a-f]{40}", str(run.get("head_sha", ""))):
        raise ValueError("The run has no source commit")
    return {"head_sha": run["head_sha"], "run_number": int(run["run_number"]),
            "created_at": str(run.get("created_at", ""))}


# ---------------------------------------------------------------------- the machine and the model the Hub promises
def cpu_name() -> str:
    with suppress(Exception):
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
                                 timeout=10)
            if out.stdout.strip():
                return out.stdout.strip()
        elif sys.platform.startswith("linux"):
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name") and ":" in line:
                    return line.split(":", 1)[1].strip()
        elif os.environ.get("PROCESSOR_IDENTIFIER"):
            return os.environ["PROCESSOR_IDENTIFIER"]
    return platform.processor() or platform.machine() or "unknown"


def runner_info() -> dict:
    return {"os": platform.platform(), "machine": platform.machine(), "cpu": cpu_name(),
            "logical_cpus": psutil.cpu_count(logical=True), "physical_cpus": psutil.cpu_count(logical=False),
            "ram_gib": round(psutil.virtual_memory().total / GIB, 2), "python": platform.python_version()}


@dataclass(frozen=True)
class Expected:
    """What the Hub says the default model file is; the app's own check uses the same source."""

    model_id: str
    repo: str
    filename: str
    sha256: str
    size: int
    license: str


def hub_expectation() -> Expected:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from spike.runtime import models

    entry = models.MODELS["qwen3.5-4b"]
    filename = entry.filename(entry.default_quant)

    async def look() -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), follow_redirects=True) as client:
            return await models.remote_file_info(client, entry.repo, filename)

    info = asyncio.run(look())
    if not re.fullmatch(r"[0-9a-f]{64}", str(info.get("sha256"))) or not isinstance(info.get("size"), int):
        raise ValueError("The Hub gave no SHA-256 and size for the default model")
    return Expected(entry.id, entry.repo, filename, info["sha256"], info["size"], str(info.get("license")))


# ---------------------------------------------------------------------- installing and uninstalling like a user
@dataclass
class Installed:
    method: str
    argv: list[str]  # how a user starts it
    remove: Callable[[], None]
    removed: Callable[[], bool]


def fuse_available() -> bool:
    return Path("/dev/fuse").exists() and bool(shutil.which("fusermount3") or shutil.which("fusermount"))


def install_dmg(artifact: Path, root: Path) -> Installed:
    mount, apps = root / "mount", root / "Applications"
    mount.mkdir(parents=True)
    apps.mkdir()
    attach = [release.tool("hdiutil"), "attach", artifact, "-nobrowse", "-readonly", "-mountpoint", mount]
    release.command(attach, timeout=300)
    try:
        if not (mount / "SPIKE.app").is_dir():
            raise RuntimeError("The disk image has no SPIKE.app")
        shutil.copytree(mount / "SPIKE.app", apps / "SPIKE.app", symlinks=True)
    finally:
        release.command([release.tool("hdiutil"), "detach", mount], timeout=120)
    app = apps / "SPIKE.app"
    binary = app / "Contents/MacOS/SPIKE"
    if not binary.is_file():
        raise RuntimeError("The copied SPIKE.app has no Contents/MacOS/SPIKE")
    return Installed("dmg-copy-app", [str(binary)], lambda: shutil.rmtree(app), lambda: not app.exists())


def install_inno(artifact: Path, root: Path) -> Installed:
    dest = root / "SPIKE"
    release.command([artifact, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={dest}"], timeout=600)
    program, uninstaller = dest / "SPIKE.exe", dest / "unins000.exe"
    if not program.is_file() or not uninstaller.is_file():
        raise RuntimeError("The installer did not leave SPIKE.exe and its uninstaller in the chosen folder")

    def remove() -> None:
        release.command([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], timeout=300)
        deadline = time.monotonic() + 60  # the uninstaller finishes its work in a second process
        while program.exists() and time.monotonic() < deadline:
            time.sleep(1)

    return Installed("inno-silent", [str(program)], remove, lambda: not program.exists())


def install_appimage(artifact: Path, root: Path, fuse: bool | None = None) -> Installed:
    root.mkdir(parents=True)
    dest = root / artifact.name
    shutil.copy2(artifact, dest)
    dest.chmod(dest.stat().st_mode | 0o755)  # artifact downloads do not keep the executable bit
    fuse = fuse_available() if fuse is None else fuse
    argv = [str(dest)] if fuse else [str(dest), "--appimage-extract-and-run"]
    return Installed("appimage" if fuse else "appimage-extract-and-run", argv, dest.unlink, lambda: not dest.exists())


def install_artifact(target: str, artifact: Path, root: Path) -> Installed:
    if target.split("-")[0] != platform.system():
        raise ValueError("Run on the matching OS runner")
    if target.startswith("Darwin"):
        return install_dmg(artifact, root)
    if target.startswith("Windows"):
        return install_inno(artifact, root)
    return install_appimage(artifact, root)


# ---------------------------------------------------------------------- the installed program, started without a window
def app_env(home: Path | None, base=None) -> dict[str, str]:
    """A clean user environment: no SPIKE_* settings of the runner, no secrets, no browser to open, no keychain prompt."""
    env = {k: v for k, v in (os.environ if base is None else base).items()
           if not k.startswith(("SPIKE_", "HF_")) and not SECRET_NAME.search(k)}
    env["SPIKE_NO_KEYRING"] = "1"
    if os.name != "nt":
        env["BROWSER"] = "true"  # the launcher falls back to webbrowser.open; this makes it a no-op
    if home is not None:
        env["SPIKE_HOME"] = str(home)
    return env


def listening_ports(pid: int) -> list[int]:
    """Loopback TCP ports a process (or any child of it, as with an AppImage runtime) listens on."""
    try:
        root = psutil.Process(pid)
        tree = [root, *root.children(recursive=True)]
    except psutil.Error:
        return []
    ports = set()
    for proc in tree:
        with suppress(psutil.Error, OSError):
            for conn in (getattr(proc, "net_connections", None) or proc.connections)(kind="tcp"):
                if conn.status == psutil.CONN_LISTEN and conn.laddr and conn.laddr.ip in LOOPBACK:
                    ports.add(conn.laddr.port)
    return sorted(ports)


def healthy(url: str) -> bool:
    try:
        response = httpx.get(url + "/api/health", timeout=2.0, trust_env=False)
        return response.status_code == 200 and response.json().get("ok") is True
    except (httpx.HTTPError, ValueError):
        return False


def tail_file(path: Path, lines: int = 15) -> str:
    with suppress(OSError):
        return "\n".join(path.read_bytes()[-8192:].decode("utf-8", errors="replace").splitlines()[-lines:])
    return ""


class App:
    """The installed program as its own process, output to a file. The port is whatever the launcher picked."""

    def __init__(self, argv: list[str], env: dict[str, str], log_path: Path, cwd: Path):
        self.log_path = log_path
        self.log = log_path.open("wb")
        self.proc = subprocess.Popen(argv, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=self.log,
                                     stderr=subprocess.STDOUT, start_new_session=os.name != "nt")

    def wait_ready(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while True:
            code = self.proc.poll()
            if code is not None:
                raise CheckFailed("start", f"the app exited with code {code} before it answered /api/health")
            for port in listening_ports(self.proc.pid):
                if healthy(f"http://127.0.0.1:{port}"):
                    return f"http://127.0.0.1:{port}"
            if time.monotonic() >= deadline:
                raise CheckFailed("start", f"the app did not answer /api/health within {timeout:.0f} s")
            time.sleep(0.5)

    def wait_exit(self, timeout: float) -> int | None:
        with suppress(subprocess.TimeoutExpired):
            return self.proc.wait(timeout)
        return None

    def alive(self) -> bool:
        return self.proc.poll() is None

    def kill(self) -> None:
        try:
            tree = [*psutil.Process(self.proc.pid).children(recursive=True), psutil.Process(self.proc.pid)]
        except psutil.Error:
            tree = []
        for proc in tree:
            with suppress(psutil.Error):
                proc.kill()
        with suppress(subprocess.TimeoutExpired):
            self.proc.wait(10)

    def close(self) -> None:
        self.log.close()

    def tail(self) -> str:
        return tail_file(self.log_path)


class PeakRss:
    """Peak resident memory of llama-server: samples every `interval` s and keeps the OS's own peak where there is one
    (Linux VmHWM, Windows peak working set). On macOS only samples exist. RSS counts memory-mapped model pages."""

    def __init__(self, root_pid: int, name: str = "llama-server", interval: float = 0.2):
        self.root, self.name, self.interval = root_pid, name, interval
        self.pids: dict[int, dict[str, int]] = {}
        self.stopped = threading.Event()
        self.thread: threading.Thread | None = None

    def track(self, pid: int) -> None:
        self.pids.setdefault(pid, {"sampled": 0, "os": 0})
        self.sample()

    def os_peak(self, pid: int) -> int:
        with suppress(OSError, ValueError, IndexError):
            if sys.platform.startswith("linux"):
                for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii", errors="replace").splitlines():
                    if line.startswith("VmHWM:"):
                        return int(line.split()[1]) * 1024
        with suppress(psutil.Error, AttributeError):
            return int(psutil.Process(pid).memory_info().peak_wset)  # Windows only
        return 0

    def sample(self) -> None:
        with suppress(psutil.Error):
            for child in psutil.Process(self.root).children(recursive=True):
                with suppress(psutil.Error):
                    if self.name in child.name().lower():
                        self.pids.setdefault(child.pid, {"sampled": 0, "os": 0})
        for pid, seen in list(self.pids.items()):
            with suppress(psutil.Error):
                seen["sampled"] = max(seen["sampled"], psutil.Process(pid).memory_info().rss)
                seen["os"] = max(seen["os"], self.os_peak(pid))

    def start(self) -> None:
        def loop() -> None:
            while not self.stopped.wait(self.interval):
                self.sample()

        self.thread = threading.Thread(target=loop, name="spike-rss", daemon=True)
        self.thread.start()

    def stop(self) -> dict:
        self.stopped.set()
        if self.thread:
            self.thread.join(5)
        self.sample()
        best = max(((max(v["sampled"], v["os"]), v) for v in self.pids.values()), key=lambda x: x[0], default=(0, None))
        if best[1] is None or not best[0]:
            return {"peak_rss_mib": None, "peak_rss_source": None}
        os_name = "VmHWM" if sys.platform.startswith("linux") else "peak_wset"
        return {"peak_rss_mib": round(best[0] / MIB, 1),
                "peak_rss_source": os_name if best[1]["os"] >= best[1]["sampled"] else "sampled"}


def parse_metrics(text: str) -> dict[str, float | None]:
    """llama-server's own Prometheus gauges (average since it started); None when it does not report one."""
    values = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and not line.startswith("#"):
            with suppress(ValueError):
                values[parts[0]] = float(parts[1])
    return {key: values.get(metric) for key, metric in METRICS.items()}


def profile_snapshot(home: Path) -> dict[str, int]:
    """Every file of the user's profile with its size, to prove an uninstall touched none of them."""
    if not home.is_dir():
        return {}
    return {p.relative_to(home).as_posix(): p.stat().st_size for p in sorted(home.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------- the check
@dataclass
class Config:
    target: str
    artifacts: Path
    work: Path
    out: Path
    default_profile: bool = False  # the app's own default ~/.spike, only on a machine that has none yet
    home: Path | None = None  # otherwise <work>/spike-home
    source_run: str = ""
    question: str = QUESTION
    chat_model: str = "spike-auto"
    max_tokens: int = 256
    start_timeout: float = 240
    download_timeout: float = 3600
    stall_timeout: float = 300
    runtime_timeout: float = 420
    chat_timeout: float = 600
    quit_timeout: float = 90
    poll_seconds: float = 1.0


@dataclass
class Check:
    cfg: Config
    expected_model: Callable[[], Expected] = hub_expectation
    install: Callable[[str, Path, Path], Installed] = install_artifact
    result: dict = field(default_factory=dict)

    def __post_init__(self):
        self.t0 = time.perf_counter()
        self.redact = Redactor(self.cfg.work)
        self.app = self.installed = self.client = self.sampler = self.expected = None
        self.home: Path = self.cfg.work
        self.digest = self.llama_pid = self.placed = None
        self.base_url = ""
        self.uninstalled = False
        self.result.update(
            schema=SCHEMA, ok=False, outcome="failed", failed_stage=None, error=None, target=self.cfg.target,
            source_run=self.cfg.source_run or None, runner=runner_info(), artifact={}, install={}, app={}, setup={},
            model={}, runtime={}, chat={}, llama_metrics={}, uninstall={}, phases=[], wall_seconds=None)

    def say(self, message: str) -> None:
        line = f"[real-model +{time.perf_counter() - self.t0:7.1f}s] {self.redact(message)}"
        print(line.encode("ascii", "backslashreplace").decode("ascii"), flush=True)

    def save(self) -> None:
        self.cfg.out.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cfg.out.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.redact.scrub(self.result), indent=2), encoding="utf-8")
        temp.replace(self.cfg.out)

    @contextmanager
    def phase(self, name: str):
        started = time.perf_counter()
        self.say(f"{name}: start")
        record = {"name": name, "ok": False, "seconds": None}
        self.result["phases"].append(record)
        try:
            yield
        except CheckFailed:
            raise
        except Exception as exc:
            raise CheckFailed(name, f"{type(exc).__name__}: {exc}") from exc
        finally:
            record["seconds"] = round(time.perf_counter() - started, 3)
            self.save()
        record["ok"] = True
        self.say(f"{name}: ok in {record['seconds']} s")
        self.save()

    # -------------------------------------------------------------- stages
    def prepare(self) -> None:
        cfg = self.cfg
        if cfg.work.exists() and any(cfg.work.iterdir()):
            raise CheckFailed("prepare", "the work directory must be new or empty")
        cfg.work.mkdir(parents=True, exist_ok=True)
        if cfg.default_profile:
            self.home = Path.home() / ".spike"
            if self.home.exists():
                raise CheckFailed("prepare", "this machine already has a SPIKE profile; not a clean machine, not touched")
            self.result["profile"] = "default (~/.spike), absent before the run"
        else:
            self.home = cfg.home or cfg.work / "spike-home"
            self.result["profile"] = "temporary directory"
        self.expected = self.expected_model()  # the Hub's promise, before anything is installed
        self.result["model"].update(id=self.expected.model_id, repo=self.expected.repo, file=self.expected.filename,
                                    license=self.expected.license, expected_bytes=self.expected.size,
                                    expected_sha256=self.expected.sha256)

    def verify(self) -> Path:
        artifact, record = verify_artifact(self.cfg.artifacts, self.cfg.target)
        self.result["artifact"] = {"name": artifact.name, "bytes": artifact.stat().st_size, "sha256": record["sha256"],
                                   "sha256_verified": True, "version": record["version"], "commit": record["commit"]}
        return artifact

    def install_app(self, artifact: Path) -> None:
        started = time.perf_counter()
        self.installed = self.install(self.cfg.target, artifact, self.cfg.work / "install")
        self.result["install"] = {"method": self.installed.method, "seconds": round(time.perf_counter() - started, 3)}

    def start_app(self) -> None:
        env = app_env(None if self.cfg.default_profile else self.home)
        self.result["app"]["env_overrides"] = sorted(set(env) & {"SPIKE_NO_KEYRING", "SPIKE_HOME", "BROWSER"})
        started = time.perf_counter()
        self.app = App(self.installed.argv, env, self.cfg.work / "app.log", self.cfg.work)
        try:
            url = self.app.wait_ready(self.cfg.start_timeout)
        except CheckFailed:
            self.result["app"]["log_tail"] = self.app.tail()
            raise
        self.client = httpx.Client(base_url=url, timeout=30.0, trust_env=False)
        self.result["app"]["start_seconds"] = round(time.perf_counter() - started, 3)

    def model_setup(self) -> None:
        client, cfg = self.client, self.cfg
        status = client.get("/api/setup").json()
        guard = {"can_download": status.get("can_download"), "complete_before": status.get("complete"),
                 "disk_free_gib": round(status.get("disk_free", 0) / GIB, 2),
                 "ram_total_gib": round(status.get("ram_total", 0) / GIB, 2),
                 "required_disk_gib": round(status.get("required_disk", 0) / GIB, 2),
                 "required_ram_gib": round(status.get("required_ram", 0) / GIB, 2)}
        self.result["setup"] = guard
        if not status.get("enabled"):
            raise CheckFailed("setup", "the first-run setup is not enabled (the app was not started by the "
                              "desktop launcher)")
        if status.get("complete"):
            raise CheckFailed("setup", "the profile already has an installed model; this is not a first run")
        if not status.get("can_download"):
            raise CheckFailed("setup", "the app's own resource guard refuses the download on this machine "
                              f"(RAM {guard['ram_total_gib']} GiB of {guard['required_ram_gib']} required, free disk "
                              f"{guard['disk_free_gib']} GiB of {guard['required_disk_gib']}); it was not bypassed",
                              outcome="refused_resources")
        started = time.perf_counter()
        response = client.post("/api/setup/download", json={"specialists": []})
        if response.status_code != 200:
            raise CheckFailed("setup", f"the app refused the download request with HTTP {response.status_code}")
        last_move = last_log = time.monotonic()
        deadline, last_done = last_move + cfg.download_timeout, -1
        while True:
            status = client.get("/api/setup").json()
            job, now = status["job"], time.monotonic()
            if job["status"] == "done":
                break
            if job["status"] == "failed":
                raise CheckFailed("setup", "the app reported the model installation as failed (hash, license or "
                                  "network step; the app deliberately keeps no reason)")
            if job.get("done") != last_done:
                last_done, last_move = job.get("done"), now
            elif now - last_move > cfg.stall_timeout:
                raise CheckFailed("setup", f"the download stalled: no progress for {cfg.stall_timeout:.0f} s at "
                                  f"{job.get('done')} of {job.get('total')} bytes")
            if now > deadline:
                raise CheckFailed("setup", f"the download did not finish within {cfg.download_timeout:.0f} s")
            if now - last_log >= 30:
                last_log = now
                self.say(f"downloading: {(job.get('done') or 0) // MIB} of {(job.get('total') or 0) // MIB} MiB")
            time.sleep(cfg.poll_seconds)
        seconds = time.perf_counter() - started
        self.result["model"]["download_seconds"] = round(seconds, 3)
        guard["complete_after"] = bool(client.get("/api/setup").json().get("complete"))
        if not guard["complete_after"]:
            raise CheckFailed("setup", "the job finished but the app does not consider the setup complete")

    def check_model(self) -> None:
        model, expected = self.result["model"], self.expected
        configured = (self.client.get("/api/settings").json().get("local_runtime") or {}).get("model") or ""
        placed = Path(configured) if configured else None
        if placed is None or not placed.is_file():
            raise CheckFailed("model", "the app did not configure an existing model file")
        models_dir = (self.home / "models").resolve()
        if not placed.resolve().is_relative_to(models_dir):
            raise CheckFailed("model", "the model was placed outside the profile's models folder")
        model["file"] = placed.name
        model["path"] = placed.resolve().relative_to(self.home.resolve()).as_posix()
        model["partial_files_left"] = len(list(models_dir.glob("*.part")))
        size = placed.stat().st_size
        started = time.perf_counter()
        self.digest = release.digest(placed)
        model.update(bytes=size, sha256=self.digest, hash_seconds=round(time.perf_counter() - started, 3),
                     placed_in_profile=True)
        seconds = model.get("download_seconds")
        model["download_mib_per_s"] = round(size / MIB / seconds, 2) if seconds else None
        model["hash_match"] = self.digest == expected.sha256 and size == expected.size
        if placed.name != expected.filename:
            raise CheckFailed("model", f"the app placed {placed.name} but this commit's catalog expects "
                              f"{expected.filename}; rebuild the installers from the same commit")
        if not model["hash_match"]:
            raise CheckFailed("model", f"the placed model ({size} bytes, SHA-256 {self.digest}) differs from the Hub's "
                              f"({expected.size} bytes, SHA-256 {expected.sha256}); refusing to run it")
        self.placed = placed

    def start_runtime(self) -> None:
        self.sampler = PeakRss(self.app.proc.pid)
        self.sampler.start()
        started = time.perf_counter()
        log = self.home / "logs" / "llama-server.log"
        try:
            response = self.client.post("/api/runtime/start", json={}, timeout=self.cfg.runtime_timeout)
        except httpx.HTTPError as exc:
            self.result["runtime"]["log_tail"] = tail_file(log)
            raise CheckFailed("runtime", f"the runtime did not start within {self.cfg.runtime_timeout:.0f} s "
                              f"({type(exc).__name__})") from exc
        if response.status_code != 200:
            self.result["runtime"]["log_tail"] = tail_file(log)
            raise CheckFailed("runtime", f"the app could not start the runtime (HTTP {response.status_code}): "
                              f"{response.text[:300]}")
        runtime = response.json()
        if runtime.get("running") is not True:
            raise CheckFailed("runtime", "the app did not report the runtime as running")
        self.llama_pid = runtime.get("pid") if isinstance(runtime.get("pid"), int) else None
        if self.llama_pid:
            self.sampler.track(self.llama_pid)
        self.base_url = str(runtime.get("base_url") or "")
        self.result["runtime"].update(start_seconds=round(time.perf_counter() - started, 3),
                                      load_seconds=runtime.get("load_seconds"), context=runtime.get("context"))

    def ask(self) -> None:
        cfg, chat = self.cfg, self.result["chat"]
        payload = {"model": cfg.chat_model, "messages": [{"role": "user", "content": cfg.question}], "stream": True,
                   "stream_options": {"include_usage": True}, "max_tokens": cfg.max_tokens, "temperature": 0}
        text, reasoning, usage, finish, chunks = [], [], None, None, 0
        first = last = None
        sent = time.perf_counter()
        timeout = httpx.Timeout(30.0, read=cfg.chat_timeout)
        with self.client.stream("POST", "/v1/chat/completions", json=payload, timeout=timeout) as response:
            if response.status_code != 200:
                response.read()
                raise CheckFailed("chat", f"the chat API answered HTTP {response.status_code}: {response.text[:300]}")
            for line in response.iter_lines():
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                event = json.loads(line[5:])
                if event.get("error"):
                    message = str(event["error"].get("message"))[:300]
                    raise CheckFailed("chat", f"the chat API reported an error: {message}")
                usage = event.get("usage") or usage
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    finish = choice.get("finish_reason") or finish
                    for key, bucket in (("content", text), ("reasoning_content", reasoning)):
                        if delta.get(key):
                            bucket.append(delta[key])
                            chunks += 1
                            last = time.perf_counter()
                            first = first or last
        answer = "".join(text).strip()
        tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        decode = (last - first) if first and last else None
        chat.update(
            endpoint="/v1/chat/completions", model=cfg.chat_model, question=cfg.question, max_tokens=cfg.max_tokens,
            ttft_seconds=round(first - sent, 3) if first else None, total_seconds=round(time.perf_counter() - sent, 3),
            prompt_tokens=usage.get("prompt_tokens") if isinstance(usage, dict) else None, completion_tokens=tokens,
            tokens_per_second=round((tokens - 1) / decode, 2) if isinstance(tokens, int) and tokens > 1 and decode
            else None, stream_chunks=chunks, finish_reason=finish, answer_chars=len(answer),
            reasoning_chars=len("".join(reasoning)), answer=answer[:300])
        if not answer:
            raise CheckFailed("chat", f"no answer text within {cfg.max_tokens} tokens ({chunks} streamed chunks, "
                              f"{chat['reasoning_chars']} characters of reasoning)")
        self.result["runtime"].update(self.sampler.stop())
        metrics = {}
        if urlsplit(self.base_url).hostname in LOOPBACK:  # never follow an address the app gave us off this machine
            with suppress(httpx.HTTPError):
                metrics = parse_metrics(httpx.get(self.base_url + "/metrics", timeout=10, trust_env=False).text)
        self.result["llama_metrics"] = metrics

    def quit_app(self) -> None:
        started = time.perf_counter()
        self.client.post("/api/setup/quit", json={}).raise_for_status()  # what the Quit button sends
        code = self.app.wait_exit(self.cfg.quit_timeout)
        if code is None:
            raise CheckFailed("quit", f"the app was still running {self.cfg.quit_timeout:.0f} s after Quit")
        self.result["app"].update(exit_code=code, quit_seconds=round(time.perf_counter() - started, 3))
        if self.llama_pid:
            deadline = time.monotonic() + 20
            while psutil.pid_exists(self.llama_pid) and time.monotonic() < deadline:
                time.sleep(0.25)
            gone = not psutil.pid_exists(self.llama_pid)
            self.result["runtime"]["stopped_with_app"] = gone
            if not gone:
                raise CheckFailed("quit", "llama-server was still running after the app exited")
        if code != 0:
            raise CheckFailed("quit", f"the app exited with code {code} after Quit")

    def uninstall(self) -> None:
        before = profile_snapshot(self.home)
        started = time.perf_counter()
        self.installed.remove()
        self.uninstalled = True
        if not self.installed.removed():
            raise CheckFailed("uninstall", "the program is still installed after uninstalling")
        after = profile_snapshot(self.home)
        lost = sorted(set(before) - set(after))
        changed = sorted(k for k in before if k in after and before[k] != after[k])
        if lost or changed:
            raise CheckFailed("uninstall", f"uninstalling changed the user's profile: missing {lost[:5]}, "
                              f"resized {changed[:5]}")
        intact = release.digest(self.placed) == self.digest
        self.result["uninstall"] = {"seconds": round(time.perf_counter() - started, 3), "program_removed": True,
                                    "profile_kept": True, "profile_files": len(after), "model_intact": intact}
        if not intact:
            raise CheckFailed("uninstall", "the model file changed while uninstalling")

    # -------------------------------------------------------------- the whole run
    def run(self) -> dict:
        try:
            with self.phase("prepare"):
                self.prepare()
            with self.phase("verify"):
                artifact = self.verify()
            with self.phase("install"):
                self.install_app(artifact)
            with self.phase("start"):
                self.start_app()
            with self.phase("ui"):
                self.result["app"].update(package_smoke.check_app(self.client))
            with self.phase("setup"):
                self.model_setup()
            with self.phase("model"):
                self.check_model()
            with self.phase("runtime"):
                self.start_runtime()
            with self.phase("chat"):
                self.ask()
            with self.phase("quit"):
                self.quit_app()
            with self.phase("uninstall"):
                self.uninstall()
            self.result.update(ok=True, outcome="ok")
        except CheckFailed as exc:
            self.result.update(outcome=exc.outcome, failed_stage=exc.stage, error=str(exc))
        except BaseException as exc:  # a cancelled run still leaves its partial evidence
            self.result.update(failed_stage="unexpected", error=f"{type(exc).__name__}: {exc}")
            if not isinstance(exc, Exception):
                raise
        finally:
            self.cleanup()
            self.result["wall_seconds"] = round(time.perf_counter() - self.t0, 3)
            self.save()
        self.say(f"result: {'ok' if self.result['ok'] else 'failed at ' + str(self.result['failed_stage'])}")
        final = self.redact.scrub(self.result)  # what is returned, printed and saved is always the scrubbed form
        print(json.dumps(final, indent=2), flush=True)
        return final

    def cleanup(self) -> None:
        """Whatever failed, leave nothing running and nothing installed on the runner."""
        if self.sampler and "peak_rss_mib" not in self.result["runtime"]:
            self.result["runtime"].update(self.sampler.stop())
        if self.app:
            if self.app.alive():
                self.app.kill()
                self.result["app"]["killed"] = True
            self.app.close()
        if self.client:
            self.client.close()
        if self.installed and not self.uninstalled:
            try:
                self.installed.remove()
                self.result["uninstall"] = {"after_failure": True, "program_removed": self.installed.removed()}
            except Exception as exc:
                self.result["uninstall"] = {"after_failure": True, "program_removed": False,
                                            "error": f"{type(exc).__name__}: {exc}"}


def run_check(cfg: Config, **hooks) -> dict:
    return Check(cfg, **hooks).run()


# ---------------------------------------------------------------------- command line
def write_outputs(values: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as out:
            out.write("".join(f"{k}={v}\n" for k, v in values.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    src = sub.add_parser("source", help="check that a workflow run id names a usable Native installers run")
    src.add_argument("--run", type=Path, required=True, help="JSON of GET /repos/OWNER/REPO/actions/runs/ID")
    src.add_argument("--artifacts", type=Path, required=True, help="JSON of that run's /artifacts")
    run = sub.add_parser("run", help="install, set up with the real model, ask a question, uninstall")
    run.add_argument("--target", choices=release.TARGETS, required=True)
    run.add_argument("--artifacts", type=Path, required=True, help="folder with the installer and its SPIKE-*.json")
    run.add_argument("--work", type=Path, required=True, help="new or empty folder for the install and the app's log")
    run.add_argument("--out", type=Path, required=True, help="where the result JSON is written")
    run.add_argument("--default-profile", action="store_true", help="use the app's own ~/.spike (refused if it exists)")
    run.add_argument("--source-run", default="", help="id of the Native installers run, recorded in the result")
    run.add_argument("--question", default=QUESTION)
    run.add_argument("--chat-model", default="spike-auto")
    run.add_argument("--max-tokens", type=int, default=256)
    for name, default in (("start", 240), ("download", 3600), ("stall", 300), ("runtime", 420), ("chat", 600),
                          ("quit", 90)):
        run.add_argument(f"--{name}-timeout", type=float, default=default, help="seconds")
    args = parser.parse_args(argv)
    if args.cmd == "source":
        found = check_source_run(json.loads(args.run.read_text(encoding="utf-8")),
                                 json.loads(args.artifacts.read_text(encoding="utf-8")))
        print(f"Native installers run #{found['run_number']} at {found['head_sha']} ({found['created_at']}) qualifies")
        write_outputs(found)
        return 0
    cfg = Config(target=args.target, artifacts=args.artifacts.resolve(), work=args.work.resolve(),
                 out=args.out.resolve(), default_profile=args.default_profile, source_run=args.source_run, question=args.question,
                 chat_model=args.chat_model, max_tokens=args.max_tokens, start_timeout=args.start_timeout,
                 download_timeout=args.download_timeout, stall_timeout=args.stall_timeout,
                 runtime_timeout=args.runtime_timeout, chat_timeout=args.chat_timeout, quit_timeout=args.quit_timeout)
    return 0 if run_check(cfg)["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
