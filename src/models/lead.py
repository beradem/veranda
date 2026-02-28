"""Standardized Lead model used across all Veranda data engines."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LeadSource(str, Enum):
    """Where the lead was discovered."""

    SEC_EDGAR = "sec_edgar"
    TAX_ASSESSOR = "tax_assessor"
    PROFESSIONAL_MAPPING = "professional_mapping"
    FEC_CAMPAIGN_FINANCE = "fec_campaign_finance"
    MANUAL = "manual"


class OutreachStatus(str, Enum):
    """Current state of outreach for this lead."""

    PENDING = "pending"
    DRAFT_READY = "draft_ready"
    APPROVED = "approved"
    SENT = "sent"
    OPENED = "opened"
    REPLIED = "replied"
    BOOKED = "booked"


class Lead(BaseModel):
    """A single prospective lead identified by a Veranda engine.

    Every engine (SEC EDGAR, Real Estate, Professional Mapping) outputs
    data into this standardized format so the rest of the pipeline can
    work with a consistent shape.
    """

    # Identity
    first_name: str
    last_name: str
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    address: Optional[str] = None

    # Professional
    professional_title: Optional[str] = None
    company: Optional[str] = None
    linkedin_url: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None

    # Wealth signals
    estimated_wealth: Optional[float] = Field(
        default=None, description="Estimated wealth or transaction value in USD"
    )
    discovery_trigger: str = Field(
        description="The event or signal that surfaced this lead, "
        "e.g. 'Sold $5.2M in AAPL stock on 2025-12-01'"
    )

    # Property details (populated by Real Estate engine)
    year_built: Optional[int] = None
    num_floors: Optional[int] = None
    building_area: Optional[int] = None
    lot_area: Optional[int] = None
    building_type: Optional[str] = None
    unit_number: Optional[str] = None
    deed_sale_amount: Optional[float] = None
    deed_date: Optional[str] = None

    # Metadata
    source: LeadSource
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="0.0 to 1.0 — higher means more data points confirmed"
    )
    discovered_at: datetime = Field(default_factory=datetime.utcnow)

    # Outreach
    outreach_status: OutreachStatus = OutreachStatus.PENDING
    outreach_draft: Optional[str] = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"
