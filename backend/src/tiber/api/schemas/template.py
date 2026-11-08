"""API schemas for templates, brand profiles, and template rendering."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...application.services.template_management import TemplatePreset
from ...domain.entities import BrandProfile, Template
from ...domain.enums import DeliveryChannel
from ...domain.value_objects import TemplateVariant
from .notification import NotificationContentModel


class TemplateVariantRequest(BaseModel):
    """One channel's notification content."""

    model_config = ConfigDict(extra="forbid")

    channel: DeliveryChannel
    content: NotificationContentModel

    def to_domain(self) -> TemplateVariant:
        """Convert the wire model to a validated channel variant."""
        return TemplateVariant(
            channel=self.channel,
            content=self.content.to_domain(),
        )


class TemplateCreateRequest(BaseModel):
    """Fields accepted when creating a template."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    variants: list[TemplateVariantRequest] | None = None
    preset_id: str | None = Field(
        default=None,
        description="Select a starter variant returned by GET /template-presets.",
    )
    brand_profile_id: UUID | None = None


class TemplateUpdateRequest(BaseModel):
    """Replacement fields for an existing template."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    variants: list[TemplateVariantRequest] = Field(min_length=1)
    brand_profile_id: UUID | None = None


class TemplateVariantResponse(BaseModel):
    """Persisted channel variant representation."""

    model_config = ConfigDict(frozen=True)

    channel: DeliveryChannel
    content: NotificationContentModel
    required_variables: list[str]

    @classmethod
    def from_entity(cls, variant: TemplateVariant) -> TemplateVariantResponse:
        """Build the response from a domain variant."""
        return cls(
            channel=variant.channel,
            content=NotificationContentModel(**variant.content.to_dict()),
            required_variables=sorted(variant.variables),
        )


class TemplateResponse(BaseModel):
    """Persisted project template representation."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    name: str
    template_slug: str
    brand_profile_id: UUID | None
    variants: list[TemplateVariantResponse]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, template: Template) -> TemplateResponse:
        """Build the response from a domain template."""
        return cls(
            id=template.id,
            project_id=template.project_id,
            name=template.name,
            template_slug=template.template_slug,
            brand_profile_id=template.brand_profile_id,
            variants=[
                TemplateVariantResponse.from_entity(variant)
                for _, variant in sorted(
                    template.variants.items(), key=lambda item: item[0].value
                )
            ],
            created_at=template.created_at,
            updated_at=template.updated_at,
        )


class TemplatePresetResponse(BaseModel):
    """Selectable non-persisted template starter."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    variant: TemplateVariantResponse

    @classmethod
    def from_preset(cls, preset: TemplatePreset) -> TemplatePresetResponse:
        """Build the API representation from a starter preset."""
        return cls(
            id=preset.id,
            name=preset.name,
            variant=TemplateVariantResponse.from_entity(preset.variant),
        )


class TemplatePreviewRequest(BaseModel):
    """Variables and channel used to render a preview."""

    model_config = ConfigDict(extra="forbid")

    channel: DeliveryChannel
    variables: dict[str, object] = Field(default_factory=dict)


class TemplatePreviewResponse(BaseModel):
    """Rendered output for dashboard/API previews."""

    model_config = ConfigDict(frozen=True)

    channel: DeliveryChannel
    content: NotificationContentModel
    required_variables: list[str]


class BrandProfileCreateRequest(BaseModel):
    """Fields accepted when creating a brand profile."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    name: str = Field(min_length=1, max_length=100)
    tokens: dict[str, str] = Field(max_length=64)


class BrandProfileUpdateRequest(BrandProfileCreateRequest):
    """Replacement fields for a brand profile."""


class BrandProfileResponse(BaseModel):
    """Persisted project brand profile."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    name: str
    tokens: dict[str, str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entity(cls, profile: BrandProfile) -> BrandProfileResponse:
        """Build the response from a domain profile."""
        return cls(
            id=profile.id,
            project_id=profile.project_id,
            name=profile.name,
            tokens=profile.tokens,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )
