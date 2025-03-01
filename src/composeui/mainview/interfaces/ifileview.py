from composeui.core.views.iview import IView

from dataclasses import dataclass, field


@dataclass(eq=False)
class IFileView(IView):
    filter_path: str = field(init=False, default="")

    def open_file(self) -> str:
        return ""

    def save_file(self) -> str:
        return ""

    def existing_directory(self) -> str:
        return ""
