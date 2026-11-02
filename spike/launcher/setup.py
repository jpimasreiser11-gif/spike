"""Explicit first-run installation. Only reviewed, published artifacts from the bundled manifest are selectable.

The catalog currently lists planned adapters, so the manifest is empty until Claude publishes measured weights.
No metadata request occurs on status reads. Base weights reuse the CLI installer's Hub license and SHA checks;
release adapters require immutable Hub revisions, known sizes, allowed licenses and SHA-256 in the manifest.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import httpx
import psutil

from spike.runtime import models
from spike.runtime.hardware import GIB
from spike.specialists.catalog import load_catalog


class Setup:
    def __init__(self, state, artifacts: dict | None = None):
        self.state = state
        self.artifacts = artifacts if artifacts is not None else json.loads(
            Path(__file__).with_name("adapters.json").read_text(encoding="utf-8"))
        catalog = load_catalog()
        for sid, item in self.artifacts.items():
            spec = catalog.specialists.get(sid)
            if (not spec or item.get("filename") != f"{spec.adapter}.gguf"
                    or not re.fullmatch(r"[\w.-]+/[\w.-]+", item.get("repo", ""))
                    or not re.fullmatch(r"[0-9a-f]{40}", item.get("revision", ""))
                    or not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", ""))
                    or item.get("license") not in models.ALLOWED_LICENSES
                    or not isinstance(item.get("size"), int) or item["size"] <= 0):
                raise ValueError("Invalid published adapter manifest")
        self.job = {"status": "idle", "file": "", "done": 0, "total": 0}

    def complete(self) -> bool:
        marker = self.state.home / "setup.json"
        try:
            files = json.loads(marker.read_text(encoding="utf-8"))["files"]
            root = self.state.home.resolve()
            return bool(files) and all(Path(p).resolve().is_relative_to(root) and Path(p).is_file() for p in files)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def resources(self, selected=()) -> dict:
        mem = psutil.virtual_memory()
        # Conservative reservation, not a performance claim: base GGUF + partial/previous copy + headroom.
        required = 6 * GIB + sum(self.artifacts[s]["size"] * 2 for s in selected)
        free = shutil.disk_usage(self.state.home).free
        return {"disk_free": free, "ram_total": mem.total, "ram_available": mem.available,
                "required_disk": required, "required_ram": 8 * GIB,
                "can_download": free >= required and mem.total >= 8 * GIB}

    def status(self) -> dict:
        return {"enabled": True, "complete": self.complete(), "job": self.job, **self.resources(),
                "specialists": [{"id": s.id, "name": s.name, "available": s.id in self.artifacts}
                                for s in load_catalog().specialists.values() if s.adapter]}

    async def install(self, selected: list[str]) -> None:
        self.job.update(status="running", file="", done=0, total=0)

        def progress(done, total):
            self.job.update(done=done, total=total)

        try:
            self.job["file"] = "qwen3.5-4b"
            base, verified = await models.download("qwen3.5-4b", dest_dir=self.state.home / "models",
                                                   progress=progress, require_hash=True)
            if not verified:
                raise ValueError("Unverified base model")
            paths = []
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=300), follow_redirects=True) as client:
                for sid in selected:
                    item = self.artifacts[sid]
                    self.job.update(file=sid, done=0, total=item["size"])
                    dest = self.state.home / "adapters" / item["filename"]
                    url = f"{models.HF}/{item['repo']}/resolve/{item['revision']}/{item['filename']}"
                    await models.download_file(client, url, dest, item["sha256"], item["size"], progress)
                    paths.append(dest.as_posix())
            cfg = dict(self.state.settings()["local_runtime"])
            cfg.update(model=base.as_posix(), adapters=list(dict.fromkeys([*cfg.get("adapters", []), *paths])))
            self.state.update_settings({"local_runtime": cfg})
            marker = self.state.home / "setup.json"
            temp = marker.with_suffix(".json.tmp")
            temp.write_text(json.dumps({"files": [base.as_posix(), *paths]}, ensure_ascii=True), encoding="utf-8")
            temp.replace(marker)
            self.job["status"] = "done"
        except (httpx.HTTPError, OSError, ValueError, KeyError, PermissionError):
            # No remote URLs, credentials or raw exception bodies in the UI/status records.
            self.job["status"] = "failed"
