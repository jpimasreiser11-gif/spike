"""Offline release inventory and evidence checks. Never executes recorded commands or publishes anything.

A passing gate checks the consistency of supplied records, not their authenticity or the quality of an AI answer.
Claude reviews the evidence; Joan authorizes publication separately. No model/provider or network is used here.
"""

import argparse
import hashlib
import html
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
COMMIT = re.compile(r'[0-9a-f]{40}')
DIGEST = re.compile(r'[0-9a-f]{64}')
IDENT = re.compile(r'[A-Za-z0-9_-]+')
PLATFORMS = ('macos', 'windows', 'linux')
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 512 * 1024 * 1024


class InventoryError(ValueError):
    """The inventory or evidence cannot be interpreted safely."""


def _require(ok, message):
    if not ok:
        raise InventoryError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _object(value, required, optional=()):
    _require(isinstance(value, dict), 'expected an object')
    _require(set(required) <= value.keys() <= set(required) | set(optional),
             f'fields must be {sorted(required)} (optional: {sorted(optional)})')


def _list(value, nonempty=False):
    _require(isinstance(value, list) and (bool(value) or not nonempty), 'expected a list' + (' with items' if nonempty else ''))
    return value


def _texts(value, nonempty=True):
    _list(value, nonempty)
    _require(all(_text(x) for x in value) and len(set(value)) == len(value), 'expected unique nonempty strings')


def _unique(value, seen):
    _require(_text(value) and IDENT.fullmatch(value) and value not in seen, f'invalid or duplicate id: {value}')
    seen.add(value)


def _timestamp(value):
    _require(isinstance(value, str) and value.endswith('Z'), 'recorded_at must be a UTC timestamp ending in Z')
    try:
        return datetime.fromisoformat(value[:-1] + '+00:00')
    except ValueError:
        raise InventoryError('invalid recorded_at timestamp') from None


def _commit(value):
    _require(isinstance(value, str) and COMMIT.fullmatch(value), 'revision must be a full lowercase Git SHA')


def _artifact(value):
    _object(value, ('path', 'sha256'))
    _require(_text(value['path']) and isinstance(value['sha256'], str) and DIGEST.fullmatch(value['sha256']),
             'artifact requires a path and SHA-256')


