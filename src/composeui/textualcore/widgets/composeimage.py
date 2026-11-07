from __future__ import annotations

import io
from importlib import import_module
from typing import TYPE_CHECKING, Any, Callable, NamedTuple

from textual.containers import Vertical
from textual.widgets import Label

if TYPE_CHECKING:
    from PIL.Image import Image
    from textual.app import ComposeResult
    from textual.widget import Widget


class Graphics(NamedTuple):
    """How the terminal draws an image in pixels."""

    #: makes the widget that draws an image, set in its `image`
    widget: Callable[[], Any]
    #: gets a cell's width and height, in pixels
    cell_size: Callable[[], tuple[int, int]]


def terminal_graphics() -> Graphics | None:
    """Find how this terminal draws pixels; None without `textual-image`, or if it can't.

    Importing `textual-image` asks the terminal what it supports, which it can do only before
    Textual takes the terminal over: this runs as the backend's module loads. Its own fallback
    draws in characters, which no figure reads well in: the view's description is better.
    """
    try:
        renderable = import_module("textual_image.renderable")
        widget = import_module("textual_image.widget")
    except ImportError:
        return None
    if renderable.Image is renderable.SixelImage:
        return Graphics(widget.SixelImage, widget.get_cell_size)
    if renderable.Image is renderable.TGPImage:
        return Graphics(widget.TGPImage, widget.get_cell_size)
    return None


#: once, for the process: see `terminal_graphics`
GRAPHICS = terminal_graphics()


def _opened(content: bytes | None) -> Image | None:
    """Get the image in `content`; None for none, or for content Pillow can't read, as an SVG."""
    if content is None:
        return None
    pillow = import_module("PIL.Image")
    try:
        image: Image = pillow.open(io.BytesIO(content))
        image.load()
    except (OSError, ValueError, SyntaxError, EOFError, pillow.DecompressionBombError):
        return None
    return image


class ComposeImage(Vertical):
    """An image in pixels where the terminal can draw them, else its description."""

    DEFAULT_CSS = """
    ComposeImage {
        width: 100%;
        height: auto;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._description = Label(markup=False)
        self._graphics = GRAPHICS
        self._pixels: Widget | None = None if GRAPHICS is None else GRAPHICS.widget()
        self._image: Image | None = None
        self._height: int | None = None

    def compose(self) -> ComposeResult:
        yield self._description
        if self._pixels is not None:
            self._pixels.display = False
            yield self._pixels

    def set_description(self, description: str) -> None:
        self._description.update(description)

    def set_image(self, content: bytes | None) -> None:
        """Show the image in `content`; the description for none, or if it can't draw it."""
        if self._pixels is None:
            return
        self._image = _opened(content)
        self._description.display = self._image is None
        self._pixels.display = self._image is not None
        self._pixels.image = self._image  # type: ignore[attr-defined]
        self._fit()

    def set_image_height(self, height: int | None) -> None:
        """Give the image this height in pixels, grown to it if need be; None: its own."""
        self._height = height
        self._fit()

    def on_resize(self) -> None:
        self._fit()

    def _fit(self) -> None:
        """Size the image in cells: its own size, shrunk to the width, in its proportions."""
        if self._graphics is None or self._pixels is None or self._image is None:
            return
        available = self.size.width
        if available == 0:  # not laid out yet: `on_resize` comes
            return
        cell_width, cell_height = self._graphics.cell_size()
        width, height = self._image.size
        shown_height = height if self._height is None else self._height
        scale = min(shown_height / height, available * cell_width / width)
        self._pixels.styles.width = max(1, round(width * scale / cell_width))
        self._pixels.styles.height = max(1, round(height * scale / cell_height))
