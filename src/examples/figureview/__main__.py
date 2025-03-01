"""Main of the MainView example."""

from examples.figureview.app import FigureViewApp
from examples.figureview.examplemainview import ExampleMainView


def main() -> None:
    r"""Launch the example."""
    main_view = ExampleMainView()
    app = FigureViewApp(main_view)
    app.run()


if __name__ == "__main__":
    main()
