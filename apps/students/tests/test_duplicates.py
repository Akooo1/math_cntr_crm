"""A new student who is already registered (owner's request, docs/SPEC.md §24)."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError

from apps.students import services
from apps.students.models import Student
from tests.factories import UserFactory, make_student, page_text

pytestmark = pytest.mark.django_db


def form(branch, **kw):
    data = {
        "last_name": "Karimov",
        "first_name": "Aziz",
        "phone": "",
        "parent_phone": "",
        "birth_date": "",
        "branch": branch.pk,
    }
    data.update(kw)
    return data


def test_the_same_own_phone_is_refused_everywhere(admin_a, director, branch_a, branch_b):
    make_student(director, branch_a, phone="+998901112233", last_name="Aliyev")
    with pytest.raises(ValidationError, match="Aliyev"):
        make_student(admin_a, branch_a, phone="+998901112233")
    other = UserFactory(role="branch_admin", branches=[branch_b])
    with pytest.raises(ValidationError) as exc:
        make_student(other, branch_b, phone="+998901112233")
    assert "Aliyev" not in str(exc.value) and branch_a.name in str(exc.value)  # no details


def test_old_duplicates_stay_editable(admin_a, branch_a):
    a = make_student(admin_a, branch_a, phone="+998901112233")
    b = make_student(admin_a, branch_a, phone="+998907770000")
    Student.objects.filter(pk=b.pk).update(phone="+998901112233")  # e.g. from before the rule
    b.refresh_from_db()
    data = {f: getattr(b, f) for f in services.students.FIELDS} | {"notes": "ok"}
    services.update_student(actor=admin_a, student=b, data=data)
    data["phone"] = "+998901112233"
    assert a.phone == data["phone"]


def test_form_refuses_same_phone_and_asks_for_a_sibling(login, admin_a, branch_a):
    make_student(admin_a, branch_a, phone="+998901112233", parent_phone="+998937778899")
    c = login(admin_a)
    resp = c.post("/oquvchilar/yangi/", form(branch_a, phone="90 111 22 33"))
    assert resp.status_code == 200 and resp.context["form"].non_field_errors()
    assert resp.context["matches"].blocking
    assert Student.objects.count() == 1

    sibling = form(branch_a, first_name="Madina", parent_phone="93 777 88 99")
    resp = c.post("/oquvchilar/yangi/", sibling)
    assert resp.status_code == 200 and Student.objects.count() == 1  # warned, not saved
    assert "baribir" in resp.content.decode()
    resp = c.post("/oquvchilar/yangi/", {**sibling, "baribir": "1"})
    assert resp.status_code == 302 and Student.objects.count() == 2


def test_same_name_and_birth_date_warns(login, admin_a, branch_a):
    make_student(admin_a, branch_a, birth_date=dt.date(2013, 3, 14))
    c = login(admin_a)
    data = form(branch_a, parent_phone="93 000 00 01", birth_date="14.03.2013", last_name="KARIMOV")
    resp = c.post("/oquvchilar/yangi/", data)
    assert resp.status_code == 200 and Student.objects.count() == 1
    box = c.get("/oquvchilar/dublikat/", data)
    assert "Karimov Aziz" in page_text(box)


def test_live_box_shows_other_branch_by_name_only(login, admin_a, director, branch_b):
    make_student(director, branch_b, phone="+998901112233", last_name="Yashirin")
    text = page_text(login(admin_a).get("/oquvchilar/dublikat/?phone=90+111+22+33"))
    assert branch_b.name in text and "Yashirin" not in text
