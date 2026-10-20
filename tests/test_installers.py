"""scripts/install.sh and scripts/install.ps1, as far as they can be checked without Windows, a network or a 2.7 GB model.

install.sh runs for real in a scratch project and HOME, with fake pipx, curl and uname on PATH. What is pinned in it for Linux
without Homebrew is checked: the download is verified against its SHA-256 and kept only if it starts, llama-server is linked
where `spike doctor` looks for it, and the step asks first. install.ps1 is checked for syntax that Windows PowerShell 5.1 cannot read.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYSTEM_PATH = "/usr/bin:/bin"
TAG = re.search(r"^llama_tag=(\S+)$", (ROOT / "scripts" / "install.sh").read_text(), re.M).group(1)

linux_with_tools = pytest.mark.skipif(
    sys.platform != "linux" or not all(shutil.which(t, path=SYSTEM_PATH) for t in ("bash", "tar", "sha256sum")),
    reason="runs install.sh on Linux with bash, tar and sha256sum",
)

FAKE_CURL = """#!/bin/sh
# "downloads" $FAKE_ASSET into the file given with -o and logs the URL (the last argument)
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in -o) out="$2"; shift ;; *) url="$1" ;; esac
  shift
done
echo "$url" >> "$FAKE_LOG"
[ -z "$FAKE_CURL_FAILS" ] || exit 22
cp "$FAKE_ASSET" "$out"
"""
FAKE_PIPX = """#!/bin/sh
if [ "$1" = environment ]; then echo "$FAKE_BIN_DIR"; else echo "pipx $*"; fi
"""
FAKE_UNAME = """#!/bin/sh
if [ "$1" = -m ]; then echo "$FAKE_ARCH"; else echo Linux; fi
"""
# the real `spike doctor`, so that finding llama-server is SPIKE's own lookup and not the test's
FAKE_SPIKE = """#!/bin/sh
exec "$REAL_PYTHON" -c 'import sys; from spike.cli import main; sys.exit(main())' "$@"
"""
GOOD_SERVER = "#!/bin/sh\necho 'version: 0.0.0 (build fake)'\n"
BROKEN_SERVER = "#!/bin/sh\necho 'llama-server: error while loading shared libraries: libgomp.so.1: cannot open shared object file' >&2\nexit 127\n"


class Project:
    """A copy of install.sh in a scratch project (web/dist stubbed), a scratch HOME, and the fakes."""

    def __init__(self, tmp_path: Path):
        self.root, self.home, self.bin = tmp_path / "project", tmp_path / "home", tmp_path / "bin"
        self.log = tmp_path / "curl.log"
        self.log.touch()
        self.asset = tmp_path / "asset.tar.gz"
        for d in (self.root / "scripts", self.root / "web" / "dist", self.home / ".local" / "bin", self.bin):
            d.mkdir(parents=True)
        (self.root / "web" / "dist" / "index.html").write_text("<html></html>")
        for name, body in (("curl", FAKE_CURL), ("pipx", FAKE_PIPX), ("uname", FAKE_UNAME)):
            self.script(self.bin / name, body)
        self.script(self.home / ".local" / "bin" / "spike", FAKE_SPIKE)
        (self.bin / "python3").symlink_to(sys.executable)
        self.install = self.root / "scripts" / "install.sh"
        self.install.write_text((ROOT / "scripts" / "install.sh").read_text())
        self.link = self.home / ".spike" / "bin" / "llama-server"
        self.dest = self.home / ".local" / "share" / "spike" / "llama.cpp" / TAG

    @staticmethod
    def script(path: Path, body: str) -> None:
        path.write_text(body)
        path.chmod(0o755)

    def serve(self, server_body: str, pin: str | None = "x64") -> str:
        """Make the fake curl hand out an archive holding this llama-server; pin its hash for this arch (x64, arm64) if asked."""
        tree = self.asset.parent / "llama-tree" / f"llama-{TAG}"
        tree.mkdir(parents=True, exist_ok=True)
        self.script(tree / "llama-server", server_body)
        with tarfile.open(self.asset, "w:gz") as tar:
            tar.add(tree, arcname=f"llama-{TAG}")
        digest = hashlib.sha256(self.asset.read_bytes()).hexdigest()
        if pin:
            text, n = re.subn(rf"^llama_sha_{pin}=[0-9a-f]{{64}}$", f"llama_sha_{pin}={digest}", self.install.read_text(), flags=re.M)
            assert n == 1
            self.install.write_text(text)
        return digest

    def env(self, arch: str, curl_fails: bool) -> dict[str, str]:
        assert shutil.which("brew", path=f"{self.bin}:{SYSTEM_PATH}") is None, "brew must not exist for these tests"
        assert shutil.which("llama-server", path=f"{self.bin}:{SYSTEM_PATH}") is None, "llama-server must not exist"
        return {
            "HOME": str(self.home), "PATH": f"{self.bin}:{SYSTEM_PATH}", "LANG": "C.UTF-8", "PYTHONPATH": str(ROOT),
            "SPIKE_NO_KEYRING": "1", "REAL_PYTHON": sys.executable, "FAKE_LOG": str(self.log), "FAKE_ASSET": str(self.asset),
            "FAKE_ARCH": arch, "FAKE_BIN_DIR": str(self.home / ".local" / "bin"), "FAKE_CURL_FAILS": "1" if curl_fails else "",
        }

    def run(self, *args: str, arch: str = "x86_64", curl_fails: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            [shutil.which("bash", path=SYSTEM_PATH), str(self.install), *args], cwd=self.root, env=self.env(arch, curl_fails),
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)

    def run_asking(self, answer, *args: str) -> tuple[int, str]:
        """Runs install.sh with a terminal (it asks on /dev/tty); answer(step title) -> 'y' or 'n' for each question."""
        import fcntl
        import pty
        import termios

        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [shutil.which("bash", path=SYSTEM_PATH), str(self.install), *args], cwd=self.root, env=self.env("x86_64", False),
            stdin=slave, stdout=slave, stderr=slave, start_new_session=True,
            preexec_fn=lambda: fcntl.ioctl(0, termios.TIOCSCTTY, 0))  # a controlling terminal for /dev/tty
        os.close(slave)
        out = ""
        while True:
            try:
                chunk = os.read(master, 4096)
            except OSError:  # the child closed its side
                break
            if not chunk:
                break
            out += chunk.decode(errors="replace")
            if out.endswith("Run it? [y/N] "):
                os.write(master, (answer(out.rsplit("\n== ", 1)[-1]) + "\n").encode())
        os.close(master)
        return proc.wait(timeout=60), out

    def curl_calls(self) -> list[str]:
        return self.log.read_text().split()

    def leftovers(self) -> list[str]:
        base = self.dest.parent
        return sorted(p.name for p in base.iterdir()) if base.exists() else []


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path)


def test_pinned_values_are_a_tag_and_two_sha256():
    text = (ROOT / "scripts" / "install.sh").read_text()
    assert re.fullmatch(r"b\d+", TAG)
    for arch in ("x64", "arm64"):
        assert re.search(rf"^llama_sha_{arch}=[0-9a-f]{{64}}$", text, re.M), arch
    assert "llama-$llama_tag-bin-ubuntu-$arch.tar.gz" in text  # the asset name the pins were taken from


@linux_with_tools
def test_install_sh_has_valid_bash_syntax():
    subprocess.run([shutil.which("bash", path=SYSTEM_PATH), "-n", str(ROOT / "scripts" / "install.sh")], check=True)


@linux_with_tools
def test_linux_without_brew_installs_the_pinned_llama_cpp_and_spike_finds_it(project):
    digest = project.serve(GOOD_SERVER)
    done = project.run("--yes", "--no-model")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"SHA-256 verified: {digest}" in done.stdout
    assert project.curl_calls() == [f"https://github.com/ggml-org/llama.cpp/releases/download/{TAG}/llama-{TAG}-bin-ubuntu-x64.tar.gz"]
    assert project.link.resolve() == (project.dest / "llama-server").resolve()  # SPIKE_HOME/bin, where find_binary looks first
    assert project.leftovers() == [TAG]  # the scratch download folder is gone
    assert "Done." in done.stdout and "llama-server: " + str(project.link) in done.stdout  # spike doctor --strict saw it

    again = project.run("--yes", "--no-model")  # a second run finds it and downloads nothing
    assert again.returncode == 0, again.stdout + again.stderr
    assert f"llama-server: {project.link}" in again.stdout and len(project.curl_calls()) == 1


@linux_with_tools
def test_aarch64_downloads_the_arm64_asset_and_checks_its_own_pin(project):
    project.serve(GOOD_SERVER, pin="arm64")
    done = project.run("--yes", "--no-model", arch="aarch64")
    assert done.returncode == 0, done.stdout + done.stderr
    assert project.curl_calls()[0].endswith(f"/{TAG}/llama-{TAG}-bin-ubuntu-arm64.tar.gz")  # only the arm64 pin was replaced


@linux_with_tools
def test_a_download_with_the_wrong_sha256_installs_nothing(project):
    project.serve(GOOD_SERVER, pin=None)  # the installer still pins the real release's hash
    done = project.run("--yes", "--no-model")
    assert done.returncode == 1
    assert "SHA-256 mismatch, nothing was installed" in done.stdout and "llama.cpp was not installed" in done.stderr
    assert not project.link.exists() and not project.link.is_symlink()
    assert project.leftovers() == []


@linux_with_tools
def test_a_failed_download_stops_the_installer(project):
    project.serve(GOOD_SERVER)
    done = project.run("--yes", "--no-model", curl_fails=True)
    assert done.returncode == 1
    assert "the download failed" in done.stdout and "llama.cpp was not installed" in done.stderr
    assert not project.link.exists() and project.leftovers() == []


@linux_with_tools
def test_a_build_that_cannot_start_is_not_kept_and_the_missing_libraries_are_named(project):
    project.serve(BROKEN_SERVER)
    done = project.run("--yes", "--no-model")
    assert done.returncode == 1
    assert "does not start on this system" in done.stdout and "libgomp.so.1" in done.stdout
    assert "libstdc++6, libgomp1 and libssl3" in done.stdout and "glibc 2.34" in done.stdout
    assert not project.link.exists() and project.leftovers() == []


@linux_with_tools
def test_other_architectures_get_the_instructions_and_no_download(project):
    project.serve(GOOD_SERVER)
    done = project.run("--yes", "--no-model", arch="riscv64")
    assert project.curl_calls() == []
    assert "llama-server was not found" in done.stdout and "conda install -c conda-forge llama.cpp" in done.stdout
    assert done.returncode == 1  # the final `spike doctor --strict` still needs a llama-server


@linux_with_tools
def test_declining_the_download_prints_the_instructions(project):
    project.serve(GOOD_SERVER)
    asked = []

    def answer(title: str) -> str:
        asked.append(title.replace("\r", "").split("\n")[0])
        return "n" if asked[-1].startswith(("Download llama.cpp", "Check the install")) else "y"

    code, out = project.run_asking(answer, "--no-model")
    assert len(asked) == 3 and asked[0] == "Install SPIKE with pipx" and asked[2] == "Check the install", asked
    assert asked[1].startswith(f"Download llama.cpp {TAG} from github.com/ggml-org/llama.cpp"), asked
    assert project.curl_calls() == []
    assert "llama-server was not found" in out and "conda install -c conda-forge llama.cpp" in out
    assert not project.link.exists() and code == 0, out


@linux_with_tools
def test_accepting_the_download_when_asked(project):
    project.serve(GOOD_SERVER)
    code, out = project.run_asking(lambda title: "y", "--no-model")
    assert code == 0, out
    assert len(project.curl_calls()) == 1 and project.link.is_symlink()


def test_install_ps1_is_ascii():
    """Windows PowerShell 5.1 reads a script without a BOM as ANSI, so anything above ASCII would be misread."""
    (ROOT / "scripts" / "install.ps1").read_bytes().decode("ascii")


@pytest.mark.skipif(shutil.which("pwsh") is None, reason="PowerShell 7 (pwsh) is not installed")
def test_install_ps1_uses_nothing_newer_than_windows_powershell_5_1():
    checker = ROOT / "tests" / "fixtures" / "check_ps51.ps1"
    done = subprocess.run(["pwsh", "-NoProfile", "-File", str(checker), "-Path", str(ROOT / "scripts" / "install.ps1")],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
