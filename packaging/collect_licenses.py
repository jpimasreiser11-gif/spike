"""License texts of what a desktop build bundles, gathered from the build environment itself (L2, offline).

The BSD, MIT, Apache and OFL licenses of the Python packages and of the web app's npm packages require their copyright
notice and license text to travel with a binary copy. PyInstaller copies the code, not those files, so `spike.spec` calls
`collect()` and adds the folder to the bundle as `licenses/third-party/`. What it writes comes from the installed
metadata (`*.dist-info`, `node_modules/*/LICENSE*`), so it describes exactly the build that is packaged; an INDEX.md
lists every package with the license it declares and the ones that ship no license file. The Python side starts from
`pyproject.toml` (the dependencies and the extras the release installs), never from how SPIKE itself was installed.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import sys
import sysconfig
import tomllib
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

EXTRAS = ("docs", "data", "finance", "motion")  # what the native-installer workflow installs next to SPIKE
OPTIONAL = ("pywebview",)  # installed on macOS and Windows only; bundled when present
LICENSE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|unlicense)([-_. ].*)?$")


def safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._@+-]+", "_", name)


def python_closure(pyproject: Path, extras: tuple[str, ...] = EXTRAS, optional: tuple[str, ...] = OPTIONAL
                   ) -> dict[str, metadata.Distribution]:
    """The installed distributions SPIKE needs at run time with `extras`, plus the `optional` ones that are installed.

    Raises ValueError when something `pyproject.toml` requires is not installed: a bundle built that way would ship
    code whose license text this folder cannot hold."""
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    wanted = list(project["dependencies"])
    for extra in extras:
        wanted += project["optional-dependencies"][extra]
    roots = [Requirement(r) for r in wanted]
    stack = [r for r in roots if r.marker is None or r.marker.evaluate()] + [Requirement(r) for r in optional]
    absent = [r.name for r in stack if r.name not in optional and not _installed(r.name)]
    if absent:
        raise ValueError(f"not installed here: {', '.join(sorted(set(absent)))}; install SPIKE with "
                         f"'.[{','.join(extras)}]' before packaging so the license texts of what it needs can be collected")
    seen: set[tuple[str, frozenset[str]]] = set()
    found: dict[str, metadata.Distribution] = {}
    while stack:
        req = stack.pop()
        key = (canonicalize_name(req.name), frozenset(req.extras))
        if key in seen:
            continue
        seen.add(key)
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            continue  # a marker-guarded or optional requirement of another package that this platform does not install
        found[canonicalize_name(dist.metadata["Name"])] = dist
        for line in dist.requires or []:
            sub = Requirement(line)
            if sub.marker is None or any(sub.marker.evaluate({"extra": e}) for e in (req.extras or {""})):
                stack.append(sub)
    return found


def _installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def declared_license(dist: metadata.Distribution) -> str:
    md = dist.metadata
    value = (md.get("License-Expression") or md.get("License") or "").strip()
    if not value or "\n" in value or len(value) > 80:
        classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
        value = "; ".join(classifiers) or "not declared"
    return value


def python_licenses(dest: Path, dists: dict[str, metadata.Distribution]) -> list[dict[str, str]]:
    """Copy each distribution's license files (what its build backend put in `*.dist-info`, also under `licenses/`)."""
    rows = []
    for _, dist in sorted(dists.items()):
        wanted = [f for f in dist.files or [] if len(f.parts) > 1 and f.parts[0].endswith((".dist-info", ".egg-info"))
                  and LICENSE_FILE.match(f.name)]
        folder = dest / "python" / safe(f"{dist.metadata['Name']}-{dist.version}")
        copied = []
        for f in wanted:
            source = Path(str(dist.locate_file(f)))
            if source.is_file():
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, folder / safe("__".join(f.parts[1:])))  # keeps licenses/LICENSE apart from LICENSE
                copied.append("/".join(f.parts[1:]))
        rows.append({"name": dist.metadata["Name"], "version": dist.version, "license": declared_license(dist),
                     "files": ", ".join(copied) or "none shipped by the package"})
    return rows


def python_runtime_license(dest: Path) -> dict[str, str]:
    """CPython's own license text: the frozen app carries the interpreter and the standard library (PSF-2.0)."""
    stdlib = Path(sysconfig.get_path("stdlib"))
    row = {"name": "CPython (interpreter and standard library)", "version": platform.python_version(),
           "license": "PSF-2.0", "files": "not found in this Python; text at https://docs.python.org/3/license.html"}
    for candidate in (stdlib / "LICENSE.txt", stdlib.parent / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE.txt"):
        if candidate.is_file():
            folder = dest / "python" / safe(f"CPython-{row['version']}")
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(candidate, folder / "LICENSE.txt")
            row["files"] = "LICENSE.txt"
            break
    return row


def npm_licenses(web: Path, dest: Path) -> list[dict[str, str]]:
    """The production packages of `web/package-lock.json` (what Vite can bundle), with their license files."""
    lock = json.loads((web / "package-lock.json").read_text(encoding="utf-8"))
    rows = []
    for path, meta in sorted(lock["packages"].items()):
        if not path or meta.get("dev") or meta.get("devOptional"):
            continue
        folder = web / path
        manifest = folder / "package.json"
        if not manifest.is_file():
            raise ValueError(f"{path} is in package-lock.json but not installed: run `npm ci` in web/ first")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        license_ = data.get("license") or meta.get("license") or "not declared"
        if isinstance(license_, dict):
            license_ = license_.get("type", "not declared")
        target = dest / "web" / safe(f"{data['name']}-{data['version']}")
        copied = []
        for f in sorted(folder.iterdir()):
            if f.is_file() and LICENSE_FILE.match(f.name):
                target.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(f, target / safe(f.name))
                copied.append(f.name)
        rows.append({"name": data["name"], "version": data["version"], "license": str(license_),
                     "files": ", ".join(copied) or "none shipped by the package"})
    return rows


def collect(dest: Path, pyproject: Path, web: Path | None = None,
            dists: dict[str, metadata.Distribution] | None = None) -> Path:
    """Write the license texts and INDEX.md into a new folder `dest`; returns it."""
    dists = python_closure(pyproject) if dists is None else dists  # may raise: nothing is deleted or written then
    if dest.exists():
        shutil.rmtree(dest)  # a build folder from an earlier run must not leave stale licenses behind
    dest.mkdir(parents=True)
    py = [python_runtime_license(dest)] + python_licenses(dest, dists)
    npm = npm_licenses(web, dest) if web is not None else []
    lines = ["# Third-party license texts in this build", "",
             "Generated from the packages installed where SPIKE was built. SPIKE's own license is `licenses/LICENSE`;",
             "the components that are not Python or npm packages are in `licenses/THIRD_PARTY.md` and `licenses/native/`.",
             "The npm list is the whole production closure of `web/package-lock.json`, a superset of what Vite bundles.",
             ""]
    for title, rows in (("Python packages", py), ("Web app packages (npm)", npm)):
        lines += [f"## {title} ({len(rows)})", "", "| Package | Version | License declared | License files |", "|---|---|---|---|"]
        lines += [f"| {r['name']} | {r['version']} | {r['license']} | {r['files']} |" for r in rows]
        lines.append("")
    (dest / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
    return dest
