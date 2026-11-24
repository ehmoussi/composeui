"""The rules every backend follows, a module per family of views, run on each backend.

A test drives the real widgets through a driver per backend (`qtdriver.py`,
`textualdriver.py`, `webdriver.py`): typed keys on Qt and Textual, the posts the page sends
on the web. `support.py` holds what a driver does, and `conftest.py` the `driver` fixture,
which runs each test on each backend. A rule that only one backend can break, such as a
toolkit's order of events, stays in that backend's folder.
"""
