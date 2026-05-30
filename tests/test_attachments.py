"""Tests for attachment tools (list, upload, download, delete).

These tests exercise three layers:
  1. WikiClient methods (api_client.py) — HTTP-level behavior via respx
  2. Formatter functions (formatters.py) — dict-to-string rendering
  3. MCP tool functions (server.py) — end-to-end tool -> client -> formatter

All tests are expected to FAIL until the attachment methods, formatters, and
tools are implemented. They will raise ImportError or AttributeError.
"""

import base64

import pytest
import httpx
import respx

from otterwiki_mcp.api_client import WikiClient, WikiAPIError
from otterwiki_mcp import formatters
import otterwiki_mcp.server as server_mod


# ---------------------------------------------------------------------------
# 1. WikiClient attachment methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_attachments_success(mock_api, wiki_client):
    """list_attachments calls GET /api/v1/pages/{path}/attachments."""
    mock_api.get("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "Test/Page",
                "attachments": [
                    {
                        "filename": "report.pdf",
                        "size": 2048,
                        "mime_type": "application/pdf",
                        "last_modified": "2026-05-20T10:00:00",
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await wiki_client.list_attachments("Test/Page")
    assert result["total"] == 1
    assert result["attachments"][0]["filename"] == "report.pdf"


@pytest.mark.asyncio
async def test_list_attachments_empty(mock_api, wiki_client):
    """list_attachments returns empty list when page has no attachments."""
    mock_api.get("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "Test/Page",
                "attachments": [],
                "total": 0,
            },
        )
    )
    result = await wiki_client.list_attachments("Test/Page")
    assert result["total"] == 0
    assert result["attachments"] == []


@pytest.mark.asyncio
async def test_list_attachments_not_found(mock_api, wiki_client):
    """list_attachments raises WikiAPIError for nonexistent page."""
    mock_api.get("/api/v1/pages/Missing/Page/attachments").mock(
        return_value=httpx.Response(404, json={"error": "Page not found"})
    )
    with pytest.raises(WikiAPIError) as exc_info:
        await wiki_client.list_attachments("Missing/Page")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_upload_attachment_success(mock_api, wiki_client):
    """upload_attachment POSTs JSON with filename, content_b64, and optional commit_message."""
    route = mock_api.post("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            201,
            json={
                "filename": "photo.png",
                "path": "Test/Page",
                "size": 1024,
                "mime_type": "image/png",
            },
        )
    )
    content_b64 = base64.b64encode(b"fake-png-data").decode()
    result = await wiki_client.upload_attachment(
        "Test/Page", "photo.png", content_b64, commit_message="Add photo"
    )
    assert result["filename"] == "photo.png"
    assert result["size"] == 1024
    # Verify [mcp] prefix on commit message
    req_body = route.calls[0].request.content
    assert b"[mcp] Add photo" in req_body
    assert b"photo.png" in req_body
    assert content_b64.encode() in req_body


@pytest.mark.asyncio
async def test_upload_attachment_without_commit_message(mock_api, wiki_client):
    """upload_attachment works without a commit_message (no [mcp] prefix sent)."""
    route = mock_api.post("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            201,
            json={
                "filename": "data.csv",
                "path": "Test/Page",
                "size": 512,
                "mime_type": "text/csv",
            },
        )
    )
    content_b64 = base64.b64encode(b"a,b,c").decode()
    result = await wiki_client.upload_attachment("Test/Page", "data.csv", content_b64)
    assert result["filename"] == "data.csv"
    req_body = route.calls[0].request.content
    assert b"commit_message" not in req_body


@pytest.mark.asyncio
async def test_download_attachment_success(mock_api, wiki_client):
    """download_attachment calls GET with URL-encoded filename."""
    mock_api.get("/api/v1/pages/Test/Page/attachments/report.pdf").mock(
        return_value=httpx.Response(
            200,
            json={
                "filename": "report.pdf",
                "content": base64.b64encode(b"%PDF-fake-content").decode(),
                "size": 16,
                "mime_type": "application/pdf",
            },
        )
    )
    result = await wiki_client.download_attachment("Test/Page", "report.pdf")
    assert result["filename"] == "report.pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["size"] == 16


