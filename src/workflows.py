"""Read-only activity summary for the active investigation services."""
import json
from .config import status


class Workflows:
    def __init__(self, store):
        self.store=store

    def public_summary(self):
        config=status();providers={}
        roles={'nebius':'NVIDIA reasoning and evidence extraction','tavily':'Web evidence research',
               'langsmith':'Investigation trace verification'}
        with self.store.connect() as connection:
            results=[json.loads(r[0]) for r in connection.execute('SELECT result FROM cases WHERE result IS NOT NULL')]
        for provider,role in roles.items():
            public={'role':role,'configured':config.get(provider+'_configured',False)}
            if provider in ('nebius','tavily'):
                calls=sum(step.get('provider')==provider and step.get('status')=='ok' for r in results for step in r.get('trace',[]))
                public.update(status='verified' if calls else 'awaiting_live_run',verified_steps=calls)
            else:
                runs=sum((r.get('observability') or {}).get('status')=='verified' for r in results)
                public.update(status='verified' if runs else 'awaiting_trace',verified_runs=runs)
            providers[provider]=public
        return {'providers':providers,
                'notice':'Activity counts cover current case revisions. Local fictional scenarios test comparison rules without provider calls; they do not measure live retail accuracy.'}
