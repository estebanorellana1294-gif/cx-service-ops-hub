"""Retry with exponential backoff and full jitter.

delay(n) = random(0, min(max_delay, base_delay * 2**n))

Full jitter spreads retries from many clients over time, so a recovering
source system is not hit by synchronized bursts. A ``Retry-After`` header
from the server takes precedence (capped by ``max_delay``).
"""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

from .errors import RetryExhaustedError

log = logging.getLogger(__name__)
T = TypeVar("T")


class RetryableError(Exception):
    """Internal signal: the attempt failed in a way that may succeed later."""

    def __init__(self, cause: Exception, retry_after: float | None = None) -> None:
        self.cause = cause
        self.retry_after = retry_after
        super().__init__(str(cause))


@dataclass
class RetryPolicy:
    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 8.0
    sleep: Callable[[float], None] = time.sleep
    rand: Callable[[], float] = random.random
    retries_performed: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

    def backoff(self, retry_number: int, retry_after: float | None = None) -> float:
        if retry_after is not None:
            return min(self.max_delay, max(0.0, retry_after))
        ceiling = min(self.max_delay, self.base_delay * 2**retry_number)
        return self.rand() * ceiling

    def run(self, attempt: Callable[[], T], description: str = "request") -> T:
        """Call ``attempt`` until it succeeds, raises a non-retryable error, or attempts run out."""
        for attempt_number in range(1, self.max_attempts + 1):
            try:
                return attempt()
            except RetryableError as exc:
                if attempt_number == self.max_attempts:
                    raise RetryExhaustedError(attempt_number, exc.cause) from exc.cause
                delay = self.backoff(attempt_number - 1, exc.retry_after)
                self.retries_performed += 1
                log.warning(
                    "%s failed (attempt %d/%d): %s. Retrying in %.2fs",
                    description, attempt_number, self.max_attempts, exc.cause, delay,
                )
                self.sleep(delay)
        raise AssertionError("unreachable")  # pragma: no cover
