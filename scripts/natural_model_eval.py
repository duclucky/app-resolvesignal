"""Evaluate actual model extraction on frozen public pages; never claim live prices."""
import argparse
import asyncio
import gzip
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.agent import apply_claims
from src.compare import compare
from src.config import ROOT
from src.parser import text_content
from src.prompts import extraction_prompt
from src.providers.live import LiveProviders
from src.schemas import Offer
from src.store import Store

OUT=ROOT.parent/'.hackathon/evidence/ecommerce/natural-source-gate'


async def run(args):
    pairs=json.loads((OUT/'natural-pairs.json').read_text(encoding='utf-8'))
    replay=json.loads((OUT/'natural-replay-evaluation.json').read_text(encoding='utf-8'))
    lookup={x['id']:x for x in replay['cases']}
    held=[x for x in pairs if x['split']=='holdout']
    if len(held)!=20:raise ValueError('Expected the frozen 20-case reserved family split.')
    if not args.run_model:
        print(json.dumps({'reserved_cases':len(held),'network_calls':0,'run_requires':'--run-model'}));return
    store=Store(ROOT/'data/investigations.sqlite3');visible={};rows=[]
    for pair in held:
        start=time.monotonic();base=lookup[pair['id']]
        offers=[Offer.model_validate(x) for x in base['offers']];texts=[]
        for offer,source in zip(offers,pair['sources']):
            name=source['snapshot']
            if name not in visible:
                html=gzip.decompress((OUT/name).read_bytes()).decode('utf-8')
                visible[name]=text_content(html)
            texts.append(('\n'.join(e.excerpt for e in offer.evidence)+'\n'+visible[name])[:5500])
        prompt=extraction_prompt(offers,texts,[]);provider=LiveProviders(store)
        row={'id':pair['id'],'expected':base['expected'],'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),
             'snapshot_times':[o.observed_at.isoformat() for o in offers]}
        try:
            answer=await provider.reason(prompt,max_tokens=2600)
            row['raw_model_output']=answer
            claims=answer.get('offers')
            if not isinstance(claims,list) or len(claims)!=2:raise ValueError('Invalid two-offer output.')
            offers=[apply_claims(o,item.get('claims',{}),text) for o,item,text in zip(offers,claims,texts)]
            decision=compare(*offers,now=max(o.observed_at for o in offers)).model_dump()
            row.update(decision=decision,offers=[o.model_dump(mode='json') for o in offers],
                       passed=decision['outcome']==base['expected']['outcome'],proposed_claims=claims)
        except (ValueError,TypeError,KeyError) as exc:
            row.update(passed=False,error_type=type(exc).__name__,error=str(exc)[:500])
        row.update(trace=provider.trace,elapsed_seconds=round(time.monotonic()-start,3));rows.append(row)
        report={'method':'Actual NVIDIA-on-Nebius model plus production quote guards and comparison, on frozen real HTML. No Tavily calls in this replay.',
                'limitations':'Convenience corpus, agent-authored targets, one brand/two templates, no positive comparable case. Reused diagnostic cases after discovered failures; no longer an untouched holdout. Not independent accuracy or a ChatGPT/Codex baseline.',
                'total':len(rows),'passed':sum(x['passed'] for x in rows),'cases':rows}
        (OUT/'natural-model-evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'id':row['id'],'passed':row['passed'],'outcome':row.get('decision',{}).get('outcome')}),flush=True)
    if not all(x['passed'] for x in rows):raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run-model',action='store_true')
    asyncio.run(run(parser.parse_args()))
