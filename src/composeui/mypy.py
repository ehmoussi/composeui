"""Mypy integration for CSV row classes and field factories."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mypy.nodes import AssignmentStmt, CallExpr, MemberExpr, RefExpr, TypeInfo
from mypy.plugin import Plugin
from mypy.plugins.attrs import attr_attrib_makers, attr_class_maker_callback, attr_define_makers

if TYPE_CHECKING:
    from collections.abc import Callable

    from mypy.plugin import ClassDefContext


_DEFINE_ROW = "composeui.core.sqlitemodel.define_csv_row"


def _define_csv_row(ctx: ClassDefContext) -> bool:
    # Mypy's attrs plugin expects converter references to have a resolved node.
    # Built-in method descriptors (e.g. str.strip) need their owning type's symbol.
    for statement in ctx.cls.defs.body:
        if not isinstance(statement, AssignmentStmt) or not isinstance(statement.rvalue, CallExpr):
            continue
        for name, expression in zip(statement.rvalue.arg_names, statement.rvalue.args):
            if name != "converter" or not isinstance(expression, MemberExpr):
                continue
            owner = expression.expr
            if isinstance(owner, RefExpr) and isinstance(owner.node, TypeInfo):
                symbol = owner.node.get(expression.name)
                if symbol is not None:
                    expression.node = symbol.node
    return attr_class_maker_callback(ctx, auto_attribs_default=None, slots_default=True)


class _CSVPlugin(Plugin):
    def get_class_decorator_hook_2(self, fullname: str) -> Callable[[ClassDefContext], bool] | None:
        return _define_csv_row if fullname == _DEFINE_ROW else None


def plugin(_version: str) -> type[Plugin]:
    """Register the CSV field factory and row decorator with mypy's attrs plugin."""
    attr_attrib_makers.add("composeui.core.sqlitemodel.csv_field")
    attr_define_makers.add(_DEFINE_ROW)
    return _CSVPlugin
