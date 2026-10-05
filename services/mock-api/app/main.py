"""Mock of a customer-service platform's ``serviceRequests`` REST resource.

The URL layout and payloads are modeled on the public Oracle Fusion Service
REST API documentation. This is an independent educational demo, not
affiliated with or endorsed by Oracle. See docs/api-assumptions.md.
"""

import os
import random
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from .models import (
    ServiceRequest,
    ServiceRequestCollection,
    ServiceRequestCreate,
    ServiceRequestPatch,
)
from .query import QueryError, parse_order_by, parse_q
from .seed import generate_tickets
from .store import NotFoundError, ServiceRequestStore, ValidationError, utc_now

API_VERSION = "11.13.18.05"
BASE_PATH = f"/crmRestApi/resources/{API_VERSION}/serviceRequests"
DEFAULT_LIMIT = 25
MAX_LIMIT = 500


def build_default_store() -> ServiceRequestStore:
    """Seed from env vars so a demo can pin its data (``SEED_REFERENCE_DATE``)."""
    reference = os.getenv("SEED_REFERENCE_DATE")
    now = datetime.fromisoformat(reference.replace("Z", "+00:00")) if reference else utc_now()
    tickets = generate_tickets(
        count=int(os.getenv("SEED_COUNT", "200")),
        seed=int(os.getenv("SEED_RANDOM", "42")),
        now=now,
    )
    return ServiceRequestStore(tickets)


def create_app(
    store: ServiceRequestStore | None = None,
    fault_rate: float | None = None,
    fault_seed: int = 0,
) -> FastAPI:
    """Build the app.

    ``fault_rate`` (or env ``MOCK_FAULT_RATE``) makes that share of resource
    calls fail with ``503 Service Unavailable``, to exercise client retries.
    """
    app = FastAPI(
        title="NorthPeak Connect - Mock Service API",
        description=(
            "Mock `serviceRequests` resource modeled on the public Oracle Fusion Service "
            "REST API docs. Synthetic data only. Independent educational demo. "
            "Not affiliated with or endorsed by Oracle."
        ),
        version="1.0.0",
    )
    app.state.store = store if store is not None else build_default_store()
    if fault_rate is None:
        fault_rate = float(os.getenv("MOCK_FAULT_RATE", "0"))
    if not 0 <= fault_rate <= 1:
        raise ValueError("fault_rate must be between 0 and 1")
    fault_rng = random.Random(fault_seed)

    @app.middleware("http")
    async def inject_faults(request: Request, call_next):
        if fault_rate and request.url.path.startswith(BASE_PATH) and fault_rng.random() < fault_rate:
            return JSONResponse(
                {"detail": "Simulated outage (MOCK_FAULT_RATE)"},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                headers={"Retry-After": "0"},
            )
        return await call_next(request)

    def get_store(request: Request) -> ServiceRequestStore:
        return request.app.state.store

    @app.get("/health", tags=["ops"])
    def health(request: Request) -> dict:
        return {"status": "ok", "serviceRequests": len(get_store(request))}

    @app.get(
        BASE_PATH,
        tags=["serviceRequests"],
        response_model=None,
        responses={200: {"model": ServiceRequestCollection}},
        summary="List service requests",
    )
    def list_service_requests(
        request: Request,
        q: str | None = Query(None, description="Filter, e.g. StatusCd='ORA_SVC_NEW';SeverityCd='ORA_SVC_SEV1'"),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        offset: int = Query(0, ge=0),
        orderBy: str | None = Query(None, description="e.g. CreationDate:desc,SrNumber"),
        totalResults: bool = Query(False, description="Include the total number of matching rows"),
    ) -> dict:
        try:
            conditions, order = parse_q(q), parse_order_by(orderBy)
        except QueryError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

        matches = get_store(request).query(conditions, order)
        page = matches[offset : offset + limit]
        body: dict = {
            "items": page,
            "count": len(page),
            "hasMore": offset + len(page) < len(matches),
            "limit": limit,
            "offset": offset,
            "links": [
                {"rel": "self", "href": str(request.url), "name": "serviceRequests", "kind": "collection"}
            ],
        }
        if totalResults:
            body["totalResults"] = len(matches)
        return jsonable_encoder(body)

    @app.get(f"{BASE_PATH}/{{sr_number}}", tags=["serviceRequests"], response_model=ServiceRequest)
    def get_service_request(sr_number: str, request: Request) -> ServiceRequest:
        try:
            return get_store(request).get(sr_number)
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Service request {sr_number} not found") from None

    @app.post(
        BASE_PATH,
        tags=["serviceRequests"],
        response_model=ServiceRequest,
        status_code=status.HTTP_201_CREATED,
    )
    def create_service_request(payload: ServiceRequestCreate, request: Request) -> ServiceRequest:
        try:
            return get_store(request).create(payload)
        except ValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    @app.patch(f"{BASE_PATH}/{{sr_number}}", tags=["serviceRequests"], response_model=ServiceRequest)
    def patch_service_request(
        sr_number: str, payload: ServiceRequestPatch, request: Request
    ) -> ServiceRequest:
        try:
            return get_store(request).patch(sr_number, payload)
        except NotFoundError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Service request {sr_number} not found") from None
        except ValidationError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return app


app = create_app()
