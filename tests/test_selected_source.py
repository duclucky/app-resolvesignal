"""Selected-source integration controls; HTTP/offer values here are constructed."""
import asyncio
import csv
import io
import json
import time

import pytest
from fastapi.testclient import TestClient

from src.main import create_app
from src.parser import parse_offer
from src.policies import validate_url


URLS = ("https://www.adafruit.com/product/6090", "https://www.adafruit.com/product/6089")


def constructed_html(capacity, price):
    data = {"@type": "Product", "name": f"Test NVMe SSD - {capacity}GB",
            "sku": capacity, "offers": {"@type": "Offer", "price": price,
            "priceCurrency": "USD", "itemCondition": "https://schema.org/NewCondition",
            "availability": "https://schema.org/OutOfStock"}}
    return '<script type="application/ld+json">' + json.dumps(data) + '</script>'


def wait_case(client, cid, revision):
    for _ in range(100):
        row = client.get('/api/cases/' + cid).json()
        if row['revision'] >= revision and row['state'] in ('completed', 'partial', 'failed'):
            return row
        time.sleep(.01)
    raise AssertionError('Case did not finish')


def test_selected_pair_public_review_export_and_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv('LANGSMITH_ENABLED', 'false')
    monkeypatch.setenv('LIVE_CALLS_ENABLED', 'false')
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('1.1.1.1', 443))])
    calls = []

    async def retrieve(url):
        calls.append(url)
        capacity = 256 if url == URLS[0] else 512
        price = '40' if url == URLS[0] and len(calls) > 2 else '50'
        html = constructed_html(capacity, price)
        return parse_offer(html, url), html

    monkeypatch.setattr('src.agent.retrieve', retrieve)
    app = create_app(tmp_path / 'selected.sqlite')
    with TestClient(app) as client:
        payload = {'idempotency_key': 'selected-source-regression', 'mode': 'public',
                   'cases': [{'sku': 'Selected SSD source control', 'reference_url': URLS[0],
                              'competitor_url': URLS[1]}]}
        response = client.post('/api/batches', json=payload)
        assert response.status_code == 200, response.text
        bid = response.json()['id']
        cid = client.get('/api/batches/' + bid).json()['cases'][0]['id']
        row = wait_case(client, cid, 1)
        assert row['state'] == 'completed'
        result = row['result']
        assert result['decision']['outcome'] == 'NOT_COMPARABLE'
        assert result['decision']['gap_percent'] is None
        assert result['comparison_scope']['kind'] == 'same_merchant_variant_control'
        assert 'not a competitor-price opportunity' in result['comparison_scope']['notice']
        assert all(o['quantity'] is None and o['eligibility'] is None for o in result['offers'])
        review = {'revision': 1, 'status': 'reviewed', 'note': 'Variant mismatch; retain evidence.'}
        assert client.post('/api/cases/' + cid + '/review', json=review).status_code == 200
        for fmt in ('csv', 'json', 'html'):
            response = client.get(f'/api/batches/{bid}/export?format={fmt}')
            assert response.status_code == 200
            assert 'same_merchant_variant_control' in response.text
        assert client.post('/api/cases/' + cid + '/refresh', json={}).status_code == 200
        row = wait_case(client, cid, 2)
        assert row['result']['comparison_scope']['kind'] == 'same_merchant_variant_control'
        assert row['result']['refresh_comparison']['fields'] == [
            {'side': 'reference', 'field': 'price', 'before': '50', 'after': '40'}]
        assert len(row['history']) == 2 and row['reviews'][0]['revision'] == 1
        assert client.post('/api/cases/' + cid + '/review', json=review).status_code == 409
        rows = list(csv.DictReader(io.StringIO(client.get(f'/api/batches/{bid}/export?format=csv').text)))
        assert rows[0]['review_status'] == 'unreviewed'
        assert calls == list(URLS) * 2


def test_selected_source_marker_remains_narrow_while_other_public_urls_are_accepted():
    from src.policies import is_selected_source
    for url in URLS:
        assert validate_url(url, resolve=False) == url
        assert is_selected_source(url)
    for url in ('https://shop.adafruit.com/product/6090',
                'https://www.adafruit.com/product/9999',
                'https://www.adafruit.com/api/product/6090',
                URLS[0] + '?token=hidden', URLS[0] + '#other',
                'https://www.adafruit.com/product/%36%30%39%30'):
        assert validate_url(url, resolve=False)==url
        assert not is_selected_source(url)


