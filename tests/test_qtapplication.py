"""Tests for the Qt app with a model, as it fails to start."""

from __future__ import annotations

import pytest

pytest.importorskip("qtpy.QtWidgets")

from composeui.core.model import Model
from composeui.core.view import MainView
from composeui.qtcore.qtapplication import QtModelApplication


class _LoggedModel(Model):
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_a_model_that_fails_to_build_raises_its_own_error() -> None:
    def build_model() -> Model:
        msg = "no database"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="no database"):
        QtModelApplication(build_main_view=MainView, build_model=build_model)


def test_a_wrong_argument_closes_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["app", "--no-such-option"])
    app = QtModelApplication(build_main_view=MainView, build_model=_LoggedModel)

    with pytest.raises(SystemExit):
        app.run()

    assert app.model.closed
