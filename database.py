"""PostgreSQL access layer for Basketbot."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg
from asyncpg import Pool, Record

from content import DEFAULT_WORKOUTS

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    name TEXT NOT NULL,
    experience TEXT,
    goal TEXT,
    exp INTEGER NOT NULL DEFAULT 0 CHECK (exp >= 0),
    weekly_exp INTEGER NOT NULL DEFAULT 0 CHECK (weekly_exp >= 0),
    streak INTEGER NOT NULL DEFAULT 0 CHECK (streak >= 0),
    last_workout TIMESTAMPTZ,
    last_inactive_notice TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS users_weekly_exp_idx
    ON users (weekly_exp DESC);

CREATE INDEX IF NOT EXISTS users_last_workout_idx
    ON users (last_workout);

CREATE TABLE IF NOT EXISTS workouts (
    workout_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    exp INTEGER NOT NULL CHECK (exp >= 0),
    description TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS workouts_category_order_idx
    ON workouts (category, sort_order, workout_id)
    WHERE active = TRUE;

CREATE TABLE IF NOT EXISTS workout_materials (
    material_id BIGSERIAL PRIMARY KEY,
    workout_id TEXT NOT NULL REFERENCES workouts(workout_id) ON DELETE CASCADE,
    material_type TEXT NOT NULL CHECK (material_type IN ('photo', 'video', 'link')),
    value TEXT NOT NULL,
    label TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS workout_materials_order_idx
    ON workout_materials (workout_id, sort_order, material_id);

CREATE TABLE IF NOT EXISTS weekly_reward_runs (
    week_start DATE PRIMARY KEY,
    first_user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    second_user_id BIGINT REFERENCES users(user_id) ON DELETE SET NULL,
    first_notified BOOLEAN NOT NULL DEFAULT FALSE,
    second_notified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS import_runs (
    source_sha256 TEXT PRIMARY KEY,
    imported_rows INTEGER NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def normalize_database_url(database_url: str) -> str:
    """Normalize provider URLs for asyncpg without logging credentials."""
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url.removeprefix("postgres://")

    parts = urlsplit(database_url)
    # Some providers append a libpq-only option that asyncpg does not need.
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if key != "channel_binding"
    ]
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


async def create_pool(database_url: str) -> Pool:
    if not database_url.strip():
        raise RuntimeError("DATABASE_URL is not configured")

    return await asyncpg.create_pool(
        dsn=normalize_database_url(database_url.strip()),
        min_size=0,
        max_size=5,
        max_inactive_connection_lifetime=60,
        command_timeout=10,
        server_settings={
            "application_name": "basketbot",
            "timezone": "UTC",
        },
    )


async def initialize_database(pool: Pool) -> None:
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('basketbot_schema_v1'))"
        )
        await connection.execute(SCHEMA_SQL)
        await connection.executemany(
            """
                INSERT INTO workouts (
                    workout_id, category, title, exp, description, sort_order
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (workout_id) DO UPDATE SET
                    category = EXCLUDED.category,
                    title = EXCLUDED.title,
                    exp = EXCLUDED.exp,
                    description = EXCLUDED.description,
                    sort_order = EXCLUDED.sort_order,
                    updated_at = NOW()
                """,
            [
                (
                    item["workout_id"],
                    item["category"],
                    item["title"],
                    item["exp"],
                    item["description"],
                    item["sort_order"],
                )
                for item in DEFAULT_WORKOUTS
            ],
        )


async def ping_database(pool: Pool) -> bool:
    try:
        return await pool.fetchval("SELECT TRUE") is True
    except (asyncpg.PostgresError, OSError, TimeoutError):
        return False


async def fetch_user_name(pool: Pool, user_id: int) -> str | None:
    return await pool.fetchval("SELECT name FROM users WHERE user_id = $1", user_id)


async def save_profile(
    pool: Pool,
    *,
    user_id: int,
    username: str | None,
    name: str,
    experience: str | None,
    goal: str | None,
    now: datetime,
) -> None:
    await pool.execute(
        """
        INSERT INTO users (
            user_id, username, name, experience, goal, last_workout
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            name = EXCLUDED.name,
            experience = EXCLUDED.experience,
            goal = EXCLUDED.goal,
            updated_at = NOW()
        """,
        user_id,
        username,
        name,
        experience,
        goal,
        now,
    )


async def fetch_profile(pool: Pool, user_id: int) -> Record | None:
    return await pool.fetchrow(
        "SELECT name, exp, streak FROM users WHERE user_id = $1",
        user_id,
    )


async def fetch_leaderboard(pool: Pool, limit: int = 10) -> Sequence[Record]:
    return await pool.fetch(
        """
        SELECT name, weekly_exp
        FROM users
        ORDER BY weekly_exp DESC, exp DESC, user_id
        LIMIT $1
        """,
        limit,
    )


async def add_experience(
    pool: Pool,
    *,
    user_id: int,
    amount: int,
    now: datetime,
) -> bool:
    updated_user_id = await pool.fetchval(
        """
        UPDATE users
        SET exp = exp + $1,
            weekly_exp = weekly_exp + $1,
            streak = streak + 1,
            last_workout = $2,
            last_inactive_notice = NULL,
            updated_at = NOW()
        WHERE user_id = $3
        RETURNING user_id
        """,
        amount,
        now,
        user_id,
    )
    return updated_user_id is not None


async def count_users(pool: Pool) -> int:
    return int(await pool.fetchval("SELECT COUNT(*) FROM users"))


async def fetch_users(pool: Pool, limit: int = 100) -> Sequence[Record]:
    return await pool.fetch(
        """
        SELECT user_id, username, name, exp, weekly_exp, streak, created_at
        FROM users
        ORDER BY created_at, user_id
        LIMIT $1
        """,
        limit,
    )


async def fetch_inactive_users(pool: Pool, deadline: datetime) -> Sequence[Record]:
    return await pool.fetch(
        """
        SELECT user_id, name
        FROM users
        WHERE last_workout < $1
          AND (
              last_inactive_notice IS NULL
              OR last_inactive_notice < $1
          )
        ORDER BY user_id
        """,
        deadline,
    )


async def mark_inactive_notice(pool: Pool, user_id: int, now: datetime) -> None:
    await pool.execute(
        """
        UPDATE users
        SET streak = 0,
            last_inactive_notice = $1,
            updated_at = NOW()
        WHERE user_id = $2
        """,
        now,
        user_id,
    )


async def fetch_workouts_by_category(pool: Pool, category: str) -> Sequence[Record]:
    return await pool.fetch(
        """
        SELECT workout_id, title
        FROM workouts
        WHERE category = $1 AND active = TRUE
        ORDER BY sort_order, workout_id
        """,
        category,
    )


async def fetch_workout(pool: Pool, workout_id: str) -> Record | None:
    return await pool.fetchrow(
        """
        SELECT workout_id, category, title, exp, description
        FROM workouts
        WHERE workout_id = $1 AND active = TRUE
        """,
        workout_id,
    )


async def fetch_materials(pool: Pool, workout_id: str) -> Sequence[Record]:
    return await pool.fetch(
        """
        SELECT material_id, material_type, value, label
        FROM workout_materials
        WHERE workout_id = $1
        ORDER BY sort_order, material_id
        """,
        workout_id,
    )


async def add_material(
    pool: Pool,
    *,
    workout_id: str,
    material_type: str,
    value: str,
    label: str | None = None,
) -> int:
    material_id = await pool.fetchval(
        """
        INSERT INTO workout_materials (workout_id, material_type, value, label)
        VALUES ($1, $2, $3, $4)
        RETURNING material_id
        """,
        workout_id,
        material_type,
        value,
        label,
    )
    return int(material_id)


async def delete_material(pool: Pool, material_id: int) -> bool:
    deleted_id = await pool.fetchval(
        """
        DELETE FROM workout_materials
        WHERE material_id = $1
        RETURNING material_id
        """,
        material_id,
    )
    return deleted_id is not None


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _record_to_json(record: Record) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in dict(record).items()}


async def export_snapshot(pool: Pool) -> dict[str, Any]:
    """Create an admin-only logical backup without writing to Render's disk."""
    async with (
        pool.acquire() as connection,
        connection.transaction(isolation="repeatable_read", readonly=True),
    ):
        users = await connection.fetch(
            """
                SELECT user_id, username, name, experience, goal, exp,
                       weekly_exp, streak, last_workout, last_inactive_notice,
                       created_at, updated_at
                FROM users
                ORDER BY user_id
                """
        )
        workouts = await connection.fetch(
            """
                SELECT workout_id, category, title, exp, description,
                       sort_order, active, created_at, updated_at
                FROM workouts
                ORDER BY sort_order, workout_id
                """
        )
        materials = await connection.fetch(
            """
                SELECT material_id, workout_id, material_type, value,
                       label, sort_order, created_at
                FROM workout_materials
                ORDER BY workout_id, sort_order, material_id
                """
        )

    return {
        "format": "basketbot-backup-v1",
        "generated_at": datetime.now().astimezone().isoformat(),
        "users": [_record_to_json(item) for item in users],
        "workouts": [_record_to_json(item) for item in workouts],
        "materials": [_record_to_json(item) for item in materials],
    }


async def prepare_weekly_reward_run(pool: Pool, week_start: date) -> Record:
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('basketbot_weekly_rewards'))"
        )
        existing = await connection.fetchrow(
            "SELECT * FROM weekly_reward_runs WHERE week_start = $1",
            week_start,
        )
        if existing is not None:
            return existing

        winners = await connection.fetch(
            """
                SELECT user_id
                FROM users
                WHERE weekly_exp > 0
                ORDER BY weekly_exp DESC, exp DESC, user_id
                LIMIT 2
                """
        )
        first_user_id = winners[0]["user_id"] if winners else None
        second_user_id = winners[1]["user_id"] if len(winners) > 1 else None

        result = await connection.fetchrow(
            """
                INSERT INTO weekly_reward_runs (
                    week_start, first_user_id, second_user_id
                )
                VALUES ($1, $2, $3)
                RETURNING *
                """,
            week_start,
            first_user_id,
            second_user_id,
        )
        await connection.execute("UPDATE users SET weekly_exp = 0, updated_at = NOW()")
        return result


