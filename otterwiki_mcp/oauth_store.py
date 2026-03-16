"""SQLite-backed OAuth provider that persists state across restarts.

Drop-in replacement for FastMCP's InMemoryOAuthProvider.  Stores clients,
authorization codes, access tokens, and refresh tokens in a local SQLite
database so that Claude.ai doesn't need to re-authorize after a server
restart.
"""

import json
import logging
import re
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from fastmcp.server.auth.auth import (
    ClientRegistrationOptions,
    OAuthProvider,
    RevocationOptions,
)

from otterwiki_mcp.consent import OAUTH_PARAM_NAMES, verify_approval_token

logger = logging.getLogger(__name__)

# Expiration defaults
AUTH_CODE_EXPIRY_SECONDS = 10 * 60  # 10 minutes
ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60  # 1 hour
REFRESH_TOKEN_EXPIRY_SECONDS = 30 * 24 * 60 * 60  # 30 days

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS oauth_clients (
    client_id      TEXT PRIMARY KEY,
    client_json    TEXT NOT NULL,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_codes (
    code                  TEXT PRIMARY KEY,
    client_id             TEXT NOT NULL,
    redirect_uri          TEXT NOT NULL,
    redirect_uri_provided_explicitly INTEGER NOT NULL DEFAULT 1,
    code_challenge        TEXT NOT NULL,
    scopes                TEXT NOT NULL,
    expires_at            REAL NOT NULL,
    resource              TEXT
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    token          TEXT PRIMARY KEY,
    client_id      TEXT NOT NULL,
    scopes         TEXT NOT NULL,
    expires_at     INTEGER,
    token_type     TEXT NOT NULL,
    refresh_token  TEXT,
    resource       TEXT
);
"""


class SQLiteOAuthProvider(OAuthProvider):
    """Persistent OAuth 2.1 provider backed by SQLite.

    Implements the same interface as ``InMemoryOAuthProvider`` so it can be
    used as a drop-in replacement anywhere FastMCP expects an
    ``OAuthProvider``.
    """

    def __init__(
        self,
        db_path: str,
        *,
        base_url: str,
        consent_url: str = "",
        signing_key: bytes = b"",
        client_registration_options: ClientRegistrationOptions | None = None,
        revocation_options: RevocationOptions | None = None,
        required_scopes: list[str] | None = None,
    ):
        super().__init__(
            base_url=base_url,
            client_registration_options=client_registration_options,
            revocation_options=revocation_options,
            required_scopes=required_scopes,
        )
        self._db_path = db_path
        self._consent_url = consent_url
        self._signing_key = signing_key
        parsed = urlparse(base_url)
        host_parts = parsed.hostname.split(".") if parsed.hostname else []
        self._wiki_slug = host_parts[0] if len(host_parts) >= 3 else ""
        if self._wiki_slug:
            if not re.fullmatch(r"[a-z0-9-]+", self._wiki_slug):
                raise ValueError(
                    f"wiki_slug derived from base_url is invalid: {self._wiki_slug!r}. "
                    "Must match [a-z0-9-]+"
                )
        else:
            logger.warning(
                "wiki_slug is empty (base_url=%r has no 3-part hostname); "
                "OAuth consent redirect will include wiki_slug= (empty). "
                "This is expected for local development.",
                base_url,
            )
        self._ensure_schema()

    # ---- helpers ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    # ---- OAuthProvider interface ----

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT client_json FROM oauth_clients WHERE client_id = ?",
                (client_id,),
            ).fetchone()
            if row is None:
                return None
            return OAuthClientInformationFull.model_validate_json(row["client_json"])
        finally:
            conn.close()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # Validate scopes if configured
        if (
            client_info.scope is not None
            and self.client_registration_options is not None
            and self.client_registration_options.valid_scopes is not None
        ):
            requested = set(client_info.scope.split())
            valid = set(self.client_registration_options.valid_scopes)
            invalid = requested - valid
            if invalid:
                raise ValueError(
                    f"Requested scopes are not valid: {', '.join(invalid)}"
                )

        if client_info.client_id is None:
            raise ValueError("client_id is required for client registration")

        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO oauth_clients (client_id, client_json, created_at) "
                "VALUES (?, ?, ?)",
                (
                    client_info.client_id,
                    client_info.model_dump_json(),
                    time.time(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        if client.client_id is None:
            raise AuthorizeError(
                error="invalid_client", error_description="Client ID is required"
            )

        # Verify client is registered
        existing = await self.get_client(client.client_id)
        if existing is None:
            raise AuthorizeError(
                error="unauthorized_client",
                error_description=f"Client '{client.client_id}' not registered.",
            )

        if not self._consent_url:
            raise AuthorizeError(
                error="server_error",
                error_description="Consent URL not configured",
            )

        # Build consent redirect — the consent page will handle login
        # and redirect back to /authorize/callback with an approval token.
        scopes_list = params.scopes if params.scopes is not None else []
        if client.scope:
            allowed = set(client.scope.split())
            scopes_list = [s for s in scopes_list if s in allowed]

        consent_params: dict[str, str] = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "code_challenge": params.code_challenge,
            "code_challenge_method": "S256",
            "state": params.state or "",
            "scope": " ".join(scopes_list),
            "response_type": "code",
            "wiki_slug": self._wiki_slug,
        }
        if params.resource:
            consent_params["resource"] = params.resource

        return f"{self._consent_url}?{urlencode(consent_params)}"

    async def complete_authorization(
        self,
        *,
        approval_token: str,
        client_id: str,
        redirect_uri: str,
        code_challenge: str,
        state: str,
        scope: str,
        resource: str | None = None,
    ) -> str:
        """Verify an approval token and issue an authorization code.

        Called by the /authorize/callback route after the user consents
        on the auth service.

        Returns:
            Redirect URI with auth code and state for the OAuth client.

        Raises:
            AuthorizeError: If the token is invalid or the client is unknown.
        """
        if not self._signing_key:
            raise AuthorizeError(
                error="server_error",
                error_description="Signing key not configured",
            )

        payload = verify_approval_token(approval_token, self._signing_key)
        if payload is None:
            raise AuthorizeError(
                error="access_denied",
                error_description="Invalid or expired approval token",
            )

        # Verify the token's client_id matches the request
        if payload.get("client_id") != client_id:
            logger.warning(
                "Approval token client_id mismatch: token=%s request=%s",
                payload.get("client_id"),
                client_id,
            )
            raise AuthorizeError(
                error="access_denied",
                error_description="Approval token client_id mismatch",
            )

        # Verify the token's wiki_slug matches this MCP server's wiki
        token_slug = payload.get("wiki_slug", "")
        if self._wiki_slug and token_slug != self._wiki_slug:
            logger.warning(
                "Approval token wiki_slug mismatch: token=%s server=%s",
                token_slug,
                self._wiki_slug,
            )
            raise AuthorizeError(
                error="access_denied",
                error_description="Approval token wiki_slug mismatch",
            )

        # Verify client is registered
        client = await self.get_client(client_id)
        if client is None:
            raise AuthorizeError(
                error="unauthorized_client",
                error_description=f"Client '{client_id}' not registered.",
            )

        # Validate redirect_uri against client's registered URIs
        if client.redirect_uris:
            registered = [str(u) for u in client.redirect_uris]
            if redirect_uri not in registered:
                logger.warning(
                    "redirect_uri not in client's registered URIs: %s",
                    redirect_uri,
                )
                raise AuthorizeError(
                    error="invalid_request",
                    error_description="redirect_uri does not match any registered URI for this client",
                )

        # Issue auth code
        code_value = f"authcode_{secrets.token_hex(20)}"
        expires_at = time.time() + AUTH_CODE_EXPIRY_SECONDS
        scopes_list = scope.split() if scope else []

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO oauth_codes "
                "(code, client_id, redirect_uri, redirect_uri_provided_explicitly, "
                "code_challenge, scopes, expires_at, resource) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    code_value,
                    client_id,
                    redirect_uri,
                    1,
                    code_challenge,
                    json.dumps(scopes_list),
                    expires_at,
                    resource,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return construct_redirect_uri(redirect_uri, code=code_value, state=state)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM oauth_codes WHERE code = ?", (authorization_code,)
            ).fetchone()
            if row is None:
                return None
            if row["client_id"] != client.client_id:
                return None
            if row["expires_at"] < time.time():
                conn.execute(
                    "DELETE FROM oauth_codes WHERE code = ?", (authorization_code,)
                )
                conn.commit()
                return None
            return AuthorizationCode(
                code=row["code"],
                client_id=row["client_id"],
                redirect_uri=row["redirect_uri"],
                redirect_uri_provided_explicitly=bool(
                    row["redirect_uri_provided_explicitly"]
                ),
                code_challenge=row["code_challenge"],
                scopes=json.loads(row["scopes"]),
                expires_at=row["expires_at"],
                resource=row["resource"],
            )
        finally:
            conn.close()

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        conn = self._connect()
        try:
            # Consume the code atomically
            row = conn.execute(
                "DELETE FROM oauth_codes WHERE code = ? RETURNING *",
                (authorization_code.code,),
            ).fetchone()
            conn.commit()
        finally:
            conn.close()

        if row is None:
            raise TokenError(
                "invalid_grant", "Authorization code not found or already used."
            )

        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")

        access_token_value = f"access_{secrets.token_hex(32)}"
        refresh_token_value = f"refresh_{secrets.token_hex(32)}"
        access_expires = int(time.time() + ACCESS_TOKEN_EXPIRY_SECONDS)
        refresh_expires = int(time.time() + REFRESH_TOKEN_EXPIRY_SECONDS)
        scopes = json.loads(row["scopes"])
        resource = row["resource"]

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO oauth_tokens "
                "(token, client_id, scopes, expires_at, token_type, refresh_token, resource) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    access_token_value,
                    client.client_id,
                    json.dumps(scopes),
                    access_expires,
                    "access",
                    refresh_token_value,
                    resource,
                ),
            )
            conn.execute(
                "INSERT INTO oauth_tokens "
                "(token, client_id, scopes, expires_at, token_type, refresh_token, resource) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    refresh_token_value,
                    client.client_id,
                    json.dumps(scopes),
                    refresh_expires,
                    "refresh",
                    access_token_value,
                    resource,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return OAuthToken(
            access_token=access_token_value,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_EXPIRY_SECONDS,
            refresh_token=refresh_token_value,
            scope=" ".join(scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM oauth_tokens WHERE token = ? AND token_type = 'access'",
                (token,),
            ).fetchone()
            if row is None:
                return None
            if row["expires_at"] is not None and row["expires_at"] < time.time():
                self._revoke_pair(conn, access_token=token)
                conn.commit()
                return None
            return AccessToken(
                token=row["token"],
                client_id=row["client_id"],
                scopes=json.loads(row["scopes"]),
                expires_at=row["expires_at"],
                resource=row["resource"],
            )
        finally:
            conn.close()

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM oauth_tokens WHERE token = ? AND token_type = 'refresh'",
                (refresh_token,),
            ).fetchone()
            if row is None:
                return None
            if row["client_id"] != client.client_id:
                return None
            if row["expires_at"] is not None and row["expires_at"] < time.time():
                self._revoke_pair(conn, refresh_token=refresh_token)
                conn.commit()
                return None
            return RefreshToken(
                token=row["token"],
                client_id=row["client_id"],
                scopes=json.loads(row["scopes"]),
                expires_at=row["expires_at"],
            )
        finally:
            conn.close()

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        original_scopes = set(refresh_token.scopes)
        requested_scopes = set(scopes)
        if not requested_scopes.issubset(original_scopes):
            raise TokenError(
                "invalid_scope",
                "Requested scopes exceed those authorized by the refresh token.",
            )

        if client.client_id is None:
            raise TokenError("invalid_client", "Client ID is required")

        # Revoke old pair
        conn = self._connect()
        try:
            self._revoke_pair(conn, refresh_token=refresh_token.token)
            conn.commit()
        finally:
            conn.close()

        # Issue new pair
        new_access = f"access_{secrets.token_hex(32)}"
        new_refresh = f"refresh_{secrets.token_hex(32)}"
        access_expires = int(time.time() + ACCESS_TOKEN_EXPIRY_SECONDS)
        refresh_expires = int(time.time() + REFRESH_TOKEN_EXPIRY_SECONDS)

        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO oauth_tokens "
                "(token, client_id, scopes, expires_at, token_type, refresh_token, resource) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_access,
                    client.client_id,
                    json.dumps(scopes),
                    access_expires,
                    "access",
                    new_refresh,
                    None,
                ),
            )
            conn.execute(
                "INSERT INTO oauth_tokens "
                "(token, client_id, scopes, expires_at, token_type, refresh_token, resource) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    new_refresh,
                    client.client_id,
                    json.dumps(scopes),
                    refresh_expires,
                    "refresh",
                    new_access,
                    None,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return OAuthToken(
            access_token=new_access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_EXPIRY_SECONDS,
            refresh_token=new_refresh,
            scope=" ".join(scopes),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        conn = self._connect()
        try:
            if isinstance(token, AccessToken):
                self._revoke_pair(conn, access_token=token.token)
            elif isinstance(token, RefreshToken):
                self._revoke_pair(conn, refresh_token=token.token)
            conn.commit()
        finally:
            conn.close()

    # ---- internal helpers ----

    @staticmethod
    def _revoke_pair(
        conn: sqlite3.Connection,
        *,
        access_token: str | None = None,
        refresh_token: str | None = None,
    ) -> None:
        """Delete a token and its paired counterpart."""
        tokens_to_delete: set[str] = set()

        for tok in (access_token, refresh_token):
            if tok is None:
                continue
            tokens_to_delete.add(tok)
            row = conn.execute(
                "SELECT refresh_token FROM oauth_tokens WHERE token = ?", (tok,)
            ).fetchone()
            if row and row["refresh_token"]:
                tokens_to_delete.add(row["refresh_token"])

        for tok in tokens_to_delete:
            conn.execute("DELETE FROM oauth_tokens WHERE token = ?", (tok,))
