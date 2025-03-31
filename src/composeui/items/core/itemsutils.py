from typing_extensions import TypeAlias

import enum
from typing import List, Optional, Union


class FloatDelegateProps:
    """Properties of a Float Delegate"""

    __slots__ = ["decimals", "maximum", "minimum"]

    def __init__(
        self,
        minimum: Optional[float] = None,
        maximum: Optional[float] = None,
        decimals: Optional[int] = None,
    ) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self.decimals = decimals


class IntDelegateProps:
    """Properties of an Integer Delegate"""

    __slots__ = ["maximum", "minimum"]

    def __init__(self, minimum: Optional[int] = None, maximum: Optional[int] = None) -> None:
        self.minimum = minimum
        self.maximum = maximum


class ComboBoxDelegateProps:
    """Properties of a CombobBox Delegate"""

    __slots__ = ["values"]

    def __init__(self, values: Optional[List[str]] = None) -> None:
        if values is None:
            self.values = []
        else:
            self.values = values


DelegateProps: TypeAlias = Union[ComboBoxDelegateProps, FloatDelegateProps, IntDelegateProps]


class BackgroundType(enum.Flag):
    """Define the background type."""

    # TODO: increase the posibilities

    NONE = 0
    STRIPED = enum.auto()
