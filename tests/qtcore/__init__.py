"""The Qt backend's tests, a module per family of `qtcore/_renderers/`.

These tests render a widget tree with Qt, check the state of the real widgets, and drive
them as the user does: typed keys, a click on a radio button, a triggered `QAction`. So they
check the round trip back into the view. `conftest.py` holds the fixtures that several
modules use, and `support.py` the helpers.
"""
