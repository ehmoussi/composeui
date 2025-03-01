"""Main of the SimpleTableView example."""

from examples.simpletableview.app import SimpleTableViewApp
from examples.simpletableview.qtexample import QtExampleMainView


def main() -> None:
    """Launch the example."""
    app = SimpleTableViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
