"""Actual selected-page GETs and local API journey; no sponsor/provider credit use.

Keeps the existing user database/configuration untouched. Public source failures are
retained as partial outcomes. This is HTTP/API verification, not browser evidence.
"""
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import time

# Process-local overrides: never mutate .env or use configured quality/inference credits.
os.environ['LIVE_CALLS_ENABLED'] = 'false'
os.environ['LANGSMITH_ENABLED'] = 'false'
APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
import httpx
from fastapi.testclient import TestClient
from src.main import create_app
from src.policies import SELECTED_SOURCE_URLS

EVIDENCE = APP.parent / '.hackathon/evidence/ecommerce/selected-source-runtime'


def main():
    EVIDENCE.mkdir(exist_ok=True)
    database = APP / '.cache/selected-source-actual.sqlite3'
    if database.exists():
        raise RuntimeError('Actual-run database already exists; preserve evidence and choose a new run explicitly.')
    requests = []

    async def guard(request):
        url = str(request.url)
        if request.method != 'GET' or url not in SELECTED_SOURCE_URLS or len(requests) >= 4:
            raise AssertionError('Only four GETs to the two preselected public pages are permitted.')
        requests.append({'url': url, 'method': request.method, 'started_at': datetime.now(timezone.utc).isoformat()})

    async def record(response):
        requests[-1]['status'] = response.status_code

    client_class = httpx.AsyncClient

    def restricted_client(**kwargs):
        kwargs['event_hooks'] = {'request': [guard], 'response': [record]}
        return client_class(**kwargs)

    # Instrument the real HTTP client, without substituting pages or responses.
    httpx.AsyncClient = restricted_client
    started = datetime.now(timezone.utc).isoformat()
    with TestClient(create_app(database)) as client:
        assert not client.get('/api/status').json()['live_enabled']
        assert not client.get('/api/status').json()['langsmith_enabled']
        home = client.get('/')
        assert home.status_code == 200 and 'id="selected-pair"' in home.text
        assert SELECTED_SOURCE_URLS[0] in home.text and SELECTED_SOURCE_URLS[1] in home.text
        payload = {'idempotency_key': 'selected-source-actual-v1', 'mode': 'public', 'cases': [{
            'sku': 'Adafruit SSD same-merchant variant control', 'reference_url': SELECTED_SOURCE_URLS[0],
            'competitor_url': SELECTED_SOURCE_URLS[1]}]}
        response = client.post('/api/batches', json=payload)
        assert response.status_code == 200, 'Selected input rejected'
        bid = response.json()['id']
        cid = client.get('/api/batches/' + bid).json()['cases'][0]['id']

        def wait(revision):
            deadline = time.monotonic() + 125
            while time.monotonic() < deadline:
                row = client.get('/api/cases/' + cid).json()
                if row['revision'] >= revision and row['state'] in ('completed', 'partial', 'failed'):
                    return row
                time.sleep(.2)
            raise AssertionError('Actual API case did not finish within its deadline')

        first = wait(1)
        assert first['result']['comparison_scope']['kind'] == 'same_merchant_variant_control'
        assert first['result']['decision']['outcome'] in ('NOT_COMPARABLE', 'INSUFFICIENT_EVIDENCE')
        assert first['state'] in ('completed', 'partial'), 'Reviewable result was not produced'
        print(json.dumps({'stage': 'actual-first-result', 'state': first['state'],
                          'outcome': first['result']['decision']['outcome']}), flush=True)
        (EVIDENCE / 'actual-first.json').write_text(json.dumps(first, indent=2), encoding='utf-8')
        review = {'revision': 1, 'status': 'reviewed', 'note': 'Automated verification note, not an actual user review: inspect same-store variant evidence.'}
        assert client.post('/api/cases/' + cid + '/review', json=review).status_code == 200
        exports = []
        for fmt in ('json', 'csv', 'html'):
            response = client.get(f'/api/batches/{bid}/export?format={fmt}')
            assert response.status_code == 200 and 'same_merchant_variant_control' in response.text
            path = EVIDENCE / ('actual-reviewed.' + fmt)
            path.write_bytes(response.content)
            exports.append(path.name)
        assert client.post('/api/cases/' + cid + '/refresh', json={}).status_code == 200
        second = wait(2)
        assert len(second['history']) == 2 and second['reviews'][0]['revision'] == 1
        assert second['result']['comparison_scope']['kind'] == 'same_merchant_variant_control'
        assert second['result']['refresh_comparison']['previous_revision'] == 1
        stale = client.post('/api/cases/' + cid + '/review', json=review)
        assert stale.status_code == 409
        for fmt in ('json', 'csv', 'html'):
            response = client.get(f'/api/batches/{bid}/export?format={fmt}')
            assert response.status_code == 200 and 'same_merchant_variant_control' in response.text
            path = EVIDENCE / ('actual-rechecked.' + fmt)
            path.write_bytes(response.content)
            exports.append(path.name)
            if fmt == 'csv':
                assert list(csv.DictReader(io.StringIO(response.text)))[0]['review_status'] == 'unreviewed'
        assert client.post('/api/cases/' + cid + '/review', json={**review, 'revision': 2,
            'status': 'follow_up', 'note': 'Automated current-revision check, not a human attestation.'}).status_code == 200
        final = client.get('/api/cases/' + cid).json()
        assert any(r['revision'] == 2 for r in final['reviews'])
        assert client.get('/api/status').json()['usage_reserved'] == {}, 'No provider reservations permitted'
        report = {'method': 'Actual public-page retrieval through local app/API; no browser or sponsor calls',
                  'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(),
                  'batch_id': bid, 'case_id': cid, 'isolated_database': str(database.relative_to(APP)),
                  'public_requests': requests, 'first_state': first['state'],
                  'first_outcome': first['result']['decision']['outcome'],
                  'refresh_state': second['state'], 'refresh_outcome': second['result']['decision']['outcome'],
                  'refresh_comparison': second['result']['refresh_comparison'],
                  'review_saved': True, 'stale_review_status': stale.status_code,
                  'current_revision_review_saved': True, 'history_revisions': len(second['history']),
                  'exports': exports, 'same_merchant_scope_preserved': True,
                  'provider_reservations': {}, 'provider_calls': 0, 'browser_verified': False,
                  'fresh_sponsor_run_verified': False,
                  'source_failures': [first['result'].get('source_failures'), second['result'].get('source_failures')]}
        (EVIDENCE / 'actual-final.json').write_text(json.dumps(final, indent=2), encoding='utf-8')
        (EVIDENCE / 'actual-api-journey.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
