"""Release evidence must match the candidate and cover real, repeated journeys, not just green CI."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.release import readiness as rd

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def catalog():
    return {'version': 1, 'sources': [{'id': 'plan', 'title': 'Approved plan', 'items': ['1']}],
            'features': [{'id': 'dev', 'title': 'Dev', 'group': 'Engineering', 'owner': 'codex',
                          'source_refs': ['plan:1'], 'tasks': ['DEV1'], 'scope': 'release',
                          'implementation': {'state': 'documented', 'revision': SHA, 'references': ['docs/PLAN.md']},
                          'journeys': [{'id': 'dev-edit', 'title': 'Edit, test, undo', 'critical': True,
                                        'platforms': ['macos'], 'mode': 'real', 'requires_model': True,
                                        'steps': ['Edit a file', 'Run its tests', 'Undo and inspect contents']}]}]}


def artifact(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    return {'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def evidence(root, count=3):
    runs = []
    for i in range(count):
        runs.append({'id': f'run-{i}', 'journey': 'dev-edit', 'revision': SHA, 'version': '0.1.0',
                     'recorded_at': f'2026-10-29T10:00:0{i}Z', 'platform': 'macos', 'mode': 'real',
                     'model': {'name': 'test-model', 'revision': 'weights-sha'}, 'configuration': {'context': 8192},
                     'outcome': 'pass', 'commands': ['spike dev workspace'],
                     'artifacts': [artifact(root, f'run-{i}.json', json.dumps({'run': i, 'result': 'pass'}))]})
    return {'version': 1, 'runs': runs, 'approvals': []}


def approved(root):
    e = evidence(root)
    for who in ['claude', 'joan']:
        e['approvals'].append({'actor': who, 'revision': SHA, 'decision': 'approve',
                               'recorded_at': '2026-10-29T11:00:00Z',
                               'artifact': artifact(root, f'{who}.txt', f'{who} reviewed {SHA}')})
    return e


def test_real_runs_and_both_reviews_are_needed(tmp_path):
    e = evidence(tmp_path)
    r = rd.evaluate(catalog(), e, tmp_path, SHA)
    assert r['features'][0]['ready'] and not r['ready']
    assert 'approval:claude' in r['blockers'] and 'approval:joan' in r['blockers']
    assert rd.evaluate(catalog(), approved(tmp_path), tmp_path, SHA)['ready']


@pytest.mark.parametrize('change', ['simulated', 'old_revision', 'model_missing', 'config_changed', 'failure', 'reused_artifact'])
def test_green_looking_evidence_cannot_replace_a_real_repeat(tmp_path, change):
    e = approved(tmp_path)
    run = e['runs'][-1]
    if change == 'simulated':
        run['mode'] = 'simulated'
    elif change == 'old_revision':
        run['revision'] = 'b' * 40
    elif change == 'model_missing':
        run['model'] = None
    elif change == 'config_changed':
        run['configuration']['context'] = 1024
    elif change == 'failure':
        run['outcome'] = 'fail'
    else:
        run['artifacts'] = e['runs'][0]['artifacts']
    assert not rd.evaluate(catalog(), e, tmp_path, SHA)['ready']


def test_a_later_failure_resets_the_streak(tmp_path):
    e = approved(tmp_path)
    run = copy.deepcopy(e['runs'][-1])
    run.update(id='failed', recorded_at='2026-10-29T10:01:00Z', outcome='fail')
    e['runs'].append(run)
    assert not rd.evaluate(catalog(), e, tmp_path, SHA)['features'][0]['ready']


def test_all_platforms_required_and_historical_failures_do_not_disappear(tmp_path):
    c, e = catalog(), approved(tmp_path)
    c['features'][0]['journeys'][0]['platforms'].append('windows')
    r = rd.evaluate(c, e, tmp_path, SHA)
    assert not r['ready'] and r['features'][0]['journeys'][0]['platforms']['windows']['passed'] == 0
    assert len(e['runs']) == 3  # no data mutated by the reporter


@pytest.mark.parametrize('damage', ['missing', 'changed', 'traversal', 'absolute', 'windows_path', 'symlink'])
def test_evidence_files_are_bounded_and_hashed(tmp_path, damage):
    e = approved(tmp_path)
    a = e['runs'][0]['artifacts'][0]
    p = tmp_path / a['path']
    if damage == 'missing':
        p.unlink()
    elif damage == 'changed':
        p.write_text('changed', encoding='utf-8')
    elif damage in ['traversal', 'absolute', 'windows_path']:
        a['path'] = {'traversal': '../private', 'absolute': '/private', 'windows_path': r'C:\private'}[damage]
    else:
        p.unlink()
        try:
            p.symlink_to(tmp_path / 'run-1.json')
        except OSError:
            pytest.skip('symlinks unavailable')
    assert not rd.evaluate(catalog(), e, tmp_path, SHA)['ready']


@pytest.mark.parametrize('damage', ['duplicate_feature', 'missing_source', 'duplicate_journey', 'no_journey', 'unknown_source', 'unknown_run', 'duplicate_run', 'empty_catalog'])
def test_broken_inventory_is_rejected(tmp_path, damage):
    c, e = catalog(), evidence(tmp_path)
    if damage == 'duplicate_feature':
        c['features'].append(copy.deepcopy(c['features'][0]))
    elif damage == 'missing_source':
        c['sources'][0]['items'].append('2')
    elif damage == 'duplicate_journey':
        c['features'][0]['journeys'] *= 2
    elif damage == 'no_journey':
        c['features'][0]['journeys'] = []
    elif damage == 'unknown_source':
        c['features'][0]['source_refs'] = ['plan:unknown']
    elif damage == 'unknown_run':
        e['runs'][0]['journey'] = 'absent'
    elif damage == 'duplicate_run':
        e['runs'].append(copy.deepcopy(e['runs'][0]))
    else:
        c['features'] = []
    with pytest.raises(rd.InventoryError):
        rd.evaluate(c, e, tmp_path, SHA)


def test_rejection_overrides_an_old_approval(tmp_path):
    e = approved(tmp_path)
    e['approvals'].append({**e['approvals'][0], 'decision': 'reject', 'recorded_at': '2026-10-29T12:00:00Z'})
    assert not rd.evaluate(catalog(), e, tmp_path, SHA)['ready']


def test_renderers_escape_untrusted_titles_and_do_not_claim_publication(tmp_path):
    c = catalog()
    c['features'][0]['title'] = '<img src=x onerror=alert(1)> | Dev'
    r = rd.evaluate(c, evidence(tmp_path), tmp_path, SHA)
    html = rd.render_html(r)
    assert '<img src=x' not in html and '&lt;img' in html and 'fetch(' not in html
    assert '\\|' in rd.render_markdown(r)
    assert 'no publica' in rd.render_markdown(r)


def test_cli_check_report_gate_and_bad_json(tmp_path, capsys):
    c, e = tmp_path / 'catalog.json', tmp_path / 'evidence.json'
    c.write_text(json.dumps(catalog()), encoding='utf-8')
    e.write_text(json.dumps(evidence(tmp_path)), encoding='utf-8')
    args = ['--catalog', str(c), '--evidence', str(e), '--root', str(tmp_path), '--revision', SHA]
    assert rd.main(['check', *args]) == 0
    assert rd.main(['gate', *args]) == 1
    assert rd.main(['report', *args, '--format', 'json']) == 0
    e.write_text('{', encoding='utf-8')
    assert rd.main(['gate', *args]) == 2
    assert 'Invalid' in capsys.readouterr().out


def test_committed_catalog_covers_all_sixty_ideas_and_is_not_launch_approval():
    c = json.loads((ROOT / 'docs/release/catalog.json').read_text(encoding='utf-8'))
    e = json.loads((ROOT / 'docs/release/evidence.json').read_text(encoding='utf-8'))
    rd.validate(c, e)
    sources = set().union(*(set(f['source_refs']) for f in c['features']))
    assert {f'ideas60:{i:02}' for i in range(1, 61)} <= sources
    assert not rd.evaluate(c, e, ROOT, SHA)['ready']


def test_shared_configuration_artifact_does_not_invalidate_independent_logs(tmp_path):
    e = approved(tmp_path)
    shared = artifact(tmp_path, 'configuration.json', '{"hardware":"test machine"}')
    for run in e['runs']:
        run['artifacts'].append(shared)
    assert rd.evaluate(catalog(), e, tmp_path, SHA)['ready']


def test_new_execution_requires_a_new_review_and_open_defect_blocks(tmp_path):
    e = approved(tmp_path)
    e['runs'][-1]['recorded_at'] = '2026-10-29T12:00:00Z'
    assert 'approval:joan' in rd.evaluate(catalog(), e, tmp_path, SHA)['blockers']
    e = approved(tmp_path)
    e['defects'] = [{'id': 'data-loss', 'title': 'Data loss on export', 'status': 'open',
                     'breaks_promise': True, 'reference': 'tests/example.py'}]
    assert 'defect:data-loss' in rd.evaluate(catalog(), e, tmp_path, SHA)['blockers']
    e['defects'][0]['status'] = 'fixed'
    assert rd.evaluate(catalog(), e, tmp_path, SHA)['ready']


def test_changed_review_artifact_blocks_and_oversized_files_are_not_hashed(tmp_path, monkeypatch):
    e = approved(tmp_path)
    (tmp_path / 'joan.txt').write_text('not the approved artifact', encoding='utf-8')
    assert 'approval:joan' in rd.evaluate(catalog(), e, tmp_path, SHA)['blockers']
    monkeypatch.setattr(rd, 'MAX_ARTIFACT_BYTES', 1)
    r = rd.evaluate(catalog(), e, tmp_path, SHA)
    assert not r['ready'] and any('size limit' in error for error in r['evidence_errors'])


@pytest.mark.parametrize('case', ['unknown_version', 'bool_version', 'missing_field', 'unknown_field', 'null',
                                  'bad_time', 'duplicate_time', 'bad_platform', 'bad_outcome', 'short_sha'])
def test_invalid_records_fail_closed(tmp_path, case):
    c, e = catalog(), evidence(tmp_path)
    if case == 'unknown_version':
        e['version'] = 2
    elif case == 'bool_version':
        e['version'] = True
    elif case == 'missing_field':
        del e['runs'][0]['artifacts']
    elif case == 'unknown_field':
        e['automatically_publish'] = True
    elif case == 'null':
        e = None
    elif case == 'bad_time':
        e['runs'][0]['recorded_at'] = 'yesterday'
    elif case == 'duplicate_time':
        e['runs'][1]['recorded_at'] = e['runs'][0]['recorded_at']
    elif case == 'bad_platform':
        e['runs'][0]['platform'] = 'any'
    elif case == 'bad_outcome':
        e['runs'][0]['outcome'] = 'probably'
    else:
        e['runs'][0]['revision'] = 'abc123'
    with pytest.raises(rd.InventoryError):
        rd.evaluate(c, e, tmp_path, SHA)


def test_exclusion_needs_a_decision_and_cannot_remove_every_release_feature(tmp_path):
    c, e = catalog(), evidence(tmp_path)
    extra = copy.deepcopy(c['features'][0])
    extra.update(id='future', scope='deferred', journeys=[])
    c['features'].append(extra)
    with pytest.raises(rd.InventoryError):
        rd.validate(c, e)
    extra['decision'] = 'Approved for a later release'
    rd.validate(c, e)
    c['features'][0].update(scope='excluded', decision='test')
    with pytest.raises(rd.InventoryError):
        rd.validate(c, e)


def test_duplicate_json_keys_and_nonstandard_numbers_are_rejected(tmp_path):
    p = tmp_path / 'input.json'
    for text in ['{"version":1,"version":2}', '{"value":NaN}']:
        p.write_text(text, encoding='utf-8')
        with pytest.raises(rd.InventoryError):
            rd._load(p)


def test_cli_writes_utf8_report_and_no_other_files(tmp_path):
    c, e, out = tmp_path / 'catalog.json', tmp_path / 'evidence.json', tmp_path / 'report.html'
    c.write_text(json.dumps(catalog()), encoding='utf-8')
    e.write_text(json.dumps(evidence(tmp_path)), encoding='utf-8')
    before = set(tmp_path.iterdir())
    assert rd.main(['report', '--catalog', str(c), '--evidence', str(e), '--root', str(tmp_path),
                    '--revision', SHA, '--format', 'html', '--out', str(out)]) == 0
    assert 'Preparación' in out.read_text(encoding='utf-8')
    assert set(tmp_path.iterdir()) - before == {out}
