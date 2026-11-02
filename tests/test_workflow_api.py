"""Workflow routes over HTTP: the catalog, checks before a save, versions in the project, import/export, runs with
their event stream, permission questions, the stop button and the stored records."""

import asyncio
import json
import time
import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from spike.core.types import StreamEvent
from spike.server.app import create_app
from spike.server.state import AppState
from spike.workflows.store import WorkflowStore
from tests.helpers import ScriptedProvider, text
from tests.helpers_workflows import doc, edge, node


def hang(provider: ScriptedProvider) -> ScriptedProvider:
    """A model that never answers (the provider the app already built, so the run really uses it)."""
    async def stream(request):
        provider.requests.append(request)
        await asyncio.Event().wait()
        yield StreamEvent(kind="done")  # pragma: no cover

    provider.stream = stream
    return provider


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts: dict[str, ScriptedProvider] = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    with TestClient(create_app(state)) as client:
        client.get("/api/providers")
        yield client, state, scripts


def new_project(client, name="Proyecto") -> str:
    return client.post("/api/projects", json={"name": name}).json()["id"]


def approval() -> dict:
    """input -> specialist -> condition(contains) -> artifact on each side."""
    return doc([node("topic", "input", name="topic", default="gatos"),
                node("write", "specialist", name="draft", prompt="Escribe sobre {{topic}}"),
                node("check", "condition", op="contains", value="aprobado"),
                node("yes", "output", mode="artifact", title="Resultado", content="{{input}}"),
                node("no", "output", mode="artifact", title="Rechazado", content="No pasa: {{input}}")],
               [edge("topic", "write"), edge("write", "check"), edge("check", "yes", "true"), edge("check", "no", "false")],
               name="Revisión")


def saving() -> dict:
    return doc([node("who", "input", name="who", default="Ana"),
                node("file", "output", mode="file", path="salida/{{who}}.txt", content="Hola {{who}}")],
               [edge("who", "file")], name="Guardar saludo")


def save(client, d, pid):
    r = client.post("/api/workflows", params={"project_id": pid}, json={"workflow": d})
    assert r.status_code == 200, r.text
    return r.json()


def start(client, wid, pid, inputs=None, **extra):
    r = client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid}, json={"inputs": inputs or {}, **extra})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def wait(client, wid, rid, pid, until=lambda run: not run["live"]):
    for _ in range(500):
        run = client.get(f"/api/workflows/{wid}/runs/{rid}", params={"project_id": pid}).json()
        if until(run):
            return run
        time.sleep(0.02)
    raise AssertionError(f"the run did not get there: {run}")


def pending_permission(state):
    for _ in range(500):
        if state.broker.pending:
            return next(iter(state.broker.pending.values()))
        time.sleep(0.02)
    raise AssertionError("no permission question")


