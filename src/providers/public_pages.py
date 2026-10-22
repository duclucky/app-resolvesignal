import httpx
import asyncio
import threading
from time import monotonic
from urllib.parse import urljoin,urlsplit,urlunsplit
from ..policies import validate_url, is_selected_source,public_addresses
from ..parser import parse_offer, text_content


_schedule_lock = threading.Lock()
_next_source_request = 0.0
_sleep = asyncio.sleep


async def wait_for_source(url):
    """Space starts 15 seconds apart for the selected source in this local process."""
    if not is_selected_source(url):return
    global _next_source_request
    while True:
        with _schedule_lock:
            now=monotonic()
            delay=_next_source_request-now
            if delay<=0:
                _next_source_request=now+15.0
                return
        # Recheck after waking so concurrent/late wakeups cannot start together.
        await _sleep(delay)


async def retrieve(url):
    selected_source=is_selected_source(url)
    for _ in range(4):
        validate_url(url)
        await wait_for_source(url)
        # Pin the socket while TLS verifies the source host. A fresh client per
        # redirect prevents two CDN hosts sharing an IP from sharing a TLS pool.
        parts=urlsplit(url);host=parts.hostname.encode('idna').decode('ascii')
        address=public_addresses(host)[0]
        pinned=urlunsplit((parts.scheme,'['+address+']' if ':' in address else address,parts.path,parts.query,''))
        async with httpx.AsyncClient(timeout=18,follow_redirects=False,trust_env=False,headers={'User-Agent':'PriceAlertInvestigator/0.1 (public product research)'}) as client:
            async with client.stream('GET',pinned,headers={'Host':host},extensions={'sni_hostname':host}) as r:
                if r.is_redirect:
                    url=urljoin(url,r.headers['location'])
                    if selected_source and not is_selected_source(url):
                        raise ValueError('Redirect left the two selected source pages.')
                    continue
                r.raise_for_status()
                if 'text/html' not in r.headers.get('content-type',''):raise ValueError('Source is not an HTML product page.')
                chunks=[];size=0
                async for chunk in r.aiter_bytes():
                    size+=len(chunk)
                    if size>4_000_000:raise ValueError('Source page exceeds the size limit.')
                    chunks.append(chunk)
                html=b''.join(chunks).decode('utf-8',errors='replace')
                return parse_offer(html,url),text_content(html)[:24000]
    raise ValueError('Too many redirects.')
