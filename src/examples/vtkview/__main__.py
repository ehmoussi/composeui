from examples.vtkview.app import VTKViewApp
from examples.vtkview.examplemainview import ExampleMainView


def main() -> None:
    main_view = ExampleMainView()
    app = VTKViewApp(main_view)
    app.run()


if __name__ == "__main__":
    main()