def events_of(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


# ---------------------------------------------------------------- catalog, checks, storage
def test_the_catalog_lists_specialists_and_usable_tools_but_not_the_one_that_needs_someone_to_answer(env):
    client, state, _ = env
    catalog = client.get("/api/workflows/catalog").json()
    assert {"core", "finance"} <= {s["id"] for s in catalog["specialists"]}
    names = {t["name"] for t in catalog["tools"]}
    assert {"calculator", "write_file", "read_file"} <= names and "ask_user" not in names
    write = next(t for t in catalog["tools"] if t["name"] == "write_file")
    assert write["policy"] == "ask" and write["parameters"]["required"] == ["path", "content"]
    assert catalog["tools_enabled"] is True and client.get("/api/workflows/catalog?project_id=nope").status_code == 404


def test_validation_names_every_problem_by_node_and_nothing_invalid_is_saved(env):
    client, _, _ = env
    pid = new_project(client)
    bad = doc([node("a", "specialist", prompt="{{ghost}}"), node("b", "specialist", prompt="x"),
               node("t", "tool", tool="rm_rf"), node("q", "tool", tool="ask_user", arguments={"question": "?"})],
              [edge("a", "b"), edge("b", "a")])
    checked = client.post("/api/workflows/validate", params={"project_id": pid}, json={"workflow": bad}).json()
    assert checked["ok"] is False
    assert {(p["code"], p["node"]) for p in checked["problems"]} >= {
        ("var_unknown", "a"), ("tool_unknown", "t"), ("tool_unavailable", "q"), ("cycle", "a")}
    refused = client.post("/api/workflows", params={"project_id": pid}, json={"workflow": bad})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_workflow"
    assert {p["code"] for p in refused.json()["detail"]["problems"]} >= {"cycle", "tool_unknown"}
    assert client.get("/api/workflows", params={"project_id": pid}).json() == []
    assert not any(f["path"].startswith("workflows/") for f in client.get(f"/api/projects/{pid}/files").json())
    assert client.post("/api/workflows/validate", json={"workflow": {"format": "other"}}).json()["ok"] is False
    assert client.post("/api/workflows/validate", json={"workflow": approval()}).json() == {"ok": True, "problems": []}


def test_versions_live_in_the_project_and_travel_with_its_export(env):
    client, _, _ = env
    pid = new_project(client)
    first = save(client, approval(), pid)
    assert first["revision"] == 1
    changed = {**approval(), "name": "Revisión v2"}
    second = client.put(f"/api/workflows/{first['id']}", params={"project_id": pid},
                        json={"workflow": changed, "base_revision": 1}).json()
    assert second["revision"] == 2
    stale = client.put(f"/api/workflows/{first['id']}", params={"project_id": pid},
                       json={"workflow": changed, "base_revision": 1})
    assert stale.status_code == 409 and stale.json()["detail"] == "workflow_conflict"
    assert client.get(f"/api/workflows/{first['id']}", params={"project_id": pid}).json()["name"] == "Revisión v2"
    assert client.get(f"/api/workflows/{first['id']}", params={"project_id": pid, "revision": 1}).json()["name"] == "Revisión"
    assert [v["revision"] for v in client.get(f"/api/workflows/{first['id']}/versions", params={"project_id": pid}).json()] == [2, 1]
    assert [w["revision"] for w in client.get("/api/workflows", params={"project_id": pid}).json()] == [2]
    assert client.get("/api/workflows").json() == []  # another place (the workspace): its own workflows
    listed = {f["path"] for f in client.get(f"/api/projects/{pid}/files").json()}
    assert {f"workflows/{first['id']}/0001.json", f"workflows/{first['id']}/0002.json"} <= listed
    archive = zipfile.ZipFile(BytesIO(client.get(f"/api/projects/{pid}/export").content))
    assert f"files/workflows/{first['id']}/0002.json" in archive.namelist()
    assert client.get("/api/workflows/wf-nope", params={"project_id": pid}).status_code == 404
    assert client.delete(f"/api/workflows/{first['id']}", params={"project_id": pid}).json() == {"ok": True}
    assert client.get("/api/workflows", params={"project_id": pid}).json() == []


def test_export_then_import_round_trips_into_another_project(env):
    client, _, _ = env
    one, two = new_project(client, "Uno"), new_project(client, "Dos")
    saved = save(client, approval(), one)
    exported = client.get(f"/api/workflows/{saved['id']}/export", params={"project_id": one})
    assert exported.headers["content-disposition"].endswith('.spike-workflow.json"')
    portable = exported.json()
    assert "id" not in portable and portable["format"] == "spike-workflow"
    imported = client.post("/api/workflows/import", params={"project_id": two}, json={"workflow": portable})
    assert imported.status_code == 200 and imported.json()["id"] != saved["id"] and imported.json()["revision"] == 1
    original = client.get(f"/api/workflows/{saved['id']}", params={"project_id": one}).json()
    copy = client.get(f"/api/workflows/{imported.json()['id']}", params={"project_id": two}).json()
    assert (copy["name"], copy["nodes"], copy["edges"]) == (original["name"], original["nodes"], original["edges"])
    tampered = {**portable, "nodes": [{**n, "tool": "ghost", "type": "tool"} if n["id"] == "write" else n
                                      for n in portable["nodes"]]}
    refused = client.post("/api/workflows/import", params={"project_id": two}, json={"workflow": tampered})
    assert refused.status_code == 422
    assert client.post("/api/workflows/import", json={"workflow": {"hello": 1}}).status_code == 400


# ---------------------------------------------------------------- runs
def test_a_run_streams_its_events_and_stores_inputs_outputs_errors_and_timings(env):
    client, state, scripts = env
    pid = new_project(client)
    wid = save(client, approval(), pid)["id"]
    scripts["spike-local"]._script = [text("APROBADO: los gatos duermen")]
    rid = start(client, wid, pid, {"topic": "gatos grandes"})
    run = wait(client, wid, rid, pid)
    assert run["status"] == "completed" and run["inputs"] == {"topic": "gatos grandes"}
    assert scripts["spike-local"].requests[0].messages[-1].content == "Escribe sobre gatos grandes"
    nodes = run["nodes"]
    assert [nodes[n]["status"] for n in ("topic", "write", "check", "yes", "no")] == ["ok", "ok", "ok", "ok", "skipped"]
    assert nodes["check"]["branch"] == "true" and nodes["no"]["skip"] == "branch"
    assert nodes["yes"]["artifact"] == {"title": "Resultado", "format": "text", "content": "APROBADO: los gatos duermen"}
    assert all(isinstance(nodes[n]["elapsed_s"], float) for n in ("topic", "write", "check", "yes"))
    assert run["elapsed_s"] >= nodes["write"]["elapsed_s"] and run["workflow_revision"] == 1
    streamed = client.get(f"/api/workflows/{wid}/runs/{rid}/events", params={"project_id": pid})
    events = events_of(streamed)
    assert events[0]["type"] == "run_start" and events[-1] == {**events[-1], "type": "run_end", "status": "completed"}
    assert [e["node"] for e in events if e["type"] == "node_start"] == ["topic", "write", "check", "yes"]
    assert "".join(e["text"] for e in events if e["type"] == "delta" and e["node"] == "write") == "APROBADO: los gatos duermen"
    later = events_of(client.get(f"/api/workflows/{wid}/runs/{rid}/events", params={"project_id": pid, "after": 3}))
    assert later == events[3:]
    stored = json.loads((state.project_files.folder(pid) / "workflows" / wid / "runs" / f"{rid}.json").read_text(encoding="utf-8"))
    assert stored["status"] == "completed" and stored["nodes"]["yes"]["artifact"]["content"] == "APROBADO: los gatos duermen"
    listed = client.get(f"/api/workflows/{wid}/runs", params={"project_id": pid}).json()
    assert [r["id"] for r in listed] == [rid] and listed[0]["nodes"]["no"] == "skipped"
    scripts["spike-local"]._script = [text("Falta revisar")]  # the other branch, in a second run
    run2 = wait(client, wid, start(client, wid, pid), pid)
    assert run2["nodes"]["check"]["branch"] == "false" and run2["nodes"]["no"]["artifact"]["title"] == "Rechazado"
    assert [r["id"] for r in client.get(f"/api/workflows/{wid}/runs", params={"project_id": pid}).json()][0] == run2["id"]


def test_saving_a_file_asks_through_the_permission_endpoint_and_a_denial_writes_nothing(env):
    client, state, _ = env
    pid = new_project(client)
    wid = save(client, saving(), pid)["id"]
    rid = start(client, wid, pid, {"who": "Luis"})
    question = pending_permission(state)
    assert question.tool == "write_file" and question.arguments == {"path": "salida/Luis.txt", "content": "Hola Luis"}
    live = client.get(f"/api/workflows/{wid}/runs/{rid}", params={"project_id": pid}).json()
    assert live["live"] is True and live["nodes"]["file"]["status"] == "running"
    assert client.post(f"/api/permissions/{question.id}", json={"decision": "deny"}).json() == {"ok": True}
    run = wait(client, wid, rid, pid)
    assert run["status"] == "failed" and run["nodes"]["file"]["status"] == "denied"
    assert not (state.project_files.folder(pid) / "salida").exists()
    rid = start(client, wid, pid, {"who": "Luis"})
    client.post(f"/api/permissions/{pending_permission(state).id}", json={"decision": "allow_once"})
    run = wait(client, wid, rid, pid)
    assert run["status"] == "completed" and run["nodes"]["file"]["file"] == "salida/Luis.txt"
    assert (state.project_files.folder(pid) / "salida" / "Luis.txt").read_text(encoding="utf-8") == "Hola Luis"
    assert any(e["type"] == "permission_resolved" and e["node"] == "file"
               for e in events_of(client.get(f"/api/workflows/{wid}/runs/{rid}/events", params={"project_id": pid})))


def test_the_stop_button_cancels_a_running_model_step_and_the_record_says_so(env):
    client, state, scripts = env
    hanging = hang(scripts["spike-local"])
    pid = new_project(client)
    wid = save(client, approval(), pid)["id"]
    rid = start(client, wid, pid)
    for _ in range(500):
        if hanging.requests:
            break
        time.sleep(0.02)
    stopped = client.post(f"/api/workflows/{wid}/runs/{rid}/stop", params={"project_id": pid})
    assert stopped.status_code == 200 and stopped.json() == {"ok": True, "status": "cancelled"}
    run = wait(client, wid, rid, pid)
    assert run["status"] == "cancelled" and run["live"] is False
    assert [run["nodes"][n]["status"] for n in ("topic", "write", "check", "yes", "no")] == [
        "ok", "cancelled", "skipped", "skipped", "skipped"]
    assert json.loads((state.project_files.folder(pid) / "workflows" / wid / "runs" / f"{rid}.json").read_text(
        encoding="utf-8"))["status"] == "cancelled"
    assert client.post(f"/api/workflows/{wid}/runs/{rid}/stop", params={"project_id": pid}).status_code == 404
    assert client.post(f"/api/workflows/{wid}/runs/nope/stop", params={"project_id": pid}).status_code == 404


def test_stopping_while_a_permission_question_is_open_withdraws_it(env):
    client, state, _ = env
    pid = new_project(client)
    wid = save(client, saving(), pid)["id"]
    rid = start(client, wid, pid)
    pending_permission(state)
    assert client.post(f"/api/workflows/{wid}/runs/{rid}/stop", params={"project_id": pid}).json()["status"] == "cancelled"
    assert state.broker.pending == {}
    assert not (state.project_files.folder(pid) / "salida").exists()


def test_inputs_are_checked_before_anything_starts(env):
    client, state, scripts = env
    pid = new_project(client)
    d = doc([node("n", "input", name="n", kind="number"), node("f", "input", name="f", kind="file", default="gone.txt"),
             node("a", "specialist", prompt="{{n}} {{f}}")], [edge("n", "a")])
    wid = save(client, d, pid)["id"]
    bad = client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid}, json={"inputs": {"n": "abc"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "invalid_inputs"
    assert {(p["code"], p["node"]) for p in bad.json()["detail"]["problems"]} == {("input_number", "n"), ("input_file", "f")}
    (state.project_files.folder(pid) / "gone.txt").write_text("here", encoding="utf-8")
    scripts["spike-local"]._script = [text("hecho")]
    assert wait(client, wid, start(client, wid, pid, {"n": "4,5"}), pid)["inputs"] == {"n": "4.5", "f": "gone.txt"}
    outside = client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid}, json={"inputs": {"n": "1", "f": "../x"}})
    assert outside.status_code == 422
    assert client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid},
                       json={"inputs": {"n": "1"}, "provider_id": "ghost"}).status_code == 400


