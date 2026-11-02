"""Research API: explicit preview/one-use analysis, paid/file guards and Forge handoff, fully offline."""

import json

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, text
from tests.test_research import evidence, pair, pdf_bytes


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    scripts = {}

    def factory(cfg):
        p = scripts.setdefault(cfg.id, ScriptedProvider([], name=cfg.id))
        p.config = cfg
        return p

    state = AppState(home=tmp_path, provider_factory=factory)
    with TestClient(create_app(state)) as client:
        client.get("/api/providers")
        ws = tmp_path / "ws"
        ws.mkdir(exist_ok=True)
        (ws / "a.txt").write_text("The result is positive.", encoding="utf-8")
        (ws / "b.txt").write_text("The result is negative.", encoding="utf-8")
        (ws / "paper.pdf").write_bytes(pdf_bytes())
        yield client, state, scripts, ws


def preview(client, **extra):
    return client.post("/api/research/preview", json={"kind": "contradictions", "paths": ["a.txt", "b.txt"],
                                                    "provider_id": "spike-local", **extra})


def execute(client, quote):
    return client.post("/api/research/analyze", json={"preview_id": quote["id"]})


def test_preview_sends_nothing_then_one_click_makes_one_guarded_call(env):
    client, state, scripts, _ = env
    quote = preview(client).json()
    local = scripts["spike-local"]
    assert quote["sources"][0]["pages"] == ["The result is positive."]
    assert quote["calls"] == 1 and quote["blocked"] is None and local.requests == []
    local._script = [text(json.dumps({"pairs": [pair()]}))]
    result = execute(client, quote)
    assert result.status_code == 200, result.text
    assert result.json()["analysis"]["status"] == "candidates"
    assert result.json()["analysis"]["pairs"][0]["left"]["quote"] == "The result is positive."
    assert len(local.requests) == 1
    assert local.requests[0].messages[-1].private == [local.requests[0].messages[-1].content]
    assert execute(client, quote).status_code == 409
    assert len(local.requests) == 1
    assert not state.store.list_conversations()  # no chat or implicit execution


def test_changed_sources_are_rejected_before_request(env):
    client, _, scripts, ws = env
    quote = preview(client).json()
    (ws / "a.txt").write_text("Changed", encoding="utf-8")
    assert execute(client, quote).status_code == 409
    assert not scripts["spike-local"].requests


@pytest.mark.parametrize("sharing,paid", [(False, True), (True, False), (False, False)])
def test_external_privacy_and_paid_guards_apply_before_any_call(env, sharing, paid):
    client, _, scripts, _ = env
    assert client.post("/api/providers", json={"preset": "openai", "api_key": "test-key", "model": "test-model",
        "allow_paid": paid, "share_files": sharing}).status_code == 200
    quote = preview(client, provider_id="openai").json()
    assert quote["blocked"]
    assert execute(client, quote).status_code == 403
    assert not scripts["openai"].requests


def test_provider_changes_invalidate_preview(env):
    client, _, scripts, _ = env
    quote = preview(client).json()
    client.patch("/api/providers/spike-local", json={"model": "other"})
    assert execute(client, quote).status_code == 409
    assert not scripts["spike-local"].requests


def test_paper_extraction_goes_to_reviewable_blueprint_without_copying_private_quotes(env):
    client, _, scripts, _ = env
    quote = preview(client, kind="paper", paths=["paper.pdf"]).json()
    scripts["spike-local"]._script = [text(json.dumps({"methods": [evidence(quote="compare two seeds")],
                                                     "equations": [], "tables": []}))]
    response = execute(client, quote)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["analysis"]["status"] == "draft"
    assert result["blueprint"]["steps"] and "paper.pdf" in json.dumps(result["blueprint"])
    assert "compare two seeds" not in json.dumps(result["blueprint"])
    assert "SHA-256" in result["blueprint"]["steps"][0]["instruction"]
    from spike.forge.blueprint import from_user
    assert from_user(result["blueprint"], env[1].catalog)
    assert len(scripts["spike-local"].requests) == 1


