"""Extract -> map: pull service requests and return canonical tickets plus a run report.

A single bad record must not stop the run: it is rejected, counted and
reported, and the other tickets are delivered. Transport failures (API down
after all retries) do stop the run, because a partial extraction silently
presented as complete would understate the backlog.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .canonical import Ticket
from .client import ServiceRequestClient
from .errors import MappingError
from .mapping import map_service_request


@dataclass(frozen=True)
class Rejection:
    record_id: str | None
    field: str
    reason: str


@dataclass
class ExtractionReport:
    started_at: datetime
    finished_at: datetime | None = None
    tickets: list[Ticket] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    records_read: int = 0
    pages: int = 0
    requests: int = 0
    retries: int = 0

    @property
    def flag_counts(self) -> Counter:
        return Counter(flag for t in self.tickets for flag in t.data_quality_flags)

    @property
    def clean_tickets(self) -> int:
        return sum(1 for t in self.tickets if not t.data_quality_flags)

    def summary(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "records_read": self.records_read,
            "tickets_mapped": len(self.tickets),
            "tickets_clean": self.clean_tickets,
            "records_rejected": len(self.rejected),
            "data_quality_flags": dict(sorted(self.flag_counts.items())),
            "rejections": [r.__dict__ for r in self.rejected],
            "pages": self.pages,
            "http_requests": self.requests,
            "retries": self.retries,
        }


def extract_tickets(client: ServiceRequestClient, *, q: str | None = None) -> ExtractionReport:
    report = ExtractionReport(started_at=datetime.now(UTC))
    retries_before = client.retry.retries_performed
    pages_before, requests_before = client.stats.pages, client.stats.requests

    for record in client.iter_service_requests(q=q):
        report.records_read += 1
        try:
            report.tickets.append(map_service_request(record))
        except MappingError as exc:
            report.rejected.append(Rejection(exc.record_id, exc.field, exc.reason))

    report.pages = client.stats.pages - pages_before
    report.requests = client.stats.requests - requests_before
    report.retries = client.retry.retries_performed - retries_before
    report.finished_at = datetime.now(UTC)
    return report
