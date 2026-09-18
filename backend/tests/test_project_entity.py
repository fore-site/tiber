"""Tests for the Project entity's derived slug.

The slug is derived once from the name on every construction path —
clients never author it — so the format regex is a *generator output
contract*, not a frozen client-facing format: it pins what the
derivation may produce, and it stays enforced for any slug supplied
via reconstitute().

Per-user slug uniqueness is what enforces project name uniqueness,
because derivation collapses name variants ("My App" and "my.app"
derive to the same slug) — a name conflict therefore surfaces as a
409 on the slug constraint at persistence time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import Project
from tiber.domain.exceptions import InvalidProjectStateError


def make_project(name: str, **overrides) -> Project:
    """Build a project with the given name."""
    kwargs = dict(user_id=uuid4(), name=name)
    kwargs.update(overrides)
    return Project.create(**kwargs)


# --- Derivation ---


def test_name_derives_to_lowercase_hyphenated_slug():
    """The canonical case: spaces become single hyphens, case is folded."""
    assert make_project("My App").slug == "my-app"
    assert make_project("Acme Onboarding").slug == "acme-onboarding"


def test_name_variants_collapse_to_the_same_slug():
    """The pair that makes slug uniqueness imply name uniqueness."""
    assert make_project("My App").slug == make_project("my.app").slug
    assert make_project("My App").slug == make_project("MY APP").slug


def test_separator_runs_collapse_without_edge_hyphens():
    """Leading/trailing separators vanish; runs collapse to one hyphen."""
    assert make_project("  A  B ").slug == "a-b"
    assert make_project("Acme -- Co!").slug == "acme-co"


def test_digits_and_mixed_tokens_survive():
    """Digits are kept inside tokens, not treated as separators."""
    assert make_project("My App 2.0").slug == "my-app-2-0"


# --- Invalid names ---


def test_name_without_ascii_token_is_rejected():
    """No ASCII alnum token means nothing to derive from: reject the name."""
    with pytest.raises(InvalidProjectStateError, match="ASCII"):
        make_project("???")
    with pytest.raises(InvalidProjectStateError, match="ASCII"):
        make_project("日本語")


def test_empty_name_is_rejected():
    """An empty (or whitespace-only) name is invalid before derivation."""
    with pytest.raises(InvalidProjectStateError, match="name"):
        make_project("")
    with pytest.raises(InvalidProjectStateError, match="name"):
        make_project("   ")


def test_create_no_longer_accepts_slug():
    """The signature is the contract: slug is not a caller input."""
    with pytest.raises(TypeError):
        Project.create(user_id=uuid4(), name="My App", slug="imposed")


# --- Rehydration: persisted identity is loaded, never re-derived ---


def test_reconstitute_loads_stored_slug_as_is():
    """A stored slug wins even when it differs from a fresh derivation.

    Guards against a future derivation-algorithm change silently
    rewriting existing projects' identities on rehydration.
    """
    restored = Project.reconstitute(
        id=uuid4(),
        user_id=uuid4(),
        name="Acme Co",  # would re-derive "acme-co"
        slug="acme",  # stored identity from an older derivation
        description=None,
        created_at=datetime.now(UTC),
        archived_at=None,
    )

    assert restored.slug == "acme"


def test_reconstitute_rejects_malformed_stored_slug():
    """The format guard still applies to slugs supplied from storage."""
    with pytest.raises(InvalidProjectStateError, match="slug"):
        Project.reconstitute(
            id=uuid4(),
            user_id=uuid4(),
            name="Acme Co",
            slug="Not A Slug",
            description=None,
            created_at=datetime.now(UTC),
            archived_at=None,
        )


# --- Rename: slug is the normalized current name, so it follows ---


def test_rename_rederives_the_slug():
    """The slug tracks the name: rename to a new token, slug follows."""
    project = make_project("My App")

    renamed = project.rename("Acme Onboarding")

    assert renamed.name == "Acme Onboarding"
    assert renamed.slug == "acme-onboarding"


def test_rename_preserves_identity_and_created_at():
    """rename() is a transition: same id, created_at unchanged, slug new."""
    project = make_project("My App")

    renamed = project.rename("New Name")

    assert renamed.id == project.id
    assert renamed.created_at == project.created_at
    assert renamed.user_id == project.user_id


def test_rename_to_name_variant_yields_same_slug():
    """Renaming to a variant of another name is a conflict preview.

    'My App' -> 'my.app' normalizes to the slug 'my-app' — if another
    project of the same user holds it, the service pre-check and the DB
    constraint both fail the rename with ProjectNameConflictError.
    """
    project = make_project("My App")

    renamed = project.rename("my.app")

    assert renamed.slug == project.slug


def test_rename_rejects_invalid_names():
    """rename() applies the same name rules as construction."""
    project = make_project("My App")

    with pytest.raises(InvalidProjectStateError, match="name"):
        project.rename("")
    with pytest.raises(InvalidProjectStateError, match="ASCII"):
        project.rename("???")
