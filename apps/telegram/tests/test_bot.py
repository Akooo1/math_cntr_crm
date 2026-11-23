"""Telegram bot with a fake Telegram (docs/SPEC.md §15). Clock: Monday 16.11.2026."""

import datetime as dt

import pytest
from django.core.exceptions import PermissionDenied
from django.core.management import call_command

from apps.billing import services as billing
from apps.billing.tests.helpers import MWF, D
from apps.core import money
from apps.core.models import AuditLog
from apps.core.system_settings import set_settings
from apps.staff import services as staff
from apps.students import services as st
from apps.telegram import client as tg
from apps.telegram import selectors, services
from apps.telegram.client import TelegramError
from apps.telegram.models import Chat, Message
from tests.factories import make_group, make_student, page_text

pytestmark = pytest.mark.django_db

PARENT_PHONE = "+998951112233"


class FakeTelegram:
    def __init__(self):
        self.sent = []
        self.fail = {}  # chat_id -> TelegramError
        self.updates = []

    def call(self, method, **params):
        if method == "getMe":
            return {"username": "markaz_bot"}
        if method == "getWebhookInfo":
            return {"url": "", "pending_update_count": 0}
        if method == "getUpdates":
            out, self.updates = self.updates, []
            return out
        return True

    def send(self, chat_id, text, **extra):
        if chat_id in self.fail:
            raise self.fail[chat_id]
        self.sent.append({"chat_id": chat_id, "text": text, **extra})
        return {"message_id": len(self.sent)}

    def texts(self, chat_id):
        return [m["text"] for m in self.sent if m["chat_id"] == chat_id]


@pytest.fixture
def bot(settings):
    settings.TELEGRAM_BOT_TOKEN = "123:TEST"
    fake = FakeTelegram()
    tg.set_client(fake)
    yield fake
    tg.set_client(None)


def update(chat_id, text=None, contact=None, user_id=None):
    msg = {
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": user_id or chat_id, "first_name": "Ota"},
    }
    if text is not None:
        msg["text"] = text
    if contact is not None:
        msg["contact"] = contact
    return {"update_id": 1, "message": msg}


def share(chat_id, number, owner=None):
    services.handle_update(
        update(chat_id, contact={"phone_number": number, "user_id": owner or chat_id})
    )


@pytest.fixture
def debtor(clock, admin_a, branch_a, monthly):
    group = make_group(admin_a, branch_a, course=monthly, start=D(2026, 9, 1), days=MWF)
    student = make_student(admin_a, branch_a, parent_phone=PARENT_PHONE)
    st.enroll(actor=admin_a, student=student, group=group, start_date=D(2026, 10, 1))
    return student  # October fee due 01.10: 46 days overdue on 16.11


class TestLinking:
    def test_start_asks_for_phone(self, bot):
        services.handle_update(update(100, "/start"))
        keyboard = bot.sent[-1]["reply_markup"]["keyboard"][0][0]
        assert keyboard["request_contact"] is True

    def test_parent_links_with_own_number(self, bot, debtor):
        share(100, "998951112233")  # Telegram sends the number without "+"
        chat = Chat.objects.get(chat_id=100)
        assert (chat.kind, chat.phone, chat.is_active) == ("parent", PARENT_PHONE, True)
        assert debtor.full_name in bot.texts(100)[-1]
        assert AuditLog.objects.filter(action="telegram.chat.connect").exists()

    def test_someone_elses_contact_is_refused(self, bot, debtor):
        share(100, "998951112233", owner=999)
        assert not Chat.objects.exists()

    def test_unknown_number(self, bot, debtor):
        share(100, "998900000000")
        assert not Chat.objects.exists()
        assert bot.sent[-1]["reply_markup"] == {"remove_keyboard": True}

    def test_stop_disconnects(self, bot, debtor):
        share(100, "998951112233")
        services.handle_update(update(100, "/stop"))
        assert not Chat.objects.get(chat_id=100).is_active

    def test_staff_link_token(self, bot, clock, director):
        token = services.link_token(director)
        assert len(token) <= 64 and token.replace("_", "").isalnum()
        services.handle_update(update(200, f"/start {token}"))
        chat = Chat.objects.get(chat_id=200)
        assert (chat.kind, chat.user) == ("staff", director)
        # A forged or old link doesn't work.
        services.handle_update(update(201, f"/start {director.pk}_{'0' * 20}"))
        old = services.link_token(director, dt.date(2026, 11, 1))
        services.handle_update(update(202, f"/start {old}"))
        assert not Chat.objects.filter(chat_id__in=[201, 202]).exists()

    def test_groups_are_ignored(self, bot):
        u = update(300, "/start")
        u["message"]["chat"]["type"] = "group"
        services.handle_update(u)
        assert bot.sent == []


