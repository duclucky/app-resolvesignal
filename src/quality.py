"""Sourced fictional regressions for local comparison checks."""
import hashlib
import json
from datetime import timedelta
from .config import ROOT
from .schemas import Offer, utcnow
from .agent import apply_claims
from .compare import compare

CORPUS=ROOT/'data/fixtures/offer-scenarios-v1.json'


def corpus():
    return json.loads(CORPUS.read_text(encoding='utf-8'))


def input_hash(case):
    return hashlib.sha256(json.dumps(case['offers'],sort_keys=True).encode()).hexdigest()



def run_case(case, claims=None):
    now=utcnow();offers=[]
    for index, source in enumerate(case['offers']):
        offer=Offer(url=source['url'],title=source['title'],category=source['category'],
                    observed_at=now-timedelta(minutes=source['age_minutes']),conflicts=source['conflicts'])
        offer=apply_claims(offer,source['claims'] if claims is None else claims[index],source['page'])
        for evidence in offer.evidence:evidence.provider='synthetic_fixture'
        offers.append(offer)
    decision=compare(*offers,now=now).model_dump()
    return {'mode':'synthetic','offers':[o.model_dump(mode='json') for o in offers], 'decision':decision,
            'summary':'Fictional offers; scenario sources are linked in the dataset. No live retailer retrieval.',
            'trace':[{'provider':'fixture','status':'ok','elapsed_ms':0}]}


def evaluate():
    dataset=corpus();rows=[]
    for case in dataset['cases']:
        result=run_case(case);decision=result['decision'];expected=case['expected']
        rows.append({'id':case['id'],'description':case['description'],'expected':expected,
                     'actual':{'outcome':decision['outcome'],'action':decision['action']},
                     'passed':all(decision[k]==v for k,v in expected.items()),'sources':case['sources'],
                     'input_hash':input_hash(case)})
    return {'dataset_id':dataset['dataset_id'],'dataset_kind':dataset['kind'],
            'dataset_sha256':hashlib.sha256(CORPUS.read_bytes()).hexdigest(), 'checked_at':utcnow().isoformat(),
            'method':'Simulated claims -> actual source-span validation -> actual deterministic comparison.',
            'limitations':dataset['limitations'],'live_provider_calls':0,'total':len(rows),
            'passed':sum(row['passed'] for row in rows),
            'false_comparable':sum(row['actual']['outcome']=='COMPARABLE_LISTED_PRICE' and row['expected']['outcome']!='COMPARABLE_LISTED_PRICE' for row in rows),
            'cases':rows}
