"""Every URL the project serves, with concrete arguments, for cross-cutting tests."""

from dataclasses import dataclass, field

from django.urls import URLPattern, URLResolver, get_resolver


def all_url_names() -> set[str]:
    names = set()

    def walk(patterns, prefix=""):
        for p in patterns:
            if isinstance(p, URLResolver):
                ns = f"{prefix}{p.namespace}:" if p.namespace else prefix
                walk(p.url_patterns, ns)
            elif isinstance(p, URLPattern) and p.name:
                names.add(prefix + p.name)

    walk(get_resolver().url_patterns)
    return names


@dataclass
class Case:
    url: str
    method: str = "get"
    expect: dict = field(default_factory=dict)  # role -> status; "anon" for anonymous
    data: dict = field(default_factory=dict)
