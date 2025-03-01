"""Disconnect all callbacks connected to signals of the views."""

from composeui.core.basesignal import BaseSignal
from composeui.core.views.view import View

from collections import deque
from dataclasses import fields


def disconnect(view: View) -> None:
    r"""Apply disconnections to the view and its children."""
    views = deque([view])
    while len(views) > 0:
        current_view = views.popleft()
        for view_field in fields(current_view):
            if view_field.type == BaseSignal:
                field = getattr(current_view, view_field.name)
                assert isinstance(
                    field, BaseSignal
                ), f"Unexpected error: {view_field.name} is not a signal"
                field.clear()
        views.extend(current_view.children.values())
