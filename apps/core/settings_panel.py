"""Sozlamalar (settings panel) sections registry (docs/SPEC.md 4.4, 6.6).

Each module owns its reference data and registers a section here. The `settings` app
renders the panel and routes /sozlamalar/<slug>/ to the section. A new module adds its
settings pages by registering a section; it never edits the settings app.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.db.models import QuerySet

from . import crud


@dataclass(frozen=True)
class Column:
    label: str
    value: Callable[[Any], Any]
    kind: str = "text"  # text | money | date | datetime | bool | phone | badge
    primary: bool = False  # shown as the card title on phones


class SettingsSection:
    slug: str = ""
    title: str = ""
    description: str = ""
    icon: str = "cog"
    order: int = 100
    group: str = ""
    permission: str = "settings.manage"
    model = None
    form_class = None
    columns: list[Column] = []
    audit_prefix: str = ""
    m2m_fields: tuple[str, ...] = ()
    allow_create = True
    allow_edit = True
    allow_toggle_active = True
    # The field that ties a row to a branch (e.g. "branch", "branch_links__branch"): the
    # list then follows the top-bar branch switcher. None = the same for every branch.
    branch_field: str | None = None
    list_template = "settings/section_list.html"
    form_template = "settings/section_form.html"
    # A custom section replaces the list page: custom_view(request, section) -> response.
    custom_view: Callable | None = None
    # Per-object actions: {"name": (label, view(request, section, obj) -> response)}.
    actions: dict = {}

    def get_queryset(self, request) -> QuerySet:
        return self.model._default_manager.all()

    def list_queryset(self, request) -> QuerySet:
        """What the list page shows: get_queryset() narrowed to the switcher's branch."""
        qs = self.get_queryset(request)
        branch = getattr(request, "branch_filter", None)
        if self.branch_field is None or branch is None:
            return qs
        qs = qs.filter(**{self.branch_field: branch})
        return qs.distinct() if "__" in self.branch_field else qs

    def can_create(self, request) -> bool:
        return self.allow_create

    def can_edit(self, request, obj) -> bool:
        return self.allow_edit

    def action_visible(self, request, obj, key) -> bool:
        """Whether the per-object action `key` is offered for this row."""
        return True

    def can_toggle(self, request, obj) -> bool:
        return self.allow_toggle_active and hasattr(obj, "is_active")

    def extra_context(self, request, obj) -> dict:
        return {}

    def get_form(self, request, instance=None, data=None):
        return self.form_class(data=data, instance=instance)

    def save(self, request, form):
        return crud.save_form(
            form, actor=request.user, action_prefix=self.audit_prefix, m2m=self.m2m_fields
        )

    def toggle(self, request, obj):
        return crud.set_active(
            obj, not obj.is_active, actor=request.user, action_prefix=self.audit_prefix
        )


_sections: dict[str, SettingsSection] = {}


def register_section(section: SettingsSection) -> SettingsSection:
    if not section.slug:
        raise ValueError("section needs a slug")
    _sections[section.slug] = section
    return section


def get_section(slug: str) -> SettingsSection | None:
    return _sections.get(slug)


def sections() -> list[SettingsSection]:
    return sorted(_sections.values(), key=lambda s: (s.order, s.slug))
