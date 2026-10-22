"""Offline review, persistence, export and profile-boundary regressions."""
import csv
import io
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from src import config
from src.main import create_app
from src.samples import sample_result
from src.store import Store


@pytest.fixture(autouse=True)
def offline_profile(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_PUBLIC_DEMO', 'false')
    monkeypatch.setenv('LIVE_CALLS_ENABLED', 'false')
    monkeypatch.setenv('LANGSMITH_ENABLED', 'false')
    monkeypatch.setattr(config, 'ENV', tmp_path/'no-credentials.env')
    async def forbidden(*args, **kwargs):
        raise AssertionError('Review and export must not call a live service')
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)


def seed(app, kind='unknown'):
    bid, _ = app.state.store.create_batch({'idempotency_key':'extended-review-check', 'mode':'sample',
        'cases':[{'sku':'Local review fixture','reference_url':'https://example.com/reference',
                  'competitor_url':'https://example.com/competitor'}]})
    cid = app.state.store.batch(bid)[0]['id']
    app.state.store.finish(cid, sample_result(kind))
    return bid, cid


@pytest.mark.parametrize('status', ['reviewed','disputed','follow_up'])
@pytest.mark.parametrize('note', ['', 'Kiểm tra giá — 日本語 ✅\nSecond line, with commas', 'x'*2000])
def test_review_round_trip_survives_reopen_and_exports(tmp_path, status, note):
    path=tmp_path/'review.sqlite';app=create_app(path);bid,cid=seed(app)
    with TestClient(app) as client:
        assert client.post(f'/api/cases/{cid}/review',json={'revision':1,'status':status,'note':note}).status_code==200
    reopened=create_app(path)
    with TestClient(reopened) as client:
        case=client.get(f'/api/cases/{cid}').json()
        assert case['reviews'][0]['status']==status and case['reviews'][0]['note']==note
        data=client.get(f'/api/batches/{bid}/export?format=json').json()[0]
        assert data['reviews']==case['reviews'] and data['decision_current'] is True
        row=next(csv.DictReader(io.StringIO(client.get(f'/api/batches/{bid}/export?format=csv').text)))
        assert row['review_status']==status and row['revision']=='1'
    assert reopened.state.store.usage()=={}


@pytest.mark.parametrize('change', [{'status':'approved'},{'note':'x'*2001},{'note':None},
                                    {'revision':0},{'revision':99}])
def test_invalid_or_stale_review_cannot_add_history(tmp_path, change):
    app=create_app(tmp_path/'invalid.sqlite');_,cid=seed(app)
    before=app.state.store.case(cid)
    with TestClient(app) as client:
        payload={'revision':1,'status':'reviewed','note':'must not be saved',**change}
        assert client.post(f'/api/cases/{cid}/review',json=payload).status_code in (409,422)
    assert app.state.store.case(cid)==before and app.state.store.usage()=={}


@pytest.mark.parametrize('state', ['queued','collecting','investigating','validating','failed','cancelled','interrupted'])
def test_inactive_or_running_attempt_cannot_accept_review_or_export_current_decision(tmp_path, state):
    app=create_app(tmp_path/'state.sqlite');bid,cid=seed(app,'comparable')
    with TestClient(app) as client:
        app.state.store.update_state(cid,state)
        before=app.state.store.case(cid)
        assert client.post(f'/api/cases/{cid}/review',json={'revision':1,'status':'reviewed'}).status_code==409
        assert app.state.store.case(cid)==before
        data=client.get(f'/api/batches/{bid}/export?format=json').json()[0]
        assert data['decision_current'] is False
        row=next(csv.DictReader(io.StringIO(client.get(f'/api/batches/{bid}/export?format=csv').text)))
        assert row['outcome']==row['action']==row['gap_percent']==''
        assert row['review_status']=='not_current' and row['retained_outcome']=='COMPARABLE_LISTED_PRICE'


