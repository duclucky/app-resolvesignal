import asyncio
import json
from decimal import Decimal
import httpx
from src.parser import parse_offer


def group_page():
    group={'@type':'ProductGroup','name':'Real format keyboard','brand':{'name':'Keychron'},'category':'Keyboards',
           'hasVariant':[{'@type':'Product','name':'Keyboard Red','gtin':'4894979019097','sku':'V1W-D1',
                'offers':{'@type':'Offer','url':'https://www.keychron.com/products/test?variant=11','price':'74.99','priceCurrency':'USD','availability':'http://schema.org/OutOfStock'}},
               {'@type':'Product','name':'Keyboard Brown','gtin':'4894979019103','sku':'V1W-D3',
                'offers':{'@type':'Offer','url':'https://www.keychron.com/products/test?variant=12','price':'79.99','priceCurrency':'USD','availability':'http://schema.org/InStock'}}]}
    return '<main><h1>Keyboard</h1></main><script type="application/ld+json">'+json.dumps(group)+'</script>'


def test_explicit_variant_uses_its_price_stock_and_gtin_not_first_variant():
    offer=parse_offer(group_page(),'https://www.keychron.com/products/test?variant=12')
    assert offer.price==Decimal('79.99') and offer.availability=='in_stock'
    assert offer.gtin=='4894979019103' and offer.seller_sku=='V1W-D3'
    assert offer.condition is None and offer.quantity is None and offer.eligibility is None
    assert not offer.conflicts


def test_missing_and_unknown_variant_abstain():
    for url in ['https://www.keychron.com/products/test','https://www.keychron.com/products/test?variant=999']:
        offer=parse_offer(group_page(),url)
        assert offer.price is None and offer.conflicts


def test_gtin_identity_is_distinct_from_retailer_sku():
    from src.schemas import Offer,Evidence
    from src.compare import compare
    def item(gtin,sku):
        o=Offer(url='https://keychron.com/test',category='keyboard',gtin=gtin,seller_sku=sku)
        o.evidence.append(Evidence(id=sku,url=o.url,field='gtin',excerpt=gtin))
        return o
    decision=compare(item('4894979019103','V1W-D3'),item('4894979019103','Keychron_V1W-D3'))
    assert decision.outcome=='INSUFFICIENT_EVIDENCE' and 'gtin' in decision.matched
    mismatch=compare(item('4894979019103','V1W-D3'),item('4894979019097','Keychron_V1W-D1'))
    assert mismatch.outcome=='NOT_COMPARABLE'


def test_cart_quantity_is_not_package_quantity():
    html=group_page()+'<form><label>Quantity<input name="quantity" value="1"></label></form>'
    assert parse_offer(html,'https://www.keychron.com/products/test?variant=12').quantity is None


def test_known_2_5mb_public_page_fits_bounded_retrieval(monkeypatch):
    monkeypatch.setattr('src.policies.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    from src.providers.public_pages import retrieve
    original=httpx.AsyncClient
    body=group_page()+'<!--'+('x'*2_500_000)+'-->'
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text=body,headers={'content-type':'text/html'}))
    monkeypatch.setattr('src.providers.public_pages.validate_url',lambda *a,**k:None)
    monkeypatch.setattr('src.providers.public_pages.httpx.AsyncClient',lambda **kw:original(transport=transport,**kw))
    offer,text=asyncio.run(retrieve('https://www.keychron.com/products/test?variant=12'))
    assert offer.price==Decimal('79.99')


def test_oversized_public_page_still_rejected(monkeypatch):
    monkeypatch.setattr('src.policies.socket.getaddrinfo',lambda *a,**k:[(2,1,6,'',('93.184.216.34',443))])
    import pytest
    from src.providers.public_pages import retrieve
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'x'*4_000_001,headers={'content-type':'text/html'}))
    monkeypatch.setattr('src.providers.public_pages.validate_url',lambda *a,**k:None)
    monkeypatch.setattr('src.providers.public_pages.httpx.AsyncClient',lambda **kw:original(transport=transport,**kw))
    with pytest.raises(ValueError,match='size limit'):
        asyncio.run(retrieve('https://www.keychron.com/products/test'))


def test_invalid_or_unproven_gtin_cannot_establish_identity():
    from src.schemas import Offer,Evidence
    from src.compare import compare
    from src.identifiers import canonical_gtin
    assert canonical_gtin('4894979019104') is None
    assert canonical_gtin('４８９４９７９０１９１０３') is None
    a=Offer(url='https://keychron.com/test',gtin='4894979019103')
    b=a.model_copy(deep=True)
    a.evidence.append(Evidence(id='gtin',url=a.url,field='gtin',excerpt=a.gtin))
    assert 'gtin' not in compare(a,b).matched


def test_live_text_for_default_variant_cannot_replace_selected_variant(monkeypatch,tmp_path):
    # Retrieval/providers are fixtures; keep DNS deterministic without bypassing URL/IP validation.
    monkeypatch.setattr('src.policies.socket.getaddrinfo', lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))])
    from src.agent import Investigator
    from src.store import Store
    class Providers:
        def __init__(self,store):self.trace=[];self.calls=0
        async def extract(self,urls):
            return {'results':[{'url':url,'raw_content':'# Keyboard Red\nPrice $74.99'} for url in urls]}
        async def reason(self,prompt,**kwargs):
            self.calls+=1
            if self.calls==1:return {'query':''}
            return {'offers':[{'claims':{'price':{'value':'74.99','quote':'Price $74.99'}}}]*2}
    async def source(url):return parse_offer(group_page(),url),'Keyboard Brown'
    monkeypatch.setattr('src.agent.LiveProviders',Providers)
    monkeypatch.setattr('src.agent.retrieve',source)
    store=Store(tmp_path/'cases.sqlite3')
    bid,_=store.create_batch({'idempotency_key':'selected','mode':'live','cases':[{
        'sku':'Selected variant','reference_url':'https://www.keychron.com/products/test?variant=12',
        'competitor_url':'https://www.keychron.com/products/test?variant=12'}]})
    cid=store.batch(bid)[0]['id'];agent=Investigator(store);agent.contexts[cid]={}
    asyncio.run(agent._run(cid));result=store.case(cid)['result']
    for offer in result['offers']:
        assert offer['price']=='79.99' and offer['gtin']=='4894979019103'
        assert any('price conflicts' in conflict for conflict in offer['conflicts'])
    assert result['decision']['outcome']=='INSUFFICIENT_EVIDENCE'
