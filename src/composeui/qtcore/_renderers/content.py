"""Qt renderers for labels, images, Markdown, console, metrics, log and status bar."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qtpy.QtGui import QTextDocument
from qtpy.QtWidgets import QApplication, QFileDialog, QLabel, QStatusBar, QTextBrowser
from typing_extensions import Protocol

from composeui.core._views.content import image_content, line_styles_after, lines_after
from composeui.core.renderer import ViewLike
from composeui.core.view import ConsoleView, LogType, MetricView, StatusBar, TextRole
from composeui.qtcore.qtrenderer import _QWIDGETSIZE_MAX, QtWidgetRenderer
from composeui.qtcore.widgets.qconsole import QConsoleBox
from composeui.qtcore.widgets.qimagelabel import QImageLabel
from composeui.qtcore.widgets.qmetric import QMetric
from composeui.qtcore.widgets.qplaintext import plain_label
from composeui.qtcore.widgets.qtextrole import role_color, role_font, role_palette_color


class LabelViewLike(ViewLike, Protocol):
    text: str
    role: TextRole


class QtLabelRenderer(QtWidgetRenderer[LabelViewLike, QLabel]):
    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "text": self._refresh_text,
                "role": self._refresh_role,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = plain_label()
            # a long line wraps to its page's width, as on the web, rather than widening the page
            self._rendered_object.setWordWrap(True)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
        rendered_object.setText(value)

    @staticmethod
    def _refresh_role(_view: LabelViewLike, rendered_object: QLabel, value: TextRole) -> None:
        # a font that sets nothing takes all of the parent's, so the body text follows the app
        rendered_object.setFont(role_font(value))
        rendered_object.setForegroundRole(role_palette_color(value))
        color = role_color(value)
        rendered_object.setStyleSheet(f"QLabel {{ color : {color}; }}" if color else "")


class ImageViewLike(ViewLike, Protocol):
    image: Path | bytes | None
    description: str
    height: int | None


class QtImageRenderer(QtWidgetRenderer[ImageViewLike, QImageLabel]):
    def __init__(self, view: ImageViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "image": self._refresh_image,
                "description": self._refresh_description,
                "height": self._refresh_height,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QImageLabel()
            self.refresh()

    @staticmethod
    def _refresh_image(
        _view: ImageViewLike, rendered_object: QImageLabel, value: Path | bytes | None
    ) -> None:
        rendered_object.set_image(image_content(value))

    @staticmethod
    def _refresh_description(
        _view: ImageViewLike, rendered_object: QImageLabel, value: str
    ) -> None:
        rendered_object.setText(value)
        rendered_object.setAccessibleName(value)

    @staticmethod
    def _refresh_height(
        _view: ImageViewLike, rendered_object: QImageLabel, value: int | None
    ) -> None:
        rendered_object.set_image_height(value)
        rendered_object.setMinimumHeight(0 if value is None else value)
        rendered_object.setMaximumHeight(_QWIDGETSIZE_MAX if value is None else value)


class MarkdownViewLike(ViewLike, Protocol):
    text: str


class QtMarkdownRenderer(QtWidgetRenderer[MarkdownViewLike, QTextBrowser]):
    def __init__(self, view: MarkdownViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._refresh_text})

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QTextBrowser()
            self._rendered_object.setOpenExternalLinks(True)
            self.refresh()

    @staticmethod
    def _refresh_text(_view: MarkdownViewLike, rendered_object: QTextBrowser, value: str) -> None:
        # raw HTML shown as text, as on the web
        features = QTextDocument.MarkdownFeature
        rendered_object.document().setMarkdown(
            value, features.MarkdownDialectGitHub | features.MarkdownNoHTML
        )


class ConsoleViewLike(ViewLike, Protocol):
    text: str
    max_lines: int
    line_count: int
    last_line: str
    ansi_colors: bool
    texts: dict[str, str]
    export_filename: str

    def export_text(self, path: Path) -> None: ...


class QtConsoleRenderer(QtWidgetRenderer[ConsoleViewLike, QConsoleBox]):
    """The console's text in a `QConsole`, its new lines added to those it shows.

    Its search field highlights the matches, its Copy button copies the whole text to the
    clipboard, and its Save button asks where to save it, in Qt's file dialog.
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
                # the dialog's, read as it opens
                "export_filename": lambda _view, _box, _value: None,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QConsoleBox()
            self._connect(self._rendered_object.save.clicked, self._save)
            self._connect(self._rendered_object.copy.clicked, self._copy)
            self._connect(self._rendered_object.text.matches_changed, self._show_matches)
            self.refresh()

    @staticmethod
    def _refresh_max_lines(
        _view: ConsoleViewLike, rendered_object: QConsoleBox, value: int
    ) -> None:
        rendered_object.text.set_max_lines(value)

    def _refresh_text(
        self, view: ConsoleViewLike, rendered_object: QConsoleBox, value: str
    ) -> None:
        self._show_text(view, rendered_object, colors=view.ansi_colors)

    def _show_text(self, view: ConsoleViewLike, box: QConsoleBox, *, colors: bool) -> None:
        """Show the whole text, with its colors if `colors`: maybe not yet the view's."""
        assert isinstance(view, ConsoleView)
        styles = [*view.line_styles, view.last_line_styles] if colors else ()
        box.text.set_text(view.text, styles)
        self._shown_count = view.line_count

    def _refresh_line_count(
        self, view: ConsoleViewLike, rendered_object: QConsoleBox, value: int
    ) -> None:
        assert isinstance(view, ConsoleView)
        lines = lines_after(view, self._shown_count)
        styles: list[Any] = []
        if view.ansi_colors:
            styles = [*line_styles_after(view, self._shown_count), view.last_line_styles]
        rendered_object.text.add(lines, view.last_line, styles)
        self._shown_count = value

    @staticmethod
    def _refresh_texts(
        _view: ConsoleViewLike, rendered_object: QConsoleBox, value: dict[str, str]
    ) -> None:
        rendered_object.save.setText(f"{value.get('save', '')}…")
        rendered_object.copy.setText(value.get("copy", ""))
        rendered_object.search.setPlaceholderText(value.get("search", ""))

    def _show_matches(self, current: int, count: int) -> None:
        """Show the search's count of matches: none without a search."""
        assert self._rendered_object is not None
        texts = self._view.texts
        if self._rendered_object.search.text() == "":
            text = ""
        elif count == 0:
            text = texts.get("no_match", "")
        else:
            text = texts.get("matches", "").format(current=current, count=count)
        self._rendered_object.matches.setText(text)

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


