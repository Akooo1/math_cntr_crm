from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditLog(models.Model):
    """Append-only (a database trigger rejects UPDATE and DELETE). docs/SPEC.md 4.6."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("User"),
    )
    action = models.CharField(_("Action"), max_length=100, db_index=True)
    entity_type = models.CharField(_("Object type"), max_length=100, db_index=True)
    entity_id = models.CharField(_("Object ID"), max_length=64, blank=True)
    branch_id = models.BigIntegerField(_("Branch"), null=True, blank=True, db_index=True)
    before = models.JSONField(_("Before"), null=True, blank=True)
    after = models.JSONField(_("After"), null=True, blank=True)
    reason = models.TextField(_("Reason"), blank=True)
    ip = models.GenericIPAddressField(_("IP address"), null=True, blank=True)
    user_agent = models.CharField(_("Browser"), max_length=300, blank=True)
    created_at = models.DateTimeField(_("Time"), auto_now_add=True, db_index=True)

    class Meta:
        db_table = "core_audit_log"
        ordering = ["-created_at", "-id"]
        verbose_name = _("Audit log entry")
        verbose_name_plural = _("Audit log")

    def __str__(self):
        return f"{self.action} {self.entity_type}#{self.entity_id}"


class OutboxEvent(models.Model):
    """Domain events for asynchronous consumers (future Telegram, SMS). docs/SPEC.md 4.4."""

    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    occurred_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        db_table = "core_outbox_event"
        ordering = ["id"]

    def __str__(self):
        return self.event_type


class SystemSetting(models.Model):
    """Typed business settings. Definitions live in code (core.system_settings)."""

    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField()
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_system_setting"

    def __str__(self):
        return self.key
