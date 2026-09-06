"""One-time, idempotent migration from basket_startup.db to PostgreSQL."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import database

USER_COLUMNS = (
    "user_id",
    "username",
    "name",
    "experience",
    "goal",
    "exp",
    "weekly_exp",
    "streak",
    "last_workout",
)


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_sqlite_users(path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
        ).fetchone()
        if table is None:
            raise RuntimeError("The SQLite file does not contain a users table")

        available_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(users)").fetchall()
        }
        if "user_id" not in available_columns:
            raise RuntimeError("The users table does not contain user_id")

        selected = [column for column in USER_COLUMNS if column in available_columns]
        rows = connection.execute(
            f"SELECT {', '.join(selected)} FROM users ORDER BY user_id"
        ).fetchall()
    finally:
        connection.close()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = {column: None for column in USER_COLUMNS}
        item.update(dict(row))
        item["last_workout"] = parse_timestamp(item["last_workout"])
        result.append(item)
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def migrate(path: Path, database_url: str) -> None:
    users = read_sqlite_users(path)
    fingerprint = sha256_file(path)
    pool = await database.create_pool(database_url)
    try:
        await database.initialize_database(pool)
        imported, row_count = await database.import_users(
            pool,
            rows=users,
            source_sha256=fingerprint,
        )
    finally:
        await pool.close()

    if imported:
        print(f"Migration complete: {row_count} users imported.")
    else:
        print(f"This exact backup was already imported ({row_count} users).")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate Basketbot users from SQLite to PostgreSQL."
    )
    parser.add_argument("sqlite_file", type=Path)
    args = parser.parse_args()

    path = args.sqlite_file.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"SQLite file not found: {path}")

    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is not configured")

    asyncio.run(migrate(path, database_url))


if __name__ == "__main__":
    main()
