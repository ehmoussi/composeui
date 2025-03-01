import contextlib
import sys

if sys.version_info >= (3, 8):
    from importlib.metadata import PackageNotFoundError, version
else:
    from importlib_metadata import PackageNotFoundError, version

with contextlib.suppress(PackageNotFoundError):
    __version__ = version("package-name")

if sys.version_info >= (3, 8):
    from importlib.metadata import version

    get_version = version
else:
    from importlib_metadata import version

    get_version = version
