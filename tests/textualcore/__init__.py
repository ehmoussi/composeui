"""The Textual backend's tests, a module per family of `textualcore/_renderers/`.

These tests drive a real widget tree with Textual's headless `App.run_test()` pilot. The views
that Qt renders also render on Textual, take the user's input, and give their state back to
the view. `support.py` holds the helpers that several modules use.
"""
