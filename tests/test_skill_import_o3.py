"""O3: install a skill from a GitHub URL, with review. A fake local HTTP server stands in for codeload.github.com:
nothing here touches the network. The flow is preview (nothing written) then install (disabled)."""

from __future__ import annotations

import http.server
import os
import re
import threading
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from spike.skills import github_import
from tests.helpers import ScriptedProvider

PREVIEW = "/api/skills/import-github/preview"
INSTALL = "/api/skills/import-github/install"
MIT = ("MIT License\n\nCopyright (c) 2026 Someone\n\nPermission is hereby granted, free of charge, to any person "
       "obtaining a copy of this software and associated documentation files (the \"Software\"), to deal in the "
       "Software without restriction.\n\nTHE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND.\n")
GPL = "GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007\n\nEveryone is permitted to copy and distribute...\n"
SKILL = "---\nname: {name}\ndescription: Summarises meeting notes into action items.\n{extra}---\n# Notes\nDo the thing.\n"


def skill_md(name: str = "meeting-notes", extra: str = "") -> bytes:
    return SKILL.format(name=name, extra=extra).encode()


def make_zip(files: dict[str, bytes], prefix: str = "repo-main/", symlinks: dict[str, str] | None = None) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(prefix + name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(prefix + name)
            info.external_attr = 0o120777 << 16
            z.writestr(info, target)
    return buf.getvalue()


def good_files(**extra: bytes) -> dict[str, bytes]:
    return {"SKILL.md": skill_md(), "LICENSE": MIT.encode(), "notes/template.md": b"# template\n", **extra}


class Fake:
    """Serves {path: bytes} on 127.0.0.1 with an OS-assigned port and records every request path."""

    def __init__(self) -> None:
        self.routes: dict[str, bytes] = {}
        self.redirects: dict[str, str] = {}
        self.requests: list[str] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                outer.requests.append(self.path)
                if self.path in outer.redirects:
                    self.send_response(302)
                    self.send_header("Location", outer.redirects[self.path])
                    self.end_headers()
                    return
                body = outer.routes.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                if not self.path.endswith("/nolength"):
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fake(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    server = Fake()
    monkeypatch.setattr(github_import, "CODELOAD", server.base)
    yield server
    server.close()


def make_client(home: Path, monkeypatch, host: str = "127.0.0.1") -> TestClient:
    monkeypatch.setenv("SPIKE_HOME", str(home))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(home / "workspace"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")

    def factory(cfg):
        provider = ScriptedProvider([], name=cfg.id)
        provider.config = cfg
        return provider

    return TestClient(create_app(AppState(home=home, provider_factory=factory)), base_url="http://127.0.0.1",
                      client=(host, 50000))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    return make_client(tmp_path / "home", monkeypatch)


def tree(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


def serve(fake: Fake, files: dict[str, bytes] | bytes, repo: str = "o/r", ref: str = "HEAD") -> None:
    fake.routes[f"/{repo}/zip/{ref}"] = files if isinstance(files, bytes) else make_zip(files)


def preview(client: TestClient, url: str = "https://github.com/o/r"):
    return client.post(PREVIEW, json={"url": url})


def code(resp) -> str:
    return resp.json()["detail"]


def install(client: TestClient, body: dict):
    return client.post(INSTALL, json={"preview_id": body["preview_id"], "sha256": body["sha256"]})


def test_happy_path_preview_writes_nothing_then_install_is_disabled(client, fake):
    serve(fake, good_files(**{"assets/logo.bin": b"\x00\x01\x02\xff"}))
    home = client.app.state.spike.home
    before = tree(home)
    resp = preview(client)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert tree(home) == before  # nothing written (skills folder, temp folders) before the install request
    assert not (home / "skills" / "meeting-notes").exists()
    assert body["name"] == "meeting-notes" and body["license"]["id"] == "MIT" and body["license"]["can_enable"] is True
    assert "# Notes" in body["skill_md"]
    files = {f["path"]: f for f in body["files"]}
    assert set(files) == {"SKILL.md", "LICENSE", "notes/template.md", "assets/logo.bin"}
    assert files["notes/template.md"]["size"] == 11 and files["notes/template.md"]["text"] == "# template\n"
    assert files["assets/logo.bin"]["binary"] is True and "text" not in files["assets/logo.bin"]
    assert fake.requests == ["/o/r/zip/HEAD"]
    resp = install(client, body)
    assert resp.status_code == 200, resp.text
    installed = home / "skills" / "meeting-notes"
    assert (installed / "assets" / "logo.bin").read_bytes() == b"\x00\x01\x02\xff"
    assert (installed / "SKILL.md").read_bytes() == skill_md()
    assert fake.requests == ["/o/r/zip/HEAD"]  # the install does not download again: it installs what was reviewed
    listed = {s["name"]: s for s in client.get("/api/skills").json()}
    assert listed["meeting-notes"]["enabled"] is False  # disabled until the user enables it
    assert "meeting-notes" in client.get("/api/settings").json()["disabled_skills"]
    assert client.put("/api/skills/meeting-notes", json={"enabled": True}).json()["enabled"] is True


def test_tree_url_selects_the_folder_and_uses_the_repo_license(client, fake):
    serve(fake, {"LICENSE": MIT.encode(), "skills/b/SKILL.md": skill_md("b"), "skills/b/x.md": b"x",
                 "skills/a/SKILL.md": skill_md("a")}, ref="v1")
    resp = preview(client, "https://github.com/o/r/tree/v1/skills/b")
    body = resp.json()
    assert fake.requests == ["/o/r/zip/v1"]
    assert body["name"] == "b" and body["license"]["id"] == "MIT" and body["license"]["source"] == "repo LICENSE"
    assert sorted(f["path"] for f in body["files"]) == ["SKILL.md", "x.md"]
    serve(fake, {"LICENSE": MIT.encode(), "skills/b/SKILL.md": skill_md("b"), "skills/a/SKILL.md": skill_md("a")})
    resp = preview(client, "https://github.com/o/r")  # repo root holds two skills: the user must pick one
    assert resp.status_code == 400 and code(resp) == "multiple_skills"
    resp = preview(client, "https://github.com/o/r/tree/HEAD/skills/zzz")
    assert resp.status_code == 400 and code(resp) == "no_skill"
    serve(fake, {"LICENSE": MIT.encode(), "README.md": b"nothing here"}, repo="o/empty")
    assert code(preview(client, "https://github.com/o/empty")) == "no_skill"


def test_the_folder_name_in_the_repo_does_not_have_to_match_the_skill_name(client, fake):
    serve(fake, {"LICENSE": MIT.encode(), "stuff/SKILL.md": skill_md("renamed")})
    body = preview(client, "https://github.com/o/r/tree/HEAD/stuff").json()
    assert body["name"] == "renamed" and body["can_install"] is True
    assert install(client, body).status_code == 200
    assert (client.app.state.spike.home / "skills" / "renamed" / "SKILL.md").is_file()


@pytest.mark.parametrize("extra,files,expected,enable", [
    ("license: Apache-2.0\n", {}, "Apache-2.0", True),
    ("license: ISC\n", {}, "ISC", True),
    ("license: BSD-3-Clause\n", {}, "BSD-3-Clause", True),
    ("license: BSD-2-Clause\n", {}, "BSD-2-Clause", True),
    ("", {"LICENSE": MIT.encode()}, "MIT", True),
    ("", {"LICENSE.txt": b"Apache License\nVersion 2.0, January 2004\n"}, "Apache-2.0", True),
    ("", {"LICENSE": ("Redistribution and use in source and binary forms, with or without modification, are "
                      "permitted. Neither the name of the copyright holder nor the names of its contributors may be "
                      "used. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS").encode()}, "BSD-3-Clause", True),
    ("", {"LICENSE": ("Redistribution and use in source and binary forms, with or without modification, are "
                      "permitted. THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS").encode()}, "BSD-2-Clause", True),
    ("", {"LICENSE": b"ISC License\nPermission to use, copy, modify, and/or distribute this software for any "
                     b"purpose with or without fee is hereby granted"}, "ISC", True),
    ("license: GPL-3.0\n", {}, "GPL-3.0", False),
    ("", {"LICENSE": GPL.encode()}, "GPL-3.0", False),
    ("license: MIT\n", {"LICENSE": GPL.encode()}, "GPL-3.0", False),  # a contradicting file wins: the stricter reading
    ("license: Proprietary. All rights reserved\n", {}, "Proprietary. All rights reserved", False),
    ("", {"LICENSE": b"Do whatever you like with this."}, "unrecognised", False),
    ("", {}, "", False),
])
def test_license_detection(client, fake, extra, files, expected, enable):
    serve(fake, {"SKILL.md": skill_md(extra=extra), **files})
    body = preview(client).json()
    lic = body["license"]
    assert lic["id"] == expected and lic["can_enable"] is enable
    assert lic["status"] == ("allowed" if enable else ("missing" if not expected else "blocked"))
    assert body["can_install"] is enable
    assert body["skill_md"]  # still visible when blocked
    resp = install(client, body)
    if enable:
        assert resp.status_code == 200
    else:
        assert resp.status_code == 403 and code(resp) == "license_blocked"
        assert not (client.app.state.spike.home / "skills" / "meeting-notes").exists()


@pytest.mark.parametrize("name", ["../evil.md", "a/../../evil.md", "/etc/passwd", "a\\..\\b.md", "C:/x.md"])
def test_unsafe_paths_refuse_the_whole_archive(client, fake, name):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("repo-main/SKILL.md", skill_md())
        z.writestr("repo-main/LICENSE", MIT)
        z.writestr(zipfile.ZipInfo(name), b"x")
    serve(fake, buf.getvalue())
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "unsafe_path"
    assert not list((client.app.state.spike.home / "skills").glob("*"))


def test_symlink_entries_are_refused(client, fake):
    fake.routes["/o/r/zip/HEAD"] = make_zip(good_files(), symlinks={"link": "/etc/passwd"})
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "symlink"


def test_zip_bomb_by_size_and_by_ratio(client, fake):
    serve(fake, good_files(**{"big.txt": b"0" * (50 * 1024**2)}))
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "file_too_large"
    serve(fake, good_files(**{"dense.txt": b"0" * 1_500_000}))  # under the per-file limit, compresses about 1000:1
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "zip_bomb"


def test_limits_on_count_total_and_download(client, fake, monkeypatch):
    many = {f"f{i}.md": b"x" for i in range(github_import.MAX_FILES + 1)}
    serve(fake, good_files(**many))
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "too_many_files"
    chunks = {f"c{i}.bin": os.urandom(github_import.MAX_FILE - 1000) for i in range(6)}
    assert sum(len(v) for v in chunks.values()) > github_import.MAX_TOTAL
    serve(fake, good_files(**chunks))
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "total_too_large"
    monkeypatch.setattr(github_import, "MAX_DOWNLOAD", 2000)
    serve(fake, good_files(**{"r.bin": os.urandom(5000)}))
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "download_too_large"


def test_download_without_content_length_is_cut_at_the_limit(client, fake, monkeypatch):
    monkeypatch.setattr(github_import, "MAX_DOWNLOAD", 500)
    serve(fake, os.urandom(100_000), ref="nolength")
    resp = preview(client, "https://github.com/o/r/tree/nolength")
    assert resp.status_code == 400 and code(resp) == "download_too_large"


def test_not_a_zip_and_missing_repo(client, fake):
    serve(fake, b"<html>not a zip</html>")
    assert code(preview(client)) == "bad_archive"
    resp = preview(client, "https://github.com/o/missing")
    assert resp.status_code == 404 and code(resp) == "not_found"


def test_preview_id_and_hash_tampering_is_refused(client, fake):
    serve(fake, good_files())
    body = preview(client).json()
    home = client.app.state.spike.home
    wrong = body["sha256"][:-1] + ("0" if body["sha256"][-1] != "0" else "1")
    resp = client.post(INSTALL, json={"preview_id": body["preview_id"], "sha256": wrong})
    assert resp.status_code == 400 and code(resp) == "hash_mismatch"
    assert client.post(INSTALL, json={"preview_id": body["preview_id"], "sha256": "zz"}).status_code == 422
    assert not (home / "skills" / "meeting-notes").exists()
    resp = client.post(INSTALL, json={"preview_id": "nope", "sha256": body["sha256"]})
    assert resp.status_code == 404 and code(resp) == "preview_expired"
    # another preview's id with this preview's hash is refused too
    serve(fake, good_files(**{"other.md": b"o"}))
    other = preview(client).json()
    resp = client.post(INSTALL, json={"preview_id": other["preview_id"], "sha256": body["sha256"]})
    assert resp.status_code == 400 and code(resp) == "hash_mismatch"
    # the right hash still works afterwards, once: the preview is single-use
    assert install(client, body).status_code == 200
    assert install(client, body).status_code == 404


def test_the_hash_covers_every_file(client, fake):
    serve(fake, good_files())
    a = preview(client).json()["sha256"]
    serve(fake, good_files(**{"extra.md": b"x"}))
    b = preview(client).json()["sha256"]
    serve(fake, good_files())
    assert a != b and preview(client).json()["sha256"] == a  # same bytes, same digest


@pytest.mark.parametrize("url", [
    "http://github.com/o/r", "https://github.com.evil.example/o/r", "https://evil.example/github.com/o/r",
    "https://user:pw@github.com/o/r", "https://github.com@evil.example/o/r", "https://github.com:444/o/r",
    "https://github.com/o", "https://github.com/", "https://github.com/o/r/blob/main/SKILL.md",
    "https://github.com/o/r?x=1", "https://github.com/o/r#frag", "https://codeload.github.com/o/r/zip/main",
    "https://github.com/o/r/tree/main/../../x", "https://github.com/o/r/tree/main/%2e%2e/x",
    "https://github.com\\@evil.example/o/r", "https://github.com\u2024evil.example/o/r", "file:///etc/passwd",
    "ftp://github.com/o/r", "github.com/o/r", "https://github.com/o/r extra", "https://github.com/o/r/tree/",
    "https://api.github.com/repos/o/r", "https://www.github.com/o/r", "https://github.com/o%2fx/r",
    "https://github.com/o/r\n", "", "https://github.com/../r", "https://github.com/o/..",
    "https://github.com/o/r/tree/main//x",
])
def test_non_github_and_odd_urls_are_refused_before_any_request(client, fake, url):
    resp = preview(client, url)
    assert resp.status_code == 400 and code(resp) == "bad_url", (url, resp.text)
    assert fake.requests == []


def test_accepted_url_forms():
    p, G = github_import.parse_github_url, github_import.GithubRef
    assert p("https://github.com/o/r") == G("o", "r", "HEAD", "")
    assert p("https://github.com/o/r.git") == G("o", "r", "HEAD", "")
    assert p("https://github.com/o/r/") == G("o", "r", "HEAD", "")
    assert p("https://github.com/o/r/tree/v1.2/a/b") == G("o", "r", "v1.2", "a/b")
    assert p("https://github.com/o/r/tree/main") == G("o", "r", "main", "")
    assert p("  https://github.com/o/r  ") == G("o", "r", "HEAD", "")


def test_redirects_stay_on_the_same_host(client, fake):
    serve(fake, good_files(), ref="moved")
    fake.redirects["/o/r/zip/HEAD"] = f"{fake.base}/o/r/zip/moved"
    assert preview(client).status_code == 200
    fake.redirects["/o/r/zip/HEAD"] = "http://127.0.0.2:1/elsewhere"
    resp = preview(client)
    assert resp.status_code == 400 and code(resp) == "redirect"


def test_downloader_uses_the_environment_proxy_settings():
    assert github_import.make_client().trust_env is True


def test_validator_problems_block_the_install(client, fake):
    serve(fake, {"SKILL.md": skill_md(extra="allowed-tools: [rm_rf_everything]\n"), "LICENSE": MIT.encode()})
    body = preview(client).json()
    assert [i["rule"] for i in body["issues"]] == ["tools"] and body["can_install"] is False
    assert str(client.app.state.spike.home) not in str(body["issues"]) and "/tmp" not in str(body["issues"])
    resp = install(client, body)
    assert resp.status_code == 400 and code(resp) == "invalid_skill"
    serve(fake, {"SKILL.md": skill_md(extra="note: password = abcdefghijklmnop1234\n"), "LICENSE": MIT.encode()})
    assert [i["rule"] for i in preview(client).json()["issues"]] == ["secret"]


def test_an_existing_skill_name_is_never_replaced(client, fake):
    serve(fake, {"SKILL.md": skill_md("landing-page"), "LICENSE": MIT.encode()})  # a bundled skill's name
    body = preview(client).json()
    resp = install(client, body)
    assert resp.status_code == 409 and code(resp) == "exists"
    serve(fake, good_files())
    first = preview(client).json()
    assert install(client, first).status_code == 200
    again = preview(client).json()
    assert install(client, again).status_code == 409


def test_requests_from_another_machine_or_site_are_refused(tmp_path, monkeypatch, fake):
    serve(fake, good_files())
    remote = make_client(tmp_path / "h2", monkeypatch, host="10.0.0.5")
    for path, body in ((PREVIEW, {"url": "https://github.com/o/r"}), (INSTALL, {"preview_id": "x", "sha256": "0" * 64})):
        assert remote.post(path, json=body).status_code == 403
    local = make_client(tmp_path / "h3", monkeypatch)
    assert local.post(PREVIEW, json={"url": "https://github.com/o/r"}, headers={"Origin": "https://evil.example"}
                      ).status_code == 403
    assert local.post(PREVIEW, content=b'{"url": "https://github.com/o/r"}',
                      headers={"content-type": "text/plain"}).status_code == 415
    assert fake.requests == []


def test_no_model_tool_can_reach_the_import(client):
    root = Path(github_import.__file__).parents[1]
    importers = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py")
                       if re.search(r"github_import|skill_import_api", p.read_text(encoding="utf-8"))
                       and p.name not in ("github_import.py", "skill_import_api.py"))
    assert importers == ["server/app.py"]  # no tool, connector, orchestrator or provider module touches it
    app_src = (root / "server" / "app.py").read_text(encoding="utf-8")
    assert len(re.findall(r"create_skill_import_router", app_src)) == 2  # one import, one include_router
    from spike.skills.validation import known_tools
    assert not [n for n in known_tools() if "github" in n or "skill" in n and "import" in n]
    assert client.post("/v1/skills/import-github/preview", json={"url": "https://github.com/o/r"}
                       ).status_code in (401, 403, 404, 405, 422)
    listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).text
    assert "import-github" not in listed and "github_import" not in listed
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith(("/v1", "/mcp")) and "import" in p]
