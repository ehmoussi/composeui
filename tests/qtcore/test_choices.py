"""Tests of the Qt radio groups, comboboxes, check lists and trees."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from qtpy.QtCore import QPoint, Qt
from qtpy.QtGui import (
    QColor,
    QPixmap,
)
from qtpy.QtWidgets import (
    QCheckBox,
    QComboBox,
    QRadioButton,
    QTreeWidget,
    QTreeWidgetItem,
)

from composeui.core.registry import RendererType
from composeui.core.view import (
    TreeNode,
)
from composeui.qtcore.qtrenderer import QtWidgetRenderer
from composeui.qtcore.widgets.qchecklist import QCheckList, QMultiComboBox
from examples.pipeform import EdgeType, PipeMainView
from tests.buildings import SiteMainView, styled_site
from tests.choices import Base, ChoicesMainView
from tests.filters import FiltersMainView

if TYPE_CHECKING:
    from pathlib import Path

    from pytestqt.qtbot import QtBot


from tests.qtcore.support import _field_widget, _widget


def test_radio_group_renderer_click_round_trips_value_and_drives_status_bar(qtbot: QtBot) -> None:
    view = PipeMainView()
    # timeout=0, set before render() (see test_status_bar_renderer_... below for why):
    # the click below triggers `_display_message_status_bar`, and the default 3s
    # timeout would otherwise leave a real background `threading.Timer` running
    # past this test, later crashing whatever test happens to be running when it
    # fires against this test's already-destroyed `QStatusBar`.
    view.status_bar.timeout = 0
    view.render(RendererType.QT)
    edge_widget = _field_widget(view.pages.inputs.pipe_form.edge_type)

    # rendering rebuilds the buttons (`refresh` re-applies `values`): the first set is
    # gone at once, not left on screen until the event loop deletes it
    buttons = edge_widget.findChildren(QRadioButton)
    assert len(buttons) == 3
    chamfer_button = next(b for b in buttons if b.text() == EdgeType.Chamfer.value)
    chamfer_button.click()

    assert view.pages.inputs.pipe_form.edge_type.value == EdgeType.Chamfer
    assert "Chamfer" in view.status_bar.message  # value_changed -> status bar

    chamfer_renderer = view.pages.inputs.pipe_form.chamfer.renderer
    assert isinstance(chamfer_renderer, QtWidgetRenderer)
    chamfer_widget = chamfer_renderer.qt_object
    assert chamfer_widget is not None
    assert chamfer_widget.isVisible() is True  # edge_type -> group visibility


def test_a_radio_group_cleared_keeps_one_choice_at_a_time(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.status_bar.timeout = 0  # its click shows a message: no timer after the test
    view.render(RendererType.QT)
    edge = view.pages.inputs.pipe_form.edge_type
    widget = _field_widget(edge)
    qtbot.addWidget(widget)
    assert [button for button in widget.findChildren(QRadioButton) if button.isChecked()]

    edge.value = None  # its buttons unchecked: shown in tests/contracts/test_choices.py

    # the group's still exclusive
    buttons = widget.findChildren(QRadioButton)
    buttons[0].click()
    buttons[1].click()
    assert [button.isChecked() for button in buttons[:2]] == [False, True]


def test_radio_buttons_sit_together_at_the_start_of_their_row(qtbot: QtBot) -> None:
    view = PipeMainView()
    view.render(RendererType.QT)
    edge_widget = _field_widget(view.pages.inputs.pipe_form.edge_type)
    edge_widget.resize(600, 40)
    edge_widget.show()
    # rendering already rebuilt them once (`refresh` re-applies `values`)
    buttons = edge_widget.findChildren(QRadioButton)
    qtbot.waitUntil(lambda: all(button.isVisible() for button in buttons))  # laid out
    buttons.sort(key=lambda button: button.x())

    assert buttons[0].x() == 0
    # each next to the one before, at its own width, not spread over the row: the stretch
    # after them takes the rest. Not a share of the row: the text's width differs between
    # systems' fonts.
    layout = edge_widget.layout()
    assert layout is not None
    for before, after in zip(buttons, buttons[1:]):
        assert after.x() == before.geometry().right() + 1 + layout.spacing()
    assert [button.width() for button in buttons] == [
        button.sizeHint().width() for button in buttons
    ]
    assert buttons[-1].geometry().right() < edge_widget.width() - 1


def _tree_item(tree: QTreeWidget, *labels: str) -> QTreeWidgetItem:
    """Get the item down a tree's labels, from a top-level one."""
    items = tree.findItems(labels[-1], Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
    (item,) = [item for item in items if _labels(item) == labels]
    return item


def _labels(item: QTreeWidgetItem) -> tuple[str, ...]:
    parent: Optional[QTreeWidgetItem] = item.parent()
    return (*(() if parent is None else _labels(parent)), item.text(0))


def test_a_tree_selects_and_expands_its_nodes_by_click_and_key(qtbot: QtBot) -> None:
    view = SiteMainView()
    view.render(RendererType.QT)
    site = view.site
    assert isinstance(site.renderer, QtWidgetRenderer)
    tree = site.renderer.qt_object
    assert isinstance(tree, QTreeWidget)
    qtbot.addWidget(tree)
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))
    tree.show()
    assert _tree_item(tree, "Building A").isExpanded()
    assert not _tree_item(tree, "Building B").isExpanded()

    room = _tree_item(tree, "Building A", "Floor 1")
    qtbot.mouseClick(
        tree.viewport(), Qt.MouseButton.LeftButton, pos=tree.visualItemRect(room).center()
    )
    assert (site.selected, selections) == (("Building A", "Floor 1"), [("Building A", "Floor 1")])
    tree.setFocus()
    qtbot.keyClick(tree, Qt.Key.Key_Right)
    assert site.expanded == [("Building A",), ("Building A", "Floor 1")]
    assert toggles == [(("Building A", "Floor 1"), True)]
    qtbot.keyClick(tree, Qt.Key.Key_Down)  # onto its first room
    assert selections[-1] == ("Building A", "Floor 1", "Room 101")

    site.expanded = [("Building B",)]
    site.selected = ("Building B", "Floor 1")
    # new nodes keep the selection still in them
    site.nodes = [*site.nodes, TreeNode("Garden")]
    assert tree.topLevelItemCount() == 4
    assert tree.selectedItems() == [_tree_item(tree, "Building B", "Floor 1")]


