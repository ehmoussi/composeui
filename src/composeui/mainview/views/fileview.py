from composeui.core.views.view import View

from dataclasses import dataclass, field


@dataclass(eq=False)
class FileView(View):
    filter_path: str = field(init=False, default="")

    def open_file(self) -> str:
        return ""

    def save_file(self) -> str:
        return ""

    def existing_directory(self) -> str:
        return ""
