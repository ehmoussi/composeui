"""The views that show text: labels, Markdown, images, logs, the console, metrics."""

from __future__ import annotations

import enum
import functools
import io
import re
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Optional,
    Union,
    cast,
)

import attrs

from composeui.core._views.base import (
    OMIT,
    UI_TEXT,
    LogType,
    View,
    _check_height,
    define_view,
    emit_if_made,
    notify_renderer,
)
from composeui.core.renderer import Renderer, RendererContainer
from composeui.core.signal import Signal, SignalNoArgs
from composeui.core.translation import (
    T,
)

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from typing_extensions import Unpack


class _MessageTimer:
    """Clears a message once its timeout passes, on its view's renderer's thread."""

    def __init__(self) -> None:
        self._timer: Optional[threading.Timer] = None

    def start(self, view: View, timeout: float, clear: Callable[[], None]) -> None:
        """Call `clear` in `timeout` seconds, instead of any call started before; never at 0."""
        self.cancel()
        if timeout > 0:
            timer = threading.Timer(timeout, lambda: self._dispatch(view, timer, clear))
            self._timer = timer
            timer.start()

    def cancel(self) -> None:
        """Take back the call started last, unless it's already on its way."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _dispatch(self, view: View, timer: threading.Timer, clear: Callable[[], None]) -> None:
        """Run `clear` on the renderer's thread, not the timer's own thread.

        `threading.Timer` calls its target on a dedicated background thread; a bound
        renderer (e.g. Qt) may only be touched from its GUI thread, so the actual
        mutation has to be marshaled through `Renderer.call_on_main_thread` instead
        of calling `clear` here directly.
        """
        clear_if_current = functools.partial(self._clear_if_current, timer, clear)
        if view.renderer is not None:
            view.renderer.call_on_main_thread(clear_if_current)
        else:
            clear_if_current()

    def _clear_if_current(self, timer: threading.Timer, clear: Callable[[], None]) -> None:
        # canceling a timer can't take back a clear already on its way
        if self._timer is timer:
            self._timer = None
            clear()


@define_view
class StatusBar(View):
    """A line at the bottom of the window that shows a short message to the user.

    `show_message` shows a message for `timeout` seconds.
    """

    _renderer_key = "status_bar"

    message: str = attrs.field(default="")
    message_changed: Signal[str] = attrs.Factory(Signal[str])
    timeout: float = attrs.field(default=3.0)
    _timer: _MessageTimer = attrs.field(
        factory=_MessageTimer, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    def show_message(self, message: str) -> None:
        """Show `message` for `timeout` seconds.

        With a `timeout` of 0, the message is not dismissed automatically.
        """
        self.message = message
        self._timer.start(self, self.timeout, self.clear_message)

    def clear_message(self) -> None:
        """Remove the message from the status bar."""
        self._timer.cancel()
        self.message = ""


# class FileType(enum.Enum):
#     OpenFile = enum.auto()
#     SaveFile = enum.auto()


@define_view
class NotificationBar(View):
    """A message above the page, with its severity, such as an error that stays until closed.

    `MainView.notify` shows one, e.g. why a file can't be saved, and `clear` removes it.
    A message replaces the one shown. An information goes after `timeout` seconds; a
    warning or an error stays until the user closes it (`closed`), or the app clears it.
    Not saved with a study: a New or an Open keeps it.
    """

    _renderer_key = "notification_bar"

    message: str = attrs.field(default="")
    kind: LogType = attrs.field(default=LogType.INFO)
    #: the seconds an information stays; 0 keeps it until closed
    timeout: float = attrs.field(default=5.0)
    #: the name of the close button, which screen readers say
    close_text: str = attrs.field(default=T("Close"), metadata={UI_TEXT: True})
    #: the user closed the message, never emitted when the app clears it
    closed: SignalNoArgs = attrs.Factory(SignalNoArgs)
    #: counts the messages shown: a close of an earlier one comes too late (see `dismiss`)
    _number: int = attrs.field(default=0, init=False, repr=False, eq=False, metadata={OMIT: True})
    _timer: _MessageTimer = attrs.field(
        factory=_MessageTimer, init=False, repr=False, eq=False, metadata={OMIT: True}
    )

    @property
    def number(self) -> int:
        """The number of the message shown, which a close button gives back to `dismiss`."""
        return self._number

    def show(self, message: str, kind: LogType = LogType.INFO) -> None:
        """Show `message` as `kind`, instead of the message shown.

        The same message again is the same one: only its timeout starts again.
        """
        if (message, kind) != (self.message, self.kind):
            self._number += 1
        self.kind = kind
        self.message = message
        timeout = self.timeout if kind == LogType.INFO else 0
        self._timer.start(self, timeout, self.clear)

    def clear(self) -> None:
        """Remove the message, without `closed`: the user didn't close it."""
        self._timer.cancel()
        self.message = ""

    def dismiss(self, number: int) -> None:
        """Remove the message `number` as the user closes it, and emit `closed`.

        A close of a message already gone or replaced does nothing: on the web, the
        page can show an earlier message for a moment.
        """
        if number != self._number or self.message == "":
            return
        self.clear()
        emit_if_made(self, "closed")


