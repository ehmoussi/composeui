"""The `widget-catalog` directive: a table of the views of `composeui.core.view`.

Built from the views' renderer keys, so a new view enters the catalog without editing it.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, ClassVar

from docutils.parsers.rst import directives
from sphinx.util.docutils import SphinxDirective

from composeui.core import view as view_module

if TYPE_CHECKING:
    from docutils import nodes
    from sphinx.application import Sphinx

_KEY_ATTRIBUTES = {"views": "_renderer_key", "form-rows": "_field_renderer_key"}


def _catalog(key_attribute: str) -> list[tuple[str, str, str]]:
    """List the public views with a key in `key_attribute`: (name, key, summary), by line."""
    views = [
        cls
        for name, cls in vars(view_module).items()
        if inspect.isclass(cls)
        and not name.startswith("_")
        and cls.__module__ == view_module.__name__
        and issubclass(cls, view_module.View)
        and getattr(cls, key_attribute, None) is not None
    ]
    views.sort(key=lambda cls: inspect.getsourcelines(cls)[1])
    rows = []
    for cls in views:
        # only the view's own docstring: an undocumented view says nothing rather than
        # its base's summary
        doc = inspect.cleandoc(cls.__dict__.get("__doc__") or "")
        rows.append((cls.__name__, getattr(cls, key_attribute), doc.split("\n\n")[0]))
    return rows


class WidgetCatalog(SphinxDirective):
    option_spec: ClassVar[dict[str, Any]] = {
        "kind": lambda argument: directives.choice(argument, list(_KEY_ATTRIBUTES)),
    }

    def run(self) -> list[nodes.Node]:
        key_column = "Field renderer" if self.options["kind"] == "form-rows" else "Renderer"
        # the directive is used in MyST pages, which parse nested text as Markdown
        lines = [f"| View | {key_column} | What it shows |", "| --- | --- | --- |"]
        for name, key, summary in _catalog(_KEY_ATTRIBUTES[self.options["kind"]]):
            text = " ".join(summary.split()).replace("|", "\\|")
            lines.append(f"| {{py:class}}`~composeui.core.view.{name}` | `{key}` | {text} |")
        return self.parse_text_to_nodes("\n".join(lines))  # type: ignore[no-any-return]


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_directive("widget-catalog", WidgetCatalog)
    return {"parallel_read_safe": True, "parallel_write_safe": True}
