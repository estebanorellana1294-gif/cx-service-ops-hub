"""In-memory repository for service requests.

A process-local dict is enough for a mock: the data is re-seeded on every
start, which keeps demos reproducible (see docs/api-assumptions.md).
"""

import threading
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

from .domain import QUEUES, StatusCd, status_type_for
from .models import VALID_CATEGORIES, ServiceRequest, ServiceRequestCreate, ServiceRequestPatch
from .query import Condition, apply_order

Clock = Callable[[], datetime]

# Attributes that may be patched but never set to null.
_NON_NULLABLE = {"Title", "ProblemDescription", "StatusCd", "SeverityCd", "QueueId", "CategoryName"}

# Default queue when a ticket is created without one (front-line triage).
DEFAULT_QUEUE_ID = 300100004


class NotFoundError(LookupError):
    pass


class ValidationError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class ServiceRequestStore:
    def __init__(self, tickets: Iterable[ServiceRequest] = (), clock: Clock = utc_now) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._by_number: dict[str, ServiceRequest] = {t.SrNumber: t for t in tickets}
        self._next_id = max((t.SrId for t in self._by_number.values()), default=100000) + 1

    def __len__(self) -> int:
        return len(self._by_number)

    def query(
        self,
        conditions: list[Condition],
        order: list[tuple[str, bool]],
    ) -> list[ServiceRequest]:
        with self._lock:
            items = list(self._by_number.values())
        items = [sr for sr in items if all(c.matches(sr) for c in conditions)]
        # Default order mirrors a typical agent worklist: newest first.
        return apply_order(items, order or [("CreationDate", True), ("SrId", True)])

    def get(self, sr_number: str) -> ServiceRequest:
        try:
            return self._by_number[sr_number]
        except KeyError:
            raise NotFoundError(sr_number) from None

    def create(self, payload: ServiceRequestCreate) -> ServiceRequest:
        queue_id = payload.QueueId if payload.QueueId is not None else DEFAULT_QUEUE_ID
        _check_queue(queue_id)
        category = payload.CategoryName or "Uncategorized"
        if payload.CategoryName is not None:
            _check_category(category)
        now = self._clock()
        with self._lock:
            sr_id = self._next_id
            self._next_id += 1
            sr = ServiceRequest(
                SrId=sr_id,
                SrNumber=format_sr_number(sr_id),
                Title=payload.Title,
                ProblemDescription=payload.ProblemDescription,
                StatusCd=StatusCd.NEW,
                StatusTypeCd=status_type_for(StatusCd.NEW),
                SeverityCd=payload.SeverityCd,
                QueueId=queue_id,
                QueueName=QUEUES[queue_id],
                CategoryName=category,
                ChannelTypeCd=payload.ChannelTypeCd,
                PrimaryContactPartyName=payload.PrimaryContactPartyName,
                AssigneeResourceName=payload.AssigneeResourceName,
                CreationDate=now,
                LastUpdateDate=now,
            )
            self._by_number[sr.SrNumber] = sr
        return sr

    def patch(self, sr_number: str, payload: ServiceRequestPatch) -> ServiceRequest:
        changes = payload.model_dump(exclude_unset=True)
        for attr in _NON_NULLABLE & changes.keys():
            if changes[attr] is None:
                raise ValidationError(f"{attr} cannot be null")
        if "QueueId" in changes:
            _check_queue(changes["QueueId"])
            changes["QueueName"] = QUEUES[changes["QueueId"]]
        if "CategoryName" in changes:
            _check_category(changes["CategoryName"])

        now = self._clock()
        with self._lock:
            current = self.get(sr_number)
            if "StatusCd" in changes:
                new_status = changes["StatusCd"]
                changes["StatusTypeCd"] = status_type_for(new_status)
                if new_status in (StatusCd.RESOLVED, StatusCd.CLOSED):
                    # Keep the original resolution time when moving RESOLVED -> CLOSED.
                    changes["ResolvedDate"] = current.ResolvedDate or now
                else:
                    changes["ResolvedDate"] = None  # reopened
            changes["LastUpdateDate"] = now
            updated = current.model_copy(update=changes)
            self._by_number[sr_number] = updated
        return updated


def format_sr_number(sr_id: int) -> str:
    return f"SR{sr_id:010d}"


def _check_queue(queue_id: int) -> None:
    if queue_id not in QUEUES:
        raise ValidationError(f"Unknown QueueId {queue_id}")


def _check_category(category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise ValidationError(f"Unknown CategoryName {category!r}")
