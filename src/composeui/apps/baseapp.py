try:
    from rich.traceback import install

    install(show_locals=False)
except (ImportError, ModuleNotFoundError):
    ...
import argparse
from typing import Optional


class BaseApp:
    def __init__(self, is_testing: bool = False) -> None:
        self.is_testing = is_testing
        self._args: Optional[argparse.Namespace] = None
        self._parser = argparse.ArgumentParser()
        self._parser.add_argument(
            "--debug", help="Run the app in debug mode", action="store_true"
        )

    def run(self) -> None:
        if not self.is_testing:
            self._args = self._parse_arguments()

    def _parse_arguments(self) -> argparse.Namespace:
        return self._parser.parse_args()
