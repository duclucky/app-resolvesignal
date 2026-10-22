import asyncio
import json
import time
import uuid
import re
import httpx
from .schemas import Offer, Evidence
from .compare import compare
from .providers.public_pages import retrieve
from .providers.live import LiveProviders
from .policies import validate_url, comparison_scope, is_selected_source
from .identifiers import canonical_gtin,labeled_gtins

FIELDS=['mpn','gtin','brand','capacity','layout','switch','condition','quantity','price','currency','availability','eligibility','price_basis']


def valid_extraction(value):
    offers=value.get('offers')
    return (isinstance(offers,list) and len(offers)==2 and
            all(isinstance(item,dict) and isinstance(item.get('claims'),dict) and
                all(isinstance(claim,dict) and 'value' in claim and isinstance(claim.get('quote'),str)
                    for claim in item['claims'].values()) for item in offers))


def apply_claims(offer,claims,text):
    """Only apply claimed fields with exact source spans. Never erase conflicts."""
    if any('unselected product variants' in x for x in offer.conflicts):return offer
    if not isinstance(claims,dict):return offer
    for field,item in claims.items():
        if field not in FIELDS or not isinstance(item,dict):continue
        value,quote=item.get('value'),item.get('quote')
        if value is None or not isinstance(quote,str) or len(quote.strip())<2 or quote not in text:continue
        if field in ('layout','switch') and offer.category!='keyboard':continue
        if field=='gtin':
            normalized=canonical_gtin(value)
            if not normalized or normalized not in labeled_gtins(quote):continue
            page_codes=labeled_gtins(text)
            if len(page_codes)!=1 or normalized not in page_codes:continue
            value=str(value)
        if field=='capacity' and offer.category!='ssd':continue
        if field=='layout':
            layout_marker=r'\b(?:ANSI|ISO|JIS|TKL|tenkeyless|full[ -]?size)\b|\b\d{2,3}\s*%'
            if not re.search(layout_marker,str(value),re.I) or not re.search(layout_marker,quote,re.I):continue
        if field=='switch' and offer.seller_sku:
            # Family-wide socket/specification text cannot identify the selected switch.
            normalize=lambda x:re.sub(r'[^a-z0-9]','',str(x).lower())
            if normalize(value) not in normalize(offer.title):continue
        # An existing quote is necessary but does not automatically support its claim.
        markers={'new':r'\bnew\b','refurbished':r'refurb|renewed','open_box':r'open.box','used':r'\bused\b','damaged':r'damaged'}
        if field=='condition' and not re.search(markers.get(value,r'(?!)'),quote,re.I):continue
        if field=='eligibility' and value=='unconditional' and not re.search(r'no membership|regular price|standard price|available to everyone',quote,re.I):continue
        if field=='quantity' and not re.search(r'numberofitems|\bpack\b|\bpackage\b|\b(?:unit|piece)\s*count\b|\b[1-9]\d*\s*(?:units?|pieces?)\b|\b1\s*[xX]\b',quote,re.I):continue
        if field=='mpn':
            if not re.search(r'\bmpn\b|\bmanufacturer[\s_-]*(?:part|model)|\bmodel(?:[\s_-]*(?:number|no\.?))?\s*[:#"\s]',quote,re.I):continue
            if re.sub(r'[^a-z0-9]','',str(value).lower()) not in re.sub(r'[^a-z0-9]','',quote.lower()):continue
        if field=='price':
            try:value=__import__('decimal').Decimal(str(value))
            except Exception:continue
            if not value.is_finite() or value<=0:continue
        if field=='quantity' and (type(value) is not int or value<1):continue
        old=getattr(offer,field)
        if field=='gtin' and old is not None and canonical_gtin(old)==canonical_gtin(value):value=old
        if old is not None and str(old).lower()!=str(value).lower():
            offer.conflicts.append(f'{field} conflicts between structured and page evidence.');continue
        try:setattr(offer,field,value)
        except (ValueError,TypeError):continue
        offer.evidence.append(Evidence(id=uuid.uuid4().hex,url=offer.url,field=field,excerpt=quote,provider='nebius_over_tavily_evidence'))
    return Offer.model_validate(offer.model_dump())


