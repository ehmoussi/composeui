import hashlib
import html
from pathlib import Path
from string import Template

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
     whose state they would contradict, at the address of a page of the app -->
<meta name="htmx-config" content='{"historyCacheSize": 0, "refreshOnHistoryMiss": true}' />
<script src="$htmx_url"></script>
<!-- built from css/app.css by `make css`: no CDN, so the page works offline -->
<link href="$css_url" rel="stylesheet" type="text/css" />
<script>
/* the theme picked in the header's Theme menu: Light or Dark win over the browser's
   light/dark preference and are remembered by this browser; System forgets the choice
   and follows the browser again. Applied here, before the body renders, so a reload
   never flashes the other theme first. */
var THEMES = ["composeui", "composeui-dark"];
function storedTheme() {
  var theme = null;
  try {
    theme = localStorage.getItem("composeui-theme");
  } catch (error) {}  // storage blocked: follow the browser's preference
  return THEMES.indexOf(theme) >= 0 ? theme : "system";
}
function applyTheme(choice) {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  document.querySelectorAll("[data-theme-option]").forEach(function (option) {
    option.setAttribute("aria-pressed", String(option.dataset.themeOption === choice));
  });
}
function setTheme(choice) {
  try {
    if (choice === "system") localStorage.removeItem("composeui-theme");
    else localStorage.setItem("composeui-theme", choice);
  } catch (error) {}
  applyTheme(choice);
}
applyTheme(storedTheme());
document.addEventListener("DOMContentLoaded", function () {
  applyTheme(storedTheme());  // again, now that the menu exists: marks the current choice
});
/* menu shortcuts: Alt+Shift+<key> clicks the item marked with that key. Matched on the
   physical key (`code`), so it works whatever character the keyboard layout, or the
   Option key on macOS, would type. (No dollar sign in here: this page is a string.Template.) */
document.addEventListener("keydown", function (event) {
  if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey) return;
  var item = document.querySelector('[data-shortcut="' + event.code + '"]');
  if (item === null) return;
  event.preventDefault();
  item.click();
});
/* keeps each form field's aria-invalid in step with its log: while typing, only the log
   is swapped, never the field. The field is invalid while its log shows an error, or
   a check of its form fails on its row (`data-form-error`). Watches the DOM, so it
   runs after every htmx swap. */
function syncInvalidFields() {
  document.querySelectorAll("[data-log]").forEach(function (log) {
    var field = document.querySelector('[aria-describedby="' + log.id + '"]');
    if (field === null) return;
    var ownError = log.dataset.log === "error" && !log.hidden;
    if (ownError || "formError" in log.dataset) field.setAttribute("aria-invalid", "true");
    else field.removeAttribute("aria-invalid");
  });
}
/* opens each dialog the server shows: one swapped in arrives closed, and the browser
   opens a modal `<dialog>` only from a script. Each element opens once: a button closes
   its dialog before the server's answer swaps it closed too. */
function openDialogs() {
  document.querySelectorAll("dialog[data-dialog]:not([hidden]):not([data-opened])").forEach(
    function (dialog) {
      dialog.dataset.opened = "";
      dialog.showModal();
    },
  );
}
/* the answer to a request whose element a swap has since replaced (e.g. a row clicked
   before the answer to a click on another row) still swaps its fragments: htmx looks
   for them from the element, which is no longer in the page. Whether it is, is read
   before htmx handles the answer, which may swap it out itself. */
document.addEventListener("htmx:beforeRequest", function (event) {
  var element = event.detail.elt;
  var request = event.detail.xhr;
  var isReplaced = false;
  request.addEventListener("readystatechange", function () {
    if (request.readyState === XMLHttpRequest.DONE) isReplaced = !element.isConnected;
  });
  request.addEventListener("load", function () {
    if (isReplaced && request.status === 200) {
      htmx.swap(document.body, request.responseText, { swapStyle: "none" });
    }
  });
});
/* editing a table cell: the server swaps the table back with a field in the cell (see
   `WebTableRenderer`), posting its text on Enter or when the user leaves it. F2 on a row
   edits its first editable cell, as a double click on the cell does; the field comes
   with its text selected, and Escape puts the text back before leaving it. */
