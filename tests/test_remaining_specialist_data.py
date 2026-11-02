"""M6 candidate data contracts: original inline fixtures, no data downloads or model calls."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'training'))

from spike_train.data import FORMATTERS, content_text  # noqa: E402
from spike_train.evaluation import check_acceptance, make_item, score  # noqa: E402

ROWS = {
    'qasc': {'id': 'e1', 'question': 'What helps a seed start growing?',
             'choices': {'label': list('ABCDEFGH'), 'text': ['water', 'plastic', 'paint', 'glass', 'steel', 'salt',
                                                          'oil', 'sandpaper']},
             'answerKey': 'A', 'fact1': 'ANSWER-BEARING-FACT', 'fact2': 'HIDDEN-FACT',
             'combinedfact': 'HIDDEN-COMPOSITION', 'formatted_question': 'HIDDEN-PRECOMPUTED'},
    'commonsense_qa': {'id': 'c1', 'question': 'Where could a person borrow a book?',
                      'choices': {'label': list('ABCDE'), 'text': ['library', 'pond', 'oven', 'cloud', 'shoe']},
                      'answerKey': 'A', 'question_concept': 'HIDDEN-CONCEPT'},
    'banking77': {'text': 'How do I activate my new card?', 'label': 0},
    'phishing_url': {'url': 'https://example.test/account', 'status': 'phishing', 'page_rank': 9},
    'billsum_title': {'summary': 'The proposed act funds three public libraries.',
                     'title': 'Public library grants', 'text': 'HIDDEN-FULL-BILL'},
}


@pytest.mark.parametrize('fmt', ROWS)
def test_remaining_formats_share_train_eval_prompts_and_reject_bad_answers(fmt):
    chat = FORMATTERS[fmt](ROWS[fmt], 'SYSTEM')
    item = make_item('fixture', fmt, 0, ROWS[fmt])
    assert [m['role'] for m in chat['messages']] == ['system', 'user', 'assistant']
    assert item.prompt == chat['messages'][1]['content']
    assert score(item, chat['messages'][-1]['content'])[1]
    assert not score(item, 'Answer: definitely-not-a-label-or-title')[1]
    assert 'HIDDEN' not in item.prompt and 'ANSWER-BEARING' not in item.prompt
    assert FORMATTERS[fmt]({}, 'S') is None
    assert make_item('bad', fmt, 0, {}) is None


@pytest.mark.parametrize('fmt,change', [
    ('qasc', {'answerKey': ''}), ('qasc', {'answerKey': 'I'}), ('qasc', {'question': 3}),
    ('qasc', {'choices': {'label': list('ABCDEFGH'), 'text': ['x'] * 7}}), ('qasc', {'choices': 'bad'}),
    ('commonsense_qa', {'answerKey': 'F'}), ('commonsense_qa', {'choices': {'label': [], 'text': []}}),
    ('banking77', {'label': -1}), ('banking77', {'label': 77}), ('banking77', {'label': True}),
    ('banking77', {'label': '0'}), ('banking77', {'text': '  '}),
    ('phishing_url', {'status': 'maybe'}), ('phishing_url', {'url': ''}), ('phishing_url', {'url': []}),
    ('billsum_title', {'summary': None}), ('billsum_title', {'title': ''}),
])
def test_malformed_remaining_rows_are_not_silently_labelled(fmt, change):
    row = {**ROWS[fmt], **change}
    assert FORMATTERS[fmt](row, 'S') is None
    assert make_item('bad', fmt, 0, row) is None


def test_all_business_labels_have_distinct_targets_and_templates_do_not_contaminate_every_row():
    targets = set()
    for label in range(77):
        chat = FORMATTERS['banking77']({**ROWS['banking77'], 'label': label}, 'S')
        targets.add(chat['messages'][-1]['content'])
        assert content_text(chat['messages'][1]['content']).strip() == ROWS['banking77']['text']
    assert len(targets) == 77
    for fmt in ('billsum_title', 'phishing_url'):
        chat = FORMATTERS[fmt](ROWS[fmt], 'S')
        field = 'summary' if fmt == 'billsum_title' else 'url'
        assert content_text(chat['messages'][1]['content']).strip() == ROWS[fmt][field]


def test_pairwise_recipe_cannot_be_accepted_by_regression_alone():
    summary = {'suites': {'general': {'vs_base': {'candidate': {'delta_points': 0, 'p_value': 1}}}}}
    acceptance = {'primary': {'suite': 'writing-pairwise', 'min_win_rate': 0.6},
                  'regression': {'suite': 'general', 'max_drop_points': 1.5}}
    accepted, reasons = check_acceptance(summary, acceptance, 'candidate')
    assert not accepted and 'pairwise' in ' '.join(reasons)

DOMAINS = {'education': ('qasc', 'qasc', 'question'),
           'core': ('commonsenseqa', 'commonsense_qa', 'question'),
           'business': ('banking77', 'banking77', 'text'),
           'security': ('phishing-url', 'phishing_url', 'url'),
           'writing': ('billsum', 'billsum_title', 'summary')}
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'evals'))

import json  # noqa: E402
import types  # noqa: E402

import export_prompts  # noqa: E402
import prepare  # noqa: E402
import run_eval  # noqa: E402
import yaml  # noqa: E402
from spike_train import licenses  # noqa: E402
from spike_train.evaluation import check_pairwise_acceptance  # noqa: E402


def config(path):
    return yaml.safe_load((ROOT / path).read_text(encoding='utf-8'))


@pytest.mark.parametrize('domain', DOMAINS)
def test_recipe_sources_disjoint_selection_and_fail_closed_before_network(domain, monkeypatch, tmp_path):
    name, fmt, field = DOMAINS[domain]
    reg = config('training/datasets.yaml')['sources']
    suites = config('evals/suites.yaml')['suites']
    cfg = config(f'training/configs/{domain}.yaml')
    assert cfg['domain_sources'] == [{'source': name + '-train'}]
    assert cfg['replay']['sources'][0]['source'] == 'oasst2'
    assert cfg['train']['max_seq_length'] == 768
    assert set(cfg['decontaminate_against']) == {'mmlu-pro', name + '-eval'}
    assert reg[name + '-train']['split'] != reg[name + '-eval']['split']
    for suffix, role in (('-train', 'train'), ('-eval', 'eval')):
        src = reg[name + suffix]
        assert src['role'] == role and src['license_status'] == 'unverified'
        assert src['license'] in licenses.TRAIN_ALLOWLIST and src['license_url'] and src['provenance']
        assert src['format'] == fmt
    monkeypatch.setattr(licenses, 'hub_license', lambda *a: pytest.fail('network attempted before review'))
    monkeypatch.setattr(prepare, 'load_rows', lambda *a, **kw: pytest.fail('dataset attempted before review'))
    for offline in (False, True):
        monkeypatch.setattr(sys, 'argv', ['prepare.py', str(ROOT / f'training/configs/{domain}.yaml'),
                                         '--out', str(tmp_path)] + (['--skip-license-check'] if offline else []))
        with pytest.raises(SystemExit, match='unverified'):
            prepare.main()
    task, = suites[domain]['tasks']
    select, = suites[domain + '-select']['tasks']
    with pytest.raises(SystemExit, match='unverified'):
        run_eval.load_items(task, reg, 0, None)
    assert select['skip'] == task['n']
    # Simulate license review ONLY for these inline fixtures, then exercise the actual seeded sampler.
    monkeypatch.setattr(licenses, 'source_license', lambda src: src['license'])
    rows = [{**ROWS[fmt], 'id': str(i)} for i in range(task['n'] + select['n'])]
    monkeypatch.setitem(sys.modules, 'datasets', types.SimpleNamespace(load_dataset=lambda *a, **kw: rows))
    accepted = run_eval.load_items(task, reg, 0, None)
    selected = run_eval.load_items(select, reg, 0, None)
    assert len(accepted) == task['n'] and len(selected) == select['n']
    assert not {i.id.split('/', 1)[1] for i in accepted} & {i.id.split('/', 1)[1] for i in selected}


@pytest.mark.parametrize('domain', DOMAINS)
def test_preparation_removes_heldout_content_and_keeps_unrelated_examples(domain, tmp_path, monkeypatch):
    name, fmt, field = DOMAINS[domain]
    cfg = config(f'training/configs/{domain}.yaml')
    cfg['replay'] = {'ratio': 0, 'sources': []}
    heldout = {**ROWS[fmt], field: 'Held out source material with more than thirteen distinct words to detect accidental use in training'}
    clean = {**ROWS[fmt], field: 'Unrelated example of a different subject'}
    if fmt in ('qasc', 'commonsense_qa'):
        clean['choices'] = {'label': ROWS[fmt]['choices']['label'],
                            'text': [f'Different choice {i}' for i in range(len(ROWS[fmt]['choices']['text']))]}
    monkeypatch.setattr(prepare, 'gate_source', lambda name, src, role, offline: src['license'])
    monkeypatch.setattr(prepare, 'load_token_counter', lambda base: lambda chat: 100)
    monkeypatch.setattr(prepare, 'load_rows', lambda src, *a, **kw: iter(
        [heldout, clean] if src['role'] == 'train' else [heldout] if src['format'] == fmt else []))
    path = tmp_path / 'recipe.yaml'
    path.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    monkeypatch.setattr(sys, 'argv', ['prepare.py', str(path), '--out', str(tmp_path)])
    assert prepare.main() == 0
    manifest = json.loads((tmp_path / domain / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['dropped']['contaminated'] == 1
    assert manifest['sources'][name + '-train']['kept'] == 1
    assert manifest['sources'][name + '-eval']['indexed_prompts'] == 1


def test_writing_export_is_seeded_separate_and_contains_no_gold(monkeypatch, tmp_path):
    reg = config('training/datasets.yaml')['sources']
    monkeypatch.setattr(licenses, 'source_license', lambda src: src['license'])
    rows = [{**ROWS['billsum_title'], 'id': str(i)} for i in range(900)]
    monkeypatch.setitem(sys.modules, 'datasets', types.SimpleNamespace(load_dataset=lambda *a, **kw: rows))
    paths = [tmp_path / 'final.jsonl', tmp_path / 'select.jsonl']
    assert export_prompts.export_suite('writing', paths[0]) == 600
    assert export_prompts.export_suite('writing-select', paths[1]) == 300
    actual = [[json.loads(s) for s in p.read_text(encoding='utf-8').splitlines()] for p in paths]
    assert not {r['id'].split('/', 1)[1] for r in actual[0]} & {r['id'].split('/', 1)[1] for r in actual[1]}
    for row in actual[0] + actual[1]:
        assert set(row) == {'id', 'prompt', 'suite', 'seed'} and row['seed'] == 0
        assert ROWS['billsum_title']['title'] not in row['prompt']
    original = paths[0].read_bytes()
    with pytest.raises(FileExistsError):
        export_prompts.export_suite('writing', paths[0])
    assert paths[0].read_bytes() == original
    # The exporter relies on the same license gate as load_items, not a separate unchecked path.
    assert reg['billsum-eval']['license_status'] == 'unverified'


def test_writing_export_blocks_unreviewed_sources_without_output(monkeypatch, tmp_path):
    monkeypatch.setattr(licenses, 'hub_license', lambda *a: pytest.fail('network attempted before review'))
    out = tmp_path / 'pairs.jsonl'
    with pytest.raises(SystemExit, match='unverified'):
        export_prompts.export_suite('writing', out)
    assert not out.exists()
    with pytest.raises(ValueError, match='unknown suite'):
        export_prompts.export_suite('not-a-suite', out)


def test_writing_acceptance_requires_pairwise_significance_and_general_regression():
    acceptance = config('training/configs/writing.yaml')['acceptance']
    summary = {'win_rate': .75, 'sign_test_p': .001,
               'general': {'suite': 'general', 'delta_points': 0}}
    assert check_pairwise_acceptance(summary, acceptance)[0]
    assert not check_pairwise_acceptance({**summary, 'sign_test_p': .7}, acceptance)[0]
    assert not check_pairwise_acceptance({**summary, 'win_rate': .5}, acceptance)[0]
    assert not check_pairwise_acceptance({**summary, 'general': {}}, acceptance)[0]
    assert not check_pairwise_acceptance({**summary, 'general': {'suite': 'general', 'delta_points': -2}}, acceptance)[0]
