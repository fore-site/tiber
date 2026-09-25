"""Domain exceptions for Tiber - Error conditions defined by the business domain.

The API layer maps these exceptions to HTTP status codes and error messages.
The domain layer should not be aware of the API layer or HTTP status codes.
The infrastructure layer raises these exceptions when it encounters an error condition that is defined by the business domain.
The domain defines them. Nothing outside the domain should define new error conditions that belong here.
"""

from typing import Any


class TiberError(Exception):
    """Base class for all Tiber domain exceptions."""

    error_code = "internal_error"

    pass


class EntityNotFoundError(TiberError):
    """Raised when a required domain entity cannot be found to complete an operation."""

    error_code = "not_found_error"

    def __init__(self, entity_cls: type, entity_id: Any):
        """Initialize an EntityNotFoundError."""
        self.entity_name = entity_cls.__name__
        self.entity_id = entity_id
        super().__init__(
            f"{self.entity_name} with identifier '{entity_id}' was not found."
        )


class TemplateChannelMismatchError(TiberError):
    """Raised when a notification uses a template for a different channel."""

    error_code = "template_channel_mismatch"

    def __init__(self, template_id: str, template_channel: str, channel: str) -> None:
        """Initialize a TemplateChannelMismatchError."""
        self.template_id = template_id
        self.template_channel = template_channel
        self.channel = channel
        super().__init__(
            f"Template '{self.template_id}' is for channel '{self.template_channel}', "
            f"not '{self.channel}'"
        )


# Policy & access


class ProjectScopeViolationError(TiberError):
    """Raised when an operation is attempted outside the scope of a project."""

    error_code = "project_scope_violated"

    def __init__(self, project_id: str, message: str) -> None:
        """Initialize a ProjectScopeViolationError with the project ID and message."""
        self.project_id = project_id
        self.message = message
        super().__init__(
            f"Project scope violation for project '{self.project_id}': {self.message}"
        )


# Delivery


class DeliveryFailedError(TiberError):
    """Raised when a delivery attempt fails."""

    error_code = "delivery_failed"

    def __init__(self, message: str) -> None:
        """Initialize a DeliveryFailedError with a message."""
        self.message = message
        super().__init__(f"Delivery failed: {self.message}")


class ProviderUnavailableError(TiberError):
    """Raised when a provider is unavailable."""

    error_code = "provider_unavailable"

    def __init__(self, provider: str) -> None:
        """Initialize a ProviderUnavailableError."""
        self.provider = provider
        super().__init__(f"{self.provider} is unavailable.")


class IdempotencyKeyConflictError(TiberError):
    """Raised when an idempotency key is reused with a different request payload.

    A duplicate submission with the identical payload is not an error —
    it returns the original cached response. This exception is raised only
    when the same key is submitted with a payload that differs from the
    original request, indicating a client-side logic error.
    """

    error_code = "idempotency_key_conflict"

    def __init__(self) -> None:
        """Initialize an IdempotencyKeyConflictError."""
        super().__init__("Duplicate key passed with different request payload.")


class InvalidStateTransitionError(TiberError):
    """Raised when a notification status transition is not allowed."""

    error_code = "invalid_state_transition"

    def __init__(self, current: str, target: str) -> None:
        """Initialize an InvalidStateTransition error with the current and target states."""
        self.current = current
        self.target = target
        super().__init__(
            f"Cannot transition Notification from '{self.current}' to '{self.target}'."
        )


class InvalidEntityAttributeError(TiberError):
    """Raised when an entity attribute fails value validation or enum parsing."""

    error_code = "invalid_entity_attribute"

    def __init__(self, message: str):
        """Initialize an InvalidEntityAttributeError."""
        self.message = message
        super().__init__(f"{self.message}")


class ProjectNameConflictError(TiberError):
    """Raised when a project name is already in use."""

    error_code = "project_name_conflict"

    def __init__(self, name: str) -> None:
        """Initialize a ProjectNameConflictError with the user ID and project name."""
        self.name = name
        super().__init__(f"Project name '{name}' is already in use.")
