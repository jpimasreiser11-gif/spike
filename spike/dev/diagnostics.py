"""On-demand developer diagnostics. Auditors are optional installed programs, never installed or run at startup.

The Visual Critic uses View's already running Playwright MCP connection and its current page, without navigation.
Reports are structured UI data (including an inline screenshot), kept private from external providers just like
file contents. Contrast covers computed solid colors in the light DOM; it is not a complete accessibility audit.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from spike.connectors.manager import ConnectorManager
from spike.connectors.mcp import McpError
from spike.dev.tools import RunCommand
from spike.runtime.models import ALLOWED_LICENSES
from spike.tools.base import Review, Tool, ToolResult
from spike.tools.builtin import Workspace
from spike.tools.sandbox import Sandbox, strip_note

CHECKS = Path(__file__).with_name('visual_checks.js').read_text(encoding='utf-8')
LICENSES = ALLOWED_LICENSES | {'bsd-2-clause', 'isc'}


def license_report(workspace: Workspace) -> list[dict[str, Any]]:
    """Review npm lock metadata locally using SPIKE's existing license allowlist; unknown is never approved.

    This checkout has no dependency-license checker: the existing allowlist gates model downloads. Here it is
    reused conservatively for exact license identifiers, not SPDX expressions. Python requirements lack license
    metadata, so their license remains unknown. No registry lookups, installs or importing project code.
    """
    rows = []
    try:
        lock = workspace.resolve('package-lock.json')
        if lock.is_file():
            packages = json.loads(lock.read_text(encoding='utf-8')).get('packages', {})
            for name, package in sorted(packages.items()):
                value = package.get('license')
                rows.append({'package': name or '.', 'license': value if isinstance(value, str) else '',
                             'status': 'unknown' if not value else
                             'allowed' if isinstance(value, str) and value.lower() in LICENSES else 'review'})
        requirements = workspace.resolve('requirements.txt')
        if requirements.is_file():
            rows.append({'package': 'requirements.txt', 'license': '', 'status': 'unknown'})
    except (OSError, PermissionError, ValueError, AttributeError, TypeError):
        rows.append({'package': 'package-lock.json / requirements.txt', 'license': '', 'status': 'error'})
    return rows


def report_result(report: dict[str, Any]) -> ToolResult:
    content = json.dumps({k: v for k, v in report.items() if k != 'screenshot'}, ensure_ascii=True)
    return ToolResult(ok=True, content=content, private=[content], data={'ui': {'kind': 'dev_diagnostic', **report}})


class DependencyDoctor(RunCommand):
    name = 'dependency_doctor'
    description = ('On explicit user request, audit workspace requirements.txt and package-lock.json with installed '
                   'pip-audit / npm audit, and review local license metadata. Asks every time: audits contact registries '
                   'and send dependency names/versions. Never installs tools, dependencies or fixes.')
    parameters = {'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'Workspace subfolder; default .'}}}

    def review(self, args: dict[str, Any]) -> Review:
        refused = super().review(args)
        return refused or Review('ask', 'Audits contact registries and send dependency names and versions.',
                                  once=True, code='dependency_doctor')

    async def run(self, args: dict[str, Any]) -> ToolResult:
        try:
            workspace = Workspace(self.workspace.resolve(str(args.get('path') or '.')))
            if not workspace.root.is_dir():
                raise ValueError
        except (PermissionError, ValueError, OSError):
            return ToolResult(ok=False, content='Invalid workspace folder. / Carpeta de trabajo no válida.')
        runner = RunCommand(workspace, self.sandbox)
        audits = []
        for name, manifest, options in (
            ('pip-audit', 'requirements.txt', ['-r', 'requirements.txt', '--format', 'json', '--no-deps', '--disable-pip']),
            ('npm', 'package-lock.json', ['audit', '--json', '--ignore-scripts', '--package-lock-only']),
        ):
            row: dict[str, Any] = {'tool': name, 'status': 'not_applicable'}
            audits.append(row)
            try:
                path = workspace.resolve(manifest)
                if not path.is_file():
                    continue
                if name == 'pip-audit':
                    # No includes, local paths, editable installs or URLs: audit exact pins without invoking pip.
                    lines = [line.split('#', 1)[0].strip() for line in path.read_text(encoding='utf-8').splitlines()]
                    if any(line and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+!-]*', line)
                           for line in lines):
                        row['status'] = 'unsupported_requirements'
                        continue
                exe = shutil.which(name)
                if not exe:
                    row['status'] = 'missing'
                    continue
                command = [exe, *options]
                result = await runner.run({'command': subprocess.list2cmdline(command) if os.name == 'nt' else
                                           shlex.join(command), 'timeout_s': 120})
                output = strip_note(result.content)
                first, _, body = output.partition('\n')
                if first not in ('exit code 0', 'exit code 1'):
                    row['status'] = 'error'
                    continue
                payload = json.loads(body)
                if not isinstance(payload, dict) or payload.get('error') or not (
                    isinstance(payload.get('dependencies'), list) if name == 'pip-audit' else
                    isinstance(payload.get('vulnerabilities'), dict) or isinstance(payload.get('advisories'), dict)
                ):
                    row['status'] = 'error'
                    continue
                row.update(status='complete' if result.ok else 'findings', result=payload)
            except (OSError, PermissionError, ValueError):
                row['status'] = 'error'
        return report_result({'report': 'dependencies', 'audits': audits, 'licenses': license_report(workspace)})


class VisualCritic(Tool):
    name = 'visual_critic'
    description = ('On user request, inspect and screenshot the current page in the already running Spike View '
                   'browser. Deterministic partial checks: contrast, alt, labels, horizontal overflow and targets '
                   'under 24 px. Does not navigate, start browsers, install tools or use a model.')
    parameters = {'type': 'object', 'properties': {}}
    risk = 'execute'
    default_policy = 'ask'

    def __init__(self, workspace: Workspace, connectors: ConnectorManager | None = None):
        self.workspace, self.connectors = workspace, connectors

    def review(self, args: dict[str, Any]) -> Review:
        return Review('ask', 'Inspects and screenshots the current View page.', once=True, code='visual_critic')

    async def run(self, args: dict[str, Any]) -> ToolResult:
        conn = self.connectors.connections.get('playwright') if self.connectors else None
        if not conn or conn.status != 'running' or not conn.client:
            return ToolResult(ok=False, content='Open Spike View first. / Abre Spike View primero.')
        if self.connectors.config('playwright').get('policy') == 'deny':
            return ToolResult(ok=False, content='View is blocked. / View está bloqueado.')
        try:
            result = await conn.client.call_tool('browser_evaluate', {'function': CHECKS})
            if result.is_error:
                raise ValueError
            # MCP versions wrap the JSON in a "### Result" section; keep only that section.
            text = result.text.removeprefix('### Result\n').split('\n### ')[0].strip()
            report = json.loads(text)
            if not isinstance(report, dict) or not isinstance(report.get('issues'), list):
                raise ValueError
            shot = await conn.client.call_tool('browser_take_screenshot', {'type': 'png', 'fullPage': True})
            blocks = (shot.raw or {}).get('content', [])
            png = next((b['data'] for b in blocks if b.get('type') == 'image' and b.get('mimeType') == 'image/png'), None)
            if shot.is_error or not png:
                raise ValueError
            return report_result({**report, 'report': 'visual', 'screenshot': f'data:image/png;base64,{png}'})
        except (McpError, ValueError, KeyError, TypeError):
            return ToolResult(ok=False, content='View checks or screenshot unavailable. / No se pudo revisar o capturar View.')


def diagnostic_tools(workspace: Workspace, sandbox: Sandbox | None = None,
                     connectors: ConnectorManager | None = None) -> list[Tool]:
    return [DependencyDoctor(workspace, sandbox), VisualCritic(workspace, connectors)]
