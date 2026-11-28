"""Where the app runs for its user: what its client can do (`ClientCapabilities`).

The same app may run on the user's own computer (Qt, Textual, a local web server) or on
another one that the user reaches through a browser or a terminal. `MainView.open_folder`,
`open_file`, `open_url` and `display_path` adapt to it. An app reads `MainView.client` only
to hide or change a control, such as an "Open folder" button that can't work.
"""

from __future__ import annotations

import contextlib
import contextvars
import getpass
import os
import subprocess
import sys
from typing import TYPE_CHECKING, ClassVar, Optional
from urllib.parse import urlsplit

import attrs

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

__all__ = ["ClientCapabilities"]

#: the schemes that `MainView.open_url` opens: a page, never a program or a file. Not
#: ``mailto``: on the web, its new tab would stay blank once the mail app opens
URL_SCHEMES = ("http", "https")


@attrs.frozen(kw_only=True)
class ClientCapabilities:
    """What the app can do for its user, from where it runs for them.

    Each backend sets it: Qt runs on the user's computer (`local`), and so does Textual,
    unless it runs over SSH or ``textual-serve``, where the app can't reach the user's
    desktop. The web serves users on other computers (`served`), unless
    ``WebSettings(client=ClientCapabilities.local())`` says that the server runs on the
    user's own computer, outside a container: nothing in a request can tell.
    """

    #: Whether a path in the app is the same path for the user: on their computer, or in
    #: the shell that runs a terminal app.
    shares_files: bool
    #: Whether `MainView.open_folder` and `open_file` open on the user's desktop: in its
    #: file manager or the file's app.
    can_open_on_desktop: bool
    #: Whether several people may use this process at once, as on a web server. It says
    #: how the app is deployed, not who the user is.
    multi_user: bool

    @classmethod
    def local(cls) -> ClientCapabilities:
        """Get the capabilities of an app on its user's own computer: Qt's."""
        return cls(shares_files=True, can_open_on_desktop=True, multi_user=False)

    @classmethod
    def served(cls) -> ClientCapabilities:
        """Get the capabilities of an app that a server runs for users on other computers."""
        return cls(shares_files=False, can_open_on_desktop=False, multi_user=True)


class _Current:
    """The capabilities of the app this process runs, from the start of its build."""

    capabilities: ClassVar[Optional[ClientCapabilities]] = None


def current_client() -> ClientCapabilities:
    """Get the capabilities the app running set; `local` while no app runs, e.g. in a test."""
    return ClientCapabilities.local() if _Current.capabilities is None else _Current.capabilities


def set_client(capabilities: ClientCapabilities) -> None:
    """Set the capabilities of the app this process runs: its `Application` does it."""
    _Current.capabilities = capabilities


#: what gives the browser's id to the main views built meanwhile: a web session's, built
#: for a request, which makes the id only once a main view asks, so that a request that
#: builds none sets no cookie
_BROWSER_ID: contextvars.ContextVar[Optional[Callable[[], str]]] = contextvars.ContextVar(
    "composeui_browser_id", default=None
)
#: the id of an account whose name can't be found, e.g. in a container without an entry
#: for its user
UNKNOWN_ACCOUNT = "local"


#: the user whom a web session's main views are built for (`MainView.user`)
_USER: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "composeui_user", default=None
)


@contextlib.contextmanager
def building_for_browser(browser_id: Callable[[], str], user: str | None = None) -> Iterator[None]:
    """Give the main views built inside the id that `browser_id` returns, and `user`."""
    token = _BROWSER_ID.set(browser_id)
    user_token = _USER.set(user)
    try:
        yield
    finally:
        _USER.reset(user_token)
        _BROWSER_ID.reset(token)


def current_user() -> str | None:
    """Get the user whom a main view is built for; None without a login (`MainView.user`)."""
    return _USER.get()


def current_browser_id() -> str:
    """Get the id of the browser a main view is built for; elsewhere, the user's account."""
    browser_id = _BROWSER_ID.get()
    if browser_id is not None:
        return browser_id()
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        # OSError from Python 3.13, before it KeyError (POSIX) or ImportError (Windows)
        return UNKNOWN_ACCOUNT


def check_url(url: str) -> None:
    """Raise `ValueError` for a URL that `MainView.open_url` doesn't open (`URL_SCHEMES`)."""
    if urlsplit(url).scheme not in URL_SCHEMES:
        msg = f"Can't open {url!r}: only {', '.join(URL_SCHEMES)} URLs open"
        raise ValueError(msg)


def launch(target: str) -> None:
    """Open `target`, a path or a URL, with the desktop's default app; don't wait for it.

    Raises `OSError`, or `subprocess.SubprocessError`, when the opener can't start. In WSL,
    Windows opens it, given the Windows form of a path: Linux has no desktop there.
    """
    if sys.platform == "win32":
        os.startfile(target)  # noqa: S606 (the desktop's own opener, given one path or URL)
        return
    if sys.platform == "darwin":
        command = ["open", target]
    elif "WSL_DISTRO_NAME" in os.environ:
        windows = target if urlsplit(target).scheme else _windows_path(target)
        # not explorer.exe: it cuts its argument at a comma, which WSL quotes only with a
        # space in it (a folder ``a,b`` opened Documents, a URL with one nothing)
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Start-Process -FilePath {_powershell_text(windows)}",
        ]
    else:
        command = ["xdg-open", target]
    # its own session: Ctrl+C in the app's terminal doesn't stop the app that it opened
    subprocess.Popen(  # noqa: S603 (a fixed opener, given one path or URL)
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


#: the quotes that end PowerShell's text in single quotes, each written twice inside it
_POWERSHELL_QUOTES = "'\u2018\u2019\u201a\u201b"


def _powershell_text(text: str) -> str:
    """Get `text` as PowerShell's literal text, which expands no variable or command."""
    for quote in _POWERSHELL_QUOTES:
        text = text.replace(quote, quote * 2)
    return f"'{text}'"


def _windows_path(path: str) -> str:
    r"""Get the path Windows gives a WSL path, e.g. ``\\wsl.localhost\Ubuntu\home``."""
    done = subprocess.run(  # noqa: S603 (WSL's own converter, given one path)
        ["wslpath", "-w", path],  # noqa: S607 (on the PATH of every WSL)
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()
