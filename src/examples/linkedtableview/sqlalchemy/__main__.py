"""Main of the LinkedTableView example with SqlAlchemy."""

from examples.linkedtableview.sqlalchemy.app import LinkedTableViewApp
from examples.linkedtableview.sqlalchemy.qtexample import QtExampleMainView


def main() -> None:
    """Launch the example."""
    app = LinkedTableViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
