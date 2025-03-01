r"""Tools to display geometry entities in an OCC viewer."""

from typing import Sequence


def display_only_entities(entries: Sequence[str]) -> None:
    r"""Display only the given entities in the OCC viewer."""
    import salome

    if salome.sg.hasDesktop():
        hide_all_entities()
        for entry in entries:
            if entry != "":
                salome.sg.Display(entry)
        salome.sg.FitAll()


def display_entity(entry: str) -> None:
    r"""Display the given entity."""
    import salome

    if salome.sg.hasDesktop() and entry != "":
        salome.sg.Display(entry)
        salome.sg.FitAll()


def display_entities(entries: Sequence[str]) -> None:
    r"""Display the given entities."""
    import salome

    if salome.sg.hasDesktop():
        for entry in entries:
            salome.sg.Display(entry)
        salome.sg.FitAll()


def hide_entity(entry: str) -> None:
    r"""Hide the given entity."""
    import salome

    if salome.sg.hasDesktop() and entry != "":
        salome.sg.Erase(entry)
        salome.sg.UpdateView()


def hide_all_entities() -> None:
    """Hide all the entities."""
    import salome

    salome.sg.EraseAll()


def clear_selections() -> None:
    import salome

    if salome.sg.hasDesktop():
        salome.sg.ClearIObjects()


def add_to_selection(entries: Sequence[str]) -> None:
    import salome

    for entry in entries:
        salome.sg.AddIObject(entry)
