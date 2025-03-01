"""Main of the MainView example."""

from examples.mainview.app import MainViewApp
from examples.mainview.qtexample import ExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = MainViewApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
