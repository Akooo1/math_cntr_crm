"""Import kinds owned by the students module: groups and students (docs/SPEC.md 6.5)."""

from django.contrib.auth import get_user_model
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core import phone as phones
from apps.core.roles import Role
from apps.core.text import search_key
from apps.settings.models import Course, Room

from .models import Enrollment, Group, Student
from .services import enrollments as enrollment_services
from .services import groups as group_services
from .services import students as student_services
from .services.importing import (
    ImportKind,
    ParseResult,
    RowError,
    as_date,
    as_phone,
    as_time,
    as_weekdays,
    register_import_kind,
    text,
)

# --- groups ------------------------------------------------------------------------------

G_NAME, G_COURSE, G_TEACHER, G_ROOM = (
    gettext_lazy("Group name"),
    gettext_lazy("Course"),
    gettext_lazy("Teacher's phone"),
    gettext_lazy("Room"),
)
G_DAYS, G_START_T, G_END_T = (
    gettext_lazy("Lesson days"),
    gettext_lazy("Lesson starts"),
    gettext_lazy("Lesson ends"),
)
G_START, G_END, G_CAP = (
    gettext_lazy("Start date"),
    gettext_lazy("End date"),
    gettext_lazy("Capacity"),
)

GROUP_COLUMNS = [
    (G_NAME, "Matematika 7-A"),
    (G_COURSE, "Matematika 7–9-sinf"),
    (G_TEACHER, "+998900000013"),
    (G_ROOM, "1-xona"),
    (G_DAYS, "Du, Cho, Ju"),
    (G_START_T, "15:00"),
    (G_END_T, "16:30"),
    (G_START, "01.09.2026"),
    (G_END, ""),
    (G_CAP, 12),
]


def parse_groups(raw, ctx) -> ParseResult:
    result = ParseResult()
    courses = {search_key(c.name): c for c in Course.objects.filter(is_active=True)}
    rooms = {search_key(r.name): r for r in Room.objects.filter(branch=ctx.branch, is_active=True)}
    teachers = {
        u.phone: u
        for u in get_user_model().objects.filter(
            role=Role.TEACHER, is_active=True, branch_links__branch=ctx.branch
        )
    }
    existing = {
        search_key(n)
        for n in Group.objects.filter(branch=ctx.branch).values_list("name", flat=True)
    }
    seen = set()
    for number, row in raw:
        errs = []

        def err(msg, number=number, errs=errs):
            errs.append(RowError(number, msg))

        name = text(row.get(str(G_NAME)))
        if not name:
            err(_("the group name is empty"))
        elif search_key(name) in existing:
            err(_('a group named "%(name)s" already exists') % {"name": name})
        elif search_key(name) in seen:
            err(_('the group name "%(name)s" repeats in the file') % {"name": name})
        seen.add(search_key(name))
        course = courses.get(search_key(text(row.get(str(G_COURSE)))))
        if course is None:
            err(_('course "%(v)s" not found in Settings') % {"v": text(row.get(str(G_COURSE)))})
        try:
            teacher = teachers.get(as_phone(row.get(str(G_TEACHER))))
        except phones.InvalidPhone:
            teacher = None
        if teacher is None:
            err(
                _('no teacher with phone "%(v)s" in this branch')
                % {"v": text(row.get(str(G_TEACHER)))}
            )
        room = None
        if text(row.get(str(G_ROOM))):
            room = rooms.get(search_key(text(row.get(str(G_ROOM)))))
            if room is None:
                err(_('room "%(v)s" not found in this branch') % {"v": text(row.get(str(G_ROOM)))})
        try:
            days = as_weekdays(row.get(str(G_DAYS)))
        except ValueError:
            days = []
            err(_("lesson days are wrong (use Du, Se, Cho, Pa, Ju, Sh, Ya)"))
        try:
            start_t, end_t = as_time(row.get(str(G_START_T))), as_time(row.get(str(G_END_T)))
            if end_t <= start_t:
                err(_("the lesson must end after it starts"))
        except ValueError:
            start_t = end_t = None
            err(_("the lesson time is wrong (use HH:MM)"))
        try:
            start = as_date(row.get(str(G_START)))
            end = as_date(row.get(str(G_END)))
            if start is None:
                err(_("the start date is empty"))
            elif end and end < start:
                err(_("the end date is before the start date"))
        except ValueError:
            start = end = None
            err(_("a date is wrong (use DD.MM.YYYY)"))
        try:
            capacity = int(text(row.get(str(G_CAP))) or 12)
            if capacity < 1:
                raise ValueError
        except ValueError:
            capacity = None
            err(_("the capacity must be a positive whole number"))
        if errs:
            result.errors.extend(errs)
            continue
        result.rows.append(
            {
                "name": name,
                "course": course,
                "teacher": teacher,
                "room": room,
                "days": days,
                "start_time": start_t,
                "end_time": end_t,
                "start_date": start,
                "end_date": end,
                "capacity": capacity,
            }
        )
    return result


