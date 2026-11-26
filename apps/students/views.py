import datetime as dt

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_POST

from apps.core import dates, listing
from apps.core.permissions import (
    accessible_branch_ids,
    ensure_branch_access,
    has_perm,
    perm_required,
)
from apps.settings.models import Branch

from . import extensions, selectors, services
from .forms import (
    ActionForm,
    EnrollForm,
    GroupForm,
    ImportForm,
    LeaveForm,
    LessonCancelForm,
    MoveForm,
    ScheduleForm,
    StudentForm,
)
from .models import Attendance, Enrollment, Group, ImportBatch
from .services import attendance as attendance_services
from .services import importing


def _error(request, exc):
    messages.error(request, " ".join(exc.messages))


def _safe_next(request, default):
    target = request.POST.get("next") or request.GET.get("next")
    return target if target and target.startswith("/") and not target.startswith("//") else default


# --- Students -----------------------------------------------------------------------

STATUS_FILTERS = {
    "faol": ("active", gettext_lazy("Studying")),
    "muzlatilgan": ("frozen", gettext_lazy("Frozen")),
    "ketgan": ("left", gettext_lazy("Left")),
    "kutilmoqda": ("new", gettext_lazy("Awaiting enrollment")),
}


@perm_required("students.view")
def student_list(request):
    everyone = selectors.students_for(request.user, request.branch_filter)
    q = request.GET.get("q", "").strip()
    qs = selectors.search_students(everyone, q)
    group_id = request.GET.get("guruh")
    if group_id:
        qs = qs.filter(enrollments__group_id=group_id, enrollments__status__in=Enrollment.OPEN)
    status = request.GET.get("holat")
    if status == "faol":
        qs = qs.filter(enrollments__status="active")
    elif status == "muzlatilgan":
        qs = qs.filter(enrollments__status="frozen").exclude(enrollments__status="active")
    elif status == "ketgan":
        qs = qs.filter(enrollments__isnull=False).exclude(enrollments__status__in=Enrollment.OPEN)
    elif status == "kutilmoqda":
        qs = qs.filter(enrollments__isnull=True)
    qs = qs.distinct()
    filtered = listing.active_filters(request, ["q", "guruh", "holat"])
    totals = listing.totals(everyone, qs if filtered else None)
    qs, sort = listing.sort_queryset(
        request,
        qs,
        {"ism": ("last_name", "first_name", "id"), "qoshilgan": ("created_at", "id")},
        default="ism",
    )
    page, query = listing.paginate(request, selectors.with_open_groups(qs))
    badges = {}
    for provider in extensions.list_badges():
        badges.update(provider(request.user, list(page.object_list)) or {})
    actions = extensions.list_actions(request.user, list(page.object_list))
    return render(
        request,
        "students/student_list.html",
        {
            "page": page,
            "totals": totals,
            "sort": sort,
            "q": q,
            "status": status,
            "group_id": group_id,
            "statuses": [(k, v[1]) for k, v in STATUS_FILTERS.items()],
            "groups": selectors.groups_for(request.user, request.branch_filter).exclude(
                status="finished"
            ),
            "badges": badges,
            "actions": actions,
            "query": query,
            "can_manage": has_perm(request.user, "students.manage"),
        },
    )


