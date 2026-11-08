"""End-to-end template and brand-profile lifecycle."""

from __future__ import annotations

from uuid import UUID

import pytest

from tiber.infrastructure.repositories.sqlalchemy_brand_profile_repository import (
    SQLAlchemyBrandProfileRepository,
)
from tiber.infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)

pytestmark = pytest.mark.e2e

AUTH = {"Authorization": "Bearer e2e-test-token"}


async def test_brand_profile_template_persistence_and_preview(
    client,
    project,
    session,
) -> None:
    """Create reusable tokens and a styled template, then render safely."""
    project_id = project.id
    presets = await client.get(
        f"/projects/{project_id}/template-presets",
        headers=AUTH,
    )
    assert presets.status_code == 200
    assert {preset["id"] for preset in presets.json()} == {
        "email-starter",
        "in-app-starter",
    }

    profile_response = await client.post(
        f"/projects/{project_id}/brand-profiles",
        headers=AUTH,
        json={"name": "Acme", "tokens": {"primary": "#123456"}},
    )
    assert profile_response.status_code == 201
    profile_id = UUID(profile_response.json()["id"])
    profile = await SQLAlchemyBrandProfileRepository(session).get_by_id(
        profile_id, project_id
    )
    assert profile is not None
    assert profile.tokens == {"primary": "#123456"}

    template_payload = {
        "name": "Transaction Alert",
        "brand_profile_id": str(profile_id),
        "variants": [
            {
                "channel": "email",
                "content": {
                    "title": "Hello {{name}}",
                    "plain_text_body": "Your transaction is ready, {{name}}.",
                    "html_body": (
                        "<html><head></head><body><h1>{{name}}</h1>"
                        '<p style="color:[[primary]]">Your transaction is ready.</p>'
                        "</body></html>"
                    ),
                },
            }
        ],
    }
    created = await client.post(
        f"/projects/{project_id}/templates",
        headers=AUTH,
        json=template_payload,
    )
    assert created.status_code == 201
    template_response = created.json()
    template_id = UUID(template_response["id"])
    assert template_response["template_slug"] == "transaction-alert"
    assert template_response["variants"][0]["required_variables"] == ["name"]

    persisted = await SQLAlchemyTemplateRepository(session).get_by_id(
        template_id, project_id
    )
    assert persisted is not None
    assert persisted.brand_profile_id == profile_id
    assert (
        persisted.variants[next(iter(persisted.variants))].content.html_body is not None
    )

    await session.refresh(project)
    listed = await client.get(
        f"/projects/{project_id}/templates?channel=email",
        headers=AUTH,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [str(template_id)]

    preview = await client.post(
        f"/projects/{project_id}/templates/{template_id}/preview",
        headers=AUTH,
        json={"channel": "email", "variables": {"name": "<script>alert(1)</script>"}},
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["content"]["title"] == "Hello <script>alert(1)</script>"
    html_body = preview_body["content"]["html_body"]
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_body
    assert "--tiber-primary:#123456" in html_body
    assert "color:#123456" in html_body

    duplicate = await client.post(
        f"/projects/{project_id}/templates",
        headers=AUTH,
        json=template_payload,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "template_name_conflict"
