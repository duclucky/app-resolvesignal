import json
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .schemas import utcnow

REFRESH_FIELDS=('title','category','mpn','gtin','capacity','layout','switch','condition','quantity',
                'price','currency','availability','eligibility','price_basis')


def refresh_comparison(previous,current,revision):
    """Compare observations, excluding operator additions and retrieval timestamps."""
    before=previous.get('retrieved_offers',previous.get('offers',[]))
    after=current.get('retrieved_offers',current.get('offers',[]))
    complete=len(before)==len(after)==2 and all(offer.get('evidence') for offer in before+after)
    fields=[]
    if complete:
        for side,old,new in zip(('reference','competitor'),before,after):
            for field in REFRESH_FIELDS:
                if field=='price' and old.get(field) is not None and new.get(field) is not None:
                    try:
                        if Decimal(str(old[field]))==Decimal(str(new[field])):continue
                    except InvalidOperation:pass
                if old.get(field)!=new.get(field):
                    fields.append({'side':side,'field':field,'before':old.get(field),'after':new.get(field)})
    return {'previous_revision':revision,'complete_pair':complete,'fields':fields,
            'previous_outcome':previous.get('decision',{}).get('outcome'),
            'current_outcome':current.get('decision',{}).get('outcome'),
            'basis':'Retrieved attributes only; previous operator confirmations are not carried forward.'}


