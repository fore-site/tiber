"""Worker half of notification creation.

    T1  claim the intake (lease)                       -> commit
        ML decision, advisory, with a timeout          -> assemble the plan
    T2  persist the plan on the intake                 -> commit
        build, render, schedule and policy-check every child in memory
    T3  save children + dispatch outbox rows + COMPLETED -> commit

Why three transactions: the plan is persisted before fan-out, so a retry after a
crash reuses the stored decision rather than asking the ML again, and T3 is
all-or-nothing, so a retry never sees half a batch.

Failure handling
    * Engine error or timeout       -> defaults are applied; never fails the intake.
    * Deterministic domain error    -> intake FAILED. The accept-time constraints are
                                       meant to make this unreachable, so it is logged
                                       as an error: treat it as a bug.
    * Infrastructure error          -> propagates so the queue retries; the lease
                                       prevents concurrent workers, and attempts are
                                       capped by ``max_attempts``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from tiber.application.ports.decision_engine import DecisionEngine, DecisionRequest
from tiber.application.ports.intake import Outbox
from tiber.application.ports.unit_of_work import UnitOfWork
from tiber.application.services.template import NotificationTemplateResolver
from tiber.domain.entities import Notification, Recipient
from tiber.domain.entities.notification_intake import NotificationIntake
from tiber.domain.enums import (
    DeliveryChannel,
    IntakeStatus,
    NotificationCategory,
    NotificationStatus,
    PolicyConsequence,
    SendTimeBasis,
)
from tiber.domain.exceptions import (
    EntityNotFoundError,
    TemplateRenderError,
    TiberError,
)
from tiber.domain.policies import PolicyResolver
from tiber.domain.repositories import (
    DeliveryConstraintRepository,
    NotificationIntakeRepository,
    NotificationRepository,
    NotificationTopicRepository,
    RecipientRepository,
)
from tiber.domain.services import validate_content
from tiber.domain.services.plan_assembly import assemble_plan, wanted_decisions
from tiber.domain.value_objects import NotificationContent
from tiber.domain.value_objects.intake import (
    MlSuggestion,
    NotificationPlan,
    ResolvedTopic,
)

logger = logging.getLogger(__name__)


class IntakeProcessor:
    """Process notification(s) validated and persisted from api layer notification intake."""

    def __init__(
        self,
        *,
        unit_of_work: UnitOfWork,
        intake_repository: NotificationIntakeRepository,
        notification_repository: NotificationRepository,
        recipient_repository: RecipientRepository,
        topic_repository: NotificationTopicRepository,
        template_resolver: NotificationTemplateResolver,
        policy_resolver: PolicyResolver,
        decision_engine: DecisionEngine,
        outbox: Outbox,
        constraint_repository: DeliveryConstraintRepository | None = None,
        engine_timeout: float = 0.25,
        lease: timedelta = timedelta(minutes=5),
        max_attempts: int = 5,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """Initialize variables for intake processing."""
        self._uow = unit_of_work
        self._intakes = intake_repository
        self._notifications = notification_repository
        self._recipients = recipient_repository
        self._topics = topic_repository
        self._template_resolver = template_resolver
        self._policy = policy_resolver
        self._engine = decision_engine
        self._outbox = outbox
        self._constraints = constraint_repository
        self._engine_timeout = engine_timeout
        self._lease = lease
        self._max_attempts = max_attempts
        self._clock = clock

    async def process(self, intake_id: UUID) -> None:
        """Handle one intake message. Safe to call repeatedly for the same id."""
        intake = await self._claim(intake_id)
        if intake is None:
            return  # missing, locked, finished, or leased by another worker

        if intake.attempts > self._max_attempts:
            await self._fail(
                intake.id, f"exceeded {self._max_attempts} processing attempts"
            )
            return

        try:
            recipient = await self._load_recipient(intake)
            if intake.plan is None:
                intake = await self._decide(intake, recipient)
            await self._fan_out(intake, recipient)
        except TemplateRenderError as exc:
            # Reachable: live rendering uses the template as of fan-out, so an
            # edit (or a deleted variant) between accept and here lands here.
            # Warning, not error: this is a lifecycle event, not a Tiber bug.
            logger.warning("Intake %s cannot render its template: %s", intake.id, exc)
            await self._fail(intake.id, str(exc))
        except (TiberError, ValueError) as exc:
            logger.error(
                "Intake %s failed deterministically; accept-time constraints should "
                "make this unreachable",
                intake.id,
                exc_info=True,
            )
            await self._fail(intake.id, f"{type(exc).__name__}: {exc}")

    # T1: claim

    async def _claim(self, intake_id: UUID) -> NotificationIntake | None:
        async with self._uow:
            intake = await self._intakes.get_for_update(intake_id)
            now = self._clock()
            if intake is None or not intake.is_claimable(now, self._lease):
                return None
            claimed = intake.claim(now, self._lease)
            await self._intakes.save(claimed)
            return claimed

    async def _load_recipient(self, intake: NotificationIntake) -> Recipient:
        recipient = await self._recipients.get_by_id(
            intake.recipient_id, intake.project_id
        )
        if recipient is None:
            raise EntityNotFoundError(Recipient, str(intake.recipient_id))
        return recipient

    # ML decision -> T2: persist plan

    async def _decide(
        self, intake: NotificationIntake, recipient: Recipient
    ) -> NotificationIntake:
        payload, constraints = intake.payload, intake.constraints
        want = wanted_decisions(payload, constraints)

        suggestion: MlSuggestion | None = None
        ml_topic: ResolvedTopic | None = None
        if want:
            suggestion = await self._ask_engine(
                DecisionRequest(
                    recipient=recipient,
                    payload=payload,
                    constraints=constraints,
                    want=want,
                )
            )
            if suggestion is not None and "topic" in want and suggestion.topic_slug:
                # The ML may only suggest topics that exist in this project.
                topic = await self._topics.get_by_slug(
                    suggestion.topic_slug, intake.project_id
                )
                if topic is not None and topic.topic_slug is not None:
                    ml_topic = ResolvedTopic(id=topic.id, slug=topic.topic_slug)

        plan = assemble_plan(
            payload=payload,
            constraints=constraints,
            ml=suggestion,
            ml_topic=ml_topic,
            now=self._clock(),
        )
        planned = intake.with_plan(plan)
        async with self._uow:
            await self._intakes.save(planned)
        return planned

    async def _ask_engine(self, request: DecisionRequest) -> MlSuggestion | None:
        """ML is advisory: any failure or timeout means "no suggestion"."""
        try:
            return await asyncio.wait_for(
                self._engine.decide(request), timeout=self._engine_timeout
            )
        except Exception:
            logger.warning(
                "Decision engine failed or timed out; applying defaults", exc_info=True
            )
            return None

    # T3: fan-out

    async def _fan_out(self, intake: NotificationIntake, recipient: Recipient) -> None:
        plan = intake.plan
        if plan is None:
            raise Exception("Plan is None.")

        existing = {
            n.channel
            for n in await self._notifications.list_by_correlation_id(
                intake.correlation_id, intake.project_id
            )
        }
        constraint = (
            await self._constraints.load_constraint(intake.project_id)
            if self._constraints is not None
            else None
        )

        children: list[Notification] = []
        for channel in plan.channels:
            if channel in existing:  # created by an earlier attempt
                continue
            child = await self._build_child(intake, plan, channel)
            children.append(await self._apply_policy(child, recipient, constraint))

        async with self._uow:
            for child in children:
                await self._notifications.save(child)
                if child.status in (
                    NotificationStatus.PENDING,
                    NotificationStatus.POSTPONED,
                ):
                    await self._outbox.enqueue_dispatch(child)
            await self._intakes.save(intake.complete(self._clock()))

    async def _build_child(
        self,
        intake: NotificationIntake,
        plan: NotificationPlan,
        channel: DeliveryChannel,
    ) -> Notification:
        payload = intake.payload

        # Classified once, here, from the intake facts: an explicit send time wins,
        # CRITICAL is always immediate, everything else may be ML-predicted.
        if payload.send_at is not None:
            send_time_basis = SendTimeBasis.EXPLICIT
        elif plan.category is NotificationCategory.CRITICAL:
            send_time_basis = SendTimeBasis.IMMEDIATE
        else:
            send_time_basis = SendTimeBasis.ML_PREDICTED

        fields = dict(
            project_id=intake.project_id,
            recipient_id=intake.recipient_id,
            correlation_id=intake.correlation_id,
            channel=channel,
            category=plan.category,
            topic_id=plan.topic.id if plan.topic else None,
            template_id=payload.template_id,
            template_variables=payload.template_variables,
            group_key=payload.group_key,
            # The client's key is stored as-is: uniqueness is (correlation_id, channel).
            idempotency_key=intake.idempotency_key,
            send_at=payload.send_at,
            send_time_basis=send_time_basis,
        )

        if payload.template_id is not None:
            # The placeholder only exists to build a provisional entity the
            # template resolver can render against; it is never persisted.
            placeholder = NotificationContent(
                title="[template pending]"
                if channel is DeliveryChannel.EMAIL
                else None,
                body="[template pending]",
            )
            provisional = Notification.create(content=placeholder, **fields)
            child = provisional.with_content(
                await self._template_resolver.resolve_content(provisional)
            )
        else:
            if payload.content is None:
                raise Exception("Payload content is None.")
            validate_content(channel, payload.content)
            child = Notification.create(content=payload.content, **fields)

        # ML-predicted send time (client send_at and CRITICAL have their own basis).
        predicted = plan.send_at.get(channel)
        if (
            predicted is not None
            and child.send_time_basis is SendTimeBasis.ML_PREDICTED
        ):
            child = child.schedule(predicted)
        return child

    async def _apply_policy(
        self, notification: Notification, recipient: Recipient, constraint
    ) -> Notification:
        """Map the policy decision onto the state machine."""
        decision = await self._policy.evaluate(notification, recipient, constraint)
        if decision.allowed:
            return notification
        if decision.consequence is PolicyConsequence.POSTPONE:
            if decision.resume_at is None:
                raise ValueError("policy returned POSTPONE without a resume time")
            return notification.mark_postponed(decision.resume_at)
        return notification.mark_suppressed(decision.reason or "policy violation")

    async def _fail(self, intake_id: UUID, reason: str) -> None:
        async with self._uow:
            current = await self._intakes.get_for_update(intake_id)
            if current is None or current.status in (
                IntakeStatus.COMPLETED,
                IntakeStatus.FAILED,
            ):
                return
            await self._intakes.save(current.fail(reason))
