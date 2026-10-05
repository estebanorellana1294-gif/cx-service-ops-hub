"""Canonical ticket model: the internal, source-independent view of a ticket.

Downstream components (rules engine, KPI dashboard) only ever see this model.
If NorthPeak later adds a second ticketing source, only a new mapper is
needed; rules and KPIs stay untouched.

Vocabulary is business-facing (``P1``, ``waiting_on_customer``) rather than
source codes (``ORA_SVC_SEV1``, ``ORA_SVC_WAITING``).
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TicketStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WAITING_ON_CUSTOMER = "waiting_on_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


OPEN_STATUSES = frozenset({TicketStatus.NEW, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_CUSTOMER})


class Priority(StrEnum):
    P1 = "P1"  # Critical
    P2 = "P2"  # High
    P3 = "P3"  # Medium
    P4 = "P4"  # Low


class Queue(StrEnum):
    NETWORK_OPS = "NETWORK_OPS"
    BILLING = "BILLING"
    FIELD_INSTALL = "FIELD_INSTALL"
    TECH_SUPPORT = "TECH_SUPPORT"
    RETENTION = "RETENTION"
    UNMAPPED = "UNMAPPED"


class Category(StrEnum):
    OUTAGE = "outage"
    BILLING = "billing"
    INSTALLATION = "installation"
    SLOW_SPEED = "slow_speed"
    EQUIPMENT = "equipment"
    CANCELLATION = "cancellation"
    UNCATEGORIZED = "uncategorized"


class Channel(StrEnum):
    PHONE = "phone"
    EMAIL = "email"
    WEB = "web"
    CHAT = "chat"
    OTHER = "other"


class Ticket(BaseModel):
    model_config = ConfigDict(frozen=True)

    ticket_id: str
    source_system: str
    source_record_id: str | None
    title: str
    description: str | None
    status: TicketStatus
    is_open: bool
    priority: Priority
    queue: Queue
    queue_name: str | None
    category: Category
    channel: Channel
    customer_name: str | None
    assignee: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolution_hours: float | None
    data_quality_flags: tuple[str, ...] = ()

    def age_hours(self, as_of: datetime) -> float:
        """Hours since creation (open tickets) or until resolution (closed ones)."""
        end = self.resolved_at or as_of
        return round((end - self.created_at).total_seconds() / 3600, 2)
