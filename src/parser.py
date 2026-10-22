"""Conservative structured-offer extraction; absent facts remain absent."""
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from bs4 import BeautifulSoup
from .schemas import Offer, Evidence
from .identifiers import valid_gtin
from urllib.parse import urlsplit,parse_qs,urljoin


def text_content(html):
    soup=BeautifulSoup(html,'html.parser')
    for x in soup(['script','style','nav','footer','header']):x.decompose()
    main=soup.find('main') or soup
    return main.get_text(' ',strip=True)


def parse_offer(html, url):
    soup=BeautifulSoup(html,'html.parser')
    title=(soup.find('h1') or soup.find('title'))
    result=Offer(url=url,title=title.get_text(' ',strip=True)[:250] if title else '')
    products=[]
    def walk(x,parent=None):
        if isinstance(x,list):
            for v in x:walk(v,parent)
        elif isinstance(x,dict):
            t=x.get('@type',[]);t=[t] if isinstance(t,str) else t
            if 'Product' in t:
                inherited={k:parent[k] for k in ('brand','category','description','additionalProperty') if parent and k in parent}
                products.append({**inherited,**x})
            for k,v in x.items():
                if k in ('@graph','mainEntity','itemListElement','item','hasVariant'):
                    walk(v,x if 'ProductGroup' in t else parent)
    for script in soup.find_all('script',type='application/ld+json'):
        try:walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):continue
    if not products:
        # Single Product microdata is another explicit retailer assertion, not a
        # guess from a title or a recommendation card elsewhere in the page.
        roots=[node for node in soup.select('[itemscope][itemtype]')
               if node.get('itemtype','').rstrip('/').split('/')[-1]=='Product']
        if len(roots)==1:
            root=roots[0]
            def prop(scope,name):
                nodes=scope.select('[itemprop="'+name+'"]')
                values=[n.get('content') or n.get('href') or n.get_text(' ',strip=True) for n in nodes]
                return values[0] if values and len(set(values))==1 else None
            product={'@type':'Product','url':root.get('itemid') or prop(root,'url')}
            for name in ('name','mpn','model','sku','brand','gtin','gtin8','gtin12','gtin13','gtin14','numberOfItems','itemCondition'):
                value=prop(root,name)
                if value is not None:product[name]=value
            offers=root.select('[itemprop="offers"][itemscope]')
            product['offers']=[{'@type':'Offer',**{name:prop(node,name) for name in
                ('price','priceCurrency','availability','itemCondition','url') if prop(node,name) is not None}} for node in offers]
            if not offers:product['offers']={}
            products=[product]
    requested=parse_qs(urlsplit(url).query).get('variant',[])
    if len(products)>1 or requested:
        def selected(p):
            offer=p.get('offers',{})
            candidates=[p.get('url'),p.get('@id')]
            if isinstance(offer,dict):candidates += [offer.get('url'),offer.get('@id')]
            target=urlsplit(url)
            for candidate in candidates:
                if not isinstance(candidate,str):continue
                candidate=urlsplit(urljoin(url,candidate))
                if candidate.hostname and candidate.hostname.removeprefix('www.')==target.hostname.removeprefix('www.') and candidate.path==target.path:
                    if len(requested)==1 and parse_qs(candidate.query).get('variant')==requested:return True
            return False
        matches=[p for p in products if selected(p)]
        if len(matches)!=1:
            result.conflicts.append('Multiple or unselected product variants; an exact variant URL is required.')
            return result
        products=matches
    if len(products)!=1:
        if products:result.conflicts.append('Multiple product records; selected variant is ambiguous.')
        return result
    p=products[0]
    def put(field,value,excerpt):
        if value is not None:
            setattr(result,field,value)
            result.evidence.append(Evidence(id=uuid.uuid4().hex,url=url,field=field,excerpt=excerpt[:500]))
    name=p.get('name') or result.title
    put('title',name,str(name))
    put('mpn',p.get('mpn') or p.get('model'),json.dumps({k:p[k] for k in ('mpn','model') if k in p}))
    sku=p.get('sku')
    # Some retailers publish numeric product IDs; preserve the ID as text,
    # retaining its original source representation and keeping it separate from MPN.
    put('seller_sku',str(sku) if type(sku) is int else sku,json.dumps({'sku':p.get('sku')}))
    for field in ('gtin','gtin8','gtin12','gtin13','gtin14'):
        if p.get(field) and valid_gtin(p[field]):
            put('gtin',str(p[field]),json.dumps({field:p[field]}));break
    brand=p.get('brand');put('brand',brand.get('name') if isinstance(brand,dict) else brand,str(brand))
    if re.search(r'\bSSD\b|solid.state',name,re.I):result.category='ssd'
    elif re.search(r'keyboard',name,re.I):result.category='keyboard'
    else:result.category='general'
    cap=re.search(r'\b(\d+(?:\.\d+)?)\s*(TB|GB)\b',name,re.I)
    if cap:put('capacity',cap[1]+' '+cap[2].upper(),name)
    offers=p.get('offers',{})
    if isinstance(offers,list):
        if len(offers)!=1:result.conflicts.append('Multiple offers without a selected seller or variant.');return result
        offers=offers[0]
    if not isinstance(offers,dict):return result
    if 'lowPrice' in offers and 'price' not in offers:
        result.conflicts.append('Aggregate starting price cannot identify the selected offer.')
    rawprice=offers.get('price')
    try:
        if rawprice is not None:put('price',Decimal(str(rawprice)),json.dumps({'price':rawprice}))
    except InvalidOperation:result.conflicts.append('Invalid structured price.')
    put('currency',offers.get('priceCurrency'),json.dumps({'priceCurrency':offers.get('priceCurrency')}))
    if rawprice is not None and offers.get('@type')=='Offer':
        put('price_basis','listed_item',json.dumps({'@type':'Offer','price':rawprice}))
    cond=offers.get('itemCondition') or p.get('itemCondition')
    conditions={'NewCondition':'new','RefurbishedCondition':'refurbished','UsedCondition':'used','DamagedCondition':'damaged'}
    if cond:put('condition',conditions.get(str(cond).split('/')[-1]),str(cond))
    avail=offers.get('availability')
    if avail:put('availability',{'InStock':'in_stock','OutOfStock':'out_of_stock','PreOrder':'preorder','BackOrder':'backorder'}.get(str(avail).split('/')[-1]),str(avail))
    # Quantity must be explicit in public evidence, never presumed to be one.
    quantity=p.get('numberOfItems')
    if str(quantity).isdigit():put('quantity',int(quantity),json.dumps({'numberOfItems':quantity}))
    for prop in p.get('additionalProperty',[]) if isinstance(p.get('additionalProperty',[]),list) else []:
        key=str(prop.get('name','')).lower();value=prop.get('value')
        field={'keyboard layout':'layout','switch type':'switch','quantity':'quantity'}.get(key)
        if field and value is not None:
            if field=='quantity' and not str(value).isdigit():continue
            put(field,int(value) if field=='quantity' else str(value),json.dumps(prop))
    # Conditional claims require contextual review; do not infer unconditional from silence.
    text=text_content(html)
    conditional=re.search(r'(members?[- ]only|with trade.in|after rebate|first[- ]order)',text,re.I)
    if conditional:put('eligibility','conditional',text[max(0,conditional.start()-40):conditional.end()+80])
    return result
