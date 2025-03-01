"""Main of the MainView example."""

from examples.formview.app import FormViewApp
from examples.formview.qtexample import QtExampleMainView


def main() -> None:
    """Launch the example."""
    app = FormViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
