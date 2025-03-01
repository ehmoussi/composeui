"""Main of the TreeView example."""

from examples.treeview.app import TreeViewApp
from examples.treeview.qtexample import QtExampleMainView


def main() -> None:
    """Launch the example."""
    app = TreeViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
