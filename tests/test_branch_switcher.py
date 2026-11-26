"""The top-bar branch switcher (request.branch_filter) drives every page.

The sweep loads every page without URL arguments as the Direktor with branch A picked and
checks that no student or group that exists only in branch B shows up. The other tests
cover the pages that work on one branch (Kassa, Ombor, Savdo): their own ?filial= must
not pin them to the old branch after a switch."""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import NoReverseMatch, reverse

from apps.core.middleware import BRANCH_FILTER_SESSION_KEY
from apps.core.models import AuditLog
from apps.crm.models import Lead
from apps.settings.models import Branch
from apps.students.models import Group, Student
from tests.factories import make_group, make_student, page_text
from tests.urls_inventory import all_url_names

pytestmark = pytest.mark.django_db

# Pages that are the same for every branch by design.
CENTER_WIDE = {
    "accounts:profile",
    "accounts:password_change",
    "settings:index",
    "reports:index",
    "salaries:index",  # one sheet per person for all branches (see the note on the page)
}


def pick(client, branch_id):
    s = client.session
    s[BRANCH_FILTER_SESSION_KEY] = branch_id
    s.save()


def main_of(resp) -> str:
    html = resp.content.decode()
    start = html.find("<main")
    return html[start : html.find("</main>", start)] if start >= 0 else html


def names_in(branch) -> set[str]:
    return (
        {s.full_name for s in Student.objects.filter(branch=branch)}
        | {g.name for g in Group.objects.filter(branch=branch)}
        | {lead.full_name for lead in Lead.objects.filter(branch=branch)}
    )


def test_no_page_shows_another_branch_when_one_is_picked(client):
    call_command("seed_demo")
    director = get_user_model().objects.filter(role="director").first()
    client.force_login(director)
    a, b = list(Branch.objects.order_by("pk"))[:2]
    only_b = names_in(b) - names_in(a)
    assert only_b
    pick(client, a.pk)
    checked, leaks = 0, {}
    for name in sorted(all_url_names() - CENTER_WIDE):
        try:
            url = reverse(name)
        except NoReverseMatch:
            continue  # needs an object; covered by the permission matrix (404 outside scope)
        resp = client.get(url)
        if resp.status_code != 200 or "html" not in resp.get("Content-Type", ""):
            continue
        checked += 1
        text = main_of(resp)
        found = sorted(n for n in only_b if n in text)
        if found:
            leaks[name] = found[:3]
    assert checked > 25
    assert leaks == {}


class TestSwitchingOnSingleBranchPages:
    def test_switch_drops_the_old_branch_and_page_from_the_address(self, login, director):
        c = login(director)
        resp = c.post("/filial/", {"branch": "", "next": "/kassa/?filial=7&sana=16.11.2026&page=3"})
        assert resp.status_code == 302 and resp["Location"] == "/kassa/?sana=16.11.2026"

    def test_kassa_follows_the_switcher_after_a_page_pick(
        self, login, director, branch_a, branch_b
    ):
        c = login(director)
        assert branch_b.name in page_text(c.get(f"/kassa/?filial={branch_b.pk}"))
        assert c.session[BRANCH_FILTER_SESSION_KEY] == branch_b.pk  # the top bar agrees
        resp = c.post("/filial/", {"branch": branch_a.pk, "next": f"/kassa/?filial={branch_b.pk}"})
        page = c.get(resp["Location"])
        assert page.context["branch"] == branch_a

    def test_store_follows_the_switcher(self, login, director, branch_a, branch_b):
        c = login(director)
        pick(c, branch_b.pk)
        assert c.get("/ombor/").context["branch"] == branch_b
        resp = c.post("/filial/", {"branch": branch_a.pk, "next": f"/ombor/?filial={branch_b.pk}"})
        assert c.get(resp["Location"]).context["branch"] == branch_a

    def test_page_pick_outside_access_is_ignored(self, login, admin_a, branch_a, branch_b):
        c = login(admin_a)
        c.get(f"/kassa/?filial={branch_b.pk}")
        assert c.session.get(BRANCH_FILTER_SESSION_KEY) is None


class TestFollowTheSwitcher:
    def test_audit_log(self, login, director, branch_a, branch_b):
        AuditLog.objects.create(action="x.a", entity_type="t", entity_id="1", branch_id=branch_a.pk)
        AuditLog.objects.create(action="x.b", entity_type="t", entity_id="2", branch_id=branch_b.pk)
        c = login(director)
        pick(c, branch_a.pk)
        shown = {e.action for e in c.get("/jurnal/").context["page"]}
        assert "x.a" in shown and "x.b" not in shown
        everything = {e.action for e in c.get("/jurnal/?branch=").context["page"]}
        assert {"x.a", "x.b"} <= everything  # "All branches" chosen on the page

    def test_message_to_parents_lists_the_branch_groups(self, login, director, branch_a, branch_b):
        ga = make_group(director, branch_a)
        gb = make_group(director, branch_b)
        make_student(director, branch_a)
        c = login(director)
        pick(c, branch_a.pk)
        groups = set(c.get("/ota-onalarga-xabar/").context["form"].fields["group"].queryset)
        assert ga in groups and gb not in groups
