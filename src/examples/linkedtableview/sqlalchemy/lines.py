from composeui.items.core.itemsutils import DelegateProps, FloatDelegateProps
from composeui.items.linkedtable.linkedtableview import LinkedTableView
from composeui.items.table.abstracttableitems import AbstractTableItems
from composeui.items.table.tableview import TableView
from composeui.store.sqlalchemystore import SqlAlchemyDataBase, SqlAlchemyStore

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    and_,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.orm import Mapped, Session, relationship

import sys
from typing import TYPE_CHECKING, Any, Generator, List, Optional

if TYPE_CHECKING:
    from examples.linkedtableview.sqlalchemy.app import Model
    from examples.linkedtableview.sqlalchemy.example import ExampleMainView

if sys.version_info >= (3, 7):  # noqa: UP036
    from sqlalchemy.orm import mapped_column

    class Line(SqlAlchemyDataBase):
        __tablename__ = "line"

        l_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
        l_index: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
        l_name: Mapped[str] = mapped_column(String, nullable=False, default="line")
        points: Mapped[List["Point"]] = relationship(
            "Point", order_by="Point.p_index", back_populates="line", uselist=True
        )
        __table_args__ = (Index("ix_line_l_index", "l_index"),)

        def __repr__(self) -> str:
            return (
                f"<Line(l_id='{self.l_id}', l_index='{self.l_index}', l_name='{self.l_name}', "
                f"points={self.points})>"
            )

    class Point(SqlAlchemyDataBase):
        __tablename__ = "point"

        p_id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
        l_id: Mapped[int] = mapped_column(
            Integer, ForeignKey("line.l_id", ondelete="CASCADE"), nullable=False
        )
        p_index: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
        p_name: Mapped[str] = mapped_column(String, nullable=False, default="point")
        x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
        y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
        z: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

        line: Mapped[Line] = relationship("Line", back_populates="points", uselist=False)
        __table_args__ = (Index("ix_point_p_index", "p_index"),)

        def __repr__(self) -> str:
            return (
                f"<Point(l_id='{self.l_id}', p_id='{self.p_id}', p_index='{self.p_index}', "
                f"p_name='{self.p_name}', x='{self.x}', y='{self.y}', z='{self.z}')>"
            )

else:
    from sqlalchemy import Column

    class Line(SqlAlchemyDataBase):
        __tablename__ = "line"

        l_id: Mapped[int] = Column(Integer, primary_key=True, nullable=False)
        l_index: Mapped[int] = Column(Integer, nullable=False, default=-1)
        l_name: Mapped[str] = Column(String, nullable=False, default="line")
        points: Mapped[List["Point"]] = relationship(
            "Point", order_by="Point.p_index", back_populates="line", uselist=True
        )

        def __repr__(self) -> str:
            return (
                f"<Line(l_id='{self.l_id}', l_index='{self.l_index}', l_name='{self.l_name}', "
                f"points={self.points})>"
            )

    class Point(SqlAlchemyDataBase):
        __tablename__ = "point"

        p_id: Mapped[int] = Column(Integer, primary_key=True, nullable=False)
        l_id: Mapped[int] = Column(
            Integer, ForeignKey("line.l_id", ondelete="CASCADE"), nullable=False
        )
        p_index: Mapped[int] = Column(Integer, nullable=False, default=-1)
        p_name: Mapped[str] = Column(String, nullable=False, default="point")
        x: Mapped[float] = Column(Float, nullable=False, default=0.0)
        y: Mapped[float] = Column(Float, nullable=False, default=0.0)
        z: Mapped[float] = Column(Float, nullable=False, default=0.0)

        line: Mapped[Line] = relationship("Line", back_populates="points", uselist=False)

        def __repr__(self) -> str:
            return (
                f"<Point(l_id='{self.l_id}', p_id='{self.p_id}', p_index='{self.p_index}', "
                f"p_name='{self.p_name}', x='{self.x}', y='{self.y}', z='{self.z}')>"
            )


