import asyncio
import json
import socket
import httpx
import pytest
from fastapi.testclient import TestClient
from src import config
from src.main import create_app
from src.schemas import Offer,Evidence
from src.compare import compare
from src.policies import validate_url


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])


def test_arbitrary_public_storefront_is_accepted(public_dns):
    assert validate_url('https://store.example.org/products/kettle?variant=42')
    assert validate_url('https://www.adafruit.com/product/9999')


@pytest.mark.parametrize('url',[
    'http://store.example.org/p','https://user:pass@store.example.org/p',
    'https://store.example.org:8080/p','https://127.0.0.1/p','https://[::1]/p',
    'https://169.254.169.254/latest/meta-data','https://10.0.0.1/p',
    'https://localhost/p','https://printer.local/p','https://0.0.0.0/p',
])
def test_local_and_credential_urls_are_rejected_before_dns(url,public_dns):
    with pytest.raises(ValueError):validate_url(url)


def test_mixed_public_private_dns_is_rejected(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443)),(2,1,6,'',('10.0.0.1',443))])
    with pytest.raises(ValueError):validate_url('https://store.example.org/p')


def test_dns_change_to_private_between_validation_and_connection_is_rejected(monkeypatch):
    from src.providers.public_pages import retrieve
    answers=iter(['93.184.216.34','127.0.0.1']);connections=[];original=httpx.AsyncClient
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',(next(answers),443))])
    def handler(request):connections.append(request);raise AssertionError('Private destination must never be requested')
    monkeypatch.setattr('src.providers.public_pages.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(ValueError):asyncio.run(retrieve('https://store.example.org/p'))
    assert connections==[]


def test_explicit_domain_policy_is_still_available_for_scoped_sources(public_dns):
    with pytest.raises(ValueError):validate_url('https://samsung.com.evil.org/p',domains=('samsung.com',))


def test_direct_connection_pins_ip_but_preserves_host_tls_and_evidence(public_dns,monkeypatch):
    from src.providers.public_pages import retrieve
    original=httpx.AsyncClient;seen=[]
    body='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'Example kettle',
        'gtin13':'4894979019103','offers':{'@type':'Offer','price':'39','priceCurrency':'USD'}})+'</script>'
    def handler(request):
        seen.append(request)
        return httpx.Response(200,text=body,headers={'content-type':'text/html'})
    monkeypatch.setattr('src.providers.public_pages.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    offer,_=asyncio.run(retrieve('https://store.example.org/products/kettle'))
    assert str(seen[0].url)=='https://93.184.216.34/products/kettle'
    assert seen[0].headers['host']=='store.example.org'
    assert seen[0].extensions['sni_hostname']=='store.example.org'
    assert offer.url=='https://store.example.org/products/kettle'
    assert offer.category=='general' and offer.gtin=='4894979019103'
    assert all(e.url==offer.url for e in offer.evidence)


def test_redirect_to_private_ip_never_connects(public_dns,monkeypatch):
    from src.providers.public_pages import retrieve
    original=httpx.AsyncClient;seen=[]
    def handler(request):
        seen.append(request);return httpx.Response(302,headers={'location':'https://169.254.169.254/latest/meta-data'})
    monkeypatch.setattr('src.providers.public_pages.httpx.AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(ValueError):asyncio.run(retrieve('https://store.example.org/p'))
    assert len(seen)==1


def test_redirect_shared_cdn_ip_gets_separate_tls_pool(public_dns,monkeypatch):
    from src.providers.public_pages import retrieve
    original=httpx.AsyncClient;clients=[];hosts=[]
    def handler(request):
        hosts.append((request.headers['host'],request.extensions['sni_hostname']))
        if len(hosts)==1:return httpx.Response(302,headers={'location':'https://another.example.org/p'})
        return httpx.Response(200,text='<h1>Example product</h1>',headers={'content-type':'text/html'})
    def factory(**kw):
        client=original(transport=httpx.MockTransport(handler),**kw);clients.append(client);return client
    monkeypatch.setattr('src.providers.public_pages.httpx.AsyncClient',factory)
    offer,_=asyncio.run(retrieve('https://store.example.org/p'))
    assert len(clients)==2 and offer.url=='https://another.example.org/p'
    assert hosts==[('store.example.org','store.example.org'),('another.example.org','another.example.org')]


def general_offer(**changes):
    data={'url':'https://store.example.org/p','title':'Example kettle','category':'general',
          'gtin':'4894979019103','condition':'new','quantity':1,'price':'39.99','currency':'USD',
          'availability':'in_stock','eligibility':'unconditional','price_basis':'listed_item',**changes}
    o=Offer(**data)
    for field in ['gtin','mpn','brand','condition','quantity','price','currency','availability','eligibility','price_basis']:
        if getattr(o,field) is not None:o.evidence.append(Evidence(id=field,url=o.url,field=field,excerpt=str(getattr(o,field))))
    return o


def test_generic_barcode_positive_and_identity_uncertainty():
    assert compare(general_offer(),general_offer(price='29.99')).outcome=='COMPARABLE_LISTED_PRICE'
    assert compare(general_offer(gtin=None,mpn='MODEL-A'),general_offer(gtin=None,mpn='MODEL-A')).outcome=='INSUFFICIENT_EVIDENCE'
    assert compare(general_offer(),general_offer(gtin='4894979019097')).outcome=='NOT_COMPARABLE'
    assert compare(general_offer(),general_offer(currency='CAD')).outcome=='NOT_COMPARABLE'
    assert compare(general_offer(),general_offer(quantity=None)).outcome=='INSUFFICIENT_EVIDENCE'


def test_public_custom_pair_is_not_collapsed_or_started_on_page_view(tmp_path,monkeypatch,public_dns):
    monkeypatch.setenv('APP_PUBLIC_DEMO','true');monkeypatch.setenv('LIVE_CALLS_ENABLED','true')
    monkeypatch.setattr(config,'ENV',tmp_path/'absent.env')
    calls=[]
    async def complete(self,cid):
        calls.append(cid);self.store.finish(cid,{'mode':'live','decision':{'outcome':'INSUFFICIENT_EVIDENCE'}})
    monkeypatch.setattr('src.main.Investigator.run',complete)
    app=create_app(tmp_path/'custom.sqlite')
    with TestClient(app) as client:
        page=client.get('/new').text
        assert 'id="case-form"' in page and 'id="csv-file"' not in page
        assert calls==[] and app.state.store.list_batches()==[]
        def payload(key,product):return {'mode':'live','idempotency_key':key,'cases':[{'sku':product,
            'reference_url':'https://store.example.org/'+product,'competitor_url':'https://another.example.org/'+product}]}
        a=client.post('/api/batches',json=payload('custom-pair-a','kettle'));assert a.status_code==200
        assert client.post('/api/batches',json=payload('custom-pair-a','kettle')).json()['id']==a.json()['id']
        b=client.post('/api/batches',json=payload('custom-pair-b','headphones'));assert b.status_code==200
        assert b.json()['id']!=a.json()['id']
        c=client.post('/api/batches',json=payload('custom-pair-c','shoes'));assert c.status_code==200
        assert client.post('/api/batches',json=payload('custom-pair-d','lamp')).status_code==429
        many=payload('custom-many','kettle');many['cases']*=2
        assert client.post('/api/batches',json=many).status_code==422
        assert len(calls)==3 and len(app.state.store.list_batches())==3