def test_parallel_reviews_are_not_lost_and_original_result_is_unchanged(tmp_path):
    app=create_app(tmp_path/'parallel.sqlite');_,cid=seed(app)
    original=app.state.store.case(cid)['result']
    def save(index):
        app.state.store.review(cid,{'revision':1,'status':'follow_up','note':f'reviewer-{index}'})
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(save, range(8)))
    saved=Store(app.state.store.path).case(cid)
    assert len(saved['reviews'])==8
    assert {r['note'] for r in saved['reviews']}=={f'reviewer-{i}' for i in range(8)}
    assert saved['result']==original and len(saved['history'])==1


def test_two_profiles_do_not_share_cases_reviews_or_group_links(tmp_path):
    first=create_app(tmp_path/'first.sqlite');bid,cid=seed(first)
    second=create_app(tmp_path/'second.sqlite')
    with TestClient(first) as a, TestClient(second) as b:
        assert a.post(f'/api/cases/{cid}/review',json={'revision':1,'status':'reviewed','note':'first only'}).status_code==200
        for path in [f'/cases/{cid}',f'/api/cases/{cid}',f'/api/batches/{bid}',f'/api/batches/{bid}/export?format=json']:
            assert b.get(path).status_code==404
        assert b.post(f'/api/cases/{cid}/review',json={'revision':1,'status':'reviewed'}).status_code==404
        assert b.get('/api/batches').json()==[]
        assert a.get(f'/api/cases/{cid}').json()['reviews'][0]['note']=='first only'


def test_escaped_review_and_source_text_remain_data_in_report(tmp_path):
    app=create_app(tmp_path/'escape.sqlite');bid,cid=seed(app)
    payload='<script>alert("review")</script><img src=x onerror=alert(1)> & 日本語'
    result=app.state.store.case(cid)['result'];result['offers'][0]['evidence'][0]['excerpt']=payload
    app.state.store.requeue(cid);app.state.store.finish(cid,result)
    with TestClient(app) as client:
        assert client.post(f'/api/cases/{cid}/review',json={'revision':2,'status':'disputed','note':payload}).status_code==200
        response=client.get(f'/api/batches/{bid}/export?format=html')
        doc=BeautifulSoup(response.text,'html.parser')
        assert not doc.select('script,img') and payload in doc.get_text()
        assert '&lt;script&gt;' in response.text
        assert client.get(f'/api/cases/{cid}').json()['reviews'][0]['note']==payload


@pytest.mark.parametrize('sku', ['=SUM(1,2)','+1+2','-1+2','@SUM(A1)','  =1+2'])
def test_csv_export_neutralizes_formula_names_without_changing_json(tmp_path, sku):
    app=create_app(tmp_path/'csv.sqlite');store=app.state.store
    bid,_=store.create_batch({'idempotency_key':'csv-formula-test','mode':'sample','cases':[
        {'sku':sku,'reference_url':'https://example.com/reference','competitor_url':'https://example.com/competitor'}]})
    cid=store.batch(bid)[0]['id'];store.finish(cid,sample_result('mismatch'))
    with TestClient(app) as client:
        row=next(csv.DictReader(io.StringIO(client.get(f'/api/batches/{bid}/export?format=csv').text)))
        assert row['sku'].startswith("'")
        assert client.get(f'/api/batches/{bid}/export?format=json').json()[0]['request']['sku']==sku


def test_read_only_pages_and_downloads_preserve_all_case_data(tmp_path):
    app=create_app(tmp_path/'read-only.sqlite');bid,cid=seed(app)
    app.state.store.review(cid,{'revision':1,'status':'follow_up','note':'retained'})
    before=app.state.store.case(cid)
    with TestClient(app) as client:
        for path in ['/', '/start', '/new', '/investigations',f'/cases/{cid}?guide=1',
                     f'/api/cases/{cid}',f'/api/batches/{bid}',
                     *[f'/api/batches/{bid}/export?format={fmt}' for fmt in ['json','csv','html']]]:
            assert client.get(path).status_code==200
    assert app.state.store.case(cid)==before and app.state.store.usage()=={}
