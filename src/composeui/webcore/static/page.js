/* The page's script (see `page.py`), run in its <head> before the body is parsed.
   Its <script> element carries the addresses of the libraries and of the scripts of the
   charts and the maps, which carry their content's hash. `tables.js` runs after it. */
(function () {
  var PAGE_SCRIPT = /** @type {HTMLScriptElement} */ (document.currentScript);
  /* what the page's other scripts share: `dispatch` from here, then `charts` and `maps`,
     which their scripts add once loaded */
  window.ComposeUI = {dispatch: dispatch};
  /* a library the page loads only once it needs it. A request that fails is forgotten, so a
     later change of the page asks again, a few times: not at each change of a page offline. */
  var MAX_LIBRARY_FAILURES = 5;
  /** @typedef {{isLoading: boolean, failures: number}} Loader */
  /** @returns {Loader} */
  function newLoader() {
    return {isLoading: false, failures: 0};
  }
  /**
   * @param {Loader} loader @param {string} url @param {(() => void) | null} onload
   * @param {string} [type]
   */
  function loadLibrary(loader, url, onload, type) {
    if (loader.isLoading || loader.failures >= MAX_LIBRARY_FAILURES) return;
    loader.isLoading = true;
    var script = document.createElement("script");
    if (type) script.type = type;
    // a module whose import failed stays failed at its address: another one asks again
    script.src = loader.failures === 0
      ? url
      : url + (url.indexOf("?") < 0 ? "?" : "&") + "retry=" + loader.failures;
    if (onload) script.onload = onload;
    script.onerror = function () {
      script.remove();
      loader.isLoading = false;
      loader.failures += 1;
    };
    document.head.appendChild(script);
  }
  /* charts (`charts.js`, uPlot) and maps (`maps.js`, deck.gl): the page loads the library,
     then the script, only once it shows the first, from a swap too. One after the other: a
     failed one loads again on a later change of the page, not as the other arrives. Once
     both are there, each change of the page goes to the script, before any check that one
     is shown: it destroys those swapped out. */
  var uPlotLoader = newLoader();
  var chartsLoader = newLoader();
  function syncCharts() {
    var charts = window.ComposeUI.charts;
    if (charts !== undefined && typeof uPlot !== "undefined") {
      charts.sync();
    } else if (document.querySelector("[data-chart]") !== null) {
      if (typeof uPlot === "undefined") {
        loadLibrary(uPlotLoader, /** @type {string} */ (PAGE_SCRIPT.dataset.uplot), syncCharts);
      } else {
        loadLibrary(chartsLoader, /** @type {string} */ (PAGE_SCRIPT.dataset.charts), syncCharts);
      }
    }
  }
  var deckLoader = newLoader();
  var mapsLoader = newLoader();
  function syncMaps() {
    var maps = window.ComposeUI.maps;
    if (maps !== undefined && typeof deck !== "undefined") {
      maps.sync();
    } else if (document.querySelector("[data-map]") !== null) {
      if (typeof deck === "undefined") {
        loadLibrary(deckLoader, /** @type {string} */ (PAGE_SCRIPT.dataset.deckgl), syncMaps);
      } else {
        loadLibrary(mapsLoader, /** @type {string} */ (PAGE_SCRIPT.dataset.maps), syncMaps);
      }
    }
  }
  /* the theme picked in the header's Theme menu: Light or Dark win over the browser's
     light/dark preference and are remembered by this browser; System forgets the choice
     and follows the browser again. Applied here, before the body renders, so a reload
     never flashes the other theme first. */
  var THEMES = ["composeui", "composeui-dark"];
  /** @returns {string} */
  function storedTheme() {
    /** @type {string | null} */
    var theme = null;
    try {
      theme = localStorage.getItem("composeui-theme");
    } catch (error) {}  // storage blocked: follow the browser's preference
    return theme !== null && THEMES.indexOf(theme) >= 0 ? theme : "system";
  }
  /** @param {string} choice */
  function applyTheme(choice) {
    if (choice === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = choice;
    document.querySelectorAll("[data-theme-option]").forEach(function (element) {
      var option = /** @type {HTMLElement} */ (element);
      option.setAttribute("aria-pressed", String(option.dataset.themeOption === choice));
    });
    // uPlot can't recolor a chart: drawn again
    if (window.ComposeUI.charts !== undefined) window.ComposeUI.charts.redraw();
  }
  /** @param {string} choice */
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
     Option key on macOS, would type. */
  document.addEventListener("keydown", function (event) {
    if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey) return;
    var item = /** @type {HTMLElement | null} */ (
      document.querySelector('[data-shortcut="' + event.code + '"]')
    );
    if (item === null) return;
    event.preventDefault();
    item.click();
  });
  /* keeps each form field's aria-invalid in step with its log: while typing, only the log
     is swapped, never the field. The field is invalid while its log shows an error, or
     a check of its form fails on its row (`data-form-error`). Watches the DOM, so it
     runs after every htmx swap. */
  function syncInvalidFields() {
    document.querySelectorAll("[data-log]").forEach(function (element) {
      var log = /** @type {HTMLElement} */ (element);
      var field = document.querySelector('[aria-describedby~="' + log.id + '"]');
      if (field === null) return;
      var ownError = log.dataset.log === "error" && !log.hidden;
      if (ownError || "formError" in log.dataset) field.setAttribute("aria-invalid", "true");
      else field.removeAttribute("aria-invalid");
    });
  }
  /* opens each dialog the server shows: one swapped in arrives closed, and the browser
     opens a modal `<dialog>` only from a script. Each element opens once: a button closes
     its dialog before the server's answer swaps it closed too. htmx processes it first:
     this runs as soon as it lands, maybe before htmx would, and Escape must post its
     `cancel` however soon it comes. */
  function openDialogs() {
    document.querySelectorAll("dialog[data-dialog]:not([hidden]):not([data-opened])").forEach(
      function (element) {
        var dialog = /** @type {HTMLDialogElement} */ (element);
        dialog.dataset.opened = "";
        htmx.process(dialog);
        dialog.showModal();
      },
    );
  }
  /* fetches each file the app gives (`#cui-downloads`), once per ticket: the server names a
     ticket in each answer until it's fetched, as an answer can be lost. The link's `download`
     keeps the page if the file is gone: the browser shows a failed download instead. */
  /** @type {Set<string | undefined>} */
  var startedDownloads = new Set();
  function startDownloads() {
    document.querySelectorAll("#cui-downloads a[data-ticket]").forEach(function (element) {
      var link = /** @type {HTMLAnchorElement} */ (element);
      if (startedDownloads.has(link.dataset.ticket)) return;
      startedDownloads.add(link.dataset.ticket);
      link.click();
    });
  }

  /* what the markup can't say itself: the page's policy (`headers.py`) runs no inline
     handler, and no code htmx would evaluate (`hx-on`, `js:` values, trigger filters). The
     values a request posts beside its element's own (see `htmx-config` in `page.py`): */
  document.addEventListener("htmx:configRequest", function (event) {
    var element = /** @type {HTMLInputElement & HTMLDetailsElement} */ (event.detail.elt);
    var parameters = event.detail.parameters;
    var triggering = event.detail.triggeringEvent;
    if ("postEvent" in element.dataset) parameters.event = triggering.type;
    if ("postPicked" in element.dataset) {
      parameters.picked = /** @type {HTMLInputElement} */ (triggering.target).value;
    }
    if ("postOpen" in element.dataset) parameters.open = element.open;
    if ("sidebarToggle" in element.dataset) {
      var sidebar = /** @type {HTMLElement} */ (
        document.getElementById(/** @type {string} */ (element.getAttribute("aria-controls")))
      );
      parameters.expanded = !sidebar.hasAttribute("data-retracted");
    }
    /* files over a limit stay here: the server would refuse their body, which shows the
       user nothing. The first one's name alone goes, with their count, and the status bar
       says why (see `widget_file`). A choice goes whole, or not at all. */
    if (element.type === "file" && /\/file$/.test(element.getAttribute("hx-post") || "")) {
      var files = Array.from(/** @type {FileList} */ (element.files));
      var size = files.reduce(function (total, file) { return total + file.size; }, 0);
      var refusal = files.length > Number(document.body.dataset.maxUploadFiles) ? "too_many"
        : size > Number(document.body.dataset.maxUpload) ? "too_large" : null;
      var first = files[0];
      if (first && refusal !== null) {
        delete parameters.file;
        parameters[refusal] = first.name;
        parameters.count = String(files.length);
      }
    }
  });
  document.addEventListener("htmx:afterRequest", function (event) {
    var element = /** @type {HTMLInputElement} */ (event.detail.elt);
    if ("clearAfterPost" in element.dataset) element.value = "";
  });
  /* a file upload's button takes no click while its file goes, and says so beside it. Marked,
     not `disabled`: a disabled button would lose the focus. The answer swaps in the file's name;
     a refused file brings none, and the text goes back. */
  /** @type {Map<HTMLElement, {button: Element, nameId: string, text: string | null}>} */
  var uploads = new Map();
  document.addEventListener("htmx:beforeRequest", function (event) {
    var input = event.detail.elt;
    if (!("uploadingText" in input.dataset)) return;
    var parent = /** @type {HTMLElement} */ (input.parentElement);
    var button = /** @type {Element} */ (parent.querySelector("[data-file-browse]"));
    var name = /** @type {Element} */ (parent.querySelector("[aria-live]"));
    uploads.set(input, { button: button, nameId: name.id, text: name.textContent });
    button.setAttribute("aria-disabled", "true");
    button.classList.add("btn-disabled");
    name.textContent = /** @type {string} */ (input.dataset.uploadingText);
  });
  document.addEventListener("htmx:afterRequest", function (event) {
    var input = event.detail.elt;
    var upload = uploads.get(input);
    if (upload === undefined) return;
    uploads.delete(input);
    upload.button.removeAttribute("aria-disabled");
    upload.button.classList.remove("btn-disabled");
    var name = document.getElementById(upload.nameId);
    if (name !== null && name.textContent === input.dataset.uploadingText) {
      name.textContent = upload.text;
    }
  });
  /* the server handles the page's posts in the order they leave (see `webcore/order.py`): a
     field's value, sent as it loses the focus, may else come after the click on the button
     that took it. Each post carries the page's id and its number, set as it leaves. Those
     replacing each other on purpose (`hx-sync` "replace": a large table's scroll windows)
     carry none, as one replaced may never reach the server, which would wait for it. */
  var PAGE_ID = Array.from(crypto.getRandomValues(new Uint8Array(16)), function (byte) {
    return ("0" + byte.toString(16)).slice(-2);
  }).join("");
  var postNumber = 0;
  document.addEventListener("htmx:beforeSend", function (event) {
    if (event.detail.requestConfig.verb !== "post") return;
    if (/:\s*replace$/.test(event.detail.elt.getAttribute("hx-sync") || "")) return;
    postNumber += 1;
    event.detail.xhr.setRequestHeader("X-ComposeUI-Page", PAGE_ID);
    event.detail.xhr.setRequestHeader("X-ComposeUI-Post", String(postNumber));
  });
  /* each request names the session that served the page (`SESSION_TAG_HEADER`): a tab left
     open on a page of an ended session (e.g. before the server restarted) shares its cookie
     with a newer tab, and the server answers it with a reload rather than a newer session's
     views. */
  document.addEventListener("htmx:configRequest", function (event) {
    var tag = document.body.dataset.session;
    if (tag) event.detail.headers["X-ComposeUI-Session"] = tag;
  });
  /* Answers can arrive in another order than the requests left: a fragment already shown
     from a later request isn't replaced by an older answer. The rest of it still applies,
     each answer sending what it changed alone. Polls count, as their fragments age too. */
  var requestNumber = 0;
  /** @type {Record<string, number>} the number of the latest request that showed each fragment */
  var fragmentNumbers = {};
  document.addEventListener("htmx:beforeSend", function (event) {
    requestNumber += 1;
    event.detail.xhr.composeuiNumber = requestNumber;
  });
  document.addEventListener("htmx:beforeSwap", function (event) {
    var number = event.detail.xhr.composeuiNumber;
    if (number === undefined) return;
    var sent = number;
    var answer = document.createElement("template");
    answer.innerHTML = event.detail.serverResponse;
    var isStale = false;
    Array.from(answer.content.children).forEach(function (fragment) {
      if (fragment.id === "" || !fragment.hasAttribute("hx-swap-oob")) return;
      if ((fragmentNumbers[fragment.id] || 0) > sent) {
        fragment.remove();
        isStale = true;
      } else {
        fragmentNumbers[fragment.id] = sent;
      }
    });
    if (isStale) event.detail.serverResponse = answer.innerHTML;
  });
  /* Save and Save As submit a form, which carries no header: its fields carry the same */
  document.addEventListener("submit", function (event) {
    var form = /** @type {HTMLFormElement} */ (event.target);
    if (form.id !== "cui-save") return;
    postNumber += 1;
    var fields = /** @type {HTMLFormControlsCollection & {page: HTMLInputElement,
      post: HTMLInputElement}} */ (form.elements);
    fields.page.value = PAGE_ID;
    fields.post.value = String(postNumber);
  });
  /* the triggers htmx would filter: Enter, Escape, and `activate` (a click, or Enter, not
     from a field or a button, which take their own) for a table's rows. Captured, so they
     come before the keydown's own handlers, as htmx's filters did. */
  document.addEventListener("keydown", function (event) {
    var target = /** @type {Element} */ (event.target);
    if (event.key === "Enter") dispatch(target, "enter-key");
    else if (event.key === "Escape") dispatch(target, "escape-key");
    if (event.key === "Enter" && target.closest("input,select,button") === null) {
      dispatch(target, "activate");  // then `tables.js` activates a table's row
    }
  }, true);
  /** @param {EventTarget} target @param {string} type */
  function dispatch(target, type) {
    target.dispatchEvent(new CustomEvent(type, { bubbles: true }));
  }
  /* a dialog's button closes it first, so the focus returns where it was, then posts its
     answer. A dialog Escape mustn't dismiss stays open: the browser lets its `cancel` be
     refused only once per user action, then closes it anyway on the next Escape, and the
     page opens it again, still shown on the server (neither event bubbles). */
  document.addEventListener("click", function (event) {
    var target = /** @type {Element} */ (event.target);
    if (target.closest("input,select,button") === null) dispatch(target, "activate");
    var closing = target.closest("[data-close-dialog]");
    if (closing !== null) /** @type {HTMLDialogElement} */ (closing.closest("dialog")).close();
  }, true);
  document.addEventListener("cancel", function (event) {
    if ("keepOpen" in /** @type {HTMLElement} */ (event.target).dataset) event.preventDefault();
  }, true);
  document.addEventListener("close", function (event) {
    var dialog = /** @type {HTMLDialogElement} */ (event.target);
    // one swapped out, or swapped in closed by the server, is no longer this one shown
    if ("keepOpen" in dialog.dataset && dialog.isConnected && !dialog.hidden) dialog.showModal();
  }, true);
  /* a menu's item, or the Theme menu's choice, closes its dropdown (daisyUI's stays open
     while it has the focus) */
  document.addEventListener("click", function (event) {
    var target = /** @type {Element} */ (event.target);
    var option = /** @type {HTMLElement | null} */ (target.closest("[data-theme-option]"));
    if (option !== null) setTheme(/** @type {string} */ (option.dataset.themeOption));
    if (option !== null || target.closest("[data-close-dropdown]") !== null) {
      /** @type {HTMLElement} */ (document.activeElement).blur();
    }
  });
  /* the answer to a request whose element a swap has since replaced (e.g. a row clicked
     before the answer to a click on another row) still swaps its fragments: htmx looks
     for them from the element, which is no longer in the page. Whether it is, is read
     before htmx handles the answer, which may swap it out itself. */
  document.addEventListener("htmx:beforeRequest", function (event) {
    var element = event.detail.elt;
    var request = event.detail.xhr;
    var isReplaced = false;
    request.addEventListener("readystatechange", function () {
      if (request.readyState === XMLHttpRequest.DONE) isReplaced = !element.isConnected;
    });
    request.addEventListener("load", function () {
      if (isReplaced && request.status === 200) {
        htmx.swap(document.body, request.responseText, {
          swapStyle: "none", swapDelay: 0, settleDelay: 0,
        });
      }
    });
  });
  /* a drop-down list swapped while the focus is in it, e.g. a multi-combobox whose choice the
     app changed: it's open only while the focus is in it, and htmx gives the focus back to
     the element of the same id, which a closed list hides. So the list stays open through the
     swap: on the element swapped out too, as htmx first gives the new one the old one's
     classes, and its own only once settled. */
  document.addEventListener("htmx:oobBeforeSwap", function (event) {
    var field = document.activeElement;
    if (field === null || field.id === "") return;
    var shown = field.closest(".dropdown");
    var swapped = event.detail.fragment.querySelector("#" + CSS.escape(field.id));
    var dropdown = /** @type {HTMLElement | null} */ (
      swapped === null ? null : swapped.closest(".dropdown")
    );
    if (shown === null || dropdown === null) return;
    shown.classList.add("dropdown-open");
    dropdown.classList.add("dropdown-open");
    dropdown.dataset.keptOpen = "";
  });
  /* once that list settled, not another answer's element: before it, htmx would give it the
     class again */
  document.addEventListener("htmx:afterSettle", function (event) {
    var dropdown = event.target;
    if (!(dropdown instanceof HTMLElement) || !("keptOpen" in dropdown.dataset)) return;
    dropdown.classList.remove("dropdown-open");
    delete dropdown.dataset.keptOpen;
  });
  /* a slider's value follows its handle while it is dragged: the server only hears of the
     moves debounced (see `WebSliderRenderer`), and its answer never swaps the slider back */
  document.addEventListener("input", function (event) {
    var slider = /** @type {HTMLInputElement} */ (event.target);
    if (!("slider" in slider.dataset)) return;
    var output = /** @type {HTMLOutputElement} */ (
      /** @type {HTMLElement} */ (slider.parentElement).querySelector("output")
    );
    /* the same decimals at every step: the browser writes 1 for 1.0 */
    output.value = Number(slider.value).toFixed(
      Number(slider.dataset.decimals),
    );
  });
  /* a range slider's handles, two range inputs on one track: the one dragged stops on the
     other, and the fill and the ends follow, as for a slider; the server hears of them
     debounced (see `WebRangeSliderRenderer`) */
  document.addEventListener("input", function (event) {
    var input = /** @type {HTMLInputElement} */ (event.target);
    if (!("rangeEnd" in input.dataset)) return;
    var track = /** @type {HTMLElement} */ (input.parentElement);
    var low = /** @type {HTMLInputElement} */ (track.querySelector('[data-range-end="low"]'));
    var high = /** @type {HTMLInputElement} */ (track.querySelector('[data-range-end="high"]'));
    if (Number(low.value) > Number(high.value)) {
      input.value = input === low ? high.value : low.value;
    }
    track.style.setProperty("--range-low", low.value);
    track.style.setProperty("--range-high", high.value);
    var isLowOnTop = low.value === high.value && Number(low.value) > Number(low.max) / 2;
    track.toggleAttribute("data-low-on-top", isLowOnTop);
    var texts = [low, high].map(function (end) {
      var value = Number(track.dataset.first) + Number(end.value) * Number(track.dataset.step);
      var text = value.toFixed(Number(track.dataset.decimals));
      end.setAttribute("aria-valuetext", text);
      return text;
    });
    var output = /** @type {HTMLOutputElement} */ (
      /** @type {HTMLElement} */ (track.parentElement).querySelector("output")
    );
    output.value = texts.join(" \u2013 ");
  });
  /* the date fields' calendar, Cally's `<calendar-date>`: the page loads it only once it
     shows its first date field, from a swap too, as it does uPlot */
  var callyLoader = newLoader();
  function loadCalendars() {
    if (document.querySelector("calendar-date") === null) return;
    loadLibrary(callyLoader, /** @type {string} */ (PAGE_SCRIPT.dataset.cally), null, "module");
  }
  /* a date field's calendar (see `WebDateInputRenderer`), a popover its button opens: it
     names the months and days in the page's language, and starts on the date, focused,
     so the arrows move from it. Opened before Cally has loaded, it waits for it to draw
     the days: the language as an attribute, which the element keeps once Cally defines
     it, unlike a property set before then. The date picked closes it, the button taking the focus
     back, once its `change` has posted it: the server swaps the field back showing it. */
  document.addEventListener("toggle", function (event) {
    var target = /** @type {HTMLElement} */ (event.target);
    /** @type {(HTMLElement & {updated?: Promise<unknown>}) | null | undefined} */
    var calendar = target.querySelector && target.querySelector("[data-date-calendar]");
    var opened = /** @type {ToggleEvent} */ (event).newState === "open";
    if (calendar === null || calendar === undefined || !opened) return;
    var shown = calendar;
    var language = document.documentElement.lang;
    if (language) calendar.setAttribute("locale", language);
    customElements.whenDefined("calendar-date").then(function () {
      return shown.updated;  // its days drawn, which it focuses
    }).then(function () {
      if (target.matches(":popover-open")) shown.focus();
    });
  }, true);
  document.addEventListener("change", function (event) {
    var target = /** @type {HTMLElement} */ (event.target);
    if (!("dateCalendar" in target.dataset)) return;
    var popover = /** @type {HTMLElement} */ (target.closest("[popover]"));
    popover.hidePopover();
    var button = document.getElementById(/** @type {string} */ (popover.dataset.dateButton));
    /** @type {HTMLElement} */ (button).focus();
  }, true);
  /* a file path field's "…" button opens the browser's file picker, a hidden file input
     beside it, which uploads the file picked (see `WebFilePathInputRenderer`) */
  document.addEventListener("click", function (event) {
    var button = /** @type {Element} */ (event.target).closest("[data-file-browse]");
    if (button === null || button.getAttribute("aria-disabled") === "true") return;
    var parent = /** @type {HTMLElement} */ (button.parentElement);
    /** @type {HTMLInputElement} */ (parent.querySelector('input[type="file"]')).click();
  });
  /* the sidebar (see `WebSidebarRenderer`): on a wide screen, its button in the header
     retracts and expands the column, then posts its state; on a phone, it shows and hides
     the drawer, through the drawer's checkbox, which a click beside the drawer unchecks
     too. The button tells screen readers whether the column, or the drawer, shows; Escape
     hides the drawer. */
  var wideScreen = window.matchMedia("(width >= 64rem)");
  /** @param {HTMLElement} toggle */
  function sidebarDrawer(toggle) {
    return /** @type {HTMLInputElement | null} */ (
      document.getElementById(/** @type {string} */ (toggle.dataset.sidebarToggle))
    );
  }
  /** @param {HTMLElement} toggle */
  function sidebarOf(toggle) {
    return document.getElementById(/** @type {string} */ (toggle.getAttribute("aria-controls")));
  }
  function syncSidebarToggles() {
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (element) {
      var toggle = /** @type {HTMLElement} */ (element);
      var sidebar = sidebarOf(toggle);
      var drawer = sidebarDrawer(toggle);
      if (sidebar === null || drawer === null) return;
      var shows = wideScreen.matches ? !sidebar.hasAttribute("data-retracted") : drawer.checked;
      toggle.setAttribute("aria-expanded", String(shows));
    });
  }
  wideScreen.addEventListener("change", syncSidebarToggles);
  document.addEventListener("click", function (event) {
    var toggle = /** @type {Element} */ (event.target).closest("[data-sidebar-toggle]");
    if (!(toggle instanceof HTMLElement)) return;
    if (wideScreen.matches) {
      /** @type {HTMLElement} */ (sidebarOf(toggle)).toggleAttribute("data-retracted");
      htmx.trigger(toggle, "sidebar-toggle");
    } else {
      /** @type {HTMLInputElement} */ (sidebarDrawer(toggle)).click();
    }
    syncSidebarToggles();
  });
  document.addEventListener("change", function (event) {
    if (/** @type {Element} */ (event.target).classList.contains("drawer-toggle")) {
      syncSidebarToggles();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("[data-sidebar-toggle]").forEach(function (element) {
      var toggle = /** @type {HTMLElement} */ (element);
      var drawer = sidebarDrawer(toggle);
      if (drawer !== null && drawer.checked) {
        drawer.click();
        toggle.focus();
      }
    });
  });
  /* splitters (see `WebSplitterRenderer`): dragging a border, or the arrow keys on it,
     shares the length of the shown panes beside it between them at once: their widths,
     or their heights across a horizontal border (a vertical splitter's). Each pane's
     share becomes its length in pixels, so they keep it as the window resizes. The
     panes' lengths are posted once the drag ends, or on each key. */
  var PANE_MIN_LENGTH = 48;
  var BORDER_KEY_STEP = 16;
  /** @param {Element} border */
  function isAcross(border) {
    return border.getAttribute("aria-orientation") === "horizontal";
  }
  /** @param {Element} border @param {HTMLElement} pane */
  function paneLength(border, pane) {
    return isAcross(border) ? pane.offsetHeight : pane.offsetWidth;
  }
  /** @param {Element} border @returns {HTMLElement[]} */
  function splitterPanes(border) {
    var children = /** @type {HTMLElement} */ (border.parentElement).children;
    return Array.prototype.filter.call(children, function (child) {
      return child.hasAttribute("data-pane");
    });
  }
  /** @param {Element} border @param {number} step */
  function paneBeside(border, step) {
    var element = /** @type {HTMLElement | null} */ (
      step < 0 ? border.previousElementSibling : border.nextElementSibling
    );
    while (
      element !== null &&
      !(element.hasAttribute("data-pane") && paneLength(border, element) > 0)
    ) {
      element = /** @type {HTMLElement | null} */ (
        step < 0 ? element.previousElementSibling : element.nextElementSibling
      );
    }
    return element;
  }
  /** @param {Element} border @param {HTMLElement} pane @param {number} total */
  function paneMinimum(border, pane, total) {
    // the pane's own, if larger: side by side, as wide as its text needs to be read
    var style = getComputedStyle(pane);
    var length = parseFloat(isAcross(border) ? style.minHeight : style.minWidth) || 0;
    return Math.min(Math.max(PANE_MIN_LENGTH, length), total / 2);
  }
  /** @typedef {{before: number, after: number}} BorderStart */
  /** @param {Element} border @param {BorderStart} start @param {number} pixels */
  function moveBorder(border, start, pixels) {
    var before = paneBeside(border, -1);
    var after = paneBeside(border, 1);
    if (before === null || after === null) return;
    var total = start.before + start.after;
    var beforeLength = Math.min(
      Math.max(start.before + pixels, paneMinimum(border, before, total)),
      total - paneMinimum(border, after, total)
    );
    var panes = splitterPanes(border);
    // every length read before any is written: each write lays the panes out again
    var lengths = panes.map(function (pane) { return paneLength(border, pane); });
    panes.forEach(function (pane, index) {
      var length = /** @type {number} */ (lengths[index]);
      if (length > 0) pane.style.setProperty("--share", length + " 1 0%");
    });
    before.style.setProperty("--share", beforeLength + " 1 0%");
    after.style.setProperty("--share", total - beforeLength + " 1 0%");
    var shown = 0;
    var lengthBefore = 0;
    panes.forEach(function (pane) {
      shown += paneLength(border, pane);
      if (pane.compareDocumentPosition(border) & Node.DOCUMENT_POSITION_FOLLOWING) {
        lengthBefore += paneLength(border, pane);
      }
    });
    border.setAttribute("aria-valuenow", String(Math.round((100 * lengthBefore) / (shown || 1))));
  }
  /** @param {Element} border */
  function postPaneLengths(border) {
    var splitter = /** @type {HTMLElement} */ (border.closest("[data-splitter]"));
    htmx.ajax("post", "/_composeui/widget/" + splitter.id, {
      source: splitter,
      swap: "none",
      values: {
        event: "resize",
        lengths: splitterPanes(border)
          .map(function (pane) { return paneLength(border, pane); })
          .join(","),
      },
    });
  }
  /** @param {Element} border @returns {BorderStart} */
  function borderStart(border) {
    var before = paneBeside(border, -1);
    var after = paneBeside(border, 1);
    return {
      before: before === null ? 0 : paneLength(border, before),
      after: after === null ? 0 : paneLength(border, after),
    };
  }
  document.addEventListener("pointerdown", function (event) {
    var target = /** @type {Element} */ (event.target);
    var border = /** @type {HTMLElement | null} */ (target.closest(".cui-splitter-border"));
    if (border === null || border.getAttribute("aria-disabled") === "true") return;
    var dragged = border;
    if (event.button !== 0) return;
    event.preventDefault();  // no text selected while dragging
    border.focus();
    border.setPointerCapture(event.pointerId);
    border.setAttribute("data-dragging", "");
    var across = isAcross(border);
    var from = across ? event.clientY : event.clientX;
    var start = borderStart(border);
    /** @param {PointerEvent} moveEvent */
    function move(moveEvent) {
      moveBorder(dragged, start, (across ? moveEvent.clientY : moveEvent.clientX) - from);
    }
    function end() {
      dragged.removeEventListener("pointermove", move);
      dragged.removeEventListener("pointerup", end);
      dragged.removeEventListener("pointercancel", end);
      dragged.removeAttribute("data-dragging");
      postPaneLengths(dragged);
    }
    border.addEventListener("pointermove", move);
    border.addEventListener("pointerup", end);
    border.addEventListener("pointercancel", end);
  });
  document.addEventListener("keydown", function (event) {
    var border = event.target;
    if (!(border instanceof HTMLElement) || !border.classList.contains("cui-splitter-border")) {
      return;
    }
    /** @type {Record<string, number | undefined>} */
    var steps = isAcross(border)
      ? { ArrowUp: -BORDER_KEY_STEP, ArrowDown: BORDER_KEY_STEP }
      : { ArrowLeft: -BORDER_KEY_STEP, ArrowRight: BORDER_KEY_STEP };
    var step = steps[event.key];
    if (step === undefined || border.getAttribute("aria-disabled") === "true") return;
    event.preventDefault();
    moveBorder(border, borderStart(border), step);
    postPaneLengths(border);
  });
  /* tabs (see `WebTabsRenderer`): a click on a tab shows its panel at once, then htmx
     posts the pick; the arrow keys, Home and End move to a tab that can be picked, and
     pick it, as an ARIA tab list does. Only the tab shown is in the tab order. */
  /** @param {HTMLElement} tab */
  function showTab(tab) {
    var list = /** @type {HTMLElement} */ (tab.closest('[role="tablist"]'));
    list.querySelectorAll('[role="tab"]').forEach(function (element) {
      var other = /** @type {HTMLElement} */ (element);
      var isShown = other === tab;
      other.setAttribute("aria-selected", String(isShown));
      other.tabIndex = isShown ? 0 : -1;
      other.classList.toggle("tab-active", isShown);
      var panel = /** @type {HTMLElement} */ (
        document.getElementById(/** @type {string} */ (other.getAttribute("aria-controls")))
      );
      panel.hidden = !isShown;
    });
  }
  document.addEventListener("click", function (event) {
    var tab = /** @type {HTMLButtonElement | null} */ (
      /** @type {Element} */ (event.target).closest("[data-tab]")
    );
    if (tab !== null && !tab.disabled) showTab(tab);
  });
  document.addEventListener("keydown", function (event) {
    var tab = event.target;
    if (!(tab instanceof HTMLElement) || !("tab" in tab.dataset)) return;
    /** @type {HTMLButtonElement[]} */
    var tabs = Array.prototype.filter.call(
      /** @type {HTMLElement} */ (tab.closest('[role="tablist"]')).querySelectorAll('[role="tab"]'),
      function (other) { return !other.hidden && !other.disabled; },
    );
    var index = tabs.indexOf(/** @type {HTMLButtonElement} */ (tab));
    /** @type {Record<string, HTMLButtonElement | undefined>} */
    var keys = {
      ArrowRight: tabs[(index + 1) % tabs.length],
      ArrowLeft: tabs[(index - 1 + tabs.length) % tabs.length],
      Home: tabs[0],
      End: tabs[tabs.length - 1],
    };
    var next = keys[event.key];
    if (next === undefined) return;
    event.preventDefault();
    next.focus();
    next.click();
  });
  /* the page's language, for screen readers and the browser's spell checker, and its
     title: the server swaps in its marker when the app changes them (see `page_marker`) */
  function syncPage() {
    var marker = document.getElementById("cui-page");
    if (marker === null) return;
    document.documentElement.lang = /** @type {string} */ (marker.dataset.language);
    var title = /** @type {string} */ (marker.dataset.title);
    if (document.title !== title) document.title = title;
  }
  /* places a field's help, opened by its "?" button, right of the button, or under it
     when the window is too narrow (a phone), never over its field: a popover otherwise
     opens in the window's middle. Placed again once shown, its size then known.
     `data-side` points its arrow at the button (see `css/app.css`). */
  /** @param {Event} event */
  function placeHelp(event) {
    var help = event.target;
    if (!(help instanceof HTMLElement) || !help.matches("[data-help]")) return;
    if (/** @type {ToggleEvent} */ (event).newState !== "open") return;
    var button = document.querySelector('[popovertarget="' + help.id + '"]');
    if (button === null) return;
    var rect = button.getBoundingClientRect();
    var gap = 8;
    help.style.inset = "auto";
    if (rect.right + gap + help.offsetWidth <= window.innerWidth - gap) {
      help.dataset.side = "right";
      help.style.left = rect.right + gap + "px";
      help.style.top = rect.top + rect.height / 2 - help.offsetHeight / 2 + "px";
    } else {
      var left = Math.max(gap, Math.min(rect.left, window.innerWidth - help.offsetWidth - gap));
      help.dataset.side = "bottom";
      help.style.left = left + "px";
      help.style.top = rect.bottom + gap + "px";
      help.style.setProperty("--arrow-x", rect.left + rect.width / 2 - left + "px");
    }
  }
  /* a console (see `WebConsoleRenderer`) keeps its last `data-max-lines` lines, the line
     being written not counted, and stays at its end as lines come, unless the user
     scrolled up to read (a scroll doesn't bubble) */
  document.addEventListener("scroll", function (event) {
    var box = event.target;
    if (!(box instanceof HTMLElement) || !("console" in box.dataset)) return;
    box.dataset.scrolledUp = String(box.scrollTop + box.clientHeight < box.scrollHeight - 4);
  }, true);
  /* a console's Copy all writes its whole text to the clipboard: the page holds the lines
     the view keeps. Without the clipboard (a page over plain HTTP from another host), it
     selects the text instead, for the user's Ctrl+C. */
  document.addEventListener("click", function (event) {
    var button = /** @type {Element} */ (event.target).closest("[data-copy-console]");
    if (!(button instanceof HTMLElement)) return;
    var box = document.getElementById(/** @type {string} */ (button.dataset.copyConsole));
    if (box === null) return;
    if (navigator.clipboard) {
      navigator.clipboard.writeText(/** @type {string} */ (box.textContent)).catch(function () {});
    } else {
      /** @type {Selection} */ (window.getSelection()).selectAllChildren(box);
    }
  });
  function keepConsoles() {
    document.querySelectorAll("[data-console]").forEach(function (element) {
      var box = /** @type {HTMLElement} */ (element);
      var excess = box.children.length - 1 - Number(box.dataset.maxLines);
      for (var dropped = 0; dropped < excess; dropped++) {
        /** @type {Element} */ (box.firstElementChild).remove();
      }
      /* the lines dropped since the console was drawn whole, for its search */
      if (excess > 0) box.dataset.dropped = String(Number(box.dataset.dropped || 0) + excess);
      if (box.dataset.scrolledUp !== "true") box.scrollTop = box.scrollHeight;
    });
    document.querySelectorAll("[data-console-search]").forEach(function (element) {
      var field = /** @type {HTMLInputElement} */ (element);
      if (field.value !== "" || consoleMatches.has(field.dataset.consoleSearch)) {
        searchConsole(field, "keep");
      }
    });
  }
  /* a console's search: its matches, plain text in any case as `find_in_lines` finds them,
     highlighted by the CSS Custom Highlight API, which leaves the text as it is. Typing
     shows the first, Enter the next, Shift+Enter the previous, around the ends; new lines
     keep the current one, or the next if it went with the oldest lines, as `follow_match`
     does. The count, in the page's language, is beside the field. */
  /* a console's id: its matches' ranges and places (line, from the first line ever, and
     start), and the current one's index */
  /** @typedef {{node: Node, start: number}} TextPoint */
  /**
   * @type {Map<string | undefined,
   *   {ranges: Range[], places: [number, number][], current: number}>}
   */
  var consoleMatches = new Map();
  document.addEventListener("input", function (event) {
    var field = /** @type {HTMLInputElement} */ (event.target);
    if ("consoleSearch" in field.dataset) searchConsole(field, "first");
  });
  document.addEventListener("keydown", function (event) {
    var field = /** @type {HTMLInputElement} */ (event.target);
    if (!("consoleSearch" in field.dataset) || event.key !== "Enter") return;
    event.preventDefault();
    searchConsole(field, event.shiftKey ? "previous" : "next");
  });
  /** @param {HTMLInputElement} field @param {string} move */
  function searchConsole(field, move) {
    var box = document.getElementById(/** @type {string} */ (field.dataset.consoleSearch));
    if (box === null) return;
    /** @type {Range[]} */
    var ranges = [];
    /** @type {[number, number][]} */
    var places = [];
    var first = Number(box.dataset.dropped || 0);
    if (field.value !== "") {
      var pattern = new RegExp(field.value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
      /* a line: its text's nodes, several when ANSI codes styled its parts */
      Array.prototype.forEach.call(box.children, function (line, index) {
        /** @type {TextPoint[]} */
        var nodes = [];
        var text = "", match;
        var walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          nodes.push({node: walker.currentNode, start: text.length});
          text += walker.currentNode.textContent;
        }
        pattern.lastIndex = 0;
        while ((match = pattern.exec(text)) !== null) {
          var range = new Range(), end = match.index + match[0].length;
          var from = textPoint(nodes, match.index, false), to = textPoint(nodes, end, true);
          range.setStart(from.node, match.index - from.start);
          range.setEnd(to.node, end - to.start);
          ranges.push(range);
          places.push([first + index, match.index]);
        }
      });
    }
    var previous = consoleMatches.get(box.id), current = 0;
    if (move !== "first" && previous !== undefined && ranges.length > 0) {
      var shown = previous.places[previous.current];
      if (move === "keep" && shown !== undefined) {
        current = places.length - 1;
        for (var index = 0; index < places.length; index++) {
          var place = /** @type {[number, number]} */ (places[index]);
          if (place[0] > shown[0] || (place[0] === shown[0] && place[1] >= shown[1])) {
            current = index;
            break;
          }
        }
      } else {
        current = previous.current + (move === "next" ? 1 : move === "previous" ? -1 : 0);
        current = (current % ranges.length + ranges.length) % ranges.length;
      }
    }
    if (field.value === "") consoleMatches.delete(box.id);
    else consoleMatches.set(box.id, {ranges: ranges, places: places, current: current});
    paintConsoleMatches();
    if (move !== "keep" && ranges.length > 0) {
      var shownRange = /** @type {Range} */ (ranges[current]);
      var line = /** @type {HTMLElement} */ (shownRange.startContainer.parentElement);
      box.scrollTop = line.offsetTop - box.clientHeight / 2;
      /* now, not on the scroll's event: the page's observer, running first, would scroll
         the box back to its end */
      box.dataset.scrolledUp = String(box.scrollTop + box.clientHeight < box.scrollHeight - 4);
    }
    var count = /** @type {HTMLElement} */ (field.parentElement).querySelector(
      "[data-console-matches]"
    );
    var matches = /** @type {string} */ (field.dataset.matches);
    var noMatch = /** @type {string} */ (field.dataset.noMatch);
    var text = field.value === "" ? "" : ranges.length === 0 ? noMatch :
      matches.replace("{current}", String(current + 1)).replace("{count}", String(ranges.length));
    /* unchanged, not set: the page's observer would run this again */
    if (count !== null && count.textContent !== text) count.textContent = text;
  }
  /* the text node holding a line's `offset`: the one it starts, or for an `isEnd`, ends */
  /** @param {TextPoint[]} nodes @param {number} offset @param {boolean} isEnd */
  function textPoint(nodes, offset, isEnd) {
    for (var index = 0; index < nodes.length; index++) {
      var node = /** @type {TextPoint} */ (nodes[index]);
      var length = /** @type {string} */ (node.node.textContent).length;
      if (offset < node.start + length || (isEnd && offset === node.start + length)) return node;
    }
    // a match is in the line's text: it has a node
    return /** @type {TextPoint} */ (nodes[nodes.length - 1]);
  }
  function paintConsoleMatches() {
    if (!window.CSS || !CSS.highlights) return;  /* still counted, and scrolled to */
    /** @type {Range[]} */
    var others = [];
    /** @type {Range[]} */
    var currents = [];
    consoleMatches.forEach(function (found, id) {
      if (document.getElementById(/** @type {string} */ (id)) === null) {
        consoleMatches.delete(id);
        return;
      }
      found.ranges.forEach(function (range, index) {
        (index === found.current ? currents : others).push(range);
      });
    });
    CSS.highlights.set("cui-match", new Highlight(...others));
    CSS.highlights.set("cui-match-current", new Highlight(...currents));
  }
  /* neither bubbles */
  document.addEventListener("beforetoggle", placeHelp, true);
  document.addEventListener("toggle", placeHelp, true);
  document.addEventListener("DOMContentLoaded", function () {
    openDialogs();
    startDownloads();
    syncCharts();
    syncMaps();
    loadCalendars();
    syncSidebarToggles();
    keepConsoles();
    new MutationObserver(function () {
      syncInvalidFields();
      syncSidebarToggles();
      openDialogs();
      startDownloads();
      syncPage();
      syncCharts();
      syncMaps();
      loadCalendars();
      keepConsoles();
    }).observe(document.body, {
      childList: true,
      subtree: true,
    });
  });
})();
