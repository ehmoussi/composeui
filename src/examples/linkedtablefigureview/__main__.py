from examples.linkedtablefigureview.app import LinkedTableFigureViewApp
from examples.linkedtablefigureview.qtexample import QtExampleMainView


def main() -> None:
    app = LinkedTableFigureViewApp(QtExampleMainView())
    app.run()


if __name__ == "__main__":
    main()
