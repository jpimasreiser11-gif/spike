"""Connectors: MCP servers from the curated catalog or added by the user, whose tools become SPIKE tools.

Every connector tool goes through the permission broker like a built-in tool: the connector's policy (ask by
default) applies to each of its tools, and a per-tool policy in Settings → Tools overrides it.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from spike.connectors.mcp import HttpTransport, McpClient, McpError, StdioTransport
from spike.store.db import Store
from spike.store.secrets import SecretStore
from spike.tools.base import Tool, ToolResult

CATALOG = Path(__file__).with_name("catalog.yaml")
POLICIES = ("allow", "ask", "deny")
ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,30}$"
START_TIMEOUT_S = 120  # npx/uvx may download the server on first start


@dataclass
class ConnectorDef:
    id: str
    name: str
    transport: str  # "stdio" | "http"
    description: str = ""
    command: str = ""
    args: list[str] = field(default_factory=list)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)  # values may use {SECRET_NAME}
    env: dict[str, str] = field(default_factory=dict)  # values may use {workspace} and {data}
    secrets: list[dict[str, Any]] = field(default_factory=list)  # {name, label, url?, optional?}
    license: str = ""
    source: str = ""
    paid: bool = False
    files: bool = False  # its results can carry the user's file contents (kept from providers not allowed them)
    requires: str = ""
    note: str = ""
    custom: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any], custom: bool = False) -> ConnectorDef:
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw and k != "custom"}
        return cls(**known, custom=custom)

    def public(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__ if k != "headers"} | {
            "header_names": sorted(self.headers)}


def load_catalog(path: Path = CATALOG) -> list[ConnectorDef]:
    return [ConnectorDef.from_dict(raw) for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []]


def tool_name(connector_id: str, remote: str) -> str:
    """OpenAI-style function names: [A-Za-z0-9_-]{1,64}."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", f"mcp__{connector_id.replace('-', '_')}__{remote}")[:64]


class McpTool(Tool):
    risk = "network"

    def __init__(self, connector: ConnectorDef, client: McpClient, spec: dict[str, Any], name: str, policy: str):
        self.connector, self.client, self.remote_name = connector, client, spec["name"]
        self.name = name
        self.description = f"[{connector.name}] {spec.get('description') or spec['name']}"[:1024]
        self.parameters = spec.get("inputSchema") or {"type": "object", "properties": {}}
        self.default_policy = policy  # type: ignore[assignment]

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await self.client.call_tool(self.remote_name, args)
        except McpError as exc:
            return ToolResult(ok=False, content=f"error: {self.connector.name}: {exc}")
        content = result.text[:100_000]
        return ToolResult(ok=not result.is_error, content=content, private=[content] if self.connector.files else [])


@dataclass
class Connection:
    client: McpClient | None = None
    tools: list[McpTool] = field(default_factory=list)
    status: str = "stopped"  # stopped | starting | running | error
    error: str | None = None


