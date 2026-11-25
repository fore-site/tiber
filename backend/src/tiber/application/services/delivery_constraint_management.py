"""Use cases for a project's singleton delivery constraint."""

from uuid import UUID

from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.domain.entities import DeliveryConstraint
from tiber.domain.repositories import DeliveryConstraintRepository
from tiber.domain.value_objects import BlackoutPeriod, QuietHours


class DeliveryConstraintManagementService:
    """Read and replace the project-level blackout and quiet-hours config."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        constraint_repository: DeliveryConstraintRepository,
    ) -> None:
        """Bind the constraint repository and transaction boundary."""
        self._uow = unit_of_work
        self._constraints = constraint_repository

    async def get(self, project_id: UUID) -> DeliveryConstraint:
        """Return the configured constraint, or the permissive default.

        An unconfigured project reads as UTC with no blackout periods and no
        quiet hours. The default is not persisted: reading settings must not be
        a write.
        """
        constraint = await self._constraints.get_by_project(project_id)
        return constraint or DeliveryConstraint.create(project_id=project_id)

    async def replace(
        self,
        *,
        project_id: UUID,
        blackout_periods: list[BlackoutPeriod],
        quiet_hours: list[QuietHours],
        timezone: str,
    ) -> DeliveryConstraint:
        """Replace the whole configuration, creating the row on first use."""
        async with self._uow:
            existing = await self._constraints.get_by_project(project_id)
            constraint = (
                existing.replace_configuration(
                    blackout_periods=blackout_periods,
                    quiet_hours=quiet_hours,
                    timezone=timezone,
                )
                if existing is not None
                else DeliveryConstraint.create(
                    project_id=project_id,
                    blackout_periods=blackout_periods,
                    quiet_hours=quiet_hours,
                    timezone=timezone,
                )
            )
            return await self._constraints.save(constraint)
