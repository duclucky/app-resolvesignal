import pytest
import csv
import io
from fastapi.testclient import TestClient
from src.main import create_app


@pytest.mark.parametrize('state',['completed','partial'])
def test_finished_cases_cannot_be_cancelled(tmp_path,state):
    app=create_app(tmp_path/'state.sqlite');store=app.state.store
    bid,_=store.create_batch({'idempotency_key':'finished-cancel','mode':'sample','cases':[{'sku':'x'}]})
    cid=store.batch(bid)[0]['id']
    result={'decision':{'outcome':'NOT_COMPARABLE'}}
    store.finish(cid,result,state=state)
    with TestClient(app) as client:
        assert client.post('/api/cases/'+cid+'/cancel',json={}).status_code==409
        assert store.case(cid)['state']==state


def test_cancelling_a_recheck_retains_historical_revision(tmp_path):
    app=create_app(tmp_path/'state.sqlite');store=app.state.store
    with TestClient(app) as client:
        bid,_=store.create_batch({'idempotency_key':'cancel-recheck','mode':'sample','cases':[{'sku':'x'}]})
        cid=store.batch(bid)[0]['id'];result={'decision':{'outcome':'NOT_COMPARABLE'}}
        store.finish(cid,result);store.requeue(cid)
        assert client.post('/api/cases/'+cid+'/cancel',json={}).status_code==200
        row=store.case(cid)
        assert row['state']=='cancelled' and row['revision']==1 and row['result']==result
        assert len(row['history'])==1
        assert client.post('/api/cases/'+cid+'/cancel',json={}).status_code==200


def test_cancelled_recheck_exports_do_not_promote_retained_decision(tmp_path):
    app=create_app(tmp_path/'state.sqlite');store=app.state.store
    with TestClient(app) as client:
        bid,_=store.create_batch({'idempotency_key':'export-cancel','mode':'sample','cases':[{'sku':'x','reference_url':'https://example.com/a','competitor_url':'https://example.com/b'}]})
        cid=store.batch(bid)[0]['id']
        store.finish(cid,{'mode':'sample','decision':{'outcome':'COMPARABLE_LISTED_PRICE','action':'REVIEW_PRICING','gap_percent':'25','reasons':['Fictional control']}})
        store.requeue(cid);store.cancel(cid)
        exported=list(csv.DictReader(io.StringIO(client.get(f'/api/batches/{bid}/export?format=csv').text)))[0]
        assert exported['outcome']==exported['action']==exported['gap_percent']==''
        assert exported['state']=='cancelled' and exported['decision_current']=='false'
        assert exported['retained_outcome']=='COMPARABLE_LISTED_PRICE'
        report=client.get(f'/api/batches/{bid}/export?format=html').text
        assert 'No completed decision for this attempt' in report
        data=client.get(f'/api/batches/{bid}/export?format=json').json()[0]
        assert data['decision_current'] is False
        assert data['result']['decision']['outcome']=='COMPARABLE_LISTED_PRICE'
