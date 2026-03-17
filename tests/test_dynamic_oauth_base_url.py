"""Tests for dynamic OAuth base URL — per-request Host header derivation.

TDD: these tests are written first and drive the implementation.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
from starlette.routing import Route

from otterwiki_mcp.consent import derive_signing_key
from otterwiki_mcp.oauth_store import SQLiteOAuthProvider


# --- Helpers ---

SIGNING_KEY = derive_signing_key("test-pem-data-" + "x" * 50)
CONSENT_URL = "https://robot.wtf/auth/oauth/consent"


def _make_provider(tmp_path, base_url="https://dev.robot.wtf", **kwargs):
    db = str(tmp_path / "test_oauth.db")
    defaults = dict(
        base_url=base_url,
        consent_url=CONSENT_URL,
        signing_key=SIGNING_KEY,
    )
    defaults.update(kwargs)
    return SQLiteOAuthProvider(db, **defaults)


# ---------------------------------------------------------------------------
# Unit tests: _get_wiki_slug()
# ---------------------------------------------------------------------------


class TestGetWikiSlug:
    def test_get_wiki_slug_from_host(self, tmp_path):
        """_get_wiki_slug() returns slug from request Host header."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")

        mock_request = MagicMock()
        mock_request.headers = {"host": "wonderchook.robot.wtf"}

        with patch(
            "otterwiki_mcp.oauth_store.get_http_request", return_value=mock_request
        ):
            slug = provider._get_wiki_slug()

        assert slug == "wonderchook"

    def test_get_wiki_slug_strips_port(self, tmp_path):
        """_get_wiki_slug() strips port from host header before parsing."""
        provider = _make_provider(tmp_path)

        mock_request = MagicMock()
        mock_request.headers = {"host": "myslug.robot.wtf:8090"}

        with patch(
            "otterwiki_mcp.oauth_store.get_http_request", return_value=mock_request
        ):
            slug = provider._get_wiki_slug()

        assert slug == "myslug"

    def test_get_wiki_slug_fallback_no_request_context(self, tmp_path):
        """_get_wiki_slug() falls back to _default_wiki_slug when no HTTP context."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")

        with patch(
            "otterwiki_mcp.oauth_store.get_http_request",
            side_effect=RuntimeError("No request context"),
        ):
            slug = provider._get_wiki_slug()

        assert slug == "dev"

    def test_get_wiki_slug_fallback_two_part_host(self, tmp_path):
        """_get_wiki_slug() falls back to _default_wiki_slug for 2-part hostname."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")

        mock_request = MagicMock()
        mock_request.headers = {"host": "robot.wtf"}

        with patch(
            "otterwiki_mcp.oauth_store.get_http_request", return_value=mock_request
        ):
            slug = provider._get_wiki_slug()

        assert slug == "dev"

    def test_get_wiki_slug_fallback_empty_default(self, tmp_path):
        """_get_wiki_slug() returns empty string when default is also empty (localhost)."""
        provider = _make_provider(tmp_path, base_url="http://localhost:8090")

        with patch(
            "otterwiki_mcp.oauth_store.get_http_request",
            side_effect=RuntimeError("No request context"),
        ):
            slug = provider._get_wiki_slug()

        assert slug == ""


# ---------------------------------------------------------------------------
# Integration tests: /.well-known/oauth-authorization-server
# ---------------------------------------------------------------------------


def _make_test_app(provider: SQLiteOAuthProvider, platform_domain: str = "robot.wtf"):
    """Build a minimal Starlette app with the provider's routes registered."""
    routes = provider.get_routes(mcp_path="/mcp")
    return Starlette(routes=routes)


class TestMetadataEndpointDynamic:
    def test_metadata_uses_request_host(self, tmp_path):
        """GET /.well-known/oauth-authorization-server with Host: wonderchook.robot.wtf
        should return endpoints containing wonderchook.robot.wtf, not dev.robot.wtf."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")
        provider._platform_domain = "robot.wtf"

        app = _make_test_app(provider)
        client = TestClient(app, raise_server_exceptions=True)

        response = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"Host": "wonderchook.robot.wtf"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "wonderchook.robot.wtf" in data["issuer"]
        assert "wonderchook.robot.wtf" in data["authorization_endpoint"]
        assert "wonderchook.robot.wtf" in data["token_endpoint"]
        # Must NOT contain the static default
        assert "dev.robot.wtf" not in data["issuer"]

    def test_metadata_fallback_without_subdomain(self, tmp_path):
        """No subdomain (2-part host) -> falls back to MCP_BASE_URL value."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")
        provider._platform_domain = "robot.wtf"

        app = _make_test_app(provider)
        client = TestClient(app, raise_server_exceptions=True)

        response = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"Host": "robot.wtf"},
        )

        assert response.status_code == 200
        data = response.json()
        # Falls back to the static base_url
        assert "dev.robot.wtf" in data["issuer"]

    def test_metadata_standard_fields_present(self, tmp_path):
        """Metadata response must include all required OAuth 2.1 fields."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")
        provider._platform_domain = "robot.wtf"

        app = _make_test_app(provider)
        client = TestClient(app, raise_server_exceptions=True)

        response = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"Host": "wonderchook.robot.wtf"},
        )

        assert response.status_code == 200
        data = response.json()
        required = [
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "response_types_supported",
            "grant_types_supported",
            "code_challenge_methods_supported",
        ]
        for field in required:
            assert field in data, f"Missing field: {field}"

    def test_metadata_no_platform_domain_uses_base_url(self, tmp_path):
        """When _platform_domain is not set, metadata always returns base_url."""
        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")
        # _platform_domain is NOT set

        app = _make_test_app(provider)
        client = TestClient(app, raise_server_exceptions=True)

        response = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"Host": "wonderchook.robot.wtf"},
        )

        assert response.status_code == 200
        data = response.json()
        # Without platform_domain, can't safely construct dynamic URL
        assert "dev.robot.wtf" in data["issuer"]


# ---------------------------------------------------------------------------
# Integration tests: authorize() uses dynamic slug
# ---------------------------------------------------------------------------


class TestAuthorizeDynamicSlug:
    @pytest.mark.asyncio
    async def test_authorize_uses_host_slug(self, tmp_path):
        """authorize() should include the slug from the request Host, not the static one."""
        from urllib.parse import parse_qs, urlparse
        from mcp.server.auth.provider import AuthorizationParams
        from mcp.shared.auth import OAuthClientInformationFull
        from pydantic import AnyHttpUrl

        provider = _make_provider(tmp_path, base_url="https://dev.robot.wtf")
        client_info = OAuthClientInformationFull(
            client_id="test-client",
            client_name="Test",
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
        )
        await provider.register_client(client_info)

        params = AuthorizationParams(
            state="s",
            scopes=[],
            code_challenge="cc",
            redirect_uri=AnyHttpUrl("http://localhost/callback"),
            redirect_uri_provided_explicitly=True,
        )

        mock_request = MagicMock()
        mock_request.headers = {"host": "wonderchook.robot.wtf"}

        with patch(
            "otterwiki_mcp.oauth_store.get_http_request", return_value=mock_request
        ):
            url = await provider.authorize(client_info, params)

        qs = parse_qs(urlparse(url).query)
        assert qs["wiki_slug"] == ["wonderchook"]
