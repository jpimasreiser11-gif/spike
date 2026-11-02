"""Reliability tests for file checkpoints (`spike/store/checkpoints.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from spike.store.checkpoints import CheckpointError, Checkpoints
from spike.store.db import Store
from tests.helpers import ScriptedProvider, call, text


def make_checkpoints(tmp_path: Path) -> tuple[Store, Checkpoints, str]:
    store = Store(tmp_path / "spike.db")
    cps = Checkpoints(store, tmp_path / "checkpoints")
    conv = store.create_conversation(title="checkpoint-reliability")
    return store, cps, conv["id"]


def test_duplicate_target_paths_are_deduplicated_in_before_and_undo(tmp_path: Path) -> None:
    store, cps, cid = make_checkpoints(tmp_path)
    ws = tmp_path / "ws"
    (ws / "sub").mkdir(parents=True)
    note = ws / "notas.md"
    note.write_text("versión 1", encoding="utf-8")

    cp_id = cps.before(cid, "c1", "write_file", [note, ws / "." / "notas.md", ws / "sub" / ".." / "notas.md"])
    assert cp_id is not None
    saved = store.get_checkpoint(cp_id)
    assert saved is not None and len(saved["files"]) == 1
    assert list((tmp_path / "checkpoints" / cp_id).glob("*.bin")) == [tmp_path / "checkpoints" / cp_id / "0.bin"]

    note.write_text("versión 2", encoding="utf-8")
    cps.after(cp_id)
    note.write_text("edición manual posterior", encoding="utf-8")

    with pytest.raises(CheckpointError) as exc_info:
        cps.undo(cp_id)
    assert exc_info.value.status == 409
    assert len(exc_info.value.changed) == 1

    cps.undo(cp_id, force=True)
    assert note.read_text(encoding="utf-8") == "versión 1"


def test_atomic_restore_preserves_file_mode_and_cleans_temp_file_on_copy_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os
    import stat

    store, cps, cid = make_checkpoints(tmp_path)
    script = tmp_path / "deploy.sh"
    script.write_text("#!/bin/sh\necho v1\n", encoding="utf-8")
    script.chmod(0o755)

    cp_id = cps.before(cid, "c1", "write_file", [script])
    assert cp_id is not None
    script.write_text("#!/bin/sh\necho v2\n", encoding="utf-8")
    script.chmod(0o644)
    cps.after(cp_id)

    def failing_replace(src, dst):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        cps.undo(cp_id)
    assert script.read_text(encoding="utf-8") == "#!/bin/sh\necho v2\n"
    assert list(tmp_path.glob(".spike-undo-*")) == []
    assert store.get_checkpoint(cp_id)["undone"] is None

    monkeypatch.undo()
    cps.undo(cp_id)
    assert script.read_text(encoding="utf-8") == "#!/bin/sh\necho v1\n"
    if os.name != "nt":
        assert stat.S_IMODE(script.stat().st_mode) == 0o755


def test_missing_backup_copy_returns_400_atomically_without_partial_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    client = TestClient(create_app(state))
    client.get("/api/providers")
    client.put("/api/settings", json={"tool_policies": {"write_file": "allow"}})

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    first = ws / "primero.txt"
    second = ws / "segundo.txt"
    first.write_text("antes-1", encoding="utf-8")
    second.write_text("antes-2", encoding="utf-8")

    conv = state.store.create_conversation(title="multi")
    cp_id = state.checkpoints.before(conv["id"], "c1", "multi_write", [first, second])
    assert cp_id is not None
    first.write_text("después-1", encoding="utf-8")
    second.write_text("después-2", encoding="utf-8")
    state.checkpoints.after(cp_id)

    # Simulate missing backup copy for the second file.
    (tmp_path / "checkpoints" / cp_id / "1.bin").unlink()

    res = client.post(f"/api/checkpoints/{cp_id}/undo", json={})
    assert res.status_code == 400
    # Atomic pre-validation: the first file must NOT have been rolled back when the second copy is missing.
    assert first.read_text(encoding="utf-8") == "después-1"
    assert second.read_text(encoding="utf-8") == "después-2"
    assert state.store.get_checkpoint(cp_id)["undone"] is None

    # Also verify normal HTTPchat flow still works end-to-end with simulated provider.
    scripts["spike-local"]._script = [call("write_file", {"path": "ok.txt", "content": "hola"}, "c2"), text("Listo")]
    chat_res = client.post("/api/chat", json={"message": "Crea ok.txt", "mode": "core"})
    assert chat_res.status_code == 200
    assert (ws / "ok.txt").read_text(encoding="utf-8") == "hola"


def test_corrupted_backup_copy_is_detected_by_sha256_before_overwriting_workspace(tmp_path: Path) -> None:
    store, cps, cid = make_checkpoints(tmp_path)
    target = tmp_path / "datos.txt"
    target.write_text("contenido íntegro UTF-8 áéíóú", encoding="utf-8")

    cp_id = cps.before(cid, "c1", "write_file", [target])
    assert cp_id is not None
    target.write_text("contenido nuevo", encoding="utf-8")
    cps.after(cp_id)

    (tmp_path / "checkpoints" / cp_id / "0.bin").write_bytes(b"corrupted-bytes")

    with pytest.raises(CheckpointError) as exc_info:
        cps.undo(cp_id, force=True)
    assert exc_info.value.status == 400
    assert target.read_text(encoding="utf-8") == "contenido nuevo"
    assert store.get_checkpoint(cp_id)["undone"] is None


def test_directory_or_file_ancestor_collision_raises_409_instead_of_writing_inside_dir(tmp_path: Path) -> None:
    store, cps, cid = make_checkpoints(tmp_path)

    # Case A: target existed as a file, later replaced by a directory.
    file_a = tmp_path / "informe.md"
    file_a.write_text("original", encoding="utf-8")
    cp_a = cps.before(cid, "c1", "write_file", [file_a])
    assert cp_a is not None
    file_a.write_text("modificado", encoding="utf-8")
    cps.after(cp_a)

    file_a.unlink()
    file_a.mkdir()
    with pytest.raises(CheckpointError) as exc_a:
        cps.undo(cp_a, force=True)
    assert exc_a.value.status == 409
    assert not (file_a / "0.bin").exists()
    assert store.get_checkpoint(cp_a)["undone"] is None

    # Case B: target did not exist before, and a directory now sits at that path.
    path_b = tmp_path / "carpeta_nueva"
    cp_b = cps.before(cid, "c2", "write_file", [path_b])
    assert cp_b is not None
    cps.after(cp_b)
    path_b.mkdir()
    with pytest.raises(CheckpointError) as exc_b:
        cps.undo(cp_b)
    assert exc_b.value.status == 409
    assert store.get_checkpoint(cp_b)["undone"] is None

    # Case C: parent directory was replaced by a regular file.
    nested = tmp_path / "parent_dir" / "nota.txt"
    nested.parent.mkdir()
    nested.write_text("antes", encoding="utf-8")
    cp_c = cps.before(cid, "c3", "write_file", [nested])
    assert cp_c is not None
    nested.write_text("después", encoding="utf-8")
    cps.after(cp_c)

    nested.unlink()
    nested.parent.rmdir()
    nested.parent.write_text("bloqueador", encoding="utf-8")
    with pytest.raises(CheckpointError) as exc_c:
        cps.undo(cp_c, force=True)
    assert exc_c.value.status == 409
    assert store.get_checkpoint(cp_c)["undone"] is None


def test_unfinalized_checkpoint_without_after_handles_untouched_and_interrupted_files(tmp_path: Path) -> None:
    _, cps, cid = make_checkpoints(tmp_path)

    # 1. Interrupted before touching the files: undo succeeds without false 409.
    untouched = tmp_path / "intacto.txt"
    untouched.write_text("v1", encoding="utf-8")
    absent = tmp_path / "ausente.txt"
    cp_untouched = cps.before(cid, "c1", "write_file", [untouched, absent])
    assert cp_untouched is not None
    cps.undo(cp_untouched)
    assert untouched.read_text(encoding="utf-8") == "v1"
    assert not absent.exists()

    # 2. Interrupted after deleting an existing file (before `after()` recorded post-step hashes):
    # must NOT mistake `_sha(deleted) is None == entry.get("after")` for an unmodified post-step state.
    deleted_mid_step = tmp_path / "borrado.txt"
    deleted_mid_step.write_text("v1", encoding="utf-8")
    cp_deleted = cps.before(cid, "c2", "write_file", [deleted_mid_step])
    assert cp_deleted is not None
    deleted_mid_step.unlink()
    with pytest.raises(CheckpointError) as exc_del:
        cps.undo(cp_deleted, force=False)
    assert exc_del.value.status == 409
    assert exc_del.value.changed == [str(deleted_mid_step)]
    cps.undo(cp_deleted, force=True)
    assert deleted_mid_step.read_text(encoding="utf-8") == "v1"


def test_failed_before_copy_cleans_up_unindexed_checkpoint_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import shutil

    store, cps, cid = make_checkpoints(tmp_path)
    f1 = tmp_path / "uno.txt"
    f2 = tmp_path / "dos.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")

    real_copy2 = shutil.copy2
    calls = 0

    def flaky_copy2(src, dst, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk read failure on second target")
        return real_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", flaky_copy2)
    with pytest.raises(OSError, match="simulated disk read failure"):
        cps.before(cid, "c1", "multi_write", [f1, f2])

    assert store.list_checkpoints(cid) == []
    assert not (tmp_path / "checkpoints").exists() or list((tmp_path / "checkpoints").iterdir()) == []
