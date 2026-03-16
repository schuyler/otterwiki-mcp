"""Integration tests for MCP tool functions (tool → client → formatter)."""

import pytest
import httpx
import respx

from otterwiki_mcp.api_client import WikiClient
import otterwiki_mcp.server as server_mod


@pytest.fixture(autouse=True)
def setup_client(wiki_client):
    """Inject the test wiki_client into the server module."""
    server_mod.client = wiki_client


@pytest.mark.asyncio
async def test_read_note_success(mock_api):
    mock_api.get("/api/v1/pages/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Iran",
                "path": "Actors/Iran",
                "content": "# Iran\n\nActor page.",
                "frontmatter": {"category": "actor", "tags": ["military"]},
                "links_to": ["Trends/Strategy"],
                "linked_from": [],
                "revision": "abc",
                "last_commit": None,
            },
        )
    )
    result = await server_mod.read_note("Actors/Iran")
    assert "# Iran" in result
    assert "Path: Actors/Iran" in result
    assert "Category: actor" in result


@pytest.mark.asyncio
async def test_read_note_not_found(mock_api):
    mock_api.get("/api/v1/pages/Missing/Page").mock(
        return_value=httpx.Response(404, json={"error": "Page not found"})
    )
    result = await server_mod.read_note("Missing/Page")
    assert "Page not found" in result
    assert "write_note" in result


@pytest.mark.asyncio
async def test_write_note_success(mock_api):
    mock_api.put("/api/v1/pages/Test/New").mock(
        return_value=httpx.Response(
            201,
            json={
                "name": "New",
                "path": "Test/New",
                "revision": "def456ab",
                "created": True,
            },
        )
    )
    result = await server_mod.write_note("Test/New", "# New\n\nContent.", commit_message="Create test")
    assert "Created Test/New" in result
    assert "def456ab" in result


@pytest.mark.asyncio
async def test_write_note_update_with_revision(mock_api):
    route = mock_api.put("/api/v1/pages/Test/Existing").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Existing",
                "path": "Test/Existing",
                "revision": "newrev456",
                "created": False,
            },
        )
    )
    result = await server_mod.write_note("Test/Existing", "# Updated\n\nNew content.", revision="oldrev123")
    assert "Updated Test/Existing" in result
    # Verify revision was sent in the request body
    req_body = route.calls[0].request.content
    assert b"oldrev123" in req_body


@pytest.mark.asyncio
async def test_write_note_update_conflict(mock_api):
    mock_api.put("/api/v1/pages/Test/Conflict").mock(
        return_value=httpx.Response(
            409,
            json={"error": "Revision mismatch", "current_revision": "abc123"},
        )
    )
    result = await server_mod.write_note("Test/Conflict", "content", revision="stale_rev")
    assert "Conflict" in result
    assert "Revision mismatch" in result
    assert "Read the page again" in result


@pytest.mark.asyncio
async def test_write_note_missing_revision_conflict(mock_api):
    mock_api.put("/api/v1/pages/Test/Existing").mock(
        return_value=httpx.Response(
            409,
            json={"error": "Revision required when updating an existing page."},
        )
    )
    result = await server_mod.write_note("Test/Existing", "content")
    assert "Conflict" in result
    assert "Revision required" in result


@pytest.mark.asyncio
async def test_edit_note_success(mock_api):
    mock_api.patch("/api/v1/pages/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Iran",
                "path": "Actors/Iran",
                "revision": "newrev12345abcde",
            },
        )
    )
    result = await server_mod.edit_note(
        "Actors/Iran", "oldrev99", "confidence: medium", "confidence: high", "Update confidence"
    )
    assert "Edited Actors/Iran" in result
    assert "newrev12" in result


@pytest.mark.asyncio
async def test_edit_note_conflict(mock_api):
    mock_api.patch("/api/v1/pages/Actors/Iran").mock(
        return_value=httpx.Response(
            409,
            json={"error": "Revision mismatch", "current_revision": "abc123"},
        )
    )
    result = await server_mod.edit_note(
        "Actors/Iran", "stale_rev", "old text", "new text"
    )
    assert "Conflict" in result
    assert "Revision mismatch" in result
    assert "Read the page again" in result


