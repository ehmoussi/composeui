import hashlib
import html
from pathlib import Path
from string import Template

_STATIC = Path(__file__).parent / "static"


def _static_url(name: str) -> str:
    """Get the address of a static file, naming its content.

    A new version of the file has a new address, so a browser never keeps using a copy it
    cached of an older one (e.g. a stylesheet without the classes a new page uses).
    """
    digest = hashlib.sha256((_STATIC / name).read_bytes()).hexdigest()[:16]
    return f"/static/{name}?v={digest}"


# no `data-theme`: daisyUI then follows the browser's light/dark preference
_PAGE = Template("""<!DOCTYPE html>
<html lang="$language">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>$title</title>
<!-- no copies of past pages: going back or forward reloads the page from the server,
     whose state they would contradict, at the address of a page of the app -->
<meta name="htmx-config" content='{"historyCacheSize": 0, "refreshOnHistoryMiss": true}' />
<script src="$htmx_url"></script>
<!-- built from css/app.css by `make css`: no CDN, so the page works offline -->
<link href="$css_url" rel="stylesheet" type="text/css" />
<script>
/* charts (see `WebChartRenderer`): uPlot draws each `[data-chart]` element from its
   JSON. The page loads uPlot only once it shows its first chart, from a swap too. A
   chart waits to be drawn until its element has a width (one on a hidden page has
   none), follows its element's width, and is rebuilt when the theme changes: uPlot
   can't recolor a chart. One swapped out is destroyed, leaving the x range the user
   zoomed into to the chart swapped in with its id (a job adding points). */
var charts = new Map();  // each element drawn, or waiting for a width, to its chart
var chartZooms = new Map();  // the zoom of a chart swapped out, by its element's id
var uPlotLoading = false;
function loadCharts() {
  if (document.querySelector("[data-chart]") === null || uPlotLoading) return;
  uPlotLoading = true;
  var script = document.createElement("script");
  script.src = "$uplot_url";
  script.onload = syncCharts;
  document.head.appendChild(script);
}
/* a CSS color as the canvas takes it: daisyUI's variables, mixed, resolved */
function resolveColor(element, color) {
  var probe = document.createElement("span");
  probe.hidden = true;
  probe.style.color = color;
  element.appendChild(probe);
  var resolved = getComputedStyle(probe).color;
  probe.remove();
  return resolved;
}
/* the theme's colors, ordered so neighbours differ in hue: primary and secondary alike
   are blue to violet */
var SERIES_COLORS = ["primary", "warning", "accent", "secondary", "success", "info", "error"];
function chartValue(unit) {
  return function (chart, value) {
    if (value === null || value === undefined) return "-";
    // its trailing zeros kept: as many digits wherever the cursor is
    return value.toPrecision(4) + (unit === "" ? "" : " " + unit);
  };
}
function chartOptions(element, spec, width) {
  var ink = resolveColor(element, "var(--color-base-content)");
  var background = resolveColor(element, "var(--color-base-100)");
  var faint = resolveColor(
    element, "color-mix(in oklch, var(--color-base-content) 12%, transparent)"
  );
  function axis(side) {
    return {
      label: side.label,
      stroke: ink,
      grid: { stroke: faint, width: 1 },
      ticks: { stroke: faint, width: 1 },
    };
  }
  var series = spec.series.map(function (series, index) {
    // its own color, the same in every theme, or the theme's
    var color = series.color || resolveColor(
      element, "var(--color-" + SERIES_COLORS[index % SERIES_COLORS.length] + ")"
    );
    var options = { label: series.name, stroke: color, value: chartValue(spec.y.unit) };
    if (series.kind === "bar") {
      // its bar in each category's group, by its left edge: offsets from the server
      function lefts(chart) {
        return chart.data[0].map(function (x) { return x + series.offset - series.width / 2; });
      }
      function widths(chart) {
        return chart.data[0].map(function () { return series.width; });
      }
      options.paths = uPlot.paths.bars({
        disp: { x0: { unit: 1, values: lefts }, size: { unit: 1, values: widths } },
      });
      options.fill = color;
      // a line of the background between neighbouring bars
      options.stroke = background;
      options.width = 1;
      options.points = { show: false };
    } else if (series.kind === "scatter") {
      // dots alone, ringed with the background: overlapping ones stay apart
      options.paths = function () { return null; };
      options.points = { show: true, size: 8, fill: color, stroke: background, width: 1 };
    } else {
      options.width = 2;
      // down to 0, uPlot's own fill, e.g. a shape
      if (series.fill) options.fill = color;
      // past the theme's colors, around again dashed
      options.dash = index < SERIES_COLORS.length ? undefined : [6, 4];
      options.spanGaps = false;
      options.points = { show: false };
    }
    return options;
  });
  var x = { label: spec.x.label, value: chartValue(spec.x.unit) };
  if (spec.x.label === "") {
    // no title: the value alone, rather than uPlot's "Value:" before it
    x.label = document.createElement("span");
    x.class = "chart-unnamed";
  }
  // a log scale: uPlot's distribution 3
  var scales = { x: { time: false, distr: spec.x.log ? 3 : 1 }, y: { distr: spec.y.log ? 3 : 1 } };
  var axes = [axis(spec.x), axis(spec.y)];
  if ("categories" in spec) {
    // a category's index stands for its name; the bars stand on 0
    var categories = spec.categories;
    var name = function (chart, index) {
      return index === null || index === undefined ? "-" : categories[index] || "";
    };
    x.value = name;
    scales.x.range = function () { return [-0.5, categories.length - 0.5]; };
    if (!spec.y.log) {
      scales.y.range = function (chart, min, max) {
        return uPlot.rangeNum(Math.min(0, min), Math.max(0, max), 0.1, true);
      };
    }
    axes[0].splits = function () {
      return categories.map(function (_, index) { return index; });
    };
    axes[0].values = function (chart, splits) {
      return splits.map(function (split) { return name(chart, split); });
    };
    axes[0].grid = { show: false };
  }
  return {
    width: width,
    height: element.clientHeight,
    scales: scales,
    axes: axes,
    series: [x].concat(series),
    // under the plot, out of its element: the element's height is the plot's
    legend: {
      mount: function (chart, legend) {
        element.chartLegend = legend;
        element.after(legend);
      },
    },
  };
}
function chartData(spec) {
  if ("data" in spec) return spec.data;
  if (spec.pairs.length === 0) return [[]];  // no series yet: the axes alone
  // each series by its own x: joined on every x, a series' own gaps kept
  return uPlot.join(spec.pairs);
}
function drawChart(element, zoom) {
  var spec = JSON.parse(element.dataset.chart);
  var options = chartOptions(element, spec, element.clientWidth);
  options.hooks = {
    // the image's download follows the zoom
    setScale: [function (chart) { updateImageLink(element, chart); }],
    setLegend: [function () { keepLegendWidths(element.chartLegend); }],
  };
  var chart = new uPlot(options, chartData(spec), element);
  if (zoom !== undefined) chart.setScale("x", zoom);
  charts.set(element, chart);
  updateImageLink(element, chart);
  postClicks(element, chart);
}
/* each value of the legend as wide as the widest it has shown: a value of other digits
   at the cursor, e.g. a minus sign or an exponent, would move its neighbours */
function keepLegendWidths(legend) {
  if (legend === undefined) return;
  legend.querySelectorAll(".u-value").forEach(function (cell) {
    var width = cell.getBoundingClientRect().width;
    if (width > (cell.widestValue || 0)) {
      cell.widestValue = width;
      cell.style.minWidth = width + "px";
    }
  });
}
/* a click on the plot posts its point, in the axes' values (see `WebChartRenderer`);
   not the end of a drag, which zooms */
var CLICK_SLOP = 3;
function postClicks(element, chart) {
  var down = null;
  chart.over.addEventListener("mousedown", function (event) {
    down = { x: event.clientX, y: event.clientY };
  });
  chart.over.addEventListener("click", function (event) {
    if (down === null) return;
    var moved = Math.abs(event.clientX - down.x) + Math.abs(event.clientY - down.y);
    down = null;
    if (moved > CLICK_SLOP) return;
    var figure = element.closest("figure");
    htmx.ajax("POST", "/widget/" + figure.id, {
      source: figure,
      swap: "none",
      values: {
        event: "click",
        x: chart.posToVal(event.offsetX, "x"),
        y: chart.posToVal(event.offsetY, "y"),
      },
    });
  });
}
/* the address of a chart's image (see `WebChartRenderer`): its format picked beside it,
   and the region the user zoomed into, which the server draws */
function updateImageLink(element, chart) {
  var figure = element.closest("figure");
  var link = figure === null ? null : figure.querySelector("[data-chart-image]");
  if (link === null) return;
  var query = new URLSearchParams({ format: figure.querySelector("[data-chart-format]").value });
  if (chart !== null && chart !== undefined && chartZoom(chart) !== undefined) {
    query.set("x_min", chart.scales.x.min);
    query.set("x_max", chart.scales.x.max);
    query.set("y_min", chart.scales.y.min);
    query.set("y_max", chart.scales.y.max);
  }
  link.setAttribute("href", link.getAttribute("href").split("?")[0] + "?" + query);
}
document.addEventListener("change", function (event) {
  if (!("chartFormat" in event.target.dataset)) return;
  var element = event.target.closest("figure").querySelector("[data-chart]");
  updateImageLink(element, charts.get(element));
});
/* no matplotlib on the server: the page draws the chart's PNG itself, a second chart
   off-screen at the image's size, in the light theme whatever the page's (a figure for
   a document), at the zoom shown. Its canvas, under the title, over the legend (both
   HTML in uPlot, not on its canvas), on a white canvas of its own, downloaded. */
var PNG_WIDTH = 1600;
var PNG_HEIGHT = 1000;
var PNG_TITLE_HEIGHT = 80;
var PNG_LEGEND_HEIGHT = 70;
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-chart-png]");
  if (button !== null) savePng(button.closest("figure"), button.dataset.chartPng);
});
function savePng(figure, name) {
  var element = figure.querySelector("[data-chart]");
  var spec = JSON.parse(element.dataset.chart);
  var shown = charts.get(element);
  var zoom = shown === null || shown === undefined ? undefined : chartZoom(shown);
  var titleHeight = spec.title === "" ? 0 : PNG_TITLE_HEIGHT;
  var stage = document.createElement("div");
  stage.dataset.theme = "composeui";
  stage.dataset.chartStage = "";
  stage.style.cssText = "position: fixed; left: -100000px; top: 0; width: " + PNG_WIDTH + "px";
  var plot = document.createElement("div");
  plot.style.height = PNG_HEIGHT - titleHeight - PNG_LEGEND_HEIGHT + "px";
  stage.appendChild(plot);
  document.body.appendChild(stage);
  var options = chartOptions(plot, spec, PNG_WIDTH);
  options.legend = { show: false };
  // the screen's fonts would be tiny on an image this large
  options.axes.forEach(function (axis, index) {
    axis.font = "22px system-ui, sans-serif";
    axis.labelFont = "600 24px system-ui, sans-serif";
    axis.size = index === 0 ? 60 : 90;
    axis.labelSize = 40;
  });
  options.series.slice(1).forEach(function (series) {
    if (series.points.show) series.points.size = 14;
    else if (series.paths === undefined) series.width = 3;
  });
  if (zoom !== undefined) {
    options.scales.x.range = function () { return [zoom.min, zoom.max]; };
  }
  // read before uPlot takes the options over
  var entries = options.series.slice(1).map(function (series, index) {
    return { name: spec.series[index].name, color: series.fill || series.stroke };
  });
  var ink = resolveColor(plot, "var(--color-base-content)");
  var isSaved = false;
  options.hooks = {
    draw: [
      function (chart) {
        if (isSaved) return;
        isSaved = true;
        var canvas = composePng(chart.ctx.canvas, spec.title, entries, ink, titleHeight);
        chart.destroy();
        stage.remove();
        canvas.toBlob(function (blob) { download(blob, name); });
      },
    ],
  };
  new uPlot(options, chartData(spec), plot);
}
function composePng(plotCanvas, title, entries, ink, titleHeight) {
  var canvas = document.createElement("canvas");
  canvas.width = PNG_WIDTH;
  canvas.height = PNG_HEIGHT;
  var context = canvas.getContext("2d");
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, PNG_WIDTH, PNG_HEIGHT);
  context.fillStyle = ink;
  context.textBaseline = "middle";
  if (title !== "") {
    context.font = "600 36px system-ui, sans-serif";
    context.textAlign = "center";
    context.fillText(title, PNG_WIDTH / 2, titleHeight / 2);
  }
  var plotHeight = PNG_HEIGHT - titleHeight - PNG_LEGEND_HEIGHT;
  context.drawImage(plotCanvas, 0, titleHeight, PNG_WIDTH, plotHeight);
  // the legend in a row, centered: each series' color, then its name
  context.font = "28px system-ui, sans-serif";
  context.textAlign = "left";
  var widths = entries.map(function (entry) { return 36 + context.measureText(entry.name).width; });
  var gap = 40;
  var total = widths.reduce(function (sum, width) { return sum + width; }, 0);
  var x = Math.max(0, (PNG_WIDTH - total - gap * (entries.length - 1)) / 2);
  var y = PNG_HEIGHT - PNG_LEGEND_HEIGHT / 2;
  entries.forEach(function (entry, index) {
    context.fillStyle = entry.color;
    context.fillRect(x, y - 12, 24, 24);
    context.fillStyle = ink;
    context.fillText(entry.name, x + 36, y);
    x += widths[index] + gap;
  });
  return canvas;
}
function download(blob, name) {
  var url = URL.createObjectURL(blob);
  var link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // once the browser has the file
  setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
}
/* the x range the user zoomed into; undefined while the chart shows all its data */
function chartZoom(chart) {
  var xs = chart.data[0];
  var scale = chart.scales.x;
  if (xs.length === 0 || (scale.min <= xs[0] && scale.max >= xs[xs.length - 1])) return undefined;
  return { min: scale.min, max: scale.max };
}
function destroyChart(element) {
  var chart = charts.get(element);
  charts.delete(element);
  element.chartObserver.disconnect();
  if (chart === null) return;
  var zoom = chartZoom(chart);
  if (zoom !== undefined) chartZooms.set(element.id, zoom);
  chart.destroy();
}
function syncCharts() {
  charts.forEach(function (chart, element) {
    if (!element.isConnected) destroyChart(element);
  });
  if (typeof uPlot === "undefined") {
    loadCharts();
    return;
  }
  document.querySelectorAll("[data-chart]").forEach(function (element) {
    if (charts.has(element)) return;
    charts.set(element, null);
    element.chartObserver = new ResizeObserver(function () {
      var chart = charts.get(element);
      var width = element.clientWidth;
      if (width === 0) return;
      if (chart === null) {
        drawChart(element, chartZooms.get(element.id));
        chartZooms.delete(element.id);
      } else if (chart.width !== width) {
        chart.setSize({ width: width, height: element.clientHeight });
      }
    });
    element.chartObserver.observe(element);
  });
}
/* the theme changed: each chart drawn again in its colors, at the same zoom */
function redrawCharts() {
  charts.forEach(function (chart, element) {
    if (chart === null) return;
    var zoom = chartZoom(chart);
    chart.destroy();
    drawChart(element, zoom);
  });
}
/* the theme picked in the header's Theme menu: Light or Dark win over the browser's
   light/dark preference and are remembered by this browser; System forgets the choice
   and follows the browser again. Applied here, before the body renders, so a reload
   never flashes the other theme first. */
var THEMES = ["composeui", "composeui-dark"];
function storedTheme() {
  var theme = null;
  try {
    theme = localStorage.getItem("composeui-theme");
  } catch (error) {}  // storage blocked: follow the browser's preference
  return THEMES.indexOf(theme) >= 0 ? theme : "system";
}
function applyTheme(choice) {
  if (choice === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  document.querySelectorAll("[data-theme-option]").forEach(function (option) {
    option.setAttribute("aria-pressed", String(option.dataset.themeOption === choice));
  });
  redrawCharts();
}
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawCharts);
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
   Option key on macOS, would type. (No dollar sign in here: this page is a string.Template.) */
document.addEventListener("keydown", function (event) {
  if (!event.altKey || !event.shiftKey || event.ctrlKey || event.metaKey) return;
  var item = document.querySelector('[data-shortcut="' + event.code + '"]');
  if (item === null) return;
  event.preventDefault();
  item.click();
});
/* keeps each form field's aria-invalid in step with its log: while typing, only the log
   is swapped, never the field. The field is invalid while its log shows an error, or
   a check of its form fails on its row (`data-form-error`). Watches the DOM, so it
   runs after every htmx swap. */
function syncInvalidFields() {
  document.querySelectorAll("[data-log]").forEach(function (log) {
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
    function (dialog) {
      dialog.dataset.opened = "";
      htmx.process(dialog);
      dialog.showModal();
    },
  );
}

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
      htmx.swap(document.body, request.responseText, { swapStyle: "none" });
    }
  });
});
/* editing a table cell: the server swaps the table back with a field in the cell (see
   `WebTableRenderer`), posting its text on Enter or when the user leaves it. F2 on a row
   edits its first editable cell, as a double click on the cell does; the field comes
   with its text selected, and Escape puts the text back before leaving it. */
document.addEventListener("keydown", function (event) {
  var target = event.target;
  if (event.key === "F2" && target.tagName === "TR") {
    var cell = target.querySelector("[data-edit]");
    if (cell !== null) {
      event.preventDefault();
      htmx.trigger(cell, "dblclick");
    }
  } else if (event.key === "Escape" && "cell" in target.dataset) {
    target.value = target.dataset.original;
    delete target.dataset.typed;
    target.blur();
  }
});
document.addEventListener("htmx:load", function (event) {
  var field = event.detail.elt.querySelector("[data-cell]");
  if (field !== null && field === document.activeElement && !("typed" in field.dataset)) {
    field.select();
  }
});
/* the field keeps the text the user is typing through a swap of its table (e.g. the
   answer to the double click's own clicks, selecting the row, arriving after a key):
   the server only gets the text at the end, so its copy of the table has the old. */
document.addEventListener("input", function (event) {
  if ("cell" in event.target.dataset) event.target.dataset.typed = "";
});
document.addEventListener("htmx:oobBeforeSwap", function (event) {
  var field = document.activeElement;
  if (field === null || !("typed" in field.dataset)) return;
  var swapped = event.detail.fragment.getElementById(field.id);
  if (swapped === null) return;
  swapped.setAttribute("value", field.value);
  swapped.dataset.typed = "";
});
/* a table's filter editor: its regular expression toggle shows only for a column a
   pattern filters, and the value's placeholder hints at what filters the column picked */
document.addEventListener("change", function (event) {
  var form = event.target.form;
  if (!form || form.querySelector("[data-filter-column]") === null) return;
  var option = form.querySelector("[data-filter-column]").selectedOptions[0];
  var toggle = form.querySelector("[data-filter-pattern]");
  var patternHint = option.dataset.patternPlaceholder;
  toggle.hidden = patternHint === "";
  var isPattern = patternHint !== "" && toggle.querySelector("input").checked;
  form.querySelector('[name="value"]').placeholder = isPattern
    ? patternHint
    : option.dataset.placeholder;
});
/* a slider's value follows its handle while it is dragged: the server only hears of the
   moves debounced (see `WebSliderRenderer`), and its answer never swaps the slider back */
document.addEventListener("input", function (event) {
  var slider = event.target;
  if (!("slider" in slider.dataset)) return;
  slider.parentElement.querySelector("output").value = slider.value;
});
/* the sidebar (see `WebSidebarRenderer`): on a wide screen, its button in the header
   retracts and expands the column, then posts its state; on a phone, it shows and hides
   the drawer, through the drawer's checkbox, which a click beside the drawer unchecks
   too. The button tells screen readers whether the column, or the drawer, shows; Escape
   hides the drawer. */
var wideScreen = window.matchMedia("(width >= 64rem)");
function sidebarDrawer(toggle) {
  return document.getElementById(toggle.dataset.sidebarToggle);
}
function syncSidebarToggles() {
  document.querySelectorAll("[data-sidebar-toggle]").forEach(function (toggle) {
    var sidebar = document.getElementById(toggle.getAttribute("aria-controls"));
    var drawer = sidebarDrawer(toggle);
    if (sidebar === null || drawer === null) return;
    var shows = wideScreen.matches ? !sidebar.hasAttribute("data-retracted") : drawer.checked;
    toggle.setAttribute("aria-expanded", String(shows));
  });
}
wideScreen.addEventListener("change", syncSidebarToggles);
document.addEventListener("click", function (event) {
  var toggle = event.target.closest("[data-sidebar-toggle]");
  if (toggle === null) return;
  if (wideScreen.matches) {
    document.getElementById(toggle.getAttribute("aria-controls")).toggleAttribute("data-retracted");
    htmx.trigger(toggle, "sidebar-toggle");
  } else {
    sidebarDrawer(toggle).click();
  }
  syncSidebarToggles();
});
document.addEventListener("change", function (event) {
  if (event.target.classList.contains("drawer-toggle")) syncSidebarToggles();
});
document.addEventListener("keydown", function (event) {
  if (event.key !== "Escape") return;
  document.querySelectorAll("[data-sidebar-toggle]").forEach(function (toggle) {
    var drawer = sidebarDrawer(toggle);
    if (drawer !== null && drawer.checked) {
      drawer.click();
      toggle.focus();
    }
  });
});
/* tabs (see `WebTabsRenderer`): a click on a tab shows its panel at once, then htmx
   posts the pick; the arrow keys, Home and End move to a tab that can be picked, and
   pick it, as an ARIA tab list does. Only the tab shown is in the tab order. */
function showTab(tab) {
  tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]').forEach(function (other) {
    var isShown = other === tab;
    other.setAttribute("aria-selected", String(isShown));
    other.tabIndex = isShown ? 0 : -1;
    other.classList.toggle("tab-active", isShown);
    document.getElementById(other.getAttribute("aria-controls")).hidden = !isShown;
  });
}
document.addEventListener("click", function (event) {
  var tab = event.target.closest("[data-tab]");
  if (tab !== null && !tab.disabled) showTab(tab);
});
document.addEventListener("keydown", function (event) {
  var tab = event.target;
  if (!(tab instanceof HTMLElement) || !("tab" in tab.dataset)) return;
  var tabs = Array.prototype.filter.call(
    tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]'),
    function (other) { return !other.hidden && !other.disabled; },
  );
  var index = tabs.indexOf(tab);
  var next = {
    ArrowRight: tabs[(index + 1) % tabs.length],
    ArrowLeft: tabs[(index - 1 + tabs.length) % tabs.length],
    Home: tabs[0],
    End: tabs[tabs.length - 1],
  }[event.key];
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
  document.documentElement.lang = marker.dataset.language;
  if (document.title !== marker.dataset.title) document.title = marker.dataset.title;
}
/* places a field's help, opened by its "?" button, right of the button, or under it
   when the window is too narrow (a phone), never over its field: a popover otherwise
   opens in the window's middle. Placed again once shown, its size then known.
   `data-side` points its arrow at the button (see `css/app.css`). */
function placeHelp(event) {
  var help = event.target;
  if (!(help instanceof HTMLElement) || !help.matches("[data-help]")) return;
  if (event.newState !== "open") return;
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
/* neither bubbles */
document.addEventListener("beforetoggle", placeHelp, true);
document.addEventListener("toggle", placeHelp, true);
document.addEventListener("DOMContentLoaded", function () {
  openDialogs();
  syncCharts();
  syncSidebarToggles();
  new MutationObserver(function () {
    syncInvalidFields();
    syncSidebarToggles();
    openDialogs();
    syncPage();
    syncCharts();
  }).observe(document.body, {
    childList: true,
    subtree: true,
  });
});
</script>
</head>

<body class="bg-base-200 min-h-screen">
<div id="app">
$content
</div>
$page_marker
$jobs_poller
</body>

</html>
""")


