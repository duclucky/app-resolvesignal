import asyncio
import csv
import io
import json
import hashlib
import os
import time
import secrets
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from .schemas import BatchInput, ReviewInput, CaseInput, ConfirmationInput, WithdrawalInput
from .config import ROOT, status, save_settings, data_directory
from .store import Store
from .agent import Investigator
from .policies import validate_url,safe_csv,SELECTED_SOURCE_URLS
from .first_run import saved_example, selected_demo_case
from .admission import DemoAdmission,COOKIE


def create_app(database=None):
    public_demo=os.environ.get('APP_PUBLIC_DEMO')=='true'
    demo_writes=deque()
    store=Store(database or data_directory()/'investigations.sqlite3');investigator=Investigator(store);tasks=set()
    admission=DemoAdmission(store) if public_demo else None
    def admit_demo_live(request,key):
        if admission:
            try:admission.admit(request.state.visitor,key)
            except ValueError as exc:raise HTTPException(429,str(exc)) from None
    def launch(cid):
        task=asyncio.create_task(investigator.run(cid));tasks.add(task);task.add_done_callback(tasks.discard)
    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        for t in tasks:t.cancel()
        if tasks:await asyncio.gather(*list(tasks),return_exceptions=True)
    app=FastAPI(title='ResolveSignal',lifespan=lifespan);app.state.store=store
    from .workflows import Workflows
    workflow=Workflows(store)
    app.mount('/static',StaticFiles(directory=ROOT/'src/static'),name='static');templates=Jinja2Templates(directory=ROOT/'src/templates')
    def asset_url(name):
        fingerprint=hashlib.sha256((ROOT/'src/static'/name).read_bytes()).hexdigest()[:12]
        return f'/static/{name}?v={fingerprint}'
    templates.env.globals['asset_url']=asset_url
    templates.env.globals['public_demo']=public_demo

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request,exc):
        # URLs and other input may accidentally contain secrets; return reasons, not input.
        return JSONResponse(status_code=422,content={'detail':[
            {key:error[key] for key in ('loc','msg','type') if key in error} for error in exc.errors()]})

    @app.middleware('http')
    async def local_guard(request,call_next):
        visitor_cookie=None
        if admission:
            request.state.visitor,visitor_cookie=admission.identify(request.cookies.get(COOKIE))
        host=request.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost','testserver'):
            return Response('Local access only.',status_code=403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if 'application/json' not in request.headers.get('content-type',''):
                return Response('JSON requests required.',status_code=415)
            origin=request.headers.get('origin')
            allowed_origins=os.environ.get('APP_ALLOWED_ORIGINS','http://127.0.0.1:8000,http://localhost:8000,http://testserver').split(',')
            if origin and origin not in allowed_origins:
                return Response('Cross-origin request denied.',status_code=403)
            if int(request.headers.get('content-length','0'))>200000:return Response('Input too large.',status_code=413)
            if public_demo:
                now=time.monotonic()
                while demo_writes and now-demo_writes[0]>=60:demo_writes.popleft()
                if len(demo_writes)>=30:
                    return JSONResponse(status_code=429,content={'detail':'Shared demo is busy. Try again in a minute.'},headers={'Retry-After':'60'})
                demo_writes.append(now)
            if request.url.path=='/api/settings' and (public_demo or os.environ.get('APP_SETTINGS_LOCKED')=='true'):
                return JSONResponse(status_code=403,content={'detail':'Settings are managed by the server administrator.'})
            paid_quality=request.url.path in ('/api/quality/check/langsmith','/api/quality/langsmith/evaluate')
            if paid_quality and (public_demo or os.environ.get('APP_EXTERNAL_ACTIONS_ENABLED','true')!='true'):
                return JSONResponse(status_code=403,content={'detail':'External quality actions are disabled for this profile.'})
        response=await call_next(request)
        if admission and visitor_cookie!=request.cookies.get(COOKIE):
            response.set_cookie(COOKIE,visitor_cookie,max_age=7*86400,httponly=True,samesite='lax',
                                secure=os.environ.get('APP_VISITOR_COOKIE_SECURE','true')=='true')
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.get('/healthz')
    def health():
        with store.connect() as connection:connection.execute('SELECT 1').fetchone()
        return {'service':'price-alert-investigator','status':'ok'}

    @app.get('/',response_class=HTMLResponse)
    def home(request:Request):return templates.TemplateResponse(request=request,name='index.html',context={
        'selected_source_urls':SELECTED_SOURCE_URLS,'example':saved_example(store),
        'page_title':'ResolveSignal · Check offers before changing a price'})

    @app.get('/start',response_class=HTMLResponse)
    def first_run(request:Request):
        return templates.TemplateResponse(request=request,name='first-run.html',context={
            'page':'start','page_title':'See the evidence · ResolveSignal',
            'main_class':'first-run','example':saved_example(store)})

    @app.get('/new',response_class=HTMLResponse)
    def new_investigation(request:Request):
        return templates.TemplateResponse(request=request,name='new.html',context={
            'page':'new','page_title':('Live check' if public_demo else 'New check')+' · ResolveSignal',
            'demo_case':selected_demo_case(store),'selected_source_urls':SELECTED_SOURCE_URLS})

    @app.get('/investigations',response_class=HTMLResponse)
    def investigation_queue(request:Request):
        return templates.TemplateResponse(request=request,name='queue.html',context={
            'page':'queue','page_title':'Price check results · ResolveSignal',
            'reference_groups':[row for row in store.list_batches() if row['label'] in
                                ('More made-up examples','Fresh public-source checks')]})

    @app.get('/cases/{cid}',response_class=HTMLResponse)
    def case_detail(request:Request,cid:str):
        row=store.case(cid)
        if not row:
            return templates.TemplateResponse(request=request,name='not-found.html',status_code=404,context={
                'page':'detail','page_title':'Result not found · ResolveSignal'})
        return templates.TemplateResponse(request=request,name='detail.html',context={
            'page':'detail','page_title':'Result details · ResolveSignal','main_class':'case-page',
            'case_id':row['id'],'batch_id':row['batch_id'],'case_title':row['request'].get('sku') or 'Offer comparison',
            'guided':request.query_params.get('guide')=='1','live_enabled':status()['live_enabled']})

    @app.get('/quality',response_class=HTMLResponse)
    def quality_page(request:Request):return templates.TemplateResponse(request=request,name='quality.html',context={
        'page':'quality','page_title':'Quality lab · ResolveSignal','main_class':'quality'})

    @app.post('/api/quality/evaluate')
    def quality_evaluate():
        from .quality import evaluate
        return evaluate()

    @app.get('/api/quality/dataset')
    def quality_dataset():
        from .quality import corpus
        return corpus()

    @app.post('/api/quality/batch')
    async def quality_batch(request:Request):
        if public_demo:raise HTTPException(403,'Developer scenario batches are unavailable in the public demo. Use the read-only evaluation results.')
        from .quality import corpus
        key=(await request.json()).get('idempotency_key','synthetic-v1')
        if public_demo:key='public-demo-synthetic-v1'
        if not isinstance(key,str) or not 8<=len(key)<=120:raise HTTPException(422,'Invalid idempotency key.')
        bid,new=store.create_batch({'idempotency_key':key,'mode':'synthetic',
            'cases':[{'sku':c['id'],'reference_url':c['offers'][0]['url'],'competitor_url':c['offers'][1]['url']} for c in corpus()['cases']]})
        if new:
            for row in store.batch(bid):launch(row['id'])
        return {'id':bid,'created':new,'kind':'synthetic_sourced_scenarios'}

    @app.post('/api/quality/check/{provider}')
    async def quality_check(provider:str):
        from .providers.quality import LangSmith
        services={'langsmith':LangSmith}
        if provider not in services:raise HTTPException(404,'Unknown provider.')
        return await services[provider]().check()

    @app.post('/api/quality/langsmith/evaluate')
    async def quality_cloud_evaluate():
        from .quality import corpus,run_case,evaluate
        from .providers.quality import LangSmith
        if not status()['langsmith_enabled']:raise HTTPException(409,'Enable LangSmith first.')
        # Hard limit: one corpus pass, no retries, no automatic model judge or inference.
        report=evaluate();receipt=await LangSmith(store=store).record_evaluation(report)
        return {**receipt,'dataset_kind':report['dataset_kind'],'total':report['total'],'passed':report['passed'],
                'notice':'Synthetic rule evaluation, not natural accuracy. Outcomes and counters only uploaded.'}

    @app.get('/api/status')
    def get_status(request:Request):return {**status(),'usage_reserved':store.usage(),
        **({'live_allowance':admission.remaining(request.state.visitor)} if admission else {})}

    @app.get('/api/workflow')
    def workflow_summary():return workflow.public_summary()

    @app.post('/api/settings')
    async def set_settings(request:Request):
        values=await request.json()
        if not isinstance(values,dict):raise HTTPException(422,'Expected settings object.')
        try:save_settings(values)
        except ValueError as e:raise HTTPException(422,str(e))
        return status()

    @app.get('/api/batches')
    def batches():return store.list_batches()

    @app.post('/api/batches')
    async def create_batch(payload:BatchInput,request:Request):
        if public_demo:
            if len(payload.cases)!=1:raise HTTPException(422,'Check one product pair at a time in the shared demo.')
            if payload.mode!='live':raise HTTPException(422,'Use the live check mode for a new public product check.')
            payload.idempotency_key='public-custom-'+hashlib.sha256(payload.idempotency_key.encode()).hexdigest()
        for x in payload.cases:
            try:validate_url(x.reference_url);validate_url(x.competitor_url)
            except ValueError as e:raise HTTPException(422,str(e))
        if payload.mode=='live' and not status()['live_enabled']:raise HTTPException(409,'Enable configured live integrations first.')
        batch_request=payload.model_dump();unique=[];seen=set()
        if public_demo and payload.mode=='live':
            with store.connect() as connection:
                exists=connection.execute('SELECT 1 FROM batches WHERE idem=?',(payload.idempotency_key,)).fetchone()
            if not exists:admit_demo_live(request,'new:'+payload.idempotency_key)
        for row in batch_request['cases']:
            pair=(row['reference_url'],row['competitor_url'])
            if pair not in seen:seen.add(pair);unique.append(row)
        batch_request['cases']=unique
        try:bid,new=store.create_batch(batch_request)
        except ValueError as e:raise HTTPException(409,str(e))
        if new:
            for row in store.batch(bid):launch(row['id'])
        return {'id':bid,'created':new}

    @app.post('/api/cases')
    async def create_case(payload:BatchInput,request:Request):return await create_batch(payload,request)

    @app.post('/api/batches/preview')
    async def preview(request:Request):
        data=await request.json();text=data.get('csv','')
        if not isinstance(text,str) or len(text)>150000:raise HTTPException(422,'CSV is too large.')
        reader=csv.DictReader(io.StringIO(text.lstrip('\ufeff')));rows=[];errors=[]
        if not reader.fieldnames or not {'reference_url','competitor_url'}.issubset(reader.fieldnames):raise HTTPException(422,'CSV requires reference_url and competitor_url columns.')
        for i,row in enumerate(reader,2):
            if len(rows)+len(errors)>=25:raise HTTPException(422,'Maximum 25 rows per batch.')
            try:
                item=CaseInput(**{k:row[k] for k in ('sku','reference_url','competitor_url') if k in row})
                validate_url(item.reference_url,resolve=False);validate_url(item.competitor_url,resolve=False);rows.append(item.model_dump())
            except ValueError as e:errors.append({'row':i,'error':str(e)[:250]})
        return {'cases':rows,'errors':errors,'network_requests':0}

    @app.post('/api/samples')
    async def samples(request:Request):
        key=(await request.json()).get('idempotency_key','sample-review')
        if public_demo:key='public-demo-samples-v1'
        bid,new=store.create_batch({'idempotency_key':key,'mode':'sample','cases':[{'sku':s,'reference_url':'https://example.com/reference','competitor_url':'https://example.com/competitor'} for s in ('comparable','mismatch','unknown')]})
        if new:
            for row in store.batch(bid):launch(row['id'])
        return {'id':bid,'created':new}

    @app.get('/api/batches/{bid}')
    def batch(bid:str):
        rows=store.batch(bid)
        if not rows:raise HTTPException(404,'Batch not found.')
        for row in rows:row['reviews']=store.case(row['id'])['reviews']
        return {'id':bid,'cases':rows}

    @app.get('/api/cases/{cid}')
    def case(cid:str):
        row=store.case(cid)
        if not row:raise HTTPException(404,'Case not found.')
        return row

    @app.post('/api/cases/{cid}/review')
    def review(cid:str,payload:ReviewInput):
        try:store.review(cid,payload.model_dump());return {'saved':True}
        except LookupError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/api/cases/{cid}/refresh')
    async def refresh(cid:str,request:Request):
        if public_demo:
            row=store.case(cid)
            if row and row['revision']>=20:raise HTTPException(429,'This shared demo case has reached its revision limit.')
            if row and row['request']['mode']=='live':
                if row['state'] not in ('completed','partial','failed','cancelled','interrupted'):
                    raise HTTPException(409,'Investigation is already running.')
                admit_demo_live(request,'refresh:'+cid+':'+secrets.token_hex(16))
        try:store.requeue(cid)
        except LookupError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
        launch(cid);return {'queued':True}

    @app.post('/api/cases/{cid}/confirmations')
    def confirm_attributes(cid:str,payload:ConfirmationInput):
        from .confirmations import add
        try:
            revision=store.revise_evidence(cid,payload.revision,lambda result:add(result,payload.model_dump()))
            return {'saved':True,'revision':revision,'source_verification':'operator_attested_not_independently_checked'}
        except LookupError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/api/cases/{cid}/confirmations/{item_id}/withdraw')
    def withdraw_confirmation(cid:str,item_id:str,payload:WithdrawalInput):
        from .confirmations import withdraw
        try:
            revision=store.revise_evidence(cid,payload.revision,lambda result:withdraw(result,item_id,payload.revision,payload.note))
            return {'saved':True,'revision':revision}
        except LookupError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))

    @app.post('/api/cases/{cid}/cancel')
    def cancel(cid:str):
        try:store.cancel(cid)
        except LookupError as e:raise HTTPException(404,str(e))
        except ValueError as e:raise HTTPException(409,str(e))
        return {'cancelled':True}

    @app.get('/api/batches/{bid}/export')
    def export(bid:str,format:str='json'):
        rows=[store.case(x['id']) for x in store.batch(bid)]
        if not rows:raise HTTPException(404,'Batch not found.')
        for row in rows:row['decision_current']=row['state'] in ('completed','partial')
        if format=='json':return Response(json.dumps(rows,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="investigation-{bid[:8]}.json"'})
        if format=='csv':
            out=io.StringIO(newline='');writer=csv.writer(out);writer.writerow(['sku','case_id','revision','mode','outcome','action','gap_percent','reason','review_status','reference_url','competitor_url','evidence_basis','active_operator_confirmations','comparison_scope','scope_note','state','decision_current','retained_outcome'])
            for row in rows:
                result=row['result'] or {};d=result.get('decision',{});reviews=[x for x in row['reviews'] if x['revision']==row['revision']]
                scope=result.get('comparison_scope') or {}
                current=row['decision_current'];reason='; '.join(d.get('reasons',[]))
                if not current:reason='No completed decision for this attempt. Retained evidence: '+reason
                writer.writerow([safe_csv(x) for x in [row['request']['sku'],row['id'],row['revision'],result.get('mode'),d.get('outcome') if current else None,d.get('action') if current else None,d.get('gap_percent') if current else None,reason,(reviews[0]['status'] if reviews else 'unreviewed') if current else 'not_current',row['request']['reference_url'],row['request']['competitor_url'],d.get('evidence_basis','retrieved_only'),str(sum(x['active'] for x in result.get('operator_confirmations',[]))),scope.get('kind'),scope.get('notice'),row['state'],str(current).lower(),d.get('outcome') if not current else None]])
            return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="investigation-{bid[:8]}.csv"'})
        if format=='html':
            return HTMLResponse(templates.get_template('report.html').render(rows=rows),headers={'Content-Disposition':f'attachment; filename="investigation-{bid[:8]}.html"'})
        raise HTTPException(422,'Choose csv, json or html.')
    return app


app=create_app()
