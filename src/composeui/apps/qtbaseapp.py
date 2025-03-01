from composeui.apps.baseapp import BaseApp
from composeui.apps.eventdrivenappmixin import EventDrivenAppMixin
from composeui.commontypes import AnyMainView, AnyModel
from composeui.core import tools
from composeui.core.basesignal import SIGNAL_LOGGER

import logging
from argparse import Namespace
from pathlib import Path


class QtBaseApp(BaseApp, EventDrivenAppMixin[AnyMainView, AnyModel]):
    def __init__(self, model: AnyModel, main_view: AnyMainView) -> None:
        super().__init__()
        self._model: AnyModel = model
        self._main_view: AnyMainView = main_view
        self.is_testing = not hasattr(main_view, "qt_app")
        self._parser.add_argument(
            "-f", metavar="FILE", help="Open the app with the FILE study", type=Path
        )
        self._parser.add_argument(
            "--log-signals", help="Log all the emitted signals.", action="store_true"
        )
        if not hasattr(main_view, "qt_app"):
            self._app = None
        else:
            self._app = main_view.qt_app
        if not hasattr(main_view, "qt_asyncio"):
            self._asyncio = None
        else:
            self._asyncio = main_view.qt_asyncio

    @property
    def main_view(self) -> AnyMainView:
        return self._main_view

    @property
    def model(self) -> AnyModel:
        return self._model

    def run(self) -> None:
        super().run()
        if self._args is not None and self._args.log_signals:
            SIGNAL_LOGGER.setLevel(level=logging.DEBUG)
        self.initialize()
        self.connect()
        if self._args is not None and self._args.f is not None:
            self._model.open_file(self._args.f)
            tools.update_all_views(self.main_view)
        if self._asyncio is not None:
            self._asyncio.run(handle_sigint=True, debug=self.model.is_debug)
        elif self._app is not None:
            self._app.exec_()

    def _parse_arguments(self) -> Namespace:
        args = super()._parse_arguments()
        if args.debug:
            self.model.is_debug = True
        if args.f is not None and isinstance(args.f, Path) and args.f.is_file():
            extension_study = self.main_view.extension_study
            if args.f.suffix != extension_study:
                msg = (
                    f"Invalid file extension: '{args.f.suffix}'. "
                    f"Expected extension: '{extension_study}'. "
                    "Please provide a file with the correct extension."
                )
                raise ValueError(msg)
        return args
