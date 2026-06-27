import importlib
import importlib.util
import json


def _modules():
    assert importlib.util.find_spec("app.repositories") is not None
    models = importlib.import_module("app.models")
    repositories = importlib.import_module("app.repositories")
    return models, repositories


def test_memory_repository_deduplicates_and_orders_gaps():
    _, repositories = _modules()
    repo = repositories.MemoryRepository(history_limit=10)

    repo.log_gap("first")
    repo.log_gap("second")
    repo.log_gap("second")

    assert [(item.question, item.count) for item in repo.list_gaps()] == [
        ("second", 2),
        ("first", 1),
    ]


def test_memory_repository_keeps_bounded_history_in_chronological_order():
    models, repositories = _modules()
    repo = repositories.MemoryRepository(history_limit=2)

    for number in range(3):
        repo.save_interaction(
            models.Interaction(
                session_id="session",
                user_message=f"q{number}",
                assistant_message=f"a{number}",
                next_step_hint=None,
                is_gap=False,
                confidence=0.8,
                citations=[],
            )
        )

    assert [(turn.user, turn.assistant) for turn in repo.get_history("session")] == [
        ("q1", "a1"),
        ("q2", "a2"),
    ]


def test_sqlite_repository_persists_gaps_feedback_and_history(tmp_path):
    models, repositories = _modules()
    database = tmp_path / "app.db"
    repo = repositories.SQLiteRepository(database, history_limit=2)

    repo.log_gap("missing procedure")
    repo.save_feedback("s1", "answer", "down", "needs a source")
    repo.save_interaction(
        models.Interaction(
            session_id="s1",
            user_message="question",
            assistant_message="answer",
            next_step_hint="next",
            is_gap=False,
            confidence=0.9,
            citations=[models.Citation(source="manual.pdf", snippet="text")],
        )
    )

    reopened = repositories.SQLiteRepository(database, history_limit=2)

    assert reopened.is_ready()
    assert reopened.list_gaps()[0].question == "missing procedure"
    assert reopened.feedback_count() == 1
    assert reopened.get_history("s1")[0].assistant == "answer"


def test_sqlite_repository_imports_legacy_gaps_once(tmp_path):
    _, repositories = _modules()
    legacy = tmp_path / "gaps.json"
    legacy.write_text(
        json.dumps(
            {
                "legacy question": {
                    "count": 3,
                    "first_seen": "2026-06-27T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )
    database = tmp_path / "app.db"

    repo = repositories.SQLiteRepository(
        database, history_limit=10, legacy_gaps_path=legacy
    )
    reopened = repositories.SQLiteRepository(
        database, history_limit=10, legacy_gaps_path=legacy
    )

    assert [(item.question, item.count) for item in reopened.list_gaps()] == [
        ("legacy question", 3)
    ]
    assert repo.is_ready()
    assert legacy.exists()


def test_backup_and_restore_verify_integrity(tmp_path):
    _, repositories = _modules()
    source = tmp_path / "source.db"
    repo = repositories.SQLiteRepository(source, history_limit=10)
    repo.log_gap("preserve me")
    backup = tmp_path / "backups" / "snapshot.db"

    repositories.backup_database(source, backup)
    restored = tmp_path / "restored.db"
    repositories.restore_database(backup, restored)
    restored_repo = repositories.SQLiteRepository(restored, history_limit=10)

    assert backup.exists()
    assert repositories.check_integrity(backup) == "ok"
    assert restored_repo.list_gaps()[0].question == "preserve me"


def test_overwrite_restore_creates_pre_restore_safety_copy(tmp_path):
    _, repositories = _modules()
    destination = tmp_path / "app.db"
    current = repositories.SQLiteRepository(destination, history_limit=10)
    current.log_gap("current data")
    source = tmp_path / "backup.db"
    old = repositories.SQLiteRepository(source, history_limit=10)
    old.log_gap("backup data")

    repositories.restore_database(source, destination, overwrite=True)

    safety_copies = list(tmp_path.glob("app.pre-restore-*.db"))
    assert len(safety_copies) == 1
    safety_repo = repositories.SQLiteRepository(safety_copies[0], history_limit=10)
    restored_repo = repositories.SQLiteRepository(destination, history_limit=10)
    assert safety_repo.list_gaps()[0].question == "current data"
    assert restored_repo.list_gaps()[0].question == "backup data"
