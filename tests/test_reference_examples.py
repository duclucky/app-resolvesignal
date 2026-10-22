import asyncio
import pytest
from src.store import Store
from src.agent import Investigator


def test_reference_catalog_runs_real_rules_and_labels_every_result(tmp_path):
    from src.reference_examples import install, EXAMPLES
    from src.quality import corpus
    store=Store(tmp_path/'references.sqlite');bid=install(store)
    rows=store.batch(bid);expected={c['id']:c['expected'] for c in corpus()['cases']}
    assert len(rows)==len(EXAMPLES)==15
    assert len({r['request']['sku'] for r in rows})==15
    assert {r['result']['decision']['outcome'] for r in rows}=={'COMPARABLE_LISTED_PRICE','NOT_COMPARABLE','INSUFFICIENT_EVIDENCE'}
    for row in rows:
        result=row['result'];assert row['state']=='completed' and result['mode']=='synthetic'
        assert result['display_title'] and result['learning_note'] and result['scenario_sources']
        assert result['decision']['outcome']==expected[row['request']['sku']]['outcome']
        assert result['decision']['action']==expected[row['request']['sku']]['action']
        assert all(s['provider']=='fixture' for s in result['trace'])
    assert store.usage()=={}
    assert store.list_batches()[0]['label']=='More made-up examples'


def test_reference_install_is_idempotent_and_preserves_reviews(tmp_path):
    from src.reference_examples import install
    store=Store(tmp_path/'references.sqlite');bid=install(store);row=store.batch(bid)[0]
    store.review(row['id'],{'revision':1,'status':'reviewed','note':'Keep this review'})
    before=store.case(row['id'])
    assert install(store)==bid
    assert len(store.list_batches())==1 and store.case(row['id'])==before


def test_reference_recheck_preserves_explanation_without_live_calls(tmp_path,monkeypatch):
    from src.reference_examples import install
    store=Store(tmp_path/'references.sqlite');bid=install(store);row=store.batch(bid)[0]
    def forbidden(*args,**kwargs):raise AssertionError('Fictional reference must remain offline')
    monkeypatch.setattr('src.agent.LiveProviders',forbidden)
    store.requeue(row['id']);asyncio.run(Investigator(store).run(row['id']))
    after=store.case(row['id'])
    assert after['revision']==2 and len(after['history'])==2
    assert after['result']['display_title']==row['result']['display_title']
    assert after['result']['learning_note']==row['result']['learning_note']
    assert after['result']['mode']=='synthetic' and store.usage()=={}


def test_reference_links_and_exports_are_publicly_readable_without_seeding_on_get(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from src.main import create_app
    from src.reference_examples import install
    monkeypatch.setenv('APP_PUBLIC_DEMO','true')
    app=create_app(tmp_path/'references.sqlite');store=app.state.store
    with TestClient(app) as client:
        client.get('/investigations');assert store.list_batches()==[]
        bid=install(store)
        page=client.get('/investigations').text
        assert f'/investigations?batch={bid}' in page and 'More made-up examples (15)' in page
        data=client.get(f'/api/batches/{bid}/export?format=json').json()
        assert len(data)==15 and all(r['result']['mode']=='synthetic' for r in data)
        assert client.post('/api/quality/batch',json={}).status_code==403
    assert store.usage()=={}


@pytest.mark.parametrize('urls,same',[
    (('https://www.samsung.com/us/a','https://samsung.com/us/b'),True),
    (('https://www.keychron.com/products/a','https://mechanicalkeyboards.com/products/a'),False),
])
def test_real_reference_same_store_scope_is_explicit(urls,same):
    from src.policies import comparison_scope
    scope=comparison_scope(*urls)
    assert bool(scope)==same
    if same:assert scope['kind']=='same_merchant_control' and 'same store' in scope['notice']
