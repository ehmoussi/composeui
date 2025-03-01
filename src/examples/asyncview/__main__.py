"""Main of the Async example using PySide6.

This example don't work with PyQt5 because async is not available.
"""

import os

os.environ["QT_API"] = "pyside6"

import importlib.util

if importlib.util.find_spec("aiofiles") is None:
    raise ImportError(
        "The aiofiles library is needed to run this example:\n"
        "python -m pip install aiofiles"
    ) from None

from examples.asyncview.app import AsyncViewApp
from examples.asyncview.examplemainview import ExampleMainView

from qtpy import API


def main() -> None:
    r"""Launch the example."""
    if API == "pyside6":
        app = AsyncViewApp(main_view=ExampleMainView())
        app.run()
    else:
        msg = f"The example is not available with {API}"
        raise NotImplementedError(msg)


if __name__ == "__main__":
    main()
