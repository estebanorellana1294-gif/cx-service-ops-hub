# Field Mapping Specification: Service Requests → Canonical Ticket

| | |
|---|---|
| **Interface** | INT-001 Service Request extraction |
| **Source** | Customer-service platform, `serviceRequests` REST resource (mock modeled on public Oracle Fusion Service docs, see [api-assumptions.md](api-assumptions.md)) |
| **Target** | NorthPeak canonical `Ticket` model, consumed by the rules engine and the KPI dashboard |
| **Direction / mode** | Source → target, batch pull (full or filtered). Write-back of status, severity, queue and assignee via `PATCH` |
| **Implementation** | `services/integration/cx_integration/mapping.py` (rules), `client.py` (transport) |
| **Version / status** | 1.0, baselined for Phase 2 |

All company names, people and data are fictional. Independent educational
demo, not affiliated with or endorsed by Oracle.

---

## 1. Purpose

NorthPeak Connect's service desk misses SLAs on high-severity tickets,
triages by hand and cannot see its backlog by queue. Both fixes (automation
rules and an operations dashboard) need ticket data that is **complete,
consistently coded and independent of the source platform's configuration**.
This specification defines how each source attribute becomes a canonical
field, and why.

## 2. Design principles

1. **Business vocabulary downstream.** Rules and KPIs use `P1`,
   `waiting_on_customer`, `BILLING`, not `ORA_SVC_SEV1` or display names.
   Source codes stay inside the mapping layer.
2. **Stable keys over labels.** Queues map by `QueueId`, not by name: admins
   rename queues ("Billing Support" → "Billing & Payments"), ids don't change.
3. **Keep the ticket, flag the defect.** Bad values get a safe default plus a
   data-quality flag. A ticket is rejected only when it cannot be
   identified or placed in time. Dropping a ticket hides real workload from
   the backlog; that is a worse outcome than a defaulted field.
4. **Defaults never hide work.** When the lifecycle state is unknown the
   ticket is treated as *open*, so it shows in the backlog and gets reviewed.
5. **One source of truth per concept.** `is_open` is derived from the
   canonical status. The source's own open/closed flag is used only to
   cross-check.
6. **UTC everywhere.** All timestamps are normalized to UTC so SLA clocks and
   daily KPIs don't shift with the server's or the agent's time zone.

## 3. Field mapping

