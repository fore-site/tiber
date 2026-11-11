from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import Project
from ...domain.exceptions import NameConflictError
from ...domain.repositories import ProjectRepository
from ..models.delivery_attempt import DeliveryAttemptModel
from ..models.notification import NotificationModel
from ..models.notification_intake import NotificationIntakeModel
from ..models.outbox import OutboxModel
from ..models.project import ProjectModel
from ..models.template import TemplateModel
from .sqlalchemy_errors import get_constraint_name

_PROJECT_SLUG_CONSTRAINT = "projects_account_slug_unique"


class SQLAlchemyProjectRepository(ProjectRepository):
    """SQLAlchemy implementation of project reads used by application services."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the repository to one request-scoped session."""
        self._session = session

    async def save(self, project: Project) -> Project:
        """Persist project state without committing the transaction."""
        try:
            async with self._session.begin_nested():
                model = await self._session.get(ProjectModel, project.id)
                if model is None:
                    model = ProjectModel(id=project.id)
                    self._session.add(model)
                model.account_id = project.account_id
                model.name = project.name
                model.slug = project.slug
                model.description = project.description
                model.created_at = project.created_at
                model.updated_at = project.updated_at
                model.deleted_at = project.deleted_at
                await self._session.flush()
        except IntegrityError as exc:
            if get_constraint_name(exc) == _PROJECT_SLUG_CONSTRAINT:
                raise NameConflictError(Project) from exc
            raise
        return project

    async def get_by_id(self, id: UUID) -> Project | None:
        """Load a project by ID."""
        model = await self._session.get(ProjectModel, id)
        if model is None:
            return None
        return Project.reconstitute(
            id=model.id,
            account_id=model.account_id,
            name=model.name,
            slug=model.slug,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )

    async def get_by_id_for_update(self, id: UUID) -> Project | None:
        """Load and lock a project row until the current transaction ends."""
        model = await self._session.scalar(
            select(ProjectModel).where(ProjectModel.id == id).with_for_update()
        )
        return self._to_entity(model) if model is not None else None

    async def get_by_slug(self, slug: str, account_id: UUID) -> Project | None:
        """Resolve a project slug within its account."""
        from sqlalchemy import select

        model = await self._session.scalar(
            select(ProjectModel).where(
                ProjectModel.slug == slug,
                ProjectModel.account_id == account_id,
            )
        )
        if model is None:
            return None
        return Project.reconstitute(
            id=model.id,
            account_id=model.account_id,
            name=model.name,
            slug=model.slug,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )

    async def list_by_account(
        self, account_id: UUID, limit: int, offset: int
    ) -> list[Project]:
        """List all projects owned by an account, newest first."""
        result = await self._session.scalars(
            select(ProjectModel)
            .where(ProjectModel.account_id == account_id)
            .order_by(ProjectModel.created_at.desc(), ProjectModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_entity(model) for model in result.all()]

    async def purge_expired(self, deleted_before: datetime, limit: int) -> int:
        """Delete expired project data in FK-safe order inside one transaction."""
        project_ids = list(
            (
                await self._session.scalars(
                    select(ProjectModel.id)
                    .where(ProjectModel.deleted_at <= deleted_before)
                    .order_by(ProjectModel.deleted_at, ProjectModel.id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
        )
        if not project_ids:
            return 0

        intake_ids = select(NotificationIntakeModel.id).where(
            NotificationIntakeModel.project_id.in_(project_ids)
        )
        notification_ids = select(NotificationModel.id).where(
            NotificationModel.project_id.in_(project_ids)
        )
        await self._session.execute(
            delete(OutboxModel).where(
                OutboxModel.aggregate_id.in_(intake_ids)
                | OutboxModel.aggregate_id.in_(notification_ids)
            )
        )
        await self._session.execute(
            delete(DeliveryAttemptModel).where(
                DeliveryAttemptModel.notification_id.in_(notification_ids)
            )
        )
        await self._session.execute(
            delete(NotificationModel).where(
                NotificationModel.project_id.in_(project_ids)
            )
        )
        await self._session.execute(
            delete(NotificationIntakeModel).where(
                NotificationIntakeModel.project_id.in_(project_ids)
            )
        )
        await self._session.execute(
            delete(TemplateModel).where(TemplateModel.project_id.in_(project_ids))
        )
        await self._session.execute(
            delete(ProjectModel).where(ProjectModel.id.in_(project_ids))
        )
        return len(project_ids)

    @staticmethod
    def _to_entity(model: ProjectModel) -> Project:
        return Project.reconstitute(
            id=model.id,
            account_id=model.account_id,
            name=model.name,
            slug=model.slug,
            description=model.description,
            created_at=model.created_at,
            updated_at=model.updated_at,
            deleted_at=model.deleted_at,
        )
