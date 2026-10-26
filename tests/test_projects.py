"""Projects: their own instructions, default specialist, workspace and chats; export and import as one zip."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    return TestClient(create_app(state)), state, local


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def make(client, **fields) -> dict:
    r = client.post("/api/projects", json={"name": "Tesis", **fields})
    assert r.status_code == 200, r.text
    return r.json()


def test_project_crud(env):
    client, _, _ = env
    p = make(client, instructions="Cita siempre las fuentes.", mode="medicine")
    assert (p["name"], p["instructions"], p["mode"]) == ("Tesis", "Cita siempre las fuentes.", "medicine")
    assert [x["id"] for x in client.get("/api/projects").json()] == [p["id"]]
    assert client.patch(f"/api/projects/{p['id']}", json={"name": "Tesis 2"}).json()["name"] == "Tesis 2"
    assert client.get(f"/api/projects/{p['id']}").json()["name"] == "Tesis 2"
    assert client.post("/api/projects", json={"name": "x", "mode": "astrology"}).status_code == 400
    assert client.post("/api/projects", json={"name": ""}).status_code == 422
    assert client.delete(f"/api/projects/{p['id']}").json()["ok"]
    assert client.get("/api/projects").json() == []
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_project_chats_use_its_instructions_and_default_specialist(env):
    client, state, local = env
    p = make(client, instructions="Cita siempre las fuentes.", mode="medicine")
    local._script = [text("ok")]
    r = client.post("/api/chat", json={"message": "hola", "project_id": p["id"]})
    conv = events_of(r)[0]
    system = local.requests[-1].messages[0].content
    assert "Spike Medicine" in system and "# Project instructions\nCita siempre las fuentes." in system
    assert [c["id"] for c in client.get(f"/api/conversations?project_id={p['id']}").json()] == [conv["id"]]
    assert client.get("/api/conversations").json() == []  # project chats live in their project
    assert client.get(f"/api/conversations/{conv['id']}").json()["project_id"] == p["id"]
    local._script = [text("ok")]  # a follow-up in the same chat keeps the project even without project_id
    client.post("/api/chat", json={"message": "y más", "conversation_id": conv["id"], "mode": "auto"})
    assert "# Project instructions" in local.requests[-1].messages[0].content
    assert client.post("/api/chat", json={"message": "x", "project_id": "nope"}).status_code == 400


def test_file_tools_use_the_project_workspace(env, tmp_path):
    client, state, local = env
    client.put("/api/settings", json={"tool_policies": {"write_file": "allow"}})
    a, b = make(client, name="A", mode="code"), make(client, name="B", mode="code")
    local._script = [call("write_file", {"path": "plan.md", "content": "secret plan"}), text("done")]
    client.post("/api/chat", json={"message": "write plan.md", "project_id": a["id"]})
    assert [f["path"] for f in client.get(f"/api/projects/{a['id']}/files").json()] == ["plan.md"]
    assert client.get(f"/api/projects/{b['id']}/files").json() == []
    assert not (tmp_path / "ws" / "plan.md").exists()
    local._script = [call("read_file", {"path": "plan.md"}), text("nothing")]
    client.post("/api/chat", json={"message": "read plan.md", "project_id": b["id"]})
    assert "secret plan" not in local.requests[-1].messages[-1].content


def test_project_files_upload_list_download_delete(env):
    client, _, _ = env
    p = make(client)
    base = f"/api/projects/{p['id']}/files"
    assert client.put(f"{base}/notes/a.txt", content=b"hola").status_code == 200
    assert client.get(base).json() == [{"path": "notes/a.txt", "size": 4}]
    assert client.get(f"{base}/notes/a.txt").content == b"hola"
    for bad in ("..%2Fescape.txt", "notes/..%2F..%2Fescape.txt"):
        assert client.put(f"{base}/{bad}", content=b"x").status_code == 400
    assert client.delete(f"{base}/notes/a.txt").json()["ok"]
    assert client.get(base).json() == []
    assert client.get(f"{base}/notes/a.txt").status_code == 404


def test_export_then_import_is_identical_and_has_no_keys(env):
    client, state, local = env
    client.post("/api/providers", json={"preset": "deepseek", "api_key": "sk-never-exported", "model": "deepseek-chat"})
    p = make(client, instructions="Formal.", mode="finance")
    client.put(f"/api/projects/{p['id']}/files/data/q3.csv", content=b"a,b\n1,2\n")
    local._script = [text("EBITDA ", "is…")]
    client.post("/api/chat", json={"message": "EBITDA?", "project_id": p["id"]})
    exported = client.get(f"/api/projects/{p['id']}/export")
    assert exported.status_code == 200 and exported.headers["content-type"] == "application/zip"
    assert b"sk-never-exported" not in exported.content

    imported = client.post("/api/projects/import", content=exported.content)
    assert imported.status_code == 200, imported.text
    q = imported.json()
    assert q["id"] != p["id"] and q["name"] == "Tesis"
    again = client.get(f"/api/projects/{q['id']}/export").content

    def contents(blob: bytes) -> dict[str, bytes]:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            return {n: z.read(n) for n in z.namelist()}

    assert contents(again) == contents(exported.content)
    convs = client.get(f"/api/conversations?project_id={q['id']}").json()
    assert [m["content"] for m in client.get(f"/api/conversations/{convs[0]['id']}").json()["messages"]] == [
        "EBITDA?", "EBITDA is…"]


def zip_of(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_import_rejects_unsafe_archives(env, tmp_path):
    client, _, _ = env
    manifest = json.dumps({"format": "spike-project", "version": 1, "project": {"name": "x"}, "conversations": []})
    assert client.post("/api/projects/import", content=b"not a zip").status_code == 400
    assert client.post("/api/projects/import", content=zip_of({"project.json": b"{}"})).status_code == 400
    evil = zip_of({"project.json": manifest.encode(), "files/../../escaped.txt": b"x"})
    assert client.post("/api/projects/import", content=evil).status_code == 400
    assert not list(tmp_path.rglob("escaped.txt"))
    assert client.get("/api/projects").json() == []


def test_project_archive_carries_notes_without_other_scopes_or_local_metadata(env):
    client, state, _ = env
    p, other = make(client), make(client)
    memory = state.memory.store
    memory.add("Responde en tablas", "rule", scope=f"project:{p['id']}",
               source="/private/local/path", meta={"credential": "never-port-this"})
    memory.add("Otra cuenta", "fact", scope=f"project:{other['id']}")
    memory.add("Privado global", "fact")
    archive = client.get(f"/api/projects/{p['id']}/export").content
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        manifest = json.loads(z.read("project.json"))
    assert manifest["memories"] == [{"kind": "rule", "text": "Responde en tablas"}]
    imported = client.post("/api/projects/import", content=archive).json()
    notes = memory.list(scope=f"project:{imported['id']}")
    assert [(m.kind, m.text, m.source, m.meta) for m in notes] == [("rule", "Responde en tablas", "", {})]
    assert notes[0].id != memory.list(scope=f"project:{p['id']}")[0].id


@pytest.mark.parametrize("memories", [None, {}, [{"kind": "invalid", "text": "x"}],
                                     [{"kind": "rule", "text": " "}], ["not a memory"]])
def test_project_import_validates_notes_before_creating_records(env, memories):
    client, _, _ = env
    manifest = {"format": "spike-project", "version": 1, "project": {"name": "x"}, "memories": memories}
    r = client.post("/api/projects/import", content=zip_of({"project.json": json.dumps(manifest).encode()}))
    assert r.status_code == 400, r.text
    assert client.get("/api/projects").json() == []


def test_project_import_rolls_back_notes_and_files_on_failure(env, monkeypatch):
    from spike.projects import ProjectError

    client, state, _ = env
    manifest = {"format": "spike-project", "version": 1, "project": {"name": "x"},
                "memories": [{"kind": "rule", "text": "Solo tablas"}]}
    blob = zip_of({"project.json": json.dumps(manifest).encode(), "files/a.txt": b"a"})

    def broken(*args):
        raise ProjectError("write failed")

    monkeypatch.setattr(state.project_files, "write", broken)
    assert client.post("/api/projects/import", content=blob).status_code == 400
    assert client.get("/api/projects").json() == []
    assert state.memory.store.list() == []


def test_project_file_symlinks_never_escape_or_enter_exports(env, tmp_path):
    client, state, _ = env
    p = make(client)
    root = state.project_files.folder(p["id"])
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
        (root / "secret.txt").symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    base = f"/api/projects/{p['id']}/files"
    for path in ("link/secret.txt", "secret.txt"):
        assert client.get(f"{base}/{path}").status_code == 400
        assert client.put(f"{base}/{path}", content=b"overwritten").status_code == 400
        assert client.delete(f"{base}/{path}").status_code == 400
    assert secret.read_text(encoding="utf-8") == "private"
    assert client.get(base).json() == []
    with zipfile.ZipFile(io.BytesIO(client.get(f"/api/projects/{p['id']}/export").content)) as z:
        assert z.namelist() == ["project.json"]


def test_project_note_export_roundtrip_is_stable_and_skips_generated_indexes(env):
    client, state, _ = env
    p = make(client)
    memory = state.memory.store
    scope = f"project:{p['id']}"
    memory.add("Primera nota", "decision", scope=scope)
    memory.add("Segunda nota", "rule", scope=scope)
    memory.add("Indexed text", "document", scope=scope, source="file:plan.txt")
    memory.add("Generated summary", "summary", scope=scope, source="conversation:old-chat")
    exported = client.get(f"/api/projects/{p['id']}/export").content
    q = client.post("/api/projects/import", content=exported).json()
    assert client.get(f"/api/projects/{q['id']}/export").content == exported
    assert len(memory.list(scope=f"project:{q['id']}")) == 2


def test_project_note_budget_rejected_without_partial_import(env, monkeypatch):
    import spike.projects as projects

    client, state, _ = env
    monkeypatch.setattr(projects, "MAX_MEMORIES", 1)
    p = make(client)
    for note in ("one", "two"):
        state.memory.store.add(note, "fact", scope=f"project:{p['id']}")
    assert client.get(f"/api/projects/{p['id']}/export").status_code == 400
    manifest = {"format": "spike-project", "version": 1, "project": {"name": "over budget"},
                "memories": [{"kind": "fact", "text": text} for text in ("one", "two")]}
    r = client.post("/api/projects/import", content=zip_of({"project.json": json.dumps(manifest).encode()}))
    assert r.status_code == 400
    assert len(client.get("/api/projects").json()) == 1


def test_project_notes_require_a_memory_store_in_direct_import(env):
    from spike.projects import ProjectError, import_project

    _, state, _ = env
    manifest = {"format": "spike-project", "version": 1, "project": {"name": "x"},
                "memories": [{"kind": "fact", "text": "Keep this note"}]}
    blob = zip_of({"project.json": json.dumps(manifest).encode()})
    with pytest.raises(ProjectError, match="project notes need a memory store"):
        import_project(state.store, state.project_files, blob, {"auto"})
    assert state.store.list_projects() == []


@pytest.mark.parametrize("linked_folder", ["project", "files"])
def test_project_root_symlinks_are_rejected_before_access(env, tmp_path, linked_folder):
    client, state, _ = env
    p = make(client)
    project = state.project_files.root / p["id"]
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("private", encoding="utf-8")
    try:
        if linked_folder == "project":
            project.parent.mkdir(parents=True, exist_ok=True)
            project.symlink_to(outside, target_is_directory=True)
        else:
            project.mkdir(parents=True)
            (project / "files").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    base = f"/api/projects/{p['id']}"
    assert client.put(f"{base}/files/new.txt", content=b"no").status_code == 400
    assert client.get(f"{base}/files/secret.txt").status_code == 400
    assert client.delete(f"{base}/files/secret.txt").status_code == 400
    assert client.get(f"{base}/files").status_code == 400
    assert client.get(f"{base}/export").status_code == 400
    assert sorted(x.name for x in outside.iterdir()) == ["secret.txt"]
    assert (outside / "secret.txt").read_text(encoding="utf-8") == "private"
