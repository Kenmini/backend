import argparse
from datetime import datetime, timezone
from pathlib import Path

from app.repositories import backup_database, restore_database
from config import SETTINGS


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def prune_backups(directory: Path, keep: int) -> None:
    if keep < 1:
        raise ValueError("Backup retention must be at least 1")
    backups = sorted(directory.glob("app-*.db"), key=lambda path: path.stat().st_mtime)
    for path in backups[:-keep]:
        path.unlink()


def next_backup_path(directory: Path, timestamp: str) -> Path:
    target = directory / f"app-{timestamp}.db"
    counter = 1
    while target.exists():
        target = directory / f"app-{timestamp}-{counter}.db"
        counter += 1
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Backup or restore the local database")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--directory", type=Path, default=Path("backups"))
    backup.add_argument("--keep", type=positive_int, default=10)
    restore = subparsers.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.command == "backup":
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = next_backup_path(args.directory, timestamp)
        backup_database(SETTINGS.database_path, target)
        prune_backups(args.directory, args.keep)
        print(target)
        return 0

    restore_database(args.source, SETTINGS.database_path, overwrite=args.overwrite)
    print(SETTINGS.database_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
