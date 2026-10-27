from __future__ import annotations

from importlib.metadata import version

from composeui.core.application import LOGGER
from composeui.core.signal import LOGGER as SIGNAL_LOGGER

__all__ = ["LOGGER", "SIGNAL_LOGGER", "__version__"]

#: the version of the installed package, from its tag (setuptools-scm)
__version__ = version("composeui")
