r"""View the filter of a table."""

from composeui.core.qt.view import View
from composeui.core.qt.widgets.checkablemenubutton import CheckableMenuButton
from composeui.items.core.ifiltertableview import IFilterTableView

from qtpy.QtGui import QIcon
from qtpy.QtWidgets import QGridLayout, QLabel, QLineEdit, QPushButton, QWidget

from dataclasses import dataclass, field
from typing import Tuple


@dataclass(eq=False)
class FilterTableView(View, IFilterTableView):
    r"""View of an action."""

    view: QWidget = field(init=False)

    def __post_init__(self) -> None:
        self.view = QWidget()
        self.layout = QGridLayout()
        # Columns selector
        self.columns_selector = CheckableMenuButton(QIcon(":/icons/tune.png"), "")
        self.columns_selector.setMaximumWidth(45)
        self.layout.addWidget(self.columns_selector, 0, 0)
        # Filter text
        self.text_lineedit = QLineEdit()
        self.text_lineedit.setToolTip("Filter Pattern")
        self.layout.addWidget(self.text_lineedit, 0, 1)
        # Case button
        self.case_button = QPushButton()
        self.case_button.setCheckable(True)
        self.case_button.setIcon(QIcon(":/icons/case.png"))
        self.case_button.setToolTip("Match Case")
        self.layout.addWidget(self.case_button, 0, 2)
        # Whole word button
        self.whole_word_button = QPushButton()
        self.whole_word_button.setCheckable(True)
        self.whole_word_button.setIcon(QIcon(":/icons/whole_word.png"))
        self.whole_word_button.setToolTip("Match Whole Word")
        self.layout.addWidget(self.whole_word_button, 0, 3)
        # Regular expression button
        self.regex_button = QPushButton()
        self.regex_button.setCheckable(True)
        self.regex_button.setIcon(QIcon(":/icons/regex.png"))
        self.regex_button.setToolTip("Use Regular Expression")
        self.layout.addWidget(self.regex_button, 0, 4)
        # information text
        self.information_label = QLabel("The regex is not recognized")
        self.information_label.setStyleSheet(
            "QLabel { color: red; font-size: 10px; font: italic; }"
        )
        self.layout.addWidget(self.information_label, 1, 0)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.view.setLayout(self.layout)
        # assign signals
        self.filter_changed.add_qt_signals(
            (self.text_lineedit, self.text_lineedit.editingFinished),
            (self.case_button, self.case_button.clicked),
            (self.whole_word_button, self.whole_word_button.clicked),
            (self.regex_button, self.regex_button.clicked),
            (self.columns_selector, self.columns_selector.selection_changed),
        )

    @property  # type: ignore[misc]
    def text(self) -> str:
        return str(self.text_lineedit.text())

    @text.setter
    def text(self, text: str) -> None:
        self.text_lineedit.setText(text)

    @property  # type: ignore[misc]
    def info_text(self) -> str:
        return str(self.information_label.text())

    @info_text.setter
    def info_text(self, info_text: str) -> None:
        self.information_label.setText(info_text)

    @property  # type: ignore[misc]
    def match_case(self) -> bool:
        return bool(self.case_button.isChecked())

    @match_case.setter
    def match_case(self, match_case: bool) -> None:
        self.case_button.setChecked(match_case)

    @property  # type: ignore[misc]
    def match_whole_word(self) -> bool:
        return bool(self.whole_word_button.isChecked())

    @match_whole_word.setter
    def match_whole_word(self, match_whole_word: bool) -> None:
        self.whole_word_button.setChecked(match_whole_word)

    @property  # type: ignore[misc]
    def use_regex(self) -> bool:
        return bool(self.regex_button.isChecked())

    @use_regex.setter
    def use_regex(self, use_regex: bool) -> None:
        self.regex_button.setChecked(use_regex)

    @property  # type: ignore[misc]
    def selected_column_indices(self) -> Tuple[int, ...]:
        return self.columns_selector.checked_indices

    @selected_column_indices.setter
    def selected_column_indices(self, indices: Tuple[int, ...]) -> None:
        # self.columns_selector.checked_indices = indices
        # raise NotImplementedError
        pass
