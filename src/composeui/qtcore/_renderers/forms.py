"""Qt form renderers and the shared form-row widget cache."""

from __future__ import annotations

import weakref
from typing import Any

from qtpy.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget
from typing_extensions import override

from composeui.core.renderer import RendererContainer
from composeui.core.view import FormLabelRowView, FormRowView, FormView, GroupFormView, View
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qformlabel import QFormLabel


class QtFormLabelRenderer(QtWidgetRenderer[FormLabelRowView, QFormLabel]):
    def __init__(self, view: FormLabelRowView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_text,
                "help": self._refresh_help,
                "help_button_text": self._refresh_help_button_text,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QFormLabel()
            self.refresh()

    @staticmethod
    def _refresh_text(_view: FormLabelRowView, rendered_object: QFormLabel, value: str) -> None:
        rendered_object.set_text(value)

    @staticmethod
    def _refresh_help(_view: FormLabelRowView, rendered_object: QFormLabel, value: str) -> None:
        rendered_object.set_help(value)

    @staticmethod
    def _refresh_help_button_text(
        _view: FormLabelRowView, rendered_object: QFormLabel, value: str
    ) -> None:
        rendered_object.set_help_button_text(value)


class QtFormRenderer(QtWidgetRenderer[FormView, QWidget]):
    @override
    def render(self) -> None:
        if self._rendered_object is None:
            if isinstance(self._view, GroupFormView):
                self._rendered_object = QGroupBox()
            else:
                self._rendered_object = QWidget()
            layout = QFormLayout()
            self._rendered_object.setLayout(layout)
            for view in self._view.content_views:
                if isinstance(view, FormRowView) and isinstance(view.renderer, RendererContainer):
                    self.add_row(layout, view, view.renderer)
                # another view, e.g. a table, as wide as the form
                elif (widget := _widget_of(view)) is not None:
                    layout.addRow(widget)
                # else a view this backend doesn't register: left out
            log = self._view.log_view.renderer
            assert isinstance(log, QtWidgetRenderer)
            assert isinstance(log.qt_object, QWidget)
            layout.addRow(log.qt_object)
            self.refresh()

    @classmethod
    def add_row(
        cls, layout: QFormLayout, row: FormRowView, row_renderer: RendererContainer[View]
    ) -> None:
        """Add `row` to `layout`: its label, beside its field above its message."""
        field_container = QWidget()
        field_container_layout = QVBoxLayout(field_container)
        # avoid extra row spacing
        field_container_layout.setContentsMargins(0, 0, 0, 0)
        field_container_layout.addWidget(cls._get_field_object(row_renderer))
        field_container_layout.addWidget(cls._get_log_object(row_renderer))
        if isinstance(row, FormLabelRowView):
            layout.addRow(cls._get_label_object(row_renderer), field_container)
        else:
            layout.addRow(field_container)

    @staticmethod
    def _get_field_object(field_row_renderer: RendererContainer[View]) -> QWidget:
        field_renderer = field_row_renderer.get_renderer("field")
        assert isinstance(field_renderer, QtWidgetRenderer)
        assert isinstance(field_renderer.qt_object, QWidget)
        return field_renderer.qt_object

    @staticmethod
    def _get_log_object(field_row_renderer: RendererContainer[View]) -> QWidget:
        log_renderer = field_row_renderer.get_renderer("log")
        assert isinstance(log_renderer, QtWidgetRenderer)
        assert isinstance(log_renderer.qt_object, QLabel)
        return log_renderer.qt_object

    @staticmethod
    def _get_label_object(field_row_renderer: RendererContainer[View]) -> QFormLabel:
        label_renderer = field_row_renderer.get_renderer("label")
        assert isinstance(label_renderer, QtFormLabelRenderer)
        assert label_renderer.qt_object is not None
        return label_renderer.qt_object


class QtGroupFormRenderer(QtFormRenderer):
    def __init__(self, view: GroupFormView) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "title": self._refresh_title,
            }
        )

    @staticmethod
    def _refresh_title(_view: FormView, rendered_object: QWidget, value: str) -> None:
        assert isinstance(rendered_object, QGroupBox)
        rendered_object.setTitle(value)


#: the widgets of the form rows shown outside a form, by their rows' renderers: built once,
#: as a widget has one parent, and gone with the row
_ROW_WIDGETS: weakref.WeakKeyDictionary[RendererContainer[Any], QWidget] = (
    weakref.WeakKeyDictionary()
)


def _widget_of(view: View) -> QWidget | None:
    """Get the widget showing `view` in a layout; a form row's anywhere, as a form shows it.

    None when this backend doesn't render `view`.
    """
    renderer = view.renderer
    if isinstance(view, FormRowView) and isinstance(renderer, RendererContainer):
        widget = _ROW_WIDGETS.get(renderer)
        if widget is None:
            widget = QWidget()
            layout = QFormLayout(widget)
            # the layout holding the row already insets it
            layout.setContentsMargins(0, 0, 0, 0)
            QtFormRenderer.add_row(layout, view, renderer)
            _ROW_WIDGETS[renderer] = widget
        return widget
    if isinstance(renderer, QtWidgetRenderer) and isinstance(renderer.qt_object, QWidget):
        return renderer.qt_object
    return None
