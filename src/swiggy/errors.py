"""Public exception hierarchy for swiggy-py."""


class SwiggyError(Exception):
    """Base class for all public swiggy-py errors."""


class ConfigurationError(SwiggyError):
    """Raised when client configuration is invalid or incomplete."""


class TransportError(SwiggyError):
    """Raised when a provider request cannot be completed."""


class ProviderResponseError(SwiggyError):
    """Raised when Swiggy returns an explicit error response."""


class SchemaDriftError(SwiggyError):
    """Raised when a provider response no longer matches its parser contract."""


class UnsafeEndpointError(SwiggyError):
    """Raised when code attempts to use a non-allowlisted endpoint."""


__all__ = [
    "ConfigurationError",
    "ProviderResponseError",
    "SchemaDriftError",
    "SwiggyError",
    "TransportError",
    "UnsafeEndpointError",
]
