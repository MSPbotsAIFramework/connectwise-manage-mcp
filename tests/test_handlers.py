# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Tool behaviour against a mocked ConnectWise API."""

import base64
import json

import httpx
import pytest
import respx
from conftest import BASE

pytestmark = pytest.mark.usefixtures("creds")


def sent(route) -> object:
    return json.loads(route.calls.last.request.content)


def params(route) -> httpx.QueryParams:
    return route.calls.last.request.url.params


# ---- client plumbing ------------------------------------------------------------


@respx.mock
async def test_auth_headers_and_paging(call):
    route = respx.get(f"{BASE}/service/tickets").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "summary": "Printer",
                    "_info": {"lastUpdated": "2026-01-01T00:00:00Z", "notes_href": "x"},
                    "board": {"id": 2, "name": "Help Desk", "_info": {"board_href": "x"}},
                }
            ],
            headers={"Link": f'<{BASE}/service/tickets?page=2>; rel="next"'},
        )
    )
    out = await call("cw_search_tickets", conditions="status/name != 'Closed'", pageSize=500)
    req = route.calls.last.request
    expected = base64.b64encode(b"examplecompany+YOUR_PUBLIC_KEY:YOUR_PRIVATE_KEY").decode()
    assert req.headers["authorization"] == f"Basic {expected}"
    assert req.headers["clientid"] == "YOUR_CLIENT_ID"
    assert params(route)["pageSize"] == "200"  # capped
    assert params(route)["page"] == "1"
    assert params(route)["conditions"] == 'status/name != "Closed"'
    assert out["has_more"] is True
    assert out["items"] == [
        {
            "id": 1,
            "summary": "Printer",
            "_info": {"lastUpdated": "2026-01-01T00:00:00Z"},
            "board": {"id": 2, "name": "Help Desk"},
        }
    ]


@respx.mock
async def test_default_page_size_and_has_more_without_link(call):
    route = respx.get(f"{BASE}/company/companies").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    out = await call("cw_search_companies")
    assert params(route)["pageSize"] == "25"
    assert out["has_more"] is False and out["count"] == 1


async def test_missing_credentials_envelope(call):
    from connectwise_manage_mcp import credentials

    token = credentials._current.set(None)
    try:
        out = await call("cw_get_company", id=1)
    finally:
        credentials._current.reset(token)
    assert out["error"]["code"] == "not_configured"


@respx.mock
@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (500, "upstream_error", True),
    ],
)
async def test_error_mapping(call, status, code, retryable):
    respx.get(f"{BASE}/company/companies/9").mock(
        return_value=httpx.Response(
            status, json={"code": "NotFound", "message": "nope", "errors": [{"field": "id", "message": "bad"}]}
        )
    )
    out = await call("cw_get_company", id=9)
    assert out["error"]["code"] == code
    assert out["error"]["retryable"] is retryable
    if status == 400:
        assert "id: bad" in out["error"]["message"]


@respx.mock
async def test_retries_rate_limit_then_succeeds(call):
    route = respx.get(f"{BASE}/system/info").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"version": "v2025.1"}),
        ]
    )
    out = await call("cw_test_connection")
    assert out["status"] == "ok" and out["version"] == "v2025.1" and route.call_count == 2


@respx.mock
async def test_create_is_not_retried_on_5xx(call):
    route = respx.post(f"{BASE}/service/tickets").mock(return_value=httpx.Response(503))
    out = await call("cw_create_ticket", summary="x")
    assert out["error"]["code"] == "upstream_error" and route.call_count == 1


async def test_bad_id_is_rejected_without_calling_api(call):
    out = await call("cw_get_ticket", id=-3)
    assert out["error"]["code"] == "invalid_argument"


@respx.mock
async def test_large_results_are_truncated(call):
    rows = [{"id": i, "notes": "x" * 500} for i in range(100)]
    respx.get(f"{BASE}/service/tickets").mock(return_value=httpx.Response(200, json=rows))
    out = await call("cw_search_tickets", pageSize=100)
    assert out["truncated"] is True and out["has_more"] is True
    assert len(json.dumps(out)) <= 21000