def test_a_workflow_that_uses_tools_does_not_run_while_tools_are_off_and_stale_tools_are_caught(env):
    client, state, _ = env
    pid = new_project(client)
    wid = save(client, saving(), pid)["id"]
    client.put("/api/settings", json={"tools_enabled": False})
    r = client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid}, json={})
    assert r.status_code == 400 and r.json()["detail"] == "tools_disabled"
    client.put("/api/settings", json={"tools_enabled": True})
    folder = state.project_files.folder(pid)  # a workflow saved by hand with a tool this computer lacks is refused
    raw = json.loads((folder / "workflows" / wid / "0001.json").read_text(encoding="utf-8"))
    raw["nodes"].append({"id": "x", "type": "tool", "name": "x", "tool": "gone", "arguments": {}})
    (folder / "workflows" / wid / "0002.json").write_text(json.dumps(raw), encoding="utf-8")
    assert WorkflowStore(folder).get(wid)["revision"] == 2
    r = client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid}, json={})
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["code"] == "tool_unknown"
    assert client.post(f"/api/workflows/{wid}/runs", params={"project_id": pid}, json={"revision": 1}).status_code == 200


def test_a_run_that_was_in_progress_when_the_app_stopped_is_shown_as_interrupted(env):
    client, state, _ = env
    pid = new_project(client)
    wid = save(client, approval(), pid)["id"]
    WorkflowStore(state.project_files.folder(pid)).save_run(wid, {"id": "1700000000000-abcdef", "status": "running",
                                                                  "started": 1.0, "nodes": {}})
    assert client.get(f"/api/workflows/{wid}/runs", params={"project_id": pid}).json()[0]["status"] == "interrupted"
    assert client.get(f"/api/workflows/{wid}/runs/1700000000000-abcdef", params={"project_id": pid}).json()["status"] == "interrupted"
    assert client.get(f"/api/workflows/{wid}/runs/1700000000000-abcdef/events", params={"project_id": pid}).status_code == 404


