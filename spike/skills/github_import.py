"""Install a skill from a GitHub URL, with review (O3). Only a person pasting a URL and pressing a button gets here:
no model tool calls this module (a test checks that nothing but the server's app module imports it).

The flow has two steps. `download_zip` + `build_preview` fetch the repository's ZIP from GitHub's archive host and
read it in memory, with limits on every size, and nothing touches the skills folder. `install_files` later writes
exactly the bytes that were previewed (the caller compares the preview's SHA-256 first). Nothing in the archive is
executed: no git, no scripts, no extraction to paths taken from the archive.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import yaml

from spike.skills.engine import NAME
from spike.skills.validation import Issue, validate_skills

CODELOAD = "https://codeload.github.com"  # the archive host; tests point this at a fake local server
MAX_DOWNLOAD = 25 * 1024**2  # bytes of the whole repository ZIP
MAX_ENTRIES = 20_000  # entries in the whole archive
MAX_FILES = 200  # files of the skill
MAX_FILE = 2 * 1024**2  # bytes of one file of the skill, uncompressed
MAX_TOTAL = 8 * 1024**2  # bytes of the skill, uncompressed
MAX_RATIO = 250  # uncompressed / compressed above this, on a file over RATIO_FROM bytes, is a zip bomb
RATIO_FROM = 64 * 1024
TEXT_PREVIEW = 64 * 1024  # characters of one text file returned in the preview
TEXT_BUDGET = 1024**2  # characters of text files returned in the preview altogether
DOWNLOAD_SECONDS = 120
LICENSE_FILE = re.compile(r"^(?:license|licence|copying|unlicense)(?:[.\-_][\w.\-]*)?$", re.I)
ALLOWED_LICENSES = ("MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC")
_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_PART = re.compile(r"^[A-Za-z0-9._+=~-]{1,100}$")
_MAX_URL = 500


class ImportFail(Exception):
    """A refusal with a stable code the UI translates; never carries the offending content."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class GithubRef:
    owner: str
    repo: str
    ref: str = "HEAD"
    path: str = ""


def parse_github_url(url: object) -> GithubRef:
    """https://github.com/<owner>/<repo> or .../tree/<ref>/<path>, and nothing else: same host, no credentials, port,
    query, fragment, escapes, dots segments or look-alike hosts. A branch name with a slash is not supported."""
    if not isinstance(url, str):
        raise ImportFail("bad_url")
    url = url.strip(" ")
    if not url or len(url) > _MAX_URL or any(not 33 <= ord(c) <= 126 for c in url) or any(c in url for c in "\\%?#@"):
        raise ImportFail("bad_url")
    prefix = "https://github.com/"
    if not url.startswith(prefix):
        raise ImportFail("bad_url")
    parts = url[len(prefix):].rstrip("/").split("/")
    if len(parts) < 2 or len(parts) == 3 or (len(parts) > 2 and parts[2] != "tree"):
        raise ImportFail("bad_url")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not _OWNER.match(owner) or not _PART.match(repo) or repo in (".", ".."):
        raise ImportFail("bad_url")
    if len(parts) == 2:
        return GithubRef(owner, repo)
    ref, rest = parts[3], parts[4:]
    if any(not _PART.match(p) or p in (".", "..") for p in [ref, *rest]) or ref.startswith("-"):
        raise ImportFail("bad_url")
    return GithubRef(owner, repo, ref, "/".join(rest))


def make_client() -> httpx.AsyncClient:
    """The app's usual outbound client: the environment's proxy settings apply (trust_env), no redirect following."""
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=False, trust_env=True,
                             headers={"User-Agent": "SPIKE"})


async def download_zip(ref: GithubRef) -> bytes:
    async def fetch() -> bytes:
        url = f"{CODELOAD}/{ref.owner}/{ref.repo}/zip/{ref.ref}"
        base = urlsplit(CODELOAD)
        async with make_client() as client:
            for _ in range(4):
                async with client.stream("GET", url) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, resp.headers.get("location", ""))
                        target = urlsplit(url)
                        if (target.scheme, target.netloc) != (base.scheme, base.netloc):
                            raise ImportFail("redirect")  # only ever the archive host, never somewhere else
                        continue
                    if resp.status_code == 404:
                        raise ImportFail("not_found", 404)
                    if resp.status_code != 200:
                        raise ImportFail("download_failed", 502)
                    declared = resp.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_DOWNLOAD:
                        raise ImportFail("download_too_large")
                    chunks, size = [], 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOWNLOAD:
                            raise ImportFail("download_too_large")
                        chunks.append(chunk)
                    return b"".join(chunks)
        raise ImportFail("redirect")

    try:
        return await asyncio.wait_for(fetch(), DOWNLOAD_SECONDS)
    except (httpx.HTTPError, TimeoutError, OSError):
        raise ImportFail("network", 502) from None


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def license_from_text(text: str) -> str:
    """An SPDX id from the text of a LICENSE file, or "unrecognised". Plain text matching on the standard wording."""
    t = _normalise(text)
    if "gnu affero general public license" in t:
        return "AGPL-3.0"
    if "gnu lesser general public license" in t:
        return "LGPL-3.0" if "version 3" in t else "LGPL-2.1"
    if "gnu general public license" in t:
        return "GPL-3.0" if "version 3" in t else "GPL-2.0"
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "permission to use, copy, modify, and/or distribute this software for any purpose with or without fee" in t:
        return "ISC"
    if "permission is hereby granted, free of charge" in t:
        return "MIT"
    if "redistribution and use in source and binary forms" in t and "advertising materials" not in t:
        if "neither the name" in t:
            return "BSD-3-Clause"
        if "this software is provided by" in t:
            return "BSD-2-Clause"
    return "unrecognised"


