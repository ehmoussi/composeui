"""Main of the Mashumaro TaskView example."""

from examples.taskview.mashumaro.app import MashumaroTaskViewApp
from examples.taskview.mashumaro.qtexample import QtExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = MashumaroTaskViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
