"""Retrieval eval: does vector search find the right runbook? No LLM needed.

Usage:  uv run python evals/retrieval_eval.py
Exits with code 1 when the pass rate is below MIN_PASS_RATE. That is what fails CI.
"""

import json
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer

from opspilot import config
from opspilot.db import connect
from opspilot.retrieval import retrieve

CASES_FILE = Path(__file__).parent / "cases.json"
MIN_PASS_RATE = 0.9  # 12 cases: at most 1 may fail


def check(case: dict, chunks: list) -> tuple[bool, str]:
    closest = chunks[0].distance if chunks else 2.0  # 2.0 = furthest possible
    if case.get("should_refuse"):
        ok = closest > config.DISTANCE_THRESHOLD
        return ok, f"closest {closest:.3f}, must be > {config.DISTANCE_THRESHOLD}"
    found = list(dict.fromkeys(c.source for c in chunks))  # unique, keeps order
    hit = any(source in found for source in case["expected_sources"])
    ok = hit and closest <= config.DISTANCE_THRESHOLD
    return ok, f"closest {closest:.3f}, found {found}"


def main() -> None:
    cases = json.loads(CASES_FILE.read_text())
    model = SentenceTransformer(config.EMBEDDING_MODEL)

    passed = 0
    guardrail_failures = []
    with connect() as conn:
        for case in cases:
            chunks = retrieve(conn, model, case["question"], config.TOP_K)
            ok, detail = check(case, chunks)
            passed += ok  # True counts as 1, False as 0
            print(f"{'PASS' if ok else 'FAIL'}  {case['id']:<18} {detail}")
            if case.get("should_refuse") and not ok:
                guardrail_failures.append(case["id"])

    if not cases:
        sys.exit("No eval cases found, refusing to report a pass")  # never pass silently

    rate = passed / len(cases)
    print(f"\n{passed}/{len(cases)} passed ({rate:.0%}), minimum {MIN_PASS_RATE:.0%}")
    if guardrail_failures:
        print(f"Blocking: guardrail cases failed: {', '.join(guardrail_failures)}")
    sys.exit(0 if rate >= MIN_PASS_RATE and not guardrail_failures else 1)


if __name__ == "__main__":
    main()