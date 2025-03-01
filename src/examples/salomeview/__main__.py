"""Main of the Salome view example."""

from examples.salomeview.app import ExampleSalomeApp


def main() -> None:
    r"""Launch the example."""
    app = ExampleSalomeApp()
    app.run()


if __name__ == "__main__":
    main()
