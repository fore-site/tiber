from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Account:
    """Account entity - a platform account that owns projects."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