class LinesQuery:
    def __init__(self, data: SqlAlchemyStore) -> None:
        self._data = data

    def add_line(self) -> int:
        return self.insert_line(-1)

    def insert_line(self, index: int, name: str = "line") -> int:
        """Insert a line at the given index and return its id."""
        with self._data.get_session() as session, session.begin():
            if index < 0:
                nb_lines = session.execute(
                    select(func.count(Line.l_id)).select_from(Line)
                ).scalar_one()
                index = max(nb_lines + index + 1, 0)
            # to keep the lines sorted
            session.execute(
                update(Line).where(Line.l_index >= index).values(l_index=Line.l_index + 1)
            )
            new_line = Line(l_index=index, l_name=name)
            session.add(new_line)
            session.flush()
            new_id = new_line.l_id
            if name == "line":
                new_line.l_name = f"{new_line.l_name} {new_line.l_id}"
            session.commit()
            return new_id

    def remove_line(self, line_index: int) -> None:
        """Remove the line at the given index."""
        with self._data.get_session() as session, session.begin():
            session.execute(delete(Line).where(Line.l_index == line_index))
            session.flush()
            session.execute(
                update(Line).where(Line.l_index > line_index).values(l_index=Line.l_index - 1)
            )
            session.commit()

    def remove_all_lines(self) -> None:
        with self._data.get_session() as session, session.begin():
            session.execute(delete(Line))
            session.commit()

    def count_lines(self) -> int:
        """Get the number of lines."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(func.count(Line.l_id)).select_from(Line)
            ).scalar_one()

    # @contextlib.contextmanager
    # def get_line(self, line_index: int) -> Generator[Line, None, None]:
    #     with self._data.get_session() as session, session.begin():
    #         line = session.scalar(select(Line).where(Line.l_index == line_index))
    #         if line is not None:
    #             yield line
    #         else:
    #             msg = f"No line at the given index: {line_index}."
    #             raise IndexError(msg)

    def get_line_id(self, line_index: int) -> int:
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Line.l_id).where(Line.l_index == line_index)
            ).scalar_one()

    def _get_line_id(self, line_index: int, session: Session) -> int:
        return session.execute(
            select(Line.l_id).where(Line.l_index == line_index)
        ).scalar_one()

    def get_line_name(self, line_index: int) -> str:
        """Get the name of the line at the given index."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Line.l_name).where(Line.l_index == line_index)
            ).scalar_one()

    def set_line_name(self, line_index: int, name: str) -> None:
        """Set the name of the line at the given index."""
        with self._data.get_session() as session, session.begin():
            session.execute(update(Line).where(Line.l_index == line_index).values(l_name=name))
            session.commit()

    def add_point(self, line_index: int) -> int:
        return self.insert_point(line_index, -1)

    def insert_point(
        self,
        line_index: int,
        index: int,
        name: str = "point",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ) -> int:
        """Insert a point at the given index and return its id."""
        if index < 0:
            nb_points = self.count_points(line_index)
            index = max(nb_points + index + 1, 0)
        with self._data.get_session() as session, session.begin():
            line_id = self._get_line_id(line_index, session)
            # to keep the points sorted
            session.execute(
                update(Point)
                .where(and_(Point.p_index >= index, Point.l_id == line_id))
                .values(p_index=Point.p_index + 1)
            )
            new_point = Point(l_id=line_id, p_index=index, p_name=name, x=x, y=y, z=z)
            session.add(new_point)
            session.flush()
            new_id = new_point.p_id
            if name == "point":
                new_point.p_name = f"{name} {new_point.p_id}"
            session.commit()
        return new_id

    def remove_point(self, line_index: int, index: int) -> None:
        """Remove the point at the given index."""
        with self._data.get_session() as session, session.begin():
            l_id = self._get_line_id(line_index, session)
            session.execute(
                delete(Point).where(and_(Point.p_index == index, Point.l_id == l_id))
            )
            session.execute(
                update(Point).where(Point.p_index >= index).values(p_index=Point.p_index - 1)
            )
            session.commit()

    def count_points(self, line_index: int) -> int:
        """Get the number of points."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(func.count("*"))
                .select_from(Point)
                .join(Line, Line.l_id == Point.l_id)
                .where(Line.l_index == line_index)
            ).scalar_one()

    def get_point_id(self, line_index: int, index: int) -> int:
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Point.p_id)
                .join(Line, Point.l_id == Line.l_id)
                .where(and_(Line.l_index == line_index, Point.p_index == index))
            ).scalar_one()

    def get_point_name(self, line_index: int, index: int) -> str:
        """Get the name of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Point.p_name)
                .join(Line, Point.l_id == Line.l_id)
                .where(and_(Line.l_index == line_index, Point.p_index == index))
            ).scalar_one()

    def set_point_name(self, line_index: int, index: int, name: str) -> None:
        """Set the name of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            l_id = self._get_line_id(line_index, session)
            session.execute(
                update(Point)
                .values(p_name=name)
                .where(and_(Point.l_id == l_id, Point.p_index == index))
            )
            session.commit()

    def get_x(self, line_index: int, index: int) -> float:
        """Get the x coordinate of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Point.x)
                .join(Line, Point.l_id == Line.l_id)
                .where(and_(Line.l_index == line_index, Point.p_index == index))
            ).scalar_one()

    def set_x(self, line_index: int, index: int, x: float) -> None:
        """Set the x coordinate of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            l_id = self._get_line_id(line_index, session)
            session.execute(
                update(Point)
                .values(x=x)
                .where(and_(Point.l_id == l_id, Point.p_index == index))
            )
            session.commit()

    def get_y(self, line_index: int, index: int) -> float:
        """Get the y coordinate of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Point.y)
                .join(Line, Point.l_id == Line.l_id)
                .where(and_(Line.l_index == line_index, Point.p_index == index))
            ).scalar_one()

    def set_y(self, line_index: int, index: int, y: float) -> None:
        """Set the y coordinate of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            l_id = self._get_line_id(line_index, session)
            session.execute(
                update(Point)
                .values(y=y)
                .where(and_(Point.l_id == l_id, Point.p_index == index))
            )
            session.commit()

    def get_z(self, line_index: int, index: int) -> float:
        """Get the z coordinate of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            return session.execute(
                select(Point.z)
                .join(Line, Point.l_id == Line.l_id)
                .where(and_(Line.l_index == line_index, Point.p_index == index))
            ).scalar_one()

    def set_z(self, line_index: int, index: int, z: float) -> None:
        """Set the z coordinate of the point at the given index."""
        with self._data.get_session() as session, session.begin():
            l_id = self._get_line_id(line_index, session)
            session.execute(
                update(Point)
                .values(z=z)
                .where(and_(Point.l_id == l_id, Point.p_index == index))
            )
            session.commit()


