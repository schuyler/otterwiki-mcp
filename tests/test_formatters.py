"""Tests for JSON → plain text formatters."""

from otterwiki_mcp.formatters import (
    format_read_note,
    format_list_notes,
    format_search_results,
    format_semantic_results,
    format_recent_changes,
    format_write_result,
    format_rename_result,
    format_delete_result,
    format_links,
    format_history,
    format_orphaned_notes,
)


def test_format_read_note_full():
    data = {
        "name": "Iran Attrition Strategy",
        "path": "Trends/Iran Attrition Strategy",
        "content": "---\ncategory: trend\n---\n\n# Iran Attrition Strategy\n\nContent.",
        "frontmatter": {
            "category": "trend",
            "tags": ["military", "p2-interceptor-race"],
            "confidence": "high",
            "last_updated": "2026-03-08",
        },
        "links_to": ["Variables/Interceptor Stockpiles", "Actors/Iran"],
        "linked_from": ["Actors/Iran"],
        "revision": "abc123",
        "last_commit": None,
    }
    result = format_read_note(data)
    assert "# Iran Attrition Strategy" in result
    assert "Path: Trends/Iran Attrition Strategy" in result
    assert "Revision: abc123" in result
    assert "Category: trend" in result
    assert "Tags: military, p2-interceptor-race" in result
    assert "Confidence: high" in result
    assert "Last Updated: 2026-03-08" in result
    assert "Links to: Variables/Interceptor Stockpiles, Actors/Iran" in result
    assert "Linked from: Actors/Iran" in result
    assert "---" in result
    assert "Content." in result


def test_format_read_note_no_frontmatter():
    data = {
        "name": "Simple Page",
        "path": "Simple Page",
        "content": "# Simple\n\nNo frontmatter.",
        "frontmatter": None,
        "links_to": [],
        "linked_from": [],
        "revision": "abc",
        "last_commit": None,
    }
    result = format_read_note(data)
    assert "# Simple Page" in result
    assert "Category" not in result
    assert "No frontmatter." in result


def test_format_list_notes_with_category_filter():
    data = {
        "pages": [
            {
                "name": "Iran",
                "path": "Actors/Iran",
                "category": "actor",
                "tags": ["military"],
                "last_updated": "2026-03-08",
                "content_length": 487,
            }
        ],
        "total": 1,
    }
    result = format_list_notes(data, {"category": "actor"})
    assert "Found 1 notes matching category=actor:" in result
    assert "Actors/Iran" in result
    assert "actor" in result
    assert "487 words" in result


def test_format_list_notes_no_filter():
    data = {"pages": [], "total": 0}
    result = format_list_notes(data)
    assert "Found 0 notes:" in result


def test_format_search_results():
    data = {
        "query": "ballistic missile",
        "results": [
            {
                "name": "Iran Strategy",
                "path": "Trends/Iran Attrition Strategy",
                "snippet": "...ballistic missile launch rates...",
                "score": 0.95,
            },
            {
                "name": "Missile Rationing",
                "path": "Propositions/Iran Rationing Ballistic Missiles",
                "snippet": "...rationing ballistic missiles...",
                "score": 0.72,
            },
        ],
        "total": 2,
    }
    result = format_search_results(data)
    assert '2 results for "ballistic missile":' in result
    assert "1. Trends/Iran Attrition Strategy (score: 0.95)" in result
    assert "   ...ballistic missile launch rates..." in result
    assert "2. Propositions/Iran Rationing Ballistic Missiles (score: 0.72)" in result


def test_format_semantic_results():
    data = {
        "query": "air defense depletion",
        "results": [
            {
                "name": "Strategy",
                "path": "Trends/Iran Attrition Strategy",
                "snippet": "multi-phase attrition campaign...",
                "distance": 0.34,
            }
        ],
        "total": 1,
    }
    result = format_semantic_results(data)
    assert '1 results for "air defense depletion":' in result
    assert "distance: 0.34" in result


def test_format_recent_changes():
    data = {
        "entries": [
            {
                "revision": "abc123",
                "author": "Claude (MCP)",
                "date": "2026-03-08T14:22:00",
                "message": "[mcp] Update: Actors/Iran",
                "pages_affected": ["Actors/Iran"],
            }
        ],
        "total": 1,
    }
    result = format_recent_changes(data)
    assert "1 recent changes:" in result
    assert "Claude (MCP)" in result
    assert "Actors/Iran" in result
    assert "[mcp] Update: Actors/Iran" in result


def test_format_write_result_created():
    data = {"name": "Page", "path": "Test/Page", "revision": "abcdef12", "created": True}
    result = format_write_result(data)
    assert result == "Created Test/Page (revision: abcdef12)"


