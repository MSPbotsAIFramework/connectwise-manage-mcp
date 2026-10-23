# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Contacts, their communication items (phone / email / fax) and contact types.

ConnectWise behaviour this module works around:
- Contact types (``/company/contacts/types``) keep their label in ``description``; ``name`` in
  conditions or orderBy is rejected with 400.
- Types can be set only when a contact is created (``types: [{"id": n}]``); afterwards they are
  managed through ``/company/contacts/{id}/typeAssociations``.
- Unknown body fields are silently dropped, so field names here follow the API model exactly.
"""

import re
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..api import ApiError, CWClient
from ..config import Settings
from ._common import (
    CREATE,
    DESTRUCTIVE,
    READ,
    UPDATE,
    Operations,
    Page,
    PageSize,
    ToolInputError,
    add_get,
    body,
    clean,
    join_conditions,
    list_result,
    page_size_param,
    paging,
    patch_ops,
    quote,
    ref,
    run,
    seg,
)

CommunicationType = Literal["Phone", "Email", "Fax"]

_BARE_NAME_RE = re.compile(r'(?<![\w/.])name\s*(=|like)\s*"([^"]*)"', re.IGNORECASE)
_TYPE_LABEL_RE = re.compile(r"(?<![\w/.])name\b(?=\s*(?:=|!=|<>|<|>|like\b|not\b|in\b|contains\b))", re.IGNORECASE)


class CommunicationItem(BaseModel):
    communicationType: CommunicationType = Field(description="Item kind")
    typeName: str = Field(description='Communication type name as configured in Manage, e.g. "Direct", "Cell", "Email"')
    value: str = Field(description="Phone number, email address or fax number")
    extension: str | None = Field(default=None, description="Phone extension")
    defaultFlag: bool | None = Field(default=None, description="Make this the default item of its kind")


def communication(
    communication_type: str, type_name: str, value: str, extension: str | None = None, default: bool | None = None
) -> dict[str, Any]:
    if not type_name.strip() or not value.strip():
        raise ToolInputError("typeName and value must not be empty.")
    return body(
        type={"name": type_name.strip()},
        value=value.strip(),
        extension=extension,
        defaultFlag=default,
        communicationType=communication_type,
    )


def rewrite_contact_name(text: str | None) -> str | None:
    """Contacts have no ``name`` field: ``name = "Jane Doe"`` -> firstName / lastName conditions."""
    if not text:
        return text

    def repl(match: re.Match) -> str:
        operator, value = match.group(1).lower(), match.group(2).strip()
        if operator == "=" and " " in value:
            first, last = value.split(" ", 1)
            return f"(firstName = {quote(first)} and lastName = {quote(last.strip())})"
        return f"(firstName {operator} {quote(value)} or lastName {operator} {quote(value)})"

    return _BARE_NAME_RE.sub(repl, text)


def rewrite_type_label(text: str | None) -> str | None:
    """Contact types keep their label in ``description``; accept ``name`` and rewrite it."""
    if not text:
        return text
    return _TYPE_LABEL_RE.sub("description", text)


async def resolve_contact_type(client: CWClient, type_name: str) -> dict[str, Any]:
    label = type_name.strip()
    if not label:
        raise ToolInputError("typeName must not be empty.")
    rows, _ = await client.get_page(
        "/company/contacts/types", {"conditions": f"description = {quote(label)}", "pageSize": 25}
    )
    for row in rows:
        if str(row.get("description", "")).strip().lower() == label.lower():
            return row
    raise ToolInputError(f"No contact type named {label!r}. Use cw_list_contact_types to see the available types.")


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="cw_search_contacts",
        description=(
            'Search contacts. Parent fields go in conditions with double quotes (firstName = "John", company/id = 5); '
            'there is no name field (a bare name = "..." is rewritten to firstName / lastName). Contact type is a '
            'child collection: filter it with typeName, typeId or childConditions (types/name = "Primary"), '
            "not in conditions."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_search_contacts(
        conditions: Annotated[
            str | None,
            Field(description="Parent-field conditions. Strings use double quotes. Do not use types/name here."),
        ] = None,
        childConditions: Annotated[
            str | None, Field(description='Child-collection conditions, e.g. types/name = "Primary" or types/id = 2')
        ] = None,
        typeName: Annotated[
            str | None, Field(description='Contact type name, sent as childConditions types/name="..."')
        ] = None,
        typeId: Annotated[
            int | None, Field(description="Contact type ID, sent as childConditions types/id=<id>")
        ] = None,
        page: Page = None,
        pageSize: PageSize = None,
        orderBy: Annotated[str | None, Field(description="Field to order by (e.g. 'lastName asc')")] = None,
        fields: Annotated[str | None, Field(description="Optional comma-separated list of fields to return")] = None,
    ) -> str:
        number, size = paging(page, pageSize)

        async def handler(client: CWClient):
            parent = join_conditions(rewrite_contact_name(join_conditions(conditions)))
            if parent and re.search(r"(?<![\w.])types/", parent):
                raise ToolInputError(
                    "Contact types cannot be filtered in conditions. Use typeName, typeId or childConditions."
                )
            child = join_conditions(
                childConditions,
                f"types/name = {quote(typeName.strip())}" if typeName and typeName.strip() else None,
                f"types/id = {seg(typeId)}" if typeId is not None else None,
            )
            params = {
                "conditions": parent,
                "childConditions": child,
                "orderBy": orderBy,
                "fields": fields,
                "page": number,
                "pageSize": size,
            }
            rows, has_next = await client.get_page("/company/contacts", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    add_get(
        mcp,
        settings,
        name="cw_get_contact",
        description="Get a specific contact by ID, including communicationItems (with their IDs) and types.",
        path="/company/contacts/{id}",
        id_help="Contact ID",
    )

    @mcp.tool(
        name="cw_create_contact",
        description=(
            "Create a contact. Besides name and company you can set site, address, department, manager, contact "
            "types (typeIds from cw_list_contact_types; only possible at creation) and phone/email items via "
            "communicationItems. email / phone are shortcuts for one Email and one Direct item."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_create_contact(
        firstName: Annotated[str, Field(description="First name")],
        lastName: Annotated[str, Field(description="Last name")],
        companyId: Annotated[int, Field(description="Company ID to associate the contact with")],
        email: Annotated[str | None, Field(description="Email address")] = None,
        phone: Annotated[str | None, Field(description="Phone number")] = None,
        title: Annotated[str | None, Field(description="Job title")] = None,
        siteId: Annotated[int | None, Field(description="Company site ID (from cw_list_sites)")] = None,
        addressLine1: Annotated[str | None, Field(description="Address line 1")] = None,
        addressLine2: Annotated[str | None, Field(description="Address line 2")] = None,
        city: Annotated[str | None, Field(description="City")] = None,
        state: Annotated[str | None, Field(description="State / province")] = None,
        zip: Annotated[str | None, Field(description="Postal / ZIP code")] = None,
        departmentId: Annotated[int | None, Field(description="Contact department ID")] = None,
        managerContactId: Annotated[int | None, Field(description="Contact ID of this contact's manager")] = None,
        typeIds: Annotated[
            list[int] | None,
            Field(description="Contact type IDs (from cw_list_contact_types). Later changes: cw_update_contact_types."),
        ] = None,
        communicationItems: Annotated[
            list[CommunicationItem] | None,
            Field(description="Extra phone/email/fax items, appended after the email/phone shortcuts"),
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            items: list[dict[str, Any]] = []
            if email and email.strip():
                items.append(communication("Email", "Email", email, default=True))
            if phone and phone.strip():
                items.append(communication("Phone", "Direct", phone, default=True))
            for item in communicationItems or []:
                items.append(
                    communication(item.communicationType, item.typeName, item.value, item.extension, item.defaultFlag)
                )
            payload = body(
                firstName=firstName,
                lastName=lastName,
                company=ref(companyId),
                site=ref(siteId),
                title=title,
                addressLine1=addressLine1,
                addressLine2=addressLine2,
                city=city,
                state=state,
                zip=zip,
                department=ref(departmentId),
                managerContactId=int(seg(managerContactId)) if managerContactId is not None else None,
                types=[ref(t) for t in typeIds] if typeIds else None,
                communicationItems=items or None,
            )
            return clean(await client.post("/company/contacts", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_contact",
        description=(
            "Update a contact with JSON Patch (op, path, value). Common paths: firstName, lastName, title, "
            "inactiveFlag (true deactivates; there is no delete), site ({id}), communicationItems (replacing the "
            "array replaces every item), customFields ([{id, value}]). Contact types cannot be patched: use "
            "cw_update_contact_types; for one phone/email use cw_add_/cw_update_contact_communication."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_contact(
        id: Annotated[int, Field(description="Contact ID")],
        operations: Operations,
    ) -> str:
        async def handler(client: CWClient):
            ops, replace_only = patch_ops(operations)
            for op in ops:
                if op["path"].strip("/").split("/")[0] in ("types", "typeIds", "typeAssociations"):
                    raise ToolInputError("Contact types cannot be patched. Use cw_update_contact_types.")
            return clean(await client.patch(f"/company/contacts/{seg(id)}", ops, idempotent=replace_only))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_add_contact_communication",
        description=(
            "Add one phone, email or fax item to an existing contact without touching its other items. "
            "To change an existing item use cw_update_contact_communication."
        ),
        annotations=CREATE,
        structured_output=False,
    )
    async def cw_add_contact_communication(
        id: Annotated[int, Field(description="Contact ID")],
        communicationType: Annotated[CommunicationType, Field(description="Item kind")],
        typeName: Annotated[str, Field(description='Communication type name, e.g. "Direct", "Cell", "Email"')],
        value: Annotated[str, Field(description="Phone number, email address or fax number")],
        extension: Annotated[str | None, Field(description="Phone extension")] = None,
        defaultFlag: Annotated[bool | None, Field(description="Make this the default item of its kind")] = None,
    ) -> str:
        async def handler(client: CWClient):
            payload = communication(communicationType, typeName, value, extension, defaultFlag)
            return clean(await client.post(f"/company/contacts/{seg(id)}/communications", payload))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_contact_communication",
        description=(
            "Update one existing phone, email or fax item of a contact without touching its other items. "
            "communicationId is communicationItems[].id from cw_get_contact. Only the fields you pass change."
        ),
        annotations=UPDATE,
        structured_output=False,
    )
    async def cw_update_contact_communication(
        id: Annotated[int, Field(description="Contact ID")],
        communicationId: Annotated[int, Field(description="Communication item ID (communicationItems[].id)")],
        communicationType: Annotated[CommunicationType | None, Field(description="Item kind")] = None,
        typeName: Annotated[str | None, Field(description='Communication type name, e.g. "Direct", "Cell"')] = None,
        value: Annotated[str | None, Field(description="Phone number, email address or fax number")] = None,
        extension: Annotated[str | None, Field(description="Phone extension; pass an empty string to clear it")] = None,
        defaultFlag: Annotated[bool | None, Field(description="Make this the default item of its kind")] = None,
    ) -> str:
        async def handler(client: CWClient):
            ops: list[dict[str, Any]] = []
            if communicationType is not None:
                ops.append({"op": "replace", "path": "communicationType", "value": communicationType})
            if typeName is not None:
                if not typeName.strip():
                    raise ToolInputError("typeName must not be empty.")
                ops.append({"op": "replace", "path": "type", "value": {"name": typeName.strip()}})
            if value is not None:
                if not value.strip():
                    raise ToolInputError("value must not be empty.")
                ops.append({"op": "replace", "path": "value", "value": value.strip()})
            if extension is not None:
                ops.append({"op": "replace", "path": "extension", "value": extension})
            if defaultFlag is not None:
                ops.append({"op": "replace", "path": "defaultFlag", "value": defaultFlag})
            if not ops:
                raise ToolInputError("Pass at least one field to change.")
            path = f"/company/contacts/{seg(id)}/communications/{seg(communicationId)}"
            return clean(await client.patch(path, ops, idempotent=True))

        return await run(settings, handler)

    @mcp.tool(
        name="cw_list_contact_types",
        description=(
            "List contact types (e.g. Primary, Decision Maker) with their IDs, for cw_create_contact typeIds or "
            "cw_update_contact_types. The label is in description."
        ),
        annotations=READ,
        structured_output=False,
    )
    async def cw_list_contact_types(
        conditions: Annotated[
            str | None,
            Field(description='Optional filter on the label, e.g. description like "Dec%" (name is rewritten)'),
        ] = None,
        pageSize: page_size_param(50) = None,
        page: Page = None,
    ) -> str:
        number, size = paging(page, pageSize, default=50)

        async def handler(client: CWClient):
            params = {
                "conditions": rewrite_type_label(join_conditions(conditions)),
                "orderBy": "description asc",
                "page": number,
                "pageSize": size,
            }
            rows, has_next = await client.get_page("/company/contacts/types", params)
            return list_result(rows, number, size, has_next)

        return await run(settings, handler)

    @mcp.tool(
        name="cw_update_contact_types",
        description=(
            "Add or remove a contact type on a contact (e.g. tag as Decision Maker). action add takes typeName or "
            "typeId; adding a type the contact already has returns the existing association. action remove takes "
            "associationId, or typeName / typeId to find the association."
        ),
        annotations=DESTRUCTIVE,
        structured_output=False,
    )
    async def cw_update_contact_types(
        id: Annotated[int, Field(description="Contact ID")],
        action: Annotated[Literal["add", "remove"], Field(description="add tags the contact; remove untags it")],
        typeName: Annotated[str | None, Field(description='Contact type name, e.g. "Decision Maker"')] = None,
        typeId: Annotated[
            int | None, Field(description="Contact type ID; wins over typeName when both are set")
        ] = None,
        associationId: Annotated[
            int | None, Field(description="Type-association ID to remove (action remove only)")
        ] = None,
    ) -> str:
        async def handler(client: CWClient):
            contact = seg(id)
            base = f"/company/contacts/{contact}/typeAssociations"
            if action == "remove" and associationId is not None:
                await client.delete(f"{base}/{seg(associationId)}")
                return {"removed": True, "associationId": int(seg(associationId))}
            if typeId is None and not (typeName and typeName.strip()):
                raise ToolInputError("Pass typeName or typeId" + (" or associationId." if action == "remove" else "."))

            type_id = int(seg(typeId)) if typeId is not None else None
            label = None
            if type_id is None and action == "add":
                found = await resolve_contact_type(client, typeName or "")
                type_id, label = int(found["id"]), found.get("description")

            existing = await client.get_all(base, page_size=200, max_rows=1000)
            match = None
            for assoc in existing:
                t = assoc.get("type") or {}
                if type_id is not None and t.get("id") == type_id:
                    match = assoc
                elif type_id is None and str(t.get("name", "")).strip().lower() == (typeName or "").strip().lower():
                    match = assoc
                if match:
                    break

            if action == "add":
                if match:
                    return {"added": False, "alreadyPresent": True, "association": clean(match)}
                created = await client.post(base, {"contact": {"id": int(contact)}, "type": {"id": type_id}})
                result: dict[str, Any] = {"added": True, "association": clean(created)}
                if label:
                    result["typeName"] = label
                return result

            if not match:
                raise ApiError("not_found", "The contact does not have that contact type.")
            await client.delete(f"{base}/{seg(match.get('id'))}")
            return {"removed": True, "associationId": match.get("id"), "type": clean(match.get("type"))}

        return await run(settings, handler)
