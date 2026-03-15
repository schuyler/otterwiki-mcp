"""Tests for consent token verification."""

import hashlib
import hmac
import json
import time

import pytest

from otterwiki_mcp.consent import (
    APPROVAL_TOKEN_LIFETIME,
    derive_signing_key,
    verify_approval_token,
)


# --- derive_signing_key ---


class TestDeriveSigningKey:
    def test_returns_32_bytes(self):
        key = derive_signing_key("x" * 100)
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_deterministic(self):
        material = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
        assert derive_signing_key(material) == derive_signing_key(material)

    def test_uses_first_64_chars(self):
        a = "A" * 64 + "B" * 100
        b = "A" * 64 + "C" * 100
        assert derive_signing_key(a) == derive_signing_key(b)

    def test_different_material_different_key(self):
        assert derive_signing_key("alpha" * 20) != derive_signing_key("bravo" * 20)

    def test_domain_separated(self):
        """Key derivation includes a 'consent:' prefix for domain separation."""
        material = "test_material_" + "x" * 50
        raw_hash = hashlib.sha256(material[:64].encode()).digest()
        consent_key = derive_signing_key(material)
        # Must differ from raw hash (because of the "consent:" prefix)
        assert consent_key != raw_hash


# --- Helper to create signed tokens ---


def _sign_token(payload: dict, signing_key: bytes) -> str:
    """Mirror of auth service's sign_token for test purposes."""
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(signing_key, payload_json.encode(), hashlib.sha256).hexdigest()
    return f"{payload_json}|{sig}"


# --- verify_approval_token ---


class TestVerifyApprovalToken:
    KEY = derive_signing_key("test-pem-material-" + "x" * 50)

    def _make_token(self, **overrides):
        payload = {
            "client_id": "test-client",
            "exp": int(time.time()) + 120,
            "type": "approval",
        }
        payload.update(overrides)
        return _sign_token(payload, self.KEY)

    def test_valid_token(self):
        token = self._make_token()
        result = verify_approval_token(token, self.KEY)
        assert result is not None
        assert result["client_id"] == "test-client"
        assert result["type"] == "approval"

    def test_expired_token_rejected(self):
        token = self._make_token(exp=int(time.time()) - 10)
        assert verify_approval_token(token, self.KEY) is None

    def test_wrong_key_rejected(self):
        token = self._make_token()
        wrong_key = derive_signing_key("wrong-key-material-" + "y" * 50)
        assert verify_approval_token(token, wrong_key) is None

    def test_tampered_payload_rejected(self):
        token = self._make_token()
        # Flip a character in the payload
        parts = token.split("|")
        tampered = parts[0][:-1] + ("X" if parts[0][-1] != "X" else "Y")
        assert verify_approval_token(f"{tampered}|{parts[1]}", self.KEY) is None

    def test_no_pipe_rejected(self):
        assert verify_approval_token("no-pipe-here", self.KEY) is None

    def test_invalid_json_rejected(self):
        sig = hmac.new(self.KEY, b"not-json", hashlib.sha256).hexdigest()
        assert verify_approval_token(f"not-json|{sig}", self.KEY) is None

    def test_empty_token_rejected(self):
        assert verify_approval_token("", self.KEY) is None

    def test_preserves_all_payload_fields(self):
        token = self._make_token(extra_field="hello", number=42)
        result = verify_approval_token(token, self.KEY)
        assert result["extra_field"] == "hello"
        assert result["number"] == 42
