import os
import sys
from datetime import datetime, timezone

import pytest

import app.database_cli as database_cli


def test_prune_backups_keeps_newest_snapshots(tmp_path):
    for number in range(12):
        path = tmp_path / f"app-{number:02}.db"
        path.write_bytes(b"database")
        os.utime(path, (number, number))

    database_cli.prune_backups(tmp_path, keep=10)

    remaining = sorted(path.name for path in tmp_path.glob("app-*.db"))
    assert remaining == [f"app-{number:02}.db" for number in range(2, 12)]


def test_prune_backups_rejects_non_positive_retention(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        database_cli.prune_backups(tmp_path, keep=0)


def test_backup_cli_rejects_bad_retention_before_writing(monkeypatch, tmp_path):
    called = False

    def fake_backup(source, destination):
        nonlocal called
        called = True

    monkeypatch.setattr(database_cli, "backup_database", fake_backup)
    monkeypatch.setattr(
        sys,
        "argv",
        ["database_cli", "backup", "--directory", str(tmp_path), "--keep", "0"],
    )

    with pytest.raises(SystemExit) as error:
        database_cli.main()

    assert error.value.code == 2
    assert called is False


def test_repeated_backup_commands_create_distinct_snapshots(monkeypatch, tmp_path):
    class FixedDateTime:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 6, 28, 0, 0, tzinfo=timezone.utc)

    def fake_backup(source, destination):
        destination.touch()

    monkeypatch.setattr(database_cli, "datetime", FixedDateTime)
    monkeypatch.setattr(database_cli, "backup_database", fake_backup)
    monkeypatch.setattr(
        sys,
        "argv",
        ["database_cli", "backup", "--directory", str(tmp_path)],
    )

    database_cli.main()
    database_cli.main()

    assert len(list(tmp_path.glob("app-*.db"))) == 2
