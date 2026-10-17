"""llama.cpp `llama-server` backend: one base model in memory, specialist LoRA adapters selected per request.

Prompt-cache safety: llama-server's prompt cache is not keyed by the LoRA configuration, so KV entries
computed with one adapter can be reused by a request using another adapter (verified on llama.cpp
62318cd, see tests/test_llamacpp_integration.py). SPIKE therefore pins requests to slot 0, serializes
them, and only enables `cache_prompt` when the adapter is the same as in the previous request.
"""

from __future__ import annotations

import asyncio

from pathlib import Path
from typing import Any

from spike.core.types import Capabilities, ChatRequest, ProviderError, StreamEvent
from spike.providers.base import raise_for_status
from spike.providers.openai_compat import OpenAICompatProvider


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
        if adapter is None:
            return []
        table = await self.adapters()
        if adapter not in table:
            raise ProviderError(f"Adapter '{adapter}' is not loaded in llama-server (loaded: {sorted(table) or 'none'}).")
        return [{"id": table[adapter], "scale": 1.0}]

    async def health(self) -> dict[str, Any]:
        response = await self.client.get(self.server_root + "/health")
        return {"status_code": response.status_code, **(response.json() if response.content else {})}

    def extra_body(self, request: ChatRequest) -> dict[str, Any]:
        same_adapter = self._last_adapter is not False and self._last_adapter == request.adapter
        body: dict[str, Any] = {"cache_prompt": same_adapter, "id_slot": 0, "timings_per_token": False}
        if request.reasoning is not None:
            body["chat_template_kwargs"] = {"enable_thinking": bool(request.reasoning)}
        lora = getattr(request, "_resolved_lora", None)
        # Always send the list: adapters omitted from it run at scale 0, so a request without an
        # adapter is guaranteed to use the plain base model even if a global scale was set.
        body["lora"] = lora or []
        return body

    async def stream(self, request: ChatRequest):  # type: ignore[override]
        try:
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
