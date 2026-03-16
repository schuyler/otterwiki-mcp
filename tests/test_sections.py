"""Tests for the section parser module."""

import pytest
from otterwiki_mcp.sections import list_sections, extract_section


class TestListSections:
    def test_list_sections_empty_doc(self):
        assert list_sections("") == []

    def test_list_sections_no_headings(self):
        assert list_sections("Just some plain text with no headings.\n\nAnother paragraph.") == []

    def test_list_sections_flat(self):
        content = "# H1\n\n## Section A\n\n## Section B\n"
        assert list_sections(content) == ["H1", "H1 > Section A", "H1 > Section B"]

    def test_list_sections_nested(self):
        content = "# Top\n\n## Sub A\n\n### Deep A1\n\n### Deep A2\n\n## Sub B\n"
        assert list_sections(content) == [
            "Top",
            "Top > Sub A",
            "Top > Sub A > Deep A1",
            "Top > Sub A > Deep A2",
            "Top > Sub B",
        ]

    def test_list_sections_heading_in_fenced_code_block_ignored(self):
        content = "# Real Heading\n\n```\n# Fake Heading\n## Also Fake\n```\n\n## Real Sub\n"
        assert list_sections(content) == ["Real Heading", "Real Heading > Real Sub"]

    def test_list_sections_only_h2_h3(self):
        content = "## Alpha\n\n### Alpha One\n\n## Beta\n"
        assert list_sections(content) == ["Alpha", "Alpha > Alpha One", "Beta"]


class TestExtractSection:
    def _doc(self):
        return (
            "# Introduction\n\nIntro content.\n\n"
            "## Background\n\nBackground content.\n\n"
            "### Military Strategy\n\nStrategy details.\n\n"
            "## Other\n\nOther content.\n"
        )

    def test_extract_section_exact_title_match(self):
        text, errors, _ = extract_section(self._doc(), "Background")
        assert errors == []
        assert "Background content." in text
        assert "## Background" in text

    def test_extract_section_includes_subsections(self):
        text, errors, _ = extract_section(self._doc(), "Background")
        assert errors == []
        assert "Strategy details." in text
        assert "### Military Strategy" in text
        assert "Other content." not in text

    def test_extract_section_path_match(self):
        text, errors, _ = extract_section(self._doc(), "Background > Military Strategy")
        assert errors == []
        assert "Strategy details." in text
        assert "Background content." not in text

    def test_extract_section_case_insensitive_path(self):
        text, errors, _ = extract_section(self._doc(), "background > military strategy")
        assert errors == []
        assert "Strategy details." in text

    def test_extract_section_case_insensitive_title(self):
        text, errors, _ = extract_section(self._doc(), "background")
        assert errors == []
        assert "Background content." in text

    def test_extract_section_no_match_returns_available(self):
        text, errors, _ = extract_section(self._doc(), "Nonexistent")
        assert text == ""
        assert len(errors) > 0
        assert any("Background" in e for e in errors)

    def test_extract_section_ambiguous_title_returns_paths(self):
        content = (
            "# Part One\n\n## Summary\n\nFirst summary.\n\n"
            "# Part Two\n\n## Summary\n\nSecond summary.\n"
        )
        text, errors, _ = extract_section(content, "Summary")
        assert text == ""
        assert len(errors) == 2
        assert any("Part One > Summary" in e for e in errors)
        assert any("Part Two > Summary" in e for e in errors)

    def test_extract_section_empty_query_returns_full_content(self):
        doc = self._doc()
        text, errors, _ = extract_section(doc, "")
        assert text == doc
        assert errors == []

    def test_extract_section_no_headings_returns_error(self):
        text, errors, _ = extract_section("Just plain text.", "Anything")
        assert text == ""
        assert errors == ["(no sections found)"]

    def test_extract_section_heading_in_code_block_not_matched(self):
        content = "# Real\n\nReal content.\n\n```\n## Fake\n\nFake content.\n```\n"
        text, errors, _ = extract_section(content, "Fake")
        assert text == ""
        assert errors == ["Real"]

    def test_extract_section_path_takes_priority_over_title(self):
        # "Background" appears as both a title-only match AND as part of
        # "Introduction > Background". Path query should prefer exact path.
        content = (
            "# Introduction\n\n## Background\n\nFirst background.\n\n"
            "# Background\n\nStandalone background.\n"
        )
        # Query by full path: should find the nested one
        text, errors, _ = extract_section(content, "Introduction > Background")
        assert errors == []
        assert "First background." in text
        assert "Standalone background." not in text

    def test_extract_section_last_section_no_trailing_heading(self):
        content = "# First\n\nFirst content.\n\n## Last\n\nLast content here.\n"
        text, errors, _ = extract_section(content, "Last")
        assert errors == []
        assert "Last content here." in text
        # Should not be cut off before end of doc
        assert text.strip().endswith("Last content here.")

    def test_extract_section_returns_canonical_path(self):
        """extract_section must return the matched heading's canonical path as third element."""
        doc = (
            "# History\n\nIntro.\n\n"
            "## Background\n\nBackground content.\n\n"
        )
        result = extract_section(doc, "background")
        assert len(result) == 3
        text, errors, matched_path = result
        assert errors == []
        assert matched_path == "History > Background"

    def test_extract_section_empty_query_matched_path_is_none(self):
        doc = "# Title\n\nContent.\n"
        text, errors, matched_path = extract_section(doc, "")
        assert text == doc
        assert errors == []
        assert matched_path is None

    def test_extract_section_failure_matched_path_is_none(self):
        doc = "# Title\n\nContent.\n"
        text, errors, matched_path = extract_section(doc, "Nonexistent")
        assert text == ""
        assert len(errors) > 0
        assert matched_path is None


