import json
from src.parser import parse_offer


def page(**changes):
    p={'@type':'Product','name':'Example SSD 1TB','mpn':'EX-1','offers':{'@type':'Offer','price':'99.99','priceCurrency':'USD','availability':'https://schema.org/InStock'}}
    p.update(changes)
    return '<h1>Example SSD 1TB</h1><script type="application/ld+json">'+json.dumps(p)+'</script>'


def test_missing_condition_and_quantity_not_invented():
    o=parse_offer(page(),'https://samsung.com/item')
    assert o.price==__import__('decimal').Decimal('99.99')
    assert o.capacity=='1 TB' and o.condition is None and o.quantity is None and o.eligibility is None


def test_aggregate_price_not_current_offer():
    o=parse_offer(page(offers={'@type':'AggregateOffer','lowPrice':50,'highPrice':100}),'https://samsung.com/item')
    assert o.price is None and o.conflicts


def test_multiple_products_abstain():
    html=page()+page()
    assert parse_offer(html,'https://samsung.com/item').conflicts
def test_numeric_publisher_sku_is_preserved_without_becoming_mpn():
    import json
    from src.parser import parse_offer
    # Real Adafruit source shape: a numeric retailer product ID, not an MPN.
    product={'@type':'Product','name':'Raspberry Pi NVMe SSD - 256GB','sku':6090,
             'offers':{'@type':'Offer','price':75.6,'priceCurrency':'USD',
                       'itemCondition':'http://schema.org/NewCondition',
                       'availability':'http://schema.org/OutOfStock'}}
    html='<script type="application/ld+json">'+json.dumps(product)+'</script>'
    offer=parse_offer(html,'https://www.adafruit.com/product/6090')
    assert offer.seller_sku=='6090' and offer.mpn is None
    assert offer.condition=='new' and offer.capacity=='256 GB'
    assert offer.quantity is None and offer.eligibility is None
    assert any(e.field=='seller_sku' and e.excerpt=='{"sku": 6090}' for e in offer.evidence)

