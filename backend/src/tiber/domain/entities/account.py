from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class Account:
    """Account entity - a platform account that owns projects.

    Accounts are ownership roots only: the domain represents them by id.
    """

    id: UUID = field(default_factory=uuid4)
