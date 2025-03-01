import typing
from typing import Any, Generator, Optional

if typing.TYPE_CHECKING:
    from composeui.items.core.ipaginationview import IPaginationView
    from composeui.items.table.abstracttableitems import AbstractTableItems


class PaginationNavigator:
    def __init__(self, view: "IPaginationView", items: "AbstractTableItems[Any]") -> None:
        self._view = view
        self._items = items
        self._current_page_size: int = 1
        self._page_size_step: int = 5

    @property
    def current_page(self) -> int:
        """Get the current page."""
        return self._view.current_page

    @property
    def current_nb_pages(self) -> int:
        """Get the current number of pages."""
        nb_rows = self._items.get_nb_rows()
        return (nb_rows // self._current_page_size) + ((nb_rows % self._current_page_size) > 0)

    def set_current_page(self, page: int) -> None:
        """Set the current page."""
        self._view.current_page = page

    def set_current_page_from_row(self, row: int) -> None:
        """Set the current page to make visibile the given row."""
        current_page = row // self._current_page_size
        self.set_current_page(current_page)

    def set_page_size_nb_categories(self, nb_categories: int) -> None:
        """Set the number of page size available to choose."""
        nb_categories = max(nb_categories, 1)
        self.page_size_step = max(self._items.get_nb_rows() // nb_categories, 5)

    def can_move_forward(self) -> bool:
        """Check if the current page can move forward."""
        return self.current_page < (self.current_nb_pages - 1)

    def can_move_backward(self) -> bool:
        """Check if the current page can move backward."""
        return self.current_page > 0

    def iter_page_sizes(self) -> Generator[int, None, None]:
        """Iterate over the current page size"""
        nb_rows = self._items.get_nb_rows()
        yield from range(self._page_size_step, nb_rows + 1, self._page_size_step)
        if (nb_rows % self._page_size_step) != 0:
            yield max(nb_rows, self._page_size_step)

    def get_page_size(self, index: int) -> Optional[int]:
        """Get the page size available at the given index.

        If there is no page size available it returns None.
        """
        if index >= 0:
            nb_rows = self._items.get_nb_rows()
            page_size = self._page_size_step + index * self._page_size_step
            if page_size > nb_rows:
                return nb_rows
            return page_size
        return None

    def update_current_page_size(self, index_page_size: int) -> bool:
        """Set the current page size according to the given index.

        If the page size of the given index is different of the current page size the current
        page is also updated to 0 (the first page)
        """
        page_size = self.get_page_size(index_page_size)
        update_current_page = page_size is not None and self._current_page_size != page_size
        if page_size is not None and page_size > 0:
            self._current_page_size = page_size
        else:
            self._current_page_size = self._page_size_step
        if update_current_page:
            self.set_current_page(0)
            return True
        return False

    def move_to_first_page(self) -> None:
        """Move the current page to the first page (i.e 0)."""
        self.set_current_page(0)

    def move_to_previous_page(self) -> None:
        """Move the current page to the previous page."""
        self.set_current_page(self.current_page - 1)

    def move_to_next_page(self) -> None:
        """Move the current page to the next page."""
        self.set_current_page(self.current_page + 1)

    def move_to_last_page(self) -> None:
        """Move the current page to the last page."""
        self.set_current_page(self.current_nb_pages - 1)

    def get_row_summary(self) -> str:
        """Get the text to display for the row summary."""
        nb_rows = self._items.get_nb_rows()
        if nb_rows == 0:
            min_row = 0
            max_row = 0
        else:
            min_row = self.get_current_min_row() + 1
            max_row = self.get_current_max_row() + 1
        return f"{min_row} to {max_row} of {nb_rows}"

    def get_navigation_description(self) -> str:
        """Get the text to display for the navigation description."""
        nb_rows = self._items.get_nb_rows()
        if nb_rows == 0:
            page = 0
        else:
            page = self.current_page + 1
        return f"Page {page} of {self.current_nb_pages}"

    def get_current_min_row(self) -> int:
        """Get the current minimum row visible."""
        return max(self.current_page * self._current_page_size, 0)

    def get_current_max_row(self) -> int:
        """Get the current maximum row visible."""
        return max(
            min(
                (self.current_page + 1) * self._current_page_size,
                self._items.get_nb_rows(),
            )
            - 1,
            0,
        )
