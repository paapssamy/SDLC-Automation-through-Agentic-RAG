"""Domain exceptions."""


class InvalidTransitionError(Exception):
    """Raised when an artifact status change is not allowed by the state machine."""


class GenerationError(Exception):
    """Raised when the LLM output is still invalid after all retries."""


class AccessDeniedError(Exception):
    """Raised when a user's role is not allowed to perform an action (RBAC)."""


class GateError(Exception):
    """Raised when a stage is requested while the previous artifact is not APPROVED."""


class ValidationFailedError(Exception):
    """Raised when generated content fails a grounding / syntax check."""
