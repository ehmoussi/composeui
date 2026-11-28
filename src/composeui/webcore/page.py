from __future__ import annotations

import hashlib
from pathlib import Path
from string import Template
from typing import TYPE_CHECKING, Final

from markupsafe import Markup, escape

from composeui.webcore.uploads import MAX_UPLOAD_FILES

if TYPE_CHECKING:
    from composeui.core.jobs import Jobs

_STATIC = Path(__file__).parent / "static"


def _static_url(name: str) -> str:
    """Get the address of a static file, naming its content.

    A new version of the file has a new address. So a browser never keeps using a copy it
    cached of an older one (e.g. a stylesheet without the classes a new page uses).
    """
    digest = hashlib.sha256((_STATIC / name).read_bytes()).hexdigest()[:16]
    return f"/_composeui/static/{name}?v={digest}"


# no `data-theme`: daisyUI then follows the browser's light/dark preference
_PAGE = Template("""<!DOCTYPE html>
<html lang="$language">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>$title</title>
$icon_link
<!-- no copies of past pages: going back or forward reloads the page from the server,
     whose state they would contradict, at the address of a page of the app. Nothing
     htmx would run or style inline, which the page's policy refuses (`headers.py`). -->
<meta name="htmx-config" content='{"historyCacheSize": 0, "refreshOnHistoryMiss": true,
  "allowEval": false, "allowScriptTags": false, "includeIndicatorStyles": false}' />
<script src="$htmx_url"></script>
<!-- built from css/app.css by `make css`: no CDN, so the page works offline -->
<link href="$css_url" rel="stylesheet" type="text/css" />
$style_links<script src="$page_url" data-uplot="$uplot_url" data-cally="$cally_url"
  data-deckgl="$deckgl_url" data-charts="$charts_url" data-maps="$maps_url"></script>
<script src="$tables_url"></script>
</head>

<body class="bg-base-200 min-h-screen" data-max-upload="$max_upload_size"
  data-max-upload-files="$max_upload_files" data-session="$session_tag">
<div id="app">
$content
</div>
$page_marker
$pollers
$downloads
<form id="$save_form" method="post" action="/_composeui/state/download" hidden>
<input type="hidden" name="page" autocomplete="off">
<input type="hidden" name="post" autocomplete="off">
<input type="hidden" name="$session_field" value="$session_tag" autocomplete="off"></form>
</body>

</html>
""")


#: read once: the files only change with a new version of the package
_STATIC_URLS = {
    # htmx 2.0.10 (https://github.com/bigskysoftware/htmx); `make web-deps` updates these files
    "htmx_url": _static_url("htmx.min.js"),
    # Tailwind and daisyUI 5.7.47 classes, daisyUI's license in daisyui.LICENSE
    "css_url": _static_url("app.css"),
    # a file, not inline: a policy can then allow the page's own scripts by address
    "page_url": _static_url("page.js"),
    # the tables' script, after the page's; those of the charts and the maps, which the
    # page's loads with their libraries
    "tables_url": _static_url("tables.js"),
    "charts_url": _static_url("charts.js"),
    "maps_url": _static_url("maps.js"),
    # uPlot 1.6.32 (https://github.com/leeoniya/uPlot), its stylesheet in css/uPlot.min.css,
    # its license in uPlot.LICENSE
    "uplot_url": _static_url("uPlot.iife.min.js"),
    # Cally 0.9.2 (https://github.com/WickyNilliams/cally), styled by daisyUI's `cally`
    "cally_url": _static_url("cally.js"),
    # deck.gl 9.2.6 (https://github.com/visgl/deck.gl), its license in deckgl.LICENSE
    "deckgl_url": _static_url("deckgl.min.js"),
}


#: a page without stylesheets of the app's
NO_LINKS: Final = Markup()


def page_marker(language: str, title: str, *, oob: bool = False) -> Markup:
    """Get the element telling the page's script its `<html lang>` and `<title>`."""
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    return Markup('<div id="cui-page" data-language="{}" data-title="{}"{} hidden></div>').format(
        language, title, swap
    )


