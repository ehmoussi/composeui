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
<link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
<style>
/* a field followed by a log showing an error is invalid too; text the browser itself
   rejects (a float field's pattern) as well, once the user has interacted with it */
.input:has(+ [data-log="error"]:not([hidden])),
.select:has(+ [data-log="error"]:not([hidden])),
.input:user-invalid {
  --input-color: var(--color-error);
  border-color: var(--color-error);
}
</style>
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
