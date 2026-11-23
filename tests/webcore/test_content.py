"""Tests of the web labels, images, Markdown, consoles, metrics, logs and status bar."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from typing_extensions import override

pytest.importorskip("starlette")
# Starlette's test client: httpx2, which needs Python 3.11, or httpx before it
pytest.importorskip("httpx2" if sys.version_info >= (3, 11) else "httpx")

from composeui.core.registry import RendererType
from composeui.core.view import (
    ButtonView,
    ImageView,
    LabelView,
    LogType,
    MainView,
    TextRole,
    child,
    define_view,
)
from composeui.webcore._renderers.content import (
    WebImageRenderer,
    WebLogRenderer,
    WebMarkdownRenderer,
    WebNotificationBarRenderer,
    WebStatusBarRenderer,
)
from composeui.webcore.changes import collect_dirty
from composeui.webcore.webapplication import WebApplication
from composeui.webcore.webrenderer import (
    WebRenderer,
    render_dirty,
)
from tests.console import MAX_LINES, STEP_LINES, ColoredRunMainView, RunMainView
from tests.markdown import HelpMainView
from tests.webcore.support import _Browser, _Element, _element, _RowsMainView, _swapped, _widget_id

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from examples.webhello import HelloMainView
    from tests.metrics import JobsMainView


def test_markdown_is_shown_as_html_its_own_markup_escaped() -> None:
    main_view = HelpMainView()
    main_view.render(RendererType.WEB)
    renderer = main_view.help.renderer
    assert isinstance(renderer, WebMarkdownRenderer)
    element = _element(renderer.to_html(), renderer.widget_id)
    assert (element.tag, element.attributes["class"]) == ("div", "cui-markdown")
    assert [tag for tag, _ in element.descendants] == ["h1", "ul", "li", "li"]
    assert element.text == "Help\n\nOpen a study\nRun it\n\n"

    with collect_dirty() as dirty:
        main_view.help.text = (
            "## Results\n\n<script>alert(1)</script>\n\n"
            "[the report](https://example.com/report) [no](javascript:alert(1))"
        )
        element = _swapped(render_dirty(dirty), renderer.widget_id)
    assert [(tag, attributes) for tag, attributes in element.descendants if tag != "p"] == [
        ("h2", {}),
        ("a", {"href": "https://example.com/report"}),
    ]
    # shown as text, not run: the browser shows the tag the text has
    assert "<script>alert(1)</script>" in element.text
    assert "<script>" not in renderer.to_html()


@pytest.mark.parametrize(
    ("role", "tag", "class_name"),
    [
        (TextRole.BODY, "span", ""),
        (TextRole.TITLE, "h2", "font-bold"),
        (TextRole.SUBTITLE, "h3", "font-semibold"),
        (TextRole.ERROR, "span", "text-error"),
    ],
)
def test_a_label_s_role_picks_its_tag_and_keeps_its_text_as_set(
    rows: _RowsMainView, role: TextRole, tag: str, class_name: str
) -> None:
    hostile = '<b onclick="x">Plan</b>\nSteel'
    rows.note.text = hostile
    rows.note.role = role
    renderer = rows.note.renderer
    assert isinstance(renderer, WebRenderer)

    element = _element(renderer.to_html(), renderer.widget_id)

    assert element.tag == tag
    classes = (element.attributes["class"] or "").split()
    assert class_name in (element.attributes["class"] or "")
    # the browser shows the line break only with this class
    assert "whitespace-pre-line" in classes
    assert element.text == hostile


def test_log_is_hidden_when_empty_and_coloured_by_type(rows: _RowsMainView) -> None:
    renderer = rows.form_log.renderer
    assert isinstance(renderer, WebLogRenderer)
    assert " hidden " in renderer.to_html()

    rows.form_log.log_message = "- first\n- second"
    rows.form_log.log_type = LogType.WARNING

    fragment = renderer.to_html()
    assert "hidden" not in fragment
    assert "text-warning" in fragment
    # the hook the page's stylesheet uses to mark the field before an error log
    assert 'data-log="warning"' in fragment
    assert "whitespace-pre-line" in fragment
    assert "- first\n- second" in fragment


def test_a_timed_message_makes_the_status_bar_fetch_itself_after_the_timeout(
    main_view: HelloMainView,
) -> None:
    status_bar = main_view.status_bar
    renderer = status_bar.renderer
    assert isinstance(renderer, WebStatusBarRenderer)
    status_bar.timeout = 3.0

    def attributes() -> dict[str, str | None]:
        return _element(renderer.to_html(), renderer.widget_id).attributes

    assert "hx-get" not in attributes()  # nothing to clear yet

    status_bar.message = "Saved"

    assert attributes()["hx-get"] == f"/_composeui/widget/{renderer.widget_id}"
    assert attributes()["hx-trigger"] == "load delay:3250ms"
    assert attributes()["hx-swap"] == "outerHTML"

    status_bar.timeout = 0  # a message that never times out needs no fetch
    assert "hx-get" not in attributes()


def test_a_notification_shows_above_the_card_and_a_close_closes_only_the_message_shown(
    client: TestClient, main_view: HelloMainView
) -> None:
    renderer = main_view.notification.renderer
    assert isinstance(renderer, WebNotificationBarRenderer)
    bar_id = renderer.widget_id
    closes: list[str] = []
    main_view.notification.closed.connect(lambda: closes.append(main_view.notification.message))
    main_view.notify("Can't save to a.txt: the disk is full.", LogType.ERROR)

    page = client.get("/").text
    shown = _element(page, bar_id)
    assert "hidden" not in shown.attributes
    assert shown.attributes["role"] == "alert"
    assert shown.text == "Can't save to a.txt: the disk is full."
    assert page.index(bar_id) < page.index('class="card ')  # above the page's content
    replaced = json.loads(_element(page, f"{bar_id}-close").attributes["hx-vals"] or "")
    # meanwhile, a job's callback shows another message, which this page hasn't shown yet
    main_view.notify("Can't open b.txt.", LogType.ERROR)

    url = f"/_composeui/widget/{bar_id}"
    assert client.post(url, data=replaced).status_code == 200
    assert main_view.notification.message == "Can't open b.txt."
    assert closes == []
    assert client.post(url, data={"event": "close", "number": "x"}).status_code == 400

    page = client.get("/").text
    current = json.loads(_element(page, f"{bar_id}-close").attributes["hx-vals"] or "")
    response = client.post(url, data=current)

    assert "hidden" in _swapped(response.text, bar_id).attributes
    assert closes == [""]  # once, after the message is gone
    assert main_view.notification.message == ""


def test_an_information_makes_the_notification_fetch_itself_after_its_timeout(
    main_view: HelloMainView,
) -> None:
    renderer = main_view.notification.renderer
    assert isinstance(renderer, WebNotificationBarRenderer)
    main_view.notification.timeout = 0  # no timer left running past the test

    def attributes() -> dict[str, str | None]:
        return _element(renderer.to_html(), renderer.widget_id).attributes

    main_view.notify("Imported 3 rows.", LogType.WARNING)
    assert attributes()["role"] == "alert"
    assert "hx-get" not in attributes()  # stays until closed

    main_view.notification.timeout = 3.0
    main_view.notify("Imported 3 rows.")

    assert attributes()["role"] == "status"
    assert attributes()["hx-get"] == f"/_composeui/widget/{renderer.widget_id}"
    assert attributes()["hx-trigger"] == "load delay:3250ms"
    main_view.clear_notification()


def test_a_disabled_notification_shows_its_close_button_disabled(main_view: HelloMainView) -> None:
    renderer = main_view.notification.renderer
    assert isinstance(renderer, WebNotificationBarRenderer)
    main_view.notify("Can't save", LogType.ERROR)

    main_view.notification.is_enabled = False  # the server then refuses a close

    assert "disabled" in _element(renderer.to_html(), f"{renderer.widget_id}-close").attributes


def test_a_console_sends_only_its_new_lines_then_the_line_being_written() -> None:
    views: list[RunMainView] = []

    class RunApp(WebApplication[RunMainView]):
        @override
        def setup_session(self, main_view: RunMainView) -> None:
            views.append(main_view)

    with _Browser(RunApp(build_main_view=RunMainView).create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        output_id, run_id = _widget_id(view.output.renderer), _widget_id(view.run.renderer)
        console = _element(page, f"{output_id}-text")
        assert (console.tag, console.attributes["data-max-lines"]) == ("pre", str(MAX_LINES))
        assert console.text == "Ready <ok>\n"

        for _ in range(2):
            body = client.post(f"/_composeui/widget/{run_id}", data={"event": "click"}).text
            assert f'id="{output_id}" hx-swap-oob' not in body
            assert f'hx-swap-oob="beforebegin:#{output_id}-last"' in body
            # the run's lines, the last run's progress line ended as the first of them
            assert (body.count("Step "), "Ready" in body) == (STEP_LINES, False)
            assert _swapped(body, f"{output_id}-last").text == "Progress 100%"

        view.run.clicked.connect(lambda: setattr(view.output, "text", "New run"))
        body = client.post(f"/_composeui/widget/{run_id}", data={"event": "click"}).text
        _swapped(body, output_id)  # whole
        assert _element(body, f"{output_id}-text").text == "New run"


def test_a_console_shows_its_ansi_colors_in_inline_styles_and_drops_them_when_asked() -> None:
    views: list[ColoredRunMainView] = []

    class ColorsApp(WebApplication[ColoredRunMainView]):
        @override
        def setup_session(self, main_view: ColoredRunMainView) -> None:
            views.append(main_view)

    def styles(markup: str, element_id: str) -> list[str | None]:
        """Get the inline styles of an element's parts."""
        found = _element(markup, element_id).descendants
        return [attributes.get("style") for _, attributes in found if "style" in attributes]

    app = ColorsApp(build_main_view=ColoredRunMainView)
    with _Browser(app.create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        output_id = _widget_id(view.output.renderer)
        console = _element(page, f"{output_id}-text")
        assert console.text == "ERROR <x> bg\ngreen"  # the text, not markup
        assert styles(page, f"{output_id}-text") == [
            "color:#cd3131;font-weight:bold",
            "background-color:#0dbc79",
            "color:#0dbc79",
        ]

        body = client.post(
            f"/_composeui/widget/{_widget_id(view.more.renderer)}", data={"event": "click"}
        ).text
        assert f'id="{output_id}" hx-swap-oob' not in body  # only the new lines
        assert 'style="color:#2472c8;font-style:italic;text-decoration:underline"' in body

        view.output.ansi_colors = False
        body = client.post(
            f"/_composeui/widget/{_widget_id(view.more.renderer)}", data={"event": "click"}
        ).text
        _swapped(body, output_id)  # whole
        assert styles(body, f"{output_id}-text") == []


def test_a_console_uses_the_translated_copy_confirmation_with_older_labels() -> None:
    views: list[RunMainView] = []

    class RunApp(WebApplication[RunMainView]):
        @override
        def setup_session(self, main_view: RunMainView) -> None:
            main_view.set_language("fr")
            main_view.output.texts = {"copy": "Copier le journal", "save": "Exporter le journal"}
            views.append(main_view)

    with _Browser(RunApp(build_main_view=RunMainView).create_starlette_app()) as client:
        page = client.get("/").text
        console = _element(page, _widget_id(views[-1].output.renderer))
        buttons = [attributes for tag, attributes in console.descendants if tag == "button"]
        assert [button["aria-label"] for button in buttons] == ["Copier le journal"]
        assert "Copié" in console.text


def test_a_console_s_link_downloads_its_text() -> None:
    views: list[RunMainView] = []

    class RunApp(WebApplication[RunMainView]):
        @override
        def setup_session(self, main_view: RunMainView) -> None:
            main_view.output.export_filename = "run é.log"
            views.append(main_view)

    with _Browser(RunApp(build_main_view=RunMainView).create_starlette_app()) as client:
        page = client.get("/").text
        (view,) = views
        output_id = _widget_id(view.output.renderer)
        links = [a for tag, a in _element(page, output_id).descendants if tag == "a"]
        assert [(a["href"], "download" in a) for a in links] == [
            (f"/_composeui/widget/{output_id}/text", True)
        ]
        view.output.append("Step 1 <done>\n")

        response = client.get(f"/_composeui/widget/{output_id}/text")
        unknown = client.get(f"/_composeui/widget/{_widget_id(view.run.renderer)}/text")

    assert response.text == "Ready <ok>\nStep 1 <done>\n"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"].endswith("filename*=UTF-8''run%20%C3%A9.log")
    assert unknown.status_code == 404


def _badge(stat: _Element) -> tuple[str, ...] | None:
    """Get the classes of a stat's badge, None without one."""
    for tag, attributes in stat.descendants:
        if tag == "span" and "badge" in (attributes.get("class") or "").split():
            return tuple((attributes.get("class") or "").split())
    return None


def test_a_metric_is_a_stat_with_its_change_as_a_badge_colored_by_sign(
    jobs: tuple[TestClient, JobsMainView],
) -> None:
    client, view = jobs
    running, failed = view.summary.running, view.summary.failed
    running_id, failed_id = _widget_id(running.renderer), _widget_id(failed.renderer)
    page = client.get("/").text
    stat = _element(page, running_id)
    assert "stat" in (stat.attributes.get("class") or "").split()
    assert "↑ 2 since yesterday" in stat.text
    badge = _badge(stat)
    assert badge is not None
    assert "badge-success" in badge
    assert _badge(_element(page, failed_id)) is None  # no change given

    running.delta = -2
    failed.label = "<Failed>"
    failed.delta = 0
    stat = _element(client.get(f"/_composeui/widget/{running_id}").text, running_id)
    assert "↓ 2 since yesterday" in stat.text
    badge = _badge(stat)
    assert badge is not None
    assert "badge-error" in badge
    stat = _element(client.get(f"/_composeui/widget/{failed_id}").text, failed_id)
    assert "<Failed>" in stat.text  # escaped, shown as text
    badge = _badge(stat)
    assert badge is not None
    assert "badge-success" not in badge
    assert "badge-error" not in badge

    with collect_dirty() as dirty:
        running.delta_format = ".1f"
        stat = _swapped(render_dirty(dirty), running_id)
    assert "↓ 2.0 since yesterday" in stat.text
    running.delta = -1 / 3
    running.delta_text = ""
    stat = _element(client.get(f"/_composeui/widget/{running_id}").text, running_id)
    assert "↓ 0.3" in stat.text


@define_view
class _PictureMainView(MainView):
    picture: ImageView = child(ImageView, description="A curve")


class _PictureApp(WebApplication[_PictureMainView]):
    """Serves `_PictureMainView`, keeping each session's main view."""

    def __init__(self, image: Path | bytes | None = None, **kwargs: Any) -> None:
        super().__init__(build_main_view=_PictureMainView, **kwargs)
        self.image = image
        self.session_views: list[_PictureMainView] = []

    @override
    def setup_session(self, main_view: _PictureMainView) -> None:
        main_view.picture.image = self.image
        self.session_views.append(main_view)


_PNG = b"\x89PNG\r\n\x1a\n image"
_SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"


def _picture_address(html: str) -> str:
    match = re.search(r'src="(/_composeui/widget/[^"]+/picture\?version=[^"]+)"', html)
    assert match is not None, html
    return match.group(1)


@pytest.mark.parametrize(
    ("content", "media_type"),
    [
        (_PNG, "image/png"),
        (b"\xff\xd8\xff\xe0 image", "image/jpeg"),
        (b"GIF87a image", "image/gif"),
        (b"GIF89a image", "image/gif"),
        (b"RIFF\x00\x00\x00\x00WEBP image", "image/webp"),
        (b"BM image", "image/bmp"),
        (b"\x00\x00\x01\x00 image", "image/x-icon"),
        (_SVG, "image/svg+xml"),
        (b"\xef\xbb\xbf<?xml version='1.0'?>\n<!-- a comment -->\n" + _SVG, "image/svg+xml"),
    ],
)
def test_an_image_is_served_by_its_content_s_type_for_the_browser_to_keep(
    content: bytes, media_type: str
) -> None:
    with _Browser(_PictureApp(content).create_starlette_app()) as browser:
        page = browser.get("/")
        assert 'alt="A curve"' in page.text
        response = browser.get(_picture_address(page.text))

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == media_type
    assert response.headers["cache-control"].startswith("private,")
    # an SVG opened on its own runs no script
    assert "default-src 'none'; style-src 'unsafe-inline'" in response.headers.get_list(
        "content-security-policy"
    )


@pytest.mark.parametrize(
    "image",
    [
        None,
        b"secret text, not an image",
        b"RIFF\x00\x00\x00\x00WAVE sound",
        b"<html><body>no vector here</body></html>",
        b"text before <svg>",
        Path("missing.png"),
    ],
)
def test_what_is_no_image_shows_its_description_and_serves_nothing(
    image: Path | bytes | None,
) -> None:
    app = _PictureApp(image)
    with _Browser(app.create_starlette_app()) as browser:
        page = browser.get("/")
        (main_view,) = app.session_views
        assert isinstance(main_view.picture.renderer, WebImageRenderer)
        widget_id = main_view.picture.renderer.widget_id
        answer = browser.get(f"/_composeui/widget/{widget_id}/picture?version=any")

    assert f'<span id="{widget_id}" data-cui="image">A curve</span>' in page.text
    assert answer.status_code == 404


def test_a_file_that_is_no_image_is_never_served_under_any_version(tmp_path: Path) -> None:
    """An app may set a path that a user typed: only an image of it may leave the server."""
    secret = tmp_path / "secret.png"
    secret.write_bytes(b"not an image")
    app = _PictureApp(secret)
    with _Browser(app.create_starlette_app()) as browser:
        browser.get("/")
        (main_view,) = app.session_views
        assert isinstance(main_view.picture.renderer, WebImageRenderer)
        widget_id = main_view.picture.renderer.widget_id
        digest = hashlib.sha256(b"not an image").hexdigest()[:16]
        answer = browser.get(f"/_composeui/widget/{widget_id}/picture?version={digest}")

    assert answer.status_code == 404


def test_a_new_image_swaps_its_address_and_the_old_one_answers_no_other_image(
    tmp_path: Path,
) -> None:
    """A browser keeps an address for good: another image under it would show stale for ever."""
    path = tmp_path / "logo.png"
    path.write_bytes(_PNG)

    @define_view
    class ChangedPictureMainView(MainView):
        picture: ImageView = child(ImageView, image=path, description="Logo")
        change: ButtonView = child(ButtonView, text="Change")

        @override
        def __attrs_post_init__(self) -> None:
            super().__attrs_post_init__()
            self.change.clicked.connect(self._change)

        def _change(self) -> None:
            self.picture.image = _PNG + b" other"

    views: list[ChangedPictureMainView] = []

    class ChangedPictureApp(WebApplication[ChangedPictureMainView]):
        @override
        def setup_session(self, main_view: ChangedPictureMainView) -> None:
            views.append(main_view)

    app = ChangedPictureApp(build_main_view=ChangedPictureMainView)
    with _Browser(app.create_starlette_app()) as browser:
        old_address = _picture_address(browser.get("/").text)
        assert browser.get(old_address).content == _PNG

        button = views[0].change.renderer
        assert isinstance(button, WebRenderer)
        swapped = browser.post(f"/_composeui/widget/{button.widget_id}", data={"event": "click"})

        new_address = _picture_address(swapped.text)
        assert 'hx-swap-oob="true"' in swapped.text
        assert new_address != old_address
        assert browser.get(new_address).content == _PNG + b" other"
        assert browser.get(old_address).status_code == 404


def test_an_image_s_height_sets_its_size_on_the_page() -> None:
    @define_view
    class TallPictureMainView(MainView):
        picture: ImageView = child(ImageView, image=_PNG, height=120)

    app: WebApplication[TallPictureMainView] = WebApplication(build_main_view=TallPictureMainView)
    with _Browser(app.create_starlette_app()) as browser:
        assert 'style="height: 120px"' in browser.get("/").text


def test_an_image_is_only_served_to_its_own_session() -> None:
    """A widget's id is guessable: an image can be private to the session that made it."""
    app = _PictureApp(_PNG)
    starlette_app = app.create_starlette_app()
    with _Browser(starlette_app) as owner, _Browser(starlette_app) as other:
        address = _picture_address(owner.get("/").text)
        assert owner.get(address).status_code == 200
        without_session = other.get(address)
        other.get("/")
        with_another_session = other.get(address)

    assert without_session.status_code == 404
    assert with_another_session.status_code == 404
    assert "no-store" in with_another_session.headers["cache-control"]


def test_a_widget_that_is_no_image_serves_nothing_at_an_image_s_address() -> None:
    @define_view
    class LabelMainView(MainView):
        note: LabelView = child(LabelView, text="Note")

    views: list[LabelMainView] = []

    class LabelApp(WebApplication[LabelMainView]):
        @override
        def setup_session(self, main_view: LabelMainView) -> None:
            views.append(main_view)

    with _Browser(LabelApp(build_main_view=LabelMainView).create_starlette_app()) as browser:
        browser.get("/")
        note = views[0].note.renderer
        assert isinstance(note, WebRenderer)
        assert browser.get(f"/_composeui/widget/{note.widget_id}/picture").status_code == 404
