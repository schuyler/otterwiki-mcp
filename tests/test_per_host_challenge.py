"""The 401 challenge's resource_metadata must name the request's tenant host."""

from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from starlette.testclient import TestClient

import otterwiki_mcp.server as server_mod

METADATA_PATH = "/.well-known/oauth-protected-resource/mcp"


@pytest.fixture
def app(monkeypatch, tmp_path):
    """The /mcp ASGI app built from the middleware that main() passes to mcp.run."""

    def build(base_url):
        key_file = tmp_path / "signing_key.pem"
        key_file.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\n" + "x" * 64 + "\n-----END RSA PRIVATE KEY-----\n"
        )
        monkeypatch.setenv("OTTERWIKI_API_URL", "http://wiki.test:80")
        monkeypatch.setenv("OTTERWIKI_API_KEY", "test-key")
        monkeypatch.setenv("MCP_BASE_URL", base_url)
        monkeypatch.setenv("PLATFORM_DOMAIN", "robot.wtf")
        monkeypatch.setenv("CONSENT_URL", "https://robot.wtf/auth/oauth/consent")
        monkeypatch.setenv("SIGNING_KEY_PATH", str(key_file))
        monkeypatch.setenv("MCP_OAUTH_DB", str(tmp_path / "oauth.db"))
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)

        with patch.object(server_mod.mcp, "run") as mock_run:
            server_mod.main()

        middleware = mock_run.call_args.kwargs.get("middleware")
        assert middleware, "main() must pass the per-host challenge middleware to mcp.run"
        return TestClient(
            server_mod.mcp.http_app(
                transport="streamable-http", stateless_http=True, middleware=middleware
            )
        )

    return build


def test_missing_token_challenge_points_at_request_host(app):
    resp = app("https://dev.robot.wtf").post("/mcp", headers={"Host": "placegarden.robot.wtf"})

    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == (
        f'Bearer resource_metadata="https://placegarden.robot.wtf{METADATA_PATH}"'
    )


def test_invalid_token_challenge_points_at_request_host(app):
    resp = app("https://dev.robot.wtf").post(
        "/mcp",
        headers={"Host": "placegarden.robot.wtf", "Authorization": "Bearer bogus"},
    )

    assert resp.status_code == 401
    challenge = resp.headers["www-authenticate"]
    assert 'error="invalid_token"' in challenge
    assert f'resource_metadata="https://placegarden.robot.wtf{METADATA_PATH}"' in challenge
    assert resp.json()["error"] == "invalid_token"


@pytest.mark.parametrize(
    "host", ["placegarden.robot.wtf", "localhost:8001", "Bad_Slug.robot.wtf"]
)
def test_challenge_matches_metadata_doc(app, host):
    client = app("https://dev.example.test")

    resource = client.get(METADATA_PATH, headers={"Host": host}).json()["resource"]
    parts = urlsplit(resource)
    expected = f'Bearer resource_metadata="{parts.scheme}://{parts.netloc}{METADATA_PATH}"'

    resp = client.post("/mcp", headers={"Host": host})
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == expected
