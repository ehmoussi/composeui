"""Main of the MainView example."""

from examples.figureview.app import FigureViewApp
from examples.figureview.qtexample import QtExampleMainView


def main() -> None:
    r"""Launch the example."""
    main_view = QtExampleMainView()
    app = FigureViewApp(main_view)
    app.run()


if __name__ == "__main__":
    main()