class TestDebtReminders:
    def test_off_by_default(self, bot, debtor, director):
        share(100, "998951112233")
        assert services.send_debt_reminders()["off"] is True

    def test_sent_once_then_waits(self, bot, debtor, director, clock):
        share(100, "998951112233")
        set_settings({"telegram.debt_reminders": 1}, actor=director)
        assert services.send_debt_reminders()["sent"] == 1
        text = bot.texts(100)[-1]
        assert debtor.full_name in text and money.format_som(900_000) in text
        again = services.send_debt_reminders()
        assert (again["sent"], again["skipped"], again["debtors"]) == (0, 1, 1)
        clock.move_to(dt.datetime(2026, 11, 23, 5, 0, tzinfo=dt.UTC))  # 7 days later
        assert services.send_debt_reminders()["sent"] == 1

    def test_paid_students_not_reminded(self, bot, debtor, director, admin_a, cash):
        share(100, "998951112233")
        set_settings({"telegram.debt_reminders": 1}, actor=director)
        billing.payments.record_payment(
            actor=admin_a, student=debtor, amount=900_000, method=cash, paid_on=D(2026, 11, 16)
        )
        assert services.send_debt_reminders()["sent"] == 0

    def test_min_days(self, bot, debtor, director):
        share(100, "998951112233")
        set_settings({"telegram.debt_reminders": 1, "telegram.debt_min_days": 60}, actor=director)
        assert services.send_debt_reminders()["sent"] == 0

    def test_blocked_chat_is_disconnected(self, bot, debtor, director):
        share(100, "998951112233")
        set_settings({"telegram.debt_reminders": 1}, actor=director)
        bot.fail[100] = TelegramError("Forbidden: bot was blocked by the user", 403)
        assert services.send_debt_reminders()["failed"] == 1
        assert not Chat.objects.get(chat_id=100).is_active
        assert Message.objects.get(kind="debt_reminder").status == "failed"

    def test_send_now_is_direktor_only(self, bot, debtor, director, admin_a):
        share(100, "998951112233")
        with pytest.raises(PermissionDenied):
            services.send_debt_reminders(force_actor=admin_a)
        assert services.send_debt_reminders(force_actor=director)["sent"] == 1  # even if off

    def test_cron_command(self, bot, debtor, director):
        share(100, "998951112233")
        set_settings({"telegram.debt_reminders": 1}, actor=director)
        call_command("telegram_send", "debts")
        assert Message.objects.filter(kind="debt_reminder", status="sent").count() == 1


