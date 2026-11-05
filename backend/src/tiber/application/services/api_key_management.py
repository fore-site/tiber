"""Use cases for project-scoped API-key lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from redis.exceptions import RedisError

from ...core.security import generate_api_key, hash_api_key
from ...domain.entities import APIKey, Project
from ...domain.repositories import APIKeyRepository, ProjectRepository
from ..ports.api_key_auth_cache import ApiKeyAuthCache
from ..ports.unit_of_work import UnitOfWork


class APIKeyManagementError(RuntimeError):
    """A rejected API-key lifecycle operation."""

    def __init__(self, code: str) -> None:
        """Store the stable application error code."""
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class APIKeyPage:
    """An API-key page and the total matching key count."""

    keys: list[APIKey]
    total: int
    limit: int
    offset: int


class APIKeyManagementService:
    """Coordinate project authorization, API-key persistence, and cache state."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        projects: ProjectRepository,
        api_keys: APIKeyRepository,
        cache: ApiKeyAuthCache,
    ) -> None:
        """Bind the project, key, transaction, and cache ports."""
        self._uow = unit_of_work
        self._projects = projects
        self._api_keys = api_keys
        self._cache = cache

    async def create(
        self,
        *,
        project_id: UUID,
        account_id: UUID,
        name: str,
    ) -> tuple[APIKey, str]:
        """Create a key for an account-owned project and return its secret once."""
        secret = generate_api_key()
        key = APIKey.create(
            project_id=project_id,
            name=name,
            key_hash=hash_api_key(secret),
            key_prefix=secret[:10],
        )
        async with self._uow:
            await self._owned_project(project_id, account_id)
            await self._api_keys.save(key)
        return key, secret

    async def list(
        self,
        *,
        project_id: UUID,
        account_id: UUID,
        limit: int,
        offset: int,
    ) -> APIKeyPage:
        """Return paginated key metadata for an account-owned project."""
        async with self._uow:
            await self._owned_project(project_id, account_id)
            keys = await self._api_keys.list_by_project(project_id, limit, offset)
            total = await self._api_keys.count_by_project(project_id)
        return APIKeyPage(keys=keys, total=total, limit=limit, offset=offset)

    async def get(
        self,
        *,
        project_id: UUID,
        account_id: UUID,
        key_id: UUID,
    ) -> APIKey:
        """Get one key's metadata within an account-owned project."""
        async with self._uow:
            await self._owned_project(project_id, account_id)
            key = await self._api_keys.get_by_id(key_id, project_id)
        if key is None:
            raise APIKeyManagementError("api_key_not_found")
        return key

    async def revoke(
        self,
        *,
        project_id: UUID,
        account_id: UUID,
        key_id: UUID,
    ) -> None:
        """Revoke a key transactionally, then invalidate its cached facts."""
        async with self._uow:
            await self._owned_project(project_id, account_id)
            key = await self._api_keys.get_by_id(key_id, project_id)
            if key is None:
                raise APIKeyManagementError("api_key_not_found")
            revoked_key = key.revoke()
            await self._api_keys.save(revoked_key)
        try:
            await self._cache.invalidate(revoked_key.key_hash)
        except RedisError as exc:
            raise APIKeyManagementError("api_key_state_unavailable") from exc

    async def _owned_project(self, project_id: UUID, account_id: UUID) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None or project.account_id != account_id:
            raise APIKeyManagementError("project_not_found")
        return project
