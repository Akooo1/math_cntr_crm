import datetime as dt
import io

import pytest
import time_machine
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from openpyxl import Workbook

from apps.core.models import AuditLog
from apps.core.roles import Role
from apps.students.models import Enrollment, Group, ImportBatch, Student
from apps.students.services import importing
from apps.students.services.importing import get_kind
from tests.factories import (
    CourseFactory,
    RoomFactory,
    UserFactory,
    make_group,
    make_student,
    page_text,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("import_granted")]


@pytest.fixture(autouse=True)
def frozen_clock():
    with time_machine.travel(dt.datetime(2026, 10, 15, 9, 0, tzinfo=dt.UTC), tick=False):
        yield


def xlsx(kind_key, rows, drop=()):
    kind = get_kind(kind_key)
    wb = Workbook()
    ws = wb.active
    headers = [str(h) for h, _e in kind.columns if str(h) not in drop]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile("fayl.xlsx", buf.getvalue())


@pytest.fixture
def refs(branch_a):
    teacher = UserFactory(role=Role.TEACHER, branches=[branch_a], phone="+998900000013")
    course = CourseFactory(name="Matematika 7–9-sinf")
    RoomFactory(branch=branch_a, name="1-xona")
    return teacher, course


GROUP_ROW = {
    "Guruh nomi": "7-A",
    "Kurs": "matematika 7–9-sinf",
    "O'qituvchi telefoni": "90 000 00 13",
    "Xona": "1-xona",
    "Dars kunlari": "Du, Chorshanba, ju",
    "Dars boshlanishi": "15:00",
    "Dars tugashi": "16:30",
    "Boshlanish sanasi": "01.09.2026",
    "Sig'imi": 12,
}


def run(actor, branch, kind, rows, **kw):
    batch = importing.validate_upload(
        actor=actor, kind_key=kind, branch=branch, uploaded_file=xlsx(kind, rows), **kw
    )
    return batch


class TestGroups:
    def test_valid_file_is_checked_then_committed(self, admin_a, branch_a, refs):
        batch = run(admin_a, branch_a, "groups", [GROUP_ROW])
        assert batch.status == ImportBatch.Status.VALIDATED and not Group.objects.exists()
        batch = importing.commit(actor=admin_a, batch=batch, branch=branch_a)
        group = Group.objects.get(name="7-A")
        assert batch.status == ImportBatch.Status.COMMITTED
        assert group.import_batch == batch and group.capacity == 12
        assert sorted(group.slots.values_list("weekday", flat=True)) == [1, 3, 5]
        assert group.lessons.exists()
        assert AuditLog.objects.filter(action="students.import.commit").exists()

    def test_file_lost_between_check_and_import(self, admin_a, branch_a, refs):
        # Hosting without a persistent disk (Railway without a volume) restarted in between.
        batch = run(admin_a, branch_a, "groups", [GROUP_ROW])
        batch.file.storage.delete(batch.file.name)
        with pytest.raises(ValidationError):
            importing.commit(actor=admin_a, batch=batch, branch=branch_a)
        assert not Group.objects.exists()

    def test_errors_are_per_row_in_uzbek_and_nothing_is_saved(self, admin_a, branch_a, refs):
        bad = {
            **GROUP_ROW,
            "Guruh nomi": "7-B",
            "Kurs": "Yo'q kurs",
            "Dars kunlari": "xyz",
            "Boshlanish sanasi": "2026-09-01",
        }
        batch = run(admin_a, branch_a, "groups", [GROUP_ROW, bad])
        assert batch.status == ImportBatch.Status.FAILED
        messages = [e["message"] for e in batch.report["errors"]]
        assert all(e["row"] == 3 for e in batch.report["errors"])
        assert any("Sozlamalarda topilmadi" in m for m in messages)
        assert any("dars kunlari" in m for m in messages)
        assert any("sana noto'g'ri" in m for m in messages)
        with pytest.raises(Exception):  # noqa: B017 - failed batch can't be committed
            importing.commit(actor=admin_a, batch=batch, branch=branch_a)
        assert not Group.objects.exists()

    def test_missing_column(self, admin_a, branch_a, refs):
        upload = xlsx("groups", [GROUP_ROW], drop=("Kurs",))
        batch = importing.validate_upload(
            actor=admin_a, kind_key="groups", branch=branch_a, uploaded_file=upload
        )
        assert "Kurs" in batch.report["errors"][0]["message"]

    def test_teacher_of_other_branch_rejected(self, admin_a, director, branch_a, branch_b, refs):
        batch = run(director, branch_b, "groups", [GROUP_ROW])
        assert batch.status == ImportBatch.Status.FAILED

    def test_admin_cannot_import_into_other_branch(self, admin_a, branch_b, refs):
        with pytest.raises(Http404):
            run(admin_a, branch_b, "groups", [GROUP_ROW])


