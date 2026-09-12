"""Focused endpoint tests for the database-backed activity API.

This module is intentionally self-contained:

* It pins DATABASE_URL to a process-unique temp SQLite file *before* the
  application modules are imported, so merely importing the module has
  no destructive DB side effects.
* Per-test setup re-runs `alembic upgrade head` and the seed function
  against a freshly reset DB so that each test starts from the same
  migrated + seeded state.
* Tests do not rely on execution order; each test re-creates the DB.
"""

import os
import tempfile
import unittest
import unittest.mock

# Create a process-unique temp directory and pin DATABASE_URL to a SQLite
# file inside it BEFORE importing any src.* module that reads DATABASE_URL
# at import time.
_TMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DIR.name}/test.db"

# Standard library + our own imports
import sys  # noqa: E402
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import alembic.command  # noqa: E402
import alembic.config  # noqa: E402

from src.app import (  # noqa: E402
    _get_or_create_user,
    get_activities,
    signup_for_activity,
    unregister_from_activity,
)
from src.database import SessionLocal, engine  # noqa: E402
from src.models import Activity, Registration, User  # noqa: E402


def _upgrade_head():
    cfg = alembic.config.Config(
        os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    )
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("prepend_sys_path", ".")
    alembic.command.upgrade(cfg, "head")


def _seed():
    from src.seed import run as seed_run
    seed_run()


def setUpModule():
    # Safety net: if any module-level import side-effect runs migrations
    # or seeds, this assertion will fail at suite start. We assert the DB
    # is currently empty so the per-test reset is the only place data
    # appears.
    _upgrade_head()
    s = SessionLocal()
    try:
        count = s.query(Activity).count()
        assert count == 0, f"DB should be empty after initial upgrade, got {count} activities"
    finally:
        s.close()


def tearDownModule():
    engine.dispose()
    _TMP_DIR.cleanup()


class _BaseApiTests(unittest.TestCase):
    """Provides a clean migrated+seeded DB for each test."""

    def setUp(self):
        # Wipe and reset the SQLite file before each test so each test
        # starts from the same migrated + seeded state.
        self._reset_db()
        _upgrade_head()
        _seed()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()
        self._close_engine()

    def _close_engine(self):
        # Dispose pooled connections so the file can be replaced.
        engine.dispose()

    def _reset_db(self):
        self._close_engine()
        path = os.path.join(_TMP_DIR.name, "test.db")
        if os.path.exists(path):
            os.remove(path)


class GetActivitiesTests(_BaseApiTests):
    def test_get_returns_seed_structure(self):
        result = get_activities(db=self.db)
        self.assertEqual(
            set(result.keys()),
            {
                "Chess Club", "Programming Class", "Gym Class", "Soccer Team",
                "Basketball Team", "Art Club", "Drama Club", "Math Club",
                "Debate Team", "GitHub Skills",
            },
        )
        chess = result["Chess Club"]
        self.assertEqual(
            chess["description"],
            "Learn strategies and compete in chess tournaments",
        )
        self.assertEqual(chess["schedule"], "Fridays, 3:30 PM - 5:00 PM")
        self.assertEqual(chess["max_participants"], 12)
        self.assertEqual(
            chess["participants"],
            ["michael@mergington.edu", "daniel@mergington.edu"],
        )
        self.assertEqual(result["GitHub Skills"]["participants"], [])

    def test_get_does_not_leak_database_ids(self):
        result = get_activities(db=self.db)
        for key in result.keys():
            self.assertNotIn("id", key)
        for value in result.values():
            for forbidden in (
                "id", "registration_id", "db_id",
                "activity_id", "user_id",
            ):
                self.assertNotIn(forbidden, value)
            for participant in value["participants"]:
                self.assertNotIn("id", participant)


