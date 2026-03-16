"""MCP server exposing Otterwiki operations as tools over Streamable HTTP."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.auth import MultiAuth, StaticTokenVerifier
from mcp.server.auth.provider import AuthorizeError
from mcp.server.auth.settings import ClientRegistrationOptions
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from fastmcp.server.dependencies import get_http_request

from otterwiki_mcp.api_client import WikiAPIError, WikiClient, current_host_header
from otterwiki_mcp.config import get_config
from otterwiki_mcp.consent import derive_signing_key
from otterwiki_mcp.oauth_store import SQLiteOAuthProvider
from otterwiki_mcp import formatters
from otterwiki_mcp import sections

logger = logging.getLogger(__name__)

MAX_CONTENT_SIZE = 1_000_000  # 1MB
_MAX_INDEX_PAGES = 100


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """Close the WikiClient's httpx.AsyncClient on shutdown."""
    try:
        yield
    finally:
        await client.close()


# Created without auth; auth and lifespan are set in main() before run().
mcp = FastMCP("Otterwiki Research Wiki")

# Initialized in main(); tools reference via module-level variable.
client: WikiClient
oauth_provider: SQLiteOAuthProvider
platform_domain: str = "robot.wtf"


def _set_host_from_request() -> None:
    """Extract the wiki slug from the incoming HTTP Host header and set current_host_header.

    The incoming Host looks like ``{slug}.mcp.robot.wtf`` (via Caddy). We
    extract ``{slug}`` and construct ``{slug}.{platform_domain}`` for the
    upstream API call so that the TenantResolver routes to the right wiki.
    """
    try:
        request = get_http_request()
    except RuntimeError:
        return  # No HTTP request context (e.g. stdio transport) — nothing to do
    host = request.headers.get("host", "")
    if not host:
        return
    # Strip port if present
    hostname = host.split(":")[0]
    # Extract slug: everything before the first dot that isn't the platform domain itself
    # e.g. "dev.mcp.robot.wtf" → slug="dev", or "dev.robot.wtf" → slug="dev"
    parts = hostname.split(".")
    if len(parts) < 3:
        return  # No subdomain — can't determine wiki slug
    slug = parts[0]
    if not slug:
        return
    current_host_header.set(f"{slug}.{platform_domain}")


def _handle_api_error(e: WikiAPIError) -> str:
    """Map HTTP errors to actionable text for Claude."""
    match e.status_code:
        case 404:
            return (
                f"Page not found: {e.path}. "
                "Use write_note to create it, or list_notes to see available pages."
            )
        case 401:
            return "Authentication failed. The API key may be misconfigured."
        case 409:
            return (
                f"Conflict: {e.detail} "
                "Read the page again to get the current revision, then retry."
            )
        case 422:
            return f"Invalid request: {e.detail}"
        case code if code >= 500:
            return (
                f"Wiki API error ({code}): {e.detail or 'unknown'}. "
                "The server may be restarting. Try again in a few seconds."
            )
        case _:
            return f"Wiki API error ({e.status_code}): {e.detail or 'unknown'}"


# --- Tools ---


