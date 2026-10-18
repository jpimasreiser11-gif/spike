"""Hatch build hook: ship the built web app inside the wheel.

Editable installs skip it (the server falls back to web/dist), so Python development and CI do not need
Node.js; a regular wheel refuses to build without the bundle instead of silently shipping no UI."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebBundleHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        dist = Path(self.root, "web", "dist")
        if not (dist / "index.html").is_file():
            raise RuntimeError("web/dist is missing: run `cd web && npm ci && npm run build` before building SPIKE")
        build_data["force_include"][str(dist)] = "spike/server/static"
