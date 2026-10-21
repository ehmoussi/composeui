/* The page's script (see `page.py`), run in its <head> before the body is parsed.
   Its <script> element carries the addresses of uPlot and Cally, which carry
   their content's hash. */
var PAGE_SCRIPT = document.currentScript;
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
  script.src = PAGE_SCRIPT.dataset.uplot;
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
      // each value held until the next point; its fill, a step area
      if (series.step) options.paths = uPlot.paths.stepped({ align: 1 });
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
  // the ranges take the reference lines in, as they would points
  var lineXs = [];
  var lineYs = [];
  spec.lines.forEach(function (line) { (line.vertical ? lineXs : lineYs).push(line.value); });
  if (!("categories" in spec)) {
    scales.x.range = rangeWith(scales.x.range, lineXs, spec.x.log, false);
  }
  scales.y.range = rangeWith(scales.y.range, lineYs, spec.y.log, true);
  return {
    width: width,
    height: element.clientHeight,
    cursor: { dataIdx: heldIndex(spec) },
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
    hooks: { draw: [drawReferenceLines(spec, ink)] },
  };
}
/* a scale's range, uPlot's own unless given, widened to `values`; as given without any */
function rangeWith(range, values, log, padded) {
  if (values.length === 0) return range;
  if (range === undefined) {
    range = function (chart, min, max) {
      if (log) return uPlot.rangeLog(min, max, 10, padded);
      return padded || min === max ? uPlot.rangeNum(min, max, 0.1, true) : [min, max];
    };
  }
  var low = Math.min.apply(null, values);
  var high = Math.max.apply(null, values);
  return function (chart, min, max, key) {
    // no data: the lines alone
    return range(
      chart, min === null ? low : Math.min(min, low), max === null ? high : Math.max(max, high), key
    );
  };
}
/* a reference line's dash pattern, by its style, in CSS pixels */
var LINE_DASHES = { solid: [], dashed: [6, 4], dotted: [2, 3], dash_dot: [6, 3, 2, 3] };
/* the reference lines (see `ReferenceLine`): in their styles, over the series, each
   labeled at its end in the ticks' font, which an image's options enlarge */
function drawReferenceLines(spec, ink) {
  return function (chart) {
    var context = chart.ctx;
    var box = chart.bbox;  // the plot, in the canvas' pixels
    var gap = 4 * uPlot.pxRatio;
    context.save();
    context.font = chart.axes[1].font[0];
    context.lineWidth = 1.5 * uPlot.pxRatio;
    context.textAlign = "right";
    spec.lines.forEach(function (line) {
      var position = chart.valToPos(line.value, line.vertical ? "x" : "y", true);
      var start = line.vertical ? box.left : box.top;
      var end = start + (line.vertical ? box.width : box.height);
      if (!(position >= start && position <= end)) return;  // zoomed past it
      context.strokeStyle = context.fillStyle = line.color || ink;
      context.setLineDash(LINE_DASHES[line.style].map(function (length) {
        return length * uPlot.pxRatio;
      }));
      context.beginPath();
      if (line.vertical) {
        context.moveTo(position, box.top);
        context.lineTo(position, box.top + box.height);
      } else {
        context.moveTo(box.left, position);
        context.lineTo(box.left + box.width, position);
      }
      context.stroke();
      // a horizontal one's over it at its right end; a vertical one's at its top, left
      // of it (now, after the data)
      if (line.vertical) {
        context.textBaseline = "top";
        context.fillText(line.label, position - gap, box.top + gap);
      } else {
        context.textBaseline = "bottom";
        context.fillText(line.label, box.left + box.width - gap, position - gap / 2);
      }
    });
    context.restore();
  };
}
/* the point whose value the legend shows at the cursor: uPlot's nearest, but a step
   line's the last at or before the cursor, whose value it holds there */
