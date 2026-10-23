# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Process-level settings. Tenant credentials are never read from here."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

URL_HEADER = "X-CW-Url"
COMPANY_ID_HEADER = "X-CW-Company-Id"
PUBLIC_KEY_HEADER = "X-CW-Public-Key"
PRIVATE_KEY_HEADER = "X-CW-Private-Key"
CLIENT_ID_HEADER = "X-CW-Client-Id"

REQUIRED_HEADERS = [URL_HEADER, COMPANY_ID_HEADER, PUBLIC_KEY_HEADER, PRIVATE_KEY_HEADER, CLIENT_ID_HEADER]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_transport: Literal["stdio", "http"] = "http"
    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # Outbound HTTP behaviour.
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_retries: int = 3
    # Upper bound for one tool call including retries (must stay below 120s).
    call_budget_seconds: float = 100.0


def get_settings() -> Settings:
    return Settings()