# ---- tickets ----------------------------------------------------------------------


@respx.mock
async def test_create_ticket_uses_references(call):
    route = respx.post(f"{BASE}/service/tickets").mock(return_value=httpx.Response(201, json={"id": 77}))
    await call("cw_create_ticket", summary="VPN down", boardId=1, companyId=2, statusId=3, parentTicketId=50)
    assert sent(route) == {
        "summary": "VPN down",
        "board": {"id": 1},
        "company": {"id": 2},
        "status": {"id": 3},
        "parentTicketId": 50,
    }


@respx.mock
async def test_update_ticket_sends_json_patch(call):
    route = respx.patch(f"{BASE}/service/tickets/5").mock(return_value=httpx.Response(200, json={"id": 5}))
    await call("cw_update_ticket", id=5, operations=[{"op": "replace", "path": "status/id", "value": 9}])
    assert sent(route) == [{"op": "replace", "path": "status/id", "value": 9}]


async def test_patch_add_without_value_is_rejected(call):
    out = await call("cw_update_ticket", id=5, operations=[{"op": "add", "path": "summary"}])
    assert out["error"]["code"] == "invalid_argument"


@respx.mock
async def test_add_ticket_note_does_not_email_by_default(call):
    route = respx.post(f"{BASE}/service/tickets/5/notes").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call("cw_add_ticket_note", id=5, text="Called user")
    assert sent(route) == {
        "text": "Called user",
        "detailDescriptionFlag": True,
        "internalAnalysisFlag": False,
        "resolutionFlag": False,
    }


@respx.mock
async def test_add_ticket_note_email_flag_turns_on_notifications(call):
    route = respx.post(f"{BASE}/service/tickets/5/notes").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call("cw_add_ticket_note", id=5, text="Fixed", resolutionFlag=True, emailContactFlag=True)
    body = sent(route)
    assert body["processNotifications"] is True and body["emailContactFlag"] is True
    assert body["resolutionFlag"] is True and body["detailDescriptionFlag"] is False
    await call("cw_add_ticket_note", id=5, text="Fixed", emailContactFlag=True, processNotifications=False)
    assert sent(route)["processNotifications"] is False


@respx.mock
async def test_ticket_notes_include_child_tickets(call):
    respx.get(f"{BASE}/service/tickets/5/notes").mock(return_value=httpx.Response(200, json=[{"id": 1, "text": "a"}]))
    children = respx.get(f"{BASE}/service/tickets").mock(
        return_value=httpx.Response(200, json=[{"id": 6, "summary": "c"}])
    )
    respx.get(f"{BASE}/service/tickets/6/notes").mock(return_value=httpx.Response(200, json=[{"id": 2, "text": "b"}]))
    out = await call("cw_get_ticket_notes", id=5)
    assert params(children)["conditions"] == "parentTicketId = 5"
    assert out["items"] == [{"id": 1, "text": "a"}]
    assert out["child_tickets"][0]["ticketId"] == 6 and out["child_tickets"][0]["notes"] == [{"id": 2, "text": "b"}]


@respx.mock
async def test_ticket_configurations_continue_after_failure(call):
    add = respx.post(f"{BASE}/service/tickets/5/configurations").mock(
        side_effect=[httpx.Response(201, json={"id": 10}), httpx.Response(400, json={"message": "duplicate"})]
    )
    respx.delete(f"{BASE}/service/tickets/5/configurations/11").mock(return_value=httpx.Response(204))
    out = await call(
        "cw_update_ticket_configurations",
        id=5,
        operations=[
            {"action": "add", "configurationId": 10},
            {"action": "add", "configurationId": 10},
            {"action": "remove", "configurationId": 11},
        ],
    )
    assert add.calls[0].request.content == b'{"id":10}'
    assert [r["success"] for r in out["results"]] == [True, False, True]
    assert out["failed"] == 1


# ---- companies ----------------------------------------------------------------------


