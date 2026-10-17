"""Specialist catalog loading and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = Path(__file__).with_name("catalog.yaml")
ADAPTER_STATUSES = {"none", "planned", "training", "trained", "evaluated"}


@dataclass
class Specialist:
    id: str
    name: str
    domain: str
    description: str
    system_prompt: str
    adapter: str | None = None
    adapter_status: str = "none"
    sensitive: bool = False
    tools: list[str] = field(default_factory=list)
    keywords: dict[str, float] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "description": self.description,
            "adapter": self.adapter,
            "adapter_status": self.adapter_status,
            "sensitive": self.sensitive,
            "tools": self.tools,
        }


@dataclass
class Catalog:
    base_model: str
    specialists: dict[str, Specialist]

    @property
    def core(self) -> Specialist:
        return self.specialists["core"]

    def get(self, specialist_id: str) -> Specialist:
        try:
            return self.specialists[specialist_id]
        except KeyError as exc:
            raise KeyError(f"Unknown specialist '{specialist_id}'") from exc


def load_catalog(path: Path | None = None, extra: list[dict[str, Any]] | None = None) -> Catalog:
    """Load the built-in catalog, then user-defined specialists (which may override built-ins by id)."""
    raw = yaml.safe_load((path or CATALOG_PATH).read_text(encoding="utf-8"))
    entries = list(raw.get("specialists", [])) + list(extra or [])
    specialists: dict[str, Specialist] = {}
    for entry in entries:
        spec = Specialist(
            id=str(entry["id"]),
            name=str(entry["name"]),
            domain=str(entry.get("domain", "")),
            description=str(entry.get("description", "")),
            system_prompt=str(entry["system_prompt"]).strip(),
            adapter=entry.get("adapter"),
            adapter_status=str(entry.get("adapter_status", "none")),
            sensitive=bool(entry.get("sensitive", False)),
            tools=list(entry.get("tools", [])),
            keywords={str(k).lower(): float(v) for k, v in (entry.get("keywords") or {}).items()},
        )
        if spec.adapter_status not in ADAPTER_STATUSES:
            raise ValueError(f"{spec.id}: invalid adapter_status '{spec.adapter_status}'")
        specialists[spec.id] = spec
    if "core" not in specialists:
        raise ValueError("Catalog must define a 'core' specialist")
    return Catalog(base_model=str(raw.get("base_model", "")), specialists=specialists)
