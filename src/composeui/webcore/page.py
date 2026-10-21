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
<!-- no copies of past pages: going back or forward reloads the page from the server,
     whose state they would contradict, at the address of a page of the app. Nothing
     htmx would run or style inline, which the page's policy refuses (`headers.py`). -->
<meta name="htmx-config" content='{"historyCacheSize": 0, "refreshOnHistoryMiss": true,
  "allowEval": false, "allowScriptTags": false, "includeIndicatorStyles": false}' />
<script src="$htmx_url"></script>
<!-- built from css/app.css by `make css`: no CDN, so the page works offline -->
<link href="$css_url" rel="stylesheet" type="text/css" />
<script src="$page_url" data-uplot="$uplot_url" data-cally="$cally_url"></script>
</head>

<body class="bg-base-200 min-h-screen">
<div id="app">
$content
</div>
$page_marker
$jobs_poller
<form id="$save_form" method="post" action="/state/download" hidden></form>
</body>

</html>
""")


#: read once: the files only change with a new version of the package
_STATIC_URLS = {
    "htmx_url": _static_url("htmx.min.js"),
    "css_url": _static_url("app.css"),
    # a file, not inline: a policy can then allow the page's own scripts by address
    "page_url": _static_url("page.js"),
    # uPlot 1.6.32 (https://github.com/leeoniya/uPlot), its stylesheet in css/uPlot.min.css
    "uplot_url": _static_url("uPlot.iife.min.js"),
    # Cally 0.9.2 (https://github.com/WickyNilliams/cally), styled by daisyUI's `cally`
    "cally_url": _static_url("cally.js"),
}


def page_marker(language: str, title: str, *, oob: bool = False) -> Markup:
    """Get the element telling the page's script its `<html lang>` and `<title>`."""
    swap = Markup(' hx-swap-oob="true"') if oob else Markup()
    return Markup('<div id="cui-page" data-language="{}" data-title="{}"{} hidden></div>').format(
        language, title, swap
    )


#: id of the form Save and Save As post, their button naming the action (`trigger`)
SAVE_FORM_ID = "cui-save"


#: milliseconds the page waits, while jobs run, before asking for what they changed
JOBS_POLL_MS = 1000


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


def get_page(title: str, content: Markup, language: str, *, jobs_running: bool) -> str:
    return _PAGE.substitute(
        {
            "title": escape(title),
            "content": content,
            "language": escape(language),
            "page_marker": page_marker(language, title),
            "jobs_poller": jobs_poller(is_running=jobs_running),
            "save_form": SAVE_FORM_ID,
            **_STATIC_URLS,
        }
    )
