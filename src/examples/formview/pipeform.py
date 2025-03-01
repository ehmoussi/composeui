from composeui import form
from composeui.commontypes import AnyFormItems
from composeui.form.abstractformitems import AbstractFormItems
from composeui.form.formview import (
    FormView,
    GroupBoxFormView,
    LabelDoubleLineEditView,
    LabelLineEditView,
    LabelRadioButtonGroupView,
    LabelSelectFileView,
)
from composeui.store.sqlitestore import SqliteStore

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, TypeVar

if TYPE_CHECKING:
    from examples.formview.app import Model
    from examples.formview.example import ExampleMainView


class EdgeType(Enum):
    Normal = 0
    Chamfer = 1
    Fillet = 2

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(eq=False)
class ChamferDimensionView(GroupBoxFormView[AnyFormItems]):
    height: LabelDoubleLineEditView[AnyFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView[AnyFormItems]
    )
    width: LabelDoubleLineEditView[AnyFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class FilletDimensionView(GroupBoxFormView[AnyFormItems]):
    radius: LabelDoubleLineEditView[AnyFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class PipeDimensionView(GroupBoxFormView[AnyFormItems]):
    radius: LabelDoubleLineEditView[AnyFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView[AnyFormItems]
    )
    width: LabelDoubleLineEditView[AnyFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView[AnyFormItems]
    )
    half_length: LabelDoubleLineEditView[AnyFormItems] = field(
        init=False, repr=False, default_factory=LabelDoubleLineEditView[AnyFormItems]
    )


@dataclass(eq=False)
class PipeFormView(GroupBoxFormView["PipeFormItems"]):
    name: LabelLineEditView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=LabelLineEditView["PipeFormItems"]
    )
    p_id: LabelLineEditView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=LabelLineEditView["PipeFormItems"]
    )
    export: LabelSelectFileView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=LabelSelectFileView["PipeFormItems"]
    )
    main: PipeDimensionView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=PipeDimensionView["PipeFormItems"]
    )
    incident: PipeDimensionView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=PipeDimensionView["PipeFormItems"]
    )
    # edge_type: ILabelComboBoxView["PipeFormItems"] = field(
    #     init=False, repr=False, default_factory=ILabelComboBoxView["PipeFormItems"]
    # )
    edge_type: LabelRadioButtonGroupView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=LabelRadioButtonGroupView["PipeFormItems"]
    )
    chamfer: ChamferDimensionView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=ChamferDimensionView["PipeFormItems"]
    )
    fillet: FilletDimensionView["PipeFormItems"] = field(
        init=False, repr=False, default_factory=FilletDimensionView["PipeFormItems"]
    )


def initialize_pipe(
    view: PipeFormView,
    main_view: "ExampleMainView",
    model: "Model",
    is_visible: bool = False,
) -> None:
    form.initialize_form_view(view, PipeFormItems(model, view))
    view.is_visible = is_visible
    view.title = "Pipe"
    view.export.field_view.mode = "save_file"
    initialize_main_pipe(view.main)
    initialize_incident_pipe(view.incident)
    initialize_chamfer(view.chamfer)
    initialize_fillet(view.fillet)
    # the edge type selection modify the visibility of the chamfer and fillet forms
    view.edge_type.field_view.dependencies.extend([view.chamfer, view.fillet])


def initialize_main_pipe(view: PipeDimensionView[Any]) -> None:
    view.title = "Main Pipe"
    view.radius.field_view.minimum = 0.0
    view.width.field_view.minimum = 0.0
    view.half_length.field_view.minimum = 0.0


def initialize_incident_pipe(view: PipeDimensionView[Any]) -> None:
    view.title = "Incident Pipe"
    view.radius.field_view.minimum = 0.0
    view.width.field_view.minimum = 0.0
    view.half_length.field_view.minimum = 0.0


def initialize_chamfer(view: ChamferDimensionView[Any]) -> None:
    view.title = "Chamfer"
    view.height.field_view.minimum = 0.0
    view.width.field_view.minimum = 0.0


def initialize_fillet(view: FilletDimensionView[Any]) -> None:
    view.title = "Fillet"
    view.radius.field_view.minimum = 0.0


V = TypeVar("V", bound=FormView[Any])


