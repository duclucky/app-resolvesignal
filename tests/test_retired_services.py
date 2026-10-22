import json
import httpx
import pytest
from fastapi.testclient import TestClient
from src.main import create_app
from src import config


@pytest.mark.parametrize('public_demo', [False, True])
def test_retired_services_are_unavailable_even_to_owner(tmp_path, monkeypatch, public_demo):
    async def forbidden(*args, **kwargs):
        raise AssertionError('Retired services must never receive requests')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.setenv('APP_OPERATOR_TOKEN', 'owner-test')
    monkeypatch.setenv('APP_PUBLIC_DEMO', str(public_demo).lower())
    monkeypatch.setenv('TOLOKA_API_KEY', 'retained-but-unused')
    with TestClient(create_app(tmp_path/'state.sqlite')) as client:
        assert set(client.get('/api/workflow').json()['providers']) == {'nebius','tavily','langsmith'}
        for path in ('/api/operations/stage_toloka','/api/operations/prepare_toloka',
                     '/api/operations/start_toloka','/api/operations/poll_toloka',
                     '/api/quality/toloka/stage','/api/quality/check/toloka',
                     '/api/quality/review/toloka/import'):
            assert client.post(path,json={},headers={'x-operator-token':'owner-test'}).status_code == 404
        for path in ('/api/workflow/evaluation-packet','/api/quality/review/toloka'):
            assert client.get(path).status_code == 404
        for path in ('/quality','/connections','/api/status'):
            content=client.get(path).text.lower()
            assert 'toloka' not in content and 'tendem' not in content
        assert client.post('/api/quality/evaluate',json={}).json()['passed'] == 37


def test_retired_credentials_cannot_be_configured_and_receipts_survive(tmp_path, monkeypatch):
    env_file=tmp_path/'settings.env'
    monkeypatch.setattr(config,'ENV',env_file)
    app=create_app(tmp_path/'state.sqlite')
    with app.state.store.connect() as connection:
        connection.execute('CREATE TABLE IF NOT EXISTS quality_workflows(provider TEXT PRIMARY KEY, receipt TEXT)')
        connection.execute('INSERT INTO quality_workflows VALUES(?,?)',('toloka',json.dumps({'status':'failed','run_id':'historical'})))
    with TestClient(app) as client:
        client.post('/api/settings',json={'TOLOKA_API_KEY':'unused','TOLOKA_TEAM_ID':'unused'})
        assert not env_file.exists()
        assert 'historical' not in client.get('/api/workflow').text
    with app.state.store.connect() as connection:
        assert json.loads(connection.execute('SELECT receipt FROM quality_workflows WHERE provider=?',('toloka',)).fetchone()[0])['run_id']=='historical'
