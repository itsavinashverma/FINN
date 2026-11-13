class FinnError(Exception):
    """Base error. Carries the source so failures are reported, never masked."""

    def __init__(self, message: str, *, source: str | None = None, retryable: bool = False):
        super().__init__(message)
        self.source = source
        self.retryable = retryable


class SourceUnavailable(FinnError):
    """Network failure, block (403), timeout or 5xx from an upstream source."""

    def __init__(self, message: str, *, source: str | None = None):
        super().__init__(message, source=source, retryable=True)


class NotFound(FinnError):
    """The source answered, but has no data for this identifier (e.g. unknown ticker)."""


class ParseError(FinnError):
    """The source answered with content we could not interpret (layout change, bad JSON)."""
