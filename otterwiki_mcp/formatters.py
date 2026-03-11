"""JSON → plain text formatting for MCP tool responses.

Each function takes the parsed API JSON dict and returns a string
suitable for Claude.ai consumption. Formats match the PRD examples.
"""


def format_read_note(data: dict) -> str:
    """Format a page response for the read_note tool."""
    lines = [f"# {data.get('name', '')}", f"Path: {data.get('path', '')}"]

    fm = data.get("frontmatter")
    if fm:
        parts = []
        if fm.get("category"):
            parts.append(f"Category: {fm.get('category', '')}")
        tags = fm.get("tags")
        if tags:
            if isinstance(tags, list):
                tags = ", ".join(tags)
            parts.append(f"Tags: {tags}")
        if parts:
            lines.append(" | ".join(parts))

        meta_parts = []
        if fm.get("confidence"):
            meta_parts.append(f"Confidence: {fm.get('confidence', '')}")
        if fm.get("last_updated"):
            meta_parts.append(f"Last updated: {fm.get('last_updated', '')}")
        if meta_parts:
            lines.append(" | ".join(meta_parts))

    links_to = data.get("links_to", [])
    linked_from = data.get("linked_from", [])
    if links_to:
        lines.append(f"Links to: {', '.join(links_to)}")
    if linked_from:
        lines.append(f"Linked from: {', '.join(linked_from)}")

    lines.append("")
    lines.append("---")
    lines.append(data.get("content", ""))

    return "\n".join(lines)


def format_list_notes(data: dict, filters: dict | None = None) -> str:
    """Format a page list response for the list_notes tool."""
    total = data.get("total", 0)
    pages = data.get("pages", [])

    # Build filter description
    filter_parts = []
    if filters:
        if filters.get("prefix"):
            filter_parts.append(f"prefix={filters.get('prefix', '')}")
        if filters.get("category"):
            filter_parts.append(f"category={filters.get('category', '')}")
        if filters.get("tag"):
            filter_parts.append(f"tag={filters.get('tag', '')}")
        if filters.get("updated_since"):
            filter_parts.append(f"updated since {filters.get('updated_since', '')}")

    if filter_parts:
        header = f"Found {total} notes matching {', '.join(filter_parts)}:"
    else:
        header = f"Found {total} notes:"

    if not pages:
        return header

    lines = [header, ""]
    for p in pages:
        cat = p.get("category") or "uncategorized"
        words = p.get("content_length", 0)
        updated = p.get("last_updated") or "unknown"
        lines.append(f"- {p.get('path', '')} ({cat}, {words} words, updated {updated})")

    return "\n".join(lines)


def format_search_results(data: dict) -> str:
    """Format full-text search results for the search_notes tool."""
    query = data.get("query", "")
    results = data.get("results", [])
    total = data.get("total", 0)

    header = f'{total} results for "{query}":'
    if not results:
        return header

    lines = [header, ""]
    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        lines.append(f"{i}. {r.get('path', '')} (score: {score:.2f})")
        snippet = r.get("snippet", "")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_semantic_results(data: dict) -> str:
    """Format semantic search results for the semantic_search tool."""
    query = data.get("query", "")
    results = data.get("results", [])
    total = data.get("total", 0)

    header = f'{total} results for "{query}":'
    if not results:
        return header

    lines = [header, ""]
    for i, r in enumerate(results, 1):
        distance = r.get("distance", 0)
        lines.append(f"{i}. {r.get('path', '')} (distance: {distance:.2f})")
        snippet = r.get("snippet", "")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")

    return "\n".join(lines).rstrip()


def format_recent_changes(data: dict) -> str:
    """Format changelog entries for the get_recent_changes tool."""
    entries = data.get("entries", [])
    total = data.get("total", 0)

    header = f"{total} recent changes:"
    if not entries:
        return header

    lines = [header, ""]
    for e in entries:
        date = e.get("date", "unknown")
        author = e.get("author", "unknown")
        pages = ", ".join(e.get("pages_affected", []))
        lines.append(f"- {date} | {author} | {pages}")
        msg = e.get("message", "")
        if msg:
            lines.append(f"  {msg}")

    return "\n".join(lines)


def format_write_result(data: dict) -> str:
    """Format a page write response for the write_note tool."""
    action = "Created" if data.get("created") else "Updated"
    rev = data.get("revision", "")[:8]
    return f"{action} {data.get('path', '')} (revision: {rev})"


def format_edit_result(data: dict) -> str:
    """Format a page edit response for the edit_note tool."""
    rev = data.get("revision", "")[:8]
    return f"Edited {data.get('path', '')} (revision: {rev})"


def format_rename_result(data: dict) -> str:
    """Format a page rename response for the rename_note tool."""
    old = data.get("old_path", "")
    new = data.get("new_path", "")
    rev = data.get("revision", "")[:8]
    updated = data.get("updated_pages", [])

    lines = [f"Renamed {old} -> {new} (revision: {rev})"]
    if updated:
        lines.append(f"Updated {len(updated)} backreferences:")
        for p in updated:
            lines.append(f"  - {p}")
    else:
        lines.append("No backreferences needed updating.")
    return "\n".join(lines)


def format_delete_result(data: dict) -> str:
    """Format a page delete response for the delete_note tool."""
    return f"Deleted {data.get('path', '')}"


def format_links(data: dict) -> str:
    """Format link data for the get_links tool."""
    path = data.get("path", "")
    links_to = data.get("links_to", [])
    linked_from = data.get("linked_from", [])

    lines = [f"Links for {path}:", ""]
    lines.append(f"Links to ({len(links_to)}):")
    if links_to:
        for link in links_to:
            lines.append(f"  - {link}")
    else:
        lines.append("  (none)")

    lines.append(f"Linked from ({len(linked_from)}):")
    if linked_from:
        for link in linked_from:
            lines.append(f"  - {link}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def format_history(data: dict) -> str:
    """Format page history for the get_history tool."""
    path = data.get("path", "")
    history = data.get("history", [])

    if not history:
        return f"No history for {path}."

    lines = [f"History for {path} ({len(history)} revisions):", ""]
    for entry in history:
        rev = entry.get("revision", "")[:8]
        date = entry.get("date", "unknown")
        author = entry.get("author", "unknown")
        msg = entry.get("message", "")
        lines.append(f"- {rev} | {date} | {author}")
        if msg:
            lines.append(f"  {msg}")

    return "\n".join(lines)


def format_orphaned_notes(orphans: list[str]) -> str:
    """Format orphaned notes list for the find_orphaned_notes tool."""
    n = len(orphans)
    if n == 0:
        return "No orphaned notes found. All pages are linked from an index page."

    lines = [f"Found {n} orphaned notes (not linked from any index page):", ""]
    for path in orphans:
        lines.append(f"- {path}")

    return "\n".join(lines)
