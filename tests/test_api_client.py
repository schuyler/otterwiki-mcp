"""Tests for the WikiClient HTTP wrapper."""

import pytest
import httpx
import respx

from otterwiki_mcp.api_client import WikiClient, WikiAPIError


@pytest.mark.asyncio
async def test_get_page_success(mock_api, wiki_client):
    mock_api.get("/api/v1/pages/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Iran",
                "path": "Actors/Iran",
                "content": "# Iran\n\nContent here.",
                "frontmatter": {"category": "actor"},
                "links_to": [],
                "linked_from": [],
                "revision": "abc123",
                "last_commit": None,
            },
        )
    )
    result = await wiki_client.get_page("Actors/Iran")
    assert result["name"] == "Iran"
    assert result["path"] == "Actors/Iran"


@pytest.mark.asyncio
async def test_get_page_not_found(mock_api, wiki_client):
    mock_api.get("/api/v1/pages/Nonexistent").mock(
        return_value=httpx.Response(404, json={"error": "Page not found: Nonexistent"})
    )
    with pytest.raises(WikiAPIError) as exc_info:
        await wiki_client.get_page("Nonexistent")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_pages_with_filters(mock_api, wiki_client):
    route = mock_api.get("/api/v1/pages").mock(
        return_value=httpx.Response(200, json={"pages": [], "total": 0})
    )
    await wiki_client.list_pages(prefix="Actors/", category="actor")
    assert route.called
    req = route.calls[0].request
    assert b"prefix=Actors%2F" in req.url.raw_path or "prefix" in str(req.url)


@pytest.mark.asyncio
async def test_put_page_with_commit_message(mock_api, wiki_client):
    route = mock_api.put("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            201,
            json={
                "name": "Page",
                "path": "Test/Page",
                "revision": "def456",
                "created": True,
            },
        )
    )
    result = await wiki_client.put_page("Test/Page", "# Test", "Create test page")
    assert result["created"] is True
    # Verify [mcp] prefix was added
    req_body = route.calls[0].request.content
    assert b"[mcp] Create test page" in req_body


@pytest.mark.asyncio
async def test_put_page_without_commit_message(mock_api, wiki_client):
    route = mock_api.put("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Page",
                "path": "Test/Page",
                "revision": "def456",
                "created": False,
            },
        )
    )
    result = await wiki_client.put_page("Test/Page", "# Test")
    assert result["created"] is False
    # No commit_message in body when not provided
    req_body = route.calls[0].request.content
    assert b"commit_message" not in req_body


@pytest.mark.asyncio
async def test_delete_page_adds_mcp_prefix(mock_api, wiki_client):
    route = mock_api.delete("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            200, json={"deleted": True, "path": "Test/Page"}
        )
    )
    await wiki_client.delete_page("Test/Page")
    req_body = route.calls[0].request.content
    assert b"[mcp] Delete: Test/Page" in req_body


@pytest.mark.asyncio
async def test_delete_page_custom_commit_message(mock_api, wiki_client):
    route = mock_api.delete("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            200, json={"deleted": True, "path": "Test/Page"}
        )
    )
    await wiki_client.delete_page("Test/Page", "Custom reason")
    req_body = route.calls[0].request.content
    assert b"[mcp] Custom reason" in req_body