@respx.mock
async def test_create_company_sends_default_site(call):
    route = respx.post(f"{BASE}/company/companies").mock(return_value=httpx.Response(201, json={"id": 3}))
    await call("cw_create_company", name="Example Co", identifier="ExampleCo", typeIds=[1], country="United States")
    assert sent(route) == {
        "name": "Example Co",
        "identifier": "ExampleCo",
        "site": {"name": "Main"},
        "types": [{"id": 1}],
        "country": {"name": "United States"},
    }


# ---- contacts ------------------------------------------------------------------------


@respx.mock
async def test_create_contact_types_and_communications(call):
    route = respx.post(f"{BASE}/company/contacts").mock(return_value=httpx.Response(201, json={"id": 8}))
    await call(
        "cw_create_contact",
        firstName="Jane",
        lastName="Doe",
        companyId=3,
        email="jane@example.com",
        siteId=4,
        typeIds=[2],
        communicationItems=[{"communicationType": "Phone", "typeName": "Cell", "value": "555-0100"}],
    )
    body = sent(route)
    assert body["types"] == [{"id": 2}] and "typeIds" not in body
    assert body["company"] == {"id": 3} and body["site"] == {"id": 4}
    assert body["communicationItems"] == [
        {"type": {"name": "Email"}, "value": "jane@example.com", "defaultFlag": True, "communicationType": "Email"},
        {"type": {"name": "Cell"}, "value": "555-0100", "communicationType": "Phone"},
    ]


@respx.mock
async def test_search_contacts_rewrites_name_and_types(call):
    route = respx.get(f"{BASE}/company/contacts").mock(return_value=httpx.Response(200, json=[]))
    await call("cw_search_contacts", conditions="name = 'Jane Doe' and company/id = 3", typeName="Decision Maker")
    p = params(route)
    assert p["conditions"] == '(firstName = "Jane" and lastName = "Doe") and company/id = 3'
    assert p["childConditions"] == 'types/name = "Decision Maker"'


async def test_search_contacts_rejects_types_in_conditions(call):
    out = await call("cw_search_contacts", conditions='types/name = "Primary"')
    assert out["error"]["code"] == "invalid_argument"


@respx.mock
async def test_list_contact_types_uses_description(call):
    route = respx.get(f"{BASE}/company/contacts/types").mock(
        return_value=httpx.Response(200, json=[{"id": 2, "description": "Decision Maker"}])
    )
    out = await call("cw_list_contact_types", conditions='name like "Dec%"')
    assert params(route)["conditions"] == 'description like "Dec%"'
    assert params(route)["orderBy"] == "description asc"
    assert params(route)["pageSize"] == "50"
    assert out["items"][0]["description"] == "Decision Maker"


@respx.mock
async def test_update_contact_communication_patches_type_by_name(call):
    route = respx.patch(f"{BASE}/company/contacts/8/communications/31").mock(return_value=httpx.Response(200, json={}))
    await call("cw_update_contact_communication", id=8, communicationId=31, typeName="Cell", extension="")
    assert sent(route) == [
        {"op": "replace", "path": "type", "value": {"name": "Cell"}},
        {"op": "replace", "path": "extension", "value": ""},
    ]


async def test_update_contact_communication_needs_a_field(call):
    out = await call("cw_update_contact_communication", id=8, communicationId=31)
    assert out["error"]["code"] == "invalid_argument"


@respx.mock
async def test_add_contact_communication(call):
    route = respx.post(f"{BASE}/company/contacts/8/communications").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    await call(
        "cw_add_contact_communication", id=8, communicationType="Phone", typeName="Direct", value="555", extension="12"
    )
    assert sent(route) == {"type": {"name": "Direct"}, "value": "555", "extension": "12", "communicationType": "Phone"}


async def test_update_contact_rejects_types_path(call):
    out = await call("cw_update_contact", id=8, operations=[{"op": "add", "path": "types", "value": [{"id": 2}]}])
    assert out["error"]["code"] == "invalid_argument"
    assert "cw_update_contact_types" in out["error"]["message"]


@respx.mock
async def test_update_contact_inactive_flag(call):
    route = respx.patch(f"{BASE}/company/contacts/8").mock(return_value=httpx.Response(200, json={"id": 8}))
    await call("cw_update_contact", id=8, operations=[{"op": "replace", "path": "inactiveFlag", "value": True}])
    assert sent(route) == [{"op": "replace", "path": "inactiveFlag", "value": True}]


