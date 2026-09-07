"""SQLAlchemy models for the Mergington High School API."""

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)

from src.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False)
    schedule = Column(String, nullable=False)
    max_participants = Column(Integer, nullable=False)


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    activity_id = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "activity_id"),
        ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["activity_id"],
            ["activities.id"],
            ondelete="RESTRICT",
        ),
    )
