---
name: web-security
description: "Invoke before adding or changing anything in ComposeUI's web backend that a browser reaches: a route, a method, a middleware, a response header, the session cookie, a form, an htmx attribute, a download or upload, or the page's scripts; and when reviewing such a change or asked whether the web backend is secure. Holds the CSRF and clickjacking rules taken from OWASP's cheat sheets, the defenses already in `webcore`, how to test them, the known gaps, and which other OWASP cheat sheet to read for uploads, XSS, CSP, headers, sessions, denial of service, deserialization and queries."
---

# Web Security

The web backend (`src/composeui/webcore/`) serves one main view per browser session,
behind a signed session cookie. Anything that cookie reaches is an attack surface: another
site can make the user's browser send requests that carry it (CSRF), or show the app in a
frame to steer the user's clicks (clickjacking).

The rules below come from two OWASP cheat sheets. Reread them when a change is not
covered here, or when this skill seems out of date:

- [Cross-Site Request Forgery Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [Clickjacking Defense](https://cheatsheetseries.owasp.org/cheatsheets/Clickjacking_Defense_Cheat_Sheet.html)

## What OWASP asks, in short

**CSRF**, in OWASP's order:

1. Use the framework's built-in CSRF protection. Starlette has none.
2. Else add CSRF tokens to every state-changing request (synchronizer token, or a signed
   double-submit cookie bound to the session).
3. "If your software targets only modern browsers, you may rely on Fetch Metadata headers
   together with the fallback options." `Sec-Fetch-*` is in all major browsers since
   March 2023. ComposeUI's web page needs a modern browser anyway (htmx, daisyUI), so it
   takes this option.
4. Add at least one defense-in-depth layer: `SameSite` cookies, `Origin`/`Referer`
   verification, or user interaction.

Fetch Metadata rules:

- Reject unsafe methods (POST, PUT, PATCH, DELETE) when `Sec-Fetch-Site: cross-site`.
- Allow `same-origin`.
- Allow `same-site` only "if your threat model trusts sibling subdomains". ComposeUI does
  not: "same site" ignores the port, so any other server on `localhost` is same-site.
- Allow `none` only for user-driven top-level navigations.
- The fallback to `Origin`, then `Referer`, is "a mandatory requirement". Match the whole
  origin (scheme, host and port), so `example.org.attacker.com` fails.
- "Missing headers and `Origin: null` are not evidence of a same-origin request." With
  neither header, reject the request.
- "Do not use GET requests for state changing operations." If one must, protect it
  anyway: "If any state-changing operation in the application is reachable via a GET
  request, SameSite=Lax will not stop it."
- `SameSite` "is useful as a defense-in-depth control but it does not replace a proper
  CSRF defense". OWASP accepts it alone only when all its conditions hold. ComposeUI fails
  two of them: localhost shares a site with every other local server, and the cookie has
  no `__Host-` prefix.
- "Cross-Site Scripting (XSS) can defeat all CSRF mitigation techniques!" A script on the
  app's own page sends same-origin requests and can read any token.

**Clickjacking:**

- Send `Content-Security-Policy: frame-ancestors 'none'` unless framing is needed. It
  "must be configured as an HTTP Response Header, not in a `<meta>` tag."
- Also send `X-Frame-Options: DENY` for older browsers. A `<meta http-equiv>` copy is
  ignored. Never use `ALLOW-FROM`.
- Put the headers on every response, not only some pages. Proxies can strip them.
- `SameSite` and frame-busting scripts are not a defense on their own.

## Other OWASP references

The rules above cover CSRF and clickjacking only. For a change in another area, read the
cheat sheet that covers it first, then check the code against it. Nobody has audited
ComposeUI against these yet: each "What to check" is an open question, not a finding.

| Area of the change | Cheat sheet | What to check in ComposeUI |
| --- | --- | --- |
| Uploads: Open (`POST /state`), `PickFileAction` | [File Upload](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html) | The size limits (`MAX_STATE_SIZE`, `MAX_FILE_SIZE`). A study is a zip, which may lie about its sizes (zip bomb): `open_study` takes only the two members, stored or deflated (`zipfile` unpacks bzip2 and LZMA whole), unencrypted, and never reads one with `archive.read` (it unpacks the whole member first): a bounded read cuts a lying member, which then fails its CRC. The study's SQLite file comes from the user too, schema included: `SqliteModel.open_data` refuses one not made as a new one is (`_schema`: tables' columns, other objects' SQL), runs its checks and migrations with `trusted_schema` off, and cuts them after `open_time_limit`. Tables' `CHECK` constraints aren't compared (they can't query, but can call costly functions such as `randomblob`). |
| Any text a view shows, the page's scripts | [XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html), [DOM-based XSS](https://cheatsheetseries.owasp.org/cheatsheets/DOM_based_XSS_Prevention_Cheat_Sheet.html) | XSS defeats every CSRF defense. The policy refuses `hx-on:*`, `hx-vals='js:...'`, trigger filters (`[...]`) and `on*=` handlers; `page.js` does their work from `data-*` attributes and custom events (`enter-key`, `escape-key`, `activate`). |
| Response headers, the page's scripts | [Content Security Policy](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html) | `headers.POLICY` on every response: scripts only from the app's files (`static/page.js`, htmx, uPlot, Cally), no inline script or handler, no `eval`; inline `style` attributes allowed (`style-src-attr`), `<style>` elements not. Icons add their own `default-src 'none'`. A violation shows only in the browser's console: `tests/test_browser.py` fails a test on one. |
| Response headers | [HTTP Headers](https://cheatsheetseries.owasp.org/cheatsheets/HTTP_Headers_Cheat_Sheet.html) | `Strict-Transport-Security` once served over HTTPS (`nosniff` and `Referrer-Policy` are sent). |
| The session cookie, `SessionStore`, `session_ttl` | [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html) | The cookie's `Secure` and `__Host-`; the idle timeout (1 hour); no absolute timeout; renewing the id (little need without a login). |
| Sessions, chart images, jobs, uploads | [Denial of Service](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html) | Every cookie-less `GET /` builds a main view (and a model) in memory, up to `max_sessions`; nothing limits one client's share. Chart images (matplotlib) and jobs cost CPU per request. |
| Loading state, form values | [Deserialization](https://cheatsheetseries.owasp.org/cheatsheets/Deserialization_Cheat_Sheet.html), [Input Validation](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html) | State is `json` structured by `cattrs`, never pickle, and `check_state_data` checks it before anything changes. Keep it that way. |
| `SqliteModel` and model code | [Query Parameterization](https://cheatsheetseries.owasp.org/cheatsheets/Query_Parameterization_Cheat_Sheet.html) | Values go as query parameters; the one f-string query (`PRAGMA user_version`) passes through `int()`. |
| Errors, `--debug`, refused requests | [Error Handling](https://cheatsheetseries.owasp.org/cheatsheets/Error_Handling_Cheat_Sheet.html), [Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html) | No traceback reaches the browser, even with `--debug`. Whether to log the origin check's refusals. |

For a whole review, use [OWASP ASVS](https://owasp.org/www-project-application-security-verification-standard/)
Level 1 as the checklist; the [OWASP Top 10](https://owasp.org/Top10/) is the overview.

## What `webcore` already does

| Defense | Where | What it does |
| --- | --- | --- |
| `SecurityHeadersMiddleware` | `headers.py` | Adds `Content-Security-Policy` (`POLICY`, with `frame-ancestors 'none'`) and `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: same-origin` (the app's own requests keep `Referer`, the origin check's fallback) to every response. Outermost middleware, so refusals get them too. |
| `BodySizeLimitMiddleware` | `limits.py` | Answers 413 to a body over `MAX_BODY_SIZE` (the largest upload plus 1 MiB): by `Content-Length` before reading, else (chunked) once the body read passes it. Starlette would otherwise spool a multipart body of any size to disk before the routes check `MAX_STATE_SIZE` and `MAX_FILE_SIZE`. |
| Session limit | `session.py` (`SessionStore.create`), `WebApplication.max_sessions` | At most `max_sessions` (1000) live, sessions being built included: a new browser then gets 503. Full refuses new sessions rather than dropping old ones, so cookie-less requests can't push out a user's unsaved work. No limit per client yet (one client can still take every slot for `session_ttl`). |
| `SameOriginMiddleware` | `origin.py` | Answers 403 to any method outside `SAFE_METHODS` (GET, HEAD, OPTIONS) unless `is_same_origin`: `Sec-Fetch-Site` must be `same-origin`; without it, `Origin`, then `Referer`, must equal the request's own origin (`URL(scope=scope)`: scheme plus `Host`); with none, refused. |
| `SameSite=Lax` cookie | `webapplication.py` (`SessionMiddleware`) | Defense in depth: no session cookie on cross-site POSTs. |
| No state change on GET | `routes.py` | Save and Save As post the page's hidden `cui-save` form to `POST /state/download`, which fires the action, then answers the file. `GET /state` only downloads. |
| Escaped output | `webrenderer.py`, `page.py` | HTML is built with `markupsafe.Markup`: `Markup(template).format(...)` escapes every argument that isn't `Markup` itself, `hx-vals` JSON included. Markdown renders with `{"html": False}`, its output marked safe. `test_the_web_backend_builds_its_html_with_markup` refuses an HTML f-string or `html.escape` there. |
| Unguessable cookie | `webapplication.py` | Signed with a per-process `secrets.token_urlsafe(32)` key; a `--reload` server's processes share one, made by the process `run` starts and passed in their environment, so the sessions they save survive their restarts. Widget ids are `id()`-based and guessable, so they only resolve inside their own session (`SessionStore`). A saved session opens only under an id of the form `SessionStore.create` makes, its directory's name. |
| Icon files | `routes.py` (`_ICON_HEADERS`) | `default-src 'none'` and `nosniff`: an SVG opened on its own runs no script. |

## Rules for a change

1. **Pick the method by effect.** A request that changes the session, a view, the model,
   or fires a signal, is a POST. GET, HEAD and OPTIONS only read. Never act on a query
   parameter of a GET (the old `GET /state?trigger=` did, and a link from another site
   fired Save).
2. **A download that must act first** posts a form (as `cui-save` does): htmx can't start a
   download, and a link would be a GET.
3. **New routes need no CSRF code.** `SameOriginMiddleware` covers every unsafe method.
   Don't exempt a route from it. If a route must take cross-origin requests (a webhook, an
   API), stop and ask the user: OWASP wants it listed, authenticated, and secured with CORS.
4. **Don't add CORS** (`CORSMiddleware`, `Access-Control-Allow-*`) without the user's
   decision. Never a wildcard origin with credentials.
5. **Keep the middleware order** in `create_starlette_app`: `SecurityHeadersMiddleware`, then
   `BodySizeLimitMiddleware`, then `SameOriginMiddleware`, then `SessionMiddleware`.
6. **Build HTML with `Markup`, never an f-string.** Write the template in `Markup(...)` and
   pass every value to `.format(...)`, which escapes it, attributes included. Return
   `Markup` from a function returning HTML, `Markup()` for nothing, and join parts with
   `Markup("").join`. Never wrap a text in `Markup(...)` yourself: only markup that is
   already safe, such as Markdown's. Keep Markdown's raw HTML off. Don't build a request's URL or method in the page's script
   from attacker-controllable input (`location`, `window.name`, `document.referrer`,
   `postMessage`): that is client-side CSRF, which no server check stops.
7. **Don't weaken the cookie.** Keep `same_site="lax"` (or stricter), signed, and with no
   `Domain` shared with subdomains.
8. **No code in the markup.** No `<script>` without `src`, no `on*=` handler, no `hx-on`,
   no `js:` value, no `hx-trigger` filter: the policy refuses them, and htmx runs
   without `allowEval`. Put the behavior in `static/page.js`, keyed on a `data-*`
   attribute. `test_no_markup_runs_code` checks the markup of the main views it lists.
9. **Don't frame the app**, not even from itself. If a feature needs a frame, ask the user
   first: it means `frame-ancestors 'self'` and `SAMEORIGIN` instead.

## Testing

`tests/test_webrenderer.py` (HTTP, `starlette.testclient`):

- Use `_Browser`, not a bare `TestClient`: it sends `Sec-Fetch-Site: same-origin`, as the
  app's own page does. A bare `TestClient` sends no such header, so its POSTs get 403,
  which is right for the refusal tests.
- A new unsafe route goes in `test_a_post_from_another_origin_is_refused`, which runs each
  route against every refused header set (`cross-site`, `same-site`, `none`, foreign and
  `null` `Origin`, foreign `Referer`, no header).
- A new kind of response goes in `test_every_response_carries_the_security_headers`.
- `test_every_view_text_is_escaped` puts hostile text in every text field of each main
  view in `_MAIN_VIEW_TYPES`, then parses the page in each state of `_states` (dialogs
  open, a cell edited, a table searched and filtered). The text must show exactly as set:
  not as markup, and not escaped twice. A new widget fails
  `test_the_listed_main_views_show_every_web_renderer` until a listed main view shows it;
  text it shows only on demand needs a state in `_states`.

`tests/test_browser.py` (Chromium, `make browser-test`), for what only a browser shows:

- A cross-origin attack page must come from a **real second server** (`_serve(...)`) when
  it loads a subresource such as an `<iframe>`. Chromium's Local Network Access check
  blocks a local address in a page fulfilled by `page.route`, before the request reaches
  the app, so the test would pass without testing anything. A top-level form submission
  from a routed page does reach the app.
- Check that each security test fails without its defense: disable the middleware, run the
  test, restore. A security test that passes either way proves nothing.

## Known gaps

These are open, not oversights to fix silently. Raise them when a change touches them:

- **Behind a reverse proxy,** the origin check compares with the `Host` the proxy forwards.
  OWASP prefers a configured expected origin, and trusts `X-Forwarded-Host` only from
  known proxies. The user guide asks a proxy to keep `Host`, `Origin`, `Referer` and
  `Sec-Fetch-*`.
- **No HTTPS, HSTS, or `__Host-` cookie prefix.** The app serves plain HTTP on
  `127.0.0.1` by default. OWASP lists HTTPS and HSTS as requirements of the Fetch Metadata
  approach for a deployed app, and `__Host-` needs `Secure`.
- **No `Vary: Sec-Fetch-Site, Origin`** on the responses. OWASP calls it operational, not
  a defense; the pages and fragments are `no-store` anyway (static files and icons are
  cached, but they don't depend on the request's origin).
- **No log-only mode** for the origin check, which OWASP suggests before enforcing on an
  existing deployment.
- **No synchronizer token.** OWASP's default; ComposeUI relies on option 3 above. A user
  who needs old browsers, or headers that a proxy strips, needs a token.
