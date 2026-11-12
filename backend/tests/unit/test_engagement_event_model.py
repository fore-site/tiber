"""Regression pins for the engagement event persistence mapping."""

from tiber.infrastructure.models import EngagementEventModel


def test_metadata_none_binds_as_sql_null() -> None:
    """A Python ``None`` must reach the check constraint as SQL NULL.

    The ``metadata`` column is JSONB and its check constraint accepts NULL but
    not JSON ``null``. SQLAlchemy's default binds Python ``None`` as JSON
    ``null``; ``none_as_null=True`` is what makes the insert pass.
    """
    column = EngagementEventModel.__table__.c["metadata"]

    assert column.type.none_as_null is True
