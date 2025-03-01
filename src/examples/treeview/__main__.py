"""Main of the TreeView example."""

from examples.treeview.app import TreeViewApp
from examples.treeview.examplemainview import ExampleMainView


def main() -> None:
    """Launch the example."""
    app = TreeViewApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
