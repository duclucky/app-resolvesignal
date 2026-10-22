import asyncio
import pytest
from src.providers.live import LiveProviders
from src.store import Store


def provider(monkeypatch,tmp_path):
    monkeypatch.setattr('src.providers.live.settings',lambda:{'LIVE_CALLS_ENABLED':'true','NEBIUS_API_KEY':'test-key','TAVILY_API_KEY':'test-key','NEBIUS_MODEL':'nvidia/Nemotron-3.5-Super-VL','NEBIUS_BUDGET_USD':'0.5','TAVILY_CREDIT_CAP':'50'})
    return LiveProviders(Store(tmp_path/'db.sqlite'))


def test_invalid_model_json_fails_explicitly(monkeypatch,tmp_path):
    p=provider(monkeypatch,tmp_path)
    async def post(*a):return {'choices':[{'message':{'content':'not-json'}}]}
    p.post=post
    with pytest.raises(ValueError,match='invalid JSON'):asyncio.run(p.reason('task'))


def test_missing_final_content_and_call_cap(monkeypatch,tmp_path):
    p=provider(monkeypatch,tmp_path)
    async def post(*a):return {'choices':[{'message':{'content':None}}]}
    p.post=post
    with pytest.raises(ValueError,match='no usable content'):asyncio.run(p.reason('task'))
    p.calls=4
    with pytest.raises(ValueError,match='call limit'):asyncio.run(p.reason('task'))


def test_partial_extract_is_preserved(monkeypatch,tmp_path):
    p=provider(monkeypatch,tmp_path)
    async def post(*a):return {'results':[{'url':'https://samsung.com/a','raw_content':'data'}],'failed_results':[{'url':'https://bestbuy.com/b','error':'timeout'}]}
    p.post=post;r=asyncio.run(p.extract(['https://samsung.com/a','https://bestbuy.com/b']))
    assert len(r['results'])==1 and len(r['failed_results'])==1
