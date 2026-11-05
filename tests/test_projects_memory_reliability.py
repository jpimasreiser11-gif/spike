"""Reliability and edge-case tests for projects and memory (G14).

Covers:
1. ZIP import/export with malformed or weird paths, file-vs-directory collisions,
   falsified ZIP headers (decompression bomb), corrupt deflate streams, and
   malformed manifest types.
2. Unicode names (NFC vs NFD normalization across ProjectFiles, ZIP round-trip,
   memory indexing/deletion, and export Content-Disposition slug).
3. 0-byte files across ProjectFiles, ZIP round-trip, ProjectBranches, and
   FolderIndex truncation re-indexing.
4. Concurrent deletion across ProjectFiles.list, export_project, file DELETE API,
   and MemoryStore.update.
5. Folder indexing with symlink loops, broken symlinks, and permission-denied files.
6. Glossary duplicate terms (zero-width characters, in-batch CSV duplicates,
   duplicate CSV header aliases, and multi-language Recall.event deduplication).
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import stat
import unicodedata
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.memory.folders import DEFAULT_INCLUDE, FolderIndex, scan_folder
from spike.memory.glossary import GLOBAL, Glossary, GlossaryError
from spike.memory.service import MemoryService
from spike.memory.store import MemoryStore
from spike.project_branches import ProjectBranches
from spike.projects import (
    ProjectError,
    ProjectFiles,
    clean_path,
    export_project,
    import_project,
)
from spike.server.app import create_app
from spike.server.state import AppState
from spike.store.db import Store
from tests.helpers import ScriptedProvider


def test_clean_path_and_zip_weird_paths_and_collisions(tmp_path: Path) -> None:
    store = Store(tmp_path / "c.db")
    files = ProjectFiles(tmp_path / "projects")
    proj = store.create_project("WeirdPaths")

    # 1. "." / "./a.txt" / "a//b.txt" / "a/." / NUL bytes must be rejected by clean_path.
    for bad in [".", "./", "./a.txt", "a/./b.txt", "a//b.txt", "a/.", "a.txt/", "bad\x00.txt", "bad\n.txt"]:
        with pytest.raises(ProjectError):
            clean_path(bad)
        with pytest.raises(ProjectError):
            files.write(proj["id"], bad, b"nope")

    # 2. File-vs-directory collisions in ProjectFiles.write must raise ProjectError (not OSError 500).
    files.write(proj["id"], "folder/note.md", b"hello")
    with pytest.raises(ProjectError, match="directory|file|path"):
        files.write(proj["id"], "folder", b"conflict with directory")

    files.write(proj["id"], "leaf.txt", b"leaf")
    with pytest.raises(ProjectError, match="directory|file|path"):
        files.write(proj["id"], "leaf.txt/child.txt", b"conflict with file")

    # 3. ZIP with file-vs-directory collision or duplicate entry must raise ProjectError.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "project.json",
            json.dumps({"format": "spike-project", "version": 1, "project": {"name": "Collision"}, "conversations": []}),
        )
        zf.writestr("files/collide", b"file first")
        zf.writestr("files/collide/sub.txt", b"then child under file")
    with pytest.raises(ProjectError):
        import_project(store, files, buf.getvalue(), set())

    # 4. Malformed manifest types (project not dict, conversations not list) must raise ProjectError.
    for bad_manifest in [
        {"format": "spike-project", "version": 1, "project": "not-a-dict", "conversations": []},
        {"format": "spike-project", "version": 1, "project": {"name": "X"}, "conversations": "not-a-list"},
        {"format": "spike-project", "version": 1, "project": {"name": "X"}, "conversations": ["not-a-dict"]},
        {
            "format": "spike-project",
            "version": 1,
            "project": {"name": "X"},
            "conversations": [{"title": "C", "messages": ["not-a-dict"]}],
        },
    ]:
        mbuf = io.BytesIO()
        with zipfile.ZipFile(mbuf, "w") as zf:
            zf.writestr("project.json", json.dumps(bad_manifest))
        with pytest.raises(ProjectError):
            import_project(store, files, mbuf.getvalue(), set())

    # 5. Decompression size check on actual read bytes when ZIP header lies about file_size = 0.
    sbuf = io.BytesIO()
    with zipfile.ZipFile(sbuf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "project.json",
            json.dumps({"format": "spike-project", "version": 1, "project": {"name": "Bomb"}, "conversations": []}),
        )
        zf.writestr("files/big.txt", b"A" * 2048)

    import spike.projects as projects_mod

    orig_max = projects_mod.MAX_FILE_BYTES
    orig_infolist = zipfile.ZipFile.infolist

    def lied_infolist(self: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
        infos = orig_infolist(self)
        for info in infos:
            if info.filename == "files/big.txt":
                info.file_size = 10  # Lie in header while actual payload is 2048 bytes
        return infos

    projects_mod.MAX_FILE_BYTES = 512
    zipfile.ZipFile.infolist = lied_infolist  # type: ignore[method-assign]
    try:
        # Python's zipfile either flags the header mismatch as corrupt or import_project catches len(data) > MAX_FILE_BYTES
        with pytest.raises(ProjectError, match="limit|corrupt"):
            import_project(store, files, sbuf.getvalue(), set())
        orig_read = zipfile.ZipFile.read
        zipfile.ZipFile.read = lambda self, name, pwd=None: (  # type: ignore[method-assign]
            b"A" * 2048 if (getattr(name, "filename", name) == "files/big.txt") else orig_read(self, name, pwd)
        )
        try:
            with pytest.raises(ProjectError, match="limit"):
                import_project(store, files, sbuf.getvalue(), set())
        finally:
            zipfile.ZipFile.read = orig_read  # type: ignore[method-assign]
    finally:
        projects_mod.MAX_FILE_BYTES = orig_max
        zipfile.ZipFile.infolist = orig_infolist  # type: ignore[method-assign]


def test_unicode_nfc_nfd_normalization_and_memory_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")
    state = AppState(home=tmp_path, provider_factory=lambda cfg: local)
    with TestClient(create_app(state)) as client:
        pr = client.post("/api/projects", json={"name": "Diseño & Árboles"})
        assert pr.status_code == 200
        pid = pr.json()["id"]

        # Upload with NFD filename (as macOS Finder / HFS+ / APFS often produces)
        nfd_name = unicodedata.normalize("NFD", "información/niño_🚀.md")
        nfc_name = unicodedata.normalize("NFC", "información/niño_🚀.md")
        assert nfd_name != nfc_name

        up = client.put(
            f"/api/projects/{pid}/files/{nfd_name}",
            content="El niño estudia astronomía en otoño.".encode(),
        )
        assert up.status_code == 200
        assert up.json()["path"] == nfc_name
        assert up.json()["indexed"] is True

        # List files returns NFC path
        listed = client.get(f"/api/projects/{pid}/files").json()
        assert [f["path"] for f in listed] == [nfc_name]

        # Export Content-Disposition preserves ASCII slug of accented project name ("Diseno-Arboles.spike-project.zip")
        exp = client.get(f"/api/projects/{pid}/export")
        assert exp.status_code == 200
        assert "Diseno" in exp.headers.get("content-disposition", "")
        assert "Arboles" in exp.headers.get("content-disposition", "")

        # Deleting via NFD or NFC URL removes both file and indexed memory source
        del_res = client.delete(f"/api/projects/{pid}/files/{nfd_name}")
        assert del_res.status_code == 200

        mems_res = client.get(f"/api/memory?scope=project:{pid}").json()
        mems = mems_res["memories"] if isinstance(mems_res, dict) and "memories" in mems_res else mems_res
        assert [m for m in mems if m["source"].startswith("file:")] == []

        # Also after deleting "información/niño_🚀.md", the empty "información" directory is pruned
        # so uploading a file named "información" succeeds without IsADirectoryError.
        up_file = client.put(
            f"/api/projects/{pid}/files/información",
            content=b"Archivo plano sin carpeta",
        )
        assert up_file.status_code == 200


def test_zero_byte_files_across_projects_branches_and_folder_index(tmp_path: Path) -> None:
    store = Store(tmp_path / "c.db")
    files = ProjectFiles(tmp_path / "projects")
    proj = store.create_project("ZeroBytes")
    pid = proj["id"]

    # 1. 0-byte file in ProjectFiles + ZIP export/import round-trip
    files.write(pid, "empty.txt", b"")
    files.write(pid, "sub/empty.md", b"")
    assert len(files.list(pid)) == 2
    assert all(f["size"] == 0 for f in files.list(pid))

    archive = export_project(store, files, pid)
    imported = import_project(store, files, archive, set())
    imp_files = files.list(imported["id"])
    assert [(f["path"], f["size"]) for f in imp_files] == [("empty.txt", 0), ("sub/empty.md", 0)]

    # 2. 0-byte file in ProjectBranches fork / compare / merge, plus file-vs-directory collision guard
    branches = ProjectBranches(store, files)
    forked = branches.fork(pid, "EmptyBranch", set())
    fid = forked["id"]
    files.write(fid, "new_empty.txt", b"")
    cmp_res = branches.compare(fid)
    assert any(f["path"] == "new_empty.txt" and not f["deleted"] for f in cmp_res["files"])
    merged = branches.merge(fid, cmp_res["token"])
    assert merged["ok"] is True
    assert files.path(pid, "new_empty.txt").read_bytes() == b""

    # Parent adds "clash/empty.txt" (0 bytes) while branch adds "clash" (0-byte file) -> merge must raise ProjectError
    files.write(pid, "clash/empty.txt", b"")
    files.write(fid, "clash", b"")
    clash_cmp = branches.compare(fid)
    with pytest.raises(ProjectError, match="directory|file|path|collision"):
        branches.merge(fid, clash_cmp["token"])
    files.path(fid, "clash").unlink()

    # 3. FolderIndex: file indexed with content, then truncated to 0 bytes -> old memory removed on re-index
    #    and a file truncated to 0 bytes between scan_folder and _index_file is recorded as "empty" (not "unreadable")
    mem_store = MemoryStore(tmp_path / "mem.db")
    try:
        folder_idx = FolderIndex(mem_store)
        docs = tmp_path / "watched"
        docs.mkdir()
        note = docs / "truncate_me.md"
        note.write_text("Important clause 42 that must be forgotten when truncated.", encoding="utf-8")

        folder = folder_idx.add(str(docs), scope="project:test")
        job1 = folder_idx.queue(folder.id)
        asyncio.run(folder_idx.run(job1))
        assert job1.indexed == 1
        assert len(mem_store.search("clause 42", ["project:test"])) >= 1

        # Truncated before scan:
        note.write_bytes(b"")
        job2 = folder_idx.queue(folder.id)
        asyncio.run(folder_idx.run(job2))
        assert job2.removed == 1
        assert job2.skipped.get("empty", 0) == 1
        assert mem_store.search("clause 42", ["project:test"]) == []

        # Truncated right after scan_folder (before _index_file):
        from spike.memory.folders import Candidate

        race_note = docs / "race_empty.md"
        race_note.write_bytes(b"")
        status = folder_idx._index_file(
            folder,
            Candidate(rel="race_empty.md", path=race_note, size=12, mtime_ns=race_note.stat().st_mtime_ns),
        )
        assert status == "empty"
    finally:
        mem_store.close()


def test_concurrent_deletion_resilience(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store(tmp_path / "c.db")
    files = ProjectFiles(tmp_path / "projects")
    proj = store.create_project("Concurrent")
    pid = proj["id"]
    files.write(pid, "vanish.txt", b"soon gone")
    files.write(pid, "stay.txt", b"still here")

    # 1. Simulate a file disappearing between files.list() and export_project reading bytes
    orig_list = files.list

    def list_with_ghost(project_id: str) -> list[dict]:
        items = orig_list(project_id)
        ghost = files.path(project_id, "vanish.txt")
        if ghost.exists():
            ghost.unlink()
        return items

    monkeypatch.setattr(files, "list", list_with_ghost)
    archive = export_project(store, files, pid)
    with zipfile.ZipFile(io.BytesIO(archive), "r") as zf:
        assert "files/stay.txt" in zf.namelist()
        assert "files/vanish.txt" not in zf.namelist()
    monkeypatch.setattr(files, "list", orig_list)

    # 2. MemoryStore.update when the row is deleted right before acquiring the write lock
    mem_store = MemoryStore(tmp_path / "mem.db")
    try:
        mem = mem_store.add("Initial text before race", kind="fact", scope="global")
        assert mem is not None

        orig_get = mem_store.get

        def get_then_concurrent_delete(memory_id: str):
            res = orig_get(memory_id)
            mem_store.delete(memory_id)
            return res

        monkeypatch.setattr(mem_store, "get", get_then_concurrent_delete)
        # Must return None cleanly instead of raising sqlite3.IntegrityError: FOREIGN KEY constraint failed
        assert mem_store.update(mem.id, text="Updated text after concurrent delete") is None
    finally:
        mem_store.close()


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink and chmod 000 semantics")
def test_folder_index_symlink_loops_broken_links_and_permission_denied(tmp_path: Path) -> None:
    mem_store = MemoryStore(tmp_path / "mem.db")
    try:
        folder_idx = FolderIndex(mem_store)
        root = tmp_path / "vault"
        root.mkdir()
        (root / "ok.md").write_text("Accessible document content.", encoding="utf-8")

        # 1. Broken symlink inside root
        (root / "broken.md").symlink_to(root / "does_not_exist.md")

        # 2. Symlink loop inside root (loop_a.md -> loop_b.md -> loop_a.md)
        (root / "loop_a.md").symlink_to(root / "loop_b.md")
        (root / "loop_b.md").symlink_to(root / "loop_a.md")

        # 3. Unreadable file (chmod 000) both for text (.md) and container (.pdf)
        secret_md = root / "secret.md"
        secret_md.write_text("Top secret unreadable file.", encoding="utf-8")
        secret_pdf = root / "secret.pdf"
        secret_pdf.write_bytes(b"%PDF-1.4 unreadable")
        secret_md.chmod(0)
        secret_pdf.chmod(0)
        try:
            inc = [*DEFAULT_INCLUDE, "*.pdf"]
            folder = folder_idx.add(str(root), scope="global", include=inc)
            scan = scan_folder(folder)
            # Broken symlink and 2 loop symlinks must all be counted as "link", NOT "denied" or silently ignored
            assert scan.skipped.get("link", 0) == 3

            job = folder_idx.queue(folder.id)
            asyncio.run(folder_idx.run(job))
            assert job.indexed == 1
            assert job.skipped.get("link", 0) == 3
            assert job.skipped.get("denied", 0) == 2

            files_status = {f["path"]: f["status"] for f in folder_idx.files(folder.id)}
            assert files_status["ok.md"] == "indexed"
            assert files_status["secret.md"] == "denied"
            assert files_status["secret.pdf"] == "denied"
        finally:
            secret_md.chmod(stat.S_IRUSR | stat.S_IWUSR)
            secret_pdf.chmod(stat.S_IRUSR | stat.S_IWUSR)
    finally:
        mem_store.close()


def test_glossary_duplicates_zero_width_csv_batches_and_recall_dedup(tmp_path: Path) -> None:
    mem_store = MemoryStore(tmp_path / "mem.db")
    try:
        g = Glossary(mem_store)

        # 1. Zero-width characters (\u200b, \ufeff) must be stripped and rejected as duplicates
        g.add("invoice", "factura", lang="es")
        with pytest.raises(GlossaryError, match="already in this glossary"):
            g.add("invoice\u200b", "factura duplicada", lang="es")
        with pytest.raises(GlossaryError, match="already in this glossary"):
            g.add("\ufeffINVOICE", "otra factura", lang="es")

        # 2. CSV import with duplicate terms inside the same CSV batch must not inflate both added & updated,
        #    and duplicate header aliases (translation + definition where definition is empty) must not wipe translation.
        mem_store2 = MemoryStore(tmp_path / "mem2.db")
        try:
            g2 = Glossary(mem_store2)
            csv_text = (
                "term,translation,definition,lang\n"
                "churn,cancelación,,es\n"
                "Churn,baja de clientes,,es\n"
            )
            report = g2.import_csv(csv_text, scope=GLOBAL)
            entries = g2.list(GLOBAL)
            assert len(entries) == 1
            assert entries[0].translation == "baja de clientes"
            assert report["added"] == 1
            assert report["updated"] == 0

            # 3. Recall.event()["glossary"] deduplicates term names when multiple languages match the same term
            g2.add("churn", "taxa de cancelamento", lang="pt")

            async def _no_embedder():
                return None

            svc = MemoryService(mem_store2, _no_embedder)
            recall = asyncio.run(svc.recall("How do we reduce churn this quarter?", None))
            assert len(recall.glossary) == 2
            assert [t.lower() for t in recall.event()["glossary"]] == ["churn"]
        finally:
            mem_store2.close()
    finally:
        mem_store.close()
