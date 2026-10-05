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
| 2 | Integration layer + field mapping | Done |
| 3 | Automation rules engine (YAML) | Planned |
| 4 | KPI dashboard (React) | Planned |
| 5 | Architecture docs, ADRs, DMAIC business case | Planned |
| 6 | Polish, CI | Planned |

## Repository layout

```
services/mock-api/     FastAPI mock of the serviceRequests resource
services/integration/  Client + mapping to the canonical ticket model
docs/                  Design notes (api-assumptions.md, field-mapping.md, ...)
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

48 tests cover every endpoint (paging, each filter operator, sorting,
create/patch side effects, validation errors, fault injection) and the properties of the seed
data.

## Phase 2: Integration Layer

`services/integration/` is a standalone Python package (`cx_integration`)
that pulls service requests from the source API and turns them into
NorthPeak's **canonical ticket model**. Downstream components (rules engine,
dashboard) only ever see that model, never source codes like `ORA_SVC_SEV1`.

```
source API ──► client.py ──► mapping.py ──► canonical.Ticket ──► rules engine / dashboard
              paging, retries   value maps,
              typed errors      data-quality flags
```

| Module | Responsibility |
|---|---|
| `client.py` | HTTP calls, pagination (`limit`/`offset` until `hasMore=false`), error classification |
| `retry.py` | Exponential backoff with full jitter, honors `Retry-After` |
| `mapping.py` | Source record → canonical `Ticket`, value maps, data-quality flags, reject rules |
| `canonical.py` | The canonical model (`Ticket`, `Priority`, `Queue`, `TicketStatus`, ...) |
| `pipeline.py` | Extract + map + run report (read / mapped / rejected / flagged / retries) |

**The functional deliverable is [docs/field-mapping.md](docs/field-mapping.md):**
source field → canonical field → transformation rule → business reason, value
maps, data-quality flags with owners, error handling and reconciliation
controls.

### Run it

```bash
docker compose up -d --build mock-api
docker compose run --rm integration --open-only          # backlog extraction report

# Show retries: make 30% of API calls fail with 503
MOCK_FAULT_RATE=0.3 docker compose up -d mock-api
docker compose run --rm integration --page-size 10 -v

# Or run locally and save the canonical tickets to a file
pip install -e services/integration
python -m cx_integration --out tickets.json
```

### Design decisions

* **Canonical model between source and consumers.** Swapping or adding a
  ticket source means writing a new mapper. Rules and KPIs stay untouched.
* **Keep the ticket, flag the defect.** Unknown codes get safe defaults plus a
  data-quality flag. Only records without `SrNumber` or `CreationDate` are
  rejected. Dropping tickets would hide real workload.
* **Retry only what is safe to retry.** GET and PATCH retry on 429/5xx and
  network errors. POST retries only when the server provably did not process
  it, and a timeout after sending raises `UnknownOutcomeError` instead of
  risking a duplicate ticket.
* **Stable paging.** Extraction sorts by `SrId` and de-duplicates, so tickets
  created mid-run don't cause skipped or repeated rows.
* **Fail loudly on partial data.** If retries run out, the run fails instead of
  returning an incomplete backlog.

### Run the tests

```bash
cd services/integration
pip install -r requirements-dev.txt
pytest
```

98 tests: retry/backoff maths, pagination edge cases, retry policy per HTTP
method and status, every mapping rule and flag, and contract tests that run
the real mock API in-process. The contract tests include a 30%-fault run and
reconcile source and target totals.

## License

MIT, see [LICENSE](LICENSE).
