"""Tests for SQLiteOAuthProvider — persistent OAuth storage."""

import time

import pytest
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationParams,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyHttpUrl

from otterwiki_mcp.oauth_store import (
    ACCESS_TOKEN_EXPIRY_SECONDS,
    AUTH_CODE_EXPIRY_SECONDS,
    REFRESH_TOKEN_EXPIRY_SECONDS,
    SQLiteOAuthProvider,
)


# --- Helpers ---


def _make_provider(tmp_path, **kwargs):
    db = str(tmp_path / "test_oauth.db")
    return SQLiteOAuthProvider(
        db,
        base_url="http://localhost:8090",
        **kwargs,
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
        scopes=[],
        code_challenge="challenge123",
        redirect_uri=AnyHttpUrl("http://localhost/callback"),
        redirect_uri_provided_explicitly=True,
    )
    defaults.update(overrides)
    return AuthorizationParams(**defaults)


# --- Client registration ---


class TestClientRegistration:
    @pytest.mark.asyncio
    async def test_register_and_get(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        loaded = await provider.get_client("test-client")
        assert loaded is not None
        assert loaded.client_id == "test-client"
        assert loaded.client_name == "Test Client"

    @pytest.mark.asyncio
    async def test_get_unknown_client(self, tmp_path):
        provider = _make_provider(tmp_path)
        assert await provider.get_client("nonexistent") is None

    @pytest.mark.asyncio
    async def test_register_overwrites(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        updated = _make_client()
        updated.client_name = "Updated Client"
        await provider.register_client(updated)

        loaded = await provider.get_client("test-client")
        assert loaded.client_name == "Updated Client"

    @pytest.mark.asyncio
    async def test_register_requires_client_id(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = OAuthClientInformationFull(
            client_id=None,
            redirect_uris=[AnyHttpUrl("http://localhost/callback")],
        )
        with pytest.raises(ValueError, match="client_id is required"):
            await provider.register_client(client)

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_path):
        """Data survives when a new provider instance opens the same DB."""
        db = str(tmp_path / "persist.db")

        p1 = SQLiteOAuthProvider(db, base_url="http://localhost:8090")
        await p1.register_client(_make_client())

        p2 = SQLiteOAuthProvider(db, base_url="http://localhost:8090")
        loaded = await p2.get_client("test-client")
        assert loaded is not None
        assert loaded.client_id == "test-client"


# --- Authorization flow ---


class TestAuthorizationFlow:
    @pytest.mark.asyncio
    async def test_full_flow(self, tmp_path):
        """Register -> authorize -> load_code -> exchange -> load_access_token."""
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        assert "code=" in redirect
        code = redirect.split("code=")[1].split("&")[0]

        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None
        assert auth_code.client_id == "test-client"

        token = await provider.exchange_authorization_code(client, auth_code)
        assert token.access_token.startswith("access_")
        assert token.refresh_token.startswith("refresh_")
        assert token.token_type == "Bearer"
        assert token.expires_in == ACCESS_TOKEN_EXPIRY_SECONDS

        access = await provider.load_access_token(token.access_token)
        assert access is not None
        assert access.client_id == "test-client"

    @pytest.mark.asyncio
    async def test_code_consumed_on_exchange(self, tmp_path):
        """Auth code is single-use."""
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)

        await provider.exchange_authorization_code(client, auth_code)

        # Second exchange should fail
        with pytest.raises(TokenError, match="already used"):
            await provider.exchange_authorization_code(client, auth_code)

    @pytest.mark.asyncio
    async def test_expired_code_rejected(self, tmp_path, monkeypatch):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]

        # Expire the code
        conn = provider._connect()
        conn.execute(
            "UPDATE oauth_codes SET expires_at = ? WHERE code = ?",
            (time.time() - 1, code),
        )
        conn.commit()
        conn.close()

        assert await provider.load_authorization_code(client, code) is None

    @pytest.mark.asyncio
    async def test_code_wrong_client_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client_a = _make_client("client-a")
        client_b = _make_client("client-b")
        await provider.register_client(client_a)
        await provider.register_client(client_b)

        redirect = await provider.authorize(client_a, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]

        assert await provider.load_authorization_code(client_b, code) is None

    @pytest.mark.asyncio
    async def test_unregistered_client_cannot_authorize(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        # Not registered
        from mcp.server.auth.provider import AuthorizeError

        with pytest.raises(AuthorizeError):
            await provider.authorize(client, _make_auth_params())


# --- Token operations ---


class TestTokenOperations:
    @pytest.mark.asyncio
    async def test_verify_token_delegates(self, tmp_path):
        """verify_token returns same result as load_access_token."""
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)

        result = await provider.verify_token(token.access_token)
        assert result is not None
        assert result.token == token.access_token

    @pytest.mark.asyncio
    async def test_expired_access_token_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)

        # Expire the access token
        conn = provider._connect()
        conn.execute(
            "UPDATE oauth_tokens SET expires_at = ? WHERE token = ?",
            (int(time.time()) - 1, token.access_token),
        )
        conn.commit()
        conn.close()

        assert await provider.load_access_token(token.access_token) is None

    @pytest.mark.asyncio
    async def test_unknown_token_returns_none(self, tmp_path):
        provider = _make_provider(tmp_path)
        assert await provider.load_access_token("bogus") is None


