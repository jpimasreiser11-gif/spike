"""The OpenAI-compatible API (/v1), exercised with the official `openai` Python client over real HTTP."""

import json
import socket
import threading
import time

import httpx
import openai
import pytest
import uvicorn
from fastapi.testclient import TestClient

from spike.core.types import StreamEvent
from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider, call, text


def usage(prompt: int, completion: int) -> StreamEvent:
    return StreamEvent(kind="usage", usage={"prompt_tokens": prompt, "completion_tokens": completion})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    monkeypatch.delenv("SPIKE_API_TOKEN", raising=False)
    local = ScriptedProvider([], name="spike-local")

    def factory(cfg):
        local.config = cfg
        return local

    state = AppState(home=tmp_path, provider_factory=factory)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(state), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    client = openai.OpenAI(base_url=f"http://127.0.0.1:{port}/v1", api_key="unused", max_retries=0)
    yield client, state, local, port
    server.should_exit = True
    thread.join(timeout=5)


def test_models_lists_auto_every_specialist_and_provider_models(api):
    client, state, _, _ = api
    ids = [m.id for m in client.models.list()]
    assert ids[0] == "spike-auto"
    assert {f"spike-{s}" for s in state.catalog.specialists} <= set(ids)
    local = state.provider_config("spike-local")
    assert f"spike-local/{local['model']}" in ids


def test_completion_runs_the_orchestrator_with_the_client_system_prompt(api):
    client, _, local, _ = api
    local._script = [text("Hola ", "joan") + [usage(11, 2)]]
    r = client.chat.completions.create(model="spike-auto", messages=[
        {"role": "system", "content": "Reply briefly."},
        {"role": "user", "content": "Hola, ¿quién eres?"},
    ])
    assert r.object == "chat.completion" and r.model == "spike-auto"
    assert r.choices[0].message.content == "Hola joan" and r.choices[0].finish_reason == "stop"
    assert (r.usage.prompt_tokens, r.usage.completion_tokens, r.usage.total_tokens) == (11, 2, 13)
    assert r.model_extra["spike"]["specialists"] == ["core"]
    system = local.requests[-1].messages[0]
    assert system.role == "system" and "Spike Core" in system.content
    assert "# Instructions from the application calling SPIKE\nReply briefly." in system.content


def test_fixed_specialist_streams_in_openai_chunks(api):
    client, _, local, _ = api
    local._script = [text("EBITDA ", "is ", "earnings.") + [usage(20, 3)]]
    stream = client.chat.completions.create(model="spike-finance", stream=True, stream_options={"include_usage": True},
                                            messages=[{"role": "user", "content": "What is EBITDA?"}])
    chunks = list(stream)
    content = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert content == "EBITDA is earnings."
    assert [c.choices[0].finish_reason for c in chunks if c.choices][-1] == "stop"
    assert chunks[-1].choices == [] and chunks[-1].usage.total_tokens == 23
    assert "Spike Finance" in local.requests[-1].messages[0].content


def test_history_reaches_the_model_in_order(api):
    client, _, local, _ = api
    local._script = [text("ok")]
    client.chat.completions.create(model="spike-core", messages=[
        {"role": "user", "content": [{"type": "text", "text": "first"}]},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ])
    req = local.requests[-1]
    assert [(m.role, m.content) for m in req.messages[1:]] == [("user", "first"), ("assistant", "answer"), ("user", "second")]


WEATHER = {"type": "function", "function": {"name": "get_weather", "description": "Weather for a city",
                                            "parameters": {"type": "object", "properties": {"city": {"type": "string"}},
                                                           "required": ["city"]}}}


def test_client_tools_come_back_as_tool_calls_and_results_go_to_the_model(api):
    client, state, local, _ = api
    local._script = [call("get_weather", {"city": "Madrid"}, call_id="call_1"), text("Sunny in Madrid.")]
    first = client.chat.completions.create(model="spike-auto", tools=[WEATHER],
                                           messages=[{"role": "user", "content": "Weather in Madrid?"}])
    msg = first.choices[0].message
    assert first.choices[0].finish_reason == "tool_calls" and msg.content is None
    assert msg.tool_calls[0].id == "call_1" and msg.tool_calls[0].function.name == "get_weather"
    assert json.loads(msg.tool_calls[0].function.arguments) == {"city": "Madrid"}
    sent = local.requests[-1]
    assert [t.name for t in sent.tools] == ["get_weather"]  # the client's tools only, never SPIKE's own
    assert not state.broker.pending

    second = client.chat.completions.create(model="spike-auto", tools=[WEATHER], messages=[
        {"role": "user", "content": "Weather in Madrid?"},
        {"role": "assistant", "content": None, "tool_calls": [m.model_dump() for m in msg.tool_calls]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"sky": "sunny"}'},
    ])
    assert second.choices[0].message.content == "Sunny in Madrid."
    tool_msg = local.requests[-1].messages[-1]
    assert (tool_msg.role, tool_msg.tool_call_id, tool_msg.name, tool_msg.content) == ("tool", "call_1", "get_weather",
                                                                                       '{"sky": "sunny"}')
    assistant = local.requests[-1].messages[-2]
    assert assistant.tool_calls[0].arguments == {"city": "Madrid"}


