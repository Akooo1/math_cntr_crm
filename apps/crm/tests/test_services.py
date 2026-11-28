import datetime as dt

import pytest
import time_machine
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.utils import timezone

from apps.core import dates
from apps.core.models import AuditLog, OutboxEvent
from apps.crm import selectors, services
from apps.crm.models import FollowUpTask, LeadActivity, LeadStage, RefusalReason, TrialLesson
from apps.students.models import Student
from tests.factories import UserFactory, make_group, make_lead

pytestmark = pytest.mark.django_db
K = LeadStage.Kind


def stage(kind):
    return LeadStage.objects.get(kind=kind)


class TestCreate:
    def test_new_lead_starts_in_new_stage_with_history(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        assert lead.stage.kind == K.NEW
        assert lead.phone_normalized == lead.phone[1:]
        assert lead.activities.get().kind == LeadActivity.Kind.CREATED
        assert OutboxEvent.objects.filter(event_type="crm.lead_created").exists()

    def test_follow_up_date_creates_task_for_manager(self, manager_a, admin_a, branch_a):
        due = timezone.now() + dt.timedelta(days=1)
        lead = make_lead(admin_a, branch_a, manager=manager_a, follow_up_at=due)
        task = lead.tasks.get()
        assert task.assigned_to == manager_a
        lead.refresh_from_db()
        assert lead.next_follow_up_at == task.due_at

    def test_cannot_create_in_foreign_branch(self, manager_a, branch_b):
        with pytest.raises(Http404):
            make_lead(manager_a, branch_b)

    def test_teacher_cannot_create(self, teacher_a, branch_a):
        with pytest.raises(PermissionDenied):
            make_lead(teacher_a, branch_a)

    def test_manager_must_belong_to_branch(self, director, branch_a, branch_b):
        other = UserFactory(role="sales_manager", branches=[branch_b])
        with pytest.raises(ValidationError):
            make_lead(director, branch_a, manager=other)


class TestDuplicates:
    def test_same_branch_duplicate_needs_confirmation(self, manager_a, branch_a):
        first = make_lead(manager_a, branch_a, phone="+998901112233")
        from apps.crm.models import LeadSource

        data = {"full_name": "X", "phone": "+998901112233", "source": LeadSource.objects.first()}
        with pytest.raises(services.DuplicateWarning) as exc:
            services.create_lead(actor=manager_a, branch=branch_a, data=data)
        assert exc.value.duplicates.leads == [first]
        services.create_lead(actor=manager_a, branch=branch_a, data=data, confirm_duplicate=True)

    def test_other_branch_shows_branch_name_only(self, manager_a, director, branch_a, branch_b):
        make_lead(director, branch_b, phone="+998901112233")
        dups = selectors.find_duplicates(manager_a, ["+998901112233"])
        assert dups.leads == [] and dups.other_branches == [branch_b.name]

    def test_extra_phone_and_students_are_checked(self, manager_a, admin_a, branch_a):
        lead = make_lead(manager_a, branch_a, phone="+998901110000", extra_phone="+998901112233")
        assert selectors.find_duplicates(manager_a, ["+998901112233"]).leads == [lead]
        Student.objects.create(
            branch=branch_a, first_name="A", last_name="B", parent_phone="+998905556677"
        )
        assert len(selectors.find_duplicates(manager_a, ["+998905556677"]).students) == 1

    def test_editing_without_changing_phone_is_not_a_duplicate(self, manager_a, branch_a):
        make_lead(manager_a, branch_a, phone="+998901112233")
        lead = make_lead(manager_a, branch_a, phone="+998901112233")
        data = {f: getattr(lead, f) for f in services.EDITABLE}
        data["notes"] = "yangi izoh"
        services.update_lead(actor=manager_a, lead=lead, data=data)  # no warning raised
        assert lead.activities.filter(kind="edit").count() == 1


class TestStages:
    def test_change_stage_logs_history(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        services.change_stage(actor=manager_a, lead=lead, stage=stage(K.CONTACTED))
        act = lead.activities.filter(kind="stage_change").get()
        assert act.from_stage.kind == K.NEW and act.to_stage.kind == K.CONTACTED

    def test_won_only_through_conversion(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        with pytest.raises(ValidationError):
            services.change_stage(actor=manager_a, lead=lead, stage=stage(K.WON))

    def test_lost_needs_reason_and_closes_tasks(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a, follow_up_at=timezone.now())
        with pytest.raises(ValidationError):
            services.change_stage(actor=manager_a, lead=lead, stage=stage(K.LOST))
        reason = RefusalReason.objects.first()
        services.refuse(actor=manager_a, lead=lead, reason=reason, note="qimmat")
        lead.refresh_from_db()
        assert lead.stage.kind == K.LOST and lead.refusal_reason == reason
        assert not lead.tasks.filter(done_at__isnull=True).exists()
        assert lead.next_follow_up_at is None

    def test_reopen_clears_reason(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        services.refuse(actor=manager_a, lead=lead, reason=RefusalReason.objects.first())
        lead = services.reopen(actor=manager_a, lead=lead)
        assert lead.stage.kind == K.CONTACTED and lead.refusal_reason is None

    def test_reopen_only_lost(self, manager_a, branch_a):
        with pytest.raises(ValidationError):
            services.reopen(actor=manager_a, lead=make_lead(manager_a, branch_a))


class TestTasks:
    def test_next_follow_up_is_earliest_open_task(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        now = timezone.now()
        late = services.create_task(
            actor=manager_a,
            lead=lead,
            assigned_to=manager_a,
            due_at=now + dt.timedelta(days=3),
            title="b",
        )
        early = services.create_task(
            actor=manager_a,
            lead=lead,
            assigned_to=manager_a,
            due_at=now + dt.timedelta(days=1),
            title="a",
        )
        lead.refresh_from_db()
        assert lead.next_follow_up_at == early.due_at
        services.complete_task(actor=manager_a, task=early)
        lead.refresh_from_db()
        assert lead.next_follow_up_at == late.due_at

    def test_grouping_overdue_today_upcoming(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        with time_machine.travel(dt.datetime(2026, 12, 10, 12, 0, tzinfo=dt.UTC), tick=False):
            base = timezone.now()
            for hours in (-30, -1, 2, 30):
                services.create_task(
                    actor=manager_a,
                    lead=lead,
                    assigned_to=manager_a,
                    due_at=base + dt.timedelta(hours=hours),
                    title=str(hours),
                )
            groups = selectors.group_tasks(selectors.tasks_for(manager_a))
            assert [t.title for t in groups["overdue"]] == ["-30", "-1"]
            assert [t.title for t in groups["today"]] == ["2"]  # 19:00 Tashkent, same day
            assert [t.title for t in groups["upcoming"]] == ["30"]

    def test_my_tasks_vs_everyone(self, manager_a, admin_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        services.create_task(
            actor=admin_a, lead=lead, assigned_to=manager_a, due_at=timezone.now(), title="x"
        )
        assert selectors.tasks_for(admin_a).count() == 0
        assert selectors.tasks_for(admin_a, everyone=True).count() == 1
        assert selectors.tasks_for(manager_a, everyone=True).count() == 1  # manager: own only


@pytest.fixture
def group_a(director, branch_a):
    """A group with a lesson every day, so 'today' always has one."""
    return make_group(
        director, branch_a, start=dates.today() - dt.timedelta(days=7), days=(1, 2, 3, 4, 5, 6, 7)
    )


class TestTrials:
    def test_booking_moves_to_trial_booked_and_attending_to_attended(
        self, manager_a, branch_a, group_a
    ):
        lead = make_lead(manager_a, branch_a)
        trial = services.book_trial(
            actor=manager_a, lead=lead, group=group_a, scheduled_date=dates.today()
        )
        assert trial.lesson.date == dates.today() and trial.group == group_a
        lead.refresh_from_db()
        assert lead.stage.kind == K.TRIAL_BOOKED
        services.set_trial_status(actor=manager_a, trial=trial, status="attended")
        lead.refresh_from_db()
        assert lead.stage.kind == K.TRIAL_ATTENDED
        assert OutboxEvent.objects.filter(event_type="crm.trial_lesson_booked").exists()

    def test_no_show_keeps_stage(self, manager_a, branch_a, group_a):
        lead = make_lead(manager_a, branch_a)
        trial = services.book_trial(
            actor=manager_a, lead=lead, group=group_a, scheduled_date=dates.today()
        )
        services.set_trial_status(actor=manager_a, trial=trial, status="no_show")
        lead.refresh_from_db()
        assert lead.stage.kind == K.TRIAL_BOOKED
        assert TrialLesson.objects.get().status == "no_show"

    def test_cannot_book_in_past_or_for_lost_lead(self, manager_a, branch_a, group_a):
        lead = make_lead(manager_a, branch_a)
        yesterday = dates.today() - dt.timedelta(days=1)
        with pytest.raises(ValidationError):
            services.book_trial(actor=manager_a, lead=lead, group=group_a, scheduled_date=yesterday)
        services.refuse(actor=manager_a, lead=lead, reason=RefusalReason.objects.first())
        with pytest.raises(ValidationError):
            services.book_trial(
                actor=manager_a, lead=lead, group=group_a, scheduled_date=dates.today()
            )

    def test_needs_a_lesson_that_day_in_the_lead_branch(
        self, manager_a, director, branch_a, branch_b
    ):
        start = dates.today() - dt.timedelta(days=7)
        weekly = make_group(director, branch_a, start=start, days=(dates.today().isoweekday(),))
        lead = make_lead(manager_a, branch_a)
        tomorrow = dates.today() + dt.timedelta(days=1)
        with pytest.raises(ValidationError):  # once-a-week group: no lesson tomorrow
            services.book_trial(actor=manager_a, lead=lead, group=weekly, scheduled_date=tomorrow)
        other = make_group(director, branch_b, start=start, days=(1, 2, 3, 4, 5, 6, 7))
        with pytest.raises(ValidationError):  # group of another branch
            services.book_trial(
                actor=manager_a, lead=lead, group=other, scheduled_date=dates.today()
            )
        trial = services.book_trial(
            actor=manager_a, lead=lead, group=weekly, scheduled_date=dates.today()
        )
        assert trial.lesson == weekly.lessons.get(date=dates.today())


class TestConversion:
    DATA = {
        "first_name": "Aziz",
        "last_name": "Karimov",
        "phone": "+998901234567",
        "parent_phone": "",
    }

    def test_convert_creates_student_and_keeps_history(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a, follow_up_at=timezone.now())
        services.add_activity(actor=manager_a, lead=lead, kind="call", text="qo'ng'iroq")
        student = services.convert(actor=manager_a, lead=lead, student_data=self.DATA)
        lead.refresh_from_db()
        assert lead.student == student and lead.stage.kind == K.WON and lead.converted_at
        assert student.branch == branch_a and student.lead == lead
        kinds = set(lead.activities.values_list("kind", flat=True))
        assert {"created", "call", "converted"} <= kinds
        assert not FollowUpTask.objects.filter(lead=lead, done_at__isnull=True).exists()
        assert AuditLog.objects.filter(action="crm.lead.convert").exists()
        assert AuditLog.objects.filter(action="students.student.create").exists()

    def test_cannot_convert_twice_or_move_after(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        services.convert(actor=manager_a, lead=lead, student_data=self.DATA)
        with pytest.raises(ValidationError):
            services.convert(actor=manager_a, lead=lead, student_data=self.DATA)
        with pytest.raises(ValidationError):
            services.change_stage(actor=manager_a, lead=lead, stage=stage(K.CONTACTED))
        assert Student.objects.count() == 1

    def test_student_needs_a_phone(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        with pytest.raises(ValidationError):
            services.convert(actor=manager_a, lead=lead, student_data={**self.DATA, "phone": ""})

    def test_existing_student_phone_is_refused_even_when_confirmed(self, manager_a, branch_a):
        """A student's own phone belongs to one student (owner's rule, SPEC §24)."""
        from django.core.exceptions import ValidationError

        Student.objects.create(
            branch=branch_a, first_name="X", last_name="Y", phone="+998901234567"
        )
        lead = make_lead(manager_a, branch_a)
        with pytest.raises(services.DuplicateWarning):
            services.convert(actor=manager_a, lead=lead, student_data=self.DATA)
        with pytest.raises(ValidationError):
            services.convert(
                actor=manager_a, lead=lead, student_data=self.DATA, confirm_duplicate=True
            )

    def test_shared_parent_phone_needs_confirmation(self, manager_a, branch_a):
        Student.objects.create(
            branch=branch_a, first_name="X", last_name="Y", parent_phone="+998901234567"
        )
        lead = make_lead(manager_a, branch_a)
        with pytest.raises(services.DuplicateWarning):
            services.convert(actor=manager_a, lead=lead, student_data=self.DATA)
        services.convert(actor=manager_a, lead=lead, student_data=self.DATA, confirm_duplicate=True)

    def test_teacher_cannot_convert(self, manager_a, teacher_a, branch_a):
        lead = make_lead(manager_a, branch_a)
        with pytest.raises(PermissionDenied):
            services.convert(actor=teacher_a, lead=lead, student_data=self.DATA)


class TestSearch:
    def test_apostrophe_insensitive_name_and_partial_phone(self, manager_a, branch_a):
        lead = make_lead(manager_a, branch_a, full_name="G‘aniyev Ulugʻbek", phone="+998901234567")
        qs = selectors.leads_for(manager_a)
        assert list(selectors.search(qs, "g'aniyev")) == [lead]
        assert list(selectors.search(qs, "ULUG'BEK")) == [lead]
        assert list(selectors.search(qs, "123 45")) == [lead]
        assert list(selectors.search(qs, "boshqa")) == []

    def test_board_scoped_to_branch(self, manager_a, director, branch_a, branch_b):
        make_lead(director, branch_b)
        mine = make_lead(manager_a, branch_a)
        cols = selectors.board(manager_a, None)
        leads = [lead for c in cols for lead in c["leads"]]
        assert leads == [mine]
