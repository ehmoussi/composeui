"""The Textual driver: keys pressed through the headless pilot."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Literal, Optional

from rich.style import Style
from rich.text import Text
from textual.widgets import Checkbox, Input, RadioButton, Select, TextArea
from textual.widgets._select import SelectCurrent, SelectOverlay
from textual.widgets.collapsible import CollapsibleTitle
from textual.widgets.selection_list import Selection

from composeui.core.registry import RendererType
from composeui.textualcore._renderers.navigation import TextualMainRenderer
from composeui.textualcore.widgets.composechecklist import ComposeCheckList, ComposeMultiComboBox
from composeui.textualcore.widgets.composeradioset import ComposeRadioSet
from composeui.textualcore.widgets.composerange import ComposeRangeSlider
from composeui.textualcore.widgets.composeslider import ComposeSlider
from composeui.textualcore.widgets.composetexteditor import ComposeTextEditorBox
from composeui.textualcore.widgets.composetree import ComposeTree
from tests.textualcore.support import _widget

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from textual.pilot import Pilot
    from textual.widget import Widget
    from textual.widgets.tree import TreeNode

    from composeui.core.view import MainView, View


class TextualDriver:
    def __init__(self) -> None:
        self._pilot: Optional[Pilot[Any]] = None

    @asynccontextmanager
    async def open(self, main_view: MainView) -> AsyncGenerator[None, None]:
        main_view.render(RendererType.TEXTUAL)
        assert isinstance(main_view.renderer, TextualMainRenderer)
        app = main_view.renderer.app
        assert app is not None
        async with app.run_test() as pilot:
            await pilot.pause()
            self._pilot = pilot
            yield

    @asynccontextmanager
    async def by_code(self) -> AsyncGenerator[None, None]:
        assert self._pilot is not None
        yield
        await self._pilot.pause()

    async def type(self, view: View, text: str, *, part: int = 0) -> None:
        box = _text_boxes(view)[part]
        await self._focus(box)
        keys = [{"\n": "enter", " ": "space"}.get(key, key) for key in text]
        # select all, then type over it
        await self._press("f7" if isinstance(box, TextArea) else "ctrl+shift+a", *keys)

    async def leave(self, view: View) -> None:
        # a text area's Tab too goes to the next field; a text editor's indents, Escape leaves
        # a read-only one's Tab leaves, as it types nothing
        box = _widget(view)
        is_indenting = isinstance(box, ComposeTextEditorBox) and not box.editor.read_only
        await self._press("escape" if is_indenting else "tab")
        assert not any(box.has_focus for box in _text_boxes(view))

    def shown_text(self, view: View, *, part: int = 0) -> str:
        box = _text_boxes(view)[part]
        return box.text if isinstance(box, TextArea) else box.value

    def edits(self, text: str) -> list[str]:
        return [text[:end] for end in range(1, len(text) + 1)]  # a report per key

    async def toggle(self, view: View) -> None:
        await self._focus(_checkbox(view))
        await self._press("space")

    def is_checked(self, view: View) -> bool:
        return _checkbox(view).value

    async def slide(self, view: View, end: Literal["start", "end"]) -> None:
        await self._focus(_slider(view))
        await self._press("home" if end == "start" else "end")

    def slider_text(self, view: View) -> str:
        # as drawn, not `shown_text()`, which can follow the value while the label stays behind
        drawn = _slider(view).render()
        assert isinstance(drawn, Text)
        return drawn.plain.lstrip("\u2500\u2501\u25cf").strip()  # the track's ─━●, then the value

    async def pick(self, view: View, label: str) -> None:
        field = _widget(view)
        await self._focus(field)
        if isinstance(field, Select):
            await self._press("enter")  # opens its list, which takes the focus
            overlay = field.query_one(SelectOverlay)
            prompts = [str(option.prompt) for option in overlay.options]
            await self._press("home", *["down"] * prompts.index(label), "enter")
        else:
            # by the arrow keys from the button pressed, where the set's cursor must be
            labels = [str(button.label) for button in field.query(RadioButton)]
            shown = self.chosen(view)
            assert shown is not None
            moves = labels.index(label) - labels.index(shown)
            await self._press(*["down" if moves > 0 else "up"] * abs(moves), "enter")

    def chosen(self, view: View) -> Optional[str]:
        field = _widget(view)
        if isinstance(field, Select):
            label = field.query_one(SelectCurrent).label
            return None if label is Select.NULL else str(label)
        assert isinstance(field, ComposeRadioSet)
        pressed = [button for button in field.query(RadioButton) if button.value]
        assert len(pressed) <= 1
        assert field.pressed_button is (pressed[0] if pressed else None)
        return str(pressed[0].label) if pressed else None

    async def search(self, view: View, text: str) -> None:
        await self._focus(_check_list(view).search_input)
        # select all, then type over it
        await self._press(
            "ctrl+shift+a", *([key if key != " " else "space" for key in text] or ["backspace"])
        )

    async def check(self, view: View, label: str) -> None:
        assert self._pilot is not None
        field = _widget(view)
        if isinstance(field, ComposeMultiComboBox) and field.collapsed:
            await self._pilot.click(field.query_one(CollapsibleTitle))  # opens its list
            await self._pilot.pause()
        choices = _check_list(view).choices
        await self._focus(choices)
        labels = [str(option.prompt) for option in choices.options]
        await self._press("home", *["down"] * labels.index(label), "space")

    def checks(self, view: View) -> list[tuple[str, bool]]:
        choices = _check_list(view).choices
        rows = []
        for option in choices.options:
            assert isinstance(option, Selection)
            rows.append((str(option.prompt), option.value in choices.selected))
        return rows

    def check_all_state(self, view: View) -> Optional[bool]:
        check_all = _check_list(view).check_all
        # the box's mark as drawn: a dash while partly checked
        return None if check_all.BUTTON_INNER == "-" else check_all.value

    async def select_node(self, view: View, labels: tuple[str, ...]) -> None:
        await self._to_node(view, labels)
        await self._press("enter")

    async def toggle_node(self, view: View, labels: tuple[str, ...]) -> None:
        await self._to_node(view, labels)
        await self._press("space")

    def selected_node(self, view: View) -> Optional[tuple[str, ...]]:
        tree = _tree(view)
        selected = []
        for line in range(tree.last_line + 1):
            node = tree.get_node_at_line(line)
            assert node is not None
            # marked as drawn: in bold
            label = tree.render_label(node, Style(), Style())
            if any(isinstance(span.style, Style) and span.style.bold for span in label.spans):
                selected.append(_labels(node))
        assert len(selected) <= 1
        return selected[0] if selected else None

    def expanded_nodes(self, view: View) -> list[tuple[str, ...]]:
        return [_labels(node) for node in _tree_nodes(_tree(view).root) if node.is_expanded]

    async def _to_node(self, view: View, labels: tuple[str, ...]) -> None:
        """Move the tree's cursor onto the node down `labels`, by key."""
        tree = _tree(view)
        await self._focus(tree)
        (node,) = [node for node in _tree_nodes(tree.root) if _labels(node) == labels]
        assert node.line != -1  # shown
        moves = node.line - tree.cursor_line
        await self._press(*["down" if moves > 0 else "up"] * abs(moves))

    async def _focus(self, widget: Widget) -> None:
        assert self._pilot is not None
        # `focus()` only asks the app to focus it later: a key could come first, and an input's
        # `Focus`, which selects all its text, after it. `set_focus` posts `Focus` now, and the
        # pause waits for the messages already posted to each widget.
        self._pilot.app.screen.set_focus(widget)
        await self._pilot.pause()

    async def _press(self, *keys: str) -> None:
        assert self._pilot is not None
        await self._pilot.press(*keys)
        # a key's `Changed` comes in a message handled after it
        await self._pilot.pause()


