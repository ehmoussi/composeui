"""Tests of where the app runs for its user: `ClientCapabilities` and the actions that adapt."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from composeui.core import client as client_module
from composeui.core.application import Application, WebSettings
from composeui.core.client import ClientCapabilities
from composeui.core.jobs import CalledInJobError, Job
from composeui.core.model import Model
from composeui.core.view import LogType, MainView
from tests.opening import HELP_URL, OpeningMainView

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture(autouse=True)
def _no_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leave no app's backend or capabilities to the next tests: building an app sets them."""
    monkeypatch.setattr("composeui.core.application._Running.backend", None)
    monkeypatch.setattr("composeui.core.client._Current.capabilities", None)


@pytest.fixture
def launched(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record what the desktop is asked to open, rather than open it."""
    targets: list[str] = []
    monkeypatch.setattr("composeui.core._views.main.launch", targets.append)
    return targets


def _as(monkeypatch: pytest.MonkeyPatch, capabilities: ClientCapabilities) -> None:
    """Run the test as an app with `capabilities` does, without building one."""
    monkeypatch.setattr("composeui.core.client._Current.capabilities", capabilities)


#: how WSL opens a path or a URL: Windows' PowerShell, which reads no profile and asks nothing
_POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]


@pytest.mark.parametrize(
    ("platform", "environment", "target", "command"),
    [
        ("darwin", {}, "/srv/runs", ["open", "/srv/runs"]),
        ("linux", {}, "/srv/runs", ["xdg-open", "/srv/runs"]),
        ("linux", {}, HELP_URL, ["xdg-open", HELP_URL]),
        # WSL has no desktop of its own: Windows opens the path it gives the Linux one,
        # quoted for PowerShell: Explorer would cut it at a comma
        (
            "linux",
            {"WSL_DISTRO_NAME": "Ubuntu"},
            "/srv/a,b",
            [*_POWERSHELL, r"Start-Process -FilePath 'C:\srv\a,b'"],
        ),
        # each quote that ends PowerShell's text written twice: none ends it early
        (
            "linux",
            {"WSL_DISTRO_NAME": "Ubuntu"},
            "https://example.org/runs?ids=1,2&by=it's\u2018\u2019\u201a\u201b$(x)",
            [
                *_POWERSHELL,
                "Start-Process -FilePath"
                " 'https://example.org/runs?ids=1,2&by=it''s"
                "\u2018\u2018\u2019\u2019\u201a\u201a\u201b\u201b$(x)'",
            ],
        ),
    ],
)
def test_the_desktop_s_own_opener_opens_a_path_or_a_url_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    environment: dict[str, str],
    target: str,
    command: list[str],
) -> None:
    started: list[tuple[list[str], dict[str, Any]]] = []
    converted: list[list[str]] = []

    def run(arguments: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        converted.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, stdout="C:\\srv\\a,b\n")

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: started.append((args, kw)))

    client_module.launch(target)

    ((arguments, options),) = started
    assert arguments == command
    assert options["start_new_session"]  # Ctrl+C in the app's terminal leaves it open
    # the opener's messages would cover a terminal app
    assert options["stdout"] == options["stderr"] == subprocess.DEVNULL
    assert converted == ([["wslpath", "-w", target]] if target == "/srv/a,b" else [])


def test_windows_opens_a_path_or_a_url_with_its_own_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("os.startfile", opened.append, raising=False)

    client_module.launch(r"C:\runs")

    assert opened == [r"C:\runs"]


def test_a_main_view_opens_a_folder_or_a_file_on_the_desktop_it_reaches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, launched: list[str]
) -> None:
    _as(monkeypatch, ClientCapabilities.local())
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    view = MainView()

    view.open_folder(tmp_path)
    view.open_file(report)
    view.open_url(HELP_URL)

    assert launched == [str(tmp_path), str(report), HELP_URL]
    assert view.notification.message == ""
    view.open_folder(report)  # a file, not a folder
    view.open_file(tmp_path / "gone.pdf")
    assert launched == [str(tmp_path), str(report), HELP_URL]
    assert (view.notification.message, view.notification.kind) == (
        f"Can't open {tmp_path / 'gone.pdf'}: it isn't there.",
        LogType.ERROR,
    )


def test_a_main_view_says_why_the_desktop_s_opener_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(_target: str) -> None:
        raise FileNotFoundError(2, "No such file or directory", "xdg-open")

    _as(monkeypatch, ClientCapabilities.local())
    monkeypatch.setattr("composeui.core._views.main.launch", fail)
    view = MainView()

    view.open_folder(tmp_path)

    assert view.notification.kind is LogType.ERROR
    assert view.notification.message == (
        f"Can't open {tmp_path}: [Errno 2] No such file or directory: 'xdg-open'."
    )


def test_a_served_main_view_tells_its_user_rather_than_open_on_the_server_s_desktop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, launched: list[str]
) -> None:
    _as(monkeypatch, ClientCapabilities.served())
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    view = MainView()

    view.open_folder(tmp_path)
    assert (view.notification.message, view.notification.kind) == (
        f"Can't open {tmp_path.name} here: the app runs on another computer.",
        LogType.WARNING,
    )
    view.open_file(report)  # nor a file, unless the app asks for a download
    view.open_file(report, download=True)
    view.open_file(tmp_path / "gone.pdf", download=True)
    assert view.notification.message == "Can't open gone.pdf: it isn't there."
    # neither a browser nor a desktop: e.g. Textual over SSH
    view.open_url(HELP_URL)
    assert view.notification.message == f"Open {HELP_URL} in your browser."

    assert launched == []
    assert [(file.filename, file.content) for file in view.downloads] == [("report.pdf", report)]


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "mailto:a@example.org", "/help", "calc"]
)
def test_only_web_pages_open_as_urls(launched: list[str], url: str) -> None:
    view = MainView()

    with pytest.raises(ValueError, match="only http, https URLs open"):
        view.open_url(url)

    view.open_url("HTTPS://example.org")  # a scheme in capitals is the same
    assert launched == ["HTTPS://example.org"]


@pytest.mark.parametrize("method", ["open_folder", "open_file", "open_url"])
def test_a_job_s_thread_can_t_open_anything_for_the_user(
    tmp_path: Path, launched: list[str], method: str
) -> None:
    view = MainView()
    target = HELP_URL if method == "open_url" else tmp_path
    refused: list[BaseException] = []

    def opening(_job: Job[None]) -> None:
        try:
            getattr(view, method)(target)
        except CalledInJobError as error:  # the job's finished callback can, on the main thread
            refused.append(error)

    view.jobs.start(opening)
    view.jobs.wait()

    assert [str(error).split(" must")[0] for error in refused] == [f"MainView.{method}"]
    assert launched == []


def test_a_path_shows_whole_where_the_user_shares_the_files_else_from_its_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results = tmp_path / "results"
    run = results / "run-3" / "out.csv"
    run.parent.mkdir(parents=True)
    named = tmp_path / "results" / ".." / "results"  # the root as the app names it
    view = MainView()
    _as(monkeypatch, ClientCapabilities.local())
    assert view.display_path(run, roots=[results]) == str(run)

    _as(monkeypatch, ClientCapabilities.served())

    assert view.display_path(run, roots=[tmp_path / "other", named]) == "results/run-3/out.csv"
    assert view.display_path(results, roots=[results]) == "results"
    assert view.display_path(run) == "out.csv"  # outside every root: its name alone
    assert view.display_path(tmp_path / "x.csv", roots=[results]) == "x.csv"


def _built(make_app: Callable[[Callable[[], MainView]], Application[MainView]]) -> list[Any]:
    """Get what the main view reads of its client as the app builds it."""
    seen: list[Any] = []

    def build() -> MainView:
        view = OpeningMainView()
        seen.append(view.client)
        return view

    make_app(build)
    return seen


def test_a_web_app_serves_other_computers_unless_its_settings_say_it_s_local() -> None:
    pytest.importorskip("starlette")
    from composeui.webcore.webapplication import WebApplication  # noqa: PLC0415 (its extra)

    served = _built(lambda build: WebApplication(build_main_view=build))
    local = _built(
        lambda build: WebApplication(
            build_main_view=build, settings=WebSettings(client=ClientCapabilities.local())
        )
    )

    assert served == [ClientCapabilities.served()]
    assert served[0].multi_user
    assert local == [ClientCapabilities.local()]


def test_a_qt_app_runs_on_its_user_s_computer() -> None:
    pytest.importorskip("qtpy")
    from composeui.qtcore.qtapplication import QtApplication  # noqa: PLC0415 (its extra)

    assert _built(lambda build: QtApplication(build_main_view=build)) == [
        ClientCapabilities.local()
    ]


@pytest.mark.parametrize(
    ("variable", "value", "reaches_desktop"),
    [
        (None, "", True),
        ("SSH_CONNECTION", "10.0.0.2 52144 10.0.0.1 22", False),
        ("SSH_TTY", "/dev/pts/3", False),
        # textual-serve runs the app in the user's browser
        ("TEXTUAL_DRIVER", "textual.drivers.web_driver:WebDriver", False),
    ],
)
def test_a_terminal_app_reaches_the_desktop_unless_it_runs_over_ssh_or_in_a_browser(
    monkeypatch: pytest.MonkeyPatch, variable: str | None, value: str, *, reaches_desktop: bool
) -> None:
    pytest.importorskip("textual")
    from composeui.textualcore.textualapplication import (  # noqa: PLC0415 (its extra)
        TextualApplication,
        TextualModelApplication,
    )

    for name in ("SSH_CONNECTION", "SSH_TTY", "TEXTUAL_DRIVER"):
        monkeypatch.delenv(name, raising=False)
    if variable is not None:
        monkeypatch.setenv(variable, value)
    expected = ClientCapabilities(
        shares_files=True, can_open_on_desktop=reaches_desktop, multi_user=False
    )

    plain = _built(lambda build: TextualApplication(build_main_view=build))
    with_model = _built(
        lambda build: TextualModelApplication(build_main_view=build, build_model=Model)
    )

    assert plain == with_model == [expected]