class AbstractPipeFormItems(AbstractFormItems["Model", V]):
    def __init__(self, model: "Model", view: V) -> None:
        super().__init__(model, view)
        self._labels: Dict[Tuple[str, ...], str] = {
            ("name",): "Name",
            ("p_id",): "Id",
            ("export",): "Export File",
            ("main", "radius"): "Radius",
            ("main", "width"): "Width",
            ("main", "half_length"): "Half Length",
            ("incident", "radius"): "Radius",
            ("incident", "width"): "Width",
            ("incident", "half_length"): "Half Length",
            ("chamfer", "width"): "Width",
            ("chamfer", "height"): "Height",
            ("fillet", "radius"): "Radius",
            ("edge_type",): "Edge Type",
        }

    @property
    def query(self) -> "PipeQuery":
        return self._model.pipe_query

    def get_label(self, field: str, parent_fields: Tuple[str, ...] = ()) -> str:
        return self._labels.get((*parent_fields, field), "")

    def is_enabled(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        if len(parent_fields) == 0 and field == "p_id":
            return False
        return super().is_enabled(field, parent_fields)

    def get_value(self, field: str, parent_fields: Tuple[str, ...] = ()) -> Any:
        if len(parent_fields) == 0:
            if field == "name":
                return self.query.get_name()
            elif field == "p_id":
                return self.query.p_id
            elif field == "export":
                value = self.query.get_export_path()
                if value is None:
                    return ""
                return str(value)
            elif field == "edge_type":
                return self.query.get_edge_type().value
        elif parent_fields[0] == "main":
            if field == "radius":
                return self.query.get_main_radius()
            elif field == "width":
                return self.query.get_main_width()
            elif field == "half_length":
                return self.query.get_main_half_length()
        elif parent_fields[0] == "incident":
            if field == "radius":
                return self.query.get_incident_radius()
            elif field == "width":
                return self.query.get_incident_width()
            elif field == "half_length":
                return self.query.get_incident_half_length()
        elif parent_fields[0] == "chamfer":
            if field == "height":
                return self.query.get_chamfer_height()
            elif field == "width":
                return self.query.get_chamfer_width()
        elif parent_fields[0] == "fillet" and field == "radius":
            return self.query.get_fillet_radius()
        return super().get_value(field, parent_fields)

    def set_value(self, field: str, value: Any, parent_fields: Tuple[str, ...] = ()) -> bool:
        if len(parent_fields) == 0:
            if field == "name":
                self.query.set_name(str(value))
                return True
            elif field == "export":
                path_value: Optional[Path]
                if value is None or value == "":
                    path_value = None
                else:
                    path_value = Path(str(value))
                self.query.set_export_path(path_value)
                return True
        float_value = self.to_float_value(value, 0.0, min_value=0.0)
        if float_value is not None:
            if len(parent_fields) == 0:
                if field == "edge_type":
                    self.query.set_edge_type(EdgeType(int(float_value)))
            elif parent_fields[0] == "main":
                if field == "radius":
                    self.query.set_main_radius(float_value)
                elif field == "width":
                    self.query.set_main_width(float_value)
                elif field == "half_length":
                    self.query.set_main_half_length(float_value)
            elif parent_fields[0] == "incident":
                if field == "radius":
                    self.query.set_incident_radius(float_value)
                elif field == "width":
                    self.query.set_incident_width(float_value)
                elif field == "half_length":
                    self.query.set_incident_half_length(float_value)
            elif parent_fields[0] == "chamfer":
                if field == "height":
                    self.query.set_chamfer_height(float_value)
                elif field == "width":
                    self.query.set_chamfer_width(float_value)
            elif parent_fields[0] == "fillet":
                if field == "radius":
                    self.query.set_fillet_radius(float_value)
            else:
                return super().set_value(field, value, parent_fields)
            return True
        return False

    def acceptable_values(
        self, field: str, parent_fields: Tuple[str, ...] = ()
    ) -> Optional[Sequence[Any]]:
        if field == "edge_type":
            return list(range(3))
        return super().acceptable_values(field, parent_fields)

    def acceptable_displayed_values(
        self, field: str, parent_fields: Tuple[str, ...] = ()
    ) -> Optional[Sequence[str]]:
        if field == "edge_type":
            return [e_type.name for e_type in EdgeType]
        return super().acceptable_displayed_values(field, parent_fields)


class PipeFormItems(AbstractPipeFormItems[PipeFormView]):
    def is_visible(self, field: str, parent_fields: Tuple[str, ...] = ()) -> bool:
        if len(parent_fields) == 0:
            if field in ("chamfer", "fillet"):
                return str(self.query.get_edge_type()) == field
            if field == "p_id":
                return self._model.is_debug
        return super().is_visible(field, parent_fields)

    def get_error_messages(self, field: str, parent_fields: Tuple[str, ...] = ()) -> List[str]:
        infos = []
        if len(parent_fields) == 0 and field == "name" and self.query.get_name() == "":
            infos.append("A name is mandatory")
        elif len(parent_fields) == 1:
            main_radius = self.query.get_main_radius()
            if (parent_fields[0] == "main" and field in ("radius", "width")) or (
                parent_fields[0] == "incident" and field == "half_length"
            ):
                main_width = self.query.get_main_width()
                incident_half_length = self.query.get_incident_half_length()
                if main_radius + main_width > incident_half_length:
                    infos.append(
                        "The sum of the radius and width of the main pipe "
                        "can't be greater than the half length of the incident pipe "
                        f"({main_radius} + {main_width} > {incident_half_length})"
                    )
            if field == "radius":
                incident_radius = self.query.get_incident_radius()
                if incident_radius > main_radius:
                    infos.append(
                        "The incident radius cant'be greater than the main radius "
                        f"({incident_radius} > {main_radius})"
                    )
        return infos


class PipeQuery:
    def __init__(self, data: SqliteStore, p_id: int) -> None:
        self._data = data
        self._p_id = p_id
        self._insert_pipe_or_ignore()

    @property
    def p_id(self) -> int:
        return self._p_id

    def _get_value(self, column: str) -> Any:
        self._insert_pipe_or_ignore()
        with self._data.get_connection() as db_conn:
            result = db_conn.execute(
                f"SELECT {column} FROM pipe WHERE p_id=:p_id",
                {"p_id": self._p_id},
            ).fetchone()
        if result is not None:
            return result[column]
        else:
            raise ValueError("Unknown Error")

    def get_name(self) -> str:
        return str(self._get_value("p_name"))

    def get_export_path(self) -> Optional[Path]:
        export_path = self._get_value("export_path")
        if export_path is None:
            return None
        return Path(export_path)

    def get_main_radius(self) -> float:
        return float(self._get_value("main_radius"))

    def get_main_width(self) -> float:
        return float(self._get_value("main_width"))

    def get_main_half_length(self) -> float:
        return float(self._get_value("main_half_length"))

    def get_incident_radius(self) -> float:
        return float(self._get_value("incident_radius"))

    def get_incident_width(self) -> float:
        return float(self._get_value("incident_width"))

    def get_incident_half_length(self) -> float:
        return float(self._get_value("incident_half_length"))

    def get_edge_type(self) -> EdgeType:
        return EdgeType(self._get_value("edge_type"))

    def get_chamfer_width(self) -> float:
        return float(self._get_value("chamfer_width"))

    def get_chamfer_height(self) -> float:
        return float(self._get_value("chamfer_height"))

    def get_fillet_radius(self) -> float:
        return float(self._get_value("fillet_radius"))

    def set_name(self, name: str) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET p_name=:p_name WHERE p_id=:p_id",
                {"p_name": name, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_export_path(self, path: Optional[Path]) -> None:
        if path is None:
            export_path = None
        else:
            export_path = str(path)
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET export_path=:export_path WHERE p_id=:p_id",
                {"export_path": export_path, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_main_radius(self, main_radius: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET main_radius=:main_radius WHERE p_id=:p_id",
                {"main_radius": main_radius, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_main_width(self, main_width: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET main_width=:main_width WHERE p_id=:p_id",
                {"main_width": main_width, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_main_half_length(self, main_half_length: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET main_half_length=:main_half_length WHERE p_id=:p_id",
                {"main_half_length": main_half_length, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_incident_radius(self, incident_radius: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET incident_radius=:incident_radius WHERE p_id=:p_id",
                {"incident_radius": incident_radius, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_incident_width(self, incident_width: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET incident_width=:incident_width WHERE p_id=:p_id",
                {"incident_width": incident_width, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_incident_half_length(self, incident_half_length: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET incident_half_length=:incident_half_length WHERE p_id=:p_id",
                {"incident_half_length": incident_half_length, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_edge_type(self, edge_type: EdgeType) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET edge_type=:edge_type WHERE p_id=:p_id",
                {"edge_type": edge_type.value, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_chamfer_height(self, chamfer_height: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET chamfer_height=:chamfer_height WHERE p_id=:p_id",
                {"chamfer_height": chamfer_height, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_chamfer_width(self, chamfer_width: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET chamfer_width=:chamfer_width WHERE p_id=:p_id",
                {"chamfer_width": chamfer_width, "p_id": self._p_id},
            )
            db_conn.commit()

    def set_fillet_radius(self, fillet_radius: float) -> None:
        with self._data.get_connection() as db_conn:
            db_conn.execute(
                "UPDATE pipe SET fillet_radius=:fillet_radius WHERE p_id=:p_id",
                {"fillet_radius": fillet_radius, "p_id": self._p_id},
            )
            db_conn.commit()

    def _count(self) -> int:
        with self._data.get_connection() as db_conn:
            result = db_conn.execute("SELECT COUNT(*) FROM pipe").fetchone()
        if result is not None:
            return int(result[0])
        else:
            return 0

    def _insert_pipe_or_ignore(self) -> None:
        if self._count() == 0:
            with self._data.get_connection() as db_conn:
                db_conn.execute("INSERT INTO pipe DEFAULT VALUES")
                db_conn.execute("INSERT INTO pipe DEFAULT VALUES")
                db_conn.commit()
