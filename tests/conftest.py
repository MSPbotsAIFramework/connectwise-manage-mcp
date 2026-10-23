# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from connectwise_manage_mcp import credentials
from connectwise_manage_mcp.config import Settings
from connectwise_manage_mcp.server import create_mcp

SITE = "cw.example.com"
BASE = "https://cw.example.com/v4_6_release/apis/3.0"


@pytest.fixture
def settings() -> Settings:
    # Keep retries fast in tests.
    return Settings(max_retries=2, call_budget_seconds=10)


@pytest.fixture
def mcp(settings):
    return create_mcp(settings)


@pytest.fixture
def creds():
    token = credentials._current.set(
        credentials.Credentials(
            url=SITE,
            company_id="examplecompany",
            public_key="YOUR_PUBLIC_KEY",
            private_key="YOUR_PRIVATE_KEY",
            client_id="YOUR_CLIENT_ID",
        )
    )
    yield
    credentials._current.reset(token)


@pytest.fixture
def call(mcp):
    async def _call(tool: str, /, **args):
        result = await mcp.call_tool(tool, args)
        blocks = result[0] if isinstance(result, tuple) else result
        return json.loads(blocks[0].text)

    return _call


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    # Retries still happen, without waiting.
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr("connectwise_manage_mcp.api.asyncio.sleep", _sleep)
