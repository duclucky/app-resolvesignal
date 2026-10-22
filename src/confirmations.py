"""Revision-scoped operator assertions. Source retrieval and human attestation stay distinct."""
import uuid
from urllib.parse import urlsplit
from .schemas import Offer,Evidence,ConfirmationInput,utcnow
from .compare import compare
from .policies import DEFAULT_DOMAINS


def merchant(url):
    host=urlsplit(url).hostname or ''
    return next((d for d in DEFAULT_DOMAINS+('example.com',) if host==d or host.endswith('.'+d)),host.lower().removeprefix('www.'))


def recompute(result,kind,revision):
    offers=[Offer.model_validate(o) for o in result['retrieved_offers']]
    for item in result['operator_confirmations']:
        if not item['active']:continue
        offer=offers[0 if item['side']=='reference' else 1]
        if getattr(offer,item['field']) is not None:raise ValueError('A confirmation cannot overwrite retrieved evidence.')
        setattr(offer,item['field'],item['value'])
        offer.evidence.append(Evidence(id=item['id'],url=item['source_url'],field=item['field'],excerpt=item['excerpt'],
            provider='operator_confirmation',origin='operator_confirmed',subject_url=offer.url,retrieved_at=None,
            confirmation_id=item['id'],confirmed_by=item['confirmed_by'],confirmed_at=item['confirmed_at']))
    result['offers']=[o.model_dump(mode='json') for o in offers]
    result['decision']=compare(*offers).model_dump()
    result['derivation']={'kind':kind,'based_on_revision':revision,'recalculated_at':utcnow().isoformat(),
                          'provider_calls':0,'source_quotes_independently_verified':False}
    # A telemetry receipt for the previous outcome does not verify the derived one.
    if 'observability' in result:result['retrieval_observability']=result.pop('observability')
    if 'elapsed_seconds' in result:result['retrieval_elapsed_seconds']=result.pop('elapsed_seconds')
    return result


def add(result,payload):
    data=ConfirmationInput.model_validate(payload)
    if len(result.get('offers',[]))!=2:raise ValueError('Two collected offers are required before confirming attributes.')
    raw=result.setdefault('retrieved_offers',result['offers'])
    result.setdefault('retrieved_decision',result['decision'])
    items=result.setdefault('operator_confirmations',[])
    active={(x['side'],x['field']) for x in items if x['active']}
    for claim in data.items:
        pair=(claim.side,claim.field);offer=Offer.model_validate(raw[0 if claim.side=='reference' else 1])
        if pair in active or getattr(offer,claim.field) is not None:
            raise ValueError('Only missing attributes can be confirmed. Withdraw an earlier confirmation before replacing it.')
        if merchant(claim.source_url)=='example.com' and result.get('mode') not in ('sample','synthetic'):
            raise ValueError('Reserved example sources are only allowed in constructed sample cases.')
        if any('unselected' in x or 'ambiguous' in x for x in offer.conflicts):
            raise ValueError('Select an exact product variant before confirming missing attributes.')
        if claim.field in ('layout','switch') and offer.category!='keyboard':raise ValueError('Keyboard attributes require a keyboard offer.')
        if claim.field=='capacity' and offer.category!='ssd':raise ValueError('Capacity requires an SSD offer.')
        if claim.field in ('condition','eligibility') and merchant(claim.source_url)!=merchant(offer.url):
            raise ValueError('Condition and price eligibility require a source from that offer merchant.')
        active.add(pair)
        items.append({**claim.model_dump(),'id':uuid.uuid4().hex,'active':True,'confirmed_by':data.confirmed_by,
                      'confirmed_at':utcnow().isoformat(),'attested':True,'source_verification':'operator_attested_not_independently_checked'})
    return recompute(result,'operator_confirmation',data.revision)


def withdraw(result,item_id,revision,note):
    item=next((x for x in result.get('operator_confirmations',[]) if x['id']==item_id and x['active']),None)
    if item is None:raise ValueError('Active confirmation not found in this evidence revision.')
    item.update(active=False,withdrawn_at=utcnow().isoformat(),withdrawal_note=note,
                withdrawn_by='local_operator_identity_unverified')
    return recompute(result,'confirmation_withdrawal',revision)
