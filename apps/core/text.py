"""Text helpers. Uzbek Latin apostrophe variants are equal for search."""

APOSTROPHES = "‘’ʻʼ`´"
_TABLE = str.maketrans({c: "'" for c in APOSTROPHES})


def normalize_apostrophes(value: str) -> str:
    return value.translate(_TABLE)


def search_key(value: str) -> str:
    return " ".join(normalize_apostrophes(value).lower().split())
