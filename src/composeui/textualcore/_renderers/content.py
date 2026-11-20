"""Textual labels, images, Markdown, console, metrics and status."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Label, Static
from typing_extensions import Protocol, override

from composeui.core._views.content import image_content, line_styles_after, lines_after
from composeui.core.renderer import ViewLike
from composeui.core.view import ConsoleView, LogType, MetricView, StatusBar
from composeui.textualcore.textualrenderer import TextualWidgetRenderer
from composeui.textualcore.widgets.composeconsole import ComposeConsoleBox
from composeui.textualcore.widgets.composeimage import ComposeImage
from composeui.textualcore.widgets.composelabel import ComposeLabel
from composeui.textualcore.widgets.composemarkdown import ComposeMarkdown
from composeui.textualcore.widgets.composemetric import ComposeMetric

if TYPE_CHECKING:
    from pathlib import Path

    from composeui.core.view import TextRole


class LabelViewLike(ViewLike, Protocol):
    text: str
    role: TextRole


class TextualLabelRenderer(TextualWidgetRenderer[LabelViewLike, ComposeLabel]):
    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "role": self._refresh_role,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeLabel(markup=False)

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: ComposeLabel, value: str) -> None:
        rendered_object.update(value)

    @staticmethod
    def _refresh_role(_view: LabelViewLike, rendered_object: ComposeLabel, value: TextRole) -> None:
        rendered_object.show_role(value)


class ImageViewLike(ViewLike, Protocol):
    image: Path | bytes | None
    description: str
    height: int | None


class TextualImageRenderer(TextualWidgetRenderer[ImageViewLike, ComposeImage]):
    def __init__(self, view: ImageViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "image": self._refresh_image,
                "description": self._refresh_description,
                "height": self._refresh_height,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeImage()

    @staticmethod
    def _refresh_image(
        _view: ImageViewLike, rendered_object: ComposeImage, value: Path | bytes | None
    ) -> None:
        rendered_object.set_image(image_content(value))

    @staticmethod
    def _refresh_description(
        _view: ImageViewLike, rendered_object: ComposeImage, value: str
    ) -> None:
        rendered_object.set_description(value)

    @staticmethod
    def _refresh_height(
        _view: ImageViewLike, rendered_object: ComposeImage, value: int | None
    ) -> None:
        rendered_object.set_image_height(value)


class MarkdownViewLike(ViewLike, Protocol):
    text: str


class TextualMarkdownRenderer(TextualWidgetRenderer[MarkdownViewLike, ComposeMarkdown]):
    def __init__(self, view: MarkdownViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._refresh_text})

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeMarkdown()

    @staticmethod
    def _refresh_text(
        _view: MarkdownViewLike, rendered_object: ComposeMarkdown, value: str
    ) -> None:
        rendered_object.set_text(value)


class ConsoleViewLike(ViewLike, Protocol):
    text: str
    max_lines: int
    line_count: int
    last_line: str
    ansi_colors: bool
    texts: dict[str, str]
    export_filename: str

    def export_text(self, path: Path) -> None: ...


class TextualConsoleRenderer(TextualWidgetRenderer[ConsoleViewLike, ComposeConsoleBox]):
    """The console's text in a `ComposeConsole`, its new lines added to those it shows.

    Above it, the search bar (`ComposeConsoleBox`) shows the count of its matches.
    """

    def __init__(self, view: ConsoleViewLike) -> None:
        super().__init__(view)
        #: how many of the view's lines had ended when the console last showed them
        self._shown_count = 0
        self._refresh_dispatcher.update(
            {
                "max_lines": self._refresh_max_lines,
                "text": self._refresh_text,
                "line_count": self._refresh_line_count,
                # the text again: with its colors or without
                "ansi_colors": lambda view, box, value: self._show_text(view, box, colors=value),
                "texts": self._refresh_texts,
                "export_filename": self._refresh_export_filename,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeConsoleBox()
            console = self._rendered_object.log_view
            console.save_path_chosen.connect(self._view.export_text)
            console.matches_changed.connect(self._show_matches)

    @staticmethod
    def _refresh_max_lines(
        _view: ConsoleViewLike, rendered_object: ComposeConsoleBox, value: int
    ) -> None:
        rendered_object.log_view.set_max_lines(value)

    def _refresh_text(
        self, view: ConsoleViewLike, rendered_object: ComposeConsoleBox, _value: str
    ) -> None:
        self._show_text(view, rendered_object, colors=view.ansi_colors)

    def _show_text(self, view: ConsoleViewLike, box: ComposeConsoleBox, *, colors: bool) -> None:
        """Show the whole text, with its colors if `colors`: maybe not yet the view's."""
        # the view as it is now: the change has waited for the app's thread
        assert isinstance(view, ConsoleView)
        styles = [*view.line_styles, view.last_line_styles] if colors else ()
        box.log_view.set_text(view.text, styles)
        self._shown_count = view.line_count

    def _refresh_line_count(
        self, view: ConsoleViewLike, rendered_object: ComposeConsoleBox, _value: int
    ) -> None:
        assert isinstance(view, ConsoleView)
        lines = lines_after(view, self._shown_count)
        styles: list[Any] = []
        if view.ansi_colors:
            styles = [*line_styles_after(view, self._shown_count), view.last_line_styles]
        rendered_object.log_view.add(lines, view.last_line, styles)
        self._shown_count = view.line_count

    @staticmethod
    def _refresh_texts(
        _view: ConsoleViewLike, rendered_object: ComposeConsoleBox, value: dict[str, str]
    ) -> None:
        rendered_object.log_view.set_texts(save=value.get("save", ""), copy=value.get("copy", ""))
        rendered_object.set_search_text(value.get("search", ""))

    @staticmethod
    def _refresh_export_filename(
        _view: ConsoleViewLike, rendered_object: ComposeConsoleBox, value: str
    ) -> None:
        rendered_object.log_view.export_filename = value

    def _show_matches(self, current: int, count: int) -> None:
        """Show the search's count of matches: none without a search."""
        assert self._rendered_object is not None
        texts = self._view.texts
        if self._rendered_object.search.value == "":
            text = ""
        elif count == 0:
            text = texts.get("no_match", "")
        else:
            text = texts.get("matches", "").format(current=current, count=count)
        self._rendered_object.matches.update(text)


