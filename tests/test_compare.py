from datetime import timedelta
import pytest
from src.schemas import Offer, Evidence, utcnow
from src.compare import compare


def offer(**changes):
    values = dict(url='https://store.example/product', title='Example SSD 1TB', category='ssd', mpn='EX-1T',
                  brand='Example', capacity='1 TB', condition='new', quantity=1, price='100', currency='USD',
                  availability='in_stock', eligibility='unconditional', price_basis='listed_item')
    values.update(changes)
    result = Offer(**values)
    for field in ('mpn','capacity','condition','quantity','price','currency','availability','eligibility','price_basis'):
        if getattr(result, field) is not None:
            result.evidence.append(Evidence(id=f'{id(result)}-{field}', url=result.url, field=field, excerpt=f'{field}: {getattr(result, field)}'))
    return result


def test_comparable_price_arithmetic():
    d=compare(offer(price='119.99'),offer(price='99.99'))
    assert d.outcome=='COMPARABLE_LISTED_PRICE'
    assert d.gap_amount=='20.00' and d.gap_percent=='16.67'
    assert d.action=='REVIEW_PRICING'


@pytest.mark.parametrize('changes',[
    {'condition':'refurbished'},{'capacity':'2 TB'},{'quantity':2},{'mpn':'EX-2T'},
    {'eligibility':'membership'},{'currency':'CAD'}])
def test_conflicts_not_comparable(changes):
    assert compare(offer(),offer(**changes)).outcome=='NOT_COMPARABLE'


@pytest.mark.parametrize('changes',[{'condition':None},{'mpn':None},{'price':None},{'price':'0'},
                                  {'eligibility':None},{'capacity':None},{'availability':None}])
def test_unknowns_withhold(changes):
    assert compare(offer(),offer(**changes)).outcome=='INSUFFICIENT_EVIDENCE'


def test_stock_is_separate_from_identity():
    d=compare(offer(),offer(availability='out_of_stock'))
    assert d.outcome=='COMPARABLE_LISTED_PRICE' and d.action=='MONITOR_AVAILABILITY'


def test_no_evidence_no_comparable():
    a,b=offer(),offer();b.evidence=[]
    assert compare(a,b).outcome=='INSUFFICIENT_EVIDENCE'


def test_stale_and_source_conflicts():
    for changes in ({'observed_at':utcnow()-timedelta(hours=2)}, {'conflicts':['Price sources disagree']}):
        assert compare(offer(),offer(**changes)).outcome=='INSUFFICIENT_EVIDENCE'


def test_keyboards_require_layout_and_switch():
    assert compare(offer(category='keyboard'),offer(category='keyboard')).outcome=='INSUFFICIENT_EVIDENCE'


def keyboard(layout,switch):
    o=offer(category='keyboard',layout=layout,switch=switch)
    for field in ('layout','switch'):
        o.evidence.append(Evidence(id=field,url=o.url,field=field,excerpt=getattr(o,field)))
    return o


def test_partial_keyboard_layout_is_unknown_not_a_mismatch():
    d=compare(keyboard('80%, ANSI','Red'),keyboard('Tenkeyless','Red'))
    assert d.outcome=='INSUFFICIENT_EVIDENCE' and 'layout' in d.unknown


def test_barebone_spelling_does_not_create_a_switch_mismatch():
    assert compare(keyboard('ANSI','Barebone'),keyboard('ANSI','Barebones')).outcome=='COMPARABLE_LISTED_PRICE'


def test_explicit_keyboard_layout_conflict_remains_a_mismatch():
    assert compare(keyboard('ANSI US','Red'),keyboard('ISO UK','Red')).outcome=='NOT_COMPARABLE'
