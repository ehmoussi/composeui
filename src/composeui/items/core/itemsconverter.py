"""Convert items of a tree in multiple formats."""

from composeui.commontypes import AnyTreeItems

from typing_extensions import OrderedDict

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Generator, Generic, List, Tuple

try:
    import pandas as pd
except (ModuleNotFoundError, ImportError):
    _HAS_PANDAS = False
else:
    _HAS_PANDAS = True

try:
    import markdown
    from markdown.extensions.toc import TocExtension
except (ModuleNotFoundError, ImportError):
    _HAS_MARKDOWN = False
else:
    _HAS_MARKDOWN = True


class ItemsConverter(Generic[AnyTreeItems]):
    """Convert the items of a tree to a dataframe/markdown/html."""

    def __init__(self, items: AnyTreeItems) -> None:
        self._items: AnyTreeItems = items

    def to_dataframe(
        self,
        parent_rows: Tuple[int, ...] = (),
        dependencies_selected_items: Tuple[OrderedDict[Tuple[int, ...], List[int]], ...] = (),
    ) -> "pd.DataFrame":
        r"""Convert the tree with the given indices to a pandas dataframe."""
        with self._switch_to_fake_selected_items(dependencies_selected_items):
            return self._to_dataframe(parent_rows)

    def to_flatten_dataframe(
        self,
        parent_rows: Tuple[int, ...] = (),
        dependencies_selected_items: Tuple[OrderedDict[Tuple[int, ...], List[int]], ...] = (),
    ) -> "pd.DataFrame":
        if not _HAS_PANDAS:
            raise ValueError("Can't convert the table/tree without pandas installed.")
        with self._switch_to_fake_selected_items(dependencies_selected_items):
            data, columns = self._flatten_tree(parent_rows)
            return pd.DataFrame(data=data, columns=columns)

    def to_dataframes(self) -> List["pd.DataFrame"]:
        r"""Convert all the possible trees pandas dataframes."""
        return list(self.iter_dataframes())

    def to_markdown(self, global_title: str = "", marker_level: int = 1) -> str:
        r"""Convert the tree to a markdown."""
        md_text = ""
        md_text += self._to_markdown(global_title, marker_level=marker_level)
        if self._items.depth == 1:
            for row in range(self._items.get_nb_rows()):
                md_text += self._to_markdown(
                    global_title=self._items.get_data(row, 0),
                    parent_rows=(row,),
                    marker_level=(marker_level + 1),
                )
        return md_text

    def to_html_snippet(self, global_title: str = "") -> str:
        r"""Convert the tree to an html snippet with only the table."""
        if _HAS_MARKDOWN:
            return str(
                markdown.markdown(
                    self.to_markdown(global_title),
                    extensions=[
                        "markdown.extensions.extra",
                        TocExtension(
                            title="Table of Contents",
                            toc_depth="1-1",
                            # anchorlink=True,
                        ),
                    ],
                )
            )
        else:
            raise ValueError("markdown dependency is missing.")

    def to_html(self, global_title: str = "") -> str:
        """Convert the table to html."""
        html_table = self.to_html_snippet(global_title)
        html_header_file = Path(Path(__file__).parent, "..", "templates", "header.html")
        html_footer_file = Path(Path(__file__).parent, "..", "templates", "footer.html")
        return html_header_file.read_text() + html_table + html_footer_file.read_text()

    def _to_markdown(
        self,
        global_title: str,
        parent_rows: Tuple[int, ...] = (),
        marker_level: int = 1,
    ) -> str:
        """Convert the tree to a markdown."""
        global_marker = "#" * marker_level
        title_marker = "#" * (marker_level + 1)
        header = "" if global_title == "" else f"{global_marker} {global_title}\n"
        body = ""
        with self._switch_to_fake_selected_items():
            for _ in self._items.iter_trigger_dependencies():
                title = self._items.get_title()
                infos = self._items.get_infos()
                dataframe = self._to_dataframe(parent_rows)
                if title != "":
                    body += f"{title_marker} {title}\n"
                if len(infos) > 0:
                    body += "\n".join(
                        f"- **{infos_type}**: {infos_data}"
                        for infos_type, infos_data in infos.items()
                    )
                    body += "\n\n"
                body += dataframe.to_markdown() + "\n\n"
        footer = "\n"
        return header + body + footer

    def _to_dataframe(self, parent_rows: Tuple[int, ...] = ()) -> "pd.DataFrame":
        """Convert the tree with the current indices to a pandas dataframe."""
        if not _HAS_PANDAS:
            raise ValueError("Can't convert the table/tree without pandas installed.")
        nb_rows = self._items.get_nb_rows(parent_rows)
        if nb_rows == 0:
            return pd.DataFrame()
        else:
            column_indices = self._items.get_exported_column_indices(parent_rows)
            if self._items.get_nb_columns() == 1 or len(column_indices) == 1:
                data = [
                    self._items.get_edit_data(row, column_indices[0], parent_rows)
                    for row in range(nb_rows)
                ]
            else:
                data = [
                    [
                        self._items.get_edit_data(row, column, parent_rows)
                        for column in column_indices
                    ]
                    for row in range(nb_rows)
                ]
            column_names = self._items.get_exported_column_names(parent_rows)
            if len(column_indices) != len(column_names):
                if hasattr(self._items, "_table_items"):
                    items_name = type(self._items._table_items).__name__  # noqa: SLF001
                else:
                    items_name = type(self._items).__name__
                msg = (
                    "The length of the exported column indices and names are incompatible in "
                    f"'{items_name}'"
                )
                raise ValueError(msg)
            return pd.DataFrame(data=data, columns=column_names)

    def _flatten_tree(
        self, parent_rows: Tuple[int, ...] = ()
    ) -> Tuple[List[List[Any]], List[str]]:
        data = []
        child_columns: List[str] = []
        for row in range(self._items.get_nb_rows(parent_rows)):
            row_data = [
                self._items.get_edit_data(row, column, parent_rows)
                for column in self._items.get_exported_column_indices(parent_rows)
            ]
            child_data, child_columns = self._flatten_tree((*parent_rows, row))
            if len(child_data) == 0:
                data.append(row_data)
            else:
                for child_row in child_data:
                    data.append(row_data + child_row)  # noqa: PERF401
        if len(data) > 0:
            columns = self._items.get_exported_column_names(parent_rows) + child_columns
        else:
            columns = []
        return data, columns

    def iter_dataframes(
        self, parent_rows: Tuple[int, ...] = ()
    ) -> Generator["pd.DataFrame", None, None]:
        """Iterate over all the possible trees converted into pandas dataframes."""
        with self._switch_to_fake_selected_items():
            for _ in self._items.iter_trigger_dependencies():
                yield self._to_dataframe(parent_rows)

    def _iter_titles(self, parent_rows: Tuple[int, ...] = ()) -> Generator[str, None, None]:
        """Iterate over all the possible titles."""
        with self._switch_to_fake_selected_items():
            for _ in self._items.iter_trigger_dependencies():
                yield self._items.get_title(parent_rows)

    def _iter_infos(
        self, parent_rows: Tuple[int, ...] = ()
    ) -> Generator[Dict[str, Any], None, None]:
        """Iterate over all the possible infos."""
        with self._switch_to_fake_selected_items():
            for _ in self._items.iter_trigger_dependencies():
                yield self._items.get_infos(parent_rows)

    @contextmanager
    def _switch_to_fake_selected_items(
        self,
        dependencies_selected_items: Tuple[OrderedDict[Tuple[int, ...], List[int]], ...] = (),
    ) -> Generator[None, None, None]:
        """Keep the current selected items of the dependencies."""
        for dependent_items in self._items.get_dependencies():
            dependent_items.set_view_selection_suspend_status(True)
        try:
            for dependency_item, selected_items in zip(
                self._items.get_dependencies(), dependencies_selected_items
            ):
                dependency_item.set_selected_items(selected_items)
            yield
        finally:
            for dependent_items in self._items.get_dependencies():
                dependent_items.set_view_selection_suspend_status(False)