# --- Refresh tokens ---


class TestRefreshTokens:
    @pytest.mark.asyncio
    async def test_refresh_flow(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)

        refresh = await provider.load_refresh_token(client, token.refresh_token)
        assert refresh is not None

        new_token = await provider.exchange_refresh_token(client, refresh, [])
        assert new_token.access_token != token.access_token
        assert new_token.refresh_token != token.refresh_token

        # Old tokens should be revoked
        assert await provider.load_access_token(token.access_token) is None

    @pytest.mark.asyncio
    async def test_refresh_wrong_client(self, tmp_path):
        provider = _make_provider(tmp_path)
        client_a = _make_client("client-a")
        client_b = _make_client("client-b")
        await provider.register_client(client_a)
        await provider.register_client(client_b)

        redirect = await provider.authorize(client_a, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client_a, code)
        token = await provider.exchange_authorization_code(client_a, auth_code)

        assert await provider.load_refresh_token(client_b, token.refresh_token) is None

    @pytest.mark.asyncio
    async def test_refresh_scope_escalation_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)
        refresh = await provider.load_refresh_token(client, token.refresh_token)

        with pytest.raises(TokenError, match="invalid_scope"):
            await provider.exchange_refresh_token(client, refresh, ["admin"])

    @pytest.mark.asyncio
    async def test_expired_refresh_token_rejected(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)

        # Expire the refresh token
        conn = provider._connect()
        conn.execute(
            "UPDATE oauth_tokens SET expires_at = ? WHERE token = ?",
            (int(time.time()) - 1, token.refresh_token),
        )
        conn.commit()
        conn.close()

        assert await provider.load_refresh_token(client, token.refresh_token) is None


# --- Revocation ---


class TestRevocation:
    @pytest.mark.asyncio
    async def test_revoke_access_token(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)

        access = await provider.load_access_token(token.access_token)
        await provider.revoke_token(access)

        assert await provider.load_access_token(token.access_token) is None
        # Paired refresh token should also be gone
        assert await provider.load_refresh_token(client, token.refresh_token) is None

    @pytest.mark.asyncio
    async def test_revoke_refresh_token(self, tmp_path):
        provider = _make_provider(tmp_path)
        client = _make_client()
        await provider.register_client(client)

        redirect = await provider.authorize(client, _make_auth_params())
        code = redirect.split("code=")[1].split("&")[0]
        auth_code = await provider.load_authorization_code(client, code)
        token = await provider.exchange_authorization_code(client, auth_code)

        refresh = await provider.load_refresh_token(client, token.refresh_token)
        await provider.revoke_token(refresh)

        assert await provider.load_refresh_token(client, token.refresh_token) is None
        # Paired access token should also be gone
        assert await provider.load_access_token(token.access_token) is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_is_noop(self, tmp_path):
        provider = _make_provider(tmp_path)
        fake = AccessToken(token="nope", client_id="x", scopes=[], expires_at=None)
        # Should not raise
        await provider.revoke_token(fake)
