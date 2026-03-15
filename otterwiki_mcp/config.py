"""Configuration from environment variables."""

import os
import sys


class Config:
    def __init__(self):
        self.api_url = os.environ.get("OTTERWIKI_API_URL", "").rstrip("/")
        self.api_key = os.environ.get("OTTERWIKI_API_KEY", "")
        self.mcp_base_url = os.environ.get("MCP_BASE_URL", "").rstrip("/")
        self.mcp_auth_token = os.environ.get("MCP_AUTH_TOKEN", "")
        self._mcp_port_raw = os.environ.get("MCP_PORT", "8090")
        self.mcp_port = 8090  # replaced by validate()
        self.mcp_oauth_db = os.environ.get("MCP_OAUTH_DB", "mcp_oauth.db")
        self.consent_url = os.environ.get(
            "CONSENT_URL", "https://robot.wtf/auth/oauth/consent"
        ).rstrip("/")
        self.signing_key_path = os.environ.get(
            "SIGNING_KEY_PATH", "/srv/data/signing_key.pem"
        )
        self.platform_domain = os.environ.get("PLATFORM_DOMAIN", "robot.wtf")

    def validate(self):
        """Check required vars. Call at server startup, not import time."""
        if not self.api_url:
            print("OTTERWIKI_API_URL is required", file=sys.stderr)
            sys.exit(1)
        if not self.api_key:
            print("OTTERWIKI_API_KEY is required", file=sys.stderr)
            sys.exit(1)
        if not self.mcp_base_url:
            print("MCP_BASE_URL is required", file=sys.stderr)
            sys.exit(1)
        try:
            self.mcp_port = int(self._mcp_port_raw)
        except (ValueError, TypeError):
            print(f"MCP_PORT must be a valid integer, got: {self._mcp_port_raw!r}", file=sys.stderr)
            sys.exit(1)
        if not (1 <= self.mcp_port <= 65535):
            print(f"MCP_PORT must be between 1 and 65535, got: {self.mcp_port}", file=sys.stderr)
            sys.exit(1)


def get_config() -> Config:
    """Create and validate config. Used by server entry point."""
    cfg = Config()
    cfg.validate()
    return cfg