def test_streamed_tool_call(api):
    client, _, local, _ = api
    local._script = [call("get_weather", {"city": "Lima"}, call_id="call_9")]
    chunks = list(client.chat.completions.create(model="spike-auto", tools=[WEATHER], stream=True,
                                                 messages=[{"role": "user", "content": "Weather in Lima?"}]))
    deltas = [tc for c in chunks if c.choices for tc in (c.choices[0].delta.tool_calls or [])]
    assert deltas[0].id == "call_9" and deltas[0].function.name == "get_weather"
    assert json.loads("".join(d.function.arguments or "" for d in deltas)) == {"city": "Lima"}
    assert chunks[-1].choices[0].finish_reason == "tool_calls"


def test_spike_tools_that_need_approval_are_refused_without_blocking(api):
    client, state, local, _ = api
    local._script = [call("write_file", {"path": "notes.md", "content": "x"}), text("I could not write it.")]
    r = client.chat.completions.create(model="spike-code", messages=[{"role": "user", "content": "Write notes.md"}])
    assert r.choices[0].message.content == "I could not write it."
    tool_result = local.requests[-1].messages[-1]
    assert tool_result.role == "tool" and "approval" in tool_result.content
    assert not state.broker.pending and not (state.tools.get("write_file") and (state.home / "ws" / "notes.md").exists())


def test_provider_passthrough_sends_the_messages_unchanged(api):
    client, state, local, _ = api
    local._script = [text("raw")]
    model = f"spike-local/{state.provider_config('spike-local')['model']}"
    r = client.chat.completions.create(model=model, messages=[{"role": "system", "content": "S"},
                                                              {"role": "user", "content": "U"}])
    assert r.choices[0].message.content == "raw"
    assert [(m.role, m.content) for m in local.requests[-1].messages] == [("system", "S"), ("user", "U")]


def test_unknown_model_and_unsupported_input_are_clear_errors(api):
    client, _, _, _ = api
    with pytest.raises(openai.NotFoundError, match="unknown model"):
        client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(openai.BadRequestError, match="image"):
        client.chat.completions.create(model="spike-auto", messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}])
    with pytest.raises(openai.BadRequestError, match="n > 1"):
        client.chat.completions.create(model="spike-auto", n=2, messages=[{"role": "user", "content": "hi"}])


def test_api_token_is_required_once_configured(api, monkeypatch):
    _, _, local, port = api
    monkeypatch.setenv("SPIKE_API_TOKEN", "s3cret-token")
    base = f"http://127.0.0.1:{port}/v1"
    with pytest.raises(openai.AuthenticationError):
        openai.OpenAI(base_url=base, api_key="wrong", max_retries=0).models.list()
    local._script = [text("ok")]
    ok = openai.OpenAI(base_url=base, api_key="s3cret-token", max_retries=0)
    assert ok.chat.completions.create(model="spike-auto", messages=[{"role": "user", "content": "hi"}]).choices
    assert httpx.get(f"{base}/models").status_code == 401


