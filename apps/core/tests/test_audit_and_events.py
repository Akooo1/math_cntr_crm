import dataclasses

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from apps.core import audit, events
from apps.core.models import AuditLog, OutboxEvent


@pytest.mark.django_db
class TestAudit:
    def test_record_keeps_only_changed_fields(self, director, branch_a):
        before = audit.snapshot(branch_a)
        branch_a.address = "Yangi manzil"
        entry = audit.record(
            director,
            "settings.branch.update",
            branch_a,
            before=before,
            after=audit.snapshot(branch_a),
        )
        assert entry.before == {"address": "Toshkent"}
        assert entry.after == {"address": "Yangi manzil"}
        assert entry.entity_type == "center_settings.branch"
        assert entry.entity_id == str(branch_a.pk)

    def test_record_skips_noop_update(self, director, branch_a):
        snap = audit.snapshot(branch_a)
        assert audit.record(director, "x.update", branch_a, before=snap, after=snap) is None

    def test_branch_id_taken_from_object(self, director, branch_a):
        from apps.settings.models import Room

        room = Room.objects.create(branch=branch_a, name="1-xona", capacity=10)
        entry = audit.record(director, "settings.room.create", room, after=audit.snapshot(room))
        assert entry.branch_id == branch_a.pk

    @pytest.mark.parametrize(
        "sql", ["UPDATE core_audit_log SET action = 'x'", "DELETE FROM core_audit_log"]
    )
    def test_audit_log_is_append_only(self, director, sql):
        audit.record(director, "test.create", entity_type="test", entity_id=1, after={"a": 1})
        with pytest.raises((InternalError, IntegrityError)), transaction.atomic():
            with connection.cursor() as cur:
                cur.execute(sql)
        assert AuditLog.objects.count() == 1


@dataclasses.dataclass(frozen=True)
class SomethingHappened(events.DomainEvent):
    name = "test.something_happened"
    value: int = 0


@pytest.mark.django_db
def test_publish_runs_handlers_and_writes_outbox():
    seen = []

    @events.subscribe(SomethingHappened)
    def handler(event):
        seen.append(event.value)

    events.publish(SomethingHappened(value=7))
    assert seen == [7]
    row = OutboxEvent.objects.get()
    assert row.event_type == "test.something_happened"
    assert row.payload == {"value": 7}
    events._handlers[SomethingHappened.name].remove(handler)
