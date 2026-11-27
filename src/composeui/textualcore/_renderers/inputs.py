"""Textual text, number and date inputs."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, cast

from textual.content import Content
from textual.validation import Integer, Number
from typing_extensions import Protocol, override

from composeui.core._views.content import matches_text
from composeui.core._views.inputs import date_hint
from composeui.core.renderer import ViewLike
from composeui.core.view import DateRangeInputMixin
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composedateinput import ComposeDateInput
from composeui.textualcore.widgets.composeinput import ComposeInput
from composeui.textualcore.widgets.composerange import ComposeDateRangeInput
from composeui.textualcore.widgets.composetextarea import ComposeTextArea
from composeui.textualcore.widgets.composetexteditor import ComposeTextEditorBox

if TYPE_CHECKING:
    import datetime
    from pathlib import Path

    from composeui.core._views.inputs import Lexer
    from composeui.core.signal import Signal, SignalNoArgs


class InputViewLike(ViewLike, Protocol):
    placeholder: str
    text: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class TextualInputRenderer(TextualWidgetRenderer[InputViewLike, ComposeInput]):
    _marks_invalid = True

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
            self._rendered_object = ComposeInput()
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_text(_view: InputViewLike, rendered_object: ComposeInput, value: str) -> None:
        rendered_object.set_value(value)

    @staticmethod
    def _refresh_placeholder(
        _view: InputViewLike, rendered_object: ComposeInput, value: str
    ) -> None:
        rendered_object.placeholder = value

    def _update_text(self, text: str) -> None:
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


class TextualTextAreaRenderer(TextualWidgetRenderer[InputViewLike, ComposeTextArea]):
    _marks_invalid = True

    def __init__(self, view: InputViewLike) -> None:
        super().__init__(view)
        self._is_edited = False
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeTextArea()
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_text(_view: InputViewLike, rendered_object: ComposeTextArea, value: str) -> None:
        if value != rendered_object.text:  # the same text keeps the cursor
            rendered_object.text = value

    @staticmethod
    def _refresh_placeholder(
        _view: InputViewLike, rendered_object: ComposeTextArea, value: str
    ) -> None:
        rendered_object.placeholder = value

    def _update_text(self, text: str) -> None:
        if text == self._view.text:  # the text the view set, not an edit
            return
        self._is_edited = True
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        # as Qt and the browser, only after a change: leaving the area doesn't commit it
        if self._is_edited:
            self._is_edited = False
            self._view.editing_finished.emit()


class TextEditorViewLike(InputViewLike, Protocol):
    texts: dict[str, str]
    export_filename: str
    language: str | Lexer | None

    def export_text(self, path: Path) -> None: ...


class TextualTextEditorRenderer(TextualWidgetRenderer[TextEditorViewLike, ComposeTextEditorBox]):
    """The text in a `ComposeTextEditor`, under its search, Copy and Save controls."""

    def __init__(self, view: TextEditorViewLike) -> None:
        super().__init__(view)
        self._is_edited = False
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "placeholder": self._refresh_placeholder,
                "texts": self._refresh_texts,
                "export_filename": self._refresh_export_filename,
                "language": self._refresh_language,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeTextEditorBox()
            editor = self._rendered_object.editor
            editor.value_changed.connect(self._update_text)
            editor.value_submitted.connect(self._editing_finished)
            editor.matches_changed.connect(self._show_matches)
            self._rendered_object.save_path_chosen.connect(self._view.export_text)

    @staticmethod
    def _refresh_text(
        _view: TextEditorViewLike, rendered_object: ComposeTextEditorBox, value: str
    ) -> None:
        if value != rendered_object.editor.text:  # the same text keeps the cursor
            rendered_object.editor.text = value

    @staticmethod
    def _refresh_placeholder(
        _view: TextEditorViewLike, rendered_object: ComposeTextEditorBox, value: str
    ) -> None:
        rendered_object.editor.placeholder = value

    @staticmethod
    def _refresh_texts(
        _view: TextEditorViewLike, rendered_object: ComposeTextEditorBox, value: dict[str, str]
    ) -> None:
        rendered_object.copy.label = value.get("copy", "")
        rendered_object.save.label = f"{value.get('save', '')}…"
        rendered_object.set_search_text(value.get("search", ""))
        rendered_object.show_position(value.get("position", ""))

    @staticmethod
    def _refresh_export_filename(
        _view: TextEditorViewLike, rendered_object: ComposeTextEditorBox, value: str
    ) -> None:
        rendered_object.export_filename = value
        rendered_object.file_name.update(value)

    @staticmethod
    def _refresh_language(
        _view: TextEditorViewLike, rendered_object: ComposeTextEditorBox, value: str | Lexer | None
    ) -> None:
        rendered_object.editor.set_syntax(value)

    def _update_text(self, text: str) -> None:
        if text == self._view.text:  # the text the view set, not an edit
            return
        self._is_edited = True
        with self.stop_refresh():
            self._view.text = text
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        # as Qt and the browser, only after a change: leaving the editor doesn't commit it
        if self._is_edited:
            self._is_edited = False
            self._view.editing_finished.emit()

    def _show_matches(self, current: int, count: int) -> None:
        """Show the search's count of matches: none without a search."""
        assert self._rendered_object is not None
        box = self._rendered_object
        box.matches.update(matches_text(self._view.texts, box.search.value, current, count))


