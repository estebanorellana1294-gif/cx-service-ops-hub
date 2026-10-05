from datetime import datetime


def test_default_page_shape(client, base):
    body = client.get(base).json()
    assert set(body) == {"items", "count", "hasMore", "limit", "offset", "links"}
    assert body["count"] == len(body["items"]) == 25
    assert body["limit"] == 25 and body["offset"] == 0
    assert body["hasMore"] is True
    assert body["links"][0]["rel"] == "self"


def test_default_order_is_newest_first(client, base):
    items = client.get(base, params={"limit": 50}).json()["items"]
    dates = [datetime.fromisoformat(i["CreationDate"]) for i in items]
    assert dates == sorted(dates, reverse=True)


def test_pagination_walks_full_collection_without_duplicates(client, base):
    seen, offset = [], 0
    while True:
        body = client.get(base, params={"limit": 60, "offset": offset}).json()
        seen += [i["SrNumber"] for i in body["items"]]
        if not body["hasMore"]:
            break
        offset += body["count"]
    assert len(seen) == len(set(seen)) == 200


def test_last_page_has_no_more(client, base):
    body = client.get(base, params={"limit": 25, "offset": 175}).json()
    assert body["count"] == 25 and body["hasMore"] is False


def test_offset_past_end_returns_empty_page(client, base):
    body = client.get(base, params={"offset": 1000}).json()
    assert body["items"] == [] and body["count"] == 0 and body["hasMore"] is False


def test_total_results_only_when_requested(client, base):
    body = client.get(base, params={"totalResults": "true", "limit": 5}).json()
    assert body["totalResults"] == 200


def test_limit_bounds_are_enforced(client, base):
    assert client.get(base, params={"limit": 0}).status_code == 422
    assert client.get(base, params={"limit": 501}).status_code == 422
    assert client.get(base, params={"offset": -1}).status_code == 422


def _all(client, base, q):
    body = client.get(base, params={"q": q, "limit": 500, "totalResults": "true"}).json()
    assert body["count"] == body["totalResults"]
    return body["items"]


def test_filter_by_status(client, base):
    items = _all(client, base, "StatusCd='ORA_SVC_WAITING'")
    assert items and all(i["StatusCd"] == "ORA_SVC_WAITING" for i in items)


def test_filter_by_severity(client, base):
    items = _all(client, base, "SeverityCd='ORA_SVC_SEV1'")
    assert items and all(i["SeverityCd"] == "ORA_SVC_SEV1" for i in items)


def test_filter_by_queue_name_and_id_agree(client, base):
    by_name = _all(client, base, "QueueName='Billing Support'")
    by_id = _all(client, base, "QueueId=300100002")
    assert by_name and [i["SrNumber"] for i in by_name] == [i["SrNumber"] for i in by_id]


def test_combined_filters_are_anded(client, base):
    items = _all(client, base, "StatusTypeCd='ORA_SVC_OPEN';QueueName='Technical Support'")
    assert items
    assert all(i["StatusTypeCd"] == "ORA_SVC_OPEN" and i["QueueName"] == "Technical Support" for i in items)


def test_filter_by_date_range(client, base):
    items = _all(client, base, "CreationDate>='2026-09-01T00:00:00Z';CreationDate<'2026-09-08T00:00:00Z'")
    assert items
    for i in items:
        assert "2026-09-01" <= i["CreationDate"][:10] <= "2026-09-07"


def test_not_equal_operator(client, base):
    items = _all(client, base, "StatusTypeCd!='ORA_SVC_CLOSED'")
    assert items and all(i["StatusTypeCd"] == "ORA_SVC_OPEN" for i in items)


def test_like_is_case_insensitive(client, base):
    items = _all(client, base, "Title LIKE '%INTERNET%'")
    assert items and all("internet" in i["Title"].lower() for i in items)


def test_quoted_value_may_contain_semicolon_and_quote(client, base):
    assert _all(client, base, "Title='a;b''c'") == []


def test_null_attribute_never_matches(client, base):
    items = _all(client, base, "ResolvedDate>='2000-01-01T00:00:00Z'")
    assert items and all(i["ResolvedDate"] is not None for i in items)


def test_order_by_ascending_and_multiple_keys(client, base):
    items = client.get(base, params={"orderBy": "SeverityCd:asc,CreationDate:desc", "limit": 500}).json()["items"]
    keys = [(i["SeverityCd"], i["CreationDate"]) for i in items]
    assert [k[0] for k in keys] == sorted(k[0] for k in keys)
    for sev in {k[0] for k in keys}:
        dates = [k[1] for k in keys if k[0] == sev]
        assert dates == sorted(dates, reverse=True)


def test_order_by_puts_nulls_last(client, base):
    items = client.get(base, params={"orderBy": "ResolvedDate:desc", "limit": 500}).json()["items"]
    resolved = [i["ResolvedDate"] for i in items]
    first_null = resolved.index(None)
    assert all(r is None for r in resolved[first_null:])


def test_invalid_q_returns_400(client, base):
    for bad in ["StatusCd", "Foo='x'", "QueueId=abc", "Title='unterminated", "CreationDate>'yesterday'"]:
        resp = client.get(base, params={"q": bad})
        assert resp.status_code == 400, bad
        assert resp.json()["detail"]


def test_invalid_order_by_returns_400(client, base):
    assert client.get(base, params={"orderBy": "Nope"}).status_code == 400
    assert client.get(base, params={"orderBy": "SrId:sideways"}).status_code == 400
