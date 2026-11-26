# Extend ComposeUI

This page explains how to add a widget or a backend to ComposeUI, and how a package outside
ComposeUI adds a widget.

## Add a widget

1. Define the view in the module of its family in `core/_views/`, and add it to the imports and
   the `__all__` of `core/view.py`. See [Views and renderers](architecture.md#views-and-renderers).
   Set its `_renderer_key` and give it a class docstring: the
   [widget catalog](development.md#documentation-site) shows its first paragraph.

   The examples below show only parts of `LabelView` and its Qt renderer. They omit imports,
   style handling, and line wrapping.

   ```python
   @define_view
   class LabelView(LabelMixin, View):
       """A label that shows text."""

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

       @override
       def render(self) -> None:
           if self._rendered_object is None:
               self._rendered_object = plain_label()
               self.refresh()

       @staticmethod
       def _refresh_text(_view: LabelViewLike, rendered_object: QLabel, value: str) -> None:
           rendered_object.setText(value)
   ```

   `plain_label()` tells Qt to display text as plain text, not as rich text. See the
   implementations for [Qt](../../src/composeui/qtcore/_renderers/content.py),
   [Textual](../../src/composeui/textualcore/_renderers/content.py), and
   [the web](../../src/composeui/webcore/_renderers/content.py).

   When the user can change the widget, `render` also connects the widget's signal to a
   method. The method sets the view attribute inside `stop_refresh()`, as `QtInputRenderer`
   does for the text of a `QLineEdit`.

   A web renderer has no widget to keep. It renders its fragment in `to_html`, and applies the
   browser's events to the view in `dispatch`. Its handlers mark it dirty (`_mark_dirty`). See
   [A button click on the web](web-backend.md#a-button-click-on-the-web). Put it in the module of
   its family in `webcore/_renderers/`, or in a new module for a new family, and its entry in
   `webcore/renderers.py`, not in `webrenderer.py` (see
   [Requests and updates](web-backend.md#requests-and-updates)).

3. Add tests for each backend that exercise the real rendered widgets. Put them in the module
   of the widget's family in `tests/qtcore/`, `tests/textualcore/` and `tests/webcore/`. See
   [Tests](development.md#tests). For example, `test_label_renderer_pushes_view_state_to_the_widget`
   in [`tests/qtcore/test_content.py`](../../tests/qtcore/test_content.py) checks that changing
   the view updates the widget.
4. Document the widget in the [user guide](../user-guide.md), and delete its item in
   [`ROADMAP.md`](../../ROADMAP.md). When an example app uses the widget, update the
   [examples guide](../examples-guide.md) too.

## Add a widget from another package

A package outside ComposeUI can add a view and its renderers without a change to ComposeUI. For
example, a view of CAD files needs a large native library that ComposeUI doesn't install.

1. Define the view with `define_view(renderer_key=...)`. The key starts with the name of the
   package's top-level module and a dot.

   ```python
   @define_view(renderer_key="composeui_cad.geometry")
   class GeometryView(View):
       """A CAD model read from a STEP file."""

       path: Optional[Path] = None
   ```

2. For each backend that shows the view, write a renderer as in [Add a widget](#add-a-widget).
   Put it in a module that only that backend imports, with a mapping like `RENDERERS`:

   ```python
   RENDERERS = {"composeui_cad.geometry": QtGeometryRenderer}
   ```

3. Declare each mapping with an entry point of the `composeui.renderers` group in the package's
   `pyproject.toml`. The name of the entry point is the backend: `qt`, `textual` or `web`.

   ```toml
   [project.entry-points."composeui.renderers"]
   qt = "composeui_cad.composeui.qt:RENDERERS"
   web = "composeui_cad.composeui.web:RENDERERS"
   ```

The backends then find the view's renderer:

- **ComposeUI's keys first.** A backend looks for a key in its own renderers first. Else it
  loads the renderers of the package that the key's first part names, such as `composeui_cad`.
  A view of ComposeUI never loads a package's renderers.
- **Only the package of the view.** When a package's renderers fail to import, the error stops
  the rendering of its own views and their check by `renders`, not of other views. To make a
  native library optional, the package leaves the key out of its mapping when the library is
  missing: the backend then doesn't show the view, and `renders` returns `False`.
- **Loaded again for each lookup.** The backend finds the entry points once, but it loads the
  package's renderers again for each lookup. So a reload shows a package installed from the
  program's folder as changed.
- **A partial package.** A backend that no package gives the key to doesn't show the view, as
  Textual doesn't show a `MapView`. `renders` tells the app.
- **Refused keys.** When the backend loads a package's renderers, it raises `ValueError` for a
  key that ComposeUI has, for a key that doesn't start with the name of the entry point's
  top-level module, and for a key that two distributions add. Only the first copy of a
  distribution on the path counts, as for an import.
- **No scripts of its own on the web.** The page serves only ComposeUI's scripts and
  stylesheets, so a web renderer of a package writes HTML that these scripts already handle.
- **One minor version.** The renderers' base classes, such as `QtWidgetRenderer` and
  `WebRenderer`, are not in the API and can change in any release. Pin ComposeUI to one minor
  version, such as `composeui>=0.5,<0.6`.

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

The views (`core/view.py` and `core/_views/`) should not need changes. `run` reads the `--backend`
choices from `RendererType`, so the new backend is one of them.
