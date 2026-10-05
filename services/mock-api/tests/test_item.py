from tests.conftest import CLOCK_NOW

NEW_TICKET = {
    "Title": "Router lights blinking red",
    "ProblemDescription": "Gateway shows red LED since storm.",
    "SeverityCd": "ORA_SVC_SEV2",
    "QueueId": 300100004,
    "CategoryName": "Equipment",
    "ChannelTypeCd": "ORA_SVC_CHAT",
    "PrimaryContactPartyName": "Test Customer",
}


def _first_open(client, base):
    q = "StatusTypeCd='ORA_SVC_OPEN';StatusCd!='ORA_SVC_NEW'"
    return client.get(base, params={"q": q, "limit": 1}).json()["items"][0]


# --- GET by SrNumber -------------------------------------------------------


def test_get_by_sr_number(client, base):
    listed = client.get(base, params={"limit": 1}).json()["items"][0]
    resp = client.get(f"{base}/{listed['SrNumber']}")
    assert resp.status_code == 200
    assert resp.json() == listed


def test_get_unknown_returns_404(client, base):
    resp = client.get(f"{base}/SR9999999999")
    assert resp.status_code == 404
    assert "SR9999999999" in resp.json()["detail"]


# --- POST ------------------------------------------------------------------


def test_create_assigns_server_fields(client, base):
    resp = client.post(base, json=NEW_TICKET)
    assert resp.status_code == 201
    sr = resp.json()
    assert sr["SrNumber"] == "SR0000010201"  # next after the 200 seeded tickets
    assert sr["StatusCd"] == "ORA_SVC_NEW" and sr["StatusTypeCd"] == "ORA_SVC_OPEN"
    assert sr["QueueName"] == "Technical Support"
    assert sr["CreationDate"] == sr["LastUpdateDate"] == CLOCK_NOW.isoformat().replace("+00:00", "Z")
    assert sr["ResolvedDate"] is None
    assert client.get(f"{base}/{sr['SrNumber']}").json() == sr


def test_create_minimal_payload_uses_defaults(client, base):
    sr = client.post(base, json={"Title": "Question about plan", "PrimaryContactPartyName": "A B"}).json()
    assert sr["SeverityCd"] == "ORA_SVC_SEV3"
    assert sr["QueueName"] == "Technical Support"
    assert sr["CategoryName"] == "Uncategorized"
    assert sr["ChannelTypeCd"] == "ORA_SVC_WEB"


def test_create_accepts_oracle_style_content_type(client, base):
    resp = client.post(
        base,
        content='{"Title": "Billing question", "PrimaryContactPartyName": "A B"}',
        headers={"Content-Type": "application/vnd.oracle.adf.resourceitem+json"},
    )
    assert resp.status_code == 201


def test_create_shows_up_in_list(client, base):
    sr = client.post(base, json=NEW_TICKET).json()
    total = client.get(base, params={"totalResults": "true", "limit": 1}).json()
    assert total["totalResults"] == 201
    assert total["items"][0]["SrNumber"] == sr["SrNumber"]  # newest first


def test_create_rejects_invalid_payloads(client, base):
    assert client.post(base, json={"PrimaryContactPartyName": "A B"}).status_code == 422  # no Title
    assert client.post(base, json={**NEW_TICKET, "SeverityCd": "URGENT"}).status_code == 422
    assert client.post(base, json={**NEW_TICKET, "SrNumber": "SR1"}).status_code == 422  # read-only
    assert client.post(base, json={**NEW_TICKET, "QueueId": 1}).status_code == 400
    assert client.post(base, json={**NEW_TICKET, "CategoryName": "Pizza"}).status_code == 400


# --- PATCH -----------------------------------------------------------------


def test_patch_partial_update(client, base):
    sr = _first_open(client, base)
    resp = client.patch(f"{base}/{sr['SrNumber']}", json={"SeverityCd": "ORA_SVC_SEV1"})
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["SeverityCd"] == "ORA_SVC_SEV1"
    assert updated["Title"] == sr["Title"]
    assert updated["LastUpdateDate"] == CLOCK_NOW.isoformat().replace("+00:00", "Z")


def test_patch_queue_updates_queue_name(client, base):
    sr = _first_open(client, base)
    updated = client.patch(f"{base}/{sr['SrNumber']}", json={"QueueId": 300100001}).json()
    assert updated["QueueName"] == "Network Operations"


def test_patch_resolve_sets_resolved_date_and_status_type(client, base):
    sr = _first_open(client, base)
    updated = client.patch(f"{base}/{sr['SrNumber']}", json={"StatusCd": "ORA_SVC_RESOLVED"}).json()
    assert updated["StatusTypeCd"] == "ORA_SVC_CLOSED"
    assert updated["ResolvedDate"] == updated["LastUpdateDate"]


def test_patch_close_keeps_original_resolved_date(client, base):
    resolved = client.get(base, params={"q": "StatusCd='ORA_SVC_RESOLVED'", "limit": 1}).json()["items"][0]
    closed = client.patch(f"{base}/{resolved['SrNumber']}", json={"StatusCd": "ORA_SVC_CLOSED"}).json()
    assert closed["ResolvedDate"] == resolved["ResolvedDate"]


def test_patch_reopen_clears_resolved_date(client, base):
    closed = client.get(base, params={"q": "StatusCd='ORA_SVC_CLOSED'", "limit": 1}).json()["items"][0]
    reopened = client.patch(f"{base}/{closed['SrNumber']}", json={"StatusCd": "ORA_SVC_INPROGRESS"}).json()
    assert reopened["StatusTypeCd"] == "ORA_SVC_OPEN"
    assert reopened["ResolvedDate"] is None


def test_patch_can_unassign(client, base):
    sr = _first_open(client, base)
    assert sr["AssigneeResourceName"]
    updated = client.patch(f"{base}/{sr['SrNumber']}", json={"AssigneeResourceName": None}).json()
    assert updated["AssigneeResourceName"] is None


def test_patch_is_persisted(client, base):
    sr = _first_open(client, base)
    client.patch(f"{base}/{sr['SrNumber']}", json={"Title": "Updated title"})
    assert client.get(f"{base}/{sr['SrNumber']}").json()["Title"] == "Updated title"


def test_patch_rejects_invalid_changes(client, base):
    url = f"{base}/{_first_open(client, base)['SrNumber']}"
    assert client.patch(url, json={"SrNumber": "SR1"}).status_code == 422  # read-only
    assert client.patch(url, json={"CreationDate": "2020-01-01T00:00:00Z"}).status_code == 422
    assert client.patch(url, json={"StatusCd": "DONE"}).status_code == 422
    assert client.patch(url, json={"Title": None}).status_code == 400
    assert client.patch(url, json={"QueueId": 42}).status_code == 400
    assert client.patch(url, json={"CategoryName": "Pizza"}).status_code == 400


def test_patch_unknown_returns_404(client, base):
    assert client.patch(f"{base}/SR9999999999", json={"Title": "Nope nope"}).status_code == 404


# --- misc ------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "serviceRequests": 200}


def test_openapi_documents_the_resource(client, base):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[base]) == {"get", "post"}
    assert set(paths[base + "/{sr_number}"]) == {"get", "patch"}
