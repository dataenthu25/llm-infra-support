"""Chunking may move or repeat words, but must never glue words together or lose them."""

import pytest

from opspilot import config
from opspilot.chunking import chunk_markdown, parse_front_matter

RUNBOOKS = sorted(config.RUNBOOKS_DIR.glob("*.md"))
HEADING_MARKERS = {"#", "##", "###", "####", "#####", "######"}


def chunk_words(body: str) -> set[str]:
    chunks = chunk_markdown(body, config.CHUNK_MAX_CHARS, config.CHUNK_OVERLAP_CHARS)
    words: set[str] = set()
    for chunk in chunks:
        words.update(chunk.text.split())
    return words


def test_wrapped_line_keeps_words_separate():
    body = "# Title\n\nCheck security groups and NACLs for\n  UDP/TCP 53.\n"
    text = " ".join(chunk_markdown(body, 1200, 150)[0].text.split())
    assert "Check security groups and NACLs for UDP/TCP 53." in text


@pytest.mark.parametrize("path", RUNBOOKS, ids=lambda p: p.name)
def test_no_glued_or_lost_words(path):
    _, body = parse_front_matter(path.read_text(encoding="utf-8"))
    source_words = set(body.split())
    words = chunk_words(body)

    # A dropped space would create a word not in the source.
    # ">" is allowed because the chunker adds it between headings in the section path.
    glued = words - source_words - {">"}
    # Heading markers are dropped on purpose; the heading text lives on in the section path.
    lost = source_words - HEADING_MARKERS - words
    assert not glued, f"chunks contain words not in the source: {sorted(glued)[:10]}"
    assert not lost, f"source words missing from chunks: {sorted(lost)[:10]}"