#: id of the form Save and Save As post, their button naming the action (`trigger`); the
#: page sets its `page` and `post` fields, its order among the page's posts (`order.py`)
SAVE_FORM_ID = "cui-save"


#: the header in which the page's htmx requests name the session that served it
SESSION_TAG_HEADER = "X-ComposeUI-Session"
#: the same, as a field of the form that Save and Save As post: no headers
SESSION_TAG_FIELD = "session"


#: milliseconds the page waits, while jobs run, before asking for what they changed
JOBS_POLL_MS = 300


def jobs_poll_delay(jobs: Jobs) -> int | None:
    """Get the milliseconds the jobs' poller waits before its next fetch, or None for none.

    `JOBS_POLL_MS` while a job runs. While a repeating task only waits for its next run,
    its `every`: that run's start then shows at most one wait late, and an idle dashboard
    asks once a wait rather than every `JOBS_POLL_MS`.
    """
    if jobs.is_running:
        return JOBS_POLL_MS
    every = jobs.repeat_every
    return None if every is None else max(JOBS_POLL_MS, round(every * 1000))


def jobs_poller(*, delay_ms: int | None, oob: bool = False) -> Markup:
    """Get the element asking the server for what the jobs changed, while they run.

    No response carries what a job's result changes (see `RenderTarget.pending`). While
    the main view's jobs run, or a task repeats, this element fetches itself after
    `delay_ms` (`jobs_poll_delay`), which brings the changes along, until it comes back
    without a fetch once they are over.
    """
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    poll = (
        Markup(
            ' hx-get="/_composeui/jobs" hx-trigger="load delay:{}ms" hx-swap="outerHTML"'
        ).format(delay_ms)
        if delay_ms is not None
        else Markup()
    )
    return Markup('<div id="cui-jobs"{}{} hidden></div>').format(poll, swap)


#: milliseconds between two asks, in a page of a ``--reload`` server, whether it restarted
RELOAD_POLL_MS = 1000


def reload_poller(instance: str | None) -> Markup:
    """Get the element asking a ``--reload`` server whether it restarted; none without.

    It asks every `RELOAD_POLL_MS`, naming `instance`, the server's process that served
    the page. Another process answers with ``HX-Refresh``: the page reloads, with the
    changed code and its session restored. An ask that fails while the server restarts is
    asked again.
    """
    if instance is None:
        return Markup()
    return Markup(
        '<div id="cui-reload" hx-get="/_composeui/reload?instance={}" hx-trigger="every {}ms"'
        ' hx-swap="none" hidden></div>'
    ).format(instance, RELOAD_POLL_MS)


def get_page(  # noqa: PLR0913 (each is a part of the page)
    title: str,
    content: Markup,
    language: str,
    *,
    pollers: Markup,
    max_upload_size: int,
    session_tag: str = "",
    icon: str | None = None,
    downloads: str = "",
    style_links: Markup = NO_LINKS,
) -> str:
    """Get the app's page showing `content`, with the browser tab's `icon` at its address.

    `pollers` are the elements asking the server for news: `jobs_poller`'s, and
    `reload_poller`'s. The page's script sends no files larger than `max_upload_size`
    together, nor more than `MAX_UPLOAD_FILES` at once, and `session_tag` with its requests
    (`SESSION_TAG_HEADER`, or Save's `SESSION_TAG_FIELD`).
    `downloads` names the files the page fetches (`downloads.downloads_marker`), and
    `style_links` the app's stylesheets, after ComposeUI's (`style.StyleFiles`).
    """
    return _PAGE.substitute(
        {
            "title": escape(title),
            "icon_link": Markup('<link rel="icon" href="{}" />').format(icon) if icon else "",
            "content": content,
            "language": escape(language),
            "page_marker": page_marker(language, title),
            "pollers": pollers,
            "downloads": downloads,
            "style_links": style_links,
            "max_upload_size": max_upload_size,
            "max_upload_files": MAX_UPLOAD_FILES,
            "session_tag": escape(session_tag),
            "session_field": SESSION_TAG_FIELD,
            "save_form": SAVE_FORM_ID,
            **_STATIC_URLS,
        }
    )
