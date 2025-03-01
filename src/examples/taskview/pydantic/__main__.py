"""Main of the Pydantic TaskView example."""

from examples.taskview.pydantic.app import PydanticTaskViewApp
from examples.taskview.pydantic.examplemainview import ExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = PydanticTaskViewApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
