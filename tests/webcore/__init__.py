"""The web backend's tests: a module per family of `webcore/_renderers/` or module of `webcore`.

Editing a field posts the browser event to `/_composeui/widget/{id}`; the response carries every
fragment the event changed as an htmx out-of-band swap, except the field itself, which
is never swapped back while the user is typing in it. The hello example and
`examples/pipeform` are driven over HTTP; a few renderer-level cases drive rows
directly through `handle_event`, the function the route calls. `conftest.py` holds the
fixtures that several modules use, and `support.py` the helpers.
"""
