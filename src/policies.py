import ipaddress
import socket
from urllib.parse import urlsplit

DEFAULT_DOMAINS = ('samsung.com','bestbuy.com','newegg.com','bhphotovideo.com','keychron.com','crucial.com','logitech.com',
                   'mechanicalkeyboards.com','serverpartdeals.com','adafruit.com')
SELECTED_SOURCE_URLS = ('https://www.adafruit.com/product/6090','https://www.adafruit.com/product/6089')


def is_selected_source(url):
    return url in SELECTED_SOURCE_URLS or url in tuple(u.replace('www.adafruit.com','adafruit.com') for u in SELECTED_SOURCE_URLS)


def comparison_scope(reference_url, competitor_url):
    if all(is_selected_source(url) for url in (reference_url,competitor_url)):
        return {'kind':'same_merchant_variant_control',
                'notice':'Same-merchant source control; not a competitor-price opportunity. Compare the selected variants and check stock and retrieval times.',
                'reference_label':'Reference variant','competitor_label':'Compared variant'}
    hosts=[urlsplit(url or '').hostname for url in (reference_url,competitor_url)]
    if all(hosts) and hosts[0].removeprefix('www.')==hosts[1].removeprefix('www.'):
        return {'kind':'same_merchant_control',
                'notice':'Both offers are from the same store. This is not a comparison between competing stores.'}
    return None


def public_addresses(host):
    addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    values=list(dict.fromkeys(a[4][0] for a in addresses))
    if not values or any(not ipaddress.ip_address(value).is_global for value in values):
        raise ValueError('The address must resolve only to public IPs.')
    return sorted(values,key=lambda value:':' in value)


def validate_url(url, domains=None, resolve=True):
    try:
        u=urlsplit(url)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None,443):
            raise ValueError('Use a public HTTPS product URL without credentials or a custom port.')
        host=u.hostname.lower().rstrip('.')
        if any(char.isspace() or ord(char)<32 for char in url) or '\\' in url or '%' in host:
            raise ValueError('Use a complete public HTTPS product URL.')
        if host=='localhost' or host.endswith(('.localhost','.local','.internal','.lan','.home')) or '.' not in host and ':' not in host:
            raise ValueError('Local and private addresses are not product websites.')
        try:literal=ipaddress.ip_address(host)
        except ValueError:literal=None
        if literal is not None and not literal.is_global:
            raise ValueError('Local and private addresses are not product websites.')
        if domains is not None and not any(host==d or host.endswith('.'+d) for d in domains):
            raise ValueError('This domain is not in the supported source list.')
        if resolve:
            public_addresses(host)
        return url
    except (OSError,ValueError) as exc:
        raise ValueError(str(exc)) from None


def safe_csv(value):
    value=str(value or '')
    return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r')) else value
