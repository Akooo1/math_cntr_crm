import datetime as dt

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import dates, phone
from apps.core.permissions import accessible_branch_ids, has_perm, perm_required

from . import selectors, services
from .forms import (
    ActivityForm,
    ConvertForm,
    LeadForm,
    RefuseForm,
    StageForm,
    TaskForm,
    TrialForm,
)
from .models import LeadSource, LeadStage, TrialLesson


def _is_htmx(request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _error(request, exc: ValidationError):
    messages.error(request, " ".join(exc.messages))


def _back_to_lead(lead):
    return redirect("crm:lead", pk=lead.pk)


# --- Board ---------------------------------------------------------------------------


@perm_required("crm.leads.view")
def board(request):
    q = request.GET.get("q", "").strip()
    filters = {
        "source": request.GET.get("manba") or None,
        "manager": request.GET.get("menejer") or None,
        "course": request.GET.get("kurs") or None,
    }
    columns = selectors.board(request.user, request.branch_filter, query=q, **filters)
    stage_param = request.GET.get("bosqich")
    selected = next((c for c in columns if str(c["stage"].pk) == stage_param), None)
    phone_column = selected or (columns[0] if columns else None)
    list_page = None
    if selected is not None:
        qs = selectors.search(selectors.leads_for(request.user, request.branch_filter), q)
        qs = qs.filter(stage=selected["stage"])
        for key, field in (
            ("source", "source_id"),
            ("manager", "manager_id"),
            ("course", "course_id"),
        ):
            if filters[key]:
                qs = qs.filter(**{field: filters[key]})
        list_page = Paginator(qs.order_by("-updated_at"), 30).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    no_stage = query.copy()
    no_stage.pop("bosqich", None)
    branch_ids = accessible_branch_ids(request.user)
    if request.branch_filter:
        branch_ids = {request.branch_filter}
    return render(
        request,
        "crm/board.html",
        {
            "columns": columns,
            "selected": selected,
            "phone_column": phone_column,
            "list_page": list_page,
            "q": q,
            "filters": filters,
            "query": query.urlencode(),
            "query_no_stage": no_stage.urlencode(),
            "sources": LeadSource.objects.filter(is_active=True),
            "managers": selectors.branch_staff(branch_ids),
            "now": dates.now(),
        },
    )


@perm_required("crm.leads.edit")
@require_POST
def move(request, pk):
    """Stage change from the board (drag and drop) or the lead card."""
    lead = selectors.get_lead(request.user, pk)
    stage = get_object_or_404(LeadStage, pk=request.POST.get("stage"), is_active=True)
    if stage.kind == LeadStage.Kind.LOST:
        target = reverse("crm:refuse", args=[lead.pk])
    elif stage.kind == LeadStage.Kind.WON:
        target = reverse("crm:convert", args=[lead.pk])
    else:
        target = None
        try:
            services.change_stage(actor=request.user, lead=lead, stage=stage)
        except ValidationError as exc:
            _error(request, exc)
            target = request.POST.get("next") or reverse("crm:lead", args=[lead.pk])
    if _is_htmx(request):
        resp = HttpResponse(status=204)
        if target:
            resp["HX-Redirect"] = target
        return resp
    return redirect(target or request.POST.get("next") or reverse("crm:lead", args=[lead.pk]))


# --- Lead create / edit / card ---------------------------------------------------------


def _lead_form_view(request, lead=None):
    branch_ids = accessible_branch_ids(request.user)
    initial = {}
    if lead is None:
        if request.branch_filter:
            initial["branch"] = request.branch_filter
        if request.user.role == "sales_manager":
            initial["manager"] = request.user.pk
    else:
        initial = {f: getattr(lead, f) for f in services.EDITABLE}
    form = LeadForm(
        request.POST or None,
        initial=initial,
        user=request.user,
        branch_ids=branch_ids,
        lead=lead,
    )
    duplicates = None
    if request.method == "POST" and form.is_valid():
        data = form.data_dict()
        confirm = data.get("confirm_duplicate", False)
        try:
            if lead is None:
                lead = services.create_lead(
                    actor=request.user, branch=data["branch"], data=data, confirm_duplicate=confirm
                )
                messages.success(request, _("Lead created."))
            else:
                services.update_lead(
                    actor=request.user, lead=lead, data=data, confirm_duplicate=confirm
                )
                messages.success(request, _("Saved."))
            return _back_to_lead(lead)
        except services.DuplicateWarning as exc:
            duplicates = exc.duplicates
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(
        request,
        "crm/lead_form.html",
        {"form": form, "lead": lead, "duplicates": duplicates},
    )


@perm_required("crm.leads.edit")
def lead_create(request):
    return _lead_form_view(request)


@perm_required("crm.leads.edit")
def lead_edit(request, pk):
    lead = selectors.get_lead(request.user, pk)
    return _lead_form_view(request, lead)


@perm_required("crm.leads.view")
def lead_detail(request, pk):
    lead = selectors.get_lead(request.user, pk)
    return render(
        request,
        "crm/lead_detail.html",
        {
            "lead": lead,
            "activities": lead.activities.select_related("created_by", "from_stage", "to_stage"),
            "open_tasks": lead.tasks.filter(done_at__isnull=True).select_related("assigned_to"),
            "done_tasks": lead.tasks.filter(done_at__isnull=False).select_related("assigned_to")[
                :10
            ],
            "trials": lead.trials.all(),
            "stage_form": StageForm(initial={"stage": lead.stage_id}),
            "activity_form": ActivityForm(),
            "task_form": TaskForm(lead=lead, user=request.user),
            "trial_form": TrialForm(),
            "now": dates.now(),
            "can_edit": has_perm(request.user, "crm.leads.edit"),
            "can_convert": has_perm(request.user, "crm.leads.convert") and not lead.is_converted,
        },
    )


# --- Lead actions ------------------------------------------------------------------------


@perm_required("crm.leads.edit")
@require_POST
def add_activity(request, pk):
    lead = selectors.get_lead(request.user, pk)
    form = ActivityForm(request.POST)
    if form.is_valid():
        try:
            services.add_activity(actor=request.user, lead=lead, **form.cleaned_data)
        except ValidationError as exc:
            _error(request, exc)
    else:
        messages.error(request, _("Write the text."))
    return _back_to_lead(lead)


@perm_required("crm.leads.edit")
def refuse(request, pk):
    lead = selectors.get_lead(request.user, pk)
    form = RefuseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.refuse(
                actor=request.user,
                lead=lead,
                reason=form.cleaned_data["reason"],
                note=form.cleaned_data["note"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("The lead is marked as refused."))
            return _back_to_lead(lead)
    return render(request, "crm/refuse.html", {"form": form, "lead": lead})


@perm_required("crm.leads.edit")
@require_POST
def reopen(request, pk):
    lead = selectors.get_lead(request.user, pk)
    try:
        services.reopen(actor=request.user, lead=lead)
    except ValidationError as exc:
        _error(request, exc)
    else:
        messages.success(request, _("The lead is reopened."))
    return _back_to_lead(lead)


@perm_required("crm.leads.edit")
@require_POST
def task_create(request, pk):
    lead = selectors.get_lead(request.user, pk)
    form = TaskForm(request.POST, lead=lead, user=request.user)
    if form.is_valid():
        try:
            services.create_task(
                actor=request.user,
                lead=lead,
                assigned_to=form.cleaned_data["assigned_to"],
                due_at=form.due_at(),
                title=form.cleaned_data["title"],
            )
        except ValidationError as exc:
            _error(request, exc)
        else:
            messages.success(request, _("Task added."))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return _back_to_lead(lead)


@perm_required("crm.leads.edit")
@require_POST
def task_done(request, pk):
    task = selectors.get_task(request.user, pk)
    services.complete_task(actor=request.user, task=task)
    if _is_htmx(request):
        return HttpResponse("")
    target = request.POST.get("next")
    return redirect(target if target and target.startswith("/") else reverse("crm:tasks"))


@perm_required("crm.leads.edit")
@require_POST
def trial_book(request, pk):
    lead = selectors.get_lead(request.user, pk)
    form = TrialForm(request.POST)
    if form.is_valid():
        try:
            services.book_trial(actor=request.user, lead=lead, **form.cleaned_data)
        except ValidationError as exc:
            _error(request, exc)
        else:
            messages.success(request, _("Booked for a trial lesson."))
    else:
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return _back_to_lead(lead)


@perm_required("crm.leads.edit")
@require_POST
def trial_status(request, pk):
    trial = selectors.get_trial(request.user, pk)
    status = request.POST.get("status", "")
    try:
        services.set_trial_status(actor=request.user, trial=trial, status=status)
    except ValidationError as exc:
        _error(request, exc)
    target = request.POST.get("next")
    return redirect(
        target if target and target.startswith("/") else reverse("crm:lead", args=[trial.lead_id])
    )


@perm_required("crm.leads.convert")
def convert(request, pk):
    lead = selectors.get_lead(request.user, pk)
    if lead.is_converted:
        messages.error(request, _("This lead is already a student."))
        return _back_to_lead(lead)
    form = ConvertForm(request.POST or None, initial=ConvertForm.initial_for(lead))
    duplicates = None
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        confirm = data.pop("confirm_duplicate", False)
        try:
            services.convert(
                actor=request.user, lead=lead, student_data=data, confirm_duplicate=confirm
            )
        except services.DuplicateWarning as exc:
            duplicates = exc.duplicates
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(
                request,
                _(
                    "The student was created. "
                    "Enrollment into a group is done by the branch administrator."
                ),
            )
            return _back_to_lead(lead)
    return render(
        request, "crm/convert.html", {"form": form, "lead": lead, "duplicates": duplicates}
    )


@perm_required("crm.leads.view")
def duplicate_check(request):
    """HTMX: warning box under the phone field while the lead form is being filled."""
    raw = [request.GET.get("phone", ""), request.GET.get("extra_phone", "")]
    phones = [p for p in (phone.normalize_or_none(r) for r in raw) if p]
    exclude = request.GET.get("lead") or None
    dups = selectors.find_duplicates(request.user, phones, exclude_lead_id=exclude)
    return render(request, "crm/_duplicates.html", {"duplicates": dups if dups else None})


# --- Lists ---------------------------------------------------------------------------


@perm_required("crm.leads.view")
def tasks(request):
    everyone = request.GET.get("hammasi") == "1" and has_perm(request.user, "crm.tasks.view_all")
    groups = selectors.group_tasks(
        selectors.tasks_for(request.user, request.branch_filter, everyone=everyone)
    )
    return render(
        request,
        "crm/tasks.html",
        {
            "groups": groups,
            "everyone": everyone,
            "can_view_all": has_perm(request.user, "crm.tasks.view_all"),
            "total": sum(len(v) for v in groups.values()),
        },
    )


@perm_required("crm.leads.view")
def trials(request):
    today = dates.today()
    items = selectors.trials_for(
        request.user, request.branch_filter, from_date=today - dt.timedelta(days=7)
    )
    upcoming = [
        t for t in items if t.scheduled_date >= today and t.status == TrialLesson.Status.BOOKED
    ]
    past_open = [
        t for t in items if t.scheduled_date < today and t.status == TrialLesson.Status.BOOKED
    ]
    recent = [t for t in items if t.status != TrialLesson.Status.BOOKED]
    return render(
        request,
        "crm/trials.html",
        {"upcoming": upcoming, "past_open": past_open, "recent": recent, "today": today},
    )
