"""Local history search: migration, literal queries, scope and lifecycle consistency."""

import sqlite3

import pytest

from spike.store.db import SCHEMA, Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / 'history.db')
    yield result
    result._conn.close()


def find(store, query='decisión', **kwargs):
    return store.search_history(query=query, **kwargs)


def test_legacy_backfill_and_reopen_survive_vacuum(tmp_path):
    path = tmp_path / 'old.db'
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO conversations VALUES ('c', 'Decisión antigua', 1, 1, 'auto', NULL)")
    conn.execute("INSERT INTO messages VALUES ('m', 'c', 'assistant', 'Decisión guardada', '{}', 2)")
    conn.commit()
    conn.close()
    for _ in range(2):
        old = Store(path)
        results = find(old)['results']
        assert {r['message_id'] for r in results} == {None, 'm'}
        old._conn.execute('VACUUM')
        assert len(find(old)['results']) == 2
        old._conn.close()


def test_search_words_phrase_unicode_and_plain_snippets(store):
    c = store.create_conversation('Notes')
    m = store.add_message(c['id'], 'assistant', '<script>alert(1)</script> Decisión muy útil.',
                          meta={'hidden': 'secretoindizado'})
    assert find(store, 'DECISION util')['results'][0]['message_id'] == m['id']
    assert not find(store, 'decisión útil', match='phrase')['results']
    assert find(store, 'decisión muy', match='phrase')['results']
    assert not find(store, 'secretoindizado')['results']
    segments = find(store)['results'][0]['segments']
    assert any(s['matched'] and s['text'] == 'Decisión' for s in segments)
    assert '<script>' in ''.join(s['text'] for s in segments)
    assert not find(store, 'decision OR missing')['results']
    assert find(store, '"decision" *')['results']  # punctuation is not query syntax
    assert not find(store, "x'); DROP TABLE messages;--")['results']
    assert store.get_message(m['id'])


def test_filters_and_project_rename(store):
    p = store.create_project('Uno')
    c = store.create_conversation('Decisión del proyecto', project_id=p['id'], created=10)
    store.add_message(c['id'], 'user', 'decisión primera', created=20)
    m = store.add_message(c['id'], 'assistant', 'decisión segunda', created=30)
    w = store.create_conversation('Decisión personal', created=5)
    assert len(find(store, scope='all')['results']) == 4
    assert [r['conversation_id'] for r in find(store, scope='workspace')['results']] == [w['id']]
    assert len(find(store, scope='project', project_id=p['id'])['results']) == 3
    assert find(store, role='assistant')['results'][0]['message_id'] == m['id']
    assert len(find(store, after=25)['results']) == 1
    store.update_project(p['id'], name='Dos')
    assert find(store, role='assistant')['results'][0]['project_name'] == 'Dos'


def test_edits_retries_and_deletes_remove_stale_results(store):
    p = store.create_project('Project')
    c = store.create_conversation('decisión vieja', project_id=p['id'])
    m = store.add_message(c['id'], 'user', 'decisión primera', created=10)
    store.add_message(c['id'], 'assistant', 'decisión segunda', created=20)
    store.update_conversation(c['id'], title='Título nuevo')
    assert not find(store, 'vieja')['results']
    store._exec('UPDATE messages SET content=? WHERE id=?', ('respuesta corregida', m['id']))
    assert not find(store, 'primera')['results']
    assert find(store, 'corregida')['results']
    store.delete_messages_from(c['id'], m['id'])
    assert not find(store, 'corregida')['results']
    assert not find(store)['results']
    store.add_message(c['id'], 'assistant', 'decisión final')
    store.delete_project(p['id'])
    assert not find(store)['results']
    assert store._conn.execute('SELECT count(*) FROM history_fts').fetchone()[0] == 0


def test_pagination_searches_beyond_sidebar_limit(store):
    first = store.create_conversation('aguja archivada', created=1)
    for i in range(205):
        store.create_conversation(f'notas {i}', created=i + 2)
    assert first['id'] not in {c['id'] for c in store.list_conversations()}
    assert find(store, 'aguja')['results'][0]['conversation_id'] == first['id']
    a = find(store, 'notas', limit=10)
    b = find(store, 'notas', limit=10, offset=a['next_offset'])
    assert a['has_more'] and len(a['results']) == 10
    assert not ({r['id'] for r in a['results']} & {r['id'] for r in b['results']})


def test_snippets_bounded(store):
    c = store.create_conversation()
    store.add_message(c['id'], 'user', 'decisión ' + 'x' * 10000)
    assert sum(len(s['text']) for s in find(store)['results'][0]['segments']) <= 1201


@pytest.mark.parametrize('kwargs', [
    {'query': ''}, {'query': '*'}, {'query': 'x' * 201}, {'query': ' '.join(['x'] * 13)},
    {'scope': 'project'}, {'scope': 'oops'}, {'project_id': 'unscoped'}, {'role': 'system'},
    {'match': 'raw'}, {'after': float('nan')}, {'after': -1}, {'limit': 51}, {'offset': -1},
])
def test_invalid_queries_are_rejected(store, kwargs):
    with pytest.raises(ValueError):
        store.search_history(**({'query': 'decisión'} | kwargs))