@perm_required("students.manage")
def student_create(request):
    form = StudentForm(
        request.POST or None,
        branch_ids=accessible_branch_ids(request.user),
        initial={"branch": request.branch_filter} if request.branch_filter else None,
    )
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        branch = data.pop("branch")
        try:
            student = services.create_student(actor=request.user, branch=branch, data=data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Student created."))
            return redirect("students:detail", pk=student.pk)
    return render(request, "students/student_form.html", {"form": form, "student": None})


@perm_required("students.manage")
def student_edit(request, pk):
    student = selectors.get_student(request.user, pk)
    initial = {f: getattr(student, f) for f in services.students.FIELDS}
    form = StudentForm(request.POST or None, initial=initial, editing=True)
    if request.method == "POST" and form.is_valid():
        try:
            services.update_student(actor=request.user, student=student, data=form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Saved."))
            return redirect("students:detail", pk=student.pk)
    return render(request, "students/student_form.html", {"form": form, "student": student})


@perm_required("students.view")
def student_detail(request, pk):
    student = selectors.get_student(request.user, pk)
    enrollments = student.enrollments.select_related(
        "group", "group__course", "group__teacher"
    ).prefetch_related("events__created_by", "freezes")
    if request.user.role == "teacher":
        enrollments = enrollments.filter(group__teacher=request.user)
    panels = []
    for panel in extensions.profile_panels():
        if has_perm(request.user, panel.permission):
            panels.append({"panel": panel, "ctx": panel.context(request, student)})
    attendance = (
        Attendance.objects.filter(student=student)
        .select_related("lesson", "lesson__group")
        .order_by("-lesson__date")[:20]
    )
    if request.user.role == "teacher":
        attendance = [a for a in attendance if a.lesson.group.teacher_id == request.user.pk]
    return render(
        request,
        "students/student_detail.html",
        {
            "student": student,
            "enrollments": enrollments,
            "status": selectors.student_status(student),
            "attendance": attendance,
            "panels": panels,
            "can_manage": has_perm(request.user, "students.manage"),
        },
    )


# --- Enrollment actions (two steps when an extension asks for confirmation) ------------


def _action_view(request, *, student, form, title, build_action, execute, back):
    confirm = None
    if request.method == "POST" and form.is_valid():
        action = build_action(form.cleaned_data)
        pending = extensions.previews(action, request.POST)
        if pending and not request.POST.get("tasdiq"):
            confirm = pending
        else:
            try:
                execute(form.cleaned_data, request.POST if pending else None)
            except ValidationError as exc:
                if pending:
                    confirm = pending
                form.add_error(None, exc)
            else:
                messages.success(request, _("Saved."))
                return redirect(back)
    hidden = [
        (k, v)
        for k, v in request.POST.items()
        if k not in ("csrfmiddlewaretoken", "tasdiq", "qayta")
        and not k.startswith(extensions.FIELD_PREFIX)
    ]
    return render(
        request,
        "students/enrollment_action.html",
        {
            "student": student,
            "form": form,
            "title": title,
            "confirm": confirm,
            "hidden": hidden,
            "back": back,
        },
    )


def _enrollment_for(request, pk) -> Enrollment:
    enrollment = Enrollment.objects.select_related("student", "group").filter(pk=pk).first()
    if enrollment is None:
        raise Http404
    selectors.get_student(request.user, enrollment.student_id)  # scope check
    return enrollment


@perm_required("students.manage")
def enroll(request, pk):
    student = selectors.get_student(request.user, pk)
    form = EnrollForm(
        request.POST or None, groups=selectors.enrollable_groups(request.user, student)
    )

    def execute(d, ext):
        services.enroll(
            actor=request.user,
            student=student,
            group=d["group"],
            start_date=d["date"],
            reason=d["reason"],
            capacity_override=d["capacity_override"],
            extension_data=ext,
        )

    return _action_view(
        request,
        student=student,
        form=form,
        title=_("Enroll into a group"),
        build_action=lambda d: services.EnrollmentAction(
            "enroll", student, d["date"], group=d["group"]
        ),
        execute=execute,
        back=reverse("students:detail", args=[student.pk]),
    )


@perm_required("students.manage")
def move(request, pk):
    e = _enrollment_for(request, pk)
    groups = selectors.enrollable_groups(request.user, e.student).exclude(pk=e.group_id)
    form = MoveForm(request.POST or None, groups=groups)

    def execute(d, ext):
        services.move(
            actor=request.user,
            enrollment=e,
            target_group=d["group"],
            effective_date=d["date"],
            reason=d["reason"],
            capacity_override=d["capacity_override"],
            extension_data=ext,
        )

    return _action_view(
        request,
        student=e.student,
        form=form,
        title=_("Move from %(group)s to another group") % {"group": e.group.name},
        build_action=lambda d: services.EnrollmentAction(
            "move", e.student, d["date"], group=d["group"], enrollment=e
        ),
        execute=execute,
        back=reverse("students:detail", args=[e.student_id]),
    )


def _simple_action(request, pk, kind, title, service, date_kw, date_label):
    e = _enrollment_for(request, pk)
    form = ActionForm(request.POST or None)
    form.fields["date"].label = date_label

    def execute(d, ext):
        service(
            actor=request.user,
            enrollment=e,
            reason=d["reason"],
            extension_data=ext,
            **{date_kw: d["date"]},
        )

    return _action_view(
        request,
        student=e.student,
        form=form,
        title=f"{title}: {e.group.name}",
        build_action=lambda d: services.EnrollmentAction(
            kind, e.student, d["date"], group=e.group, enrollment=e
        ),
        execute=execute,
        back=reverse("students:detail", args=[e.student_id]),
    )


@perm_required("students.manage")
def freeze(request, pk):
    return _simple_action(
        request, pk, "freeze", _("Freeze"), services.freeze, "from_date", _("Frozen from")
    )


@perm_required("students.manage")
def unfreeze(request, pk):
    return _simple_action(
        request,
        pk,
        "unfreeze",
        _("Unfreeze"),
        services.unfreeze,
        "effective_date",
        _("Attends again from"),
    )


@perm_required("students.manage")
def leave(request, pk):
    e = _enrollment_for(request, pk)
    form = LeaveForm(request.POST or None)
    form.fields["date"].label = _("First day not attending")

    def execute(d, ext):
        services.leave(
            actor=request.user,
            enrollment=e,
            end_date=d["date"],
            reason=d["reason"],
            leave_reason=d["leave_reason"],
            extension_data=ext,
        )

    return _action_view(
        request,
        student=e.student,
        form=form,
        title=f"{_('Leave the group')}: {e.group.name}",
        build_action=lambda d: services.EnrollmentAction(
            "leave", e.student, d["date"], group=e.group, enrollment=e
        ),
        execute=execute,
        back=reverse("students:detail", args=[e.student_id]),
    )


# --- Groups -------------------------------------------------------------------------------


@perm_required("groups.view")
def group_list(request):
    everything = selectors.groups_for(request.user, request.branch_filter)
    qs = everything
    show = request.GET.get("holat", "faol")
    if show == "faol":
        qs = qs.exclude(status=Group.Status.FINISHED)
    elif show == "tugagan":
        qs = qs.filter(status=Group.Status.FINISHED)
    course = request.GET.get("kurs")
    if course:
        qs = qs.filter(course_id=course)
    teacher = request.GET.get("oqituvchi")
    if teacher:
        qs = qs.filter(teacher_id=teacher)
    qs = qs.prefetch_related("slots").order_by("name")
    return render(
        request,
        "students/group_list.html",
        {
            "groups": qs,
            "totals": listing.totals(
                everything,
                qs,
                filtered=show != "hammasi"
                or listing.active_filters(request, ["kurs", "oqituvchi"]),
            ),
            "show": show,
            "can_manage": has_perm(request.user, "groups.manage"),
        },
    )


def _group_form_view(request, group=None):
    branch_ids = accessible_branch_ids(request.user)
    initial = (
        {"branch": request.branch_filter} if (group is None and request.branch_filter) else None
    )
    form = GroupForm(request.POST or None, instance=group, branch_ids=branch_ids, initial=initial)
    schedule = ScheduleForm(
        request.POST or None, slots=list(group.slots.all()) if group else None, prefix="s"
    )
    if request.method == "POST" and form.is_valid() and schedule.is_valid():
        try:
            saved = services.save_group(
                actor=request.user, group=form.save(commit=False), slots=schedule.slots
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, _("Saved. The lesson calendar was updated."))
            return redirect("students:group", pk=saved.pk)
    return render(
        request, "students/group_form.html", {"form": form, "schedule": schedule, "group": group}
    )


@perm_required("groups.manage")
def group_create(request):
    return _group_form_view(request)


@perm_required("groups.manage")
def group_edit(request, pk):
    group = selectors.get_group(request.user, pk)
    return _group_form_view(request, Group.objects.get(pk=group.pk))


@perm_required("groups.view")
def group_detail(request, pk):
    group = selectors.get_group(request.user, pk)
    members = (
        group.enrollments.filter(status__in=Enrollment.OPEN)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    )
    return render(
        request,
        "students/group_detail.html",
        {
            "group": group,
            "members": members,
            "slots": group.slots.all(),
            "upcoming": selectors.upcoming_lessons(group),
            "recent": selectors.recent_lessons(group),
            "can_manage": has_perm(request.user, "groups.manage"),
            "can_mark": has_perm(request.user, "attendance.mark"),
            "cancel_form": LessonCancelForm(),
            "seats": group.capacity - group.open_count,
        },
    )


@perm_required("groups.manage")
@require_POST
def lesson_cancel(request, pk):
    lesson = selectors.get_lesson(request.user, pk)
    form = LessonCancelForm(request.POST)
    if form.is_valid():
        try:
            services.cancel_lesson(
                actor=request.user, lesson=lesson, reason=form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            _error(request, exc)
        else:
            messages.success(request, _("The lesson was cancelled."))
    else:
        messages.error(request, _("Write the reason."))
    return redirect(_safe_next(request, reverse("students:group", args=[lesson.group_id])))


@perm_required("groups.manage")
@require_POST
def lesson_restore(request, pk):
    lesson = selectors.get_lesson(request.user, pk)
    services.restore_lesson(actor=request.user, lesson=lesson)
    messages.success(request, _("The lesson was restored."))
    return redirect(_safe_next(request, reverse("students:group", args=[lesson.group_id])))


# --- Attendance ---------------------------------------------------------------------------


@perm_required("attendance.mark")
def attendance_day(request):
    raw = request.GET.get("sana")
    try:
        day = dates.parse_date(raw) if raw else dates.today()
    except ValueError:
        day = dates.today()
    lessons = selectors.lessons_on(request.user, day, request.branch_filter)
    return render(
        request,
        "students/attendance_day.html",
        {
            "day": day,
            "lessons": lessons,
            "totals": listing.totals(len(lessons)),
            "prev": day - dt.timedelta(days=1),
            "next": day + dt.timedelta(days=1),
            "is_today": day == dates.today(),
        },
    )


@perm_required("attendance.mark")
def attendance_lesson(request, pk):
    lesson = selectors.get_lesson(request.user, pk)
    rows = selectors.roster(lesson)
    marks = {a.student_id: a.status for a in lesson.attendance.all()}
    return render(
        request,
        "students/attendance_lesson.html",
        {
            "lesson": lesson,
            "rows": [{"enrollment": e, "status": marks.get(e.student_id)} for e in rows],
            "editable": attendance_services.can_mark(request.user, lesson),
            "present": sum(1 for s in marks.values() if s == "present"),
            "total": len(rows),
        },
    )


@perm_required("attendance.mark")
@require_POST
def attendance_mark(request, pk):
    lesson = selectors.get_lesson(request.user, pk)
    try:
        student_id = int(request.POST.get("student", "0"))
    except ValueError as exc:
        raise Http404 from exc
    status = request.POST.get("status", "")
    try:
        services.mark_attendance(
            actor=request.user, lesson=lesson, student_id=student_id, status=status
        )
    except ValidationError as exc:
        if request.headers.get("HX-Request"):
            return HttpResponse(" ".join(exc.messages), status=422)
        _error(request, exc)
        return redirect("students:attendance_lesson", pk=lesson.pk)
    if request.headers.get("HX-Request"):
        enrollment = next(e for e in selectors.roster(lesson) if e.student_id == student_id)
        return render(
            request,
            "students/_attendance_row.html",
            {
                "row": {"enrollment": enrollment, "status": status},
                "lesson": lesson,
                "editable": True,
            },
        )
    return redirect("students:attendance_lesson", pk=lesson.pk)


# --- Import -------------------------------------------------------------------------------


def _batches_for(user):
    qs = ImportBatch.objects.select_related("uploaded_by")
    ids = accessible_branch_ids(user)
    if ids is not None:
        qs = qs.filter(report__branch_id__in=list(ids))
    return qs


@perm_required("import.run")
def import_page(request):
    kinds = importing.kinds()
    form = ImportForm(
        request.POST or None,
        request.FILES or None,
        kinds=kinds,
        branch_ids=accessible_branch_ids(request.user),
        initial={"branch": request.branch_filter} if request.branch_filter else None,
    )
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            batch = importing.validate_upload(
                actor=request.user,
                kind_key=d["kind"],
                branch=d["branch"],
                uploaded_file=d["file"],
                update_existing=d["update_existing"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            return redirect("students:import_batch", pk=batch.pk)
    return render(
        request,
        "students/import.html",
        {"form": form, "kinds": kinds, "batches": _batches_for(request.user)[:15]},
    )


@perm_required("import.run")
def import_template(request, kind):
    try:
        k = importing.get_kind(kind)
    except ValidationError as exc:
        raise Http404 from exc
    response = HttpResponse(
        importing.template_workbook(k),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="namuna-{kind}.xlsx"'
    return response


def _batch(request, pk):
    batch = _batches_for(request.user).filter(pk=pk).first()
    if batch is None:
        raise Http404
    return batch


@perm_required("import.run")
def import_batch(request, pk):
    batch = _batch(request, pk)
    kind = importing.get_kind(batch.kind)
    return render(request, "students/import_batch.html", {"batch": batch, "kind": kind})


@perm_required("import.run")
@require_POST
def import_commit(request, pk):
    batch = _batch(request, pk)
    branch = Branch.objects.get(pk=batch.branch_id)
    ensure_branch_access(request.user, branch.pk)
    try:
        batch = importing.commit(actor=request.user, batch=batch, branch=branch)
    except ValidationError as exc:
        _error(request, exc)
    else:
        if batch.status == ImportBatch.Status.COMMITTED:
            messages.success(request, _("Import finished."))
        else:
            messages.error(request, _("The data changed since the check. See the errors."))
    return redirect("students:import_batch", pk=batch.pk)