class FloatInputViewLike(ViewLike, Protocol):
    placeholder: str
    value: float | None
    minimum: float | None
    maximum: float | None
    decimals: int | None
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs

    def shown_text(self, value: float | None, decimals: int | None) -> str: ...


class TextualFloatInputRenderer(TextualWidgetRenderer[FloatInputViewLike, ComposeInput]):
    _marks_invalid = True

    def __init__(self, view: FloatInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                # shown, not enforced: Textual's `Number` validator only bounds min/max,
                # with no equivalent of Qt's `QDoubleValidator.setDecimals`
                "decimals": self._refresh_decimals,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeInput()
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_value(
        view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.set_value(view.shown_text(value, view.decimals))

    @staticmethod
    def _refresh_decimals(
        view: FloatInputViewLike, rendered_object: ComposeInput, value: int | None
    ) -> None:
        rendered_object.set_value(view.shown_text(view.value, value))

    @staticmethod
    def _refresh_placeholder(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: str
    ) -> None:
        rendered_object.placeholder = value

    @staticmethod
    def _refresh_minimum(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.validators = [
            v for v in rendered_object.validators if not isinstance(v, Number)
        ]
        rendered_object.validators.append(Number(minimum=value, maximum=_view.maximum))

    @staticmethod
    def _refresh_maximum(
        _view: FloatInputViewLike, rendered_object: ComposeInput, value: float | None
    ) -> None:
        rendered_object.validators = [
            v for v in rendered_object.validators if not isinstance(v, Number)
        ]
        rendered_object.validators.append(Number(minimum=_view.minimum, maximum=value))

    def _update_text(self, text: str) -> None:
        # transient invalid text while typing (e.g. "-") is ignored
        with self.stop_refresh(), contextlib.suppress(ValueError):
            self._view.value = float(text) if text != "" else None
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


class IntInputViewLike(ViewLike, Protocol):
    placeholder: str
    value: int | None
    minimum: int | None
    maximum: int | None
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs


class TextualIntInputRenderer(TextualWidgetRenderer[IntInputViewLike, ComposeInput]):
    """An input taking only a whole number; Textual has no spin box.

    As on the float input, a value out of `minimum`/`maximum` is marked invalid, not refused.
    """

    _marks_invalid = True

    def __init__(self, view: IntInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_range,
                "maximum": self._refresh_range,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            # `type="integer"` lets in only what can start an int: digits and a sign
            self._rendered_object = ComposeInput(type="integer")
            self._rendered_object.value_changed.connect(self._update_text)
            self._rendered_object.value_submitted.connect(self._editing_finished)

    @staticmethod
    def _refresh_value(
        _view: IntInputViewLike, rendered_object: ComposeInput, value: int | None
    ) -> None:
        rendered_object.set_value(str(value) if value is not None else "")

    @staticmethod
    def _refresh_placeholder(
        _view: IntInputViewLike, rendered_object: ComposeInput, value: str
    ) -> None:
        rendered_object.placeholder = value

    @staticmethod
    def _refresh_range(view: IntInputViewLike, rendered_object: ComposeInput, _value: Any) -> None:
        # `type="integer"` adds an `Integer` validator of its own, without a range
        rendered_object.validators = [
            v for v in rendered_object.validators if not isinstance(v, Number)
        ]
        rendered_object.validators.append(Integer(minimum=view.minimum, maximum=view.maximum))

    def _update_text(self, text: str) -> None:
        # transient invalid text while typing (e.g. "-"); ignore it
        with self.stop_refresh(), contextlib.suppress(ValueError):
            self._view.value = int(text) if text != "" else None
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)

    def _editing_finished(self) -> None:
        self._view.editing_finished.emit()


class DateInputViewLike(ViewLike, Protocol):
    placeholder: str
    value: datetime.date | None
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    month_names: list[str]
    day_names: list[str]
    pick_text: str
    text_changed: Signal[str]
    text_edited: Signal[str]
    editing_finished: SignalNoArgs
    value_changed: Signal[datetime.date | None]


class TextualDateInputRenderer(TextualWidgetRenderer[DateInputViewLike, ComposeDateInput]):
    """A field typing the date as the view's `date_format` says, beside a calendar button.

    Textual has no date picker: the calendar is a screen of its own, its months and days
    named as the view's `month_names` and `day_names`, so in the main view's language.
    """

    _marks_invalid = True

    def __init__(self, view: DateInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "placeholder": self._refresh_placeholder,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "date_format": self._refresh_date_format,
                "month_names": self._refresh_month_names,
                "day_names": self._refresh_day_names,
                "pick_text": self._refresh_pick_text,
                # its calendar's keys move by month, its title naming the month shown
                "previous_month_text": lambda _view, _rendered_object, _value: None,
                "next_month_text": lambda _view, _rendered_object, _value: None,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeDateInput()
            self._rendered_object.date_edited.connect(self._update_value)
            self._rendered_object.input.value_changed.connect(self._update_text)
            # a picked date changes the text, but the user didn't type it
            self._rendered_object.text_picked.connect(self._view.text_changed.emit)
            self._rendered_object.input.value_submitted.connect(self._view.editing_finished.emit)

    @staticmethod
    def _refresh_value(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: datetime.date | None
    ) -> None:
        rendered_object.set_date(value)

    @staticmethod
    def _refresh_placeholder(
        view: DateInputViewLike, rendered_object: ComposeDateInput, value: str
    ) -> None:
        rendered_object.input.placeholder = date_hint(value, view.date_format)

    @staticmethod
    def _refresh_minimum(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: datetime.date | None
    ) -> None:
        rendered_object.minimum = value
        rendered_object.input.validate(rendered_object.input.value)

    @staticmethod
    def _refresh_maximum(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: datetime.date | None
    ) -> None:
        rendered_object.maximum = value
        rendered_object.input.validate(rendered_object.input.value)

    @staticmethod
    def _refresh_date_format(
        view: DateInputViewLike, rendered_object: ComposeDateInput, value: str
    ) -> None:
        rendered_object.set_date_format(value)
        rendered_object.input.placeholder = date_hint(view.placeholder, value)

    @staticmethod
    def _refresh_month_names(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: list[str]
    ) -> None:
        rendered_object.month_names = list(value)

    @staticmethod
    def _refresh_day_names(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: list[str]
    ) -> None:
        rendered_object.day_names = list(value)

    @staticmethod
    def _refresh_pick_text(
        _view: DateInputViewLike, rendered_object: ComposeDateInput, value: str
    ) -> None:
        rendered_object.button.tooltip = Content(value)

    def _update_value(self, value: datetime.date | None) -> None:
        with self.stop_refresh():
            self._view.value = value
        self._view.value_changed.emit(value)

    def _update_text(self, text: str) -> None:
        self._view.text_changed.emit(text)
        self._view.text_edited.emit(text)


class DateRangeInputViewLike(ViewLike, Protocol):
    value: tuple[datetime.date | None, datetime.date | None]
    minimum: datetime.date | None
    maximum: datetime.date | None
    date_format: str
    month_names: list[str]
    day_names: list[str]
    start_text: str
    end_text: str
    pick_text: str
    value_changed: Signal[tuple[datetime.date | None, datetime.date | None]]


class TextualDateRangeInputRenderer(
    TextualWidgetRenderer[DateRangeInputViewLike, ComposeDateRangeInput]
):
    """Two date fields, the start and the end, each beside its calendar button."""

    _marks_invalid = True

    def __init__(self, view: DateRangeInputViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "value": self._refresh_value,
                "minimum": self._refresh_minimum,
                "maximum": self._refresh_maximum,
                "date_format": self._refresh_date_format,
                "month_names": self._refresh_month_names,
                "day_names": self._refresh_day_names,
                "start_text": self._refresh_start_text,
                "end_text": self._refresh_end_text,
                "pick_text": self._refresh_pick_text,
            }
        )
        # its calendar's keys move by month, its title naming the month shown
        self._refresh_dispatcher.update(
            dict.fromkeys(
                ("previous_month_text", "next_month_text"),
                lambda _view, _rendered_object, _value: None,
            )
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeDateRangeInput()
            self._rendered_object.end_edited.connect(self._update_end)

    @staticmethod
    def _refresh_value(
        _view: DateRangeInputViewLike,
        rendered_object: ComposeDateRangeInput,
        value: tuple[datetime.date | None, datetime.date | None],
    ) -> None:
        for field, date in zip(rendered_object.fields, value):
            field.set_date(date)

    @staticmethod
    def _refresh_minimum(
        _view: DateRangeInputViewLike,
        rendered_object: ComposeDateRangeInput,
        value: datetime.date | None,
    ) -> None:
        for field in rendered_object.fields:
            field.minimum = value
            field.input.validate(field.input.value)

    @staticmethod
    def _refresh_maximum(
        _view: DateRangeInputViewLike,
        rendered_object: ComposeDateRangeInput,
        value: datetime.date | None,
    ) -> None:
        for field in rendered_object.fields:
            field.maximum = value
            field.input.validate(field.input.value)

    @staticmethod
    def _refresh_date_format(
        view: DateRangeInputViewLike, rendered_object: ComposeDateRangeInput, value: str
    ) -> None:
        for field, text in zip(rendered_object.fields, (view.start_text, view.end_text)):
            field.set_date_format(value)
            field.input.placeholder = date_hint(text, value)

    @staticmethod
    def _refresh_month_names(
        _view: DateRangeInputViewLike, rendered_object: ComposeDateRangeInput, value: list[str]
    ) -> None:
        for field in rendered_object.fields:
            field.month_names = list(value)

    @staticmethod
    def _refresh_day_names(
        _view: DateRangeInputViewLike, rendered_object: ComposeDateRangeInput, value: list[str]
    ) -> None:
        for field in rendered_object.fields:
            field.day_names = list(value)

    @staticmethod
    def _refresh_start_text(
        view: DateRangeInputViewLike, rendered_object: ComposeDateRangeInput, value: str
    ) -> None:
        rendered_object.start.input.placeholder = date_hint(value, view.date_format)

    @staticmethod
    def _refresh_end_text(
        view: DateRangeInputViewLike, rendered_object: ComposeDateRangeInput, value: str
    ) -> None:
        rendered_object.end.input.placeholder = date_hint(value, view.date_format)

    @staticmethod
    def _refresh_pick_text(
        _view: DateRangeInputViewLike, rendered_object: ComposeDateRangeInput, value: str
    ) -> None:
        for field in rendered_object.fields:
            field.button.tooltip = Content(value)

    def _update_end(self, index: int, date: datetime.date | None) -> None:
        view = self._view
        # the field reports only a new date, so the range changes
        value = DateRangeInputMixin.with_end(view.value, index, date)
        with self.stop_refresh():
            view.value = value
        # the other field, if it followed; not the one typed in, whose text the user writes
        other = 1 - index
        cast("ComposeDateRangeInput", self._rendered_object).fields[other].set_date(value[other])
        view.value_changed.emit(value)
