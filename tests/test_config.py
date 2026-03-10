"""Tests for config.py — environment variable loading and validation."""

import pytest

from otterwiki_mcp.config import Config, get_config


# --- Minimal valid env for all tests that need it ---

VALID_ENV = {
    "OTTERWIKI_API_URL": "http://wiki.test:80",
    "OTTERWIKI_API_KEY": "test-key",
    "MCP_BASE_URL": "http://localhost:8090",
}


class TestConfigInit:
    """Config.__init__ reads environment variables correctly."""

    def test_reads_all_vars(self, monkeypatch):
        monkeypatch.setenv("OTTERWIKI_API_URL", "http://wiki.test:80/")
        monkeypatch.setenv("OTTERWIKI_API_KEY", "key123")
        monkeypatch.setenv("MCP_BASE_URL", "http://localhost:9000/")
        monkeypatch.setenv("MCP_AUTH_TOKEN", "tok-abc")
        monkeypatch.setenv("MCP_PORT", "9999")

        cfg = Config()
        assert cfg.api_url == "http://wiki.test:80"  # trailing slash stripped
        assert cfg.api_key == "key123"
        assert cfg.mcp_base_url == "http://localhost:9000"  # trailing slash stripped
        assert cfg.mcp_auth_token == "tok-abc"
        assert cfg._mcp_port_raw == "9999"

    def test_defaults_when_unset(self, monkeypatch):
        monkeypatch.delenv("OTTERWIKI_API_URL", raising=False)
        monkeypatch.delenv("OTTERWIKI_API_KEY", raising=False)
        monkeypatch.delenv("MCP_BASE_URL", raising=False)
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("MCP_PORT", raising=False)

        cfg = Config()
        assert cfg.api_url == ""
        assert cfg.api_key == ""
        assert cfg.mcp_base_url == ""
        assert cfg.mcp_auth_token == ""
        assert cfg._mcp_port_raw == "8090"
        assert cfg.mcp_port == 8090


class TestConfigValidate:
    """Config.validate() enforces required vars and port constraints."""

    def _set_valid_env(self, monkeypatch):
        for k, v in VALID_ENV.items():
            monkeypatch.setenv(k, v)

    def test_passes_with_valid_env(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        cfg = Config()
        cfg.validate()  # should not raise
        assert cfg.mcp_port == 8090

    def test_missing_api_url_exits(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.delenv("OTTERWIKI_API_URL")
        cfg = Config()
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_missing_api_key_exits(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.delenv("OTTERWIKI_API_KEY")
        cfg = Config()
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_missing_mcp_base_url_exits(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.delenv("MCP_BASE_URL")
        cfg = Config()
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_mcp_auth_token_optional(self, monkeypatch):
        """MCP_AUTH_TOKEN may be omitted — validate() must not exit."""
        self._set_valid_env(monkeypatch)
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        cfg = Config()
        cfg.validate()
        assert cfg.mcp_auth_token == ""

    def test_invalid_port_non_numeric_exits(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("MCP_PORT", "not-a-number")
        cfg = Config()
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_port_zero_exits(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("MCP_PORT", "0")
        cfg = Config()
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_port_too_high_exits(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("MCP_PORT", "65536")
        cfg = Config()
        with pytest.raises(SystemExit):
            cfg.validate()

    def test_port_boundary_low(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("MCP_PORT", "1")
        cfg = Config()
        cfg.validate()
        assert cfg.mcp_port == 1

    def test_port_boundary_high(self, monkeypatch):
        self._set_valid_env(monkeypatch)
        monkeypatch.setenv("MCP_PORT", "65535")
        cfg = Config()
        cfg.validate()
        assert cfg.mcp_port == 65535


class TestGetConfig:
    """get_config() creates and validates in one call."""

    def test_returns_validated_config(self, monkeypatch):
        for k, v in VALID_ENV.items():
            monkeypatch.setenv(k, v)
        cfg = get_config()
        assert cfg.api_url == "http://wiki.test:80"
        assert cfg.mcp_port == 8090

    def test_exits_on_invalid(self, monkeypatch):
        monkeypatch.delenv("OTTERWIKI_API_URL", raising=False)
        monkeypatch.delenv("OTTERWIKI_API_KEY", raising=False)
        monkeypatch.delenv("MCP_BASE_URL", raising=False)
        with pytest.raises(SystemExit):
            get_config()