class Investigator:
    def __init__(self,store):self.store=store;self.semaphore=asyncio.Semaphore(2);self.contexts={}

    async def run(self,cid):
        async with self.semaphore:
            request=self.store.case(cid)['request']
            self.contexts[cid]={'mode':request['mode'],'trace':[]}
            scope=comparison_scope(request.get('reference_url'),request.get('competitor_url'))
            if scope:self.contexts[cid]['comparison_scope']=scope
            try:
                async with asyncio.timeout(120):await self._run(cid)
            except TimeoutError:
                self.finish_unresolved(cid,'Investigation timed out.')
            except Exception as exc:
                self.finish_unresolved(cid,str(exc)[:250])
            finally:
                self.contexts.pop(cid,None)
                row=self.store.case(cid)
                if (row and row['result'] and row['state'] in ('completed','partial','failed') and
                    (row['request']['mode']=='live' or
                     (row['request']['mode']=='public' and row['result'].get('comparison_scope',{}).get('kind')!='same_merchant_variant_control'))):
                    from .providers.quality import LangSmith
                    receipt=await LangSmith(store=self.store).record(cid,row['result'])
                    self.store.attach_observation(cid,row['revision'],receipt)

    def finish_unresolved(self,cid,error):
        context=self.contexts[cid]
        result={**context,'decision':{'outcome':'INSUFFICIENT_EVIDENCE','action':'REQUEST_REVIEW',
                'reasons':['Investigation did not finish; retained evidence requires review.']}}
        self.store.finish(cid,result,error,'partial' if context.get('offers') else 'failed')

    def active(self,cid):
        if self.store.case(cid)['state']=='cancelled':raise asyncio.CancelledError()

    async def _run(self,cid):
        row=self.store.case(cid);req=row['request'];start=time.monotonic()
        if req['mode']=='sample':
            from .samples import sample_result
            self.store.finish(cid,sample_result(req['sku']));return
        if req['mode']=='synthetic':
            from .quality import corpus
            from .reference_examples import result_for
            case=next(c for c in corpus()['cases'] if c['id']==req['sku'])
            self.store.finish(cid,result_for(case));return
        live=LiveProviders(self.store) if req['mode']=='live' else None
        if live:
            live.check_active=lambda:self.active(cid)
            self.contexts[cid]['trace']=live.trace
        self.store.update_state(cid,'collecting');offers=[];texts=[];errors=[]
        self.contexts[cid]['source_failures']=errors
        access=[];self.contexts[cid]['source_access']=access
        if live:
            # This source is retrieved directly under its shared rate gate, not by a remote extractor.
            provider_urls=[req[key] for key in ('reference_url','competitor_url') if not is_selected_source(req[key])]
            try:extracted=await live.extract(provider_urls) if provider_urls else {}
            except ValueError:
                extracted={};errors.append('Tavily initial extraction unavailable; public-page fallback attempted.')
            for key in ['reference_url','competitor_url']:
                self.active(cid)
                url=req[key];validate_url(url)
                found=next((x for x in extracted.get('results',[]) if x['url']==url),None)
                text=found.get('raw_content','') if found else ''
                o=Offer(url=url)
                # Preserve selected-variant structured data that text extraction drops.
                page_start=time.monotonic()
                try:
                    structured,visible=await retrieve(url)
                    o=structured
                    live.trace.append({'provider':'public_page','status':'ok','elapsed_ms':round((time.monotonic()-page_start)*1000),
                                       'selected_variant_structured':bool(o.price is not None),'gtin_validated':bool(o.gtin)})
                    selected='\n'.join(e.excerpt for e in o.evidence)
                    text=selected+'\n'+(text or visible)
                    access.append({'url':url,'status':'readable','method':'direct'})
                except (ValueError,OSError,httpx.HTTPError) as exc:
                    status=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None
                    access.append({'url':url,'status':'blocked' if status in (401,403,429) else 'unavailable','http_status':status,
                                   'fallback_text_available':bool(text)})
                    live.trace.append({'provider':'public_page','status':'unavailable','elapsed_ms':round((time.monotonic()-page_start)*1000)})
                if not text:errors.append('No readable offer evidence: '+url)
                # Limit boilerplate while preserving source order and exact quote substrings.
                lines=text.splitlines();signals=[i for i,line in enumerate(lines) if re.search(r'^# |model|MFR|MPN|SKU|GTIN|price|\$|condition|stock|quantity|pack|keyboard|SSD|member|rebate',line,re.I)]
                indexes=set()
                for i in signals:
                    indexes.update(range(max(0,i-1),min(len(lines),i+3)))
                text='\n'.join(lines[i] for i in sorted(indexes))[:6000] or text[:6000]
                heading=next((line.lstrip('# ').strip() for line in lines if line.startswith('# ')),None)
                o.title=o.title or (heading or text[:140]).strip()
                if re.search(r'\bSSD\b|solid.state',o.title,re.I):o.category='ssd'
                elif re.search(r'keyboard',o.title,re.I):o.category='keyboard'
                else:o.category='general'
                offers.append(o);texts.append(text)
                self.contexts[cid]['offers']=[item.model_dump(mode='json') for item in offers]
        else:
            for key in ['reference_url','competitor_url']:
                self.active(cid);url=req[key];validate_url(url)
                try:o,text=await retrieve(url)
                except Exception:
                    o,text=Offer(url=url),' '
                    errors.append('Public page could not be retrieved: '+url)
                offers.append(o);texts.append(text)
                self.contexts[cid]['offers']=[item.model_dump(mode='json') for item in offers]
        self.contexts[cid]['offers']=[o.model_dump(mode='json') for o in offers]
        research=[]
        if live:
            self.store.update_state(cid,'investigating')
            # The model specifies a bounded evidence question. Only approved tools run.
            scope=await live.reason('Given two retail pages, return {"query": "one short manufacturer/model or offer-terms search question", "missing_fields": ["fields"]}. Use observed model/name. If unavailable, ask about the URL product. Pages:\n'+json.dumps([{'url':o.url,'title':o.title,'content':t[:3000]} for o,t in zip(offers,texts)],ensure_ascii=False),max_tokens=400,
                                    validator=lambda value:isinstance(value.get('query'),str))
            query=scope.get('query')
            if isinstance(query,str) and query.strip():
                self.active(cid)
                try:search=await live.search(query[:250])
                except ValueError:
                    search={};errors.append('Tavily follow-up search unavailable; retailer evidence retained.')
                research=[{'url':x['url'],'title':x.get('title'),'discovery_snippet':x.get('content','')[:800]} for x in search.get('results',[])]
                approved=[]
                for item in research:
                    try:
                        validate_url(item['url'])
                        if not is_selected_source(item['url']):approved.append(item['url'])
                    except ValueError:continue
                if approved:
                    try:
                        extra=await live.extract(approved[:2]);research=[{'url':x['url'],'content':x['raw_content'][:4000]} for x in extra.get('results',[])]
                    except ValueError:errors.append('Tavily follow-up extraction unavailable; search snippets remain discovery only.')
                self.contexts[cid]['research']=research
            self.active(cid)
            from .prompts import extraction_prompt
            prompt=extraction_prompt(offers,texts,research)
            if hasattr(live,'fits_input') and not live.fits_input(prompt):
                for page_limit,research_limit in ((4000,1500),(2500,500),(1000,0)):
                    prompt=extraction_prompt(offers,texts,research,page_limit=page_limit,research_limit=research_limit)
                    if live.fits_input(prompt):
                        live.trace.append({'provider':'agent','status':'input_reduced',
                                           'page_character_limit':page_limit,'research_character_limit':research_limit})
                        break
            answer=await live.reason(prompt,max_tokens=2600,validator=valid_extraction)
            if not valid_extraction(answer):raise ValueError('Invalid two-offer model schema.')
            for i,item in enumerate(answer['offers']):offers[i]=apply_claims(offers[i],item.get('claims',{}),texts[i])
            summary=f'Collected {sum(len(o.evidence) for o in offers)} validated retailer source spans. Only supported fields contribute to the decision.'
        else:summary='Public structured-page inspection only. NVIDIA and Tavily were not called.'
        self.active(cid);self.store.update_state(cid,'validating');d=compare(*offers)
        scope=self.contexts[cid].get('comparison_scope')
        self.store.finish(cid,{'mode':req['mode'],**({'comparison_scope':scope} if scope else {}),'offers':[o.model_dump(mode='json') for o in offers],
            'decision':d.model_dump(),'summary':summary,'research':research,'trace':live.trace if live else [],
            'elapsed_seconds':round(time.monotonic()-start,2),'source_failures':errors,'source_access':access},
            None if not errors else 'Some public retrievals failed; inspect evidence.',state='partial' if errors else 'completed')