def validate(catalog, evidence):
    """Validate v1 structures and full source coverage. File integrity is checked separately by evaluate()."""
    _object(catalog, ('version', 'sources', 'features'))
    _object(evidence, ('version', 'runs', 'approvals'), ('defects',))
    _require(type(catalog['version']) is int and catalog['version'] == 1
             and type(evidence['version']) is int and evidence['version'] == 1, 'unsupported version')
    source_ids, source_refs, mapped = set(), set(), set()
    for source in _list(catalog['sources'], True):
        _object(source, ('id', 'title', 'items'))
        _unique(source['id'], source_ids)
        _require(_text(source['title']), 'source needs a title')
        _texts(source['items'])
        source_refs.update(f"{source['id']}:{item}" for item in source['items'])
    feature_ids, journeys = set(), set()
    released = 0
    for feature in _list(catalog['features'], True):
        _object(feature, ('id', 'title', 'group', 'owner', 'source_refs', 'tasks', 'scope', 'implementation', 'journeys'),
                ('decision', 'notes', 'tests'))
        _unique(feature['id'], feature_ids)
        _require(all(_text(feature[k]) for k in ('title', 'group', 'owner')), 'feature needs title, group and owner')
        _texts(feature['source_refs'])
        _texts(feature['tasks'], False)
        _texts(feature.get('tests', []), False)
        _require(set(feature['source_refs']) <= source_refs, 'unknown source reference')
        mapped.update(feature['source_refs'])
        _require(feature['scope'] in ('release', 'deferred', 'excluded'), 'invalid scope')
        _require(feature['scope'] == 'release' or _text(feature.get('decision')), 'out-of-scope item needs an explicit decision')
        implementation = feature['implementation']
        _object(implementation, ('state', 'revision', 'references'))
        _require(implementation['state'] in ('documented', 'in_review', 'planned', 'excluded'), 'invalid implementation state')
        _commit(implementation['revision'])
        _texts(implementation['references'])
        released += feature['scope'] == 'release'
        for journey in _list(feature['journeys'], feature['scope'] == 'release'):
            _object(journey, ('id', 'title', 'critical', 'platforms', 'mode', 'requires_model', 'steps'))
            _unique(journey['id'], journeys)
            _require(_text(journey['title']), 'journey needs a title')
            _require(type(journey['critical']) is bool and type(journey['requires_model']) is bool, 'expected booleans')
            _texts(journey['platforms'])
            _require(set(journey['platforms']) <= set(PLATFORMS), 'unknown platform')
            _require(journey['mode'] == 'real', 'release journeys require real execution')
            _texts(journey['steps'])
    _require(released > 0, 'at least one release feature is required')
    _require(mapped == source_refs, f'unmapped source items: {sorted(source_refs - mapped)}')
    runs, times = set(), set()
    for run in _list(evidence['runs']):
        _object(run, ('id', 'journey', 'revision', 'version', 'recorded_at', 'platform', 'mode', 'model',
                      'configuration', 'outcome', 'commands', 'artifacts'))
        _unique(run['id'], runs)
        _require(_text(run['journey']) and run['journey'] in journeys, 'unknown run journey')
        _commit(run['revision'])
        _require(_text(run['version']), 'run needs a version')
        _require(run['platform'] in PLATFORMS and run['mode'] in ('real', 'simulated'), 'invalid run platform or mode')
        timestamp = _timestamp(run['recorded_at'])
        key = (run['journey'], run['revision'], run['platform'], timestamp)
        _require(key not in times, 'ambiguous run order: duplicate timestamp for journey/platform/revision')
        times.add(key)
        _require(run['outcome'] in ('pass', 'fail', 'blocked', 'cancelled'), 'invalid outcome')
        _require(isinstance(run['configuration'], dict), 'configuration must be an object')
        if run['model'] is not None:
            _object(run['model'], ('name', 'revision'))
            _require(all(_text(v) for v in run['model'].values()), 'model needs name and revision')
        _texts(run['commands'])
        for artifact in _list(run['artifacts'], True):
            _artifact(artifact)
    times = set()
    for approval in _list(evidence['approvals']):
        _object(approval, ('actor', 'revision', 'decision', 'recorded_at', 'artifact'))
        _require(approval['actor'] in ('claude', 'joan') and approval['decision'] in ('approve', 'reject'), 'invalid approval')
        _commit(approval['revision'])
        key = (approval['actor'], approval['revision'], _timestamp(approval['recorded_at']))
        _require(key not in times, 'ambiguous approval order')
        times.add(key)
        _artifact(approval['artifact'])
    defects = set()
    for defect in _list(evidence.get('defects', [])):
        _object(defect, ('id', 'title', 'status', 'breaks_promise', 'reference'))
        _unique(defect['id'], defects)
        _require(_text(defect['title']) and _text(defect['reference']), 'defect needs title and reference')
        _require(defect['status'] in ('open', 'fixed') and type(defect['breaks_promise']) is bool, 'invalid defect')


def _check_artifact(root, artifact):
    """Bounded reads only, with symlinks refused on every path component. Paths are portable POSIX relatives."""
    value = artifact['path']
    path = PurePosixPath(value)
    if '\\' in value or ':' in value or path.is_absolute() or '..' in path.parts or not path.parts or path.as_posix() != value:
        return 'non-portable or escaping artifact path'
    current = root
    try:
        for part in path.parts:
            current = current / part
            if current.is_symlink():
                return 'symlink artifact refused'
        if not current.resolve().is_relative_to(root) or not current.is_file():
            return 'artifact missing or outside root'
        if current.stat().st_size > MAX_ARTIFACT_BYTES:
            return 'artifact exceeds size limit'
        digest, size = hashlib.sha256(), 0
        with current.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                size += len(block)
                if size > MAX_ARTIFACT_BYTES:
                    return 'artifact exceeds size limit'
                digest.update(block)
        return '' if digest.hexdigest() == artifact['sha256'] else 'artifact checksum mismatch'
    except (OSError, ValueError):
        return 'artifact unreadable'


