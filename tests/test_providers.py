import json

import httpx
import pytest

from spike.core.types import ChatRequest, Message, ToolSpec
from spike.providers.anthropic import AnthropicProvider, to_anthropic
from spike.providers.base import ProviderConfig
from spike.providers.llamacpp import LlamaCppProvider
from spike.providers.openai_compat import OpenAICompatProvider
from spike.providers.tool_emulation import StreamingToolFilter, parse_tool_calls


def sse(*objs) -> bytes:
    lines = []
    for o in objs:
        lines.append("data: " + (o if isinstance(o, str) else json.dumps(o)) + "\n\n")
    return "".join(lines).encode()


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def oa_config(**kw) -> ProviderConfig:
    return ProviderConfig(id="t", kind="openai", name="Test", base_url="http://x/v1", model="m", **kw)


WEATHER = ToolSpec(name="weather", description="get weather", parameters={"type": "object", "properties": {}})


async def collect(provider, request):
    return [e async for e in provider.stream(request)]


# ---------------------------------------------------------------- tool emulation
def test_parse_tool_calls_valid_and_malformed():
    out = 'Let me check.<tool_call>{"name": "weather", "arguments": {"city": "Madrid"}}</tool_call>' \
          '<tool_call>{not json}</tool_call>'
    visible, calls, malformed = parse_tool_calls(out)
    assert [c.name for c in calls] == ["weather"]
    assert calls[0].arguments == {"city": "Madrid"}
    assert malformed == ["<tool_call>{not json}</tool_call>"]
    assert visible.startswith("Let me check.")


def test_streaming_filter_hides_split_tags():
    f = StreamingToolFilter()
    chunks = ["Hi <to", "ol_call>{\"name\":\"a\",", "\"arguments\":{}}</tool", "_call> bye"]
    visible = "".join(f.feed(c) for c in chunks) + f.flush()
    assert visible == "Hi  bye"
    assert "<tool_call>" in f.raw


def test_streaming_filter_returns_unclosed_block():
    f = StreamingToolFilter()
    visible = f.feed("answer <tool_call>{\"name\":") + f.flush()
    assert visible == 'answer <tool_call>{"name":'


# ---------------------------------------------------------------- OpenAI compatible
async def test_openai_streams_text_and_native_tool_calls():
    seen = {}

    def handler(request: httpx.Request):
        seen["body"] = json.loads(request.content)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=sse(
            {"choices": [{"delta": {"content": "Hel"}}]},
            {"choices": [{"delta": {"content": "lo"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c9", "function": {"name": "weather", "arguments": "{\"ci"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "ty\": \"Paris\"}"}}]}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}},
            "[DONE]",
        ), headers={"content-type": "text/event-stream"})

    p = OpenAICompatProvider(oa_config(api_key="sk-test"), client=client_for(handler))
    events = await collect(p, ChatRequest(messages=[Message(role="user", content="hi")], tools=[WEATHER]))
    assert "".join(e.text for e in events if e.kind == "text") == "Hello"
    tc = [e.tool_call for e in events if e.kind == "tool_call"]
    assert tc[0].id == "c9" and tc[0].arguments == {"city": "Paris"}
    assert any(e.kind == "usage" for e in events)
    assert events[-1].kind == "done" and events[-1].finish_reason == "tool_calls"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["body"]["tools"][0]["function"]["name"] == "weather"
    assert seen["body"]["stream"] is True


async def test_openai_emulated_tools_when_not_native():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=sse(
            {"choices": [{"delta": {"content": "Checking <tool_"}}]},
            {"choices": [{"delta": {"content": "call>{\"name\": \"weather\", \"arguments\": {}}</tool_call>"}}]},
            "[DONE]",
        ))

    p = OpenAICompatProvider(oa_config(capabilities={"native_tools": False}), client=client_for(handler))
    events = await collect(p, ChatRequest(messages=[Message(role="user", content="hi")], tools=[WEATHER]))
    assert "tools" not in seen["body"]
    assert "<tools>" in seen["body"]["messages"][0]["content"]
    assert "".join(e.text for e in events if e.kind == "text").strip() == "Checking"
    assert [e.tool_call.name for e in events if e.kind == "tool_call"] == ["weather"]


async def test_paid_provider_blocked_without_authorization():
    def handler(request):  # must never be called
        raise AssertionError("network call made for unauthorized paid provider")

    p = OpenAICompatProvider(oa_config(paid=True, allow_paid=False), client=client_for(handler))
    events = await collect(p, ChatRequest(messages=[Message(role="user", content="hi")]))
    assert events[0].kind == "error" and "Allow paid requests" in events[0].text


