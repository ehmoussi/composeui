# Web backend — Starlette + htmx + daisyUI

**Status: complete** (M0–M10, branch `web-backend`). `composeui.webcore` is a third
backend next to `qtcore` and `textualcore`: it renders `composeui.core.view` trees as
server-rendered HTML that htmx updates, with no client-side framework. Selected with
`RendererType.WEB`, run with `WebApplication`. Follow-ups live in `NEXT_PLAN.md`.

## Milestones

| | Delivered |
|---|---|
| M0 | `web` extra, `webcore/` package, `RendererType.WEB`, vendored htmx, page shell |
| M1 | `WebMainRenderer` (page) and `WebStatusBarRenderer` |
| M2 | Text input; the dirty-set / out-of-band update mechanism everything else reuses |
| M3 | Label, form label, float input, validation log |
| M4 | Radio group, combobox |
| M5 | Forms and group forms; `pipeform.py` runs on the web (`WebPipeApp`) |
| M6 | One app state per browser session |
| M7 | Save (download) and Open (upload) of the view state |
| M8 | File menu in the header; Alt+Shift shortcuts; New and Exit |
| M9 | End-to-end pipe form test, HTML assertion helper, test campaign (63 → 58 tests) |
| M10 | Compiled CSS (no CDN), accessibility, README section |

Core fixes found along the way, on every backend: New now resets the main view
(`MainView.reset_state()`, it was a no-op); saved files hold every field (fields equal to
their attrs default used to load back as the fresh view's starting state);
`MainView.file_view` is excluded from saved state.

## Decisions

- **htmx request/response, not websockets or a JS framework.** Interactions start from
  a browser event; the response swaps in HTML the server rendered. Changes elsewhere on
  the page (e.g. the status bar) arrive as htmx out-of-band (OOB) swaps.
- **Starlette, not FastAPI:** `cattrs` already serializes, and Pydantic/OpenAPI add
  nothing to an HTML endpoint. **Hand-written HTML** per renderer, not Jinja2, matching
  the one-class-per-widget style of the other backends; all view text goes through
  `html.escape`.
- **No changes to `core/view.py` were needed for the backend itself**: same `Renderer`
  contract, one `RENDERERS` mapping, one `RendererType` member.

## How it works

**Renderers.** A renderer's rendered object is a stable id, `cui-{id(view)}-{role}`
(`_role` per class, so a form row's label, field and log, which share one view, get
distinct ids). `to_html(oob=...)` renders the fragment; its root keeps its id when hidden
(`hidden` attribute) so a later swap has a target. `dispatch(event, form)` applies a
browser event, the way Qt/Textual renderers react to widget signals.

**Updates.** Setting a view attribute marks its renderer dirty in a request-scoped set
(`collect_dirty`; a no-op outside requests, e.g. on the status bar's timer thread). After
dispatching, the route renders every dirty fragment as an OOB swap (`render_dirty`,
dropping fragments nested in another dirty one). **Focus rule:** the element that sent
the request is never swapped back (the value is set under `stop_refresh()`, and every
control uses `hx-swap="none"`), so typing is never interrupted. One exception: leaving a
float field with unparsable text swaps it back to the view's value.

**Events.** `POST /widget/{id}`, with the event name in the body: `input` →
`text_changed` + `text_edited`; `change` → `editing_finished` for text, `value_changed`
for choices (posted by label, the `values` key, like `serialize_value`); `triggered` for
actions. A `change` repeating the last posted text doesn't re-emit.

| Route | Purpose |
|---|---|
| `GET /` | The page (starts a session if needed) |
| `POST /widget/{id}` | A browser event → OOB fragments of everything it changed |
| `GET /widget/{id}` | A fragment as it is now (a status bar refetches itself after its timeout) |
| `GET /state?trigger=` | Save: download the state (fires the Save action first) |
| `POST /state` | Open: upload a state file (fires the Open action first), then reload |
| `/static` | htmx, `app.css` |

**Sessions.** A signed cookie (random per-process key, `same_site="lax"`) maps to a
`WebSession` in an in-memory `SessionStore`, dropped after `session_ttl` (1 h) idle. A
session owns its renderers by id and an `RLock`: widget ids only resolve within their own
session, and the status bar timer takes the lock (`call_on_main_thread`). Each session
builds its own main view: `build_main_view()`, signal injection, `setup_session(main_view)`,
then `-f FILE`. A request whose session is gone answers `HX-Refresh` (a plain download
link is redirected instead). Exit drops the session and redirects to a fresh one; New
calls core's `reset_state()`.

**Save / Open.** Save downloads `save_state`'s JSON under a sanitized file name. An upload
is checked (extension, ≤ 5 MB, a JSON object) and applied to a scratch instance first, so
a bad file never half-loads; a rejection says why in the status bar.

**Page.** Header with the menus and title, the content in a card, the status bar docked at
the bottom. Responses send `Cache-Control: no-store` and controls set
`autocomplete="off"`, so a reload always shows the server's state. Menu shortcuts:
a view's `Ctrl+<key>` works as `Alt+Shift+<key>` (browsers keep the Ctrl ones), through
one `keydown` handler matching the physical key; Save As has none.

**Styling.** `css/app.css` builds the committed `static/app.css` with `make css`
(Tailwind 4.3.3 and daisyUI 5.7.47 standalone; tools downloaded into the ignored
`css/vendor/`). Nothing loads from another host. A field turns red when the log after it
shows an error.

**Accessibility.** `aria-live` on the status bar and logs; `<label for>`; a row's field is
`aria-describedby` its log and `aria-invalid` while it shows an error (a small
`MutationObserver` keeps that in sync, since the field isn't swapped while typed in); a
radio group is `aria-labelledby` its row's label.

```
src/composeui/webcore/
    webapplication.py   WebApplication, create_starlette_app, setup_session, session_ttl
    webrenderer.py      WebRenderer + one class per widget, RENDERERS, collect_dirty
    session.py          WebSession, SessionStore, save/load of uploaded state
    routes.py           the routes above
    page.py             page shell and its small scripts
    static/             htmx.min.js (vendored), app.css (built)
css/app.css             source of static/app.css
```

**Tests** (`tests/test_webrenderer.py`) drive the examples over HTTP with Starlette's
`TestClient`, reach each session's view through the real `setup_session` hook, and check
fragments with an `html.parser` helper. They include an end-to-end pipe form scenario
and a check that every class the renderers emit exists in the built stylesheet.
Browser-only behaviour (caret, shortcuts, `aria-invalid` sync, offline page, the status
bar's auto-clear) is checked in headless Chromium by `tests/test_browser.py`
(`make browser-test`).

## Differences from the desktop backends (by design)

- `open_file`/`save_file` return `None`; Save and Open are a download and an upload.
- `app.main_view` is only a template: wire behavior inside the views or in
  `setup_session`, since `app.connect(view=app.main_view...)` reaches no browser.
- Tabs of one browser share a session; state lives in memory (a restart starts over);
  single process.
- No server push: the page changes in response to the user's own requests (plus the
  status bar refetching itself after a timed message).
- `Menu.is_visible` is ignored (a dropdown is always shown); a checkable action shows
  `is_checked` but triggering doesn't toggle it (as with Qt's view state); `icon`/`data`
  aren't displayed; the Open file picker doesn't filter by extension (the server does).
