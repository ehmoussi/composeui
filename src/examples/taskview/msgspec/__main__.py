"""Main of the Msgspec TaskView example."""

from examples.taskview.msgspec.app import MsgspecTaskViewApp
from examples.taskview.msgspec.examplemainview import ExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = MsgspecTaskViewApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
