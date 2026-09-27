"""Search the ingested runbooks.

Usage:  uv run python scripts/search.py "why is my postgres replica lagging?"
"""

import sys

from sentence_transformers import SentenceTransformer

from opspilot import config
from opspilot.db import connect
from opspilot.retrieval import retrieve

TOP_K = 3


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('Usage: uv run python scripts/search.py "your question"')
    question = " ".join(sys.argv[1:])

    model = SentenceTransformer(config.EMBEDDING_MODEL)
    with connect() as conn:
        results = retrieve(conn, model, question, TOP_K)

    print(f"\nQuestion: {question}\n")
    for rank, chunk in enumerate(results, start=1):
        preview = " ".join(chunk.content.split())[:200]  # collapse newlines for display
        print(f"{rank}. {chunk.source}  (distance {chunk.distance:.3f})")
        print(f"   section: {chunk.section}")
        print(f"   {preview}...\n")


if __name__ == "__main__":
    main()
