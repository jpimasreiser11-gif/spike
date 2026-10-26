"""Application state shared by the HTTP API: storage, providers, specialists, tools and the local runtime."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import socket
import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from spike.analytics.tools import analytics_tools
from spike.connectors import browser
from spike.connectors.manager import ConnectorManager
from spike.core.context import estimate_tokens
from spike.core.types import ChatRequest, Message, ProviderError
from spike.design.library import DesignLibrary
from spike.desktop import settings as desktop_settings
from spike.desktop.service import DesktopService
from spike.dev.diagnostics import diagnostic_tools
from spike.evolution.router_learning import apply_overlay
from spike.evolution.service import Evolution
from spike.evolution.store import EvolutionStore
from spike.finance import live as live_trading
from spike.finance.market import EXCHANGES, ccxt_exchange
from spike.finance.tools import Finance, finance_tools
from spike.forge import prototypes
from spike.forge.blueprint import Blueprint, make_blueprint
from spike.memory.extract import extract_text
from spike.memory.learn import correction_rule, explicit_memories
from spike.memory.service import Embedder, MemoryService, scopes_for
from spike.memory.store import MemoryStore
from spike.memory.tools import memory_tools
from spike.motion.tools import motion_tools
from spike.orchestrator.minds import Mind
from spike.orchestrator.orchestrator import Backend, Orchestrator, OrchestratorOptions
from spike.projects import ProjectFiles
from spike.providers.base import Provider, ProviderConfig
from spike.providers.guard import CURRENT_CHAT, GuardedProvider, call_cost, month_start, usage_tokens
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
from spike.tools.builtin import Workspace, default_registry
from spike.tools.sandbox import MODES as SANDBOX_MODES
from spike.tools.sandbox import Sandbox
from spike.trust import escalate
from spike.trust import settings as trust_settings

DEFAULT_SETTINGS: dict[str, Any] = {
    "custom_instructions": "",
    "specialist_instructions": {},
    "default_provider": "spike-local",
    "specialist_bindings": {},  # specialist id -> {"provider_id": ..., "model": ...}
    "tool_policies": {},
    "sandbox": "auto",  # auto = isolate python and data_python when the computer can | off | required (run_command too)
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
    "memory": {"enabled": True, "embeddings": "auto", "auto_summary": True, "learn": True},
    # trustworthy answers: claim labels on, an external second opinion offered (never sent without a click) when an
    # answer has this many unchecked claims, and the optional model pass that may lower labels
    "trust": dict(trust_settings.DEFAULTS),
    "disabled_skills": [],
    # desktop actions (A19): off until the user turns them on; only an API provider with a computer-use tool does them,
    # and every action waits for the user's approval
    "desktop": dict(desktop_settings.DEFAULTS),
    # Evolution: learn from corrections, route corrections and failures on this computer; a learned router is used
    # only after it passes its gate, and every version can be rolled back
    # training_data: opt-in (level 3); auto_strategy: tie-breaks from past use refresh themselves, behind the check
    # (EV3); personal_adapter: opt-in (EV6), off until the user turns it on
    "evolution": {"enabled": True, "auto_router": True, "training_data": False, "auto_strategy": True,
                  "personal_adapter": False},
    # the browser connector's domains ("allow" | "deny") and what other domains do ("ask" | "allow")
    "browser": {"domains": {}, "unknown": "ask"},
    # Spike Finance: public prices from this exchange; real orders off until the user sets them up
    "finance": {"exchange": "kraken", "live": dict(live_trading.DEFAULTS)},
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
RELATIONS_PROMPT = (
    "You help build a knowledge graph. Below is one note and the entities found in it. Propose at most 6 relations "
    "that the note itself states between two of those entities. Reply only with JSON: "
    '{"relations": [{"from": "<entity>", "label": "<short verb phrase, in the note\'s language>", "to": "<entity>"}]}. '
    'Use the entity names exactly as listed. If the note states no relation, reply {"relations": []}.'
)
RELATIONS_SCHEMA = {"type": "object", "properties": {"relations": {"type": "array", "maxItems": 6, "items": {
    "type": "object", "properties": {"from": {"type": "string"}, "label": {"type": "string"},
                                     "to": {"type": "string"}}, "required": ["from", "label", "to"]}}},
    "required": ["relations"]}
log = logging.getLogger(__name__)


def clean_finance(value: dict[str, Any]) -> dict[str, Any]:
    unknown = set(value) - {"exchange", "live"}
    if unknown:
        raise ValueError(f"unknown finance settings: {sorted(unknown)}")
    if value.get("exchange") not in EXCHANGES:
        raise ValueError(f"exchange must be one of {', '.join(EXCHANGES)}")
    return {"exchange": value["exchange"], "live": live_trading.clean(value.get("live") or {})}


class AppState:
    def __init__(self, home: Path | None = None, provider_factory=create_provider, market_factory=ccxt_exchange):
        self.home = home or spike_home()
        self.store = Store(self.home / "spike.db")
        self.temp = Store(Path(":memory:"))  # temporary chats: never on disk, gone when SPIKE stops
        self.checkpoints = Checkpoints(self.store, self.home / "checkpoints")
        self.secrets = SecretStore(self.home / "secrets.json")
        self.provider_factory = provider_factory
        self._providers: dict[str, Provider] = {}
        self.installed_adapters: dict[str, set[str]] = {}
        self.optimizing = False  # Evolution level 2 runs one optimisation at a time
        self.asking: set[str] = set()  # answers whose second opinion is being asked for (in memory: it cannot get stuck)
        self.runtime: LlamaServer | None = None
        self.broker = PermissionBroker(self.settings()["tool_policies"])
        self.connectors = ConnectorManager(self.store, self.secrets, workspace_dir(), self.home / "connectors")
        self.broker.on_domain = lambda domain, rule: self.connectors.set_domain(domain, rule)
        self.memory = MemoryService(MemoryStore(self.home / "memory.db"), self._embedder, lambda: [self.home])
        self.embed_server: LlamaServer | None = None
        self.embed_error: str | None = None
        self._summarized: dict[str, int] = {}
        self._background: set[asyncio.Task] = set()
        self._tuning = asyncio.Lock()
        self.finance = Finance(self.home, self.secrets, lambda: self.settings()["finance"], market_factory)
        mode = self.settings()["sandbox"]
        self.sandbox = Sandbox(mode if mode in SANDBOX_MODES else "auto")
        self.tools = default_registry(workspace_dir(), self.sandbox)
        workspace = Workspace(workspace_dir())
        for tool in [*memory_tools(self.memory, None), *finance_tools(self.finance, workspace),
                     *analytics_tools(workspace, self.sandbox), *motion_tools(workspace),
                     *diagnostic_tools(workspace, self.sandbox, self.connectors)]:
            self.tools.register(tool)
        self.tools.shared = self.connectors.tools
        self.project_files = ProjectFiles(self.home / "projects")
        self._project_tools: dict[str, ToolRegistry] = {}
        self.evolution = Evolution(EvolutionStore(self.home / "evolution.db"))
        self.catalog = self._load_catalog()
        self.skills = SkillLibrary([(BUNDLED, "bundled"), (self.home / "skills", "user")])
        self.skills.prefer = self._prefer_skills
        self.designs = DesignLibrary(self.home / "design-systems")
        self.desktop = DesktopService(lambda: self.settings()["desktop"], self.provider, self.provider_configs, self.home)
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
        if "browser" in patch:
            patch = {**patch, "browser": browser.clean(patch["browser"])}
        if "sandbox" in patch and patch["sandbox"] not in SANDBOX_MODES:
            raise ValueError(f"sandbox must be one of {', '.join(SANDBOX_MODES)}")
        if "trust" in patch:
            if not isinstance(patch["trust"], dict):
                raise ValueError("'trust' must be an object")
            patch = {**patch, "trust": trust_settings.clean({**self.trust_settings(), **patch["trust"]})}
        if "desktop" in patch:
            if not isinstance(patch["desktop"], dict):
                raise ValueError("'desktop' must be an object")
            patch = {**patch, "desktop": desktop_settings.clean({**desktop_settings.DEFAULTS,
                                                                 **self.settings()["desktop"], **patch["desktop"]})}
        if "finance" in patch:
            now, given = self.settings()["finance"], patch["finance"]
            if not isinstance(given, dict):
                raise ValueError("'finance' must be an object")
            live = {**now.get("live", {}), **given["live"]} if isinstance(given.get("live"), dict) else given.get(
                "live", now.get("live"))
            patch = {**patch, "finance": clean_finance({**now, **given, "live": live})}
        for key, value in patch.items():
            self.store.set_setting(key, value)
        if "tool_policies" in patch:
            self.broker.policies = dict(patch["tool_policies"])
        if "sandbox" in patch:
            self.sandbox.mode = patch["sandbox"]
        if "desktop" in patch and not patch["desktop"]["enabled"] and self.desktop.task is not None:
            self.desktop.task.stop()  # turning the setting off ends a running task at once
        if "custom_specialists" in patch:
            self.catalog = self._load_catalog()
        return self.settings()

    def base_catalog(self) -> Catalog:
        """The catalog with the user's custom specialists, without anything learned."""
        return load_catalog(extra=self.store.get_setting("custom_specialists", []))

    def _load_catalog(self) -> Catalog:
        return apply_overlay(self.base_catalog(), self.evolution.router_overlay())

    def reload_catalog(self) -> None:
        self.catalog = self._load_catalog()

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
        prototypes.forget(self.prototypes_home, self.project_files.folder(project_id))
        self.project_files.remove(project_id)
        scope = f"project:{project_id}"
        self.memory.folders.forget_scope(scope)
        self.memory.glossary.delete_scope(scope)
        self.memory.tutor.delete_scope(scope)
        self.memory.graph.delete_scope(scope)
        self.memory.store.delete_scope(scope)

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
            self._project_tools[project_id] = self.tools_in(self.project_files.folder(project_id), project_id)
        return self._project_tools[project_id]

    def tools_in(self, folder: Path, project_id: str | None = None) -> ToolRegistry:
        """The tools of a run whose file tools work in `folder`: a project's folder, or a checkout of one branch."""
        registry = default_registry(folder, self.sandbox)
        workspace = Workspace(folder)
        for tool in [*memory_tools(self.memory, project_id), *finance_tools(self.finance, workspace),
                     *analytics_tools(workspace, self.sandbox), *motion_tools(workspace),
                     *diagnostic_tools(workspace, self.sandbox, self.connectors)]:
            registry.register(tool)
        registry.shared = self.connectors.tools
        return registry

    def orchestrator(self, override_provider: str | None = None, broker: PermissionBroker | None = None,
                     project_id: str | None = None, tools: ToolRegistry | None = None) -> Orchestrator:
        settings = self.settings()
        local_ctx = settings["local_runtime"].get("context") or recommend(detect()).context

        def resolve(spec: Specialist) -> Backend:
            pid, model = self.binding(spec, override_provider)
            provider = self.provider(pid)
            adapter = None
            wanted = spec.adapter or (self.personal_adapter() if spec.id == "core" else None)  # EV6: core only
            if wanted and provider.capabilities.adapters and wanted in self.installed_adapters.get(pid, set()):
                adapter = wanted
            max_ctx = provider.capabilities.max_context or (local_ctx if provider.config.local else 32768)
            budget = max(2048, max_ctx - (settings["max_tokens"] or 2048) - 512)
            return Backend(provider=provider, model=model, adapter=adapter, context_budget=budget)

        return Orchestrator(self.catalog, resolve, tools or self.tools_for(project_id), broker or self.broker,
                            skills=self.skills)

    async def blueprint(self, task: str, provider_id: str | None = None, project_id: str | None = None) -> Blueprint:
        """A Forge blueprint drafted by the core model of this run, for the user to review."""
        orchestrator = self.orchestrator(provider_id, project_id=project_id)
        core = orchestrator.resolve(self.catalog.core)
        candidates = orchestrator.router.route(task).specialists
        return await make_blueprint(core.provider, self.catalog, task, [c for c in candidates if c != "core"],
                                    model=core.model)

    def options(self, mode: str, project: dict[str, Any] | None = None) -> OrchestratorOptions:
        s = self.settings()
        return OrchestratorOptions(
            mode=mode, custom_instructions=s["custom_instructions"], specialist_instructions=s["specialist_instructions"],
            project_instructions=(project or {}).get("instructions", ""),
            skill_mode=s["skill_mode"], disabled_skills=list(s["disabled_skills"]),
            use_planner=s["use_planner"], parallel=s["parallel"], temperature=s["temperature"],
            max_tokens=s["max_tokens"], reasoning=s["reasoning"], tools_enabled=s["tools_enabled"],
            design=self.designs.get((project or {}).get("design") or ""),  # the project's, unless the chat picks one
            **self.learned_prompts(),
        )

    def learned_prompts(self) -> dict[str, Any]:
        """Evolution level 2: each specialist's active learned instructions and skill modes."""
        from spike.evolution.prompts import learned

        found = learned(self.evolution.store, list(self.catalog.specialists))
        return {"learned_instructions": {k: list(v.instructions) for k, v in found.items() if v.instructions},
                "learned_skills": {k: v.skill_modes() for k, v in found.items() if v.skills}}

    def providers_for_run(self, override_provider: str | None) -> set[str]:
        return {self.binding(spec, override_provider)[0] for spec in self.catalog.specialists.values()}

    async def ensure_adapters(self, override_provider: str | None = None) -> None:
        """Learn which adapters each provider of the coming run has loaded, once per provider."""
        for pid in self.providers_for_run(override_provider):
            if pid not in self.installed_adapters and self.provider_config(pid):
                await self.refresh_adapters(pid)

    def store_for(self, conversation_id: str | None) -> Store:
        """The store holding this chat: the temporary one for temporary chats, the database otherwise."""
        return self.temp if conversation_id and self.temp.get_conversation(conversation_id) else self.store

    # ------------------------------------------------------------------ learning from the user (Evolution 1)
    def learn_from(self, message: str, conversation: dict[str, Any], user_message_id: str,
                   answered_before: bool) -> tuple[dict[str, Any], list[Any]]:
        """What the user's message teaches: sentences they asked SPIKE to remember are saved now; a correction of
        the previous answer becomes a proposed rule for them to approve. Returns (meta for the answer, saved)."""
        cfg = self.memory_settings()
        if not cfg["enabled"] or not cfg["learn"]:
            return {}, []
        scope = scopes_for(conversation.get("project_id"))[0]
        store, saved, items = self.memory.store, [], []
        for item in explicit_memories(message):
            memory = store.find_text(scope, item.kind, item.text)
            existing = memory is not None
            if memory is None:
                memory = store.add(item.text, item.kind, scope, meta={
                    "by": "user", "from": "message", "conversation": conversation["id"], "message": user_message_id})
            saved.append(memory)
            items.append({"id": memory.id, "kind": memory.kind, "text": memory.text, "scope": scope,
                          **({"existing": True} if existing else {})})
        learn: dict[str, Any] = {}
        if items:
            learn["saved"] = items
            self.background(self.memory.index())
        elif answered_before and (proposal := correction_rule(message)):
            learn["correction"] = {"text": proposal, "status": "proposed"}
        return learn, saved

    def apply_learning(self, user_message_id: str, action: str, text: str | None = None,
                       memory_id: str | None = None) -> dict[str, Any]:
        """The user's answer to a proposed rule (save, with their wording, or dismiss), or undo of a saved item."""
        message = self.store.get_message(user_message_id)
        if message is None or message["role"] != "user":
            raise LookupError("message not found")
        thread = self.store.messages(message["conversation_id"])
        after = thread[next(i for i, m in enumerate(thread) if m["id"] == user_message_id) + 1:]
        answer = next((m for m in after if m["role"] == "assistant"), None)
        learn = (answer or {}).get("meta", {}).get("learn")
        if answer is None or not learn:
            raise ValueError("nothing to learn from this message")
        conversation = self.store.get_conversation(message["conversation_id"]) or {}
        scope = scopes_for(conversation.get("project_id"))[0]
        store, correction = self.memory.store, learn.get("correction")
        if action in ("save", "dismiss"):
            if not correction:
                raise ValueError("this message has no proposed rule")
            if action == "dismiss":
                correction["status"] = "dismissed"
            elif correction["status"] != "saved":
                wording = (text if text is not None else correction["text"]).strip()
                if not wording or len(wording) > 2000:
                    raise ValueError("the rule must be between 1 and 2000 characters")
                memory = store.find_text(scope, "rule", wording)
                correction.pop("existing", None)
                if memory is not None:
                    correction["existing"] = True  # the user already had this rule: undo leaves it alone
                else:
                    memory = store.add(wording, "rule", scope, meta={
                        "by": "user", "from": "correction", "conversation": message["conversation_id"],
                        "message": user_message_id})
                    self.background(self.memory.index())
                correction.update(status="saved", memory=memory.id, text=wording)
                if self.evolution_settings()["enabled"]:
                    self.evolution.record_correction(thread, user_message_id, wording, memory.id)
        elif action == "undo":
            if correction and memory_id and correction.get("memory") == memory_id:
                if not correction.pop("existing", False):
                    store.delete(memory_id)
                correction["status"] = "proposed"
                correction.pop("memory", None)
                self.evolution.forget_correction(user_message_id)
            else:
                item = next((s for s in learn.get("saved", []) if s["id"] == memory_id and not s.get("existing")), None)
                if item is None:
                    raise LookupError("nothing to undo")
                store.delete(item["id"])
                item["undone"] = True
        else:
            raise ValueError(f"unknown action '{action}'")
        self.store.update_message_meta(answer["id"], answer["meta"])
        return learn

    # ------------------------------------------------------------------ trust
    def trust_settings(self) -> dict[str, Any]:
        return {**trust_settings.DEFAULTS, **(self.settings()["trust"] or {})}

    def escalation_offer(self, trust: dict[str, Any], used: set[str], question: str, answer: str
                         ) -> dict[str, Any] | None:
        """The second opinion offered for a low-confidence answer: why, and for each external provider (one with a
        key that the run did not already use) what would be sent, what it would cost at the prices the user entered
        and whether the paid-call guard or a monthly limit would stop it. None when the answer is fine, the offer is
        off or no external provider is configured. Nothing is sent."""
        cfg = self.trust_settings()
        low = escalate.low_confidence((trust.get("counts") or {}).get("unchecked", 0),
                                      bool(trust.get("verifier_failed")), cfg["escalate_unchecked"])
        if not cfg["escalate"] or low is None:
            return None
        private = bool(trust.get("private"))
        messages = escalate.build_messages(question, answer, escalate.unchecked_claims(trust), private)
        max_tokens = self.settings()["max_tokens"] or 2048
        offers = []
        for raw in self.external_providers():
            if raw["id"] in used:
                continue
            provider = self.provider(raw["id"])
            offers.append({
                "provider_id": raw["id"], "name": raw["name"], "model": raw.get("model", ""),
                "paid": bool(raw.get("paid")), "blocked": provider.blocked(),
                "files": "none" if not private else "sent" if provider.receives_files else "withheld",
                **escalate.estimate(messages, dict(raw.get("limits") or {}), max_tokens, raw["name"],
                                    provider.receives_files)})
        offers.sort(key=lambda o: (o["blocked"] is not None, o["cost"] is None))
        return {**low, "offers": offers, "status": "offered"} if offers else None

    def external_providers(self) -> list[dict[str, Any]]:
        """The providers a second opinion can go to: not local, with an API key."""
        return [c for c in self.provider_configs() if not c.get("local") and self.secrets.has(f"provider:{c['id']}")]

    async def escalate(self, user_message_id: str, provider_id: str) -> dict[str, Any]:
        """The user clicked "ask <provider>": send the question, the local answer and its unchecked claims to that
        provider through its guard (paid-call permission, monthly limits, files withheld unless allowed) and keep its
        answer with the message. LookupError: no such answer; ValueError: not offered or not an external provider;
        RuntimeError: already asked or being asked; PermissionError: the guard blocks it; ProviderError: it failed."""
        store = next((x for x in (self.store, self.temp) if x.get_message(user_message_id)), None)
        message = store.get_message(user_message_id) if store else None
        if store is None or message is None or message["role"] != "user":
            raise LookupError("message not found")
        thread = store.messages(message["conversation_id"])
        answer = next((m for m in thread[next(i for i, m in enumerate(thread) if m["id"] == user_message_id) + 1:]
                       if m["role"] == "assistant"), None)
        trust = ((answer or {}).get("meta") or {}).get("trust") or {}
        offer = trust.get("escalation")
        if answer is None or not offer or not offer.get("offers"):
            raise ValueError("this answer was not offered a second opinion")
        if offer["status"] == "answered":
            raise RuntimeError("a second opinion was already asked for this answer")
        if answer["id"] in self.asking:
            raise RuntimeError("a second opinion is being asked for this answer")
        raw = next((c for c in self.external_providers() if c["id"] == provider_id), None)
        if raw is None:
            raise ValueError(f"'{provider_id}' is not an external provider with an API key")
        provider = self.provider(provider_id)
        if (reason := provider.blocked()) is not None:
            raise PermissionError(reason)
        settings = self.settings()
        max_tokens = settings["max_tokens"] or 2048
        private = bool(trust.get("private"))
        request = ChatRequest(
            messages=escalate.build_messages(message["content"], answer["content"], escalate.unchecked_claims(trust),
                                             private),
            model=raw.get("model") or None, temperature=settings["temperature"], max_tokens=max_tokens)
        CURRENT_CHAT.set(message["conversation_id"])  # the call log notes which chat the call was for
        parts: list[str] = []
        usage: tuple[int, int] | None = None
        withheld, error = 0, None
        self.asking.add(answer["id"])
        try:
            async for ev in provider.stream(request):
                if ev.kind == "text":
                    parts.append(ev.text)
                elif ev.kind == "usage" and ev.usage:
                    usage = usage_tokens(ev.usage) or usage
                elif ev.kind == "notice" and (ev.notice or {}).get("type") == "privacy":
                    withheld = int(ev.notice["withheld"])
                elif ev.kind == "error":
                    error = ev.text
        except Exception as exc:  # the chat must be able to ask again
            error = f"{exc.__class__.__name__}: {exc}"
        finally:
            self.asking.discard(answer["id"])
        if error is not None or not parts:
            offer["error"] = error or "the provider returned no answer"
            store.update_message_meta(answer["id"], answer["meta"])
            raise ProviderError(offer["error"])
        estimated = usage is None
        tokens_in = usage[0] if usage else sum(estimate_tokens(m.content) for m in request.messages)
        tokens_out = usage[1] if usage else estimate_tokens("".join(parts))
        offer.pop("error", None)
        offer["status"] = "answered"
        offer["answer"] = {"provider_id": provider_id, "name": raw["name"], "model": raw.get("model", ""),
                           "text": "".join(parts), "tokens_in": tokens_in, "tokens_out": tokens_out,
                           "estimated": estimated, "cost": call_cost(dict(raw.get("limits") or {}), tokens_in,
                                                                     tokens_out),
                           "files_withheld": withheld, "time": time.time()}
        store.update_message_meta(answer["id"], answer["meta"])
        return offer

    # ------------------------------------------------------------------ Parallel Prototypes
    @property
    def prototypes_home(self) -> Path:
        return self.home / "prototypes"

    def prototype_root(self, project_id: str | None) -> Path:
        """The folder the prototypes are built from: the project's folder, or the workspace."""
        return self.project_files.folder(project_id) if project_id else workspace_dir()

    async def prototype_blueprints(self, task: str, provider_id: str | None = None, project_id: str | None = None
                                   ) -> list[Blueprint]:
        """Two blueprints for one task, one per approach (prototypes.APPROACH_HINTS), drafted by the core model of
        this run one after the other, for the user to review. Nothing runs."""
        orchestrator = self.orchestrator(provider_id, project_id=project_id)
        core = orchestrator.resolve(self.catalog.core)
        candidates = [c for c in orchestrator.router.route(task).specialists if c != "core"]
        return [await make_blueprint(core.provider, self.catalog, task, candidates, model=core.model,
                                     approach=prototypes.APPROACH_HINTS[label]) for label in prototypes.LABELS]

    # ------------------------------------------------------------------ Parallel Minds
    def minds_estimate(self, message: str, minds: list[Mind], mode: str = "auto", provider_id: str | None = None,
                       history_tokens: int = 0, project_id: str | None = None) -> dict[str, Any]:
        """What the minds would cost, before anything runs: ×N time and tokens, per provider the calls they make, their
        tokens (output at its maximum) and the cost at the prices the user entered, and the first reason the guard
        would stop the batch (paid calls not allowed, or a monthly limit the batch would cross). Nothing is sent or
        logged. A mind that runs a multi-step plan makes more calls than one: it is counted as one call per
        specialist of the lexical router's route and three of the core model (plan, checker, merge), and flagged."""
        settings = self.settings()
        router = self.orchestrator(provider_id, project_id=project_id).router
        max_tokens = settings["max_tokens"] or 2048
        base_in = history_tokens + estimate_tokens(message)
        per: dict[str, dict[str, int]] = {}
        multi = False
        for mind in minds:
            wanted = mind.mode or mode
            if wanted != "auto":
                specs = [self.catalog.get(wanted)]
            else:
                decision = router.route(message)
                specs = [self.catalog.get(s) for s in decision.specialists]
                if decision.mode == "multi" and settings["use_planner"]:
                    multi, specs = True, [self.catalog.core, *specs, self.catalog.core, self.catalog.core]
            for spec in specs:
                row = per.setdefault(self.binding(spec, mind.provider_id or provider_id)[0],
                                     {"calls": 0, "tokens_in": 0, "tokens_out": 0})
                row["calls"] += 1
                row["tokens_in"] += base_in + estimate_tokens(spec.system_prompt)
                row["tokens_out"] += max_tokens
        providers, unpriced = [], []
        for pid, row in per.items():
            raw = self.provider_config(pid) or {}
            guarded = self.provider(pid)
            local = bool(raw.get("local"))
            cost = None if local else call_cost(dict(raw.get("limits") or {}), row["tokens_in"], row["tokens_out"])
            if cost is None and not local:
                unpriced.append(raw.get("name", pid))
            providers.append({"provider_id": pid, "name": raw.get("name", pid), "local": local,
                              "paid": bool(raw.get("paid")), **row,
                              "cost": None if cost is None else round(cost, 6),
                              "blocked": guarded.blocked_for(row["calls"], row["tokens_in"], row["tokens_out"])})
        priced = [p["cost"] for p in providers if p["cost"] is not None]
        return {"n": len(minds), "multiplier": len(minds), "multi_step": multi, "providers": providers,
                "cost": round(sum(priced), 6) if priced else None, "unpriced": unpriced,
                "blocked": next((p["blocked"] for p in providers if p["blocked"]), None)}

    # ------------------------------------------------------------------ evolution
    def evolution_settings(self) -> dict[str, Any]:
        return {**DEFAULT_SETTINGS["evolution"], **(self.settings()["evolution"] or {})}

    def adapters_path(self) -> Path:
        return adapters_dir()

    def route_correction(self, user_message_id: str, specialist: str) -> dict[str, Any]:
        """The user is retrying this question with another specialist: record it and, when automatic, learn the
        router again behind its gate."""
        if specialist not in self.catalog.specialists:
            raise ValueError(f"unknown specialist '{specialist}'")
        message = self.store.get_message(user_message_id)
        if message is None or message["role"] != "user":
            raise LookupError("message not found")
        thread = self.store.messages(message["conversation_id"])
        after = thread[next(i for i, m in enumerate(thread) if m["id"] == user_message_id) + 1:]
        answer = next((m for m in after if m["role"] == "assistant"), None)
        routed = [s["id"] for s in ((answer or {}).get("meta", {}).get("route") or {}).get("specialists") or []]
        cfg = self.evolution_settings()
        if not cfg["enabled"]:
            return {"recorded": False}
        item = self.evolution.record_route(message["content"], routed, specialist, message["conversation_id"],
                                           user_message_id)
        out: dict[str, Any] = {"recorded": item is not None}
        if item is not None and cfg["auto_router"]:
            out["router"] = self.learn_router()
        return out

    def learn_router(self) -> dict[str, Any]:
        report = self.evolution.learn_router(self.base_catalog())
        self.reload_catalog()
        return report

    def rollback(self, component: str) -> dict[str, Any] | None:
        """Go back to the version a component's active version replaced (the built-in one when there is none)."""
        from spike.evolution import adapters, personal

        if component == "router":
            previous = self.evolution.store.rollback("router")
            self.reload_catalog()
            return previous
        if component == "strategy" or (component.startswith("prompt:") and component[7:] in self.catalog.specialists):
            return self.evolution.store.rollback(component)
        if component == adapters.component(personal.PERSONAL):  # the personal adapter (EV6)
            return adapters.rollback(self.evolution.store, self.adapters_path(), personal.PERSONAL)
        spec = self.catalog.specialists.get(component.removeprefix("adapter:"))
        if not component.startswith("adapter:") or spec is None:
            raise LookupError(f"unknown component '{component}'")
        return adapters.rollback(self.evolution.store, self.adapters_path(), spec)

    def build_examples(self) -> dict[str, Any]:
        """Evolution level 3: saved corrections become training examples, only with the user's consent."""
        from spike.evolution import dataset

        if not self.evolution_settings()["training_data"]:
            raise PermissionError("turn on “Use my corrections to retrain” in Settings → Evolution first")
        base = self.base_catalog()
        return dataset.build(self.evolution, self.store,
                             lambda sid: base.specialists[sid].system_prompt if sid in base.specialists else "")

    async def optimize_prompt(self, specialist: str, typed: list[str] | None = None, max_calls: int | None = None,
                              progress=None, answer=None) -> dict[str, Any]:
        """Evolution level 2 for one specialist (spike.evolution.prompts); `answer` replaces the model in tests."""
        from spike.evolution import prompts
        from spike.evolution.checks import answer_with_variant, catalog_check, router_check, skills_check

        if specialist not in self.catalog.specialists:
            raise ValueError(f"unknown specialist '{specialist}'")
        skills = [s.name for s in self.skills.all() if specialist in (s.specialists or [])]

        def gate() -> tuple[bool, str]:
            checks = [router_check(self), catalog_check(self), skills_check(self)]
            return all(c["ok"] for c in checks), "; ".join(c["detail"] for c in checks if not c["ok"])

        return await prompts.optimize(
            self.evolution.store, specialist, prompts.eval_set(self.evolution.store, specialist),
            answer or (lambda q, v: answer_with_variant(self, q, specialist, v)),
            prompts.ideas_for(self.evolution.store, specialist, typed), skills,
            max_calls or prompts.MAX_CALLS, progress, gate)

    def propose_prompt(self, specialist: str, lines: list[str] | None = None,
                       skills: dict[str, str] | None = None) -> dict[str, Any]:
        """EV8: store a candidate prompt version for a specialist; it is used only after `activate_prompt`."""
        from spike.evolution import prompts

        if specialist not in self.catalog.specialists:
            raise ValueError(f"unknown specialist '{specialist}'")
        return prompts.propose(self.evolution.store, specialist, lines, skills)

    async def activate_prompt(self, specialist: str, version: int | None = None, answer=None) -> dict[str, Any]:
        """EV8: make a candidate prompt version the one in use, only if it scores within the tolerance of the version
        in use on the local eval set and the other regression checks pass; `answer` replaces the model in tests."""
        from spike.evolution import prompts
        from spike.evolution.checks import answer_with_variant, catalog_check, router_check, skills_check

        if specialist not in self.catalog.specialists:
            raise ValueError(f"unknown specialist '{specialist}'")

        def gate() -> tuple[bool, str]:
            checks = [router_check(self), catalog_check(self), skills_check(self)]
            return all(c["ok"] for c in checks), "; ".join(c["detail"] for c in checks if not c["ok"])

        return await prompts.activate(self.evolution.store, specialist, version,
                                      answer or (lambda q, v: answer_with_variant(self, q, specialist, v)), gate)

    # ------------------------------------------------------------------ evolution: personal adapter (EV6)
    def personal_adapter(self) -> str | None:
        """The accepted personal adapter Spike Core loads, only while the setting is on."""
        from spike.evolution import personal

        return personal.in_use(self.evolution.store, self.evolution_settings(), self.adapters_path())

    def personal_overview(self) -> dict[str, Any]:
        """What the personal adapter would be trained on, whether it can be trained here and what is in use."""
        from spike.evolution import adapters, personal

        cfg = self.evolution_settings()
        built = personal.build_set(self.evolution.store, self.store, bool(cfg["training_data"]))
        entries = [{k: e[k] for k in ("id", "source", "conversation", "question", "answer", "excluded", "duplicate")}
                   for e in built["entries"]]
        return {"enabled": bool(cfg["personal_adapter"]), "training_data": bool(cfg["training_data"]),
                **personal.availability(), "counts": built["counts"], "chats": built["chats"], "entries": entries,
                "marked": [{"id": m["id"], "conversation": m["conversation"], "title": m.get("title", "")}
                           for m in personal.marked(self.evolution.store)],
                "active": self.evolution.store.active(adapters.component(personal.PERSONAL)),
                "versions": self.evolution.store.versions(adapters.component(personal.PERSONAL))[:5],
                "command": "spike evolve personal-adapter --llama-cpp ~/src/llama.cpp"}

    # ------------------------------------------------------------------ evolution: tool strategy (EV3)
    def _prefer_skills(self, ranked: list[tuple[float, str]], specialist: str, text: str) -> list[str]:
        """The skill router's tie-break: the learned preference when Evolution is on and it passed its check."""
        preference = self.evolution.strategy_preference() if self.evolution_settings()["enabled"] else None
        return preference.order(ranked, specialist, text) if preference else [name for _, name in ranked]

    def record_strategy(self, question: str, meta: dict[str, Any], message_id: str) -> None:
        """A finished run's tools and skills, by task type; refreshes the tie-break every few new uses if automatic."""
        from spike.evolution import strategy

        if not self.evolution.record_strategy(question, meta, message_id) or not self.evolution_settings()["auto_strategy"]:
            return
        last = next(iter(self.evolution.store.versions(strategy.COMPONENT)), None)
        if self.evolution.store.count_runs() - (last["report"].get("uses", 0) if last else 0) >= strategy.AUTO_EVERY:
            self.learn_strategy()

    def flag_correction(self, message: str, conversation_id: str, user_message_id: str, answered_before: bool) -> None:
        """This message corrects the previous answer (the same patterns as the correction rule): what that answer
        used no longer counts as a success."""
        if not answered_before or not self.evolution_settings()["enabled"] or correction_rule(message) is None:
            return
        thread = self.store.messages(conversation_id)
        at = next((i for i, m in enumerate(thread) if m["id"] == user_message_id), None)
        previous = next((m for m in reversed(thread[:at]) if m["role"] == "assistant"), None) if at else None
        if previous is not None:
            self.evolution.flag_strategy([previous["id"]], "corrected")

    def learn_strategy(self) -> dict[str, Any]:
        """Snapshot the recorded uses as the skill router's tie-break; kept only if routing does not get worse and the
        regression checks pass with it applied."""
        from spike.evolution import strategy
        from spike.evolution.checks import catalog_check, router_check, skills_check

        def gate(preference: strategy.Preference) -> tuple[bool, str]:
            with strategy.preferring(self.skills, preference):
                checks = [router_check(self), catalog_check(self), skills_check(self)]
            return all(c["ok"] for c in checks), "; ".join(c["detail"] for c in checks if not c["ok"])

        return strategy.learn(self.evolution.store, self.skills, gate)

    def reset_strategy(self) -> int:
        from spike.evolution import strategy

        return strategy.reset(self.evolution.store)

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

    async def propose_relations(self, memory_id: str, override_provider: str | None = None) -> list[dict[str, Any]]:
        """Ask the local model which of the entities in one note are related, and store the answers as proposals the
        user confirms or rejects. Only a local model is asked, so a note never leaves the computer for this."""
        memory = self.memory.store.get(memory_id)
        if memory is None:
            raise LookupError("memory not found")
        names = self.memory.graph.note_entities(memory_id)[:24]
        if len(names) < 2:
            return []
        pid, model = self.binding(self.catalog.specialists["core"], override_provider)
        provider = self.provider(pid)
        if not provider.config.local:
            raise PermissionError("relations are proposed only by a local model: nothing from your notes is sent "
                                  "to an external provider for this")
        request = ChatRequest(
            messages=[Message(role="system", content=RELATIONS_PROMPT),
                      Message(role="user", content=f"NOTE:\n{memory.text[:3000]}\n\nENTITIES:\n"
                                                   + "\n".join(f"- {n}" for n in names))],
            model=model, max_tokens=400, temperature=0.1, reasoning=False,
            json_schema=RELATIONS_SCHEMA if provider.capabilities.json_schema else None)
        text = ""
        async for ev in provider.stream(request):
            if ev.kind == "text":
                text += ev.text
            elif ev.kind == "error":
                raise RuntimeError("the local model did not answer")
        match = re.search(r"\{.*\}", text, re.S)
        try:
            items = json.loads(match.group(0))["relations"] if match else []
            triples = [(str(i["from"]), str(i["label"]), str(i["to"])) for i in items if isinstance(i, dict)][:6]
        except (ValueError, KeyError, TypeError):
            triples = []
        return self.memory.graph.propose(memory_id, triples)

    async def close(self) -> None:
        for task in list(self._background):
            task.cancel()
        if self.embed_server:
            await self.embed_server.stop()
        await self.connectors.close_all()
        self.finance.close()

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

    # ------------------------------------------------------------------ tuning
    def tune_report(self) -> dict[str, Any] | None:
        path = self.home / "tune.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    async def run_tune(self, quick: bool = False, tuner=None) -> AsyncIterator[dict[str, Any]]:
        """Measure settings for the local model (`spike.tune`), save the best ones and the report. The local engine
        is stopped while it runs, so only one model is in memory, and started again afterwards."""
        from spike.tune import save_report, tune

        model = (self.settings()["local_runtime"].get("model") or "").strip()
        if not model or not Path(model).expanduser().is_file():
            raise ValueError("No local model configured. Download one with `spike models pull` or set it in Settings.")
        if self._tuning.locked():
            raise RuntimeError("a tuning run is already in progress")
        async with self._tuning:
            was_running = bool(self.runtime and self.runtime.running())
            if was_running:
                await self.stop_runtime()
            try:
                async for ev in (tuner or tune)(Path(model).expanduser(), quick=quick):
                    if ev["type"] == "tune_done":
                        cfg = dict(self.settings()["local_runtime"])
                        cfg.update({k: ev["best"][k] for k in ("threads", "kv_cache_type", "context")})
                        self.update_settings({"local_runtime": cfg})
                        save_report(ev["report"], self.home / "tune.json")
                        ev = {**ev, "applied": True}
                    yield ev
            finally:
                if was_running:
                    await self.start_runtime()
