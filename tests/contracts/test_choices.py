"""The rules of the radio groups, comboboxes, check lists and trees on every backend."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Any

import pytest
from attrs import Factory

from composeui.core.view import (
    CheckListView,
    ComboBoxView,
    MainView,
    MultiComboBoxView,
    RadioGroupView,
    TreeView,
    define_view,
)
from tests.buildings import SITE

if TYPE_CHECKING:
    from tests.contracts.support import Driver


class _Edge(enum.Enum):
    NORMAL = 1
    CHAMFER = 2
    FILLET = 3


class _Base(enum.Enum):
    UNTER = 1
    HINTER = 2
    WEITER = 3


def _edge() -> RadioGroupView[_Edge]:
    edge = RadioGroupView[_Edge](
        values={"Normal": _Edge.NORMAL, "Chamfer": _Edge.CHAMFER, "Fillet": _Edge.FILLET}
    )
    edge.value = _Edge.NORMAL
    return edge


def _size() -> ComboBoxView[str]:
    size = ComboBoxView[str](values={"Small": "small", "Medium": "medium", "Large": "large"})
    size.value = "small"
    return size


@define_view
class _OneChoiceMainView(MainView):
    edge: RadioGroupView[_Edge] = Factory(_edge)
    size: ComboBoxView[str] = Factory(_size)


@define_view
class _HoursMainView(MainView):
    hours: CheckListView[int] = Factory(
        lambda: CheckListView[int](
            values={"Early morning": 5, "Morning": 9, "Noon": 12, "Evening": 19}, has_search=True
        )
    )


@define_view
class _BasesMainView(MainView):
    bases: MultiComboBoxView[_Base] = Factory(
        lambda: MultiComboBoxView[_Base](
            values={"Unter": _Base.UNTER, "Hinter": _Base.HINTER, "Weiter": _Base.WEITER}
        )
    )


@define_view
class _SiteMainView(MainView):
    site: TreeView = Factory(lambda: TreeView(nodes=SITE, expanded=[("Building A",)]))


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["edge", "size"])
async def test_a_choice_of_one_reports_the_user_s_pick_not_the_code_s(
    driver: Driver, name: str
) -> None:
    view = _OneChoiceMainView()
    field = getattr(view, name)
    first, picked, last = field.values.items()
    picks: list[object] = []
    field.value_changed.connect(picks.append)

    async with driver.open(view):
        assert (driver.chosen(field), picks) == (first[0], [])
        async with driver.by_code():
            field.value = None
        assert (driver.chosen(field), picks) == (None, [])
        async with driver.by_code():
            field.value = first[1]
        async with driver.by_code():
            field.values = dict((picked, last, first))  # the code's choice among the new ones
            field.value = last[1]
        assert (driver.chosen(field), picks) == (last[0], [])

        await driver.pick(field, picked[0])
        assert (field.value, driver.chosen(field), picks) == (picked[1], picked[0], [picked[1]])

        async with driver.by_code():
            field.value = None  # once the user picked one
        assert (driver.chosen(field), picks) == (None, [picked[1]])

        async with driver.by_code():
            field.value = picked[1]
        async with driver.by_code():
            field.values = dict((first,))  # without the code's choice: cleared
        assert (field.value, driver.chosen(field), picks) == (None, None, [picked[1]])


def _checks(field: Any, chosen: list[object]) -> list[tuple[str, bool]]:
    return [(label, value in chosen) for label, value in field.values.items()]


@pytest.mark.asyncio
@pytest.mark.parametrize("main_view", [_HoursMainView, _BasesMainView])
async def test_a_choice_of_several_reports_the_user_s_checks_not_the_code_s(
    driver: Driver, main_view: type[MainView]
) -> None:
    view = main_view()
    (field,) = [getattr(view, name) for name in ("hours", "bases") if hasattr(view, name)]
    labels = list(field.values)
    values = list(field.values.values())
    changes: list[list[object]] = []
    field.selected_changed.connect(changes.append)

    async with driver.open(view):
        async with driver.by_code():
            field.selected = [values[2]]
        assert (driver.checks(field), driver.check_all_state(field), changes) == (
            _checks(field, [values[2]]),
            None,
            [],
        )

        await driver.check(field, labels[1])
        assert (field.selected, driver.checks(field), changes) == (
            [values[1], values[2]],
            _checks(field, [values[1], values[2]]),
            [[values[1], values[2]]],
        )
        await driver.check(field, labels[2])  # unchecked
        assert (field.selected, driver.checks(field), changes[1:]) == (
            [values[1]],
            _checks(field, [values[1]]),
            [[values[1]]],
        )

        async with driver.by_code():
            field.selected = values  # once the user checked one
        assert (driver.checks(field), driver.check_all_state(field)) == (
            _checks(field, values),
            True,
        )
        async with driver.by_code():
            field.selected = [values[0]]  # the check-all box from checked to partly
        assert (driver.checks(field), driver.check_all_state(field), len(changes)) == (
            _checks(field, [values[0]]),
            None,
            2,
        )
        async with driver.by_code():
            field.selected = []
        assert (driver.checks(field), driver.check_all_state(field), len(changes)) == (
            _checks(field, []),
            False,
            2,
        )


@pytest.mark.asyncio
async def test_a_check_list_shows_the_code_s_choice_among_the_choices_its_search_shows(
    driver: Driver,
) -> None:
    view = _HoursMainView()
    hours = view.hours
    changes: list[list[int]] = []
    hours.selected_changed.connect(changes.append)

    async with driver.open(view):
        await driver.search(hours, "MORN")
        assert (hours.search, driver.checks(hours)) == (
            "MORN",
            [("Early morning", False), ("Morning", False)],
        )

        async with driver.by_code():
            hours.selected = [12]  # a choice that the search hides
        assert (driver.checks(hours), driver.check_all_state(hours)) == (
            [("Early morning", False), ("Morning", False)],
            False,
        )
        async with driver.by_code():
            hours.search = ""
        assert (driver.checks(hours), driver.check_all_state(hours), changes) == (
            _checks(hours, [12]),
            None,
            [],
        )


@pytest.mark.asyncio
async def test_a_tree_reports_the_user_s_selections_and_toggles_not_the_code_s(
    driver: Driver,
) -> None:
    view = _SiteMainView()
    site = view.site
    selections: list[tuple[str, ...]] = []
    toggles: list[tuple[tuple[str, ...], bool]] = []
    site.selection_changed.connect(selections.append)
    site.toggled.connect(lambda path, is_expanded: toggles.append((path, is_expanded)))

    async with driver.open(view):
        async with driver.by_code():
            site.expanded = [("Building B",)]  # Building A collapsed
            site.selected = ("Building B", "Floor 1")
        assert (driver.expanded_nodes(site), driver.selected_node(site)) == (
            [("Building B",)],
            ("Building B", "Floor 1"),
        )
        assert (selections, toggles) == ([], [])

        await driver.toggle_node(site, ("Building B", "Floor 1"))
        assert (site.expanded, driver.expanded_nodes(site), toggles) == (
            [("Building B",), ("Building B", "Floor 1")],
            [("Building B",), ("Building B", "Floor 1")],
            [(("Building B", "Floor 1"), True)],
        )
        await driver.select_node(site, ("Building B", "Floor 1", "Lobby"))
        assert (site.selected, driver.selected_node(site), selections) == (
            ("Building B", "Floor 1", "Lobby"),
            ("Building B", "Floor 1", "Lobby"),
            [("Building B", "Floor 1", "Lobby")],
        )

        async with driver.by_code():
            site.expanded = [("Building A",)]  # once the user expanded one: the others collapsed
            site.selected = ("Parking",)  # once the user selected one
        assert (driver.expanded_nodes(site), driver.selected_node(site)) == (
            [("Building A",)],
            ("Parking",),
        )
        assert (len(selections), len(toggles)) == (1, 1)

        async with driver.by_code():
            site.expanded = []
        assert (driver.expanded_nodes(site), driver.selected_node(site)) == ([], ("Parking",))
        assert (len(selections), len(toggles)) == (1, 1)
