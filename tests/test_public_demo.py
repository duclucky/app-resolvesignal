from fastapi.testclient import TestClient

from src.main import create_app
from src import config


def demo_client(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_PUBLIC_DEMO', 'true')
    monkeypatch.setenv('APP_ALLOWED_ORIGINS', 'https://app.resolvesignal.com')
    monkeypatch.setattr(config, 'ENV', tmp_path / 'absent.env')
    return TestClient(create_app(tmp_path / 'demo.sqlite'))


def test_public_demo_has_disclosure_and_locks_admin_actions(tmp_path, monkeypatch):
    with demo_client(tmp_path, monkeypatch) as client:
        assert 'Shared public demo' in client.get('/new').text
        headers = {'origin': 'https://app.resolvesignal.com'}
        for path in ('/api/settings', '/api/quality/check/langsmith'):
            assert client.post(path, json={}, headers=headers).status_code == 403


def test_public_samples_are_shared_without_importing_private_data(tmp_path, monkeypatch):
    with demo_client(tmp_path, monkeypatch) as client:
        assert client.get('/api/batches').json() == []
        first = client.post('/api/samples', json={'idempotency_key': 'visitor-one'}).json()
        second = client.post('/api/samples', json={'idempotency_key': 'visitor-two'}).json()
        assert first['id'] == second['id']
        assert len(client.get('/api/batches').json()) == 1


def test_public_demo_rejects_private_live_inputs_before_any_provider(tmp_path, monkeypatch):
    import httpx
    async def forbidden(*args, **kwargs):
        raise AssertionError('Rejected inputs must not reach any provider.')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    with demo_client(tmp_path, monkeypatch) as client:
        payload = {'mode': 'live', 'idempotency_key': 'unapproved-public-input', 'cases': [
            {'sku': 'custom', 'reference_url': 'https://127.0.0.1/a', 'competitor_url': 'https://bestbuy.com/b'}]}
        assert client.post('/api/batches', json=payload).status_code == 422


def test_public_demo_bounds_write_rate(tmp_path, monkeypatch):
    with demo_client(tmp_path, monkeypatch) as client:
        codes = [client.post('/api/batches/preview', json={'csv': ''}).status_code for _ in range(31)]
        assert codes[:30] == [422] * 30
        assert codes[-1] == 429


def test_live_demo_works_with_bounded_shared_rechecks(tmp_path, monkeypatch):
    import src.main as main
    from src.samples import sample_result
    monkeypatch.setenv('LIVE_CALLS_ENABLED', 'true')
    monkeypatch.setattr(main, 'validate_url', lambda url: url)
    async def complete(self, cid):
        self.store.finish(cid, sample_result('comparable'))
    monkeypatch.setattr(main.Investigator, 'run', complete)
    with demo_client(tmp_path, monkeypatch) as client:
        payload = {'mode': 'live', 'idempotency_key': 'demo-live-request', 'cases': [
            {'reference_url': main.SELECTED_SOURCE_URLS[0], 'competitor_url': main.SELECTED_SOURCE_URLS[1]}]}
        response = client.post('/api/batches', json=payload)
        assert response.status_code == 200
        bid = response.json()['id']
        assert client.post('/api/batches', json=payload).json()['id'] == bid
        cid = client.get('/api/batches/' + bid).json()['cases'][0]['id']
        assert client.post('/api/cases/' + cid + '/refresh', json={}).status_code == 200
        assert client.post('/api/cases/' + cid + '/refresh', json={}).status_code == 200
        assert client.post('/api/cases/' + cid + '/refresh', json={}).status_code == 429