class TestTildeFences:
    def test_list_sections_heading_in_tilde_fence_ignored(self):
        content = "# Real Heading\n\n~~~\n# Fake Heading\n## Also Fake\n~~~\n\n## Real Sub\n"
        assert list_sections(content) == ["Real Heading", "Real Heading > Real Sub"]

    def test_extract_section_heading_in_tilde_fence_not_matched(self):
        content = "# Real\n\nReal content.\n\n~~~\n## Fake\n\nFake content.\n~~~\n"
        text, errors, matched_path = extract_section(content, "Fake")
        assert text == ""
        assert errors == ["Real"]
        assert matched_path is None


class TestFenceCountMismatch:
    def test_four_backtick_fence_not_closed_by_three(self):
        """A 4-backtick opening fence must not be closed by a 3-backtick line."""
        content = (
            "# Real Heading\n\n"
            "````\n"
            "## Fake Inside Four-tick\n"
            "```\n"           # This 3-tick line should NOT close the 4-tick fence
            "## Still Fake\n"
            "````\n"          # This closes the 4-tick fence
            "\n## Real Sub\n"
        )
        result = list_sections(content)
        assert result == ["Real Heading", "Real Heading > Real Sub"]

    def test_three_backtick_fence_closed_by_three(self):
        """A 3-backtick fence is correctly closed by a 3-backtick line."""
        content = "# Real\n\n```\n## Fake\n```\n\n## Real Sub\n"
        assert list_sections(content) == ["Real", "Real > Real Sub"]


class TestClosedHeadings:
    def test_atx_closed_heading_strips_trailing_hashes(self):
        """Closed ATX headings like '## Title ##' should capture just 'Title'."""
        content = "## Title ##\n\nContent.\n"
        assert list_sections(content) == ["Title"]

    def test_atx_closed_heading_with_spaces(self):
        """Closed ATX headings like '## Title  ##' should capture just 'Title'."""
        content = "# Outer\n\n## Inner Section  ##\n\nContent.\n"
        assert list_sections(content) == ["Outer", "Outer > Inner Section"]

    def test_extract_section_closed_heading(self):
        content = "## Title ##\n\nSome content here.\n"
        text, errors, matched_path = extract_section(content, "Title")
        assert errors == []
        assert "Some content here." in text
        assert matched_path == "Title"
