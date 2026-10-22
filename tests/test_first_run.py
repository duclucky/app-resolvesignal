import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from src.main import create_app


def saved_result():
    return {'mode':'live','decision':{'outcome':'NOT_COMPARABLE','action':'DISMISS_MISMATCH',
            'reasons':['capacity: 256 GB versus 512 GB'],'unknown':['quantity','eligibility']},
            'offers':[{'url':'https://www.adafruit.com/product/'+sku,'title':'Raspberry Pi SSD '+capacity,
                       'capacity':capacity,'availability':'out_of_stock','observed_at':'2026-10-21T17:58:24+00:00',
                       'evidence':[{'field':'capacity','excerpt':'SSD capacity '+capacity,'provider':'public_page','url':'https://www.adafruit.com/product/'+sku}]}
                      for sku,capacity in [('6090','256 GB'),('6089','512 GB')]],
            'trace':[{'provider':'nebius','status':'ok','model':'nvidia/Nemotron-3.5-Super-VL'},
                     {'provider':'tavily','status':'ok'}], 'observability':{'status':'verified'}}


def seed(store,result,state='completed',mode='live'):
    bid,_=store.create_batch({'idempotency_key':'saved-first-run','mode':mode,'cases':[
        {'sku':'Saved control','reference_url':'https://www.adafruit.com/product/6090',
         'competitor_url':'https://www.adafruit.com/product/6089'}]})
    cid=store.batch(bid)[0]['id'];store.finish(cid,result,state=state)
    return cid


def test_saved_real_first_run_is_read_only_and_uses_this_profiles_case(tmp_path,monkeypatch):
    async def forbidden(*args,**kwargs):raise AssertionError('A saved example must not call a provider')
    monkeypatch.setattr(httpx.AsyncClient,'request',forbidden)
    app=create_app(tmp_path/'saved.sqlite');store=app.state.store
    result=saved_result();result['offers'][0]['evidence'][0]['excerpt']='<script>alert(1)</script> 256 GB'
    cid=seed(store,result)
    before=store.case(cid)
    with TestClient(app) as client:
        home=BeautifulSoup(client.get('/').text,'html.parser')
        assert home.select_one('[data-first-run]')['href']==f'/cases/{cid}?guide=1#decision-summary'
        response=client.get('/start');assert response.status_code==200
        doc=BeautifulSoup(response.text,'html.parser')
        link=doc.select_one('[data-open-saved-case]')
        assert link['href']==f'/cases/{cid}?guide=1#decision-summary'
        assert '256 GB' in doc.text and '512 GB' in doc.text
        assert doc.select_one('time')['datetime']=='2026-10-21T17:58:24+00:00'
        assert 'Saved result' in doc.text and 'not a new live run' in doc.text
        assert doc.find('script',string='alert(1)') is None
        assert client.get(f'/cases/{cid}?guide=1').status_code==200
    assert store.case(cid)==before and store.usage()=={}


@pytest.mark.parametrize('variation',['empty','sample','stopped','no_trace','no_readback',
                                     'no_quote','wrong_source','no_timezone','operator_assisted'])
def test_first_run_never_promotes_a_sample_or_unverified_result(tmp_path,variation):
    app=create_app(tmp_path/'fallback.sqlite');store=app.state.store
    if variation!='empty':
        result=saved_result();state='completed';mode='live'
        if variation=='sample':result['mode']='sample';mode='sample'
        if variation=='stopped':state='cancelled'
        if variation=='no_trace':result['trace']=[]
        if variation=='no_readback':result['observability']={'status':'failed'}
        if variation=='no_quote':result['offers'][0]['evidence']=[]
        if variation=='wrong_source':result['offers'][0]['evidence'][0]['url']='https://example.com/wrong'
        if variation=='no_timezone':result['offers'][0]['observed_at']='2026-10-21T17:58:24'
        if variation=='operator_assisted':result['decision']['evidence_basis']='operator_assisted'
        seed(store,result,state,mode)
    with TestClient(app) as client:
        page=BeautifulSoup(client.get('/start').text,'html.parser')
        assert page.select_one('[data-open-saved-case]') is None
        assert page.select_one('#guided-samples') is not None
        assert 'fictional' in page.text.lower()
        assert store.usage()=={}
