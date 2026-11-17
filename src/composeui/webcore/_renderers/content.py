"""The web renderers of what a page shows: metrics, labels, images, Markdown, consoles, logs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from markupsafe import Markup

from composeui.core.renderer import ViewLike
from composeui.core.view import FormRowView, StatusBar

if TYPE_CHECKING:
    from pathlib import Path

import hashlib
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt
from typing_extensions import Protocol

from composeui.core._views.content import image_content, line_styles_after, lines_after
from composeui.core.view import ConsoleView, LogType, MetricView, TextRole, TextStyle
from composeui.webcore.webrenderer import WebRenderer

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


class MetricViewLike(ViewLike, Protocol):
    label: str
    value: str
    delta: float | None
    delta_text: str
    delta_format: str


class WebMetricRenderer(WebRenderer[MetricViewLike]):
    """A daisyUI stat: its label, its value, and its change as a badge colored by its sign."""

    _role = "metric"

    def __init__(self, view: MetricViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "label": self._mark_dirty,
                "value": self._mark_dirty,
                "delta": self._mark_dirty,
                "delta_text": self._mark_dirty,
                "delta_format": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        delta = self._view.delta
        badge = ""
        if delta is not None:
            color = "badge-success" if delta > 0 else "badge-error" if delta < 0 else "badge-ghost"
            text = MetricView.badge(delta, self._view.delta_text, self._view.delta_format)
            badge = Markup(
                '<div class="stat-desc"><span class="badge badge-soft {}">{}</span></div>'
            ).format(color, text)
        return Markup(
            '<div {root_attributes} class="stat px-0">'
            '<div class="stat-title">{label}</div>'
            '<div class="stat-value">{value}</div>{badge}</div>'
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            label=self._view.label,
            value=self._view.value,
            badge=badge,
        )


class LabelViewLike(ViewLike, Protocol):
    text: str
    role: TextRole


#: the tag of a role's text and its classes; the page's `<h1>` is the app's title
_ROLE_MARKUP = {
    TextRole.BODY: ("span", ""),
    TextRole.TITLE: ("h2", "text-xl font-bold"),
    TextRole.SUBTITLE: ("h3", "font-semibold text-base-content/70"),
    TextRole.CAPTION: ("span", "text-sm text-base-content/70"),
    TextRole.MUTED: ("span", "text-base-content/70"),
    TextRole.ERROR: ("span", "text-error"),
    TextRole.WARNING: ("span", "text-warning"),
    TextRole.SUCCESS: ("span", "text-success"),
}


class WebLabelRenderer(WebRenderer[LabelViewLike]):
    _role = "label"

    def __init__(self, view: LabelViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty, "role": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        tag, classes = _ROLE_MARKUP[self._view.role]
        return Markup('<{tag} {attributes} class="{classes}">{text}</{tag}>').format(
            tag=tag,
            attributes=self._root_attributes(oob=oob),
            classes=classes,
            text=self._view.text,
        )


class ImageViewLike(ViewLike, Protocol):
    image: Path | bytes | None
    description: str
    height: int | None


#: how the image types a browser shows start, with their media types; the rest of a view's
#: content, such as a text file that a user named, is never served
_IMAGE_STARTS = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"\x00\x00\x01\x00", "image/x-icon"),
)
#: the bytes of a file read to find its `<svg>` tag, after an XML header, a comment or a doctype
_SVG_HEADER_SIZE = 4096


def _image_media_type(content: bytes) -> str | None:
    """Get the media type of an image from how it starts; None if it isn't one."""
    for start, media_type in _IMAGE_STARTS:
        if content.startswith(start):
            return media_type
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    header = content[:_SVG_HEADER_SIZE]
    if header.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<") and b"<svg" in header:
        return "image/svg+xml"
    return None


