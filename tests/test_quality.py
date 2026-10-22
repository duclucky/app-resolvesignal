import asyncio
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from src.main import create_app


def test_quality_corpus_runs_without_credentials_or_network(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError('Offline evaluation attempted a network request')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    with TestClient(create_app(tmp_path/'quality.sqlite')) as client:
        response=client.post('/api/quality/evaluate',json={})
        assert response.status_code==200
        report=response.json()
        assert report['total']>=24 and report['passed']==report['total']
        assert report['dataset_kind']=='synthetic_sourced_scenarios'
        assert report['live_provider_calls']==0
        assert report['false_comparable']==0
        assert all(r['sources'] and r['passed'] for r in report['cases'])



def test_langsmith_trace_minimizes_data_and_degrades_safely():
    from src.providers.quality import LangSmith
    requests=[]
    async def handle(request):
        requests.append(request)
        if request.method=='GET':return httpx.Response(200,json={'id':request.url.path.split('/')[-1]})
        return httpx.Response(200,json={})
    s={'LANGSMITH_API_KEY':'private-secret','LANGSMITH_ENABLED':'true'}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            p=LangSmith(s,client=client)
            return await p.record('fixture',{'mode':'synthetic','offers':[{'url':'https://example.com/?token=secret','title':'private'}], 'decision':{'outcome':'NOT_COMPARABLE','action':'DISMISS_MISMATCH'},'trace':[{'provider':'nebius','status':'ok','elapsed_ms':2,'secret':'leak'}]})
    result=asyncio.run(run())
    assert result['status']=='verified'
    bodies=' '.join(r.content.decode() for r in requests)
    assert 'private-secret' not in bodies and 'token=secret' not in bodies and 'private' not in bodies and 'leak' not in bodies
    assert any(json.loads(r.content).get('parent_run_id') for r in requests if r.method=='POST')




def test_langsmith_eventual_readback_and_failure_never_raise():
    from src.providers.quality import LangSmith
    reads=0
    async def handle(request):
        nonlocal reads
        if request.method=='GET':
            reads+=1
            if reads<3:return httpx.Response(404,json={})
            return httpx.Response(200,json={'id':request.url.path.split('/')[-1]})
        return httpx.Response(200,json={})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await LangSmith({'LANGSMITH_API_KEY':'key','LANGSMITH_ENABLED':'true'},client).record('eventual',{'decision':{}})
    assert asyncio.run(run())['status']=='verified' and reads==3


def test_langsmith_cap_stops_network_and_failed_trace_preserves_case(tmp_path):
    from src.providers.quality import LangSmith
    from src.store import Store
    store=Store(tmp_path/'cap.sqlite');store.reserve('langsmith_reserved_runs',100,100)
    bid,_=store.create_batch({'idempotency_key':'trace-cap-case','mode':'live','cases':[{'sku':'x'}]})
    cid=store.batch(bid)[0]['id'];original={'decision':{'outcome':'NOT_COMPARABLE'}};store.finish(cid,original)
    async def forbidden(request):raise AssertionError('No calls after cap')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            return await LangSmith({'LANGSMITH_API_KEY':'key','LANGSMITH_ENABLED':'true'},client,store).record(cid,original)
    receipt=asyncio.run(run());assert receipt['status']=='failed'
    store.attach_observation(cid,1,receipt)
    assert store.case(cid)['result']['decision']==original['decision']
    store.requeue(cid);store.finish(cid,original)
    assert not store.attach_observation(cid,1,receipt)


def test_langsmith_suite_batches_minimized_results_and_verifies_all_cases():
    from src.providers.quality import LangSmith
    from src.quality import evaluate
    runs=[];requests=[]
    async def handle(r):
        requests.append(r)
        if r.url.path=='/runs/batch':runs.extend(json.loads(r.content)['post'])
        if r.url.path=='/runs/query':return httpx.Response(200,json={'runs':[{'id':x['id'],'outputs':x['outputs']} for x in runs]})
        return httpx.Response(200,json={})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            return await LangSmith({'LANGSMITH_API_KEY':'key','LANGSMITH_ENABLED':'true'},client).record_evaluation(evaluate())
    result=asyncio.run(run())
    assert result['status']=='verified' and result['uploaded']==37 and len(requests)==3
    assert len(runs)==38 and sum(bool(r.get('parent_run_id')) for r in runs)==37
    assert 'https://' not in ' '.join(r.content.decode() for r in requests)


def test_synthetic_batch_export_stays_explicit(tmp_path,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('Synthetic batch must be offline')
    monkeypatch.setattr(httpx.AsyncClient,'request',forbidden)
    with TestClient(create_app(tmp_path/'batch.sqlite')) as client:
        batch=client.post('/api/quality/batch',json={'idempotency_key':'synthetic-review-export'}).json()
        import time
        for _ in range(40):
            rows=client.get('/api/batches/'+batch['id']).json()['cases']
            if all(row['state']=='completed' for row in rows):break
            time.sleep(.01)
        assert len(rows)==37 and all(row['result']['mode']=='synthetic' for row in rows)
        html=client.get('/api/batches/'+batch['id']+'/export?format=html').text
        assert 'Constructed sample. No current prices' in html
        assert 'synthetic' in client.get('/api/batches/'+batch['id']+'/export?format=csv').text


def test_public_investigation_records_optional_receipt_on_its_revision(tmp_path,monkeypatch):
    from src.agent import Investigator
    from src.schemas import Offer
    from src.store import Store
    store=Store(tmp_path/'observed.sqlite')
    bid,_=store.create_batch({'idempotency_key':'observed-public','mode':'public','cases':[
        {'sku':'unreadable','reference_url':'https://samsung.com/a','competitor_url':'https://samsung.com/b'}]})
    cid=store.batch(bid)[0]['id'];seen=[]
    async def retrieve(url):return Offer(url=url),''
    async def record(self,case_id,result,evaluation=None):
        seen.append(case_id);assert result['decision']['outcome']=='INSUFFICIENT_EVIDENCE'
        return {'status':'verified','run_id':'test-receipt'}
    monkeypatch.setattr('src.agent.validate_url',lambda *a,**k:None)
    monkeypatch.setattr('src.agent.retrieve',retrieve)
    monkeypatch.setattr('src.providers.quality.LangSmith.record',record)
    asyncio.run(Investigator(store).run(cid))
    row=store.case(cid)
    assert seen==[cid] and row['result']['observability']['status']=='verified'
    assert row['history'][0]['result']['observability']==row['result']['observability']
