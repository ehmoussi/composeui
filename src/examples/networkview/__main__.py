"""Main of the NetworkView example."""

from examples.networkview.app import NetworkViewApp
from examples.networkview.qtexample import QtExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = NetworkViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
