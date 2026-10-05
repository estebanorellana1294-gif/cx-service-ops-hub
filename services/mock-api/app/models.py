"""Pydantic schemas for the serviceRequests resource.

Enum types are imported under aliases because the attribute names
(StatusCd, SeverityCd, ...) would otherwise shadow them in class bodies.

Field names intentionally use the PascalCase attribute names of the
publicly documented Oracle Fusion Service ``serviceRequests`` resource.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .domain import CATEGORIES
from .domain import ChannelTypeCd as ChannelType
from .domain import SeverityCd as Severity
from .domain import StatusCd as Status
from .domain import StatusTypeCd as StatusType


class ServiceRequest(BaseModel):
    """A service request (ticket) as returned by the API."""

    SrId: int
    SrNumber: str
    Title: str
    ProblemDescription: str
    StatusCd: Status
    StatusTypeCd: StatusType
    SeverityCd: Severity
    QueueId: int
    QueueName: str
    CategoryName: str
    ChannelTypeCd: ChannelType
    PrimaryContactPartyName: str
    AssigneeResourceName: str | None = None
    CreationDate: datetime
    LastUpdateDate: datetime
    ResolvedDate: datetime | None = None


class ServiceRequestCreate(BaseModel):
    """Payload for POST. Server assigns ids, status and audit dates."""

    model_config = ConfigDict(extra="forbid")

    Title: str = Field(min_length=3, max_length=200)
    ProblemDescription: str = Field(default="", max_length=4000)
    SeverityCd: Severity = Severity.SEV3
    QueueId: int | None = None
    CategoryName: str | None = None
    ChannelTypeCd: ChannelType = ChannelType.WEB
    PrimaryContactPartyName: str = Field(min_length=1, max_length=200)
    AssigneeResourceName: str | None = None


class ServiceRequestPatch(BaseModel):
    """Payload for PATCH. Only updatable attributes are accepted.

    Read-only attributes (SrId, SrNumber, CreationDate, ...) are rejected
    by ``extra="forbid"`` so the client gets a clear 422 instead of a
    silently ignored field.
    """

    model_config = ConfigDict(extra="forbid")

    Title: str | None = Field(default=None, min_length=3, max_length=200)
    ProblemDescription: str | None = Field(default=None, max_length=4000)
    StatusCd: Status | None = None
    SeverityCd: Severity | None = None
    QueueId: int | None = None
    CategoryName: str | None = None
    AssigneeResourceName: str | None = None


class Link(BaseModel):
    rel: str
    href: str
    name: str
    kind: str


class ServiceRequestCollection(BaseModel):
    """Collection envelope: items + paging metadata."""

    items: list[ServiceRequest]
    count: int
    hasMore: bool
    limit: int
    offset: int
    totalResults: int | None = None
    links: list[Link]


VALID_CATEGORIES = frozenset(CATEGORIES)