def test_remote_clients_need_a_token(tmp_path, monkeypatch):
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    monkeypatch.delenv("SPIKE_API_TOKEN", raising=False)
    state = AppState(home=tmp_path, provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    client = TestClient(create_app(state))  # TestClient's peer address is not a loopback address
    r = client.get("/v1/models")
    assert r.status_code == 403 and "SPIKE_API_TOKEN" in r.json()["error"]["message"]


def test_foreign_host_headers_are_rejected(tmp_path, monkeypatch):
    """DNS rebinding: a web page that resolves its own name to 127.0.0.1 must not reach the API."""
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    state = AppState(home=tmp_path, provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    client = TestClient(create_app(state, allowed_hosts={"127.0.0.1", "localhost"}), base_url="http://127.0.0.1:8740")
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health", headers={"host": "evil.example:8740"}).status_code == 403
    assert client.get("/v1/models", headers={"host": "evil.example"}).status_code == 403


def test_other_sites_cannot_call_spike_from_the_browser(api, tmp_path, monkeypatch):
    """A page on another site can send requests to 127.0.0.1 from the user's browser; the Origin header gives it away."""
    _, _, _, port = api
    r = httpx.post(f"http://127.0.0.1:{port}/v1/chat/completions", headers={"origin": "https://evil.example"},
                   content=json.dumps({"model": "spike-auto", "messages": [{"role": "user", "content": "hi"}]}))
    assert r.status_code == 403 and "SPIKE_API_TOKEN" in r.json()["error"]["message"]
    state = AppState(home=tmp_path / "other", provider_factory=lambda cfg: ScriptedProvider([], name=cfg.id))
    client = TestClient(create_app(state, allowed_hosts={"127.0.0.1"}), base_url="http://127.0.0.1:8740")
    assert client.post("/api/conversations", headers={"origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/conversations", headers={"origin": "http://127.0.0.1:8740"}).status_code == 200


def test_upstream_errors_keep_the_openai_shape(api):
    client, _, local, _ = api
    local._script = [[StreamEvent(kind="error", text="Provider X may bill your account.")]]
    with pytest.raises(openai.APIStatusError, match="may bill your account") as info:
        client.chat.completions.create(model="spike-core", messages=[{"role": "user", "content": "hi"}])
    assert info.value.status_code == 502
    local._script = [[StreamEvent(kind="error", text="Provider X may bill your account.")]]
    with pytest.raises(openai.APIError, match="may bill your account"):
        list(client.chat.completions.create(model="spike-core", stream=True,
                                            messages=[{"role": "user", "content": "hi"}]))


@pytest.mark.parametrize("host, allowed", [("127.0.0.1", True), ("0.0.0.0", None)])
def test_spike_serve_checks_host_names_unless_bound_to_every_interface(host, allowed, tmp_path, monkeypatch):
    import argparse

    from spike import cli

    monkeypatch.setenv("SPIKE_HOME", str(tmp_path))
    monkeypatch.setenv("SPIKE_NO_KEYRING", "1")
    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: seen.update(app=app, **kw))
    cli.cmd_serve(argparse.Namespace(host=host, port=8740, start_local=False, open=False))
    client = TestClient(seen["app"], base_url=f"http://{host}:8740")
    assert client.get("/api/health").status_code == 200
    assert (client.get("/api/health", headers={"host": "evil.example"}).status_code == 200) is (allowed is None)


def test_a_cut_answer_reports_length(api):
    client, _, local, _ = api
    local._script = [[StreamEvent(kind="text", text="Half an ans"), StreamEvent(kind="done", finish_reason="length")]]
    r = client.chat.completions.create(model="spike-auto", max_tokens=4, messages=[{"role": "user", "content": "hi"}])
    assert r.choices[0].finish_reason == "length"
    assert local.requests[-1].max_tokens == 4


TOTAL = {"type": "json_schema", "json_schema": {"name": "total", "schema": {
    "type": "object", "properties": {"total": {"type": "integer"}}, "required": ["total"]}}}


def test_answer_contract_returns_bare_json_that_follows_the_schema(api):
    client, _, local, _ = api
    local._script = [text('```json\n{"total": 3}\n```')]
    r = client.chat.completions.create(model="spike-finance", response_format=TOTAL,
                                       messages=[{"role": "user", "content": "Suma 1 y 2"}])
    assert r.choices[0].message.content == '{"total": 3}'
    assert r.model_extra["spike"]["contract"] == {"valid": True, "attempts": 1}
    assert local.requests[-1].json_schema == TOTAL["json_schema"]["schema"] and local.requests[-1].tools == []


def test_answer_contract_asks_again_with_the_errors(api):
    client, _, local, _ = api
    local._script = [text('{"total": "tres"}'), text('{"total": 3}')]
    r = client.chat.completions.create(model="spike-finance", response_format=TOTAL,
                                       messages=[{"role": "user", "content": "Suma 1 y 2"}])
    assert r.choices[0].message.content == '{"total": 3}'
    assert r.model_extra["spike"]["contract"] == {"valid": True, "attempts": 2}
    repair = local.requests[-1].messages[-1]
    assert repair.role == "user" and "total: 'tres' is not of type 'integer'" in repair.content
    assert local.requests[-1].messages[-2].content == '{"total": "tres"}'


def test_answer_contract_reports_an_answer_that_still_breaks_it(api):
    client, _, local, _ = api
    local._script = [text("tres"), text("{}")]
    stream = client.chat.completions.create(model="spike-finance", response_format=TOTAL, stream=True,
                                            messages=[{"role": "user", "content": "Suma 1 y 2"}])
    chunks = list(stream)
    assert "".join(c.choices[0].delta.content or "" for c in chunks if c.choices) == "{}"
    contract = chunks[-1].model_extra["spike"]["contract"]
    assert contract["valid"] is False and contract["attempts"] == 2
    assert contract["errors"] == ["(root): 'total' is a required property"]


def test_an_invalid_schema_is_refused(api):
    client, _, _, _ = api
    bad = {"type": "json_schema", "json_schema": {"name": "x", "schema": {"type": "objekt"}}}
    with pytest.raises(openai.BadRequestError, match="invalid JSON Schema"):
        client.chat.completions.create(model="spike-finance", response_format=bad,
                                       messages=[{"role": "user", "content": "x"}])
