import json

import httpx
import pytest

from cx_integration.client import CONTENT_TYPE, RESOURCE_PATH, ServiceRequestClient
from cx_integration.errors import (
    ClientRequestError,
    NotFoundError,
    PaginationError,
    RetryExhaustedError,
    ServerError,
    UnknownOutcomeError,
)
from tests.conftest import collection, paged_handler, record

# --- pagination ----------------------------------------------------------------


def test_iterates_all_pages(make_client):
    records = [record(n) for n in range(5)]
    client = make_client(paged_handler(records))
    assert [r["SrNumber"] for r in client.iter_service_requests()] == [r["SrNumber"] for r in records]
    assert client.stats.pages == 3 and client.stats.requests == 3


def test_sends_stable_order_filter_and_total_on_first_page(make_client):
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return paged_handler([record(n) for n in range(3)])(request)

    list(make_client(handler).iter_service_requests(q="SeverityCd='ORA_SVC_SEV1'"))
    assert seen[0] == {
        "limit": "2", "offset": "0", "orderBy": "SrId:asc", "q": "SeverityCd='ORA_SVC_SEV1'", "totalResults": "true",
    }
    assert seen[1]["offset"] == "2" and "totalResults" not in seen[1]


def test_empty_collection(make_client):
    assert list(make_client(paged_handler([])).iter_service_requests()) == []


def test_duplicates_across_pages_are_skipped(make_client):
    # Server shifts data between calls: record 1 shows up on both pages.
    pages = {0: [record(0), record(1)], 2: [record(1), record(2)]}

    def handler(request):
        offset = int(request.url.params["offset"])
        return collection(pages[offset], offset=offset, has_more=offset == 0)

    numbers = [r["SrNumber"] for r in make_client(handler).iter_service_requests()]
    assert numbers == [record(0)["SrNumber"], record(1)["SrNumber"], record(2)["SrNumber"]]


def test_has_more_with_empty_page_is_an_error(make_client):
    client = make_client(lambda request: collection([], offset=0, has_more=True))
    with pytest.raises(PaginationError, match="empty"):
        list(client.iter_service_requests())


def test_offset_mismatch_is_an_error(make_client):
    client = make_client(lambda request: collection([record(0)], offset=99, has_more=False))
    with pytest.raises(PaginationError, match="offset"):
        list(client.iter_service_requests())


def test_runaway_pagination_is_stopped(make_client):
    def handler(request):
        offset = int(request.url.params["offset"])
        return collection([record(offset)], offset=offset, has_more=True)

    with pytest.raises(PaginationError, match="max_pages"):
        list(make_client(handler, max_pages=5).iter_service_requests())


def test_malformed_collection_is_an_error(make_client):
    client = make_client(lambda request: httpx.Response(200, json={"rows": []}))
    with pytest.raises(PaginationError, match="items"):
        client.get_page()


def test_page_size_is_validated():
    with pytest.raises(ValueError):
        ServiceRequestClient(page_size=0)
    with pytest.raises(ValueError):
        ServiceRequestClient(page_size=501)


# --- retries -----------------------------------------------------------------


def _flaky(failures: list[httpx.Response | Exception], then: httpx.Response):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) <= len(failures):
            failure = failures[len(calls) - 1]
            if isinstance(failure, Exception):
                raise failure
            return failure
        return then

    return handler, calls


OK_ITEM = httpx.Response(200, json=record(1))


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_get_retries_transient_statuses(make_client, sleeps, status):
    handler, calls = _flaky([httpx.Response(status, json={"detail": "busy"})], OK_ITEM)
    client = make_client(handler)
    assert client.get("SR1")["SrNumber"] == record(1)["SrNumber"]
    assert len(calls) == 2 and sleeps.calls == [0.5]


@pytest.mark.parametrize("exc", [httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])
def test_get_retries_transport_errors(make_client, exc):
    handler, calls = _flaky([exc, exc], OK_ITEM)
    assert make_client(handler).get("SR1")
    assert len(calls) == 3


def test_retry_after_header_is_honored(make_client, sleeps):
    handler, _ = _flaky([httpx.Response(429, headers={"Retry-After": "3"})], OK_ITEM)
    make_client(handler).get("SR1")
    assert sleeps.calls == [3.0]


