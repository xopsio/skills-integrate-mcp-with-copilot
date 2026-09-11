"""Focused endpoint tests for the database-backed activity API."""

import os
import sys
import unittest

# Ensure repo root is on path so `src` package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force a temp DB BEFORE importing the app
_TEST_DB_PATH = "/tmp/test_mergington_api.db"
if os.path.exists(_TEST_DB_PATH):
    os.remove(_TEST_DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src import app as app_module  # noqa: E402
from src.app import (  # noqa: E402
    get_activities,
    signup_for_activity,
    unregister_from_activity,
)
from src.database import DATABASE_URL, SessionLocal, engine  # noqa: E402
from src.models import Activity, Registration, User  # noqa: E402

# Bring up schema + seed using the SAME DATABASE_URL the app will use
import alembic.config  # noqa: E402
import alembic.command  # noqa: E402


def _upgrade():
    cfg = alembic.config.Config(
        os.path.join(
            os.path.dirname(__file__), "..", "alembic.ini"
        )
    )
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("prepend_sys_path", ".")
    alembic.command.upgrade(cfg, "head")


def _seed():
    from src.seed import run as seed_run
    seed_run()


_upgrade()
_seed()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.db = SessionLocal()
        # We don't commit here; test endpoints own their txns.
        self._db_cm = None

    def tearDown(self):
        self.db.close()

    # ------- helpers -------

    def _fresh_db(self):
        return SessionLocal()

    # ------- GET /activities -------

    def test_get_returns_seed_structure(self):
        result = get_activities(db=self.db)
        self.assertEqual(set(result.keys()), {
            "Chess Club", "Programming Class", "Gym Class", "Soccer Team",
            "Basketball Team", "Art Club", "Drama Club", "Math Club",
            "Debate Team", "GitHub Skills",
        })
        chess = result["Chess Club"]
        self.assertEqual(chess["description"], "Learn strategies and compete in chess tournaments")
        self.assertEqual(chess["schedule"], "Fridays, 3:30 PM - 5:00 PM")
        self.assertEqual(chess["max_participants"], 12)
        self.assertEqual(chess["participants"], ["michael@mergington.edu", "daniel@mergington.edu"])
        # GitHub Skills should be present with empty participants
        self.assertEqual(result["GitHub Skills"]["participants"], [])

    def test_get_does_not_leak_database_ids(self):
        result = get_activities(db=self.db)
        # Top-level keys must be activity names only
        for key in result.keys():
            self.assertNotIn("id", key)
        for value in result.values():
            # No id/registration_id/db_id/etc. allowed in the payload
            for forbidden in ("id", "registration_id", "db_id", "activity_id", "user_id"):
                self.assertNotIn(forbidden, value)
            for p in value["participants"]:
                self.assertNotIn("id", p)

    # ------- signup -------

    def test_signup_missing_activity_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            signup_for_activity(activity_name="Nonexistent", email="x@x.com", db=self.db)
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Activity not found")

    def test_signup_new_email_creates_user_and_registration(self):
        new_email = "newuser@example.com"
        result = signup_for_activity(activity_name="Chess Club", email=new_email, db=self.db)
        self.assertEqual(result, {"message": f"Signed up {new_email} for Chess Club"})

        fresh = self._fresh_db()
        try:
            u = fresh.query(User).filter_by(email=new_email).one()
            self.assertIsNotNone(u)
            r = fresh.query(Registration).filter_by(user_id=u.id).one()
            self.assertEqual(r.activity.name, "Chess Club")
        finally:
            fresh.close()

    def test_signup_same_email_two_activities_one_user_two_regs(self):
        email = "shared@example.com"
        signup_for_activity(activity_name="Chess Club", email=email, db=self.db)
        signup_for_activity(activity_name="Programming Class", email=email, db=self.db)

        fresh = self._fresh_db()
        try:
            users = fresh.query(User).filter_by(email=email).all()
            self.assertEqual(len(users), 1, "expected exactly one User row")
            regs = fresh.query(Registration).filter_by(user_id=users[0].id).all()
            self.assertEqual(len(regs), 2, "expected exactly two Registration rows")
            names = {r.activity.name for r in regs}
            self.assertEqual(names, {"Chess Club", "Programming Class"})
        finally:
            fresh.close()

    def test_signup_duplicate_returns_exact_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            signup_for_activity(
                activity_name="Chess Club",
                email="michael@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Student is already signed up")

    def test_signup_duplicate_unique_constraint_still_protects(self):
        # Manually insert a second registration with same (user_id, activity_id)
        # bypassing the endpoint, then endpoint signup must still produce 400.
        fresh = self._fresh_db()
        try:
            u = fresh.query(User).filter_by(email="michael@mergington.edu").one()
            a = fresh.query(Activity).filter_by(name="Chess Club").one()
            # Should already exist; this just confirms the constraint is in place
            existing = (
                fresh.query(Registration)
                .filter_by(user_id=u.id, activity_id=a.id)
                .one_or_none()
            )
            self.assertIsNotNone(existing)
            from sqlalchemy.exc import IntegrityError
            with self.assertRaises(IntegrityError):
                fresh.add(Registration(user_id=u.id, activity_id=a.id))
                fresh.flush()
            fresh.rollback()
        finally:
            fresh.close()

        # Endpoint must still refuse
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            signup_for_activity(
                activity_name="Chess Club",
                email="michael@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Student is already signed up")

    def test_signup_past_max_participants_not_rejected(self):
        # Gym Class has max_participants=30, currently 2 participants
        # Add many more without rejection.
        for i in range(40):
            signup_for_activity(
                activity_name="Gym Class",
                email=f"extra{i}@example.com",
                db=self.db,
            )
        fresh = self._fresh_db()
        try:
            a = fresh.query(Activity).filter_by(name="Gym Class").one()
            regs = fresh.query(Registration).filter_by(activity_id=a.id).count()
            self.assertEqual(regs, 42)
        finally:
            fresh.close()

    # ------- unregister -------

    def test_unregister_missing_activity_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            unregister_from_activity(
                activity_name="Nonexistent",
                email="michael@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Activity not found")

    def test_unregister_unknown_email_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            unregister_from_activity(
                activity_name="Chess Club",
                email="unknown@example.com",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Student is not signed up for this activity")

    def test_unregister_user_not_registered_for_activity_400(self):
        # 'emma@mergington.edu' exists (in Programming Class), not in Chess Club
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            unregister_from_activity(
                activity_name="Chess Club",
                email="emma@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "Student is not signed up for this activity")

    def test_unregister_success_removes_only_registration(self):
        result = unregister_from_activity(
            activity_name="Chess Club",
            email="michael@mergington.edu",
            db=self.db,
        )
        self.assertEqual(result, {"message": "Unregistered michael@mergington.edu from Chess Club"})

        fresh = self._fresh_db()
        try:
            u = fresh.query(User).filter_by(email="michael@mergington.edu").one()
            self.assertIsNotNone(u, "User must NOT be deleted by unregister")
            chess = fresh.query(Activity).filter_by(name="Chess Club").one()
            reg = (
                fresh.query(Registration)
                .filter_by(user_id=u.id, activity_id=chess.id)
                .one_or_none()
            )
            self.assertIsNone(reg)
            # Daniel should still be in Chess Club
            daniel = fresh.query(User).filter_by(email="daniel@mergington.edu").one()
            daniel_reg = (
                fresh.query(Registration)
                .filter_by(user_id=daniel.id, activity_id=chess.id)
                .one_or_none()
            )
            self.assertIsNotNone(daniel_reg)
        finally:
            fresh.close()

    # ------- session dependency closes -------

    def test_request_session_closes_after_request(self):
        # Patch Session.close to record invocations, then call the dependency
        # generator and ensure close() ran in the finally block.
        from src import database as db_mod
        real_close = db_mod.SessionLocal().__class__.close
        call_log = []

        def spy_close(self):
            call_log.append(self)
            real_close(self)

        from sqlalchemy.orm import Session
        original_close = Session.close
        Session.close = spy_close
        try:
            from src.database import get_db
            gen = get_db()
            session = next(gen)
            try:
                next(gen)
            except StopIteration:
                pass
            self.assertTrue(len(call_log) >= 1, "Session.close() was not called")
            self.assertIs(session, call_log[-1])
        finally:
            Session.close = original_close


class UserEmailRaceRecoveryTests(unittest.TestCase):
    """Verify that the _get_or_create_user savepoint path recovers from
    a uq_users_email race.  We simulate the race by pre-creating a User
    inside an outside transaction and committing it before the endpoint
    code path attempts its nested create."""

    def setUp(self):
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_user_get_or_create_reuses_existing_user(self):
        # Simulate a competing insert: pre-create a User outside our flow.
        email = "race@example.com"
        # First, force-create via session directly so the row exists
        existing = User(email=email)
        self.db.add(existing)
        self.db.commit()

        # Now call the helper. It will hit the IntegrityError path on the
        # nested savepoint and recover by reading the existing row.
        from src.app import _get_or_create_user
        result = _get_or_create_user(self.db, email)
        self.assertIsNotNone(result)
        self.assertEqual(result.email, email)
        self.assertEqual(result.id, existing.id)
        # No double User created
        fresh = SessionLocal()
        try:
            count = fresh.query(User).filter_by(email=email).count()
            self.assertEqual(count, 1)
        finally:
            fresh.close()


if __name__ == "__main__":
    unittest.main()
