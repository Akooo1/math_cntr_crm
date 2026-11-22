import datetime as dt

import pytest

from apps.core import dates, money, phone, text


class TestMoney:
    def test_format_som_uses_narrow_spaces(self):
        assert money.format_som(1_250_000) == "1 250 000 so'm"

    def test_format_small_and_negative(self):
        assert money.format_som(0) == "0 so'm"
        assert money.format_som(-45_000) == "-45 000 so'm"

    @pytest.mark.parametrize(
        "raw,expected",
        [("1 250 000", 1_250_000), ("450000", 450_000), ("45 000", 45_000), (12, 12)],
    )
    def test_parse_amount(self, raw, expected):
        assert money.parse_amount(raw) == expected

    @pytest.mark.parametrize("raw", ["", "abc", "12.5x", None])
    def test_parse_amount_rejects(self, raw):
        with pytest.raises(ValueError):
            money.parse_amount(raw)


class TestPhone:
    @pytest.mark.parametrize(
        "raw",
        ["+998 90 123 45 67", "998901234567", "90 123 45 67", "+998 (90) 123-45-67", "901234567"],
    )
    def test_normalize(self, raw):
        assert phone.normalize(raw) == "+998901234567"

    @pytest.mark.parametrize("raw", ["12345", "+7 900 123 45 67", "", "99890123456789"])
    def test_invalid(self, raw):
        with pytest.raises(phone.InvalidPhone):
            phone.normalize(raw)

    def test_format(self):
        assert phone.format_phone("+998901234567") == "+998 90 123 45 67"


class TestDates:
    def test_format_and_parse(self):
        assert dates.format_date(dt.date(2026, 3, 5)) == "05.03.2026"
        assert dates.parse_date("05.03.2026") == dt.date(2026, 3, 5)

    def test_add_months_clips_to_month_end(self):
        assert dates.add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
        assert dates.add_months(dt.date(2028, 1, 31), 1) == dt.date(2028, 2, 29)
        assert dates.add_months(dt.date(2026, 11, 15), 3, day=5) == dt.date(2027, 2, 5)

    def test_today_is_tashkent(self, settings):
        import time_machine

        # 20:30 UTC on 31.12 is already 01:30 on 01.01 in Tashkent (UTC+5)
        with time_machine.travel(dt.datetime(2026, 12, 31, 20, 30, tzinfo=dt.UTC), tick=False):
            assert dates.today() == dt.date(2027, 1, 1)


def test_search_key_treats_apostrophes_equal():
    assert text.search_key("Oʻzbek  G‘ulom") == text.search_key("o'zbek g'ulom")
