import os

import app.database_cli as database_cli


def test_prune_backups_keeps_newest_snapshots(tmp_path):
    for number in range(12):
        path = tmp_path / f"app-{number:02}.db"
        path.write_bytes(b"database")
        os.utime(path, (number, number))

    database_cli.prune_backups(tmp_path, keep=10)

    remaining = sorted(path.name for path in tmp_path.glob("app-*.db"))
    assert remaining == [f"app-{number:02}.db" for number in range(2, 12)]
