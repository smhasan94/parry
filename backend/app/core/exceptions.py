class ParryError(Exception):
    """Base exception for Parry domain errors."""

    def __init__(self, message: str, code: str = "INTERNAL_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(ParryError):
    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            message=f"{resource} not found: {identifier}",
            code="NOT_FOUND",
        )


class ConflictError(ParryError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="CONFLICT")


class PolicyViolationError(ParryError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="POLICY_VIOLATION")


class ConfigurationError(ParryError):
    """A required setting is missing or malformed.

    Raised in preference to degrading to an insecure fallback — e.g. we
    refuse to store a credential rather than store it unencrypted
    because no key was configured.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="CONFIGURATION_ERROR")