def _text_boxes(view: View) -> list[Input | TextArea]:
    """Find the boxes that the user types in, in order.

    The field, or its own: a date's, a file path's, a date range's two; a text editor's text.
    """
    field = _widget(view)
    if isinstance(field, (Input, TextArea)):
        return [field]
    if isinstance(field, ComposeTextEditorBox):  # not its search
        return [field.editor]
    boxes = [box for box in field.query("Input, TextArea") if isinstance(box, (Input, TextArea))]
    assert boxes
    return boxes


def _checkbox(view: View) -> Checkbox:
    checkbox = _widget(view)
    assert isinstance(checkbox, Checkbox)
    return checkbox


def _slider(view: View) -> ComposeSlider | ComposeRangeSlider:
    slider = _widget(view)
    assert isinstance(slider, (ComposeSlider, ComposeRangeSlider))
    return slider


def _check_list(view: View) -> ComposeCheckList:
    """Find the list of `view`'s boxes: the field, or a drop-down list's."""
    field = _widget(view)
    if isinstance(field, ComposeMultiComboBox):
        return field.check_list
    assert isinstance(field, ComposeCheckList)
    return field


def _tree(view: View) -> ComposeTree:
    tree = _widget(view)
    assert isinstance(tree, ComposeTree)
    return tree


def _tree_nodes(parent: TreeNode[Any]) -> list[TreeNode[Any]]:
    """Get the nodes under `parent`, depth first."""
    return [node for child in parent.children for node in (child, *_tree_nodes(child))]


def _labels(node: TreeNode[Any]) -> tuple[str, ...]:
    """Get the labels down to `node`, from its top-level node: the hidden root's left out."""
    parent = node.parent
    above = () if parent is None or parent.parent is None else _labels(parent)
    return (*above, str(node.label))
