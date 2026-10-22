const q=s=>document.querySelector(s);const providerChecks={};
const node=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text;if(cls)n.className=cls;return n;};
async function refreshWorkflow(){
  const response=await fetch('/api/workflow');if(!response.ok)throw Error('Service activity could not be loaded.');
  const data=await response.json(),container=q('#provider-workflow');container.replaceChildren();
  const names={nebius:'NVIDIA / Nebius',tavily:'Tavily',langsmith:'LangSmith'};
  const states={verified:'Saved activity verified',awaiting_live_run:'Awaiting a live investigation',awaiting_trace:'Awaiting verified trace'};
  for(const [key,item] of Object.entries(data.providers)){
    const card=node('article','','case');card.append(node('h3',names[key]),node('p',item.role),node('strong',states[item.status]||String(item.status).replaceAll('_',' ')));
    if(item.verified_steps)card.append(node('p',`${item.verified_steps} successful provider step${item.verified_steps===1?"":"s"} in the latest saved evidence.`,'help'));
    if(item.verified_runs)card.append(node('p',`${item.verified_runs} trace${item.verified_runs===1?"":"s"} verified through LangSmith readback.`,'help'));
    if(!item.configured)card.append(node('p','Server connection not configured.','help'));
    container.append(card);
  }
  q('#workflow-notice').textContent=data.notice;

}
q('#refresh-workflow').onclick=()=>refreshWorkflow().catch(error=>q('#workflow-notice').textContent=error.message);
refreshWorkflow().catch(error=>q('#workflow-notice').textContent=error.message);
async function post(path,body={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'Please check your input.');return data;}
async function busy(button,status,work){button.disabled=true;status.textContent='Working…';try{await work();}catch(e){status.textContent=e.message;}finally{button.disabled=false;}}
q('#evaluate').onclick=()=>busy(q('#evaluate'),q('#local-status'),async()=>{const report=await post('/api/quality/evaluate');q('#local-status').textContent=`${report.passed}/${report.total} synthetic regression cases passed. No live provider calls.`;q('#evaluation-results').hidden=false;q('#quality-summary').hidden=false;q('#quality-summary').replaceChildren();for(const [n,label] of [[report.total,'Scenarios'],[report.passed,'Passed'],[report.false_comparable,'False comparable']]){const item=node('div',label);item.prepend(node('b',String(n)));q('#quality-summary').append(item);}q('#quality-results').replaceChildren();for(const row of report.cases){const item=node('details','','case');item.append(node('summary',`${row.passed?'PASS':'FAIL'} · ${row.id}`),node('p',row.description),node('p',`${row.actual.outcome} · ${row.actual.action}`),node('p',`Authored target: ${row.expected.outcome} · ${row.expected.action}`,'help'));for(const source of row.sources){const link=node('a',source.basis);link.href=source.url.startsWith('https://')?source.url:'/api/quality/dataset';link.target='_blank';link.rel='noopener noreferrer';const p=node('p','');p.append(link);item.append(p);}q('#quality-results').append(item);}});
if(q('#open-batch'))q('#open-batch').onclick=()=>busy(q('#open-batch'),q('#local-status'),async()=>{const r=await post('/api/quality/batch',{idempotency_key:crypto.randomUUID()});localStorage.setItem('activeBatch',r.id);q('#local-status').textContent='Synthetic cases created. Opening the review workspace.';location.href='/investigations?batch='+encodeURIComponent(r.id);});
for(const button of document.querySelectorAll('.check-provider'))button.onclick=()=>busy(button,q('#provider-status'),async()=>{const r=await post('/api/quality/check/'+button.dataset.provider);providerChecks[button.dataset.provider]=r.status;q('#provider-status').textContent=Object.entries(providerChecks).map(([name,status])=>name+': '+status).join(' · ')+(r.message?' · '+r.message:'');});
if(q('#cloud-eval'))q('#cloud-eval').onclick=()=>busy(q('#cloud-eval'),q('#cloud-status'),async()=>{const r=await post('/api/quality/langsmith/evaluate');q('#cloud-status').textContent=`${r.uploaded}/${r.total} stored traces verified. Synthetic evaluation: ${r.passed}/${r.total}.`+(r.uploaded<r.total?' Upload stopped; check provider access.':'');});
(async()=>{if(!q('#provider-status'))return;const s=await(await fetch('/api/status')).json();q('#provider-status').textContent=['langsmith'].map(p=>`${p}: ${s[p+'_configured']?'key configured':'not configured'}`).join(' · ');q('#cloud-eval').disabled=!s.langsmith_configured||!s.langsmith_enabled||s.external_actions_enabled===false;if(s.external_actions_enabled===false){for(const button of document.querySelectorAll('.check-provider'))button.disabled=true;q('#provider-status').textContent+=' · Quality operations require the owner. Live trace status is shown above.';}})().catch(e=>{if(q('#provider-status'))q('#provider-status').textContent=e.message;});

