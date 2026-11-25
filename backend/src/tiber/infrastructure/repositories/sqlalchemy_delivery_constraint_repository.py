from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain.entities import DeliveryConstraint
from ...domain.repositories import DeliveryConstraintRepository
from ..models.delivery_constraint import DeliveryConstraintModel
from .constraint_json import (
    blackout_from_json,
    blackout_to_json,
    quiet_hours_from_json,
    quiet_hours_to_json,
)


class SQLAlchemyDeliveryConstraintRepository(DeliveryConstraintRepository):
    """SQLAlchemy implementation of the DeliveryConstraintRepository.

    Windows and periods are configuration payloads: they are stored as JSONB
    documents and validated by the domain value objects on every
    rehydration, so a corrupted row fails loudly at load instead of silently
    disabling a project's delivery restrictions.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an async session."""
        self._session = session

    async def save(self, constraint: DeliveryConstraint) -> DeliveryConstraint:
        """Insert or update the project's single constraint row."""
        model = DeliveryConstraintModel(
            id=constraint.id,
            project_id=constraint.project_id,
            blackout_periods=[
                blackout_to_json(period) for period in constraint.blackout_periods
            ],
            quiet_hours=[
                quiet_hours_to_json(window) for window in constraint.quiet_hours
            ],
            timezone=constraint.timezone,
        )
        await self._session.merge(model)
        await self._session.flush()
        return constraint

    async def get_by_project(self, project_id: UUID) -> DeliveryConstraint | None:
        """Get the constraint configured for a project, None when absent."""
        model = await self._get_model(project_id)
        return self._to_entity(model) if model else None

    async def load_constraint(self, project_id: UUID) -> DeliveryConstraint | None:
        """Load the constraint for policy evaluation, None when absent.

        A missing configuration is the permissive default (no restrictions
        configured), not an error - policy evaluation reads this as "no
        project-level silence applies".
        """
        return await self.get_by_project(project_id)

    async def _get_model(self, project_id: UUID) -> DeliveryConstraintModel | None:
        """Fetch the project's constraint row, if any."""
        result = await self._session.execute(
            select(DeliveryConstraintModel).where(
                DeliveryConstraintModel.project_id == project_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _to_entity(model: DeliveryConstraintModel) -> DeliveryConstraint:
        """Rebuild the domain entity from the persisted row."""
        return DeliveryConstraint.reconstitute(
            id=model.id,
            project_id=model.project_id,
            blackout_periods=[
                blackout_from_json(period) for period in model.blackout_periods
            ],
            quiet_hours=[quiet_hours_from_json(window) for window in model.quiet_hours],
            timezone=model.timezone,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
