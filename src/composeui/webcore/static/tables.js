/* the tables' script (see `WebTableRenderer` and `WebSourceTableRenderer`), run once after
   `page.js`, before the body is parsed: its listeners are there before the user can act */
(function () {
  /* a double click on a table's row, or Enter, activates it, unless on a cell's field,
     widget or editable text. Posted after the click or Enter selecting it, so the server
     handles it after (see `webcore/order.py`); not from the row, which htmx would make wait
     for its selection's answer, then drop, the answer swapping the row out. Captured, as
     `page.js`'s Enter, which runs first: it dispatches the `activate` selecting the row. */
  document.addEventListener("keydown", function (event) {
    var target = /** @type {Element} */ (event.target);
    if (event.key === "Enter" && target.closest("input,select,button") === null) {
      activateRow(target);
    }
  }, true);
  document.addEventListener("dblclick", function (event) {
    activateRow(/** @type {Element} */ (event.target));
  });
  /** @param {Element} target */
  function activateRow(target) {
    if (target.closest("input,select,button,a,[data-edit]") !== null) return;
    var row = /** @type {HTMLElement | null} */ (target.closest("tr[data-activate]"));
    if (row === null) return;
    htmx.ajax("post", /** @type {string} */ (row.getAttribute("hx-post")), {
      source: /** @type {HTMLElement} */ (row.parentElement),
      values: {event: "activate_row", row: row.dataset.activate},
      swap: "none"
    });
  }
  /* editing a table cell: the server swaps the table back with a field in the cell (see
     `WebTableRenderer`), posting its text on Enter or when the user leaves it. F2 on a row
     edits its first editable cell, as a double click on the cell does; the field comes
     with its text selected, and Escape puts the text back before leaving it. */
  document.addEventListener("keydown", function (event) {
    var target = /** @type {Element} */ (event.target);
    if (event.key !== "F2" || target.tagName !== "TR") return;
    var cell = target.querySelector("[data-edit]");
    if (cell !== null) {
      event.preventDefault();
      htmx.trigger(cell, "dblclick");
    }
  });
  /* captured, so before `page.js`'s Escape hiding the sidebar's drawer, which this script's
     listeners would else follow: its focus would leave the field first, posting its text */
  document.addEventListener("keydown", function (event) {
    var target = /** @type {HTMLInputElement} */ (event.target);
    if (event.key !== "Escape" || !("cell" in target.dataset)) return;
    target.value = /** @type {string} */ (target.dataset.original);
    delete target.dataset.typed;
    target.blur();
  }, true);
  document.addEventListener("htmx:load", function (event) {
    var field = /** @type {HTMLInputElement | null} */ (
      event.detail.elt.querySelector("[data-cell]")
    );
    if (field !== null && field === document.activeElement && !("typed" in field.dataset)) {
      field.select();
    }
  });
  /* the field keeps the text the user is typing through a swap of its table (e.g. the
     answer to the double click's own clicks, selecting the row, arriving after a key):
     the server only gets the text at the end, so its copy of the table has the old. */
  document.addEventListener("input", function (event) {
    var target = /** @type {HTMLElement} */ (event.target);
    if ("cell" in target.dataset) target.dataset.typed = "";
  });
  document.addEventListener("htmx:oobBeforeSwap", function (event) {
    var field = /** @type {HTMLInputElement | null} */ (document.activeElement);
    if (field === null || !("typed" in field.dataset)) return;
    var swapped = /** @type {HTMLElement | null} */ (
      event.detail.fragment.querySelector("#" + CSS.escape(field.id))
    );
    if (swapped === null) return;
    swapped.setAttribute("value", field.value);
    swapped.dataset.typed = "";
  });
  /* a table's check-all box while some of its rows are checked: only a script shows a
     box partly checked */
  document.addEventListener("htmx:load", function (event) {
    event.detail.elt.querySelectorAll("[data-indeterminate]").forEach(function (box) {
      /** @type {HTMLInputElement} */ (box).indeterminate = true;
    });
  });
  /* a table's filter editor: its regular expression toggle shows only for a column a
     pattern filters, and the value's placeholder hints at what filters the column picked */
  document.addEventListener("change", function (event) {
    var form = /** @type {HTMLInputElement} */ (event.target).form;
    if (!form || form.querySelector("[data-filter-column]") === null) return;
    var column = /** @type {HTMLSelectElement} */ (form.querySelector("[data-filter-column]"));
    var option = /** @type {HTMLOptionElement} */ (column.selectedOptions[0]);
    var toggle = /** @type {HTMLElement} */ (form.querySelector("[data-filter-pattern]"));
    var patternHint = option.dataset.patternPlaceholder;
    toggle.hidden = patternHint === "";
    var isPattern =
      patternHint !== "" && /** @type {HTMLInputElement} */ (toggle.querySelector("input")).checked;
    var value = /** @type {HTMLInputElement} */ (form.querySelector('[name="value"]'));
    var hint = isPattern ? patternHint : option.dataset.placeholder;
    value.placeholder = /** @type {string} */ (hint);
  });
  /* a large table draws the rows around the view alone (see `WebSourceTableRenderer`): once
     the user stops scrolling its frame outside them, post the row under the headers and
     how far down the rows it is, in rows' heights, which the frame's hidden fields take.
     A filler stands for its rows, scaled past the rows the scroll bar's height stands for:
     the row is where the scroll position falls among the rows each filler stands for.
     Scrolling doesn't bubble: captured. */
  var WINDOW_SCROLL_MS = 100;
  /** @param {HTMLElement} frame */
  function fetchWindow(frame) {
    var rows = frame.querySelectorAll("tr[data-window-row]");
    if (rows.length === 0) return;
    var view = frame.getBoundingClientRect();
    var head = /** @type {Element} */ (frame.querySelector("thead")).getBoundingClientRect().height;
    var firstRow = /** @type {Element} */ (rows[0]);
    var first = firstRow.getBoundingClientRect();
    var last = /** @type {Element} */ (rows[rows.length - 1]).getBoundingClientRect();
    if (first.top <= view.top + head && last.bottom >= view.bottom) return;  // drawn already
    var body = /** @type {Element} */ (frame.querySelector("tbody")).getBoundingClientRect();
    var table = /** @type {Element} */ (frame.querySelector("table"));
    var count = Number(table.getAttribute("aria-rowcount")) - 1;
    var drawn = Number(firstRow.getAttribute("aria-rowindex")) - 2;  /* the first row drawn */
    var at = view.top + head - body.top;  /* the rows' offset under the headers */
    var above = first.top - body.top;
    var below = last.bottom - body.top;
    var shown;
    if (at < above) {
      shown = (at / above) * drawn;
    } else if (at < below) {
      shown = drawn + (at - above) / first.height;
    } else {
      var after = count - drawn - rows.length;
      var past = body.height > below ? ((at - below) / (body.height - below)) * after : 0;
      shown = drawn + rows.length + past;
    }
    var offset = /** @type {HTMLInputElement} */ (frame.querySelector("[data-scroll-offset]"));
    offset.value = String(at / first.height);
    var start = /** @type {HTMLInputElement} */ (frame.querySelector("[data-scroll-start]"));
    start.value = String(Math.min(Math.max(Math.floor(shown), 0), Math.max(count - 1, 0)));
    window.ComposeUI.dispatch(start, "scroll-window");
  }
  document.addEventListener("scroll", function (event) {
    var target = event.target;
    if (!(target instanceof HTMLElement) || !("virtualScroll" in target.dataset)) return;
    var frame = target;
    clearTimeout(frame.windowTimer);
    frame.windowTimer = setTimeout(function () { fetchWindow(frame); }, WINDOW_SCROLL_MS);
  }, true);
  /* Ctrl+C in a large table's frame copies its selected rows, unless the user selected text
     there, which the browser copies: the server answers them in the hidden element posting
     the copy. Firefox and Safari let the page write the clipboard only during the user's
     Ctrl+C, before the answer: the clipboard gets an item then, its text a promise the
     answer keeps (`copyAnswers`). No row selected, it's refused: the clipboard keeps its
     text. A browser without `ClipboardItem` writes the text once answered. */
  /** @type {{resolve: (text: string) => void, reject: (error: Error) => void}[]} */
  var copyAnswers = [];
  document.addEventListener("copy", function (event) {
    var target = event.target;
    var frame = target instanceof Element ? target.closest("[data-virtual-scroll]") : null;
    if (frame === null || !(/** @type {Selection} */ (document.getSelection()).isCollapsed)) {
      return;
    }
    event.preventDefault();
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      /** @type {Promise<string>} */
      var text = new Promise(function (resolve, reject) {
        copyAnswers.push({ resolve: resolve, reject: reject });
      });
      var item = new ClipboardItem({
        "text/plain": text.then(function (copied) {
          return new Blob([copied], { type: "text/plain" });
        }),
      });
      navigator.clipboard.write([item]).catch(function () {});  /* nothing to copy */
    }
    var parent = /** @type {Element} */ (frame.parentElement);
    var copied = /** @type {Element} */ (parent.querySelector("[data-copied]"));
    window.ComposeUI.dispatch(copied, "copy-rows");
  });
  document.addEventListener("htmx:load", function (event) {
    /* the answer comes on its own, or in the whole table swapped in */
    var elt = event.detail.elt;
    var copied = elt.matches("[data-copy-answer]") ? elt : elt.querySelector("[data-copy-answer]");
    if (copied === null) return;
    var answer = copyAnswers.shift();
    var text = /** @type {string} */ (copied.textContent);
    if (answer !== undefined) {
      if (text !== "") answer.resolve(text);
      else answer.reject(new Error("no row selected"));
    } else if (text !== "" && navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(function () {});
    }
  });
})();
