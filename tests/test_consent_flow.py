"""Tests for the consent redirect flow in SQLiteOAuthProvider."""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl

from otterwiki_mcp.consent import derive_signing_key
from otterwiki_mcp.oauth_store import SQLiteOAuthProvider


# --- Helpers ---

SIGNING_KEY = derive_signing_key("test-pem-data-" + "x" * 50)
CONSENT_URL = "https://robot.wtf/auth/oauth/consent"


def _make_provider(tmp_path, consent_url=CONSENT_URL, signing_key=SIGNING_KEY):
    db = str(tmp_path / "test_oauth.db")
    return SQLiteOAuthProvider(
        db,
        base_url="http://localhost:8090",
        consent_url=consent_url,
        signing_key=signing_key,
    )


def _make_client(client_id="test-client") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name="Test Client",
        redirect_uris=[AnyHttpUrl("http://localhost/callback")],
    )


def _make_auth_params(**overrides) -> AuthorizationParams:
    defaults = dict(
        state="test-state",
        scopes=["read", "write"],
        code_challenge="challenge123",
        redirect_uri=AnyHttpUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
    )
    defaults.update(overrides)
    return AuthorizationParams(**defaults)


def _sign_approval_token(payload: dict, key: bytes = SIGNING_KEY) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(key, payload_json.encode(), hashlib.sha256).hexdigest()
    return f"{payload_json}|{sig}"


# --- authorize() consent redirect ---


