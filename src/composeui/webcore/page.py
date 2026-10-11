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
<html lang="en">
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
document.addEventListener("DOMContentLoaded", function () {
  openDialogs();
  new MutationObserver(function () {
    syncInvalidFields();
    openDialogs();
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
</body>

</html>
""")


#: read once: the files only change with a new version of the package
_STATIC_URLS = {"htmx_url": _static_url("htmx.min.js"), "css_url": _static_url("app.css")}


def get_page(title: str, content: str) -> str:
    return _PAGE.substitute({"title": html.escape(title), "content": content, **_STATIC_URLS})
