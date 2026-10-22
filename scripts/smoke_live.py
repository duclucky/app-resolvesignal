"""Run a specified real case; requires configured, authorized provider caps."""
import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.agent import Investigator
from src.config import ROOT,status
from src.policies import validate_url
from src.store import Store

parser=argparse.ArgumentParser();parser.add_argument('--reference',required=True);parser.add_argument('--competitor',required=True);parser.add_argument('--output',default='../.hackathon/evidence/ecommerce/live-smoke.json');args=parser.parse_args()

async def main():
    for url in (args.reference,args.competitor):validate_url(url)
    if not status()['live_enabled']:raise SystemExit('Live integrations are disabled.')
    s=Store(ROOT/'data/investigations.sqlite3');bid,_=s.create_batch({'idempotency_key':str(uuid.uuid4()),'mode':'live','cases':[{'sku':'Live smoke test','reference_url':args.reference,'competitor_url':args.competitor}]})
    cid=s.batch(bid)[0]['id'];await Investigator(s).run(cid);row=s.case(cid)
    Path(args.output).write_text(json.dumps(row,indent=2),encoding='utf-8')
    print(json.dumps({'batch':bid,'case':cid,'state':row['state'],'outcome':row['result']['decision']['outcome'],'trace_calls':len(row['result'].get('trace',[])),'error':row['error']}))
    if row['state'] not in ('completed','partial'):raise SystemExit(1)

asyncio.run(main())