@mcp.tool()
async def read_note(path: str, revision: str = "", section: str = "") -> str:
    """Read a wiki page by path. Returns frontmatter, content, and WikiLinks.

    Args:
        path: Page path, e.g. "Actors/Iran"
        revision: Optional git revision SHA to read a historical version. Use get_history to find available revision SHAs.
        section: Optional section title or path (e.g. "Background" or "Background > Military Strategy") to return only that section's content.
    """
    _set_host_from_request()
    try:
        data = await client.get_page(path, revision=revision or None)
        if section:
            content = data.get("content", "")
            section_text, error_paths = sections.extract_section(content, section)
            if not section_text:
                if error_paths == ["(no sections found)"]:
                    return f"Section not found: '{section}'. This page has no sections."
                return (
                    f"Section not found: '{section}'. Available sections:\n"
                    + "\n".join(f"  - {p}" for p in error_paths)
                )
            data = dict(data)
            data["content"] = section_text
            data["_section"] = section
        return formatters.format_read_note(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def write_note(
    path: str, content: str, revision: str = "", commit_message: str = ""
) -> str:
    """Create or overwrite a wiki page. When updating an existing page, you must supply the revision SHA from read_note for optimistic locking. Omit revision to create a new page.

    Args:
        path: Page path, e.g. "Actors/Iran"
        content: Full page content (markdown with optional YAML frontmatter between --- delimiters).
        revision: Current revision SHA of the page (from read_note). Required when updating an existing page. Omit when creating a new page.
        commit_message: Optional commit message.
    """
    _set_host_from_request()
    if len(content) > MAX_CONTENT_SIZE:
        return f"Content too large ({len(content)} bytes). Maximum size is {MAX_CONTENT_SIZE} bytes."
    try:
        data = await client.put_page(path, content, commit_message or None, revision or None)
        return formatters.format_write_result(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def edit_note(
    path: str, revision: str, old_string: str, new_string: str, commit_message: str = ""
) -> str:
    """Edit a wiki page in place. Finds the single occurrence of old_string and replaces it with new_string. Requires the current revision SHA (from read_note) for optimistic locking — if the page was modified since you last read it, you'll get a conflict error and must re-read before retrying.

    Args:
        path: Page path, e.g. "Actors/Iran"
        revision: Current revision SHA of the page (from read_note). Can be full or short (7+ chars).
        old_string: Exact text to find (must appear exactly once in the page). Matches against full content including frontmatter.
        new_string: Replacement text. Use empty string to delete old_string.
        commit_message: Optional commit message.
    """
    _set_host_from_request()
    try:
        data = await client.patch_page(path, revision, old_string, new_string, commit_message or None)
        return formatters.format_edit_result(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def list_notes(
    prefix: str = "",
    category: str = "",
    tag: str = "",
    updated_since: str = "",
) -> str:
    """List wiki pages. All filters are optional and compose with AND logic.

    Args:
        prefix: Filter by path prefix, e.g. "Actors/" or "Events/"
        category: Filter by frontmatter category
        tag: Filter by frontmatter tag
        updated_since: ISO 8601 date, e.g. "2026-03-08"
    """
    _set_host_from_request()
    try:
        data = await client.list_pages(
            prefix=prefix, category=category, tag=tag, updated_since=updated_since
        )
        filters = {
            k: v
            for k, v in {
                "prefix": prefix,
                "category": category,
                "tag": tag,
                "updated_since": updated_since,
            }.items()
            if v
        }
        return formatters.format_list_notes(data, filters or None)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def search_notes(query: str) -> str:
    """Full-text keyword search across all wiki pages."""
    _set_host_from_request()
    try:
        data = await client.search(query)
        return formatters.format_search_results(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def semantic_search(query: str, n: int = 5, max_chunks_per_page: int = 2) -> str:
    """Semantic similarity search. Finds pages conceptually related to the query, even without exact keyword matches.

    Args:
        query: Natural language query describing what you're looking for
        n: Number of results to return (1-50, default 5)
        max_chunks_per_page: Maximum number of chunks to return per page (default 2)
    """
    _set_host_from_request()
    n = max(1, min(n, 50))
    try:
        data = await client.semantic_search(query, n=n, max_chunks_per_page=max_chunks_per_page)
        return formatters.format_semantic_results(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def get_links(path: str) -> str:
    """Get incoming and outgoing WikiLinks for a page."""
    _set_host_from_request()
    try:
        data = await client.get_links(path)
        return formatters.format_links(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def get_recent_changes(limit: int = 20) -> str:
    """Get recent changelog entries across all wiki pages.

    Args:
        limit: Maximum number of entries to return (default 20)
    """
    _set_host_from_request()
    limit = max(1, min(limit, 200))
    try:
        data = await client.get_changelog(limit=limit)
        return formatters.format_recent_changes(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def get_history(path: str, limit: int = 10) -> str:
    """Get revision history for a page. Use with read_note(revision=...) to view older versions.

    Args:
        path: Page path, e.g. "Actors/Iran"
        limit: Maximum number of revisions to return (default 10)
    """
    _set_host_from_request()
    limit = max(1, min(limit, 200))
    try:
        data = await client.get_history(path, limit=limit)
        return formatters.format_history(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def rename_note(path: str, new_path: str, commit_message: str = "") -> str:
    """Rename a wiki page and automatically update all backreferences (WikiLinks from other pages that point to this page). The rename and all link updates happen in a single atomic commit.

    Args:
        path: Current page path, e.g. "Actors/Iran"
        new_path: New page path, e.g. "Actors/Iran (Islamic Republic)"
        commit_message: Optional commit message.
    """
    _set_host_from_request()
    try:
        data = await client.rename_page(path, new_path, commit_message or None)
        return formatters.format_rename_result(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def delete_note(path: str, commit_message: str = "") -> str:
    """Delete a wiki page. Permanently deletes — content can only be recovered through git history. Confirm with the user before calling."""
    _set_host_from_request()
    try:
        data = await client.delete_page(path, commit_message or None)
        return formatters.format_delete_result(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def find_orphaned_notes() -> str:
    """Find wiki pages that no other page links to. Orphaned pages may be missing from the wiki's navigation structure."""
    _set_host_from_request()
    try:
        # Get all pages
        all_data = await client.list_pages()
        all_pages = all_data.get("pages", [])
        all_paths = [p["path"] for p in all_pages]

        # Fetch link data for all pages in parallel; skip failures
        results = await asyncio.gather(
            *(client.get_links(path) for path in all_paths),
            return_exceptions=True,
        )

        # A page is orphaned if no other page links to it (linked_from is empty)
        # Exception: "Home" is the root page and is not expected to have incoming links
        orphans = []
        for path, result in zip(all_paths, results):
            if isinstance(result, BaseException):
                logger.warning("Failed to fetch links for %s: %s", path, result)
                continue
            if path == "Home":
                continue
            linked_from = result.get("linked_from", [])
            if not linked_from:
                orphans.append(path)

        orphans.sort()
        return formatters.format_orphaned_notes(orphans)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


# --- Authorize callback ---


@mcp.custom_route("/authorize/callback", methods=["GET"])
async def authorize_callback(request: Request) -> Response:
    """Handle redirect from consent page after user approval.

    Verifies the approval token, issues an auth code, and redirects
    the OAuth client (e.g. Claude.ai) back to its redirect_uri.
    """
    params = request.query_params
    approval_token = params.get("approval_token", "")
    if not approval_token:
        return JSONResponse(
            {"error": "missing_token", "error_description": "approval_token is required"},
            status_code=400,
        )

    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")
    state = params.get("state", "")
    scope = params.get("scope", "")
    resource = params.get("resource") or None

    if not client_id or not redirect_uri or not code_challenge:
        return JSONResponse(
            {
                "error": "invalid_request",
                "error_description": "client_id, redirect_uri, and code_challenge are required",
            },
            status_code=400,
        )

    try:
        redirect_url = await oauth_provider.complete_authorization(
            approval_token=approval_token,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            state=state,
            scope=scope,
            resource=resource,
        )
    except AuthorizeError as e:
        logger.warning("Authorization callback failed: %s", e.error_description)
        return JSONResponse(
            {"error": e.error, "error_description": e.error_description},
            status_code=403,
        )

    return RedirectResponse(url=redirect_url, status_code=302)


# --- Entry point ---


def _load_signing_key(path: str) -> bytes:
    """Read the PEM file and derive the HMAC signing key."""
    try:
        with open(path) as f:
            pem_data = f.read()
        return derive_signing_key(pem_data)
    except FileNotFoundError:
        logger.warning("Signing key not found at %s — consent flow will fail", path)
        return b""
    except Exception:
        logger.exception("Failed to load signing key from %s", path)
        return b""


def main():
    global client, oauth_provider, platform_domain
    cfg = get_config()
    client = WikiClient(cfg.api_url, cfg.api_key)
    platform_domain = cfg.platform_domain
    mcp._lifespan = _lifespan

    signing_key = _load_signing_key(cfg.signing_key_path)

    oauth_provider = SQLiteOAuthProvider(
        cfg.mcp_oauth_db,
        base_url=cfg.mcp_base_url,
        consent_url=cfg.consent_url,
        signing_key=signing_key,
        client_registration_options=ClientRegistrationOptions(enabled=True),
    )
    verifiers = []
    if cfg.mcp_auth_token:
        verifiers.append(
            StaticTokenVerifier(
                tokens={cfg.mcp_auth_token: {"client_id": "claude-code", "scopes": []}}
            )
        )
    mcp.auth = MultiAuth(server=oauth_provider, verifiers=verifiers)

    mcp.run(transport="streamable-http", host="0.0.0.0", port=cfg.mcp_port, stateless_http=True)


if __name__ == "__main__":
    main()
