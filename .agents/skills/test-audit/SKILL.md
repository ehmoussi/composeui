---
name: test-audit
description: "Invoke whenever writing, changing, reviewing, or sweeping ComposeUI tests. Authoring gate for new tests plus audit workflow for low-value, implementation-coupled, or duplicative tests and the test-only production seams they demand."
---

# Test Audit

Three modes, one value bar. Authoring mode gates every new or changed test at
write time. Audit mode runs focused sweeps of tests that re-assert source,
duplicate stronger proof, couple behavior to implementation, or keep test-only
production seams alive. Continue broad audits as separate coherent follow-up
commits; optimize for confidence, not deletion count. Campaign mode prunes one
whole backend's or core area's test surface; see [Campaign mode](#campaign-mode).

## Authoring gate

Before adding any test, answer four questions; a missing answer means do not
add it yet:

1. What observable behavior, invariant, or independent contract does it protect?
2. What credible regression makes it fail?
3. Why does existing coverage not already catch that failure? Each contract has
   one primary test owner at the strongest boundary; another layer needs its
   own distinct risk, such as a toolkit event, threading, or HTTP round-trip
   failure the owner cannot reach. Prefer extending a `pytest.mark.parametrize`
   case or shared fixture (e.g. the `app`/`client`/`rows` fixtures in
   `tests/test_webrenderer.py`) over a near-duplicate test; consolidate
   duplicated setup in the same change.
4. Does it need a production seam (public helper, flag, wrapper, injection hook,
   extra `RENDERERS` entry) that no production caller needs? If yes, move the
   test to the real boundary instead.

Then check the test against every [junk pattern](#junk-patterns); a match fails
the gate unless the [retention bar](#retention-bar) names the contract it
independently guards. A test that would break under behavior-preserving
refactoring is asserting implementation, not behavior; rewrite it at the
owning boundary before landing it.

The owning boundary in ComposeUI is usually a real rendered widget: set a view
attribute and assert on the toolkit widget, or drive the widget and assert on
the view or a `Signal` callback. Use `qtbot` for Qt, `App.run_test()` with the
pilot for Textual, and the Starlette `TestClient` for web. Pure core behavior
(`Signal` injection, validators, `save_state`/`load_state`, registry) is owned
by core tests with no backend. What happens only once a response reaches a real
page is owned by Playwright in `tests/test_browser.py`; see
[Browser tests](#browser-tests-playwright).

Bug regression tests must fail on the pre-fix code for the intended reason and
pass after the owner-boundary repair. A regression test that never demonstrably
failed proves the mock, not the fix. One regression at the owner boundary
covers the bug; do not replay the same scenario in every backend unless each
backend has its own renderer code path for it.

## Browser tests (Playwright)

`tests/test_browser.py` serves the web app over uvicorn and drives it in headless
Chromium. Browser tests are slow and opt-in, so the gate is stricter for them:

- **Only what a browser alone can show.** If the markup or the response proves it
  (an attribute, a fragment, an `HX-*` header, a status code), it belongs in
  `tests/test_webrenderer.py` with the `TestClient`, even when the user only
  notices it in a browser: an `accept` attribute, an `aria-describedby` link, an
  OOB fragment. A browser test owns what happens after the response arrives: the
  scripts in `webcore/static/page.js` (Alt+Shift shortcuts, keeping `aria-invalid` in step
  with a swapped log), htmx swaps leaving the focused field and its caret alone, a
  fragment fetching itself again (the status bar's auto-clear), the page loading
  nothing from another host.
- **Drive it like a user.** Find elements by label or role (`get_by_label`,
  `get_by_role`, the `footer` landmark), never by `cui-<id>` ids, which come from
  `id()` and change every run. Act with `press_sequentially`, `press` and
  `keyboard.press`; `page.evaluate` that sets a value, dispatches an event or
  calls `htmx.ajax` supplies the event ordering the browser should produce. Use
  `page.evaluate` only to read what no locator exposes (a computed style,
  `typeof htmx`).
- **Wait on events, not time.** `expect(...)` assertions retry on their own; wrap
  an action that posts in `_posted(page)` to wait for the server's answer. No
  `time.sleep` or `page.wait_for_timeout`. A test of a timeout derives its wait
  from the app's own setting (`_MESSAGE_TIMEOUT`), with a margin, rather than a
  bare number.
- **The real app, one session per test.** The `page` fixture opens a fresh browser
  context, so each test gets its own cookie and session; the server and browser
  are module-scoped and must stay stateless between tests. Configure the app
  through `setup_session` (as `_BrowserHelloApp` does), not by reaching into
  sessions. `page.route` may block or record requests to other hosts; never stub
  the app's own routes, which turns the test into a mock of the server.
- **One journey per contract.** Prefer one test that types, then checks the
  field, the caret and the swapped neighbours together, over several tests
  replaying the same setup. Never repeat a `TestClient` test in the browser.
- **Keep the guards.** New tests live in `tests/test_browser.py`, which is marked
  `browser` (`pytestmark`), skips without Playwright (`pytest.importorskip`) and
  skips without Chromium (the `browser` fixture). `make test` excludes the marker
  and CI runs them in its own `browser` job.

A skipped browser test proves nothing: when the regression proof needs one,
check the run reports it passed, not skipped, and break the script or renderer
it covers to show it fails.

## Junk patterns

The shared checklist for both modes: the authoring gate rejects a new test that
matches one, and audits hunt for existing tests that do.

- assertion-free coverage probes (render a view, assert nothing about the widget);
- self-comparisons and identity copiers (set a view attribute, read the same
  attribute back without going through the widget);
- copied inventories: hardcoded lists of `RENDERERS` keys, `_refresh_dispatcher`
  attribute names, `RendererType` members, or view field names;
- exact source, import, or string greps, including whole-HTML snapshot matches
  where a targeted fragment or attribute check is the real contract;
- private predicate or call-shape tests (`_refresh_*` handlers,
  web `_dirty` bookkeeping) duplicated by a real widget or request test;
- duplicate invocations of the same contract across Qt, Textual and web tests
  when the behavior lives in `composeui.core`;
- backend-local replays of shared core helpers (validation, signal injection,
  cattrs hooks) that core tests already own;
- tests whose only purpose is preserving test-only exports, globals, or wrappers;
- dead production code whose only callers are tests;
- expected values produced by the renderer or helper under test (e.g. comparing
  the response to another call of the same `render`);
- mocks that implement the asserted behavior: a fake widget, a `MagicMock`
  renderer, or a patched `Signal.emit` standing in for the real toolkit path, or
  one identical mock standing in for different backends;
- fixtures that supply the event ordering the toolkit should produce, such as
  calling the view-side handler directly instead of typing into the widget, or
  state persistence asserted against a file `save_state` never writes;
- capability tests that restate declared values (`_renderer_key`, field
  defaults, `attrs` metadata) instead of exercising the rendering or
  serialization they promise;
- negative controls that pass for an unrelated reason, such as a `None` renderer
  because the backend never registered the key, or a 400 from a different guard
  in `webcore/routes.py`;
- names or fixtures that promise more than the input exercises, such as a
  "round-trips" test that only checks one direction;
- browser tests that re-check markup a `TestClient` test can see, wait with
  fixed sleeps, locate by `cui-<id>` ids, or set values through `page.evaluate`
  instead of typing (see [Browser tests](#browser-tests-playwright)).

## Value bar

Tests justify their maintenance cost by protecting behavior, a credible
regression, or an independently meaningful contract. In an audit, an existing
test that must change for behavior-preserving source reorganization is suspect,
not automatically deletable; the authoring gate still rejects new ones.

Before judging a candidate, read the complete test and production owner, its
entry point, callers, callees, sibling backend implementations, overlapping
tests (including the examples in `src/examples/` the tests drive), and relevant
`git log -p` history. Read `AGENTS.md` and, for web work, the design notes at
the end of `ROADMAP.md` first. When the test claims toolkit-backed behavior (Qt
signals, Textual message ordering, htmx swap semantics, cattrs hooks), inspect
the dependency source or types under `.venv/` directly.

## Discovery

Keep discovery read-only and report evidence before editing. For broad scope,
split discovery into lanes (parallel agents only when the user asks for them):

- core (`src/composeui/core/`, `tests/test_view_state.py`,
  `tests/test_validation.py`, `tests/test_renderer_registry.py`);
- Qt (`src/composeui/qtcore/`, `tests/test_qtrenderer.py`,
  `tests/test_pipeview.py`, `tests/test_statusbar_thread_safety.py`);
- Textual (`src/composeui/textualcore/`, `tests/test_textual_renderer.py`);
- web (`src/composeui/webcore/`, `tests/test_webrenderer.py`, and
  `tests/test_browser.py` for `webcore/static/page.js` and htmx behavior);
- a cross-cutting pattern sweep (same contract asserted in several backends,
  examples used as fixtures, coverage-only tests).

Use `make test` coverage output (`--cov-report=term-missing`) to find untested
renderer branches, but never write a test just to cover a line. Outside
campaign mode, prefer a few high-confidence candidates over a large speculative
inventory. Hunt for the [junk patterns](#junk-patterns).

## Retention bar

Keep a test when it independently enforces a public view API, the renderer
contract (`render`, `refresh_attribute`, `_refresh_dispatcher`),
`Signal`/`Application.connect` keyword injection (`view`, `main_view`, `model`),
saved-state format and `load_state` compatibility, field exclusion from state
(`Signal`/`Renderer`/`Validator`), backend registration, thread safety, HTML
escaping or other web security, Python 3.9 compatibility, or an architecture
rule from `AGENTS.md`. Also keep:

- call ordering when order is observable behavior (e.g. editing-finished fires
  once, after the value is applied);
- regressions with a credible failure mode;
- source or import inspection when it is the cheapest independent guard, such
  as `test_importing_the_core_does_not_import_any_backend_toolkit`: it fails
  when the contract changes and survives an identifier-only refactor;
- cross-backend consistency checks derived from live data, such as
  `test_every_backend_registers_the_same_renderer_keys` (it compares the
  backends' `RENDERERS` to each other rather than to a copied list);
- a retained test that fails on the baseline: treat it as a possible product
  bug, reproduce it, and repair the owner rather than deleting it.

Static or slow is not a deletion reason. A test that resembles implementation
may still be the independent contract; prove otherwise before removing it.

## Candidate evidence

Record every field below before editing. A missing field means the candidate is
not ready for deletion:

- exact test name and location (`tests/<file>.py::<test>`);
- what failure it can actually detect;
- non-test callers of the covered production or support seam;
- stronger remaining owner-boundary proof, or why no proof is needed;
- relevant history (`git log -L` / `git log -S`) and the reason the test or seam
  exists;
- production or test-support deletion unlocked;
- risk and the focused validation command.

## Edit shape

Choose one coherent owner-boundary batch, usually one backend or one core area.
Delete obsolete test-only exports, globals, wrappers, and dead production paths
instead of preserving aliases. Move retained regressions to their canonical
owners (core behavior to core tests, renderer behavior to that backend's file).
Consolidate repeated per-backend assertions into one core test or one
parametrized test.

Prefer net-negative production LOC. Do not add replacement tests that restate
the same implementation, and do not convert uncertain candidates into cleanup
to increase deletion counts. Keep `ruff` (`select = ["ALL"]`) and `mypy` clean
without new `noqa`; tests stay fully annotated.

## Campaign mode

Campaign mode sweeps every test owned by one backend or core area in a single
pass. Before starting, list every test in scope with a one-line verdict (keep,
rewrite at owner boundary, merge into parametrized case, delete) plus its
evidence fields, and get the user's go-ahead on that inventory before editing.
Land the campaign as several focused commits (deletions, consolidations,
rewrites), each passing validation on its own.

## Validation

1. Run the smallest owner and sibling tests:
   `QT_QPA_PLATFORM=offscreen uv run pytest tests/<file>.py -k <filter>`.
2. For deleted tests, confirm the contract is still owned: run the remaining
   owner test, and temporarily break the production code to show it fails;
   revert the break before continuing.
3. Run `make lint`, then `git diff --check`.
4. Run `make mypy`, then the full `make test` (CI runs the same checks, but run them first).
   Compare coverage against the baseline run and explain any drop.
   When browser tests, `webcore/static/page.js` or the markup they rely on changed, also
   run `make browser-test` (once: `uv run --group browser playwright install
   chromium`) and check they passed rather than skipped; `make test` excludes them.
5. Inspect `git diff --numstat`; report production/examples separately from
   tests and test support.
6. After final audit edits, run the `code-review` skill on the diff.

## Landing and continuation

Commit, push, or open a PR only when authorized. Follow the commit rules in
`AGENTS.md` (short imperative capitalized subject, one focused change per
commit). Land one coherent batch at a time; after landing, refresh from the
current branch and rerun read-only discovery for the next high-confidence batch.

## Handoff

Report:

- root cause and removed low-value categories;
- production owner simplifications;
- retained false positives and why they remain valuable;
- focused and full proof actually run, with coverage before and after;
- production versus test LOC;
- commit or PR state;
- named follow-ups.
