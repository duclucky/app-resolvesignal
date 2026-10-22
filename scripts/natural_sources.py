"""Bounded collection/evaluation of real public storefront snapshots; no invented offers."""
import argparse
import asyncio
import gzip
import hashlib
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from bs4 import BeautifulSoup
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.parser import parse_offer
from src.compare import compare
from src.identifiers import canonical_gtin

OUT=Path(__file__).resolve().parents[2]/'.hackathon/evidence/ecommerce/natural-source-gate'
# Official URLs identified in public source pages; family-disjoint development/holdout split.
FAMILIES=[
 ('development','v1','keychron-v1-qmk-via-custom-mechanical-keyboard','keychron-v1'),
 ('development','v1-8k','keychron-v1-8k-qmk-wired-custom-mechanical-keyboard','keychron-v1-8k-rgb-keyboard'),
 ('development','q1-pro','keychron-q1-pro-qmk-via-wireless-custom-mechanical-keyboard','keychron-q1-pro-w-knob'),
 ('holdout','k8-v2','keychron-k8-qmk-wireless-mechanical-keyboard-version-2','keychron-k8-qmk-v2-hotswap-wireless-rgb-keyboard'),
 ('holdout','k1-v6','keychron-k1-qmk-wireless-mechanical-keyboard-version-6','keychron-k1-version-6-tkl-hotswap-wireless-rgb-keyboard'),
 ('holdout','q1-v2','keychron-q1','keychron-q1-v2'),
 ('holdout','q2','keychron-q2-qmk-custom-mechanical-keyboard','keychron-q2'),
 ('holdout','q5','keychron-q5-qmk-custom-mechanical-keyboard','keychron-q5-w-knob')]


def records(html):
    soup=BeautifulSoup(html,'html.parser');rows=[]
    for script in soup.find_all('script',type='application/ld+json'):
        try:
            data=json.loads(script.get_text())
            if isinstance(data,dict) and data.get('@type') in ('Product','ProductGroup'):
                for product in data.get('hasVariant',[data]):
                    offer=product.get('offers',{})
                    if isinstance(offer,dict) and offer.get('url'):
                        rows.append({'url':offer['url'],'title':product.get('name'),'sku':product.get('sku'),
                                     'gtin':product.get('gtin') or product.get('gtin13'),'price':offer.get('price'),
                                     'currency':offer.get('priceCurrency'),'availability':offer.get('availability'),
                                     'condition':offer.get('itemCondition'),'package_quantity':product.get('numberOfItems')})
        except (ValueError,TypeError):continue
    return rows


async def collect():
    OUT.mkdir(parents=True,exist_ok=True);snapshots=[];semaphore=asyncio.Semaphore(2)
    async def fetch(client,split,family,side,slug):
        host='www.keychron.com' if side=='manufacturer' else 'mechanicalkeyboards.com'
        url=f'https://{host}/products/{slug}'
        async with semaphore:
            stamp=datetime.now(timezone.utc).isoformat();row={'split':split,'family':family,'side':side,'url':url,'retrieved_at':stamp}
            try:
                response=await client.get(url);row.update(status=response.status_code,bytes=len(response.content))
                if response.status_code==200 and len(response.content)<=4_000_000:
                    path=OUT/f'{family}-{side}.html.gz'
                    path.write_bytes(gzip.compress(response.content));row['snapshot']=path.name
                    row['sha256']=hashlib.sha256(response.content).hexdigest();row['variants']=records(response.text)
            except httpx.HTTPError as exc:row['error_type']=type(exc).__name__
            snapshots.append(row);print(json.dumps({'family':family,'side':side,'status':row.get('status'),'variants':len(row.get('variants',[]))}),flush=True)
    async with httpx.AsyncClient(timeout=25,follow_redirects=False,trust_env=False,
        headers={'User-Agent':'PriceAlertInvestigator/0.1 (bounded public product research)'}) as client:
        await asyncio.gather(*(fetch(client,split,family,side,slug) for split,family,a,b in FAMILIES for side,slug in [('manufacturer',a),('retailer',b)]))
    (OUT/'snapshots.json').write_text(json.dumps(snapshots,indent=2),encoding='utf-8')
    return snapshots


