from composeui.commontypes import AnyFormItems
from composeui.form.qtformview import QtGroupBoxApplyFormView, QtGroupBoxFormView
from examples.formview.pipeapplyform import PipeApplyFormItems, PipeApplyFormView
from examples.formview.pipeform import (
    ChamferDimensionView,
    FilletDimensionView,
    PipeDimensionView,
    PipeFormItems,
    PipeFormView,
)

from dataclasses import dataclass


@dataclass(eq=False)
class QtPipeDimensionView(
    QtGroupBoxFormView[AnyFormItems], PipeDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class QtChamferDimensionView(
    QtGroupBoxFormView[AnyFormItems], ChamferDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class QtFilletDimensionView(
    QtGroupBoxFormView[AnyFormItems], FilletDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class QtPipeFormView(QtGroupBoxFormView[PipeFormItems], PipeFormView): ...


@dataclass(eq=False)
class QtPipeApplyFormView(QtGroupBoxApplyFormView[PipeApplyFormItems], PipeApplyFormView): ...