function heldIndex(spec) {
  return function (chart, seriesIndex, nearest, x) {
    var series = spec.series[seriesIndex - 1];  // none for the x, at 0
    if (series === undefined || !series.step || series.kind !== "line" || nearest === null) {
      return nearest;
    }
    var xs = chart.data[0];
    var ys = chart.data[seriesIndex];
    var index = nearest;
    // back over a later point, and over the other series' x, where it has no point
    while (index >= 0 && (xs[index] > x || ys[index] === undefined)) index--;
    return index < 0 ? null : index;
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
  // the image's download follows the zoom
  options.hooks.setScale = [function (chart) { updateImageLink(element, chart); }];
  options.hooks.setLegend = [function () { keepLegendWidths(element.chartLegend); }];
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
  // once its reference lines are drawn
  options.hooks.draw.push(function (chart) {
    if (isSaved) return;
    isSaved = true;
    var canvas = composePng(chart.ctx.canvas, spec.title, entries, ink, titleHeight);
    chart.destroy();
    stage.remove();
    canvas.toBlob(function (blob) { download(blob, name); });
  });
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
   Option key on macOS, would type. */
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

/* what the markup can't say itself: the page's policy (`headers.py`) runs no inline
   handler, and no code htmx would evaluate (`hx-on`, `js:` values, trigger filters). The
   values a request posts beside its element's own (see `htmx-config` in `page.py`): */
document.addEventListener("htmx:configRequest", function (event) {
  var element = event.detail.elt;
  var parameters = event.detail.parameters;
  var triggering = event.detail.triggeringEvent;
  if ("postEvent" in element.dataset) parameters.event = triggering.type;
  if ("postPicked" in element.dataset) parameters.picked = triggering.target.value;
  if ("postOpen" in element.dataset) parameters.open = element.open;
  if ("sidebarToggle" in element.dataset) {
    var sidebar = document.getElementById(element.getAttribute("aria-controls"));
    parameters.expanded = !sidebar.hasAttribute("data-retracted");
  }
});
document.addEventListener("htmx:afterRequest", function (event) {
  if ("clearAfterPost" in event.detail.elt.dataset) event.detail.elt.value = "";
});
/* the triggers htmx would filter: Enter, Escape, and `activate` (a click, or Enter, not
   from a field or a button, which take their own) for a table's rows. Captured, so they
   come before the keydown's own handlers, as htmx's filters did. */
document.addEventListener("keydown", function (event) {
  if (event.key === "Enter") dispatch(event.target, "enter-key");
  else if (event.key === "Escape") dispatch(event.target, "escape-key");
  if (event.key === "Enter" && event.target.closest("input,select,button") === null) {
    dispatch(event.target, "activate");
  }
}, true);
function dispatch(target, type) {
  target.dispatchEvent(new CustomEvent(type, { bubbles: true }));
}
/* a dialog's button closes it first, so the focus returns where it was, then posts its
   answer; a dialog Escape mustn't dismiss stays open (`cancel` doesn't bubble) */
document.addEventListener("click", function (event) {
  if (event.target.closest("input,select,button") === null) dispatch(event.target, "activate");
  var closing = event.target.closest("[data-close-dialog]");
  if (closing !== null) closing.closest("dialog").close();
}, true);
document.addEventListener("cancel", function (event) {
  if ("keepOpen" in event.target.dataset) event.preventDefault();
}, true);
/* a menu's item, or the Theme menu's choice, closes its dropdown (daisyUI's stays open
   while it has the focus) */
document.addEventListener("click", function (event) {
  var option = event.target.closest("[data-theme-option]");
  if (option !== null) setTheme(option.dataset.themeOption);
  if (option !== null || event.target.closest("[data-close-dropdown]") !== null) {
    document.activeElement.blur();
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
/* a table's check-all box while some of its rows are checked: only a script shows a
   box partly checked */
document.addEventListener("htmx:load", function (event) {
  event.detail.elt.querySelectorAll("[data-indeterminate]").forEach(function (box) {
    box.indeterminate = true;
  });
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
/* the date fields' calendar, Cally's `<calendar-date>`: the page loads it only once it
   shows its first date field, from a swap too, as it does uPlot */
var callyLoading = false;
function loadCalendars() {
  if (callyLoading || document.querySelector("calendar-date") === null) return;
  callyLoading = true;
  var script = document.createElement("script");
  script.type = "module";
  script.src = PAGE_SCRIPT.dataset.cally;
  document.head.appendChild(script);
}
/* a date field's calendar (see `WebDateInputRenderer`), a popover its button opens: it
   names the months and days in the page's language, and starts on the date, focused,
   so the arrows move from it. Opened before Cally has loaded, it waits for it to draw
   the days: the language as an attribute, which the element keeps once Cally defines
   it, unlike a property set before then. The date picked closes it, the button taking the focus
   back, once its `change` has posted it: the server swaps the field back showing it. */
document.addEventListener("toggle", function (event) {
  var calendar = event.target.querySelector && event.target.querySelector("[data-date-calendar]");
  if (calendar === null || calendar === undefined || event.newState !== "open") return;
  var language = document.documentElement.lang;
  if (language) calendar.setAttribute("locale", language);
  customElements.whenDefined("calendar-date").then(function () {
    return calendar.updated;  // its days drawn, which it focuses
  }).then(function () {
    if (event.target.matches(":popover-open")) calendar.focus();
  });
}, true);
document.addEventListener("change", function (event) {
  if (!("dateCalendar" in event.target.dataset)) return;
  var popover = event.target.closest("[popover]");
  popover.hidePopover();
  document.getElementById(popover.dataset.dateButton).focus();
}, true);
/* a file path field's "…" button opens the browser's file picker, a hidden file input
   beside it, which uploads the file picked (see `WebFilePathInputRenderer`) */
document.addEventListener("click", function (event) {
  var button = event.target.closest("[data-file-browse]");
  if (button === null) return;
  button.parentElement.querySelector('input[type="file"]').click();
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
/* splitters (see `WebSplitterRenderer`): dragging a border, or the arrow keys on it,
   shares the length of the shown panes beside it between them at once: their widths,
   or their heights across a horizontal border (a vertical splitter's). Each pane's
   share becomes its length in pixels, so they keep it as the window resizes. The
   panes' lengths are posted once the drag ends, or on each key. */
var PANE_MIN_LENGTH = 48;
var BORDER_KEY_STEP = 16;
function isAcross(border) {
  return border.getAttribute("aria-orientation") === "horizontal";
}
function paneLength(border, pane) {
  return isAcross(border) ? pane.offsetHeight : pane.offsetWidth;
}
function splitterPanes(border) {
  return Array.prototype.filter.call(border.parentElement.children, function (child) {
    return child.hasAttribute("data-pane");
  });
}
function paneBeside(border, step) {
  var element = step < 0 ? border.previousElementSibling : border.nextElementSibling;
  while (
    element !== null &&
    !(element.hasAttribute("data-pane") && paneLength(border, element) > 0)
  ) {
    element = step < 0 ? element.previousElementSibling : element.nextElementSibling;
  }
  return element;
}
function paneMinimum(border, pane, total) {
  // the pane's own, if larger: side by side, as wide as its text needs to be read
  var style = getComputedStyle(pane);
  var length = parseFloat(isAcross(border) ? style.minHeight : style.minWidth) || 0;
  return Math.min(Math.max(PANE_MIN_LENGTH, length), total / 2);
}
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
    if (lengths[index] > 0) pane.style.setProperty("--share", lengths[index] + " 1 0%");
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
function postPaneLengths(border) {
  var splitter = border.closest("[data-splitter]");
  htmx.ajax("POST", "/widget/" + splitter.id, {
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
function borderStart(border) {
  var before = paneBeside(border, -1);
  var after = paneBeside(border, 1);
  return {
    before: before === null ? 0 : paneLength(border, before),
    after: after === null ? 0 : paneLength(border, after),
  };
}
document.addEventListener("pointerdown", function (event) {
  var border = event.target.closest(".cui-splitter-border");
  if (border === null || border.getAttribute("aria-disabled") === "true") return;
  if (event.button !== 0) return;
  event.preventDefault();  // no text selected while dragging
  border.focus();
  border.setPointerCapture(event.pointerId);
  border.setAttribute("data-dragging", "");
  var across = isAcross(border);
  var from = across ? event.clientY : event.clientX;
  var start = borderStart(border);
  function move(moveEvent) {
    moveBorder(border, start, (across ? moveEvent.clientY : moveEvent.clientX) - from);
  }
  function end() {
    border.removeEventListener("pointermove", move);
    border.removeEventListener("pointerup", end);
    border.removeEventListener("pointercancel", end);
    border.removeAttribute("data-dragging");
    postPaneLengths(border);
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
  loadCalendars();
  syncSidebarToggles();
  new MutationObserver(function () {
    syncInvalidFields();
    syncSidebarToggles();
    openDialogs();
    syncPage();
    syncCharts();
    loadCalendars();
  }).observe(document.body, {
    childList: true,
    subtree: true,
  });
});
