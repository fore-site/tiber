"""
Domain exceptions for Tiber - Error conditions defined by the business domain.

The API layer maps these exceptions to HTTP status codes and error messages. 
The domain layer should not be aware of the API layer or HTTP status codes.
The infrastructure layer raises these exceptions when it encounters an error condition that is defined by the business domain.
The domain defines them. Nothing outside the domain should define new error conditions that belong here.
"""

class TiberError(Exception):
    """Base class for all Tiber domain exceptions."""
    pass


# Not Found Errors


class NotFoundError(TiberError):
    """Base class for all "not found" errors."""
    def __init__(self, entity: str, identifier: str) -> None:
        super().__init__(f"{entity} with identifier '{identifier}' not found.")
        self.entity = entity
        self.identifier = identifier


class ProjectNotFoundError(NotFoundError):
    """Raised when a project is not found."""
    def __init__(self, project_id: str) -> None:
        super().__init__("Project", project_id)


class NotificationNotFoundError(NotFoundError):
    """Raised when a notification is not found."""
    def __init__(self, notification_id: str) -> None:
        super().__init__("Notification", notification_id)


class RecipientNotFoundError(NotFoundError):
    """Raised when a recipient is not found."""
    def __init__(self, recipient_id: str) -> None:
        super().__init__("Recipient", recipient_id)


class TemplateNotFoundError(NotFoundError):
    """Raised when a template is not found."""
    def __init__(self, template_id: str) -> None:
        super().__init__("Template", template_id)


class UserPreferenceNotFoundError(NotFoundError):
    """Raised when a user preference is not found."""
    def __init__(self, user_preference_id: str) -> None:
        super().__init__("User Preference", user_preference_id)


class APIKeyNotFoundError(NotFoundError):
    """Raised when an API key is not found."""
    def __init__(self, api_key_id: str) -> None:
        super().__init__("API Key", api_key_id)


class ProviderNotFoundError(NotFoundError):
    """Raised when a provider is not found."""
    def __init__(self, provider_id: str) -> None:
        super().__init__("Provider", provider_id)


class WebhookEndpointNotFoundError(NotFoundError):
    """Raised when a webhook endpoint is not found."""
    def __init__(self, webhook_endpoint_id: str) -> None:
        super().__init__("Webhook Endpoint", webhook_endpoint_id)


class WebhookEventNotFoundError(NotFoundError):
    """Raised when a webhook event is not found."""
    def __init__(self, webhook_event_id: str) -> None:
        super().__init__("Webhook Event", webhook_event_id)


class DeliveryPolicyNotFoundError(NotFoundError):
    """Raised when a delivery policy is not found."""
    def __init__(self, delivery_policy_id: str) -> None:
        super().__init__("Delivery Policy", delivery_policy_id)


class DeliveryAttemptNotFoundError(NotFoundError):
    """Raised when a delivery attempt is not found."""
    def __init__(self, delivery_attempt_id: str) -> None:
        super().__init__("Delivery Attempt", delivery_attempt_id)


class EngagementEventNotFoundError(NotFoundError):
    """Raised when an engagement event is not found."""
    def __init__(self, engagement_event_id: str) -> None:
        super().__init__("Engagement Event", engagement_event_id)


# Policy & access


class PolicyViolation(TiberError):
    """Raised when a notification violates a delivery policy.
    policy_type distinguishes between preferences, calender, and compliant constraint violations.
    """
    def __init__(self, policy_type: str, message: str) -> None:
        super().__init__(f"Policy violation ({policy_type}): {message}")
        self.policy_type = policy_type
        self.message = message


class ProjectScopeViolation(TiberError):
    """Raised when an operation is attempted outside the scope of a project."""
    def __init__(self, project_id: str, message: str) -> None:
        super().__init__(f"Project scope violation for project '{project_id}': {message}")
        self.project_id = project_id
        self.message = message


class APIKeyRevoked(TiberError):
    """Raised when an operation is attempted with a revoked API key."""
    def __init__(self) -> None:
        super().__init__(f"API key has been revoked.")


class AuthenticationFailed(TiberError):
    """Raised when authentication fails."""
    def __init__(self, message: str) -> None:
        super().__init__(f"Authentication failed: {message}")
        self.message = message


# Idempotency


class IdempotencyKeyConflict(TiberError):
    """
    Raised when a duplicate submission is detected within the same TTL window.
    The caller should handle this by returning the same response as the original request, not a 409.
    """


# Rate limiting


class RateLimitExceeded(TiberError):
    """Raised when a rate limit is exceeded."""
    def __init__(self) -> None:
        super().__init__("Rate limit exceeded.")


# Delivery


class DeliveryFailed(TiberError):
    """Raised when a delivery attempt fails."""
    def __init__(self, message: str) -> None:
        super().__init__(f"Delivery failed: {message}")
        self.message = message


class ProviderUnavailable(TiberError):
    """Raised when a provider is unavailable."""
    def __init__(self) -> None:
        super().__init__(f"Selected provider is unavailable.")