| # | Source field | Canonical field | Transformation rule | Business reason |
|---|---|---|---|---|
| 1 | `SrNumber` | `ticket_id` | Trim. **Required**: reject the record if missing/blank. | The number agents and customers quote. It is the join key for every report and rule log. |
| 2 | `SrId` | `source_record_id` | Convert to string. Optional. | Technical key kept for traceability and support cases with the platform team. |
| 3 | *(constant)* | `source_system` | `"fusion-service-mock"` | Data lineage. Allows a second source (e.g. a field-service tool) without id collisions. |
| 4 | `Title` | `title` | Trim and collapse whitespace. Blank → `"(no title)"` + `MISSING_TITLE`. Longer than 200 characters → truncated with `…` + `TITLE_TRUNCATED`. | Keyword triage rules (Phase 3) and dashboard lists need a clean, bounded one-liner. |
| 5 | `ProblemDescription` | `description` | Trim. Blank → `null`. | Secondary input for keyword triage. Kept free-text, no length limit. |
| 6 | `StatusCd` | `status` | Value map §4.1. Unknown → derived from `StatusTypeCd` (closed → `closed`, otherwise `in_progress`) + `UNKNOWN_STATUS`. | Rules and KPIs need a fixed status list. "Waiting on customer" is named explicitly because the SLA clock pauses there (Phase 3). |
| 7 | *(derived from `status`)* | `is_open` | `true` for `new`, `in_progress`, `waiting_on_customer`. | Backlog and "open tickets" KPI. One definition used everywhere. |
| 8 | `StatusTypeCd` | *(validation only)* | If it disagrees with the derived `is_open` → `STATUS_TYPE_MISMATCH`. Canonical status wins. | Detects inconsistent source configuration without letting it corrupt the backlog count. |
| 9 | `SeverityCd` | `priority` | Value map §4.2. Unknown/missing → `P3` + `UNKNOWN_SEVERITY`. | Priority is the key into the SLA policy. P3 is the "standard" SLA: it neither inflates the critical queue nor hides the ticket. |
| 10 | `QueueId` | `queue` | Value map §4.3 by id. If the id is missing/unknown, try `QueueName` (case-insensitive) + `QUEUE_MATCHED_BY_NAME`. Still unknown → `UNMAPPED` + `UNKNOWN_QUEUE`. | Assignment rules and backlog-by-queue need stable queue codes. `UNMAPPED` is a visible bucket on the dashboard, so misrouted tickets show up instead of disappearing. |
| 11 | `QueueName` | `queue_name` | Trim. Copied as-is for display. | Agents recognize the label they see in the platform. |
| 12 | `CategoryName` | `category` | Lowercase; spaces, `_` and `-` treated alike; value map §4.4. Blank → `uncategorized` (no flag). Unknown → `uncategorized` + `UNKNOWN_CATEGORY`. | Category drives the Pareto analysis. Blank is normal for un-triaged web tickets: the triage rule fills it, so it is not a defect. |
| 13 | `ChannelTypeCd` | `channel` | Value map §4.5. Unknown → `other` + `UNKNOWN_CHANNEL`. | Channel mix analysis (cost per contact differs strongly by channel). |
| 14 | `PrimaryContactPartyName` | `customer_name` | Trim. Blank → `null`. | Display only. Personal data: not used in rules or logs. |
| 15 | `AssigneeResourceName` | `assignee` | Trim. Blank → `null` (= unassigned). | "Unassigned P1" is a key escalation trigger. Blank and null must mean the same thing. |
| 16 | `CreationDate` | `created_at` | Parse ISO 8601, convert to UTC. No offset → assume UTC + `NAIVE_TIMESTAMP_ASSUMED_UTC`. **Required**: reject if missing or unparseable. | SLA clock start and the date axis of every volume KPI. A ticket without it cannot be measured. |
| 17 | `LastUpdateDate` | `updated_at` | As #16. Missing → `created_at`. Earlier than `created_at` → `created_at` + `UPDATED_BEFORE_CREATED`. | Staleness checks ("no update in 48h"). |
| 18 | `ResolvedDate` | `resolved_at` | As #16, then: ticket open → `null` (+ `RESOLVED_DATE_ON_OPEN_TICKET` if a date was sent). Ticket closed without a date → `null` + `MISSING_RESOLVED_DATE`. Earlier than `created_at` → `null` + `RESOLVED_BEFORE_CREATED`. | SLA met/breached and MTTR are calculated from this field. An impossible date is worse than no date, so it is dropped rather than averaged in. |
| 19 | *(derived)* | `resolution_hours` | `(resolved_at − created_at)` in hours, 2 decimals. `null` when `resolved_at` is `null`. | Average resolution time KPI. Computed once here so every consumer uses the same definition. |
| 20 | *(derived)* | `data_quality_flags` | Ordered, de-duplicated list of the flags raised above. | Data stewardship: measurable source data quality, fixed at the source rather than patched downstream. |

Source attributes not listed (party ids, product, flexfields, child
resources) are **out of scope** for v1.0.

## 4. Value maps

### 4.1 Status

| Source `StatusCd` | Canonical `status` | `is_open` | SLA clock (Phase 3) |
|---|---|---|---|
| `ORA_SVC_NEW` | `new` | yes | running |
| `ORA_SVC_INPROGRESS` | `in_progress` | yes | running |
| `ORA_SVC_WAITING` | `waiting_on_customer` | yes | paused |
| `ORA_SVC_RESOLVED` | `resolved` | no | stopped |
| `ORA_SVC_CLOSED` | `closed` | no | stopped |
| *other* | from `StatusTypeCd`; `in_progress` if unknown | | flag `UNKNOWN_STATUS` |

### 4.2 Severity → priority

| Source `SeverityCd` | Canonical `priority` | Meaning at NorthPeak |
|---|---|---|
| `ORA_SVC_SEV1` | `P1` | Critical: area outage or many customers without service |
| `ORA_SVC_SEV2` | `P2` | High: one customer fully without service |
| `ORA_SVC_SEV3` | `P3` | Medium: degraded service, billing dispute |
| `ORA_SVC_SEV4` | `P4` | Low: information request, cosmetic issue |
| *other / missing* | `P3` | flag `UNKNOWN_SEVERITY` |