class ConnectorManager:
    def __init__(self, store: Store, secrets: SecretStore, workspace: Path, data_dir: Path,
                 catalog: list[ConnectorDef] | None = None):
        self.store, self.secrets, self.workspace, self.data_dir = store, secrets, workspace, data_dir
        self.catalog = catalog if catalog is not None else load_catalog()
        self.connections: dict[str, Connection] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ definitions and settings
    def definitions(self) -> list[ConnectorDef]:
        custom = [ConnectorDef.from_dict(raw, custom=True) for raw in self.store.get_setting("custom_connectors", [])]
        return self.catalog + custom

    def get(self, cid: str) -> ConnectorDef | None:
        return next((d for d in self.definitions() if d.id == cid), None)

    def config(self, cid: str) -> dict[str, Any]:
        return {"enabled": False, "policy": "ask", **self.store.get_setting("connectors", {}).get(cid, {})}

    def _save_config(self, cid: str, **fields: Any) -> None:
        all_configs = self.store.get_setting("connectors", {})
        all_configs[cid] = {**all_configs.get(cid, {}), **fields}
        self.store.set_setting("connectors", all_configs)

    def add_custom(self, raw: dict[str, Any]) -> ConnectorDef:
        definition = ConnectorDef.from_dict(raw, custom=True)
        if not re.match(ID_PATTERN, definition.id) or self.get(definition.id):
            raise ValueError(f"connector id '{definition.id}' is invalid or already used")
        if definition.transport == "stdio" and not definition.command:
            raise ValueError("a stdio connector needs a command")
        if definition.transport == "http" and not re.match(r"^https?://", definition.url):
            raise ValueError("an http connector needs an http(s) URL")
        if definition.transport not in ("stdio", "http"):
            raise ValueError("transport must be 'stdio' or 'http'")
        stored = {k: v for k, v in definition.public().items() if k not in ("custom", "header_names")}
        self.store.set_setting("custom_connectors", [*self.store.get_setting("custom_connectors", []),
                                                     stored | {"headers": definition.headers}])
        return definition

    async def remove_custom(self, cid: str) -> None:
        definition = self.get(cid)
        if definition is None or not definition.custom:
            raise ValueError("only connectors you added can be removed")
        await self.stop(cid)
        self.store.set_setting("custom_connectors",
                               [c for c in self.store.get_setting("custom_connectors", []) if c["id"] != cid])
        for secret in definition.secrets:
            self.secrets.delete(self._secret_key(cid, secret["name"]))
        all_configs = self.store.get_setting("connectors", {})
        all_configs.pop(cid, None)
        self.store.set_setting("connectors", all_configs)

    @staticmethod
    def _secret_key(cid: str, name: str) -> str:
        return f"connector:{cid}:{name}"

    # ------------------------------------------------------------------ tools
    def tools(self) -> list[Tool]:
        return [t for c in self.connections.values() if c.status == "running" for t in c.tools]

    # ------------------------------------------------------------------ lifecycle
    def _fill(self, text: str, values: dict[str, str]) -> str:
        return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: values.get(m.group(1), m.group(0)), text)

    def _client(self, definition: ConnectorDef) -> McpClient:
        data = self.data_dir / definition.id  # a connector's own files (e.g. the memory server's graph)
        data.mkdir(parents=True, exist_ok=True)
        values = {"workspace": str(self.workspace), "data": str(data)}
        missing = []
        for secret in definition.secrets:
            value = self.secrets.get(self._secret_key(definition.id, secret["name"]))
            if value:
                values[secret["name"]] = value
            elif not secret.get("optional"):
                missing.append(secret.get("label") or secret["name"])
        if missing:
            raise McpError("needs " + ", ".join(missing))
        if definition.transport == "http":
            headers = {k: self._fill(v, values) for k, v in definition.headers.items()}
            return McpClient(HttpTransport(self._fill(definition.url, values), headers))
        env = {k: self._fill(v, values) for k, v in definition.env.items()}
        env |= {s["name"]: values[s["name"]] for s in definition.secrets if s["name"] in values}
        return McpClient(StdioTransport(definition.command, [self._fill(a, values) for a in definition.args], env=env,
                                        cwd=str(self.workspace)))

    async def start(self, cid: str) -> Connection:
        definition = self.get(cid)
        if definition is None:
            raise KeyError(cid)
        await self.stop(cid)
        conn = self.connections[cid] = Connection(status="starting")
        try:
            conn.client = self._client(definition)
            await asyncio.wait_for(conn.client.start(), timeout=START_TIMEOUT_S)
            specs = await conn.client.list_tools()
        except (McpError, TimeoutError, OSError) as exc:
            conn.status, conn.error = "error", str(exc) or exc.__class__.__name__
            if conn.client:
                detail = conn.client.transport.diagnostics()
                if detail and detail not in conn.error:
                    conn.error += "\n" + detail[-800:]
                await conn.client.close()
            conn.client = None
            return conn
        policy = self.config(cid)["policy"]
        names: set[str] = set()
        for spec in specs:
            name = tool_name(cid, spec["name"])
            while name in names:
                name = name[:60] + f"_{len(names)}"
            names.add(name)
            conn.tools.append(McpTool(definition, conn.client, spec, name, policy))
        conn.status, conn.error = "running", None
        return conn

    async def stop(self, cid: str) -> None:
        conn = self.connections.pop(cid, None)
        if conn and conn.client:
            await conn.client.close()

    async def ensure_started(self) -> None:
        """Start enabled connectors not tried yet in this process; failed ones wait for the user to retry."""
        async with self._lock:
            for definition in self.definitions():
                if self.config(definition.id)["enabled"] and definition.id not in self.connections:
                    await self.start(definition.id)

    async def update(self, cid: str, enabled: bool | None = None, policy: str | None = None,
                     secrets: dict[str, str] | None = None) -> None:
        definition = self.get(cid)
        if definition is None:
            raise KeyError(cid)
        if policy is not None:
            if policy not in POLICIES:
                raise ValueError(f"policy must be one of {POLICIES}")
            self._save_config(cid, policy=policy)
            for tool in self.connections.get(cid, Connection()).tools:
                tool.default_policy = policy  # type: ignore[assignment]
        allowed = {s["name"] for s in definition.secrets}
        for name, value in (secrets or {}).items():
            if name not in allowed:
                raise ValueError(f"'{name}' is not a setting of this connector")
            if value:
                self.secrets.set(self._secret_key(cid, name), value)
            else:
                self.secrets.delete(self._secret_key(cid, name))
        if enabled is not None:
            self._save_config(cid, enabled=enabled)
        async with self._lock:
            if self.config(cid)["enabled"] and (enabled or secrets or cid not in self.connections):
                await self.start(cid)
            elif not self.config(cid)["enabled"]:
                await self.stop(cid)

    async def close_all(self) -> None:
        for cid in list(self.connections):
            await self.stop(cid)

    # ------------------------------------------------------------------ API view
    def public(self, definition: ConnectorDef, broker_policy=None) -> dict[str, Any]:
        conn = self.connections.get(definition.id, Connection())
        cfg = self.config(definition.id)
        values = {"workspace": str(self.workspace), "data": str(self.data_dir / definition.id)}
        preview = (self._fill(definition.url, values) if definition.transport == "http"
                   else " ".join([definition.command, *(self._fill(a, values) for a in definition.args)]))
        return definition.public() | {
            "preview": preview, "enabled": cfg["enabled"], "policy": cfg["policy"], "status": conn.status, "error": conn.error,
            "secrets_set": {s["name"]: self.secrets.has(self._secret_key(definition.id, s["name"]))
                            for s in definition.secrets},
            "tools": [{"name": t.name, "remote_name": t.remote_name, "description": t.description,
                       "policy": broker_policy(t) if broker_policy else t.default_policy} for t in conn.tools],
        }
