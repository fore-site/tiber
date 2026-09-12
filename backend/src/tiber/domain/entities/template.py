from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel


@dataclass(frozen=True, kw_only=True)
class Template:
    """Template entity - reusable notification content.

    ``subject`` is required for email and must be absent for other channels,
    enforced both here and by the ``templates_subject_check`` DB constraint.
    Supports ``{{variable}}`` interpolation.
    """

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    slug: str
    channel: DeliveryChannel
    body: str
    subject: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the template's state after initialization."""
        if not self.name or not self.name.strip():
            raise ValueError("Template name must not be empty")
        if not self.slug or not self.slug.strip():
            raise ValueError("Template slug must not be empty")
        if not self.body or not self.body.strip():
            raise ValueError("Template body must not be empty")

        if self.channel == DeliveryChannel.EMAIL:
            if self.subject is None:
                raise ValueError("Email templates must have a subject")
        else:
            if self.subject is not None:
                raise ValueError(
                    f"Subject must not be set for {self.channel.value} templates"
                )

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        name: str,
        slug: str,
        channel: DeliveryChannel,
        body: str,
        subject: str | None = None,
    ) -> Template:
        """Create a new template with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            name=name,
            slug=slug,
            channel=channel,
            body=body,
            subject=subject,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        name: str,
        slug: str,
        channel: DeliveryChannel,
        body: str,
        subject: str | None,
        created_at: datetime,
        updated_at: datetime,
    ) -> Template:
        """Rebuild an existing template from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            name=name,
            slug=slug,
            channel=channel,
            body=body,
            subject=subject,
            created_at=created_at,
            updated_at=updated_at,
        )
