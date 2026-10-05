"""Deterministic synthetic data for "NorthPeak Connect" (fictional ISP).

The generator is a pure function of ``(count, seed, now)`` so the same seed
always produces the same tickets relative to the reference date. Every name,
place and device model below is invented.

Shape of the data (chosen so later phases have something to find):
* Category mix follows a Pareto-like distribution (slow speed + billing
  dominate).
* Weekday volume is higher than weekend volume.
* Two regional outage days produce volume spikes, so the control chart in
  the dashboard has genuine out-of-control points.
* Resolution times are log-normal per severity; Sev1 medians sit close to
  their target, so a meaningful share breaches it (the business pain point).
* Recent tickets, plus a few stale ones, are still open (the backlog).
"""

import math
import random
from datetime import datetime, timedelta

from .domain import QUEUE_ID_BY_NAME, QUEUES, ChannelTypeCd, SeverityCd, StatusCd, status_type_for
from .models import ServiceRequest
from .store import format_sr_number

WINDOW_DAYS = 90
FIRST_SR_ID = 10001

# Days before the reference date on which a regional outage hit.
OUTAGE_SPIKES = {23: ("Pine Hollow", 12), 61: ("Cedar Ridge", 10)}

CATEGORY_WEIGHTS = {
    "Slow Speed": 28,
    "Billing": 22,
    "Outage": 16,
    "Equipment": 14,
    "Installation": 12,
    "Cancellation": 8,
}

SEVERITY_WEIGHTS = {  # per category: Sev1, Sev2, Sev3, Sev4
    "Outage": (45, 40, 15, 0),
    "Slow Speed": (2, 23, 60, 15),
    "Billing": (0, 10, 55, 35),
    "Equipment": (3, 32, 50, 15),
    "Installation": (5, 30, 45, 20),
    "Cancellation": (0, 15, 45, 40),
}

QUEUE_BY_CATEGORY = {
    "Outage": "Network Operations",
    "Billing": "Billing Support",
    "Installation": "Field Installation",
    "Slow Speed": "Technical Support",
    "Equipment": "Technical Support",
    "Cancellation": "Customer Retention",
}

# Reference resolution targets in hours. The authoritative SLA policy lives
# in the rules engine (phase 3); here it only shapes the distribution.
TARGET_HOURS = {SeverityCd.SEV1: 4, SeverityCd.SEV2: 8, SeverityCd.SEV3: 24, SeverityCd.SEV4: 72}
# Median resolution as a fraction of target, and log-normal spread.
MEDIAN_FACTOR = {SeverityCd.SEV1: 0.85, SeverityCd.SEV2: 0.7, SeverityCd.SEV3: 0.6, SeverityCd.SEV4: 0.5}
SIGMA = 0.7

CHANNEL_WEIGHTS = {
    ChannelTypeCd.PHONE: 45,
    ChannelTypeCd.CHAT: 25,
    ChannelTypeCd.WEB: 20,
    ChannelTypeCd.EMAIL: 10,
}

WEEKDAY_WEIGHTS = (1.25, 1.15, 1.1, 1.05, 1.0, 0.65, 0.55)  # Mon..Sun

AGENTS = {
    "Network Operations": ["Dana Whitfield", "Rafael Ortega", "Imogen Hale"],
    "Billing Support": ["Priya Raman", "Tomás Lindqvist", "Grace Okafor"],
    "Field Installation": ["Owen Brandt", "Lucia Ferraro"],
    "Technical Support": ["Marcus Bell", "Aiko Tanaka", "Samir Haddad", "Elena Petrova"],
    "Customer Retention": ["Hannah Moreau", "Julian Cross"],
}

FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Mia", "Ethan", "Zoe", "Lucas", "Chloe", "Mateo", "Nora",
    "Isaac", "Leah", "Felix", "Ruby", "Adrian", "Clara", "Hugo", "Iris", "Jonah", "Maya",
]
LAST_NAMES = [
    "Ashford", "Brennan", "Calloway", "Delgado", "Ellison", "Fairbanks", "Garrity", "Holloway",
    "Iverson", "Jablonski", "Kowalczyk", "Lachance", "Montero", "Nakamura", "Oduya", "Prescott",
]
AREAS = ["Pine Hollow", "Cedar Ridge", "Maple Crossing", "Granite Falls", "Willow Bend", "Harbor View"]
DEVICES = ["NP-Gateway X2", "NP-Gateway X3", "NP-Mesh Node", "NP-TV Box 4K"]

TITLES = {
    "Outage": [
        "No internet service in {area}",
        "Total loss of TV and internet",
        "Internet down since this morning",
        "Service outage reported in {area}",
    ],
    "Slow Speed": [
        "Internet much slower than contracted plan",
        "Speed drops every evening",
        "Video streaming keeps buffering",
        "Upload speed below 1 Mbps",
    ],
    "Billing": [
        "Charged twice for monthly plan",
        "Promotional discount not applied",
        "Unexpected fee on latest invoice",
        "Request for refund after service outage",
    ],
    "Equipment": [
        "{device} keeps rebooting",
        "{device} lights blinking red",
        "Replacement request for faulty {device}",
        "Wi-Fi drops when {device} overheats",
    ],
    "Installation": [
        "Technician did not show for installation",
        "Reschedule installation appointment",
        "New installation incomplete, no signal",
        "Request for additional outlet installation",
    ],
    "Cancellation": [
        "Customer requests service cancellation",
        "Cancellation due to relocation outside coverage",
        "Wants to cancel after repeated outages",
        "Cancel TV package, keep internet",
    ],
}