@pytest.mark.asyncio
async def test_edit_note_not_found(mock_api):
    mock_api.patch("/api/v1/pages/Missing/Page").mock(
        return_value=httpx.Response(404, json={"error": "Page not found"})
    )
    result = await server_mod.edit_note("Missing/Page", "rev", "old", "new")
    assert "Page not found" in result


@pytest.mark.asyncio
async def test_edit_note_ambiguous(mock_api):
    mock_api.patch("/api/v1/pages/Test/Page").mock(
        return_value=httpx.Response(
            422,
            json={"error": "old_string is ambiguous: found 3 occurrences"},
        )
    )
    result = await server_mod.edit_note("Test/Page", "rev", "foo", "bar")
    assert "ambiguous" in result


@pytest.mark.asyncio
async def test_list_notes_with_filters(mock_api):
    mock_api.get("/api/v1/pages").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {
                        "name": "Iran",
                        "path": "Actors/Iran",
                        "category": "actor",
                        "tags": [],
                        "last_updated": "2026-03-08",
                        "content_length": 400,
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await server_mod.list_notes(category="actor")
    assert "Found 1 notes matching category=actor:" in result
    assert "Actors/Iran" in result


@pytest.mark.asyncio
async def test_search_notes(mock_api):
    mock_api.get("/api/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "missile",
                "results": [
                    {
                        "name": "Strategy",
                        "path": "Trends/Strategy",
                        "snippet": "missile content",
                        "score": 0.8,
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await server_mod.search_notes("missile")
    assert '1 results for "missile":' in result


@pytest.mark.asyncio
async def test_semantic_search(mock_api):
    mock_api.get("/api/v1/semantic-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "air defense",
                "results": [
                    {
                        "name": "Strategy",
                        "path": "Trends/Strategy",
                        "snippet": "attrition campaign",
                        "distance": 0.4,
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await server_mod.semantic_search("air defense", n=3)
    assert "distance: 0.40" in result


@pytest.mark.asyncio
async def test_semantic_search_passes_max_chunks_per_page(mock_api):
    route = mock_api.get("/api/v1/semantic-search").mock(
        return_value=httpx.Response(
            200,
            json={
                "query": "air defense",
                "results": [],
                "total": 0,
            },
        )
    )
    await server_mod.semantic_search("air defense", n=3, max_chunks_per_page=1)
    req_url = str(route.calls[0].request.url)
    assert "max_chunks_per_page=1" in req_url


@pytest.mark.asyncio
async def test_rename_note_success(mock_api):
    mock_api.post("/api/v1/pages/Actors/Iran/rename").mock(
        return_value=httpx.Response(
            200,
            json={
                "old_path": "Actors/Iran",
                "new_path": "Actors/Iran (Islamic Republic)",
                "revision": "abc12345deadbeef",
                "updated_pages": ["Events/Day 10"],
            },
        )
    )
    result = await server_mod.rename_note(
        "Actors/Iran", "Actors/Iran (Islamic Republic)", "Rename with new name"
    )
    assert "Renamed Actors/Iran -> Actors/Iran (Islamic Republic)" in result
    assert "abc12345" in result
    assert "Updated 1 backreferences:" in result
    assert "Events/Day 10" in result


@pytest.mark.asyncio
async def test_rename_note_not_found(mock_api):
    mock_api.post("/api/v1/pages/Missing/Page/rename").mock(
        return_value=httpx.Response(404, json={"error": "Page not found: Missing/Page"})
    )
    result = await server_mod.rename_note("Missing/Page", "New/Path")
    assert "Page not found" in result


@pytest.mark.asyncio
async def test_rename_note_conflict(mock_api):
    mock_api.post("/api/v1/pages/Old/Page/rename").mock(
        return_value=httpx.Response(409, json={"error": "A page already exists at: New/Page"})
    )
    result = await server_mod.rename_note("Old/Page", "New/Page")
    assert "Conflict" in result


@pytest.mark.asyncio
async def test_delete_note_success(mock_api):
    mock_api.delete("/api/v1/pages/Test/Old").mock(
        return_value=httpx.Response(
            200, json={"deleted": True, "path": "Test/Old"}
        )
    )
    result = await server_mod.delete_note("Test/Old")
    assert result == "Deleted Test/Old"


@pytest.mark.asyncio
async def test_get_links(mock_api):
    mock_api.get("/api/v1/links/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "Actors/Iran",
                "links_to": ["Trends/Strategy"],
                "linked_from": ["Events/Day1"],
            },
        )
    )
    result = await server_mod.get_links("Actors/Iran")
    assert "Links for Actors/Iran:" in result
    assert "Trends/Strategy" in result
    assert "Events/Day1" in result


@pytest.mark.asyncio
async def test_get_recent_changes(mock_api):
    mock_api.get("/api/v1/changelog").mock(
        return_value=httpx.Response(
            200,
            json={
                "entries": [
                    {
                        "revision": "abc",
                        "author": "Claude (MCP)",
                        "date": "2026-03-08T14:00:00",
                        "message": "[mcp] Update: Actors/Iran",
                        "pages_affected": ["Actors/Iran"],
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await server_mod.get_recent_changes(limit=10)
    assert "1 recent changes:" in result
    assert "Claude (MCP)" in result


@pytest.mark.asyncio
async def test_find_orphaned_notes(mock_api):
    """Pages with no incoming links are orphaned; pages with incoming links are not."""
    mock_api.get("/api/v1/pages").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {"name": "Iran", "path": "Actors/Iran", "category": "actor",
                     "tags": [], "last_updated": "2026-03-08", "content_length": 100},
                    {"name": "Master", "path": "Index/Master", "category": "index",
                     "tags": [], "last_updated": "2026-03-08", "content_length": 50},
                    {"name": "Orphan", "path": "Draft/Orphan", "category": None,
                     "tags": [], "last_updated": "2026-03-08", "content_length": 30},
                ],
                "total": 3,
            },
        )
    )
    # Actors/Iran has an incoming link from Index/Master
    mock_api.get("/api/v1/links/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Actors/Iran", "links_to": [], "linked_from": ["Index/Master"]},
        )
    )
    # Index/Master has no incoming links (it's a root/nav page)
    mock_api.get("/api/v1/links/Index/Master").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Index/Master", "links_to": ["Actors/Iran"], "linked_from": []},
        )
    )
    # Draft/Orphan has no incoming links
    mock_api.get("/api/v1/links/Draft/Orphan").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Draft/Orphan", "links_to": [], "linked_from": []},
        )
    )
    result = await server_mod.find_orphaned_notes()
    assert "Found 2 orphaned notes" in result
    assert "- Draft/Orphan" in result
    assert "- Index/Master" in result
    assert "Actors/Iran" not in result.split("orphaned")[1]  # Iran is linked, not orphaned


