"""Fetch data from a given url."""

from composeui.core import tools
from composeui.core.basesignal import CallbackFunc
from composeui.mainview.views.mainview import MainView
from composeui.network.networkview import HttpMethod

from typing import Any, Dict, Iterable, Optional


def fetch(
    main_view: MainView,
    url: str,
    method: HttpMethod,
    body: Optional[Dict[str, Any]] = None,
    reply_callback: Optional[Iterable[CallbackFunc]] = None,
) -> None:
    clean_network_view(main_view=main_view)
    main_view.network_view.url = url
    main_view.network_view.method = method
    if body is not None:
        main_view.network_view.body = body
    if reply_callback is not None:
        main_view.network_view.reply_finished += [[check_reply, *reply_callback]]
    main_view.network_view.run()


def clean_network_view(*, main_view: MainView) -> None:
    main_view.network_view.reply_finished.clear()
    main_view.network_view.url = ""
    main_view.network_view.method = HttpMethod.GET
    main_view.network_view.body = {}
    main_view.received_data = None
    main_view.status_code = 0


def check_reply(*, main_view: MainView) -> bool:
    if main_view.network_view.received_data is None:
        tools.display_error_message(main_view, "The fetch request have failed.")
        return False
    return True


async def fetch_async(
    main_view: MainView, url: str, method: HttpMethod, body: Optional[Dict[str, Any]] = None
) -> Optional[Any]:
    clean_network_view(main_view=main_view)
    main_view.network_view.url = url
    main_view.network_view.method = method
    if body is not None:
        main_view.network_view.body = body
    await main_view.network_view.run_async()
    check_reply(main_view=main_view)
    return main_view.network_view.received_data