class TestMorningSummary:
    def test_summary(self, bot, clock, director, branch_a, teacher_a, admin_a, manager_a):
        services.handle_update(update(200, f"/start {services.link_token(director)}"))
        staff.save_location(
            actor=director, branch=branch_a, latitude=41.2756, longitude=69.2034, radius_m=200
        )
        for user, start in ((teacher_a, dt.time(9, 0)), (admin_a, dt.time(9, 0))):
            staff.save_schedule(actor=director, user=user, start_time=start, workdays=[1])
        staff.save_schedule(actor=director, user=manager_a, start_time=dt.time(14, 0), workdays=[1])
        clock.move_to(dt.datetime(2026, 11, 16, 4, 25, tzinfo=dt.UTC))  # 09:25
        staff.check_in(actor=teacher_a, latitude=41.2756, longitude=69.2034, accuracy_m=10)
        clock.move_to(dt.datetime(2026, 11, 16, 4, 30, tzinfo=dt.UTC))  # 09:30
        assert services.send_morning_summary() == {"sent": 1, "failed": 0}
        text = bot.texts(200)[-1]
        assert teacher_a.full_name in text and "25" in text  # late 25 min
        assert admin_a.full_name in text  # work started, not here
        assert manager_a.full_name not in text  # starts at 14:00


class TestScreens:
    def test_settings_page_and_actions(self, bot, login, director, debtor, clock):
        client = login(director)
        text = page_text(client.get("/sozlamalar/telegram/"))
        assert "@markaz_bot" in text
        resp = client.get("/sozlamalar/telegram/")
        assert f"start={services.link_token(director)}" in resp.content.decode()
        services.handle_update(update(200, f"/start {services.link_token(director)}"))
        client.post("/sozlamalar/telegram/", {"action": "test"})
        assert Message.objects.filter(kind="test", status="sent").exists()

    def test_bot_off_without_token(self, settings, login, director):
        settings.TELEGRAM_BOT_TOKEN = ""
        tg.set_client(None)
        assert tg.get_client() is None
        assert selectors.bot_username() == ""
        assert page_text(login(director).get("/sozlamalar/telegram/"))
        call_command("telegram_bot", "--once")  # idles instead of crashing

    def test_student_panel(self, bot, login, director, debtor):
        client = login(director)
        assert "Ulanmagan" in page_text(client.get(f"/oquvchilar/{debtor.pk}/"))
        share(100, "998951112233")
        assert "Ota-ona ulangan" in page_text(client.get(f"/oquvchilar/{debtor.pk}/"))

    def test_polling_command_handles_updates(self, bot):
        bot.updates = [update(100, "/start")]
        call_command("telegram_bot", "--once")
        assert bot.sent and bot.sent[-1]["chat_id"] == 100


class TestDiagnostics:
    def test_client_drops_null_params(self, monkeypatch):
        import io
        import json as jsonlib

        sent = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout):
            sent["body"] = jsonlib.loads(req.data)
            return Resp(b'{"ok": true, "result": []}')

        monkeypatch.setattr(tg.urllib.request, "urlopen", fake_urlopen)
        tg.TelegramClient("123:ABC").call("getUpdates", offset=None, timeout=25)
        assert sent["body"] == {"timeout": 25}

    def test_check_without_token(self, settings, capsys):
        settings.TELEGRAM_BOT_TOKEN = ""
        tg.set_client(None)
        call_command("telegram_check")
        assert "TELEGRAM_BOT_TOKEN is empty" in capsys.readouterr().out

    def test_check_with_bot(self, bot, capsys):
        call_command("telegram_check")
        out = capsys.readouterr().out
        assert "@markaz_bot" in out and "FAIL" not in out


def test_check_explains_misnamed_env_file(settings, tmp_path, capsys):
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.BASE_DIR = tmp_path
    tg.set_client(None)
    (tmp_path / ".env.txt").write_text("TELEGRAM_BOT_TOKEN=123:ABC\n", encoding="utf-8")
    call_command("telegram_check")
    out = capsys.readouterr().out
    assert ".env.txt: has the token" in out and "named exactly .env" in out
    assert "123:ABC" not in out


