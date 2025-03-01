"""Main of the TableView example."""

from examples.tableview.app import TableViewApp
from examples.tableview.examplemainview import ExampleMainView


def main() -> None:
    """Launch the example."""
    app = TableViewApp(ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
