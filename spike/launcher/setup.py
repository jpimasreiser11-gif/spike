"""Explicit first-run installation. Only reviewed, published artifacts from the bundled manifest are selectable.

The catalog currently lists planned adapters, so the manifest is empty until Claude publishes measured weights.
No metadata request occurs on status reads. Base weights reuse the CLI installer's Hub license and SHA checks;
release adapters require immutable Hub revisions, known sizes, allowed licenses and SHA-256 in the manifest.
"""

from __future__ import annotations

import errno
import json
import re
import shutil
from pathlib import Path

import httpx
import psutil

from spike.runtime import models
from spike.runtime.hardware import GIB
from spike.specialists.catalog import load_catalog

SETUP_MESSAGES: dict[str, dict[str, str]] = {
    "no_model": {
        "es": "Aún no hay ningún modelo local instalado. Puedes descargarlo ahora, usar un proveedor de API externo o importar un archivo .gguf local.",
        "en": "No local model is installed yet. You can download it now, use an external API provider, or import a local .gguf file.",
    },
    "ready": {
        "es": "Listo para descargar el modelo base y los adaptadores seleccionados con verificación de licencia y SHA-256.",
        "en": "Ready to download the base model and selected adapters with license and SHA-256 verification.",
    },
    "done": {
        "es": "Modelo local preparado y verificado.",
        "en": "Local model ready and verified.",
    },
    "offline": {
        "es": "Sin conexión a internet para descargar el modelo. Comprueba tu red y reintenta, usa una API externa o importa un archivo .gguf local.",
        "en": "No internet connection to download the model. Check your network and retry, use an external API, or import a local .gguf file.",
    },
    "disk": {
        "es": "Espacio en disco o memoria RAM insuficiente para descargar el modelo. Libera espacio en disco y reintenta, usa una API externa o importa un archivo .gguf local.",
        "en": "Not enough disk space or RAM to download the model. Free up disk space and retry, use an external API, or import a local .gguf file.",
    },
    "interrupted": {
        "es": "La descarga se cortó a mitad. El archivo parcial se ha conservado; pulsa Reanudar descarga para continuar desde donde se quedó, usa una API externa o importa un archivo .gguf local.",
        "en": "The download was cut midway. The partial file was kept; click Resume download to continue where it left off, use an external API, or import a local .gguf file.",
    },
    "checksum": {
        "es": "El SHA-256 del archivo no coincide con el esperado y se ha descartado por seguridad. Reintenta la descarga, usa una API externa o importa un archivo .gguf local verificado.",
        "en": "The file's SHA-256 did not match the expected hash and was discarded for safety. Retry the download, use an external API, or import a verified local .gguf file.",
    },
    "license": {
        "es": "La licencia o el SHA-256 del repositorio remoto no cumplen los requisitos de instalación verificada. Usa una API externa o importa un archivo .gguf local.",
        "en": "The remote repository's license or SHA-256 does not meet verified installation requirements. Use an external API or import a local .gguf file.",
    },
    "import_invalid": {
        "es": "No se pudo importar el archivo .gguf local. Comprueba que la ruta existe, termina en .gguf y no es un enlace simbólico.",
        "en": "Could not import the local .gguf file. Check that the path exists, ends with .gguf, and is not a symlink.",
    },
    "failed": {
        "es": "La instalación falló. Puedes reintentar o reanudar la descarga, usar una API externa o importar un archivo .gguf local.",
        "en": "Installation failed. You can retry or resume the download, use an external API, or import a local .gguf file.",
    },
}


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
        self.job = {
            "status": "idle",
            "file": "",
            "done": 0,
            "total": 0,
            "reason": "",
            "resumable": False,
            "message": dict(SETUP_MESSAGES["no_model"]),
        }

    def complete(self) -> bool:
        marker = self.state.home / "setup.json"
        try:
            files = json.loads(marker.read_text(encoding="utf-8"))["files"]
            root = self.state.home.resolve()
            return bool(files) and all(Path(p).resolve().is_relative_to(root) and Path(p).is_file() for p in files)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _part_bytes(self) -> int:
        total = 0
        for folder in (self.state.home / "models", self.state.home / "adapters"):
            if folder.is_dir():
                for part in folder.glob("*.part"):
                    try:
                        if part.is_file() and not part.is_symlink():
                            total += part.stat().st_size
                    except OSError:
                        pass
        return total

    def has_local_model(self) -> bool:
        if self.complete():
            return True
        try:
            cfg_model = (self.state.settings().get("local_runtime") or {}).get("model")
            if cfg_model and Path(cfg_model).is_file():
                return True
        except Exception:
            pass
        models_folder = self.state.home / "models"
        return models_folder.is_dir() and any(p.is_file() for p in models_folder.glob("*.gguf"))

    def resources(self, selected=()) -> dict:
        mem = psutil.virtual_memory()
        # Conservative reservation, not a performance claim: base GGUF + partial/previous copy + headroom.
        required = 6 * GIB + sum(self.artifacts[s]["size"] * 2 for s in selected)
        free = shutil.disk_usage(self.state.home).free
        low_disk = free < required
        low_ram = mem.total < 8 * GIB
        return {
            "disk_free": free,
            "ram_total": mem.total,
            "ram_available": mem.available,
            "required_disk": required,
            "required_ram": 8 * GIB,
            "low_disk": low_disk,
            "low_ram": low_ram,
            "can_download": not low_disk and not low_ram,
        }

    def status(self) -> dict:
        res = self.resources()
        is_complete = self.complete()
        has_model = self.has_local_model()
        part_bytes = self._part_bytes()
        if is_complete:
            messages = dict(SETUP_MESSAGES["done"])
        elif self.job.get("status") == "failed" and self.job.get("reason") in SETUP_MESSAGES:
            messages = dict(SETUP_MESSAGES[self.job["reason"]])
        elif not res["can_download"]:
            messages = dict(SETUP_MESSAGES["disk"])
        elif part_bytes > 0:
            messages = dict(SETUP_MESSAGES["interrupted"])
        else:
            messages = dict(SETUP_MESSAGES["no_model"])
        return {
            "enabled": True,
            "complete": is_complete,
            "has_local_model": has_model,
            "part_bytes": part_bytes,
            "messages": messages,
            "job": self.job,
            **res,
            "specialists": [
                {"id": s.id, "name": s.name, "available": s.id in self.artifacts}
                for s in load_catalog().specialists.values()
                if s.adapter
            ],
        }

    @staticmethod
    def _classify_failure(exc: BaseException, part_bytes: int) -> tuple[str, bool]:
        msg = str(exc).lower()
        if isinstance(exc, PermissionError) or "license" in msg:
            return "license", False
        if isinstance(exc, ValueError):
            if "checksum mismatch" in msg or "invalid sha-256" in msg or "unverified" in msg or "sha-256" in msg or "hash" in msg:
                return "checksum", False
            if "incomplete download" in msg or "content-range" in msg:
                return "interrupted", part_bytes > 0
        if isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.ENOSPC:
            return "disk", part_bytes > 0
        if isinstance(exc, (httpx.ReadError, httpx.RemoteProtocolError, httpx.StreamError)):
            return "interrupted", True
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError, httpx.TimeoutException)):
            if part_bytes > 0:
                return "interrupted", True
            return "offline", False
        if isinstance(exc, httpx.HTTPStatusError):
            if part_bytes > 0:
                return "interrupted", True
            return "offline", False
        if part_bytes > 0:
            return "interrupted", True
        return "failed", False

    async def install(self, selected: list[str]) -> None:
        self.job.update(
            status="running",
            file="",
            done=0,
            total=0,
            reason="",
            resumable=False,
            message=dict(SETUP_MESSAGES["ready"]),
        )

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
            self.job.update(
                status="done",
                reason="",
                resumable=False,
                message=dict(SETUP_MESSAGES["done"]),
            )
        except (httpx.HTTPError, OSError, ValueError, KeyError, PermissionError) as exc:
            # No remote URLs, credentials or raw exception bodies in the UI/status records.
            part_bytes = self._part_bytes()
            reason, resumable = self._classify_failure(exc, part_bytes)
            self.job.update(
                status="failed",
                reason=reason,
                resumable=resumable,
                message=dict(SETUP_MESSAGES[reason]),
            )

    def import_local(self, raw_path: str | Path, expected_sha256: str | None = None) -> Path:
        raw = str(raw_path).strip()
        if not raw or ":" in Path(raw).name:
            self.job.update(status="failed", reason="import_invalid", resumable=False,
                            message=dict(SETUP_MESSAGES["import_invalid"]))
            raise ValueError("Invalid local model path")
        src = Path(raw).expanduser()
        if src.is_symlink() or not src.is_file() or src.suffix.lower() != ".gguf" or src.stat().st_size <= 0:
            self.job.update(status="failed", reason="import_invalid", resumable=False,
                            message=dict(SETUP_MESSAGES["import_invalid"]))
            raise ValueError("Invalid local model file")
        digest = models.sha256_file(src)
        if expected_sha256:
            clean_expected = expected_sha256.strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", clean_expected) or digest != clean_expected:
                self.job.update(status="failed", reason="checksum", resumable=False,
                                message=dict(SETUP_MESSAGES["checksum"]))
                raise ValueError(f"checksum mismatch for {src.name}")
        dest_dir = self.state.home / "models"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.is_symlink():
            self.job.update(status="failed", reason="import_invalid", resumable=False,
                            message=dict(SETUP_MESSAGES["import_invalid"]))
            raise ValueError("Refusing symlink destination")
        if src.resolve() != dest.resolve():
            tmp_dest = dest.with_suffix(dest.suffix + ".import.tmp")
            shutil.copy2(src, tmp_dest)
            tmp_dest.replace(dest)
        record = {
            "id": src.stem,
            "repo": "local/import",
            "file": dest.name,
            "quant": "custom",
            "license": "local",
            "size": dest.stat().st_size,
            "sha256": digest,
            "sha256_verified": bool(expected_sha256),
            "unverified": not bool(expected_sha256),
        }
        models.manifest_path(dest).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        cfg = dict(self.state.settings()["local_runtime"])
        cfg["model"] = dest.as_posix()
        self.state.update_settings({"local_runtime": cfg})
        marker = self.state.home / "setup.json"
        temp = marker.with_suffix(".json.tmp")
        temp.write_text(json.dumps({"files": [dest.as_posix()]}, ensure_ascii=True), encoding="utf-8")
        temp.replace(marker)
        self.job.update(
            status="done",
            file=dest.name,
            done=dest.stat().st_size,
            total=dest.stat().st_size,
            reason="",
            resumable=False,
            message=dict(SETUP_MESSAGES["done"]),
        )
        return dest