class MetricViewLike(ViewLike, Protocol):
    label: str
    value: str
    delta: float | None
    delta_text: str
    delta_format: str


class QtMetricRenderer(QtWidgetRenderer[MetricViewLike, QMetric]):
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

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QMetric()
            self.refresh()

    @staticmethod
    def _refresh_label(_view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        rendered_object.label.setText(value)

    @staticmethod
    def _refresh_value(_view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        rendered_object.value.setText(value)

    @staticmethod
    def _refresh_delta(view: MetricViewLike, rendered_object: QMetric, value: float | None) -> None:
        QtMetricRenderer._show_badge(rendered_object, value, view.delta_text, view.delta_format)

    @staticmethod
    def _refresh_delta_text(view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        QtMetricRenderer._show_badge(rendered_object, view.delta, value, view.delta_format)

    @staticmethod
    def _refresh_delta_format(view: MetricViewLike, rendered_object: QMetric, value: str) -> None:
        QtMetricRenderer._show_badge(rendered_object, view.delta, view.delta_text, value)

    @staticmethod
    def _show_badge(
        rendered_object: QMetric, delta: float | None, delta_text: str, delta_format: str
    ) -> None:
        if delta is None:
            rendered_object.set_delta("", 0)
        else:
            sign = int(delta > 0) - int(delta < 0)
            rendered_object.set_delta(MetricView.badge(delta, delta_text, delta_format), sign)


class LogViewLike(ViewLike, Protocol):
    log_message: str
    log_type: LogType


class QtLogRenderer(QtWidgetRenderer[LogViewLike, QLabel]):
    def __init__(self, view: LogViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "log_message": self._refresh_log_message,
                "log_type": self._refresh_log_type,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = plain_label()
            self._rendered_object.setWordWrap(True)
            self.refresh()

    @staticmethod
    def _refresh_log_message(_view: LogViewLike, rendered_object: QLabel, value: str) -> None:
        rendered_object.setVisible(value != "")
        rendered_object.setText(value)

    @staticmethod
    def _refresh_log_type(_view: LogViewLike, rendered_object: QLabel, value: LogType) -> None:
        if value == LogType.ERROR:
            rendered_object.setStyleSheet("QLabel { color : red; }")
        elif value == LogType.WARNING:
            rendered_object.setStyleSheet("QLabel { color : orange; }")
        else:
            rendered_object.setStyleSheet("")


class QtStatusBarRenderer(QtWidgetRenderer[StatusBar, QStatusBar]):
    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._refresh_message,
            }
        )

    def render(self) -> None:
        if self._rendered_object is None:
            self._rendered_object = QStatusBar()
            self._relay(self._view.message_changed, self._rendered_object.messageChanged)
            self.refresh()

    @staticmethod
    def _refresh_message(_view: StatusBar, rendered_object: QStatusBar, message: str) -> None:
        rendered_object.showMessage(message)
