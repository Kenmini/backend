from collections import defaultdict
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from threading import RLock
from typing import Protocol

from app.models import Gap, HistoryTurn, Interaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository(Protocol):
    def is_ready(self) -> bool: ...
    def log_gap(self, question: str) -> None: ...
    def list_gaps(self) -> list[Gap]: ...
    def save_feedback(
        self, session_id: str, message: str, rating: str, note: str | None
    ) -> None: ...
    def save_interaction(self, interaction: Interaction) -> None: ...
    def get_history(self, session_id: str) -> list[HistoryTurn]: ...


class MemoryRepository:
    def __init__(self, history_limit: int):
        self.history_limit = history_limit
        self._gaps: dict[str, Gap] = {}
        self._feedback: list[dict] = []
        self._interactions: dict[str, list[Interaction]] = defaultdict(list)
        self._lock = RLock()

    def is_ready(self) -> bool:
        return True

    def log_gap(self, question: str) -> None:
        question = question.strip()
        if not question:
            return
        now = _now()
        with self._lock:
            current = self._gaps.get(question)
            if current:
                self._gaps[question] = Gap(
                    question=question,
                    count=current.count + 1,
                    first_seen=current.first_seen,
                    last_seen=now,
                )
            else:
                self._gaps[question] = Gap(question, 1, now, now)

    def list_gaps(self) -> list[Gap]:
        with self._lock:
            return sorted(
                self._gaps.values(), key=lambda item: (-item.count, item.first_seen)
            )

    def save_feedback(
        self, session_id: str, message: str, rating: str, note: str | None
    ) -> None:
        with self._lock:
            self._feedback.append(
                {
                    "session_id": session_id,
                    "message": message,
                    "rating": rating,
                    "note": note,
                    "created_at": _now(),
                }
            )

    def feedback_count(self) -> int:
        with self._lock:
            return len(self._feedback)

    def save_interaction(self, interaction: Interaction) -> None:
        with self._lock:
            items = self._interactions[interaction.session_id]
            items.append(interaction)
            del items[: -self.history_limit]

    def get_history(self, session_id: str) -> list[HistoryTurn]:
        with self._lock:
            return [
                HistoryTurn(item.user_message, item.assistant_message)
                for item in self._interactions.get(session_id, [])
            ]


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gaps (
    question TEXT PRIMARY KEY,
    count INTEGER NOT NULL CHECK (count > 0),
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    message TEXT NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('up', 'down')),
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_message TEXT NOT NULL,
    assistant_message TEXT NOT NULL,
    next_step_hint TEXT,
    is_gap INTEGER NOT NULL,
    confidence REAL NOT NULL,
    citations_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interactions_session
ON interactions(session_id, id DESC);
"""


class SQLiteRepository:
    def __init__(
        self,
        path: str | Path,
        history_limit: int,
        legacy_gaps_path: str | Path | None = None,
    ):
        self.path = Path(path)
        self.history_limit = history_limit
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        if legacy_gaps_path:
            self._import_legacy_gaps(Path(legacy_gaps_path))

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_versions(version, applied_at) VALUES(1, ?)",
                (_now(),),
            )
            connection.commit()

    def _import_legacy_gaps(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        with closing(self._connect()) as connection:
            count = connection.execute("SELECT COUNT(*) FROM gaps").fetchone()[0]
            if count:
                return
            for question, value in raw.items():
                first_seen = value.get("first_seen") or _now()
                connection.execute(
                    """
                    INSERT OR IGNORE INTO gaps(question, count, first_seen, last_seen)
                    VALUES(?, ?, ?, ?)
                    """,
                    (question, max(1, int(value.get("count", 1))), first_seen, first_seen),
                )
            connection.commit()

    def is_ready(self) -> bool:
        try:
            with closing(self._connect()) as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def log_gap(self, question: str) -> None:
        question = question.strip()
        if not question:
            return
        now = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO gaps(question, count, first_seen, last_seen)
                VALUES(?, 1, ?, ?)
                ON CONFLICT(question) DO UPDATE SET
                    count = count + 1,
                    last_seen = excluded.last_seen
                """,
                (question, now, now),
            )
            connection.commit()

    def list_gaps(self) -> list[Gap]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT question, count, first_seen, last_seen
                FROM gaps ORDER BY count DESC, first_seen ASC
                """
            ).fetchall()
        return [Gap(**dict(row)) for row in rows]

    def save_feedback(
        self, session_id: str, message: str, rating: str, note: str | None
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO feedback(session_id, message, rating, note, created_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (session_id, message, rating, note, _now()),
            )
            connection.commit()

    def feedback_count(self) -> int:
        with closing(self._connect()) as connection:
            return connection.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    def save_interaction(self, interaction: Interaction) -> None:
        citations = json.dumps(
            [asdict(citation) for citation in interaction.citations], ensure_ascii=False
        )
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO interactions(
                    session_id, user_message, assistant_message, next_step_hint,
                    is_gap, confidence, citations_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction.session_id,
                    interaction.user_message,
                    interaction.assistant_message,
                    interaction.next_step_hint,
                    int(interaction.is_gap),
                    interaction.confidence,
                    citations,
                    _now(),
                ),
            )
            connection.execute(
                """
                DELETE FROM interactions
                WHERE session_id = ? AND id NOT IN (
                    SELECT id FROM interactions
                    WHERE session_id = ? ORDER BY id DESC LIMIT ?
                )
                """,
                (interaction.session_id, interaction.session_id, self.history_limit),
            )
            connection.commit()

    def get_history(self, session_id: str) -> list[HistoryTurn]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT user_message, assistant_message FROM (
                    SELECT id, user_message, assistant_message FROM interactions
                    WHERE session_id = ? ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (session_id, self.history_limit),
            ).fetchall()
        return [HistoryTurn(row["user_message"], row["assistant_message"]) for row in rows]


def check_integrity(path: str | Path) -> str:
    with closing(sqlite3.connect(Path(path))) as connection:
        return connection.execute("PRAGMA integrity_check").fetchone()[0]


def backup_database(source: str | Path, destination: str | Path) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source_path)) as source_connection:
        with closing(sqlite3.connect(destination_path)) as destination_connection:
            source_connection.backup(destination_connection)
    if check_integrity(destination_path) != "ok":
        destination_path.unlink(missing_ok=True)
        raise RuntimeError("Backup integrity check failed")
    return destination_path


def restore_database(
    source: str | Path, destination: str | Path, *, overwrite: bool = False
) -> Path:
    source_path = Path(source)
    destination_path = Path(destination)
    if check_integrity(source_path) != "ok":
        raise RuntimeError("Source backup integrity check failed")
    if destination_path.exists() and not overwrite:
        raise FileExistsError(destination_path)
    if destination_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safety_copy = destination_path.with_name(
            f"{destination_path.stem}.pre-restore-{timestamp}{destination_path.suffix}"
        )
        backup_database(destination_path, safety_copy)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(f"{destination_path}{suffix}").unlink(missing_ok=True)
    shutil.copy2(source_path, destination_path)
    if check_integrity(destination_path) != "ok":
        raise RuntimeError("Restored database integrity check failed")
    return destination_path