def license_from_front(value: object) -> str:
    """The license named in the SKILL.md front matter ("" when absent or only pointing at a file)."""
    text = "" if value is None else str(value).strip()
    if not text or text.lower().startswith("complete terms in"):
        return ""
    known = {"mit": "MIT", "apache-2.0": "Apache-2.0", "bsd-2-clause": "BSD-2-Clause",
             "bsd-3-clause": "BSD-3-Clause", "isc": "ISC"}
    return known.get(text.lower(), text[:80])


def pick_license(front: object, skill_files: dict[str, bytes], repo_files: dict[str, bytes]) -> dict:
    """The license and whether it may be enabled. The skill's own declarations are read first (front matter, LICENSE
    files in its folder); the repository's LICENSE only when the skill has none. If they disagree, a license that is
    not allowed wins: the stricter reading."""
    found: list[tuple[str, str]] = []
    if front_id := license_from_front(front):
        found.append((front_id, "frontmatter"))
    found += [(license_from_text(data.decode("utf-8", "replace")), name) for name, data in sorted(skill_files.items())]
    if not found:
        found = [(license_from_text(data.decode("utf-8", "replace")), f"repo {name}")
                 for name, data in sorted(repo_files.items())]
    blocked = next(((i, s) for i, s in found if i not in ALLOWED_LICENSES), None)
    chosen = blocked or (found[0] if found else ("", ""))
    status = "missing" if not found else ("blocked" if blocked else "allowed")
    return {"id": chosen[0], "source": chosen[1], "status": status, "can_enable": status == "allowed"}


def _is_binary(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return True
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def digest(files: dict[str, bytes]) -> str:
    """One SHA-256 over every path and every file's content, in path order: what was reviewed is what is installed."""
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(f"{path}\0{len(files[path])}\0".encode())
        h.update(hashlib.sha256(files[path]).digest())
    return h.hexdigest()


@dataclass
class Preview:
    source: GithubRef
    name: str
    description: str
    license: dict
    issues: list[Issue]
    files: dict[str, bytes] = field(repr=False)
    sha256: str = ""

    @property
    def can_install(self) -> bool:
        return bool(self.name) and not self.issues and self.license["can_enable"]

    def public(self) -> dict:
        listing, budget = [], TEXT_BUDGET
        for path in sorted(self.files, key=lambda p: (p != "SKILL.md", p)):
            data = self.files[path]
            row: dict = {"path": path, "size": len(data), "binary": _is_binary(data)}
            if not row["binary"]:
                text = data.decode("utf-8")
                if len(text) <= min(TEXT_PREVIEW, budget):
                    row["text"] = text
                    budget -= len(text)
                else:
                    row["truncated"] = True
                    if budget > 0:
                        row["text"] = text[:min(TEXT_PREVIEW, budget)]
                        budget -= len(row["text"])
            listing.append(row)
        skill_md = self.files.get("SKILL.md", b"").decode("utf-8", "replace")
        return {"name": self.name, "description": self.description, "license": self.license, "sha256": self.sha256,
                "issues": [{"rule": i.rule, "location": i.location} for i in self.issues],
                "can_install": self.can_install, "skill_md": skill_md[:200_000], "files": listing,
                "total_bytes": sum(len(d) for d in self.files.values()),
                "source": {"owner": self.source.owner, "repo": self.source.repo, "ref": self.source.ref,
                           "path": self.source.path}}


def _safe_parts(name: str) -> list[str]:
    if (not name or "\\" in name or "\x00" in name or ":" in name or name.startswith("/")
            or any(p in ("..", ".") for p in name.split("/"))):
        raise ImportFail("unsafe_path")
    parts = name.split("/")
    if parts[-1] == "":
        parts.pop()  # a directory entry
    if any(p == "" for p in parts):
        raise ImportFail("unsafe_path")
    return parts


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    """At most `limit` bytes of an entry, counted as they are decompressed (a header can lie about its size)."""
    try:
        with archive.open(info) as stream:
            data = stream.read(limit + 1)
    except (zipfile.BadZipFile, zlib_error, RuntimeError, NotImplementedError, OSError, EOFError):
        raise ImportFail("bad_archive") from None
    if len(data) > limit:
        raise ImportFail("file_too_large")
    return data


try:  # zlib errors from corrupt deflate streams
    from zlib import error as zlib_error
except ImportError:  # pragma: no cover
    zlib_error = ValueError


def build_preview(blob: bytes, source: GithubRef) -> Preview:
    try:
        archive = zipfile.ZipFile(BytesIO(blob))
    except (zipfile.BadZipFile, OSError):
        raise ImportFail("bad_archive") from None
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ImportFail("too_many_files")
        entries: dict[str, zipfile.ZipInfo] = {}  # path below the archive's single top folder -> entry
        tops = set()
        for info in infos:
            parts = _safe_parts(info.filename)
            if not parts:
                continue
            tops.add(parts[0])
            if len(parts) > 1 and not info.is_dir():
                rel = "/".join(parts[1:])
                if rel in entries:
                    raise ImportFail("bad_archive")
                entries[rel] = info
        if len(tops) != 1:
            raise ImportFail("bad_archive")
        root = _find_root(entries, source)
        prefix = f"{root}/" if root else ""
        chosen = {p[len(prefix):]: i for p, i in entries.items() if p.startswith(prefix)}
        if len({p.lower() for p in chosen}) != len(chosen):
            raise ImportFail("bad_archive")
        if len(chosen) > MAX_FILES:
            raise ImportFail("too_many_files")
        total = 0
        for info in chosen.values():
            if info.flag_bits & 0x1:
                raise ImportFail("bad_archive")  # encrypted
            if stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG):
                raise ImportFail("symlink")  # symbolic links and other special entries are never unpacked
            if info.file_size > MAX_FILE:
                raise ImportFail("file_too_large")
            if info.file_size > RATIO_FROM and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise ImportFail("zip_bomb")
            total += info.file_size
        if total > MAX_TOTAL:
            raise ImportFail("total_too_large")
        files, total = {}, 0
        for path, info in chosen.items():
            files[path] = _read(archive, info, MAX_FILE)
            total += len(files[path])
            if total > MAX_TOTAL:
                raise ImportFail("total_too_large")
        if "SKILL.md" not in files:
            raise ImportFail("no_skill")
        repo_files = {}
        for rel, info in entries.items():
            if "/" not in rel and LICENSE_FILE.match(rel) and root and info.file_size <= 200_000:
                repo_files[rel] = _read(archive, info, 200_000)
        if not root:
            repo_files = {}
    return _review(source, files, repo_files)


