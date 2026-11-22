"""The Textual backend's renderers by key, which `composeui.core.registry` looks up."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from composeui.textualcore._renderers.actions import (
    TextualActionRenderer,
    TextualMenuRenderer,
    TextualSeparatorRenderer,
    TextualToolBarRenderer,
)
from composeui.textualcore._renderers.charts import TextualChartRenderer
from composeui.textualcore._renderers.choices import (
    TextualCheckListRenderer,
    TextualComboBoxRenderer,
    TextualMultiComboBoxRenderer,
    TextualRadioGroupRenderer,
    TextualTreeRenderer,
)
from composeui.textualcore._renderers.containers import (
    TextualExpanderRenderer,
    TextualGridRenderer,
    TextualHorizontalRenderer,
    TextualListRenderer,
    TextualPageRenderer,
    TextualSplitterRenderer,
    TextualTabPageRenderer,
    TextualTabsRenderer,
    TextualVerticalRenderer,
)
from composeui.textualcore._renderers.content import (
    TextualConsoleRenderer,
    TextualImageRenderer,
    TextualLabelRenderer,
    TextualLogRenderer,
    TextualMarkdownRenderer,
    TextualMetricRenderer,
    TextualNotificationBarRenderer,
    TextualStatusBarRenderer,
)
from composeui.textualcore._renderers.controls import (
    TextualButtonRenderer,
    TextualCheckBoxRenderer,
    TextualDialogButtonRenderer,
    TextualDownloadRenderer,
    TextualFloatRangeSliderRenderer,
    TextualFloatSliderRenderer,
    TextualProgressBarRenderer,
    TextualRangeSliderRenderer,
    TextualSliderRenderer,
)
from composeui.textualcore._renderers.dialogs import (
    TextualDialogRenderer,
    TextualFormDialogRenderer,
)
from composeui.textualcore._renderers.files import (
    TextualFilePathInputRenderer,
    TextualFileUploadRenderer,
    TextualFolderPathInputRenderer,
    TextualSavePathInputRenderer,
)
from composeui.textualcore._renderers.forms import (
    TextualFormLabelRenderer,
    TextualFormRenderer,
    TextualGroupFormRenderer,
)
from composeui.textualcore._renderers.graphics import TextualDrawingRenderer
from composeui.textualcore._renderers.inputs import (
    TextualDateInputRenderer,
    TextualDateRangeInputRenderer,
    TextualFloatInputRenderer,
    TextualInputRenderer,
    TextualIntInputRenderer,
    TextualTextAreaRenderer,
)
from composeui.textualcore._renderers.navigation import (
    TextualMainRenderer,
    TextualRouterRenderer,
    TextualSidebarRenderer,
)
from composeui.textualcore._renderers.tables import TextualSourceTableRenderer, TextualTableRenderer

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.renderer import Renderer


#: renderer keys of the Textual backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {
    "action": TextualActionRenderer,
    "button": TextualButtonRenderer,
    "download": TextualDownloadRenderer,
    "dialog_button": TextualDialogButtonRenderer,
    "chart": TextualChartRenderer,
    "drawing": TextualDrawingRenderer,
    "checkbox": TextualCheckBoxRenderer,
    "check_list": TextualCheckListRenderer,
    "combobox": TextualComboBoxRenderer,
    "source_table": TextualSourceTableRenderer,
    "date_input": TextualDateInputRenderer,
    "date_range_input": TextualDateRangeInputRenderer,
    "file_path_input": TextualFilePathInputRenderer,
    "file_upload": TextualFileUploadRenderer,
    "folder_path_input": TextualFolderPathInputRenderer,
    "save_path_input": TextualSavePathInputRenderer,
    "dialog": TextualDialogRenderer,
    "expander": TextualExpanderRenderer,
    "float_input": TextualFloatInputRenderer,
    "int_input": TextualIntInputRenderer,
    "form": TextualFormRenderer,
    "content_dialog": TextualFormDialogRenderer,
    "form_dialog": TextualFormDialogRenderer,
    "form_label": TextualFormLabelRenderer,
    "grid": TextualGridRenderer,
    "group_form": TextualGroupFormRenderer,
    "horizontal": TextualHorizontalRenderer,
    "input": TextualInputRenderer,
    "label": TextualLabelRenderer,
    "list": TextualListRenderer,
    "log": TextualLogRenderer,
    "main": TextualMainRenderer,
    "image": TextualImageRenderer,
    "markdown": TextualMarkdownRenderer,
    "console": TextualConsoleRenderer,
    "menu": TextualMenuRenderer,
    "metric": TextualMetricRenderer,
    "multi_combobox": TextualMultiComboBoxRenderer,
    "page": TextualPageRenderer,
    "progress_bar": TextualProgressBarRenderer,
    "slider": TextualSliderRenderer,
    "float_range_slider": TextualFloatRangeSliderRenderer,
    "float_slider": TextualFloatSliderRenderer,
    "radio_group": TextualRadioGroupRenderer,
    "range_slider": TextualRangeSliderRenderer,
    "router": TextualRouterRenderer,
    "separator": TextualSeparatorRenderer,
    "sidebar": TextualSidebarRenderer,
    "splitter": TextualSplitterRenderer,
    "notification_bar": TextualNotificationBarRenderer,
    "status_bar": TextualStatusBarRenderer,
    "table": TextualTableRenderer,
    "text_area": TextualTextAreaRenderer,
    "tab_page": TextualTabPageRenderer,
    "tabs": TextualTabsRenderer,
    "toolbar": TextualToolBarRenderer,
    "tree": TextualTreeRenderer,
    "vertical": TextualVerticalRenderer,
}
