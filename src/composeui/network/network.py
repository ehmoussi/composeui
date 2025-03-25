"""Fetch data from a given url."""

from composeui.core.basesignal import CallbackFunc
from composeui.mainview.views.mainview import MainView
from composeui.network.networkmanager import HttpMethod

from typing import AsyncGenerator, Iterable, Optional


def fetch(
    main_view: MainView,
    url: str,
    method: HttpMethod,
    body: Optional[bytes] = None,
    reply_callbacks: Optional[Iterable[CallbackFunc]] = None,
) -> None:
    clean_network_manager(main_view=main_view)
    main_view.network_manager.url = url
    main_view.network_manager.method = method
    if body is not None:
        main_view.network_manager.body = body
    if reply_callbacks is not None:
        main_view.network_manager.reply_finished.extend(reply_callbacks)
    main_view.network_manager.run()


def clean_network_manager(*, main_view: MainView) -> None:
    main_view.network_manager.reply_finished.clear()
    main_view.network_manager.url = ""
    main_view.network_manager.method = HttpMethod.GET
    main_view.network_manager.body = b""
    main_view.response = b""
    main_view.status_code = 0


async def fetch_async(
    main_view: MainView, url: str, method: HttpMethod, body: Optional[bytes] = None
) -> bytes:
    clean_network_manager(main_view=main_view)
    main_view.network_manager.url = url
    main_view.network_manager.method = method
    if body is not None:
        main_view.network_manager.body = body
    await main_view.network_manager.run_async()
    return main_view.network_manager.response


async def fetch_stream_async(
    main_view: MainView,
    url: str,
    method: HttpMethod,
    body: Optional[bytes] = None,
    chunk_size: int = 1024,
) -> AsyncGenerator[bytes, None]:
    clean_network_manager(main_view=main_view)
    main_view.network_manager.url = url
    main_view.network_manager.method = method
    if body is not None:
        main_view.network_manager.body = body
    async for response in main_view.network_manager.stream(chunk_size):
        yield response