@pytest.mark.asyncio
async def test_find_orphaned_notes_all_linked(mock_api):
    """When all pages have incoming links, none are orphaned."""
    mock_api.get("/api/v1/pages").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {"name": "Iran", "path": "Actors/Iran", "category": "actor",
                     "tags": [], "last_updated": "2026-03-08", "content_length": 100},
                    {"name": "Strategy", "path": "Trends/Strategy", "category": "trend",
                     "tags": [], "last_updated": "2026-03-08", "content_length": 200},
                ],
                "total": 2,
            },
        )
    )
    mock_api.get("/api/v1/links/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Actors/Iran", "links_to": [], "linked_from": ["Trends/Strategy"]},
        )
    )
    mock_api.get("/api/v1/links/Trends/Strategy").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Trends/Strategy", "links_to": ["Actors/Iran"], "linked_from": ["Actors/Iran"]},
        )
    )
    result = await server_mod.find_orphaned_notes()
    assert "No orphaned notes found" in result


@pytest.mark.asyncio
async def test_find_orphaned_notes_partial_link_failure(mock_api):
    """One failing get_links call should not abort the whole operation."""
    mock_api.get("/api/v1/pages").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": [
                    {"name": "Iran", "path": "Actors/Iran", "category": "actor",
                     "tags": [], "last_updated": "2026-03-08", "content_length": 100},
                    {"name": "Broken", "path": "Index/Broken", "category": "index",
                     "tags": [], "last_updated": "2026-03-08", "content_length": 50},
                    {"name": "Orphan", "path": "Draft/Orphan", "category": None,
                     "tags": [], "last_updated": "2026-03-08", "content_length": 30},
                ],
                "total": 3,
            },
        )
    )
    mock_api.get("/api/v1/links/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Actors/Iran", "links_to": [], "linked_from": ["Index/Broken"]},
        )
    )
    # Index/Broken links endpoint returns 500
    mock_api.get("/api/v1/links/Index/Broken").mock(
        return_value=httpx.Response(500, json={"error": "Internal server error"})
    )
    mock_api.get("/api/v1/links/Draft/Orphan").mock(
        return_value=httpx.Response(
            200,
            json={"path": "Draft/Orphan", "links_to": [], "linked_from": []},
        )
    )
    result = await server_mod.find_orphaned_notes()
    # Should not crash — Draft/Orphan has no incoming links
    assert "orphaned" in result
    assert "Draft/Orphan" in result


