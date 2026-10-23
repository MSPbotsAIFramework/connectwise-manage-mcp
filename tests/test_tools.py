# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""tools/list contract: names and parameters must stay compatible with the registered connector.

``fixtures/tools_baseline.json`` is the tools/list of the previous connector (names and input schemas;
descriptions removed) and never changes.
``fixtures/tools_snapshot.json`` is this server's own parameter list; regenerate it with
``UPDATE_SNAPSHOT=1 uv run pytest tests/test_tools.py`` after an intended change.
"""

import json
import os
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
BASELINE = {t["name"]: t for t in json.loads((FIXTURES / "tools_baseline.json").read_text())}
SNAPSHOT = FIXTURES / "tools_snapshot.json"


async def _tools(mcp):
    return {t.name: t for t in await mcp.list_tools()}


def _types(prop: dict) -> set[str]:
    out = set()
    if "type" in prop:
        out |= set(prop["type"]) if isinstance(prop["type"], list) else {prop["type"]}
    for alt in prop.get("anyOf", []) + prop.get("oneOf", []):
        out |= _types(alt)
    if "$ref" in prop or "enum" in prop and not out:
        out.add("string" if "enum" in prop else "object")
    return out - {"null"}


def _enum(prop: dict) -> set | None:
    if "enum" in prop:
        return set(prop["enum"])
    for alt in prop.get("anyOf", []):
        if "enum" in alt:
            return set(alt["enum"])
    return None


def _resolve(schema: dict, prop: dict) -> dict:
    ref = prop.get("$ref") or next((a["$ref"] for a in prop.get("anyOf", []) if "$ref" in a), None)
    if ref:
        return schema["$defs"][ref.rsplit("/", 1)[-1]]
    return prop


async def test_tool_names_match_baseline(mcp):
    assert set(await _tools(mcp)) == set(BASELINE)
    assert len(BASELINE) == 87


async def test_parameters_are_backward_compatible(mcp):
    tools = await _tools(mcp)
    for name, expected in BASELINE.items():
        old = expected["inputSchema"]
        new = tools[name].inputSchema
        props = new.get("properties", {})
        required = set(new.get("required", []))
        assert set(old.get("properties", {})) <= set(props), f"{name} lost parameters"
        assert required <= set(old.get("required", [])), f"{name} gained required parameters"
        for param, old_prop in old.get("properties", {}).items():
            new_prop = _resolve(new, props[param])
            old_types, new_types = _types(old_prop), _types(new_prop) or _types(props[param])
            for t in old_types:
                ok = (
                    t in new_types
                    or (t == "number" and "integer" in new_types)
                    or (t == "integer" and "number" in new_types)
                )
                assert ok, f"{name}.{param}: baseline type {t} not accepted (now {new_types})"
            old_enum, new_enum = _enum(old_prop), _enum(new_prop)
            if old_enum:
                assert new_enum is not None and old_enum <= new_enum, f"{name}.{param} lost enum values"


async def test_nested_item_fields_are_kept(mcp):
    tools = await _tools(mcp)
    for name, expected in BASELINE.items():
        for param, old_prop in expected["inputSchema"].get("properties", {}).items():
            items = old_prop.get("items") or {}
            old_fields = set(items.get("properties", {}))
            for alt in items.get("oneOf", []):
                old_fields |= set(alt.get("properties", {}))
            if not old_fields:
                continue
            new = tools[name].inputSchema
            new_prop = _resolve(new, new["properties"][param])
            new_items = new_prop.get("items") or next(
                (a.get("items") for a in new_prop.get("anyOf", []) if a.get("items")), {}
            )
            new_items = _resolve(new, new_items)
            assert old_fields <= set(new_items.get("properties", {})), f"{name}.{param} items lost fields"


async def test_snapshot(mcp):
    tools = await _tools(mcp)
    current = {
        name: {
            "params": sorted(t.inputSchema.get("properties", {})),
            "required": sorted(t.inputSchema.get("required", [])),
        }
        for name, t in sorted(tools.items())
    }
    if os.environ.get("UPDATE_SNAPSHOT") or not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n")
    assert current == json.loads(SNAPSHOT.read_text())


async def test_descriptions_are_concise(mcp):
    for tool in (await _tools(mcp)).values():
        assert tool.description and len(tool.description) <= 600, tool.name
        assert tool.description.isascii(), tool.name


async def test_annotations(mcp):
    tools = await _tools(mcp)
    for name in ("cw_delete_time_entry", "cw_close_adjustment", "cw_update_invoice", "cw_update_schedule_entry"):
        assert tools[name].annotations.destructiveHint is True, name
    for name, tool in tools.items():
        if name.startswith(("cw_search_", "cw_get_", "cw_list_")) or name == "cw_test_connection":
            assert tool.annotations.readOnlyHint is True, name
        else:
            assert tool.annotations.readOnlyHint is False, name


async def test_page_size_is_capped_in_schema(mcp):
    for tool in (await _tools(mcp)).values():
        prop = tool.inputSchema.get("properties", {}).get("pageSize")
        if prop:
            assert "max: 200" in prop["description"], tool.name


async def test_no_agent_id_parameter(mcp):
    # The platform injects its own value into parameters named agent_id.
    for tool in (await _tools(mcp)).values():
        assert "agent_id" not in tool.inputSchema.get("properties", {}), tool.name
