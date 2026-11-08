import pytest

from tiber.api.schemas.notification import (
    NotificationContentModel,
    NotificationCreateRequest,
)
from tiber.domain.enums import DeliveryChannel
from tiber.domain.exceptions import InvalidEntityAttributeError
from tiber.domain.services.channel_content import validate_content
from tiber.domain.value_objects import NotificationContent


def test_notification_content_round_trip_preserves_both_representations() -> None:
    """Persisting content keeps text and HTML representations intact."""
    content = NotificationContent(
        title="Receipt",
        plain_text_body="Thanks for your purchase.",
        html_body="<p>Thanks for your purchase.</p>",
    )

    restored = NotificationContent.from_dict(content.to_dict())

    assert restored == content


@pytest.mark.parametrize(
    "channel",
    [DeliveryChannel.EMAIL, DeliveryChannel.IN_APP],
)
def test_html_only_content_is_valid_for_html_channels(channel) -> None:
    """HTML-only content is valid for channels with HTML delivery."""
    content = NotificationContent(
        title="Receipt" if channel is DeliveryChannel.EMAIL else None,
        html_body="<p>Thanks for your purchase.</p>",
    )

    validate_content(channel, content)


@pytest.mark.parametrize("channel", [DeliveryChannel.SMS, DeliveryChannel.PUSH])
def test_html_only_content_is_rejected_for_text_channels(channel) -> None:
    """Text-only channels cannot deliver an HTML-only body."""
    content = NotificationContent(html_body="<p>Thanks for your purchase.</p>")

    with pytest.raises(InvalidEntityAttributeError):
        validate_content(channel, content)


def test_plain_text_fallback_allows_delivery_to_text_channel() -> None:
    """Text-only channels use plain text when both representations exist."""
    content = NotificationContent(
        plain_text_body="Thanks for your purchase.",
        html_body="<p>Thanks for your purchase.</p>",
    )

    validate_content(DeliveryChannel.SMS, content)


def test_api_content_model_accepts_both_body_representations() -> None:
    """The API model preserves both formats and emits the canonical field names."""
    model = NotificationContentModel(
        title="Receipt",
        plain_text_body="Thanks.",
        html_body="<p>Thanks.</p>",
    )

    assert model.to_domain().plain_text_body == "Thanks."
    assert model.model_dump() == {
        "title": "Receipt",
        "plain_text_body": "Thanks.",
        "html_body": "<p>Thanks.</p>",
        "actions": [],
        "images": [],
    }


def test_api_content_model_accepts_legacy_body_input() -> None:
    """The previous `body` input remains accepted as a plain-text alias."""
    model = NotificationContentModel(body="Thanks.")

    assert model.plain_text_body == "Thanks."
    assert "plain_text_body" in model.model_dump()


def test_api_request_rejects_template_and_direct_content_together() -> None:
    """Direct content and a template are mutually exclusive request sources."""
    with pytest.raises(ValueError, match="exactly one"):
        NotificationCreateRequest(
            email="recipient@example.com",
            template_slug="receipt",
            content=NotificationContentModel(plain_text_body="Thanks."),
        )
