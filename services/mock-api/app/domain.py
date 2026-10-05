"""Reference data for the NorthPeak Connect service desk.

Lookup codes follow the ``ORA_SVC_*`` naming pattern seen in the public
Oracle Fusion Service documentation. They are approximations for a demo,
see docs/api-assumptions.md.
"""

from enum import StrEnum


class StatusCd(StrEnum):
    NEW = "ORA_SVC_NEW"
    IN_PROGRESS = "ORA_SVC_INPROGRESS"
    WAITING = "ORA_SVC_WAITING"
    RESOLVED = "ORA_SVC_RESOLVED"
    CLOSED = "ORA_SVC_CLOSED"


class StatusTypeCd(StrEnum):
    """Coarse lifecycle bucket derived from StatusCd."""

    OPEN = "ORA_SVC_OPEN"
    CLOSED = "ORA_SVC_CLOSED"


class SeverityCd(StrEnum):
    SEV1 = "ORA_SVC_SEV1"  # Critical: service down / many customers affected
    SEV2 = "ORA_SVC_SEV2"  # High: single customer fully down
    SEV3 = "ORA_SVC_SEV3"  # Medium: degraded service / billing dispute
    SEV4 = "ORA_SVC_SEV4"  # Low: information request / cosmetic


class ChannelTypeCd(StrEnum):
    PHONE = "ORA_SVC_PHONE"
    EMAIL = "ORA_SVC_EMAIL"
    WEB = "ORA_SVC_WEB"
    CHAT = "ORA_SVC_CHAT"


OPEN_STATUSES = frozenset({StatusCd.NEW, StatusCd.IN_PROGRESS, StatusCd.WAITING})


def status_type_for(status: StatusCd) -> StatusTypeCd:
    return StatusTypeCd.OPEN if status in OPEN_STATUSES else StatusTypeCd.CLOSED


# QueueId -> QueueName. Numeric ids mimic the surrogate keys of a real CRM.
QUEUES: dict[int, str] = {
    300100001: "Network Operations",
    300100002: "Billing Support",
    300100003: "Field Installation",
    300100004: "Technical Support",
    300100005: "Customer Retention",
}

QUEUE_ID_BY_NAME: dict[str, int] = {name: qid for qid, name in QUEUES.items()}

CATEGORIES: tuple[str, ...] = (
    "Outage",
    "Billing",
    "Installation",
    "Slow Speed",
    "Equipment",
    "Cancellation",
)
