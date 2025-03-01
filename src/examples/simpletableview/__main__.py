"""Main of the SimpleTableView example."""

from examples.simpletableview.app import SimpleTableViewApp
from examples.simpletableview.examplemainview import ExampleMainView


def main() -> None:
    """Launch the example."""
    app = SimpleTableViewApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
