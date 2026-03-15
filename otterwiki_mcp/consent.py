"""Consent token verification for MCP OAuth flow.

The auth service (robot.wtf) creates HMAC-signed approval tokens when a user
consents to an OAuth authorization request. The MCP server verifies these
tokens on the /authorize/callback redirect before issuing an auth code.

Both services share the same platform signing key, so HMAC-based tokens
work without a shared database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time


# Approval token lifetime — must match the auth service
APPROVAL_TOKEN_LIFETIME = 120  # 2 minutes

# OAuth params preserved through the consent flow
OAUTH_PARAM_NAMES = (
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "response_type",
    "resource",
)


def derive_signing_key(private_key_material: str) -> bytes:
    """Derive an HMAC signing key from platform private key material.

    Uses a prefix to domain-separate the consent key from other uses
    of the same key material.

    Args:
        private_key_material: First 64 chars of the PEM private key.
    """
    return hashlib.sha256(
        f"consent:{private_key_material[:64]}".encode()
    ).digest()


def verify_approval_token(token: str, signing_key: bytes) -> dict | None:
    """Verify and decode an approval token from the consent page.

    Args:
        token: The signed token string ("{json_payload}|{hex_signature}").
        signing_key: HMAC key bytes (must match the key used to sign).

    Returns:
        Decoded payload dict, or None if invalid/expired.
    """
    if "|" not in token:
        return None
    payload_json, sig = token.rsplit("|", 1)
    expected = hmac.new(
        signing_key, payload_json.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload
