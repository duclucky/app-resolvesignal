"""Operator provenance changes the evidence basis, never retrieved facts or freshness."""
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from src.main import create_app
from src.schemas import Offer,Evidence,utcnow
from src.compare import compare


def case_with_missing_fields(app, *, stale=False, mismatch=False):
    store=app.state.store
    bid,_=store.create_batch({'idempotency_key':'confirmed-source','mode':'public','cases':[{
        'sku':'Test public-shaped SSD','reference_url':'https://samsung.com/a','competitor_url':'https://bestbuy.com/b'}]})
    cid=store.batch(bid)[0]['id'];offers=[]
    for side,url,price in [('reference','https://samsung.com/a','100'),('competitor','https://bestbuy.com/b','90')]:
        o=Offer(url=url,category='ssd',mpn='TEST-1' if not mismatch or side=='reference' else 'TEST-2',
                capacity='1 TB',price=price,currency='USD',price_basis='listed_item',availability='in_stock',
                observed_at=utcnow()-timedelta(hours=1) if stale else utcnow())
        for field in ('mpn','capacity','price','currency','price_basis','availability'):
            o.evidence.append(Evidence(id=side+field,url=url,field=field,excerpt=str(getattr(o,field))))
        offers.append(o)
    store.finish(cid,{'mode':'public','offers':[o.model_dump(mode='json') for o in offers],
                      'decision':compare(*offers).model_dump(),'trace':[]})
    return cid,bid


def payload(revision=1):
    return {'revision':revision,'confirmed_by':'Development tester','attested':True,
            'items':[{'side':side,'field':field,'value':value,'source_url':url,
                      'excerpt':quote} for side,url in [('reference','https://samsung.com/a'),('competitor','https://bestbuy.com/b')]
                     for field,value,quote in [('condition','new','Condition: new retail product.'),
                                               ('quantity',1,'Pack quantity: 1 SSD unit.'),
                                               ('eligibility','unconditional','Regular price available to everyone.')]]}


def test_confirmed_missing_fields_recompute_and_export_without_network(tmp_path,monkeypatch):
    app=create_app(tmp_path/'db.sqlite')
    def forbidden(*a,**k):raise AssertionError('Operator confirmation must not call a provider or fetch a URL.')
    monkeypatch.setattr('src.policies.socket.getaddrinfo',forbidden)
    with TestClient(app) as client:
        cid,bid=case_with_missing_fields(app)
        response=client.post(f'/api/cases/{cid}/confirmations',json=payload())
        assert response.status_code==200
        row=client.get(f'/api/cases/{cid}').json();r=row['result']
        assert row['revision']==2 and r['decision']['outcome']=='COMPARABLE_LISTED_PRICE'
        assert r['decision']['evidence_basis']=='operator_assisted'
        assert r['decision']['gap_amount']=='10.00'
        assert r['retrieved_offers'][0]['condition'] is None
        assert len(r['operator_confirmations'])==6
        assert all(e['retrieved_at'] is None for o in r['offers'] for e in o['evidence'] if e['origin']=='operator_confirmed')
        assert all(c['confirmed_by']=='Development tester' and c['active'] for c in r['operator_confirmations'])
        assert row['history'][-1]['result']['decision']['outcome']=='INSUFFICIENT_EVIDENCE'
        assert client.post(f'/api/cases/{cid}/review',json={'revision':1,'status':'reviewed','note':'stale review'}).status_code==409
        for fmt in ('json','csv','html'):
            exported=client.get(f'/api/batches/{bid}/export',params={'format':fmt})
            assert exported.status_code==200 and 'operator_assisted' in exported.text
        assert 'Development tester' in client.get(f'/api/batches/{bid}/export?format=html').text


def test_conflicting_observed_facts_and_price_overrides_rejected_atomically(tmp_path):
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,_=case_with_missing_fields(app)
        data=payload();data['items'].append({'side':'reference','field':'mpn','value':'OTHER',
            'source_url':'https://samsung.com/a','excerpt':'Model number: OTHER product.'})
        assert client.post(f'/api/cases/{cid}/confirmations',json=data).status_code==409
        assert client.get(f'/api/cases/{cid}').json()['revision']==1
        data=payload();data['items'][0]['field']='price';data['items'][0]['value']='1'
        assert client.post(f'/api/cases/{cid}/confirmations',json=data).status_code==422


@pytest.mark.parametrize('mutation',[
    lambda d:d.update(attested=False),
    lambda d:d.update(attested=1),
    lambda d:d.update(confirmed_by=' '),
    lambda d:d['items'][0].update(source_url='https://user:password@samsung.com/a'),
    lambda d:d['items'][0].update(source_url='https://127.0.0.1/a'),
    lambda d:d['items'][0].update(source_url='https://samsung.com/a?api_key=private'),
    lambda d:d['items'][1].update(value=True),
    lambda d:d['items'][1].update(value=0),
    lambda d:d['items'][0].update(excerpt=' '),
])
def test_invalid_confirmations_rejected(tmp_path,mutation):
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,_=case_with_missing_fields(app);data=payload();mutation(data)
        assert client.post(f'/api/cases/{cid}/confirmations',json=data).status_code==422
        assert client.get(f'/api/cases/{cid}').json()['revision']==1


