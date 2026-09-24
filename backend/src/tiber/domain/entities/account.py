from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Account:
    """Account entity - a platform account that owns projects.

    An account is identified by email and owns projects. OAuth (GitHub) accounts
    have a ``github_id`` and no ``password_hash``; email/password accounts
    have a ``password_hash``.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
