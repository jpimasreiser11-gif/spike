"""Project deletion handles Git's read-only objects and reports a locked file before losing the project record."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from spike.projects import ProjectError, ProjectFiles
from tests.test_projects import env  # noqa: F401 -- shared isolated application fixture


def test_readonly_git_object_is_retried_before_removing_project(tmp_path, monkeypatch):
    files = ProjectFiles(tmp_path / "projects")
    target = files.folder("project") / ".git" / "objects" / "object"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"object")
    target.chmod(stat.S_IREAD)
    calls = []

    def windows_rmtree(path, **kwargs):
        onerror = kwargs.get("onerror")
        if onerror is None:  # old ignore_errors=True silently leaves the file on Windows
            return
        onerror(os.unlink, str(target), (PermissionError, PermissionError("read-only object"), None))
        calls.append(path)

    monkeypatch.setattr("spike.projects.shutil.rmtree", windows_rmtree)
    files.remove("project")
    assert not target.exists() and calls


def test_real_tree_with_readonly_file_is_removed(tmp_path):
    files = ProjectFiles(tmp_path / "projects")
    target = files.folder("project") / ".git" / "objects" / "object"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"object")
    target.chmod(stat.S_IREAD)
    try:
        files.remove("project")
        assert not (files.root / "project").exists()
    finally:
        if target.exists():
            target.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_failed_delete_preserves_project_and_allows_retry(env, monkeypatch):  # noqa: F811 -- imported pytest fixture
    client, state, _ = env
    project = client.post("/api/projects", json={"name": "No perder"}).json()
    pid = project["id"]
    chat = state.store.create_conversation(project_id=pid)
    state.store.add_message(chat["id"], "user", "keep this conversation")
    client.put(f"/api/projects/{pid}/files/note.txt", content=b"keep")
    real_remove = state.project_files.remove

    def fail(_pid):
        raise ProjectError("Close applications using these files / Cierra las aplicaciones que usan estos archivos")

    monkeypatch.setattr(state.project_files, "remove", fail)
    result = client.delete(f"/api/projects/{pid}")
    assert result.status_code == 409
    assert client.get(f"/api/projects/{pid}").status_code == 200
    assert state.project_files.path(pid, "note.txt").read_bytes() == b"keep"
    assert len(state.store.messages(chat["id"])) == 1
    monkeypatch.setattr(state.project_files, "remove", real_remove)
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert not (state.project_files.root / pid).exists()
    assert state.store.get_conversation(chat["id"]) is None


def test_unrecoverable_error_is_reported_and_missing_folder_is_ok(tmp_path, monkeypatch):
    files = ProjectFiles(tmp_path / "projects")
    files.remove("absent")

    def locked(path, **kwargs):
        raise PermissionError("file remains locked")

    monkeypatch.setattr("spike.projects.shutil.rmtree", locked)
    with pytest.raises(ProjectError):
        files.remove("project")


@pytest.mark.parametrize("pid", ["..", "../other", "a/b", "a\\b", "/absolute", "C:other", ""])
def test_remove_rejects_ids_outside_one_project(tmp_path, monkeypatch, pid):
    monkeypatch.setattr("spike.projects.shutil.rmtree", lambda *a, **k: pytest.fail("invalid ID reached deletion"))
    with pytest.raises(ProjectError):
        ProjectFiles(tmp_path / "projects").remove(pid)


def test_retry_never_changes_permissions_outside_project(tmp_path, monkeypatch):
    files = ProjectFiles(tmp_path / "projects")
    files.folder("project")
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    before = outside.stat().st_mode

    def injected(path, **kwargs):
        kwargs["onerror"](os.unlink, str(outside), (PermissionError, PermissionError("outside"), None))

    monkeypatch.setattr("spike.projects.shutil.rmtree", injected)
    with pytest.raises(ProjectError):
        files.remove("project")
    assert outside.read_bytes() == b"keep" and outside.stat().st_mode == before


def test_remove_rejects_project_resolving_outside_managed_root(tmp_path, monkeypatch):
    files = ProjectFiles(tmp_path / "projects")
    base = files.folder("project").parent
    outside = tmp_path / "outside"
    outside.mkdir()
    resolve = Path.resolve
    # Windows junctions need not be reported as symbolic links. Emulate their resolved path without creating one.
    monkeypatch.setattr(Path, "resolve", lambda path, *a, **kw: outside if path == base else resolve(path, *a, **kw))
    monkeypatch.setattr("spike.projects.shutil.rmtree", lambda *a, **kw: pytest.fail("external project reached deletion"))
    with pytest.raises(ProjectError):
        files.remove("project")