def test_a_tree_shows_its_nodes_icon_style_and_mark_named_by_a_tooltip(
    qtbot: QtBot, tmp_path: Path
) -> None:
    icon = tmp_path / "building.png"
    pixmap = QPixmap(8, 8)
    pixmap.fill(QColor("blue"))
    assert pixmap.save(str(icon))
    view = SiteMainView()
    view.render(RendererType.QT)
    site = view.site
    assert isinstance(site.renderer, QtWidgetRenderer)
    tree = site.renderer.qt_object
    assert isinstance(tree, QTreeWidget)
    qtbot.addWidget(tree)
    assert tree.isColumnHidden(1)  # no node marked: no column for the marks

    site.nodes = styled_site(str(icon))
    assert not tree.isColumnHidden(1)
    building, parking = _tree_item(tree, "Building A"), _tree_item(tree, "Parking")
    assert not building.icon(0).isNull()
    assert parking.icon(0).isNull()
    assert (building.font(0).bold(), building.font(0).underline()) == (True, False)
    assert (parking.font(0).bold(), parking.font(0).underline()) == (False, True)
    done, failed = (
        _tree_item(tree, "Building A", "Room 101"),
        _tree_item(tree, "Building A", "Room 102"),
    )
    assert building.icon(1).isNull()
    assert not done.icon(1).isNull()
    assert done.icon(1).cacheKey() != failed.icon(1).cacheKey()
    assert [item.toolTip(1) for item in (done, failed, parking)] == ["Done", "Error", "Warning"]
    site.done_text = "Terminé"  # as the main view's language changes
    assert [item.toolTip(1) for item in (done, failed)] == ["Terminé", "Error"]