def test_gives_up_and_reports_last_error(make_client, sleeps):
    handler, calls = _flaky([httpx.Response(503, json={"detail": "down"})] * 10, OK_ITEM)
    with pytest.raises(RetryExhaustedError) as info:
        make_client(handler, max_attempts=3).get("SR1")
    assert len(calls) == 3
    assert isinstance(info.value.last_error, ServerError) and info.value.last_error.status_code == 503
    assert sleeps.calls == [0.5, 1.0]


def test_retry_mid_pagination_resumes_same_page(make_client):
    records = [record(n) for n in range(4)]
    good = paged_handler(records)
    failed_once = set()

    def handler(request):
        offset = request.url.params["offset"]
        if offset == "2" and offset not in failed_once:
            failed_once.add(offset)
            return httpx.Response(503)
        return good(request)

    client = make_client(handler)
    assert len(list(client.iter_service_requests())) == 4
    assert client.retry.retries_performed == 1


@pytest.mark.parametrize(
    ("status", "error"),
    [(400, ClientRequestError), (401, ClientRequestError), (404, NotFoundError), (422, ClientRequestError)],
)
def test_client_errors_are_not_retried(make_client, sleeps, status, error):
    handler, calls = _flaky([httpx.Response(status, json={"detail": "nope"})], OK_ITEM)
    with pytest.raises(error) as info:
        make_client(handler).get("SR1")
    assert len(calls) == 1 and sleeps.calls == []
    assert info.value.status_code == status and info.value.detail == "nope"


def test_error_detail_falls_back_to_text(make_client):
    client = make_client(lambda request: httpx.Response(400, text="plain text error"))
    with pytest.raises(ClientRequestError, match="plain text error"):
        client.get("SR1")


# --- writes --------------------------------------------------------------------


def test_create_posts_with_resource_content_type(make_client):
    captured = []

    def handler(request):
        captured.append(request)
        return httpx.Response(201, json=record(9))

    make_client(handler).create({"Title": "New", "PrimaryContactPartyName": "A B"})
    assert captured[0].method == "POST" and captured[0].url.path == RESOURCE_PATH
    assert captured[0].headers["Content-Type"] == CONTENT_TYPE
    assert json.loads(captured[0].content) == {"Title": "New", "PrimaryContactPartyName": "A B"}


def test_create_retries_only_when_request_was_not_processed(make_client):
    handler, calls = _flaky([httpx.Response(503), httpx.ConnectError("refused")], httpx.Response(201, json=record(9)))
    assert make_client(handler).create({"Title": "x"})["SrNumber"]
    assert len(calls) == 3


def test_create_does_not_retry_ambiguous_500(make_client):
    handler, calls = _flaky([httpx.Response(500)], httpx.Response(201, json=record(9)))
    with pytest.raises(ServerError):
        make_client(handler).create({"Title": "x"})
    assert len(calls) == 1


def test_create_read_timeout_reports_unknown_outcome(make_client):
    handler, calls = _flaky([httpx.ReadTimeout("slow")], httpx.Response(201, json=record(9)))
    with pytest.raises(UnknownOutcomeError, match="duplicate"):
        make_client(handler).create({"Title": "x"})
    assert len(calls) == 1


def test_update_patches_item_and_is_retried(make_client):
    handler, calls = _flaky([httpx.Response(500)], httpx.Response(200, json=record(1, SeverityCd="ORA_SVC_SEV2")))
    updated = make_client(handler).update("SR0000010001", {"SeverityCd": "ORA_SVC_SEV2"})
    assert updated["SeverityCd"] == "ORA_SVC_SEV2"
    assert calls[-1].method == "PATCH" and calls[-1].url.path == f"{RESOURCE_PATH}/SR0000010001"
    assert len(calls) == 2


def test_context_manager_closes_owned_http_client():
    with ServiceRequestClient("http://source.test") as client:
        http = client._http
    assert http.is_closed


def test_injected_http_client_is_not_closed(make_client):
    client = make_client(paged_handler([]))
    client.close()
    assert not client._http.is_closed