@pytest.mark.asyncio
async def test_error_auth_failure(mock_api):
    mock_api.get("/api/v1/pages/Any").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    result = await server_mod.read_note("Any")
    assert "Authentication failed" in result


@pytest.mark.asyncio
async def test_error_server_500(mock_api):
    mock_api.get("/api/v1/pages/Any").mock(
        return_value=httpx.Response(500, json={"error": "Internal server error"})
    )
    result = await server_mod.read_note("Any")
    assert "500" in result
    assert "Internal server error" in result


@pytest.mark.asyncio
async def test_error_unknown_4xx(mock_api):
    mock_api.get("/api/v1/pages/Any").mock(
        return_value=httpx.Response(403, json={"error": "Forbidden"})
    )
    result = await server_mod.read_note("Any")
    assert "403" in result
    assert "Forbidden" in result


@pytest.mark.asyncio
async def test_get_history_success(mock_api):
    mock_api.get("/api/v1/pages/Actors/Iran/history").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "Actors/Iran",
                "history": [
                    {
                        "revision": "abc12345deadbeef",
                        "author": "Claude (MCP)",
                        "date": "2026-03-08T14:00:00",
                        "message": "[mcp] Update: Actors/Iran",
                    },
                    {
                        "revision": "def67890cafebabe",
                        "author": "admin",
                        "date": "2026-03-07T10:00:00",
                        "message": "Initial creation",
                    },
                ],
            },
        )
    )
    result = await server_mod.get_history("Actors/Iran", limit=5)
    assert "History for Actors/Iran (2 revisions)" in result
    assert "abc12345" in result
    assert "Claude (MCP)" in result
    assert "Initial creation" in result


@pytest.mark.asyncio
async def test_get_history_not_found(mock_api):
    mock_api.get("/api/v1/pages/Missing/Page/history").mock(
        return_value=httpx.Response(404, json={"error": "Page not found"})
    )
    result = await server_mod.get_history("Missing/Page")
    assert "Page not found" in result


@pytest.mark.asyncio
async def test_read_note_with_revision(mock_api):
    route = mock_api.get("/api/v1/pages/Actors/Iran").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Iran",
                "path": "Actors/Iran",
                "content": "# Iran\n\nOld content.",
                "frontmatter": None,
                "links_to": [],
                "linked_from": [],
                "revision": "abc12345",
                "last_commit": None,
            },
        )
    )
    result = await server_mod.read_note("Actors/Iran", revision="abc12345")
    assert "Old content." in result
    # Verify revision param was sent
    req = route.calls[0].request
    assert "revision=abc12345" in str(req.url)


@pytest.mark.asyncio
async def test_transport_error_returns_string(mock_api):
    """httpx transport errors (ConnectError, timeout, etc.) are caught and returned as strings."""
    mock_api.get("/api/v1/pages/Any").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    result = await server_mod.read_note("Any")
    assert isinstance(result, str)
    assert "Could not reach the wiki API" in result


