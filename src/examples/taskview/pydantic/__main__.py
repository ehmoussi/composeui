"""Main of the Pydantic TaskView example."""

from examples.taskview.pydantic.app import PydanticTaskViewApp
from examples.taskview.pydantic.qtexample import QtExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = PydanticTaskViewApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
