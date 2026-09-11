"""
High School Management System API

A FastAPI application that allows students to view and sign up
for extracurricular activities at Mergington High School.
"""

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.database import get_db
from src.models import Activity, Registration, User

app = FastAPI(
    title="Mergington High School API",
    description="API for viewing and signing up for extracurricular activities",
)

# Mount the static files directory
app.mount("/static", StaticFiles(directory=os.path.join(Path(__file__).parent, "static")), name="static")


def _get_or_create_user(db: Session, email: str) -> User:
    """Get an existing User by email or create one.

    Uses a nested transaction / savepoint so that the unique-constraint
    race on uq_users_email can be recovered without rolling back the
    outer transaction.
    """
    user = db.query(User).filter_by(email=email).one_or_none()
    if user is not None:
        return user

    try:
        with db.begin_nested():
            user = User(email=email)
            db.add(user)
            db.flush()
        return user
    except IntegrityError:
        existing = db.query(User).filter_by(email=email).one_or_none()
        if existing is not None:
            return existing
        raise


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


@app.get("/activities")
def get_activities(db: Session = Depends(get_db)):
    activities = db.query(Activity).order_by(Activity.id).all()
    result = {}
    for activity in activities:
        participants = [
            reg.user.email
            for reg in sorted(
                db.query(Registration)
                .filter_by(activity_id=activity.id)
                .all(),
                key=lambda r: r.id,
            )
        ]
        result[activity.name] = {
            "description": activity.description,
            "schedule": activity.schedule,
            "max_participants": activity.max_participants,
            "participants": participants,
        }
    return result


@app.post("/activities/{activity_name}/signup")
def signup_for_activity(
    activity_name: str, email: str, db: Session = Depends(get_db)
):
    """Sign up a student for an activity."""
    try:
        activity = (
            db.query(Activity).filter_by(name=activity_name).one_or_none()
        )
        if activity is None:
            raise HTTPException(
                status_code=404, detail="Activity not found"
            )

        user = _get_or_create_user(db, email)

        existing_reg = (
            db.query(Registration)
            .filter_by(user_id=user.id, activity_id=activity.id)
            .one_or_none()
        )
        if existing_reg is not None:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail="Student is already signed up",
            )

        try:
            with db.begin_nested():
                db.add(
                    Registration(
                        user_id=user.id, activity_id=activity.id
                    )
                )
                db.flush()
        except IntegrityError:
            existing_after_race = (
                db.query(Registration)
                .filter_by(user_id=user.id, activity_id=activity.id)
                .one_or_none()
            )
            if existing_after_race is not None:
                db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail="Student is already signed up",
                )
            raise

        db.commit()
        return {
            "message": f"Signed up {email} for {activity_name}"
        }
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


@app.delete("/activities/{activity_name}/unregister")
def unregister_from_activity(
    activity_name: str, email: str, db: Session = Depends(get_db)
):
    """Unregister a student from an activity."""
    activity = (
        db.query(Activity).filter_by(name=activity_name).one_or_none()
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity not found")

    user = db.query(User).filter_by(email=email).one_or_none()
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Student is not signed up for this activity",
        )

    registration = (
        db.query(Registration)
        .filter_by(user_id=user.id, activity_id=activity.id)
        .one_or_none()
    )
    if registration is None:
        raise HTTPException(
            status_code=400,
            detail="Student is not signed up for this activity",
        )

    db.delete(registration)
    db.commit()
    return {
        "message": f"Unregistered {email} from {activity_name}"
    }
