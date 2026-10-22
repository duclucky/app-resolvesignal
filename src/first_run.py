"""Read-only first-use view of a verified result from the current profile."""
from datetime import datetime
from .policies import SELECTED_SOURCE_URLS


def selected_demo_case(store):
    """Find existing selected live work without creating or refreshing it."""
    with store.connect() as connection:
        rows=connection.execute("SELECT cases.* FROM cases JOIN batches ON batches.id=cases.batch_id "
                                "ORDER BY (batches.idem='public-demo-live-v1') DESC, batches.created DESC").fetchall()
    for raw in rows:
        row=store._decode(raw);request=row['request']
        if request.get('mode')=='live' and [request.get(k) for k in ('reference_url','competitor_url')]==list(SELECTED_SOURCE_URLS):
            offers=(row.get('result') or {}).get('offers',[])
            return {'id':row['id'],'state':row['state'],'revision':row['revision'],
                    'times':[offer.get('observed_at') for offer in offers if offer.get('observed_at')]}
    return None


def saved_example(store):
    with store.connect() as connection:
        rows = connection.execute(
            "SELECT cases.* FROM cases JOIN batches ON batches.id=cases.batch_id "
            "WHERE state='completed' ORDER BY batches.created DESC"
        ).fetchall()
    for raw in rows:
        row = store._decode(raw)
        request, result = row['request'], row.get('result') or {}
        if request.get('mode') != 'live' or result.get('mode') != 'live':
            continue
        if [request.get(key) for key in ('reference_url', 'competitor_url')] != list(SELECTED_SOURCE_URLS):
            continue
        decision = result.get('decision', {})
        if decision.get('evidence_basis') == 'operator_assisted':
            continue
        if decision.get('outcome') != 'NOT_COMPARABLE' or decision.get('action') != 'DISMISS_MISMATCH':
            continue
        trace = result.get('trace', [])
        if not any(step.get('provider') == 'nebius' and step.get('status') == 'ok'
                   and str(step.get('model', '')).startswith('nvidia/') for step in trace):
            continue
        if not any(step.get('provider') == 'tavily' and step.get('status') == 'ok' for step in trace):
            continue
        if result.get('observability', {}).get('status') != 'verified':
            continue
        offers = result.get('offers', [])
        if len(offers) != 2 or [offer.get('url') for offer in offers] != list(SELECTED_SOURCE_URLS):
            continue
        if [offer.get('capacity') for offer in offers] != ['256 GB', '512 GB']:
            continue
        quotes = [next((item.get('excerpt') for item in offer.get('evidence', [])
                        if item.get('field') == 'capacity' and item.get('url') == offer['url']
                        and item.get('origin') != 'operator_confirmed'), None) for offer in offers]
        try:
            times = [datetime.fromisoformat(offer['observed_at']) for offer in offers]
            if any(time.tzinfo is None for time in times) or not all(quotes):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        return {'id': row['id'], 'revision': row['revision'],
                'offers': [{'capacity': offer['capacity'], 'url': offer['url'],
                            'quote': quote, 'observed_at': offer['observed_at'],
                            'observed_label': time.strftime('%d %b %Y, %H:%M %z')}
                           for offer, quote, time in zip(offers, quotes, times)]}
    return None
