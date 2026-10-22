"""Split a plain-text legal document into sections by its headings.

Legal documents don't share one heading style, so a line counts as a heading
if it matches any of these:

    # Definitions                 markdown
    ARTICLE IV / Section 5.2      article / section keywords
    1. TERM / 12.3 Payment Terms  numbered (decimal, roman or lettered)
    STATEMENT OF FACTS            a short line in ALL CAPS

Numbered lines are the hard case: "1. The Supplier shall deliver the goods."
is a list item, not a heading, and "Section 4.2 shall survive termination."
is a sentence. The rule used: a numbered or keyword line is a heading only if
the words after the number are short and don't read like a sentence (no ending
punctuation), unless they're in ALL CAPS.

Headings also have levels, because legal documents nest: "3." is level 1 and
"3.1" is level 2; "III." is level 1 and "A." under it is level 2. A section's
text runs until the next heading at the same or a higher level, so asking for
"III. ARGUMENT" returns its subsections too, not an empty body.
"""

import re
from dataclasses import dataclass

MAX_HEADING_CHARS = 100
PREAMBLE = "Preamble"

_MARKDOWN = re.compile(r"^#{1,6}\s+(?P<title>.+)$")
_KEYWORD = re.compile(
    r"^(?P<keyword>ARTICLE|Article|SECTION|Section|§)\s*(?P<number>[IVXLC]+|\d+(?:\.\d+)*)\b"
    r"[.:]?(?:\s+(?P<title>\S.*))?$"
)
# 1.  12.3  IV.  A.  followed by a title. A lone C/D/L/M is read as a letter, not a
# roman numeral: "C. Damages" after "B." is far more likely than section 100.
_NUMBERED = re.compile(
    r"^(?:(?P<decimal>\d+(?:\.\d+)*)\.?|(?P<roman>[IVXLC]{2,}|[IVX])\.|(?P<letter>[A-Z])\.)"
    r"\s+(?P<title>\S.*)$"
)


@dataclass(frozen=True)
class Section:
    heading: str
    level: int  # 1 is top level; larger numbers are nested deeper
    text: str  # the body without the heading line, including any subsections


def heading_level(line: str) -> int | None:
    """The heading level of `line`, or None if it isn't a heading."""
    line = line.strip()
    if not line or len(line) > MAX_HEADING_CHARS:
        return None
    if _MARKDOWN.match(line):
        return len(line) - len(line.lstrip("#"))
    if match := _KEYWORD.match(line):
        if match["title"] is not None and not _looks_like_title(match["title"]):
            return None
        if match["keyword"].upper() == "ARTICLE":
            return 1
        return 1 + match["number"].count(".")  # Section 5 -> 1, Section 5.2 -> 2
    if match := _NUMBERED.match(line):
        if not _looks_like_title(match["title"]):
            return None
        if match["decimal"]:
            return 1 + match["decimal"].count(".")  # 3 -> 1, 3.1 -> 2, 3.1.4 -> 3
        return 1 if match["roman"] else 2  # III. is top level, A. sits under it
    return 1 if _is_all_caps(line) else None


def is_heading(line: str) -> bool:
    return heading_level(line) is not None


def _looks_like_title(title: str) -> bool:
    return _is_all_caps(title) or (len(title.split()) <= 8 and title[-1] not in ".;,:")


def _is_all_caps(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def split_sections(text: str) -> list[Section]:
    """Return sections in document order. Any text before the first heading
    becomes a level-1 "Preamble" section, so no content is ever dropped."""
    # Pass 1: cut the document at every heading line.
    # Each entry is (heading, level, heading_line, body_lines).
    parts: list[tuple[str, int, str | None, list[str]]] = [(PREAMBLE, 1, None, [])]
    for line in text.splitlines():
        level = heading_level(line)
        if level is None:
            parts[-1][3].append(line)
        else:
            parts.append((_clean_heading(line), level, line.strip(), []))
    if not "\n".join(parts[0][3]).strip():
        parts.pop(0)  # no text before the first heading

    # Pass 2: a section's text is its own body, then every following part that
    # is nested deeper (a higher level number), until a sibling or parent heading.
    sections: list[Section] = []
    for i, (heading, level, _, body) in enumerate(parts):
        lines = list(body)
        for _, child_level, child_line, child_body in parts[i + 1 :]:
            if child_level <= level:
                break
            lines.append(child_line or "")
            lines.extend(child_body)
        sections.append(Section(heading=heading, level=level, text="\n".join(lines).strip()))
    return sections


def find_section(sections: list[Section], query: str) -> Section | None:
    """Match a heading case-insensitively: an exact match wins, then the first
    heading that contains the query (so "termination" finds "8. TERMINATION")."""
    wanted = _normalize(query)
    if not wanted:
        return None
    for section in sections:
        if _normalize(section.heading) == wanted:
            return section
    for section in sections:
        if wanted in _normalize(section.heading):
            return section
    return None


def _clean_heading(line: str) -> str:
    line = line.strip()
    if match := _MARKDOWN.match(line):
        return match["title"].strip()
    return line


def _normalize(text: str) -> str:
    return " ".join(text.lower().split()).rstrip(".:")
