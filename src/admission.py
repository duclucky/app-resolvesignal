"""Anonymous visitor fairness within the persistent, unchanged shared allowance."""
import hashlib
import hmac
import re
import secrets
import time

COOKIE='resolvesignal_visitor'


class DemoAdmission:
    def __init__(self,store):
        self.store=store;self.secret=store.demo_secret()

    def identify(self,cookie,now=None):
        now=time.time() if now is None else now
        valid=False
        if isinstance(cookie,str) and re.fullmatch(r'[a-f0-9]{32}\.[0-9]{1,12}\.[a-f0-9]{64}',cookie):
            identity,issued,signature=cookie.split('.')
            expected=hmac.new(self.secret,(identity+'.'+issued).encode(),'sha256').hexdigest()
            valid=hmac.compare_digest(expected,signature) and -60<=now-int(issued)<7*86400
        if not valid:
            identity=secrets.token_hex(16);issued=str(int(now))
            signature=hmac.new(self.secret,(identity+'.'+issued).encode(),'sha256').hexdigest()
            cookie=identity+'.'+issued+'.'+signature
        return hashlib.sha256(identity.encode()).hexdigest(),cookie

    def admit(self,session,key,now=None):
        return self.store.admit_demo(session,key,time.time() if now is None else now)

    def remaining(self,session,now=None):
        return self.store.demo_remaining(session,time.time() if now is None else now)