def test_format_write_result_updated():
    data = {
        "name": "Page",
        "path": "Test/Page",
        "revision": "abcdef1234567890",
        "created": False,
    }
    result = format_write_result(data)
    assert result == "Updated Test/Page (revision: abcdef12)"


def test_format_rename_result_with_updates():
    data = {
        "old_path": "Actors/Iran",
        "new_path": "Actors/Iran (Islamic Republic)",
        "revision": "abcdef1234567890",
        "updated_pages": ["Events/Day 10", "Trends/Strategy"],
    }
    result = format_rename_result(data)
    assert "Renamed Actors/Iran -> Actors/Iran (Islamic Republic)" in result
    assert "abcdef12" in result
    assert "Updated 2 backreferences:" in result
    assert "  - Events/Day 10" in result
    assert "  - Trends/Strategy" in result


def test_format_rename_result_no_updates():
    data = {
        "old_path": "Old/Page",
        "new_path": "New/Page",
        "revision": "deadbeef12345678",
        "updated_pages": [],
    }
    result = format_rename_result(data)
    assert "Renamed Old/Page -> New/Page" in result
    assert "No backreferences needed updating." in result


def test_format_delete_result():
    data = {"deleted": True, "path": "Test/Page"}
    result = format_delete_result(data)
    assert result == "Deleted Test/Page"


def test_format_links():
    data = {
        "path": "Actors/Iran",
        "links_to": ["Trends/Iran Attrition Strategy"],
        "linked_from": ["Events/Day 10"],
    }
    result = format_links(data)
    assert "Links for Actors/Iran:" in result
    assert "Links to (1):" in result
    assert "  - Trends/Iran Attrition Strategy" in result
    assert "Linked from (1):" in result
    assert "  - Events/Day 10" in result


def test_format_links_empty():
    data = {"path": "Lonely/Page", "links_to": [], "linked_from": []}
    result = format_links(data)
    assert "(none)" in result


def test_format_history():
    data = {
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
    }
    result = format_history(data)
    assert "History for Actors/Iran (2 revisions):" in result
    assert "abc12345" in result
    assert "def67890" in result
    assert "Claude (MCP)" in result
    assert "Initial creation" in result


def test_format_history_empty():
    data = {"path": "Actors/Iran", "history": []}
    result = format_history(data)
    assert "No history for Actors/Iran." == result


def test_format_orphaned_notes():
    orphans = ["Draft/Note1", "Draft/Note2"]
    result = format_orphaned_notes(orphans)
    assert "Found 2 orphaned notes" in result
    assert "- Draft/Note1" in result
    assert "- Draft/Note2" in result


def test_format_orphaned_notes_none():
    result = format_orphaned_notes([])
    assert "No orphaned notes found" in result
    assert "incoming link" in result


def test_format_semantic_results_legacy_schema():
    """Existing schema (snippet only) still works without crashing."""
    data = {
        "query": "air defense depletion",
        "results": [
            {
                "name": "Strategy",
                "path": "Trends/Iran Attrition Strategy",
                "snippet": "multi-phase attrition campaign...",
                "distance": 0.34,
            }
        ],
        "total": 1,
    }
    result = format_semantic_results(data)
    assert "distance: 0.34" in result
    assert "multi-phase attrition campaign" in result


def test_format_semantic_results_new_fields_full():
    """New schema fields: text, section_path, chunk_index, total_chunks, page_word_count."""
    data = {
        "query": "air power",
        "results": [
            {
                "path": "Trends/Strategy",
                "distance": 0.25,
                "text": "Air power projection details here.",
                "section_path": "Background > Air Assets",
                "chunk_index": 0,
                "total_chunks": 3,
                "page_word_count": 1500,
            }
        ],
        "total": 1,
    }
    result = format_semantic_results(data)
    assert "[1/3]" in result
    assert "1500 words" in result
    assert "Section: Background > Air Assets" in result
    assert "Air power projection details here." in result


def test_format_semantic_results_text_preferred_over_snippet():
    """When both text and snippet are present, text wins."""
    data = {
        "query": "test",
        "results": [
            {
                "path": "Test/Page",
                "distance": 0.1,
                "text": "Text field content.",
                "snippet": "Snippet content.",
            }
        ],
        "total": 1,
    }
    result = format_semantic_results(data)
    assert "Text field content." in result
    assert "Snippet content." not in result


def test_format_semantic_results_no_section_path_omits_line():
    """When section_path is absent, no Section: line is emitted."""
    data = {
        "query": "test",
        "results": [
            {
                "path": "Test/Page",
                "distance": 0.1,
                "text": "Some text.",
            }
        ],
        "total": 1,
    }
    result = format_semantic_results(data)
    assert "Section:" not in result


def test_format_semantic_results_no_results():
    data = {"query": "foo", "results": [], "total": 0}
    result = format_semantic_results(data)
    assert result == '0 results for "foo":'
