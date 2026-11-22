from django import forms
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from . import audit_display
from .forms import StyledForm, UzDateField
from .middleware import BRANCH_FILTER_SESSION_KEY
from .models import AuditLog
from .permissions import accessible_branch_ids, has_perm, login_required, perm_required
from .registry import registry


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")


@perm_required("dashboard.view")
def home(request):
    widgets = sorted(
        (w for w in registry.widgets.values() if has_perm(request.user, w.permission)),
        key=lambda w: w.order,
    )
    rendered = []
    for w in widgets:
        ctx = w.context(request) if w.context else {}
        rendered.append({"widget": w, "context": ctx})
    return render(request, "core/home.html", {"widgets": rendered})


@login_required
@require_POST
def switch_branch(request):
    raw = request.POST.get("branch") or ""
    allowed = accessible_branch_ids(request.user)
    if raw == "":
        request.session[BRANCH_FILTER_SESSION_KEY] = None
    else:
        try:
            branch_id = int(raw)
        except ValueError:
            branch_id = None
        if branch_id is not None and (allowed is None or branch_id in allowed):
            request.session[BRANCH_FILTER_SESSION_KEY] = branch_id
    target = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        target = "/"
    return redirect(target)


class AuditFilterForm(StyledForm):
    actor = forms.ModelChoiceField(
        label=_("User"), queryset=get_user_model().objects.none(), required=False
    )
    branch = forms.TypedChoiceField(label=_("Branch"), required=False, coerce=int, empty_value=None)
    entity_type = forms.ChoiceField(label=_("Object type"), required=False)
    date_from = UzDateField(label=_("From"), required=False)
    date_to = UzDateField(label=_("To"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["actor"].queryset = get_user_model().objects.order_by("full_name")
        self.fields["actor"].empty_label = _("All users")
        branches = (
            registry.branch_options_provider(None) if registry.branch_options_provider else []
        )
        self.fields["branch"].choices = [("", _("All branches"))] + [
            (b.id, b.name) for b in branches
        ]
        types = AuditLog.objects.order_by().values_list("entity_type", flat=True).distinct()
        self.fields["entity_type"].choices = [("", _("All objects"))] + sorted(
            ((t, str(audit_display.entity_label(t))) for t in types), key=lambda c: c[1]
        )


@perm_required("audit.view")
def audit_log(request):
    form = AuditFilterForm(request.GET or None)
    qs = AuditLog.objects.select_related("actor")
    if form.is_valid():
        data = form.cleaned_data
        if data["actor"]:
            qs = qs.filter(actor=data["actor"])
        if data["branch"]:
            qs = qs.filter(branch_id=data["branch"])
        if data["entity_type"]:
            qs = qs.filter(entity_type=data["entity_type"])
        if data["date_from"]:
            qs = qs.filter(created_at__date__gte=data["date_from"])
        if data["date_to"]:
            qs = qs.filter(created_at__date__lte=data["date_to"])
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    branches = registry.branch_options_provider(None) if registry.branch_options_provider else []
    branch_names = {b.id: b.name for b in branches}
    entries = [
        {
            "obj": e,
            "verb": audit_display.verb_label(e.action),
            "entity": audit_display.entity_label(e.entity_type),
            "branch": branch_names.get(e.branch_id, ""),
            "changes": audit_display.changes(e),
        }
        for e in page.object_list
    ]
    query = request.GET.copy()
    query.pop("page", None)
    return render(
        request,
        "core/audit_log.html",
        {"form": form, "page": page, "entries": entries, "query": query.urlencode()},
    )


# --- Error pages (Uzbek; Django's defaults are English) ---------------------------


def bad_request(request, exception=None):
    return render(request, "errors/400.html", status=400)


def permission_denied(request, exception=None):
    return render(request, "errors/403.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "errors/404.html", status=404)


def server_error(request):
    return render(request, "errors/500.html", status=500)


def csrf_failure(request, reason=""):
    return render(request, "errors/csrf.html", status=403)
