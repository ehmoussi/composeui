"""Tools to manipulate the salome study."""

import salome

from typing import Iterator


def rename_salome_object(entry: str, name: str) -> None:
    r"""Rename a salome object."""
    salome_object = salome.myStudy.FindObjectID(entry)
    if salome_object is not None and salome_object.GetName() != name:
        editor = salome.kernel.studyedit.getStudyEditor()
        editor.setName(salome_object, name)


def find_object_name(entry: str) -> str:
    """Find the object name."""
    salome_object = salome.myStudy.FindObjectID(entry)
    if salome_object is not None:
        return str(salome_object.GetName())
    else:
        return ""


def find_object_parent_entry(entry: str) -> str:
    """Find the object parent entry."""
    salome_object = salome.myStudy.FindObjectID(entry)
    if salome_object is not None:
        return str(salome_object.GetFather().GetID())
    else:
        return ""


def has_geom_object_with_entry(entry: str) -> bool:
    """Check if the given entry correspond to a geometry object."""
    geom_tools = salome.geom.geomtools.GeomStudyTools()
    try:
        geom_tools.getGeomObjectFromEntry(entry)
    except AttributeError:
        return False
    else:
        return True


def iter_object_children_entries(
    entry: str, exclude_nameless_objects: bool = False
) -> Iterator[str]:
    r"""Iterate over the children of the given entry.

    - Excluding nameless objects can be used to exclude "red child" corresponding to the
    dependance of the object
    """
    salome_object = salome.myStudy.FindObjectID(entry)
    if salome_object is not None:
        object_iterator = salome.myStudy.NewChildIterator(salome_object)
        while object_iterator.More():
            salome_child_object = object_iterator.Value()
            if salome_child_object is not None and (
                (not exclude_nameless_objects) or (salome_child_object.GetName() != "")
            ):
                yield str(salome_child_object.GetID())
            object_iterator.Next()


# Don't work because it needs a component
# def find_or_create_component(name: str, component_id: int, is_visible: bool = True):
#     component = salome.myStudy.FindComponent(name)
#     if component is None:
#         builder = salome.myStudy.NewBuilder()
#         component = builder.NewComponent(name)
#         attr = builder.FindOrCreateAttribute(component, "AttributeName")
#         attr.SetValue(name)
#         attr = builder.FindOrCreateAttribute(component, "AttributePixMap")
#         attr.SetPixMap(f"{name}.png")
#         attr = builder.FindOrCreateAttribute(component, "AttributeLocalID")
#         attr.SetValue(component_id)
#         if not is_visible and salome.sg.hasDesktop():
#             salome.sg.updateObjBrowser()
#             helper.hide_row_by_entry(component.GetID())
#     return component
