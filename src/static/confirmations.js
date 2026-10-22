/* Sourced operator assertions are local, revision-scoped and removable. */
function confirmationPanel(row, reload) {
  const result = row.result;
  if (result?.offers?.length !== 2) return null;
  const panel = el('details', undefined, 'confirmation-panel');
  const claims = result.operator_confirmations || [], active = claims.filter(item => item.active);
  const editable = ['completed', 'partial'].includes(row.state);
  panel.append(el('summary', `User-confirmed details · ${active.length} active`));
  panel.append(el('p', 'Add a missing detail only if you checked it in a source. Include the link and quote. These details are marked as user-confirmed, not independently verified. A new source check requires new confirmation.', 'help'));
  for (const claim of claims) {
    const entry = el('div', undefined, 'confirmation-entry');
    entry.append(el('strong', `${UI.offerLabel(claim.side)} · ${labels[claim.field]||human(claim.field)} = ${claim.value} · ${claim.active ? 'Active' : 'Withdrawn'}`));
    entry.append(el('p', `Confirmed by ${claim.confirmed_by} · ${new Date(claim.confirmed_at).toLocaleString()} · Source not independently checked`, 'help'), el('blockquote', claim.excerpt));
    const link = el('a', claim.source_url); link.href = claim.source_url; link.target = '_blank'; link.rel = 'noopener noreferrer'; entry.append(link);
    if (claim.active && editable) {
      const button = el('button', 'Withdraw confirmation', 'text-button'); button.type = 'button';
      button.onclick = async () => {
        button.disabled = true;
        try {
          await api(`/api/cases/${row.id}/confirmations/${claim.id}/withdraw`, {revision: row.revision});
          await reload(); message('Confirmation removed from this version. The result was updated and earlier versions are kept.');
        } catch (error) {message(error.message, true); button.disabled = false;}
      };
      entry.append(button);
    }
    panel.append(entry);
  }
  if (!editable) return panel;
  const raw = result.retrieved_offers || result.offers;
  function fieldsFor(index) {
    const offer = raw[index], side = index ? 'competitor' : 'reference';
    if (offer.conflicts.some(text => /unselected|ambiguous/.test(text))) return [];
    const fields = ['condition', 'quantity', 'eligibility', 'mpn', 'brand'];
    if (offer.category === 'keyboard') fields.push('layout', 'switch');
    if (offer.category === 'ssd') fields.push('capacity');
    return fields.filter(field => offer[field] == null && !active.some(item => item.side === side && item.field === field));
  }
  if (!fieldsFor(0).length && !fieldsFor(1).length) {
    panel.append(el('p', 'No missing details can be added to this result.', 'help')); return panel;
  }
  const form = el('form', undefined, 'confirmation-form');
  function input(name, text, control) {
    control.id = `${row.id}-confirmation-${name}`;
    const label = el('label', text); label.htmlFor = control.id; form.append(label, control); return control;
  }
  const name = input('name', 'Confirmed by (self-reported)', el('input'));
  name.required = true; name.minLength = 2; name.maxLength = 80; name.autocomplete = 'off';
  const side = input('side', 'Offer', el('select'));
  for (const [value, label] of [['reference', 'Offer A'], ['competitor', 'Offer B']]) {
    const option = el('option', label); option.value = value; side.append(option);
  }
  const field = input('field', 'Missing detail', el('select'));
  const valueSlot = el('div'); form.append(valueSlot); let value;
  const source = input('source', 'Public source URL', el('input')); source.type = 'url'; source.required = true; source.maxLength = 2048;
  const quote = input('quote', 'Quote that supports this detail', el('textarea')); quote.required = true; quote.minLength = 12; quote.maxLength = 1000;
  form.append(el('p', 'Use a public HTTPS source. Condition and price conditions must link to the same store as the offer. Do not enter account, payment or customer information.', 'help'));
  const attested = el('input'); attested.type = 'checkbox'; attested.required = true;
  const consent = el('label', undefined, 'checklabel'); consent.append(attested, el('span', 'I checked the source and confirm this detail applies to this exact offer.')); form.append(consent);
  const save = el('button', 'Save detail & update result', 'secondary'); save.type = 'submit';
  const status = el('p', '', 'help'); status.setAttribute('role', 'status'); form.append(save, status);
  function changeField() {
    valueSlot.replaceChildren();
    const options = {condition: ['new', 'refurbished', 'open_box', 'used', 'damaged'], eligibility: ['unconditional', 'conditional', 'membership', 'trade_in', 'rebate']};
    value = el(options[field.value] ? 'select' : 'input'); value.required = true; value.id = `${row.id}-confirmation-value`;
    const label = el('label', field.value === 'quantity' ? 'Confirmed pack quantity (not cart quantity)' : 'Confirmed value'); label.htmlFor = value.id; valueSlot.append(label, value);
    if (options[field.value]) {
      const placeholder = el('option', 'Choose a value'); placeholder.value = ''; value.append(placeholder);
      for (const item of options[field.value]) {const option = el('option', ({unconditional:'No special conditions',conditional:'Has special conditions',membership:'Members only',trade_in:'Trade-in required',rebate:'Rebate required'})[item] || item.replaceAll('_', ' ')); option.value = item; value.append(option);}
    } else if (field.value === 'quantity') {value.type = 'number'; value.min = '1'; value.max = '10000'; value.step = '1';}
    else value.maxLength = 120;
    quote.value = ''; attested.checked = false;
  }
  function changeSide() {
    const index = side.value === 'reference' ? 0 : 1; field.replaceChildren();
    for (const key of fieldsFor(index)) {
      const option = el('option', ({quantity: 'Pack quantity', eligibility: 'Price conditions', mpn: 'Manufacturer part number'})[key] || key); option.value = key; field.append(option);
    }
    save.disabled = !field.options.length; source.value = raw[index].url; changeField();
  }
  side.onchange = changeSide; field.onchange = changeField;
  if (!fieldsFor(0).length) side.value = 'competitor'; changeSide();
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true; status.textContent = 'Saving detail…';
    try {
      await api(`/api/cases/${row.id}/confirmations`, {revision: row.revision, confirmed_by: name.value, attested: attested.checked,
        items: [{side: side.value, field: field.value, value: field.value === 'quantity' ? Number(value.value) : value.value, source_url: source.value, excerpt: quote.value}]});
      document.activeElement?.blur(); await reload(); message('User-confirmed detail saved in a new version. The app has not independently checked the source.');
    } catch (error) {status.textContent = error.message; save.disabled = false;}
  };
  panel.append(form); return panel;
}
