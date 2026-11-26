"""Small helpers for the UI kit (CLAUDE.md, "UI kit")."""

from django.contrib import messages


def undo_message(request, text, undo_path: str) -> None:
    """A success toast with an "Undo" button that POSTs to `undo_path` (a same-site path).

    Only for actions that are safe to reverse (a task, a lead's stage). Money actions never
    get an undo: the ledger is append-only and has its own reversal flow.
    """
    messages.success(request, text, extra_tags=f"undo:{undo_path}")
