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
