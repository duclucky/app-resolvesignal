"""Constructed examples for interface checks. Never presented as current prices."""
from .schemas import Offer, Evidence
from .compare import compare


def sample_result(kind):
    offers=[]
    for side,price in [('reference','119.99'),('competitor','89.99')]:
        o=Offer(url=f'https://example.com/{side}',title='Sample SSD 1TB',category='ssd',mpn='SAMPLE-1T',brand='Sample',capacity='1 TB',condition='new',quantity=1,price=price,currency='USD',availability='in_stock',eligibility='unconditional',price_basis='listed_item')
        if side=='competitor' and kind=='mismatch':o.condition='refurbished'
        if side=='competitor' and kind=='unknown':o.eligibility=None
        for field in ['mpn','condition','quantity','capacity','price','currency','availability','eligibility','price_basis']:
            if getattr(o,field) is not None:o.evidence.append(Evidence(id=f'{side}-{field}',url=o.url,field=field,excerpt=f'Constructed example: {field} = {getattr(o,field)}',provider='constructed_sample'))
        offers.append(o)
    return {'mode':'sample','offers':[o.model_dump(mode='json') for o in offers],'decision':compare(*offers).model_dump(),'summary':'Constructed example for exploring the review workflow. No current retail data or sponsor calls.','trace':[],'research':[],'elapsed_seconds':0}
