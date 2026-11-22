"""Per-request values (IP, user agent) that the audit log reads without passing `request`."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestInfo:
    ip: str | None = None
    user_agent: str = ""


_EMPTY = RequestInfo()
current_request: ContextVar[RequestInfo | None] = ContextVar("current_request", default=None)


def get_request_info() -> RequestInfo:
    return current_request.get() or _EMPTY
