"""Sozlamalar panel: index + generic list/create/edit/toggle for registered sections."""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.permissions import has_perm, perm_required, require_perm
from apps.core.settings_panel import get_section, sections


def _section_or_404(request, slug):
    section = get_section(slug)
    if section is None:
        raise Http404
    require_perm(request.user, section.permission)
    return section


@perm_required("settings.manage")
def index(request):
    visible = sorted(
        (s for s in sections() if has_perm(request.user, s.permission)), key=lambda s: s.order
    )
    groups: dict[str, list] = {}
    for section in visible:
        groups.setdefault(str(section.group), []).append(section)
    grouped = [{"name": name, "sections": items} for name, items in groups.items()]
    return render(request, "settings/index.html", {"groups": grouped})


@perm_required("settings.manage")
def section_list(request, slug):
    section = _section_or_404(request, slug)
    if section.custom_view is not None:
        return section.custom_view(request, section)
    show_inactive = request.GET.get("nofaol") == "1"
    qs = section.get_queryset(request)
    if hasattr(section.model, "is_active") and not show_inactive:
        qs = qs.filter(is_active=True)
    rows = [
        {
            "obj": obj,
            "can_edit": section.can_edit(request, obj),
            "can_toggle": section.can_toggle(request, obj),
        }
        for obj in qs
    ]
    return render(
        request,
        section.list_template,
        {
            "section": section,
            "rows": rows,
            "show_inactive": show_inactive,
            "has_active_flag": hasattr(section.model, "is_active"),
            "can_create": section.can_create(request),
        },
    )


def _get_obj(section, request, pk):
    return get_object_or_404(section.get_queryset(request), pk=pk)


def _form_view(request, section, obj=None):
    data = request.POST if request.method == "POST" else None
    form = section.get_form(request, instance=obj, data=data)
    if request.method == "POST" and form.is_valid():
        try:
            section.save(request, form)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Saved."))
            return redirect("settings:section_list", slug=section.slug)
    return render(
        request,
        section.form_template,
        {
            "section": section,
            "form": form,
            "obj": obj,
            "title": str(obj) if obj else _("New"),
            **section.extra_context(request, obj),
        },
    )


@perm_required("settings.manage")
def section_create(request, slug):
    section = _section_or_404(request, slug)
    if not section.can_create(request):
        raise Http404
    return _form_view(request, section)


@perm_required("settings.manage")
def section_edit(request, slug, pk):
    section = _section_or_404(request, slug)
    if not section.allow_edit:
        raise Http404
    obj = _get_obj(section, request, pk)
    if not section.can_edit(request, obj):
        raise PermissionDenied
    return _form_view(request, section, obj)


@perm_required("settings.manage")
@require_POST
def section_toggle(request, slug, pk):
    section = _section_or_404(request, slug)
    obj = _get_obj(section, request, pk)
    if not section.can_toggle(request, obj):
        raise PermissionDenied
    try:
        section.toggle(request, obj)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, _("Saved."))
    return redirect("settings:section_list", slug=section.slug)


@perm_required("settings.manage")
def section_action(request, slug, pk, action):
    section = _section_or_404(request, slug)
    if action not in section.actions:
        raise Http404
    obj = _get_obj(section, request, pk)
    _label, view = section.actions[action]
    return view(request, section, obj)
