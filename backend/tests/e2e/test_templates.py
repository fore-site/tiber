"""End-to-end template lifecycle and Liquid rendering."""

from __future__ import annotations

from uuid import UUID

import pytest

from tiber.infrastructure.repositories.sqlalchemy_template_repository import (
    SQLAlchemyTemplateRepository,
)

pytestmark = pytest.mark.e2e

AUTH = {"Authorization": "Bearer e2e-test-token"}


async def test_template_persistence_and_liquid_preview(
    client,
    project,
    session,
) -> None:
    """Create a template, render it safely, and render inline content."""
    project_id = project.id
    presets = await client.get(
        f"/v1/projects/{project_id}/template-presets",
        headers=AUTH,
    )
    assert presets.status_code == 200
    assert {preset["id"] for preset in presets.json()} == {
        "email-starter",
        "in-app-starter",
    }

    template_payload = {
        "name": "Transaction Alert",
        "variants": [
            {
                "channel": "email",
                "content": {
                    "title": "Hello {{ name | escape }}",
                    "plain_text_body": "Your transaction is ready, {{ name }}.",
                    "html_body": (
                        "<html><head></head><body>"
                        "<h1>{{ name | escape }}</h1>"
                        '<p style="color:#3157d5">'
                        "{% if urgent %}Urgent: {% endif %}"
                        "{{ note | default: 'ready' }}"
                        "</p></body></html>"
                    ),
                },
            }
        ],
    }
    created = await client.post(
        f"/v1/projects/{project_id}/templates",
        headers=AUTH,
        json=template_payload,
    )
    assert created.status_code == 201
    template_response = created.json()
    template_id = UUID(template_response["id"])
    assert template_response["template_slug"] == "transaction-alert"
    # ``| escape`` is a filter, not part of the variable name. ``urgent`` is only
    # read by a tag (``{% if %}``), so it is optional and not a required variable.
    assert template_response["variants"][0]["required_variables"] == ["name", "note"]

    persisted = await SQLAlchemyTemplateRepository(session).get_by_id(
        template_id, project_id
    )
    assert persisted is not None
    assert (
        persisted.variants[next(iter(persisted.variants))].content.html_body is not None
    )

    await session.refresh(project)
    listed = await client.get(
        f"/v1/projects/{project_id}/templates?channel=email",
        headers=AUTH,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [str(template_id)]

    preview = await client.post(
        f"/v1/projects/{project_id}/templates/{template_id}/preview",
        headers=AUTH,
        json={
            "channel": "email",
            "variables": {
                "name": "<script>alert(1)</script>",
                "urgent": True,
                "note": "go",
            },
        },
    )
    assert preview.status_code == 200
    preview_body = preview.json()
    # No autoescaping: only the explicit ``| escape`` filter escapes.
    assert preview_body["content"]["title"] == (
        "Hello &lt;script&gt;alert(1)&lt;/script&gt;"
    )
    html_body = preview_body["content"]["html_body"]
    assert "<h1>&lt;script&gt;alert(1)&lt;/script&gt;</h1>" in html_body
    assert "Urgent: go" in html_body

    rendered = await client.post(
        f"/v1/projects/{project_id}/templates/preview",
        headers=AUTH,
        json={
            "channel": "in_app",
            "content": {
                "title": "Hello {{ who }}",
                "html_body": "<p>{{ who | escape }}</p>",
            },
            "variables": {"who": "<b>Ada</b>"},
        },
    )
    assert rendered.status_code == 200
    rendered_body = rendered.json()
    # In-app does not persist a subject, so the send path drops the title.
    assert rendered_body["content"]["title"] is None
    assert rendered_body["content"]["html_body"] == "<p>&lt;b&gt;Ada&lt;/b&gt;</p>"
    assert rendered_body["required_variables"] == ["who"]

    duplicate = await client.post(
        f"/v1/projects/{project_id}/templates",
        headers=AUTH,
        json=template_payload,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"] == "name_conflict"
