from composeui.core.basesignal import BaseSignal
from composeui.core.views.iview import IView

from typing_extensions import Literal

from dataclasses import dataclass, field

FileMode = Literal["open_file", "save_file", "existing_directory"]


@dataclass(eq=False)
class ISelectPathView(IView):
    path: str = field(init=False, default="")
    label: str = field(init=False, default="")
    is_read_only: bool = field(init=False, default=True)
    button_name: str = field(init=False, default="...")
    filter_path: str = field(init=False, default="")
    mode: FileMode = field(init=False, default="open_file")
    select_clicked: BaseSignal = field(init=False, default=BaseSignal())
