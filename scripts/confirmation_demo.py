"""Seed one explicitly fictional operator-confirmation case; no network or provider usage."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.config import ROOT
from src.samples import sample_result
from src.store import Store

store=Store(ROOT/'data/investigations.sqlite3')
bid,new=store.create_batch({'idempotency_key':'operator-confirmation-demo-v1','mode':'sample','cases':[{
    'sku':'unknown','reference_url':'https://example.com/reference','competitor_url':'https://example.com/competitor'}]})
row=store.batch(bid)[0]
if new:store.finish(row['id'],sample_result('unknown'))
print(json.dumps({'batch':bid,'case':row['id'],'created':new,'kind':'constructed_sample',
    'source_card':'data/fixtures/operator-source-card.md','network_calls':0}))
