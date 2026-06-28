from qtpy.QtGui import QIcon


class QIconPath(QIcon):
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self._path = path

    def get_path(self) -> str:
        return self._path
