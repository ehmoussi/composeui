# Extend ComposeUI

This page explains how to add a widget or a backend to ComposeUI.

## Add a widget

1. Define the view in the module of its family in `core/_views/`, and add it to the imports and
   the `__all__` of `core/view.py`. See [Views and renderers](architecture.md#views-and-renderers).
   Set its `_renderer_key` and give it a class docstring: the
   [widget catalog](development.md#documentation-site) shows its first paragraph.

   ```python
   @define_view
   class LabelView(LabelMixin, View):
       _renderer_key = "label"
   ```

2. In each backend, add a renderer and its `RENDERERS` entry (`"label": QtLabelRenderer`).
   Put it in its family's module in the backend's `_renderers/` package, and its entry in
   that backend's `renderers.py`.
   The renderer registers a handler per view attribute and creates its rendered object in
   `render`:

   ```python
   class QtLabelRenderer(QtWidgetRenderer[LabelViewLike, QLabel]):
       def __init__(self, view: LabelViewLike) -> None:
           super().__init__(view)
           self._refresh_dispatcher.update(
               {
                   "text": self._refresh_text,
               }
           )

       def render(self) -> None:
           if self._rendered_object is None:
               self._rendered_object = QLabel()
               self.refresh()

       @staticmethod
       def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
           rendered_object.setText(value)
   ```

   When the user can change the widget, `render` also connects the widget's signal to a
   method. The method sets the view attribute inside `stop_refresh()`, as `QtInputRenderer`
   does for the text of a `QLineEdit`.

   A web renderer has no widget to keep. It renders its fragment in `to_html`, and applies the
   browser's events to the view in `dispatch`. Its handlers mark it dirty (`_mark_dirty`). See
   [A button click on the web](web-backend.md#a-button-click-on-the-web). Put it in the module of its
   family in `webcore/_renderers/`, or in a new module for a new family, and its entry in
   `webcore/renderers.py`, not in `webrenderer.py` (see
   [Requests and updates](web-backend.md#requests-and-updates)).

3. Add tests for each backend that exercise the real rendered widgets. See
   [Tests](development.md#tests).
4. Document the widget in the [user guide](../user-guide.md), and delete its item in
   [`ROADMAP.md`](../../ROADMAP.md). When an example app uses the widget, update the
   [examples guide](../examples-guide.md) too.

## Add a backend

1. Add one `RendererType` member in `core/registry.py`, with the `Backend` paths of the new
   modules, and the extra in `pyproject.toml` that installs its dependencies.
2. In the renderers module of the new backend, add a `RENDERERS` mapping.
3. In its application module, add its application classes as `APPLICATION` and
   `MODEL_APPLICATION`. They are built from `build_main_view=`, plus `build_model=` and
   `setup_model=` for the model application.
4. Add the new backend's `RENDERERS` to
   `test_every_backend_registers_the_same_renderer_keys_except_graphical_maps` in
   `tests/test_renderer_registry.py`. Register each supported view; Textual omits maps.
   Then add tests for its renderers and its application. See
   [Tests](development.md#tests).
5. Add the backend and its extra to the "Backends" table of the
   [user guide](../user-guide/running-the-app.md#backends). In each feature section of the user
   guide, say what the new backend shows, as the section does for Qt, Textual, and the web.

The views (`core/view.py` and `core/_views/`) should not need changes. `run` reads the `--backend` choices from
`RendererType`, so the new backend is one of them.