@respx.mock
async def test_update_contact_types_add_by_name(call):
    types = respx.get(f"{BASE}/company/contacts/types").mock(
        return_value=httpx.Response(200, json=[{"id": 2, "description": "Decision Maker"}])
    )
    respx.get(f"{BASE}/company/contacts/8/typeAssociations").mock(return_value=httpx.Response(200, json=[]))
    post = respx.post(f"{BASE}/company/contacts/8/typeAssociations").mock(
        return_value=httpx.Response(201, json={"id": 40, "type": {"id": 2, "name": "Decision Maker"}})
    )
    out = await call("cw_update_contact_types", id=8, action="add", typeName="decision maker")
    assert params(types)["conditions"] == 'description = "decision maker"'
    assert sent(post) == {"contact": {"id": 8}, "type": {"id": 2}}
    assert out["added"] is True


@respx.mock
async def test_update_contact_types_add_existing_is_noop(call):
    respx.get(f"{BASE}/company/contacts/8/typeAssociations").mock(
        return_value=httpx.Response(200, json=[{"id": 40, "type": {"id": 2, "name": "Decision Maker"}}])
    )
    post = respx.post(f"{BASE}/company/contacts/8/typeAssociations")
    out = await call("cw_update_contact_types", id=8, action="add", typeId=2)
    assert out["alreadyPresent"] is True and not post.called


@respx.mock
async def test_update_contact_types_remove_by_name(call):
    respx.get(f"{BASE}/company/contacts/8/typeAssociations").mock(
        return_value=httpx.Response(200, json=[{"id": 40, "type": {"id": 2, "name": "Decision Maker"}}])
    )
    delete = respx.delete(f"{BASE}/company/contacts/8/typeAssociations/40").mock(return_value=httpx.Response(204))
    out = await call("cw_update_contact_types", id=8, action="remove", typeName="Decision Maker")
    assert delete.called and out["removed"] is True


@respx.mock
async def test_update_contact_types_remove_missing_is_not_found(call):
    respx.get(f"{BASE}/company/contacts/8/typeAssociations").mock(return_value=httpx.Response(200, json=[]))
    out = await call("cw_update_contact_types", id=8, action="remove", typeId=2)
    assert out["error"]["code"] == "not_found"


# ---- time, schedule, projects ------------------------------------------------------------


@respx.mock
async def test_create_time_entry(call):
    route = respx.post(f"{BASE}/time/entries").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call(
        "cw_create_time_entry",
        chargeToType="ServiceTicket",
        chargeToId=5,
        memberId=7,
        timeStart="2026-01-01T01:00:00Z",
        actualHours=0.5,
        workTypeId=3,
    )
    assert sent(route) == {
        "chargeToType": "ServiceTicket",
        "chargeToId": 5,
        "member": {"id": 7},
        "timeStart": "2026-01-01T01:00:00Z",
        "actualHours": 0.5,
        "workType": {"id": 3},
    }


@respx.mock
async def test_delete_time_entry(call):
    respx.delete(f"{BASE}/time/entries/4").mock(return_value=httpx.Response(204))
    assert await call("cw_delete_time_entry", id=4) == {"deleted": True, "id": 4}


@respx.mock
async def test_create_schedule_entry(call):
    route = respx.post(f"{BASE}/schedule/entries").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call(
        "cw_create_schedule_entry",
        objectId=5,
        typeId=4,
        memberId=7,
        dateStart="2026-01-01T02:00:00Z",
        dateEnd="2026-01-01T03:00:00Z",
        statusId=2,
    )
    assert sent(route) == {
        "objectId": 5,
        "type": {"id": 4},
        "member": {"id": 7},
        "dateStart": "2026-01-01T02:00:00Z",
        "dateEnd": "2026-01-01T03:00:00Z",
        "status": {"id": 2},
    }


@respx.mock
async def test_search_project_tickets_by_project(call):
    route = respx.get(f"{BASE}/project/tickets").mock(return_value=httpx.Response(200, json=[]))
    await call("cw_search_project_tickets", projectId=12, conditions="closedFlag = false")
    assert params(route)["conditions"] == "(project/id = 12) and (closedFlag = false)"


