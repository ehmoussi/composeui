from __future__ import annotations

import hashlib
from pathlib import Path
from string import Template

from markupsafe import Markup, escape

_STATIC = Path(__file__).parent / "static"


def _static_url(name: str) -> str:
    """Get the address of a static file, naming its content.

    A new version of the file has a new address, so a browser never keeps using a copy it
    cached of an older one (e.g. a stylesheet without the classes a new page uses).
    """
    digest = hashlib.sha256((_STATIC / name).read_bytes()).hexdigest()[:16]
    return f"/static/{name}?v={digest}"


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
<script src="$page_url" data-uplot="$uplot_url" data-cally="$cally_url"
  data-deckgl="$deckgl_url"></script>
</head>

<body class="bg-base-200 min-h-screen">
<div id="app">
$content
</div>
$page_marker
$pollers
<form id="$save_form" method="post" action="/state/download" hidden>
<input type="hidden" name="page" autocomplete="off">
<input type="hidden" name="post" autocomplete="off"></form>
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
    # uPlot 1.6.32 (https://github.com/leeoniya/uPlot), its stylesheet in css/uPlot.min.css,
    # its license in uPlot.LICENSE
    "uplot_url": _static_url("uPlot.iife.min.js"),
    # Cally 0.9.2 (https://github.com/WickyNilliams/cally), styled by daisyUI's `cally`
    "cally_url": _static_url("cally.js"),
    # deck.gl 9.2.6 (https://github.com/visgl/deck.gl), its license in deckgl.LICENSE
    "deckgl_url": _static_url("deckgl.min.js"),
}


def page_marker(language: str, title: str, *, oob: bool = False) -> Markup:
    """Get the element telling the page's script its `<html lang>` and `<title>`."""
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    return Markup('<div id="cui-page" data-language="{}" data-title="{}"{} hidden></div>').format(
        language, title, swap
    )


#: id of the form Save and Save As post, their button naming the action (`trigger`); the
#: page sets its `page` and `post` fields, its order among the page's posts (`order.py`)
SAVE_FORM_ID = "cui-save"


#: milliseconds the page waits, while jobs run, before asking for what they changed
JOBS_POLL_MS = 300


def jobs_poller(*, is_running: bool, oob: bool = False) -> Markup:
    """Get the element asking the server for what the jobs changed, while they run.

    No response carries what a job's result changes (see `RenderTarget.pending`): while
    the main view's jobs run, this element fetches itself every `JOBS_POLL_MS`, which
    brings the changes along, until it comes back without a fetch once they are over.
    """
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    poll = (
        Markup(' hx-get="/jobs" hx-trigger="load delay:{}ms" hx-swap="outerHTML"').format(
            JOBS_POLL_MS
        )
        if is_running
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
        '<div id="cui-reload" hx-get="/reload?instance={}" hx-trigger="every {}ms"'
        ' hx-swap="none" hidden></div>'
    ).format(instance, RELOAD_POLL_MS)


def get_page(
    title: str, content: Markup, language: str, *, pollers: Markup, icon: str | None = None
) -> str:
    """Get the app's page showing `content`, with the browser tab's `icon` at its address.

    `pollers` are the elements asking the server for news: `jobs_poller`'s, and
    `reload_poller`'s.
    """
    return _PAGE.substitute(
        {
            "title": escape(title),
            "icon_link": Markup('<link rel="icon" href="{}" />').format(icon) if icon else "",
            "content": content,
            "language": escape(language),
            "page_marker": page_marker(language, title),
            "pollers": pollers,
            "save_form": SAVE_FORM_ID,
            **_STATIC_URLS,
        }
    )
