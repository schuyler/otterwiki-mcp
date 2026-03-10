"""MCP server exposing Otterwiki operations as tools over Streamable HTTP."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

from otterwiki_mcp.api_client import WikiAPIError, WikiClient
from otterwiki_mcp.config import Config
from otterwiki_mcp import formatters

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
                "Conflict: the page was modified since last read. "
                "Read the page again to get the current version, then retry."
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
async def read_note(path: str, revision: str = "") -> str:
    """Read a wiki page by path. Returns frontmatter, content, and WikiLinks.

    Args:
        path: Page path, e.g. "Actors/Iran"
        revision: Optional git revision SHA to read a historical version. Use get_history to find available revision SHAs.
    """
    try:
        data = await client.get_page(path, revision=revision or None)
        return formatters.format_read_note(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def write_note(
    path: str, content: str, commit_message: str = ""
) -> str:
    """Create or update a wiki page. Content should be markdown with optional YAML frontmatter between --- delimiters. Recognized frontmatter fields: category (actor|variable|trend|proposition|event|reference|index), tags (list of strings), confidence (low|medium|high), last_updated (YYYY-MM-DD)."""
    if len(content) > MAX_CONTENT_SIZE:
        return f"Content too large ({len(content)} bytes). Maximum size is {MAX_CONTENT_SIZE} bytes."
    try:
        data = await client.put_page(path, content, commit_message or None)
        return formatters.format_write_result(data)
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
        category: Filter by frontmatter category (actor, variable, trend, proposition, event, reference, index)
        tag: Filter by frontmatter tag
        updated_since: ISO 8601 date, e.g. "2026-03-08"
    """
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
    try:
        data = await client.search(query)
        return formatters.format_search_results(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def semantic_search(query: str, n: int = 5) -> str:
    """Semantic similarity search. Finds pages conceptually related to the query, even without exact keyword matches.

    Args:
        query: Natural language query describing what you're looking for
        n: Number of results to return (1-50, default 5)
    """
    n = max(1, min(n, 50))
    try:
        data = await client.semantic_search(query, n=n)
        return formatters.format_semantic_results(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def get_links(path: str) -> str:
    """Get incoming and outgoing WikiLinks for a page."""
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
    limit = max(1, min(limit, 200))
    try:
        data = await client.get_history(path, limit=limit)
        return formatters.format_history(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def delete_note(path: str, commit_message: str = "") -> str:
    """Delete a wiki page. Permanently deletes — content can only be recovered through git history. Confirm with the user before calling."""
    try:
        data = await client.delete_page(path, commit_message or None)
        return formatters.format_delete_result(data)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


@mcp.tool()
async def find_orphaned_notes() -> str:
    """Find wiki pages that are not linked from any index page. Orphaned pages may be missing from the wiki's navigation structure."""
    try:
        # Get all pages
        all_data = await client.list_pages()
        all_paths = {p["path"] for p in all_data.get("pages", [])}

        # Get index pages
        index_data = await client.list_pages(category="index")
        index_pages = index_data.get("pages", [])
        index_paths = {p["path"] for p in index_pages}

        if len(index_pages) > _MAX_INDEX_PAGES:
            return (
                f"Too many index pages ({len(index_pages)}). "
                f"Maximum supported is {_MAX_INDEX_PAGES}."
            )

        # Fetch all index pages in parallel; skip failures
        results = await asyncio.gather(
            *(client.get_page(p["path"]) for p in index_pages),
            return_exceptions=True,
        )

        linked_paths: set[str] = set()
        for idx_page, result in zip(index_pages, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Failed to fetch index page %s: %s",
                    idx_page["path"],
                    result,
                )
                continue
            linked_paths.update(result.get("links_to", []))

        # Orphans = all pages - linked pages - index pages themselves
        orphans = sorted(all_paths - linked_paths - index_paths)
        return formatters.format_orphaned_notes(orphans)
    except WikiAPIError as e:
        return _handle_api_error(e)
    except Exception as e:
        return f"Could not reach the wiki API: {e}"


# --- Entry point ---


def main():
    global client
    cfg = Config()
    cfg.validate()
    client = WikiClient(cfg.api_url, cfg.api_key)
    mcp._lifespan = _lifespan
    mcp.auth = StaticTokenVerifier(
        tokens={
            cfg.mcp_auth_token: {"client_id": "claude", "scopes": []},
        }
    )
    mcp.run(transport="streamable-http", host="0.0.0.0", port=cfg.mcp_port)


if __name__ == "__main__":
    main()
