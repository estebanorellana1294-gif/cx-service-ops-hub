"""Source ``serviceRequests`` record -> canonical :class:`Ticket`.

Every rule here is documented, with its business reason, in
docs/field-mapping.md. Keep the two in sync.

Error policy
------------
* **Reject** (raise :class:`MappingError`) only when the record cannot be
  identified or placed in time: missing ``SrNumber`` or ``CreationDate``.
  A ticket without them cannot be tracked against an SLA.
* **Default and flag** everything else: an unknown severity becomes P3 with a
  ``UNKNOWN_SEVERITY`` flag. The ticket still reaches the backlog and the
  KPIs, and the flag tells data stewards what to fix at the source.
"""

import re
from datetime import UTC, datetime
from typing import Any

from .canonical import OPEN_STATUSES, Category, Channel, Priority, Queue, Ticket, TicketStatus
from .errors import MappingError

SOURCE_SYSTEM = "fusion-service-mock"
TITLE_MAX_LENGTH = 200
MISSING_TITLE = "(no title)"

STATUS_MAP = {
    "ORA_SVC_NEW": TicketStatus.NEW,
    "ORA_SVC_INPROGRESS": TicketStatus.IN_PROGRESS,
    "ORA_SVC_WAITING": TicketStatus.WAITING_ON_CUSTOMER,
    "ORA_SVC_RESOLVED": TicketStatus.RESOLVED,
    "ORA_SVC_CLOSED": TicketStatus.CLOSED,
}

STATUS_TYPE_OPEN = {"ORA_SVC_OPEN": True, "ORA_SVC_CLOSED": False}

PRIORITY_MAP = {
    "ORA_SVC_SEV1": Priority.P1,
    "ORA_SVC_SEV2": Priority.P2,
    "ORA_SVC_SEV3": Priority.P3,
    "ORA_SVC_SEV4": Priority.P4,
}
DEFAULT_PRIORITY = Priority.P3

# Keyed by QueueId: ids are stable, display names get renamed by admins.
QUEUE_BY_ID = {
    300100001: Queue.NETWORK_OPS,
    300100002: Queue.BILLING,
    300100003: Queue.FIELD_INSTALL,
    300100004: Queue.TECH_SUPPORT,
    300100005: Queue.RETENTION,
}
QUEUE_BY_NAME = {
    "network operations": Queue.NETWORK_OPS,
    "billing support": Queue.BILLING,
    "field installation": Queue.FIELD_INSTALL,
    "technical support": Queue.TECH_SUPPORT,
    "customer retention": Queue.RETENTION,
}

CATEGORY_MAP = {
    "outage": Category.OUTAGE,
    "billing": Category.BILLING,
    "installation": Category.INSTALLATION,
    "slow speed": Category.SLOW_SPEED,
    "equipment": Category.EQUIPMENT,
    "cancellation": Category.CANCELLATION,
    "uncategorized": Category.UNCATEGORIZED,
}

CHANNEL_MAP = {
    "ORA_SVC_PHONE": Channel.PHONE,
    "ORA_SVC_EMAIL": Channel.EMAIL,
    "ORA_SVC_WEB": Channel.WEB,
    "ORA_SVC_CHAT": Channel.CHAT,
}


class _Flags:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, code: str) -> None:
        if code not in self.items:
            self.items.append(code)