class TestParentMessages:
    """Templates ("Farzandingiz kelmadi") sent by the Direktor to connected parents."""

    @pytest.fixture
    def lesson_day(self, bot, clock, admin_a, branch_a, monthly, director):
        from apps.students.models import Lesson

        group = make_group(admin_a, branch_a, course=monthly, start=D(2026, 9, 1), days=MWF)
        absent = make_student(admin_a, branch_a, parent_phone=PARENT_PHONE, first_name="Ali")
        present = make_student(admin_a, branch_a, first_name="Vali")
        for s in (absent, present):
            st.enroll(actor=admin_a, student=s, group=group, start_date=D(2026, 11, 2))
        lesson = Lesson.objects.get(group=group, date=D(2026, 11, 16))
        st.mark_attendance(actor=admin_a, lesson=lesson, student_id=absent.pk, status="absent")
        st.mark_attendance(actor=admin_a, lesson=lesson, student_id=present.pk, status="present")
        share(100, "998951112233")
        return {"group": group, "absent": absent, "present": present}

    def test_default_templates_exist(self, db):
        from apps.telegram.models import Template

        assert Template.objects.filter(title="Darsga kelmadi").exists()

    def test_render_placeholders(self, lesson_day):
        from apps.telegram.services.parents import render

        text = render("{oquvchi} | {guruh} | {sana} | {markaz} | {x}", lesson_day["absent"], "7-A")
        assert (
            text
            == f"{lesson_day['absent'].full_name} | 7-A | 16.11.2026 | Matematika Markazi | {{x}}"
        )

    def test_absent_mode_reaches_only_absent_students_parents(self, lesson_day, director, bot):
        targets = selectors.recipients(
            director, "absent", group=lesson_day["group"], day=D(2026, 11, 16)
        )
        assert [s for s, _g in targets] == [lesson_day["absent"]]
        result = services.parents.send_to_parents(
            actor=director,
            targets=targets,
            text="Farzandingiz {oquvchi} kelmadi",
            day=D(2026, 11, 16),
        )
        assert (result["sent"], result["failed"], result["no_parent"]) == (1, 0, [])
        assert bot.texts(100)[-1] == f"Farzandingiz {lesson_day['absent'].full_name} kelmadi"
        assert Message.objects.filter(kind="custom", student=lesson_day["absent"]).exists()
        assert AuditLog.objects.filter(action="telegram.message.send").exists()

    def test_group_mode_reports_unconnected_parents(self, lesson_day, director):
        targets = selectors.recipients(director, "group", group=lesson_day["group"])
        result = services.parents.send_to_parents(actor=director, targets=targets, text="Salom")
        assert result["sent"] == 1 and result["no_parent"] == [lesson_day["present"]]

    def test_only_direktor_sends(self, lesson_day, admin_a):
        with pytest.raises(PermissionDenied):
            services.parents.send_to_parents(actor=admin_a, targets=[], text="x")

    def test_page_preview_then_send(self, lesson_day, login, director, bot):
        client = login(director)
        data = {
            "text": "Farzandingiz {oquvchi} bugun kelmadi",
            "mode": "absent",
            "group": lesson_day["group"].pk,
            "day": "16.11.2026",
        }
        text = page_text(client.post("/ota-onalarga-xabar/", {**data, "action": "preview"}))
        assert lesson_day["absent"].full_name in text and "Ota-ona ulangan" in text
        assert bot.sent[-1]["chat_id"] == 100 and "kelmadi" not in bot.sent[-1]["text"]
        before = len(bot.sent)
        client.post("/ota-onalarga-xabar/", {**data, "action": "send"})
        assert len(bot.sent) == before + 1

    def test_from_student_profile(self, lesson_day, login, director, bot):
        client = login(director)
        page = page_text(client.get(f"/oquvchilar/{lesson_day['absent'].pk}/"))
        assert "Xabar yuborish" in page
        resp = client.get(f"/ota-onalarga-xabar/?oquvchi={lesson_day['absent'].pk}")
        assert lesson_day["absent"].full_name in page_text(resp)
        client.post(
            "/ota-onalarga-xabar/",
            {
                "text": "Salom",
                "mode": "student",
                "student": lesson_day["absent"].pk,
                "action": "send",
            },
        )
        assert bot.texts(100)[-1] == "Salom"
