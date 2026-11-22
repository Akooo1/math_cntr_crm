"""Modules talk only through public interfaces (CLAUDE.md, module boundaries).

import-linter (`lint-imports`) enforces the layer direction; this test enforces *which*
submodules of another module may be imported.
"""

import ast
from pathlib import Path

from django.conf import settings

PUBLIC = {"services", "selectors", "events", "models", "policies"}
APPS = Path(settings.BASE_DIR) / "apps"
EXEMPT_APPS = {"core", "demo"}  # core is the shared kernel; demo is a dev tool


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.count(".") == 1:  # "from apps.x import services"
                for alias in node.names:
                    yield f"{node.module}.{alias.name}", node.lineno
            else:
                yield node.module, node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno


def test_cross_module_imports_use_public_interfaces():
    bad = []
    for path in APPS.rglob("*.py"):
        rel = path.relative_to(APPS)
        owner = rel.parts[0]
        if owner in EXEMPT_APPS or "migrations" in rel.parts or "tests" in rel.parts:
            continue
        for module, line in _imports(path):
            parts = module.split(".")
            if parts[0] != "apps" or len(parts) < 2:
                continue
            target = parts[1]
            if target in (owner, "core"):
                continue
            if len(parts) < 3 or parts[2] not in PUBLIC:
                bad.append(f"{rel}:{line} imports {module}")
    assert not bad, "\n".join(bad)
