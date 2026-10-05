# API assumptions: the mock `serviceRequests` resource

> **Modeled on public docs, may differ from the real API.**
> The mock service approximates the shape of the `serviceRequests` resource
> described in Oracle's publicly available Fusion Service REST API
> documentation. It was written from that public documentation only, for
> educational purposes. Field names, lookup codes, query syntax and error
> behavior are simplified and **may differ from the real API**. Do not use
> this mock as a reference for a production integration.
>
> Independent educational demo. Not affiliated with or endorsed by Oracle.

## Why model the mock on a real API?

The integration layer and rules engine in later phases should deal with the
same things a real CX integration project deals with: PascalCase attribute
names, coded lookup values (`ORA_SVC_SEV1`), offset pagination with a
`hasMore` flag and a query-by-example filter language. A mock with a generic
REST shape would hide exactly the mapping work this project is meant to show.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/crmRestApi/resources/11.13.18.05/serviceRequests` | List with paging, filtering and sorting |
| `GET` | `/crmRestApi/resources/11.13.18.05/serviceRequests/{SrNumber}` | Get one service request |
| `POST` | `/crmRestApi/resources/11.13.18.05/serviceRequests` | Create |
| `PATCH` | `/crmRestApi/resources/11.13.18.05/serviceRequests/{SrNumber}` | Partial update |
| `GET` | `/health` | Liveness (mock-only, not part of the modeled API) |

The version segment `11.13.18.05` follows the URL pattern in the public docs.
The mock serves only this one version.

## Attributes

| Attribute | Type | Notes |
|---|---|---|
| `SrId` | integer | Surrogate key, server-assigned |
| `SrNumber` | string | Business key used in URLs, format `SR` + 10 digits |
| `Title` | string | Short summary (3 to 200 characters) |
| `ProblemDescription` | string | Free text |
| `StatusCd` | lookup | `ORA_SVC_NEW`, `ORA_SVC_INPROGRESS`, `ORA_SVC_WAITING`, `ORA_SVC_RESOLVED`, `ORA_SVC_CLOSED` |
| `StatusTypeCd` | lookup | `ORA_SVC_OPEN` / `ORA_SVC_CLOSED`, derived from `StatusCd`, read-only |
| `SeverityCd` | lookup | `ORA_SVC_SEV1` (critical) to `ORA_SVC_SEV4` (low) |
| `QueueId` | integer | Must be one of the five configured queues |
| `QueueName` | string | Derived from `QueueId`, read-only |
| `CategoryName` | string | Outage, Billing, Installation, Slow Speed, Equipment, Cancellation |
| `ChannelTypeCd` | lookup | `ORA_SVC_PHONE`, `ORA_SVC_EMAIL`, `ORA_SVC_WEB`, `ORA_SVC_CHAT` |
| `PrimaryContactPartyName` | string | Synthetic customer name |
| `AssigneeResourceName` | string, nullable | Agent name; `null` = unassigned |
| `CreationDate` | datetime (UTC) | Server-assigned |
| `LastUpdateDate` | datetime (UTC) | Set on every change |
| `ResolvedDate` | datetime (UTC), nullable | Set when the ticket moves to RESOLVED/CLOSED, cleared on reopen |

**Simplifications.** The real resource has far more attributes (contacts and
accounts as party ids, product, child resources such as messages and
attachments, flexfields). The mock flattens what it keeps into plain names
(for example a contact *name* and no party id). Exact lookup codes for
status and severity are configurable in a real deployment, so the values
above are illustrative.

### Reference data

| QueueId | QueueName |
|---|---|
| 300100001 | Network Operations |
| 300100002 | Billing Support |
| 300100003 | Field Installation |
| 300100004 | Technical Support (default for new tickets without a queue) |
| 300100005 | Customer Retention |

## Collection response

```json
{
  "items": [ { "SrNumber": "SR0000010152", "...": "..." } ],
  "count": 25,
  "hasMore": true,
  "limit": 25,
  "offset": 0,
  "links": [ { "rel": "self", "href": "...", "name": "serviceRequests", "kind": "collection" } ],
  "totalResults": 200
}
```

* `count` is the number of items **in this page**, not the total.
* `totalResults` is returned only when the request includes `totalResults=true`.
* `limit` defaults to 25 and is capped at 500. `offset` is zero-based.
* `hasMore` is `true` when rows exist after this page. Clients should page
  until `hasMore` is `false`.
* Only a collection-level `self` link is returned. Item-level links, `next`
  links and the `fields`, `onlyData`, `expand` and `finder` parameters are
  **not implemented**.

## Filtering with `q`

```
q=StatusTypeCd='ORA_SVC_OPEN';SeverityCd='ORA_SVC_SEV1'
q=QueueName='Billing Support'
q=CreationDate>='2026-09-01T00:00:00Z';CreationDate<'2026-09-08T00:00:00Z'
q=Title LIKE '%router%'
```

| Rule | Mock behavior |
|---|---|
| Combining | `;` separates conditions, combined with **AND**. `OR` and parentheses are not supported. |
| Operators | `=`, `!=` (or `<>`), `>`, `>=`, `<`, `<=`, `LIKE` |
| Literals | Strings in single quotes, `''` escapes a quote. Integers may be unquoted. Dates in ISO 8601. |
| `LIKE` | `%` is the wildcard, comparison is case-insensitive |
| Nulls | A condition on a null attribute never matches (no `IS NULL` support) |
| Filterable attributes | All attributes above except `SrId` and `ProblemDescription` |
| Errors | Unknown attribute, bad operator or bad literal returns `400` |

The real API also offers a richer row-match expression syntax and named
finders. The mock does not.

## Sorting with `orderBy`

`orderBy=SeverityCd:asc,CreationDate:desc`. Direction defaults to `asc`.
Nulls always sort last. Without `orderBy` the list is newest first
(`CreationDate:desc`), the way an agent worklist usually opens.

## Create (`POST`)

Required: `Title`, `PrimaryContactPartyName`. Optional: `ProblemDescription`,
`SeverityCd` (default `ORA_SVC_SEV3`), `QueueId` (default Technical Support),
`CategoryName`, `ChannelTypeCd` (default `ORA_SVC_WEB`), `AssigneeResourceName`.
The server assigns `SrId`, `SrNumber`, `StatusCd=ORA_SVC_NEW` and the dates,
and returns `201` with the full record. Read-only or unknown attributes in
the payload are rejected with `422`.

## Update (`PATCH`)

Partial update. Updatable: `Title`, `ProblemDescription`, `StatusCd`,
`SeverityCd`, `QueueId`, `CategoryName`, `AssigneeResourceName` (the only one
that may be set to `null`). Side effects, applied by the server:

* `StatusTypeCd` and `QueueName` are recalculated.
* Moving to RESOLVED or CLOSED sets `ResolvedDate` (an existing one is kept,
  so RESOLVED → CLOSED does not move the resolution time).
* Moving back to an open status clears `ResolvedDate`.
* `LastUpdateDate` is set to the current time.

The mock does **not** enforce a status transition model (any status can go
to any status). Real deployments usually restrict transitions per
configuration.

## Content types

Both `application/json` and `application/vnd.oracle.adf.resourceitem+json`
request bodies are accepted. Responses are `application/json`.

## Errors

| Status | When |
|---|---|
| `400` | Invalid `q`/`orderBy`, unknown `QueueId` or `CategoryName`, null for a non-nullable attribute |
| `404` | `SrNumber` not found |
| `422` | Payload fails schema validation (missing field, bad lookup code, read-only attribute) |

Error bodies use FastAPI's `{"detail": ...}` format. The real API returns
errors in a different format.

## Not modeled

Authentication, ETags / optimistic locking, `DELETE`, child resources,
batch requests, rate limiting. Persistence is in memory: every restart
re-seeds the same deterministic data set.
