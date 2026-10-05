from datetime import UTC, datetime

import pytest

from cx_integration.canonical import Category, Channel, Priority, Queue, TicketStatus
from cx_integration.errors import MappingError
from cx_integration.mapping import MISSING_TITLE, TITLE_MAX_LENGTH, map_service_request
from tests.conftest import record


def test_maps_a_clean_closed_record():
    t = map_service_request(record(1))
    assert t.ticket_id == "SR0000010001"
    assert t.source_system == "fusion-service-mock" and t.source_record_id == "10001"
    assert t.status is TicketStatus.CLOSED and t.is_open is False
    assert t.priority is Priority.P1
    assert t.queue is Queue.NETWORK_OPS and t.queue_name == "Network Operations"
    assert t.category is Category.OUTAGE
    assert t.channel is Channel.PHONE
    assert t.created_at == datetime(2026, 9, 15, 9, 0, tzinfo=UTC)
    assert t.resolved_at == datetime(2026, 9, 15, 14, 30, tzinfo=UTC)
    assert t.resolution_hours == 5.5
    assert t.data_quality_flags == ()


def test_maps_an_open_record():
    t = map_service_request(
        record(2, StatusCd="ORA_SVC_WAITING", StatusTypeCd="ORA_SVC_OPEN", ResolvedDate=None)
    )
    assert t.status is TicketStatus.WAITING_ON_CUSTOMER and t.is_open
    assert t.resolved_at is None and t.resolution_hours is None
    assert t.age_hours(datetime(2026, 9, 16, 9, 0, tzinfo=UTC)) == 24.0
    assert t.data_quality_flags == ()


@pytest.mark.parametrize(
    ("source", "expected"),
    [("ORA_SVC_NEW", "new"), ("ORA_SVC_INPROGRESS", "in_progress"), ("ORA_SVC_WAITING", "waiting_on_customer"),
     ("ORA_SVC_RESOLVED", "resolved"), ("ORA_SVC_CLOSED", "closed")],
)
def test_status_lookup(source, expected):
    is_open = expected in {"new", "in_progress", "waiting_on_customer"}
    t = map_service_request(
        record(3, StatusCd=source, StatusTypeCd="ORA_SVC_OPEN" if is_open else "ORA_SVC_CLOSED",
               ResolvedDate=None if is_open else "2026-09-15T14:30:00Z")
    )
    assert t.status == expected and t.is_open is is_open


@pytest.mark.parametrize(
    ("source", "expected"),
    [("ORA_SVC_SEV1", "P1"), ("ORA_SVC_SEV2", "P2"), ("ORA_SVC_SEV3", "P3"), ("ORA_SVC_SEV4", "P4")],
)
def test_priority_lookup(source, expected):
    assert map_service_request(record(4, SeverityCd=source)).priority == expected


@pytest.mark.parametrize(
    ("queue_id", "expected"),
    [(300100001, "NETWORK_OPS"), (300100002, "BILLING"), (300100003, "FIELD_INSTALL"),
     (300100004, "TECH_SUPPORT"), (300100005, "RETENTION"), ("300100002", "BILLING")],
)
def test_queue_lookup_by_id(queue_id, expected):
    t = map_service_request(record(5, QueueId=queue_id, QueueName="Renamed By Admin"))
    assert t.queue == expected and t.data_quality_flags == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Slow Speed", "slow_speed"), ("slow_speed", "slow_speed"), ("  BILLING ", "billing"),
     ("slow-speed", "slow_speed"), (None, "uncategorized"), ("Uncategorized", "uncategorized")],
)
def test_category_normalization(raw, expected):
    t = map_service_request(record(6, CategoryName=raw))
    assert t.category == expected and t.data_quality_flags == ()


def test_text_fields_are_trimmed_and_blank_becomes_null():
    t = map_service_request(
        record(7, Title="  Router   keeps \n rebooting ", ProblemDescription="   ",
               AssigneeResourceName="", PrimaryContactPartyName="  Ava Ashford ")
    )
    assert t.title == "Router keeps rebooting"
    assert t.description is None and t.assignee is None
    assert t.customer_name == "Ava Ashford"


def test_timestamps_are_normalized_to_utc():
    t = map_service_request(record(8, CreationDate="2026-09-15T04:00:00-05:00"))
    assert t.created_at == datetime(2026, 9, 15, 9, 0, tzinfo=UTC)


# --- data quality flags (record kept, value defaulted) --------------------------------


