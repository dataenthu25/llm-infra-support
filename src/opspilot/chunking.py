"""Split markdown documents into chunks for embedding.

Steps:
1. Read the front matter block (--- key: value ---) at the top of the file.
2. Split the body into sections at every markdown heading (#, ##, ### ...).
3. Cut sections longer than max_chars into smaller pieces at paragraph breaks.
4. Start each chunk with the last whole sentences of the previous chunk (the overlap).
"""

import re
from dataclasses import dataclass

# A heading is 1-6 '#' characters, a space, then the title.
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# A sentence ends with . ! or ? followed by whitespace.
SENTENCE_END_RE = re.compile(r"[.!?]\s+")


@dataclass
class Chunk:
    section: str  # heading path, e.g. "Postgres replication lag > Diagnosis"
    text: str     # what gets embedded and stored


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Return (metadata, body). Only simple `key: value` lines are supported."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    metadata = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"')
    body = text[end + len("\n---\n"):]
    return metadata, body


def split_into_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown into (section_path, section_text) pairs, one per heading."""
    sections: list[tuple[str, str]] = []
    heading_stack: list[tuple[int, str]] = []  # (level, title) of current heading and its parents
    lines: list[str] = []
    in_code_block = False

    for line in body.splitlines():
        # Lines like "# restart the pod" inside ``` blocks are comments, not headings.
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
        match = None if in_code_block else HEADING_RE.match(line)

        if not match:
            lines.append(line)
            continue

        # A new heading ends the previous section.
        _add_section(sections, heading_stack, lines)
        lines = []
        level = len(match.group(1))
        # Headings at the same or a deeper level are no longer parents of this one.
        heading_stack = [(lvl, title) for lvl, title in heading_stack if lvl < level]
        heading_stack.append((level, match.group(2)))

    _add_section(sections, heading_stack, lines)
    return sections


def _add_section(sections, heading_stack, lines) -> None:
    text = "\n".join(lines).strip()
    if text:  # skip headings with no text under them
        path = " > ".join(title for _, title in heading_stack) or "Introduction"
        sections.append((path, text))


def split_long_text(text: str, max_chars: int) -> list[str]:
    """Cut text into pieces of at most ~max_chars, breaking only between paragraphs.

    A single paragraph longer than max_chars is kept whole rather than cut mid-sentence.
    """
    if len(text) <= max_chars:
        return [text]

    pieces = []
    current = ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > max_chars:
            pieces.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        pieces.append(current)
    return pieces


def tail(text: str, n: int) -> str:
    """Return the last whole sentences of text that fit in about n characters.

    Returns "" when no sentence starts inside the last n characters, or when the
    result would contain part of a code block: no overlap beats a confusing fragment.
    """
    if n <= 0:
        return ""
    if len(text) <= n:
        overlap = text
    else:
        end_part = text[-n:]
        match = SENTENCE_END_RE.search(end_part)
        if not match:
            return ""
        overlap = end_part[match.end():]  # starts right after a sentence ending
    if "```" in overlap:
        return ""
    return overlap.strip()


def chunk_markdown(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Turn a markdown body into chunks: heading path + overlap + section text."""
    chunks = []
    previous_piece = ""
    for section, text in split_into_sections(body):
        for piece in split_long_text(text, max_chars):
            overlap = tail(previous_piece, overlap_chars)
            parts = [section, overlap, piece]
            chunk_text = "\n\n".join(part for part in parts if part)
            chunks.append(Chunk(section=section, text=chunk_text))
            previous_piece = piece
    return chunks
