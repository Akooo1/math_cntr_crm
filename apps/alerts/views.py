from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core import listing
from apps.core.permissions import perm_required
from apps.core.ui import undo_message

from . import selectors, services
from .models import Task

KINDS = {"davomat": Task.Kind.ABSENCE, "qarz": Task.Kind.DEBT, "lid": Task.Kind.LEAD}


def _safe(target) -> bool:
    return bool(target) and target.startswith("/") and not target.startswith("//")


@perm_required("alerts.view")
def task_list(request):
    slug = request.GET.get("tur", "")
    kind = KINDS.get(slug)
    everything = selectors.open_tasks(request.user, request.branch_filter)
    shown = selectors.open_tasks(request.user, request.branch_filter, kind)
    counts = selectors.counts(request.user, request.branch_filter)
    page, query = listing.paginate(request, shown)
    return render(
        request,
        "alerts/list.html",
        {
            "page": page,
            "query": query,
            "totals": listing.totals(everything, shown if kind else None),
            "slug": slug,
            "chips": [
                ("", _("All"), counts["total"]),
                ("davomat", _("Missed lessons"), counts[Task.Kind.ABSENCE]),
                ("qarz", _("Overdue debt"), counts[Task.Kind.DEBT]),
                ("lid", _("Leads"), counts[Task.Kind.LEAD]),
            ],
        },
    )


@perm_required("alerts.view")
@require_POST
def done(request, pk):
    task = selectors.get_task(request.user, pk)
    services.close(actor=request.user, task=task)
    undo_message(request, _("Marked as done."), reverse("alerts:reopen", args=[task.pk]))
    target = request.POST.get("next")
    return redirect(target if _safe(target) else reverse("alerts:list"))


@perm_required("alerts.view")
@require_POST
def reopen(request, pk):
    task = selectors.get_task(request.user, pk)
    services.reopen(actor=request.user, task=task)
    target = request.POST.get("next")
    return redirect(target if _safe(target) else reverse("alerts:list"))
