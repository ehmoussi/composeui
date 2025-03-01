"""Common types."""

import typing
from typing import Any, TypeVar, Union

if typing.TYPE_CHECKING:
    from composeui.form.abstractformitems import AbstractFormItems
    from composeui.form.formview import FormView
    from composeui.items.table.abstracttableitems import AbstractTableItems
    from composeui.items.table.tableview import TableView
    from composeui.items.tree.abstracttreeitems import AbstractTreeItems
    from composeui.items.tree.treeview import TreeView
    from composeui.mainview.views.mainview import MainView
    from composeui.model.basemodel import BaseModel


AnyModel = TypeVar("AnyModel", bound="BaseModel")
AnyTableItems = TypeVar("AnyTableItems", bound="AbstractTableItems[Any]")
AnyTreeItems = TypeVar("AnyTreeItems", bound="AbstractTreeItems[Any]")
AnyItems = TypeVar("AnyItems", bound="Union[AbstractTableItems[Any], AbstractTreeItems[Any]]")
AnyMasterTableItems = TypeVar("AnyMasterTableItems", bound="AbstractTableItems[Any]")
AnyDetailTableItems = TypeVar("AnyDetailTableItems", bound="AbstractTableItems[Any]")
AnyItemsView = Union["TreeView[Any]", "TableView[Any]"]

AnyMainView = TypeVar("AnyMainView", bound="MainView")
AnyFormView = TypeVar("AnyFormView", bound="FormView[Any]")
AnyFormItems = TypeVar("AnyFormItems", bound="AbstractFormItems[Any, Any]")

try:
    import pydantic
except (ImportError, ModuleNotFoundError):
    pass
else:
    AnyPydanticBaseModel = TypeVar("AnyPydanticBaseModel", bound=pydantic.BaseModel)

try:
    import msgspec
except (ImportError, ModuleNotFoundError):
    pass
else:
    AnyMsgspecStruct = TypeVar("AnyMsgspecStruct", bound=msgspec.Struct)


try:
    from mashumaro.mixins.json import DataClassJSONMixin
except (ImportError, ModuleNotFoundError):
    pass
else:
    AnyMashumaroDataClass = TypeVar("AnyMashumaroDataClass", bound=DataClassJSONMixin)