#: A zero-argument check: reads whatever state it needs itself (e.g. `self.text`
#: via a bound method) and returns an error message, or None if it passes.
Validator = Callable[[], Optional[str]]


@define_view
class LogMixin:
    """The fields of a message that a check (`validator`) writes, e.g. an error."""

    log_message: str = attrs.field(default="")
    log_type: LogType = attrs.field(default=LogType.ERROR)
    validator: Optional[Validator] = attrs.field(default=None, repr=False, metadata={OMIT: True})
    #: the row's check ran (`run_validator`), passing or not, e.g. for a form dialog's OK
    checked: SignalNoArgs = attrs.Factory(SignalNoArgs)

    def set_validator(
        self, validator: Validator, *signals: Signal[Unpack[tuple[Any, ...]]]
    ) -> None:
        """Wire `validator` to run against this row whenever any of `signals` fires.

        A failing (non-None) result is pushed into this row's own `log_message`/`log_type`,
        and a passing (None) result clears them. It doesn't run `validator` immediately: call
        `run_validator` afterward for an initial check. E.g. an empty required field should
        already show its error before the first edit.
        """
        self.validator = validator
        for signal in signals:
            signal.connect(self.run_validator)

    def run_validator(self, *_args: Any) -> None:
        """Re-run `validator`, if set, and push its result into the row's own log.

        Takes (and ignores) any positional arguments, so it can be connected directly to
        signals of any arity. E.g. a per-keystroke ``text_edited: Signal[str]``, or a
        no-argument ``editing_finished: SignalNoArgs``.
        """
        if self.validator is None:
            return
        message = self.validator()
        self.log_message = message or ""
        self.log_type = LogType.ERROR if message else LogType.INFO
        # most rows' isn't connected: don't make it. A mixin of views only
        emit_if_made(cast("View", self), "checked")

    def _check_again(self) -> None:
        if self.log_message != "":
            self.run_validator()


@define_view
class LogView(LogMixin, View):
    """A message to the user, for example an error, styled by its `log_type`.

    A new message replaces the last one. For a stream of output, see `ConsoleView`.
    """

    _renderer_key = "log"


class TextRole(enum.Enum):
    """What a text is, which each backend shows in its own way."""

    BODY = enum.auto()
    TITLE = enum.auto()
    SUBTITLE = enum.auto()
    CAPTION = enum.auto()
    MUTED = enum.auto()
    ERROR = enum.auto()
    WARNING = enum.auto()
    SUCCESS = enum.auto()


@define_view
class LabelMixin:
    """The fields of a label: its `text` and its `role`."""

    text: str = attrs.field(default="", metadata={UI_TEXT: True})
    role: TextRole = attrs.field(default=TextRole.BODY, metadata={OMIT: True})


@define_view
class LabelView(LabelMixin, View):
    """Read-only text, for example a caption; each line break in it starts a new line."""

    _renderer_key = "label"


@define_view
class MarkdownMixin:
    """The fields of a Markdown view: its `text`."""

    #: read-only Markdown, e.g. a help page; its links open in the browser
    text: str = attrs.field(default="", metadata={UI_TEXT: True})


@define_view
class MarkdownView(MarkdownMixin, View):
    """Read-only Markdown text, for example a help page.

    Its links open in the browser. Raw HTML in the text is never read as markup.
    """

    _renderer_key = "markdown"


