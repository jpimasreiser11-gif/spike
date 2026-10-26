"""OpenAI-compatible API (/v1) so any OpenAI client (Aider, OpenCode, Continue, scripts) can use SPIKE.

Models: `spike-auto` (the orchestrator routes), `spike-<specialist>` (one specialist) and `<provider>/<model>`
(passthrough to a configured provider). Requests that carry the client's own tools, a response format or a tool
result run in direct mode: one model call with the specialist's prompt and the client's tools only, and tool calls
go back to the client. Everything else runs the orchestrator, whose own tools never wait for approval here:
nobody can answer an approval card through this API, so those tools are refused.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import os
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from spike.contracts import check, repair_prompt, schema_error
from spike.core.context import fit_messages
from spike.core.types import ChatRequest, Message, StreamEvent, ToolCall, ToolSpec
from spike.server.state import AppState
from spike.specialists.catalog import Specialist
from spike.tools.base import HeadlessBroker

AUTO = "spike-auto"
TOKEN_ENV = "SPIKE_API_TOKEN"

Out = tuple[str, Any]  # ("text" | "reasoning" | "tool_call" | "usage" | "finish" | "error" | "spike", value)


class ApiError(Exception):
    def __init__(self, status: int, message: str, kind: str = "invalid_request_error", param: str | None = None,
                 code: str | None = None):
        super().__init__(message)
        self.status, self.message, self.kind, self.param, self.code = status, message, kind, param, code

    def body(self) -> dict[str, Any]:
        return {"error": {"message": self.message, "type": self.kind, "param": self.param, "code": self.code}}

    def response(self) -> JSONResponse:
        return JSONResponse(self.body(), status_code=self.status)


@dataclass
class Completion:
    model: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    client_tools: bool = False
    stream: bool = False
    include_usage: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop: list[str] = field(default_factory=list)
    json_schema: dict[str, Any] | None = None


# ---------------------------------------------------------------------- access
def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_access(request: Request) -> None:
    token = os.environ.get(TOKEN_ENV, "")
    if token:
        scheme, _, given = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(given.strip().encode(), token.encode()):
            raise ApiError(401, f"invalid or missing API key: send 'Authorization: Bearer <{TOKEN_ENV}>'",
                           code="invalid_api_key")
        return
    if request.headers.get("origin"):  # a web page in the user's browser, not a local program
        raise ApiError(403, f"browser requests need an API token: start SPIKE with {TOKEN_ENV} set",
                       "permission_error")
    if not _is_loopback(request.client.host if request.client else ""):
        raise ApiError(403, f"without {TOKEN_ENV} only programs on this computer can use the API",
                       "permission_error")


# ---------------------------------------------------------------------- request parsing
def _text(content: Any, where: str) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ApiError(400, "message content must be a string or a list of parts", param=where)
    parts = []
    for part in content:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind == "text":
            parts.append(str(part.get("text") or ""))
        elif kind in ("image_url", "input_image"):
            raise ApiError(400, "image input is not supported yet", param=where)
        else:
            raise ApiError(400, f"unsupported content part type '{kind}'", param=where)
    return "\n".join(parts)


def _call_id() -> str:
    return f"call_{uuid.uuid4().hex[:24]}"


def parse_messages(raw: Any) -> list[Message]:
    if not isinstance(raw, list) or not raw:
        raise ApiError(400, "'messages' must be a non-empty list", param="messages")
    out: list[Message] = []
    names: dict[str, str] = {}  # tool_call_id -> tool name, for tool results that do not repeat it
    for i, m in enumerate(raw):
        where = f"messages[{i}]"
        role = m.get("role") if isinstance(m, dict) else None
        if role in ("system", "developer"):
            out.append(Message(role="system", content=_text(m.get("content"), where)))
        elif role == "user":
            out.append(Message(role="user", content=_text(m.get("content"), where)))
        elif role == "assistant":
            calls = []
            for tc in m.get("tool_calls") or []:
                fn = (tc or {}).get("function") or {}
                args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(args) if isinstance(args, str) else args
                except ValueError:
                    args = None
                if not isinstance(args, dict):
                    raise ApiError(400, "tool call arguments must be a JSON object", param=where)
                call = ToolCall(id=str(tc.get("id") or _call_id()), name=str(fn.get("name") or ""), arguments=args)
                names[call.id] = call.name
                calls.append(call)
            out.append(Message(role="assistant", content=_text(m.get("content"), where), tool_calls=calls))
        elif role == "tool":
            cid = str(m.get("tool_call_id") or "")
            out.append(Message(role="tool", content=_text(m.get("content"), where), tool_call_id=cid,
                               name=names.get(cid) or m.get("name")))
        else:
            raise ApiError(400, f"unsupported message role '{role}'", param=where)
    return out


def parse_tools(raw: Any) -> list[ToolSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ApiError(400, "'tools' must be a list", param="tools")
    specs = []
    for i, tool in enumerate(raw):
        fn = tool.get("function") if isinstance(tool, dict) and tool.get("type", "function") == "function" else None
        if not isinstance(fn, dict) or not fn.get("name"):
            raise ApiError(400, "only function tools are supported", param=f"tools[{i}]")
        specs.append(ToolSpec(name=str(fn["name"]), description=str(fn.get("description") or ""),
                              parameters=fn.get("parameters") or {"type": "object", "properties": {}}))
    return specs


def _number(body: dict[str, Any], key: str, kind: type) -> Any:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or (kind is int and value != int(value)):
        raise ApiError(400, f"'{key}' must be a number", param=key)
    return kind(value)


def parse_completion(body: Any) -> Completion:
    if not isinstance(body, dict):
        raise ApiError(400, "the request body must be a JSON object")
    model = body.get("model")
    if not isinstance(model, str) or not model:
        raise ApiError(400, "'model' is required", param="model")
    if body.get("n") not in (None, 1):
        raise ApiError(400, "n > 1 is not supported", param="n")
    messages = parse_messages(body.get("messages"))
    tools = parse_tools(body.get("tools"))
    client_tools = bool(tools)
    if body.get("tool_choice") == "none":
        tools = []
    fmt = body.get("response_format") or {}
    schema = None
    if fmt.get("type") == "json_object":
        schema = {"type": "object"}
    elif fmt.get("type") == "json_schema":
        schema = (fmt.get("json_schema") or {}).get("schema") or {"type": "object"}
        if (problem := schema_error(schema)) is not None:
            raise ApiError(400, problem, param="response_format")
    elif fmt.get("type") not in (None, "text"):
        raise ApiError(400, f"unsupported response_format type '{fmt.get('type')}'", param="response_format")
    stop = body.get("stop")
    stop = [stop] if isinstance(stop, str) else [str(s) for s in stop or []]
    max_tokens = _number(body, "max_completion_tokens", int) or _number(body, "max_tokens", int)
    return Completion(
        model=model, messages=messages, tools=tools, client_tools=client_tools, stream=bool(body.get("stream")),
        include_usage=bool((body.get("stream_options") or {}).get("include_usage")),
        temperature=_number(body, "temperature", float), top_p=_number(body, "top_p", float),
        max_tokens=max_tokens, stop=stop, json_schema=schema,
    )


# ---------------------------------------------------------------------- runs
async def _provider_events(events: AsyncIterator[StreamEvent]) -> AsyncIterator[Out]:
    async for ev in events:
        if ev.kind in ("text", "reasoning") and ev.text:
            yield ev.kind, ev.text
        elif ev.kind == "tool_call" and ev.tool_call:
            yield "tool_call", ev.tool_call
        elif ev.kind == "usage" and ev.usage:
            yield "usage", ev.usage
        elif ev.kind == "error":
            yield "error", ev.text
            return
        elif ev.kind == "done":
            yield "finish", ev.finish_reason


def _options(state: AppState, mode: str, app_instructions: str, req: Completion):
    opts = state.options(mode)
    return replace(opts, app_instructions=app_instructions,
                   temperature=req.temperature if req.temperature is not None else opts.temperature,
                   max_tokens=req.max_tokens or opts.max_tokens)


async def run_passthrough(state: AppState, pid: str, model: str, req: Completion,
                          extra: list[Message] | None = None) -> AsyncIterator[Out]:
    yield "spike", {"provider": pid}
    request = ChatRequest(messages=[*req.messages, *(extra or [])], model=model, temperature=req.temperature, top_p=req.top_p,
                          max_tokens=req.max_tokens, tools=req.tools, stop=req.stop, json_schema=req.json_schema)
    async for out in _provider_events(state.provider(pid).stream(request)):
        yield out


async def run_direct(state: AppState, spec: Specialist, app_instructions: str, conversation: list[Message],
                     req: Completion, extra: list[Message] | None = None) -> AsyncIterator[Out]:
    yield "spike", {"specialists": [spec.id]}
    await state.ensure_adapters()
    orchestrator = state.orchestrator()
    backend = orchestrator.resolve(spec)
    opts = _options(state, spec.id, app_instructions, req)
    messages, _ = fit_messages([orchestrator.system_message(spec, opts), *conversation, *(extra or [])],
                               backend.context_budget)
    request = ChatRequest(messages=messages, model=backend.model, adapter=backend.adapter,
                          temperature=opts.temperature, top_p=req.top_p, max_tokens=opts.max_tokens, tools=req.tools,
                          stop=req.stop, json_schema=req.json_schema, reasoning=opts.reasoning)
    async for out in _provider_events(backend.provider.stream(request)):
        yield out


async def run_orchestrated(state: AppState, mode: str, app_instructions: str, conversation: list[Message],
                           req: Completion) -> AsyncIterator[Out]:
    await state.ensure_adapters()
    await state.connectors.ensure_started()
    orchestrator = state.orchestrator(broker=HeadlessBroker(state.broker))
    opts = _options(state, mode, app_instructions, req)
    async for ev in orchestrator.run(conversation[:-1], conversation[-1].content, opts):
        kind = ev["type"]
        if kind == "usage" and ev.get("usage"):
            yield "usage", ev["usage"]
        elif "subtask" in ev:  # a specialist's report: only the merged answer goes to the client
            continue
        elif kind in ("delta", "reasoning") and ev.get("text"):
            yield "text" if kind == "delta" else "reasoning", ev["text"]
        elif kind == "done":
            yield "spike", {"specialists": ev["specialists"]}
            if ev.get("error"):
                yield "error", ev["error"]
            else:
                yield "finish", ev.get("finish_reason")


async def with_contract(attempt: Callable[[list[Message]], AsyncIterator[Out]],
                        schema: dict[str, Any], retries: int = 1) -> AsyncIterator[Out]:
    """Collect the answer, check it against the schema and, if it breaks it, ask once more with the errors. The
    client gets the JSON alone (fences removed) and `spike.contract` says whether it follows the schema."""
    extra: list[Message] = []
    for n in range(1, retries + 2):
        parts: list[str] = []
        finish, spike = None, {}
        async for kind, value in attempt(extra):
            if kind == "text":
                parts.append(value)
            elif kind == "finish":
                finish = value
            elif kind == "spike":
                spike = value
            elif kind == "error":
                yield kind, value
                return
            else:  # reasoning and usage of every attempt reach the client
                yield kind, value
        answer = "".join(parts)
        value, errors = check(answer, schema)
        if not errors or n > retries:
            break
        extra = [Message(role="assistant", content=answer), Message(role="user", content=repair_prompt(errors))]
    yield "text", json.dumps(value, ensure_ascii=False) if not errors else answer
    yield "spike", {**spike, "contract": {"valid": not errors, "attempts": n, **({"errors": errors} if errors else {})}}
    yield "finish", finish


def plan_run(state: AppState, req: Completion) -> AsyncIterator[Out]:
    if req.model == AUTO:
        spec_id = None
    elif req.model.startswith("spike-") and req.model[6:] in state.catalog.specialists:
        spec_id = req.model[6:]
    else:
        pid, sep, model = req.model.partition("/")
        if sep and model and state.provider_config(pid):
            if req.json_schema is not None and not req.client_tools:
                return with_contract(lambda extra: run_passthrough(state, pid, model, req, extra), req.json_schema)
            return run_passthrough(state, pid, model, req)
        raise ApiError(404, f"unknown model '{req.model}': GET /v1/models lists the available ones",
                       param="model", code="model_not_found")
    app_instructions = "\n\n".join(m.content for m in req.messages if m.role == "system" and m.content.strip())
    conversation = [m for m in req.messages if m.role != "system"]
    if not conversation or conversation[-1].role == "assistant":
        raise ApiError(400, "the last message must come from the user or be a tool result", param="messages")
    if req.client_tools or req.json_schema is not None or conversation[-1].role == "tool":
        if spec_id is None:
            last_user = next((m.content for m in reversed(conversation) if m.role == "user"), "")
            spec_id = state.orchestrator().router.route(last_user).specialists[0]
        spec = state.catalog.get(spec_id)
        if req.json_schema is not None and not req.client_tools:
            return with_contract(lambda extra: run_direct(state, spec, app_instructions, conversation, req, extra),
                                 req.json_schema)
        return run_direct(state, spec, app_instructions, conversation, req)
    return run_orchestrated(state, spec_id or "auto", app_instructions, conversation, req)


# ---------------------------------------------------------------------- responses
def _add_usage(total: dict[str, int] | None, usage: dict[str, Any]) -> dict[str, int] | None:
    """Only report complete non-negative backend counts; missing usage is unknown, not zero."""
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    if any(type(v) is not int or v < 0 for v in (prompt, completion)):
        return total
    total = dict(total or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    total["prompt_tokens"] += prompt
    total["completion_tokens"] += completion
    total["total_tokens"] = total["prompt_tokens"] + total["completion_tokens"]
    return total


def _tool_call(call: ToolCall, index: int | None = None) -> dict[str, Any]:
    out = {"id": call.id or _call_id(), "type": "function",
           "function": {"name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)}}
    return out if index is None else {"index": index, **out}


def _finish(reason: str | None, calls: list[ToolCall]) -> str:
    if calls:
        return "tool_calls"
    return reason if reason in ("length", "content_filter") else "stop"


async def complete(req: Completion, outs: AsyncIterator[Out]) -> JSONResponse:
    text, reasoning, calls, reason, spike = [], [], [], None, {}
    usage: dict[str, int] | None = None
    async for kind, value in outs:
        if kind == "text":
            text.append(value)
        elif kind == "reasoning":
            reasoning.append(value)
        elif kind == "tool_call":
            calls.append(value)
        elif kind == "usage":
            usage = _add_usage(usage, value)
        elif kind == "finish":
            reason = value
        elif kind == "spike":
            spike = value
        elif kind == "error":
            raise ApiError(502, value, "api_error", code="upstream_error")
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text) or (None if calls else "")}
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if calls:
        message["tool_calls"] = [_tool_call(c) for c in calls]
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex}", "object": "chat.completion", "created": int(time.time()),
        "model": req.model, "choices": [{"index": 0, "message": message, "finish_reason": _finish(reason, calls)}],
        "usage": usage, "spike": spike,
    })


def stream(req: Completion, outs: AsyncIterator[Out]) -> StreamingResponse:
    cid, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())

    def chunk(delta: dict[str, Any] | None, finish: str | None = None, **extra: Any) -> bytes:
        choices = [] if delta is None else [{"index": 0, "delta": delta, "finish_reason": finish}]
        body = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": req.model,
                "choices": choices, **extra}
        return f"data: {json.dumps(body, ensure_ascii=False, default=str)}\n\n".encode()

    async def events() -> AsyncIterator[bytes]:
        calls, reason, spike = [], None, {}
        usage: dict[str, int] | None = None
        yield chunk({"role": "assistant", "content": ""})
        try:
            async for kind, value in outs:
                if kind == "text":
                    yield chunk({"content": value})
                elif kind == "reasoning":
                    yield chunk({"reasoning_content": value})
                elif kind == "tool_call":
                    yield chunk({"tool_calls": [_tool_call(value, len(calls))]})
                    calls.append(value)
                elif kind == "usage":
                    usage = _add_usage(usage, value)
                elif kind == "finish":
                    reason = value
                elif kind == "spike":
                    spike = value
                elif kind == "error":
                    raise ApiError(502, value, "api_error", code="upstream_error")
        except ApiError as exc:
            yield f"data: {json.dumps(exc.body(), ensure_ascii=False)}\n\n".encode()
            return
        except Exception as exc:  # never leave the client waiting without a reason
            err = ApiError(500, f"{exc.__class__.__name__}: {exc}", "api_error")
            yield f"data: {json.dumps(err.body(), ensure_ascii=False)}\n\n".encode()
            return
        yield chunk({}, _finish(reason, calls), spike=spike)
        if req.include_usage:
            yield chunk(None, usage=usage)
        yield b"data: [DONE]\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------- routes
def create_router(get_state) -> APIRouter:
    router = APIRouter(prefix="/v1")

    @router.get("/models")
    async def models(request: Request):
        try:
            check_access(request)
        except ApiError as exc:
            return exc.response()
        state: AppState = get_state()
        ids = [AUTO, *(f"spike-{sid}" for sid in state.catalog.specialists)]
        ids += [f"{c['id']}/{c['model']}" for c in state.provider_configs() if c.get("model")]
        return {"object": "list", "data": [{"id": i, "object": "model", "created": 0,
                                            "owned_by": i.split("/")[0] if "/" in i else "spike"} for i in ids]}

    @router.post("/chat/completions")
    async def chat_completions(request: Request):
        try:
            check_access(request)
            try:
                body = await request.json()
            except ValueError as exc:
                raise ApiError(400, "the request body must be JSON") from exc
            req = parse_completion(body)
            outs = plan_run(get_state(), req)
            return stream(req, outs) if req.stream else await complete(req, outs)
        except ApiError as exc:
            return exc.response()
        except Exception as exc:  # an OpenAI-shaped error, so clients show the reason
            return ApiError(500, f"{exc.__class__.__name__}: {exc}", "api_error").response()

    return router
