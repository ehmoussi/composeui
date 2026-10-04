# Pages plan

Add pages with a route to core, and a toolbar that mirrors those routes: clicking a toolbar
entry shows its page.

**Status: done** on the `pages` branch, with the recommendations below and real URL routes
on the web. Where the implementation differs from the plan:

- A page's `title` and `icon` aren't fields of their own: they read and write its
  `action`'s `text` and `icon`, so the toolbar can't drift from them.
- Pages aren't shown and hidden through their `is_visible`, which is saved, loaded and
  reset like any field and would then disagree with the unsaved `current_route`. Each
  backend puts every page in a slot of its own and shows the current route's slot,
  leaving `is_visible` to the page. The page actions are left out of saved state too
  (`OMIT`), so their check marks always match `current_route`.
- So New doesn't go back to the first page: `reset_state` skips omitted fields, and keeps
  the page shown, as it keeps `file_view`.
- Textual uses a `ContentSwitcher` and a row of `ComposeToolbarButton`s docked at the
  top; the current page's button is highlighted (`variant="primary"`).
- Web: an unknown address is a 404, not a redirect to the first page. A browser asks for
  addresses of its own (`/favicon.ico`), which would otherwise navigate the session. The
  history uses `HX-Push-Url` from the server on any navigation (a toolbar link, or an
  app's own `navigate`); htmx's history cache is off, so back and forward reload the page
  from the server instead of showing a stale copy.
- The three backends landed in one commit: the registry consistency test requires them
  to register the same keys.

There is no toolbar in core today: `MainView` only has a commented-out `study_toolbar`, and
the web header's "toolbar" is really the `FileMenu` drawn as buttons. This plan adds one.

## Core (`core/view.py`)

1. **`PageView(View)`**, renderer key `"page"`.
   - `route: str`: a unique id like `"inputs"` or `"results"`. Like `MainView.title`, it
     is set once in the subclass's `__attrs_post_init__` and frozen, so state loading
     never touches it.
   - `title: str` and `icon: Optional[str]`: what the toolbar shows for the page.
   - The page's content is its other view fields (forms, tables, labels). A page lays them
     out the way the main window lays out its content today: a vertical column.

2. **`Router(View)`**, renderer key `"router"`. It holds the pages as attrs fields, the
   same way `FormView` holds its rows.
   - `current_route: str`: starts on the first page's route.
   - `navigate(route)`: checks that the route exists (`ValueError` if not) and sets
     `current_route`. It then sets each page's `is_visible` to whether it is the current
     one. Showing a page is just the visibility every backend already handles, so
     backends need very little routing logic.
   - `route_changed: Signal[str]`, so app code can react to a page being opened.
   - `pages` property, like `FormView.field_rows`.

3. **The toolbar mirrors the routes.**
   - Each `PageView` has an `action: ActionView` field: checkable, with text and icon
     copied from the page's title and icon. That action is the page's toolbar entry, and
     it is left out of the page's content.
   - `Router.__attrs_post_init__` connects each page's `action.triggered` to
     `navigate(page.route)`. `navigate` keeps the check marks exclusive: only the current
     page's action is checked.
   - Clicking a toolbar entry is a plain `ActionView.triggered`, so the existing action
     renderers and shortcuts keep working. A page can even get a shortcut through
     `page.action.shortcut`.

4. **State.** `current_route` is navigation, not study data: tag it `OMIT`, as
   `file_view` is, so Save/Open don't record which page was open. "New" still goes back to
   the first page through `reset_state`'s rebuild. `MainView` itself doesn't change: an
   app adds a `router: MyRouter` field to its main view.

## Backends

Each main renderer treats a `Router` child specially.

- **Qt**: a `QToolBar` added with `addToolBar`, holding the pages' `QAction`s in an
  exclusive `QActionGroup`. The pages go in a `QStackedWidget` in the central widget,
  switched on `current_route`.
- **Textual**: a row of toolbar buttons at the top (or `Tabs`) and a `ContentSwitcher` for
  the pages.
- **Web**:
  - A navigation bar under the header with one button per page, the current one
    highlighted. All pages are rendered, and the ones not shown are `hidden`.
  - Real URL routes: `GET /{route}` opens the page on that route, and the toolbar buttons
    use `hx-push-url`. The address bar, back/forward and bookmarks then work.
  - An unknown route sends you to the first page.

Each backend registers `"page"` and `"router"`, so the registry consistency test still
passes.

## Example and tests

- **Example**: split `pipeform` into two pages, "Inputs" (the current form) and "Results"
  (a table), so the example shows routing on all three backends.
- **Core tests**:
  - `navigate` switches which page is visible and keeps the checks exclusive.
  - An unknown route raises `ValueError`.
  - `reset_state` goes back to the first page.
  - The current route isn't saved.
- **Backend tests**:
  - Qt and Textual: clicking a toolbar entry shows its page.
  - Web: `GET /results` serves that page, a toolbar POST swaps the page, and a browser
    test checks back/forward.

## Commits

1. Core `PageView` and `Router`
2. Qt
3. Textual
4. Web (including URL routes)
5. Example
6. README and docs

## Decisions

1. **The open page isn't saved** (`OMIT`).
2. **Toolbar entries are per page** (`PageView.action`); a generic `ToolBar` can come later.
3. **The web gets real URL routes now** (`/{route}` with history).
