from collections import Counter
from datetime import timedelta

from app.domain import CATEGORIES, QUEUES, SeverityCd, StatusCd, StatusTypeCd
from app.seed import OUTAGE_SPIKES, TARGET_HOURS, WINDOW_DAYS, generate_tickets
from tests.conftest import REFERENCE_NOW


def _tickets(seed=42):
    return generate_tickets(200, seed=seed, now=REFERENCE_NOW)


def test_is_deterministic():
    assert _tickets() == _tickets()
    assert _tickets() != _tickets(seed=7)


def test_count_and_unique_numbers():
    tickets = _tickets()
    assert len(tickets) == 200
    assert len({t.SrNumber for t in tickets}) == 200


def test_all_timestamps_within_window_and_consistent():
    start = REFERENCE_NOW - timedelta(days=WINDOW_DAYS)
    for t in _tickets():
        assert start <= t.CreationDate <= REFERENCE_NOW
        assert t.CreationDate <= t.LastUpdateDate <= REFERENCE_NOW
        if t.ResolvedDate:
            assert t.CreationDate < t.ResolvedDate <= REFERENCE_NOW


def test_status_type_and_resolution_are_consistent():
    for t in _tickets():
        is_open = t.StatusCd in (StatusCd.NEW, StatusCd.IN_PROGRESS, StatusCd.WAITING)
        assert t.StatusTypeCd == (StatusTypeCd.OPEN if is_open else StatusTypeCd.CLOSED)
        assert (t.ResolvedDate is None) == is_open
        assert (t.AssigneeResourceName is None) == (t.StatusCd == StatusCd.NEW)


def test_reference_data_is_covered():
    tickets = _tickets()
    assert {t.CategoryName for t in tickets} == set(CATEGORIES)
    assert {t.SeverityCd for t in tickets} == set(SeverityCd)
    assert {t.QueueId for t in tickets} == set(QUEUES)
    assert all(QUEUES[t.QueueId] == t.QueueName for t in tickets)


def test_has_an_open_backlog_in_every_queue():
    open_by_queue = Counter(t.QueueName for t in _tickets() if t.StatusTypeCd == StatusTypeCd.OPEN)
    assert set(open_by_queue) == set(QUEUES.values())
    assert 20 <= sum(open_by_queue.values()) <= 60


def test_outage_spike_days_stand_out():
    per_day = Counter((REFERENCE_NOW.date() - t.CreationDate.date()).days for t in _tickets())
    typical = sorted(per_day.values())[len(per_day) // 2]
    for days_ago in OUTAGE_SPIKES:
        assert per_day[days_ago] >= 3 * typical


def test_sev1_breaches_its_target_more_often_than_sev3():
    def breach_rate(sev):
        resolved = [t for t in _tickets() if t.SeverityCd == sev and t.ResolvedDate]
        late = [t for t in resolved if t.ResolvedDate - t.CreationDate > timedelta(hours=TARGET_HOURS[sev])]
        return len(late) / len(resolved)

    assert breach_rate(SeverityCd.SEV1) > breach_rate(SeverityCd.SEV3)