def test_stale_revision_and_wrong_merchant_terms_rejected(tmp_path):
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,_=case_with_missing_fields(app)
        data=payload();data['items'][0]['source_url']='https://bestbuy.com/b'
        assert client.post(f'/api/cases/{cid}/confirmations',json=data).status_code==409
        assert client.post(f'/api/cases/{cid}/confirmations',json=payload()).status_code==200
        assert client.post(f'/api/cases/{cid}/confirmations',json=payload()).status_code==409


def test_reserved_example_source_only_accepted_for_labeled_samples(tmp_path):
    from src.samples import sample_result
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,_=case_with_missing_fields(app)
        data=payload();data['items'][0]['source_url']='https://example.com/fictional-card'
        assert client.post(f'/api/cases/{cid}/confirmations',json=data).status_code==409
        store=app.state.store;bid,_=store.create_batch({'idempotency_key':'sample-confirmation','mode':'sample','cases':[{
            'sku':'unknown','reference_url':'https://example.com/reference','competitor_url':'https://example.com/competitor'}]})
        sample=store.batch(bid)[0]['id'];store.finish(sample,sample_result('unknown'))
        data={'revision':1,'confirmed_by':'Fictional test operator','attested':True,'items':[{
            'side':'competitor','field':'eligibility','value':'unconditional','source_url':'https://example.com/competitor',
            'excerpt':'Fictional operator card: regular price available to everyone.'}]}
        assert client.post(f'/api/cases/{sample}/confirmations',json=data).status_code==200
        result=client.get(f'/api/cases/{sample}').json()['result']
        assert result['mode']=='sample' and result['decision']['evidence_basis']=='operator_assisted'
        item=result['operator_confirmations'][0]
        assert client.post(f'/api/cases/{sample}/confirmations/{item["id"]}/withdraw',json={'revision':2}).status_code==200
        import csv,io
        exported=list(csv.DictReader(io.StringIO(client.get(f'/api/batches/{bid}/export?format=csv').text)))[0]
        assert exported['active_operator_confirmations']=='0' and exported['evidence_basis']=='retrieved_only'


def test_confirmation_markup_escaped_in_report(tmp_path):
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,bid=case_with_missing_fields(app);data=payload()
        data['confirmed_by']='<script>operator</script>'
        data['items'][0]['excerpt']='Condition: new. <img src=x onerror=alert(1)>'
        assert client.post(f'/api/cases/{cid}/confirmations',json=data).status_code==200
        report=client.get(f'/api/batches/{bid}/export?format=html').text
        assert '<script>' not in report and '<img' not in report
        assert '&lt;script&gt;' in report and '&lt;img' in report


def test_invalid_source_errors_do_not_echo_credential_like_input(tmp_path):
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,_=case_with_missing_fields(app);data=payload()
        data['items'][0]['source_url']='https://samsung.com/a?api_key=test-private-credential'
        response=client.post(f'/api/cases/{cid}/confirmations',json=data)
        assert response.status_code==422 and 'test-private-credential' not in response.text


def test_confirmation_cannot_refresh_price_or_erase_identifier_conflict(tmp_path):
    for name,opts in [('stale',{'stale':True}),('mismatch',{'mismatch':True})]:
        app=create_app(tmp_path/(name+'.sqlite'))
        with TestClient(app) as client:
            cid,_=case_with_missing_fields(app,**opts)
            before=client.get(f'/api/cases/{cid}').json()['result']['offers'][0]['observed_at']
            assert client.post(f'/api/cases/{cid}/confirmations',json=payload()).status_code==200
            result=client.get(f'/api/cases/{cid}').json()['result']
            assert result['offers'][0]['observed_at']==before
            assert result['decision']['outcome']==('INSUFFICIENT_EVIDENCE' if name=='stale' else 'NOT_COMPARABLE')


def test_withdrawal_reverts_decision_preserves_audit_and_refresh_drops_confirmations(tmp_path):
    app=create_app(tmp_path/'db.sqlite')
    with TestClient(app) as client:
        cid,_=case_with_missing_fields(app)
        client.post(f'/api/cases/{cid}/confirmations',json=payload())
        row=client.get(f'/api/cases/{cid}').json();item=row['result']['operator_confirmations'][0]
        assert client.post(f'/api/cases/{cid}/confirmations/{item["id"]}/withdraw',json={'revision':2}).status_code==200
        row=client.get(f'/api/cases/{cid}').json()
        assert row['revision']==3 and row['result']['decision']['outcome']=='INSUFFICIENT_EVIDENCE'
        assert row['result']['offers'][0]['condition'] is None
        assert not row['result']['operator_confirmations'][0]['active']
        assert row['history'][1]['result']['decision']['outcome']=='COMPARABLE_LISTED_PRICE'
        store=app.state.store;store.requeue(cid)
        retrieved=row['result']['retrieved_offers'];store.finish(cid,{'mode':'public','offers':retrieved,'decision':{}})
        assert not store.case(cid)['result'].get('operator_confirmations')
