"""FastAPI app: POST /ask answers questions using the ingested runbooks.

Run with:  uv run uvicorn opspilot.api:app --reload
Docs at:   http://localhost:8000/docs
"""

import logging
import time
from contextlib import asynccontextmanager

import openai
from fastapi import FastAPI, HTTPException
from langfuse import propagate_attributes
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

from opspilot import config
from opspilot.db import connect
from opspilot.retrieval import RetrievedChunk, embed_question, search
from opspilot.tracing import create_langfuse, shutdown_langfuse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("opspilot.api")

NO_RUNBOOK_ANSWER = "I don't have a runbook for that."

SYSTEM_PROMPT = """You are OpsPilot, an assistant for on-call engineers.
Answer using ONLY the context passages. Each passage starts with its source file name.

Format:
- Answer as a bullet list.
- End every bullet with the source file name of the passage it came from, in square brackets.
  Example: - Cancel the blocking query on the replica with pg_cancel_backend. [db-postgres-replication-lag.md]
- If a bullet uses two files, list both at the end: [first-file.md] [second-file.md]
- If the context does not cover some part of the question, end with this bullet:
  - Not covered by the runbooks: <that part of the question>.
- If the context covers none of the question, reply with only that bullet.

Never use outside knowledge. Never invent commands, thresholds, names or file names."""


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class Source(BaseModel):
    source: str
    section: str
    distance: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    model: str | None  # None when the LLM was not called
    retrieval_ms: int  # embed the question + pgvector query
    generation_ms: int  # LLM call
    latency_ms: int  # whole request
    input_tokens: int
    output_tokens: int


# Created once at startup and shared by every request.
resources: dict = {}


def load_resources() -> None:
    resources["embedder"] = SentenceTransformer(config.EMBEDDING_MODEL)
    resources["llm"] = openai.OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    resources["langfuse"] = create_langfuse()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_resources()
    yield  # the app serves requests while we're paused here
    # Send the traces still queued in memory. Gives up after 5 s if Langfuse is down.
    shutdown_langfuse(resources["langfuse"])
    resources.clear()


app = FastAPI(title="OpsPilot", lifespan=lifespan)


def build_user_prompt(question: str, chunks: list[RetrievedChunk]) -> str:
    passages = "\n\n---\n\n".join(
        f"Source: {chunk.source}\nSection: {chunk.section}\n\n{chunk.content}" for chunk in chunks
    )
    return f"Context passages:\n\n{passages}\n\n---\n\nQuestion: {question}"


def elapsed_ms(start: float) -> int:
    return round((time.perf_counter() - start) * 1000)


def source_list(chunks: list[RetrievedChunk]) -> list[dict]:
    return [{"source": c.source, "section": c.section, "distance": round(c.distance, 4)} for c in chunks]


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    # Plain `def` (not `async def`): FastAPI runs it in a worker thread, so the blocking
    # embedding, database and LLM calls don't freeze the server for other requests.
    langfuse = resources["langfuse"]
    # One trace per request: this root span is the trace, each step below is a child observation.
    # The tags are set on every observation in the trace, so traces can be filtered by them.
    with (
        langfuse.start_as_current_observation(name="ask", input={"question": request.question}) as root,
        propagate_attributes(
            trace_name="ask",
            tags=[f"model:{config.LLM_MODEL}", f"threshold:{config.DISTANCE_THRESHOLD}"],
        ),
    ):
        response = answer_question(request.question)
        root.update(output={"answer": response.answer, "sources": [s.source for s in response.sources]})
    return response


def answer_question(question: str) -> AskResponse:
    langfuse = resources["langfuse"]
    start = time.perf_counter()

    with langfuse.start_as_current_observation(
        name="embed-question", as_type="embedding", model=config.EMBEDDING_MODEL, input=question
    ) as span:
        query_embedding = embed_question(resources["embedder"], question)
        span.update(output={"dimensions": len(query_embedding)})

    with langfuse.start_as_current_observation(
        name="vector-search", as_type="retriever", input={"top_k": config.TOP_K}
    ) as span:
        with connect() as conn:
            chunks = search(conn, query_embedding, config.TOP_K)
        span.update(output=source_list(chunks))
    retrieval_ms = elapsed_ms(start)

    # Guardrail: if even the closest chunk is too far away, don't call the LLM.
    # Return no sources; log the near misses so the threshold can be tuned.
    if not chunks or chunks[0].distance > config.DISTANCE_THRESHOLD:
        near_misses = "; ".join(f"{c.source} > {c.section} ({c.distance:.3f})" for c in chunks)
        logger.info(
            "No runbook within distance %.2f for %r. Near misses: %s",
            config.DISTANCE_THRESHOLD, question, near_misses or "none",
        )
        # Adds "refused" to the trace's tags (merged with the model/threshold tags).
        with propagate_attributes(tags=["refused"]):
            langfuse.create_event(
                name="refused",
                metadata={
                    "threshold": config.DISTANCE_THRESHOLD,
                    "closest_distance": round(chunks[0].distance, 4) if chunks else None,
                    "near_misses": source_list(chunks),
                },
            )
        return AskResponse(
            answer=NO_RUNBOOK_ANSWER,
            sources=[],
            model=None,
            retrieval_ms=retrieval_ms,
            generation_ms=0,
            latency_ms=elapsed_ms(start),
            input_tokens=0,
            output_tokens=0,
        )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(question, chunks)},
    ]
    temperature = 0  # we want the most likely, factual answer, not creativity
    generation_start = time.perf_counter()
    with langfuse.start_as_current_observation(
        name="llm",
        as_type="generation",
        model=config.LLM_MODEL,
        model_parameters={"temperature": temperature},
        input=messages,
    ) as generation:
        try:
            completion = resources["llm"].chat.completions.create(
                model=config.LLM_MODEL, messages=messages, temperature=temperature
            )
        except openai.APIConnectionError:
            message = f"Cannot reach the LLM at {config.LLM_BASE_URL}. Is it running?"
            generation.update(level="ERROR", status_message=message)
            raise HTTPException(503, message)
        except openai.APIStatusError as e:
            message = f"LLM error ({e.status_code}): {e.message}"
            generation.update(level="ERROR", status_message=message)
            raise HTTPException(502, message)
        generation_ms = elapsed_ms(generation_start)

        answer = completion.choices[0].message.content or ""
        usage = completion.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        model = completion.model or config.LLM_MODEL
        generation.update(
            model=model,
            output=answer,
            usage_details={"input": input_tokens, "output": output_tokens},
        )

    return AskResponse(
        answer=answer,
        sources=[
            Source(source=c.source, section=c.section, distance=round(c.distance, 4))
            for c in chunks
        ],
        model=model,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        latency_ms=elapsed_ms(start),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
