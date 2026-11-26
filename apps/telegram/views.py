from django.shortcuts import render

from apps.core import dates
from apps.core.permissions import perm_required

from . import selectors, services
from .forms import SendForm
from .models import Template


def _templates_json():
    return {t.pk: t.text for t in selectors.templates()}


@perm_required("telegram.send")
def send(request):
    """Pick a template and recipients, preview, then send to the connected parents."""
    initial = {"mode": "absent", "day": dates.today()}
    student = None
    if request.GET.get("oquvchi"):
        try:
            initial.update(mode="student", student=int(request.GET["oquvchi"]))
        except ValueError:
            pass
    form = SendForm(
        request.POST or None,
        user=request.user,
        branch_filter=request.branch_filter,
        initial=initial,
    )
    targets, result, preview = [], None, None
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        targets = selectors.recipients(
            request.user, d["mode"], group=d["group"], day=d["day"], student=d["student"]
        )
        if request.POST.get("action") == "send" and targets:
            result = services.parents.send_to_parents(
                actor=request.user, targets=targets, text=d["text"], day=d["day"]
            )
        else:
            preview = [
                {
                    "student": s,
                    "connected": bool(services.parents.parent_chats(s)),
                    "text": services.parents.render(d["text"], s, g, d["day"]),
                }
                for s, g in targets
            ]
    if initial.get("student") and request.method == "GET":
        targets = selectors.recipients(request.user, "student", student=initial["student"])
        student = targets[0][0] if targets else None
    return render(
        request,
        "telegram/send.html",
        {
            "form": form,
            "preview": preview,
            "result": result,
            "student": student,
            "templates": Template.objects.filter(is_active=True),
        },
    )
