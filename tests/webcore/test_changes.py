"""Tests of the changes that come with a response: what code, jobs and threads change."""

from __future__ import annotations

import sys
import threading
import time
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.view import (
    ButtonView,
    MainView,
    TableView,
    child,
    define_view,
)
from composeui.webcore.changes import collect_dirty
from composeui.webcore.page import JOBS_POLL_MS
from composeui.webcore.session import WebSession
from composeui.webcore.webrenderer import (
    WebRenderer,
    render_dirty,
)

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from composeui.core.jobs import Job
    from examples.pipeform import PipeMainView
    from examples.webhello import HelloMainView
    from tests.pages import PagesMainView

from tests.webcore.support import _element, _field_id, _find, _part, _swapped, _widget_id


def test_one_keystroke_fans_out_to_the_log_the_summary_and_the_status_bar(
    main_view: HelloMainView, client: TestClient
) -> None:
    assert main_view.form.name.log_message == "A name is mandatory"
    input_id = _field_id(main_view.form.name)

    body = client.post(
        f"/_composeui/widget/{input_id}", data={"value": "Bob", "event": "input"}
    ).text

    assert main_view.form.name.text == "Bob"
    assert "hidden" in _swapped(body, _widget_id(_part(main_view.form.name, "log"))).attributes
    summary = _swapped(body, _widget_id(main_view.summary.renderer))
    assert summary.text == "Bob hasn't said how old they are."
    assert _swapped(body, _widget_id(main_view.status_bar.renderer)).text == "Hello, Bob!"
    assert _find(body, input_id) is None  # the field being typed in is never swapped back


def test_a_changed_field_inside_a_changed_group_is_swapped_once(
    pipe_main_view: PipeMainView,
) -> None:
    main_pipe = pipe_main_view.pages.inputs.pipe_form.main_pipe
    group, radius = main_pipe.renderer, _part(main_pipe.radius, "field")
    assert isinstance(group, WebRenderer)

    with collect_dirty() as dirty:
        main_pipe.is_enabled = False
        main_pipe.radius.value = 1.0
    body = render_dirty(dirty)

    assert set(dirty) == {group.widget_id, radius.widget_id}
    # htmx would swap it twice otherwise: it only arrives within its group's fragment
    assert body.count(f'id="{radius.widget_id}"') == 1
    assert "hx-swap-oob" not in _element(body, radius.widget_id).attributes
    assert _swapped(body, group.widget_id).tag == "fieldset"


