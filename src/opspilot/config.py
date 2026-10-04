"""Settings for ingestion, search and the API. Change them here, not in the other files."""

import os
from pathlib import Path

from dotenv import load_dotenv

# src/opspilot/config.py -> parents[2] is the project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS_DIR = PROJECT_ROOT / "data" / "runbooks"

# Read .env from the project root, if present. Variables already set in the shell win.
load_dotenv(PROJECT_ROOT / ".env")

# Matches the user/password/db/port in docker-compose.yml. Override with the DATABASE_URL env var.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://opspilot:opspilot@localhost:5433/opspilot"
)

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384  # bge-small turns every text into a vector of 384 numbers

# ~1200 characters is roughly 300 tokens, well under bge-small's 512-token input limit.
CHUNK_MAX_CHARS = 1200
# Upper bound for the overlap; only whole sentences are copied from the previous chunk.
CHUNK_OVERLAP_CHARS = 150

# Retrieval
TOP_K = int(os.environ.get("TOP_K", "4"))
# If even the closest chunk is farther than this (cosine distance), don't call the LLM.
DISTANCE_THRESHOLD = float(os.environ.get("DISTANCE_THRESHOLD", "0.45"))

# LLM: any OpenAI-compatible endpoint. Defaults point at a local Ollama.
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")  # Ollama ignores it, but the client requires one

# Tracing (optional): set both keys to send a trace per /ask request to Langfuse.
# Leave them empty to run without tracing. See langfuse/docker-compose.yml for a local server.
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3000")
TRACING_ENABLED = bool(LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY)
