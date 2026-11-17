"""The `widget-catalog` directive: a table of the views of `composeui.core.view`.

Built from the views' renderer keys and the backends' ``RENDERERS``, so a new view, or a
backend that renders it, enters the catalog without editing it.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import TYPE_CHECKING, Any, ClassVar

from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective

from composeui.core import _views as views_package
from composeui.core import view as view_module
from composeui.core.registry import RendererType

if TYPE_CHECKING:
    from types import ModuleType

    from docutils import nodes
    from sphinx.application import Sphinx

_KEY_ATTRIBUTES = {"views": "_renderer_key", "form-rows": "_field_renderer_key"}


def _family_modules() -> list[ModuleType]:
    """Get the modules of `composeui.core._views`, which define the views of each family."""
    return [
        importlib.import_module(f"{views_package.__name__}.{info.name}")
        for info in pkgutil.iter_modules(views_package.__path__)
    ]


def _catalog(key_attribute: str) -> list[tuple[str, str, str]]:
    """List the public views with a key in `key_attribute`: (name, key, summary).

    By family, the module that defines them, then in their order there.
    """
    views = [
        cls
        for module in _family_modules()
        for name, cls in vars(module).items()
        if inspect.isclass(cls)
        and not name.startswith("_")
        and cls.__module__ == module.__name__
        and issubclass(cls, view_module.View)
        and getattr(cls, key_attribute, None) is not None
    ]
    views.sort(key=lambda cls: (cls.__module__, inspect.getsourcelines(cls)[1]))
    rows = []
    for cls in views:
        # only the view's own docstring: an undocumented view says nothing rather than
        # its base's summary
        doc = inspect.cleandoc(cls.__dict__.get("__doc__") or "")
        rows.append((cls.__name__, getattr(cls, key_attribute), doc.split("\n\n")[0]))
    return rows


def _registered_keys() -> dict[RendererType, set[str]]:
    """Give the renderer keys that each backend registers."""
    return {
        renderer_type: set(importlib.import_module(renderer_type.value.renderers).RENDERERS)
        for renderer_type in RendererType
    }


class WidgetCatalog(SphinxDirective):
    option_spec: ClassVar[dict[str, Any]] = {
        "kind": lambda argument: directives.choice(argument, list(_KEY_ATTRIBUTES)),
    }

    def run(self) -> list[nodes.Node]:
        key_column = "Field renderer" if self.options["kind"] == "form-rows" else "Renderer"
        registered = _registered_keys()
        backends = "".join(f" {renderer_type.name.title()} |" for renderer_type in registered)
        # the directive is used in MyST pages, which parse nested text as Markdown
        lines = [
            f"| View | {key_column} |{backends} What it shows |",
            "| --- | --- |" + " :-: |" * len(registered) + " --- |",
        ]
        for name, key, summary in _catalog(_KEY_ATTRIBUTES[self.options["kind"]]):
            text = " ".join(summary.split()).replace("|", "\\|")
            shown = "".join(f" {'✓' if key in keys else '—'} |" for keys in registered.values())
            lines.append(f"| {{py:class}}`~composeui.core.view.{name}` | `{key}` |{shown} {text} |")
        return self.parse_text_to_nodes("\n".join(lines))  # type: ignore[no-any-return]


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("widget-catalog", WidgetCatalog)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
