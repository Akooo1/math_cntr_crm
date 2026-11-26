from django import forms
from django.utils.translation import gettext_lazy as _

from apps.core import dates
from apps.core.forms import StyledForm, StyledModelForm, UzDateField
from apps.students import selectors as student_selectors

from . import selectors
from .models import Template

MODES = [
    ("absent", _("Absent from the lesson on a date")),
    ("group", _("The whole group")),
    ("student", _("One student")),
]


class TemplateForm(StyledModelForm):
    class Meta:
        model = Template
        fields = ["title", "text", "sort_order"]
        widgets = {"text": forms.Textarea(attrs={"rows": 5})}


class SendForm(StyledForm):
    template = forms.ModelChoiceField(queryset=None, label=_("Template"), required=False)
    text = forms.CharField(
        label=_("Text"), widget=forms.Textarea(attrs={"rows": 5}), max_length=1000
    )
    mode = forms.ChoiceField(label=_("To whom"), choices=MODES, widget=forms.RadioSelect)
    group = forms.ModelChoiceField(queryset=None, label=_("Group"), required=False)
    day = UzDateField(label=_("Date"), required=False)
    student = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, user=None, branch_filter=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["template"].queryset = selectors.templates()
        self.fields["template"].empty_label = _("Choose")
        self.fields["template"].widget.attrs["data-fill-target"] = "id_text"
        self.fields["group"].queryset = (
            student_selectors.groups_for(user, branch_filter)
            .exclude(status="finished")
            .order_by("name")
        )
        self.fields["group"].empty_label = _("Choose")
        # "One student" only when coming from a student's profile.
        from_profile = self.initial.get("student") or (
            self.data and self.data.get("mode") == "student"
        )
        if not from_profile:
            self.fields["mode"].choices = MODES[:2]

    def clean(self):
        data = super().clean()
        mode = data.get("mode")
        if mode in ("absent", "group") and not data.get("group"):
            self.add_error("group", _("Choose the group."))
        if mode == "absent" and not data.get("day"):
            data["day"] = dates.today()
        if mode == "student" and not data.get("student"):
            self.add_error(None, _("Open the student's profile and send from there."))
        return data
