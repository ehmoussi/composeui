"""Tools to manipulate GEOM entities."""

from typing import Any, List, Tuple


def set_transparency(entry: str, value: float) -> None:
    r"""Set Transparency for the geom object."""
    import salome

    if salome.sg.hasDesktop():
        geom_gui = salome.ImportComponentGUI("GEOM")
        geom_gui.setTransparency(entry, value)


def find_geom_object(entry: str) -> Any:
    r"""Find a geom object from its entry."""
    import salome

    salome_object = salome.myStudy.FindObjectID(entry)
    if salome_object is None:
        return None
    return salome_object.GetObject()


def set_color_geom_object(entry: str, r: int, g: int, b: int) -> None:
    r"""set a color for a geom object."""
    import salome
    import SALOMEDS

    salome_object = salome.myStudy.FindObjectID(entry)
    salome_geom = salome_object.GetObject()
    salome_geom.SetColor(SALOMEDS.Color(r, g, b))


def remove_geom_object_from_study(entry: str) -> None:
    r"""Remove a geom object from the salome study, based on the object's entry."""
    import salome
    import salome.geom.geomtools

    geom_tools = salome.geom.geomtools.GeomStudyTools()
    if salome.sg.hasDesktop():
        geom_tools.eraseShapeByEntry(entry)
    geom_obj = geom_tools.removeFromStudy(entry)
    geom_obj.Destroy()


def find_in_place(geometry: Any, entry: str) -> Any:
    """Find a subshape of the given geometry corresponding to the given entry."""
    import salome
    import salome.geom

    geompy = salome.geom.geomBuilder.New()
    subshape = salome.myStudy.FindObjectID(entry).GetObject()
    return geompy.ShapesOp.GetInPlaceByHistory(geometry, subshape)


def find_subshapes_from(geometry: Any, entries: List[str]) -> List[str]:
    """Find the subshapes of the given from the given entries."""
    import salome.geom

    geompy = salome.geom.geomBuilder.New()
    return [
        entry
        for entry in entries
        if geompy.ShapesOp.GetSame(geometry, find_geom_object(entry)) is not None
    ]


def display_item(
    entry: str,
    display_mode: int = 1,
    color: Tuple[int, int, int] = (0, 0, 0),  # (236, 163, 255),
) -> None:
    import salome

    if salome.sg.hasDesktop():
        geom_gui = salome.ImportComponentGUI("GEOM")
        geom_gui.createAndDisplayFitAllGO(entry)
        geom_gui.setDisplayMode(entry, display_mode)
        geom_gui.setColor(entry, *color)
        salome.sg.updateObjBrowser()


def remove_item(entry: str, do_update: bool = True) -> None:
    """Remove the item corresponding to the given entry."""
    import salome
    from salome.kernel.services import IDToSObject

    if salome.sg.hasDesktop():
        geom_tools = salome.geom.geomtools.GeomStudyTools()
        geom_tools.eraseShapeByEntry(entry)
    editor = salome.kernel.studyedit.getStudyEditor()
    study_object = IDToSObject(entry)
    editor.removeItem(study_object, True)
    if do_update and salome.sg.hasDesktop():
        salome.sg.updateObjBrowser()


def remove_items(entries: str) -> None:
    """Remove the items corresponding to the given entry."""
    import salome

    for entry in entries:
        remove_item(entry, do_update=False)
    if salome.sg.hasDesktop():
        salome.sg.updateObjBrowser()


def display_name(entry: str) -> None:
    """Display the name of the given entry in the 3D GEOM view."""
    import salome

    if salome.sg.hasDesktop():
        geom_gui = salome.ImportComponentGUI("GEOM")
        geom_gui.setNameMode(entry, True)


def display_names(entries: List[str]) -> None:
    """Display the names of the given entries in the 3D GEOM view."""
    import salome

    if salome.sg.hasDesktop():
        geom_gui = salome.ImportComponentGUI("GEOM")
        for entry in entries:
            geom_gui.setNameMode(entry, True)


def hide_name(entry: str) -> None:
    """Display the name of the given entry in the 3D GEOM view."""
    import salome

    if salome.sg.hasDesktop():
        geom_gui = salome.ImportComponentGUI("GEOM")
        geom_gui.setNameMode(entry, False)


def hide_names(entries: List[str]) -> None:
    """Display the names of the given entries in the 3D GEOM view."""
    import salome

    if salome.sg.hasDesktop():
        geom_gui = salome.ImportComponentGUI("GEOM")
        for entry in entries:
            geom_gui.setNameMode(entry, False)


# def create_item(shape, name: str, component, parent_name: str = "") -> str:
#     editor = salome.kernel.studyedit.getStudyEditor()
#     shape.SetName(name)
#     ior = salome.orb.object_to_string(shape)
#     icon = None
#     if salome.sg.hasDesktop():
#         geom_gui = salome.ImportComponentGUI("GEOM")
#         icon = geom_gui.getShapeTypeIcon(ior)
#     if parent_name == "":
#         parent = component
#     else:
#         parent = editor.findOrCreateItem(component, parent_name)
#     item = editor.createItem(parent, name=name, IOR=ior, icon=icon)
#     return str(item.GetID())

# @contextmanager
# def display_preview(
#     shape,
#     component_name: str,
#     name: str = "tmp_shape",
#     display_mode: int = 1,
#     color: Tuple[int, int, int] = (236, 163, 255),
# ):
#     """Display a preview of the given shape."""
#     try:
#         entry = create_item(shape, name, component_name)
#         if entry != "":
#             display_item(entry, display_mode, color)
#             yield entry
#     finally:
#         if entry != "":
#             remove_item(entry)
