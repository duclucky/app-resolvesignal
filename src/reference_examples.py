"""Curated fictional results for learning the comparison/review workflow."""

EXAMPLES = {
    'ssd-lower': ('Same SSD, lower price', 'Matching product details and price terms make this listed-price difference worth reviewing.'),
    'ssd-equal': ('Same SSD, same price', 'Comparable offers do not always call for a price change.'),
    'stock-out_of_stock': ('Cheaper offer is out of stock', 'Check stock before acting on a lower listed price.'),
    'different-capacity-2-TB': ('1 TB versus 2 TB', 'A similar product name does not make different storage sizes comparable.'),
    'different-condition-refurbished': ('New versus refurbished', 'Check item condition before treating the lower price as a competing offer.'),
    'different-quantity-2': ('One drive versus a two-pack', 'A pack price and a single-item price are different offers.'),
    'different-eligibility-membership': ('Regular price versus member price', 'A membership-only price has a different buying condition.'),
    'different-eligibility-rebate': ('Regular price versus rebate price', 'An after-rebate price is not the same as an unconditional listed price.'),
    'keyboard-layout': ('Same keyboard, different layout', 'Check the selected keyboard layout, not only the model family.'),
    'keyboard-switch': ('Same keyboard, different switches', 'The switch choice can change the product even when its name looks the same.'),
    'missing-mpn': ('Product identity is missing', 'Without a matching part number or valid barcode, a similar title is not enough.'),
    'missing-quantity': ('Pack size is not stated', 'Do not assume an unstated pack quantity is one.'),
    'missing-eligibility': ('Price conditions are unclear', 'Check who can get this price before using the difference.'),
    'stale-page': ('One price was checked too long ago', 'Old evidence needs another check before a new pricing decision.'),
    'conflicting-variant': ('The page disagrees with itself', 'Conflicting details about the selected variant need checking at the source.'),
}


def result_for(case):
    from .quality import run_case
    result=run_case(case)
    if case['id'] in EXAMPLES:
        title,note=EXAMPLES[case['id']]
        result.update(display_title=title,learning_note=note,scenario_sources=case['sources'])
    return result


def install(store):
    """Seed once; never overwrite a saved result, history or user's review."""
    from .quality import corpus
    cases={c['id']:c for c in corpus()['cases']}
    request={'idempotency_key':'reference-examples-v1','mode':'synthetic',
             'label':'More made-up examples',
             'cases':[{'sku':key,'reference_url':cases[key]['offers'][0]['url'],
                       'competitor_url':cases[key]['offers'][1]['url']} for key in EXAMPLES]}
    bid,_=store.create_batch(request)
    for row in store.batch(bid):
        if row['revision']==0 and row['state']=='queued':
            store.finish(row['id'],result_for(cases[row['request']['sku']]))
    return bid
