"""G34 backup and restore: a ZIP of the user's data without secrets, a verified manifest, a preview, and a restore that
overwrites only when asked. Hostile archives are refused."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike import backup
from spike.backup import BackupError
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider

KEY = "sk-g34-provider-probe-1d2c3b"
CONN = "g34-connector-probe-9e8f7a"
ZIP = {"content-type": "application/zip"}


def make_app(home: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SPIKE_HOME", str(home))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(home / "workspace"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")

    def factory(cfg):
        provider = ScriptedProvider([], name=cfg.id)
        provider.config = cfg
        return provider

    return TestClient(create_app(AppState(home=home, provider_factory=factory)), base_url="http://127.0.0.1",
                      client=("127.0.0.1", 50000))


def fill(client: TestClient) -> dict:
    st = client.app.state.spike
    conv = st.store.create_conversation("Backup me")
    st.store.add_message(conv["id"], "user", "hello history")
    project = client.post("/api/projects", json={"name": "Proj G34"}).json()
    client.post("/api/memory", json={"text": "remember the g34 fact"})
    (st.home / "skills" / "mine").mkdir(parents=True)
    (st.home / "skills" / "mine" / "SKILL.md").write_text("---\nname: mine\ndescription: x\n---\nbody\n", encoding="utf-8")
    (st.home / "projects" / project["id"]).mkdir(parents=True, exist_ok=True)
    (st.home / "projects" / project["id"] / "notes.txt").write_text("project file", encoding="utf-8")
    assert client.post("/api/providers", json={"preset": "deepseek", "api_key": KEY, "model": "deepseek-chat"}
                       ).status_code == 200
    listed = client.get("/api/connectors").json()
    connectors = listed if isinstance(listed, list) else listed.get("connectors", [])
    c = next(c for c in connectors if c.get("secrets"))
    assert client.put(f"/api/connectors/{c['id']}", json={"secrets": {c["secrets"][0]["name"]: CONN}}).status_code == 200
    (st.home / "models").mkdir(exist_ok=True)
    (st.home / "models" / "big.gguf").write_bytes(b"MODEL" * 100)
    return {"conv": conv["id"], "project": project["id"]}


def zip_entries(blob: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return {n: z.read(n) for n in z.namelist()}


def build(entries: dict[str, bytes], *, version: int = 1, extra_manifest: list | None = None,
          sha_override: dict[str, str] | None = None, raw_names: dict[str, str] | None = None,
          unlisted: dict[str, bytes] | None = None) -> bytes:
    files = [{"path": p, "size": len(d), "sha256": (sha_override or {}).get(p) or hashlib.sha256(d).hexdigest()}
             for p, d in entries.items()]
    files += extra_manifest or []
    manifest = {"format": "spike-backup", "version": version, "spike_version": "0", "created": 0,
                "include_models": False, "files": files}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        for p, d in entries.items():
            z.writestr((raw_names or {}).get(p, f"files/{p}"), d)
        for p, d in (unlisted or {}).items():
            z.writestr(f"files/{p}", d)
    return buf.getvalue()


def test_export_has_manifest_hashes_and_never_a_secret(tmp_path, monkeypatch):
    client = make_app(tmp_path / "home", monkeypatch)
    fill(client)
    res = client.get("/api/backup/export")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    entries = zip_entries(res.content)
    manifest = json.loads(entries["manifest.json"])
    assert manifest["format"] == "spike-backup" and manifest["version"] == 1 and manifest["spike_version"]
    paths = {f["path"] for f in manifest["files"]}
    assert {"spike.db", "memory.db"} <= paths
    assert any(p.startswith("skills/mine/") for p in paths) and any(p.startswith("projects/") for p in paths)
    assert not any(p.startswith(("models/", "adapters/")) for p in paths)  # large downloads are opt-in
    for f in manifest["files"]:
        assert hashlib.sha256(entries[f"files/{f['path']}"]).hexdigest() == f["sha256"]
    assert not any("secrets" in p for p in paths)
    for name, data in entries.items():
        assert KEY.encode() not in data and CONN.encode() not in data, name
    # the keys were really stored, so the absence is meaningful
    stored = (tmp_path / "home" / "secrets.json").read_text(encoding="utf-8")
    assert KEY in stored and CONN in stored


def test_models_only_when_asked(tmp_path, monkeypatch):
    client = make_app(tmp_path / "home", monkeypatch)
    fill(client)
    assert "files/models/big.gguf" not in zip_entries(client.get("/api/backup/export").content)
    assert "files/models/big.gguf" in zip_entries(client.get("/api/backup/export?include_models=1").content)


def test_export_leaves_out_links_secret_looking_files_and_unrestorable_names(tmp_path):
    (tmp_path / "projects" / "p").mkdir(parents=True)
    (tmp_path / "projects" / "p" / "ok.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "projects" / "p" / ".env").write_text("TOKEN=x", encoding="utf-8")
    (tmp_path / "projects" / "p" / "server.key").write_text("k", encoding="utf-8")
    if os.name != "nt":  # on Windows "odd:name" writes a stream of a file called "odd"
        (tmp_path / "projects" / "p" / "odd:name").write_text("x", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    with contextlib.suppress(OSError):  # Windows without the symlink privilege
        (tmp_path / "projects" / "p" / "link").symlink_to(tmp_path / "outside.txt")
    (tmp_path / "secrets.json").write_text("{}", encoding="utf-8")
    out = io.BytesIO()
    paths = {f["path"] for f in backup.create_backup(tmp_path, out)["files"]}
    assert paths == {"projects/p/ok.txt"}
    assert backup.inspect_backup(out.getvalue(), tmp_path / "elsewhere")["add"] == 1


def test_open_database_is_copied_consistently(tmp_path):
    """A row committed while the connection stays open (it sits in the -wal file) is in the backup: a raw copy of
    spike.db would miss it."""
    from spike.store.db import Store

    store = Store(tmp_path / "spike.db")
    conv = store.create_conversation("in the wal")
    assert (tmp_path / "spike.db-wal").exists()
    out = io.BytesIO()
    backup.create_backup(tmp_path, out)
    copy = tmp_path / "copy.db"
    copy.write_bytes(zip_entries(out.getvalue())["files/spike.db"])
    rows = sqlite3.connect(copy).execute("SELECT id FROM conversations").fetchall()
    assert (conv["id"],) in rows


def test_preview_then_restore_never_overwrites_unasked(tmp_path, monkeypatch):
    src = make_app(tmp_path / "a", monkeypatch)
    ids = fill(src)
    blob = src.get("/api/backup/export").content
    dst = make_app(tmp_path / "b", monkeypatch)
    (tmp_path / "b" / "skills" / "mine").mkdir(parents=True)
    own = tmp_path / "b" / "skills" / "mine" / "SKILL.md"
    own.write_text("LOCAL EDIT", encoding="utf-8")
    prev = dst.post("/api/backup/preview", content=blob, headers=ZIP).json()
    by = {f["path"]: f["action"] for f in prev["files"]}
    assert by["skills/mine/SKILL.md"] == "replace" and prev["replace"] >= 1 and prev["add"] >= 1
    assert own.read_text(encoding="utf-8") == "LOCAL EDIT"  # a preview changes nothing
    res = dst.post("/api/backup/restore", content=blob, headers=ZIP).json()
    assert res["skipped"] >= 1 and own.read_text(encoding="utf-8") == "LOCAL EDIT"  # no overwrite without confirmation
    notes = tmp_path / "b" / "projects" / ids["project"] / "notes.txt"
    assert notes.read_text(encoding="utf-8") == "project file"
    res = dst.post("/api/backup/restore?overwrite=1", content=blob, headers=ZIP).json()
    assert "LOCAL EDIT" not in own.read_text(encoding="utf-8") and res["replaced"] >= 1
    st = dst.app.state.spike  # the app runs on the restored data
    assert any(c["id"] == ids["conv"] for c in st.store.list_conversations())
    assert any("g34 fact" in m["text"] for m in dst.get("/api/memory").json())
    assert not (tmp_path / "b" / "secrets.json").exists() or KEY not in (tmp_path / "b" / "secrets.json").read_text()


def test_routes_refuse_other_sites_and_wrong_types(tmp_path, monkeypatch):
    client = make_app(tmp_path / "home", monkeypatch)
    blob = client.get("/api/backup/export").content
    evil = {"origin": "http://evil.example"}
    assert client.post("/api/backup/preview", content=blob, headers=ZIP | evil).status_code == 403
    assert client.post("/api/backup/restore", content=blob, headers=ZIP | evil).status_code == 403
    assert client.get("/api/backup/export", headers=evil).status_code == 403
    assert client.post("/api/backup/restore", content=blob, headers={"content-type": "text/plain"}).status_code == 415


HOSTILE = {
    "dotdot": ({"../evil.txt": b"x"}, {"../evil.txt": "files/../evil.txt"}),
    "absolute": ({"/etc/evil": b"x"}, {"/etc/evil": "files//etc/evil"}),
    "backslash": ({"projects\\..\\evil": b"x"}, None),
    "secret_file": ({"secrets.json": b"{}"}, None),
    "unknown_root": ({"random/thing": b"x"}, None),
}


@pytest.mark.parametrize("case", list(HOSTILE))
def test_hostile_paths_are_refused(tmp_path, case):
    entries, raw = HOSTILE[case]
    home = tmp_path / "home"
    home.mkdir()
    with pytest.raises(BackupError):
        backup.inspect_backup(build(entries, raw_names=raw), home)
    with pytest.raises(BackupError):
        backup.restore_backup(build(entries, raw_names=raw), home, overwrite=True)
    assert not (tmp_path / "evil.txt").exists() and not (home / "secrets.json").exists()


def test_symlink_entry_is_refused(tmp_path):
    buf = io.BytesIO()
    entry = {"path": "skills/link", "size": 6, "sha256": hashlib.sha256(b"/etc/x").hexdigest()}
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "spike-backup", "version": 1, "spike_version": "0",
                                                "created": 0, "include_models": False, "files": [entry]}))
        info = zipfile.ZipInfo("files/skills/link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        z.writestr(info, b"/etc/x")
    with pytest.raises(BackupError, match="symlink"):
        backup.inspect_backup(buf.getvalue(), tmp_path)


def test_truncated_unknown_version_sha_and_listing_mismatch(tmp_path):
    good = build({"skills/a/SKILL.md": b"hello"})
    assert backup.inspect_backup(good, tmp_path)["add"] == 1
    with pytest.raises(BackupError):
        backup.inspect_backup(good[: len(good) // 2], tmp_path)
    with pytest.raises(BackupError, match="version"):
        backup.inspect_backup(build({"skills/a/SKILL.md": b"hello"}, version=99), tmp_path)
    with pytest.raises(BackupError, match="SHA-256"):
        backup.inspect_backup(build({"skills/a/SKILL.md": b"hello"}, sha_override={"skills/a/SKILL.md": "0" * 64}),
                              tmp_path)
    with pytest.raises(BackupError, match="not in the manifest"):
        backup.inspect_backup(build({"skills/a/SKILL.md": b"hello"}, unlisted={"skills/other.txt": b"smuggled"}),
                              tmp_path)
    with pytest.raises(BackupError, match="missing"):
        backup.inspect_backup(build({"skills/a/SKILL.md": b"hello"}, extra_manifest=[
            {"path": "skills/b/SKILL.md", "size": 1, "sha256": "0" * 64}]), tmp_path)
    with pytest.raises(BackupError):
        backup.inspect_backup(b"not a zip at all", tmp_path)


def test_zip_bomb_is_capped_by_decompressed_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "MAX_BYTES", 10_000)
    blob = build({"skills/a/big.txt": b"0" * 200_000})
    assert len(blob) < 2000  # a tiny archive that expands 100x
    with pytest.raises(BackupError, match="too large"):
        backup.inspect_backup(blob, tmp_path)
    # a header that lies about its size is caught while reading, not trusted
    monkeypatch.setattr(backup, "MAX_BYTES", 150_000)
    monkeypatch.setattr(backup, "_declared_total", lambda infos: 0)
    with pytest.raises(BackupError, match="too large"):
        backup.inspect_backup(blob, tmp_path)
