"""
gaps.py — Knowledge-gap store (the signature agentic feature).

When the agent cannot find documented support for a question (top retrieval
score below GAP_THRESHOLD), we log the question here so a professor can review
what the lab has never written down. Backed by a local gaps.json file for the
MVP.

Dedup strategy: keyed by the exact (stripped) question string. A repeated
question increments `count` instead of adding a duplicate, so the professor can
see which gaps are asked most often.

TODO(production): move this to DynamoDB (or any shared DB) so multiple backend
instances share one gaps store and it survives restarts/redeploys.
"""

import json
import os
from datetime import datetime, timezone

from config import GAPS_FILE


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (timezone-aware)."""
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    """Read the gaps file; return an empty store if it doesn't exist yet."""
    if not os.path.exists(GAPS_FILE):
        return {}
    try:
        with open(GAPS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt/unreadable file: start fresh rather than crash the API.
        return {}


def _save(store: dict) -> None:
    """Write the gaps store back to disk (UTF-8, human-readable)."""
    with open(GAPS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def log_gap(question: str) -> None:
    """
    Record a knowledge gap. Deduplicated by the exact question string:
    first occurrence stores first_seen; repeats just increment count.
    """
    question = (question or "").strip()
    if not question:
        return
    store = _load()
    entry = store.get(question)
    if entry:
        entry["count"] += 1
    else:
        store[question] = {"count": 1, "first_seen": _now_iso()}
    _save(store)


def list_gaps() -> list[dict]:
    """
    Return all logged gaps, most-asked first, each as:
        { "question": str, "count": int, "first_seen": str }
    """
    store = _load()
    gaps = [
        {"question": q, "count": e["count"], "first_seen": e["first_seen"]}
        for q, e in store.items()
    ]
    gaps.sort(key=lambda g: g["count"], reverse=True)
    return gaps
