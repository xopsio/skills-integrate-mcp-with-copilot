"""SQLAlchemy models for the Mergington High School API."""

from sqlalchemy import (
    Column,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from src.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False, unique=True)

    registrations = relationship(
        "Registration", back_populates="user", passive_deletes="all"
    )


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=False)
    schedule = Column(String, nullable=False)
    max_participants = Column(Integer, nullable=False)

    registrations = relationship(
        "Registration", back_populates="activity", passive_deletes="all"
    )


class Registration(Base):
    __tablename__ = "registrations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    activity_id = Column(Integer, nullable=False)

    user = relationship("User", back_populates="registrations")
    activity = relationship("Activity", back_populates="registrations")

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
