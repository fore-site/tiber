"""Domain exceptions for Tiber - Error conditions defined by the business domain.

The API layer maps these exceptions to HTTP status codes and error messages.
The domain layer should not be aware of the API layer or HTTP status codes.
The infrastructure layer raises these exceptions when it encounters an error condition that is defined by the business domain.
The domain defines them. Nothing outside the domain should define new error conditions that belong here.
"""


class TiberError(Exception):
    """Base class for all Tiber domain exceptions."""

    error_code = "internal_error"

    pass


# Not Found Errors


class NotFoundError(TiberError):
    """Base class for all "not found" errors."""

    error_code = "not_found"

    def __init__(self, entity: str, identifier: str) -> None:
        """Initialize a NotFoundError with the entity type and identifier."""
        super().__init__(f"{entity} with identifier '{identifier}' not found.")
        self.entity = entity
        self.identifier = identifier


class ProjectNotFoundError(NotFoundError):
    """Raised when a project is not found."""

    error_code = "project_not_found"

    def __init__(self, project_id: str) -> None:
        """Initialize a ProjectNotFoundError with the project ID."""
        super().__init__("Project", project_id)


class NotificationNotFoundError(NotFoundError):
    """Raised when a notification is not found."""

    error_code = "notification_not_found"

    def __init__(self, notification_id: str) -> None:
        """Initialize a NotificationNotFoundError with the notification ID."""
        super().__init__("Notification", notification_id)


class RecipientNotFoundError(NotFoundError):
    """Raised when a recipient is not found."""

    error_code = "recipient_not_found"

    def __init__(self, recipient_id: str) -> None:
        """Initialize a RecipientNotFoundError with the recipient ID."""
        super().__init__("Recipient", recipient_id)


class TemplateNotFoundError(NotFoundError):
    """Raised when a template is not found."""

    error_code = "template_not_found"

    def __init__(self, template_id: str) -> None:
        """Initialize a TemplateNotFoundError with the template ID."""
        super().__init__("Template", template_id)


class UserPreferenceNotFoundError(NotFoundError):
    """Raised when a user preference is not found."""

    error_code = "preference_not_found"

    def __init__(self, user_preference_id: str) -> None:
        """Initialize a UserPreferenceNotFoundError with the user preference ID."""
        super().__init__("User Preference", user_preference_id)


class APIKeyNotFoundError(NotFoundError):
    """Raised when an API key is not found."""

    error_code = "apikey_not_found"

    def __init__(self, api_key_id: str) -> None:
        """Initialize a APIKeyNotFoundError with the API key ID."""
        super().__init__("API Key", api_key_id)


class ProviderNotFoundError(NotFoundError):
    """Raised when a provider is not found."""

    error_code = "provider_not_found"

    def __init__(self, provider_id: str) -> None:
        """Initialize a ProviderNotFoundError with the provider ID."""
        super().__init__("Provider", provider_id)


class WebhookEndpointNotFoundError(NotFoundError):
    """Raised when a webhook endpoint is not found."""

    error_code = "webhook_endpoint_not_found"

    def __init__(self, webhook_endpoint_id: str) -> None:
        """Initialize a WebhookEndpointNotFoundError with the webhook endpoint ID."""
        super().__init__("Webhook Endpoint", webhook_endpoint_id)


class WebhookEventNotFoundError(NotFoundError):
    """Raised when a webhook event is not found."""

    error_code = "webhook_event_not_found"

    def __init__(self, webhook_event_id: str) -> None:
        """Initialize a WebhookEventNotFoundError with the webhook event ID."""
        super().__init__("Webhook Event", webhook_event_id)


class DeliveryPolicyNotFoundError(NotFoundError):
    """Raised when a delivery policy is not found."""

    error_code = "delivery_policy_not_found"

    def __init__(self, delivery_policy_id: str) -> None:
        """Initialize a DeliveryPolicyNotFoundError with the delivery policy ID."""
        super().__init__("Delivery Policy", delivery_policy_id)


class DeliveryAttemptNotFoundError(NotFoundError):
    """Raised when a delivery attempt is not found."""

    error_code = "delivery_attempt_not_found"

    def __init__(self, delivery_attempt_id: str) -> None:
        """Initialize a DeliveryAttemptNotFoundError with the delivery attempt ID."""
        super().__init__("Delivery Attempt", delivery_attempt_id)


class EngagementEventNotFoundError(NotFoundError):
    """Raised when an engagement event is not found."""

    error_code = "engagement_event_not_found"

    def __init__(self, engagement_event_id: str) -> None:
        """Initialize an EngagementEventNotFoundError with the engagement event ID."""
        super().__init__("Engagement Event", engagement_event_id)


# Policy & access


class PolicyViolationError(TiberError):
    """Raised when a notification violates a delivery policy.

    policy_type distinguishes between preferences, calender, and compliant constraint violations.
    """

    error_code = "policy_violated"

    def __init__(self, policy_type: str, message: str) -> None:
        """Initialize a PolicyViolationError with the policy type and message."""
        super().__init__(f"Policy violation ({policy_type}): {message}")
        self.policy_type = policy_type
        self.message = message


class ProjectScopeViolationError(TiberError):
    """Raised when an operation is attempted outside the scope of a project."""

    error_code = "project_scope_violated"

    def __init__(self, project_id: str, message: str) -> None:
        """Initialize a ProjectScopeViolationError with the project ID and message."""
        super().__init__(
            f"Project scope violation for project '{project_id}': {message}"
        )
        self.project_id = project_id
        self.message = message


class APIKeyRevokedError(TiberError):
    """Raised when an operation is attempted with a revoked API key."""

    error_code = "apikey_revoked"

    def __init__(self) -> None:
        """Initialize an APIKeyRevokedError."""
        super().__init__("API key has been revoked.")


class AuthenticationFailedError(TiberError):
    """Raised when authentication fails."""

    error_code = "authentication_failed"

    def __init__(self, message: str) -> None:
        """Initialize an AuthenticationFailedError with a message."""
        super().__init__(f"Authentication failed: {message}")
        self.message = message


# Rate limiting


class RateLimitExceededError(TiberError):
    """Raised when a rate limit is exceeded."""

    error_code = "ratelimit_exceeded"

    def __init__(self, retry_after: int | None) -> None:
        """Initialize a RateLimitExceededError."""
        self.retry_after = retry_after
        super().__init__("Rate limit exceeded.")


# Delivery


class DeliveryFailedError(TiberError):
    """Raised when a delivery attempt fails."""

    error_code = "delivery_failed"

    def __init__(self, message: str) -> None:
        """Initialize a DeliveryFailedError with a message."""
        super().__init__(f"Delivery failed: {message}")
        self.message = message


class ProviderUnavailableError(TiberError):
    """Raised when a provider is unavailable."""

    error_code = "provider_unavailable"

    def __init__(self, provider: str) -> None:
        """Initialize a ProviderUnavailableError."""
        self.provider = provider
        super().__init__(f"{provider} is unavailable.")


class PermissionDeniedError(TiberError):
    """Raised when a caller is authenticated but lacks permission for the requested operation."""

    error_code = "permission_denied"

    def __init__(self) -> None:
        """Initialize a PermissionDeniedError."""
        super().__init__("You do not have permission to access this resource.")
