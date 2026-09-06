import sqlite3
import tempfile
import unittest
from pathlib import Path

import database
import main
from content import CATEGORIES, DEFAULT_WORKOUTS
from migrate_sqlite import read_sqlite_users


class ConfigurationTests(unittest.TestCase):
    def test_neon_url_is_normalized_for_asyncpg(self) -> None:
        source = (
            "postgres://user:password@example.neon.tech/app"
            "?sslmode=require&channel_binding=require"
        )
        normalized = database.normalize_database_url(source)
        self.assertTrue(normalized.startswith("postgresql://"))
        self.assertIn("sslmode=require", normalized)
        self.assertNotIn("channel_binding", normalized)

    def test_only_http_links_are_accepted(self) -> None:
        self.assertTrue(main.is_http_url("https://example.com/video"))
        self.assertTrue(main.is_http_url("http://example.com"))
        self.assertFalse(main.is_http_url("javascript:alert(1)"))
        self.assertFalse(main.is_http_url("example.com"))


class ContentTests(unittest.TestCase):
    def test_default_workouts_have_unique_valid_ids(self) -> None:
        workout_ids = [item["workout_id"] for item in DEFAULT_WORKOUTS]
        self.assertEqual(len(workout_ids), len(set(workout_ids)))
        for item in DEFAULT_WORKOUTS:
            self.assertIn(item["category"], CATEGORIES)
            self.assertGreaterEqual(item["exp"], 0)


class SqliteMigrationTests(unittest.TestCase):
    def test_current_sqlite_schema_is_read_without_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "basket_startup.db"
            connection = sqlite3.connect(path)
            try:
                connection.execute(
                    """
                    CREATE TABLE users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        name TEXT,
                        experience TEXT,
                        goal TEXT,
                        exp INTEGER DEFAULT 0,
                        weekly_exp INTEGER DEFAULT 0,
                        streak INTEGER DEFAULT 0,
                        last_workout TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO users (
                        user_id, username, name, experience, goal,
                        exp, weekly_exp, streak, last_workout
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        123,
                        "player",
                        "Игрок",
                        "exp_amateur",
                        "goal_skills",
                        150,
                        50,
                        2,
                        "2026-08-31 07:00:00",
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            users = read_sqlite_users(path)

        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["user_id"], 123)
        self.assertEqual(users[0]["exp"], 150)
        self.assertIsNotNone(users[0]["last_workout"].tzinfo)


if __name__ == "__main__":
    unittest.main()
