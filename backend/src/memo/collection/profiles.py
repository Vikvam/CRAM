"""Profiles. Phase 1 has exactly one; the picker arrives with phase 4 (PLAN 6)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from memo.db.models import Profile
from memo.models.ids import new_id

DEFAULT_PROFILE = "me"


def get_or_create_profile(session: Session, name: str = DEFAULT_PROFILE) -> Profile:
    profile = session.scalar(select(Profile).where(Profile.name == name))
    if profile is None:
        profile = Profile(id=new_id("p"), name=name)
        session.add(profile)
        session.flush()
    return profile
