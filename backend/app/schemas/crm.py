"""CRM seed records and identity lookup; a phone can map to multiple customers."""

from datetime import date

from pydantic import BaseModel, Field, model_validator

from .common import Channel, NonNegativeVND, Outcome, PhoneNumber


class CRMOrder(BaseModel):
    order_id: str
    sku: str
    price_vnd: NonNegativeVND
    date: date
    status: str
    tracking: str | None = None


class CRMSession(BaseModel):
    session_id: str
    date: date
    channel: Channel
    summary: str
    outcome: Outcome


class CustomerRecord(BaseModel):
    customer_id: str
    name: str
    honorific: str
    phone: PhoneNumber
    zalo_id: str | None = None
    fb_id: str | None = None
    region: str
    orders: list[CRMOrder] = Field(default_factory=list)
    sessions: list[CRMSession] = Field(default_factory=list)
    shared_phone_with: str | None = None


class CRMSeed(BaseModel):
    customers: list[CustomerRecord]
    notes: str | list[str] | None = None


class CustomerLookup(BaseModel):
    phone: PhoneNumber | None = None
    zalo_id: str | None = None
    fb_id: str | None = None

    @model_validator(mode="after")
    def require_identity(self) -> "CustomerLookup":
        if not any((self.phone, self.zalo_id, self.fb_id)):
            raise ValueError("Provide phone, zalo_id or fb_id")
        return self


class CustomerLookupResult(BaseModel):
    found: bool
    ambiguous: bool = False
    customer_id: str | None = None
    name: str | None = None
    honorific: str | None = None
    phone: PhoneNumber | None = None
    identities: dict[str, str | None] = Field(default_factory=dict)
    orders: list[CRMOrder] = Field(default_factory=list)
    sessions: list[CRMSession] = Field(default_factory=list)
    candidates: list["CustomerCandidate"] = Field(default_factory=list)


class CustomerCandidate(BaseModel):
    customer_id: str
    name: str
    honorific: str
    sessions: list[CRMSession] = Field(default_factory=list)
    orders: list[CRMOrder] = Field(default_factory=list)