#: read once: the files only change with a new version of the package
_STATIC_URLS = {
    "htmx_url": _static_url("htmx.min.js"),
    "css_url": _static_url("app.css"),
    # uPlot 1.6.32 (https://github.com/leeoniya/uPlot), its stylesheet in css/uPlot.min.css
    "uplot_url": _static_url("uPlot.iife.min.js"),
}


def page_marker(language: str, title: str, *, oob: bool = False) -> str:
    """Get the element telling the page's script its `<html lang>` and `<title>`."""
    swap = ' hx-swap-oob="true"' if oob else ""
    return (
        f'<div id="cui-page" data-language="{html.escape(language)}"'
        f' data-title="{html.escape(title)}"{swap} hidden></div>'
    )


#: milliseconds the page waits, while jobs run, before asking for what they changed
JOBS_POLL_MS = 1000


def jobs_poller(*, is_running: bool, oob: bool = False) -> str:
    """Get the element asking the server for what the jobs changed, while they run.

    No response carries what a job's result changes (see `RenderTarget.pending`): while
    the main view's jobs run, this element fetches itself every `JOBS_POLL_MS`, which
    brings the changes along, until it comes back without a fetch once they are over.
    """
    swap = ' hx-swap-oob="true"' if oob else ""
    poll = (
        f' hx-get="/jobs" hx-trigger="load delay:{JOBS_POLL_MS}ms" hx-swap="outerHTML"'
        if is_running
        else ""
    )
    return f'<div id="cui-jobs"{poll}{swap} hidden></div>'


def get_page(title: str, content: str, language: str, *, jobs_running: bool) -> str:
    return _PAGE.substitute(
        {
            "title": html.escape(title),
            "content": content,
            "language": html.escape(language),
            "page_marker": page_marker(language, title),
            "jobs_poller": jobs_poller(is_running=jobs_running),
            **_STATIC_URLS,
        }
    )
