"""Public formats use real exporters; sharing excludes private inputs by construction."""

import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import jsonschema
import pytest

from spike import bench
from spike.packs import export_pack
from spike.projects import ProjectFiles, export_project
from spike.proof import build_proof
from spike.store.db import Store

ROOT = Path(__file__).resolve().parents[1]


def validate(name, value):
    schema = json.loads((ROOT / 'docs' / 'schemas' / f'{name}.schema.json').read_text(encoding='utf-8'))
    jsonschema.Draft202012Validator.check_schema(schema)
    assert '/v1/' in schema['$id']
    jsonschema.validate(value, schema)
    broken = dict(value, version=999)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, schema)


def extract(blob, name):
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return json.loads(archive.read(name))


def report():
    return {'hardware': {'cpu_model': 'Apple M4 Max private-user', 'physical_cores': 14,
                         'logical_cores': 14, 'total_ram_gb': 35.7, 'hostname': 'private-host'},
            'model': {'path': '/Users/private-user/private-host/Qwen3.5-4B-Q4_K_M.gguf'},
            'spike_version': '0.1.0', 'llama_cpp_build': {'commit': '620d2225c', 'path': '/secret'},
            'settings': {'server_context': 8192},
            'results': [{'variant': '/secret/adapter', 'prompt_tokens': 1024,
                         'gen_tok_s': {'median': 12.3}, 'ttft_s': {'median': 0.4}}]}


def test_bench_share_is_an_allowlist(monkeypatch):
    monkeypatch.setattr(bench.platform, 'release', lambda: '27.0-private-host')
    shared = bench.share_report(report())
    encoded = json.dumps(shared)
    for secret in ('private-user', 'private-host', '/Users', '/secret', 'hostname', 'adapter'):
        assert secret not in encoded
    assert shared['hardware']['ram_gb'] == 36
    assert shared['model'] == 'Qwen3.5-4B-Q4_K_M'
    validate('bench-share', shared)