@pytest.mark.asyncio
async def test_search(mock_api, wiki_client):
    mock_api.get("/api/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "test",
                "results": [
                    {
                        "name": "Page",
                        "path": "Test/Page",
                        "snippet": "matched text",
                        "score": 0.9,
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await wiki_client.search("test")
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_semantic_search(mock_api, wiki_client):
    mock_api.get("/api/v1/semantic-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "concept",
                "results": [
                    {
                        "name": "Page",
                        "path": "Test/Page",
                        "snippet": "relevant text",
                        "distance": 0.35,
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await wiki_client.semantic_search("concept", n=3)
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_get_history(mock_api, wiki_client):
    mock_api.get("/api/v1/pages/Actors/Iran/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "Actors/Iran",
                "history": [
                    {"revision": "abc", "author": "admin", "date": "2026-03-08", "message": "edit"},
                ],
            },
        )
    )
    result = await wiki_client.get_history("Actors/Iran", limit=5)
    assert result["path"] == "Actors/Iran"
    assert len(result["history"]) == 1


@pytest.mark.asyncio
async def test_empty_response_body(mock_api, wiki_client):
    """G3: empty response body should return {} not crash on json()."""
    mock_api.delete("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(204)
    )
    result = await wiki_client.delete_page("Test/Page")
    assert result == {}


@pytest.mark.asyncio
async def test_auth_error(mock_api, wiki_client):
    mock_api.get("/api/v1/pages/Any").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    with pytest.raises(WikiAPIError) as exc_info:
        await wiki_client.get_page("Any")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_token_sent(mock_api, wiki_client):
    route = mock_api.get("/api/v1/pages").mock(
        return_value=httpx.Response(200, json={"pages": [], "total": 0})
    )
    await wiki_client.list_pages()
    auth_header = route.calls[0].request.headers["authorization"]
    assert auth_header == "Bearer test-api-key"


@pytest.mark.asyncio
async def test_non_json_success_raises_api_error(mock_api, wiki_client):
    """C1/G9: 200 with non-JSON body (e.g. HTML from proxy) raises WikiAPIError."""
    mock_api.get("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            200,
            content=b"<html><body>Gateway OK</body></html>",
            headers={"content-type": "text/html"},
        )
    )
    with pytest.raises(WikiAPIError) as exc_info:
        await wiki_client.get_page("Test/Page")
    assert exc_info.value.status_code == 200
    assert "Gateway OK" in exc_info.value.detail


# --- C5/Z4: Page path validation tests ---

METHODS_UNDER_TEST = [
    ("get_page", ("PLACEHOLDER",)),
    ("put_page", ("PLACEHOLDER", "content")),
    ("delete_page", ("PLACEHOLDER",)),
    ("rename_page", ("PLACEHOLDER", "valid/path")),
    ("get_history", ("PLACEHOLDER",)),
    ("get_links", ("PLACEHOLDER",)),
]


def _make_args(args_template, bad_path):
    """Replace PLACEHOLDER with the bad path value."""
    return tuple(bad_path if a == "PLACEHOLDER" else a for a in args_template)


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,args_template", METHODS_UNDER_TEST)
async def test_path_traversal_rejected(mock_api, wiki_client, method_name, args_template):
    """Paths containing '..' must be rejected."""
    with pytest.raises(ValueError, match="must not contain"):
        await getattr(wiki_client, method_name)(*_make_args(args_template, "../../admin"))


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,args_template", METHODS_UNDER_TEST)
async def test_path_leading_slash_rejected(mock_api, wiki_client, method_name, args_template):
    """Paths starting with '/' must be rejected."""
    with pytest.raises(ValueError, match="must not start with"):
        await getattr(wiki_client, method_name)(*_make_args(args_template, "/etc/passwd"))


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,args_template", METHODS_UNDER_TEST)
async def test_path_null_byte_rejected(mock_api, wiki_client, method_name, args_template):
    """Paths containing null bytes must be rejected."""
    with pytest.raises(ValueError, match="null bytes"):
        await getattr(wiki_client, method_name)(*_make_args(args_template, "page\x00evil"))


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,args_template", METHODS_UNDER_TEST)
async def test_path_empty_rejected(mock_api, wiki_client, method_name, args_template):
    """Empty paths must be rejected."""
    with pytest.raises(ValueError, match="must not be empty"):
        await getattr(wiki_client, method_name)(*_make_args(args_template, ""))


# --- rename_page new_path validation ---

@pytest.mark.asyncio
async def test_rename_page_validates_new_path_traversal(mock_api, wiki_client):
    with pytest.raises(ValueError, match="must not contain"):
        await wiki_client.rename_page("valid/path", "../../evil")


@pytest.mark.asyncio
async def test_rename_page_validates_new_path_empty(mock_api, wiki_client):
    with pytest.raises(ValueError, match="must not be empty"):
        await wiki_client.rename_page("valid/path", "")


@pytest.mark.asyncio
async def test_rename_page_sends_mcp_prefix(mock_api, wiki_client):
    route = mock_api.post("/api/v1/pages/Old/Page/rename").mock(
        return_value=httpx.Response(
            200,
            json={
                "old_path": "Old/Page",
                "new_path": "New/Page",
                "revision": "abc123",
                "updated_pages": [],
            },
        )
    )
    await wiki_client.rename_page("Old/Page", "New/Page", "Rename page")
    req_body = route.calls[0].request.content
    assert b"[mcp] Rename page" in req_body
    assert b"New/Page" in req_body