_SECTIONED_PAGE = {
    "name": "History",
    "path": "Topics/History",
    "content": (
        "# History\n\nIntro.\n\n"
        "## Background\n\nBackground content.\n\n"
        "## Other\n\nOther content.\n"
    ),
    "frontmatter": None,
    "links_to": [],
    "linked_from": [],
    "revision": "abc123",
    "last_commit": None,
}


@pytest.mark.asyncio
async def test_read_note_section_found(mock_api):
    mock_api.get("/api/v1/pages/Topics/History").mock(
        return_value=httpx.Response(200, json=_SECTIONED_PAGE)
    )
    result = await server_mod.read_note("Topics/History", section="Background")
    assert "Background content." in result
    assert "## Other" not in result
    assert "Section: History > Background" in result


@pytest.mark.asyncio
async def test_read_note_section_not_found(mock_api):
    mock_api.get("/api/v1/pages/Topics/History").mock(
        return_value=httpx.Response(200, json=_SECTIONED_PAGE)
    )
    result = await server_mod.read_note("Topics/History", section="Nonexistent")
    assert "Section not found" in result
    assert "Background" in result


@pytest.mark.asyncio
async def test_read_note_section_empty_returns_full(mock_api):
    mock_api.get("/api/v1/pages/Topics/History").mock(
        return_value=httpx.Response(200, json=_SECTIONED_PAGE)
    )
    result = await server_mod.read_note("Topics/History", section="")
    assert "Background content." in result
    assert "Other content." in result


@pytest.mark.asyncio
async def test_read_note_section_no_headings(mock_api):
    page = dict(_SECTIONED_PAGE, content="Just plain text without any headings.")
    mock_api.get("/api/v1/pages/Topics/History").mock(
        return_value=httpx.Response(200, json=page)
    )
    result = await server_mod.read_note("Topics/History", section="Anything")
    assert "no sections" in result.lower()


@pytest.mark.asyncio
async def test_read_note_section_ambiguous(mock_api):
    page = dict(
        _SECTIONED_PAGE,
        content=(
            "# Part One\n\n## Summary\n\nFirst summary.\n\n"
            "# Part Two\n\n## Summary\n\nSecond summary.\n"
        ),
    )
    mock_api.get("/api/v1/pages/Topics/History").mock(
        return_value=httpx.Response(200, json=page)
    )
    result = await server_mod.read_note("Topics/History", section="Summary")
    assert "Section not found" in result
    assert "Part One > Summary" in result
    assert "Part Two > Summary" in result


@pytest.mark.asyncio
async def test_read_note_section_clears_links(mock_api):
    """When a section is extracted, links_to and linked_from should be absent."""
    page = dict(
        _SECTIONED_PAGE,
        links_to=["Other/Page"],
        linked_from=["Index/Main"],
    )
    mock_api.get("/api/v1/pages/Topics/History").mock(
        return_value=httpx.Response(200, json=page)
    )
    result = await server_mod.read_note("Topics/History", section="Background")
    assert "Background content." in result
    assert "Other/Page" not in result
    assert "Index/Main" not in result


@pytest.mark.asyncio
async def test_semantic_search_max_chunks_clamped(mock_api):
    """max_chunks_per_page above 10 should be clamped to 10."""
    route = mock_api.get("/api/v1/semantic-search").mock(
        return_value=httpx.Response(
            200,
            json={"query": "test", "results": [], "total": 0},
        )
    )
    await server_mod.semantic_search("test", n=5, max_chunks_per_page=99)
    req_url = str(route.calls[0].request.url)
    assert "max_chunks_per_page=10" in req_url


@pytest.mark.asyncio
async def test_semantic_search_max_chunks_clamped_min(mock_api):
    """max_chunks_per_page below 1 should be clamped to 1."""
    route = mock_api.get("/api/v1/semantic-search").mock(
        return_value=httpx.Response(
            200,
            json={"query": "test", "results": [], "total": 0},
        )
    )
    await server_mod.semantic_search("test", n=5, max_chunks_per_page=0)
    req_url = str(route.calls[0].request.url)
    assert "max_chunks_per_page=1" in req_url