class MetricViewLike(ViewLike, Protocol):
    label: str
    value: str
    delta: float | None
    delta_text: str
    delta_format: str


class TextualMetricRenderer(TextualWidgetRenderer[MetricViewLike, ComposeMetric]):
    def __init__(self, view: MetricViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._refresh_label,
                "value": self._refresh_value,
                "delta": self._refresh_delta,
                "delta_text": self._refresh_delta_text,
                "delta_format": self._refresh_delta_format,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = ComposeMetric()

    @staticmethod
    def _refresh_label(_view: MetricViewLike, rendered_object: ComposeMetric, value: str) -> None:
        rendered_object.label.update(value)

    @staticmethod
    def _refresh_value(_view: MetricViewLike, rendered_object: ComposeMetric, value: str) -> None:
        rendered_object.value.update(value)

    @staticmethod
    def _refresh_delta(
        view: MetricViewLike, rendered_object: ComposeMetric, value: float | None
    ) -> None:
        TextualMetricRenderer._show_badge(
            rendered_object, value, view.delta_text, view.delta_format
        )

    @staticmethod
    def _refresh_delta_text(
        view: MetricViewLike, rendered_object: ComposeMetric, value: str
    ) -> None:
        TextualMetricRenderer._show_badge(rendered_object, view.delta, value, view.delta_format)

    @staticmethod
    def _refresh_delta_format(
        view: MetricViewLike, rendered_object: ComposeMetric, value: str
    ) -> None:
        TextualMetricRenderer._show_badge(rendered_object, view.delta, view.delta_text, value)

    @staticmethod
    def _show_badge(
        rendered_object: ComposeMetric, delta: float | None, delta_text: str, delta_format: str
    ) -> None:
        if delta is None:
            rendered_object.set_delta("", 0)
        else:
            sign = int(delta > 0) - int(delta < 0)
            rendered_object.set_delta(MetricView.badge(delta, delta_text, delta_format), sign)


class LogViewLike(ViewLike, Protocol):
    log_message: str
    log_type: LogType


class TextualLogRenderer(TextualWidgetRenderer[LogViewLike, Label]):
    def __init__(self, view: LogViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "log_message": self._refresh_log_message,
                "log_type": self._refresh_log_type,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Label(markup=False)
            # default `width: auto` sizes to the unwrapped text - fine for a short
            # label, but a long validation message would silently overflow past the
            # terminal width and get clipped instead of wrapping.
            self._rendered_object.styles.width = "1fr"

    @staticmethod
    def _refresh_log_message(_view: LogViewLike, rendered_object: Label, value: str) -> None:
        rendered_object.display = value != ""
        rendered_object.update(value)

    @staticmethod
    def _refresh_log_type(_view: LogViewLike, rendered_object: Label, value: LogType) -> None:
        if value == LogType.ERROR:
            rendered_object.styles.color = "red"
        elif value == LogType.WARNING:
            rendered_object.styles.color = "orange"
        else:
            rendered_object.styles.color = None


class TextualStatusBarRenderer(TextualWidgetRenderer[StatusBar, Static]):
    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._refresh_message,
            }
        )

    @override
    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = Static(markup=False)
            self._rendered_object.styles.dock = "bottom"

    @staticmethod
    def _refresh_message(_view: StatusBar, rendered_object: Static, value: str) -> None:
        rendered_object.update(value)
