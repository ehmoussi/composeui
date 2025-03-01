from examples.linkedtablefigureview.app import LinkedTableFigureViewApp
from examples.linkedtablefigureview.mainview import ExampleMainView


def main() -> None:
    app = LinkedTableFigureViewApp(ExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
