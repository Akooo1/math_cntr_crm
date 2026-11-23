"""Read the project's .env as a fallback for values Docker Compose didn't pass.

Compose passes `TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN:-}`, which becomes an empty
variable when Compose can't read .env (saved by Windows Notepad with a BOM, spaces around
"=", quotes). Locally the project folder is mounted at /app, so the file itself is still
readable. The production image never contains .env (.dockerignore).
"""

import os
from pathlib import Path


def parse(text: str) -> dict[str, str]:
    values = {}
    for raw in text.lstrip("﻿").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _sep, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load(path: Path) -> list[str]:
    """Fill variables that are missing or empty. Returns the names it filled."""
    if not path.is_file():
        return []
    try:
        values = parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return []
    filled = []
    for key, value in values.items():
        if value and not os.environ.get(key):
            os.environ[key] = value
            filled.append(key)
    return filled