def _find_root(entries: dict[str, zipfile.ZipInfo], source: GithubRef) -> str:
    """The folder that holds the skill: the URL's path, else the repository root, else the only folder with SKILL.md."""
    if source.path:
        if f"{source.path}/SKILL.md" not in entries:
            raise ImportFail("no_skill")
        return source.path
    if "SKILL.md" in entries:
        return ""
    found = sorted(p[:-len("/SKILL.md")] for p in entries if p.endswith("/SKILL.md") and p.count("/") <= 3)
    if not found:
        raise ImportFail("no_skill")
    if len(found) > 1:
        raise ImportFail("multiple_skills")
    return found[0]


def _review(source: GithubRef, files: dict[str, bytes], repo_files: dict[str, bytes]) -> Preview:
    text = files["SKILL.md"].decode("utf-8", "replace")
    front: dict = {}
    parts = text.split("---", 2)
    if text.startswith("---") and len(parts) == 3:
        try:
            loaded = yaml.safe_load(parts[1])
            front = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:
            front = {}
    name = front.get("name") if isinstance(front.get("name"), str) else ""
    issues: list[Issue] = []
    if not NAME.match(name) or len(name) > 64:
        name = ""
        issues.append(Issue("format", "SKILL.md"))
    else:
        with tempfile.TemporaryDirectory(prefix="spike-skill-") as temp:
            staged = Path(temp) / name
            for path, data in files.items():
                (staged / path).parent.mkdir(parents=True, exist_ok=True)
                (staged / path).write_bytes(data)
            base = (Path(temp) / name).as_posix()
            for issue in validate_skills([staged]):
                if issue.rule == "license":
                    continue  # the importer decides licenses itself, with a stricter allow-list
                issues.append(Issue(issue.rule, issue.location.removeprefix(base).lstrip("/") or "SKILL.md"))
    skill_licenses = {p: d for p, d in files.items() if "/" not in p and LICENSE_FILE.match(p)}
    return Preview(source=source, name=name, description=str(front.get("description") or "").strip()[:1024],
                   license=pick_license(front.get("license"), skill_licenses, repo_files), issues=issues,
                   files=files, sha256=digest(files))


def install_files(preview: Preview, skills_dir: Path) -> Path:
    """Write the previewed bytes as <skills_dir>/<name>. The folder is staged beside the skills folder and moved in
    with one rename, so a failure leaves nothing half-installed. Never replaces an existing skill."""
    final = skills_dir / preview.name
    if final.exists() or final.is_symlink():
        raise ImportFail("exists", 409)
    skills_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".import-", dir=skills_dir.parent))
    try:
        staged = stage / preview.name
        for path, data in preview.files.items():
            target = staged / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        os.rename(staged, final)
    except OSError:
        raise ImportFail("write_failed", 500) from None
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return final
