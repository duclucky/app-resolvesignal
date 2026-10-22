import json
from fastapi.testclient import TestClient
from src.main import create_app
from src.store import Store
from src.policies import validate_url,safe_csv
import pytest


def test_idempotency_refresh_review_and_history(tmp_path):
    s=Store(tmp_path/'db.sqlite');request={'idempotency_key':'unique-test','mode':'sample','cases':[{'sku':'x'}]}
    bid,new=s.create_batch(request);assert new and s.create_batch(request)==(bid,False)
    with pytest.raises(ValueError):s.create_batch({**request,'cases':[{'sku':'other'}]})
    cid=s.batch(bid)[0]['id'];s.finish(cid,{'decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
    s.review(cid,{'revision':1,'status':'reviewed','note':'first'})
    s.requeue(cid)
    with pytest.raises(ValueError):s.review(cid,{'revision':1,'status':'reviewed','note':'stale'})
    s.finish(cid,{'decision':{'outcome':'NOT_COMPARABLE'}})
    with pytest.raises(ValueError):s.review(cid,{'revision':1,'status':'reviewed','note':'stale'})
    assert len(s.case(cid)['history'])==2 and len(s.case(cid)['reviews'])==1


def test_cancel_and_recover(tmp_path):
    s=Store(tmp_path/'db.sqlite');bid,_=s.create_batch({'idempotency_key':'cancel-test','mode':'public','cases':[{}]});cid=s.batch(bid)[0]['id']
    s.update_state(cid,'cancelled');s.finish(cid,{'late':True});assert s.case(cid)['revision']==0
    s.requeue(cid);s.update_state(cid,'collecting');s.recover();assert s.case(cid)['state']=='interrupted'


def test_usage_cap_is_persistent(tmp_path):
    path=tmp_path/'db.sqlite';s=Store(path);s.reserve('test',3,5)
    with pytest.raises(ValueError):Store(path).reserve('test',3,5)
    assert s.usage()['test']==3


def test_refresh_reports_observed_changes_without_treating_confirmation_as_retrieval(tmp_path):
    s=Store(tmp_path/'refresh.sqlite')
    bid,_=s.create_batch({'idempotency_key':'refresh-diff','mode':'public','cases':[{'sku':'x'}]})
    cid=s.batch(bid)[0]['id']
    before={'price':'100.00','currency':'USD','condition':None,'observed_at':'2026-10-21T00:00:00Z',
            'evidence':[{'field':'price','excerpt':'Price $100.00'}]}
    first={'offers':[{**before,'condition':'new'},before], 'retrieved_offers':[before,before],
           'decision':{'outcome':'COMPARABLE_LISTED_PRICE','evidence_basis':'operator_assisted'}}
    s.finish(cid,first)
    s.requeue(cid)
    s.finish(cid,{'offers':[{**before,'price':'90.00','observed_at':'2026-10-21T01:00:00Z'},before],
                  'decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
    result=s.case(cid)['result']
    delta=result['refresh_comparison']
    assert delta['previous_revision']==1 and delta['complete_pair'] is True
    assert delta['fields']==[{'side':'reference','field':'price','before':'100.00','after':'90.00'}]
    assert delta['previous_outcome']=='COMPARABLE_LISTED_PRICE'
    assert delta['current_outcome']=='INSUFFICIENT_EVIDENCE'
    assert len(s.case(cid)['history'])==2


def test_failed_refresh_never_claims_unchanged_offer(tmp_path):
    s=Store(tmp_path/'missing-refresh.sqlite')
    bid,_=s.create_batch({'idempotency_key':'missing-refresh','mode':'public','cases':[{}]})
    cid=s.batch(bid)[0]['id']
    s.finish(cid,{'offers':[{'price':'10'},{'price':'20'}],'decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
    s.requeue(cid)
    s.finish(cid,{'decision':{'outcome':'INSUFFICIENT_EVIDENCE'}},'Unavailable','failed')
    delta=s.case(cid)['result']['refresh_comparison']
    assert delta['complete_pair'] is False and delta['fields']==[]


def test_refresh_html_reports_changes_and_escapes_values(tmp_path):
    app=create_app(tmp_path/'refresh-export.sqlite')
    with TestClient(app) as client:
        store=app.state.store
        bid,_=store.create_batch({'idempotency_key':'refresh-export','mode':'public','cases':[{'sku':'x'}]})
        cid=store.batch(bid)[0]['id']
        before={'title':'<script>alert(1)</script>','price':'100','evidence':[{'field':'price','excerpt':'Price $100'}]}
        store.finish(cid,{'offers':[before,before],'decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
        store.requeue(cid)
        store.finish(cid,{'offers':[{**before,'title':'SSD-X','price':'90'},before],
                          'decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
        report=client.get(f'/api/batches/{bid}/export?format=html')
        assert report.status_code==200 and 'Changes since revision 1' in report.text
        assert 'price: 100' in report.text and '&lt;script&gt;' in report.text
        assert '<script>alert(1)</script>' not in report.text
        exported=client.get(f'/api/batches/{bid}/export?format=json').json()
        assert exported[0]['result']['refresh_comparison']['fields'][1]['field']=='price'


def test_refresh_observation_comparison_requires_evidence_and_ignores_price_format():
    from src.store import refresh_comparison
    observed={'price':'100.00','evidence':[{'field':'price','excerpt':'Price $100.00'}]}
    previous={'offers':[observed,observed]}
    assert refresh_comparison(previous,{'offers':[{},{}]},1)['complete_pair'] is False
    comparison=refresh_comparison(previous,{'offers':[{**observed,'price':'100'},observed]},1)
    assert comparison['complete_pair'] is True and comparison['fields']==[]


@pytest.mark.parametrize('url',['http://samsung.com/item','https://metadata.local/item','https://user:pass@samsung.com/item','https://127.0.0.1/item','https://samsung.com:8080/item','file:///x'])
def test_bad_urls_rejected(url):
    with pytest.raises(ValueError):validate_url(url,resolve=False)


def test_dns_private_rejected(monkeypatch):
    monkeypatch.setattr('src.policies.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(ValueError):validate_url('https://samsung.com/product')


def test_csv_preview_is_offline_and_html_escapes(tmp_path,monkeypatch):
    app=create_app(tmp_path/'api.sqlite')
    def no_network(*a,**k):raise AssertionError('Preview must not resolve DNS')
    monkeypatch.setattr('src.policies.socket.getaddrinfo',no_network)
    with TestClient(app) as c:
        r=c.post('/api/batches/preview',json={'csv':'sku,reference_url,competitor_url\n=SUM(A1),https://samsung.com/a,https://bestbuy.com/b'})
        assert r.status_code==200 and r.json()['network_requests']==0
        assert c.post('/api/batches/preview',json={'csv':'bad\nwrong'}).status_code==422
        assert c.post('/api/samples',json={'idempotency_key':'cors-check'},headers={'origin':'https://evil.example'}).status_code==403
        assert 'live_enabled' in c.get('/api/status').json()
        assert 'NEBIUS_API_KEY' not in c.get('/api/status').text
        assert c.get('/').status_code==200
    assert safe_csv(' =1+2').startswith("'")
