"""Lab requests use an in-process fake compatible server; previews never contact a provider."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from spike.providers.openai_compat import OpenAICompatProvider
from spike.server.app import create_app
from spike.server.state import AppState


@pytest.fixture
def env(tmp_path):
    bodies = []

    def remote(request):
        body = json.loads(request.content)
        bodies.append(body)
        if body.get("stream"):
            chunks = [{"choices": [{"delta": {"content": "OK"}}]},
                      {"usage": {"prompt_tokens": 10, "completion_tokens": 2}}, "[DONE]"]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join(
                "data: " + (c if isinstance(c, str) else json.dumps(c)) + "\n\n" for c in chunks).encode())
        message = {"content": "OK"}
        if "tools" in body:
            message = {"tool_calls": [{"function": {"name": "lab_echo", "arguments": '{"value":"ok"}'}}]}
        elif "response_format" in body:
            message = {"content": '{"ok":true}'}
        elif isinstance(body["messages"][0]["content"], list):
            message = {"content": "red"}
        elif str(body["messages"][0]["content"]).startswith("LAB_START_7"):
            message = {"content": "LAB_START_7 LAB_END_9"}
        return httpx.Response(200, json={"choices": [{"message": message}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 2}})

    state = AppState(home=tmp_path, provider_factory=lambda cfg: OpenAICompatProvider(
        cfg, client=httpx.AsyncClient(transport=httpx.MockTransport(remote))))
    client = TestClient(create_app(state))
    client.post("/api/providers", json={"preset": "custom-openai", "model": "fake", "allow_paid": True,
                                        "limits": {"price_in": 2, "price_out": 4}})
    return client, state, bodies


def preview(client, **kw):
    return client.post("/api/lab/preview", json={"kind": "compare", "prompt": "hello",
                       "targets": [{"specialist": "core", "provider_id": "custom-openai"}], **kw})


def execute(client, quote):
    return client.post("/api/lab/execute", json={"quote_id": quote.json()["id"]})


def test_preview_and_history_do_not_call_provider(env):
    client, _, bodies = env
    quote = preview(client)
    assert quote.status_code == 200, quote.text
    assert quote.json()["estimated_cost"] > 0
    assert client.get("/api/lab/runs").json() == []
    assert client.post("/api/lab/execute", json={}).status_code == 422
    assert bodies == []


def test_compare_eval_save_export_and_single_use(env):
    client, state, bodies = env
    quote = preview(client, cases=[{"prompt": "one", "expected": "OK"}, {"prompt": "two", "expected": "wrong"}],
                    targets=[{"specialist": "core", "provider_id": "custom-openai"},
                             {"specialist": "writing", "provider_id": "custom-openai"}])
    run = execute(client, quote)
    assert run.status_code == 200, run.text
    data = run.json()
    assert len(data["rows"]) == len(bodies) == 4
    assert [r["score"] for r in data["rows"]] == [1, 0, 1, 0]
    assert all(r["latency_ms"] >= 0 and r["tokens_in"] == 10 and not r["estimated_tokens"] for r in data["rows"])
    assert data["rows"][0]["cost"] == pytest.approx(0.000028)
    assert bodies[0]["messages"][1] == bodies[2]["messages"][1]
    assert bodies[0]["messages"][0] != bodies[2]["messages"][0]
    assert execute(client, quote).status_code == 409
    assert client.get("/api/lab/runs").json()[0] == data
    exported = client.get(f'/api/lab/runs/{data["id"]}/export')
    assert exported.json() == data
    assert "attachment" in exported.headers["content-disposition"]
    assert state.store.get_setting("lab_runs")[0] == data


def test_probe_real_payloads_and_evidence(env):
    client, _, bodies = env
    quote = preview(client, kind="probe")
    assert bodies == []
    run = execute(client, quote)
    assert run.status_code == 200, run.text
    rows = run.json()["rows"]
    assert {r["capability"] for r in rows} == {"tools", "json", "vision", "streaming", "context"}
    assert all(r["status"] == "observed" for r in rows)
    assert len(bodies) == 5
    assert bodies[0]["tools"][0]["function"]["name"] == "lab_echo"
    assert bodies[1]["response_format"] == {"type": "json_object"}
    assert bodies[2]["messages"][0]["content"][1]["type"] == "image_url"
    assert bodies[3]["stream"] is True
    assert rows[4]["context_tokens_tested"] > 0
    assert "max_context" not in rows[4]


@pytest.mark.parametrize("patch", [{"allow_paid": False}, {"limits": {"monthly_cost": 0}}])
def test_guards_stop_probe_and_comparison(env, patch):
    client, _, bodies = env
    client.patch("/api/providers/custom-openai", json=patch)
    for kind in ("probe", "compare"):
        quote = preview(client, kind=kind)
        assert quote.json()["blocked"]
        assert execute(client, quote).status_code == 403
    assert bodies == []


def test_stale_quote_and_invalid_targets_never_call(env):
    client, _, bodies = env
    quote = preview(client)
    client.patch("/api/providers/custom-openai", json={"model": "changed"})
    assert execute(client, quote).status_code == 409
    assert preview(client, targets=[{"specialist": "missing"}]).status_code == 400
    assert preview(client, cases=[{"prompt": "x"}] * 17).status_code == 422
    assert bodies == []


def test_probe_ignores_declared_capabilities_and_rejects_plain_text(env):
    client, state, bodies = env
    client.patch("/api/providers/custom-openai", json={"capabilities": {"native_tools": False, "vision": False,
                                                                       "json_schema": False, "streaming": False}})
    provider = state.provider("custom-openai")
    def ignore_flags(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    provider.inner._client = httpx.AsyncClient(transport=httpx.MockTransport(ignore_flags))
    run = execute(client, preview(client, kind="probe")).json()
    assert [r["status"] for r in run["rows"][:4]] == ["not_observed", "failed", "not_observed", "not_observed"]
    assert run["rows"][4]["status"] == "not_observed"  # accepting a request alone is not context retention
    assert all(r["estimated_tokens"] for r in run["rows"])
    assert "tools" in bodies[0]  # native API probe, never prompt emulation


def test_missing_prices_expiration_and_error_safety(env, monkeypatch):
    import spike.server.lab_api as lab_api

    client, state, bodies = env
    client.patch("/api/providers/custom-openai", json={"limits": {}})
    quote = preview(client, kind="probe")
    assert quote.json()["estimated_cost"] is None
    monkeypatch.setattr(lab_api.time, "time", lambda: 10**12)
    assert execute(client, quote).status_code == 409
    assert bodies == []
    def failed(request):
        return httpx.Response(500, text="sk-do-not-store-secret")
    state.provider("custom-openai").inner._client = httpx.AsyncClient(transport=httpx.MockTransport(failed))
    run = execute(client, preview(client, kind="probe"))
    assert all(r["status"] == "failed" for r in run.json()["rows"])
    assert "sk-do-not-store-secret" not in run.text
    assert "sk-do-not-store-secret" not in str(state.store.get_setting("lab_runs"))


def test_guard_rechecks_between_probe_calls(env):
    client, state, bodies = env
    client.patch("/api/providers/custom-openai", json={"limits": {"monthly_tokens": 1}})
    run = execute(client, preview(client, kind="probe")).json()
    assert len(bodies) == 1
    assert run["rows"][0]["status"] == "observed"
    assert all(r["status"] == "failed" for r in run["rows"][1:])


def test_binding_models_adapter_and_unscored_prompt(env):
    client, state, bodies = env
    state.update_settings({"specialist_bindings": {"core": {"provider_id": "custom-openai", "model": "bound"}}})
    row = execute(client, preview(client, targets=[{"specialist": "core"}])).json()["rows"][0]
    assert row["model"] == "bound" and row["score"] is None and row["adapter"] is None
    assert bodies[0]["model"] == "bound"
    execute(client, preview(client, kind="probe", targets=[{"specialist": "core"}]))
    assert all(b["model"] == "bound" for b in bodies)


def test_unsupported_protocol_and_unknown_export(env):
    from tests.helpers import ScriptedProvider, text

    client, state, bodies = env
    state.provider("custom-openai").inner = ScriptedProvider(lambda _: text("OK"))
    quote = preview(client, kind="probe")
    assert quote.json()["calls"] == 0
    run = execute(client, quote).json()
    assert len(run["rows"]) == 5 and all(r["status"] == "untested" for r in run["rows"])
    assert client.get("/api/lab/runs/missing/export").status_code == 404
    assert bodies == []


def test_native_messages_probe_without_emulating_json_mode(env):
    from spike.providers.anthropic import AnthropicProvider

    client, state, bodies = env
    provider = state.provider("custom-openai")
    def remote(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert request.url.path.endswith("/messages")
        if body.get("stream"):
            chunks = [{"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
                      {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "OK"}},
                      {"type": "message_delta", "usage": {"output_tokens": 2}}, {"type": "message_stop"}]
            return httpx.Response(200, content="".join("data: " + json.dumps(c) + "\n\n" for c in chunks).encode())
        content = [{"type": "text", "text": "OK"}]
        if "tools" in body:
            content = [{"type": "tool_use", "name": "lab_echo", "input": {"value": "ok"}}]
        elif isinstance(body["messages"][0]["content"], list):
            content = [{"type": "text", "text": "red"}]
        elif str(body["messages"][0]["content"]).startswith("LAB_START_7"):
            content = [{"type": "text", "text": "LAB_START_7 LAB_END_9"}]
        return httpx.Response(200, json={"content": content, "usage": {"input_tokens": 10, "output_tokens": 2}})
    provider.inner = AnthropicProvider(provider.config, client=httpx.AsyncClient(transport=httpx.MockTransport(remote)))
    quote = preview(client, kind="probe")
    assert quote.json()["calls"] == 4 and bodies == []
    rows = execute(client, quote).json()["rows"]
    assert rows[1]["status"] == "untested"  # this protocol has no JSON mode in SPIKE; no prompt-only false positive
    assert all(r["status"] == "observed" for r in rows if r["capability"] != "json")
    assert bodies[1]["messages"][0]["content"][1]["source"]["media_type"] == "image/png"
    assert all(r["tokens_in"] == 10 and r["tokens_out"] == 2 for r in rows if r["capability"] != "json")


def test_comparison_estimates_tokens_and_keeps_only_50_runs(env):
    client, state, _ = env
    state.store.set_setting("lab_runs", [{"id": str(i)} for i in range(50)])
    def response(request):
        return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n')
    state.provider("custom-openai").inner._client = httpx.AsyncClient(transport=httpx.MockTransport(response))
    data = execute(client, preview(client)).json()
    assert data["rows"][0]["estimated_tokens"]
    assert data["rows"][0]["tokens_in"] > 0
    runs = client.get("/api/lab/runs").json()
    assert len(runs) == 50 and runs[0] == data and runs[-1]["id"] == "48"


def test_adapters_use_only_known_installed_weights(env):
    from spike.core.types import Capabilities
    from tests.helpers import ScriptedProvider, text

    client, state, _ = env
    requests = []
    def script(request):
        requests.append(request)
        return text("OK")
    provider = state.provider("custom-openai")
    provider.inner = ScriptedProvider(script)
    spec = state.catalog.specialists["writing"]
    spec.adapter = "writing-adapter"
    provider.inner.default_capabilities = lambda: Capabilities(adapters=True)
    target = [{"specialist": "writing", "provider_id": "custom-openai"}]
    execute(client, preview(client, targets=target))
    assert requests[0].adapter is None
    state.installed_adapters["custom-openai"] = {spec.adapter}
    row = execute(client, preview(client, targets=target)).json()["rows"][0]
    assert requests[1].adapter == row["adapter"] == spec.adapter


def test_request_bounds_and_persisted_history_after_restart(env):
    client, state, bodies = env
    assert preview(client, prompt="", cases=[]).status_code == 400
    assert preview(client, targets=[{"specialist": "core"}] * 3, cases=[{"prompt": "x"}] * 16).status_code == 400
    assert preview(client, kind="probe", targets=[{"specialist": "core"}] * 2).status_code == 400
    run = execute(client, preview(client)).json()
    fresh = TestClient(create_app(AppState(home=state.home)))
    assert fresh.get("/api/lab/runs").json()[0] == run
    assert len(bodies) == 1


def test_stream_error_after_text_does_not_claim_capability(env):
    client, state, _ = env
    def failed_stream(request):
        body = json.loads(request.content)
        if body.get("stream"):
            return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"OK"}}]}\n\n'
                                  b'data: {"error":{"message":"do-not-store"}}\n\n')
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    state.provider("custom-openai").inner._client = httpx.AsyncClient(transport=httpx.MockTransport(failed_stream))
    run = execute(client, preview(client, kind="probe"))
    assert run.json()["rows"][3]["status"] == "failed"
    assert "do-not-store" not in run.text
