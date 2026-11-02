"""Notices of the npm packages in the web UI that llama.cpp's `llama-server` embeds (`tools/ui` at the staged tag).

`llama-server` serves a SvelteKit app compiled into the binary; SPIKE never opens it, but its bytes ship with SPIKE's
bundle, and the MIT, ISC, BSD and Apache licenses of the packages it contains ask for their notices. Upstream does not
list them, so this script derives them from the tag's own files, reading only (nothing from the package tree runs):

* roots: the packages that `tools/ui/src` imports at run time (type-only imports, `.d.ts`, tests and stories are left
  out), plus the client runtimes the build adds (svelte, @sveltejs/kit, katex fonts, workbox for the service worker);
* closure: each root's production `dependencies`, resolved like Node does (nested `node_modules` first), except for
  CSS build plugins, of which only the generated CSS ships;
* texts: each package's own LICENSE / LICENCE / COPYING / NOTICE files; identical texts are written once.

This is a static superset of what Vite bundles (tree-shaking drops more), never a subset. Run it on a checkout of
the tag after `npm ci --ignore-scripts` in `tools/ui`:

    python packaging/llama_ui_notices.py <llama.cpp>/tools/ui packaging/licenses/llama-ui-npm.txt --tag b11709 --commit <sha>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

NAME = re.compile(r"^(@[a-z0-9][\w.~-]*/)?[a-z0-9][\w.~-]*$")
IMPORT = re.compile(r"""^\s*import\s+(type\s+)?(?:[\w*{}\s,$]+\s+from\s+)?['"]([^'"]+)['"]"""
                    r"""|\bimport\(\s*['"]([^'"]+)['"]\s*\)|@import\s+['"]([^'"]+)['"]|@plugin\s+['"]([^'"]+)['"]""", re.M)
LICENSE_FILE = re.compile(r"^(licen[cs]e|copying|notice)", re.I)
SOURCES = {".ts", ".js", ".svelte", ".css", ".svx"}
BUILD_RUNTIME = ("svelte", "@sveltejs/kit", "katex")  # code or assets the build itself puts in the output
CSS_ONLY = {"tailwindcss", "@tailwindcss/forms", "@tailwindcss/typography", "tw-animate-css"}
WORKBOX_BUILD_ONLY = {"workbox-build", "workbox-cli"}
MIT = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE."""


def package_of(spec: str) -> str | None:
    if spec.startswith((".", "/", "$", "virtual:", "node:", "~")):
        return None
    parts = spec.split("/")
    name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return name if NAME.match(name) else None


def runtime_roots(ui: Path) -> dict[str, list[str]]:
    roots: dict[str, set[str]] = {}
    for path in sorted((ui / "src").rglob("*")):
        name = path.name
        if (path.suffix not in SOURCES or name.endswith(".d.ts") or "/vendors/" in path.as_posix()
                or any(part in name for part in (".test.", ".spec.", ".stories."))):
            continue
        for match in IMPORT.finditer(path.read_text(encoding="utf-8", errors="replace")):
            if match.group(1):  # `import type`: erased by the compiler
                continue
            package = package_of(next(group for group in match.groups()[1:] if group))
            if package:
                roots.setdefault(package, set()).add(path.relative_to(ui).as_posix())
    modules = ui / "node_modules"
    for package in (*BUILD_RUNTIME, *sorted(p.name for p in modules.glob("workbox-*") if p.name not in WORKBOX_BUILD_ONLY)):
        roots.setdefault(package, set()).add("(added by the build)")
    return {name: sorted(files) for name, files in sorted(roots.items())}


def closure(ui: Path, roots) -> list[dict]:
    modules = ui / "node_modules"
    seen: dict[str, dict] = {}
    stack = [(name, modules) for name in sorted(roots, reverse=True)]
    while stack:
        name, base = stack.pop()
        where = base / name if (base / name / "package.json").is_file() else modules / name
        manifest = where / "package.json"
        if not manifest.is_file():
            raise ValueError(f"{name} is not installed under {modules}; run `npm ci --ignore-scripts` first")
        key = where.resolve().as_posix()
        if key in seen:
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        seen[key] = {"name": data["name"], "version": str(data.get("version", "")), "license": data.get("license"),
                     "author": data.get("author"), "dir": where}
        if data["name"] in CSS_ONLY:
            continue
        nested = where / "node_modules"
        for dep in sorted(data.get("dependencies") or {}, reverse=True):
            stack.append((dep, nested if (nested / dep / "package.json").is_file() else modules))
    return sorted(seen.values(), key=lambda p: (p["name"], p["version"]))


def author_name(author) -> str:
    if isinstance(author, dict):
        return author.get("name", "")
    return re.sub(r"\s*[<(].*$", "", author or "").strip()


def render(ui: Path, *, tag: str, commit: str) -> str:
    roots = runtime_roots(ui)
    packages = closure(ui, roots)
    texts: dict[str, dict] = {}
    bare: list[str] = []
    vendored = [{"name": f"vendored in tools/ui/src/lib/vendors: {d.name}", "version": "", "license": None, "author": None,
                 "dir": d} for d in sorted((ui / "src/lib/vendors").glob("*")) if d.is_dir()]
    for package in packages + vendored:
        label = f"{package['name']}@{package['version']}" if package["version"] else package["name"]
        files = sorted(f for f in package["dir"].iterdir() if f.is_file() and LICENSE_FILE.match(f.name))
        if not files:
            holder = author_name(package["author"]) or "its authors"
            if package["license"] != "MIT":
                raise ValueError(f"{label} has no license file and is not MIT; read its terms before shipping it")
            bare.append(f"{label}: MIT, no license file in the package; Copyright (c) {holder}")
            continue
        for path in files:
            text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
            entry = texts.setdefault(hashlib.sha256(text.encode()).hexdigest(), {"text": text, "who": []})
            if label not in entry["who"]:
                entry["who"].append(label)
    licenses = sorted({p["license"] for p in packages if isinstance(p["license"], str)})
    undeclared = sorted({p["name"] for p in packages if not isinstance(p["license"], str)})
    out = [f"npm packages in the web UI that llama-server embeds (llama.cpp tag {tag}, commit {commit}, tools/ui)",
           "",
           "Generated by packaging/llama_ui_notices.py from the tag's tools/ui/src and package-lock.json (installed with",
           "`npm ci --ignore-scripts`; nothing was built or run). The list is a static superset of what the bundle",
           "contains: run-time imports of the UI's source plus their production dependencies. SPIKE does not use this UI.",
           "",
           f"{len(packages)} packages and {len(vendored)} vendored libraries; declared licenses: {', '.join(licenses)}"
           + (f"; no license field (their own license file below applies): {', '.join(undeclared)}." if undeclared else "."),
           "Where a package offers a choice (dompurify: MPL-2.0 OR Apache-2.0), SPIKE takes the permissive one.",
           "",
           "Packages imported by the UI's source or added by the build: " + ", ".join(roots),
           ""]
    for entry in sorted(texts.values(), key=lambda e: e["who"][0]):
        out += ["=" * 79, "Packages: " + ", ".join(entry["who"]), "=" * 79, "", entry["text"], ""]
    if bare:
        out += ["=" * 79, "MIT packages without a license file of their own: the MIT License, with these copyright lines",
                "=" * 79, "", *bare, "", MIT, ""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ui", type=Path, help="tools/ui of a llama.cpp checkout, after npm ci --ignore-scripts")
    parser.add_argument("out", type=Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    args.out.write_text(render(args.ui, tag=args.tag, commit=args.commit), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
