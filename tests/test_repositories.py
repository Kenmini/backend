import importlib
import importlib.util
import json
from datetime import datetime, timezone

import pytest


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


def test_integrity_check_does_not_create_a_missing_database(tmp_path):
    _, repositories = _modules()
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError):
        repositories.check_integrity(missing)

    assert not missing.exists()


def test_backup_rejects_a_missing_source_without_creating_files(tmp_path):
    _, repositories = _modules()
    missing = tmp_path / "missing.db"
    backup = tmp_path / "backup.db"

    with pytest.raises(FileNotFoundError):
        repositories.backup_database(missing, backup)

    assert not missing.exists()
    assert not backup.exists()


def test_backup_rejects_an_empty_file_that_is_not_an_application_database(tmp_path):
    _, repositories = _modules()
    empty = tmp_path / "empty.db"
    empty.touch()
    backup = tmp_path / "backup.db"

    with pytest.raises(RuntimeError, match="integrity"):
        repositories.backup_database(empty, backup)

    assert not backup.exists()


def test_failed_backup_does_not_destroy_an_existing_snapshot(tmp_path, monkeypatch):
    _, repositories = _modules()
    source = tmp_path / "source.db"
    source_repository = repositories.SQLiteRepository(source, history_limit=10)
    source_repository.log_gap("new data")
    destination = tmp_path / "snapshot.db"
    old_repository = repositories.SQLiteRepository(destination, history_limit=10)
    old_repository.log_gap("old data")
    real_check = repositories.check_integrity

    def reject_new_snapshot(path):
        path = type(destination)(path)
        if path == destination or path.name.startswith(".snapshot.db."):
            return "simulated corruption"
        return real_check(path)

    monkeypatch.setattr(repositories, "check_integrity", reject_new_snapshot)

    with pytest.raises(RuntimeError, match="integrity"):
        repositories.backup_database(source, destination)

    preserved = repositories.SQLiteRepository(destination, history_limit=10)
    assert preserved.list_gaps()[0].question == "old data"


def test_restore_rejects_a_missing_source_without_overwriting_data(tmp_path):
    _, repositories = _modules()
    destination = tmp_path / "app.db"
    current = repositories.SQLiteRepository(destination, history_limit=10)
    current.log_gap("keep me")
    missing = tmp_path / "missing.db"

    with pytest.raises(FileNotFoundError):
        repositories.restore_database(missing, destination, overwrite=True)

    assert not missing.exists()
    reopened = repositories.SQLiteRepository(destination, history_limit=10)
    assert reopened.list_gaps()[0].question == "keep me"


def test_malformed_legacy_gap_file_is_ignored(tmp_path):
    _, repositories = _modules()
    legacy = tmp_path / "gaps.json"
    legacy.write_text("[]", encoding="utf-8")

    repository = repositories.SQLiteRepository(
        tmp_path / "app.db", history_limit=10, legacy_gaps_path=legacy
    )

    assert repository.is_ready()
    assert repository.list_gaps() == []


def test_repeated_restores_do_not_overwrite_safety_copies(tmp_path, monkeypatch):
    _, repositories = _modules()

    class FixedDateTime:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 6, 28, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(repositories, "datetime", FixedDateTime)
    destination = tmp_path / "app.db"
    current = repositories.SQLiteRepository(destination, history_limit=10)
    current.log_gap("original")
    first_source = tmp_path / "first.db"
    first = repositories.SQLiteRepository(first_source, history_limit=10)
    first.log_gap("first")
    second_source = tmp_path / "second.db"
    second = repositories.SQLiteRepository(second_source, history_limit=10)
    second.log_gap("second")

    repositories.restore_database(first_source, destination, overwrite=True)
    repositories.restore_database(second_source, destination, overwrite=True)

    safety_copies = list(tmp_path.glob("app.pre-restore-*.db"))
    assert len(safety_copies) == 2


def test_failed_restore_copy_keeps_the_active_database(tmp_path, monkeypatch):
    _, repositories = _modules()
    destination = tmp_path / "app.db"
    current = repositories.SQLiteRepository(destination, history_limit=10)
    current.log_gap("active data")
    source = tmp_path / "backup.db"
    backup = repositories.SQLiteRepository(source, history_limit=10)
    backup.log_gap("backup data")

    def fail_after_partial_copy(source_path, destination_path):
        type(destination)(destination_path).write_bytes(b"partial")
        raise OSError("simulated copy failure")

    monkeypatch.setattr(repositories.shutil, "copy2", fail_after_partial_copy)

    with pytest.raises(OSError, match="copy failure"):
        repositories.restore_database(source, destination, overwrite=True)

    reopened = repositories.SQLiteRepository(destination, history_limit=10)
    assert reopened.list_gaps()[0].question == "active data"