class TestStudents:
    def test_students_created_and_enrolled(self, admin_a, branch_a, refs):
        teacher, course = refs
        group = make_group(
            admin_a, branch_a, teacher=teacher, course=course, name="7-A", start=dt.date(2026, 9, 1)
        )
        rows = [
            {
                "Familiya": "Karimov",
                "Ism": "Aziz",
                "Telefon": "901112233",
                "Guruh nomi": "7-a",
                "Guruhga qo'shilgan sana": "01.09.2026",
                "Ota-onasining telefoni": "+998 90 444 55 66",
            },
            {"Familiya": "Aliyeva", "Ism": "Madina", "Ota-onasining telefoni": "93 777 88 99"},
        ]
        batch = importing.commit(
            actor=admin_a, batch=run(admin_a, branch_a, "students", rows), branch=branch_a
        )
        assert batch.report["summary"] == {
            "students_created": 2,
            "students_updated": 0,
            "enrollments_created": 1,
        }
        aziz = Student.objects.get(phone="+998901112233")
        assert aziz.import_batch == batch
        assert Enrollment.objects.get(student=aziz).group == group

    def test_duplicate_phone_needs_update_flag(self, admin_a, branch_a, refs):
        make_student(admin_a, branch_a, phone="+998901112233", parent_phone="")
        row = {
            "Familiya": "Karimov",
            "Ism": "Aziz",
            "Telefon": "901112233",
            "Ota-onasi ismi": "",
            "Izohlar": "yangi",
        }
        failed = run(admin_a, branch_a, "students", [row])
        assert failed.status == ImportBatch.Status.FAILED
        ok = run(admin_a, branch_a, "students", [row], update_existing=True)
        batch = importing.commit(actor=admin_a, batch=ok, branch=branch_a)
        assert batch.report["summary"]["students_updated"] == 1
        assert Student.objects.count() == 1

    def test_repeated_phone_in_file_and_other_branch(
        self, admin_a, director, branch_a, branch_b, refs
    ):
        make_student(director, branch_b, phone="+998905550000", parent_phone="")
        rows = [
            {"Familiya": "A", "Ism": "B", "Telefon": "901112233"},
            {"Familiya": "C", "Ism": "D", "Telefon": "901112233"},
            {"Familiya": "E", "Ism": "F", "Telefon": "905550000"},
        ]
        batch = run(admin_a, branch_a, "students", rows)
        rows_with_errors = sorted({e["row"] for e in batch.report["errors"]})
        assert rows_with_errors == [3, 4]

    def test_one_student_in_three_groups_by_one_row_per_group(self, admin_a, branch_a, refs):
        teacher, course = refs
        groups = [
            make_group(
                admin_a, branch_a, teacher=teacher, course=course, name=n, start=dt.date(2026, 9, 1)
            )
            for n in ("7-A", "7-B", "Olimpiada")
        ]
        base = {"Familiya": "Karimov", "Ism": "Aziz", "Telefon": "901112233"}
        rows = [
            {**base, "Guruh nomi": g.name, "Guruhga qo'shilgan sana": "01.09.2026"} for g in groups
        ]
        rows[2]["Familiya"] = "KARIMOV"  # same person, typed differently
        batch = importing.commit(
            actor=admin_a, batch=run(admin_a, branch_a, "students", rows), branch=branch_a
        )
        assert batch.report["summary"] == {
            "students_created": 1,
            "students_updated": 0,
            "enrollments_created": 3,
        }
        aziz = Student.objects.get()
        assert {e.group for e in Enrollment.objects.filter(student=aziz)} == set(groups)

    def test_repeated_rows_that_make_no_sense_are_refused(self, admin_a, branch_a, refs):
        teacher, course = refs
        make_group(
            admin_a, branch_a, teacher=teacher, course=course, name="7-A", start=dt.date(2026, 9, 1)
        )
        joined = {"Guruh nomi": "7-A", "Guruhga qo'shilgan sana": "01.09.2026"}
        rows = [
            {"Familiya": "A", "Ism": "B", "Telefon": "901112233", **joined},
            {"Familiya": "A", "Ism": "B", "Telefon": "901112233", **joined},  # same group again
            {"Familiya": "C", "Ism": "D", "Telefon": "901112233", **joined},  # another name
            {"Familiya": "A", "Ism": "B", "Telefon": "901112233"},  # repeat without a group
        ]
        batch = run(admin_a, branch_a, "students", rows)
        assert sorted({e["row"] for e in batch.report["errors"]}) == [3, 4, 5]
        assert batch.status == ImportBatch.Status.FAILED and not Student.objects.exists()

    def test_siblings_share_the_parent_phone(self, admin_a, branch_a, refs):
        sister = make_student(
            admin_a,
            branch_a,
            last_name="Aliyeva",
            first_name="Madina",
            parent_phone="+998937778899",
        )
        rows = [
            {"Familiya": "Aliyev", "Ism": "Jasur", "Ota-onasining telefoni": "93 777 88 99"},
            {
                "Familiya": sister.last_name,
                "Ism": sister.first_name,
                "Ota-onasining telefoni": "93 777 88 99",
                "Izohlar": "yangilandi",
            },
        ]
        batch = importing.commit(
            actor=admin_a,
            batch=run(admin_a, branch_a, "students", rows, update_existing=True),
            branch=branch_a,
        )
        assert batch.report["summary"]["students_created"] == 1  # the brother
        assert batch.report["summary"]["students_updated"] == 1  # the sister, found by name
        sister.refresh_from_db()
        assert sister.notes == "yangilandi"
        assert Student.objects.filter(parent_phone="+998937778899").count() == 2

    def test_commit_revalidates(self, admin_a, branch_a, refs):
        row = {"Familiya": "A", "Ism": "B", "Telefon": "901112233"}
        batch = run(admin_a, branch_a, "students", [row])
        make_student(admin_a, branch_a, phone="+998901112233", parent_phone="")  # appears meanwhile
        batch = importing.commit(actor=admin_a, batch=batch, branch=branch_a)
        assert batch.status == ImportBatch.Status.FAILED
        assert Student.objects.count() == 1


def test_import_pages(login, admin_a, branch_a, refs):
    c = login(admin_a)
    assert c.get("/import/").status_code == 200
    resp = c.get("/import/namuna/students/")
    assert resp["Content-Type"].startswith("application/vnd.openxmlformats")
    upload = xlsx("groups", [GROUP_ROW])
    resp = c.post("/import/", {"kind": "groups", "branch": branch_a.pk, "file": upload})
    batch = ImportBatch.objects.get()
    assert resp.status_code == 302 and resp["Location"] == f"/import/{batch.pk}/"
    assert "Xato topilmadi" in page_text(c.get(resp["Location"]))
    assert c.post(f"/import/{batch.pk}/tasdiqlash/").status_code == 302
    assert Group.objects.filter(name="7-A").exists()
