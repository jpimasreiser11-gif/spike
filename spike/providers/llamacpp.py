"""llama.cpp `llama-server` backend: one base model in memory, specialist LoRA adapters selected per request.

Adapter selection (verified against llama.cpp 62318cd source and tests/test_llamacpp_integration.py):
  * An empty or missing `lora` field does not mean "no adapter": the server falls back to the global
    adapter scales, which are 1.0 for every `--lora` file. SPIKE therefore always sends an explicit scale
    for every loaded adapter (1.0 for the selected one, 0.0 for the rest), and LlamaServer resets the
    global scales to 0 at startup for clients that send nothing.
  * With an explicit list the server clears the slot's prompt cache when the adapter set changes; on the
    fallback path it does not, so a cached prefix computed with one adapter could be reused without it.
    As defense in depth SPIKE also pins requests to slot 0, serializes them and only enables
    `cache_prompt` when the adapter is the same as in the previous request.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from spike.core.types import Capabilities, ChatRequest, ProviderError, StreamEvent
from spike.providers.base import raise_for_status
from spike.providers.openai_compat import OpenAICompatProvider


def explicit_lora(ids: Iterable[int], selected: int | None) -> list[dict[str, Any]]:
    return [{"id": i, "scale": 1.0 if i == selected else 0.0} for i in sorted(ids)]


class LlamaCppProvider(OpenAICompatProvider):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._adapters: dict[str, int] | None = None
        self._last_adapter: str | None | bool = False  # False = no request yet
        self._lock = asyncio.Lock()

    def default_capabilities(self) -> Capabilities:
        return Capabilities(streaming=True, native_tools=True, json_schema=True, adapters=True, reasoning=True)

    @property
    def server_root(self) -> str:
        base = self.config.base_url.rstrip("/")
        return base[: -len("/v1")] if base.endswith("/v1") else base

    async def adapters(self, refresh: bool = False) -> dict[str, int]:
        """Map adapter name (file stem) -> llama-server adapter id."""
        if self._adapters is None or refresh:
            response = await self.client.get(self.server_root + "/lora-adapters", headers=self.headers())
            await raise_for_status(response, self.config.name)
            self._adapters = {Path(a["path"]).stem: int(a["id"]) for a in response.json()}
        return self._adapters

    async def resolve_lora(self, adapter: str | None) -> list[dict[str, Any]]:
        """Explicit scale for every loaded adapter; see the module docstring for why `[]` is unsafe."""
        table = await self.adapters()
        if adapter is not None and adapter not in table:
            raise ProviderError(f"Adapter '{adapter}' is not loaded in llama-server (loaded: {sorted(table) or 'none'}).")
        return explicit_lora(table.values(), table.get(adapter) if adapter else None)

    async def health(self) -> dict[str, Any]:
        response = await self.client.get(self.server_root + "/health")
        return {"status_code": response.status_code, **(response.json() if response.content else {})}

    def extra_body(self, request: ChatRequest) -> dict[str, Any]:
        same_adapter = self._last_adapter is not False and self._last_adapter == request.adapter
        body: dict[str, Any] = {"cache_prompt": same_adapter, "id_slot": 0, "timings_per_token": False}
        if request.reasoning is not None:
            body["chat_template_kwargs"] = {"enable_thinking": bool(request.reasoning)}
        lora = getattr(request, "_resolved_lora", None)
        if lora:  # no adapters loaded -> nothing to select
            body["lora"] = lora
        return body

    async def stream(self, request: ChatRequest):  # type: ignore[override]
        try:
            self.validate_vision(request)
            lora = await self.resolve_lora(request.adapter)
        except Exception as exc:
            yield StreamEvent(kind="error", text=str(exc))
            return
        request._resolved_lora = lora  # type: ignore[attr-defined]  # read by extra_body()
        async with self._lock:
            try:
                async for event in super().stream(request):
                    yield event
            finally:
                self._last_adapter = request.adapter