def test_the_page_asks_for_what_jobs_change_while_they_run(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    page = pages_client.get("/results").text
    assert "hx-get" not in _element(page, "cui-jobs").attributes  # no job yet
    (main_view,) = pages_views
    results, submit = main_view.router.results, main_view.router.inputs.submit
    total_id = _widget_id(results.total.renderer)
    release = threading.Event()

    def work(_job: Job[int]) -> int:
        release.wait(10)
        return 7

    def show(total: int) -> None:
        results.total.text = f"Total: {total}"

    def start() -> None:
        main_view.jobs.start(work).finished.connect(show)

    submit.clicked.connect(start)
    response = pages_client.post(
        f"/_composeui/widget/{_widget_id(submit.renderer)}", data={"event": "click"}
    )
    poller = _swapped(response.text, "cui-jobs").attributes
    assert poller["hx-get"] == "/_composeui/jobs"
    assert poller["hx-trigger"] == f"load delay:{JOBS_POLL_MS}ms"
    assert poller["hx-swap"] == "outerHTML"
    assert "hx-get" in _element(pages_client.get("/_composeui/jobs").text, "cui-jobs").attributes

    release.set()
    deadline = time.monotonic() + 10
    while main_view.jobs.is_running and time.monotonic() < deadline:
        time.sleep(0.01)
    polled = pages_client.get("/_composeui/jobs").text

    assert "hx-get" not in _element(polled, "cui-jobs").attributes  # over: done asking
    assert _swapped(polled, total_id).text == "Total: 7"


def test_the_page_asks_once_a_wait_while_a_task_only_waits_for_its_next_run(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    pages_client.get("/results")
    (main_view,) = pages_views
    task = main_view.jobs.task(lambda _job: 7, every=2.5)
    submit = main_view.router.inputs.submit

    def start() -> None:
        task.start()

    submit.clicked.connect(start)
    pages_client.post(f"/_composeui/widget/{_widget_id(submit.renderer)}", data={"event": "click"})
    deadline = time.monotonic() + 10
    while not task.has_result and time.monotonic() < deadline:
        time.sleep(0.01)
    poller = _element(pages_client.get("/_composeui/jobs").text, "cui-jobs").attributes

    assert poller["hx-trigger"] == "load delay:2500ms"  # not every 300 ms until the next run

    task.cancel()
    assert (
        "hx-get" not in _element(pages_client.get("/_composeui/jobs").text, "cui-jobs").attributes
    )


@define_view
class GuestsMainView(MainView):
    guests: TableView = child(TableView, headers=["Name"])
    add: ButtonView = child(ButtonView, text="Add")


def test_a_row_added_with_plus_equals_comes_with_the_response() -> None:
    main_view = GuestsMainView()
    session = WebSession(main_view)

    def add() -> None:
        # in place before, the same list set back: the table saw no change
        main_view.guests.rows += [["Ada"]]

    main_view.add.clicked.connect(add)
    response = session.handle_event(_widget_id(main_view.add.renderer), "click", {})

    assert response is not None
    table_id = _widget_id(main_view.guests.renderer)
    assert "Ada" in _swapped(response[0], table_id).text


def test_a_job_s_finished_callback_starts_the_next_job(
    pages_views: list[PagesMainView], pages_client: TestClient
) -> None:
    pages_client.get("/results")
    (main_view,) = pages_views
    results, submit = main_view.router.results, main_view.router.inputs.submit
    total_id = _widget_id(results.total.renderer)

    def first(_job: Job[int]) -> int:
        return 3

    def second(_job: Job[int], value: int) -> int:
        return value * 2

    def show(total: int) -> None:
        results.total.text = f"Total: {total}"

    def start_second(value: int) -> None:
        # the web runs it in the first job's thread, under the session's lock
        main_view.jobs.start(second, value).finished.connect(show)

    def start() -> None:
        main_view.jobs.start(first).finished.connect(start_second)

    submit.clicked.connect(start)
    pages_client.post(f"/_composeui/widget/{_widget_id(submit.renderer)}", data={"event": "click"})
    deadline = time.monotonic() + 10
    while results.total.text != "Total: 6" and time.monotonic() < deadline:
        time.sleep(0.01)

    assert _swapped(pages_client.get("/_composeui/jobs").text, total_id).text == "Total: 6"


# handed over by the view it changes, or by the main view, as an app does
@pytest.mark.parametrize("through_main_view", [False, True])
def test_what_a_thread_changes_comes_with_the_session_s_next_response(
    pages_views: list[PagesMainView], pages_client: TestClient, *, through_main_view: bool
) -> None:
    pages_client.get("/results")
    (main_view,) = pages_views
    results, submit = main_view.router.results, main_view.router.inputs.submit
    bar_id, total_id = _widget_id(results.progress.renderer), _widget_id(results.total.renderer)

    def work(value: int) -> None:
        def advance() -> None:
            results.progress.value = value
            results.total.text = f"Total: {value}"

        renderer = (main_view if through_main_view else results.progress).renderer
        assert renderer is not None
        worker = threading.Thread(target=renderer.call_on_main_thread, args=(advance,))
        worker.start()
        worker.join()

    work(40)
    fetched = pages_client.get(f"/_composeui/widget/{bar_id}").text
    assert _element(fetched, bar_id).attributes["value"] == "40"
    assert "hx-swap-oob" not in _element(fetched, bar_id).attributes  # the fetch's own swap
    assert _swapped(fetched, total_id).text == "Total: 40"
    # sent once
    assert _find(pages_client.get(f"/_composeui/widget/{bar_id}").text, total_id) is None

    work(50)
    response = pages_client.post(
        f"/_composeui/widget/{_widget_id(submit.renderer)}", data={"event": "click"}
    )
    assert _swapped(response.text, bar_id).attributes["value"] == "50"
    # changed by both, swapped once, as the click left it
    assert response.text.count(f'id="{total_id}"') == 1
    assert _swapped(response.text, total_id).text == "Submitted: "

    work(60)
    assert _element(pages_client.get("/results").text, total_id).text == "Total: 60"
    assert (
        _find(pages_client.get(f"/_composeui/widget/{bar_id}").text, total_id) is None
    )  # shown already