def test_cli_share_prints_and_saves_only_shared_data(tmp_path, monkeypatch, capsys):
    from spike.cli import main

    async def fake(args):
        return report()

    monkeypatch.setattr(bench, 'run_benchmark', fake)
    target = tmp_path / 'share.json'
    assert main(['bench', '--model', '/secret/model.gguf', '--share', '--out', str(target)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(target.read_text(encoding='utf-8'))
    assert 'path' not in json.dumps(printed)


def test_pack_schemas_validate_exported_manifests(tmp_path):
    skill = tmp_path / 'sample'
    skill.mkdir()
    (skill / 'SKILL.md').write_text('---\nname: sample\ndescription: Sample\n---\nInstructions', encoding='utf-8')
    for schema, skills in [('specialist-pack', []), ('skill-pack', [skill])]:
        blob = export_pack([{'id': 'example', 'name': 'Example', 'instructions': 'Be precise.'}], [], skills)
        validate(schema, extract(blob, 'pack.json'))


def test_project_schema_validates_export(tmp_path):
    store = Store(tmp_path / 'store.db')
    project = store.create_project('Example')
    conv = store.create_conversation('Example chat', project_id=project['id'])
    store.add_message(conv['id'], 'user', 'Example message')
    validate('project-export', extract(export_project(store, ProjectFiles(tmp_path / 'files'), project['id']),
                                       'project.json'))


def test_selective_proof_and_capsule(tmp_path, monkeypatch):
    monkeypatch.setenv('API_KEY', 'private-secret')
    monkeypatch.setenv('OMP_NUM_THREADS', '4')
    monkeypatch.delenv('OPENBLAS_NUM_THREADS', raising=False)
    monkeypatch.delenv('MKL_NUM_THREADS', raising=False)
    monkeypatch.setenv('SPIKE_HOME', '/private/home')
    conv = {'id': 'chat', 'title': 'private-title', 'created': 1}
    blob = build_proof(conv, [], [], [], [], {'custom_instructions': 'private-instructions'},
                       include={'environment'})
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert set(archive.namelist()) == {'README.txt', 'manifest.json', 'environment.json', 'SHA256SUMS'}
        assert b'private-' not in b''.join(archive.read(n) for n in archive.namelist())
        capsule = json.loads(archive.read('environment.json'))
        assert capsule['env'] == {'OMP_NUM_THREADS': '4'}
        validate('proof-package', json.loads(archive.read('manifest.json')))
    with pytest.raises(ValueError):
        build_proof(conv, [], [], [], [], {}, include={'typo'})


def test_compatibility_is_current_and_check_detects_drift(tmp_path):
    command = [sys.executable, str(ROOT / 'scripts' / 'compat_matrix.py')]
    assert subprocess.run([*command, '--check'], cwd=ROOT, capture_output=True).returncode == 0
    target = tmp_path / 'compat.md'
    assert subprocess.run([*command, '--out', str(target)], cwd=ROOT, capture_output=True).returncode == 0
    target.write_text('stale', encoding='utf-8')
    assert subprocess.run([*command, '--out', str(target), '--check'], cwd=ROOT, capture_output=True).returncode == 1


def test_unknown_benchmark_labels_are_withheld():
    raw = report()
    raw['model']['path'] = r'C:\Users\private-user\custom-private.gguf'
    raw['hardware']['cpu_model'] = 'private-host 192.168.1.2'
    raw['llama_cpp_build'] = 'private-user@private-host:/private/build'
    shared = bench.share_report(raw)
    assert shared['model'] == shared['hardware']['cpu_class'] == 'unknown'
    assert shared['llama_cpp_version'] is None
    assert 'private' not in json.dumps(shared)


def test_default_proof_schema_and_every_checksum(monkeypatch):
    import hashlib

    monkeypatch.setenv('OMP_NUM_THREADS', '/private/not-a-number')
    blob = build_proof({'id': 'chat', 'title': 'Example', 'created': 1}, [], [], [], [], {})
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        validate('proof-package', json.loads(archive.read('manifest.json')))
        assert 'OMP_NUM_THREADS' not in json.loads(archive.read('environment.json'))['env']
        sums = archive.read('SHA256SUMS').decode('utf-8').splitlines()
        assert len(sums) == len(archive.namelist()) - 1
        for line in sums:
            digest, name = line.split('  ')
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest


def test_compatibility_tracks_sources_without_promoting_unmeasured_rows(tmp_path):
    from scripts.compat_matrix import render

    workflows = tmp_path / '.github' / 'workflows'
    workflows.mkdir(parents=True)
    (workflows / 'test.yml').write_text('jobs:\n  python:\n    runs-on: windows-latest\n', encoding='utf-8')
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'STATUS.md').write_text(
        '| Unmeasured feature | not measured | none |\n'
        '| Router | **measured**: 10/10 | pytest |\n'
        '## Measured with real weights\n| model | tok/s |\n|---|---|\n| local | 12 |\n\n'
        '## Built, not yet measured with real weights\n| invented | 99 |\n', encoding='utf-8')
    content = render(tmp_path)
    assert 'windows-latest' in content and '| local | 12 |' in content
    assert '**measured**: 10/10' in content
    assert 'Unmeasured feature' not in content and 'invented' not in content


def test_cli_share_default_file(tmp_path, monkeypatch, capsys):
    from spike.cli import main

    async def fake(args):
        return report()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bench, 'run_benchmark', fake)
    assert main(['bench', '--model', 'example.gguf', '--share']) == 0
    assert json.loads((tmp_path / 'bench-share.json').read_text(encoding='utf-8')) == json.loads(capsys.readouterr().out)


async def test_share_benchmark_never_writes_the_private_report(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx

    model = tmp_path / 'model.gguf'
    model.write_bytes(b'fake weights; no model process is started')
    target = tmp_path / 'out.json'
    server = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), load_seconds=1, base_url='http://fake',
                             process=SimpleNamespace(pid=1), memory_rss_mb=lambda: 1)
    monkeypatch.setattr(bench, 'LlamaServer', lambda config: server)
    monkeypatch.setattr(bench, 'detect', lambda: SimpleNamespace(to_dict=lambda: report()['hardware']))
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    monkeypatch.setattr(bench.httpx, 'AsyncClient', lambda **kwargs: client)
    monkeypatch.setattr(bench, 'prompt_tokens', AsyncMock(return_value=[1]))
    monkeypatch.setattr(bench, 'one_run', AsyncMock(return_value={'ttft_s': 0.1, 'gen_tok_s': 12, 'prompt_tok_s': 15}))
    monkeypatch.setattr(bench, 'RSSSampler', lambda pid: nullcontext(SimpleNamespace(peak=0, peak_anon=None)))
    args = SimpleNamespace(model=str(model), adapter=[], contexts='1', gen=1, port=1, threads=1, gpu_layers=0,
                           kv='q8_0', repeats=1, out=str(target), share=True)
    raw = await bench.run_benchmark(args)
    assert raw['model']['path'] == model.as_posix()
    assert not target.exists()
    server.stop.assert_awaited_once()
