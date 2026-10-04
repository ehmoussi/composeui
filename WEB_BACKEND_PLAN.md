# Web backend plan — Starlette + htmx + daisyUI

Goal: a third `composeui` backend (`composeui.webcore`), sitting next to `qtcore` and
`textualcore`, selected via `RendererType.WEB`. Renders `composeui.core.view` trees as
server-rendered HTML, using htmx for interactivity (no client-side JS framework) and
daisyUI/Tailwind for styling.

## Decisions already made (see conversation)

- **htmx over websockets.** Most composeui interactions originate from a browser event
  (edit a field, click a button) — a plain `hx-post` request/response cycle covers that.
  Cross-widget cascades (e.g. `hello.py`: editing the greeting input updates the *status
  bar*, a different widget) are handled with htmx's out-of-band swaps (`hx-swap-oob`), not
  a socket.
- **No Preact.** Because updates are whole-fragment HTML swaps, not fine-grained DOM
  patches, there's no need for a client-side component tree/virtual DOM. The server
  renders real HTML; htmx just swaps it in.
- **Starlette over FastAPI.** `cattrs` already does serialization; FastAPI's main value-add
  (Pydantic validation/OpenAPI) is redundant for an htmx-driven HTML endpoint. Starlette is
  the leaner match for this project's existing minimal-dependency style (`attrs`, `cattrs`,
  `qtpy` only).
- **Known gap: true unprompted server push** (e.g. `StatusBar.show_message`'s
  `threading.Timer`-based auto-clear) has no open channel to deliver into under plain
  htmx. Punt on it for v1 (see M10) rather than pulling in SSE/websockets up front.

## How this maps onto the existing `Renderer` abstraction

This is the one part that doesn't port 1:1 from `qtcore`/`textualcore`, so nail it down
before writing widget renderers:

- **`_rendered_object` becomes a stable string id**, not a live widget instance — e.g.
  `f"cui-{id(view)}"`, assigned once the first time `render()` runs on a given view and
  reused for the view's lifetime (views live for the whole session, same as Qt/Textual).
  **Revised in M2:** form rows bind 2–3 renderers (`label`/`field`/`log`) to the *same*
  view through a `RendererContainer`, so `id(view)` alone collides. Each renderer class
  carries a `_role: ClassVar[str]` (`"input"`, `"log"`, `"form_label"`, ...) and the id
  is `f"cui-{id(view)}-{role}"` — unique because a row never holds two renderers of the
  same class. The row's input and its log then swap independently, which matters (see
  "focus rule" below).
- **`refresh_attribute` doesn't mutate anything** — there's nothing live to mutate between
  requests. Instead it marks the *view* dirty in a **request-scoped set** (a `contextvar`,
  reset at the start of every request by ASGI middleware). Every attribute this renderer
  cares about can share one `_mark_dirty` handler in `_refresh_dispatcher` (you don't need
  Qt/Textual's per-attribute fine dispatch — htmx swaps a whole fragment at a time, so
  "any attribute of this widget changed" and "this widget's fragment needs a fresh render"
  are the same event). This mirrors how `_TextualNoopRenderer` shares one `_noop` handler
  across several attributes.
- **Each `Web*Renderer` gets a `to_html() -> str` method** (escape all view-supplied text
  with `html.escape`) — this replaces "build/mutate a live widget" as the actual rendering
  logic, called on demand rather than once at construction time.
