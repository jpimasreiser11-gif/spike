"""Application state shared by the HTTP API: storage, providers, specialists, tools and the local runtime."""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Any

from spike.connectors.manager import ConnectorManager
from spike.core.context import estimate_tokens
from spike.core.types import ChatRequest, Message
from spike.memory.extract import extract_text
from spike.memory.service import Embedder, MemoryService, scopes_for
from spike.memory.store import MemoryStore
from spike.memory.tools import memory_tools
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.projects import ProjectFiles
from spike.providers.base import Provider, ProviderConfig
from spike.providers.guard import GuardedProvider, month_start
from spike.providers.llamacpp import LlamaCppProvider
from spike.providers.registry import PRESETS_BY_ID, create_provider
from spike.runtime.hardware import detect, recommend
from spike.runtime.llamacpp_server import LlamaServer, ServerConfig, find_binary
from spike.runtime.models import EMBEDDING_MODEL, MODELS
from spike.runtime.paths import adapters_dir, models_dir, spike_home, workspace_dir
from spike.skills.engine import BUNDLED, SkillLibrary
from spike.specialists.catalog import Catalog, Specialist, load_catalog
from spike.store.checkpoints import Checkpoints
from spike.store.db import Store
from spike.store.secrets import SecretStore
from spike.tools.base import PermissionBroker, ToolRegistry
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
    "skill_mode": "auto",
    # Neural Memory: recall in chats; vectors from a local embedding model when installed ("off" = words only);
    # chat summaries only when the summarising model is local, so memory never spends money
    "memory": {"enabled": True, "embeddings": "auto", "auto_summary": True},
    "disabled_skills": [],
    "local_runtime": {"model": "", "adapters": [], "context": None, "threads": None, "gpu_layers": None,
                      "kv_cache_type": "q8_0", "port": 8737},
}
SETTING_KEYS = set(DEFAULT_SETTINGS)
SUMMARY_EVERY = 6  # messages between automatic chat summaries
SUMMARY_PROMPT = (
    "You keep SPIKE's long-term memory. From the conversation below, write the durable things worth remembering "
    "in later chats: facts about the user and their work, decisions taken, preferences, open tasks. At most 5 short "
    "bullet points, in the conversation's language, with no greetings or small talk. If nothing is worth "
    "remembering, reply exactly NONE."
)
log = logging.getLogger(__name__)


