"""Optional Langfuse tracing for POST /ask.

Tracing must never break or slow down a request. The Langfuse SDK only queues finished spans
in memory; a background thread sends them in batches. If Langfuse is down or slow, the export
fails on that thread (logged and dropped) while requests carry on. The queue is bounded, so
spans are dropped rather than piling up during a long outage.
"""

import logging
import threading

from langfuse import Langfuse
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

from opspilot import config

logger = logging.getLogger("opspilot.tracing")

SHUTDOWN_TIMEOUT_S = 5.0
SERVICE_NAME = "opspilot"  # shown as resourceAttributes.service.name on every span


def create_langfuse() -> Langfuse:
    """Return a Langfuse client, or a disabled one (its spans do nothing) if the keys aren't set."""
    if config.TRACING_ENABLED:
        logger.info("Langfuse tracing enabled, sending traces to %s", config.LANGFUSE_BASE_URL)
        return Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            base_url=config.LANGFUSE_BASE_URL,
            # Like the SDK's default provider, but named (instead of "unknown_service:python")
            # and without OpenTelemetry's exit hook, which would retry the flush without a
            # time limit after shutdown_langfuse() has given up.
            tracer_provider=TracerProvider(
                resource=Resource.create({"service.name": SERVICE_NAME}), shutdown_on_exit=False
            ),
        )

    logger.info("LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY not set: tracing disabled")
    # Without keys the SDK logs an "Authentication error" warning. Here that's expected, so hide it.
    sdk_logger = logging.getLogger("langfuse")
    previous_level = sdk_logger.level
    sdk_logger.setLevel(logging.ERROR)
    try:
        return Langfuse(tracing_enabled=False)
    finally:
        sdk_logger.setLevel(previous_level)


def shutdown_langfuse(langfuse: Langfuse, timeout_s: float = SHUTDOWN_TIMEOUT_S) -> None:
    """Send the queued traces, but never hold up the app's shutdown for more than timeout_s.

    If Langfuse is unreachable, the SDK waits its export timeout (5 s) for every batch of up
    to 512 spans, so a full queue would take ~25 s, long enough for Kubernetes to kill the pod.
    """
    flush = threading.Thread(target=langfuse.shutdown, name="langfuse-shutdown", daemon=True)
    flush.start()
    flush.join(timeout_s)
    if flush.is_alive():
        logger.warning("Langfuse did not accept traces within %.0f s; unsent traces are dropped", timeout_s)