@pytest.mark.asyncio
async def test_download_attachment_url_encodes_filename(mock_api, wiki_client):
    """download_attachment URL-encodes filenames with special characters."""
    # Mock the URL-encoded path directly — verifies download_attachment encodes the filename
    route = mock_api.get("/api/v1/pages/Test/Page/attachments/file%20with%20spaces.pdf").mock(
        return_value=httpx.Response(
            200,
            json={
                "filename": "file with spaces.pdf",
                "content": base64.b64encode(b"content").decode(),
                "size": 7,
                "mime_type": "application/pdf",
            },
        )
    )
    result = await wiki_client.download_attachment("Test/Page", "file with spaces.pdf")
    assert result["filename"] == "file with spaces.pdf"


@pytest.mark.asyncio
async def test_download_attachment_not_found(mock_api, wiki_client):
    """download_attachment raises WikiAPIError for missing file."""
    mock_api.get("/api/v1/pages/Test/Page/attachments/missing.pdf").mock(
        return_value=httpx.Response(404, json={"error": "Attachment not found"})
    )
    with pytest.raises(WikiAPIError) as exc_info:
        await wiki_client.download_attachment("Test/Page", "missing.pdf")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_attachment_success(mock_api, wiki_client):
    """delete_attachment sends DELETE with JSON body containing filename."""
    route = mock_api.delete("/api/v1/pages/Test/Page/attachments/old_file.pdf").mock(
        return_value=httpx.Response(
            200,
            json={"deleted": True, "filename": "old_file.pdf"},
        )
    )
    result = await wiki_client.delete_attachment(
        "Test/Page", "old_file.pdf", commit_message="Remove outdated file"
    )
    assert result["deleted"] is True
    req_body = route.calls[0].request.content
    assert b"[mcp] Remove outdated file" in req_body


@pytest.mark.asyncio
async def test_delete_attachment_default_commit_message(mock_api, wiki_client):
    """delete_attachment uses a default commit message when none provided."""
    route = mock_api.delete("/api/v1/pages/Test/Page/attachments/old_file.pdf").mock(
        return_value=httpx.Response(
            200,
            json={"deleted": True, "filename": "old_file.pdf"},
        )
    )
    result = await wiki_client.delete_attachment("Test/Page", "old_file.pdf")
    assert result["deleted"] is True
    req_body = route.calls[0].request.content
    # Should have a default commit message with [mcp] prefix
    assert b"[mcp]" in req_body


@pytest.mark.asyncio
async def test_delete_attachment_not_found(mock_api, wiki_client):
    """delete_attachment raises WikiAPIError for missing file."""
    mock_api.delete("/api/v1/pages/Test/Page/attachments/missing.pdf").mock(
        return_value=httpx.Response(404, json={"error": "Attachment not found"})
    )
    with pytest.raises(WikiAPIError) as exc_info:
        await wiki_client.delete_attachment("Test/Page", "missing.pdf")
    assert exc_info.value.status_code == 404


# --- Path validation for attachment methods ---

ATTACHMENT_METHODS_UNDER_TEST = [
    ("list_attachments", ("PLACEHOLDER",)),
    ("upload_attachment", ("PLACEHOLDER", "file.txt", "dGVzdA==")),
    ("download_attachment", ("PLACEHOLDER", "file.txt")),
    ("delete_attachment", ("PLACEHOLDER", "file.txt")),
]


