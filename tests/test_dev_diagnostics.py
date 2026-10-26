"""A5: explicit audits, local license metadata and deterministic checks in an offline browser fixture."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from spike.connectors.mcp import CallResult
from spike.dev.diagnostics import DependencyDoctor, VisualCritic, license_report
from spike.dev.tools import dev_tools
from spike.tools.base import PermissionBroker
from spike.tools.builtin import Workspace
from spike.tools.sandbox import Sandbox


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path)


async def test_fake_pip_audit_binary_merges_licenses(ws, monkeypatch):
    binary = ws.root / ('pip-audit.cmd' if os.name == 'nt' else 'pip-audit')
    script = ws.root / 'audit.py'
    script.write_text('import json, sys\nfrom pathlib import Path\n'
                      'Path("called").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")\n'
                      'print(json.dumps({"dependencies": [{"name": "demo", "version": "1", '
                      '"vulns": [{"id": "TEST-1"}]}]}))\nsys.exit(1)\n', encoding='utf-8')
    binary.write_text(f'@"{sys.executable}" "{script}" %*\n' if os.name == 'nt' else
                      f'#!{sys.executable}\nexec(compile(open({str(script)!r}, encoding="utf-8").read(), "audit", "exec"))\n',
                      encoding='utf-8')
    if os.name != 'nt':
        binary.chmod(0o755)
    monkeypatch.setattr('spike.dev.diagnostics.shutil.which', lambda name: str(binary) if name == 'pip-audit' else None)
    (ws.root / 'requirements.txt').write_text('demo==1\n', encoding='utf-8')
    (ws.root / 'package-lock.json').write_text(json.dumps({'packages': {'node_modules/demo': {'license': 'MIT'}}}),
                                              encoding='utf-8')
    tool = DependencyDoctor(ws, Sandbox('off'))
    assert not (ws.root / 'called').exists()
    policy, review = PermissionBroker({'dependency_doctor': 'allow'}).policy_for_call(tool, {})
    assert policy == 'ask' and review.once
    result = await tool.run({})
    assert result.ok
    report = result.data['ui']
    assert report['kind'] == 'dev_diagnostic' and report['audits'][0]['status'] == 'findings'
    assert report['audits'][0]['result']['dependencies'][0]['vulns'][0]['id'] == 'TEST-1'
    assert report['licenses'][0]['status'] == 'allowed'
    assert json.loads((ws.root / 'called').read_text(encoding='utf-8')) == ['-r', 'requirements.txt', '--format', 'json', '--no-deps', '--disable-pip']


async def test_missing_auditors_invalid_json_and_no_manifests(ws, monkeypatch):
    monkeypatch.setattr('spike.dev.diagnostics.shutil.which', lambda _: None)
    (ws.root / 'requirements.txt').touch()
    (ws.root / 'package-lock.json').write_text('{}', encoding='utf-8')
    result = await DependencyDoctor(ws).run({})
    assert {a['status'] for a in result.data['ui']['audits']} == {'missing'}
    (ws.root / 'package-lock.json').write_text('broken', encoding='utf-8')
    assert license_report(ws)[0]['status'] == 'error'
    (ws.root / 'package-lock.json').unlink()
    (ws.root / 'requirements.txt').unlink()
    assert {a['status'] for a in (await DependencyDoctor(ws).run({})).data['ui']['audits']} == {'not_applicable'}


def test_license_metadata_unknown_and_escape(ws, tmp_path):
    (ws.root / 'package-lock.json').write_text(json.dumps({'packages': {'a': {'license': 'GPL-3.0'}, 'b': {}}}), encoding='utf-8')
    assert [r['status'] for r in license_report(ws)] == ['review', 'unknown']
    outside = tmp_path.parent / f'{tmp_path.name}-outside.json'
    outside.write_text('{}', encoding='utf-8')
    (ws.root / 'package-lock.json').unlink()
    try:
        (ws.root / 'package-lock.json').symlink_to(outside)
    except OSError:
        pytest.skip('symlinks unavailable')
    assert license_report(ws)[0]['status'] == 'error'


class Browser:
    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if name == 'browser_evaluate':
            return CallResult('### Result\n' + json.dumps({'url': 'about:blank', 'issues': [{'code': 'alt', 'selector': '#photo'}]}), False)
        return CallResult('', False, {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': 'cG5n'}]})


async def test_critic_reuses_running_view_and_returns_screenshot(ws):
    client = Browser()
    manager = SimpleNamespace(connections={'playwright': SimpleNamespace(status='running', client=client)},
                              config=lambda _: {'enabled': True, 'policy': 'ask'})
    tool = VisualCritic(ws, manager)
    assert tool.review({}).once and tool.default_policy == 'ask'
    result = await tool.run({})
    assert result.ok and result.data['ui']['screenshot'] == 'data:image/png;base64,cG5n'
    assert result.data['ui']['issues'][0]['selector'] == '#photo'
    assert [c[0] for c in client.calls] == ['browser_evaluate', 'browser_take_screenshot']
    manager.connections.clear()
    assert not (await tool.run({})).ok
    assert {'dependency_doctor', 'visual_critic'} <= {t.name for t in dev_tools(ws, connectors=manager)}


async def test_critic_finds_every_planted_issue_offline(ws):
    from spike.dev.diagnostics import CHECKS

    playwright = pytest.importorskip('playwright.async_api')
    async with playwright.async_playwright() as pw:
        executable = os.environ.get('SPIKE_CHROMIUM') or pw.chromium.executable_path
        if not Path(executable).is_file():
            pytest.skip('needs installed Chromium or SPIKE_CHROMIUM; never downloaded by tests')
        browser = await pw.chromium.launch(headless=True, executable_path=executable)
        try:
            page = await browser.new_page(viewport={'width': 800, 'height': 600})
            await page.route('**/*', lambda route: route.abort())
            await page.set_content('''<body style="background:white;color:black">
<p id="contrast" style="color:#aaa">Low contrast</p>
<p id="large" style="font-size:24px;color:#aaa">Large contrast</p>
<img id="photo" width="30" height="30"><img id="decorative" alt="" width="30" height="30">
<input id="unnamed" style="width:100px;height:30px"><label for="named">Name</label><input id="named">
<div id="overflow" style="position:absolute;left:810px;width:30px;height:30px"></div>
<button id="tiny" aria-label="Close" style="width:15px;height:15px;padding:0;border:0"></button>
<button id="good" style="width:50px;height:30px">OK</button>
<div hidden><button id="hidden"></button></div></body>''')
            result = await page.evaluate(CHECKS)
            issues = {(i['code'], i['selector']) for i in result['issues']}
            assert {('contrast', '#contrast'), ('contrast', '#large'), ('alt', '#photo'),
                    ('label', '#unnamed'), ('overflow', '#overflow'), ('tap', '#tiny')} <= issues
            assert not any(selector in {'#good', '#hidden', '#decorative'} for _, selector in issues)
            assert await page.screenshot(type='png')
        finally:
            await browser.close()


@pytest.mark.parametrize('contents', ['-r ../secret.txt', 'demo @ file:///private/secret', '-e .', '--index-url https://private.test', 'demo>=1'])
async def test_doctor_refuses_requirements_that_can_resolve_or_read_outside_workspace(ws, monkeypatch, contents):
    monkeypatch.setattr('spike.dev.diagnostics.shutil.which', lambda _: pytest.fail('unsafe requirements must not run'))
    (ws.root / 'requirements.txt').write_text(contents, encoding='utf-8')
    result = await DependencyDoctor(ws).run({})
    assert result.data['ui']['audits'][0]['status'] == 'unsupported_requirements'


async def test_doctor_confines_subfolder_and_handles_invalid_auditor_results(ws, monkeypatch):
    from spike.dev.tools import RunCommand
    from spike.tools.base import ToolResult

    monkeypatch.setattr('spike.dev.diagnostics.shutil.which', lambda _: 'fake-npm')
    folder = ws.root / 'web'
    folder.mkdir()
    (folder / 'package-lock.json').write_text('{}', encoding='utf-8')
    calls = []

    async def run(self, args):
        calls.append((self.workspace.root, args['command']))
        return ToolResult(ok=True, content='exit code 0\n{"error": {"code": "FAIL"}}')

    monkeypatch.setattr(RunCommand, 'run', run)
    result = await DependencyDoctor(ws).run({'path': 'web'})
    assert result.data['ui']['audits'][1]['status'] == 'error'
    assert calls[0][0] == folder
    assert 'audit --json --ignore-scripts --package-lock-only' in calls[0][1]
    assert not (await DependencyDoctor(ws).run({'path': '..'})).ok


async def test_critic_reports_mcp_failure_missing_screenshot_and_respects_blocked_connector(ws):
    client = Browser()
    manager = SimpleNamespace(connections={'playwright': SimpleNamespace(status='running', client=client)},
                              config=lambda _: {'policy': 'deny'})
    assert not (await VisualCritic(ws, manager).run({})).ok and not client.calls
    manager.config = lambda _: {'policy': 'ask'}

    async def fail(name, args):
        return CallResult('error with private data', True)

    client.call_tool = fail
    result = await VisualCritic(ws, manager).run({})
    assert not result.ok and 'private data' not in result.content

    async def no_image(name, args):
        return CallResult('{"issues": []}', False)

    client.call_tool = no_image
    assert not (await VisualCritic(ws, manager).run({})).ok


def test_diagnostics_registered_for_app_and_project(tmp_path, monkeypatch):
    from spike.server.state import AppState

    monkeypatch.setenv('SPIKE_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SPIKE_WORKSPACE', str(tmp_path / 'ws'))
    monkeypatch.setenv('SPIKE_NO_KEYRING', '1')
    state = AppState(home=tmp_path / 'home')
    project = state.store.create_project('Example')
    for registry in (state.tools, state.tools_for(project['id'])):
        assert registry.get('dependency_doctor').default_policy == 'ask'
        assert 'dependency_doctor' in state.catalog.get('code').tools
        assert 'visual_critic' in state.catalog.get('core').tools
        assert registry.get('visual_critic').connectors is state.connectors


@pytest.mark.parametrize('exit_code,body,expected', [
    (0, '{"vulnerabilities": {}}', 'complete'),
    (1, '{"vulnerabilities": {"demo": {"severity": "high"}}}', 'findings'),
    (0, 'not json', 'error'),
    (0, '[]', 'error'),
    (2, '{"vulnerabilities": {}}', 'error'),
])
async def test_npm_results_are_distinguished_from_incomplete_audits(ws, monkeypatch, exit_code, body, expected):
    from spike.dev.tools import RunCommand
    from spike.tools.base import ToolResult

    (ws.root / 'package-lock.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr('spike.dev.diagnostics.shutil.which', lambda _: 'npm')

    async def run(self, args):
        return ToolResult(ok=exit_code == 0, content=f'exit code {exit_code}\n{body}')

    monkeypatch.setattr(RunCommand, 'run', run)
    result = await DependencyDoctor(ws).run({})
    assert result.data['ui']['audits'][1]['status'] == expected
    assert result.private == [result.content]


async def test_denial_and_headless_call_never_run_auditors(ws, monkeypatch):
    from spike.agent.loop import AgentRun, run_agent
    from spike.core.types import Message
    from spike.tools.base import HeadlessBroker
    from tests.helpers import ScriptedProvider, call, text

    monkeypatch.setattr('spike.dev.diagnostics.shutil.which', lambda _: pytest.fail('denied auditor ran'))
    tool = DependencyDoctor(ws, Sandbox('off'))
    for broker in (PermissionBroker(), HeadlessBroker(PermissionBroker())):
        results = []
        async for ev in run_agent(ScriptedProvider([call(tool.name, {}), text('done')]),
                                  [Message(role='user', content='audit')], tools=[tool], broker=broker, run=AgentRun()):
            if ev['type'] == 'permission_request':
                broker.resolve(ev['id'], 'deny')
            if ev['type'] == 'tool_result':
                results.append(ev)
        assert len(results) == 1 and not results[0]['ok']
