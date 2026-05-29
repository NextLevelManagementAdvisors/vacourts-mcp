"""Normalized output schema shared by bulk + live layers."""
from pydantic import BaseModel
from typing import Optional

class Hearing(BaseModel):
    date: Optional[str] = None
    type: Optional[str] = None
    result: Optional[str] = None
    room: Optional[str] = None

class CaseRecord(BaseModel):
    source: str               # "bulk" | "ocis" | "cjisweb"
    court_level: str          # "circuit" | "gd"
    court_code: str           # 3-digit locality code (FIPS) -> joins bulk + localities.yaml
    court_name: str
    division: str             # "civil" | "criminal" | "traffic"
    case_number: str
    party_name: str
    role: Optional[str] = None        # defendant / plaintiff / etc
    charge_or_cause: Optional[str] = None
    status: Optional[str] = None
    filed_date: Optional[str] = None
    disposition: Optional[str] = None
    disposition_date: Optional[str] = None
    hearings: list[Hearing] = []
    fetched_at: Optional[str] = None
    raw_url: Optional[str] = None
