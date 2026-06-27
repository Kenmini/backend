"""Knowledge-gap store, backed by a local JSON file (gaps.json).

Deduped by exact question; repeats increment count. See PROJECT_CONTEXT.md for
why this is the signature feature and the path to a real DB.
"""

import json
import os
from datetime import datetime, timezone

from config import GAPS_FILE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not os.path.exists(GAPS_FILE):
        return {}
    try:
        with open(GAPS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(store: dict) -> None:
    with open(GAPS_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def log_gap(question: str) -> None:
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
    """All gaps as {question, count, first_seen}, most-asked first."""
    store = _load()
    gaps = [
        {"question": q, "count": e["count"], "first_seen": e["first_seen"]}
        for q, e in store.items()
    ]
    gaps.sort(key=lambda g: g["count"], reverse=True)
    return gaps
