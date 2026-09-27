"""Database helpers: connect to Postgres and create the table that stores chunks."""

import psycopg
from pgvector.psycopg import register_vector

from opspilot.config import DATABASE_URL, EMBEDDING_DIM

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,   -- file name, e.g. k8s-node-notready.md
    section     TEXT NOT NULL,   -- heading path, e.g. "Kubernetes node NotReady > Diagnosis"
    team        TEXT,            -- owning team from the file's front matter
    chunk_index INT  NOT NULL,   -- position of the chunk within its file
    content     TEXT NOT NULL,   -- the text that was embedded
    embedding   vector({EMBEDDING_DIM}) NOT NULL
);

-- HNSW index for fast approximate nearest-neighbour search using cosine distance
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
    ON chunks USING hnsw (embedding vector_cosine_ops);
"""


def connect() -> psycopg.Connection:
    """Open a connection with pgvector support enabled."""
    conn = psycopg.connect(DATABASE_URL)
    # The extension must exist before register_vector can look up the 'vector' type.
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    return conn


def create_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)