def evaluate(catalog, evidence, root, revision):
    """Critical journeys need three consecutive independent passes with the same model/version/configuration."""
    validate(catalog, evidence)
    _commit(revision)
    root = Path(root).resolve()
    errors, invalid = [], set()
    for run in evidence['runs']:
        for artifact in run['artifacts']:
            if error := _check_artifact(root, artifact):
                errors.append(f"{run['id']}: {error} ({artifact['path']})")
                invalid.add(run['id'])
    features, blockers = [], []
    for feature in catalog['features']:
        item = {**feature, 'journeys': [], 'ready': feature['scope'] == 'release'}
        for journey in feature['journeys']:
            platforms = {}
            for platform in journey['platforms']:
                relevant = sorted((r for r in evidence['runs'] if r['journey'] == journey['id']
                                   and r['platform'] == platform and r['revision'] == revision and r['mode'] == 'real'),
                                  key=lambda r: _timestamp(r['recorded_at']))
                streak, seen, signature = [], set(), None
                for run in relevant:
                    current = json.dumps([run['version'], run['model'], run['configuration']], sort_keys=True)
                    digests = tuple(sorted({a['sha256'] for a in run['artifacts']}))
                    valid = run['outcome'] == 'pass' and run['id'] not in invalid
                    valid = valid and (not journey['requires_model'] or run['model'] is not None)
                    if current != signature or not valid or digests in seen:
                        streak, seen = [], set()
                    signature = current
                    if valid:
                        streak.append(run['id'])
                        seen.add(digests)
                required = 3 if journey['critical'] else 1
                platforms[platform] = {'passed': len(streak), 'required': required, 'runs': streak,
                                       'ready': len(streak) >= required}
            complete = all(p['ready'] for p in platforms.values())
            item['journeys'].append({**journey, 'platforms': platforms, 'ready': complete})
            item['ready'] &= complete
        features.append(item)
        if feature['scope'] == 'release' and not item['ready']:
            blockers.append(f"feature:{feature['id']}")
    candidate_runs = [r for r in evidence['runs'] if r['revision'] == revision and r['mode'] == 'real']
    if len({r['version'] for r in candidate_runs}) > 1:
        blockers.append('candidate:inconsistent-version')
    latest_run = max((_timestamp(r['recorded_at']) for r in candidate_runs), default=None)
    for actor in ('claude', 'joan'):
        records = [a for a in evidence['approvals'] if a['actor'] == actor and a['revision'] == revision]
        latest = max(records, key=lambda a: _timestamp(a['recorded_at']), default=None)
        error = _check_artifact(root, latest['artifact']) if latest else ''
        if error:
            errors.append(f'approval:{actor}: {error}')
        if (not latest or latest['decision'] != 'approve' or error
                or (latest_run and _timestamp(latest['recorded_at']) <= latest_run)):
            blockers.append(f'approval:{actor}')
    for defect in evidence.get('defects', []):
        if defect['status'] == 'open' and defect['breaks_promise']:
            blockers.append(f"defect:{defect['id']}")
    if errors:
        blockers.append('evidence:integrity')
    return {'revision': revision, 'ready': not blockers, 'blockers': blockers, 'features': features,
            'evidence_errors': errors, 'defects': evidence.get('defects', []),
            'notice': 'Checks supplied records only; this tool does not publish or authorize release. '
                      'Comprueba registros aportados; no publica ni autoriza el lanzamiento.'}


def _md(value):
    return html.escape(str(value)).replace('|', r'\|').replace('\n', ' ')


def render_markdown(report):
    lines = ['# SPIKE · Release readiness / Preparación del lanzamiento', '', report['notice'], '',
             f"Candidate / Candidato: `{report['revision']}`", '',
             f"Gate: {'PASS / PASA' if report['ready'] else 'BLOCKED / BLOQUEADO'}", '',
             '| Feature / Función | Owner | Implementation | Scope | Real journeys / Recorridos reales |',
             '|---|---|---|---|---|']
    for feature in report['features']:
        coverage = '; '.join(f"{j['id']}: " + ', '.join(f"{p} {s['passed']}/{s['required']}" for p, s in j['platforms'].items())
                             for j in feature['journeys']) or feature.get('decision', '')
        lines.append('| ' + ' | '.join(_md(x) for x in (feature['title'], feature['owner'], feature['implementation']['state'],
                                                       feature['scope'], coverage)) + ' |')
    lines += ['', '## Blockers / Bloqueos', '', *[f'- {_md(b)}' for b in report['blockers']], '',
              '## Evidence errors / Errores de evidencia', '', *[f'- {_md(e)}' for e in report['evidence_errors']]]
    return '\n'.join(lines).rstrip() + '\n'