def _click_box_text(qtbot: QtBot, box: QCheckBox) -> None:
    """Click a check box on its text, not on its square."""
    qtbot.mouseClick(
        box,
        Qt.MouseButton.LeftButton,
        pos=QPoint(box.sizeHint().width() - 4, box.height() // 2),
    )


def test_a_check_list_checks_the_view_s_values_its_check_all_box_those_the_search_shows(
    qtbot: QtBot,
) -> None:
    view = ChoicesMainView()
    view.render(RendererType.QT)
    check_list = _widget(view.hours)
    assert isinstance(check_list, QCheckList)
    qtbot.addWidget(check_list)
    check_list.show()
    seen: list[list[int]] = []
    view.hours.selected_changed.connect(seen.append)

    qtbot.keyClicks(check_list.search_field, "MORN")
    rows = [box.text() for box in check_list.boxes]
    assert (view.hours.search, rows) == ("MORN", ["Early morning", "Morning"])
    _click_box_text(qtbot, check_list.boxes[1])
    assert (view.hours.selected, seen) == ([9], [[9]])
    assert check_list.check_all.checkState() == Qt.CheckState.PartiallyChecked

    check_list.check_all.click()  # partly checked: checks all those shown
    assert (view.hours.selected, seen[-1]) == ([5, 9], [5, 9])
    assert check_list.check_all.checkState() == Qt.CheckState.Checked

    view.hours.search = ""
    view.hours.values = {"Dawn": 5, "Day": 9, "Dusk": 12, "Night": 19}  # the same keys
    assert [box.text() for box in check_list.boxes] == ["Dawn", "Day", "Dusk", "Night"]


def test_a_multi_combobox_shows_the_choice_on_its_button_and_the_boxes_in_its_menu(
    qtbot: QtBot,
) -> None:
    view = ChoicesMainView()
    view.render(RendererType.QT)
    combobox = _field_widget(view.bases)
    assert isinstance(combobox, QMultiComboBox)
    qtbot.addWidget(combobox)
    assert combobox.text() == "None"
    assert not combobox.check_list.search_field.isVisibleTo(combobox.check_list)

    menu = combobox.menu()
    assert menu is not None
    combobox.resize(300, combobox.height())
    menu.popup(combobox.mapToGlobal(combobox.rect().bottomLeft()))  # as a click does
    assert menu.width() >= combobox.width()  # as wide as the button, as a combobox's list
    weiter = combobox.check_list.boxes[2]
    # anywhere on its row, past its text: a click reaching the menu would close it
    qtbot.mouseClick(
        weiter, Qt.MouseButton.LeftButton, pos=QPoint(weiter.width() - 4, weiter.height() // 2)
    )
    qtbot.mouseClick(combobox.check_list, Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert menu.isVisible()
    menu.close()

    assert (view.bases.selected, combobox.text()) == ([Base.WEITER], "Weiter")
    view.bases.selected = [Base.UNTER, Base.HINTER]
    assert combobox.text() == "2 selected"


def test_a_tree_keeps_its_node_selected_when_the_user_deselects_it(qtbot: QtBot) -> None:
    view = SiteMainView()
    view.render(RendererType.QT)
    site = view.site
    tree = _widget(site)
    assert isinstance(tree, QTreeWidget)
    qtbot.addWidget(tree)
    tree.show()
    site.selected = ("Building A", "Floor 1")
    selections: list[tuple[str, ...]] = []
    site.selection_changed.connect(selections.append)
    item = _tree_item(tree, "Building A", "Floor 1")

    qtbot.mouseClick(
        tree.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        tree.visualItemRect(item).center(),
    )

    assert tree.selectedItems() == [item]
    assert (site.selected, selections) == (("Building A", "Floor 1"), [])


def test_a_none_choice_is_shown_selected_and_picked_back(qtbot: QtBot) -> None:
    view = FiltersMainView()
    view.render(RendererType.QT)
    region, shown = view.form.region, view.form.shown
    combobox, radios = _field_widget(region), _field_widget(shown)
    assert isinstance(combobox, QComboBox)
    qtbot.addWidget(combobox)
    qtbot.addWidget(radios)
    picked: list[object] = []
    region.value_changed.connect(picked.append)

    assert combobox.currentText() == "All regions"
    assert [b.text() for b in radios.findChildren(QRadioButton) if b.isChecked()] == ["All regions"]
    region.value = "south"
    assert combobox.currentText() == "South"
    combobox.setCurrentIndex(0)  # what the user's pick does

    assert (region.value, picked) == (None, [None])
