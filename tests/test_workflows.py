from src.workflows import Workflows
from src.store import Store


def test_activity_counts_only_successful_current_revisions(tmp_path):
    store=Store(tmp_path/'state.sqlite')
    bid,_=store.create_batch({'idempotency_key':'activity-summary','mode':'live','cases':[{'sku':'x'}]})
    cid=store.batch(bid)[0]['id']
    store.finish(cid,{'trace':[{'provider':'nebius','status':'ok'},{'provider':'tavily','status':'failed'}],
                      'observability':{'status':'verified'}})
    providers=Workflows(store).public_summary()['providers']
    assert providers['nebius']['verified_steps']==1
    assert providers['tavily']['verified_steps']==0
    assert providers['langsmith']['verified_runs']==1
    store.requeue(cid)
    store.finish(cid,{'trace':[]})
    providers=Workflows(store).public_summary()['providers']
    assert providers['nebius']['verified_steps']==0
    assert providers['langsmith']['verified_runs']==0