def _image_version(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


class WebImageRenderer(WebRenderer[ImageViewLike]):
    """An `<img>` that the session's own route serves, or its description without an image.

    Not the process's registry of icons: an image can be private to its session. Not a
    `data:` address either: each swap of the fragment would send it again.
    """

    _role = "image"

    def __init__(self, view: ImageViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "image": self._mark_dirty,
                "description": self._mark_dirty,
                "height": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        content = image_content(self._view.image)
        if content is None or _image_media_type(content) is None:
            return Markup("<span {}>{}</span>").format(
                self._root_attributes(oob=oob), self._view.description
            )
        height = self._view.height
        return Markup(
            '<img {} class="max-w-full self-start object-contain object-left" alt="{}"'
            ' src="/widget/{}/picture?version={}"{}>'
        ).format(
            self._root_attributes(oob=oob),
            self._view.description,
            self.widget_id,
            _image_version(content),
            Markup("") if height is None else Markup(' style="height: {}px"').format(int(height)),
        )

    def picture(self, version: str) -> tuple[bytes, str] | None:
        """Get the image's content and media type; None unless it is still at `version`.

        Its address names its content, so a browser can keep it: an older version, or a
        file that changed, must not answer another image under that address.
        """
        content = image_content(self._view.image)
        if content is None or _image_version(content) != version:
            return None
        media_type = _image_media_type(content)
        return None if media_type is None else (content, media_type)


class MarkdownViewLike(ViewLike, Protocol):
    text: str


class WebMarkdownRenderer(WebRenderer[MarkdownViewLike]):
    """Markdown as HTML, tables included, as Qt and Textual show them.

    Raw HTML is off: the text can't inject markup (and markdown-it refuses `javascript:`
    links).
    """

    _role = "markdown"

    def __init__(self, view: MarkdownViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update({"text": self._mark_dirty})

    def to_html(self, *, oob: bool = False) -> Markup:
        parser = MarkdownIt("commonmark", {"html": False}).enable("table")
        # markup the parser escaped itself: the text's own HTML is off
        content = Markup(parser.render(self._view.text))  # noqa: S704
        return Markup('<div {} class="cui-markdown">{}</div>').format(
            self._root_attributes(oob=oob), content
        )


class ConsoleViewLike(ViewLike, Protocol):
    text: str
    max_lines: int
    line_count: int
    last_line: str
    ansi_colors: bool
    line_styles: Sequence[tuple[tuple[int, int, TextStyle], ...]]
    last_line_styles: Sequence[tuple[int, int, TextStyle]]
    lines: Sequence[str]
    texts: dict[str, str]
    export_filename: str


def _css_style(style: TextStyle) -> str:
    """Get the inline CSS of text in `style`: its colors are "#rrggbb", from the view."""
    declarations = []
    if style.foreground is not None:
        declarations.append(f"color:{style.foreground}")
    if style.background is not None:
        declarations.append(f"background-color:{style.background}")
    if style.is_bold:
        declarations.append("font-weight:bold")
    if style.is_italic:
        declarations.append("font-style:italic")
    if style.is_underlined:
        declarations.append("text-decoration:underline")
    return ";".join(declarations)


class WebConsoleRenderer(WebRenderer[ConsoleViewLike]):
    """The console's lines in a box, the line being written last; a change sends new lines.

    Each line is a ``<span>`` ended by its newline, in a ``<pre>``. New lines go before
    the line being written, which is swapped: the text the page holds stays as it is. The
    page's script drops the oldest lines past `data-max-lines`, and keeps the box at its
    end as lines come, unless the user scrolled up (see `page.js`). Above the box, a button
    copies the whole text, in the page, which holds the lines the view keeps; a link
    downloads it (`text_file`, by the `/widget/{id}/text` route). The search field finds
    in the page too, as `find_in_lines` does, and highlights the matches without changing
    the text; it stays as typed when the whole console is swapped (`hx-preserve`).
    """

    _role = "console"

    def __init__(self, view: ConsoleViewLike) -> None:
        super().__init__(view)
        #: how many of the view's lines had ended when the page last got them
        self._sent: int | None = None
        self._is_whole = True
        self._refresh_dispatcher.update(
            {
                "max_lines": self._mark_dirty,
                "text": self._mark_dirty,
                "line_count": self._mark_added,
                "ansi_colors": self._mark_dirty,
                "texts": self._mark_dirty,
                # the download's, read as it is asked for
                "export_filename": lambda _view, _rendered_object, _value: None,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        sent, self._sent = self._sent, self._view.line_count
        is_whole, self._is_whole = self._is_whole, False
        if oob and not is_whole and sent is not None:
            assert isinstance(self._view, ConsoleView)
            lines = lines_after(self._view, sent)
            styles = line_styles_after(self._view, sent)
            added = Markup('<span hx-swap-oob="beforebegin:#{}-last">{}</span>').format(
                self.widget_id, self._lines_html(lines, styles)
            )
            return (added if len(lines) > 0 else Markup()) + self._last_html(oob=True)
        return Markup(
            '<div {root_attributes} class="flex flex-col gap-2">'
            '<div class="flex flex-wrap items-center gap-1">'
            '<input type="search" id="{widget_id}-search" class="input input-xs w-48"'
            ' placeholder="{search}" aria-label="{search}" autocomplete="off" hx-preserve'
            ' data-console-search="{widget_id}-text" data-matches="{matches}"'
            ' data-no-match="{no_match}">'
            '<span class="text-sm" aria-live="polite" data-console-matches></span>'
            '<button type="button" class="btn btn-ghost btn-xs ml-auto"'
            ' data-copy-console="{widget_id}-text">{copy}</button>'
            # a plain link: htmx can't start a download
            '<a class="btn btn-ghost btn-xs" href="/widget/{widget_id}/text"'
            " download>{save}</a></div>"
            '<pre id="{widget_id}-text" class="cui-console" data-console'
            ' data-max-lines="{max_lines}" tabindex="0">'
            "{lines}{last}</pre></div>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            widget_id=self.widget_id,
            save=self._view.texts.get("save", ""),
            copy=self._view.texts.get("copy", ""),
            search=self._view.texts.get("search", ""),
            matches=self._view.texts.get("matches", ""),
            no_match=self._view.texts.get("no_match", ""),
            max_lines=self._view.max_lines,
            lines=self._lines_html(self._view.lines, self._view.line_styles),
            last=self._last_html(oob=False),
        )

    def text_file(self) -> tuple[str, str]:
        """Get the download's name, and the text."""
        return self._view.export_filename, self._view.text

    def _lines_html(
        self, lines: Sequence[str], styles: Sequence[Sequence[tuple[int, int, TextStyle]]]
    ) -> Markup:
        return Markup("").join(
            Markup("<span>{}\n</span>").format(self._styled_html(line, line_styles))
            for line, line_styles in zip(lines, styles)
        )

    def _last_html(self, *, oob: bool) -> Markup:
        """Render the line being written: its own swap when `oob`."""
        swap = Markup(' hx-swap-oob="true"') if oob else Markup()
        last = self._styled_html(self._view.last_line, self._view.last_line_styles)
        return Markup('<span id="{}-last"{}>{}</span>').format(self.widget_id, swap, last)

    def _styled_html(self, line: str, styles: Sequence[tuple[int, int, TextStyle]]) -> Markup:
        """Render a line's text, its styled parts in their styles if the view shows them."""
        if not self._view.ansi_colors:
            return Markup("{}").format(line)
        parts: list[Markup] = []
        position = 0
        for start, end, style in styles:
            parts.append(Markup("{}").format(line[position:start]))
            parts.append(
                Markup('<span style="{}">{}</span>').format(_css_style(style), line[start:end])
            )
            position = end
        parts.append(Markup("{}").format(line[position:]))
        return Markup("").join(parts)

    def _mark_dirty(self, view: ConsoleViewLike, rendered_object: str, value: Any) -> None:
        self._is_whole = True
        super()._mark_dirty(view, rendered_object, value)

    def _mark_added(self, view: ConsoleViewLike, rendered_object: str, value: Any) -> None:
        # the lines added, unless the whole console is to go
        super()._mark_dirty(view, rendered_object, value)


class LogViewLike(ViewLike, Protocol):
    log_message: str
    log_type: LogType


_LOG_CLASSES: Final[dict[LogType, str]] = {
    LogType.ERROR: "text-error",
    LogType.WARNING: "text-warning",
    LogType.INFO: "text-info",
}


class WebLogRenderer(WebRenderer[LogViewLike]):
    _role = "log"

    def __init__(self, view: LogViewLike) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "log_message": self._mark_dirty,
                "log_type": self._mark_dirty,
            }
        )
        if isinstance(view, FormRowView):
            # carried by the log, not the field: swapping a field being typed in would
            # reset its caret
            self._refresh_dispatcher["has_form_error"] = self._mark_dirty

    def to_html(self, *, oob: bool = False) -> Markup:
        attributes = self._root_attributes(oob=oob)
        if self._view.is_visible and self._view.log_message == "":
            attributes += " hidden"  # same as Qt/Textual: an empty log takes no room
        if isinstance(self._view, FormRowView) and self._view.has_form_error:
            attributes += " data-form-error"  # a check of the form failed on this row
        # `pre-line`: `FormView.validate` joins its messages with newlines.
        # `data-log`, `data-form-error`: the page's stylesheet and script mark the field
        # just before the log as invalid
        return Markup(
            '<p {attributes} aria-live="polite" data-log="{lower}" class="text-sm'
            ' whitespace-pre-line {LOG_CLASSES}">{log_message}</p>'
        ).format(
            attributes=attributes,
            lower=self._view.log_type.name.lower(),
            LOG_CLASSES=_LOG_CLASSES[self._view.log_type],
            log_message=self._view.log_message,
        )


#: seconds a status bar waits past its message's timeout before fetching itself again
_AUTO_CLEAR_MARGIN = 0.25


class WebStatusBarRenderer(WebRenderer[StatusBar]):
    _role = "status_bar"

    def __init__(self, view: StatusBar) -> None:
        super().__init__(view)
        self._refresh_dispatcher.update(
            {
                "message": self._mark_dirty,
                "timeout": self._mark_dirty,
            }
        )

    def to_html(self, *, oob: bool = False) -> Markup:
        # docked like Qt/Textual's status bar; an empty message leaves a quiet empty line
        return Markup(
            "<footer {root_attributes}{auto_clear_attributes}"
            ' role="status" aria-live="polite"'
            ' class="status-bar fixed inset-x-0 bottom-0 z-20 flex min-h-9 items-center gap-2'
            ' border-t border-base-300 px-4 text-sm">'
            "{message}"
            "</footer>"
        ).format(
            root_attributes=self._root_attributes(oob=oob),
            auto_clear_attributes=self._auto_clear_attributes(),
            message=self._view.message,
        )

    def _auto_clear_attributes(self) -> Markup:
        """Fetch the bar again once its message has timed out.

        `show_message`'s timer clears the message on the server outside any request,
        so no response ever tells the browser. Instead, a bar showing a message asks
        for its own current state once, just after `timeout`; by then the timer has
        cleared it. A message that was replaced or re-shown meanwhile comes back with
        its own fresh delay, so a stale fetch is harmless.
        """
        if self._view.message == "" or self._view.timeout <= 0:
            return Markup()
        # margin: the browser's delay starts after the server's timer did, but not by much
        delay_ms = round((self._view.timeout + _AUTO_CLEAR_MARGIN) * 1000)
        return Markup(
            ' hx-get="/widget/{}" hx-trigger="load delay:{}ms" hx-swap="outerHTML"'
        ).format(self.widget_id, delay_ms)
