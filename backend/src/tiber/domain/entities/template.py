from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel
from ..services.channel_content import validate_content
from ..value_objects import NotificationContent


@dataclass(frozen=True, kw_only=True)
class Template:
    """Template entity - reusable notification content."""

    # Ids are system-generated: callers never supply one. kw_only makes the
    # defaulted id legal ahead of required fields.
    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    channel: DeliveryChannel
    content: NotificationContent
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the template's state after initialization."""
        # Boundary coercion before the channel/title check reads the field.
        object.__setattr__(self, "channel", DeliveryChannel(self.channel.lower()))

        if not self.name or not self.name.strip():
            raise ValueError("Template name must not be empty")

        validate_content(self.channel, self.content)

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        name: str,
        channel: DeliveryChannel,
        content: NotificationContent,
    ) -> Template:
        """Create a new template with a system-generated id and timestamps."""
        return cls(
            project_id=project_id,
            name=name,
            channel=channel,
            content=content,
        )

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        name: str,
        channel: DeliveryChannel,
        content: NotificationContent,
        created_at: datetime,
        updated_at: datetime,
    ) -> Template:
        """Rebuild an existing template from persisted state."""
        return cls(
            id=id,
            project_id=project_id,
            name=name,
            channel=channel,
            content=content,
            created_at=created_at,
            updated_at=updated_at,
        )

    def update_content(self, new_content: NotificationContent) -> Template:
        """Return a new Template instance with updated content."""
        return replace(self, content=new_content, updated_at=datetime.now(UTC))

    def update_name(self, new_name: str) -> Template:
        """Return a new Template instance with updated name."""
        return replace(self, name=new_name, updated_at=datetime.now(UTC))
