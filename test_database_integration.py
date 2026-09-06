import os
import unittest
from datetime import datetime, timezone

import database

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not configured")
class DatabaseIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.pool = await database.create_pool(TEST_DATABASE_URL)
        await database.initialize_database(self.pool)
        await self.pool.execute(
            """
            TRUNCATE TABLE
                workout_materials,
                weekly_reward_runs,
                import_runs,
                users
            RESTART IDENTITY CASCADE
            """
        )

    async def asyncTearDown(self) -> None:
        await self.pool.close()

    async def test_profile_experience_material_and_backup_round_trip(self) -> None:
        now = datetime.now(timezone.utc)
        await database.save_profile(
            self.pool,
            user_id=123,
            username="player",
            name="Игрок",
            experience="exp_amateur",
            goal="goal_skills",
            now=now,
        )
        updated = await database.add_experience(
            self.pool,
            user_id=123,
            amount=50,
            now=now,
        )
        material_id = await database.add_material(
            self.pool,
            workout_id="dribble_base",
            material_type="link",
            value="https://example.com/training",
            label="Техника",
        )

        profile = await database.fetch_profile(self.pool, 123)
        users = await database.fetch_users(self.pool)
        snapshot = await database.export_snapshot(self.pool)

        self.assertTrue(updated)
        self.assertEqual(profile["exp"], 50)
        self.assertEqual(users[0]["user_id"], 123)
        self.assertEqual(users[0]["username"], "player")
        self.assertGreater(material_id, 0)
        self.assertEqual(len(snapshot["users"]), 1)
        self.assertEqual(snapshot["users"][0]["user_id"], 123)
        self.assertEqual(
            snapshot["materials"][0]["value"], "https://example.com/training"
        )

    async def test_initialization_does_not_delete_existing_users(self) -> None:
        await database.save_profile(
            self.pool,
            user_id=456,
            username=None,
            name="Existing user",
            experience="exp_novice",
            goal="goal_phys",
            now=datetime.now(timezone.utc),
        )

        await database.initialize_database(self.pool)

        self.assertEqual(
            await database.fetch_user_name(self.pool, 456), "Existing user"
        )


if __name__ == "__main__":
    unittest.main()
