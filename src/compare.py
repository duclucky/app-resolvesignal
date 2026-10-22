import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from .schemas import Decision, utcnow
from .identifiers import canonical_gtin


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower()) if value is not None else None


def supported(offer, field):
    return any(e.field==field and e.excerpt.strip() and (
        (e.origin=='retrieved' and e.url==offer.url) or
        (e.origin=='operator_confirmed' and e.subject_url==offer.url and e.confirmation_id and e.confirmed_by and e.confirmed_at)
    ) for e in offer.evidence)


def layout_dimensions(value):
    """Keep physical standard, size and locale separate; missing parts stay unknown."""
    text=str(value).lower();parts={}
    standard=re.search(r'\b(ansi|iso|jis)\b',text)
    size=re.search(r'\b(\d{2,3})\s*%',text)
    locale=re.search(r'\b(us|uk)\b',text)
    if standard:parts['standard']=standard[1]
    if size:parts['size']=size[1]
    elif re.search(r'\b(tkl|tenkeyless)\b',text):parts['size']='80'
    elif re.search(r'\bfull[ -]?size\b',text):parts['size']='100'
    if locale:parts['locale']=locale[1]
    return parts


def compare(reference, competitor, now=None):
    now = now or utcnow()
    d = Decision()
    if any(e.origin=='operator_confirmed' for o in (reference,competitor) for e in o.evidence):
        d.evidence_basis='operator_assisted'
        d.caveats.append('Includes operator-confirmed attributes. Source quotes and operator identity were not independently verified by the app.')
    fields = ['condition','quantity','currency','eligibility','price_basis']
    identity_conflicts=[]
    gtins=[canonical_gtin(o.gtin) if supported(o,'gtin') else None for o in (reference,competitor)]
    mpns=[o.mpn if supported(o,'mpn') else None for o in (reference,competitor)]
    if all(gtins):
        if gtins[0]!=gtins[1]:identity_conflicts.append(f'gtin: {reference.gtin} versus {competitor.gtin}')
        else:d.matched.append('gtin')
    if all(mpns):fields.insert(0,'mpn')
    elif not all(gtins):d.unknown.append('mpn or validated GTIN')
    if reference.category == competitor.category == 'ssd':
        fields += ['capacity']
    elif reference.category == competitor.category == 'keyboard':
        fields += ['layout','switch']
    else:
        # A matching validated barcode identifies a specific generic product/variant.
        # A family title or matching MPN alone cannot establish arbitrary variants.
        if not all(gtins):d.unknown.append('matching product barcode for this product type')
        d.caveats.append('Other product types require matching valid product barcodes. Check the exact size, color, bundle and selected variant on both pages.')
    conflicts = identity_conflicts
    for field in fields:
        a,b = getattr(reference,field),getattr(competitor,field)
        if a is None or b is None or not supported(reference,field) or not supported(competitor,field):
            d.unknown.append(field)
        elif field=='layout' and normalized(a)!=normalized(b):
            left,right=layout_dimensions(a),layout_dimensions(b)
            shared=left.keys() & right.keys()
            if any(left[k]!=right[k] for k in shared):conflicts.append(f'{field}: {a} versus {b}')
            elif left and left==right:d.matched.append(field)
            else:d.unknown.append(field)
        elif field=='switch' and normalized(a) in ('barebone','barebones') and normalized(b) in ('barebone','barebones'):
            d.matched.append(field)
        elif normalized(a) != normalized(b):
            conflicts.append(f'{field}: {a} versus {b}')
        else:
            d.matched.append(field)
    d.evidence_ids = [e.id for o in (reference,competitor) for e in o.evidence]
    if conflicts:
        d.outcome='NOT_COMPARABLE';d.action='DISMISS_MISMATCH';d.reasons=conflicts
        return d
    for label,o in [('reference',reference),('competitor',competitor)]:
        if o.price is None or not o.price.is_finite() or o.price <= 0 or not supported(o,'price'):
            d.unknown.append(f'{label} valid price')
        if o.currency != 'USD':d.unknown.append(f'{label} supported USD market')
        if o.eligibility != 'unconditional':d.unknown.append(f'{label} unconditional eligibility')
        if not o.availability or not supported(o,'availability'):d.unknown.append(f'{label} availability')
        if o.observed_at.tzinfo is None or now-o.observed_at > timedelta(minutes=30) or o.observed_at > now+timedelta(minutes=2):
            d.unknown.append(f'{label} fresh observation')
        if o.conflicts:d.unknown.extend(o.conflicts)
        if not o.shipping:d.caveats.append(f'{label.title()} shipping unknown.')
        if not o.tax:d.caveats.append(f'{label.title()} tax unknown.')
    if d.unknown:
        d.reasons=['Material fields are missing, stale or conflicting.']
        return d
    d.outcome='COMPARABLE_LISTED_PRICE'
    gap=reference.price-competitor.price
    money=lambda x: str(x.quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
    d.gap_amount=money(gap);d.gap_percent=money(gap/reference.price*100)
    d.action='MONITOR_AVAILABILITY' if competitor.availability!='in_stock' else ('REVIEW_PRICING' if gap>0 else 'NO_PRICE_ACTION')
    d.reasons=['Decisive product and offer fields match on the disclosed listed-price basis.']
    if d.evidence_basis=='operator_assisted':
        d.reasons=['Product and offer fields match conditional on the operator confirmations, on the disclosed listed-price basis.']
    return d
