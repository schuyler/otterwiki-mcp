"""Tests for multi-tenant wiki routing via Host header forwarding."""

import pytest
import httpx
import respx
from unittest.mock import MagicMock, patch

from otterwiki_mcp.api_client import WikiClient, current_host_header
import otterwiki_mcp.server as server_mod


@pytest.fixture(autouse=True)
def reset_host_header():
    """Ensure the contextvar is reset between tests."""
    token = current_host_header.set(None)
    yield
    current_host_header.set(None)


@pytest.fixture(autouse=True)
def setup_client(wiki_client):
    """Inject the test wiki_client into the server module."""
    server_mod.client = wiki_client


# --- current_host_header contextvar tests ---


@pytest.mark.asyncio
async def test_host_header_forwarded_when_set(mock_api):
    """When current_host_header is set, the Host header appears in API requests."""
    route = mock_api.get("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Page",
                "path": "Test/Page",
                "content": "# Test",
                "frontmatter": None,
                "links_to": [],
                "linked_from": [],
                "revision": "abc",
                "last_commit": None,
            },
        )
    )
    current_host_header.set("dev.robot.wtf")
    result = await server_mod.read_note("Test/Page")
    assert "# Test" in result
    # Verify the Host header was sent
    req = route.calls[0].request
    assert req.headers.get("host") == "dev.robot.wtf"


@pytest.mark.asyncio
async def test_no_host_header_when_not_set(mock_api):
    """When current_host_header is None, no extra Host header is added."""
    route = mock_api.get("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Page",
                "path": "Test/Page",
                "content": "# Test",
                "frontmatter": None,
                "links_to": [],
                "linked_from": [],
                "revision": "abc",
                "last_commit": None,
            },
        )
    )
    result = await server_mod.read_note("Test/Page")
    assert "# Test" in result
    # Host header should not be overridden (httpx default is the base_url host)
    req = route.calls[0].request
    assert req.headers.get("host") != "dev.robot.wtf"


@pytest.mark.asyncio
async def test_host_header_on_write(mock_api):
    """Host header is forwarded on write (PUT) requests too."""
    route = mock_api.put("/api/v1/pages/Test/New").mock(
        return_value=httpx.Response(
            201,
            json={
                "name": "New",
                "path": "Test/New",
                "revision": "def456",
                "created": True,
            },
        )
    )
    current_host_header.set("staging.robot.wtf")
    await server_mod.write_note("Test/New", "# New")
    req = route.calls[0].request
    assert req.headers.get("host") == "staging.robot.wtf"


# --- _set_host_from_request tests ---


def _make_mock_request(host: str) -> MagicMock:
    """Create a mock starlette-like request with the given Host header."""
    request = MagicMock()
    request.headers = {"host": host}
    return request


def test_set_host_extracts_slug_from_mcp_subdomain():
    """dev.mcp.robot.wtf -> Host: dev.robot.wtf"""
    server_mod.platform_domain = "robot.wtf"
    with patch("otterwiki_mcp.server.get_http_request", return_value=_make_mock_request("dev.mcp.robot.wtf")):
        server_mod._set_host_from_request()
    assert current_host_header.get() == "dev.robot.wtf"


def test_set_host_extracts_slug_from_direct_subdomain():
    """dev.robot.wtf -> Host: dev.robot.wtf"""
    server_mod.platform_domain = "robot.wtf"
    with patch("otterwiki_mcp.server.get_http_request", return_value=_make_mock_request("dev.robot.wtf")):
        server_mod._set_host_from_request()
    assert current_host_header.get() == "dev.robot.wtf"


def test_set_host_with_port():
    """dev.mcp.robot.wtf:8090 -> Host: dev.robot.wtf (port stripped)"""
    server_mod.platform_domain = "robot.wtf"
    with patch("otterwiki_mcp.server.get_http_request", return_value=_make_mock_request("dev.mcp.robot.wtf:8090")):
        server_mod._set_host_from_request()
    assert current_host_header.get() == "dev.robot.wtf"


def test_set_host_no_subdomain_skipped():
    """robot.wtf (no subdomain) -> no host header set"""
    server_mod.platform_domain = "robot.wtf"
    with patch("otterwiki_mcp.server.get_http_request", return_value=_make_mock_request("robot.wtf")):
        server_mod._set_host_from_request()
    assert current_host_header.get() is None


def test_set_host_empty_host_skipped():
    """Empty Host header -> no host header set"""
    server_mod.platform_domain = "robot.wtf"
    with patch("otterwiki_mcp.server.get_http_request", return_value=_make_mock_request("")):
        server_mod._set_host_from_request()
    assert current_host_header.get() is None


def test_set_host_no_request_context():
    """When get_http_request raises RuntimeError (e.g. stdio), no crash."""
    server_mod.platform_domain = "robot.wtf"
    with patch("otterwiki_mcp.server.get_http_request", side_effect=RuntimeError("No HTTP request")):
        server_mod._set_host_from_request()  # Should not raise
    assert current_host_header.get() is None


def test_set_host_custom_platform_domain():
    """Custom PLATFORM_DOMAIN is used correctly."""
    server_mod.platform_domain = "wikibot.io"
    with patch("otterwiki_mcp.server.get_http_request", return_value=_make_mock_request("myteam.mcp.wikibot.io")):
        server_mod._set_host_from_request()
    assert current_host_header.get() == "myteam.wikibot.io"


# --- Config tests ---


def test_config_platform_domain_default():
    """PLATFORM_DOMAIN defaults to empty string when not set."""
    import os
    from otterwiki_mcp.config import Config

    env = {
        "OTTERWIKI_API_URL": "http://localhost:8000",
        "OTTERWIKI_API_KEY": "test",
        "MCP_BASE_URL": "http://localhost:8090",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = Config()
    assert cfg.platform_domain == ""


def test_config_platform_domain_custom():
    """PLATFORM_DOMAIN can be overridden."""
    import os
    from otterwiki_mcp.config import Config

    env = {
        "OTTERWIKI_API_URL": "http://localhost:8000",
        "OTTERWIKI_API_KEY": "test",
        "MCP_BASE_URL": "http://localhost:8090",
        "PLATFORM_DOMAIN": "wikibot.io",
    }
    with patch.dict(os.environ, env, clear=True):
        cfg = Config()
    assert cfg.platform_domain == "wikibot.io"
