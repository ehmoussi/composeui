"""The web backend's renderers by key, which `composeui.core.registry` looks up."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Final

from composeui.webcore._renderers.actions import (
    WebActionRenderer,
    WebMenuRenderer,
    WebSeparatorRenderer,
    WebToolBarRenderer,
)
from composeui.webcore._renderers.charts import WebChartRenderer
from composeui.webcore._renderers.choices import (
    WebCheckListRenderer,
    WebComboBoxRenderer,
    WebMultiComboBoxRenderer,
    WebRadioGroupRenderer,
    WebTreeRenderer,
)
from composeui.webcore._renderers.containers import (
    WebExpanderRenderer,
    WebGridRenderer,
    WebHorizontalRenderer,
    WebListRenderer,
    WebPageRenderer,
    WebSplitterRenderer,
    WebTabPageRenderer,
    WebTabsRenderer,
    WebVerticalRenderer,
)
from composeui.webcore._renderers.content import (
    WebConsoleRenderer,
    WebImageRenderer,
    WebLabelRenderer,
    WebLogRenderer,
    WebMarkdownRenderer,
    WebMetricRenderer,
    WebNotificationBarRenderer,
    WebStatusBarRenderer,
)
from composeui.webcore._renderers.controls import (
    WebButtonRenderer,
    WebCheckBoxRenderer,
    WebDialogButtonRenderer,
    WebDownloadRenderer,
    WebFloatRangeSliderRenderer,
    WebFloatSliderRenderer,
    WebProgressBarRenderer,
    WebRangeSliderRenderer,
    WebSliderRenderer,
)
from composeui.webcore._renderers.dialogs import WebDialogRenderer, WebFormDialogRenderer
from composeui.webcore._renderers.files import (
    WebFilePathInputRenderer,
    WebFileUploadRenderer,
    WebFolderPathInputRenderer,
    WebSavePathInputRenderer,
)
from composeui.webcore._renderers.forms import (
    WebFormLabelRenderer,
    WebFormRenderer,
    WebGroupFormRenderer,
)
from composeui.webcore._renderers.graphics import WebDrawingRenderer, WebMapRenderer
from composeui.webcore._renderers.inputs import (
    WebDateInputRenderer,
    WebDateRangeInputRenderer,
    WebFloatInputRenderer,
    WebInputRenderer,
    WebIntInputRenderer,
    WebTextAreaRenderer,
)
from composeui.webcore._renderers.navigation import (
    WebMainRenderer,
    WebRouterRenderer,
    WebSidebarRenderer,
)
from composeui.webcore._renderers.tables import WebSourceTableRenderer, WebTableRenderer

if TYPE_CHECKING:
    from composeui.core.renderer import Renderer

#: renderer keys of the web backend, looked up by `composeui.core.registry.create_renderer`
RENDERERS: Final[dict[str, Callable[[Any], Renderer[Any, Any]]]] = {
    "action": WebActionRenderer,
    "button": WebButtonRenderer,
    "download": WebDownloadRenderer,
    "dialog_button": WebDialogButtonRenderer,
    "chart": WebChartRenderer,
    "drawing": WebDrawingRenderer,
    "map": WebMapRenderer,
    "checkbox": WebCheckBoxRenderer,
    "check_list": WebCheckListRenderer,
    "combobox": WebComboBoxRenderer,
    "source_table": WebSourceTableRenderer,
    "date_input": WebDateInputRenderer,
    "date_range_input": WebDateRangeInputRenderer,
    "file_path_input": WebFilePathInputRenderer,
    "file_upload": WebFileUploadRenderer,
    "folder_path_input": WebFolderPathInputRenderer,
    "save_path_input": WebSavePathInputRenderer,
    "dialog": WebDialogRenderer,
    "expander": WebExpanderRenderer,
    "float_input": WebFloatInputRenderer,
    "int_input": WebIntInputRenderer,
    "form": WebFormRenderer,
    "content_dialog": WebFormDialogRenderer,
    "form_dialog": WebFormDialogRenderer,
    "form_label": WebFormLabelRenderer,
    "grid": WebGridRenderer,
    "group_form": WebGroupFormRenderer,
    "horizontal": WebHorizontalRenderer,
    "input": WebInputRenderer,
    "label": WebLabelRenderer,
    "list": WebListRenderer,
    "log": WebLogRenderer,
    "main": WebMainRenderer,
    "image": WebImageRenderer,
    "markdown": WebMarkdownRenderer,
    "console": WebConsoleRenderer,
    "menu": WebMenuRenderer,
    "metric": WebMetricRenderer,
    "multi_combobox": WebMultiComboBoxRenderer,
    "page": WebPageRenderer,
    "progress_bar": WebProgressBarRenderer,
    "slider": WebSliderRenderer,
    "float_range_slider": WebFloatRangeSliderRenderer,
    "float_slider": WebFloatSliderRenderer,
    "radio_group": WebRadioGroupRenderer,
    "range_slider": WebRangeSliderRenderer,
    "router": WebRouterRenderer,
    "separator": WebSeparatorRenderer,
    "sidebar": WebSidebarRenderer,
    "splitter": WebSplitterRenderer,
    "notification_bar": WebNotificationBarRenderer,
    "status_bar": WebStatusBarRenderer,
    "table": WebTableRenderer,
    "text_area": WebTextAreaRenderer,
    "tab_page": WebTabPageRenderer,
    "tabs": WebTabsRenderer,
    "toolbar": WebToolBarRenderer,
    "tree": WebTreeRenderer,
    "vertical": WebVerticalRenderer,
}
