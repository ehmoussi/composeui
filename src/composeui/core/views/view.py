from composeui.core.basesignal import BaseSignal

from dataclasses import dataclass, field
from typing import Any, List, MutableMapping


@dataclass(eq=False)
class View:
    view_name: str = field(init=False)
    is_visible: bool = field(init=False, default=False)
    is_enabled: bool = field(init=False, default=False)
    minimum_width: int = field(init=False, default=0)
    minimum_height: int = field(init=False, default=0)
    children: MutableMapping[str, "View"] = field(init=False, repr=False, default_factory=dict)
    dependencies: List["View"] = field(init=False, repr=False, default_factory=list)
    block_signals: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.view_name = f"{self.__class__.__name__}_{id(self)}"

    def update(self) -> None:
        return

    def __setattr__(self, name: str, value: Any) -> None:
        if isinstance(value, View):
            value.view_name = name
            self.children[name] = value
        elif isinstance(value, BaseSignal) and (
            not hasattr(self, name) or getattr(self, name) is not value
        ):
            raise TypeError("BaseSignal needs to be instanciated as a class attribute")
        return super().__setattr__(name, value)


@dataclass(eq=False)
class GroupView(View):
    title: str = field(init=False, default="")
    is_checkable: bool = field(init=False, default=False)
    is_checked: bool = field(init=False, default=False)
