"""Section-level parser for wiki page content.

Provides list_sections() and extract_section() for reading sub-sections
of markdown documents without fetching an entire page.
"""

import dataclasses
import re


@dataclasses.dataclass
class _Heading:
    level: int       # 1-6
    title: str       # heading text
    path: str        # full " > "-joined path
    line_index: int  # index into lines list


def _parse_headings(content: str) -> list[_Heading]:
    """Parse markdown headings, ignoring those inside fenced code blocks."""
    lines = content.splitlines(keepends=True)
    headings: list[_Heading] = []
    in_fence = False
    fence_char: str = ""
    fence_count: int = 0
    stack: list[tuple[int, str]] = []  # [(level, title), ...]

    for i, line in enumerate(lines):
        # Toggle fence state
        m_fence = re.match(r'^\s*(`{3,}|~{3,})', line)
        if m_fence:
            if not in_fence:
                # Opening fence: record character and count
                fence_str = m_fence.group(1)
                fence_char = fence_str[0]
                fence_count = len(fence_str)
                in_fence = True
            else:
                # Closing fence: must use same character with >= count
                fence_str = m_fence.group(1)
                if fence_str[0] == fence_char and len(fence_str) >= fence_count:
                    in_fence = False
                    fence_char = ""
                    fence_count = 0
            continue

        if in_fence:
            continue

        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if not m:
            continue

        level = len(m.group(1))
        title = m.group(2).strip().rstrip('#').strip()

        # Pop stack entries at same or deeper level
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))

        path = " > ".join(t for _, t in stack)
        headings.append(_Heading(level=level, title=title, path=path, line_index=i))

    return headings


def list_sections(content: str) -> list[str]:
    """Return a list of section paths for all headings in the document."""
    return [h.path for h in _parse_headings(content)]


def extract_section(content: str, section_query: str) -> tuple[str, list[str], str | None]:
    """Extract the text of a section by title or full path.

    Returns (section_text, error_paths, matched_path).
    On success, error_paths is [] and matched_path is the canonical heading path.
    On failure, section_text is "" and error_paths lists available paths
    (or ["(no sections found)"] if the document has no headings), and
    matched_path is None.
    An empty section_query returns the full document content with matched_path None.
    """
    if not section_query:
        return (content, [], None)

    headings = _parse_headings(content)
    if not headings:
        return ("", ["(no sections found)"], None)

    q = section_query.strip().lower()

    # 1. Try exact path match or suffix path match (e.g. "B > C" matches "A > B > C")
    path_matches = [
        h for h in headings
        if h.path.lower() == q or h.path.lower().endswith(" > " + q)
    ]
    if len(path_matches) == 1:
        matched = path_matches[0]
    elif len(path_matches) == 0:
        # 2. Try title match
        title_matches = [h for h in headings if h.title.lower() == q]
        if len(title_matches) == 1:
            matched = title_matches[0]
        elif len(title_matches) > 1:
            return ("", [h.path for h in title_matches], None)
        else:
            return ("", [h.path for h in headings], None)
    else:
        # Multiple path matches (shouldn't normally happen, but handle gracefully)
        return ("", [h.path for h in path_matches], None)

    # Extract lines from the matched heading to the next heading at same or higher level
    lines = content.splitlines(keepends=True)
    start = matched.line_index
    end = len(lines)
    for h in headings:
        if h.line_index > start and h.level <= matched.level:
            end = h.line_index
            break

    section_text = "".join(lines[start:end])
    return (section_text, [], matched.path)
