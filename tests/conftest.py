"""Shared fixtures for MCP server tests."""

import pytest
import httpx
import respx

from otterwiki_mcp.api_client import WikiClient


@pytest.fixture
def mock_api():
    """Activate respx mock router for httpx requests."""
    with respx.mock(base_url="http://test-wiki:80") as router:
        yield router


@pytest.fixture
def wiki_client(mock_api):
    """WikiClient pointing at the mocked base URL."""
    return WikiClient("http://test-wiki:80", "test-api-key")