class SignupTests(_BaseApiTests):
    def test_missing_activity_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            signup_for_activity(
                activity_name="Nonexistent",
                email="x@x.com",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Activity not found")

    def test_new_email_creates_user_and_registration(self):
        email = "newuser@example.com"
        result = signup_for_activity(
            activity_name="Chess Club",
            email=email,
            db=self.db,
        )
        self.assertEqual(
            result,
            {"message": f"Signed up {email} for Chess Club"},
        )

        fresh = SessionLocal()
        try:
            u = fresh.query(User).filter_by(email=email).one()
            r = fresh.query(Registration).filter_by(user_id=u.id).one()
            self.assertEqual(r.activity.name, "Chess Club")
        finally:
            fresh.close()

    def test_same_email_two_activities_one_user_two_regs(self):
        email = "shared@example.com"
        signup_for_activity(
            activity_name="Chess Club", email=email, db=self.db,
        )
        signup_for_activity(
            activity_name="Programming Class", email=email, db=self.db,
        )
        fresh = SessionLocal()
        try:
            users = fresh.query(User).filter_by(email=email).all()
            self.assertEqual(len(users), 1)
            regs = fresh.query(Registration).filter_by(
                user_id=users[0].id
            ).all()
            self.assertEqual(len(regs), 2)
            self.assertEqual(
                {r.activity.name for r in regs},
                {"Chess Club", "Programming Class"},
            )
        finally:
            fresh.close()

    def test_duplicate_returns_exact_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            signup_for_activity(
                activity_name="Chess Club",
                email="michael@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail, "Student is already signed up"
        )

    def test_duplicate_unique_constraint_protects(self):
        # Manually attempt to add a duplicate registration row bypassing
        # the endpoint. The unique constraint must still raise.
        fresh = SessionLocal()
        try:
            u = fresh.query(User).filter_by(
                email="michael@mergington.edu"
            ).one()
            a = fresh.query(Activity).filter_by(name="Chess Club").one()
            from sqlalchemy.exc import IntegrityError
            with self.assertRaises(IntegrityError):
                fresh.add(
                    Registration(user_id=u.id, activity_id=a.id)
                )
                fresh.flush()
            fresh.rollback()
        finally:
            fresh.close()

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            signup_for_activity(
                activity_name="Chess Club",
                email="michael@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail, "Student is already signed up"
        )

    def test_past_max_participants_not_rejected(self):
        for i in range(40):
            signup_for_activity(
                activity_name="Gym Class",
                email=f"extra{i}@example.com",
                db=self.db,
            )
        fresh = SessionLocal()
        try:
            a = fresh.query(Activity).filter_by(name="Gym Class").one()
            count = fresh.query(Registration).filter_by(
                activity_id=a.id
            ).count()
            self.assertEqual(count, 42)
        finally:
            fresh.close()


class UnregisterTests(_BaseApiTests):
    def test_missing_activity_404(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            unregister_from_activity(
                activity_name="Nonexistent",
                email="michael@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "Activity not found")

    def test_unknown_email_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            unregister_from_activity(
                activity_name="Chess Club",
                email="unknown@example.com",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail,
            "Student is not signed up for this activity",
        )

    def test_existing_user_not_registered_for_activity_400(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            unregister_from_activity(
                activity_name="Chess Club",
                email="emma@mergington.edu",
                db=self.db,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(
            ctx.exception.detail,
            "Student is not signed up for this activity",
        )

    def test_success_removes_only_registration(self):
        result = unregister_from_activity(
            activity_name="Chess Club",
            email="michael@mergington.edu",
            db=self.db,
        )
        self.assertEqual(
            result,
            {"message": "Unregistered michael@mergington.edu from Chess Club"},
        )
        fresh = SessionLocal()
        try:
            u = fresh.query(User).filter_by(
                email="michael@mergington.edu"
            ).one()
            self.assertIsNotNone(u)
            chess = fresh.query(Activity).filter_by(name="Chess Club").one()
            reg = fresh.query(Registration).filter_by(
                user_id=u.id, activity_id=chess.id
            ).one_or_none()
            self.assertIsNone(reg)
            daniel = fresh.query(User).filter_by(
                email="daniel@mergington.edu"
            ).one()
            daniel_reg = fresh.query(Registration).filter_by(
                user_id=daniel.id, activity_id=chess.id
            ).one_or_none()
            self.assertIsNotNone(daniel_reg)
        finally:
            fresh.close()

    def test_success_persists_across_sessions(self):
        signup_for_activity(
            activity_name="Chess Club",
            email="persist@example.com",
            db=self.db,
        )
        # Open a fresh Session and confirm the row exists.
        fresh = SessionLocal()
        try:
            u = fresh.query(User).filter_by(
                email="persist@example.com"
            ).one()
            self.assertIsNotNone(u)
        finally:
            fresh.close()
        # Unregister and confirm via fresh Session
        unregister_from_activity(
            activity_name="Chess Club",
            email="persist@example.com",
            db=self.db,
        )
        fresh = SessionLocal()
        try:
            u = fresh.query(User).filter_by(
                email="persist@example.com"
            ).one()
            a = fresh.query(Activity).filter_by(name="Chess Club").one()
            reg = fresh.query(Registration).filter_by(
                user_id=u.id, activity_id=a.id
            ).one_or_none()
            self.assertIsNone(reg)
        finally:
            fresh.close()


class SessionDependencyTests(_BaseApiTests):
    def test_session_closes_after_dependency_exit(self):
        from src.database import get_db
        gen = get_db()
        session = next(gen)
        try:
            next(gen)
        except StopIteration:
            pass
        # Spy on Session.close to confirm the dependency's finally block ran
        from sqlalchemy.orm import Session
        closed = []

        original_close = Session.close

        def spy(self):
            closed.append(self)
            original_close(self)

        Session.close = spy
        try:
            gen2 = get_db()
            s2 = next(gen2)
            try:
                next(gen2)
            except StopIteration:
                pass
            self.assertTrue(any(s is s2 for s in closed))
        finally:
            Session.close = original_close


class UserEmailRaceRecoveryTests(_BaseApiTests):
    """Verify that _get_or_create_user recovers from a real UNIQUE
    violation on uq_users_email.

    This is a deterministically instrumented race window with a real
    database UNIQUE failure — NOT a real concurrent integration test.
    The competing User row is committed with a separate Session, and only
    the helper's FIRST email lookup is forced to miss; the INSERT itself
    is not mocked, so SQLite raises the actual IntegrityError inside the
    savepoint, and the recovery lookup runs the original implementation.
    """

    def test_recovery_branch_with_real_unique_violation(self):
        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.orm import Session as _Session

        email = "race@example.com"

        # 1. Commit the competing User with a separate Session.
        priming = SessionLocal()
        try:
            competing = User(email=email)
            priming.add(competing)
            priming.commit()
            competing_id = competing.id
        finally:
            priming.close()

        # 2. Call the helper with another Session.
        fresh = SessionLocal()
        try:
            original_query = _Session.query
            first_lookup_forced = {"forced": False}

            def miss_first_email_lookup(self_, *entity, **kw):
                real_query = original_query(self_, *entity, **kw)
                # Narrow instrumentation: only the first query (the helper's
                # initial email lookup) gets a one_or_none that misses; the
                # recovery lookup runs the original implementation.
                if not first_lookup_forced["forced"]:
                    first_lookup_forced["forced"] = True
                    real_query.one_or_none = lambda: None
                return real_query

            rollback_calls = {"n": 0}
            original_rollback = _Session.rollback

            def counting_rollback(self_, *args, **kwargs):
                rollback_calls["n"] += 1
                return original_rollback(self_, *args, **kwargs)

            original_flush = _Session.flush
            raised_exceptions = []
            nested_tx_at_failure = []

            def spying_flush(self_, *args, **kwargs):
                try:
                    return original_flush(self_, *args, **kwargs)
                except Exception as exc:
                    raised_exceptions.append(exc)
                    # Record whether a nested transaction (savepoint) was
                    # active at the moment the real DB error surfaced.
                    nested_tx_at_failure.append(self_.in_nested_transaction())
                    raise

            try:
                _Session.query = miss_first_email_lookup
                _Session.rollback = counting_rollback
                _Session.flush = spying_flush
                result = _get_or_create_user(fresh, email)
            finally:
                _Session.query = original_query
                _Session.rollback = original_rollback
                _Session.flush = original_flush

            # Assertions
            self.assertTrue(
                first_lookup_forced["forced"],
                "first lookup should have been forced to miss",
            )
            # The duplicate INSERT reached SQLite: the real flush raised
            # exactly one IntegrityError whose orig is a genuine
            # sqlite3.IntegrityError (i.e. not a mocked exception).
            import sqlite3
            self.assertEqual(
                len(raised_exceptions), 1,
                "exactly one real IntegrityError should have been raised by flush()",
            )
            real_exc = raised_exceptions[0]
            self.assertIsInstance(real_exc, IntegrityError)
            self.assertIsInstance(
                real_exc.orig, sqlite3.IntegrityError,
                "the IntegrityError must originate from the real SQLite driver",
            )
            # The genuine UNIQUE violation must have occurred while the
            # nested transaction (savepoint) was active.
            self.assertEqual(
                nested_tx_at_failure, [True],
                "the real UNIQUE failure must happen inside the savepoint",
            )
            self.assertIsNotNone(result)
            self.assertEqual(result.email, email)
            self.assertEqual(
                result.id, competing_id,
                "recovered User must be the committed competing User",
            )
            self.assertEqual(
                rollback_calls["n"], 0,
                "expected-recovery path must NOT call full Session.rollback()",
            )

            # Session must remain usable after recovery.
            usable = fresh.query(Activity).first()
            self.assertIsNotNone(usable)

        finally:
            fresh.close()

        # Exactly one User with that email afterwards.
        verify = SessionLocal()
        try:
            count = verify.query(User).filter_by(email=email).count()
            self.assertEqual(count, 1)
        finally:
            verify.close()


if __name__ == "__main__":
    unittest.main()
