# Build on each target OS; PyInstaller is supplied by release tooling, never installed by SPIKE.
import importlib.util
import os
import platform
import runpy
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH).parent
system = platform.system()
arch = platform.machine()
if arch.lower() in {"aarch64", "arm64"}:
    arch = "arm64"
elif arch.lower() in {"amd64", "x86_64"}:
    arch = "AMD64" if system == "Windows" else "x86_64"
target = f"{system}-{arch}"
stage = Path(os.environ.get("SPIKE_LLAMA_STAGE", root / "packaging" / "vendor" / target / "b11709"))
runpy.run_path(str(root / "packaging" / "stage_llama.py"))["validate_stage"](stage, target)
web = root / "web" / "dist"
if not (web / "index.html").is_file():
    raise ValueError("Build web/dist before packaging")
data = collect_data_files("spike") + [(str(web), "spike/server/static")]
data += [(str(root / "LICENSE"), "licenses"), (str(root / "THIRD_PARTY.md"), "licenses"),
         (str(root / "packaging" / "licenses"), "licenses/native")]
data += [(str(stage / "LICENSE"), "llama"), (str(stage / "manifest.json"), "llama")]
binaries = [(str(p), "llama") for p in stage.iterdir() if p.name not in {"LICENSE", "manifest.json"}]
hidden = collect_submodules("spike") + collect_submodules("uvicorn")
if importlib.util.find_spec("webview") is not None:
    view_data, view_bins, view_hidden = collect_all("webview")
    data += view_data
    binaries += view_bins
    hidden += view_hidden
a = Analysis([str(root / "packaging" / "entry.py")], pathex=[str(root), str(root / "packaging")], binaries=binaries,
             datas=data, hiddenimports=hidden)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SPIKE", console=True)
collection = COLLECT(exe, a.binaries, a.datas, name="SPIKE")
if system == "Darwin":
    app = BUNDLE(collection, name="SPIKE.app", bundle_identifier="local.spike.app",
                 info_plist={"CFBundleShortVersionString": os.environ.get("SPIKE_VERSION", "0.1.0"),
                             "NSHighResolutionCapable": True})