def test_a_file_input_passes_a_path_and_the_contents_stay_private_from_a_provider_that_may_not_receive_files(env):
    client, state, scripts = env
    secret = "ZX-ALBATROS-9931"
    pid = new_project(client)
    client.put(f"/api/projects/{pid}/files/notas.txt", content=f"El código es {secret}.".encode())
    d = doc([node("doc", "input", name="doc", kind="file"),
             node("read", "tool", name="text", tool="read_file", arguments={"path": "{{doc}}"}),
             node("sum", "specialist", name="sum", prompt="Resume: {{input}}")], [edge("doc", "read"), edge("read", "sum")])
    wid = save(client, d, pid)["id"]
    assert client.post("/api/providers", json={"preset": "openai", "api_key": "sk-test", "model": "gpt-test",
                                               "allow_paid": True}).status_code == 200
    scripts["openai"]._script = [text("Un resumen sin detalles")]
    rid = start(client, wid, pid, {"doc": "notas.txt"}, provider_id="openai")
    run = wait(client, wid, rid, pid)
    assert run["status"] == "completed" and run["inputs"] == {"doc": "notas.txt"}  # the path, not the contents
    sent = " ".join(m.content for r in scripts["openai"].requests for m in r.messages)
    assert secret not in sent and "withheld" in sent  # the remote provider never got the file's text
    assert secret in run["nodes"]["read"]["output"] and run["nodes"]["read"]["private"] is True
    assert run["nodes"]["sum"]["private"] is False
    client.patch("/api/providers/openai", json={"share_files": True})  # the user allows it for this provider
    scripts["openai"]._script = [text(f"Contiene {secret}")]
    run = wait(client, wid, start(client, wid, pid, {"doc": "notas.txt"}, provider_id="openai"), pid)
    assert secret in scripts["openai"].requests[-1].messages[-1].content and run["nodes"]["sum"]["private"] is True
