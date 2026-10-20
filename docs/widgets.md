# Widget catalog

This catalog lists each view that a backend renders, in the order of `composeui.core.view`.
Each name links to its [API reference](api/view.md). The
[user guide](user-guide.md#widgets) shows how to use them. Qt, Textual, and the web render
every view of this catalog.

## Views

These views have a renderer of their own (their `_renderer_key`).

```{widget-catalog}
:kind: views
```

## Form rows

A form row is a field with its label, in a `FormView`. The form renders the row, and the
field of the row has the renderer of the view in the second column (its
`_field_renderer_key`).

```{widget-catalog}
:kind: form-rows
```
