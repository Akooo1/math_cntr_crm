"""config/dotenv.py: the .env fallback for local runs."""

from config import dotenv


def test_parse_tolerates_windows_notepad():
    text = (
        "﻿TELEGRAM_BOT_TOKEN = 123456:ABC-def_ghi \r\n"
        "# comment\r\n"
        'DIRECTOR_NAME="Ism Familiya"\r\n'
        "export DEMO_SEED=0\r\n"
        "BROKEN LINE\r\n"
    )
    assert dotenv.parse(text) == {
        "TELEGRAM_BOT_TOKEN": "123456:ABC-def_ghi",
        "DIRECTOR_NAME": "Ism Familiya",
        "DEMO_SEED": "0",
    }


def test_load_fills_only_missing_or_empty(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("TELEGRAM_BOT_TOKEN=123:ABC\nDEMO_SEED=0\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")  # what Compose passes when it can't read .env
    monkeypatch.setenv("DEMO_SEED", "1")  # set explicitly: wins
    filled = dotenv.load(f)
    import os

    assert filled == ["TELEGRAM_BOT_TOKEN"]
    assert os.environ["TELEGRAM_BOT_TOKEN"] == "123:ABC"
    assert os.environ["DEMO_SEED"] == "1"
    assert dotenv.load(tmp_path / "missing.env") == []
