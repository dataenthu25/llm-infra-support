"""Find the chunks closest to a question. Shared by the API and scripts/search.py."""

from dataclasses import dataclass

import psycopg
from sentence_transformers import SentenceTransformer

# BGE models expect this prefix on queries (not on the stored documents).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# <=> is pgvector's cosine distance operator: 0 = same direction, 2 = opposite.
SEARCH_SQL = """
    SELECT source, section, team, content, embedding <=> %(query)s AS distance
    FROM chunks
    ORDER BY embedding <=> %(query)s
    LIMIT %(k)s
"""


@dataclass
class RetrievedChunk:
    source: str
    section: str
    team: str | None
    content: str
    distance: float


def retrieve(
    conn: psycopg.Connection, model: SentenceTransformer, question: str, k: int
) -> list[RetrievedChunk]:
    """Return the k chunks closest to the question, closest first."""
    query_embedding = model.encode(
        QUERY_PREFIX + question, normalize_embeddings=True, show_progress_bar=False
    )
    rows = conn.execute(SEARCH_SQL, {"query": query_embedding, "k": k}).fetchall()
    return [RetrievedChunk(*row) for row in rows]
