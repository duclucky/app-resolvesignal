const $ = selector => document.querySelector(selector);
const UI = window.InvestigationUI;
const page = document.body.dataset.page;
const caseId = document.body.dataset.caseId;
const query = new URLSearchParams(location.search);
let activeBatch = '', timer = null, previewRows = [], signature = '', filter = 'all';
const drafts = new Map(), expanded = new Set(), revealed = new Set();
const labels = {mpn:'Part number (MPN)',gtin:'Product barcode (GTIN)',seller_sku:'Store product code',capacity:'Capacity',layout:'Layout',switch:'Switch',condition:'Condition',quantity:'Pack quantity',availability:'Availability',eligibility:'Price conditions'};
const el = (tag, text, cls) => {const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const human = value => value == null ? 'Unknown' : String(value).replaceAll('_',' ');
const stamp = value => {const date=new Date(value);return value && !Number.isNaN(date.valueOf()) ? date.toLocaleString(undefined,{timeZoneName:'short'}) : 'Time not available';};
const sourceLabel = url => {try {const u=new URL(url);return u.hostname+u.pathname;}catch{return 'Source';}};
function link(text,url){const a=el('a',text);a.href=url;a.target='_blank';a.rel='noopener noreferrer';return a;}
function message(text,error=false){$('#message').textContent=text;$('#message').className=error?'error':'';$('#message').setAttribute('role',error?'alert':'status');}
async function api(path,body){
  let response;
  try {response=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});}
  catch {throw Error('Could not connect. Check your connection and try again.');}
  let data;try {data=await response.json();}catch {throw Error('We could not complete this request. Please try again.');}
  if(response.status===409&&path.endsWith('/review'))throw Error('This result changed or is still running. Copy your note, reload the result, then review the latest version.');
  if(!response.ok){
    const detail=typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.slice(0,2).map(item=>item.msg).join(' '):'Please check the input and try again.';
    const descriptions={
      'Case not found.':'Result not found. Open Results to choose another result.',
      'Batch not found.':'Result group not found. Choose another group in Results.',
      'Investigation is already running.':'A check is already running. Open the current result to see progress.',
      'Only an active investigation can be cancelled.':'This check has already stopped. Reload the result to see its status.',
      'The shared demo allows three live investigations per hour. Samples remain available.':'The shared demo has reached its hourly limit. View a saved result or try made-up examples.',
      'This shared demo case has reached its revision limit.':'This result has reached its limit for new versions. You can still view its saved evidence.',
      'Enable configured live integrations first.':'Live checks are turned off. You can still view saved results or try made-up examples.'};
    const error=Error(descriptions[detail]||detail);error.details=data.detail;throw error;
  }
  return data;
}
async function batchList(){
  const rows=await api('/api/batches'),select=$('#batches');
  const option=el('option','Choose a group');option.value='';option.disabled=Boolean(activeBatch);select.replaceChildren(option);
  for(const row of rows){const title=row.mode==='sample'?'Made-up examples':row.label==='Investigation'?'Price checks':row.label||'Price checks';const o=el('option',`${title} · ${row.case_count??'?'} ${row.case_count===1?'result':'results'} · ${stamp(row.created)}`);o.value=row.id;select.append(o);}select.value=activeBatch;return rows;
}
function queueURL(id,view='all'){
  const params=new URLSearchParams({batch:id});if(view!=='all')params.set('filter',view);
  return '/investigations?'+params;
}
function navigateToBatch(id){localStorage.setItem('activeBatch',id);location.assign(queueURL(id));}
async function openBatch(id){
  if(timer)clearTimeout(timer);activeBatch=id;signature='';
  localStorage.setItem('activeBatch',id);history.replaceState(null,'',queueURL(id,filter));
  await renderBatch(true);await batchList();message('');
}
function poll(running){if(timer)clearTimeout(timer);timer=running?setTimeout(()=>renderBatch().catch(error=>message(error.message,true)),1400):null;}
function preserveDetails(details,key){details.open=expanded.has(key);details.addEventListener('toggle',()=>details.open?expanded.add(key):expanded.delete(key));return details;}
function offerCard(offer,label,full=false){
  const card=el('section',undefined,'offer');card.setAttribute('aria-label',label);
  card.append(el('small',label),el('h3',UI.offerTitle(offer)),link(sourceLabel(offer.url),offer.url));
  const displayPrice=offer.price!=null&&Number.isFinite(Number(offer.price))?`${offer.currency||''} ${Number(offer.price).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`.trim():'Price unknown';
  const price=el('div',undefined,'price-row');price.append(el('span',displayPrice,'price'),el('span','listed price'));card.append(price);
  card.append(el('p',human(offer.availability),`stock-label ${['out_of_stock','preorder','backorder'].includes(offer.availability)?'unavailable':''}`));
  if(!full){const facts=['capacity','layout','switch','condition'].filter(field=>offer[field]!=null).map(field=>String(offer[field]));if(facts.length)card.append(el('p',facts.join(' · '),'offer-key-facts'));card.append(el('p','Last checked '+stamp(offer.observed_at),'evidence-meta'));return card;}
  const dl=el('dl');
  for(const field of ['mpn','gtin','seller_sku','capacity','layout','switch','condition','quantity','eligibility']){
    if(['layout','switch'].includes(field)&&offer.category!=='keyboard')continue;
    if(field==='capacity'&&offer.category!=='ssd')continue;
    const confirmed=(offer.evidence||[]).some(e=>e.field===field&&e.origin==='operator_confirmed');
    dl.append(el('dt',labels[field]),el('dd',human(offer[field])+(confirmed?' · user-confirmed':''),offer[field]==null?'unknown-value':''));
  }
  card.append(dl,el('p','Last checked '+stamp(offer.observed_at),'evidence-meta'));return card;
}
function stepper(row){
  const list=el('ol',undefined,'workflow-steps');list.setAttribute('aria-label','Check progress');
  UI.steps(row).forEach((stage,index)=>{const item=el('li',undefined,stage.state);if(stage.state==='current')item.setAttribute('aria-current','step');const number=el('span',String(index+1),'stage-number');number.setAttribute('aria-hidden','true');item.append(number,el('span',stage.label));const sr=el('span',` (${stage.state})`,'sr-only');item.append(sr);list.append(item);});return list;
}
function fullEvidencePanel(row,result){
  const details=preserveDetails(el('details'),row.id+':all-evidence');const count=(result.offers||[]).reduce((n,o)=>n+(o.evidence||[]).length,0);
  details.id='all-evidence-'+row.id;
  details.append(el('summary',`All source quotes · ${count}`));
  for(const offer of result.offers||[])for(const evidence of offer.evidence||[]){
    const item=el('div',undefined,'evidence');item.append(el('strong',labels[evidence.field]||human(evidence.field)),el('blockquote',evidence.excerpt),link(sourceLabel(evidence.url),evidence.url));
    item.append(el('div',evidence.origin==='operator_confirmed'?`User-confirmed by ${evidence.confirmed_by} · ${stamp(evidence.confirmed_at)} · Source not independently checked`:`${human(evidence.provider)} · ${stamp(evidence.retrieved_at)}`,'evidence-meta'));details.append(item);
  }
  if(result.refresh_comparison){const change=result.refresh_comparison;details.append(el('h4',`Changes since version ${change.previous_revision}`),el('p',change.basis),el('p',`Result: ${UI.outcomeLabel(change.previous_outcome)} → ${UI.outcomeLabel(change.current_outcome)}`));
    if(!change.complete_pair)details.append(el('p','Incomplete refresh evidence. Offer changes could not be established.'));
    else if(!change.fields.length)details.append(el('p','No changes in compared retrieved attributes. Missing facts can remain unresolved.'));
    else for(const item of change.fields)details.append(el('p',`${UI.offerLabel(item.side)} · ${labels[item.field]||human(item.field)}: ${human(item.before)} → ${human(item.after)}`));
  }
  if(result.summary)details.append(el('p',result.summary));
  for(const step of result.trace||[])details.append(el('p',`${step.provider} · ${step.status}${typeof step.elapsed_ms==='number'?' · '+step.elapsed_ms+' ms':''}${step.model?' · '+step.model:''}${step.delay_seconds!==undefined?' · wait '+step.delay_seconds+' s':''}${step.page_character_limit?' · source context reduced':''}`,'help'));
  for(const source of result.research||[])details.append(link(source.title||sourceLabel(source.url),source.url));
  return details;
}
function historyPanel(row,includeCurrent=false){
  const details=preserveDetails(el('details'),row.id+':history');details.append(el('summary',`${includeCurrent?"Saved":"Earlier"} result versions · ${includeCurrent?row.revision:row.revision-1}`));let loaded=false;
  async function load(){if(!details.open||loaded)return;loaded=true;try{const full=await api('/api/cases/'+row.id);
    for(const previous of full.history.filter(item=>includeCurrent||item.revision<row.revision)){
      details.append(el('h4',`Version ${previous.revision} · ${UI.outcomeLabel(previous.result.decision?.outcome)}`),el('p',stamp(previous.created),'help'));
      for(const claim of previous.result.operator_confirmations||[]){details.append(el('p',`${UI.offerLabel(claim.side)} · ${labels[claim.field]||human(claim.field)} = ${claim.value} · ${claim.active?'Active in this version':'Withdrawn'} · ${claim.confirmed_by} (self-reported)`),el('blockquote',claim.excerpt),link(sourceLabel(claim.source_url),claim.source_url));}
      for(const review of full.reviews.filter(item=>item.revision===previous.revision))details.append(el('p',`${UI.reviewLabel(review.status)}: ${review.note}`,'review-status'));
    }
  }catch(error){details.append(el('p',error.message,'error'));loaded=false;}}
  details.addEventListener('toggle',load);if(details.open)load();return details;
}
function reviewPanel(row){
  const saved=UI.currentReview(row),key=`${row.id}:${row.revision}`,draft=drafts.get(key)||{status:saved?.status||'reviewed',note:saved?.note||''};
  const panel=el('form',undefined,'review-panel');panel.id='review-'+row.id;panel.tabIndex=-1;panel.append(el('h3','Your review'),el('p','Choose a review status, add an optional note, then save. This records your review; it does not change a price.','review-help'),el('p',saved?`Review saved for this version · ${UI.reviewLabel(saved.status)}`:'No review saved for this version.','review-status'));
  const note=el('textarea');note.id=`${row.id}-review-note`;note.placeholder='What did you check, and what should happen next?';note.value=draft.note;note.maxLength=2000;
  const label=el('label','Review note (optional)');label.htmlFor=note.id;panel.append(label,note);
  if($('.demo-notice'))panel.append(el('p','Demo reviews are public. Do not enter private information.','help'));
  const controls=el('div',undefined,'review-row'),select=el('select');select.id=`${row.id}-review-status`;const statusLabel=el('label','Review status');statusLabel.htmlFor=select.id;panel.append(statusLabel);
  for(const value of ['reviewed','disputed','follow_up']){const option=el('option',UI.reviewLabel(value));option.value=value;select.append(option);}select.value=draft.status;
  const remember=()=>{
    drafts.set(key,{status:select.value,note:note.value});
    const changed=note.value!==(saved?.note||'')||select.value!==(saved?.status||'reviewed');
    feedback.setAttribute('role','status');
    feedback.textContent=changed?`You have unsaved changes. Click ${saved?'Update review':'Save review'} to save them.`:saved?'Review saved. You can update it or return to Results.':'Your review is saved only when you click Save review.';
  };note.addEventListener('input',remember);select.addEventListener('change',remember);
  const save=el('button',saved?'Update review':'Save review','secondary');save.type='submit';save.id=`${row.id}-save-review`;controls.append(select,save);panel.append(controls);
  const feedback=el('p',saved?'Review saved. You can update it or return to Results.':'Your review is saved only when you click Save review.','review-feedback');feedback.id=`${row.id}-review-feedback`;feedback.tabIndex=-1;feedback.setAttribute('role','status');panel.append(feedback);
  if(draft.note!==(saved?.note||'')||draft.status!==(saved?.status||'reviewed'))remember();
  if(saved){const back=el('a','Back to results →','text-button review-back');back.href=$('#back-to-queue').getAttribute('href');panel.append(back);}
  panel.onsubmit=async event=>{event.preventDefault();save.disabled=true;save.textContent='Saving…';try{await api(`/api/cases/${row.id}/review`,{revision:row.revision,status:select.value,note:note.value});drafts.delete(key);await renderBatch(true);message('Review saved. If you run a new check, review the new version too.');document.getElementById(feedback.id)?.focus({preventScroll:true});}catch(error){feedback.textContent=error.message;feedback.setAttribute('role','alert');message(error.message,true);save.disabled=false;save.textContent=saved?'Update review':'Save review';}};
  return panel;
}
function decisionSummary(row){
  const brief=UI.decisionBrief(row);if(!brief)return null;
  const box=el('section',undefined,'decision-summary');box.id='decision-summary';box.tabIndex=-1;
  box.setAttribute('aria-labelledby','decision-summary-title');
  const heading=el('h2',brief.title);heading.id='decision-summary-title';
  if(['sample','synthetic'].includes(row.result.mode))box.append(el('p','MADE-UP EXAMPLE · NOT LIVE PRICES','sample-warning'));
  if(row.result.decision.evidence_basis==='operator_assisted')box.append(el('p','INCLUDES USER-CONFIRMED DETAILS · NOT INDEPENDENTLY VERIFIED','operator-warning'));
  box.append(el('p','WHAT TO DO NEXT','eyebrow'),heading,el('p',brief.reason,'decision-why'),el('p',brief.instruction,'decision-next'));
  const links=el('div',undefined,'decision-links'),quotes=el('a','1. Check the evidence ↓','secondary');quotes.href='#evidence-'+row.id;
  quotes.onclick=()=>{const details=document.getElementById('evidence-'+row.id);if(details){details.open=true;expanded.add(row.id+':evidence');}};
  const review=el('a','2. Write your review ↓','text-button');review.href='#review-'+row.id;
  links.append(quotes,review);box.append(links);
  if(row.result.decision.unknown?.length){const facts=UI.missingFacts(row.result.decision.unknown);const missing=el('details',undefined,'missing-fields');missing.append(el('summary',`Missing details · ${facts.length}`));const list=el('ul');for(const fact of facts)list.append(el('li',fact));missing.append(list);box.append(missing);}
  return box;
}
function recoveryPanel(row){
  const plan=UI.recoveryPlan(row);if(!plan.length)return null;
  const panel=el('section',undefined,'recovery-panel');panel.setAttribute('aria-label','How to complete this check');panel.append(el('h3','How to complete this check'));
  const list=el('ol');for(const step of plan){const item=el('li');item.append(el('strong',step.title),el('p',step.instruction,'help'));if(step.url)item.append(link('Open this source page ↗',step.url));list.append(item);}panel.append(list);
  const actions=el('div',undefined,'decision-links'),input=el('a','Try different product links →','secondary');input.href='/new';const review=el('a','Save what needs checking ↓','text-button');review.href='#review-'+row.id;actions.append(input,review);panel.append(actions);return panel;
}
function selectedEvidencePanel(row,result){
  const details=preserveDetails(el('details'),row.id+':evidence');details.id='evidence-'+row.id;
  const quotes=UI.supportingQuotes(result);details.append(el('summary',`Source evidence · ${quotes.length} quotes`),el('p',UI.currentDecision(row)?'These excerpts support the result. Open a source link to check the original page.':'These excerpts are from an older result. They do not confirm the outcome of this attempt.','help'));
  for(const {offer,evidence} of quotes){const item=el('div',undefined,'evidence');item.append(el('strong',(offer===result.offers[0]?'Offer A':'Offer B')+' · '+(labels[evidence.field]||human(evidence.field))),el('blockquote',evidence.excerpt),link(sourceLabel(evidence.url),evidence.url));
    item.append(el('p',evidence.origin==='operator_confirmed'?`User-confirmed · ${stamp(evidence.confirmed_at)} · Source not independently checked`:`Last checked ${stamp(evidence.retrieved_at||offer.observed_at)}`,'evidence-meta'));details.append(item);}
  if(!quotes.length)details.append(el('p','No source quotes are available for this result. Check the missing details before acting.'));
  details.append(el('p','All quotes, service calls and earlier results are in More details below.','help'));return details;
}
function caseCard(row){
  const card=el('article',undefined,'case'),result=row.result,decision=result?.decision||{},currentDecision=UI.currentDecision(row),terminal=UI.terminal(row);card.dataset.caseId=row.id;card.setAttribute('aria-labelledby','case-title');
  $('#case-title').textContent=UI.caseTitle(row);
  $('#case-intro').textContent=!terminal?'The check is running. Wait for the result, or stop this check.':!currentDecision?'This check did not finish. Read any saved evidence, then run the check again.':row.state==='partial'?'Some parts of this check did not finish. Check the missing details, then save a review with what still needs checking.':'See why these offers can or cannot be compared. Check the evidence, then save your review below.';
  const header=el('div',undefined,'case-head');
  const resultLabel=UI.outcomeLabel(currentDecision?.outcome)+(currentDecision?.outcome==='COMPARABLE_LISTED_PRICE'&&decision.evidence_basis==='operator_assisted'?' · user-confirmed':'');
  const tone=currentDecision?.outcome==='COMPARABLE_LISTED_PRICE'&&decision.evidence_basis!=='operator_assisted'?'good':currentDecision?.outcome==='NOT_COMPARABLE'?'bad':'unknown';
  const outcome=currentDecision?(row.state==='partial'?'Partly complete · ':'')+resultLabel:terminal?UI.stateLabel(row.state):(row.revision?'Checking again':'Check in progress');
  header.append(el('span',outcome,'badge '+(terminal&&row.state!=='partial'?tone:'unknown')),
    el('span',currentDecision?'Saved result':terminal?'Try this check again':'Please wait','case-meta'));card.append(header);
  const brief=decisionSummary(row);if(brief)card.append(brief);
  const recovery=recoveryPanel(row);if(recovery)card.append(recovery);
  if(row.error)card.append(el('p',row.error,'sample-warning'));
  if(result?.mode==='synthetic'&&result.learning_note)card.append(el('p',result.learning_note,'help'));
  if(!terminal)card.append(stepper(row),el('p',row.revision?'Checking the sources again. The older result below is not the result of this new check.':'Reading the sources. You can review the result when the check finishes.','pending-note'));
  if(result){
    if(!currentDecision)card.append(el('p',`Older saved evidence · Version ${row.revision}. This is not a new completed result. Do not act on the older evidence.`,'sample-warning'));
    const scope=result.comparison_scope;
    if(scope)card.append(el('p',scope.kind==='same_merchant_variant_control'?'Both offers are from the same store. This check compares product versions, not competing stores.':scope.notice,'scope-notice'));
    if(!currentDecision&&['sample','synthetic'].includes(result.mode))card.append(el('p','MADE-UP EXAMPLE · NOT LIVE PRICES','sample-warning'));
    if(!currentDecision&&decision.evidence_basis==='operator_assisted')card.append(el('p','INCLUDES USER-CONFIRMED DETAILS · NOT INDEPENDENTLY VERIFIED','operator-warning'));
    if(currentDecision&&decision.gap_percent!=null)card.append(el('p',`${decision.gap_percent}% listed-price difference`,'case-reason'));
    if(result.offers?.length){const comparison=el('div',undefined,'comparison');result.offers.forEach((offer,index)=>comparison.append(offerCard(offer,index?'Offer B':'Offer A')));card.append(comparison);}
    card.append(selectedEvidencePanel(row,result));
    if(currentDecision)card.append(reviewPanel(row));
    const controls=el('div',undefined,'case-actions');
    if(terminal){const refresh=el('button',['sample','synthetic'].includes(result.mode)?'Run example again':'Run a new check','text-button');refresh.type='button';if(result.mode==='live'&&document.body.dataset.liveEnabled==='false')refresh.disabled=true;refresh.onclick=async()=>{refresh.disabled=true;try{await api(`/api/cases/${row.id}/refresh`,{});signature='';await renderBatch(true);message('New check started. Your earlier review stays with the older result.');}catch(error){message(error.message,true);refresh.disabled=false;}};controls.append(refresh,el('p',['sample','synthetic'].includes(result.mode)?'Runs this made-up example again. No live product prices are fetched.':'Gets a new result. Your current review stays with this saved version.','help'));if(result.mode==='live')controls.append(el('p',document.body.dataset.liveEnabled==='false'?'Live checks are disabled on this profile.':'Uses provider credits within the demo limits.','help'));}
    else controls.append(cancelButton(row));
    card.append(controls);
    const advanced=preserveDetails(el('details',undefined,'advanced-details'),row.id+':advanced');advanced.append(el('summary','More details'),el('p','Optional: all product details, source quotes, service calls, confirmed details and earlier results.','help'),el('p',`Saved version ${row.revision} · ${UI.stateLabel(row.state)} · Result ID ${row.id}`,'case-meta'));
    const allOffers=preserveDetails(el('details'),row.id+':all-attributes');allOffers.append(el('summary','All product details'));const complete=el('div',undefined,'comparison');(result.offers||[]).forEach((offer,index)=>complete.append(offerCard(offer,index?'Offer B':'Offer A',true)));allOffers.append(complete);advanced.append(allOffers,fullEvidencePanel(row,result));
    const confirmation=confirmationPanel(row,()=>renderBatch(true));if(confirmation){preserveDetails(confirmation,row.id+':confirmations');advanced.append(confirmation);}
    if(row.revision>1||(!currentDecision&&row.revision>0))advanced.append(historyPanel(row,!currentDecision));
    if(decision.caveats?.length)advanced.append(el('p',decision.caveats.join(' '),'case-caveat'));
    advanced.append(el('p',result.mode==='live'?'This saved result used live services. Their call records are listed above.':['sample','synthetic'].includes(result.mode)?'Made-up offers. This example did not fetch live prices or call an AI model.':'This result read public pages without calling Tavily or a Nebius model.','help'));card.append(advanced);
  }else if(!terminal)card.append(cancelButton(row));
  else {const retry=el('button','Try this check again','text-button');retry.onclick=async()=>{try{await api(`/api/cases/${row.id}/refresh`,{});await renderBatch(true);}catch(error){message(error.message,true);}};card.append(retry);}
  return card;
}
function cancelButton(row){const button=el('button','Stop this check','text-button');button.type='button';button.onclick=async()=>{button.disabled=true;try{await api(`/api/cases/${row.id}/cancel`,{});await renderBatch(true);message('Check stopped. The evidence collected so far is kept in More details.');}catch(error){message(error.message,true);button.disabled=false;}};return button;}
function queueCard(row){
  const card=el('article',undefined,'queue-card'),left=el('div',undefined,'queue-card-main');
  const title=el('h3'),a=el('a',UI.caseTitle(row));
  const params=new URLSearchParams();if(filter!=='all')params.set('filter',filter);
  a.href='/cases/'+encodeURIComponent(row.id)+(params.size?'?'+params:'');title.append(a);
  left.append(el('p',UI.stateLabel(row.state),'case-meta'),title);
  const decision=UI.currentDecision(row),finished=UI.terminal(row);
  const stopped=['failed','cancelled','interrupted'].includes(row.state);
  let outcome=decision?UI.outcomeLabel(decision.outcome):UI.stateLabel(row.state);
  if(row.state==='partial')outcome='Partly complete · '+UI.outcomeLabel(decision?.outcome);
  const tone=stopped||row.state==='partial'?'unknown':decision?.outcome==='NOT_COMPARABLE'?'bad':decision?.outcome==='COMPARABLE_LISTED_PRICE'?'good':'unknown';
  const meta=el('div',undefined,'queue-card-status');meta.append(el('span',outcome,'badge '+tone),el('span',stopped?'Run this check again':UI.currentReview(row)?'Review saved · '+UI.reviewLabel(UI.currentReview(row).status):finished?'Not reviewed yet':'In progress','queue-review'));
  const notice=['sample','synthetic'].includes(row.result?.mode)?'Made-up example · not live prices':row.result?.comparison_scope?.kind==='same_merchant_variant_control'?'Different versions sold by the same store':row.result?.comparison_scope?'Offers from the same store':row.request.mode==='live'?'Live source check':'Product page check';
  left.append(el('p',row.error||(decision?.reasons?.[0]?UI.readableReason(decision.reasons[0]):null)||(row.result&&!decision?'Older evidence is saved, but this check has no new completed result.':'Open this result to see the available evidence.'),'queue-reason'),el('p',notice,'queue-source'));
  const open=el('a','Open result →','secondary queue-open');open.href=a.href;open.setAttribute('aria-label','Open result: '+UI.caseTitle(row));meta.append(open);
  card.append(left,meta);return card;
}
async function renderBatch(force=false){
  if(page!=='detail'&&!activeBatch)return;
  if(!force&&document.activeElement?.closest('.case')&&['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){poll(true);return;}
  if(timer)clearTimeout(timer);
  const requested=activeBatch;
  const payload=await api(page==='detail'?'/api/cases/'+encodeURIComponent(caseId):'/api/batches/'+encodeURIComponent(requested));
  if(requested!==activeBatch)return;
  const rows=page==='detail'?[payload]:payload.cases;
  const running=rows.some(row=>!UI.terminal(row)),next=filter+'|'+JSON.stringify(payload);
  if(!force&&next===signature){poll(running);return;}signature=next;
  const focus=document.activeElement?.id,selection=document.activeElement?.selectionStart;
  $('#cases').replaceChildren();const shown=page==='detail'?rows:UI.filterCases(rows,filter);
  for(const row of shown)$('#cases').append(page==='detail'?caseCard(row):queueCard(row));
  if(!shown.length)$('#cases').append(el('p','No results match this filter. Choose All results to see the whole group.','pending-note'));
  if(page==='queue'){
    const counts=UI.decisionCounts(rows);
    $('#summary').hidden=false;$('#summary').replaceChildren();
    for(const key of ['COMPARABLE_LISTED_PRICE','NOT_COMPARABLE','INSUFFICIENT_EVIDENCE']){if(!counts[key])continue;const item=el('div',UI.outcomeLabel(key));item.prepend(el('b',String(counts[key])));$('#summary').append(item);}
    $('#exportbar').hidden=false;$('#batch-info').textContent=`${rows.length} ${rows.length===1?'result':'results'} in this group · ${running?'Checks in progress':rows.some(row=>['failed','cancelled','interrupted'].includes(row.state))?'Some checks need to run again':'Checks complete'}`;
    for(const format of ['csv','json','html'])$('#export-'+format).href=`/api/batches/${encodeURIComponent(activeBatch)}/export?format=${format}`;
  }
  if(focus){const target=document.getElementById(focus);if(target&&document.activeElement?.tagName==='BODY'){target.focus({preventScroll:true});if(typeof selection==='number'&&target.setSelectionRange)try{target.setSelectionRange(selection,selection);}catch{}}}
  poll(running);
}
function clearInputErrors(){for(const id of ['reference','competitor']){$('#'+id).removeAttribute('aria-invalid');$('#'+id+'-error').hidden=true;}}
function validateInput(){clearInputErrors();let first=null;for(const id of ['reference','competitor']){const input=$('#'+id);let text='';if(!input.value.trim())text='Add a product URL.';else try{const url=new URL(input.value);if(url.protocol!=='https:')text='Use a public HTTPS product URL.';}catch{text='Enter a complete product URL.';}if(text){input.setAttribute('aria-invalid','true');$('#'+id+'-error').textContent=text;$('#'+id+'-error').hidden=false;first=first||input;}}if(first){first.focus();return false;}return true;}
function initNew(){
$('#case-form').onsubmit=async event=>{
  event.preventDefault();if(!validateInput())return;const button=$('#investigate');button.disabled=true;button.textContent='Starting a new check…';$('#form-status').textContent='Checking the page links and starting a new check.';
  try{const result=await api('/api/batches',{cases:[{sku:$('#sku').value,reference_url:$('#reference').value.trim(),competitor_url:$('#competitor').value.trim()}],mode:$('#mode').value,idempotency_key:crypto.randomUUID()});navigateToBatch(result.id);}
  catch(error){$('#form-status').textContent='The check did not start.';message(error.message,true);}
  finally{button.disabled=false;button.replaceChildren(document.createTextNode('Run a new check '),el('span','↗'));}
};
for(const id of ['reference','competitor'])$('#'+id).addEventListener('input',()=>{$('#'+id).removeAttribute('aria-invalid');$('#'+id+'-error').hidden=true;});
$('#selected-pair').onclick=()=>{const button=$('#selected-pair');$('#reference').value=button.dataset.reference;$('#competitor').value=button.dataset.competitor;$('#sku').value='Adafruit SSD variant control';$('#mode').value=button.dataset.mode||'public';$('#mode').dispatchEvent(new Event('change'));clearInputErrors();$('#form-status').textContent='Page links added. Choose Run a new check to read the pages.';$('#reference').focus();};
$('#samples').onclick=async()=>{const button=$('#samples');button.disabled=true;try{const result=await api('/api/samples',{idempotency_key:crypto.randomUUID()});navigateToBatch(result.id);}catch(error){message(error.message,true);button.disabled=false;}};
$('#mode').onchange=()=>{$('#mode-help').textContent=$('#mode').value==='live'?'Uses Tavily and NVIDIA on Nebius within the set credit limits. Missing details stay unknown.':'Reads the product pages without model calls or provider credits. Missing details stay unknown.';};
if($('#csv-file'))$('#csv-file').onchange=async event=>{previewRows=[];$('#run-csv').disabled=true;try{const file=event.target.files[0];if(!file)return;if(file.size>150000)throw Error('Choose a CSV smaller than 150 KB.');const result=await api('/api/batches/preview',{csv:await file.text()});previewRows=result.cases;$('#csv-preview').textContent=`${result.cases.length} valid rows · ${result.errors.length} errors. No retrieval yet.\n`+result.errors.map(item=>`Row ${item.row}: ${item.error}`).join('\n');$('#run-csv').disabled=!result.cases.length||result.errors.length>0;}catch(error){$('#csv-preview').textContent=error.message;}};
if($('#run-csv'))$('#run-csv').onclick=async()=>{const button=$('#run-csv');button.disabled=true;try{const result=await api('/api/batches',{cases:previewRows,mode:$('#mode').value,idempotency_key:crypto.randomUUID()});navigateToBatch(result.id);}catch(error){message(error.message,true);}finally{button.disabled=!previewRows.length;}};
}
function initDemo(){
  const status=$('#demo-status'),refresh=$('#demo-refresh'),start=$('#start-demo');
  api('/api/status').then(state=>{if(!state.live_enabled){if(refresh)refresh.disabled=true;if(start)start.disabled=true;status.textContent='New live checks are turned off. You can still view saved results or try made-up examples.';}}).catch(error=>{if(refresh)refresh.disabled=true;if(start)start.disabled=true;status.textContent=error.message;});
  if(refresh)refresh.onclick=async()=>{refresh.disabled=true;status.textContent='Starting a new check. Reading the pages again uses demo provider credits…';try{await api('/api/cases/'+refresh.dataset.caseId+'/refresh',{});location.assign('/cases/'+refresh.dataset.caseId+'#decision-summary');}catch(error){status.textContent=error.message;refresh.disabled=false;}};
  if(start)start.onclick=async()=>{start.disabled=true;status.textContent='Starting a new check. Reading the pages uses demo provider credits…';try{const batch=await api('/api/batches',{mode:'live',idempotency_key:crypto.randomUUID(),cases:[{sku:'Adafruit SSD variant control',reference_url:start.dataset.reference,competitor_url:start.dataset.competitor}]});navigateToBatch(batch.id);}catch(error){status.textContent=error.message;start.disabled=false;}};
  $('#demo-samples').onclick=async()=>{const button=$('#demo-samples');button.disabled=true;try{const batch=await api('/api/samples',{idempotency_key:crypto.randomUUID()});navigateToBatch(batch.id);}catch(error){message(error.message,true);button.disabled=false;}};
  for(const time of document.querySelectorAll('.demo-preset time')){const date=new Date(time.dateTime);time.textContent=time.dateTime&&!Number.isNaN(date.valueOf())?date.toLocaleString(undefined,{timeZoneName:'short'}):'Time not available';}
}
(async()=>{
  if(page==='demo'){
    initDemo();
  }else if(page==='start'){
    const button=$('#guided-samples');if(button)button.onclick=async()=>{button.disabled=true;try{const result=await api('/api/samples',{idempotency_key:crypto.randomUUID()});navigateToBatch(result.id);}catch(error){message(error.message,true);button.disabled=false;}};
  }else if(page==='new'){
    initNew();const status=await api('/api/status');$('#mode option[value="live"]').disabled=!status.live_enabled;if(status.public_demo){$('#mode').value='live';const allowance=status.live_allowance;if(!status.live_enabled){$('#investigate').disabled=true;$('#form-status').textContent='New live checks are turned off. You can still view saved results and examples.';}else if(allowance){$('#form-status').textContent=`Available this hour: ${allowance.session_remaining} for this visitor session, ${allowance.shared_remaining} shared. Saved results and made-up examples stay available.`;$('#investigate').disabled=allowance.session_remaining===0||allowance.shared_remaining===0;}}
  }else if(page==='queue'){
    const allowed=['all','unreviewed','COMPARABLE_LISTED_PRICE','NOT_COMPARABLE','INSUFFICIENT_EVIDENCE'];
    filter=allowed.includes(query.get('filter'))?query.get('filter'):'all';$('#case-filter').value=filter;
    $('#batches').onchange=event=>{if(event.target.value){filter='all';$('#case-filter').value='all';openBatch(event.target.value).catch(error=>message(error.message,true));}};
    $('#case-filter').onchange=event=>{filter=event.target.value;if(activeBatch)history.replaceState(null,'',queueURL(activeBatch,filter));renderBatch(true).catch(error=>message(error.message,true));};
    const rows=await batchList(),id=UI.initialBatch(rows,query.get('batch'),localStorage.getItem('activeBatch'));
    if(id)try{await openBatch(id);}catch(error){$('#cases').replaceChildren(el('p','This group could not be loaded. Choose another saved group.','pending-note'));message(error.message,true);}
  }else if(page==='detail'){
    activeBatch=document.body.dataset.batchId;
    const back=$('#back-to-queue');
    const allowed=['unreviewed','COMPARABLE_LISTED_PRICE','NOT_COMPARABLE','INSUFFICIENT_EVIDENCE'];
    if(allowed.includes(query.get('filter')))back.href=queueURL(activeBatch,query.get('filter'));
    await renderBatch(true);
    if(location.hash==='#decision-summary'){
      const summary=$('#decision-summary');if(summary){summary.focus({preventScroll:true});summary.scrollIntoView({block:'start'});}
    }
  }
})().catch(error=>message(error.message,true));
