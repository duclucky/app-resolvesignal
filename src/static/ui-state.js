/* Original, dependency-free presentation logic. No confidence/progress percentage is inferred. */
(function (root) {
  function currentReview(row) {
    if (!['completed', 'partial'].includes(row.state)) return null;
    return (row.reviews || []).find(review => review.revision === row.revision) || null;
  }

  function currentDecision(row) {
    return ['completed', 'partial'].includes(row.state) ? row.result?.decision || null : null;
  }

  function outcomeLabel(value) {
    return {COMPARABLE_LISTED_PRICE:'Can compare',NOT_COMPARABLE:'Do not compare',INSUFFICIENT_EVIDENCE:'More info needed'}[value]||'No completed result';
  }

  function reviewLabel(value) {
    return {reviewed:'I reviewed this',disputed:'I disagree with this result',follow_up:'Needs more checking'}[value]||'Review status unavailable';
  }

  function stateLabel(value) {
    return {queued:'Waiting to start',collecting:'Reading source pages',investigating:'Checking offers',validating:'Checking evidence',
      completed:'Check complete',partial:'Partly complete',failed:'Check failed',cancelled:'Check stopped',interrupted:'Check interrupted'}[value]||'Check status unavailable';
  }

  function offerLabel(side) {return side==='reference'?'Offer A':side==='competitor'?'Offer B':'Offer';}

  function offerTitle(offer) {
    const title=String(offer.title||'').trim();
    return !title||/^\[!?\[|^\[(?:Jump|Skip) to\b/i.test(title)?'Product title unavailable':title;
  }

  function decisionBrief(row) {
    const decision=currentDecision(row);
    if(!decision)return null;
    const titles={DISMISS_MISMATCH:'Do not compare these prices.',REQUEST_REVIEW:'Check the missing details.',
      REVIEW_PRICING:'Review the price difference.',MONITOR_AVAILABILITY:'Check stock first.',NO_PRICE_ACTION:'No price change suggested.'};
    const instructions={
      DISMISS_MISMATCH:'Check the difference in the source evidence, then save a review. Do not use this pair for a price change.',
      REQUEST_REVIEW:'Open the sources to check the missing details below. Save a review with what still needs checking.',
      REVIEW_PRICING:'Check the product details and price terms. Save your review before deciding whether to change a price.',
      MONITOR_AVAILABILITY:'Confirm both offers are in stock before using this price difference. Save a review with what you find.',
      NO_PRICE_ACTION:'Check the evidence, then save your review. You can check the sources again later.'};
    return {title:titles[decision.action]||'Check the evidence before acting.',
      reason:(decision.reasons||[]).map(readableReason).join(' · ')||'The reason is not available. Check the source evidence.',
      instruction:instructions[decision.action]||'Read the source evidence and save a review with what you found.'};
  }

  const fieldNames={capacity:'Capacity',condition:'Condition',quantity:'Pack quantity',eligibility:'Price conditions',
    mpn:'Manufacturer part number',gtin:'Product barcode (GTIN)',layout:'Keyboard layout',switch:'Switch type',currency:'Currency',price_basis:'Price basis'};
  function readableReason(text){
    const descriptions={
      'Decisive product and offer fields match on the disclosed listed-price basis.':'Product details and offer terms match for this listed-price comparison.',
      'Material fields are missing, stale or conflicting.':'Key details are missing, out of date or inconsistent.'};
    return descriptions[text]||String(text).replace(/^([a-z_]+):/,(_,field)=>(fieldNames[field]||field.replaceAll('_',' '))+':');
  }
  function missingFacts(fields){
    const generic=(fields||[]).includes('matching product barcode for this product type');
    return [...new Set((fields||[]).filter(field=>!generic||field!=='mpn or validated GTIN').map(field=>{
      if(field==='matching product barcode for this product type')return 'Matching valid product barcodes on both pages';
      if(field==='mpn or validated GTIN')return 'Matching manufacturer part number or valid product barcode (GTIN)';
      if(field==='supported category')return 'Supported product type';
      if(fieldNames[field])return fieldNames[field];
      const match=String(field).match(/^(reference|competitor) (.+)$/);
      if(match){const names={'unconditional eligibility':'price without membership or other restrictions',
        'valid price':'verified price','supported USD market':'USD price','availability':'stock status','fresh observation':'recent retrieval time'};
        return offerLabel(match[1])+': '+(names[match[2]]||match[2].replaceAll('_',' '));}
      return String(field).replaceAll('_',' ');
    }))];
  }
  function recoveryPlan(row){
    if(!currentDecision(row)||!['INSUFFICIENT_EVIDENCE'].includes(row.result.decision.outcome))return [];
    const result=row.result,steps=[];
    for(const [index,offer] of (result.offers||[]).entries()){
      const access=(result.source_access||[]).find(item=>item.url===offer.url),label=index?'Offer B':'Offer A';
      if(access?.status==='blocked')steps.push({kind:'blocked',title:label+' blocks direct reading',
        instruction:offer.evidence?.length?'Some evidence came from web extraction. Open this page to check the missing facts.':'Open this page yourself, or try another public product page with the same exact version.',url:offer.url});
      else if(!offer.evidence?.length)steps.push({kind:'unreadable',title:label+' has no usable product evidence',
        instruction:'Use the full product link with its exact version selected. Try another store if this page needs a login or does not show the product.',url:offer.url});
    }
    const missing=result.decision.unknown||[];
    if(missing.some(field=>/gtin|barcode|mpn/i.test(field)))steps.push({kind:'identity',title:'Check the exact product and barcode',
      instruction:'Look for GTIN, UPC or EAN on both product pages and check the size, color and pack. Do not substitute a store SKU or a similar product title.'});
    if(missing.some(field=>/condition|quantity|eligibility/.test(field)))steps.push({kind:'terms',title:'Check condition, pack size and price terms',
      instruction:'Confirm whether each offer is new, how many items it includes and whether its price needs membership, a rebate or another condition. You can add sourced confirmations in More details → User-confirmed details.'});
    if(!steps.length)steps.push({kind:'details',title:'Check the missing details at the source',
      instruction:'Open the product pages and check the details listed below. Run a new check after correcting the links, or save a review with what still needs checking.'});
    return steps.slice(0,3);
  }
  function supportingQuotes(result){
    const reasonFields=(result.decision?.reasons||[]).map(text=>String(text).match(/^([a-z_]+):/)).filter(Boolean).map(match=>match[1]);
    const fields=reasonFields.length?reasonFields:['mpn','gtin','capacity','layout','switch','condition','price','title'];
    const quotes=[];
    for(const offer of result.offers||[]){let count=0;
      for(const field of [...new Set(fields)]){
        const evidence=(offer.evidence||[]).find(item=>item.field===field&&item.excerpt);
        if(evidence){quotes.push({offer,evidence});count++;}
        if(!reasonFields.length&&count>=2)break;
      }
    }
    return quotes;
  }
  function caseTitle(row){
    if(row.result?.mode==='synthetic'&&row.result.display_title)return row.result.display_title+' · made-up example';
    const sample={comparable:'Matching offers · made-up example',mismatch:'Different conditions · made-up example',unknown:'Missing price conditions · made-up example'};
    if(row.request.mode==='sample'&&sample[row.request.sku])return sample[row.request.sku];
    return row.request.sku==='Adafruit SSD variant control'?'Adafruit SSD comparison':row.request.sku||'Offer comparison';
  }

  function decisionCounts(rows) {
    const counts={COMPARABLE_LISTED_PRICE:0,NOT_COMPARABLE:0,INSUFFICIENT_EVIDENCE:0};
    for(const row of rows){const outcome=currentDecision(row)?.outcome;if(outcome in counts)counts[outcome]++;}
    return counts;
  }

  function initialBatch(rows, explicit, saved) {
    return explicit || (rows.some(row=>row.id===saved) ? saved : rows[0]?.id) || null;
  }

  function steps(row) {
    const labels = ['Read source pages', 'Check offers', 'Save review'];
    let states;
    if (row.state === 'completed') states = ['done', 'done', currentReview(row) ? 'done' : 'current'];
    else if (row.state === 'partial') states = ['warning', 'warning', 'current'];
    else if (['failed', 'cancelled', 'interrupted'].includes(row.state)) states = ['stopped', 'pending', 'pending'];
    else if (['investigating', 'validating'].includes(row.state)) states = ['done', 'current', 'pending'];
    else states = ['current', 'pending', 'pending'];
    return labels.map((label, index) => ({label, state: states[index]}));
  }

  function terminal(row) {
    return ['completed', 'partial', 'failed', 'cancelled', 'interrupted'].includes(row.state);
  }

  function filterCases(rows, filter) {
    if (filter === 'all') return rows;
    if (filter === 'unreviewed') return rows.filter(row => terminal(row) && !currentReview(row));
    return rows.filter(row => currentDecision(row)?.outcome === filter);
  }

  const api = {currentReview, currentDecision, outcomeLabel, reviewLabel, stateLabel, offerLabel, offerTitle, decisionBrief, readableReason, missingFacts, recoveryPlan, supportingQuotes, caseTitle, decisionCounts, initialBatch, steps, terminal, filterCases};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.InvestigationUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