class AppState:
    def __init__(self, home: Path | None = None, provider_factory=create_provider):
        self.home = home or spike_home()
        self.store = Store(self.home / "spike.db")
        self.checkpoints = Checkpoints(self.store, self.home / "checkpoints")
        self.secrets = SecretStore(self.home / "secrets.json")
        self.provider_factory = provider_factory
        self._providers: dict[str, Provider] = {}
        self.installed_adapters: dict[str, set[str]] = {}
        self.runtime: LlamaServer | None = None
        self.broker = PermissionBroker(self.settings()["tool_policies"])
        self.connectors = ConnectorManager(self.store, self.secrets, workspace_dir(), self.home / "connectors")
        self.memory = MemoryService(MemoryStore(self.home / "memory.db"), self._embedder)
        self.embed_server: LlamaServer | None = None
        self.embed_error: str | None = None
        self._summarized: dict[str, int] = {}
        self._background: set[asyncio.Task] = set()
        self.tools = default_registry(workspace_dir())
        for tool in memory_tools(self.memory, None):
            self.tools.register(tool)
        self.tools.shared = self.connectors.tools
        self.project_files = ProjectFiles(self.home / "projects")
        self._project_tools: dict[str, ToolRegistry] = {}
        self.catalog = self._load_catalog()
        self.skills = SkillLibrary([(BUNDLED, "bundled"), (self.home / "skills", "user")])
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

    def provider(self, pid: str) -> GuardedProvider:
        if pid in self._providers:
            return self._providers[pid]
        raw = self.provider_config(pid)
        if raw is None:
            raise KeyError(f"unknown provider '{pid}'")
        cfg = ProviderConfig(
            id=raw["id"], kind=raw["kind"], name=raw["name"], base_url=raw["base_url"], model=raw.get("model", ""),
            api_key=self.secrets.get(f"provider:{pid}"), paid=bool(raw.get("paid")),
            allow_paid=bool(raw.get("allow_paid")), local=bool(raw.get("local")),
            share_files=bool(raw.get("share_files")),
            headers=dict(raw.get("headers") or {}), capabilities=dict(raw.get("capabilities") or {}),
        )
        provider = GuardedProvider(self.provider_factory(cfg), self.store,
                                   lambda: dict((self.provider_config(pid) or {}).get("limits") or {}))
        self._providers[pid] = provider
        return provider

    def usage(self) -> list[dict[str, Any]]:
        """This month's use of each provider, next to the limits the user set for it."""
        since = month_start()
        return [{"provider_id": c["id"], "name": c["name"], "local": bool(c.get("local")),
                 "limits": dict(c.get("limits") or {}), **self.store.usage_since(c["id"], since)}
                for c in self.provider_configs()]

    def forget_project(self, project_id: str) -> None:
        self.checkpoints.prune()  # the project's chats are gone: so are the copies kept to undo their steps
        self._project_tools.pop(project_id, None)
        self.project_files.remove(project_id)
        self.memory.store.delete_scope(f"project:{project_id}")

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
        provider = self.provider(pid).inner
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

    def tools_for(self, project_id: str | None) -> ToolRegistry:
        """The tools of a project's chats: file tools work in that project's own folder."""
        if not project_id:
            return self.tools
        if project_id not in self._project_tools:
            registry = default_registry(self.project_files.folder(project_id))
            for tool in memory_tools(self.memory, project_id):
                registry.register(tool)
            registry.shared = self.connectors.tools
            self._project_tools[project_id] = registry
        return self._project_tools[project_id]

    def orchestrator(self, override_provider: str | None = None, broker: PermissionBroker | None = None,
                     project_id: str | None = None) -> Orchestrator:
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

        return Orchestrator(self.catalog, resolve, self.tools_for(project_id), broker or self.broker, skills=self.skills)

    def options(self, mode: str, project: dict[str, Any] | None = None) -> OrchestratorOptions:
        s = self.settings()
        return OrchestratorOptions(
            mode=mode, custom_instructions=s["custom_instructions"], specialist_instructions=s["specialist_instructions"],
            project_instructions=(project or {}).get("instructions", ""),
            skill_mode=s["skill_mode"], disabled_skills=list(s["disabled_skills"]),
            use_planner=s["use_planner"], parallel=s["parallel"], temperature=s["temperature"],
            max_tokens=s["max_tokens"], reasoning=s["reasoning"], tools_enabled=s["tools_enabled"],
        )

    def providers_for_run(self, override_provider: str | None) -> set[str]:
        return {self.binding(spec, override_provider)[0] for spec in self.catalog.specialists.values()}

    async def ensure_adapters(self, override_provider: str | None = None) -> None:
        """Learn which adapters each provider of the coming run has loaded, once per provider."""
        for pid in self.providers_for_run(override_provider):
            if pid not in self.installed_adapters and self.provider_config(pid):
                await self.refresh_adapters(pid)

    # ------------------------------------------------------------------ memory
    def memory_settings(self) -> dict[str, Any]:
        return {**DEFAULT_SETTINGS["memory"], **(self.settings()["memory"] or {})}

    def embedding_model(self) -> Path | None:
        entry = MODELS[EMBEDDING_MODEL]
        return next((p for q in entry.quants if (p := models_dir() / entry.filename(q)).is_file()), None)

    async def _embedder(self) -> Embedder | None:
        """The local embedding server, started on first use; None when memory search runs on words only."""
        cfg = self.memory_settings()
        path = self.embedding_model()
        if not cfg["enabled"] or cfg["embeddings"] == "off" or path is None or find_binary() is None:
            return None
        if self.embed_server is None or not self.embed_server.running():
            if self.embed_error:
                return None  # it failed once: words only until the settings change or SPIKE restarts
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            server = LlamaServer(ServerConfig(model=path, port=port, context=4096, kv_cache_type="f16",
                                              extra_args=["--embedding", "--pooling", "last", "-b", "4096",
                                                          "-ub", "4096"]))
            server.log_path = self.home / "logs" / "llama-embedding.log"
            try:
                await server.start(timeout_s=120)
            except (OSError, RuntimeError, TimeoutError) as exc:
                self.embed_error = str(exc)
                return None
            self.embed_server = server
        return Embedder(self.embed_server.base_url, model=path.name, query_prefix=MODELS[EMBEDDING_MODEL].query_prefix)

    def memory_status(self) -> dict[str, Any]:
        path = self.embedding_model()
        return {**self.memory_settings(), "stats": self.memory.store.stats(), "semantic": {
            "model": path.name if path else None, "installed": path is not None,
            "running": bool(self.embed_server and self.embed_server.running()), "error": self.embed_error,
            "install": f"spike models pull {EMBEDDING_MODEL}"}}

    def index_project_file(self, project_id: str, relative: str) -> bool:
        """Put a project file's text in the project's memory, replacing an older version; False if unreadable."""
        text = extract_text(self.project_files.path(project_id, relative))
        scope, source = f"project:{project_id}", f"file:{relative}"
        if text is None:
            self.memory.store.delete_source(scope, source)
            return False
        self.memory.store.replace_source(scope, source, text, "document")
        self.background(self.memory.index())
        return True

    def background(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def maybe_summarize(self, conversation_id: str, override_provider: str | None = None) -> bool:
        """Every few messages, save what a chat established as a 'summary' memory (local models only)."""
        cfg = self.memory_settings()
        conv = self.store.get_conversation(conversation_id)
        if not conv or not cfg["enabled"] or not cfg["auto_summary"]:
            return False
        messages = [m for m in self.store.messages(conversation_id) if m["role"] in ("user", "assistant") and m["content"]]
        scope, source = scopes_for(conv.get("project_id"))[0], f"conversation:{conversation_id}"
        previous = self.memory.store.find_source(scope, source)
        done = max(self._summarized.get(conversation_id, 0), (previous.meta.get("messages", 0) if previous else 0))
        if len(messages) < SUMMARY_EVERY or len(messages) - done < SUMMARY_EVERY:
            return False
        pid, model = self.binding(self.catalog.specialists["core"], override_provider or conv.get("provider_id"))
        provider = self.provider(pid)
        if not provider.config.local:
            return False
        self._summarized[conversation_id] = len(messages)
        lines, used = [], 0
        for m in reversed(messages):  # the most recent part of the chat that fits
            line = f"{m['role'].upper()}: {m['content']}"
            if used + estimate_tokens(line) > 3000:
                break
            lines.insert(0, line)
            used += estimate_tokens(line)
        request = ChatRequest(messages=[Message(role="system", content=SUMMARY_PROMPT),
                                        Message(role="user", content="\n\n".join(lines))],
                              model=model, max_tokens=300, temperature=0.2, reasoning=False)
        text = ""
        try:
            async for ev in provider.stream(request):
                if ev.kind == "text":
                    text += ev.text
                elif ev.kind == "error":
                    return False
        except Exception as exc:  # a failed summary never breaks the chat
            log.warning("memory: summary failed: %s", exc)
            return False
        text = text.strip()
        if not text or text.upper().startswith("NONE"):
            return False
        self.memory.store.replace_source(scope, source, text, "summary",
                                         {"messages": len(messages), "title": conv["title"]})
        await self.memory.index()
        return True

    async def close(self) -> None:
        for task in list(self._background):
            task.cancel()
        if self.embed_server:
            await self.embed_server.stop()
        await self.connectors.close_all()

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
