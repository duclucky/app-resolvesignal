const {test} = require('node:test');
const assert = require('node:assert/strict');
const {steps, currentReview, terminal, filterCases, currentDecision, decisionCounts, initialBatch, decisionBrief} = require('../src/static/ui-state.js');
const {supportingQuotes, missingFacts} = require('../src/static/ui-state.js');

test('recovery distinguishes blocked sources, missing evidence and identity without inventing a block',()=>{
  const {recoveryPlan}=require('../src/static/ui-state.js');
  const row={state:'completed',result:{decision:{outcome:'INSUFFICIENT_EVIDENCE',unknown:['mpn or validated GTIN','quantity']},
    offers:[{url:'https://a.example/p',evidence:[]},{url:'https://b.example/p',evidence:[{field:'price'}]}],
    source_access:[{url:'https://a.example/p',status:'blocked',http_status:403}]}};
  const plan=recoveryPlan(row);assert.equal(plan[0].kind,'blocked');assert.equal(plan[0].url,row.result.offers[0].url);
  assert.ok(plan.some(s=>s.kind==='identity'));assert.ok(plan.some(s=>s.kind==='terms'));
  delete row.result.source_access;assert.equal(recoveryPlan(row)[0].kind,'unreadable');
  row.result.decision.outcome='NOT_COMPARABLE';assert.deepEqual(recoveryPlan(row),[]);
  assert.equal(missingFacts(['mpn or validated GTIN','matching product barcode for this product type']).length,1);
});

test('unreadable page navigation is not presented as a product title',()=>{
  const {offerTitle}=require('../src/static/ui-state.js');
  assert.equal(offerTitle({title:'[Jump to content in footer](#footercontent)\n[![JBL Brand]'}),'Product title unavailable');
  assert.equal(offerTitle({title:''}),'Product title unavailable');
  assert.equal(offerTitle({title:'JBL Flip 6'}),'JBL Flip 6');
});

test('compact quotes isolate the mismatch without dropping or mutating the full evidence',()=>{
  const offers=['a','b'].map((url,i)=>({url,evidence:[{field:'title',excerpt:'Drive'},
    {field:'capacity',excerpt:i?'512 GB':'256 GB',url},
    {field:'capacity',excerpt:i?'512 GB':'256 GB',url,provider:'duplicate'}]}));
  const result={offers,decision:{reasons:['capacity: 256 GB versus 512 GB']}};
  const before=JSON.stringify(result),quotes=supportingQuotes(result);
  assert.equal(quotes.length,2);assert.equal(quotes[0].evidence.field,'capacity');
  assert.equal(JSON.stringify(result),before);
  assert.deepEqual(supportingQuotes({offers:[],decision:{}}),[]);
});

test('missing facts use readable labels and retain both generic and offer-specific uncertainty',()=>{
  const text=missingFacts(['eligibility','competitor unconditional eligibility','quantity','mpn or validated GTIN']).join(' · ');
  assert.ok(text.includes('Price conditions'));assert.ok(text.includes('Offer B'));
  assert.ok(text.includes('Pack quantity'));assert.ok(text.includes('manufacturer part number'));
  assert.equal(text.includes('eligibility'),false);
});

test('action-first summary never turns retained or partial evidence into a price recommendation', () => {
  const result={decision:{outcome:'NOT_COMPARABLE',action:'DISMISS_MISMATCH',reasons:['Different capacities']}};
  assert.equal(decisionBrief({state:'completed',result}).title,'Do not compare these prices.');
  assert.equal(decisionBrief({state:'completed',result}).reason,'Different capacities');
  for(const state of ['collecting','failed','cancelled','interrupted'])assert.equal(decisionBrief({state,result}),null);
  assert.equal(decisionBrief({state:'partial',result:{decision:{outcome:'INSUFFICIENT_EVIDENCE',action:'REQUEST_REVIEW'}}}).title,'Check the missing details.');
  assert.equal(decisionBrief({state:'completed',result:{decision:{outcome:'COMPARABLE_LISTED_PRICE',action:'REVIEW_PRICING'}}}).title,'Review the price difference.');
});

test('refresh does not carry an old review into the current revision', () => {
  const row = {state:'completed', revision:2, reviews:[{revision:1, status:'reviewed'}]};
  assert.equal(currentReview(row), null);
  assert.deepEqual(steps(row).map(step=>step.state), ['done','done','current']);
  assert.equal(filterCases([row], 'unreviewed').length, 1);
  row.reviews.push({revision:2, status:'follow_up'});
  assert.equal(currentReview(row).status, 'follow_up');
  assert.equal(steps(row)[2].state, 'done');
});

test('partial and failed investigations are never shown as successfully complete', () => {
  assert.deepEqual(steps({state:'partial'}).map(step=>step.state), ['warning','warning','current']);
  for (const state of ['failed','cancelled','interrupted']) {
    assert.equal(steps({state})[0].state, 'stopped');
    assert.equal(steps({state}).filter(step=>step.state==='done').length, 0);
    assert.equal(terminal({state}), true);
  }
});

test('processing reflects backend state and has no invented percentage', () => {
  for (const state of ['queued','collecting']) assert.equal(steps({state})[0].state, 'current');
  for (const state of ['investigating','validating']) assert.equal(steps({state})[1].state, 'current');
  assert.equal(terminal({state:'collecting'}), false);
  assert.equal(steps({state:'collecting'}).some(step=>'percentage' in step), false);
});

test('decision filters retain failures for review rather than hiding them', () => {
  const rows = [{state:'failed', revision:1},
    {state:'completed',revision:1,result:{decision:{outcome:'NOT_COMPARABLE'}}},
    {state:'collecting',revision:0}];
  assert.equal(filterCases(rows,'all').length, 3);
  assert.equal(filterCases(rows,'unreviewed').length, 2);
  assert.equal(filterCases(rows,'NOT_COMPARABLE').length, 1);
});

test('stopped rechecks keep historical evidence outside current outcome filters and counts', () => {
  const result={decision:{outcome:'COMPARABLE_LISTED_PRICE'}};
  const rows=['cancelled','interrupted','failed','collecting'].map(state=>({state,revision:1,result}));
  assert.equal(filterCases(rows,'COMPARABLE_LISTED_PRICE').length,0);
  for(const row of rows)assert.equal(currentDecision(row),null);
  assert.equal(currentReview({...rows[0],reviews:[{revision:1,status:'reviewed'}]}),null);
  assert.equal(filterCases(rows,'all').length,4);
  assert.equal(decisionCounts(rows).COMPARABLE_LISTED_PRICE,0);
  const complete={state:'completed',result},partial={state:'partial',result:{decision:{outcome:'INSUFFICIENT_EVIDENCE'}}};
  assert.equal(currentDecision(complete).outcome,'COMPARABLE_LISTED_PRICE');
  assert.equal(decisionCounts([...rows,complete,partial]).COMPARABLE_LISTED_PRICE,1);
  assert.equal(decisionCounts([...rows,complete,partial]).INSUFFICIENT_EVIDENCE,1);
});

test('saved batch missing from this profile falls back but explicit links are respected', () => {
  const rows=[{id:'demo-batch'},{id:'other-batch'}];
  assert.equal(initialBatch(rows,null,'private-batch'),'demo-batch');
  assert.equal(initialBatch(rows,null,'other-batch'),'other-batch');
  assert.equal(initialBatch(rows,'explicit-missing','other-batch'),'explicit-missing');
  assert.equal(initialBatch([],null,'stale'),null);
});
