"""'No English text in the UI' checks (docs/SPEC.md 8.1)."""

import html
import re
from pathlib import Path

import polib
import pytest
from django.conf import settings

from apps.core.roles import Role
from tests.test_permission_matrix import cases, objects  # noqa: F401 - fixture reuse

ROOT = Path(settings.BASE_DIR)
PO = ROOT / "locale" / "uz" / "LC_MESSAGES" / "django.po"

# Common English UI words. Tokens keep apostrophes, so Uzbek "to'lov" is not "to".
ENGLISH = {
    "the",
    "and",
    "of",
    "is",
    "are",
    "be",
    "this",
    "that",
    "with",
    "for",
    "from",
    "your",
    "required",
    "invalid",
    "submit",
    "page",
    "error",
    "field",
    "please",
    "enter",
    "select",
    "choose",
    "password",
    "login",
    "log",
    "save",
    "cancel",
    "delete",
    "edit",
    "add",
    "search",
    "next",
    "previous",
    "yes",
    "none",
    "true",
    "false",
    "null",
    "active",
    "inactive",
    "user",
    "users",
    "branch",
    "branches",
    "course",
    "courses",
    "settings",
    "home",
    "profile",
    "new",
    "name",
    "phone",
    "amount",
    "date",
    "price",
    "prices",
    "status",
    "actions",
    "all",
    "more",
    "filter",
    "reset",
    "details",
    "back",
    "help",
    "note",
    "reason",
    "created",
    "changed",
    "director",
    "teacher",
    "manager",
    "administrator",
    "monthly",
    "installment",
    "room",
    "rooms",
    "discount",
    "payment",
    "payments",
    "receipt",
    "audit",
    "lead",
    "leads",
    "system",
    "general",
    "history",
    "object",
    "before",
    "after",
    "time",
    "value",
    "order",
}
TOKEN = re.compile(r"[A-Za-z][A-Za-z'ʻ’‘-]*")


def visible_text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    attrs = re.findall(r'(?i)\b(?:placeholder|title|aria-label|alt|data-confirm)="([^"]*)"', markup)
    text = re.sub(r"(?s)<!--.*?-->", " ", markup)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text + " " + " ".join(attrs))


def english_words(text: str) -> set[str]:
    return {t for t in TOKEN.findall(text) if t.lower() in ENGLISH}


def test_catalog_is_complete():
    po = polib.pofile(str(PO))
    untranslated = [e.msgid for e in po.untranslated_entries()]
    fuzzy = [e.msgid for e in po.fuzzy_entries()]
    assert not untranslated, f"Untranslated: {untranslated}"
    assert not fuzzy, f"Fuzzy: {fuzzy}"
    same = [
        e.msgid for e in po.translated_entries() if e.msgid == e.msgstr and english_words(e.msgid)
    ]
    assert not same, f"msgstr equals the English msgid: {same}"


def _template_files():
    dirs = [ROOT / "templates", *ROOT.glob("apps/*/templates")]
    for d in dirs:
        yield from d.rglob("*.html")


def strip_template(src: str) -> str:
    src = re.sub(r"(?s)\{#.*?#\}", " ", src)
    src = re.sub(r"(?s)\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", " ", src)
    src = re.sub(r"(?s)\{%\s*blocktranslate\b.*?%\}.*?\{%\s*endblocktranslate\s*%\}", " ", src)
    src = re.sub(r"(?s)\{%.*?%\}", " ", src)
    src = re.sub(r"(?s)\{\{.*?\}\}", " ", src)
    return src


@pytest.mark.parametrize("path", sorted(_template_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_templates_have_no_raw_text(path):
    text = visible_text(strip_template(path.read_text()))
    words = [t for t in TOKEN.findall(text) if len(t) > 1]
    assert not words, f"Raw text outside {{% translate %}} in {path.name}: {words}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "role", [Role.DIRECTOR, Role.BRANCH_ADMIN, Role.SALES_MANAGER, Role.TEACHER, "anon"]
)
def test_rendered_pages_have_no_english(client, objects, users_by_role, role):  # noqa: F811
    if role != "anon":
        client.force_login(users_by_role[role], backend="apps.accounts.backends.PhoneBackend")
    found = {}
    pages = {"/kirish/"} if role == "anon" else set()
    for items in cases(objects).values():
        for case in items:
            if case.method == "get" and case.expect.get(role) == 200:
                pages.add(case.url)
    pages |= {"/yoq-sahifa/"}  # the 404 page
    for url in sorted(pages):
        resp = client.get(url)
        words = english_words(visible_text(resp.content.decode()))
        if words:
            found[url] = sorted(words)
    # Error pages for denied access
    if role not in (Role.DIRECTOR, "anon"):
        words = english_words(visible_text(client.get("/sozlamalar/").content.decode()))
        if words:
            found["/sozlamalar/ (403)"] = sorted(words)
    assert not found, f"English words in the UI: {found}"


@pytest.mark.django_db
def test_form_errors_are_uzbek(client, director):
    client.force_login(director, backend="apps.accounts.backends.PhoneBackend")
    resp = client.post("/sozlamalar/filiallar/yangi/", {"name": "", "receipt_prefix": "toolong1"})
    assert not english_words(visible_text(resp.content.decode()))


def test_detector_catches_english():
    assert english_words(visible_text("<p>This field is required.</p>")) == {
        "This",
        "is",
        "field",
        "required",
    }
    assert not english_words(visible_text("<p>To'lov qabul qilindi. Ha, yo'q.</p>"))
    assert strip_template("<p>{% translate 'Save' %}</p>").strip() == "<p> </p>"