def _make_args(args_template, bad_path):
    """Replace PLACEHOLDER with the bad path value."""
    return tuple(bad_path if a == "PLACEHOLDER" else a for a in args_template)


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,args_template", ATTACHMENT_METHODS_UNDER_TEST)
async def test_attachment_path_traversal_rejected(
    mock_api, wiki_client, method_name, args_template
):
    """Paths containing '..' must be rejected by attachment methods."""
    with pytest.raises(ValueError, match="must not contain"):
        await getattr(wiki_client, method_name)(
            *_make_args(args_template, "../../admin")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name,args_template", ATTACHMENT_METHODS_UNDER_TEST)
async def test_attachment_path_empty_rejected(
    mock_api, wiki_client, method_name, args_template
):
    """Empty page paths must be rejected by attachment methods."""
    with pytest.raises(ValueError, match="must not be empty"):
        await getattr(wiki_client, method_name)(*_make_args(args_template, ""))


# ---------------------------------------------------------------------------
# 2. Formatter functions for attachments
# ---------------------------------------------------------------------------


def test_format_attachments_with_items():
    """format_attachments renders a list of attachments."""
    data = {
        "path": "Test/Page",
        "attachments": [
            {
                "filename": "report.pdf",
                "size": 2048,
                "mime_type": "application/pdf",
                "last_modified": "2026-05-20T10:00:00",
            },
            {
                "filename": "photo.png",
                "size": 1024,
                "mime_type": "image/png",
            },
        ],
        "total": 2,
    }
    result = formatters.format_attachments(data)
    assert "Test/Page" in result
    assert "2" in result
    assert "report.pdf" in result
    assert "photo.png" in result
    assert "application/pdf" in result
    assert "image/png" in result


def test_format_attachments_empty():
    """format_attachments renders an empty list."""
    data = {
        "path": "Test/Page",
        "attachments": [],
        "total": 0,
    }
    result = formatters.format_attachments(data)
    assert "Test/Page" in result
    assert "0" in result


def test_format_upload_attachment():
    """format_upload_attachment renders the upload confirmation."""
    data = {
        "filename": "photo.png",
        "path": "Test/Page",
        "size": 1024,
        "mime_type": "image/png",
    }
    result = formatters.format_upload_attachment(data)
    assert "photo.png" in result
    assert "Test/Page" in result
    assert "1024" in result


def test_format_download_attachment():
    """format_download_attachment renders download metadata."""
    data = {
        "filename": "report.pdf",
        "content": base64.b64encode(b"PDF data").decode(),
        "size": 8,
        "mime_type": "application/pdf",
    }
    result = formatters.format_download_attachment(data)
    assert "report.pdf" in result
    assert "application/pdf" in result
    assert "8" in result


def test_format_delete_attachment():
    """format_delete_attachment renders the deletion confirmation."""
    data = {
        "deleted": True,
        "filename": "old_file.pdf",
    }
    result = formatters.format_delete_attachment(data)
    assert "old_file.pdf" in result
    assert "deleted" in result.lower() or "Deleted" in result


# ---------------------------------------------------------------------------
# 3. MCP tool functions for attachments (server.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_client(wiki_client):
    """Inject the test wiki_client into the server module."""
    server_mod.client = wiki_client


@pytest.mark.asyncio
async def test_list_attachments_tool_success(mock_api):
    """list_attachments tool returns formatted attachment list."""
    mock_api.get("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            200,
            json={
                "path": "Test/Page",
                "attachments": [
                    {
                        "filename": "report.pdf",
                        "size": 2048,
                        "mime_type": "application/pdf",
                    }
                ],
                "total": 1,
            },
        )
    )
    result = await server_mod.list_attachments("Test/Page")
    assert "Test/Page" in result
    assert "report.pdf" in result


@pytest.mark.asyncio
async def test_list_attachments_tool_not_found(mock_api):
    """list_attachments tool handles 404 gracefully."""
    mock_api.get("/api/v1/pages/Missing/Page/attachments").mock(
        return_value=httpx.Response(404, json={"error": "Page not found"})
    )
    result = await server_mod.list_attachments("Missing/Page")
    assert "Page not found" in result


