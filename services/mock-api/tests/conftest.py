from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import BASE_PATH, create_app
from app.seed import generate_tickets
from app.store import ServiceRequestStore

REFERENCE_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CLOCK_NOW = datetime(2026, 10, 5, 13, 30, tzinfo=UTC)


@pytest.fixture
def store() -> ServiceRequestStore:
    return ServiceRequestStore(generate_tickets(200, seed=42, now=REFERENCE_NOW), clock=lambda: CLOCK_NOW)


@pytest.fixture
def client(store: ServiceRequestStore) -> TestClient:
    return TestClient(create_app(store))


@pytest.fixture
def base() -> str:
    return BASE_PATH
