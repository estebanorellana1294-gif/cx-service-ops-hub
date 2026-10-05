"""HTTP client for the source ``serviceRequests`` resource.

Responsibilities of this module, and nothing else:

* build requests (paths, query parameters, content type),
* classify failures into retryable / non-retryable,
* walk the paginated collection safely.

It returns *source* records (plain dicts, source field names). Converting
them into the canonical model is the job of :mod:`cx_integration.mapping`.
"""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx

from .errors import (
    ApiError,
    ClientRequestError,
    NotFoundError,
    PaginationError,
    ServerError,
    UnknownOutcomeError,
)
from .retry import RetryableError, RetryPolicy

log = logging.getLogger(__name__)

RESOURCE_PATH = "/crmRestApi/resources/11.13.18.05/serviceRequests"
CONTENT_TYPE = "application/vnd.oracle.adf.resourceitem+json"

# Statuses worth retrying for idempotent calls (GET, PATCH with absolute values).
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
# For POST only statuses that guarantee the request was NOT processed;
# retrying after a 500/504 could create a duplicate ticket.
RETRYABLE_STATUS_NON_IDEMPOTENT = frozenset({429, 503})

# Stable order for extraction: new tickets get a higher SrId and land at the
# end, so offset paging does not skip or repeat rows while data is changing.
EXTRACTION_ORDER = "SrId:asc"


@dataclass(frozen=True)
class Page:
    items: list[dict[str, Any]]
    offset: int
    has_more: bool
    total_results: int | None


@dataclass
class ClientStats:
    requests: int = 0
    pages: int = 0


class ServiceRequestClient:
    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        page_size: int = 100,
        timeout: float = 10.0,
        retry: RetryPolicy | None = None,
        http: httpx.Client | None = None,
        max_pages: int = 10_000,
    ) -> None:
        if not 1 <= page_size <= 500:
            raise ValueError("page_size must be between 1 and 500")
        self.page_size = page_size
        self.max_pages = max_pages
        self.retry = retry or RetryPolicy()
        self.stats = ClientStats()
        self._owns_http = http is None
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "ServiceRequestClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- reads -------------------------------------------------------------

    def get(self, sr_number: str) -> dict[str, Any]:
        return self._request("GET", f"{RESOURCE_PATH}/{sr_number}").json()

    def get_page(
        self, offset: int = 0, *, q: str | None = None, order_by: str = EXTRACTION_ORDER
    ) -> Page:
        params: dict[str, Any] = {"limit": self.page_size, "offset": offset, "orderBy": order_by}
        if q:
            params["q"] = q
        if offset == 0:
            params["totalResults"] = "true"
        body = self._request("GET", RESOURCE_PATH, params=params).json()
        try:
            return Page(
                items=body["items"],
                offset=body["offset"],
                has_more=body["hasMore"],
                total_results=body.get("totalResults"),
            )
        except KeyError as exc:
            raise PaginationError(f"Collection response is missing {exc}") from None

    def iter_pages(self, *, q: str | None = None, order_by: str = EXTRACTION_ORDER) -> Iterator[Page]:
        offset = 0
        for _ in range(self.max_pages):
            page = self.get_page(offset, q=q, order_by=order_by)
            self.stats.pages += 1
            if page.offset != offset:
                raise PaginationError(f"Asked for offset {offset}, server returned {page.offset}")
            yield page
            if not page.has_more:
                return
            if not page.items:
                raise PaginationError(f"hasMore=true but page at offset {offset} is empty")
            offset += len(page.items)
        raise PaginationError(f"Stopped after max_pages={self.max_pages}; collection never ended")

    def iter_service_requests(
        self, *, q: str | None = None, order_by: str = EXTRACTION_ORDER
    ) -> Iterator[dict[str, Any]]:
        """Yield every matching record once, across all pages.

        Records already seen (same SrNumber) are skipped: with offset paging a
        row can reappear if the data set shifts between two page requests.
        """
        seen: set[str] = set()
        for page in self.iter_pages(q=q, order_by=order_by):
            for record in page.items:
                key = record.get("SrNumber")
                if key in seen:
                    log.info("Skipping duplicate %s returned by a later page", key)
                    continue
                seen.add(key)
                yield record

    # -- writes ------------------------------------------------------------

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", RESOURCE_PATH, json=payload, idempotent=False).json()

    def update(self, sr_number: str, changes: dict[str, Any]) -> dict[str, Any]:
        # PATCH with absolute values (no increments) is safe to repeat.
        return self._request("PATCH", f"{RESOURCE_PATH}/{sr_number}", json=changes).json()

    # -- plumbing ----------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        idempotent: bool = True,
    ) -> httpx.Response:
        retryable_status = RETRYABLE_STATUS if idempotent else RETRYABLE_STATUS_NON_IDEMPOTENT
        headers = {"Content-Type": CONTENT_TYPE} if json is not None else None

        def attempt() -> httpx.Response:
            self.stats.requests += 1
            try:
                response = self._http.request(method, path, params=params, json=json, headers=headers)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached the server: always safe to retry.
                raise RetryableError(exc) from exc
            except httpx.TransportError as exc:
                # Sent but no answer (read timeout, dropped connection):
                # only retry if repeating the call cannot cause a duplicate.
                if idempotent:
                    raise RetryableError(exc) from exc
                raise UnknownOutcomeError(
                    f"{method} {path} sent but no response ({exc}); check the source system "
                    "before retrying to avoid a duplicate"
                ) from exc
            if response.is_success:
                return response
            error = _to_api_error(response)
            if response.status_code in retryable_status:
                raise RetryableError(error, _retry_after(response))
            raise error

        return self.retry.run(attempt, description=f"{method} {path}")


def _to_api_error(response: httpx.Response) -> ApiError:
    try:
        body = response.json()
        detail = str(body.get("detail", body) if isinstance(body, dict) else body)
    except ValueError:
        detail = response.text
    args = (response.status_code, detail, response.request.method, str(response.request.url))
    if response.status_code == 404:
        return NotFoundError(*args)
    if response.status_code == 429 or response.status_code >= 500:
        return ServerError(*args)
    return ClientRequestError(*args)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # HTTP-date form: fall back to computed backoff
