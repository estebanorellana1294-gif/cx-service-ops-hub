import pytest

from cx_integration.errors import RetryExhaustedError
from cx_integration.retry import RetryableError, RetryPolicy


def _policy(sleeps, **kwargs):
    return RetryPolicy(sleep=sleeps, rand=lambda: 1.0, **kwargs)


def test_success_on_first_attempt_does_not_sleep(sleeps):
    assert _policy(sleeps).run(lambda: "ok") == "ok"
    assert sleeps.calls == []


def test_exponential_backoff_until_success(sleeps):
    outcomes = iter([RetryableError(OSError("a")), RetryableError(OSError("b")), "ok"])

    def attempt():
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    policy = _policy(sleeps, base_delay=0.5)
    assert policy.run(attempt) == "ok"
    assert sleeps.calls == [0.5, 1.0]
    assert policy.retries_performed == 2


def test_backoff_is_capped(sleeps):
    policy = _policy(sleeps, base_delay=1, max_delay=3)
    assert [policy.backoff(n) for n in range(4)] == [1, 2, 3, 3]


def test_full_jitter_scales_the_delay():
    policy = RetryPolicy(base_delay=2, rand=lambda: 0.25)
    assert policy.backoff(1) == 1.0  # 0.25 * 2 * 2**1


def test_retry_after_overrides_backoff_but_is_capped():
    policy = RetryPolicy(max_delay=5)
    assert policy.backoff(0, retry_after=2) == 2
    assert policy.backoff(0, retry_after=60) == 5
    assert policy.backoff(0, retry_after=-1) == 0


def test_gives_up_after_max_attempts(sleeps):
    cause = OSError("still down")

    def attempt():
        raise RetryableError(cause)

    with pytest.raises(RetryExhaustedError) as info:
        _policy(sleeps, max_attempts=3).run(attempt)
    assert info.value.attempts == 3 and info.value.last_error is cause
    assert len(sleeps.calls) == 2  # no sleep after the final attempt


def test_non_retryable_errors_propagate_immediately(sleeps):
    def attempt():
        raise ValueError("bad request")

    with pytest.raises(ValueError):
        _policy(sleeps).run(attempt)
    assert sleeps.calls == []


def test_max_attempts_must_be_positive():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
