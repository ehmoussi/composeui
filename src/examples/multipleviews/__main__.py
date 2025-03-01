"""Main of the Multiple Views example."""

from examples.multipleviews.app import MultipleViewsApp
from examples.multipleviews.qtexample import QtExampleMainView


def main() -> None:
    r"""Launch the example."""
    app = MultipleViewsApp(main_view=QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
