import html
from string import Template

_PAGE = Template("""<!DOCTYPE html>
<html>
<head>
<title>$title</title>
<script src="/static/htmx.min.js"></script>
<link href="https://cdn.jsdelivr.net/npm/daisyui@5" rel="stylesheet" type="text/css" />
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
</head>

<body>
<div id="app">
$content
</div>
</body>

</html>
""")


def get_page(title: str, content: str) -> str:
    return _PAGE.substitute({"title": html.escape(title), "content": content})
