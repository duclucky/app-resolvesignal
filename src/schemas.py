from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, StrictInt, StrictStr, StrictBool, model_validator


def utcnow():
    return datetime.now(timezone.utc)


class Evidence(BaseModel):
    id: str
    url: str
    excerpt: str
    field: str
    retrieved_at: datetime | None = Field(default_factory=utcnow)
    provider: str = 'public_page'
    origin: Literal['retrieved','operator_confirmed'] = 'retrieved'
    subject_url: str | None = None
    confirmation_id: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class Offer(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)
    url: str
    title: str = ''
    category: Literal['ssd', 'keyboard', 'general', 'unknown'] = 'unknown'
    mpn: str | None = None
    gtin: str | None = None
    seller_sku: str | None = None
    brand: str | None = None
    capacity: str | None = None
    layout: str | None = None
    switch: str | None = None
    condition: Literal['new','refurbished','open_box','used','damaged'] | None = None
    quantity: int | None = None
    price: Decimal | None = None
    currency: str | None = None
    availability: Literal['in_stock','out_of_stock','preorder','backorder'] | None = None
    eligibility: Literal['unconditional','conditional','membership','trade_in','rebate'] | None = None
    price_basis: Literal['listed_item'] | None = None
    shipping: str | None = None
    tax: str | None = None
    observed_at: datetime = Field(default_factory=utcnow)
    evidence: list[Evidence] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    outcome: str = 'INSUFFICIENT_EVIDENCE'
    action: str = 'REQUEST_REVIEW'
    evidence_basis: Literal['retrieved_only','operator_assisted'] = 'retrieved_only'
    reasons: list[str] = Field(default_factory=list)
    matched: list[str] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)
    gap_percent: str | None = None
    gap_amount: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=lambda: ['Listed prices only. Shipping and tax may differ.'])


class CaseInput(BaseModel):
    sku: str = Field(default='', max_length=100)
    reference_url: str = Field(max_length=2048)
    competitor_url: str = Field(max_length=2048)


class BatchInput(BaseModel):
    cases: list[CaseInput] = Field(min_length=1, max_length=25)
    idempotency_key: str = Field(min_length=8, max_length=120)
    mode: Literal['public', 'live'] = 'public'


class ReviewInput(BaseModel):
    revision: int
    status: Literal['reviewed', 'disputed', 'follow_up']
    note: str = Field(default='', max_length=2000)


class ConfirmationItem(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    side: Literal['reference','competitor']
    field: Literal['condition','quantity','eligibility','layout','switch','capacity','mpn','brand']
    value: StrictInt | StrictStr
    source_url: str = Field(min_length=10,max_length=2048)
    excerpt: str = Field(min_length=12,max_length=1000)

    @model_validator(mode='after')
    def validate_attribute(self):
        from urllib.parse import urlsplit,parse_qs
        from .policies import validate_url
        validate_url(self.source_url,resolve=False)
        query=parse_qs(urlsplit(self.source_url).query,keep_blank_values=True)
        if any(k.lower() in ('api_key','apikey','token','secret','password','auth','authorization','key') for k in query):
            raise ValueError('Use a public source URL without authentication parameters.')
        if self.field=='quantity':
            if type(self.value) is not int or not 1<=self.value<=10000:raise ValueError('Pack quantity must be an integer from 1 to 10000.')
        elif not isinstance(self.value,str) or not 1<=len(self.value.strip())<=120:
            raise ValueError('Attribute value must be nonempty text up to 120 characters.')
        # Reuse the actual offer type contract, including condition/eligibility enums.
        Offer(url=self.source_url,**{self.field:self.value})
        return self


class ConfirmationInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    revision: int = Field(ge=1)
    confirmed_by: str = Field(min_length=2,max_length=80)
    attested: StrictBool
    items: list[ConfirmationItem] = Field(min_length=1,max_length=12)

    @model_validator(mode='after')
    def require_attestation(self):
        if not self.attested:raise ValueError('Explicit source attestation is required.')
        return self


class WithdrawalInput(BaseModel):
    model_config = ConfigDict(extra='forbid',str_strip_whitespace=True)
    revision: int = Field(ge=1)
    note: str = Field(default='',max_length=500)
