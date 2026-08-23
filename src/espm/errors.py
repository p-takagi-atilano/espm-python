from dataclasses import dataclass


class EspmError(Exception):
    """Base class for all SDK errors."""


class EspmReadOnlyError(EspmError):
    """Raised when a non-GET request is attempted through the transport."""


@dataclass(slots=True)
class EspmApiError(EspmError):
    message: str
    status_code: int | None = None
    error_codes: tuple[str, ...] = ()
    request_id: str | None = None

    def __str__(self) -> str:
        status = f" (HTTP {self.status_code})" if self.status_code is not None else ""
        codes = f" [{', '.join(self.error_codes)}]" if self.error_codes else ""
        return f"ESPM API error{status}{codes}: {self.message}"


class EspmAuthenticationError(EspmApiError):
    pass


class EspmAuthorizationError(EspmApiError):
    pass


class EspmNotFoundError(EspmApiError):
    pass
