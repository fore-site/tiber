"""Version 1 of the HTTP API: its routers, its schemas, its curated spec.

A version package is the seam a new API version is built against. Adding `v2`
means adding a sibling package that exposes the same `api_vN` bundle and
registering it in `tiber.api.versions`; nothing here has to move again.
"""

from fastapi import APIRouter

from tiber.api.v1.routers import (
    api_keys,
    auth,
    delivery_attempts,
    delivery_constraints,
    engagement_events,
    notification,
    projects,
    recipients,
    sender_identities,
    templates,
    topics,
    webhooks,
)

api_v1 = APIRouter()
for module in (
    auth,
    api_keys,
    projects,
    notification,
    recipients,
    sender_identities,
    topics,
    templates,
    delivery_constraints,
    delivery_attempts,
    engagement_events,
    webhooks,
):
    api_v1.include_router(module.router)
