"""Main of the Multiple Views example."""

from examples.multipleviews.app import MultipleViewsApp
from examples.multipleviews.examplemainview import ExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = MultipleViewsApp(main_view=ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