class LinesItems(AbstractTableItems["Model"]):
    def __init__(self, view: TableView["LinesItems"], model: "Model") -> None:
        super().__init__(view, model)
        self._titles = ["Name", "Id"]
        self._cached_data: List[List[str]] = []

    def get_cached_data(self) -> Optional[List[List[str]]]:
        return self._cached_data

    def update_cache(self) -> None:
        self._cached_data = self.get_all_datas()

    def get_nb_columns(self) -> int:
        if self._model.is_debug:
            return len(self._titles)
        else:
            return len(self._titles) - 1

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self) -> int:
        return self._model.lines_query.count_lines()

    def insert(self, row: int) -> Optional[int]:
        self._model.lines_query.insert_line(row)
        self.update_cache()
        return row

    def _remove_by_id(self, rid: int) -> None:
        row = self.get_row_from_id(rid)
        self._model.lines_query.remove_line(row)
        self.update_cache()

    def remove_all(self) -> None:
        self._model.lines_query.remove_all_lines()

    def get_data(self, row: int, column: int) -> str:
        if column == 0:
            return self._model.lines_query.get_line_name(row)
        elif column == 1:
            return str(self._model.lines_query.get_line_id(row))
        return ""

    def get_data_by_id(self, rid: Any, column: int) -> str:
        return self.get_data(self.get_row_from_id(rid), column)

    def is_editable(self, row: int, column: int) -> bool:
        return column == 0

    def set_data(self, row: int, column: int, value: str) -> bool:
        if column == 0:
            self._model.lines_query.set_line_name(row, str(value))
            self.update_cache()
            return True
        return False


