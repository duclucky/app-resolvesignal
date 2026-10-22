"""Evaluate explicitly constructed cases. This is not a live provider benchmark."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from src.samples import sample_result

parser=argparse.ArgumentParser();parser.add_argument('--output',default='../.hackathon/evidence/ecommerce/constructed-evaluation.json');args=parser.parse_args()
expected={'comparable':'COMPARABLE_LISTED_PRICE','mismatch':'NOT_COMPARABLE','unknown':'INSUFFICIENT_EVIDENCE'}
rows=[{'case':key,'expected':value,'actual':sample_result(key)['decision']['outcome']} for key,value in expected.items()]
report={'method':'Constructed regression examples; no natural held-out corpus or live accuracy claim.','cases':rows,'passed':sum(x['expected']==x['actual'] for x in rows),'total':len(rows)}
Path(args.output).write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2));sys.exit(0 if report['passed']==report['total'] else 1)
