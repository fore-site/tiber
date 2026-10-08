from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel
from ..exceptions import InvalidEntityAttributeError
from ..value_objects import TemplateVariant


@dataclass(frozen=True, kw_only=True)
class Template:
    """Template aggregate that holds different channel variants."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    variants: dict[DeliveryChannel, TemplateVariant] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the template's state after initialization."""
        if not self.name or not self.name.strip():
            raise InvalidEntityAttributeError("Template name must not be empty")

    @classmethod
    def create(
        cls, *, project_id: UUID, name, variants: list[TemplateVariant]
    ) -> Template:
        """Create a new Template aggregate with a system-generated id and timestamps."""
        template_variants = {}
        for variant in variants:
            template_variants[variant.channel] = variant
        return cls(project_id=project_id, name=name, variants=template_variants)

    @classmethod
    def reconstitute(
        cls,
        *,
        id: UUID,
        project_id: UUID,
        name: str,
        variants: list[TemplateVariant],
        created_at: datetime,
        updated_at: datetime,
    ) -> Template:
        """Rebuild an existing Template aggregate from persisted state."""
        template_variants = {}
        for variant in variants:
            template_variants[variant.channel] = variant
        return cls(
            id=id,
            project_id=project_id,
            name=name,
            variants=template_variants,
            created_at=created_at,
            updated_at=updated_at,
        )

    def add_or_update_variants(self, variant: TemplateVariant) -> Template:
        """Add a template variant or update existing one."""
        variants_copy = self.variants.copy()
        variants_copy[variant.channel] = variant
        return replace(self, variants=variants_copy, updated_at=datetime.now(UTC))

    def remove_variant(self, channel: DeliveryChannel) -> Template:
        """Remove a template variant."""
        validated_channel = DeliveryChannel(channel)
        variants_copy = self.variants.copy()
        variants_copy.pop(validated_channel, None)
        return replace(self, variants=variants_copy, updated_at=datetime.now(UTC))

    def update_name(self, new_name: str) -> Template:
        """Return a new Template aggregate instance with updated name."""
        return replace(self, name=new_name, updated_at=datetime.now(UTC))
