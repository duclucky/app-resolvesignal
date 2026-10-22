import httpx
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from src.main import create_app


def existing_live_case(store):
    urls=['https://www.adafruit.com/product/6090','https://www.adafruit.com/product/6089']
    bid,_=store.create_batch({'idempotency_key':'public-demo-live-v1','mode':'live','cases':[
        {'sku':'Adafruit SSD variant control','reference_url':urls[0],'competitor_url':urls[1]}]})
    cid=store.batch(bid)[0]['id']
    offers=[{'url':url,'capacity':capacity,'observed_at':'2026-10-21T17:58:24+00:00',
             'evidence':[{'field':'capacity','url':url,'excerpt':capacity}]} for url,capacity in zip(urls,['256 GB','512 GB'])]
    store.finish(cid,{'mode':'live','offers':offers,'decision':{'outcome':'NOT_COMPARABLE','action':'DISMISS_MISMATCH'},
                     'trace':[{'provider':'nebius','status':'ok','model':'nvidia/test'},{'provider':'tavily','status':'ok'}],
                     'observability':{'status':'verified'}})
    return cid


def test_public_form_and_saved_link_do_not_create_work_on_get(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_PUBLIC_DEMO','true')
    async def forbidden(*args,**kwargs):raise AssertionError('Opening the preset must not call providers')
    monkeypatch.setattr(httpx.AsyncClient,'request',forbidden)
    app=create_app(tmp_path/'demo.sqlite');cid=existing_live_case(app.state.store)
    before=app.state.store.case(cid)
    with TestClient(app) as client:
        doc=BeautifulSoup(client.get('/new').text,'html.parser')
        assert doc.select_one('#case-form') is not None
        assert doc.select_one('#csv-file') is None and doc.select_one('#mode').option['value']=='live'
        assert doc.select_one('#open-saved')['href']==f'/cases/{cid}#decision-summary'
        assert doc.select_one('#demo-refresh') is None
        assert 'View saved result' in doc.text
        home=BeautifulSoup(client.get('/').text,'html.parser')
        assert home.select_one('[data-first-run]')['href']==f'/cases/{cid}?guide=1#decision-summary'
    assert app.state.store.case(cid)==before and app.state.store.usage()=={}


def test_public_quality_cannot_create_developer_batches(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_PUBLIC_DEMO','true')
    app=create_app(tmp_path/'quality.sqlite')
    with TestClient(app) as client:
        doc=BeautifulSoup(client.get('/quality').text,'html.parser')
        assert doc.select_one('#open-batch') is None
        assert doc.select_one('#cloud-eval') is None and doc.select_one('.check-provider') is None
        assert client.post('/api/quality/batch',json={'idempotency_key':'public-developer-test'}).status_code==403
        assert client.get('/api/batches').json()==[]
        assert client.post('/api/quality/evaluate',json={}).json()['passed']==37
    assert app.state.store.usage()=={}


def test_empty_public_preset_requires_an_explicit_start_and_stopped_work_is_not_a_saved_result(tmp_path,monkeypatch):
    monkeypatch.setenv('APP_PUBLIC_DEMO','true')
    app=create_app(tmp_path/'empty.sqlite')
    with TestClient(app) as client:
        doc=BeautifulSoup(client.get('/new').text,'html.parser')
        assert doc.select_one('#case-form') and not doc.select_one('#open-saved')
        assert app.state.store.list_batches()==[]
        cid=existing_live_case(app.state.store)
        app.state.store.requeue(cid);app.state.store.cancel(cid)
        doc=BeautifulSoup(client.get('/new').text,'html.parser')
        assert 'View previous attempt' in doc.select_one('#open-saved').text
        assert 'saved result' not in doc.select_one('#open-saved').text.lower()
        assert app.state.store.case(cid)['state']=='cancelled'
    assert app.state.store.usage()=={}


def test_batch_picker_metadata_names_fictional_examples_without_exposing_request(tmp_path):
    app=create_app(tmp_path/'labels.sqlite')
    bid,_=app.state.store.create_batch({'idempotency_key':'named-sample-test','mode':'sample','cases':[{'sku':'example'}]})
    with TestClient(app) as client:
        row=client.get('/api/batches').json()[0]
        assert row['id']==bid and row['case_count']==1
        assert row['label']=='Fictional examples'
        assert 'request' not in row
