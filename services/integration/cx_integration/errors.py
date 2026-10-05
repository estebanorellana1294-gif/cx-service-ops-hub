"""Exception hierarchy of the integration layer.

Callers can catch :class:`IntegrationError` for "anything went wrong", or a
specific subclass when they need to react differently (e.g. a 404 during a
write-back is expected; a 401 is not).
"""


class IntegrationError(Exception):
    """Base class for every error raised by this package."""


class ApiError(IntegrationError):
    """The source API answered with a non-success HTTP status."""

    def __init__(self, status_code: int, detail: str, method: str, url: str) -> None:
        self.status_code = status_code
        self.detail = detail
        self.method = method
        self.url = url
        super().__init__(f"{method} {url} -> HTTP {status_code}: {detail}")


class ClientRequestError(ApiError):
    """4xx: the request is wrong. Retrying the same request will not help."""


class NotFoundError(ClientRequestError):
    """404: the requested service request does not exist."""


class ServerError(ApiError):
    """5xx (or 429): the source system is failing or throttling."""


class RetryExhaustedError(IntegrationError):
    """A retryable failure persisted after the last allowed attempt."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Gave up after {attempts} attempts: {last_error}")


class UnknownOutcomeError(IntegrationError):
    """A non-idempotent write was sent but no response arrived.

    The ticket may or may not have been created, so the call is not retried
    automatically: a duplicate ticket is worse than a reported failure.
    """


class PaginationError(IntegrationError):
    """The collection metadata is inconsistent (e.g. hasMore with an empty page)."""


class MappingError(IntegrationError):
    """A source record cannot be mapped to the canonical model and is rejected."""

    def __init__(self, record_id: str | None, field: str, reason: str) -> None:
        self.record_id = record_id
        self.field = field
        self.reason = reason
        super().__init__(f"Record {record_id or '<unknown>'}: {field}: {reason}")
