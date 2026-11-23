import datetime as dt

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.forms import PhoneField, StyledForm, StyledModelForm, UzDateField, UzTimeField
from apps.settings.models import Branch, Course
from apps.students.models import Group

from . import selectors
from .models import LeadActivity, LeadSource, LeadStage, RefusalReason

# --- Sozlamalar (reference data) ------------------------------------------------------


class LeadSourceForm(StyledModelForm):
    class Meta:
        model = LeadSource
        fields = ["name", "sort_order"]


class LeadStageForm(StyledModelForm):
    class Meta:
        model = LeadStage
        fields = ["name", "color", "sort_order"]

    def save(self, commit=True):
        if self.instance.pk is None:
            self.instance.kind = LeadStage.Kind.CUSTOM
        return super().save(commit)


class RefusalReasonForm(StyledModelForm):
    class Meta:
        model = RefusalReason
        fields = ["name", "sort_order"]


# --- Leads ---------------------------------------------------------------------------


def combine(day: dt.date, time: dt.time | None) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(day, time or dt.time(10, 0)))


class LeadForm(StyledForm):
    full_name = forms.CharField(label=_("Name"), max_length=150)
    phone = PhoneField(label=_("Phone"))
    extra_phone = PhoneField(label=_("Extra phone"), required=False)
    source = forms.ModelChoiceField(label=_("Source"), queryset=LeadSource.objects.none())
    course = forms.ModelChoiceField(
        label=_("Course of interest"), queryset=Course.objects.none(), required=False
    )
    branch = forms.ModelChoiceField(label=_("Branch"), queryset=Branch.objects.none())
    manager = forms.ModelChoiceField(
        label=_("Manager"), queryset=selectors.User.objects.none(), required=False
    )
    notes = forms.CharField(label=_("Notes"), widget=forms.Textarea, required=False)
    follow_up_date = UzDateField(
        label=_("Next follow-up"),
        required=False,
        help_text=_("A follow-up task is created for the manager."),
    )
    confirm_duplicate = forms.BooleanField(label=_("Save anyway"), required=False)

    def __init__(self, *args, user, branch_ids, lead=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lead = lead
        self.fields["source"].queryset = LeadSource.objects.filter(is_active=True)
        self.fields["course"].queryset = Course.objects.filter(is_active=True)
        branches = Branch.objects.filter(is_active=True)
        if branch_ids is not None:
            branches = branches.filter(pk__in=branch_ids)
        self.fields["branch"].queryset = branches
        self.fields["manager"].queryset = selectors.branch_staff(branch_ids)
        if lead is not None:
            del self.fields["branch"]
            del self.fields["follow_up_date"]
            self.fields["manager"].queryset = selectors.branch_staff([lead.branch_id])
        elif branches.count() == 1:
            self.fields["branch"].initial = branches.first()
            self.fields["branch"].widget = forms.HiddenInput()
        self.style_fields()

    def data_dict(self) -> dict:
        d = dict(self.cleaned_data)
        if d.get("follow_up_date"):
            d["follow_up_at"] = combine(d["follow_up_date"], None)
        return d


class StageForm(StyledForm):
    stage = forms.ModelChoiceField(label=_("Stage"), queryset=LeadStage.objects.none())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stage"].queryset = LeadStage.objects.filter(is_active=True).exclude(
            kind__in=[LeadStage.Kind.WON, LeadStage.Kind.LOST]
        )


class RefuseForm(StyledForm):
    reason = forms.ModelChoiceField(
        label=_("Refusal reason"), queryset=RefusalReason.objects.none()
    )
    note = forms.CharField(label=_("Note"), widget=forms.Textarea, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].queryset = RefusalReason.objects.filter(is_active=True)


class ActivityForm(StyledForm):
    kind = forms.ChoiceField(
        label=_("Type"),
        choices=[(LeadActivity.Kind.NOTE, _("Note")), (LeadActivity.Kind.CALL, _("Call"))],
        widget=forms.RadioSelect,
        initial=LeadActivity.Kind.NOTE,
    )
    text = forms.CharField(label=_("Text"), widget=forms.Textarea)


class TaskForm(StyledForm):
    title = forms.CharField(label=_("Task"), max_length=200, initial=_("Call back"))
    due_date = UzDateField(label=_("Date"))
    due_time = UzTimeField(label=_("Time"), required=False, initial="10:00")
    assigned_to = forms.ModelChoiceField(
        label=_("Assigned to"), queryset=selectors.User.objects.none()
    )

    def __init__(self, *args, lead, user, **kwargs):
        super().__init__(*args, **kwargs)
        ids = set(selectors.branch_staff([lead.branch_id]).values_list("pk", flat=True)) | {user.pk}
        self.fields["assigned_to"].queryset = selectors.User.objects.filter(pk__in=ids).order_by(
            "full_name"
        )
        self.fields["assigned_to"].initial = lead.manager_id or user.pk
        self.fields["due_date"].initial = dates.today() + dt.timedelta(days=1)

    def due_at(self) -> dt.datetime:
        return combine(self.cleaned_data["due_date"], self.cleaned_data.get("due_time"))


class TrialForm(StyledForm):
    group = forms.ModelChoiceField(label=_("Group"), queryset=Group.objects.none())
    scheduled_date = UzDateField(label=_("Trial lesson date"))
    note = forms.CharField(label=_("Note"), widget=forms.Textarea, required=False)

    def __init__(self, *args, lead=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Group.objects.none()
        if lead is not None:
            qs = (
                Group.objects.filter(branch_id=lead.branch_id)
                .exclude(status=Group.Status.FINISHED)
                .select_related("course")
                .prefetch_related("slots")
            )
            if lead.course_id:
                self.fields["group"].initial = qs.filter(course_id=lead.course_id).first()
        self.fields["group"].queryset = qs
        self.fields["group"].label_from_instance = lambda g: f"{g.name} · {_schedule(g)}"
        self.style_fields()

    def clean_scheduled_date(self):
        value = self.cleaned_data["scheduled_date"]
        if value < dates.today():
            raise ValidationError(_("The trial lesson date can't be in the past."))
        return value


def _schedule(group) -> str:
    return ", ".join(
        f"{s.get_weekday_display()[:2]} {s.start_time:%H:%M}" for s in group.slots.all()
    )


class ConvertForm(StyledForm):
    last_name = forms.CharField(label=_("Last name"), max_length=100)
    first_name = forms.CharField(label=_("First name"), max_length=100)
    middle_name = forms.CharField(label=_("Middle name"), max_length=100, required=False)
    birth_date = UzDateField(label=_("Date of birth"), required=False)
    phone = PhoneField(label=_("Student's phone"), required=False)
    parent_name = forms.CharField(label=_("Parent's name"), max_length=150, required=False)
    parent_phone = PhoneField(label=_("Parent's phone"), required=False)
    notes = forms.CharField(label=_("Notes"), widget=forms.Textarea, required=False)
    confirm_duplicate = forms.BooleanField(label=_("Save anyway"), required=False)

    def clean(self):
        data = super().clean()
        if not data.get("phone") and not data.get("parent_phone"):
            raise ValidationError(_("Enter the student's or the parent's phone."))
        return data

    @staticmethod
    def initial_for(lead) -> dict:
        parts = lead.full_name.split()
        return {
            "last_name": parts[0] if len(parts) > 1 else "",
            "first_name": " ".join(parts[1:]) if len(parts) > 1 else lead.full_name,
            "phone": lead.phone,
            "notes": lead.notes,
        }
