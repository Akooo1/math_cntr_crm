"""Sozlamalar sections owned by the settings module."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from apps.core import system_settings
from apps.core.forms import StyledForm
from apps.core.settings_panel import Column, SettingsSection, register_section

from . import services
from .forms import (
    BranchForm,
    BranchReceiptInfoForm,
    CenterInfoForm,
    CourseForm,
    PasswordResetForm,
    RoomForm,
    StaffUserForm,
)
from .models import Branch, BranchReceiptInfo, Course, Room
from .selectors import center_info

GROUP_ORG = _("Organization")
GROUP_STUDY = _("Courses and prices")
GROUP_FINANCE = _("Finance")
GROUP_CRM = _("Leads")
GROUP_SYSTEM = _("System")


class BranchSection(SettingsSection):
    slug = "filiallar"
    title = _("Branches")
    description = _("Branch names, addresses and receipt number prefixes.")
    icon = "building"
    order = 10
    group = GROUP_ORG
    model = Branch
    form_class = BranchForm
    audit_prefix = "settings.branch"
    columns = [
        Column(_("Name"), lambda b: b.name, primary=True),
        Column(_("Address"), lambda b: b.address),
        Column(_("Phone"), lambda b: b.phone, kind="phone"),
        Column(_("Receipt prefix"), lambda b: b.receipt_prefix),
    ]


class RoomSection(SettingsSection):
    slug = "xonalar"
    title = _("Rooms")
    description = _("Classrooms in each branch.")
    icon = "door"
    order = 20
    group = GROUP_ORG
    model = Room
    form_class = RoomForm
    audit_prefix = "settings.room"
    columns = [
        Column(_("Name"), lambda r: r.name, primary=True),
        Column(_("Branch"), lambda r: r.branch.name),
        Column(_("Capacity"), lambda r: r.capacity),
    ]

    def get_queryset(self, request):
        return Room.objects.select_related("branch")


class CourseSection(SettingsSection):
    slug = "kurslar"
    title = _("Courses")
    description = _("Courses and their pricing model.")
    icon = "book"
    order = 30
    group = GROUP_STUDY
    model = Course
    form_class = CourseForm
    audit_prefix = "settings.course"
    columns = [
        Column(_("Name"), lambda c: c.name, primary=True),
        Column(_("Pricing model"), lambda c: c.get_pricing_model_display(), kind="badge"),
        Column(_("Duration (months)"), lambda c: c.duration_months or "—"),
    ]


def _reset_password_view(request, section, user):
    form = PasswordResetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            from apps.accounts import services as account_services

            account_services.reset_password(
                actor=request.user, user=user, new_password=form.cleaned_data["password"]
            )
        except ValidationError as exc:
            form.add_error("password", exc)
        else:
            messages.success(request, gettext("The password was reset."))
            return redirect("settings:section_list", slug=section.slug)
    return render(
        request,
        "settings/section_form.html",
        {"section": section, "form": form, "obj": user, "title": gettext("Reset password")},
    )


class UserSection(SettingsSection):
    slug = "foydalanuvchilar"
    title = _("Users")
    description = _("Staff accounts, roles and branches.")
    icon = "users"
    order = 5
    group = GROUP_ORG
    form_class = StaffUserForm
    audit_prefix = "accounts.user"
    columns = [
        Column(_("Full name"), lambda u: u.full_name, primary=True),
        Column(_("Phone"), lambda u: u.phone, kind="phone"),
        Column(_("Role"), lambda u: u.get_role_display(), kind="badge"),
        Column(
            _("Branches"),
            lambda u: ", ".join(link.branch.name for link in u.branch_links.all()) or "—",
        ),
    ]
    actions = {"parol": (_("Reset password"), _reset_password_view)}

    @property
    def model(self):
        return get_user_model()

    def get_queryset(self, request):
        return get_user_model().objects.prefetch_related("branch_links__branch")

    def get_form(self, request, instance=None, data=None):
        return StaffUserForm(data=data, instance=instance)

    def save(self, request, form):
        return services.save_staff_user(actor=request.user, form=form, instance=form.instance)

    def can_toggle(self, request, obj):
        return obj.pk != request.user.pk

    def toggle(self, request, obj):
        services.set_user_active(actor=request.user, user=obj, active=not obj.is_active)


def _receipt_view(request, section):
    info = center_info()
    form = CenterInfoForm(
        request.POST if request.method == "POST" else None,
        instance=info if info.pk else None,
        initial=None if info.pk else {"center_name": info.center_name},
    )
    if request.method == "POST" and form.is_valid():
        services.save_center_info(actor=request.user, form=form)
        messages.success(request, gettext("Saved."))
        return redirect("settings:section_list", slug=section.slug)
    branches = Branch.objects.select_related("receipt_info").order_by("name")
    return render(
        request,
        "settings/receipt.html",
        {"section": section, "form": form, "branches": branches},
    )


def _branch_receipt_view(request, section, branch):
    instance = BranchReceiptInfo.objects.filter(branch=branch).first()
    form = BranchReceiptInfoForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        services.save_branch_receipt_info(actor=request.user, form=form, branch=branch)
        messages.success(request, gettext("Saved."))
        return redirect("settings:section_list", slug=section.slug)
    return render(
        request,
        "settings/section_form.html",
        {"section": section, "form": form, "obj": branch, "title": branch.name},
    )


class ReceiptSection(SettingsSection):
    slug = "chek"
    title = _("Receipt details")
    description = _("Center name, legal details and receipt text, with branch overrides.")
    icon = "receipt"
    order = 40
    group = GROUP_FINANCE
    model = Branch
    custom_view = staticmethod(_receipt_view)
    allow_create = False
    allow_edit = False
    allow_toggle_active = False
    actions = {"filial": (_("Branch details"), _branch_receipt_view)}


class SystemSettingsForm(StyledForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django import forms

        values = system_settings.all_values()
        for d in system_settings.definitions():
            name = d.key.replace(".", "__")
            if d.choices:
                field = forms.TypedChoiceField(
                    label=d.label, choices=d.choices, coerce=int, help_text=d.help_text
                )
            else:
                field = forms.IntegerField(
                    label=d.label,
                    min_value=d.min_value,
                    max_value=d.max_value,
                    help_text=d.help_text,
                )
            field.initial = values[d.key]
            self.fields[name] = field
        self.style_fields()

    def values(self) -> dict[str, int]:
        return {k.replace("__", "."): v for k, v in self.cleaned_data.items()}


def _system_view(request, section):
    form = SystemSettingsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        system_settings.set_settings(form.values(), actor=request.user)
        messages.success(request, gettext("Saved."))
        return redirect("settings:section_list", slug=section.slug)
    return render(
        request,
        "settings/section_form.html",
        {"section": section, "form": form, "title": section.title, "standalone": True},
    )


def _outbox_view(request, section):
    from apps.core import outbox

    if request.method == "POST":
        try:
            days = int(request.POST.get("days", ""))
            deleted = outbox.purge(actor=request.user, older_than_days=days)
        except ValueError:
            messages.error(request, gettext("Choose how old the records must be."))
        else:
            messages.success(request, gettext("Deleted: %(n)s.") % {"n": deleted})
        return redirect("settings:section_list", slug=section.slug)
    return render(
        request,
        "settings/outbox.html",
        {"section": section, "stats": outbox.stats(), "ages": outbox.AGE_CHOICES},
    )


class OutboxSection(SettingsSection):
    slug = "bildirishnomalar"
    title = _("Notification queue")
    description = _("Records for Telegram notifications. Delete old ones by hand.")
    icon = "list"
    order = 95
    group = GROUP_SYSTEM
    model = Branch
    custom_view = staticmethod(_outbox_view)
    allow_create = False
    allow_edit = False
    allow_toggle_active = False


class SystemSection(SettingsSection):
    slug = "umumiy"
    title = _("General settings")
    description = _("Rounding, due dates, backdating window, session length.")
    icon = "sliders"
    order = 90
    group = GROUP_SYSTEM
    model = Branch
    custom_view = staticmethod(_system_view)
    allow_create = False
    allow_edit = False
    allow_toggle_active = False


for section in (
    UserSection(),
    BranchSection(),
    RoomSection(),
    CourseSection(),
    ReceiptSection(),
    SystemSection(),
    OutboxSection(),
):
    register_section(section)
