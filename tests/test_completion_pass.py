import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from src.agent import apply_claims
from src.schemas import Offer
from src.parser import parse_offer
from src.store import Store


@pytest.mark.parametrize('label',['UPC','EAN','GTIN13','Barcode'])
def test_labeled_valid_barcode_from_page_can_be_extracted(label):
    text=f'Example headphones\n{label}: 4894979019103'
    result=apply_claims(Offer(url='https://example.com/p',category='general'),
        {'gtin':{'value':'4894979019103','quote':f'{label}: 4894979019103'}},text)
    assert result.gtin=='4894979019103'
    assert result.evidence[0].url==result.url and result.evidence[0].excerpt in text


@pytest.mark.parametrize('quote,page,value',[
    ('SKU: 4894979019103','SKU: 4894979019103','4894979019103'),
    ('UPC: 4894979019104','UPC: 4894979019104','4894979019104'),
    ('UPC: 4894979019103','No barcode is stated','4894979019103'),
    ('UPC: 4894979019103','UPC: 4894979019103\nRelated item EAN: 4894979019097','4894979019103'),
])
def test_unproven_or_ambiguous_barcode_is_not_applied(quote,page,value):
    offer=Offer(url='https://example.com/p',category='general')
    result=apply_claims(offer,{'gtin':{'value':value,'quote':quote}},page)
    assert result.gtin is None and result.evidence==[]


def test_single_product_microdata_preserves_identity_price_and_no_defaults():
    page='''<main><article itemscope itemtype="https://schema.org/Product">
      <h1 itemprop="name">Example headphones</h1><meta itemprop="gtin13" content="4894979019103">
      <span itemprop="mpn">DEMO-HEADPHONES</span><div itemprop="offers" itemscope itemtype="https://schema.org/Offer">
      <meta itemprop="price" content="39.99"><meta itemprop="priceCurrency" content="USD">
      <link itemprop="availability" href="https://schema.org/InStock"></div></article></main>'''
    result=parse_offer(page,'https://example.com/p')
    assert result.gtin=='4894979019103' and str(result.price)=='39.99'
    assert result.category=='general' and result.availability=='in_stock'
    assert result.quantity is result.condition is result.eligibility is None
    assert parse_offer(page+page,'https://example.com/p').gtin is None


def test_quota_persists_and_session_cannot_take_shared_allowance(tmp_path):
    from src.admission import DemoAdmission
    path=tmp_path/'quota.sqlite';a=DemoAdmission(Store(path))
    session_a,cookie_a=a.identify(None,now=1000)
    session_b,cookie_b=a.identify(None,now=1000)
    assert a.identify(cookie_a,now=1000)[0]==session_a
    assert a.identify(cookie_a+'broken',now=1000)[0]!=session_a
    assert a.admit(session_a,'a1',now=1000)
    assert not a.admit(session_a,'a1',now=1001)
    assert a.admit(session_a,'a2',now=1002)
    with pytest.raises(ValueError,match='session'):a.admit(session_a,'a3',now=1003)
    restarted=DemoAdmission(Store(path))
    assert restarted.identify(cookie_a,now=1004)[0]==session_a
    with pytest.raises(ValueError,match='session'):restarted.admit(session_a,'a3',now=1004)
    assert restarted.admit(session_b,'b1',now=1005)
    with pytest.raises(ValueError,match='shared'):restarted.admit(session_b,'b2',now=1006)
    assert restarted.admit(session_a,'later',now=4601)


def test_quota_concurrent_admissions_respect_atomic_global_limit(tmp_path):
    from src.admission import DemoAdmission
    path=tmp_path/'parallel.sqlite';DemoAdmission(Store(path))
    def enter(i):
        admission=DemoAdmission(Store(path));session,_=admission.identify(None,now=1000)
        try:admission.admit(session,str(i),now=1000);return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=6) as pool:result=list(pool.map(enter,range(10)))
    assert sum(result)==3


def test_home_primary_action_is_custom_input(tmp_path):
    from bs4 import BeautifulSoup
    from fastapi.testclient import TestClient
    from src.main import create_app
    with TestClient(create_app(tmp_path/'home.sqlite')) as client:
        doc=BeautifulSoup(client.get('/').text,'html.parser')
        assert doc.select_one('.hero-actions .primary')['href']=='/new'
        assert 'Check your products' in doc.select_one('.hero-actions .primary').text


def test_custom_store_confirmation_accepts_same_store_but_rejects_unrelated_store():
    import copy
    from src.confirmations import add
    from src.samples import sample_result
    result=sample_result('unknown');result['mode']='live'
    for offer,host in zip(result['offers'],['shop-one.example.org','shop-two.example.org']):
        offer['url']='https://'+host+'/p';offer['condition']=None
        for evidence in offer['evidence']:evidence['url']=offer['url']
    payload={'revision':1,'confirmed_by':'Local tester','attested':True,'items':[
        {'side':'reference','field':'condition','value':'new','source_url':'https://shop-one.example.org/terms',
         'excerpt':'This exact item is sold in new condition.'}]}
    assert add(copy.deepcopy(result),payload)['operator_confirmations'][0]['active']
    payload['items'][0]['source_url']='https://unrelated.example.org/terms'
    with pytest.raises(ValueError,match='merchant'):add(copy.deepcopy(result),payload)


def test_public_session_quota_and_cancelled_attempt_survive_restart(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from src.main import create_app
    from src import config
    monkeypatch.setenv('APP_PUBLIC_DEMO','true');monkeypatch.setenv('LIVE_CALLS_ENABLED','true')
    monkeypatch.setattr(config,'ENV',tmp_path/'absent.env')
    monkeypatch.setattr('src.main.validate_url',lambda url:url)
    async def finish_or_cancel(self,cid):
        row=self.store.case(cid)
        if row['revision']:self.store.cancel(cid)
        else:self.store.finish(cid,{'mode':'live','decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
    monkeypatch.setattr('src.main.Investigator.run',finish_or_cancel)
    path=tmp_path/'quota-api.sqlite';app=create_app(path)
    payload={'mode':'live','idempotency_key':'persistent-api-check','cases':[
        {'reference_url':'https://example.com/a','competitor_url':'https://example.com/b'}]}
    with TestClient(app,base_url='https://testserver') as client:
        bid=client.post('/api/batches',json=payload).json()['id']
        cid=client.get('/api/batches/'+bid).json()['cases'][0]['id']
        assert client.post('/api/cases/'+cid+'/refresh',json={}).status_code==200
        assert app.state.store.case(cid)['revision']==1 and app.state.store.case(cid)['state']=='cancelled'
        assert client.post('/api/cases/'+cid+'/refresh',json={}).status_code==429
        cookies=dict(client.cookies)
    with TestClient(create_app(path),base_url='https://testserver',cookies=cookies) as restarted:
        assert restarted.get('/api/status').json()['live_allowance']['session_remaining']==0
        assert restarted.post('/api/cases/'+cid+'/refresh',json={}).status_code==429
    with TestClient(create_app(path),base_url='https://testserver') as second:
        assert second.post('/api/cases/'+cid+'/refresh',json={}).status_code==200
        assert second.post('/api/cases/'+cid+'/refresh',json={}).status_code==429
