"""Telegram connections and the message log (docs/SPEC.md §15.1)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Chat(models.Model):
    class Kind(models.TextChoices):
        PARENT = "parent", _("Parent")
        STAFF = "staff", _("Staff")

    chat_id = models.BigIntegerField(_("Telegram chat"), unique=True)
    kind = models.CharField(_("Type"), max_length=10, choices=Kind.choices)
    phone = models.CharField(_("Phone"), max_length=13, blank=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="telegram_chats",
        verbose_name=_("User"),
    )
    tg_name = models.CharField(_("Telegram name"), max_length=150, blank=True)
    connected_at = models.DateTimeField(_("Connected at"))
    is_active = models.BooleanField(_("Active"), default=True)
    disconnected_at = models.DateTimeField(_("Disconnected at"), null=True, blank=True)

    class Meta:
        db_table = "telegram_chat"
        verbose_name = _("Telegram connection")
        ordering = ["-connected_at"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="parent") & ~Q(phone=""))
                | (Q(kind="staff") & Q(user__isnull=False)),
                name="telegram_chat_kind_fields",
            )
        ]

    def __str__(self):
        return f"{self.kind} {self.chat_id}"


class Message(models.Model):
    class Kind(models.TextChoices):
        DEBT = "debt_reminder", _("Debt reminder")
        SUMMARY = "morning_summary", _("Morning summary")
        TEST = "test", _("Test message")
        CUSTOM = "custom", _("Message to parents")
        REPLY = "reply", _("Bot reply")
        BACKUP = "backup", _("Database backup")
        ALERT = "alert", _("Warning")

    class Status(models.TextChoices):
        SENT = "sent", _("Sent")
        FAILED = "failed", _("Not sent")

    chat = models.ForeignKey(
        Chat, on_delete=models.PROTECT, related_name="messages", verbose_name=_("Recipient")
    )
    kind = models.CharField(_("Type"), max_length=20, choices=Kind.choices)
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("Student"),
    )
    text = models.TextField(_("Text"))
    status = models.CharField(_("Status"), max_length=10, choices=Status.choices)
    error = models.TextField(_("Error"), blank=True)
    sent_at = models.DateTimeField(_("Time"), db_index=True)

    class Meta:
        db_table = "telegram_message"
        verbose_name = _("Telegram message")
        ordering = ["-sent_at", "-id"]
        indexes = [models.Index(fields=["student", "kind", "sent_at"])]

    def __str__(self):
        return f"{self.kind} -> {self.chat_id} ({self.status})"


class Template(models.Model):
    """A ready-made message the Direktor sends to parents ("Farzandingiz kelmadi")."""

    title = models.CharField(_("Name"), max_length=100)
    text = models.TextField(
        _("Text"),
        max_length=1000,
        help_text=_(
            "You can use: {oquvchi} student, {guruh} group, {sana} date, {filial} branch, "
            "{telefon} branch phone, {markaz} center name."
        ),
    )
    is_active = models.BooleanField(_("Active"), default=True)
    sort_order = models.PositiveIntegerField(_("Order"), default=100)

    class Meta:
        db_table = "telegram_template"
        verbose_name = _("Message template")
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title
