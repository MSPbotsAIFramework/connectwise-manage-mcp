# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import pytest
from starlette.testclient import TestClient

from connectwise_manage_mcp import api, credentials
from connectwise_manage_mcp.config import REQUIRED_HEADERS, Settings
from connectwise_manage_mcp.server import create_app

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
INIT = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PLACEHOLDERS = {name: "probe-placeholder" for name in REQUIRED_HEADERS}


@pytest.fixture
def client():
    with TestClient(create_app(Settings())) as c:
        yield c


def test_health_needs_no_credentials(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_missing_headers_is_401(client):
    r = client.post("/mcp", json=LIST, headers=HEADERS)
    assert r.status_code == 401
    body = r.json()
    assert body["required_headers"] == REQUIRED_HEADERS
    assert set(body["missing_headers"]) == set(REQUIRED_HEADERS)


@pytest.mark.parametrize("missing", REQUIRED_HEADERS)
def test_each_header_is_required(client, missing):
    h = {**HEADERS, **{k: v for k, v in PLACEHOLDERS.items() if k != missing}}
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 401
    assert r.json()["missing_headers"] == [missing]


def test_blank_header_counts_as_missing(client):
    h = {**HEADERS, **PLACEHOLDERS, "X-CW-Private-Key": "   "}
    assert client.post("/mcp", json=LIST, headers=h).status_code == 401


def test_placeholder_values_pass_initialize_and_tools_list(client):
    # The platform probes with placeholder values; formats are not validated here.
    h = {**HEADERS, **{k.lower(): v for k, v in PLACEHOLDERS.items()}}
    assert client.post("/mcp", json=INIT, headers=h).status_code == 200
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 200
    assert len(r.json()["result"]["tools"]) == 92


def test_placeholder_values_give_tool_error_not_http_error(client):
    h = {**HEADERS, **PLACEHOLDERS}
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "cw_get_ticket", "arguments": {"id": 1}},
    }
    r = client.post("/mcp", json=call, headers=h)
    assert r.status_code == 200
    assert '"invalid_argument"' in r.json()["result"]["content"][0]["text"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("na.myconnectwise.net", "https://na.myconnectwise.net/v4_6_release/apis/3.0"),
        ("https://na.myconnectwise.net/", "https://na.myconnectwise.net/v4_6_release/apis/3.0"),
        ("https://na.myconnectwise.net/v4_6_release/apis/3.0", "https://na.myconnectwise.net/v4_6_release/apis/3.0"),
        (
            "https://api-eu.myconnectwise.net/v4_6_release/apis/3.0/",
            "https://api-eu.myconnectwise.net/v4_6_release/apis/3.0",
        ),
        ("https://cw.example.com/v2025_1/apis/3.0/service", "https://cw.example.com/v2025_1/apis/3.0"),
        ("  cw.example.com:8443 ", "https://cw.example.com:8443/v4_6_release/apis/3.0"),
        ("http://cw.example.com", "http://cw.example.com/v4_6_release/apis/3.0"),
    ],
)
def test_base_url_normalisation(raw, expected):
    assert api.base_url(raw) == expected


@pytest.mark.parametrize(
    "raw", ["probe-placeholder", "ftp://cw.example.com", "https://user:pw@cw.example.com", "a b.com"]
)
def test_base_url_rejects(raw):
    with pytest.raises(api.ApiError) as exc:
        api.base_url(raw)
    assert exc.value.code == "invalid_argument"


def test_credentials_do_not_leak_between_requests():
    assert credentials.current() is None
