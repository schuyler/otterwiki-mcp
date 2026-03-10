"""Tests for server.py:main() — auth configuration with MultiAuth."""

from unittest.mock import patch, MagicMock

import pytest

from fastmcp.server.auth import MultiAuth, StaticTokenVerifier
from fastmcp.server.auth.providers.in_memory import InMemoryOAuthProvider

import otterwiki_mcp.server as server_mod


# --- Minimal valid env for main() ---

VALID_ENV = {
    "OTTERWIKI_API_URL": "http://wiki.test:80",
    "OTTERWIKI_API_KEY": "test-key",
    "MCP_BASE_URL": "http://localhost:8090",
}


def _run_main(monkeypatch, extra_env=None):
    """Set env, patch mcp.run to prevent actually starting, then call main().

    Returns the auth object assigned to mcp.auth.
    """
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    if extra_env:
        for k, v in extra_env.items():
            monkeypatch.setenv(k, v)
    # Ensure MCP_AUTH_TOKEN is absent unless explicitly provided
    if not extra_env or "MCP_AUTH_TOKEN" not in extra_env:
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

    with patch.object(server_mod.mcp, "run"):
        server_mod.main()

    return server_mod.mcp.auth


class TestAuthSetup:
    """main() constructs MultiAuth correctly based on env."""

    def test_multiauth_without_token(self, monkeypatch):
        """No MCP_AUTH_TOKEN -> MultiAuth with InMemoryOAuthProvider, no verifiers."""
        auth = _run_main(monkeypatch)

        assert isinstance(auth, MultiAuth)
        assert isinstance(auth.server, InMemoryOAuthProvider)
        assert auth.verifiers == []

    def test_multiauth_with_token(self, monkeypatch):
        """MCP_AUTH_TOKEN set -> MultiAuth with InMemoryOAuthProvider + StaticTokenVerifier."""
        auth = _run_main(monkeypatch, extra_env={"MCP_AUTH_TOKEN": "my-secret-token"})

        assert isinstance(auth, MultiAuth)
        assert isinstance(auth.server, InMemoryOAuthProvider)
        assert len(auth.verifiers) == 1
        assert isinstance(auth.verifiers[0], StaticTokenVerifier)

    def test_static_verifier_contains_token(self, monkeypatch):
        """The StaticTokenVerifier should accept the configured token."""
        token = "my-secret-token"
        auth = _run_main(monkeypatch, extra_env={"MCP_AUTH_TOKEN": token})

        verifier = auth.verifiers[0]
        assert token in verifier.tokens
        assert verifier.tokens[token]["client_id"] == "claude-code"
        assert verifier.tokens[token]["scopes"] == []

    def test_oauth_provider_base_url(self, monkeypatch):
        """InMemoryOAuthProvider receives MCP_BASE_URL."""
        auth = _run_main(monkeypatch)
        # InMemoryOAuthProvider stores base_url as AnyHttpUrl
        assert str(auth.server.base_url) == "http://localhost:8090/"

    def test_empty_token_treated_as_absent(self, monkeypatch):
        """An empty MCP_AUTH_TOKEN is falsy, so no StaticTokenVerifier."""
        auth = _run_main(monkeypatch, extra_env={"MCP_AUTH_TOKEN": ""})

        assert isinstance(auth, MultiAuth)
        assert auth.verifiers == []


class TestAuthVerification:
    """Verify that the constructed auth actually accepts/rejects tokens."""

    @pytest.mark.asyncio
    async def test_static_token_accepted(self, monkeypatch):
        """A valid bearer token should pass verification."""
        token = "test-bearer-token"
        auth = _run_main(monkeypatch, extra_env={"MCP_AUTH_TOKEN": token})

        result = await auth.verify_token(token)
        assert result is not None
        assert result.client_id == "claude-code"

    @pytest.mark.asyncio
    async def test_wrong_token_rejected(self, monkeypatch):
        """An unknown bearer token should be rejected by all verifiers."""
        auth = _run_main(monkeypatch, extra_env={"MCP_AUTH_TOKEN": "correct-token"})

        result = await auth.verify_token("wrong-token")
        assert result is None


class TestMainSideEffects:
    """main() sets up client and lifespan correctly."""

    def test_wiki_client_created(self, monkeypatch):
        """main() should create a WikiClient with the config values."""
        _run_main(monkeypatch)

        assert server_mod.client is not None
        # Verify the client was configured with the right base URL
        assert str(server_mod.client._client.base_url).rstrip("/") == "http://wiki.test"

    def test_mcp_run_called_with_correct_args(self, monkeypatch):
        """main() calls mcp.run() with streamable-http transport and correct port."""
        for k, v in VALID_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("MCP_PORT", "9999")

        with patch.object(server_mod.mcp, "run") as mock_run:
            server_mod.main()
            mock_run.assert_called_once_with(
                transport="streamable-http", host="0.0.0.0", port=9999
            )

    def test_lifespan_set(self, monkeypatch):
        """main() attaches the _lifespan context manager to mcp."""
        _run_main(monkeypatch)
        assert server_mod.mcp._lifespan is server_mod._lifespan
