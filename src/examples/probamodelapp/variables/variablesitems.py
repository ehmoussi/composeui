from composeui.items.core.itemsutils import ComboBoxDelegateProps, DelegateProps
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.tableview import TableView
from examples.probamodelapp.probamodelapp.model import Model

from typing import Any, List, Optional


class VariablesItems(AbstractTableItems[Model]):
    def __init__(self, model: Model) -> None:
        super().__init__(TableView(), model, title="Variables")
        self._titles = ["Name", "Distribution", "Id"]

    def get_row_from_id(self, rid: Any) -> int:
        return self._model.variables_query.get_row_index(rid)

    def get_id_from_row(self, row: int) -> Any:
        return self._model.variables_query.get_v_id(row)

    def get_nb_columns(self) -> int:
        return len(self._titles)

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self) -> int:
        return self._model.variables_query.count()

    def insert(self, row: int) -> Optional[int]:
        from examples.probamodelapp.variables.models import Variable

        self._model.variables_query.add("Variable", Variable.Distribution.Normal.name)
        return super().insert(row)

    def _remove_by_id(self, rid: Any) -> None:
        self._model.variables_query.remove(rid)

    def get_data_by_id(self, rid: Any, column: int) -> str:
        if column == 0:
            return self._model.variables_query.get_name(rid)
        elif column == 1:
            return self._model.variables_query.get_distribution(rid)
        elif column == 2:
            return str(self._model.variables_query.get_id(rid))
        return super().get_data_by_id(rid, column)

    def get_data_by_row_id(self, rid: Any) -> List[str]:
        return list(map(str, self._model.variables_query.get_row_data_by_id(rid)))

    def get_all_datas(self) -> List[List[str]]:
        return [
            [row[0], row[1], str(row[2])] for row in self._model.variables_query.get_data()
        ]

    def set_data(self, row: int, column: int, value: str) -> bool:
        if column == 0:
            self._model.variables_query.set_name(row, value)
        elif column == 1:
            self._model.variables_query.set_distribution(row, value)
        else:
            return False
        return True

    def get_delegate_props_by_id(
        self, column: int, *, rid: Optional[Any] = None
    ) -> Optional[DelegateProps]:
        from examples.probamodelapp.variables.models import Variable

        if column == 1:
            return ComboBoxDelegateProps(list(Variable.Distribution))
        return super().get_delegate_props_by_id(column, rid=rid)