@pytest.mark.parametrize(
    ("overrides", "flag", "check"),
    [
        ({"SeverityCd": "URGENT"}, "UNKNOWN_SEVERITY", lambda t: t.priority is Priority.P3),
        ({"SeverityCd": None}, "UNKNOWN_SEVERITY", lambda t: t.priority is Priority.P3),
        ({"ChannelTypeCd": "ORA_SVC_FAX"}, "UNKNOWN_CHANNEL", lambda t: t.channel is Channel.OTHER),
        ({"CategoryName": "Pizza"}, "UNKNOWN_CATEGORY", lambda t: t.category is Category.UNCATEGORIZED),
        ({"QueueId": None}, "QUEUE_MATCHED_BY_NAME", lambda t: t.queue is Queue.NETWORK_OPS),
        ({"QueueId": 1, "QueueName": "Mystery"}, "UNKNOWN_QUEUE", lambda t: t.queue is Queue.UNMAPPED),
        ({"QueueId": "abc", "QueueName": None}, "UNKNOWN_QUEUE", lambda t: t.queue is Queue.UNMAPPED),
        ({"Title": "   "}, "MISSING_TITLE", lambda t: t.title == MISSING_TITLE),
        ({"Title": "x" * 300}, "TITLE_TRUNCATED", lambda t: len(t.title) == TITLE_MAX_LENGTH),
        ({"StatusCd": "ORA_SVC_ESCALATED", "StatusTypeCd": "ORA_SVC_OPEN", "ResolvedDate": None},
         "UNKNOWN_STATUS", lambda t: t.status is TicketStatus.IN_PROGRESS and t.is_open),
        ({"StatusCd": "ORA_SVC_ARCHIVED"}, "UNKNOWN_STATUS",
         lambda t: t.status is TicketStatus.CLOSED and t.resolution_hours == 5.5),
        ({"StatusCd": None, "StatusTypeCd": None, "ResolvedDate": None}, "UNKNOWN_STATUS",
         lambda t: t.is_open),
        ({"StatusTypeCd": "ORA_SVC_OPEN"}, "STATUS_TYPE_MISMATCH", lambda t: t.is_open is False),
        ({"StatusCd": "ORA_SVC_INPROGRESS", "StatusTypeCd": "ORA_SVC_OPEN"}, "RESOLVED_DATE_ON_OPEN_TICKET",
         lambda t: t.resolved_at is None),
        ({"ResolvedDate": None}, "MISSING_RESOLVED_DATE", lambda t: t.resolution_hours is None),
        ({"ResolvedDate": "2026-09-14T00:00:00Z"}, "RESOLVED_BEFORE_CREATED", lambda t: t.resolved_at is None),
        ({"ResolvedDate": "yesterday"}, ("INVALID_TIMESTAMP", "MISSING_RESOLVED_DATE"),
         lambda t: t.resolved_at is None),
        ({"LastUpdateDate": "2026-09-01T00:00:00Z"}, "UPDATED_BEFORE_CREATED",
         lambda t: t.updated_at == t.created_at),
        ({"LastUpdateDate": None}, None, lambda t: t.updated_at == t.created_at),
        ({"CreationDate": "2026-09-15T09:00:00"}, "NAIVE_TIMESTAMP_ASSUMED_UTC",
         lambda t: t.created_at.tzinfo is UTC),
    ],
)
def test_defects_are_defaulted_and_flagged(overrides, flag, check):
    t = map_service_request(record(10, **overrides))
    expected = flag if isinstance(flag, tuple) else (flag,) if flag else ()
    assert t.data_quality_flags == expected
    assert check(t)


def test_flags_are_not_duplicated():
    t = map_service_request(
        record(11, CreationDate="2026-09-15T09:00:00", LastUpdateDate="2026-09-15T10:00:00",
               ResolvedDate="2026-09-15T11:00:00")
    )
    assert t.data_quality_flags == ("NAIVE_TIMESTAMP_ASSUMED_UTC",)


# --- rejections ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "field"),
    [({"SrNumber": None}, "SrNumber"), ({"SrNumber": "  "}, "SrNumber"),
     ({"CreationDate": None}, "CreationDate"), ({"CreationDate": "not a date"}, "CreationDate")],
)
def test_unidentifiable_records_are_rejected(overrides, field):
    with pytest.raises(MappingError) as info:
        map_service_request(record(12, **overrides))
    assert info.value.field == field


def test_non_object_record_is_rejected():
    with pytest.raises(MappingError):
        map_service_request(["not", "a", "dict"])  # type: ignore[arg-type]


def test_ticket_is_immutable():
    t = map_service_request(record(13))
    with pytest.raises(Exception):
        t.priority = Priority.P4  # type: ignore[misc]