def test_selected_source_retrieval_throttles_and_rejects_unapproved_redirect(monkeypatch):
    monkeypatch.setattr('src.policies.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    async def check_retrieval():
        import httpx
        from src.providers import public_pages
        from src.policies import validate_url as check
        clock = [100.0]
        starts = []
        monkeypatch.setattr(public_pages, '_next_source_request', 0.0)
        monkeypatch.setattr(public_pages, 'monotonic', lambda: clock[0])
    
        async def sleep(delay):
            clock[0] += delay
    
        def handler(request):
            starts.append(clock[0])
            return httpx.Response(200, text=constructed_html(256, '50'), headers={'content-type': 'text/html'})
    
        client_class = httpx.AsyncClient
        monkeypatch.setattr(public_pages, '_sleep', sleep)
        monkeypatch.setattr(public_pages, 'validate_url', lambda url: check(url, resolve=False))
        monkeypatch.setattr(public_pages.httpx, 'AsyncClient',
                            lambda **kw: client_class(**kw, transport=httpx.MockTransport(handler)))
        for url in URLS:
            offer, _ = await public_pages.retrieve(url)
            assert offer.capacity == '256 GB'
        assert starts == [100.0, 115.0]
    
        for target in ('https://www.adafruit.com/product/9999', 'https://samsung.com/other-product'):
            seen = []

            def redirect(request):
                seen.append(str(request.url))
                assert request.url.path == '/product/6090' and request.headers['host']=='www.adafruit.com', 'Unapproved redirect destination was requested'
                return httpx.Response(302, headers={'location': target})

            monkeypatch.setattr(public_pages.httpx, 'AsyncClient',
                                lambda **kw: client_class(**kw, transport=httpx.MockTransport(redirect)))
            with pytest.raises(ValueError, match='two selected'):
                await public_pages.retrieve(URLS[0])
            assert seen == ['https://93.184.216.34/product/6090']
    asyncio.run(check_retrieval())


def test_selected_source_failure_retains_scope_and_never_claims_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv('LANGSMITH_ENABLED', 'false')
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('1.1.1.1', 443))])
    calls = []

    async def retrieve(url):
        calls.append(url)
        if len(calls) > 2:
            raise ValueError('Source unavailable')
        html = constructed_html(256 if url == URLS[0] else 512, '50')
        return parse_offer(html, url), html

    monkeypatch.setattr('src.agent.retrieve', retrieve)
    with TestClient(create_app(tmp_path / 'failed-refresh.sqlite')) as client:
        bid = client.post('/api/batches', json={'idempotency_key': 'selected-failure-test',
            'mode': 'public', 'cases': [{'reference_url': URLS[0], 'competitor_url': URLS[1]}]}).json()['id']
        cid = client.get('/api/batches/' + bid).json()['cases'][0]['id']
        wait_case(client, cid, 1)
        client.post('/api/cases/' + cid + '/refresh', json={})
        row = wait_case(client, cid, 2)
        assert row['state'] == 'partial' and row['result']['source_failures']
        assert row['result']['decision']['outcome'] == 'INSUFFICIENT_EVIDENCE'
        assert row['result']['comparison_scope']['kind'] == 'same_merchant_variant_control'
        assert row['result']['refresh_comparison']['complete_pair'] is False
        assert len(row['history']) == 2


def test_live_workflow_keeps_selected_source_under_direct_rate_gate(tmp_path, monkeypatch):
    """Mock provider boundaries; this is not evidence of actual sponsor integration."""
    from src.agent import Investigator
    from src.store import Store
    monkeypatch.setenv('LANGSMITH_ENABLED', 'false')
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('1.1.1.1', 443))])
    calls = []

    class Providers:
        def __init__(self, store):
            self.trace = []

        async def extract(self, urls):
            raise AssertionError('Selected source must not bypass its direct rate gate via remote extraction')

        async def reason(self, prompt, **kwargs):
            calls.append('reason')
            if calls.count('reason') == 1:
                return {'query': 'Test SSD capacity', 'missing_fields': ['quantity']}
            return {'offers': [{'claims': {}}, {'claims': {}}]}

        async def search(self, query):
            calls.append('search')
            return {'results': [{'url': URLS[0], 'title': 'Discovery lead', 'content': 'not final evidence'}]}

    async def retrieve(url):
        html = constructed_html(256 if url == URLS[0] else 512, '50')
        return parse_offer(html, url), html

    monkeypatch.setattr('src.agent.LiveProviders', Providers)
    monkeypatch.setattr('src.agent.retrieve', retrieve)
    store = Store(tmp_path / 'mock-live.sqlite')
    bid, _ = store.create_batch({'idempotency_key': 'mock-live-rate-policy', 'mode': 'live',
        'cases': [{'reference_url': URLS[0], 'competitor_url': URLS[1]}]})
    cid = store.batch(bid)[0]['id']
    asyncio.run(Investigator(store).run(cid))
    result = store.case(cid)['result']
    assert result['decision']['outcome'] == 'NOT_COMPARABLE'
    assert result['comparison_scope']['kind'] == 'same_merchant_variant_control'
    assert calls == ['reason', 'search', 'reason']


def test_selected_public_inspection_never_dispatches_optional_cloud_tracing(tmp_path, monkeypatch):
    from src.agent import Investigator
    from src.store import Store
    monkeypatch.setenv('LANGSMITH_ENABLED', 'true')
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('1.1.1.1', 443))])

    async def forbidden_trace(*args, **kwargs):
        raise AssertionError('Selected public inspection must not dispatch optional provider calls')

    async def retrieve(url):
        html = constructed_html(256 if url == URLS[0] else 512, '50')
        return parse_offer(html, url), html

    monkeypatch.setattr('src.providers.quality.LangSmith.record', forbidden_trace)
    monkeypatch.setattr('src.agent.retrieve', retrieve)
    store = Store(tmp_path / 'no-public-cloud.sqlite')
    bid, _ = store.create_batch({'idempotency_key': 'public-no-cloud-regression', 'mode': 'public',
        'cases': [{'reference_url': URLS[0], 'competitor_url': URLS[1]}]})
    cid = store.batch(bid)[0]['id']
    asyncio.run(Investigator(store).run(cid))
    assert store.case(cid)['result']['decision']['outcome'] == 'NOT_COMPARABLE'
    assert store.usage() == {}
