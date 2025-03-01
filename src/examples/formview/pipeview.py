from composeui.commontypes import AnyFormItems
from composeui.form.qtformview import QtGroupBoxApplyFormView, QtGroupBoxFormView
from examples.formview.pipeapplyform import IPipeApplyFormView, PipeApplyFormItems
from examples.formview.pipeform import (
    IChamferDimensionView,
    IFilletDimensionView,
    IPipeDimensionView,
    IPipeFormView,
    PipeFormItems,
)

from dataclasses import dataclass


@dataclass(eq=False)
class PipeDimensionView(
    QtGroupBoxFormView[AnyFormItems], IPipeDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class ChamferDimensionView(
    QtGroupBoxFormView[AnyFormItems], IChamferDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class FilletDimensionView(
    QtGroupBoxFormView[AnyFormItems], IFilletDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class PipeFormView(QtGroupBoxFormView[PipeFormItems], IPipeFormView): ...


@dataclass(eq=False)
class PipeApplyFormView(QtGroupBoxApplyFormView[PipeApplyFormItems], IPipeApplyFormView): ...
