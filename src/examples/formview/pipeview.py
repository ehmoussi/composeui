from composeui.commontypes import AnyFormItems
from composeui.form.formview import GroupBoxApplyFormView, GroupBoxFormView
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
class PipeDimensionView(GroupBoxFormView[AnyFormItems], IPipeDimensionView[AnyFormItems]): ...


@dataclass(eq=False)
class ChamferDimensionView(
    GroupBoxFormView[AnyFormItems], IChamferDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class FilletDimensionView(
    GroupBoxFormView[AnyFormItems], IFilletDimensionView[AnyFormItems]
): ...


@dataclass(eq=False)
class PipeFormView(GroupBoxFormView[PipeFormItems], IPipeFormView): ...


@dataclass(eq=False)
class PipeApplyFormView(GroupBoxApplyFormView[PipeApplyFormItems], IPipeApplyFormView): ...
