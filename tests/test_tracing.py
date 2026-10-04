"""Tracing for POST /ask, with fake embedder, database and LLM (nothing needs to be running)."""

import json
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import numpy as np
import pytest
from langfuse import Langfuse
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from opspilot import api, config, tracing
from opspilot.retrieval import RetrievedChunk

TAGS = (f"model:{config.LLM_MODEL}", f"threshold:{config.DISTANCE_THRESHOLD}")


def fake_llm() -> SimpleNamespace:
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="- Check lag. [a.md]"))],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=8),
        model="fake-model",
    )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_: completion)))


def use_fakes(monkeypatch, langfuse: Langfuse, closest_distance: float) -> None:
    chunks = [
        RetrievedChunk("a.md", "A > Lag", None, "text", closest_distance),
        RetrievedChunk("b.md", "B", None, "text", 0.7),
    ]
    monkeypatch.setattr(api, "connect", contextmanager(lambda: (yield None)))
    monkeypatch.setattr(api, "search", lambda conn, embedding, k: chunks)
    monkeypatch.setattr(api, "resources", {
        "embedder": SimpleNamespace(encode=lambda *args, **kwargs: np.zeros(384)),
        "llm": fake_llm(),
        "langfuse": langfuse,
    })


@pytest.fixture
def exported_spans():
    """A real Langfuse client whose spans go to memory instead of a server."""
    exporter = InMemorySpanExporter()
    # The SDK keeps one client per public key, so use a fresh key per test.
    langfuse = Langfuse(
        public_key=f"pk-test-{uuid.uuid4()}", secret_key="sk-test",
        base_url="http://127.0.0.1:1", span_exporter=exporter,
    )

    def spans_by_name() -> dict:
        langfuse.flush()
        return {span.name: span for span in exporter.get_finished_spans()}

    yield langfuse, spans_by_name
    langfuse.shutdown()


def test_answered_request_is_one_trace_with_three_steps(monkeypatch, exported_spans):
    langfuse, spans_by_name = exported_spans
    use_fakes(monkeypatch, langfuse, closest_distance=0.2)

    response = api.ask(api.AskRequest(question="Replica is behind?"))

    spans = spans_by_name()
    assert set(spans) == {"ask", "embed-question", "vector-search", "llm"}
    assert len({span.context.trace_id for span in spans.values()}) == 1
    assert all(span.attributes["langfuse.trace.tags"] == TAGS for span in spans.values())

    search = spans["vector-search"].attributes
    assert search["langfuse.observation.type"] == "retriever"
    assert json.loads(search["langfuse.observation.output"]) == [
        {"source": "a.md", "section": "A > Lag", "distance": 0.2},
        {"source": "b.md", "section": "B", "distance": 0.7},
    ]

    llm = spans["llm"].attributes
    assert llm["langfuse.observation.type"] == "generation"
    assert llm["langfuse.observation.model.name"] == "fake-model"
    assert json.loads(llm["langfuse.observation.input"])[1]["content"].endswith("Replica is behind?")
    assert llm["langfuse.observation.output"] == response.answer
    assert json.loads(llm["langfuse.observation.usage_details"]) == {"input": 120, "output": 8}


def test_refused_request_records_near_misses_and_is_tagged(monkeypatch, exported_spans):
    langfuse, spans_by_name = exported_spans
    use_fakes(monkeypatch, langfuse, closest_distance=0.6)

    response = api.ask(api.AskRequest(question="Who won the game?"))

    assert response.answer == api.NO_RUNBOOK_ANSWER
    spans = spans_by_name()
    assert "llm" not in spans
    assert spans["ask"].attributes["langfuse.trace.tags"] == (*TAGS, "refused")

    event = spans["refused"].attributes
    assert event["langfuse.observation.type"] == "event"
    assert event["langfuse.observation.metadata.closest_distance"] == "0.6"
    assert [m["source"] for m in json.loads(event["langfuse.observation.metadata.near_misses"])] == [
        "a.md", "b.md",
    ]


def test_without_keys_ask_works_and_nothing_is_traced(monkeypatch):
    monkeypatch.setattr(config, "TRACING_ENABLED", False)
    langfuse = tracing.create_langfuse()
    use_fakes(monkeypatch, langfuse, closest_distance=0.2)

    assert api.ask(api.AskRequest(question="Replica is behind?")).answer == "- Check lag. [a.md]"
    assert langfuse.get_current_trace_id() is None
    langfuse.shutdown()


def langfuse_at(monkeypatch, base_url: str) -> Langfuse:
    """The client the app creates (tracing.create_langfuse), pointed at base_url."""
    monkeypatch.setattr(config, "TRACING_ENABLED", True)
    # The SDK keeps one client per public key, so use a fresh key per test.
    monkeypatch.setattr(config, "LANGFUSE_PUBLIC_KEY", f"pk-test-{uuid.uuid4()}")
    monkeypatch.setattr(config, "LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setattr(config, "LANGFUSE_BASE_URL", base_url)
    return tracing.create_langfuse()


def test_shutdown_sends_queued_traces_to_langfuse(monkeypatch):
    received_span_names = []
    received_service_names = set()

    class FakeLangfuse(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/api/public/otel/v1/traces"
            body = ExportTraceServiceRequest.FromString(self.rfile.read(int(self.headers["Content-Length"])))
            for resource_spans in body.resource_spans:
                received_service_names.update(
                    a.value.string_value for a in resource_spans.resource.attributes if a.key == "service.name"
                )
                for scope_spans in resource_spans.scope_spans:
                    received_span_names.extend(span.name for span in scope_spans.spans)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), FakeLangfuse)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    langfuse = langfuse_at(monkeypatch, f"http://127.0.0.1:{server.server_port}")
    use_fakes(monkeypatch, langfuse, closest_distance=0.2)

    api.ask(api.AskRequest(question="Replica is behind?"))
    assert received_span_names == []  # still queued: the request didn't wait for Langfuse

    tracing.shutdown_langfuse(langfuse)
    assert sorted(received_span_names) == ["ask", "embed-question", "llm", "vector-search"]
    assert received_service_names == {"opspilot"}
    server.shutdown()


def test_hung_langfuse_server_does_not_slow_ask_or_hang_shutdown(monkeypatch):
    # Accepts TCP connections but never answers: the worst kind of Langfuse outage.
    hung_server = socket.create_server(("127.0.0.1", 0))
    monkeypatch.setenv("LANGFUSE_TIMEOUT", "1")
    monkeypatch.setenv("LANGFUSE_FLUSH_AT", "1")  # one export per span: shutdown has many to send
    langfuse = langfuse_at(monkeypatch, f"http://127.0.0.1:{hung_server.getsockname()[1]}")
    use_fakes(monkeypatch, langfuse, closest_distance=0.2)

    start = time.perf_counter()
    for _ in range(5):
        api.ask(api.AskRequest(question="Replica is behind?"))
    assert time.perf_counter() - start < 0.5

    start = time.perf_counter()
    tracing.shutdown_langfuse(langfuse, timeout_s=1)
    assert time.perf_counter() - start < 1.5
    hung_server.close()
