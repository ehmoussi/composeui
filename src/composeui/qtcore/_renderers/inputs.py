"""Qt renderers for text, number and date fields."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from qtpy.QtGui import QDoubleValidator
from qtpy.QtWidgets import QAbstractSpinBox, QApplication, QFileDialog, QLineEdit, QSpinBox
from typing_extensions import Protocol, override

from composeui.core._views.inputs import date_hint
from composeui.core.renderer import ViewLike
from composeui.core.view import DateRangeInputMixin
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qdatefield import QDateField, QDateRangeField
from composeui.qtcore.widgets.qplaintext import plain_tool_tip
from composeui.qtcore.widgets.qtextarea import QTextArea
from composeui.qtcore.widgets.qtexteditor import QTextEditorBox

if TYPE_CHECKING:
    import datetime

    from composeui.core.signal import Signal, SignalNoArgs


class _InputViewLike(ViewLike, Protocol):
    placeholder: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class InputViewLike(_InputViewLike, Protocol):
    text: str


class QtInputRenderer(QtWidgetRenderer[InputViewLike, QLineEdit]):
    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLineEdit()
            self._connect(
                self._rendered_object.textChanged,
                self._update_text,
                self._view.text_changed.call_callbacks,
            )
            # Qt reports an edit before the change: the view has the text first
            self._connect(
                self._rendered_object.textEdited,
                self._update_text,
                self._view.text_edited.call_callbacks,
            )
            self._relay(self._view.editing_finished, self._rendered_object.editingFinished)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: InputViewLike, rendered_object: QLineEdit, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_placeholder(_view: InputViewLike, rendered_object: QLineEdit, value: str) -> None:
        rendered_object.setPlaceholderText(value)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class QtTextAreaRenderer(QtWidgetRenderer[InputViewLike, QTextArea]):
    _invalid_style = "QPlainTextEdit { border: 1px solid red; }"

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTextArea()
            self._connect(
                self._rendered_object.text_changed,
                self._update_text,
                self._view.text_changed.call_callbacks,
                self._view.text_edited.call_callbacks,
            )
            self._relay(self._view.editing_finished, self._rendered_object.editing_finished)
            # the text only changes without signals from the view: each change is an edit
            self.refresh()

    @staticmethod
    def _refresh_text(_view: InputViewLike, rendered_object: QTextArea, value: str) -> None:
        if value != rendered_object.toPlainText():  # the same text keeps the caret
            rendered_object.setPlainText(value)

    @staticmethod
    def _refresh_placeholder(_view: InputViewLike, rendered_object: QTextArea, value: str) -> None:
        rendered_object.setPlaceholderText(value)

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text


class TextEditorViewLike(InputViewLike, Protocol):
    texts: dict[str, str]
    export_filename: str

    def export_text(self, path: Path) -> None: ...


class QtTextEditorRenderer(QtWidgetRenderer[TextEditorViewLike, QTextEditorBox]):
    """The text in a `QTextEditorBox`: a `QTextEditor` under a search, Copy and Save.

    Its Save button asks where to save the text, in Qt's file dialog.
    """

    def __init__(self, view: TextEditorViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
                "texts": self._refresh_texts,
                "export_filename": self._refresh_export_filename,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTextEditorBox()
            editor = self._rendered_object.text
            self._connect(
                editor.text_changed,
                self._update_text,
                self._view.text_changed.call_callbacks,
                self._view.text_edited.call_callbacks,
            )
            self._relay(self._view.editing_finished, editor.editing_finished)
            self._connect(self._rendered_object.save.clicked, self._save)
            self._connect(self._rendered_object.copy.clicked, self._copy)
            self._connect(editor.matches_changed, self._show_matches)
            self.refresh()

    @staticmethod
    def _refresh_text(
        _view: TextEditorViewLike, rendered_object: QTextEditorBox, value: str
    ) -> None:
        rendered_object.text.set_text(value)

    @staticmethod
    def _refresh_placeholder(
        _view: TextEditorViewLike, rendered_object: QTextEditorBox, value: str
    ) -> None:
        rendered_object.text.setPlaceholderText(value)

    @staticmethod
    def _refresh_texts(
        _view: TextEditorViewLike, rendered_object: QTextEditorBox, value: dict[str, str]
    ) -> None:
        rendered_object.set_texts(value)
        rendered_object.show_position(value.get("position", ""))

    @staticmethod
    def _refresh_export_filename(
        _view: TextEditorViewLike, rendered_object: QTextEditorBox, value: str
    ) -> None:
        rendered_object.name.setText(value)  # the dialog reads it as it opens

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text

    def _show_matches(self, current: int, count: int) -> None:
        assert self._rendered_object is not None
        self._rendered_object.show_matches(current, count, self._view.texts)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._view.text)

    def _save(self) -> None:
        """Ask where to save the text, and save it there."""
        assert self._rendered_object is not None
        path, _chosen = QFileDialog.getSaveFileName(
            self._rendered_object, self._view.texts.get("save", ""), self._view.export_filename
        )
        if path != "":
            self._view.export_text(Path(path))


class FloatInputViewLike(_InputViewLike, Protocol):
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None

    def shown_text(self, value: float | None, decimals: int | None) -> str: ...


class QtFloatInputRenderer(QtWidgetRenderer[FloatInputViewLike, QLineEdit]):
    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "decimals": self._refresh_decimals,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QLineEdit()
            validator = QDoubleValidator()
            self._rendered_object.setValidator(validator)
            self._connect(
                self._rendered_object.textChanged,
                self._update_text,
                self._view.text_changed.call_callbacks,
            )
            # Qt reports an edit before the change: the view has the value first
            self._connect(
                self._rendered_object.textEdited,
                self._update_text,
                self._view.text_edited.call_callbacks,
            )
            self._relay(self._view.editing_finished, self._rendered_object.editingFinished)
            self.refresh()

    @staticmethod
    def _refresh_value(
        view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        rendered_object.setText(view.shown_text(value, view.decimals))

    @staticmethod
    def _refresh_placeholder(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: str
    ) -> None:
        rendered_object.setPlaceholderText(value)

    @staticmethod
    def _refresh_minimum(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setBottom(float("-inf") if value is None else value)

    @staticmethod
    def _refresh_maximum(
        _view: FloatInputViewLike, rendered_object: QLineEdit, value: float | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setTop(float("inf") if value is None else value)

    @staticmethod
    def _refresh_decimals(
        view: FloatInputViewLike, rendered_object: QLineEdit, value: int | None
    ) -> None:
        validator = rendered_object.validator()
        assert isinstance(validator, QDoubleValidator)
        validator.setDecimals(-1 if value is None else value)
        rendered_object.setText(view.shown_text(view.value, value))

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            if text != "":
                self._view.value = float(text)
            else:
                self._view.value = None


def _line_edit(rendered_object: QAbstractSpinBox) -> QLineEdit:
    """Get the field of a spin box or a date edit."""
    # `QAbstractSpinBox.lineEdit` is protected
    line_edit = rendered_object.findChild(QLineEdit)
    assert line_edit is not None
    return line_edit


class IntInputViewLike(_InputViewLike, Protocol):
    value: int | None
    minimum: int | None
    maximum: int | None


#: a spin box's widest range: Qt's spin box holds a 32-bit int
_INT_MINIMUM, _INT_MAXIMUM = -(2**31), 2**31 - 1


class QtIntInputRenderer(QtWidgetRenderer[IntInputViewLike, QSpinBox]):
    """A spin box, keeping its value within `minimum`/`maximum`.

    It shows no value while the view's is `None`; once it has one, leaving it emptied
    puts the last value back, as any Qt spin box does.
    """

    _invalid_style = "QSpinBox { border: 1px solid red; }"

    def __init__(self, view: IntInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QSpinBox()
            self._rendered_object.setRange(_INT_MINIMUM, _INT_MAXIMUM)
            # its text only changes once acceptable, so never for a transient "-"
            self._connect(self._rendered_object.valueChanged, self._update_value)
            self._relay(self._view.editing_finished, self._rendered_object.editingFinished)
            self._relay(self._view.text_changed, self._rendered_object.textChanged)
            line_edit = _line_edit(self._rendered_object)
            # Qt reports an edit before the spin box reads it: the view has the value first
            self._connect(
                line_edit.textEdited, self._update_edited, self._view.text_edited.call_callbacks
            )
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: IntInputViewLike, rendered_object: QSpinBox, value: int | None
    ) -> None:
        if value is None:
            rendered_object.clear()
        else:
            rendered_object.setValue(value)

    @staticmethod
    def _refresh_placeholder(
        _view: IntInputViewLike, rendered_object: QSpinBox, value: str
    ) -> None:
        _line_edit(rendered_object).setPlaceholderText(value)

    @staticmethod
    def _refresh_minimum(
        view: IntInputViewLike, rendered_object: QSpinBox, value: int | None
    ) -> None:
        rendered_object.setMinimum(_INT_MINIMUM if value is None else value)
        # a new range shows a value even while the view has none
        QtIntInputRenderer._refresh_value(view, rendered_object, view.value)

    @staticmethod
    def _refresh_maximum(
        view: IntInputViewLike, rendered_object: QSpinBox, value: int | None
    ) -> None:
        rendered_object.setMaximum(_INT_MAXIMUM if value is None else value)
        QtIntInputRenderer._refresh_value(view, rendered_object, view.value)

    def _update_value(self, value: int) -> None:
        with self.stop_refresh():
            self._view.value = value

    def _update_edited(self, _text: str) -> None:
        """Give the view the value edited, a whole number in range, before the spin box does."""
        assert self._rendered_object is not None
        text = self._rendered_object.cleanText()
        if text == "":
            with self.stop_refresh():
                self._view.value = None
            return
        try:
            value = int(text)
        except ValueError:
            return  # transient text, e.g. "-": the spin box keeps its value
        if self._rendered_object.minimum() <= value <= self._rendered_object.maximum():
            self._update_value(value)


class DateInputViewLike(_InputViewLike, Protocol):
    value: datetime.date | None
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    pick_text: str
    value_changed: Signal[datetime.date | None]


class QtDateInputRenderer(QtWidgetRenderer[DateInputViewLike, QDateField]):
    """A field typing the date as the view's `date_format` says, beside a calendar button.

    Its calendar names the months and days in the system's language: Qt's own, as the
    web's in the browser's.
    """

    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: DateInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "date_format": self._refresh_date_format,
                "pick_text": self._refresh_pick_text,
                # Qt's calendar names them, in the system's language
                "month_names": lambda _view, _rendered_object, _value: None,
                "day_names": lambda _view, _rendered_object, _value: None,
                "previous_month_text": lambda _view, _rendered_object, _value: None,
                "next_month_text": lambda _view, _rendered_object, _value: None,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QDateField()
            # first, so the view's callbacks see the new date
            self._connect(self._rendered_object.date_edited, self._update_value)
            line_edit = self._rendered_object.line_edit
            self._relay(self._view.editing_finished, line_edit.editingFinished)
            # not the line edit's `textChanged`: it also reports the dates set by code
            self._relay(self._view.text_changed, self._rendered_object.text_changed)
            self._relay(self._view.text_edited, line_edit.textEdited)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: DateInputViewLike, rendered_object: QDateField, value: datetime.date | None
    ) -> None:
        rendered_object.set_date(value)

    @staticmethod
    def _refresh_placeholder(
        view: DateInputViewLike, rendered_object: QDateField, value: str
    ) -> None:
        rendered_object.line_edit.setPlaceholderText(date_hint(value, view.date_format))

    # the new limit: the view still holds the old one as its renderer hears of the change
    @staticmethod
    def _refresh_minimum(
        view: DateInputViewLike, rendered_object: QDateField, value: datetime.date | None
    ) -> None:
        rendered_object.set_range(value, view.maximum)

    @staticmethod
    def _refresh_maximum(
        view: DateInputViewLike, rendered_object: QDateField, value: datetime.date | None
    ) -> None:
        rendered_object.set_range(view.minimum, value)

    @staticmethod
    def _refresh_date_format(
        view: DateInputViewLike, rendered_object: QDateField, value: str
    ) -> None:
        rendered_object.set_date_format(value)
        rendered_object.line_edit.setPlaceholderText(date_hint(view.placeholder, value))

    @staticmethod
    def _refresh_pick_text(
        _view: DateInputViewLike, rendered_object: QDateField, value: str
    ) -> None:
        rendered_object.button.setToolTip(plain_tool_tip(value))
        rendered_object.button.setAccessibleName(value)

    def _update_value(self, value: datetime.date | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)


class DateRangeInputViewLike(ViewLike, Protocol):
    value: tuple[datetime.date | None, datetime.date | None]
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    start_text: str
    end_text: str
    pick_text: str
    value_changed: Signal[tuple[datetime.date | None, datetime.date | None]]


class QtDateRangeInputRenderer(QtWidgetRenderer[DateRangeInputViewLike, QDateRangeField]):
    """Two date fields, the start and the end, each beside its calendar button."""

    _invalid_style = "QLineEdit { border: 1px solid red; }"

    def __init__(self, view: DateRangeInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "date_format": self._refresh_date_format,
                "start_text": self._refresh_start_text,
                "end_text": self._refresh_end_text,
                "pick_text": self._refresh_pick_text,
            }
        )
        # Qt's calendar names them, in the system's language
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("month_names", "day_names", "previous_month_text", "next_month_text"),
                lambda _view, _rendered_object, _value: None,
            )
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QDateRangeField()
            self._connect(self._rendered_object.end_edited, self._update_end)
            self.refresh()

    @staticmethod
    def _refresh_value(
        _view: DateRangeInputViewLike,
        rendered_object: QDateRangeField,
        value: tuple[datetime.date | None, datetime.date | None],
    ) -> None:
        for field, date in zip(rendered_object.fields, value):
            field.set_date(date)

    @staticmethod
    def _refresh_minimum(
        view: DateRangeInputViewLike, rendered_object: QDateRangeField, value: datetime.date | None
    ) -> None:
        for field in rendered_object.fields:
            field.set_range(value, view.maximum)

    @staticmethod
    def _refresh_maximum(
        view: DateRangeInputViewLike, rendered_object: QDateRangeField, value: datetime.date | None
    ) -> None:
        for field in rendered_object.fields:
            field.set_range(view.minimum, value)

    @staticmethod
    def _refresh_date_format(
        view: DateRangeInputViewLike, rendered_object: QDateRangeField, value: str
    ) -> None:
        texts = (view.start_text, view.end_text)
        for field, text in zip(rendered_object.fields, texts):
            field.set_date_format(value)
            field.line_edit.setPlaceholderText(date_hint(text, value))

    @staticmethod
    def _refresh_start_text(
        view: DateRangeInputViewLike, rendered_object: QDateRangeField, value: str
    ) -> None:
        rendered_object.start.line_edit.setPlaceholderText(date_hint(value, view.date_format))
        rendered_object.start.line_edit.setAccessibleName(value)

    @staticmethod
    def _refresh_end_text(
        view: DateRangeInputViewLike, rendered_object: QDateRangeField, value: str
    ) -> None:
        rendered_object.end.line_edit.setPlaceholderText(date_hint(value, view.date_format))
        rendered_object.end.line_edit.setAccessibleName(value)

    @staticmethod
    def _refresh_pick_text(
        _view: DateRangeInputViewLike, rendered_object: QDateRangeField, value: str
    ) -> None:
        for field in rendered_object.fields:
            field.button.setToolTip(plain_tool_tip(value))
            field.button.setAccessibleName(value)

    def _update_end(self, index: int, date: datetime.date | None) -> None:
        view = self._view
        # the field reports only a new date, so the range changes
        value = DateRangeInputMixin.with_end(view.value, index, date)
        with self.stop_refresh():
            view.value = value
        # the other field, if it followed; not the one typed in, whose text the user writes
        other = 1 - index
        cast("QDateRangeField", self._rendered_object).fields[other].set_date(value[other])
        view.value_changed.emit(value)
