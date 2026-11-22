from .permissions import accessible_branch_ids
from .request_context import RequestInfo, current_request

BRANCH_FILTER_SESSION_KEY = "branch_filter"


def client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = current_request.set(
            RequestInfo(ip=client_ip(request), user_agent=request.META.get("HTTP_USER_AGENT", ""))
        )
        try:
            return self.get_response(request)
        finally:
            current_request.reset(token)


class BranchFilterMiddleware:
    """Sets request.branch_filter: the branch picked in the switcher, or None for 'all'.

    The value is re-validated against the user's access on every request.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.branch_filter = None
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            chosen = request.session.get(BRANCH_FILTER_SESSION_KEY)
            allowed = accessible_branch_ids(user)
            if chosen is not None and (allowed is None or chosen in allowed):
                request.branch_filter = chosen
            elif allowed is not None and len(allowed) == 1:
                request.branch_filter = next(iter(allowed))
        return self.get_response(request)