class PointsItems(AbstractTableItems["Model"]):
    def __init__(self, view: TableView["PointsItems"], model: "Model") -> None:
        super().__init__(view, model)
        self._titles = ["Name", "X", "Y", "Z", "Id"]
        self._cached_data: List[List[str]] = []

    def get_cached_data(self) -> List[List[str]] | None:
        return self._cached_data

    def update_cache(self) -> None:
        self._cached_data = self.get_all_datas()

    def get_lines_items(self) -> LinesItems:
        assert len(self._dependencies) == 1, "LinesItems is missing as a dependency"
        assert isinstance(
            self._dependencies[0], LinesItems
        ), "The dependency is not of type LinesItems"
        return self._dependencies[0]

    def get_current_line_index(self) -> int:
        if len(self._dependencies) > 0 and isinstance(self._dependencies[0], LinesItems):
            selected_rows = self._dependencies[0].get_selected_rows()
            if len(selected_rows) != 0:
                return selected_rows[-1]
        return -1

    def can_enable_table(self) -> bool:
        return self.get_current_line_index() != -1

    def get_exported_column_names(self) -> List[str]:
        return self._titles[:4]

    def get_nb_columns(self) -> int:
        if self._model.is_debug:
            return len(self._titles)
        else:
            return len(self._titles) - 1

    def get_column_title(self, column: int) -> str:
        return self._titles[column]

    def get_nb_rows(self) -> int:
        line_index = self.get_current_line_index()
        if line_index != -1:
            return self._model.lines_query.count_points(line_index)
        else:
            return 0

    def insert(self, row: int) -> Optional[int]:
        self._model.lines_query.insert_point(self.get_current_line_index(), row)
        self.update_cache()
        return row

    def _remove_by_id(self, rid: Any) -> None:
        row = self.get_row_from_id(rid)
        self._model.lines_query.remove_point(self.get_current_line_index(), row)
        self.update_cache()

    def get_data(self, row: int, column: int) -> str:
        line_row = self.get_current_line_index()
        if column == 0:
            return self._model.lines_query.get_point_name(line_row, row)
        elif 1 <= column <= 3:
            if column == 1:
                value = self._model.lines_query.get_x(line_row, row)
            elif column == 2:
                value = self._model.lines_query.get_y(line_row, row)
            else:
                value = self._model.lines_query.get_z(line_row, row)
            return self.display_float(value, 2)
        elif column == 4:
            return str(self._model.lines_query.get_point_id(line_row, row))
        return super().get_data(row, column)

    def get_data_by_id(self, rid: Any, column: int) -> str:
        return self.get_data(self.get_row_from_id(rid), column)

    def get_edit_data(self, row: int, column: int) -> Any:
        line_row = self.get_current_line_index()
        if column == 1:
            return self._model.lines_query.get_x(line_row, row)
        elif column == 2:
            return self._model.lines_query.get_y(line_row, row)
        elif column == 3:
            return self._model.lines_query.get_z(line_row, row)
        return super().get_edit_data(row, column)

    def is_editable(self, row: int, column: int) -> bool:
        return column < 4

    def set_data(self, row: int, column: int, value: str) -> bool:
        line_row = self.get_current_line_index()
        if column == 0:
            self._model.lines_query.set_point_name(line_row, row, str(value))
            self.update_cache()
            return True
        elif 1 <= column <= 3:
            float_value = self.to_float_value(value, 0.0)
            if float_value is not None:
                if column == 1:
                    self._model.lines_query.set_x(line_row, row, float_value)
                elif column == 2:
                    self._model.lines_query.set_y(line_row, row, float_value)
                elif column == 3:
                    self._model.lines_query.set_z(line_row, row, float_value)
                self.update_cache()
                return True
        return False

    def get_delegate_props(
        self, column: int, *, row: Optional[int] = None
    ) -> Optional[DelegateProps]:
        if 1 <= column <= 3:
            return FloatDelegateProps()
        return super().get_delegate_props(column, row=row)

    def get_title(self) -> str:
        line_index = self.get_current_line_index()
        if line_index != -1:
            return self._model.lines_query.get_line_name(line_index)
        else:
            return ""

    def iter_trigger_dependencies(self) -> Generator[None, None, None]:
        lines_items = self.get_lines_items()
        for row in range(lines_items.get_nb_rows()):
            lines_items.set_selected_rows([row])
            yield


def initialize_lines(
    view: LinkedTableView[LinesItems, PointsItems],
    main_view: "ExampleMainView",
    model: "Model",
) -> None:
    view.has_import = True
    view.has_export = True
    view.master_table.items = LinesItems(view.master_table, model)
    view.detail_table.items = PointsItems(view.detail_table, model)
    view.detail_table.items.add_dependency(view.master_table.items)
