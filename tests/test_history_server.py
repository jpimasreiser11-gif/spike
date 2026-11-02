"""History API stays local and never exposes temporary chats or tool metadata."""

import pytest
from fastapi.testclient import TestClient

from spike.server.app import create_app
from spike.server.state import AppState
from tests.helpers import ScriptedProvider


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('SPIKE_HOME', str(tmp_path))
    monkeypatch.setenv('SPIKE_WORKSPACE', str(tmp_path / 'ws'))
    monkeypatch.setenv('SPIKE_NO_KEYRING', '1')
    local = ScriptedProvider([], name='spike-local')
    state = AppState(home=tmp_path, provider_factory=lambda cfg: local)
    with TestClient(create_app(state)) as client:
        yield client, state, local


def test_search_is_local_persistent_only_and_uncached(env):
    client, state, local = env
    c = state.store.create_conversation('Local')
    m = state.store.add_message(c['id'], 'assistant', 'Aguja persistente', meta={'secret': 'exclusivometa'})
    temp = state.temp.create_conversation('Aguja temporal')
    state.temp.add_message(temp['id'], 'user', 'Aguja temporal')
    response = client.post('/api/history/search', json={'query': 'aguja'})
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert [r['message_id'] for r in response.json()['results']] == [m['id']]
    assert not client.post('/api/history/search', json={'query': 'exclusivometa'}).json()['results']
    assert local.requests == []


def test_project_scope_and_invalid_inputs(env):
    client, state, _ = env
    p = state.store.create_project('Proyecto')
    c = state.store.create_conversation('aguja', project_id=p['id'])
    assert not client.post('/api/history/search', json={'query': 'aguja', 'scope': 'workspace'}).json()['results']
    body = {'query': 'aguja', 'scope': 'project', 'project_id': p['id']}
    assert client.post('/api/history/search', json=body).json()['results'][0]['conversation_id'] == c['id']
    body['project_id'] = 'missing'
    assert client.post('/api/history/search', json=body).status_code == 404
    for invalid in [{'query': ''}, {'query': 'a', 'scope': 'project'}, {'query': 'x', 'offset': 1001},
                    {'query': '*'}, {'query': 'x', 'role': 'system'}, {'query': 'x', 'project_id': p['id']}]:
        assert client.post('/api/history/search', json=invalid).status_code in (400, 422)


def test_branch_uses_index_triggers(env):
    client, state, _ = env
    p = state.store.create_project('Transferencia')
    c = state.store.create_conversation('Recetas', project_id=p['id'])
    state.store.add_message(c['id'], 'user', 'conservaraguja', created=1)
    second = state.store.add_message(c['id'], 'user', 'otro turno', created=2)
    fork = client.post(f"/api/conversations/{c['id']}/branch", json={'before': second['id']})
    assert fork.status_code == 200
    results = client.post('/api/history/search', json={'query': 'conservaraguja'}).json()['results']
    assert {r['conversation_id'] for r in results} == {c['id'], fork.json()['id']}


def test_imported_project_is_searchable_without_manual_reindex(env):
    client, state, _ = env
    p = state.store.create_project('Imported')
    c = state.store.create_conversation('Notes', project_id=p['id'])
    state.store.add_message(c['id'], 'user', 'importedneedle', created=1)
    exported = client.get(f"/api/projects/{p['id']}/export")
    assert exported.status_code == 200
    imported = client.post('/api/projects/import', content=exported.content)
    assert imported.status_code == 200
    q = imported.json()
    response = client.post('/api/history/search', json={'query': 'importedneedle', 'scope': 'project',
                                                       'project_id': q['id']})
    assert len(response.json()['results']) == 1
    assert response.json()['results'][0]['conversation_id'] != c['id']
