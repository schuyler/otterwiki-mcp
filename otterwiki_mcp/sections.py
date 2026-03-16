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
    stack: list[tuple[int, str]] = []  # [(level, title), ...]

    for i, line in enumerate(lines):
        # Toggle fence state
        if re.match(r'^\s*`{3,}', line):
            in_fence = not in_fence
            continue

        if in_fence:
            continue

        m = re.match(r'^(#{1,6})\s+(.*)', line)
        if not m:
            continue

        level = len(m.group(1))
        title = m.group(2).strip()

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


def extract_section(content: str, section_query: str) -> tuple[str, list[str]]:
    """Extract the text of a section by title or full path.

    Returns (section_text, error_paths). On success, error_paths is [].
    On failure, section_text is "" and error_paths lists available paths
    (or ["(no sections found)"] if the document has no headings).
    An empty section_query returns the full document content.
    """
    if not section_query:
        return (content, [])

    headings = _parse_headings(content)
    if not headings:
        return ("", ["(no sections found)"])

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
            return ("", [h.path for h in title_matches])
        else:
            return ("", [h.path for h in headings])
    else:
        # Multiple path matches (shouldn't normally happen, but handle gracefully)
        return ("", [h.path for h in path_matches])

    # Extract lines from the matched heading to the next heading at same or higher level
    lines = content.splitlines(keepends=True)
    start = matched.line_index
    end = len(lines)
    for h in headings:
        if h.line_index > start and h.level <= matched.level:
            end = h.line_index
            break

    section_text = "".join(lines[start:end])
    return (section_text, [])
