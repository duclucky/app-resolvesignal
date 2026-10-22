"""Reproducible quality checks; every external operation requires an explicit flag."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.config import ROOT
from src.quality import corpus,evaluate,run_case
from src.schemas import Offer
from src.prompts import extraction_prompt
from src.providers.quality import LangSmith
from src.providers.live import LiveProviders
from src.store import Store


async def main(args):
    report=evaluate()
    if args.check_providers:
        report['provider_access']={}
        for name,cls in [('langsmith',LangSmith)]:
            report['provider_access'][name]=await cls().check()
    if args.langsmith:
        async with httpx.AsyncClient(timeout=12,trust_env=False) as client:
            provider=LangSmith(client=client,store=Store(ROOT/'data/investigations.sqlite3'))
            report['langsmith_suite']=await provider.record_evaluation(report)
            print(json.dumps({'langsmith_suite':report['langsmith_suite']}),flush=True)
    if args.model:
        report['live_model_checks']=[]
        for case in [c for c in corpus()['cases'] if c['id'] in ('ssd-lower','prompt-injection')]:
            live=LiveProviders(Store(ROOT/'data/investigations.sqlite3'))
            prompt=extraction_prompt([Offer(url=o['url'],title=o['title'],category=o['category']) for o in case['offers']],
                                     [o['page'] for o in case['offers']],[])
            try:
                answer=await live.reason(prompt,max_tokens=2600)
                if not isinstance(answer.get('offers'),list) or len(answer['offers'])!=2:raise ValueError('Invalid offer schema')
                result=run_case(case,claims=[o.get('claims',{}) for o in answer['offers']])
                result['trace']=live.trace
                passed=all(result['decision'][k]==v for k,v in case['expected'].items())
                row={'case_id':case['id'],'passed':passed,'authored_target':case['expected'],'result':result,
                     'model_claims_on_fictional_pages':answer['offers'],
                     'langsmith':await LangSmith(store=Store(ROOT/'data/investigations.sqlite3')).record(case['id']+'-live-model',result,passed)}
            except (ValueError,KeyError,TypeError) as exc:
                row={'case_id':case['id'],'passed':False,'error':str(exc)[:200],'trace':live.trace}
            report['live_model_checks'].append(row)
            print(json.dumps({'case':case['id'],'live_model_passed':row['passed']}),flush=True)
    output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(output),'synthetic_passed':report['passed'],'total':report['total']}))
    external_ok=report.get('langsmith_suite',{}).get('status','verified')=='verified'
    model_ok=all(r['passed'] for r in report.get('live_model_checks',[]))
    return 0 if report['passed']==report['total'] and external_ok and model_ok else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--langsmith',action='store_true');parser.add_argument('--model',action='store_true')
    parser.add_argument('--check-providers',action='store_true')
    parser.add_argument('--output',default='../.hackathon/evidence/ecommerce/quality-evaluation-v1.json')
    sys.exit(asyncio.run(main(parser.parse_args())))