def commit_groups(rows, ctx) -> dict:
    for r in rows:
        group = Group(
            branch=ctx.branch,
            course=r["course"],
            teacher=r["teacher"],
            room=r["room"],
            name=r["name"],
            start_date=r["start_date"],
            end_date=r["end_date"],
            capacity=r["capacity"],
        )
        slots = [
            {"weekday": d, "start_time": r["start_time"], "end_time": r["end_time"], "room": None}
            for d in r["days"]
        ]
        group_services.save_group(actor=ctx.actor, group=group, slots=slots, import_batch=ctx.batch)
    return {"groups_created": len(rows)}


# --- students ----------------------------------------------------------------------------

S_LAST, S_FIRST, S_MIDDLE, S_BIRTH = (
    gettext_lazy("Last name"),
    gettext_lazy("First name"),
    gettext_lazy("Middle name"),
    gettext_lazy("Date of birth"),
)
S_PHONE, S_PARENT, S_PARENT_PHONE = (
    gettext_lazy("Phone"),
    gettext_lazy("Parent's name"),
    gettext_lazy("Parent's phone"),
)
S_GROUP, S_JOINED, S_NOTES = (
    gettext_lazy("Group name"),
    gettext_lazy("Joined the group on"),
    gettext_lazy("Notes"),
)

STUDENT_COLUMNS = [
    (S_LAST, "Karimov"),
    (S_FIRST, "Aziz"),
    (S_MIDDLE, ""),
    (S_BIRTH, "14.03.2013"),
    (S_PHONE, "+998901234567"),
    (S_PARENT, "Karimova Dilfuza"),
    (S_PARENT_PHONE, "+998907654321"),
    (S_GROUP, "Matematika 7-A"),
    (S_JOINED, "01.09.2026"),
    (S_NOTES, ""),
]