### 4.3 Queue

| Source `QueueId` | Source `QueueName` (fallback) | Canonical `queue` |
|---|---|---|
| 300100001 | Network Operations | `NETWORK_OPS` |
| 300100002 | Billing Support | `BILLING` |
| 300100003 | Field Installation | `FIELD_INSTALL` |
| 300100004 | Technical Support | `TECH_SUPPORT` |
| 300100005 | Customer Retention | `RETENTION` |
| *other* | *no match* | `UNMAPPED` (flag `UNKNOWN_QUEUE`) |

### 4.4 Category

| Source `CategoryName` (normalized) | Canonical `category` |
|---|---|
| outage | `outage` |
| billing | `billing` |
| installation | `installation` |
| slow speed | `slow_speed` |
| equipment | `equipment` |
| cancellation | `cancellation` |
| uncategorized / blank | `uncategorized` |
| *other* | `uncategorized` (flag `UNKNOWN_CATEGORY`) |

### 4.5 Channel

| Source `ChannelTypeCd` | Canonical `channel` |
|---|---|
| `ORA_SVC_PHONE` | `phone` |
| `ORA_SVC_EMAIL` | `email` |
| `ORA_SVC_WEB` | `web` |
| `ORA_SVC_CHAT` | `chat` |
| *other* | `other` (flag `UNKNOWN_CHANNEL`) |

## 5. Data-quality flags

| Flag | Raised when | Default applied | Owner to fix at source |
|---|---|---|---|
| `UNKNOWN_STATUS` | `StatusCd` not in §4.1 | From `StatusTypeCd`, else open | Platform admin (new status added without informing integration) |
| `STATUS_TYPE_MISMATCH` | `StatusTypeCd` contradicts `StatusCd` | Canonical status wins | Platform admin |
| `UNKNOWN_SEVERITY` | `SeverityCd` not in §4.2 | `P3` | Platform admin |
| `QUEUE_MATCHED_BY_NAME` | `QueueId` missing/unknown but name matched | Matched queue | Integration team (update id map) |
| `UNKNOWN_QUEUE` | Neither id nor name matched | `UNMAPPED` | Service desk lead (routing setup) |
| `UNKNOWN_CATEGORY` | Category not in §4.4 | `uncategorized` | Service desk lead (category list) |
| `UNKNOWN_CHANNEL` | Channel not in §4.5 | `other` | Platform admin |
| `MISSING_TITLE` | Title blank | `"(no title)"` | Agent coaching |
| `TITLE_TRUNCATED` | Title longer than 200 characters | Truncated | (informational) |
| `INVALID_TIMESTAMP` | A date field is not ISO 8601 | Field treated as missing | Platform / integration team |
| `NAIVE_TIMESTAMP_ASSUMED_UTC` | Date without UTC offset | Treated as UTC | Integration team |
| `UPDATED_BEFORE_CREATED` | `LastUpdateDate < CreationDate` | `created_at` | Platform admin |
| `RESOLVED_DATE_ON_OPEN_TICKET` | Open ticket carries a `ResolvedDate` | Ignored | Platform admin (reopen workflow) |
| `MISSING_RESOLVED_DATE` | Closed ticket without `ResolvedDate` | `null`, excluded from MTTR | Platform admin |
| `RESOLVED_BEFORE_CREATED` | `ResolvedDate < CreationDate` | `null`, excluded from MTTR | Platform admin |

**Rejections** (record not loaded, listed in the run report with id, field
and reason): missing/blank `SrNumber`, missing/unparseable `CreationDate`,
record that is not a JSON object.

## 6. Extraction & error handling

