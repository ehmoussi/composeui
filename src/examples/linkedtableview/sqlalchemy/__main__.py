"""Main of the LinkedTableView example with SqlAlchemy."""

from examples.linkedtableview.sqlalchemy.app import LinkedTableViewApp
from examples.linkedtableview.sqlalchemy.examplemainview import ExampleMainView


def main() -> None:
    """Launch the example."""
    app = LinkedTableViewApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