def map_service_request(record: dict[str, Any], *, source_system: str = SOURCE_SYSTEM) -> Ticket:
    if not isinstance(record, dict):
        raise MappingError(None, "<record>", f"expected an object, got {type(record).__name__}")

    flags = _Flags()
    ticket_id = _clean(record.get("SrNumber"))
    if not ticket_id:
        raise MappingError(None, "SrNumber", "missing business key")

    created_at = _parse_ts(record.get("CreationDate"), flags)
    if created_at is None:
        raise MappingError(ticket_id, "CreationDate", "missing or not an ISO 8601 timestamp")

    status = _map_status(record, flags)
    is_open = status in OPEN_STATUSES

    updated_at = _parse_ts(record.get("LastUpdateDate"), flags) or created_at
    if updated_at < created_at:
        flags.add("UPDATED_BEFORE_CREATED")
        updated_at = created_at

    resolved_at = _map_resolved_at(record, created_at, is_open, flags)
    resolution_hours = (
        round((resolved_at - created_at).total_seconds() / 3600, 2) if resolved_at else None
    )

    return Ticket(
        ticket_id=ticket_id,
        source_system=source_system,
        source_record_id=_clean(record.get("SrId")),
        title=_map_title(record.get("Title"), flags),
        description=_clean(record.get("ProblemDescription")),
        status=status,
        is_open=is_open,
        priority=_lookup(PRIORITY_MAP, record.get("SeverityCd"), DEFAULT_PRIORITY, "UNKNOWN_SEVERITY", flags),
        queue=_map_queue(record, flags),
        queue_name=_clean(record.get("QueueName")),
        category=_map_category(record.get("CategoryName"), flags),
        channel=_lookup(CHANNEL_MAP, record.get("ChannelTypeCd"), Channel.OTHER, "UNKNOWN_CHANNEL", flags),
        customer_name=_clean(record.get("PrimaryContactPartyName")),
        assignee=_clean(record.get("AssigneeResourceName")),
        created_at=created_at,
        updated_at=updated_at,
        resolved_at=resolved_at,
        resolution_hours=resolution_hours,
        data_quality_flags=tuple(flags.items),
    )


# -- field rules -------------------------------------------------------------


def _map_status(record: dict[str, Any], flags: _Flags) -> TicketStatus:
    status = STATUS_MAP.get(record.get("StatusCd"))
    status_type_open = STATUS_TYPE_OPEN.get(record.get("StatusTypeCd"))
    if status is None:
        flags.add("UNKNOWN_STATUS")
        # Fall back to the coarse lifecycle bucket; when even that is
        # missing, assume open so the ticket is not hidden from the backlog.
        return TicketStatus.CLOSED if status_type_open is False else TicketStatus.IN_PROGRESS
    if status_type_open is not None and status_type_open != (status in OPEN_STATUSES):
        flags.add("STATUS_TYPE_MISMATCH")
    return status


def _map_resolved_at(
    record: dict[str, Any], created_at: datetime, is_open: bool, flags: _Flags
) -> datetime | None:
    resolved_at = _parse_ts(record.get("ResolvedDate"), flags)
    if is_open:
        if resolved_at is not None:
            flags.add("RESOLVED_DATE_ON_OPEN_TICKET")
        return None
    if resolved_at is None:
        flags.add("MISSING_RESOLVED_DATE")
        return None
    if resolved_at < created_at:
        flags.add("RESOLVED_BEFORE_CREATED")
        return None
    return resolved_at


def _map_queue(record: dict[str, Any], flags: _Flags) -> Queue:
    queue_id = record.get("QueueId")
    try:
        queue = QUEUE_BY_ID.get(int(queue_id)) if queue_id is not None else None
    except (TypeError, ValueError):
        queue = None
    if queue is not None:
        return queue
    by_name = QUEUE_BY_NAME.get((_clean(record.get("QueueName")) or "").lower())
    if by_name is not None:
        flags.add("QUEUE_MATCHED_BY_NAME")
        return by_name
    flags.add("UNKNOWN_QUEUE")
    return Queue.UNMAPPED


def _map_category(value: Any, flags: _Flags) -> Category:
    text = _clean(value)
    if text is None:
        return Category.UNCATEGORIZED  # expected for un-triaged tickets, not a defect
    normalized = re.sub(r"[\s_-]+", " ", text).lower()
    category = CATEGORY_MAP.get(normalized)
    if category is None:
        flags.add("UNKNOWN_CATEGORY")
        return Category.UNCATEGORIZED
    return category


def _map_title(value: Any, flags: _Flags) -> str:
    text = _clean(value)
    if text is None:
        flags.add("MISSING_TITLE")
        return MISSING_TITLE
    text = re.sub(r"\s+", " ", text)
    if len(text) > TITLE_MAX_LENGTH:
        flags.add("TITLE_TRUNCATED")
        text = text[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return text


# -- helpers -----------------------------------------------------------------


def _lookup(table: dict, value: Any, default: Any, flag: str, flags: _Flags) -> Any:
    try:
        return table[value]
    except (KeyError, TypeError):
        flags.add(flag)
        return default


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_ts(value: Any, flags: _Flags) -> datetime | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        flags.add("INVALID_TIMESTAMP")
        return None
    if parsed.tzinfo is None:
        flags.add("NAIVE_TIMESTAMP_ASSUMED_UTC")
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