@pytest.mark.parametrize("answer", ["not json", "[]", '{"pairs": [{}]}', '{"pairs": [{"left": null}]}'])
def test_bad_model_output_does_not_create_valid_evidence(env, answer):
    client, _, scripts, _ = env
    quote = preview(client).json()
    scripts["spike-local"]._script = [text(answer)]
    assert execute(client, quote).status_code == 422


def test_notebook_only_exports_selected_conversation_and_makes_no_calls(env):
    client, state, scripts, _ = env
    conv = state.store.create_conversation()
    other = state.store.create_conversation()
    state.store.add_message(conv["id"], "assistant", "```python\nprint('hola')\n```")
    state.store.add_message(other["id"], "user", "PRIVATE OTHER CHAT")
    response = client.get(f"/api/research/notebooks/{conv['id']}")
    assert response.status_code == 200 and "attachment" in response.headers["content-disposition"]
    assert response.json()["nbformat"] == 4
    assert "PRIVATE OTHER CHAT" not in response.text
    assert client.get("/api/research/notebooks/unknown").status_code == 404
    assert not scripts["spike-local"].requests


def test_invalid_project_counts_paths_and_project_scope(env):
    client, state, scripts, _ = env
    for extra in ({"project_id": "unknown"}, {"paths": ["a.txt"]}, {"paths": ["../a.txt", "b.txt"]},
                  {"kind": "paper", "paths": ["a.txt"]}, {"provider_id": "unknown"}):
        assert preview(client, **extra).status_code in (400, 404, 422)
    project = state.store.create_project("Research")
    assert preview(client, project_id=project["id"]).status_code == 400  # not workspace files
    assert not scripts["spike-local"].requests


def test_changes_while_provider_is_running_cannot_return_current_evidence(env):
    client, _, scripts, ws = env
    quote = preview(client).json()

    def script(request):
        (ws / "a.txt").write_text("The evidence changed mid-request.", encoding="utf-8")
        return text(json.dumps({"pairs": [pair()]}))

    scripts["spike-local"]._script = script
    response = execute(client, quote)
    assert response.status_code == 409 and response.json()["detail"] == "changed_preview"


def test_authorized_external_call_records_file_sending(env):
    client, _, scripts, _ = env
    client.post("/api/providers", json={"preset": "openai", "api_key": "test-key", "model": "test-model",
                                      "allow_paid": True, "share_files": True})
    quote = preview(client, provider_id="openai").json()
    scripts["openai"]._script = [text(json.dumps({"pairs": [pair()]}))]
    assert execute(client, quote).status_code == 200
    assert len(scripts["openai"].requests) == 1
    sent = scripts["openai"].requests[0].messages[-1].content
    assert "The result is positive." in sent
    calls = client.get("/api/calls?remote=true").json()
    assert calls[0]["files_sent"] == 1 and calls[0]["files_withheld"] == 0


def test_expired_preview_and_context_budget_do_not_call(env, monkeypatch):
    from types import SimpleNamespace

    import spike.server.research_api as module
    client, _, scripts, _ = env
    quote = preview(client).json()
    now = module.time.monotonic()
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now + 301))
    assert execute(client, quote).status_code == 409
    scripts["spike-local"].config.capabilities["max_context"] = 32
    quote = preview(client).json()
    assert quote["blocked"] == "context_limit"
    assert execute(client, quote).status_code == 403
    assert not scripts["spike-local"].requests


def test_temporary_chat_export_and_deleted_project_are_scoped(env):
    client, state, scripts, _ = env
    conv = state.temp.create_conversation()
    state.temp.add_message(conv["id"], "user", "temporary note")
    assert "temporary note" in client.get(f"/api/research/notebooks/{conv['id']}").text
    state.temp.delete_conversation(conv["id"])
    assert client.get(f"/api/research/notebooks/{conv['id']}").status_code == 404
    project = state.store.create_project("Research")
    root = state.prototype_root(project["id"])
    root.mkdir(exist_ok=True, parents=True)
    (root / "a.txt").write_text("The result is positive.", encoding="utf-8")
    (root / "b.txt").write_text("The result is negative.", encoding="utf-8")
    quote = preview(client, project_id=project["id"]).json()
    state.store.delete_project(project["id"])
    assert execute(client, quote).status_code == 404
    assert not scripts["spike-local"].requests