def render_html(report):
    esc = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    rows = []
    for feature in report['features']:
        journeys = ''.join('<li>' + esc(j['title']) + ': ' + ', '.join(
            f"{esc(p)} {s['passed']}/{s['required']}" for p, s in j['platforms'].items()) + '</li>' for j in feature['journeys'])
        details = '<ul>' + journeys + '</ul>' if journeys else esc(feature.get('decision', ''))
        steps = ''.join('<li>' + esc(step) + '</li>' for j in feature['journeys'] for step in j['steps'])
        details += ('<details><summary>Pasos y referencias / Steps and references</summary><ol>' + steps + '</ol><p>'
                    + esc(feature.get('notes', '')) + '</p><p>Origen: ' + esc(', '.join(feature['source_refs']))
                    + '</p><p>Tareas: ' + esc(', '.join(feature['tasks']) or 'Pendiente de asignar')
                    + '</p><ul>' + ''.join('<li><code>' + esc(ref) + '</code></li>'
                                          for ref in feature['implementation']['references']) + '</ul></details>')
        rows.append(f'<tr data-ready="{str(feature["ready"]).lower()}"><th scope="row">{esc(feature["title"])}'
                    f'<small>{esc(feature["group"])} · {esc(feature["id"])}</small></th>'
                    f'<td>{esc(feature["owner"])}</td><td>{esc(feature["implementation"]["state"])}</td>'
                    f'<td>{esc(feature["scope"])}</td><td>{details}</td></tr>')
    return '''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>SPIKE · Release readiness</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fdfdfa;color:#052e1e;font:16px/1.55 system-ui}
main{max-width:1440px;margin:auto;padding:48px 24px}h1{font-size:clamp(28px,4vw,52px);line-height:1.1}header{max-width:960px}
.badge{background:#e3fada;padding:8px 16px;border-radius:32px;display:inline-block;font-weight:700}
input,select{font:inherit;border:1px solid #4d695d;border-radius:8px;padding:10px;max-width:100%;background:white;color:inherit}
label{display:inline-block;margin:12px 20px 12px 0}table{border-collapse:collapse;width:100%;min-width:850px}
th,td{text-align:left;border-bottom:1px solid #b6c9bc;padding:16px;vertical-align:top}th{font-weight:600}thead{background:#e3fada}
small{display:block;font-weight:400}ul{margin:0;padding-left:20px}.scroll{overflow:auto}code{overflow-wrap:anywhere}
[hidden]{display:none!important}:focus-visible{outline:3px solid #125c40;outline-offset:3px}
</style><main><header><p class="badge">SPIKE · Evidence before promises</p><h1>Preparación del lanzamiento</h1>
<p>Inventario y recorridos reales. Código documentado o en revisión no significa producto validado.</p>''' + (
        f'<p>{esc(report["notice"])}</p><p><strong>{"PASA / PASS" if report["ready"] else "BLOQUEADO / BLOCKED"}</strong>'
        f' · Candidato <code>{esc(report["revision"])}</code></p></header>'
        '<label>Buscar función, módulo o responsable<br><input id="search" type="search"></label>'
        '<label>Mostrar<br><select id="filter"><option value="all">Todas</option><option value="false">Pendientes</option>'
        '<option value="true">Con recorridos aportados</option></select></label><p id="count" role="status"></p>'
        '<div class="scroll" tabindex="0" role="region" aria-label="Inventario completo"><table><thead><tr>'
        '<th>Función</th><th>Responsable</th><th>Implementación</th><th>Alcance</th><th>Evidencia real</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></div><h2>Bloqueos</h2><ul>'
        + ''.join('<li>' + esc(b) + '</li>' for b in report['blockers']) + '</ul><h2>Integridad</h2><ul>'
        + ''.join('<li>' + esc(e) + '</li>' for e in report['evidence_errors']) + '''</ul></main><script>
const search = document.getElementById('search'), filter = document.getElementById('filter');
const rows = [...document.querySelectorAll('tbody tr')];
function update(){let visible=0;for(const row of rows){row.hidden=!(row.textContent.toLocaleLowerCase().includes(
search.value.toLocaleLowerCase())&&(filter.value==='all'||row.dataset.ready===filter.value));if(!row.hidden)visible++;}
document.getElementById('count').textContent=visible+' / '+rows.length+' funciones';}
search.addEventListener('input',update);filter.addEventListener('change',update);update();
</script></html>''')


def _load(path):
    if path.stat().st_size > MAX_RECORD_BYTES:
        raise InventoryError('record exceeds size limit')
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, f'duplicate JSON key: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda value: _require(False, f'invalid JSON number: {value}'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('check', 'report', 'gate'))
    parser.add_argument('--catalog', type=Path, default=ROOT / 'docs/release/catalog.json')
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/release/evidence.json')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--format', choices=('json', 'markdown', 'html'), default='markdown')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    try:
        catalog, evidence = _load(args.catalog), _load(args.evidence)
        _commit(args.revision)
        validate(catalog, evidence)
        if args.command == 'check':
            print('Valid / Valido: source coverage and record structure')
            return 0
        report = evaluate(catalog, evidence, args.root, args.revision)
        output = json.dumps(report, indent=2, ensure_ascii=True) + '\n' if args.format == 'json' else (
            render_html(report) if args.format == 'html' else render_markdown(report))
        if args.out:
            args.out.write_text(output, encoding='utf-8')
        else:
            # Non-UTF-8 terminals may not support source titles; file output always remains UTF-8.
            import sys
            print(output.encode(sys.stdout.encoding or 'utf-8', errors='backslashreplace')
                  .decode(sys.stdout.encoding or 'utf-8'), end='')
        return 1 if args.command == 'gate' and not report['ready'] else 0
    except (InventoryError, OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        print(f'Invalid / Invalido: {str(error).encode("ascii", errors="backslashreplace").decode("ascii")}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
