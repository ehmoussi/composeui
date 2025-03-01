"""Main of the Msgspec TaskView example."""

from examples.taskview.msgspec.app import MsgspecTaskViewApp
from examples.taskview.msgspec.qtexample import QtExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = MsgspecTaskViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
