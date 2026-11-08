from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ..enums import DeliveryChannel
from ..exceptions import InvalidEntityAttributeError
from ..services.slug import SLUG_RE, derive_slug, require_derivable_name
from ..value_objects import TemplateVariant


@dataclass(frozen=True, kw_only=True)
class Template:
    """Template aggregate that holds different channel variants."""

    id: UUID = field(default_factory=uuid4)
    project_id: UUID
    name: str
    template_slug: str | None = None
    brand_profile_id: UUID | None = None
    variants: dict[DeliveryChannel, TemplateVariant] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate the template's state after initialization."""
        if not self.name or not self.name.strip():
            raise InvalidEntityAttributeError("Template name must not be empty")

        if self.template_slug is None:
            require_derivable_name(self.name)
            object.__setattr__(self, "template_slug", derive_slug(self.name))

        if self.template_slug and not SLUG_RE.fullmatch(self.template_slug):
            raise InvalidEntityAttributeError(
                "Template slug must be lowercase letters and digits separated "
                "by single hyphens, with no leading or trailing hyphen "
                f"(got: {self.template_slug!r})"
            )

    @classmethod
    def create(
        cls,
        *,
        project_id: UUID,
        name: str,
        variants: list[TemplateVariant],
        brand_profile_id: UUID | None = None,
    ) -> Template:
        """Create a new Template aggregate with a system-generated id and timestamps."""
        template_variants: dict[DeliveryChannel, TemplateVariant] = {}
        for variant in variants:
            template_variants[variant.channel] = variant
        return cls(
            project_id=project_id,
            name=name,
            variants=template_variants,
            brand_profile_id=brand_profile_id,
        )

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
        brand_profile_id: UUID | None = None,
    ) -> Template:
        """Rebuild an existing Template aggregate from persisted state."""
        template_variants: dict[DeliveryChannel, TemplateVariant] = {}
        for variant in variants:
            template_variants[variant.channel] = variant
        return cls(
            id=id,
            project_id=project_id,
            name=name,
            variants=template_variants,
            brand_profile_id=brand_profile_id,
            created_at=created_at,
            updated_at=updated_at,
        )

    # Variables
    @property
    def required_variables(self) -> frozenset[str]:
        """Every variable any variant uses, each name once.

        Good for showing developers what a template needs. Do NOT use it to
        validate a send: a send to one channel only needs that variant's
        variables. Use ``variables_for`` for that.
        """
        return frozenset().union(*(v.variables for v in self.variants.values()))

    def variables_for(self, channel: DeliveryChannel) -> frozenset[str]:
        """Variables the given channel's variant needs to render."""
        variant = self.variants.get(channel)
        if variant is None:
            raise InvalidEntityAttributeError(
                f"Template has no variant for channel {channel.value!r}"
            )
        return variant.variables

    def add_or_update_variants(self, variant: TemplateVariant) -> Template:
        """Add a template variant or update existing one."""
        variants_copy = self.variants.copy()
        variants_copy[variant.channel] = variant
        return replace(self, variants=variants_copy, updated_at=datetime.now(UTC))

    def remove_variant(self, channel: DeliveryChannel) -> Template:
        """Remove a template variant."""
        variants_copy = self.variants.copy()
        variants_copy.pop(channel, None)
        return replace(self, variants=variants_copy, updated_at=datetime.now(UTC))

    def rename(self, name: str) -> Template:
        """Rename the template; the slug follows the name."""
        if not name or not name.strip():
            raise InvalidEntityAttributeError("Template name must not be empty")
        require_derivable_name(name)

        return replace(
            self,
            name=name,
            template_slug=derive_slug(name),
            updated_at=datetime.now(UTC),
        )

    def update(
        self,
        *,
        name: str,
        variants: list[TemplateVariant],
        brand_profile_id: UUID | None,
    ) -> Template:
        """Replace template variants and its optional brand profile."""
        if not name or not name.strip():
            raise InvalidEntityAttributeError("Template name must not be empty")
        require_derivable_name(name)
        template_variants = {variant.channel: variant for variant in variants}
        return replace(
            self,
            name=name,
            template_slug=derive_slug(name),
            variants=template_variants,
            brand_profile_id=brand_profile_id,
            updated_at=datetime.now(UTC),
        )
