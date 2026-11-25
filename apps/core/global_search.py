"""Global search (Ctrl+K). Modules register a provider in AppConfig.ready(); core never
imports them. Each provider searches only what the user may see (its own selectors apply
role and branch scope) and is skipped when the user lacks its permission."""

from collections.abc import Callable
from dataclasses import dataclass

from .permissions import has_perm

MIN_QUERY = 2
PER_GROUP = 6


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    subtitle: str = ""


@dataclass(frozen=True)
class SearchProvider:
    key: str
    label: str
    icon: str
    permission: str
    search: Callable  # search(request, query, limit) -> list[SearchHit]
    order: int = 100


_providers: dict[str, SearchProvider] = {}


def register_search_provider(provider: SearchProvider):
    _providers[provider.key] = provider


def providers() -> list[SearchProvider]:
    return sorted(_providers.values(), key=lambda p: p.order)


def run(request, query: str, limit: int = PER_GROUP) -> list[dict]:
    query = " ".join((query or "").split())
    if len(query) < MIN_QUERY:
        return []
    groups = []
    for p in providers():
        if not has_perm(request.user, p.permission):
            continue
        hits = p.search(request, query, limit)
        if hits:
            groups.append({"provider": p, "hits": hits})
    return groups
