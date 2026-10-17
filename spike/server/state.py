"""Application state shared by the HTTP API: storage, providers, specialists, tools and the local runtime."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.providers.base import Provider, ProviderConfig
from spike.providers.llamacpp import LlamaCppProvider
from spike.providers.registry import PRESETS_BY_ID, create_provider
from spike.runtime.hardware import detect, recommend
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig
from spike.runtime.paths import adapters_dir, spike_home, workspace_dir
from spike.specialists.catalog import Catalog, Specialist, load_catalog
from spike.store.db import Store
from spike.store.secrets import SecretStore
from spike.tools.base import PermissionBroker
from spike.tools.builtin import default_registry

DEFAULT_SETTINGS: dict[str, Any] = {
    "custom_instructions": "",
    "specialist_instructions": {},
    "default_provider": "spike-local",
    "specialist_bindings": {},  # specialist id -> {"provider_id": ..., "model": ...}
    "tool_policies": {},
    "tools_enabled": True,
    "use_planner": True,
    "parallel": False,
    "reasoning": None,
    "temperature": None,
    "max_tokens": 2048,
    "custom_specialists": [],
    "local_runtime": {"model": "", "adapters": [], "context": None, "threads": None, "gpu_layers": None,
                      "kv_cache_type": "q8_0", "port": 8737},
}
SETTING_KEYS = set(DEFAULT_SETTINGS)


class AppState:
    def __init__(self, home: Path | None = None, provider_factory=create_provider):
        self.home = home or spike_home()
        self.store = Store(self.home / "spike.db")
        self.secrets = SecretStore(self.home / "secrets.json")
        self.provider_factory = provider_factory
        self._providers: dict[str, Provider] = {}
        self.installed_adapters: dict[str, set[str]] = {}
        self.runtime: LlamaServer | None = None
        self.broker = PermissionBroker(self.settings()["tool_policies"])
        self.tools = default_registry(workspace_dir())
        self.catalog = self._load_catalog()
        if not self.store.list_providers():
            self._seed_providers()

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict[str, Any]:
        out = {}
        for key, default in DEFAULT_SETTINGS.items():
            out[key] = self.store.get_setting(key, default)
        return out

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        unknown = set(patch) - SETTING_KEYS
        if unknown:
            raise ValueError(f"unknown settings: {sorted(unknown)}")
        for key, value in patch.items():
            self.store.set_setting(key, value)
        if "tool_policies" in patch:
            self.broker.policies = dict(patch["tool_policies"])
        if "custom_specialists" in patch:
            self.catalog = self._load_catalog()
        return self.settings()

    def _load_catalog(self) -> Catalog:
        return load_catalog(extra=self.store.get_setting("custom_specialists", []))

    # ------------------------------------------------------------------ providers
    def _seed_providers(self) -> None:
        preset = PRESETS_BY_ID["spike-local"]
        self.store.save_provider({"id": preset.id, "kind": preset.kind, "name": preset.name, "base_url": preset.base_url,
                                  "model": preset.example_model, "paid": False, "allow_paid": False, "local": True,
                                  "preset": preset.id, "capabilities": dict(preset.capabilities)})

    def provider_configs(self) -> list[dict[str, Any]]:
        return self.store.list_providers()

    def provider_config(self, pid: str) -> dict[str, Any] | None:
        return next((c for c in self.provider_configs() if c["id"] == pid), None)

    def provider(self, pid: str) -> Provider:
        if pid in self._providers:
            return self._providers[pid]
        raw = self.provider_config(pid)
        if raw is None:
            raise KeyError(f"unknown provider '{pid}'")
        cfg = ProviderConfig(
            id=raw["id"], kind=raw["kind"], name=raw["name"], base_url=raw["base_url"], model=raw.get("model", ""),
            api_key=self.secrets.get(f"provider:{pid}"), paid=bool(raw.get("paid")),
            allow_paid=bool(raw.get("allow_paid")), local=bool(raw.get("local")),
            headers=dict(raw.get("headers") or {}), capabilities=dict(raw.get("capabilities") or {}),
        )
        provider = self.provider_factory(cfg)
        self._providers[pid] = provider
        return provider

    def invalidate_provider(self, pid: str) -> None:
        self._providers.pop(pid, None)
        self.installed_adapters.pop(pid, None)

    def public_provider(self, raw: dict[str, Any]) -> dict[str, Any]:
        out = dict(raw)
        out["has_key"] = self.secrets.has(f"provider:{raw['id']}")
        try:
            out["capabilities_effective"] = asdict(self.provider(raw["id"]).capabilities)
        except Exception:
            out["capabilities_effective"] = None
        return out

    async def refresh_adapters(self, pid: str) -> set[str]:
        provider = self.provider(pid)
        if isinstance(provider, LlamaCppProvider):
            try:
                self.installed_adapters[pid] = set(await provider.adapters(refresh=True))
            except Exception:
                self.installed_adapters[pid] = set()
        else:
            self.installed_adapters[pid] = set()
        return self.installed_adapters[pid]

    # ------------------------------------------------------------------ orchestration
    def binding(self, spec: Specialist, override_provider: str | None = None) -> tuple[str, str | None]:
        if override_provider:
            return override_provider, None
        b = self.settings()["specialist_bindings"].get(spec.id) or {}
        return b.get("provider_id") or self.settings()["default_provider"], b.get("model") or None

    def orchestrator(self, override_provider: str | None = None) -> Orchestrator:
        settings = self.settings()
        local_ctx = settings["local_runtime"].get("context") or recommend(detect()).context

        def resolve(spec: Specialist) -> Backend:
            pid, model = self.binding(spec, override_provider)
            provider = self.provider(pid)
            adapter = None
            if spec.adapter and provider.capabilities.adapters and spec.adapter in self.installed_adapters.get(pid, set()):
                adapter = spec.adapter
            max_ctx = provider.capabilities.max_context or (local_ctx if provider.config.local else 32768)
            budget = max(2048, max_ctx - (settings["max_tokens"] or 2048) - 512)
            return Backend(provider=provider, model=model, adapter=adapter, context_budget=budget)

        return Orchestrator(self.catalog, resolve, self.tools, self.broker)

    def options(self, mode: str) -> OrchestratorOptions:
        s = self.settings()
        return OrchestratorOptions(
            mode=mode, custom_instructions=s["custom_instructions"], specialist_instructions=s["specialist_instructions"],
            use_planner=s["use_planner"], parallel=s["parallel"], temperature=s["temperature"],
            max_tokens=s["max_tokens"], reasoning=s["reasoning"], tools_enabled=s["tools_enabled"],
        )

    def providers_for_run(self, override_provider: str | None) -> set[str]:
        return {self.binding(spec, override_provider)[0] for spec in self.catalog.specialists.values()}

    # ------------------------------------------------------------------ local runtime
    def runtime_config(self) -> ServerConfig:
        cfg = self.settings()["local_runtime"]
        if not cfg.get("model"):
            raise ValueError("No local model configured. Download one with `spike models pull` or set it in Settings.")
        rec = recommend(detect())
        adapters = [Path(p) for p in cfg.get("adapters") or []] or sorted(adapters_dir().glob("*.gguf"))
        return ServerConfig(
            model=Path(cfg["model"]).expanduser(), adapters=adapters, port=int(cfg.get("port") or 8737),
            context=int(cfg.get("context") or rec.context), threads=cfg.get("threads") or rec.threads,
            gpu_layers=rec.gpu_layers if cfg.get("gpu_layers") is None else int(cfg["gpu_layers"]),
            kv_cache_type=cfg.get("kv_cache_type") or rec.kv_cache_type,
        )

    async def start_runtime(self) -> dict[str, Any]:
        config = self.runtime_config()
        if self.runtime and self.runtime.running():
            await self.runtime.stop()
        self.runtime = LlamaServer(config)
        await self.runtime.start()
        local = self.provider_config("spike-local")
        if local is not None:
            local["base_url"] = self.runtime.base_url + "/v1"
            self.store.save_provider(local)
            self.invalidate_provider("spike-local")
        return self.runtime.status()

    async def stop_runtime(self) -> None:
        if self.runtime:
            await self.runtime.stop()
