# CX Service Ops Hub

Demo of a customer-service operations toolkit: a mock CX platform API, an
integration layer, an automation rules engine and a KPI dashboard, built
around a fictional internet & TV provider.

> **Independent educational demo. Not affiliated with or endorsed by Oracle.**
> The mock API is modeled on the publicly documented Oracle Fusion Service
> REST API (`serviceRequests` resource) and may differ from the real API.
> All data is synthetic. See [docs/api-assumptions.md](docs/api-assumptions.md).

## Business context

**NorthPeak Connect** is a fictional mid-size home internet & TV provider with
about 150k customers. Its service desk struggles with:

* SLA breaches on high-severity tickets,
* manual triage of incoming requests,
* no visibility of the backlog by queue.

This project builds, phase by phase, the pieces a CX solution architect would
put in front of that problem.

| Phase | Scope | Status |
|---|---|---|
| 1 | Mock Service API | Done |
| 2 | Integration layer + field mapping | Planned |
| 3 | Automation rules engine (YAML) | Planned |
| 4 | KPI dashboard (React) | Planned |
| 5 | Architecture docs, ADRs, DMAIC business case | Planned |
| 6 | Polish, CI | Planned |

## Repository layout

```
services/mock-api/     FastAPI mock of the serviceRequests resource
docs/                  Design notes (api-assumptions.md, ...)
docker-compose.yml     Runs everything with one command
```

## Quick start

```bash
docker compose up --build
```

* API: <http://localhost:8000/crmRestApi/resources/11.13.18.05/serviceRequests>
* Interactive docs (Swagger UI): <http://localhost:8000/docs>

For reproducible data (screenshots, demos), pin the seed's reference date:

```bash
SEED_REFERENCE_DATE=2026-10-05T12:00:00Z docker compose up --build
```

## Phase 1: Mock Service API

A FastAPI service that behaves like the `serviceRequests` resource of a
CX platform, loaded with 200 synthetic tickets from the last 90 days.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/crmRestApi/resources/11.13.18.05/serviceRequests` | List: `limit`/`offset` paging, `q` filter, `orderBy`, `totalResults` |
| `GET` | `.../serviceRequests/{SrNumber}` | Get one |
| `POST` | `.../serviceRequests` | Create |
| `PATCH` | `.../serviceRequests/{SrNumber}` | Partial update |

### Examples

```bash
BASE=http://localhost:8000/crmRestApi/resources/11.13.18.05/serviceRequests

# Open Sev1 tickets, with the total count
curl -G "$BASE" --data-urlencode "q=StatusTypeCd='ORA_SVC_OPEN';SeverityCd='ORA_SVC_SEV1'" \
     --data-urlencode "totalResults=true"

# Billing queue backlog, oldest first, second page of 10
curl -G "$BASE" --data-urlencode "q=QueueName='Billing Support';StatusTypeCd='ORA_SVC_OPEN'" \
     --data-urlencode "orderBy=CreationDate:asc" --data-urlencode "limit=10" --data-urlencode "offset=10"

# Create a ticket
curl -X POST "$BASE" -H "Content-Type: application/json" \
     -d '{"Title":"No signal after storm","PrimaryContactPartyName":"Jane Sample","SeverityCd":"ORA_SVC_SEV2","QueueId":300100001,"CategoryName":"Outage"}'

# Resolve it (sets ResolvedDate and StatusTypeCd automatically)
curl -X PATCH "$BASE/SR0000010201" -H "Content-Type: application/json" -d '{"StatusCd":"ORA_SVC_RESOLVED"}'
```

### Seed data

`app/seed.py` generates the tickets deterministically from a random seed and
a reference date, so the same inputs always give the same data set. The
distributions are shaped to resemble a real ISP service desk and to give
later phases something to find:

| Aspect | How it is generated |
|---|---|
| Categories | Pareto-like mix: Slow Speed and Billing lead, Cancellation is rare |
| Volume | Weekdays busier than weekends, business-hours arrival curve |
| Incidents | Two regional outage days (Pine Hollow, Cedar Ridge) create volume spikes |
| Severity | Depends on category (outages are mostly Sev1/Sev2, billing mostly Sev3/Sev4) |
| Routing | Category decides the queue; some Slow Speed tickets go to Network Operations |
| Resolution time | Log-normal per severity; Sev1 often misses its target |
| Backlog | Recent and some stale tickets remain open in every queue |

Names, places (Pine Hollow, Cedar Ridge, ...) and devices (NP-Gateway X2,
...) are invented.

### Design decisions

* **API shape copied from public docs**: PascalCase attributes, `ORA_SVC_*`
  lookup codes, `items/count/hasMore/limit/offset` envelope and `q` filters.
  This makes the Phase 2 mapping work realistic. Every approximation is listed
  in [docs/api-assumptions.md](docs/api-assumptions.md).
* **In-memory store, re-seeded at start-up**: no database server to run, and
  every demo starts from the same known state.
* **`SrNumber` as the URL key**: matches the documented resource, and it is
  the number agents and customers actually quote.
* **Strict payloads**: read-only or unknown attributes are rejected (422)
  instead of silently ignored, so integration bugs surface early.
* **App factory with injectable store and clock**: tests run against a fixed
  date and are fully deterministic.

### Run the tests

```bash
cd services/mock-api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
```

46 tests cover every endpoint (paging, each filter operator, sorting,
create/patch side effects, validation errors) and the properties of the seed
data.

## License

MIT, see [LICENSE](LICENSE).