# ---- catalog, inventory ---------------------------------------------------------------------


@respx.mock
async def test_create_catalog_item_merges_extra_fields(call):
    route = respx.post(f"{BASE}/procurement/catalog").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call(
        "cw_create_catalog_item",
        identifier="SKU-1",
        description="Widget",
        subcategoryId=2,
        typeId=3,
        price=10.0,
        extraFields={"manufacturerPartNumber": "MPN", "identifier": "ignored"},
    )
    assert sent(route) == {
        "manufacturerPartNumber": "MPN",
        "identifier": "SKU-1",
        "description": "Widget",
        "subcategory": {"id": 2},
        "type": {"id": 3},
        "price": 10.0,
    }


@respx.mock
async def test_inventory_on_hand_walks_bins_and_adds_costs(call):
    bins = respx.get(f"{BASE}/procurement/warehouseBins").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "A1"}, {"id": 2, "name": "A2"}])
    )
    respx.get(f"{BASE}/procurement/warehouseBins/1/inventoryOnHand").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"catalogItem": {"id": 9, "identifier": "SKU"}, "onHand": -2},
                {"catalogItem": {"id": 10}, "onHand": 0},
            ],
        )
    )
    respx.get(f"{BASE}/procurement/warehouseBins/2/inventoryOnHand").mock(return_value=httpx.Response(200, json=[]))
    catalog = respx.get(f"{BASE}/procurement/catalog").mock(
        return_value=httpx.Response(200, json=[{"id": 9, "identifier": "SKU", "description": "Widget", "cost": 2.5}])
    )
    out = await call("cw_get_inventory_on_hand", warehouseId=3)
    assert params(bins)["conditions"] == "(warehouse/id = 3) and (inactiveFlag = false)"
    assert params(catalog)["conditions"] == "id in (9)"
    assert out["bins_scanned"] == 2 and out["count"] == 1
    row = out["items"][0]
    assert row["onHand"] == -2 and row["unitCost"] == 2.5 and row["extendedValue"] == -5.0


@respx.mock
async def test_adjustment_detail_joins_serials(call):
    route = respx.post(f"{BASE}/procurement/adjustments/5/details").mock(
        return_value=httpx.Response(201, json={"id": 1})
    )
    await call(
        "cw_add_adjustment_detail",
        adjustmentId=5,
        catalogItemId=9,
        warehouseId=3,
        warehouseBinId=1,
        quantityAdjusted=-2,
        serialNumbers=["S1", "S2"],
    )
    assert sent(route) == {
        "catalogItem": {"id": 9},
        "warehouse": {"id": 3},
        "warehouseBin": {"id": 1},
        "quantityAdjusted": -2,
        "serialNumber": "S1,S2",
    }


@respx.mock
async def test_close_adjustment(call):
    route = respx.patch(f"{BASE}/procurement/adjustments/5").mock(
        return_value=httpx.Response(200, json={"closedFlag": True})
    )
    await call("cw_close_adjustment", id=5)
    assert sent(route) == [{"op": "replace", "path": "closedFlag", "value": True}]


# ---- finance, sales -----------------------------------------------------------------------


async def test_update_invoice_rejects_other_paths(call):
    out = await call("cw_update_invoice", id=3, operations=[{"op": "replace", "path": "total", "value": 1}])
    assert out["error"]["code"] == "invalid_argument"


@respx.mock
async def test_update_invoice_alias_and_dry_run(call):
    respx.get(f"{BASE}/finance/invoices/3").mock(
        return_value=httpx.Response(200, json={"id": 3, "status": {"id": 1, "name": "New"}, "billingSite": {"id": 4}})
    )
    patch = respx.patch(f"{BASE}/finance/invoices/3")
    out = await call(
        "cw_update_invoice",
        id=3,
        operations=[
            {"op": "replace", "path": "/status/id", "value": 11},
            {"op": "replace", "path": "billToSite/id", "value": 5},
        ],
        dryRun=True,
    )
    assert not patch.called
    assert out["saved"] is False
    assert out["preview"]["status"]["id"] == 11 and out["preview"]["billingSite"]["id"] == 5