async def test_auth_error_is_readable():
    p = OpenAICompatProvider(oa_config(), client=client_for(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})))
    events = await collect(p, ChatRequest(messages=[Message(role="user", content="hi")]))
    assert events[0].kind == "error" and "authentication failed" in events[0].text


async def test_connection_error_is_reported():
    def handler(request):
        raise httpx.ConnectError("refused")

    p = OpenAICompatProvider(oa_config(), client=client_for(handler))
    events = await collect(p, ChatRequest(messages=[Message(role="user", content="hi")]))
    assert events[0].kind == "error" and "connection failed" in events[0].text


# ---------------------------------------------------------------- llama.cpp adapters
async def test_llamacpp_selects_adapter_per_request():
    bodies = []

    def handler(request: httpx.Request):
        if request.url.path == "/lora-adapters":
            return httpx.Response(200, json=[{"id": 0, "path": "/m/spike-finance.gguf", "scale": 0.0},
                                             {"id": 1, "path": "/m/spike-medicine.gguf", "scale": 0.0}])
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=sse({"choices": [{"delta": {"content": "ok"}}]}, "[DONE]"))

    cfg = ProviderConfig(id="l", kind="llamacpp", name="Local", base_url="http://127.0.0.1:8737/v1", local=True)
    p = LlamaCppProvider(cfg, client=client_for(handler))
    await collect(p, ChatRequest(messages=[Message(role="user", content="q")], adapter="spike-medicine", reasoning=False))
    await collect(p, ChatRequest(messages=[Message(role="user", content="q")]))
    # explicit scale for every loaded adapter: llama-server treats `[]` as "use global scales", not "base"
    assert bodies[0]["lora"] == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 1.0}]
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert bodies[1]["lora"] == [{"id": 0, "scale": 0.0}, {"id": 1, "scale": 0.0}]  # base model only

    events = await collect(p, ChatRequest(messages=[Message(role="user", content="q")], adapter="spike-law"))
    assert events[0].kind == "error" and "not loaded" in events[0].text


# ---------------------------------------------------------------- Anthropic
def test_to_anthropic_merges_tool_results():
    from spike.core.types import ToolCall

    system, msgs = to_anthropic([
        Message(role="system", content="S"),
        Message(role="user", content="hi"),
        Message(role="assistant", content="", tool_calls=[ToolCall(id="t1", name="weather", arguments={"a": 1})]),
        Message(role="tool", content="sunny", tool_call_id="t1", name="weather"),
    ])
    assert system == "S"
    assert msgs[1]["content"][0] == {"type": "tool_use", "id": "t1", "name": "weather", "input": {"a": 1}}
    assert msgs[2]["role"] == "user" and msgs[2]["content"][0]["type"] == "tool_result"


async def test_anthropic_stream_text_thinking_and_tool():
    events_raw = [
        ("message_start", {"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}}),
        ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Hi"}}),
        ("content_block_start", {"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "tu1", "name": "weather"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{\"city\":"}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "\"Rome\"}"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 2}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events_raw).encode()
    seen = {}

    def handler(request):
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=body)

    cfg = ProviderConfig(id="a", kind="anthropic", name="Anthropic", base_url="https://api.anthropic.com/v1",
                         model="claude-x", api_key="k", paid=True, allow_paid=True)
    p = AnthropicProvider(cfg, client=client_for(handler))
    events = await collect(p, ChatRequest(messages=[Message(role="system", content="S"), Message(role="user", content="hi")], tools=[WEATHER]))
    assert [e.text for e in events if e.kind == "reasoning"] == ["hmm"]
    assert "".join(e.text for e in events if e.kind == "text") == "Hi"
    assert [e.tool_call.arguments for e in events if e.kind == "tool_call"] == [{"city": "Rome"}]
    assert events[-1].finish_reason == "tool_calls"
    # message_delta carries the cumulative output count: one merged usage event, not 1 + 9
    assert [e.usage for e in events if e.kind == "usage"] == [{"input_tokens": 3, "output_tokens": 9}]
    assert seen["headers"]["x-api-key"] == "k"
    assert seen["body"]["system"] == "S" and seen["body"]["tools"][0]["input_schema"]


@pytest.mark.parametrize("preset_id", ["openai", "anthropic", "deepseek", "gemini", "openrouter", "groq"])
def test_remote_presets_are_marked_paid(preset_id):
    from spike.providers.registry import PRESETS_BY_ID

    assert PRESETS_BY_ID[preset_id].paid is True