document.addEventListener("keydown", function (event) {
  var target = event.target;
  if (event.key === "F2" && target.tagName === "TR") {
    var cell = target.querySelector("[data-edit]");
    if (cell !== null) {
      event.preventDefault();
      htmx.trigger(cell, "dblclick");
    }
  } else if (event.key === "Escape" && "cell" in target.dataset) {
    target.value = target.dataset.original;
    delete target.dataset.typed;
    target.blur();
  }
});
document.addEventListener("htmx:load", function (event) {
  var field = event.detail.elt.querySelector("[data-cell]");
  if (field !== null && field === document.activeElement && !("typed" in field.dataset)) {
    field.select();
  }
});
/* the field keeps the text the user is typing through a swap of its table (e.g. the
   answer to the double click's own clicks, selecting the row, arriving after a key):
   the server only gets the text at the end, so its copy of the table has the old. */
document.addEventListener("input", function (event) {
  if ("cell" in event.target.dataset) event.target.dataset.typed = "";
});
document.addEventListener("htmx:oobBeforeSwap", function (event) {
  var field = document.activeElement;
  if (field === null || !("typed" in field.dataset)) return;
  var swapped = event.detail.fragment.getElementById(field.id);
  if (swapped === null) return;
  swapped.setAttribute("value", field.value);
  swapped.dataset.typed = "";
});
/* the page's language, for screen readers and the browser's spell checker, and its
   title: the server swaps in its marker when the app changes them (see `page_marker`) */
function syncPage() {
  var marker = document.getElementById("cui-page");
  if (marker === null) return;
  document.documentElement.lang = marker.dataset.language;
  if (document.title !== marker.dataset.title) document.title = marker.dataset.title;
}
document.addEventListener("DOMContentLoaded", function () {
  openDialogs();
  new MutationObserver(function () {
    syncInvalidFields();
    openDialogs();
    syncPage();
  }).observe(document.body, {
    childList: true,
    subtree: true,
  });
});
</script>
</head>

<body class="bg-base-200 min-h-screen">
<div id="app">
$content
</div>
$page_marker
$jobs_poller
</body>

</html>
""")


#: read once: the files only change with a new version of the package
_STATIC_URLS = {"htmx_url": _static_url("htmx.min.js"), "css_url": _static_url("app.css")}


def page_marker(language: str, title: str, *, oob: bool = False) -> str:
    """Get the element telling the page's script its `<html lang>` and `<title>`."""
    swap = ' hx-swap-oob="true"' if oob else ""
    return (
        f'<div id="cui-page" data-language="{html.escape(language)}"'
        f' data-title="{html.escape(title)}"{swap} hidden></div>'
    )


#: milliseconds the page waits, while jobs run, before asking for what they changed
JOBS_POLL_MS = 1000


def jobs_poller(*, is_running: bool, oob: bool = False) -> str:
    """Get the element asking the server for what the jobs changed, while they run.

    No response carries what a job's result changes (see `RenderTarget.pending`): while
    the main view's jobs run, this element fetches itself every `JOBS_POLL_MS`, which
    brings the changes along, until it comes back without a fetch once they are over.
    """
    swap = ' hx-swap-oob="true"' if oob else ""
    poll = (
        f' hx-get="/jobs" hx-trigger="load delay:{JOBS_POLL_MS}ms" hx-swap="outerHTML"'
        if is_running
        else ""
    )
    return f'<div id="cui-jobs"{poll}{swap} hidden></div>'


def get_page(title: str, content: str, language: str, *, jobs_running: bool) -> str:
    return _PAGE.substitute(
        {
            "title": html.escape(title),
            "content": content,
            "language": html.escape(language),
            "page_marker": page_marker(language, title),
            "jobs_poller": jobs_poller(is_running=jobs_running),
            **_STATIC_URLS,
        }
    )