@respx.mock
async def test_update_invoice_sends_patch(call):
    route = respx.patch(f"{BASE}/finance/invoices/3").mock(return_value=httpx.Response(200, json={"id": 3}))
    await call("cw_update_invoice", id=3, operations=[{"op": "replace", "path": "billToSite", "value": {"id": 5}}])
    assert sent(route) == [{"op": "replace", "path": "billingSite", "value": {"id": 5}}]


@respx.mock
async def test_agreement_recap_falls_back_to_id_condition(call):
    route = respx.get(f"{BASE}/finance/agreementrecap").mock(
        side_effect=[httpx.Response(400, json={"message": "InvalidCondition"}), httpx.Response(200, json=[{"id": 7}])]
    )
    out = await call("cw_get_agreement_recap", id=7)
    assert route.calls[0].request.url.params["conditions"] == "agreementId = 7"
    assert route.calls[1].request.url.params["conditions"] == "id = 7"
    assert out == {"id": 7}


@respx.mock
async def test_create_agreement_addition(call):
    route = respx.post(f"{BASE}/finance/agreements/2/additions").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call("cw_create_agreement_addition", agreementId=2, productId=9, billCustomer="Billable", quantity=3)
    assert sent(route) == {"product": {"id": 9}, "billCustomer": "Billable", "quantity": 3}


@respx.mock
async def test_list_agreement_types_returns_items(call):
    respx.get(f"{BASE}/finance/agreements/types").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Gold"}, {"id": 2, "name": "Silver"}])
    )
    out = await call("cw_list_agreement_types")
    assert out["items"] == [{"id": 1, "name": "Gold"}, {"id": 2, "name": "Silver"}]
    assert out["page"] == 1 and out["page_size"] == 25


@respx.mock
async def test_list_agreement_types_passes_conditions(call):
    route = respx.get(f"{BASE}/finance/agreements/types").mock(return_value=httpx.Response(200, json=[]))
    await call("cw_list_agreement_types", conditions="inactiveFlag = false")
    assert params(route)["conditions"] == "inactiveFlag = false"


@respx.mock
async def test_list_agreement_types_passes_fields_and_orderby(call):
    route = respx.get(f"{BASE}/finance/agreements/types").mock(return_value=httpx.Response(200, json=[]))
    await call("cw_list_agreement_types", fields="id, name", orderBy="name asc")
    assert params(route)["fields"] == "id, name"
    assert params(route)["orderBy"] == "name asc"


@respx.mock
async def test_list_agreement_types_pagination(call):
    route = respx.get(f"{BASE}/finance/agreements/types").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "name": "Gold"}, {"id": 2, "name": "Silver"}])
    )
    out = await call("cw_list_agreement_types", pageSize=2)
    assert params(route)["page"] == "1" and params(route)["pageSize"] == "2"
    assert out["has_more"] is True
    out_default = await call("cw_list_agreement_types")
    assert out_default["page"] == 1 and out_default["page_size"] == 25


@respx.mock
async def test_opportunity_forecast_items(call):
    respx.get(f"{BASE}/sales/opportunities/4/forecast").mock(
        return_value=httpx.Response(200, json={"id": 4, "forecastItems": [{"id": 1}, {"id": 2}]})
    )
    out = await call("cw_search_opportunity_forecasts", opportunityId=4, pageSize=1)
    assert out["items"] == [{"id": 1}] and out["has_more"] is True and out["total_count"] == 2


@respx.mock
async def test_sales_order_products_scoped(call):
    route = respx.get(f"{BASE}/procurement/products").mock(return_value=httpx.Response(200, json=[]))
    await call("cw_get_sales_order_products", salesOrderId=6)
    assert params(route)["conditions"] == "salesOrder/id = 6"


# ---- ticket classification and time entry billing (PRD-20969) ---------------


