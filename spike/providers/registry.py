"""Provider presets and factory. Adding a provider is a preset entry, not a core change."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from spike.providers.anthropic import AnthropicProvider
from spike.providers.base import Provider, ProviderConfig
from spike.providers.llamacpp import LlamaCppProvider
from spike.providers.openai_compat import OpenAICompatProvider

KINDS: dict[str, type[Provider]] = {
    "openai": OpenAICompatProvider,
    "llamacpp": LlamaCppProvider,
    "anthropic": AnthropicProvider,
}


@dataclass(frozen=True)
class Preset:
    id: str
    kind: str
    name: str
    base_url: str
    paid: bool
    local: bool = False
    needs_key: bool = True
    key_url: str = ""
    example_model: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)


PRESETS: list[Preset] = [
    Preset("spike-local", "llamacpp", "SPIKE local (llama.cpp)", "http://127.0.0.1:8737/v1", paid=False, local=True,
           needs_key=False, example_model="spike-base"),
    Preset("ollama", "openai", "Ollama", "http://127.0.0.1:11434/v1", paid=False, local=True, needs_key=False,
           example_model="qwen3.5:4b", capabilities={"stream_usage": False}),
    Preset("lmstudio", "openai", "LM Studio", "http://127.0.0.1:1234/v1", paid=False, local=True, needs_key=False),
    Preset("llamacpp-external", "llamacpp", "llama.cpp server (custom)", "http://127.0.0.1:8080/v1", paid=False,
           local=True, needs_key=False),
    Preset("openai", "openai", "OpenAI", "https://api.openai.com/v1", paid=True,
           key_url="https://platform.openai.com/api-keys"),
    Preset("anthropic", "anthropic", "Anthropic", "https://api.anthropic.com/v1", paid=True,
           key_url="https://console.anthropic.com/settings/keys"),
    Preset("deepseek", "openai", "DeepSeek", "https://api.deepseek.com/v1", paid=True,
           key_url="https://platform.deepseek.com/api_keys", example_model="deepseek-chat"),
    Preset("gemini", "openai", "Google Gemini (OpenAI endpoint)", "https://generativelanguage.googleapis.com/v1beta/openai",
           paid=True, key_url="https://aistudio.google.com/apikey", capabilities={"stream_usage": False}),
    Preset("openrouter", "openai", "OpenRouter", "https://openrouter.ai/api/v1", paid=True,
           key_url="https://openrouter.ai/keys"),
    Preset("groq", "openai", "Groq", "https://api.groq.com/openai/v1", paid=True, key_url="https://console.groq.com/keys"),
    Preset("mistral", "openai", "Mistral", "https://api.mistral.ai/v1", paid=True,
           key_url="https://console.mistral.ai/api-keys", capabilities={"stream_usage": False}),
    Preset("together", "openai", "Together AI", "https://api.together.xyz/v1", paid=True,
           key_url="https://api.together.ai/settings/api-keys"),
    Preset("custom-openai", "openai", "Custom OpenAI-compatible", "http://127.0.0.1:8000/v1", paid=True),
]

PRESETS_BY_ID = {p.id: p for p in PRESETS}


def create_provider(config: ProviderConfig, client: httpx.AsyncClient | None = None) -> Provider:
    try:
        cls = KINDS[config.kind]
    except KeyError as exc:
        raise ValueError(f"Unknown provider kind '{config.kind}'. Known: {sorted(KINDS)}") from exc
    return cls(config, client=client)
