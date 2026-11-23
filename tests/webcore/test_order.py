"""Tests of the order in which the web backend handles the posts of a page."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import TYPE_CHECKING, Any

import pytest

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from hypothesis import given
from hypothesis import strategies as st

from composeui.webcore.order import (
    ORDER_TIMEOUT,
    PAGE_FIELD,
    PAGE_HEADER,
    POST_FIELD,
    POST_HEADER,
    DuplicatePostError,
    PostOrder,
)
from tests.webcore.support import _action_id, _field_id

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from examples.webhello import HelloMainView

#: a page's id, as `page.js` makes one: the posts of one page are handled in their order
_PAGE = "0123456789abcdef0123456789abcdef"


def test_a_field_s_post_waits_for_the_one_its_page_sent_before_it(
    main_view: HelloMainView, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("composeui.webcore.order.ORDER_TIMEOUT", 0.3)
    started = time.monotonic()

    # the page's second post, numbered in its headers: the first never comes
    response = client.post(
        f"/_composeui/widget/{_field_id(main_view.form.name)}",
        data={"value": "Ada", "event": "input"},
        headers={PAGE_HEADER: _PAGE, POST_HEADER: "2"},
    )

    # it waited for its turn (at least about as long: asyncio may wake a little early)
    assert time.monotonic() - started >= 0.3 / 2
    assert (response.status_code, main_view.form.name.text) == (200, "Ada")


def test_save_s_form_waits_for_the_post_its_page_sent_before_it(
    main_view: HelloMainView, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("composeui.webcore.order.ORDER_TIMEOUT", 0.3)
    main_view.form.name.text = "Bob"
    save = {"trigger": _action_id(main_view.file_menu.save), PAGE_FIELD: _PAGE, POST_FIELD: "2"}
    started = time.monotonic()

    # the page's second post, numbered in its form's fields, as headers can't be
    response = client.post("/_composeui/state/download", data=save)

    assert time.monotonic() - started >= 0.3 / 2
    assert json.loads(response.text)["views"]["form"]["name"]["text"] == "Bob"


@st.composite
def _arrivals(draw: st.DrawFn) -> list[tuple[str, int]]:
    """Draw the posts of one to three pages, each numbered from 1, in any order of arrival."""
    counts = draw(st.lists(st.integers(1, 4), min_size=1, max_size=3))
    posts = [
        (f"{page:032x}", number)
        for page, count in enumerate(counts)
        for number in range(1, count + 1)
    ]
    return draw(st.permutations(posts))


@given(_arrivals())
def test_posts_arriving_in_any_order_are_handled_in_the_order_each_page_sent_them(
    arrivals: list[tuple[str, int]],
) -> None:
    async def handle_all() -> list[tuple[str, int]]:
        order = PostOrder()
        handled: list[tuple[str, int]] = []

        async def post(page: str, number: int) -> None:
            async with order.turn({PAGE_HEADER: page, POST_HEADER: str(number)}):
                handled.append((page, number))

        posts = []
        for page, number in arrivals:
            posts.append(asyncio.ensure_future(post(page, number)))
            await asyncio.sleep(0)  # on its way before the next one comes
        # all handled well before a turn times out: none waited for nothing
        await asyncio.wait_for(asyncio.gather(*posts), ORDER_TIMEOUT / 2)
        return handled

    handled = asyncio.run(handle_all())
    for page in {page for page, _ in arrivals}:
        numbers = [number for handled_page, number in handled if handled_page == page]
        assert numbers == sorted(numbers) == [n for p, n in sorted(arrivals) if p == page]


async def _send(order: PostOrder, handled: list[tuple[str, int]], page: str, number: int) -> Any:
    """Send a post, then let it go as far as it can before another post comes.

    Get its task: done once handled, else waiting for its turn.
    """

    async def post() -> None:
        async with order.turn({PAGE_HEADER: page, POST_HEADER: str(number)}):
            handled.append((page, number))

    task = asyncio.ensure_future(post())
    for _ in range(20):  # turns of the event loop, not time: a post waiting never ends
        await asyncio.sleep(0)
    return task


def test_a_duplicate_post_repeats_nothing_and_releases_no_later_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("composeui.webcore.order.ORDER_TIMEOUT", 60)

    async def handle_all() -> list[tuple[str, int]]:
        order = PostOrder()
        handled: list[tuple[str, int]] = []
        may_end = asyncio.Event()

        async def original() -> None:
            async with order.turn({PAGE_HEADER: _PAGE, POST_HEADER: "1"}):
                await may_end.wait()
                handled.append((_PAGE, 1))

        first = asyncio.ensure_future(original())
        await asyncio.sleep(0)
        with pytest.raises(DuplicatePostError):
            await (await _send(order, handled, _PAGE, 1))
        second = await _send(order, handled, _PAGE, 2)
        assert not second.done()  # the original is still running

        may_end.set()
        await asyncio.wait_for(asyncio.gather(first, second), 10)
        with pytest.raises(DuplicatePostError):  # once ended too
            await (await _send(order, handled, _PAGE, 2))
        return handled

    assert asyncio.run(handle_all()) == [(_PAGE, 1), (_PAGE, 2)]


def test_a_page_remembers_only_its_latest_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("composeui.webcore.order._MAX_SEEN", 1)

    async def handle_all() -> list[tuple[str, int]]:
        order = PostOrder()
        handled: list[tuple[str, int]] = []
        await _send(order, handled, _PAGE, 1)
        await _send(order, handled, _PAGE, 2)
        await _send(order, handled, _PAGE, 1)  # forgotten: as a new post
        return handled

    assert asyncio.run(handle_all()) == [(_PAGE, 1), (_PAGE, 2), (_PAGE, 1)]


def test_a_duplicate_post_gets_an_empty_answer_and_changes_nothing(
    main_view: HelloMainView, client: TestClient
) -> None:
    age_id = _field_id(main_view.form.age)
    headers = {PAGE_HEADER: _PAGE, POST_HEADER: "1"}
    data = {"value": "3", "event": "input"}
    assert (
        client.post(f"/_composeui/widget/{age_id}", data=data, headers=headers).status_code == 200
    )
    main_view.form.age.value = 9.0

    response = client.post(f"/_composeui/widget/{age_id}", data=data, headers=headers)

    assert (response.status_code, response.text) == (204, "")
    assert main_view.form.age.value == 9.0


def test_a_post_waits_for_a_missing_one_only_so_long(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handle_all() -> list[tuple[str, int]]:
        order = PostOrder()
        handled: list[tuple[str, int]] = []
        timeout = 0.05
        monkeypatch.setattr("composeui.webcore.order.ORDER_TIMEOUT", timeout)
        # the first one never comes, e.g. aborted by the page: the second one is handled,
        # once its wait ends (bounded, with a wide margin: a wait that never ends fails)
        await asyncio.wait_for(await _send(order, handled, _PAGE, 2), 100 * timeout)
        # no other wait: one coming after its turn is handled at once, the next ones' kept
        monkeypatch.setattr("composeui.webcore.order.ORDER_TIMEOUT", 60)
        late, third = await _send(order, handled, _PAGE, 1), await _send(order, handled, _PAGE, 3)
        assert (late.done(), third.done()) == (True, True)
        return handled

    assert asyncio.run(handle_all()) == [(_PAGE, 2), (_PAGE, 1), (_PAGE, 3)]


def test_a_page_forgotten_for_newer_ones_waits_for_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("composeui.webcore.order.MAX_PAGES", 1)
    monkeypatch.setattr("composeui.webcore.order.ORDER_TIMEOUT", 60)
    other_page = "f" * 32  # e.g. the same app in another tab

    async def handle_all() -> list[tuple[str, int]]:
        order = PostOrder()
        handled: list[tuple[str, int]] = []
        waiting = await _send(order, handled, _PAGE, 2)
        assert not waiting.done()
        # its page no longer the one kept: handled once the other page's post is
        await _send(order, handled, other_page, 1)
        assert waiting.done()
        return handled

    assert asyncio.run(handle_all()) == [(other_page, 1), (_PAGE, 2)]
