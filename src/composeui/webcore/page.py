import html
from string import Template

# no `data-theme`: daisyUI then follows the browser's light/dark preference
_PAGE = Template("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>$title</title>
<script src="/static/htmx.min.js"></script>
<!-- built from css/app.css by `make css`: no CDN, so the page works offline -->
<link href="/static/app.css" rel="stylesheet" type="text/css" />
<script>
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
   is swapped, never the field. Watches the DOM, so it runs after every htmx swap. */
function syncInvalidFields() {
  document.querySelectorAll("[data-log]").forEach(function (log) {
    var field = document.querySelector('[aria-describedby="' + log.id + '"]');
    if (field === null) return;
    if (log.dataset.log === "error" && !log.hidden) field.setAttribute("aria-invalid", "true");
    else field.removeAttribute("aria-invalid");
  });
}
document.addEventListener("DOMContentLoaded", function () {
  new MutationObserver(syncInvalidFields).observe(document.body, {
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


def get_page(title: str, content: str) -> str:
    return _PAGE.substitute({"title": html.escape(title), "content": content})