async def mark_reward_notified(pool: Pool, week_start: date, position: int) -> None:
    if position == 1:
        column = "first_notified"
    elif position == 2:
        column = "second_notified"
    else:
        raise ValueError("position must be 1 or 2")

    await pool.execute(
        f"UPDATE weekly_reward_runs SET {column} = TRUE WHERE week_start = $1",
        week_start,
    )


async def import_users(
    pool: Pool,
    *,
    rows: Iterable[Mapping[str, Any]],
    source_sha256: str,
) -> tuple[bool, int]:
    prepared_rows = [
        (
            int(row["user_id"]),
            row.get("username"),
            row.get("name") or "Игрок",
            row.get("experience"),
            row.get("goal"),
            max(0, int(row.get("exp") or 0)),
            max(0, int(row.get("weekly_exp") or 0)),
            max(0, int(row.get("streak") or 0)),
            row.get("last_workout"),
        )
        for row in rows
    ]

    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtext('basketbot_sqlite_import'))"
        )
        previous_count = await connection.fetchval(
            "SELECT imported_rows FROM import_runs WHERE source_sha256 = $1",
            source_sha256,
        )
        if previous_count is not None:
            return False, int(previous_count)

        await connection.executemany(
            """
                INSERT INTO users (
                    user_id, username, name, experience, goal,
                    exp, weekly_exp, streak, last_workout
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (user_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    name = EXCLUDED.name,
                    experience = EXCLUDED.experience,
                    goal = EXCLUDED.goal,
                    exp = EXCLUDED.exp,
                    weekly_exp = EXCLUDED.weekly_exp,
                    streak = EXCLUDED.streak,
                    last_workout = EXCLUDED.last_workout,
                    updated_at = NOW()
                """,
            prepared_rows,
        )
        await connection.execute(
            """
                INSERT INTO import_runs (source_sha256, imported_rows)
                VALUES ($1, $2)
                """,
            source_sha256,
            len(prepared_rows),
        )
        return True, len(prepared_rows)
