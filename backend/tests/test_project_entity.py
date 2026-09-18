"""Tests for the Project entity's slug invariant.

The slug is the client-chosen, human-readable identifier that appears in
dashboard URLs: URL-safe by construction. The regex (lowercase letters and
digits separated by single hyphens, no leading/trailing hyphen) is the
entity's contract — tightened beyond the API's early ``[a-z0-9-]+`` sketch
because a slug is a web identifier, and formats are contract: loosening
later is cheap, tightening after clients depend on it is breaking.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tiber.domain.entities import Project


def make_project(*, slug: str) -> Project:
    """Build a project with the given slug."""
    return Project.create(user_id=uuid4(), name="My Application", slug=slug)


def test_valid_slug_is_accepted():
    """Single token and hyphen-separated tokens both construct."""
    assert make_project(slug="acme").slug == "acme"
    assert make_project(slug="acme-onboarding").slug == "acme-onboarding"
    assert make_project(slug="a1-b2").slug == "a1-b2"


def test_uppercase_is_rejected():
    """Slugs normalize nowhere: uppercase is a client error, not a coercion."""
    with pytest.raises(ValueError, match="slug"):
        make_project(slug="Acme")


def test_leading_or_trailing_hyphen_is_rejected():
    """A URL fragment '-acme' or 'acme-' would render as a broken path."""
    with pytest.raises(ValueError, match="slug"):
        make_project(slug="-acme")
    with pytest.raises(ValueError, match="slug"):
        make_project(slug="acme-")


def test_double_hyphen_is_rejected():
    """'acme--onboarding' encodes two separators for one boundary."""
    with pytest.raises(ValueError, match="slug"):
        make_project(slug="acme--onboarding")


def test_whitespace_and_empty_are_rejected():
    """Spaces and the empty string cannot appear in a URL path."""
    with pytest.raises(ValueError, match="slug"):
        make_project(slug="acme onboarding")
    with pytest.raises(ValueError, match="slug"):
        make_project(slug="")