| Situation | Behavior | Reason |
|---|---|---|
| Large collections | Paged with `limit`/`offset` (default 100 per page) until `hasMore=false` | Bounded memory and response size |
| Data changing during extraction | Sorted by `SrId:asc`; duplicates (same `SrNumber`) skipped | New tickets append at the end, so offset paging stays stable |
| Inconsistent paging (`hasMore` with empty page, offset mismatch, never-ending collection) | Run stops with `PaginationError` | Prevents silent infinite loops or gaps |
| `429`, `500`, `502`, `503`, `504`, connection error, timeout on GET / PATCH | Retry up to 4 attempts, exponential backoff with full jitter (0.5s base, 8s cap). `Retry-After` honored | Transient failures should not need manual reruns; jitter avoids synchronized bursts on a recovering system |
| Same failures on POST (create) | Retry only on `429`, `503` and connection-refused. A timeout after sending raises `UnknownOutcomeError` | A blind retry could create a duplicate ticket. Someone has to check the source first |
| `400`, `401`, `403`, `404`, `422` | No retry, typed error (`ClientRequestError`, `NotFoundError`) | The same request will fail again; retrying only adds load |
| Retries exhausted | Run stops with `RetryExhaustedError` (last error attached) | A partial extraction must never be presented as complete: it would understate the backlog |
| Single bad record | Rejected or flagged (§5). The run continues | One defect should not block the whole desk's data |

## 7. Reconciliation controls

Every run produces a report (`python -m cx_integration` prints it as JSON):

```json
{
  "records_read": 200,
  "tickets_mapped": 200,
  "tickets_clean": 200,
  "records_rejected": 0,
  "data_quality_flags": {},
  "rejections": [],
  "pages": 2,
  "http_requests": 2,
  "retries": 0
}
```

* **Completeness:** `records_read = tickets_mapped + records_rejected`.
  The source's `totalResults` is compared with `records_read` in the contract
  tests.
* **Accuracy:** count per priority in the target equals the source count per
  `SeverityCd` (automated in `test_contract_mock_api.py`).
* **Quality KPI:** `tickets_clean / tickets_mapped`, tracked over time. The
  target is ≥ 98%.

## 8. Worked example

Source record (`ProblemDescription` / `description` omitted for brevity):

```json
{
  "SrId": 10152, "SrNumber": "SR0000010152",
  "Title": "Wi-Fi drops when NP-Gateway X2 overheats",
  "StatusCd": "ORA_SVC_WAITING", "StatusTypeCd": "ORA_SVC_OPEN",
  "SeverityCd": "ORA_SVC_SEV1", "QueueId": 300100004, "QueueName": "Technical Support",
  "CategoryName": "Equipment", "ChannelTypeCd": "ORA_SVC_EMAIL",
  "PrimaryContactPartyName": "Ruby Ellison", "AssigneeResourceName": "Marcus Bell",
  "CreationDate": "2026-09-15T09:35:42Z", "LastUpdateDate": "2026-09-28T14:16:59Z",
  "ResolvedDate": null
}
```

Canonical ticket:

```json
{
  "ticket_id": "SR0000010152", "source_system": "fusion-service-mock", "source_record_id": "10152",
  "title": "Wi-Fi drops when NP-Gateway X2 overheats",
  "status": "waiting_on_customer", "is_open": true, "priority": "P1",
  "queue": "TECH_SUPPORT", "queue_name": "Technical Support",
  "category": "equipment", "channel": "email",
  "customer_name": "Ruby Ellison", "assignee": "Marcus Bell",
  "created_at": "2026-09-15T09:35:42Z", "updated_at": "2026-09-28T14:16:59Z",
  "resolved_at": null, "resolution_hours": null, "data_quality_flags": []
}
```

A P1 ticket that has been waiting on the customer for weeks is exactly what
the Phase 3 rules will catch (paused SLA clock and stale-ticket escalation).

## 9. Assumptions and open points

| # | Item | Status |
|---|---|---|
| A1 | Lookup codes follow the public docs naming pattern; a real tenant may use its own codes. The value maps are the single place to change. | Assumption |
| A2 | Severity is used as priority. Some deployments separate impact/urgency; that would add a priority matrix here. | Assumption |
| A3 | The source returns UTC timestamps; the naive-timestamp rule is a safety net. | Assumption |
| O1 | Incremental extraction (`LastUpdateDate >= last run`) instead of full pulls once volumes grow. | Open (roadmap) |
| O2 | Customer name is personal data. Masking in non-production environments to be agreed with the data protection officer. | Open |