def make_pairs(snapshots):
    pairs=[]
    for split,family,*_ in FAMILIES:
        sides={r['side']:r for r in snapshots if r['family']==family}
        if len(sides)!=2 or any(not r.get('variants') for r in sides.values()):continue
        a,b=sides['manufacturer'],sides['retailer']
        # SKU suffixes generate research candidates only; never establish identity.
        # Prefer separate selected pairs over reversing or duplicating a case.
        def sku_key(row):
            sku=row.get('sku') or ''
            return sku.removeprefix('Keychron_').removeprefix('KC_')
        candidates=[(x,y) for x in a['variants'] for y in b['variants'] if sku_key(x) and sku_key(x)==sku_key(y)]
        candidates += [(x,y) for x in a['variants'] for y in b['variants']
                       if canonical_gtin(x.get('gtin')) and canonical_gtin(x.get('gtin'))==canonical_gtin(y.get('gtin'))]
        candidates += [(x,y) for x in a['variants'] for y in b['variants']]
        variants=[];seen=set()
        for x,y in candidates:
            if (x['url'],y['url']) in seen:continue
            seen.add((x['url'],y['url']))
            gx,gy=canonical_gtin(x.get('gtin')),canonical_gtin(y.get('gtin'))
            if gx and gy and gx!=gy:
                target='NOT_COMPARABLE'
                rationale='Publisher GTIN assertions conflict. Automatic comparison must be withheld; physical identity is not independently verified.'
            else:
                # These captured sources omit explicit condition and package count.
                # Do not generalize this expectation to a different source corpus.
                if any(z.get('condition') or z.get('package_quantity') for z in (x,y)):
                    raise ValueError('Source terms changed; manually re-annotate this corpus.')
                target='INSUFFICIENT_EVIDENCE'
                rationale='Missing explicit condition/package-count evidence; matching seller SKU suffixes alone do not prove identity.'
            variants.append((f'selected-{len(variants)+1}',x['url'],y['url'],target,rationale))
            if len(variants)==3:break
        variants.append(('unselected-variant',a['url'],b['url'],'INSUFFICIENT_EVIDENCE','Base family URLs do not select an exact variant.'))
        for kind,reference,competitor,target,rationale in variants:
            lookup={urlsplit(a['url']).hostname:a,urlsplit(b['url']).hostname:b}
            sources=[lookup[urlsplit(url).hostname] for url in (reference,competitor)]
            pairs.append({'id':family+'-'+kind,'split':split,'family':family,'kind':'natural_public_snapshots',
                          'reference_url':reference,'competitor_url':competitor,'sources':sources,
                          'authored_target':{'outcome':target,'rationale':rationale},
                          'annotation_status':'agent_authored_from_publisher_records_not_independent_human_labels'})
    return pairs


def evaluate(pairs):
    rows=[]
    for pair in pairs:
        offers=[]
        for url,source in zip([pair['reference_url'],pair['competitor_url']],pair['sources']):
            html=gzip.decompress((OUT/source['snapshot']).read_bytes()).decode('utf-8')
            offer=parse_offer(html,url);offer.observed_at=datetime.fromisoformat(source['retrieved_at'])
            offers.append(offer)
        now=max(o.observed_at for o in offers)
        # Frozen-at-collection evaluation is explicitly replay, never a current-price result.
        decision=compare(*offers,now=now).model_dump()
        rows.append({'id':pair['id'],'split':pair['split'],'expected':pair['authored_target'],'actual':decision,
                     'passed':decision['outcome']==pair['authored_target']['outcome'],
                     'offers':[o.model_dump(mode='json') for o in offers]})
    return {'method':'Frozen real-page structured-data replay at collection time; no synthetic prices or new provider calls.',
            'annotation_limit':'Agent-authored expectations; no independent human accuracy claim.',
            'total':len(rows),'passed':sum(r['passed'] for r in rows),
            'development':sum(r['split']=='development' for r in rows),'holdout':sum(r['split']=='holdout' for r in rows),
            'full_comparable':sum(r['actual']['outcome']=='COMPARABLE_LISTED_PRICE' for r in rows),'cases':rows}


async def main(args):
    snapshots=await collect() if args.collect else json.loads((OUT/'snapshots.json').read_text(encoding='utf-8'))
    pairs=make_pairs(snapshots)
    (OUT/'natural-pairs.json').write_text(json.dumps(pairs,indent=2),encoding='utf-8')
    report=evaluate(pairs);(OUT/'natural-replay-evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'}))
    return 0 if report['total'] and report['passed']==report['total'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--collect',action='store_true')
    sys.exit(asyncio.run(main(parser.parse_args())))
