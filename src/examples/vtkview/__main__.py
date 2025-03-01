from examples.vtkview.app import VTKViewApp
from examples.vtkview.qtexample import QtExampleMainView


def main() -> None:
    main_view = QtExampleMainView()
    app = VTKViewApp(main_view)
    app.run()


if __name__ == "__main__":
    main()
