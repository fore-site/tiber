"""NotificationTopic slugs are what the accept path resolves against.

The slug is derived on creation and rename, and reconstitution must preserve
the stored slug rather than recomputing it: if derivation rules ever change,
existing rows keep the identity clients already use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from tiber.domain.entities import NotificationTopic
from tiber.domain.enums import NotificationCategory
from tiber.domain.exceptions import InvalidEntityAttributeError


def test_create_derives_the_slug_from_the_title():
    """New topics get a URL-safe slug without the caller supplying one."""
    topic = NotificationTopic.create(
        project_id=uuid4(),
        category=NotificationCategory.INFORMATIONAL,
        title="Password Resets",
    )

    assert topic.topic_slug == "password-resets"


def test_rename_updates_the_slug():
    """Renaming a topic keeps name and slug in sync."""
    topic = NotificationTopic.create(
        project_id=uuid4(),
        category=NotificationCategory.INFORMATIONAL,
        title="Password Resets",
    )

    renamed = topic.rename("Account Recovery")

    assert renamed.topic_slug == "account-recovery"


def test_reconstitute_preserves_the_persisted_slug():
    """A stored slug wins over one re-derived from a later-edited title."""
    now = datetime.now(UTC)

    topic = NotificationTopic.reconstitute(
        id=uuid4(),
        project_id=uuid4(),
        category=NotificationCategory.CRITICAL,
        title="Renamed In The UI",
        topic_slug="original-slug",
        created_at=now,
        updated_at=now,
    )

    assert topic.topic_slug == "original-slug"


def test_create_rejects_a_title_that_cannot_be_slugged():
    """A title with no ASCII letters or digits is rejected at construction."""
    with pytest.raises(InvalidEntityAttributeError):
        NotificationTopic.create(
            project_id=uuid4(),
            category=NotificationCategory.INFORMATIONAL,
            title="!!!",
        )
