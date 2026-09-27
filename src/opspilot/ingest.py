"""Ingest markdown runbooks into Postgres/pgvector.

Run with:  uv run opspilot-ingest
"""

from pathlib import Path

from sentence_transformers import SentenceTransformer

from opspilot import config
from opspilot.chunking import chunk_markdown, parse_front_matter
from opspilot.db import connect, create_schema


def load_chunks(runbooks_dir: Path) -> list[dict]:
    """Read every markdown file and return one dict per chunk, with its metadata."""
    rows = []
    for path in sorted(runbooks_dir.glob("*.md")):
        metadata, body = parse_front_matter(path.read_text(encoding="utf-8"))
        chunks = chunk_markdown(body, config.CHUNK_MAX_CHARS, config.CHUNK_OVERLAP_CHARS)
        for index, chunk in enumerate(chunks):
            rows.append({
                "source": path.name,
                "section": chunk.section,
                "team": metadata.get("team"),
                "chunk_index": index,
                "content": chunk.text,
            })
    return rows


def main() -> None:
    rows = load_chunks(config.RUNBOOKS_DIR)
    num_files = len({row["source"] for row in rows})
    print(f"Split {num_files} files into {len(rows)} chunks")

    print(f"Loading embedding model {config.EMBEDDING_MODEL} ...")
    model = SentenceTransformer(config.EMBEDDING_MODEL)
    embeddings = model.encode(
        [row["content"] for row in rows],
        batch_size=32,
        normalize_embeddings=True,  # unit-length vectors, as recommended for cosine search
        show_progress_bar=True,
    )

    for row, embedding in zip(rows, embeddings):
        row["embedding"] = embedding

    # `with` commits the transaction on success and rolls back on error.
    with connect() as conn:
        create_schema(conn)
        # Re-ingest from scratch each run: no duplicates, and removed files disappear.
        conn.execute("TRUNCATE chunks")
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO chunks (source, section, team, chunk_index, content, embedding)
                VALUES (%(source)s, %(section)s, %(team)s, %(chunk_index)s, %(content)s, %(embedding)s)
                """,
                rows,
            )

    print(f"Stored {len(rows)} chunks in the 'chunks' table")


if __name__ == "__main__":
    main()
