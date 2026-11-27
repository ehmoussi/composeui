"""The Qt backend's renderers by key, which `composeui.core.registry` looks up."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from composeui.qtcore._renderers.actions import (
    QtActionRenderer,
    QtMenuButtonRenderer,
    QtMenuRenderer,
    QtSeparatorRenderer,
    QtToolBarRenderer,
)
from composeui.qtcore._renderers.charts import QtChartRenderer
from composeui.qtcore._renderers.choices import (
    QtCheckListRenderer,
    QtComboBoxRenderer,
    QtMultiComboBoxRenderer,
    QtRadioGroupRenderer,
    QtTreeRenderer,
)
from composeui.qtcore._renderers.containers import (
    QtExpanderRenderer,
    QtGridRenderer,
    QtHorizontalRenderer,
    QtListRenderer,
    QtPageRenderer,
    QtSplitterRenderer,
    QtTabPageRenderer,
    QtTabsRenderer,
    QtVerticalRenderer,
)
from composeui.qtcore._renderers.content import (
    QtConsoleRenderer,
    QtImageRenderer,
    QtLabelRenderer,
    QtLogRenderer,
    QtMarkdownRenderer,
    QtMetricRenderer,
    QtNotificationBarRenderer,
    QtStatusBarRenderer,
)
from composeui.qtcore._renderers.controls import (
    QtButtonRenderer,
    QtCheckBoxRenderer,
    QtDialogButtonRenderer,
    QtDownloadRenderer,
    QtFloatRangeSliderRenderer,
    QtFloatSliderRenderer,
    QtProgressBarRenderer,
    QtRangeSliderRenderer,
    QtSliderRenderer,
)
from composeui.qtcore._renderers.dialogs import QtDialogRenderer, QtFormDialogRenderer
from composeui.qtcore._renderers.files import (
    QtFilePathInputRenderer,
    QtFileUploadRenderer,
    QtFolderPathInputRenderer,
    QtSavePathInputRenderer,
)
from composeui.qtcore._renderers.forms import (
    QtFormLabelRenderer,
    QtFormRenderer,
    QtGroupFormRenderer,
)
from composeui.qtcore._renderers.graphics import QtDrawingRenderer, _map_renderer
from composeui.qtcore._renderers.inputs import (
    QtDateInputRenderer,
    QtDateRangeInputRenderer,
    QtFloatInputRenderer,
    QtInputRenderer,
    QtIntInputRenderer,
    QtTextAreaRenderer,
    QtTextEditorRenderer,
)
from composeui.qtcore._renderers.navigation import (
    QtMainRenderer,
    QtRouterRenderer,
    QtSidebarRenderer,
)
from composeui.qtcore._renderers.tables import QtSourceTableRenderer, QtTableRenderer

if TYPE_CHECKING:
    from collections.abc import Callable

    from composeui.core.renderer import Renderer


#: renderer keys of the Qt backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {
    "action": QtActionRenderer,
    "button": QtButtonRenderer,
    "download": QtDownloadRenderer,
    "dialog_button": QtDialogButtonRenderer,
    "chart": QtChartRenderer,
    "drawing": QtDrawingRenderer,
    "map": _map_renderer,
    "checkbox": QtCheckBoxRenderer,
    "check_list": QtCheckListRenderer,
    "combobox": QtComboBoxRenderer,
    "source_table": QtSourceTableRenderer,
    "date_input": QtDateInputRenderer,
    "date_range_input": QtDateRangeInputRenderer,
    "file_path_input": QtFilePathInputRenderer,
    "file_upload": QtFileUploadRenderer,
    "folder_path_input": QtFolderPathInputRenderer,
    "save_path_input": QtSavePathInputRenderer,
    "dialog": QtDialogRenderer,
    "expander": QtExpanderRenderer,
    "float_input": QtFloatInputRenderer,
    "int_input": QtIntInputRenderer,
    "form": QtFormRenderer,
    "content_dialog": QtFormDialogRenderer,
    "form_dialog": QtFormDialogRenderer,
    "form_label": QtFormLabelRenderer,
    "grid": QtGridRenderer,
    "group_form": QtGroupFormRenderer,
    "horizontal": QtHorizontalRenderer,
    "input": QtInputRenderer,
    "label": QtLabelRenderer,
    "list": QtListRenderer,
    "log": QtLogRenderer,
    "main": QtMainRenderer,
    "image": QtImageRenderer,
    "markdown": QtMarkdownRenderer,
    "console": QtConsoleRenderer,
    "menu": QtMenuRenderer,
    "menu_button": QtMenuButtonRenderer,
    "metric": QtMetricRenderer,
    "multi_combobox": QtMultiComboBoxRenderer,
    "notification_bar": QtNotificationBarRenderer,
    "page": QtPageRenderer,
    "progress_bar": QtProgressBarRenderer,
    "slider": QtSliderRenderer,
    "float_range_slider": QtFloatRangeSliderRenderer,
    "float_slider": QtFloatSliderRenderer,
    "radio_group": QtRadioGroupRenderer,
    "range_slider": QtRangeSliderRenderer,
    "router": QtRouterRenderer,
    "separator": QtSeparatorRenderer,
    "sidebar": QtSidebarRenderer,
    "splitter": QtSplitterRenderer,
    "status_bar": QtStatusBarRenderer,
    "table": QtTableRenderer,
    "text_area": QtTextAreaRenderer,
    "text_editor": QtTextEditorRenderer,
    "tab_page": QtTabPageRenderer,
    "tabs": QtTabsRenderer,
    "toolbar": QtToolBarRenderer,
    "tree": QtTreeRenderer,
    "vertical": QtVerticalRenderer,
}
