"""Run a fixed set of questions through /ask and print a markdown results table.

Usage:  uv run python scripts/benchmark.py
Calls the endpoint function in-process (no server needed); Postgres and the LLM must be running.
"""

import re

from opspilot import api

QUESTIONS = [
    "Our postgres replica is 5 minutes behind. What should I check?",
    "Pods keep getting OOMKilled after a deploy. What do I do?",
    "Clients get 502 errors from the load balancer during deploys. Why?",
    "Small requests work but large uploads hang over the VPN. What's wrong?",
    "The Redis sessions cluster is full. How do I fix it, and what is the on-call phone number?",
    "Who is Donald Trump?",
]

FILE_CITATION_RE = re.compile(r"\[([^\]\s]+\.md)\]")


def cited_bullets(answer: str, allowed_files: set[str]) -> str:
    """How many bullets end with a citation of a retrieved file (or say 'Not covered')."""
    bullets = [line.strip() for line in answer.splitlines() if line.strip().startswith(("-", "*"))]
    ok = 0
    for bullet in bullets:
        cited = FILE_CITATION_RE.findall(bullet)
        if "Not covered by the runbooks" in bullet:
            ok += 1
        elif cited and bullet.endswith("]") and all(name in allowed_files for name in cited):
            ok += 1
    return f"{ok}/{len(bullets)}" if bullets else "-"


def main() -> None:
    api.load_resources()
    api.ask(api.AskRequest(question=QUESTIONS[0]))  # warm-up: Ollama loads the model on first use

    rows = []
    for question in QUESTIONS:
        result = api.ask(api.AskRequest(question=question))
        print(f"\n### {question}\n{result.answer}")
        allowed = {s.source for s in result.sources}
        rows.append((question, result, cited_bullets(result.answer, allowed) if allowed else "-"))

    print("\n| Question | Retrieval ms | Generation ms | Tokens in | Tokens out | Model | Cited bullets |")
    print("|---|---:|---:|---:|---:|---|---:|")
    for question, r, cited in rows:
        print(
            f"| {question} | {r.retrieval_ms} | {r.generation_ms} | {r.input_tokens} "
            f"| {r.output_tokens} | {r.model or '- (not called)'} | {cited} |"
        )


if __name__ == "__main__":
    main()
