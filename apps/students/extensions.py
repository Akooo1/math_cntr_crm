"""Enrollment extension point (docs/SPEC.md 4.4).

Higher modules (billing now, salaries later) plug into enroll / move / freeze / unfreeze /
leave without the students module importing them. An extension can add a confirmation
step (e.g. the prorated charge suggestion) and act inside the same transaction.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EnrollmentAction:
    kind: str  # "enroll" | "move" | "freeze" | "unfreeze" | "leave"
    student: Any
    effective_date: dt.date
    group: Any = None  # target group for enroll / move
    enrollment: Any = None  # existing enrollment for move / freeze / unfreeze / leave


@dataclass
class ActionResult:
    enrollment: Any  # the enrollment that is open after the action (new one for move)
    closed: Any = None  # the enrollment that was closed (move: the old one)
    extra: dict = field(default_factory=dict)


class EnrollmentExtension(Protocol):
    key: str
    template: str  # partial shown on the confirmation step

    def preview(self, action: EnrollmentAction, data=None) -> dict | None:
        """Context for the confirmation step, or None when there is nothing to confirm.
        `data` is the submitted step (for "recalculate"); fields must start with "x_"."""

    def validate(self, action: EnrollmentAction, data) -> list[str]:
        """Errors for the submitted confirmation data (already translated)."""

    def apply(self, action: EnrollmentAction, data, *, actor, result: ActionResult) -> None:
        """Runs inside the enrollment transaction. `data` is None when there was no step."""


_extensions: dict[str, EnrollmentExtension] = {}


def register(extension: EnrollmentExtension) -> None:
    _extensions[extension.key] = extension


def all_extensions() -> list[EnrollmentExtension]:
    return list(_extensions.values())


FIELD_PREFIX = "x_"  # extension form fields; not copied into the step's hidden fields


def previews(action: EnrollmentAction, data=None) -> list[tuple[EnrollmentExtension, dict]]:
    out = []
    for ext in all_extensions():
        ctx = ext.preview(action, data)
        if ctx is not None:
            out.append((ext, ctx))
    return out


# --- Student profile panels and list badges ----------------------------------------------
# Billing (phase 4) adds the balance/ledger panel and the payment-status badge here.


@dataclass(frozen=True)
class ProfilePanel:
    key: str
    template: str
    permission: str
    context: Any  # callable(request, student) -> dict
    order: int = 100


_panels: dict[str, ProfilePanel] = {}
_badges: list = []  # callables(user, students: list) -> {student_id: (label, css)}


def register_profile_panel(panel: ProfilePanel) -> None:
    _panels[panel.key] = panel


def profile_panels() -> list[ProfilePanel]:
    return sorted(_panels.values(), key=lambda p: p.order)


def register_list_badge(provider) -> None:
    if provider not in _badges:
        _badges.append(provider)


def list_badges() -> list:
    return list(_badges)
