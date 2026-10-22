"""Minimized LangSmith tracing and bounded evaluation uploads."""
import json
import asyncio
import uuid
from datetime import datetime, timezone
import httpx
from ..config import settings


class QualityService:
    def __init__(self, config=None, client=None, store=None):
        self.config = settings() if config is None else config
        self.client = client
        self.store = store

    async def request(self, method, url, **kwargs):
        if self.client is not None:
            response = await self.client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient(timeout=12, trust_env=False) as client:
                response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response


class LangSmith(QualityService):
    BASE = 'https://api.smith.langchain.com'

    def headers(self):
        headers = {'x-api-key': self.config['LANGSMITH_API_KEY']}
        if self.config.get('LANGSMITH_WORKSPACE_ID'):
            headers['x-tenant-id'] = self.config['LANGSMITH_WORKSPACE_ID']
        return headers

    async def check(self):
        if not self.config.get('LANGSMITH_API_KEY'):
            return {'status': 'not_configured'}
        try:
            await self.request('GET', self.BASE+'/sessions', headers=self.headers(), params={'limit': 1})
            return {'status': 'verified', 'operation': 'list_projects'}
        except (httpx.HTTPError, ValueError):
            return {'status': 'failed', 'message': 'LangSmith access check failed. No response body retained.'}

    async def record_evaluation(self,report):
        """One bounded batch avoids per-case ingestion/read rate limits."""
        from datetime import timedelta
        if self.config.get('LANGSMITH_ENABLED')!='true' or not self.config.get('LANGSMITH_API_KEY'):
            return {'status':'disabled','uploaded':0}
        if report.get('dataset_kind')!='synthetic_sourced_scenarios' or not 1<=len(report['cases'])<=50:
            raise ValueError('Only bounded synthetic evaluation summaries are accepted.')
        root_id=str(uuid.uuid4());start=datetime.now(timezone.utc)
        order=lambda stamp,rid:stamp.strftime('%Y%m%dT%H%M%S%fZ')+rid
        root_order=order(start,root_id)
        root={'id':root_id,'trace_id':root_id,'dotted_order':root_order,'name':'Synthetic scenario evaluation',
              'run_type':'chain','session_name':'price-alert-investigator','start_time':start.isoformat(),
              'end_time':(start+timedelta(microseconds=100)).isoformat(),
              'inputs':{'dataset_id':report['dataset_id'],'dataset_sha256':report['dataset_sha256']},
              'outputs':{'passed':report['passed'],'total':report['total'],'false_comparable':report['false_comparable']},
              'extra':{'metadata':{'synthetic':True,'evaluation_method':'simulated_claims_production_validation','data_policy':'outcomes_and_counters_only'}}}
        runs=[root]
        for index,row in enumerate(report['cases'],1):
            rid=str(uuid.uuid4());stamp=start+timedelta(microseconds=index)
            runs.append({'id':rid,'trace_id':root_id,'parent_run_id':root_id,'dotted_order':root_order+'.'+order(stamp,rid),
                'name':row['id'],'run_type':'chain','session_name':root['session_name'],'start_time':stamp.isoformat(),
                'end_time':stamp.isoformat(),'inputs':{'case_id':row['id'],'input_hash':row['input_hash']},
                'outputs':{'actual':row['actual'],'authored_target':row['expected'],'passed':row['passed']},
                'extra':{'metadata':{'synthetic':True}}})
        stage='batch_upload'
        try:
            if self.store is not None:self.store.reserve('langsmith_reserved_runs',1,100)
            await self.request('POST',self.BASE+'/runs/batch',headers=self.headers(),json={'post':runs})
            stage='feedback'
            await self.request('POST',self.BASE+'/feedback',headers=self.headers(),json={
                'id':str(uuid.uuid4()),'run_id':root_id,'key':'synthetic_expected_outcome',
                'score':report['passed']/report['total'],'feedback_source':{'type':'api'}})
            stage='batch_readback';expected={r['id']:r['outputs'] for r in runs}
            for attempt in range(4):
                stored=(await self.request('POST',self.BASE+'/runs/query',headers=self.headers(),
                    json={'id':list(expected),'limit':100,'select':['id','outputs']})).json()
                found={r['id']:r.get('outputs') for r in stored.get('runs',[])}
                if found==expected:
                    return {'status':'verified','run_id':root_id,'uploaded':len(runs)-1,'total':report['total'],
                            'verification':'All root/child IDs and result summaries read back from provider.'}
                if attempt<3:await asyncio.sleep((0.3,0.7,1.5)[attempt])
            raise ValueError('Batch readback incomplete')
        except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
            return {'status':'failed','run_id':root_id,'uploaded':0,'stage':stage,
                    'http_status':exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None,
                    'message':'Batch upload/readback did not verify; local evaluation preserved.'}

    async def record(self, case_id, result, evaluation=None):
        """Allowlist counters and outcomes, never source text, prompts, notes or URLs."""
        if self.config.get('LANGSMITH_ENABLED') != 'true' or not self.config.get('LANGSMITH_API_KEY'):
            return {'status': 'disabled'}
        run_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        decision = result.get('decision', {})
        outputs = {k: decision[k] for k in ('outcome', 'action', 'gap_percent') if k in decision}
        outputs['evidence_count'] = sum(len(o.get('evidence', [])) for o in result.get('offers', []))
        root = {'id': run_id, 'name': 'Offer investigation', 'run_type': 'chain',
                'session_name': 'price-alert-investigator', 'start_time': now,
                'inputs': {'case_id': str(case_id)[:80], 'mode': result.get('mode', 'unknown')},
                'extra': {'metadata': {'data_policy': 'outcomes_and_counters_only',
                                        'synthetic': result.get('mode') in ('synthetic', 'sample')}}}
        stage='create_run'
        try:
            if self.store is not None:
                self.store.reserve('langsmith_reserved_runs',1,100)
            await self.request('POST', self.BASE+'/runs', headers=self.headers(), json=root)
            for index, step in enumerate(result.get('trace', [])[:12]):
                provider = step.get('provider')
                if provider not in ('tavily', 'nebius', 'fixture'):
                    continue
                child = {'id': str(uuid.uuid4()), 'parent_run_id': run_id,
                         'name': provider+' step '+str(index+1), 'run_type': 'tool',
                         'session_name': root['session_name'], 'start_time': now, 'end_time': now,
                         'inputs': {}, 'outputs': {k: step[k] for k in ('status', 'elapsed_ms', 'model') if k in step}}
                await self.request('POST', self.BASE+'/runs', headers=self.headers(), json=child)
            stage='complete_run'
            await self.request('PATCH', self.BASE+'/runs/'+run_id, headers=self.headers(),
                               json={'outputs': outputs, 'end_time': datetime.now(timezone.utc).isoformat()})
            if evaluation is not None:
                stage='feedback'
                await self.request('POST', self.BASE+'/feedback', headers=self.headers(), json={
                    'id': str(uuid.uuid4()), 'run_id': run_id, 'key': 'synthetic_expected_outcome',
                    'score': float(bool(evaluation)), 'feedback_source': {'type': 'api'}})
            # Acceptance must be checked against actual stored state, not just POST 2xx.
            stage='readback'
            for attempt in range(4):
                try:
                    stored=(await self.request('GET',self.BASE+'/runs/'+run_id,headers=self.headers())).json()
                    break
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code!=404 or attempt==3:raise
                    await asyncio.sleep((0.3,0.7,1.5)[attempt])
            if stored.get('id') != run_id:
                raise ValueError('Trace readback mismatch')
            return {'status': 'verified', 'run_id': run_id, 'data_policy': 'outcomes_and_counters_only'}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            return {'status': 'failed', 'run_id': run_id, 'stage':stage,
                    'http_status':exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None,
                    'message': 'Optional trace upload/readback failed; investigation preserved.'}