DESCRIPTIONS = {
    "Outage": "Customer in {area} reports complete loss of service. Gateway shows no upstream signal.",
    "Slow Speed": "Speed tests show roughly {pct}% of the contracted plan, mainly between 7pm and 11pm.",
    "Billing": "Customer disputes the latest invoice. Amount in question: ${amount}.",
    "Equipment": "Customer reports intermittent failure of the {device}. Power-cycle did not help.",
    "Installation": "Installation order for a residence in {area} needs follow-up.",
    "Cancellation": "Customer asked to cancel. Tenure: {tenure} months. Retention offer not yet made.",
}


def _weighted(rng: random.Random, weights: dict) -> object:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _random_hour(rng: random.Random) -> float:
    # Contact-centre arrival pattern: busy 9-21h, quiet overnight.
    hour = rng.choices(range(24), weights=[1, 1, 1, 1, 1, 2, 3, 5, 8, 10, 10, 9, 8, 9, 9, 8, 8, 9, 10, 10, 8, 6, 3, 2])[0]
    return hour + rng.random()


def _plan_days(rng: random.Random, count: int, today_weekday: int) -> list[tuple[int, str | None]]:
    """Return ``(days_ago, outage_area)`` for each ticket to create."""
    plan: list[tuple[int, str | None]] = []
    for days_ago, (area, extra) in OUTAGE_SPIKES.items():
        if days_ago < WINDOW_DAYS:
            plan.extend((days_ago, area) for _ in range(min(extra, count - len(plan))))
    weights = [WEEKDAY_WEIGHTS[(today_weekday - d) % 7] for d in range(WINDOW_DAYS)]
    remaining = count - len(plan)
    plan.extend((d, None) for d in rng.choices(range(WINDOW_DAYS), weights=weights, k=remaining))
    return plan


def generate_tickets(count: int = 200, seed: int = 42, now: datetime | None = None) -> list[ServiceRequest]:
    if now is None:
        raise ValueError("A timezone-aware reference date is required")
    rng = random.Random(seed)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)

    raw: list[tuple[datetime, str, str | None]] = []
    for days_ago, outage_area in _plan_days(rng, count, day0.weekday()):
        created = day0 - timedelta(days=days_ago) + timedelta(hours=_random_hour(rng))
        if created >= now:  # today's ticket "in the future": pull it back into the past
            created = now - timedelta(minutes=rng.randint(5, 600))
        category = "Outage" if outage_area else str(_weighted(rng, CATEGORY_WEIGHTS))
        raw.append((created.replace(microsecond=0), category, outage_area))

    raw.sort(key=lambda r: r[0])
    tickets = []
    for index, (created, category, outage_area) in enumerate(raw):
        tickets.append(_build_ticket(rng, FIRST_SR_ID + index, created, category, outage_area, now))
    return tickets


def _build_ticket(
    rng: random.Random,
    sr_id: int,
    created: datetime,
    category: str,
    outage_area: str | None,
    now: datetime,
) -> ServiceRequest:
    severities = list(SeverityCd)
    if outage_area:
        severity = SeverityCd.SEV1 if rng.random() < 0.7 else SeverityCd.SEV2
    else:
        severity = rng.choices(severities, weights=SEVERITY_WEIGHTS[category])[0]

    queue_name = QUEUE_BY_CATEGORY[category]
    if category == "Slow Speed" and rng.random() < 0.2:
        queue_name = "Network Operations"  # escalated to network team
    queue_id = QUEUE_ID_BY_NAME[queue_name]

    area = outage_area or rng.choice(AREAS)
    fill = {
        "area": area,
        "device": rng.choice(DEVICES),
        "pct": rng.randint(15, 55),
        "amount": f"{rng.uniform(19, 180):.2f}",
        "tenure": rng.randint(2, 96),
    }
    title = rng.choice(TITLES["Outage"][:1] if outage_area else TITLES[category]).format(**fill)
    description = DESCRIPTIONS[category].format(**fill)

    median = TARGET_HOURS[severity] * MEDIAN_FACTOR[severity]
    resolution_hours = math.exp(rng.gauss(math.log(median), SIGMA))
    resolved_at = created + timedelta(hours=resolution_hours)
    # Stale backlog (forgotten or waiting on customer), mostly in the last month.
    stuck = rng.random() < (0.30 if now - created < timedelta(days=30) else 0.04)

    if resolved_at <= now and not stuck:
        status = StatusCd.CLOSED if now - resolved_at > timedelta(days=3) else StatusCd.RESOLVED
        resolved_date: datetime | None = resolved_at.replace(microsecond=0)
        last_update = resolved_date
    else:
        age = now - created
        if age < timedelta(hours=2):
            status = StatusCd.NEW
        else:
            status = StatusCd.WAITING if stuck or rng.random() < 0.3 else StatusCd.IN_PROGRESS
        resolved_date = None
        last_update = (created + age * rng.uniform(0.1, 0.9)).replace(microsecond=0)

    assignee = None if status == StatusCd.NEW else rng.choice(AGENTS[queue_name])

    return ServiceRequest(
        SrId=sr_id,
        SrNumber=format_sr_number(sr_id),
        Title=title,
        ProblemDescription=description,
        StatusCd=status,
        StatusTypeCd=status_type_for(status),
        SeverityCd=severity,
        QueueId=queue_id,
        QueueName=QUEUES[queue_id],
        CategoryName=category,
        ChannelTypeCd=_weighted(rng, CHANNEL_WEIGHTS),
        PrimaryContactPartyName=f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}",
        AssigneeResourceName=assignee,
        CreationDate=created,
        LastUpdateDate=last_update,
        ResolvedDate=resolved_date,
    )
