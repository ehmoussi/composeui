"""Main of the TableView example."""

from examples.tableview.app import TableViewApp
from examples.tableview.qtexample import QtExampleMainView


def main() -> None:
    """Launch the example."""
    app = TableViewApp(QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