class TestAuthorizeConsentRedirect:
    @pytest.mark.asyncio
    async def test_redirects_to_consent_url(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        url = await provider.authorize(client, _make_auth_params())
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "robot.wtf"
        assert parsed.path == "/auth/oauth/consent"

    @pytest.mark.asyncio
    async def test_passes_oauth_params(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        url = await provider.authorize(client, _make_auth_params())
        qs = parse_qs(urlparse(url).query)

        assert qs["client_id"] == ["test-client"]
        assert qs["redirect_uri"] == ["http://localhost/callback"]
        assert qs["code_challenge"] == ["challenge123"]
        assert qs["code_challenge_method"] == ["S256"]
        assert qs["state"] == ["test-state"]
        assert qs["scope"] == ["read write"]
        assert qs["response_type"] == ["code"]

    @pytest.mark.asyncio
    async def test_no_auth_code_stored(self, tmp_path):
        """authorize() should NOT store an auth code — that happens in complete_authorization."""
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        await provider.authorize(client, _make_auth_params())

        conn = provider._connect()
        try:
            count = conn.execute("SELECT COUNT(*) FROM oauth_codes").fetchone()[0]
            assert count == 0
        finally:
            conn.close()

    @pytest.mark.asyncio
    async def test_unregistered_client_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()

        with pytest.raises(AuthorizeError):
            await provider.authorize(client, _make_auth_params())

    @pytest.mark.asyncio
    async def test_missing_consent_url_raises(self, tmp_path):
        provider = _make_provider(tmp_path, consent_url="")
        client = _make_client()
        await provider.register_client(client)

        with pytest.raises(AuthorizeError) as exc_info:
            await provider.authorize(client, _make_auth_params())
        assert exc_info.value.error_description == "Consent URL not configured"


# --- complete_authorization() ---


class TestCompleteAuthorization:
    @pytest.mark.asyncio
    async def test_issues_auth_code(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        token = _sign_approval_token({
            "client_id": "test-client",
            "exp": int(time.time()) + 120,
            "type": "approval",
        })

        redirect = await provider.complete_authorization(
            approval_token=token,
            client_id="test-client",
            redirect_uri="http://localhost/callback",
            code_challenge="challenge123",
            state="test-state",
            scope="read write",
        )

        assert "code=" in redirect
        assert "state=test-state" in redirect
        code = redirect.split("code=")[1].split("&")[0]
        assert code.startswith("authcode_")

    @pytest.mark.asyncio
    async def test_auth_code_is_loadable(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        token = _sign_approval_token({
            "client_id": "test-client",
            "exp": int(time.time()) + 120,
        })

        redirect = await provider.complete_authorization(
            approval_token=token,
            client_id="test-client",
            redirect_uri="http://localhost/callback",
            code_challenge="challenge123",
            state="s",
            scope="read",
        )

        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None
        assert auth_code.client_id == "test-client"
        assert auth_code.code_challenge == "challenge123"
        assert auth_code.scopes == ["read"]

    @pytest.mark.asyncio
    async def test_expired_approval_token_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        token = _sign_approval_token({
            "client_id": "test-client",
            "exp": int(time.time()) - 10,
        })

        with pytest.raises(AuthorizeError) as exc_info:
            await provider.complete_authorization(
                approval_token=token,
                client_id="test-client",
                redirect_uri="http://localhost/callback",
                code_challenge="c",
                state="s",
                scope="",
            )
        assert "Invalid or expired" in exc_info.value.error_description

    @pytest.mark.asyncio
    async def test_wrong_signing_key_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        wrong_key = derive_signing_key("wrong-key-" + "y" * 60)
        token = _sign_approval_token(
            {"client_id": "test-client", "exp": int(time.time()) + 120},
            key=wrong_key,
        )

        with pytest.raises(AuthorizeError) as exc_info:
            await provider.complete_authorization(
                approval_token=token,
                client_id="test-client",
                redirect_uri="http://localhost/callback",
                code_challenge="c",
                state="s",
                scope="",
            )
        assert "Invalid or expired" in exc_info.value.error_description

    @pytest.mark.asyncio
    async def test_client_id_mismatch_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        await provider.register_client(_make_client("client-a"))
        await provider.register_client(_make_client("client-b"))

        token = _sign_approval_token({
            "client_id": "client-a",
            "exp": int(time.time()) + 120,
        })

        with pytest.raises(AuthorizeError) as exc_info:
            await provider.complete_authorization(
                approval_token=token,
                client_id="client-b",
                redirect_uri="http://localhost/callback",
                code_challenge="c",
                state="s",
                scope="",
            )
        assert "mismatch" in exc_info.value.error_description

    @pytest.mark.asyncio
    async def test_unregistered_client_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)

        token = _sign_approval_token({
            "client_id": "ghost",
            "exp": int(time.time()) + 120,
        })

        with pytest.raises(AuthorizeError) as exc_info:
            await provider.complete_authorization(
                approval_token=token,
                client_id="ghost",
                redirect_uri="http://localhost/callback",
                code_challenge="c",
                state="s",
                scope="",
            )
        assert "not registered" in exc_info.value.error_description

    @pytest.mark.asyncio
    async def test_missing_signing_key_raises(self, tmp_path):
        provider = _make_provider(tmp_path, signing_key=b"")
        client = _make_client()
        await provider.register_client(client)

        with pytest.raises(AuthorizeError) as exc_info:
            await provider.complete_authorization(
                approval_token="fake",
                client_id="test-client",
                redirect_uri="http://localhost/callback",
                code_challenge="c",
                state="s",
                scope="",
            )
        assert "Signing key not configured" in exc_info.value.error_description

    @pytest.mark.asyncio
    async def test_full_round_trip(self, tmp_path):
        """authorize -> consent -> complete_authorization -> exchange_code."""
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        # Step 1: authorize redirects to consent
        consent_redirect = await provider.authorize(client, _make_auth_params())
        assert "robot.wtf" in consent_redirect

        # Step 2: simulate consent approval
        token = _sign_approval_token({
            "client_id": "test-client",
            "exp": int(time.time()) + 120,
        })

        # Step 3: complete authorization
        code_redirect = await provider.complete_authorization(
            approval_token=token,
            client_id="test-client",
            redirect_uri="http://localhost/callback",
            code_challenge="challenge123",
            state="test-state",
            scope="read write",
        )

        # Step 4: exchange code for token
        code = code_redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None

        oauth_token = await provider.exchange_authorization_code(client, auth_code)
        assert oauth_token.access_token.startswith("access_")
        assert oauth_token.refresh_token.startswith("refresh_")
