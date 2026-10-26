"""A9: local snapshots, approved diffs, versioned discussions and specialist isolation."""

import pytest

from tests.helpers import text
from tests.test_projects import env as project_env
from tests.test_projects import events_of, make

env = project_env


def test_fork_merge_round_trip_and_stale_approval(env):
    client, state, local = env
    p = make(client, instructions="Fuentes", mode="code")
    base = f"/api/projects/{p['id']}"
    client.put(base + "/files/a.txt", content=b"old\n")
    local._script = [text("answer")]
    client.post("/api/chat", json={"project_id": p["id"], "message": "question"})
    fork = client.post(base + "/fork", json={"name": "Alternative"})
    assert fork.status_code == 200, fork.text
    q = fork.json()
    qb = f"/api/projects/{q['id']}"
    assert q["instructions"] == "Fuentes"
    assert len(client.get(f"/api/conversations?project_id={q['id']}").json()) == 1
    client.put(qb + "/files/a.txt", content=b"new\n")
    client.put(qb + "/files/b.bin", content=b"\x00\xff")
    preview = client.get(qb + "/compare").json()
    assert "-old" in preview["files"][0]["diff"] and "+new" in preview["files"][0]["diff"]
    assert client.post(qb + "/merge", json={"token": preview["token"], "approved": False}).status_code == 422
    client.put(base + "/files/a.txt", content=b"concurrent\n")
    assert client.post(qb + "/merge", json={"token": preview["token"], "approved": True}).status_code == 409
    preview = client.get(qb + "/compare").json()
    assert preview["files"][0]["conflict"]
    assert client.post(qb + "/merge", json={"token": preview["token"], "approved": True}).status_code == 200
    assert client.get(base + "/files/a.txt").content == b"new\n"
    assert client.get(base + "/files/b.bin").content == b"\x00\xff"
    assert client.get(qb + "/compare").json()["files"] == []


def test_branch_rejects_symlinks(env, tmp_path):
    client, state, _ = env
    p = make(client)
    outside = tmp_path / "private.txt"
    outside.write_text("private", encoding="utf-8")
    link = state.project_files.folder(p["id"]) / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert client.post(f"/api/projects/{p['id']}/fork", json={"name": "x"}).status_code == 400


def test_versioned_comment_thread_only_sent_on_request(env):
    client, state, local = env
    artifact = client.post("/api/artifact-versions", json={"content": "first\nsecond", "title": "Page"}).json()
    aid = artifact["id"]
    url = f"/api/artifact-versions/{aid}/comments"
    assert client.post(url, json={"line": 3, "text": "bad"}).status_code == 400
    thread = client.post(url, json={"line": 2, "text": "Change second"}).json()
    reply = client.post(url, json={"line": 2, "text": "Agreed", "parent": thread["id"]})
    assert reply.status_code == 200
    assert len(client.get(url).json()) == 2
    other = client.post("/api/artifact-versions", json={"content": "changed", "title": "Page"}).json()
    assert client.get(f"/api/artifact-versions/{other['id']}/comments").json() == []
    local._script = [text("ok")]
    r = client.post("/api/chat", json={"message": "hello"})
    assert "Change second" not in local.requests[-1].messages[0].content
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "apply", "conversation_id": events_of(r)[0]["id"],
                                    "comment_threads": [thread["id"]]})
    assert "Change second" in local.requests[-1].messages[0].content
    assert "Agreed" in local.requests[-1].messages[0].content
    assert state.discussions.comments(aid)[0]["line"] == 2


def test_specialist_knowledge_isolated_and_documents(env):
    client, _, local = env
    for spec, secret in (("code", "quartz code detail"), ("medicine", "quartz medical detail")):
        scope = f"specialist:{spec}"
        assert client.post("/api/memory", json={"scope": scope, "kind": "document", "text": secret}).status_code == 200
    assert client.post("/api/memory", json={"scope": "specialist:missing", "kind": "fact", "text": "x"}).status_code == 400
    local._script = [text("ok")]
    client.post("/api/chat", json={"message": "quartz", "mode": "code"})
    prompt = local.requests[-1].messages[0].content
    assert "quartz code detail" in prompt and "quartz medical detail" not in prompt


def test_deletions_parent_only_files_and_stale_source(env):
    client, _, _ = env
    p = make(client)
    url = f"/api/projects/{p['id']}"
    client.put(url + "/files/remove.txt", content=b"delete")
    q = client.post(url + "/fork", json={"name": "branch"}).json()
    branch = f"/api/projects/{q['id']}"
    client.delete(branch + "/files/remove.txt")
    client.put(url + "/files/parent-only.txt", content=b"preserve")
    preview = client.get(branch + "/compare").json()
    assert preview["files"][0]["deleted"]
    client.put(branch + "/files/late.txt", content=b"late")
    assert client.post(branch + "/merge", json={"token": preview["token"], "approved": True}).status_code == 409
    preview = client.get(branch + "/compare").json()
    client.post(branch + "/merge", json={"token": preview["token"], "approved": True})
    assert client.get(url + "/files/remove.txt").status_code == 404
    assert client.get(url + "/files/parent-only.txt").content == b"preserve"


