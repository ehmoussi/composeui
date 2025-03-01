"""Main of the LinkedTableView Sqlite example."""

from examples.linkedtableview.sqlite.app import LinkedTableViewApp
from examples.linkedtableview.sqlite.qtexample import QtExampleMainView


def main() -> None:
    """Launch the example."""
    app = LinkedTableViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
