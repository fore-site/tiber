from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True, kw_only=True)
class Account:
    """Account entity - a platform account that owns projects.

    Accounts are ownership roots only: the domain represents them by id.
    Authentication and profile data (email, credentials, verification)
    belong to the supporting auth capability and are stored in
    infrastructure, accessed through application-layer ports — Tiber is a
    notification-delivery platform, not an authentication service.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
