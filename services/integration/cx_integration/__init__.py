"""Integration layer between the source service platform and NorthPeak's internal tools."""

from .canonical import Category, Channel, Priority, Queue, Ticket, TicketStatus
from .client import ServiceRequestClient
from .errors import (
    ApiError,
    ClientRequestError,
    IntegrationError,
    MappingError,
    NotFoundError,
    PaginationError,
    RetryExhaustedError,
    ServerError,
    UnknownOutcomeError,
)
from .mapping import map_service_request
from .pipeline import ExtractionReport, extract_tickets
from .retry import RetryPolicy

__all__ = [
    "ApiError",
    "Category",
    "Channel",
    "ClientRequestError",
    "ExtractionReport",
    "IntegrationError",
    "MappingError",
    "NotFoundError",
    "PaginationError",
    "Priority",
    "Queue",
    "RetryExhaustedError",
    "RetryPolicy",
    "ServerError",
    "ServiceRequestClient",
    "Ticket",
    "TicketStatus",
    "UnknownOutcomeError",
    "extract_tickets",
    "map_service_request",
]
