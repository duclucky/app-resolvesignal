"""GS1 check-digit validation; a valid number is still a publisher assertion."""
import re

BARCODE_LABEL=re.compile(r'''\b(?:gtin(?:-?(?:8|12|13|14))?|upc(?:-a)?|ean(?:-13)?|barcode)["']?\s*[:#=]?\s*["']?([0-9][0-9 -]{6,24}[0-9])''',re.I)


def labeled_gtins(text):
    values={}
    for match in BARCODE_LABEL.finditer(text):
        value=re.sub(r'[ -]','',match[1])
        if valid_gtin(value):values[canonical_gtin(value)]=value
    return values

def valid_gtin(value):
    value=str(value)
    if len(value) not in (8,12,13,14) or not value.isascii() or not value.isdigit():return False
    total=sum(int(c)*(3 if i%2==0 else 1) for i,c in enumerate(reversed(value[:-1])))
    return (10-total%10)%10==int(value[-1])


def canonical_gtin(value):
    return str(value).zfill(14) if valid_gtin(value) else None
