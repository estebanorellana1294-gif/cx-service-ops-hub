"""Contract tests: the integration layer against the real mock API, in-process.

Starlette's TestClient is an ``httpx.Client``, so it can be injected into
:class:`ServiceRequestClient` without a running server.
"""

import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

MOCK_API_DIR = Path(__file__).resolve().parents[2] / "mock-api"
sys.path.insert(0, str(MOCK_API_DIR))
mock_main = pytest.importorskip("app.main", reason="mock-api sources not available")
from app.seed import generate_tickets  # noqa: E402
from app.store import ServiceRequestStore  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from cx_integration import (  # noqa: E402
    NotFoundError,
    RetryPolicy,
    ServiceRequestClient,
    TicketStatus,
    extract_tickets,
    map_service_request,
)
from cx_integration.__main__ import main as cli_main  # noqa: E402

REFERENCE_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def _client(fault_rate: float = 0.0, page_size: int = 50) -> ServiceRequestClient:
    store = ServiceRequestStore(generate_tickets(200, seed=42, now=REFERENCE_NOW))
    http = TestClient(mock_main.create_app(store, fault_rate=fault_rate, fault_seed=1))
    retry = RetryPolicy(max_attempts=6, sleep=lambda s: None)
    return ServiceRequestClient(http=http, page_size=page_size, retry=retry)


def test_full_extraction_maps_every_seeded_ticket_cleanly():
    report = extract_tickets(_client())
    assert report.records_read == 200 and len(report.tickets) == 200
    assert report.rejected == [] and report.clean_tickets == 200
    assert report.pages == 4 and report.retries == 0
    assert len({t.ticket_id for t in report.tickets}) == 200


def test_open_only_extraction_matches_source_backlog():
    client = _client()
    source_open = client.get_page(q="StatusTypeCd='ORA_SVC_OPEN'").total_results
    report = extract_tickets(client, q="StatusTypeCd='ORA_SVC_OPEN'")
    assert len(report.tickets) == source_open > 0
    assert all(t.is_open and t.resolved_at is None for t in report.tickets)


def test_canonical_totals_reconcile_with_source():
    report = extract_tickets(_client())
    by_priority = Counter(t.priority.value for t in report.tickets)
    client = _client()
    for sev, prio in [("ORA_SVC_SEV1", "P1"), ("ORA_SVC_SEV2", "P2"), ("ORA_SVC_SEV3", "P3"), ("ORA_SVC_SEV4", "P4")]:
        assert client.get_page(q=f"SeverityCd='{sev}'").total_results == by_priority[prio]


def test_extraction_survives_an_unstable_source():
    report = extract_tickets(_client(fault_rate=0.3, page_size=20))
    assert len(report.tickets) == 200
    assert report.retries > 0
    assert report.requests == report.pages + report.retries


def test_write_back_round_trip():
    client = _client()
    created = client.create(
        {"Title": "Gateway offline after storm", "PrimaryContactPartyName": "Test Customer",
         "SeverityCd": "ORA_SVC_SEV2", "QueueId": 300100001, "CategoryName": "Outage"}
    )
    client.update(created["SrNumber"], {"StatusCd": "ORA_SVC_RESOLVED"})
    ticket = map_service_request(client.get(created["SrNumber"]))
    assert ticket.status is TicketStatus.RESOLVED and ticket.resolved_at is not None
    assert ticket.data_quality_flags == ()


def test_not_found_is_typed():
    with pytest.raises(NotFoundError):
        _client().get("SR9999999999")


def test_cli_writes_tickets_and_prints_report(tmp_path, capsys, monkeypatch):
    client = _client()
    monkeypatch.setattr("cx_integration.__main__.ServiceRequestClient", lambda *a, **k: client)
    out = tmp_path / "tickets.json"
    assert cli_main(["--open-only", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert '"records_rejected": 0' in printed
    assert out.read_text().startswith("[")