class Store:
    def __init__(self,path):
        self.path=str(path);Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY, idem TEXT UNIQUE, request TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, batch_id TEXT, request TEXT, state TEXT, revision INTEGER DEFAULT 0, result TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS revisions(case_id TEXT, revision INTEGER, result TEXT, created TEXT, PRIMARY KEY(case_id,revision));
            CREATE TABLE IF NOT EXISTS reviews(case_id TEXT, revision INTEGER, status TEXT, note TEXT, created TEXT);
            CREATE TABLE IF NOT EXISTS usage(provider TEXT, units REAL, created TEXT);
            ''')

    def connect(self):
        c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row;return c

    def demo_secret(self):
        import secrets
        with self.connect() as c:
            c.executescript('CREATE TABLE IF NOT EXISTS demo_meta(name TEXT PRIMARY KEY,value TEXT);'
                            'CREATE TABLE IF NOT EXISTS demo_admissions(key TEXT PRIMARY KEY,session TEXT,created REAL);')
            c.execute('INSERT OR IGNORE INTO demo_meta VALUES(?,?)',('session_signing',secrets.token_hex(32)))
            return bytes.fromhex(c.execute('SELECT value FROM demo_meta WHERE name=?',('session_signing',)).fetchone()[0])

    def admit_demo(self,session,key,now):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM demo_admissions WHERE key=?',(key,)).fetchone():return False
            rows=c.execute('SELECT session FROM demo_admissions WHERE created>?',(now-3600,)).fetchall()
            if len(rows)>=3:raise ValueError('The shared demo has used its three live checks for this hour. View saved results or try made-up examples.')
            if sum(row['session']==session for row in rows)>=2:
                raise ValueError('This visitor session has used its two live checks for this hour. View saved results or try made-up examples.')
            c.execute('INSERT INTO demo_admissions VALUES(?,?,?)',(key,session,now))
            return True

    def demo_remaining(self,session,now):
        with self.connect() as c:
            rows=c.execute('SELECT session FROM demo_admissions WHERE created>?',(now-3600,)).fetchall()
        return {'shared_remaining':max(0,3-len(rows)),'session_remaining':max(0,2-sum(row['session']==session for row in rows)),
                'shared_limit':3,'session_limit':2,'window_seconds':3600}

    def create_batch(self,request):
        with self.connect() as c:
            old=c.execute('SELECT * FROM batches WHERE idem=?',(request['idempotency_key'],)).fetchone()
            if old:
                if json.loads(old['request'])!=request:raise ValueError('Idempotency key already used for another request.')
                return old['id'],False
            bid=uuid.uuid4().hex;c.execute('INSERT INTO batches VALUES(?,?,?,?)',(bid,request['idempotency_key'],json.dumps(request),utcnow().isoformat()))
            for item in request['cases']:
                cid=uuid.uuid4().hex;c.execute('INSERT INTO cases(id,batch_id,request,state) VALUES(?,?,?,?)',(cid,bid,json.dumps({**item,'mode':request['mode']}),'queued'))
            return bid,True

    def list_batches(self):
        with self.connect() as c:
            rows=c.execute('SELECT id,created,request FROM batches ORDER BY created DESC LIMIT 40').fetchall()
        result=[]
        for row in rows:
            request=json.loads(row['request']);cases=request.get('cases',[]);mode=request.get('mode')
            selected=bool(cases) and cases[0].get('reference_url')=='https://www.adafruit.com/product/6090' and cases[0].get('competitor_url')=='https://www.adafruit.com/product/6089'
            label=request.get('label') or ('Fictional examples' if mode=='sample' else 'Rule-test scenarios' if mode=='synthetic'
                   else 'Adafruit SSD comparison' if selected else (cases[0].get('sku') if cases else None) or 'Investigation')
            result.append({'id':row['id'],'created':row['created'],'label':label,'case_count':len(cases),'mode':mode})
        return result

    def batch(self,bid):
        with self.connect() as c:return [self._decode(x) for x in c.execute('SELECT * FROM cases WHERE batch_id=?',(bid,))]

    @staticmethod
    def _decode(row):
        if not row:return None
        d=dict(row)
        for k in ('request','result'):
            if d.get(k):d[k]=json.loads(d[k])
        return d

    def case(self,cid):
        with self.connect() as c:
            d=self._decode(c.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone())
            if d:
                d['reviews']=[dict(x) for x in c.execute('SELECT * FROM reviews WHERE case_id=? ORDER BY created DESC',(cid,))]
                d['history']=[{'revision':x['revision'],'result':json.loads(x['result']),'created':x['created']} for x in c.execute('SELECT * FROM revisions WHERE case_id=? ORDER BY revision DESC',(cid,))]
            return d

    def update_state(self,cid,state):
        with self.connect() as c:c.execute("UPDATE cases SET state=? WHERE id=? AND state!='cancelled'",(state,cid))

    def cancel(self,cid):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT state FROM cases WHERE id=?',(cid,)).fetchone()
            if not row:raise LookupError('Case not found.')
            if row['state']=='cancelled':return
            if row['state'] not in ('queued','collecting','investigating','validating'):
                raise ValueError('Only an active investigation can be cancelled.')
            c.execute("UPDATE cases SET state='cancelled' WHERE id=?",(cid,))

    def finish(self,cid,result,error=None,state='completed'):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
            if row['state']=='cancelled':return
            if row['result']:
                result={**result,'refresh_comparison':refresh_comparison(json.loads(row['result']),result,row['revision'])}
            rev=row['revision']+1;encoded=json.dumps(result)
            c.execute('INSERT INTO revisions VALUES(?,?,?,?)',(cid,rev,encoded,utcnow().isoformat()))
            c.execute('UPDATE cases SET state=?,revision=?,result=?,error=? WHERE id=?',(state,rev,encoded,error,cid))

    def review(self,cid,review):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT revision,state FROM cases WHERE id=?',(cid,)).fetchone()
            if not row:raise LookupError('Case not found.')
            if row['revision']!=review['revision'] or row['state'] not in ('completed','partial'):raise ValueError('This evidence changed or is still running. Reload before reviewing.')
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?)',(cid,review['revision'],review['status'],review['note'],utcnow().isoformat()))

    def attach_observation(self,cid,revision,observation):
        """Attach optional telemetry receipt only to the exact investigated revision."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT revision,result FROM cases WHERE id=?',(cid,)).fetchone()
            if not row or row['revision']!=revision or not row['result']:return False
            result=json.loads(row['result']);result['observability']=observation;encoded=json.dumps(result)
            c.execute('UPDATE cases SET result=? WHERE id=?',(encoded,cid))
            c.execute('UPDATE revisions SET result=? WHERE case_id=? AND revision=?',(encoded,cid,revision))
            return True

    def revise_evidence(self,cid,revision,transform):
        """Check and append atomically so refresh/other tabs cannot race a confirmation."""
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM cases WHERE id=?',(cid,)).fetchone()
            if not row:raise LookupError('Case not found.')
            if row['revision']!=revision or row['state'] not in ('completed','partial'):
                raise ValueError('Evidence changed or is running. Reload before confirming attributes.')
            if not row['result']:raise ValueError('Collected offer evidence is required.')
            result=transform(json.loads(row['result']));encoded=json.dumps(result);new_revision=revision+1
            c.execute('INSERT INTO revisions VALUES(?,?,?,?)',(cid,new_revision,encoded,utcnow().isoformat()))
            c.execute('UPDATE cases SET revision=?,result=? WHERE id=?',(new_revision,encoded,cid))
            return new_revision

    def requeue(self,cid):
        with self.connect() as c:
            row=c.execute('SELECT state FROM cases WHERE id=?',(cid,)).fetchone()
            if not row:raise LookupError('Case not found.')
            if row['state'] not in ('completed','partial','failed','cancelled','interrupted'):raise ValueError('Investigation is already running.')
            c.execute("UPDATE cases SET state='queued',error=NULL WHERE id=?",(cid,))

    def recover(self):
        with self.connect() as c:c.execute("UPDATE cases SET state='interrupted',error='Application restarted. Recheck to resume.' WHERE state IN ('queued','collecting','investigating','validating')")

    def reserve(self,provider,units,limit):
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE');used=c.execute('SELECT COALESCE(SUM(units),0) FROM usage WHERE provider=?',(provider,)).fetchone()[0]
            if used+units>limit:raise ValueError(f'{provider} local usage cap reached.')
            c.execute('INSERT INTO usage VALUES(?,?,?)',(provider,units,utcnow().isoformat()))

    def usage(self):
        with self.connect() as c:return {r[0]:r[1] for r in c.execute('SELECT provider,SUM(units) FROM usage GROUP BY provider')}