@respx.mock
async def test_list_ticket_types_by_board(call):
    route = respx.get(f"{BASE}/service/boards/7/types").mock(
        return_value=httpx.Response(200, json=[{"id": 3, "name": "Offboarding"}])
    )
    data = await call("cw_list_ticket_types", **{"boardId": 7})
    assert data["items"] == [{"id": 3, "name": "Offboarding"}]
    assert params(route)["page"] == "1"


@respx.mock
async def test_list_ticket_subtypes_without_type_reads_board_subtypes(call):
    respx.get(f"{BASE}/service/boards/7/subtypes").mock(
        return_value=httpx.Response(200, json=[{"id": 4, "name": "User"}])
    )
    data = await call("cw_list_ticket_subtypes", **{"boardId": 7})
    assert data["items"] == [{"id": 4, "name": "User"}]


@respx.mock
async def test_list_ticket_subtypes_for_type_uses_associations(call):
    route = respx.get(f"{BASE}/service/boards/7/typeSubTypeItemAssociations").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"id": 1, "type": {"id": 3}, "subType": {"id": 5, "name": "Mailbox"}, "item": {"id": 9, "name": "A"}},
                {"id": 2, "type": {"id": 3}, "subType": {"id": 4, "name": "Account"}, "item": {"id": 8, "name": "B"}},
                {"id": 3, "type": {"id": 3}, "subType": {"id": 5, "name": "Mailbox"}, "item": {"id": 8, "name": "B"}},
            ],
        )
    )
    data = await call("cw_list_ticket_subtypes", **{"boardId": 7, "typeId": 3})
    assert params(route)["conditions"] == "type/id = 3"
    assert data["items"] == [{"id": 4, "name": "Account"}, {"id": 5, "name": "Mailbox"}]


@respx.mock
async def test_list_ticket_items_for_type_and_subtype(call):
    route = respx.get(f"{BASE}/service/boards/7/typeSubTypeItemAssociations").mock(
        return_value=httpx.Response(200, json=[{"id": 1, "item": {"id": 9, "name": "Disable"}}])
    )
    data = await call("cw_list_ticket_items", **{"boardId": 7, "typeId": 3, "subTypeId": 5})
    assert params(route)["conditions"] == "(type/id = 3) and (subType/id = 5)"
    assert data["items"] == [{"id": 9, "name": "Disable"}]


@respx.mock
async def test_list_work_types_and_roles(call):
    respx.get(f"{BASE}/time/workTypes").mock(return_value=httpx.Response(200, json=[{"id": 1, "name": "Regular"}]))
    respx.get(f"{BASE}/time/workRoles").mock(return_value=httpx.Response(200, json=[{"id": 2, "name": "Engineer"}]))
    assert (await call("cw_list_work_types"))["items"] == [{"id": 1, "name": "Regular"}]
    assert (await call("cw_list_work_roles"))["items"] == [{"id": 2, "name": "Engineer"}]


@respx.mock
async def test_create_time_entry_sends_billing_and_destination_flags(call):
    route = respx.post(f"{BASE}/time/entries").mock(return_value=httpx.Response(201, json={"id": 11}))
    await call(
        "cw_create_time_entry",
        **{
            "chargeToType": "ServiceTicket",
            "chargeToId": 100,
            "memberId": 5,
            "timeStart": "2026-10-25T01:00:00Z",
            "actualHours": 0.5,
            "notes": "Offboarded user",
            "billableOption": "Billable",
            "addToDetailDescriptionFlag": True,
            "addToInternalAnalysisFlag": True,
            "addToResolutionFlag": True,
        },
    )
    payload = sent(route)
    assert payload["billableOption"] == "Billable"
    assert payload["addToDetailDescriptionFlag"] is True
    assert payload["addToInternalAnalysisFlag"] is True
    assert payload["addToResolutionFlag"] is True


@respx.mock
async def test_create_ticket_sets_item(call):
    route = respx.post(f"{BASE}/service/tickets").mock(return_value=httpx.Response(201, json={"id": 1}))
    await call("cw_create_ticket", **{"summary": "Offboard", "boardId": 7, "typeId": 3, "subTypeId": 5, "itemId": 9})
    payload = sent(route)
    assert payload["type"] == {"id": 3} and payload["subType"] == {"id": 5} and payload["item"] == {"id": 9}