def image_content(image: Union[Path, bytes, None]) -> Optional[bytes]:
    """Get the bytes of an `ImageView.image`; None without one, or for a file it can't read."""
    if isinstance(image, Path):
        try:
            return image.read_bytes()
        except OSError:
            return None
    return image


@define_view
class ImageView(View):
    """An image from a file, from bytes, or from a Matplotlib figure.

    Without an image, or with one that the backend cannot draw, it shows its `description`.
    Textual shows it too, unless the terminal can draw the image with the `terminal-images` extra.
    An image never grows past its own size unless `height` asks for it, and it shrinks to
    the width it has. It keeps its proportions.

    A study saves neither `image` nor `height`: they are the app's, and a study's file must
    not name a file to show. Give the image again in `MainView.loaded`.
    """

    _renderer_key = "image"

    #: a file's path, read each time the image shows, or a file's content
    image: Union[Path, bytes, None] = attrs.field(default=None, metadata={OMIT: True})
    #: what the image shows, for a screen reader and where it cannot show
    description: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: its height on screen, in pixels (a terminal's rows of about 16); None: its own
    height: Optional[int] = attrs.field(
        default=None, validator=[_check_height], metadata={OMIT: True}
    )

    def show_figure(self, figure: Figure) -> None:
        """Show a Matplotlib `figure` as it is now, as a PNG image at the figure's own size."""
        content = io.BytesIO()
        figure.savefig(content, format="png")
        self.image = content.getvalue()


#: what ends a line, or starts it again ("\r"), in a console's text
_LINE_BREAKS = re.compile(r"(\r\n|\n|\r)")
#: a console's texts, by what they're for: its controls saving the text to a file, copying
#: it to the clipboard, and searching it, with the count of the matches
CONSOLE_TEXTS: Mapping[str, str] = {
    "save": T("Save output"),
    "copy": T("Copy all"),
    "search": T("Search"),
    "matches": T("{current} of {count}"),
    "no_match": T("No match"),
}


#: an escape sequence of a terminal: a CSI one (a color, a cursor's move...), an OSC one (a
#: title, a link...), or another of two characters
_ESCAPE = re.compile(r"\x1b(?:\[([0-?]*)[ -/]*([@-~])|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")
#: the start of one, cut at the end of a text: the next text ends it
_ESCAPE_START = re.compile(r"\x1b(?:\[[0-?]*[ -/]*|\][^\x07\x1b]*\x1b?)?\Z")
#: the 16 colors of ANSI escape codes, then their bright ones: readable on a light or dark page
_ANSI_COLORS = (
    "#000000", "#cd3131", "#0dbc79", "#e5e510", "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
    "#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff",
)  # fmt: skip


@attrs.frozen
class TextStyle:
    """How a part of a console's line looks, as its ANSI escape codes ask (see `ConsoleView`).

    Colors are "#rrggbb", None for the console's own.
    """

    foreground: Optional[str] = None
    background: Optional[str] = None
    is_bold: bool = False
    is_italic: bool = False
    is_underlined: bool = False


#: the style of text no escape code styled
PLAIN_TEXT = TextStyle()


#: where the 256 colors' 6 by 6 by 6 cube starts, after the 16 colors, then its grays
_CUBE_START = 16
_GRAYS_START = 232
#: the SGR codes turning a style on or off: the style, and its value
_SGR_FLAGS = {
    1: ("is_bold", True),
    3: ("is_italic", True),
    4: ("is_underlined", True),
    22: ("is_bold", False),
    23: ("is_italic", False),
    24: ("is_underlined", False),
}
#: the SGR codes of a color: what it colors, and its index (None for the console's own)
_SGR_COLORS: dict[int, tuple[str, Optional[int]]] = {
    **{30 + index: ("foreground", index) for index in range(8)},
    **{90 + index: ("foreground", 8 + index) for index in range(8)},
    39: ("foreground", None),
    **{40 + index: ("background", index) for index in range(8)},
    **{100 + index: ("background", 8 + index) for index in range(8)},
    49: ("background", None),
}
#: the SGR codes of a color given next: by its index (5, then it), or red, green, blue (2)
_SGR_EXTENDED = {38: "foreground", 48: "background"}
_INDEXED, _RGB = 5, 2


def _ansi_color(index: int) -> str:
    """Get the color of an ANSI code's index: 16 colors, a 6 by 6 by 6 cube, then grays."""
    if index < _CUBE_START:
        return _ANSI_COLORS[index]
    if index < _GRAYS_START:
        cube = index - _CUBE_START
        steps = (cube // 36, cube // 6 % 6, cube % 6)
        return "#{:02x}{:02x}{:02x}".format(*(0 if step == 0 else 55 + 40 * step for step in steps))
    gray = 8 + 10 * (min(index, 255) - _GRAYS_START)
    return f"#{gray:02x}{gray:02x}{gray:02x}"


def _styled(style: TextStyle, parameters: str) -> TextStyle:
    """Get `style` as an SGR escape code (``ESC [ parameters m``) changes it."""
    codes = [int(code) if code.isdigit() else 0 for code in re.split("[;:]", parameters or "0")]
    changes: dict[str, Any] = {}
    index = 0
    while index < len(codes):
        code = codes[index]
        if code == 0:
            style, changes = PLAIN_TEXT, {}
        elif code in _SGR_FLAGS:
            name, value = _SGR_FLAGS[code]
            changes[name] = value
        elif code in _SGR_COLORS:
            name, color = _SGR_COLORS[code]
            changes[name] = None if color is None else _ansi_color(color)
        elif code in _SGR_EXTENDED and index + 2 < len(codes):
            kind, values = codes[index + 1], codes[index + 2 :]
            if kind == _INDEXED:
                changes[_SGR_EXTENDED[code]] = _ansi_color(min(values[0], 255))
                index += 2
            elif kind == _RGB and len(values) >= len("rgb"):
                rgb = [min(value, 255) for value in values[:3]]
                changes[_SGR_EXTENDED[code]] = "#{:02x}{:02x}{:02x}".format(*rgb)
                index += 4
            else:  # an unknown kind, or cut short: its values can't be told from codes
                index = len(codes)
        index += 1
    return attrs.evolve(style, **changes)


def find_in_lines(lines: Sequence[str], query: str) -> list[tuple[int, int, int]]:
    """Find `query` in a console's `lines`, as its search does: plain text, any case.

    Get each match's line, start and end, in order; none for an empty query.
    """
    if query == "":
        return []
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    return [
        (index, match.start(), match.end())
        for index, line in enumerate(lines)
        for match in pattern.finditer(line)
    ]


def follow_match(
    matches: Sequence[tuple[int, int, int]], first_line: int, current: Optional[tuple[int, int]]
) -> int:
    """Get the index of a search's current match among `matches`, after lines came or went.

    `current` is the match shown before, as its line's number, counted from the first line
    ever shown, and its start; `first_line` is the number of `matches`' first line. The
    match is the same one, or the next if it went, else the last; the first without one.
    """
    if current is None or len(matches) == 0:
        return 0
    for index, (line, start, _end) in enumerate(matches):
        if (first_line + line, start) >= current:
            return index
    return len(matches) - 1


@define_view
class ConsoleView(View):
    r"""Plain text that the app adds to as it comes, for example the output of a process.

    `append` adds text: "\n" ends a line, and "\r" starts the line again, as a terminal
    shows a progress line. The view keeps the last `max_lines` lines and drops the oldest.
    Set `text` to replace the text, or call `clear`. The view shows the text as it is,
    never as markup, and scrolls to its end as text comes, unless the user scrolled up.

    Its text is the app's output, not study data: never saved, loaded or reset. For a
    single message to the user, such as an error, see `LogView`. The user saves the text
    to a file (`export_text`), named `export_filename` at first, or copies it all. The
    user searches the text too: plain text, any case, as `find_in_lines` finds it.

    The text loses the escape sequences of a terminal, such as the ANSI codes coloring a
    solver's output, so it reads, searches and saves as plain text. With `ansi_colors`,
    the view shows the colors and styles those codes ask for (`line_styles`).
    """

    _renderer_key = "console"

    def _trim(self, _attribute: attrs.Attribute[Any], max_lines: int) -> int:
        self._drop_oldest(max_lines)
        return max_lines

    #: the most lines kept, the line being written not counted; the oldest go first
    max_lines: int = attrs.field(
        default=10_000,
        validator=attrs.validators.ge(1),
        on_setattr=[attrs.setters.validate, _trim, notify_renderer],
        metadata={OMIT: True},
    )
    _lines: deque[str] = attrs.field(
        factory=deque[str], init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    _last_line: str = attrs.field(default="", init=False, repr=False, metadata={OMIT: True})
    #: a "\r" ended the text so far: the next text starts the last line again
    _is_returned: bool = attrs.field(default=False, init=False, repr=False, metadata={OMIT: True})
    _line_count: int = attrs.field(default=0, init=False, repr=False, metadata={OMIT: True})
    #: whether it shows the colors and styles of the text's ANSI escape codes
    ansi_colors: bool = attrs.field(default=False, metadata={OMIT: True})
    _line_styles: deque[tuple[tuple[int, int, TextStyle], ...]] = attrs.field(
        factory=deque, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    _last_line_styles: list[tuple[int, int, TextStyle]] = attrs.field(
        factory=list, init=False, repr=False, eq=False, metadata={OMIT: True}
    )
    #: the style the escape codes so far ask for, for the next text
    _style: TextStyle = attrs.field(
        default=PLAIN_TEXT, init=False, repr=False, metadata={OMIT: True}
    )
    #: an escape sequence cut at the end of the text so far: the next text ends it
    _escape: str = attrs.field(default="", init=False, repr=False, metadata={OMIT: True})
    #: the texts of its controls, by what they're for (see `CONSOLE_TEXTS`)
    texts: dict[str, str] = attrs.field(
        factory=lambda: dict(CONSOLE_TEXTS), metadata={UI_TEXT: True}
    )
    #: the name offered for the file the text is saved to
    export_filename: str = attrs.field(default="output.txt", metadata={OMIT: True})

    @property
    def text(self) -> str:
        """Get the lines kept, then the line being written."""
        return "\n".join([*self._lines, self._last_line])

    @text.setter
    def text(self, text: str) -> None:
        self._lines.clear()
        self._line_styles.clear()
        self._last_line = ""
        self._last_line_styles = []
        self._is_returned = False
        self._style = PLAIN_TEXT
        self._escape = ""
        self._add(text)
        self._refresh("text")

    @property
    def lines(self) -> Sequence[str]:
        """Get the lines kept, each ended, the oldest first."""
        return self._lines

    @property
    def last_line(self) -> str:
        """Get the line being written: the text after the last line's end."""
        return self._last_line

    @property
    def line_styles(self) -> Sequence[tuple[tuple[int, int, TextStyle], ...]]:
        """Get the styled parts of each line kept, as `lines`: start, end and style."""
        return self._line_styles

    @property
    def last_line_styles(self) -> Sequence[tuple[int, int, TextStyle]]:
        """Get the styled parts of the line being written: start, end and style."""
        return self._last_line_styles

    @property
    def line_count(self) -> int:
        """Get how many lines have ended since the view was built, the dropped ones too."""
        return self._line_count

    def append(self, text: str) -> None:
        """Add `text` at the end, e.g. the output a process has written since the last call."""
        self._add(text)
        self._refresh("line_count")

    def clear(self) -> None:
        """Remove the whole text."""
        self.text = ""

    def export_text(self, path: Path) -> None:
        """Write the text to the file `path`, in UTF-8, and say how it went.

        Outside a main view, a failure raises `OSError` instead.
        """
        main_view = None if self._main_view is None else self._main_view()
        try:
            path.write_text(self.text, encoding="utf-8")
        except OSError as error:
            if main_view is None:
                raise
            failed = self.tr("Can't save to {name}: {error}.")
            main_view.notify(failed.format(name=path.name, error=error), LogType.ERROR)
            return
        if main_view is not None:
            done = self.tr("Saved the output to {name}.")
            main_view.status_bar.show_message(done.format(name=path.name))

    def _add(self, text: str) -> None:
        text, self._escape = self._escape + text, ""
        cut = _ESCAPE_START.search(text)
        if cut is not None:
            text, self._escape = text[: cut.start()], text[cut.start() :]
        start = 0
        for escape in _ESCAPE.finditer(text):
            self._add_text(text[start : escape.start()])
            if escape.group(2) == "m":  # a color or a style; the other sequences go
                self._style = _styled(self._style, escape.group(1))
            start = escape.end()
        self._add_text(text[start:])
        self._drop_oldest(self.max_lines)

    def _add_text(self, text: str) -> None:
        """Add `text`, without escape sequences, in the current style."""
        for part in _LINE_BREAKS.split(text.replace("\x1b", "")):
            if part in ("\n", "\r\n"):
                self._lines.append(self._last_line)
                self._line_styles.append(tuple(self._last_line_styles))
                self._line_count += 1
                self._last_line, self._last_line_styles = "", []
                self._is_returned = False
            elif part == "\r":
                # a "\n" may come next, in the next text: the line then ends as it is
                self._is_returned = True
            elif part != "":
                if self._is_returned:
                    self._last_line, self._last_line_styles = "", []
                start = len(self._last_line)
                self._last_line += part
                styles = self._last_line_styles
                if styles and styles[-1][1:] == (start, self._style):  # one part, longer
                    styles[-1] = (styles[-1][0], len(self._last_line), self._style)
                elif self._style != PLAIN_TEXT:
                    styles.append((start, len(self._last_line), self._style))
                self._is_returned = False

    def _drop_oldest(self, max_lines: int) -> None:
        while len(self._lines) > max_lines:
            self._lines.popleft()
            self._line_styles.popleft()

    def _refresh(self, name: str) -> None:
        """Show the change: not a field's, which the renderer would hear by itself."""
        renderer = self.renderer
        if isinstance(renderer, (Renderer, RendererContainer)):
            renderer.refresh_attribute(name, getattr(self, name))


def lines_after(console: ConsoleView, count: int) -> list[str]:
    """Get the lines kept that ended after the first `count`, e.g. the ones not shown yet."""
    lines = console.lines
    new = min(console.line_count - count, len(lines))
    return [lines[index] for index in range(len(lines) - new, len(lines))]


def line_styles_after(
    console: ConsoleView, count: int
) -> list[tuple[tuple[int, int, TextStyle], ...]]:
    """Get the styles of `lines_after`'s lines, as `ConsoleView.line_styles` gives them."""
    styles = console.line_styles
    new = min(console.line_count - count, len(styles))
    return [styles[index] for index in range(len(styles) - new, len(styles))]


_MAX_METRIC_FORMAT_LENGTH = 64
_MAX_METRIC_FORMAT_COMPONENT = 1000


def _check_delta_format(_view: MetricView, _attribute: attrs.Attribute[Any], value: str) -> None:
    # A saved study controls this format: bound it before formatting allocates its output.
    if len(value) > _MAX_METRIC_FORMAT_LENGTH or any(
        int(number) > _MAX_METRIC_FORMAT_COMPONENT for number in re.findall(r"\d+", value)
    ):
        msg = (
            f"MetricView.delta_format must have at most {_MAX_METRIC_FORMAT_LENGTH} characters, "
            f"with width and precision at most {_MAX_METRIC_FORMAT_COMPONENT}."
        )
        raise ValueError(msg)
    format(0.0, value)


@define_view
class MetricView(View):
    """A figure read at a glance, e.g. the jobs running, and how much it changed.

    A row of them in a `HorizontalView` makes a dashboard's summary.
    """

    _renderer_key = "metric"

    #: what the figure counts, e.g. "Running"
    label: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: the figure as shown, formatted by the app, e.g. "3" or "12.5 GB"
    value: str = attrs.field(default="")
    #: how much the figure changed; None shows no badge, else its sign colors the badge
    delta: Optional[float] = attrs.field(default=None)
    #: after the change in its badge, e.g. "since yesterday"
    delta_text: str = attrs.field(default="", metadata={UI_TEXT: True})
    #: Python number format for the change's magnitude, e.g. ".1f" or ".1%"
    delta_format: str = attrs.field(default=".15g", validator=[_check_delta_format])

    @staticmethod
    def badge(delta: float, delta_text: str, delta_format: str = ".15g") -> str:
        """Get the badge's text, e.g. "↑ 2 since yesterday", a fall "↓ 2", no change "→ 0".

        Take the values separately, as a renderer refreshes one before the view holds it.
        """
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        # The default's 15 digits hide float noise and keep counts below 1e15 out of exponents.
        text = f"{arrow} {abs(delta):{delta_format}}"
        return f"{text} {delta_text}" if delta_text != "" else text
