from fastapi.testclient import TestClient

from src.main import create_app
from src import config


def test_hosted_origin_is_exact_and_settings_are_server_managed(tmp_path, monkeypatch):
    env_file = tmp_path / 'operator.env'
    monkeypatch.setattr(config, 'ENV', env_file)
    monkeypatch.setenv('APP_ALLOWED_ORIGINS', 'http://127.0.0.1:4840,http://localhost:4840')
    monkeypatch.setenv('APP_SETTINGS_LOCKED', 'true')
    with TestClient(create_app(tmp_path / 'hosted.sqlite')) as client:
        allowed = {'origin': 'http://127.0.0.1:4840'}
        preview = {'csv': 'sku,reference_url,competitor_url\nssd,https://samsung.com/a,https://bestbuy.com/b'}
        assert client.post('/api/batches/preview', json=preview, headers=allowed).status_code == 200
        assert client.post('/api/batches/preview', json=preview, headers={'origin': 'http://127.0.0.1:4840.evil.example'}).status_code == 403
        assert client.post('/api/settings', json={'LIVE_CALLS_ENABLED': 'true'}, headers=allowed).status_code == 403
        assert not env_file.exists()
        assert client.get('/api/status').json()['settings_managed'] is True
        assert client.get('/', headers={'host': 'untrusted.example'}).status_code == 403


def test_hosted_lock_blocks_paid_quality_actions_but_not_local_work(tmp_path, monkeypatch):
    import httpx
    async def forbidden(*args, **kwargs):
        raise AssertionError('Hosted lock must reject before any provider request.')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.setenv('APP_EXTERNAL_ACTIONS_ENABLED', 'false')
    with TestClient(create_app(tmp_path / 'offline.sqlite')) as client:
        for url in ['/api/quality/check/langsmith', '/api/quality/langsmith/evaluate']:
            assert client.post(url, json={}).status_code == 403
        assert client.post('/api/quality/evaluate', json={}).json()['passed'] == 37
        result = client.post('/api/samples', json={'idempotency_key': 'hosted-offline-samples'})
        assert result.status_code == 200
        assert client.get('/healthz').json() == {'service': 'price-alert-investigator', 'status': 'ok'}


def test_profile_state_path_is_used_without_writing_to_release(tmp_path, monkeypatch):
    state = tmp_path / 'state'
    monkeypatch.setenv('APP_DATA_DIR', str(state))
    app = create_app()
    assert app.state.store.path == str(state / 'investigations.sqlite3')
    with TestClient(app) as client:
        assert client.get('/healthz').status_code == 200
    assert (state / 'investigations.sqlite3').exists()