@pytest.mark.asyncio
async def test_upload_attachment_tool_success(mock_api):
    """upload_attachment tool sends content and returns formatted result."""
    mock_api.post("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            201,
            json={
                "filename": "photo.png",
                "path": "Test/Page",
                "size": 1024,
                "mime_type": "image/png",
            },
        )
    )
    content_b64 = base64.b64encode(b"fake-png").decode()
    result = await server_mod.upload_attachment(
        "Test/Page", "photo.png", content_b64, commit_message="Add photo"
    )
    assert "photo.png" in result
    assert "Test/Page" in result


@pytest.mark.asyncio
async def test_upload_attachment_tool_default_commit_message(mock_api):
    """upload_attachment tool uses empty commit_message by default."""
    route = mock_api.post("/api/v1/pages/Test/Page/attachments").mock(
        return_value=httpx.Response(
            201,
            json={
                "filename": "data.csv",
                "path": "Test/Page",
                "size": 10,
                "mime_type": "text/csv",
            },
        )
    )
    content_b64 = base64.b64encode(b"a,b,c\n").decode()
    result = await server_mod.upload_attachment("Test/Page", "data.csv", content_b64)
    assert "data.csv" in result


@pytest.mark.asyncio
async def test_download_attachment_tool_success(mock_api):
    """download_attachment tool returns formatted download metadata."""
    mock_api.get("/api/v1/pages/Test/Page/attachments/report.pdf").mock(
        return_value=httpx.Response(
            200,
            json={
                "filename": "report.pdf",
                "content": base64.b64encode(b"PDF content").decode(),
                "size": 11,
                "mime_type": "application/pdf",
            },
        )
    )
    result = await server_mod.download_attachment("Test/Page", "report.pdf")
    assert "report.pdf" in result
    assert "application/pdf" in result


@pytest.mark.asyncio
async def test_download_attachment_tool_not_found(mock_api):
    """download_attachment tool handles 404 gracefully."""
    mock_api.get("/api/v1/pages/Test/Page/attachments/missing.pdf").mock(
        return_value=httpx.Response(404, json={"error": "Attachment not found"})
    )
    result = await server_mod.download_attachment("Test/Page", "missing.pdf")
    assert "not found" in result.lower() or "404" in result


@pytest.mark.asyncio
async def test_delete_attachment_tool_success(mock_api):
    """delete_attachment tool returns formatted deletion confirmation."""
    mock_api.delete("/api/v1/pages/Test/Page/attachments/old_file.pdf").mock(
        return_value=httpx.Response(
            200,
            json={"deleted": True, "filename": "old_file.pdf"},
        )
    )
    result = await server_mod.delete_attachment("Test/Page", "old_file.pdf")
    assert "old_file.pdf" in result


@pytest.mark.asyncio
async def test_delete_attachment_tool_with_commit_message(mock_api):
    """delete_attachment tool passes commit_message through."""
    route = mock_api.delete("/api/v1/pages/Test/Page/attachments/old_file.pdf").mock(
        return_value=httpx.Response(
            200,
            json={"deleted": True, "filename": "old_file.pdf"},
        )
    )
    result = await server_mod.delete_attachment(
        "Test/Page", "old_file.pdf", commit_message="Cleanup old files"
    )
    assert "old_file.pdf" in result
    req_body = route.calls[0].request.content
    assert b"[mcp] Cleanup old files" in req_body


@pytest.mark.asyncio
async def test_delete_attachment_tool_not_found(mock_api):
    """delete_attachment tool handles 404 gracefully."""
    mock_api.delete("/api/v1/pages/Test/Page/attachments/missing.pdf").mock(
        return_value=httpx.Response(404, json={"error": "Attachment not found"})
    )
    result = await server_mod.delete_attachment("Test/Page", "missing.pdf")
    assert "not found" in result.lower() or "404" in result


@pytest.mark.asyncio
async def test_upload_attachment_tool_transport_error(mock_api):
    """upload_attachment tool catches transport errors and returns string."""
    mock_api.post("/api/v1/pages/Test/Page/attachments").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    result = await server_mod.upload_attachment(
        "Test/Page", "file.txt", base64.b64encode(b"data").decode()
    )
    assert isinstance(result, str)
    assert "Could not reach the wiki API" in result
