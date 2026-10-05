import json
from collections.abc import Callable

import httpx
import pytest

from cx_integration.client import RESOURCE_PATH, ServiceRequestClient
from cx_integration.retry import RetryPolicy

Handler = Callable[[httpx.Request], httpx.Response]


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


@pytest.fixture
def sleeps() -> SleepRecorder:
    return SleepRecorder()


@pytest.fixture
def make_client(sleeps: SleepRecorder) -> Callable[..., ServiceRequestClient]:
    """Client wired to a fake transport; backoff sleeps are recorded, not slept."""

    def factory(handler: Handler, *, page_size: int = 2, max_attempts: int = 4, **kwargs) -> ServiceRequestClient:
        http = httpx.Client(base_url="http://source.test", transport=httpx.MockTransport(handler))
        retry = RetryPolicy(max_attempts=max_attempts, base_delay=0.5, max_delay=8, sleep=sleeps, rand=lambda: 1.0)
        return ServiceRequestClient(http=http, page_size=page_size, retry=retry, **kwargs)

    return factory


def collection(items: list[dict], *, offset: int, has_more: bool, total: int | None = None) -> httpx.Response:
    body = {"items": items, "count": len(items), "hasMore": has_more, "limit": 2, "offset": offset, "links": []}
    if total is not None:
        body["totalResults"] = total
    return httpx.Response(200, content=json.dumps(body), headers={"Content-Type": "application/json"})


def paged_handler(records: list[dict], page_size: int = 2) -> Handler:
    """A well-behaved server over a fixed list of records."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == RESOURCE_PATH
        offset = int(request.url.params.get("offset", 0))
        limit = int(request.url.params.get("limit", page_size))
        page = records[offset : offset + limit]
        return collection(page, offset=offset, has_more=offset + len(page) < len(records), total=len(records))

    return handler


def record(n: int, **overrides) -> dict:
    """A valid source record. Override fields to create edge cases."""
    base = {
        "SrId": 10000 + n,
        "SrNumber": f"SR{10000 + n:010d}",
        "Title": "Internet down since this morning",
        "ProblemDescription": "Gateway shows no upstream signal.",
        "StatusCd": "ORA_SVC_CLOSED",
        "StatusTypeCd": "ORA_SVC_CLOSED",
        "SeverityCd": "ORA_SVC_SEV1",
        "QueueId": 300100001,
        "QueueName": "Network Operations",
        "CategoryName": "Outage",
        "ChannelTypeCd": "ORA_SVC_PHONE",
        "PrimaryContactPartyName": "Ava Ashford",
        "AssigneeResourceName": "Dana Whitfield",
        "CreationDate": "2026-09-15T09:00:00Z",
        "LastUpdateDate": "2026-09-15T15:30:00Z",
        "ResolvedDate": "2026-09-15T14:30:00Z",
    }
    base.update(overrides)
    return base