def parse_students(raw, ctx) -> ParseResult:
    result = ParseResult()
    groups = {
        search_key(g.name): g
        for g in Group.objects.filter(branch=ctx.branch).exclude(status="finished")
    }
    # A student in several groups comes as one row per group with the same phone: the first
    # row creates (or updates) the student, the next rows only add a group.
    seen_phones: dict[str, dict] = {}
    for number, row in raw:
        errs = []

        def err(msg, number=number, errs=errs):
            errs.append(RowError(number, msg))

        last, first = text(row.get(str(S_LAST))), text(row.get(str(S_FIRST)))
        if not last or not first:
            err(_("the last name and first name are required"))
        try:
            ph = as_phone(row.get(str(S_PHONE)))
            parent_ph = as_phone(row.get(str(S_PARENT_PHONE)))
        except phones.InvalidPhone:
            ph = parent_ph = ""
            err(_("a phone number is wrong (use +998 90 123 45 67)"))
        if not ph and not parent_ph and not errs:
            err(_("enter the student's or the parent's phone"))
        try:
            birth = as_date(row.get(str(S_BIRTH)))
            joined = as_date(row.get(str(S_JOINED)))
        except ValueError:
            birth = joined = None
            err(_("a date is wrong (use DD.MM.YYYY)"))
        # The student's own phone is one person. A parent's phone may be shared by siblings,
        # so without the student's phone a row is that phone plus the name.
        name_key = (search_key(last), search_key(first))
        key_phone = ph or ((parent_ph, *name_key) if parent_ph else "")
        existing = None
        first_row = seen_phones.get(key_phone) if key_phone else None
        if first_row is not None:
            if name_key != first_row["name"]:
                err(
                    _("the phone repeats row %(n)d of the file with another name")
                    % {"n": first_row["number"]}
                )
            elif not text(row.get(str(S_GROUP))):
                err(_("the phone repeats row %(n)d of the file") % {"n": first_row["number"]})
            existing = first_row["existing"]
        elif key_phone:
            seen_phones[key_phone] = first_row = {
                "number": number,
                "name": name_key,
                "existing": None,
                "groups": {},
            }
            match = Student.objects.filter(phone=ph).first() if ph else None
            if match is None and not ph:
                match = next(
                    (
                        s
                        for s in Student.objects.filter(phone="", parent_phone=parent_ph)
                        if (search_key(s.last_name), search_key(s.first_name)) == name_key
                    ),
                    None,
                )
            if match is not None:
                if match.branch_id != ctx.branch.pk:
                    err(_("this phone belongs to a student of another branch"))
                elif not ctx.update_existing:
                    err(
                        _("student %(name)s already exists (tick 'update existing')")
                        % {"name": match.full_name}
                    )
                else:
                    existing = first_row["existing"] = match
            first_row = None  # this is the first row, not a repeat
        group = None
        group_name = text(row.get(str(S_GROUP)))
        if group_name:
            group = groups.get(search_key(group_name))
            if group is None:
                err(_('group "%(v)s" not found in this branch') % {"v": group_name})
            elif joined is None:
                err(_("enter the date the student joined the group"))
            elif joined < group.start_date:
                err(_("the join date is before the group starts"))
            elif first_row is not None and group.pk in first_row["groups"]:
                err(
                    _("the student is already in this group on row %(n)d")
                    % {"n": first_row["groups"][group.pk]}
                )
            elif (
                existing
                and Enrollment.objects.filter(
                    student=existing, group=group, status__in=Enrollment.OPEN
                ).exists()
            ):
                group = None  # already enrolled: only contacts get updated
        if key_phone and group is not None:
            seen_phones[key_phone]["groups"].setdefault(group.pk, number)
        if errs:
            result.errors.extend(errs)
            continue
        result.rows.append(
            {
                "key": key_phone,
                "repeat": first_row is not None,
                "existing": existing,
                "data": {
                    "last_name": last,
                    "first_name": first,
                    "middle_name": text(row.get(str(S_MIDDLE))),
                    "birth_date": birth,
                    "phone": ph,
                    "parent_name": text(row.get(str(S_PARENT))),
                    "parent_phone": parent_ph,
                    "notes": text(row.get(str(S_NOTES))),
                },
                "group": group,
                "joined": joined,
            }
        )
    return result


def commit_students(rows, ctx) -> dict:
    created = updated = enrolled = 0
    reason = _("Imported from Excel")
    by_phone = {}
    for r in rows:
        if r["repeat"]:
            student = by_phone[r["key"]]  # another group for the student of an earlier row
        elif r["existing"] is not None:
            data = {k: v for k, v in r["data"].items() if v not in ("", None)}
            merged = {f: getattr(r["existing"], f) for f in student_services.FIELDS} | data
            student = student_services.update_student(
                actor=ctx.actor, student=r["existing"], data=merged
            )
            updated += 1
        else:
            student = student_services.create_student(
                actor=ctx.actor, branch=ctx.branch, data=r["data"], import_batch=ctx.batch
            )
            created += 1
        by_phone.setdefault(r["key"], student)
        if r["group"] is not None:
            # Imported enrollments skip extensions: past money comes from opening balances.
            enrollment_services.enroll(
                actor=ctx.actor,
                student=student,
                group=r["group"],
                start_date=r["joined"],
                reason=reason,
                capacity_override=True,
                skip_extensions=True,
                import_batch=ctx.batch,
            )
            enrolled += 1
    return {
        "students_created": created,
        "students_updated": updated,
        "enrollments_created": enrolled,
    }


def register():
    register_import_kind(
        ImportKind(
            key="groups",
            label=gettext_lazy("Groups"),
            columns=GROUP_COLUMNS,
            parse=parse_groups,
            commit=commit_groups,
            help_text=gettext_lazy("Courses, teachers and rooms must exist in Settings first."),
        )
    )
    register_import_kind(
        ImportKind(
            key="students",
            label=gettext_lazy("Students"),
            columns=STUDENT_COLUMNS,
            parse=parse_students,
            commit=commit_students,
            supports_update=True,
            help_text=gettext_lazy(
                "Import groups first. A student is matched by phone (with only the parent's "
                "phone: by phone and name). A student in several groups: one row per group "
                "with the same phone and name."
            ),
        )
    )
