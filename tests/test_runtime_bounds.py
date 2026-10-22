import asyncio
import json

import httpx
import pytest

from src.agent import Investigator
from src.schemas import Offer, Evidence
from src.store import Store
from test_providers import provider


def transport_for(monkeypatch, responses):
    original = httpx.AsyncClient
    requests = []

    def respond(request):
        requests.append(request)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr('src.providers.live.httpx.AsyncClient',
                        lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    return requests


def test_retry_after_charges_each_attempt_and_redacts_response(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    requests = transport_for(monkeypatch, [
        httpx.Response(429, headers={'Retry-After': '2'}, text='secret-provider-body'),
        httpx.Response(200, json={'results': []}),
    ])
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(asyncio, 'sleep', sleep)
    assert asyncio.run(p.search('SSD')) == {'results': []}
    assert delays == [2] and len(requests) == 2 and p.searches == 2
    assert p.store.usage()['tavily_reserved_credits'] == 4
    assert 'secret-provider-body' not in json.dumps(p.trace)


def test_denied_access_is_not_retried(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    requests = transport_for(monkeypatch, [httpx.Response(403, text='secret')])
    with pytest.raises(ValueError, match='request failed'):
        asyncio.run(p.search('SSD'))
    assert len(requests) == 1


def test_retry_cannot_exceed_page_cap(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    requests = transport_for(monkeypatch, [httpx.Response(503)] * 3)
    async def sleep(delay):
        pass
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    with pytest.raises(ValueError, match='Page limit'):
        asyncio.run(p.extract(['https://samsung.com/a'] * 4))
    assert len(requests) == 1 and p.pages == 4


def test_cumulative_input_budget_blocks_before_next_request(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    calls = []
    async def post(*args):
        calls.append(args)
        return {'choices': [{'message': {'content': '{}'}}]}
    p.post = post
    asyncio.run(p.reason('a' * 13000, max_tokens=100))
    with pytest.raises(ValueError, match='input token budget'):
        asyncio.run(p.reason('b' * 13000, max_tokens=100))
    assert len(calls) == 1


def test_schema_gets_one_repair_within_shared_budget(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    responses = ['{"offers":[]}', '{"offers":[{"claims":{}},{"claims":{}}]}']
    async def post(*args):
        return {'choices': [{'message': {'content': responses.pop(0)}}]}
    p.post = post
    def validate(value):
        return isinstance(value.get('offers'), list) and len(value['offers']) == 2
    result = asyncio.run(p.reason('Extract offers', max_tokens=400, validator=validate))
    assert len(result['offers']) == 2 and p.calls == 2
    assert p.trace[-1]['status'] == 'schema_repair'


def test_success_settles_token_reservations_to_reported_usage(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    response = {'choices': [{'message': {'content': '{}'}}],
                'usage': {'prompt_tokens': 1000, 'completion_tokens': 10}}
    requests = transport_for(monkeypatch, [httpx.Response(200, json=response)] * 2)
    async def run():
        await p.reason('a' * 13000, max_tokens=100)
        await p.reason('b' * 13000, max_tokens=100)
    asyncio.run(run())
    assert len(requests) == 2 and p.input_tokens == 2000 and p.output_tokens == 20


def test_invalid_schema_repairs_only_once(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    async def post(*args):
        return {'choices': [{'message': {'content': '{}'}}]}
    p.post = post
    with pytest.raises(ValueError, match='invalid schema'):
        asyncio.run(p.reason('Extract', validator=lambda value:False))
    assert p.calls == 2


def test_reduced_prompt_keeps_contract_and_selected_evidence():
    from src.prompts import extraction_prompt
    offers=[Offer(url='https://samsung.com/a')]*2
    prompt=extraction_prompt(offers,['selected evidence\n'+'x'*6000]*2,[{'content':'y'*6000}],
                             page_limit=1000,research_limit=0)
    assert 'EXACTLY TWO' in prompt and 'Do not infer new' in prompt
    assert 'selected evidence' in prompt and 'y'*100 not in prompt
    assert len(prompt.encode('utf-8'))<6000


def test_cancel_during_retry_prevents_next_request(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    requests = transport_for(monkeypatch, [httpx.Response(429, headers={'Retry-After': '1'})])
    cancelled = False
    def active():
        if cancelled:
            raise asyncio.CancelledError()
    p.check_active = active
    async def sleep(delay):
        nonlocal cancelled
        cancelled = True
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(p.search('SSD'))
    assert len(requests) == 1


def test_long_retry_after_stops_without_early_retry(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    requests = transport_for(monkeypatch, [httpx.Response(429, headers={'Retry-After': '300'})])
    with pytest.raises(ValueError, match='deadline'):
        asyncio.run(p.search('SSD'))
    assert len(requests) == 1


def test_network_timeout_retries_at_most_twice(monkeypatch, tmp_path):
    p = provider(monkeypatch, tmp_path)
    requests = transport_for(monkeypatch, [httpx.ReadTimeout('private detail')] * 3)
    delays = []
    async def sleep(delay):
        delays.append(delay)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    with pytest.raises(ValueError, match='request failed'):
        asyncio.run(p.search('SSD'))
    assert len(requests)==3 and delays==[1,2]
    assert p.searches==3 and p.store.usage()['tavily_reserved_credits']==6
    assert 'private detail' not in json.dumps(p.trace)


def test_reason_failure_preserves_collected_evidence_as_partial(monkeypatch, tmp_path):
    # Retrieval/providers are fixtures; keep DNS deterministic without bypassing URL/IP validation.
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    store = Store(tmp_path / 'cases.sqlite')
    bid, _ = store.create_batch({'idempotency_key': 'partial', 'mode': 'live', 'cases': [{
        'sku': 'real-format', 'reference_url': 'https://samsung.com/a',
        'competitor_url': 'https://bestbuy.com/b'}]})
    cid = store.batch(bid)[0]['id']
    class Providers:
        def __init__(self, store):
            self.trace = []
        async def extract(self, urls):
            return {'results': [{'url': u, 'raw_content': '# SSD\nModel: SSD-X'} for u in urls]}
        async def reason(self, *args, **kwargs):
            raise ValueError('nebius request failed')
    async def retrieve(url):
        o = Offer(url=url, title='SSD-X', category='ssd', mpn='SSD-X')
        o.evidence.append(Evidence(id=url, url=url, field='mpn', excerpt='Model: SSD-X'))
        return o, 'Model: SSD-X'
    async def telemetry(*args):
        return {'status': 'disabled'}
    monkeypatch.setattr('src.agent.LiveProviders', Providers)
    monkeypatch.setattr('src.agent.retrieve', retrieve)
    monkeypatch.setattr('src.providers.quality.LangSmith.record', telemetry)
    asyncio.run(Investigator(store).run(cid))
    row = store.case(cid)
    assert row['state'] == 'partial' and len(row['result']['offers']) == 2
    assert row['result']['decision']['outcome'] == 'INSUFFICIENT_EVIDENCE'
    assert row['result']['offers'][0]['evidence'][0]['excerpt'] == 'Model: SSD-X'


def test_extract_failure_still_uses_public_source_fallback(monkeypatch, tmp_path):
    # Retrieval/providers are fixtures; keep DNS deterministic without bypassing URL/IP validation.
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    store = Store(tmp_path / 'fallback.sqlite')
    bid, _ = store.create_batch({'idempotency_key': 'fallback', 'mode': 'live', 'cases': [{
        'sku': 'fallback', 'reference_url': 'https://samsung.com/a',
        'competitor_url': 'https://bestbuy.com/b'}]})
    cid = store.batch(bid)[0]['id']
    class Providers:
        def __init__(self, store):
            self.trace = []
        async def extract(self, urls):
            raise ValueError('tavily request failed')
        async def reason(self, *args, **kwargs):
            return {'query': '', 'offers': [{'claims': {}}, {'claims': {}}]}
    async def retrieve(url):
        return Offer(url=url, title='SSD-X', category='ssd'), 'SSD-X'
    monkeypatch.setattr('src.agent.LiveProviders', Providers)
    monkeypatch.setattr('src.agent.retrieve', retrieve)
    agent = Investigator(store)
    agent.contexts[cid] = {}
    asyncio.run(agent._run(cid))
    row = store.case(cid)
    assert row['state'] == 'partial' and len(row['result']['offers']) == 2
    assert 'Tavily' in row['result']['source_failures'][0]