def test_documents_replace_within_specialist_and_persist_comments(env):
    client, state, _ = env
    for value in ("first", "second"):
        r = client.post("/api/specialist-documents", json={"specialist": "code", "filename": "notes.md", "text": value})
        assert r.status_code == 200
        assert r.json()["source"] == "file:notes.md"
    notes = client.get("/api/memory?scope=specialist:code").json()
    assert len(notes) == 1 and notes[0]["text"] == "second"
    assert client.post("/api/specialist-documents", json={"specialist": "unknown", "filename": "a", "text": "b"}).status_code == 400
    artifact = client.post("/api/artifact-versions", json={"title": "é", "content": "ñ"}).json()["id"]
    comment = client.post(f"/api/artifact-versions/{artifact}/comments", json={"line": 1, "text": "revisión"}).json()
    from spike.artifact_comments import ArtifactComments
    from spike.store.db import Store

    reopened = ArtifactComments(Store(state.home / "spike.db"))
    assert reopened.comments(artifact)[0]["text"] == "revisión"
    other = client.post("/api/artifact-versions", json={"title": "x", "content": "other"}).json()["id"]
    assert client.post(f"/api/artifact-versions/{other}/comments", json={"line": 1, "text": "bad", "parent": comment["id"]}).status_code == 400
    assert client.post("/api/chat", json={"message": "x", "comment_threads": ["unknown"]}).status_code == 400
    assert client.post("/api/jobs/unknown/cancel").status_code == 404
    assert client.get("/api/jobs").json()["limit"] == 1


def test_merge_failure_leaves_parent_unchanged(env, monkeypatch):
    client, state, _ = env
    p = make(client)
    base = f"/api/projects/{p['id']}"
    client.put(base + "/files/a", content=b"original")
    q = client.post(base + "/fork", json={"name": "branch"}).json()["id"]
    client.put(f"/api/projects/{q}/files/a", content=b"edited")
    preview = client.get(f"/api/projects/{q}/compare").json()
    original = state.store._exec

    def fail(sql, params=()):
        if sql.startswith("UPDATE project_branches"):
            raise OSError("simulated persistence failure")
        return original(sql, params)

    monkeypatch.setattr(state.store, "_exec", fail)
    with pytest.raises(OSError):
        state.branches.merge(q, preview["token"])
    assert client.get(base + "/files/a").content == b"original"


@pytest.mark.asyncio
async def test_real_app_paths_submit_render_indexing_and_eval(env, monkeypatch):
    import asyncio

    from spike.evolution import prompts
    from spike.tools.base import ToolResult

    _, state, _ = env
    state.jobs.ram_floor = 0
    render = state.tools.get("render_video")

    async def fake_render(args):
        return ToolResult(ok=True, content="fake")

    monkeypatch.setattr(render, "_run", fake_render)
    assert (await render.run({})).ok

    class FakeEmbedder:
        model = "fake"

    async def embedder():
        return FakeEmbedder()

    async def fake_index(embedding, limit):
        return 0

    async def fake_activate(*args):
        return {"ok": True}

    monkeypatch.setattr(state.memory, "get_embedder", embedder)
    monkeypatch.setattr(state.memory, "_index", fake_index)
    monkeypatch.setattr(prompts, "activate", fake_activate)
    assert await state.memory.index() == 0
    assert await state.activate_prompt("code") == {"ok": True}
    assert [j["kind"] for j in state.jobs.list()] == ["render", "indexing", "eval"]
    jid = state.jobs.submit("training", lambda: asyncio.sleep(0))
    await state.jobs.wait(jid)
    await state.jobs.close()


def test_cancelled_eval_stream_emits_terminal_event(env, monkeypatch):
    import asyncio

    client, state, _ = env

    async def cancelled(*args):
        raise asyncio.CancelledError

    monkeypatch.setattr(state, "optimize_prompt", cancelled)
    response = client.post("/api/evolution/prompts/code/optimize", json={})
    assert events_of(response)[-1]["type"] == "error"
    assert not state.optimizing


def test_fork_and_merge_refresh_project_file_knowledge(env):
    client, state, _ = env
    p = make(client)
    base = f"/api/projects/{p['id']}"
    client.put(base + "/files/note.txt", content=b"quartz old")
    q = client.post(base + "/fork", json={"name": "alternative"}).json()["id"]
    assert state.memory.store.find_source(f"project:{q}", "file:note.txt").text == "quartz old"
    branch = f"/api/projects/{q}"
    client.put(branch + "/files/note.txt", content=b"quartz new")
    preview = client.get(branch + "/compare").json()
    client.post(branch + "/merge", json={"approved": True, "token": preview["token"]})
    assert state.memory.store.find_source(f"project:{p['id']}", "file:note.txt").text == "quartz new"
    client.delete(branch + "/files/note.txt")
    preview = client.get(branch + "/compare").json()
    client.post(branch + "/merge", json={"approved": True, "token": preview["token"]})
    assert state.memory.store.find_source(f"project:{p['id']}", "file:note.txt") is None


@pytest.mark.asyncio
async def test_indexing_ram_gate_precedes_embedding_startup(env, monkeypatch):
    import asyncio

    _, state, _ = env
    started = []
    state.jobs.available = lambda: 0

    async def embedder():
        started.append(True)
        return None

    monkeypatch.setattr(state.memory, "get_embedder", embedder)
    task = asyncio.create_task(state.memory.index())
    await asyncio.sleep(0.01)
    try:
        assert not started
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await state.jobs.close()


def test_fork_rejects_project_directory_symlink_before_creating_files(env, tmp_path):
    client, state, _ = env
    p = make(client)
    outside = tmp_path / "outside"
    outside.mkdir()
    state.project_files.root.mkdir(exist_ok=True)
    try:
        (state.project_files.root / p["id"]).symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert client.post(f"/api/projects/{p['id']}/fork", json={"name": "x"}).status_code == 400
    assert not (outside / "files").exists()
