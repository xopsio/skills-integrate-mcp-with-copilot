"""Seed the database with the current demo data from the application."""

from src.database import SessionLocal
from src.models import Activity, Registration, User

SEED_ACTIVITIES = [
    {
        "name": "Chess Club",
        "description": "Learn strategies and compete in chess tournaments",
        "schedule": "Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 12,
        "participants": ["michael@mergington.edu", "daniel@mergington.edu"],
    },
    {
        "name": "Programming Class",
        "description": "Learn programming fundamentals and build software projects",
        "schedule": "Tuesdays and Thursdays, 3:30 PM - 4:30 PM",
        "max_participants": 20,
        "participants": ["emma@mergington.edu", "sophia@mergington.edu"],
    },
    {
        "name": "Gym Class",
        "description": "Physical education and sports activities",
        "schedule": "Mondays, Wednesdays, Fridays, 2:00 PM - 3:00 PM",
        "max_participants": 30,
        "participants": ["john@mergington.edu", "olivia@mergington.edu"],
    },
    {
        "name": "Soccer Team",
        "description": "Join the school soccer team and compete in matches",
        "schedule": "Tuesdays and Thursdays, 4:00 PM - 5:30 PM",
        "max_participants": 22,
        "participants": ["liam@mergington.edu", "noah@mergington.edu"],
    },
    {
        "name": "Basketball Team",
        "description": "Practice and play basketball with the school team",
        "schedule": "Wednesdays and Fridays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
        "participants": ["ava@mergington.edu", "mia@mergington.edu"],
    },
    {
        "name": "Art Club",
        "description": "Explore your creativity through painting and drawing",
        "schedule": "Thursdays, 3:30 PM - 5:00 PM",
        "max_participants": 15,
        "participants": ["amelia@mergington.edu", "harper@mergington.edu"],
    },
    {
        "name": "Drama Club",
        "description": "Act, direct, and produce plays and performances",
        "schedule": "Mondays and Wednesdays, 4:00 PM - 5:30 PM",
        "max_participants": 20,
        "participants": ["ella@mergington.edu", "scarlett@mergington.edu"],
    },
    {
        "name": "Math Club",
        "description": "Solve challenging problems and participate in math competitions",
        "schedule": "Tuesdays, 3:30 PM - 4:30 PM",
        "max_participants": 10,
        "participants": ["james@mergington.edu", "benjamin@mergington.edu"],
    },
    {
        "name": "Debate Team",
        "description": "Develop public speaking and argumentation skills",
        "schedule": "Fridays, 4:00 PM - 5:30 PM",
        "max_participants": 12,
        "participants": ["charlotte@mergington.edu", "henry@mergington.edu"],
    },
    {
        "name": "GitHub Skills",
        "description": (
            "Learn practical coding and collaboration skills through GitHub. "
            "Part of the GitHub Certifications program to help with "
            "college applications."
        ),
        "schedule": "Wednesdays, 3:30 PM - 5:00 PM",
        "max_participants": 25,
        "participants": [],
    },
]


def _preflight(activities):
    """Validate the seed dataset before any database writes."""
    seen_names = set()
    for entry in activities:
        if entry["name"] in seen_names:
            raise ValueError(f"duplicate activity name in seed data: {entry['name']!r}")
        seen_names.add(entry["name"])

        seen_emails = set()
        for email in entry["participants"]:
            if email in seen_emails:
                raise ValueError(
                    f"duplicate participant {email!r} within activity "
                    f"{entry['name']!r}"
                )
            seen_emails.add(email)


def _get_or_create_user(session, email):
    user = session.query(User).filter_by(email=email).one_or_none()
    if user is None:
        user = User(email=email)
        session.add(user)
        session.flush()
    return user


def _get_or_create_activity(session, name, description, schedule, max_participants):
    activity = session.query(Activity).filter_by(name=name).one_or_none()
    if activity is None:
        activity = Activity(
            name=name,
            description=description,
            schedule=schedule,
            max_participants=max_participants,
        )
        session.add(activity)
        session.flush()
    else:
        if (
            activity.description != description
            or activity.schedule != schedule
            or activity.max_participants != max_participants
        ):
            raise ValueError(
                f"conflicting existing activity {name!r}: "
                f"description={activity.description!r} "
                f"schedule={activity.schedule!r} "
                f"max_participants={activity.max_participants!r}"
            )
    return activity


def _has_registration(session, user_id, activity_id):
    return (
        session.query(Registration)
        .filter_by(user_id=user_id, activity_id=activity_id)
        .one_or_none()
        is not None
    )


def run():
    """Seed the database. Safe to rerun; idempotent for the demo dataset."""
    _preflight(SEED_ACTIVITIES)

    session = SessionLocal()
    try:
        for entry in SEED_ACTIVITIES:
            activity = _get_or_create_activity(
                session,
                entry["name"],
                entry["description"],
                entry["schedule"],
                entry["max_participants"],
            )
            for email in entry["participants"]:
                user = _get_or_create_user(session, email)
                if _has_registration(session, user.id, activity.id):
                    continue
                session.add(Registration(user_id=user.id, activity_id=activity.id))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run()