- **The route handler, not the renderer, assembles the HTTP response.** After running the
  triggered callback (a `Signal.emit()`, same as Qt/Textual's `_update_text` etc.), it
  reads the dirty-set contextvar, calls `to_html()` on each dirty renderer, and
  concatenates: the fragment matching the element htmx targeted swaps in place normally;
  every other dirty fragment carries `hx-swap-oob="true"` on its own root tag.
  **Revised in M2 (focus rule):** the element that fired the request is *never* swapped.
  Re-rendering the `<input>` the user is typing in would reset the caret and drop
  keystrokes typed while the request was in flight. So every interactive element uses
  `hx-swap="none"` and the whole response is OOB fragments (htmx still processes OOB
  content when the main swap is `none`). That falls out of the existing design: the route
  writes the new value under `renderer.stop_refresh()`, so `notify_renderer` never calls
  `refresh_attribute` for the source widget and it never enters the dirty set.
- **The dirty set is opened by the route handler, not by middleware.** Sync Starlette
  endpoints run in a threadpool with a *copy* of the context, so a contextvar set by
  middleware is fragile. A small `collect_dirty()` context manager inside the handler
  does the job instead. Outside a request (the `StatusBar` timer thread, `render()`
  during startup), `_mark_dirty` must be a silent no-op: the contextvar defaults to
  `None`.

This keeps the same base-class contract (`render`, `refresh_attribute`, `_update_state`,
`_refresh_dispatcher`) that `Renderer` already requires, so `core/view.py` and
`core/registry.py` need **zero changes** — only new code under `webcore/`.

## Session state

Unlike Qt/Textual (one process, one `MainView`, one user), a web server can have several
browser tabs/users at once, and HTTP is stateless between requests. v1 plan: an in-memory
`dict[session_id, MainView]` (module-level dict is fine to start), `session_id` from a
signed cookie via Starlette's `SessionMiddleware` (needs `itsdangerous`). Good enough for
single-process local/dev use; note as a known limitation (no horizontal scaling without
moving state out of process — `MainView.save_state`/`load_state` already round-trips the
whole tree through `cattrs`, which is a plausible future path to a Redis-backed store, but
out of scope for v1).

Each session also needs an **id → `View` registry** (walk the tree the same way
`_add_reference_to_signals`/`_register_actions` already do in `application.py`/
`textualrenderer.py`) so an incoming `POST /widget/{id}/{event}` can find the target view.

## Endpoint shape

- `GET /` — render the full page: HTML shell (head with htmx `<script>` + daisyUI/Tailwind
  CSS) + the `MainView`'s full HTML tree. Issues the session cookie if missing.
- `POST /widget/{widget_id}/{event}` — generic dispatch: look up the view by id, map
  `event` to the right `Signal` (`"edited"` → `text_edited`, `"changed"` → `text_changed`,
  `"blur"` → `editing_finished`, matching the existing Qt/Textual event names), pull the
  new value from the form body, set it on the view under `renderer.stop_refresh()` (same
  pattern as `TextualInputRenderer._update_text`), then `.emit()` the signal — that's what
  runs user callbacks/validators, which may dirty other views elsewhere in the tree.
  Response = OOB fragments for everything the dirty set collected (see the focus rule).
  Uniform form contract: every widget submits its value under the field name `value`.
  **Revised in M2:** one `<input>` has to report two events (debounced `input` →
  `edited`, `change` → `finished`, which `pipeform.py`'s float validators rely on), but
  an element can carry only one `hx-post` URL. So the event name goes in the body
  (`hx-vals='js:{"event": event.type}'`) and the route is `POST /widget/{widget_id}`.
  The route maps `input` → `text_changed` + `text_edited` (both, same as
  `TextualInputRenderer._update_text`), `change` → `editing_finished`, and a
  radio/select `change` → `value_changed`.
- File save/open (see M7) get their own endpoints — they don't fit the generic dispatch
  shape (see below).

## Module layout

```
src/composeui/webcore/
    __init__.py
    webapplication.py   # WebApplication(Application[MainViewT]); run() starts uvicorn
    webrenderer.py       # WebRenderer base + one class per widget type + RENDERERS dict
    session.py            # session_id -> MainView registry, widget id -> View lookup
    routes.py              # Starlette route handlers (index, widget dispatch, file open/save)
static/
    htmx.min.js           # vendored, no npm/build step
    app.css                # see M10 for CDN-vs-compiled Tailwind/daisyUI
```

Add `RendererType.WEB = "composeui.webcore.webrenderer"` in `core/registry.py` (one-line
addition, same as the existing QT/TEXTUAL entries).

## New dependencies

`pyproject.toml`, new `web` optional-dependency group:
- `starlette` — ASGI framework
- `uvicorn` — ASGI server (`WebApplication.run()` calls `uvicorn.run(...)`)
- `python-multipart` — Starlette needs it to parse form/file POST bodies
- `itsdangerous` — needed by `SessionMiddleware` for the signed session cookie

Dev group addition: `httpx` (Starlette's `TestClient` is httpx-based; not currently a dep).

Templating: **hand-rolled small `str`-returning functions per renderer**, not Jinja2 — every
widget's HTML is a few lines (`<input>`, a `<label>`, a `<div class="radio-group">…`), this
keeps parity with the existing one-class-per-widget-type style in `qtrenderer.py`/
`textualrenderer.py` instead of introducing a template-file layer. Escape all view text
with stdlib `html.escape`.

## Milestones (build + test each before moving on)

1. **M0 — Scaffolding.** `web` extra in `pyproject.toml`, `webcore/` package skeleton,
   `RendererType.WEB` registry entry, a Starlette app that serves a static page with
   htmx + daisyUI (CDN script tags for now). Confirm `uv run uvicorn composeui.webcore...`
   serves something.

   1. ~~Add the `web` optional-dependency group to `pyproject.toml`: `starlette`, `uvicorn`,
      `python-multipart`, `itsdangerous`; add `httpx` to the `dev` group (needed later by
      Starlette's `TestClient` in M9, cheap to add now). `uv sync --extra web`.~~
   2. ~~Create the `src/composeui/webcore/` package: `__init__.py`, `webrenderer.py` (just an
      empty `RENDERERS: dict[str, Callable[[Any], Renderer[Any, Any]]] = {}` for now),
      `webapplication.py`, `routes.py`, `session.py` (stub, filled in at M6). Mirrors the
      existing `qtcore`/`textualcore` layout.~~
   3. ~~Add `RendererType.WEB = "composeui.webcore.webrenderer"` to `core/registry.py`
      (one line, same shape as the existing `QT`/`TEXTUAL` entries). `create_renderer`
      should resolve it fine even with an empty `RENDERERS` dict — same "backend doesn't
      support this key yet" fallback already used for partial backends.~~
   4. ~~Vendor `static/htmx.min.js` (download once, commit it — no npm/build step). Reference
      daisyUI + Tailwind via their CDN `<script>` tags for now; M10 swaps these for a
      compiled `static/app.css`.~~
   5. ~~Write the base HTML shell as a small helper (e.g. `webcore/page.py`): `<!doctype
      html>` + `<head>` with the htmx `<script src="/static/htmx.min.js">` and the
      daisyUI/Tailwind CDN tags + an empty `<body>` container `<div id="app">`.~~
   6. ~~Wire a minimal `Starlette` app in `routes.py`: mount `/static`, add a `GET /` route
      whose handler returns the shell HTML. No `MainView` rendering yet — the only goal
      here is confirming the page loads with htmx and daisyUI present (e.g. drop in one
      hardcoded `<button class="btn btn-primary">` to eyeball daisyUI styling actually
      applied).~~
   7. ~~`webapplication.py`: `WebApplication(Application[MainViewT])` whose `run()` calls
      `super().run()` then `uvicorn.run(app, ...)` — same shape as `QtApplication.run()`
      handing off to `QApplication.exec()`.~~
   8. ~~Smoke-test: `uv run uvicorn composeui.webcore.routes:app --reload`, open the page in
      a browser, confirm the daisyUI-styled placeholder renders and `htmx.version` is
      defined in the devtools console.~~
   9. ~~`make check` (ruff + mypy) passes on the new package before starting M1 — nothing in
      it is worth building on top of if it doesn't already lint/type-check clean.~~

2. **M1 — MainView shell + StatusBar.** `WebMainRenderer` renders the base page (head +
   body container); `WebStatusBarRenderer` renders the status bar fragment. Port `hello.py`
   far enough to serve a page with just a status bar.

   No interactivity yet — that's M2's dirty-set/OOB mechanism. M1 is purely: a real
   `composeui.core.view` tree rendered once to static HTML and served, replacing M0's
   hardcoded button.

   1. ~~`webrenderer.py`: add a `WebRenderer(Renderer[TView, str])` base class.
      `render()` assigns `self._rendered_object = f"cui-{id(self._view)}"` the first time
      it runs (idempotent on repeat calls, same guard style as
      `TextualWidgetRenderer.render()`'s `if self._rendered_object is None`). Add an
      abstract `to_html() -> str` that concrete renderers implement. `_update_state` can
      be a no-op stub for now (`pass` — nothing reads state back from HTML until a real
      widget with user input exists, starting M2).~~
   2. ~~`WebStatusBarRenderer(WebRenderer[StatusBar, str])`: `to_html()` returns something
      like `<div id="{id}" class="alert alert-info">{html.escape(view.message)}</div>` —
      pick whichever daisyUI component reads naturally for a status line (`alert` or
      `toast`); render the container even when `message` is empty so the id is always
      present in the page (M2+ needs a stable target to swap into).~~
   3. ~~`WebMainRenderer(MainRenderer[MainView, str])`: `render()` same id-assignment as
      above; `to_html()` walks `main_view.children_views` and joins each child renderer's
      `to_html()` into the page body. Must still satisfy `MainRenderer`'s abstract
      `close()`/`open_file()`/`save_file()` — stub all three (`raise NotImplementedError`)
      since file handling doesn't land until M7; don't invent fake `Path` behavior here.~~
   4. ~~Register both in `webrenderer.py`'s `RENDERERS` dict: `"main": WebMainRenderer`,
      `"status_bar": WebStatusBarRenderer` — matches the `_renderer_key` values already on
      `MainView`/`StatusBar` in `core/view.py`, so no core changes needed, same as
      Qt/Textual's registration.~~
   5. ~~`routes.py`/`webapplication.py`: give the Starlette `app` somewhere to find the
      rendered `MainView` — store it on `app.state.main_view` (idiomatic Starlette; also
      the natural seam M6 later swaps for a per-session lookup). `WebApplication.run()`
      needs to actually call `self.render(RendererType.WEB)` before `uvicorn.run(...)` —
      it doesn't yet; without it `main_view.renderer` stays `None` and there's nothing to
      serve. Mirrors `QtApplication.run()`'s `self.render(RendererType.QT)` call.~~
   6. ~~Update `homepage` in `routes.py` to drop the hardcoded button and instead render
      `get_page(main_view.title, main_view.renderer.to_html())` using the app-state
      `main_view` from step 5.~~
   7. ~~Port `hello.py` (or a small new `examples/web_hello.py`) to construct a `MainView`
      with just the default `status_bar` (no greeting input yet — that's M2) and run it
      through `WebApplication`.~~
   8. ~~Manual check: start the app, `GET /`, confirm the page source contains the status
      bar's `<div id="cui-...">` styled with the chosen daisyUI classes, even though
      `message` is empty and nothing is interactive yet.~~
   9. ~~`make check` before starting M2.~~

   **M1 follow-ups (fixed in M2 step 1).** These were gaps in the M1 code, found while
   planning M2. They were fixed before the rest of M2, which builds directly on them:
   - ~~**Empty dispatchers.** `WebStatusBarRenderer` and `WebMainRenderer` registered no
     refresh handlers, so setting *any* view attribute after `render()` raised
     `MissingRefreshAttributeFunctionError` (`status_bar.message = "x"` and
     `main_view.minimum_width = 3` both did). *Fixed:* every `WebRenderer` attribute
     maps to `_mark_dirty` (M2 step 2); `WebMainRenderer`'s attributes are no-ops,
     because the page itself is never swapped.~~
   - ~~**`WebMainRenderer` was not a `MainRenderer`**, so `MainView.close()`/
     `ask_*_filepath()` silently skipped it. *Fixed:* it is now a standalone
     `MainRenderer[MainView, str]`, not a `WebRenderer`, since it never renders a
     swappable fragment. **This reverses M1 step 3's decision:** `open_file`/`save_file`
     return `None` ("the user picked no path") instead of raising. Core's
     `FileMenu._save_state`/`_load_state` are connected to `save`/`open_file.triggered`,
     so a `NotImplementedError` would surface as a 500 as soon as M8 dispatches those
     triggers. `None` is what those callbacks already treat as "cancelled", and it
     settles the open question in M7. `close()` is a no-op until sessions exist
     (M6/M8).~~
   - ~~**Two `MainView`s.** `WebApplication.__init__` built one (`self.main_view`, the
     instance that `Application.connect`, `_add_reference_to_signals` and `-f FILE` act
     on), and `create_starlette_app`'s lifespan built and served a second one that got
     none of that. *Fixed:* `WebApplication.create_starlette_app()` renders and serves
     `self._main_view`. M6 replaces it with per-session construction and a
     `setup_session` hook.~~
   - ~~**`--reload` didn't work.** `uvicorn.run(<lambda>, factory=True, reload=True)`
     cannot reload: uvicorn needs an import string, and its reloader re-imports the
     app in a child process that never runs the user's script, so a global set by
     `configure()` would be empty there too. *Fixed by removal:* `--reload`,
     `configure()`, the unused `WebApplication.lifespan` and the commented-out
     `uvicorn.Config` code are gone. `--host` was added. To reload during development,
     point `uvicorn --reload --factory` at a module-level factory.~~
   - ~~**`to_html()` meant two things.** On the main renderer it returned a full
     `<html>` page; everywhere else it returned a fragment. *Fixed:* the main renderer's
     method is `page_html()` (served through `render_page()`), so OOB assembly can
     never emit a whole document.~~
   - ~~**Local env.** `.venv/.../uvicorn/supervisors/__init__.py` was truncated (an
     `except ImportError:` with no body → `IndentationError` on `import uvicorn`). The
     corrupt copy came from uv's cache, so `--reinstall-package` alone reinstalled the
     same broken file. *Fixed:* `uv cache clean uvicorn`, then
     `uv sync --group dev --all-extras --reinstall-package uvicorn`.~~

3. **M2 — InputView, end to end.** `WebInputRenderer`: `<input>` with `hx-post` and a
   debounced `input` trigger (see the revised endpoint shape above). Build the dirty-set
   contextvar and the OOB response assembly here: this is the core mechanism the rest of
   the backend reuses. Acceptance target: extend `examples/webhello.py` into the README's
   `HelloMainView` greeting example (there is no `hello.py` file; the README quickstart
   is the reference). Prove that editing the input updates the *status bar* fragment
   through an OOB swap in the same response, over real HTTP.

   1. ~~Fix the M1 follow-ups above (each entry records its fix).~~
   2. ~~`webrenderer.py`: add a module-level `_DIRTY: ContextVar[dict[str, WebRenderer] |
      None] = ContextVar("composeui_web_dirty", default=None)`. The dict is keyed by id,
      insertion-ordered and deduplicated. Add a `collect_dirty()` context manager that
      sets it to `{}`, yields the dict, and resets the token. `WebRenderer.__init__`
      registers `_mark_dirty` for `is_visible`/`is_enabled`, and every subclass
      registers it for each attribute its `to_html()` reads.
      `_mark_dirty(view, rendered_object, value)` adds `self` (so it is a bound method
      rather than a `@staticmethod`; the dispatcher type allows any callable) and does
      nothing when `_DIRTY.get()` is `None`.~~
   3. ~~Base `WebRenderer` HTML conventions, as helpers that every `to_html()` uses:
      - always emit the root element with `id`, even when `is_visible` is False. Emit
        the `hidden` attribute instead, so a later "becomes visible" swap still has a
        target (`pipeform.py`'s chamfer/fillet groups depend on this);
      - `is_enabled=False` → `disabled` on the interactive element;
      - all view text through `html.escape(..., quote=True)`, attributes included;
      - an `oob: bool = False` keyword on `to_html()`. When it is True, add
        `hx-swap-oob="true"` to the root tag. Only the response assembly passes it.~~
   4. ~~`_role: ClassVar[str]` on each renderer class plus the id scheme
      `f"cui-{id(view)}-{role}"` (see the revised mapping section). Update
      `WebStatusBarRenderer` to it.~~
   5. ~~`WebInputRenderer(WebRenderer[InputViewLike])`. Define the `InputViewLike`
      Protocol locally, the same way `textualrenderer.py` does. The output is a daisyUI
      `<input class="input" type="text" name="value" value=... placeholder=...
      hx-post="/widget/{id}" hx-trigger="input changed delay:300ms, change"
      hx-vals='js:{"event": event.type}' hx-swap="none" hx-sync="this:queue all">`.
      `queue all` keeps the `change` event from being dropped behind an in-flight
      debounced edit. Dispatcher: `text`, `placeholder` → `_mark_dirty`. Add a
      `dispatch(event, form)` method, so that each renderer knows how to apply its own
      event (instead of a big `isinstance` switch in the route):
      `"input"` → `with self.stop_refresh(): view.text = value`, then emit
      `text_changed` and `text_edited`; `"change"` → emit `editing_finished`. Same
      shape as `TextualInputRenderer._update_text`/`_editing_finished`. Register
      `"input": WebInputRenderer`.~~
   6. ~~Widget lookup: a module-level `weakref.WeakValueDictionary[str, WebRenderer]`,
      filled by `WebRenderer.render()`. It is good enough for the single served
      `MainView` and is replaced per session in M6. Doing it at render time avoids
      having to reach into `RendererContainer._renderers` (private) to find row
      renderers.~~
   7. ~~`routes.py`: `def widget_event(request)` must be sync, so view callbacks run in
      the threadpool and not on the event loop. It looks up the renderer (unknown id →
      404), parses the form (`python-multipart`), and runs
      `with collect_dirty() as dirty: renderer.dispatch(event, form)`. It returns
      `HTMLResponse("".join(r.to_html(oob=True) for r in dirty.values()))`. **Ancestor
      dedupe:** when a group and one of its descendants are both dirty (from M5 on),
      emitting both would swap the child twice. Drop any fragment whose `id="..."` also
      appears inside another emitted fragment. A string check is enough here; renderers
      don't know their parents. Register `Route("/widget/{widget_id}", widget_event,
      methods=["POST"])`.~~
   8. ~~Thread safety, simple version: one `threading.Lock` around dispatch plus render
      (per session from M6 on). Override `WebRenderer.call_on_main_thread` to take that
      same lock, so `StatusBar`'s timer thread can't mutate the tree in the middle of a
      request. That is the web equivalent of Qt's "marshal onto the GUI thread".~~
   9. ~~Example: `webhello.py` gets the README's `GreetingInputView` (with the
      `main_view`-injected `show_message` callback) as a `HelloMainView` field.~~
   10. ~~Tests: new `tests/test_webrenderer.py` with `pytest.importorskip("starlette")`,
       using Starlette's `TestClient`:
       - `GET /` contains the input and the status bar ids;
       - `POST /widget/{input id}` with `value=Bob&event=input` returns a body that
         contains the status bar fragment with `hx-swap-oob` and `Hello, Bob!`, and does
         *not* contain the input's own id (focus rule);
       - `view.text == "Bob"` afterwards;
       - an unknown id gives 404;
       - setting a view attribute outside a request does not raise and records nothing.~~
   11. ~~Manual check in a browser: type in the field, watch the status bar update, and
       confirm the caret is never reset mid-typing. Then run `make check`.~~ *(Done: in headless Chromium driven by
       Playwright, typing `Bob` shows `Hello, Bob!` while the input keeps focus, and
       typing on to `Bobby` lands at the end, so no caret reset.)*

   *Implementation notes (M2 as built):* tests build the app with
   `WebApplication.create_starlette_app()`. The route is `async` only to await the form
   body; dispatch itself runs in the threadpool through `handle_event`, which holds the
   lock and opens the dirty set. The README quickstart's `main_view: "HelloMainView"`
   annotation fails mypy (`Signal.connect` types the injected `main_view` as
   `MainView`); `webhello.py` uses `MainView`, and the README should be fixed in M10.
   Core's `Signal._log_signal` crashes on built-in callbacks such as `list.append` (no
   `__code__`); that is a separate core bug, worked around in tests.

4. **M3 — LabelView, FloatInputView, LogMixin validation.** Extend the dirty-set pattern
   to more leaf widgets, and prove that a validator-driven log update joins the same
   multi-widget OOB fan-out (more than M2's 2-widget case).

   1. ~~`WebLabelRenderer` (`"label"`): `<span id class="label-text">`; dispatcher
      `text`. `WebFormLabelRenderer` (`"form_label"`, `_role="form_label"`):
      `<label for="{field id}" class="label">` reading `view.label`. To build `for=`
      it derives the field id from the same view plus the field renderer's role (pass
      the field role in at construction or compute it from `_field_renderer_key`).~~
   2. ~~`WebFloatInputRenderer` (`"float_input"`): `<input type="number" inputmode="decimal"
      min max step>`, with `step = 10**-decimals` when `decimals` is set, `"any"`
      otherwise. This gives client-side min/max enforcement for free, which is more
      than Textual does for `decimals`. Same triggers/`dispatch` as the input. On
      `"input"`, transient unparsable text (`"-"`, `"1."`) is ignored with
      `contextlib.suppress(ValueError)`, exactly like `TextualFloatInputRenderer`;
      `""` → `None`. Dispatcher: `value`, `placeholder`, `minimum`, `maximum`,
      `decimals`. Render `value` with `repr`-free formatting (`format(v, "g")`) so
      `20.0` doesn't come back as `20.000000001`.~~
   3. ~~`WebLogRenderer` (`"log"`, `_role="log"`): `<p id class="text-sm whitespace-pre-line
      text-error|text-warning|text-info">`. `pre-line` because `FormView.validate`
      joins messages with `\n- `. It is `hidden` when `log_message == ""` (matches
      `TextualLogRenderer`) or when `is_visible` is False. Dispatcher:
      `log_message`, `log_type`.~~
   4. ~~Test at the renderer level, not over HTTP: rows only get a page position once
      the form renderer exists (M5). Render a `LabelRowInputView` (validator on
      `text_edited`), a `LabelRowFloatInputView` and a `LabelView` directly, then assert
      on `to_html()` before and after attribute changes and on `dispatch()` inside
      `collect_dirty()`. Full-page HTTP coverage comes in M5/M9.~~
   5. ~~Tests: clearing a validated input in one dispatch dirties the row's *log*, but not
      its input; typing `"1."` into the float input leaves `value` unchanged and doesn't
      raise; a `change` event fires `editing_finished` exactly once; escaping (a
      `<script>` label renders inert). `make check`.~~

   *Implementation notes (M3 as built), where it differs from the steps above:*
   - **Float input is `type="text" inputmode="decimal"`, not `type="number"`.** A
     number input reports `""` for transient text such as the `-` of `-5`, which is
     indistinguishable from a cleared field, so the server would briefly set `value`
     to `None` and emit. A text field posts the raw text and unparsable text is
     ignored, exactly like Qt/Textual. So `minimum`/`maximum`/`decimals` are tracked
     (they mark the field dirty) but, as in Textual, not enforced on input. A
     `pattern` (checked in Chromium: accepts `-`, `1.`, `1e3`; rejects `abc`,
     `1.2.3`) marks malformed text red once the user has interacted with the field.
     Values render with `str(value)`, the same as Qt, instead of `format(v, "g")`,
     which turns `1234567.0` into `1.23457e+06`.
   - **Revised after M4 (field ↔ message):** daisyUI's `validator` class was dropped.
     It painted a field *green* from the browser's own rules alone, even when the
     server-side message next to it said "A name is mandatory". Instead, the page's
     stylesheet turns a field red when the log right after it shows an error
     (`.input:has(+ [data-log="error"]:not([hidden]))`; logs carry `data-log`), so
     the field never needs swapping while being typed in. Leaving a float field
     (`change`) with unparsable text swaps the field back to the view's value without
     emitting `editing_finished` (Qt's validator never accepts such text), so the
     field never shows `4a` while the validators judge 4. Both were checked in Chromium.
     M5's form rows put each field right before its log, so the same rule applies there.
   - **Revised after M4 (stale page after a restart):** after filling the form,
     restarting the server and reloading, the browser showed the old values next to
     messages from the restarted server's empty state ("A name is mandatory",
     "Nobody…"). Reproduced in Firefox: with no cache header it reused the old page or
     refilled the fresh page's fields from what was typed. Every HTML response now
     sends `Cache-Control: no-store`, and every form control has `autocomplete="off"`,
     so a reload always shows the server's state. A restart still *loses* that state:
     it lives in memory (see "Session state"). Keeping it across restarts would mean
     persisting each session's `save_state` JSON (M6+), not trusting the browser's
     copy.
   - **Shared `_WebTextFieldRenderer` base** for both text fields, typed with a
     `TextFieldViewLike` Protocol (placeholder + the three signals). A `change` that
     follows an `input` with the same text does not re-emit `text_changed`/
     `text_edited`. The float field compares against the last *posted* text, and a
     server-side `value` change resets that, so the server's value wins.
   - `WebFormLabelRenderer` finds its field id through the row's public
     `RendererContainer.get_renderer("field")` at render time, not through
     `_field_renderer_key`. `label-text` was dropped (daisyUI 5 removed it); the label
     uses `label text-sm font-medium`.
   - "1." from step 5 parses fine in Python (`float("1.") == 1.0`); the test uses
     `-` for transient text instead.

5. **M4 — RadioGroupView / ComboboxView (`ValuesGroupMixin`).** Render as daisyUI
   `radio`/`select` components and wire `value_changed`.

   1. ~~Shared wire format: options are identified by their **label** (the `values` key),
      never by `str(value)`, the same convention as `serialize_value`/
      `deserialize_value`. The route turns the posted label back into a value with
      `view.deserialize_value(label)`. An unknown label gives `None` plus a warning
      log, and **never** `ValueError` from `_check_value`, because a stale page posting
      an old label must not 500.~~
   2. ~~`WebRadioGroupRenderer` (`"radio_group"`): a `<div id role="radiogroup"
      hx-post="/widget/{id}" hx-trigger="change" hx-vals='js:{"event": "change"}'
      hx-swap="none" hx-include="this">` wrapping one `<label><input type="radio"
      class="radio" name="value" value="{label}" checked?> {label}</label>` per entry.
      The radio `name` must also be unique per group, otherwise two groups on one page
      share a radio set. Either use `name="{id}"` and read that field, or keep
      `name="value"` with each group wrapped in its own `<form>`. **Pick `name="{id}"`**
      and have `dispatch` read `form[self._rendered_object]`.~~
   3. ~~`WebComboboxRenderer` (`"combobox"`): `<select class="select" name="value"
      hx-post ... hx-trigger="change">`, with a leading empty `<option value="">` only
      when `value is None` (Qt's `QValueComboBox` shows nothing selected in that case).~~
   4. ~~Both renderers: dispatcher `value`, `values` → `_mark_dirty`. A `values` change
      re-renders the whole option set, and `_reconcile_values` has already cleared a
      no-longer-valid `value`. `dispatch("change")` →
      `with stop_refresh(): view.value = deserialize_value(label)`, then
      `value_changed.emit(view.value)`, the same shape as `_update_value` in both other
      backends.~~
   5. ~~Tests (direct renderer level, as in M3): select a label → `view.value` is the enum
      member and `value_changed` fires once; replacing `values` marks the group dirty and
      the new HTML has the new options with the right one `checked`/`selected`; a bogus
      label → `value is None` and no exception; two radio groups render distinct
      `name`s. `make check`.~~

   *Implementation notes (M4 as built), where it differs from the steps above:*
   - **htmx attributes sit on each radio `<input>`, not on the wrapping `<div>`.**
     htmx always sends the triggering element's named value, and a radio is checked by
     the time its `change` fires. That avoids relying on `hx-include="this"` pulling
     inputs out of a non-form container. The radio group and the `<select>` are named
     after the widget id, and `dispatch` reads `form[widget_id]`.
   - **Choosing the current value again does nothing**, so `value_changed` only fires
     on a real change. The empty `<option>` posts `""`, which means `None` directly,
     without going through `deserialize_value`'s unknown-label warning. That makes
     the empty choice a way to clear the combobox, and it stays in the browser's list
     after a pick, because the source `<select>` is never swapped back (re-rendering it
     would drop keyboard focus mid-arrowing).
   - **A form label doesn't use `for=` on a radio group** (a `<div>` isn't labelable).
     A public `is_labelable` class flag on `WebRenderer` lets `WebFormLabelRenderer`
     skip it. Ideally the group would get an `aria-labelledby` (M10 accessibility pass).
   - Tests run mostly over HTTP rather than at the renderer level, through the hello
     example, which gained a greeting-style radio group (Casual/Formal re-greets in the
     status bar) and a favourite-colour combobox that starts empty and feeds the
     summary. A radio *row* (`LabelRowRadioGroupView`) is covered at renderer level.
     Checked in headless Chromium: clicking Formal and picking Blue update the status
     bar and summary, and neither the radio group nor the select is swapped back.

6. **M5 — FormView / FormRowView / GroupFormView.** Assemble `examples/pipeform.py` as
   the acceptance target, as it already is for `qtrenderer`/`textualrenderer`. Nested
   rows and groups are styled with daisyUI `fieldset`.

   1. ~~`WebFormRenderer` (`"form"`, `_role="form"`): `<div id class="flex flex-col
      gap-2">`. For each `view.field_rows`:
      - a `FormRowView` with a `RendererContainer` renders as a row wrapper (`<div
        class="flex flex-col">`, *no* id of its own) containing `label` (if
        `FormLabelRowView`), `field` and `log`, fetched with the public
        `RendererContainer.get_renderer(name)`. The same helper structure as
        `TextualFormRenderer._get_*_widget`, including a clear error when a key is
        missing;
      - a nested `FormView` → its own renderer's `to_html()`.
      Then append `view.log_view`'s renderer (the form-level cross-field log).
      Dispatcher: `is_visible`, `is_enabled` only, because a form's rows are not
      attributes that change. Row *visibility*: a `FormRowView`'s `is_visible` reaches
      every renderer in its container, so each of the three hides itself, and no row
      wrapper id is needed.~~
   2. ~~`WebGroupFormRenderer` (`"group_form"`): the same, wrapped in `<fieldset id
      class="fieldset bg-base-200 border-base-300 rounded-box border p-4"><legend
      class="fieldset-legend">{title}</legend>…`. Dispatcher adds `title`.~~
   3. ~~`WebMainRenderer.page_html()`: the main content first, then the status bar pinned
      at the bottom (`fixed bottom-0` / daisyUI `footer`), mirroring Textual's docked
      status bar. `title` already goes into `<title>`.~~ *(Done early, after M2: a
      `navbar` header shows the title; content sits in a centered `max-w-3xl` card; the
      status bar is a neutral `<footer role="status">` fixed to the bottom instead of an
      always-visible `alert`. `page.py` gained `lang`, charset and viewport meta tags,
      and has no `data-theme`, so daisyUI follows the browser's light/dark preference.
      M8's menu goes in the header.)*
   4. ~~`pipeform.py`: add `class WebPipeApp(WebApplication[PipeMainView])` next to the
      Qt and Textual apps, with `build_main_view=PipeMainView`. The module already
      imports both other backends unconditionally, so a third import matches the
      existing convention.~~
   5. ~~Acceptance over HTTP (TestClient), in `tests/test_webrenderer.py`:
      - `GET /` renders every row label, the Normal radio `checked`, Steel `selected`,
        and the chamfer/fillet groups present but `hidden`;
      - selecting `Chamfer` returns OOB fragments for the chamfer group (no longer
        `hidden`) and the status bar (`Edge type changed: Chamfer`). This is a 3-widget
        fan-out from one click, and nothing is emitted for the radio group itself;
      - setting main-pipe radius to `5` then `change` makes the form-level log appear
        with the incident-radius message (validator wired to `editing_finished`);
      - clearing Name makes that row's log show `A name is mandatory`.~~
   6. ~~Manual browser pass over the whole form, then `make check`.~~

   *Implementation notes (M5 as built), where it differs from the steps above:*
   - **A plain form is a `<fieldset>` too, not a `<div>`.** A disabled fieldset
     natively disables every control inside it, the way disabling a Qt container
     disables its children, so `is_enabled` on a form or group needs no propagation
     code. `WebGroupFormRenderer` subclasses `WebFormRenderer` and adds the daisyUI
     `fieldset` styling and the `<legend>` title. Rows render label, field, log in
     that order (field right before log, which the field-error CSS rule relies on).
     The row wrapper has no id, and a row whose field the backend doesn't support
     renders nothing.
   - **The hello example became a real form** (`HelloFormView` with name, age,
     greeting-style and colour rows, each owning its label and log), plus a summary
     label after it. The age row's validity for the summary is read from its own log
     instead of re-running the check. Its tests moved to the row-based views.
   - The pipeform tests skip if Qt/Textual are missing, because `pipeform.py` imports
     all three apps. The form-level cross-field log (pipeform's radius checks) isn't
     tied to one field, so it doesn't turn any field red; only a row's own log does.
   - Checked in headless Chromium: both forms render with each label above its field;
     Chamfer/Fillet groups reveal and hide; shrinking the main radius to 5 and leaving
     the field shows the form-level radius message. (Pipeform's own message text
     reads "cant'be", a pre-existing typo in the example, left alone.)

7. **M6 — Real session handling.** Move off a single global `MainView` (fine for manual
   testing through M5) to the per-session cookie-backed registry, so two browsers (or
   users) don't clobber each other's state. *(Corrected: a cookie is shared by every tab
   of one browser, so tabs share one session, like two windows on the same document.
   Per-tab sessions would need the id in each page, and then every refresh would start
   an empty form.)*

   1. ~~`session.py`: `@attrs.define class WebSession: main_view: MainView;
      renderers: dict[str, WebRenderer]; lock: threading.Lock`, plus a
      `SessionStore` (a plain `dict[str, WebSession]` behind a lock, with
      `get_or_create(session_id)` and `drop(session_id)`). Session ids come from
      `secrets.token_urlsafe()`, stored in `request.session["cui"]` through Starlette's
      `SessionMiddleware` (`secret_key` from a `COMPOSEUI_SECRET` env var, falling
      back to a random per-process key with a logged warning: sessions then don't
      survive a restart, which is fine for dev). Keep the default `same_site="lax"`:
      cross-site POSTs don't carry the cookie, which is the CSRF story for v1.~~
   2. ~~**Per-session construction (design decision).** Each session needs its own
      `MainView`, built by `build_main_view()`. `WebApplication` already takes a factory
      for this reason. Per session, the store must: build it, call core's
      `_add_reference_to_signals(main_view, model)` (so `main_view`/`model` injection
      works for that instance), set `is_visible = True`, and render it. **Limitation to
      document:** `app.connect(view=app.main_view.x, ...)` binds to the template
      instance only, so web apps must wire behavior inside the views (as
      `pipeform.py`/the README already do) or in an overridable
      `WebApplication.setup_session(main_view)` hook. Add that hook. A shared `Model`
      (`ModelApplication`) is shared across sessions; say so in the docstring.~~
   3. ~~Render-time registration: replace M2's global `WeakValueDictionary` with a
      `ContextVar[dict[str, WebRenderer] | None]` that the store sets while it calls
      `main_view.render(RendererType.WEB)`, so each `WebRenderer.render()` registers
      into *its* session. This keeps the lookup per session and stops a client from
      posting another session's (guessable, `id()`-based) widget ids. The renderer
      also keeps a reference to its session's lock for `call_on_main_thread` (M2
      step 8).~~
   4. ~~Routes resolve `request.session` → `WebSession`, and run dispatch/render under
      `session.lock`. A request without a valid session (expired cookie, server
      restart) on `POST /widget/...` responds with an `HX-Refresh: true` header, so the
      page reloads into a fresh session instead of erroring.~~
   5. ~~`-f FILE`: apply it to each new session's `MainView` (`load_state` after build).
      That is the meaning closest to "open the app with this study".~~
   6. ~~Eviction: idle TTL (e.g. 1 h since last request, checked on access) so the dict
      doesn't grow forever. Cancel a dropped session's pending `StatusBar._timer`.~~
   7. ~~Tests: two `TestClient`s (separate cookie jars) edit the same widget path and each
      sees only its own value; client A posting client B's widget id gets 404; no cookie
      on POST gives `HX-Refresh`; `setup_session` runs once per session. `make check`.~~

   *Implementation notes (M6 as built), where it differs from the steps above:*
   - **No `COMPOSEUI_SECRET`:** the cookie is signed with a random per-process key.
     Sessions live in memory, so after a restart an old cookie has no session to point
     at whatever the key, and the session ids are unguessable 32-byte tokens anyway.
     A fixed key would add configuration without keeping anything alive.
   - **`RenderTarget`** (in `webrenderer.py`: a session's renderers by id plus its
     `RLock`) is what `rendering_into()` registers renderers into, and `WebSession`
     (in `session.py`) subclasses it with the `MainView` and the locked `page_html`/
     `handle_event`/`fragment` entry points. A renderer rendered outside any session
     (renderer-level tests) registers nowhere and calls `call_on_main_thread` callbacks
     directly.
   - **Expiry** is checked on each store access (`>= session_ttl` idle seconds, a
     `WebApplication.session_ttl` class setting, 1 h by default). A dropped session's
     `StatusBar` timer isn't cancelled: that would mean reaching into the private
     `_timer`, and a late clear on a tree nothing displays any more is harmless.
   - **Per-session construction** runs `build_main_view()`,
     `_add_reference_to_signals`, `is_visible = True`, then `setup_session(main_view)`,
     and only then `load_state(-f FILE)`, matching Qt/Textual apps that load `-f`
     after their wiring. `WebApplication` extends `Application` only; a web
     `ModelApplication` (one `Model` shared by every session) is not built yet.
   - Tests reach each session's view through the real `setup_session` hook (no
     test-only accessor), and cover: two browsers isolated, another session's widget
     id → 404 (with a positive control), no live session → `HX-Refresh` on POST and
     GET, one build per session across reloads, idle expiry, `-f` in every new
     session (through `run()`, with only `uvicorn.run` replaced), and the timer waiting
     for the session lock (M9 step 3, done early). Checked in Chromium with two
     browser contexts, plus a server restart mid-session.

8. **M7 — Save/Load state.** These fit neither the generic widget-dispatch endpoint nor
   the `MainRenderer.open_file()/save_file() -> Path | None` contract: there is no
   browser-side filesystem path to hand back. This is a deliberate deviation, not a 1:1
   port. Decided (see M1 follow-ups): `WebMainRenderer.open_file`/`save_file` return
   `None`, and the real work happens in two endpoints.

   1. ~~`GET /state` (Save): `json.dumps(CONVERTER.unstructure(main_view))` with
      `Content-Disposition: attachment; filename="{name}"`, where the name is
      `state_filepath.name` if set, else `f"{slug(title)}{extension}"`. A plain
      `<a href="/state" download>`, *not* htmx: htmx can't trigger downloads.~~
   2. ~~`POST /state` (Open): `<input type="file" name="file" accept="{extension}"
      hx-post="/state" hx-encoding="multipart/form-data" hx-trigger="change"
      hx-swap="none">`. The handler reads the upload, rejects the wrong extension or bad
      JSON with a `status_bar.show_message(...)` OOB fragment (and a 200, so htmx swaps
      it), then applies it with `composeui.core.view._apply_state(main_view, data)`.
      That is the same in-place apply `load_state` uses, minus the `Path`; importing a
      core private is acceptable here, and tests already do it. Note a possible public
      `MainView.load_state_data(dict)` as a follow-up rather than changing core now.
      Set `state_filepath = Path(upload.filename)` (name only) so the next Save offers
      the same name.~~
   3. ~~A load touches arbitrarily many attributes, so skip the dirty set entirely and
      respond with `HX-Refresh: true`. `GET /` re-renders from the session's (now
      loaded) state.~~
   4. ~~Tests: round trip. Change Name/edge type, `GET /state`, check headers + JSON, build
      a fresh session, `POST /state` with that JSON, then check that the view state is
      restored (edge type value is `EdgeType.Chamfer`, chamfer group visible in the next
      `GET /`). A bad extension or invalid JSON gives a status bar error and no state
      change. `make check`.~~

   *Implementation notes (M7 as built), where it differs from the steps above:*
   - **Endpoints only; the Save link and Open file input arrive with M8's menu.**
     M7 checked them over HTTP: in tests, and with curl against a real server (save in
     one cookie session, upload into a fresh one, the page shows the loaded name).
   - **A rejected file never half-loads.** `_apply_state` sets fields one by one, so a
     file failing halfway (a valid name, then an age of `"abc"`) used to leave the name
     applied. The upload is first applied to a scratch instance of the main view's
     class, and the session is only touched if that succeeds. Rejections, each with a
     status-bar message and no state change: wrong extension, more than 5 MB, invalid
     JSON, JSON that isn't an object, a file that doesn't structure into the view (the
     cattrs/conversion errors listed in `session._BAD_STATE_ERRORS`).
   - **File names are sanitized** to `[A-Za-z0-9._-]` before reaching the download's
     `Content-Disposition`: an uploaded name is attacker-controlled, and a raw quote
     there could break out of the header value. The test builds its multipart body by
     hand, because httpx percent-encodes the quote before it would reach the server.
     The default download name is the lowercased title plus the extension
     (`hello-composeui.hello`).
   - Without a session, `GET /state` redirects to `/` (a plain link, so no `HX-*`
     header would work) and `POST /state` answers `HX-Refresh`. Both live in
     `WebSession.save_state`/`load_state` under the session lock. Tests use the hello
     example (name and greeting style round-trip through a download and an upload into
     another browser's session) rather than pipeform.

9. **M8 — Menu / ActionView.** A daisyUI navbar/dropdown for `FileMenu`, with
   `triggered` signals posted to endpoints.

   1. ~~`WebMenuRenderer` (`"menu"`): `<div class="dropdown"><div tabindex="0"
      role="button" class="btn btn-ghost">{title}</div><ul class="menu dropdown-content
      ...">children</ul></div>`, walking `children_views` the same way the form walks
      rows. `Menu.__attrs_post_init__` sets `is_visible = False` ("visible only when
      triggered", a Qt popup notion), so the web renderer **ignores** `is_visible` for
      menus (no-op dispatcher entry, like `_TextualNoopRenderer`). Otherwise the menu
      would always be `hidden`.~~
   2. ~~`WebActionRenderer` (`"action"`): `<li><button hx-post="/widget/{id}"
      hx-vals='{"event": "triggered"}' hx-swap="none">{text}<kbd
      class="kbd kbd-sm">{shortcut}</kbd></button></li>`. `dispatch("triggered")` →
      `view.triggered.emit()`. `WebSeparatorRenderer` (`"separator"`): an `<li>`
      divider. Exceptions, by type: `SaveAction`/`SaveAsAction` render as the M7
      download link (`<a href="/state" download>`), and `OpenFileAction` renders as the
      M7 file input. The `GET /state` handler still emits `triggered` first, so user
      callbacks connected to it run; core's `FileMenu._save_state` then just gets
      `None` from `ask_save_filepath`, which is harmless.~~
   3. ~~Keyboard shortcuts: display only for v1. Chrome reserves Ctrl+N/Ctrl+W/Ctrl+T, and
      Ctrl+Q quits Firefox on Linux, so faithful bindings are impossible. Ctrl+S/Ctrl+O
      *can* be intercepted (`keydown` + `preventDefault`), but that needs a few lines
      of JS. Note it as a follow-up.~~
   4. ~~`WebMainRenderer`: render the main view's menus in a top `navbar bg-base-100`
      before the content. `close()` sets a `closed` flag on the session; after
      dispatch, the route sees it, drops the session (M6), and answers with
      `HX-Redirect: /` (a fresh session). New stays generic: `NewAction._new_study` is a
      no-op hook in core, the same as on Qt/Textual.~~
   5. ~~Tests: `GET /` contains the navbar with New/Open/Save/Save As/Exit and their
      `kbd` shortcuts; POSTing Exit drops the session and returns `HX-Redirect`;
      a user callback connected to `new.triggered` runs on POST. `make check`.~~

   *Implementation notes (M8 as built), where it differs from the steps above:*
   - **Save, Save As and Open still fire their own `triggered`.** The Save/Save As
     links are `/state?trigger={action id}`, and the Open file input posts a `trigger`
     field with the upload. `WebSession.trigger_action` fires that action's
     `triggered` (only for an action id of this session) before the download or the
     load, so user code connected to those signals still runs. Core's
     `FileMenu._save_state`/`_load_state` then get `None` from `ask_*_filepath`,
     which is harmless.
   - **Checkable actions show `is_checked` (a ✓) but triggering doesn't toggle it.**
     That matches Qt, whose `QAction` toggles its own check mark without writing it
     back to the view. Disabled actions render as `menu-disabled` and refuse
     `triggered` (400). `icon` and `data` mark the item dirty but aren't displayed.
   - The Open file input has no `accept` filter: an action doesn't know its main
     view's extension. The server checks the extension instead (M7). Items close the
     dropdown on click (`hx-on:click` blurs the focused element, since daisyUI keeps a
     dropdown open while something inside it has focus).
   - **Exit** sets `WebMainRenderer.is_closed` from `close()`. After the request,
     `widget_event` sees `WebSession.closed`, drops the session from the store, and
     answers `HX-Redirect: /`, which lands on a fresh session.
   - Checked in Chromium: the menu sits in the header with its shortcuts; Save
     downloads `hello-composeui.hello` and closes the dropdown; Exit lands on an empty
     form; Open with the saved file brings the name back.
   - **Revised after M8 (shortcuts):** step 3's display-only `Ctrl+…` labels are
     replaced by working shortcuts the browser leaves free. A view's `Ctrl+<letter or
     digit>` shows and works as `Alt+Shift+<key>` (New N, Open O, Save S, Exit Q), the
     combination web apps use for their own shortcuts. One page-level `keydown`
     handler (in `page.py`) clicks the item marked `data-shortcut="Key<X>"`, matching
     the physical key (`event.code`), so keyboard layouts and macOS's Option key don't
     change it. Any other shortcut has no web equivalent and shows nothing: Save As's
     `Ctrl+Shift+S` would collide with Save's, and in a browser it downloads just like
     Save anyway. Core's shortcuts are unchanged; Qt and Textual still use them.
     Checked in Chromium from inside a text field: Alt+Shift+S downloads, N posts New,
     Q exits to a fresh form, O opens the file picker.
   - **Revised after M8 (New):** step 4 left New generic, and so it did nothing:
     core's `NewAction._new_study` was an empty method, on every backend. Fixed in
     core: New calls `MainView.reset_state()`, which builds a fresh instance of the
     main view's class and copies its state into the live tree in place (like
     `load_state`: renderers and connected signals stay bound, and only fields that
     actually change reach the UI). So it also restores whatever
     `__attrs_post_init__` set up, and clears `state_filepath`. On the web, the reset
     fields come back as ordinary out-of-band fragments: no reload, same session. A
     first web-only version (swapping in a new session view) was replaced by this.
     Checked: web (File → New and Alt+Shift+N), Qt (the real `QAction`), Textual
     (Ctrl+N in the pilot) all clear the form.

10. **M9 — Tests.** By now each milestone has added its own tests to
    `tests/test_webrenderer.py` (AGENTS.md: every behavior change needs a test). M9 is
    the consolidation pass, the same shape as `tests/test_qtrenderer.py`'s module
    docstring + pipeform-driven flow:
    1. ~~One end-to-end pipeform scenario through `TestClient` with `HX-Request: true`:
       load the page, edit Name, change material, pick Fillet, fix a dimension until the
       form log clears, save, reload in a new session, confirm the state. Assert on the
       returned HTML (OOB fragments present, source widget absent) *and* on the `View`
       objects' state after every step.~~
    2. ~~A small HTML helper for assertions (`stdlib html.parser`, which finds an element
       by id and returns its attributes/text) so tests don't do brittle substring
       matching on markup. No new dependency.~~
    3. ~~A thread-safety test in the style of `tests/test_statusbar_thread_safety.py`:
       `show_message` with a tiny timeout, the timer fires while a request holds the
       session lock, and the clear lands after it with no exception.~~ *(Done early in M6:
       `test_a_message_timer_waits_for_the_request_holding_the_session`.)*
    4. ~~Coverage check: `webcore/` at least on par with `qtrenderer.py`'s 86%.~~
    5. ~~Add `--extra web` to the README/AGENTS.md dev sync line if it isn't there yet;
       `make all` clean.~~

    *Implementation notes (M9 as built):*
    - **The end-to-end scenario found a core save/load bug, on every backend.** Saved
      files left out each field equal to its attrs default (`_cattrs_omit_if_default`),
      but views set their starting state in `__attrs_post_init__`. So a value changed
      back to its attrs default loaded as the fresh view's starting value instead: a
      reopened pipe study with a name still showed "A name is mandatory", and a Fillet
      study loaded with its Fillet group hidden. Saved files now hold every field,
      covered by a core regression test (`test_load_state_restores_values_equal_to_
      attrs_defaults`). Saving every field also exposed `MainView.file_view` (a file
      dialog's last answer) overwriting the path the dialog had just returned on load.
      It is now `OMIT`ted from state like validators: never saved, loaded or reset.
    - Scenario: `test_a_pipe_study_from_first_page_to_reopening_it_elsewhere`, with the
      helper `_element`/`_swapped`/`_selected` built on `html.parser` (an element by
      id, its attributes, unescaped text and descendant tags). It fails at the reopened
      name's message with the old `omit_if_default`. Coverage: `routes.py`/`session.py`
      99%, `webrenderer.py` 96%, `page.py`/`webapplication.py` 100% (bar: 86%). The
      README's dev sync line now installs every extra (`--all-extras`), like AGENTS.md;
      `make all` is clean.
    - **Test campaign (approved inventory), three commits, tests only:** five tests
      deleted because stronger tests own their contracts (each owner proven by breaking
      production and watching it fail; the age test gained a message-only change no
      test owned before), four merged into their owners (the hello page structure,
      escaping of an input value and a label's text, the pipe form's first page and its
      "typing alone doesn't run the cross-field check" step), and thirteen rewritten
      onto the HTML helper instead of raw-markup substrings (the nested-fragment test
      now uses a real pipe form group, and its test-only container renderer is gone).
      63 web tests became 58; coverage unchanged.

11. **M10 — Polish.**
    1. ~~Swap the CDN Tailwind/daisyUI tags for a compiled `static/app.css`. Tailwind
       ships a standalone CLI binary, so the Python project needs no Node/npm: download
       it once, run `tailwindcss -i input.css -o static/app.css` with
       `@plugin "daisyui"` (daisyUI is also available as a standalone `daisyui.mjs` for
       the binary), and commit the output. Classes are built in Python strings, so
       point Tailwind's `@source` at `src/composeui/webcore/**/*.py`. Add a
       `make css` target. Also vendor or drop the CDN dependency entirely, so the
       backend works offline.~~
    2. ~~`StatusBar` auto-clear: **use a one-shot fetch, not polling.** When `message`
       is non-empty and `timeout > 0`, render the status bar with
       `hx-get="/widget/{id}" hx-trigger="load delay:{timeout}s" hx-swap="outerHTML"`.
       Add a `GET /widget/{id}` route that returns the fragment's current HTML. The
       server's own `threading.Timer` will have cleared the message by then, so the
       swap shows the cleared state at the right time, with no every-2s traffic and no
       SSE. A new message re-renders the bar, and the new fragment carries a fresh
       trigger, so an older pending fetch just returns current state harmlessly.~~ *(Done early, after M4:
       before this, the browser kept showing a message the server had already
       cleared, even across unrelated updates, because the timer clears it outside any
       request. Built as described, plus a 0.25 s margin on the delay, since the browser's
       delay starts slightly after the server's timer. Checked in Chromium: a message is
       gone by ~3.3 s, and one re-shown before then keeps its own full delay.)*
    3. ~~Accessibility pass: `aria-live="polite"` on the status bar and logs,
       `aria-invalid`/`aria-describedby` linking an input to its row log, and `<label
       for>` everywhere (M3 step 1).~~
    4. ~~README section for the web backend, mirroring the Qt quickstart: the hello
       example with `WebApplication`, `uv sync --extra web`,
       `uv run python -m examples.webhello`, plus the documented limitations (per-session
       construction and `app.connect`, single process, no unprompted push, save/open
       through browser download/upload).~~

    *Implementation notes (M10 as built):*
    - **CSS:** `css/app.css` (Tailwind 4.3.3 + daisyUI 5.7.47, scanning only
      `src/composeui/webcore`, plus the field-error rule moved out of `page.py`'s inline
      `<style>`) builds the committed `static/app.css` with `make css`. The target
      downloads the pinned standalone CLI and `daisyui.mjs` into the git-ignored
      `css/vendor/`. The page loads nothing from another host: checked in Chromium with
      every external request blocked (none attempted, styling identical). Tests: the
      page references no other host, and every class found in live hello/pipeform pages
      (plus each log colour and a disabled menu item) is in the built stylesheet, which
      catches a class added in Python without `make css`.
    - **Accessibility:** a form row's field gets `aria-describedby` → its log, and
      `aria-invalid` while the log shows an error. Because the field isn't swapped while
      being typed in, a small `MutationObserver` in `page.py` keeps `aria-invalid` in
      step whenever a log is swapped. A radio group gets `aria-labelledby` → its row's
      label (`<label for>` can't name a `<div>`). Checked in Chromium's accessibility
      tree: the name field reads as "Name", described "A name is mandatory", invalid
      until a name is typed; the radio group is named "Greeting".
    - **README:** a "Web backend" section (the quickstart's views served by
      `WebApplication`, run and checked as written, plus how the web differs: sessions,
      `setup_session`, save/open, Alt+Shift shortcuts, single process and no push), the
      backends in the intro, the `tui`/`web` install lines, and the quickstart's
      `main_view: "HelloMainView"` annotation (which fails mypy) changed to `MainView`.
      AGENTS.md documents `make css` and `css/`.

## Explicit non-goals for v1

- No websocket/SSE channel (see StatusBar note above).
- No multi-process/horizontal scaling (in-memory session dict only).
- No attempt to literally implement `MainRenderer.open_file`/`save_file`'s blocking
  `Path`-returning contract — the web backend gets its own save/open endpoints instead.
