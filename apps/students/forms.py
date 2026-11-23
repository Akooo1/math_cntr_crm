import datetime as dt

from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.forms import PhoneField, StyledForm, StyledModelForm, UzDateField, UzTimeField
from apps.core.roles import Role
from apps.settings.models import Branch, Course, Room

from .models import Group, ImportBatch, ScheduleSlot


def _branches(branch_ids):
    qs = Branch.objects.filter(is_active=True)
    return qs if branch_ids is None else qs.filter(pk__in=branch_ids)


class StudentForm(StyledForm):
    last_name = forms.CharField(label=_("Last name"), max_length=100)
    first_name = forms.CharField(label=_("First name"), max_length=100)
    middle_name = forms.CharField(label=_("Middle name"), max_length=100, required=False)
    birth_date = UzDateField(label=_("Date of birth"), required=False)
    phone = PhoneField(label=_("Student's phone"), required=False)
    parent_name = forms.CharField(label=_("Parent's name"), max_length=150, required=False)
    parent_phone = PhoneField(label=_("Parent's phone"), required=False)
    extra_phone = PhoneField(label=_("Extra phone"), required=False)
    notes = forms.CharField(label=_("Notes"), widget=forms.Textarea, required=False)
    branch = forms.ModelChoiceField(label=_("Branch"), queryset=Branch.objects.none())

    def __init__(self, *args, branch_ids=None, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        branches = _branches(branch_ids)
        self.fields["branch"].queryset = branches
        if editing:
            del self.fields["branch"]
        elif branches.count() == 1:
            self.fields["branch"].initial = branches.first()
            self.fields["branch"].widget = forms.HiddenInput()

    def clean(self):
        data = super().clean()
        if not data.get("phone") and not data.get("parent_phone"):
            raise ValidationError(_("Enter the student's or the parent's phone."))
        return data


class GroupForm(StyledModelForm):
    class Meta:
        model = Group
        fields = [
            "name",
            "branch",
            "course",
            "teacher",
            "room",
            "start_date",
            "end_date",
            "capacity",
            "status",
            "default_installment_template",
        ]
        field_classes = {"start_date": UzDateField, "end_date": UzDateField}

    def __init__(self, *args, branch_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        branches = _branches(branch_ids)
        self.fields["branch"].queryset = branches
        teachers = get_user_model().objects.filter(role=Role.TEACHER, is_active=True)
        rooms = Room.objects.filter(is_active=True).select_related("branch")
        if branch_ids is not None:
            teachers = teachers.filter(branch_links__branch_id__in=branch_ids).distinct()
            rooms = rooms.filter(branch_id__in=branch_ids)
        self.fields["teacher"].queryset = teachers.order_by("full_name")
        self.fields["room"].queryset = rooms
        self.fields["course"].queryset = Course.objects.filter(is_active=True)
        tpl = self.fields["default_installment_template"]
        tpl.queryset = tpl.queryset.filter(is_active=True)
        tpl.help_text = _("Only for installment courses.")
        if self.instance.pk:
            self.fields["branch"].disabled = True
        elif branches.count() == 1:
            self.fields["branch"].initial = branches.first()
            self.fields["branch"].widget = forms.HiddenInput()
        self.style_fields()


class ScheduleForm(StyledForm):
    """One row per weekday: tick the day, set the time."""

    def __init__(self, *args, slots=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing = {s.weekday: s for s in (slots or [])}
        for day, label in ScheduleSlot.Weekday.choices:
            slot = existing.get(day)
            self.fields[f"d{day}"] = forms.BooleanField(
                label=label, required=False, initial=bool(slot)
            )
            self.fields[f"d{day}_start"] = UzTimeField(
                label=_("Starts"),
                required=False,
                initial=slot.start_time if slot else dt.time(15, 0),
            )
            self.fields[f"d{day}_end"] = UzTimeField(
                label=_("Ends"),
                required=False,
                initial=slot.end_time if slot else dt.time(16, 30),
            )
        self.style_fields()

    def rows(self):
        for day, label in ScheduleSlot.Weekday.choices:
            yield label, self[f"d{day}"], self[f"d{day}_start"], self[f"d{day}_end"]

    def clean(self):
        data = super().clean()
        slots = []
        for day, _label in ScheduleSlot.Weekday.choices:
            if not data.get(f"d{day}"):
                continue
            start, end = data.get(f"d{day}_start"), data.get(f"d{day}_end")
            if not start or not end or end <= start:
                raise ValidationError(
                    _("Check the lesson times: each lesson must end after it starts.")
                )
            slots.append({"weekday": day, "start_time": start, "end_time": end, "room": None})
        if not slots:
            raise ValidationError(_("Add at least one lesson to the weekly schedule."))
        self.slots = slots
        return data


# --- Enrollment actions ------------------------------------------------------------------


class ActionForm(StyledForm):
    """Shared shape for enroll / move / freeze / unfreeze / leave."""

    date = UzDateField(label=_("Date"))
    reason = forms.CharField(label=_("Reason"), widget=forms.Textarea, required=False)

    def __init__(self, *args, require_reason=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].required = require_reason
        self.fields["date"].initial = dates.today()


class EnrollForm(ActionForm):
    group = forms.ModelChoiceField(label=_("Group"), queryset=Group.objects.none())
    capacity_override = forms.BooleanField(label=_("Over capacity"), required=False)

    field_order = ["group", "date", "reason", "capacity_override"]

    def __init__(self, *args, groups=None, **kwargs):
        super().__init__(*args, require_reason=False, **kwargs)
        self.fields["group"].queryset = groups
        self.fields["group"].label_from_instance = _group_label
        self.fields["date"].label = _("Start date")


class MoveForm(ActionForm):
    group = forms.ModelChoiceField(label=_("New group"), queryset=Group.objects.none())
    capacity_override = forms.BooleanField(label=_("Over capacity"), required=False)

    field_order = ["group", "date", "reason", "capacity_override"]

    def __init__(self, *args, groups=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["group"].queryset = groups
        self.fields["group"].label_from_instance = _group_label


def _group_label(group) -> str:
    seats = group.capacity - getattr(group, "open_count", 0)
    return f"{group.name} · {group.course.name} · {seats}/{group.capacity}"


class LessonCancelForm(StyledForm):
    reason = forms.CharField(label=_("Reason"), max_length=255)


# --- Import -------------------------------------------------------------------------------


class ImportForm(StyledForm):
    kind = forms.ChoiceField(label=_("What to import"))
    branch = forms.ModelChoiceField(label=_("Branch"), queryset=Branch.objects.none())
    file = forms.FileField(label=_("Excel file (.xlsx)"))
    update_existing = forms.BooleanField(
        label=_("Update existing students"),
        required=False,
        help_text=_("Students found by phone get their details updated instead of an error."),
    )

    def __init__(self, *args, kinds, branch_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"].choices = [(k.key, k.label) for k in kinds]
        branches = _branches(branch_ids)
        self.fields["branch"].queryset = branches
        if branches.count() == 1:
            self.fields["branch"].initial = branches.first()
            self.fields["branch"].widget = forms.HiddenInput()

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith(".xlsx"):
            raise ValidationError(_("Upload an .xlsx file."))
        if f.size > 5 * 1024 * 1024:
            raise ValidationError(_("The file is larger than 5 MB."))
        return f


IMPORT_STATUSES = ImportBatch.Status
