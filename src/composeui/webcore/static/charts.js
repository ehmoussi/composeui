/* charts (see `WebChartRenderer`): uPlot draws each `[data-chart]` element from its
   JSON. The page loads this script and uPlot only once it shows its first chart, from a
   swap too (see `page.js`), which then calls `sync` at each change of the page. A
   chart waits to be drawn until its element has a width (one on a hidden page has
   none), follows its element's width, and is rebuilt when the theme changes: uPlot
   can't recolor a chart. One swapped out is destroyed, leaving the x range the user
   zoomed into to the chart swapped in with its id (a job adding points). */
(function () {
  /** @type {Map<HTMLElement, uPlot | null>} each element drawn, or waiting for a width */
  var charts = new Map();
  /** @type {Map<string, ChartZoom>} the zoom of a chart swapped out, by its element's id */
  var chartZooms = new Map();
  /* a CSS color as the canvas takes it: daisyUI's variables, mixed, resolved */
  /** @param {HTMLElement} element @param {string} color */
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
  /** @param {string} unit @param {boolean} [whole] @returns {uPlot.Series.Value} */
  function chartValue(unit, whole) {
    return function (chart, value) {
      if (value === null || value === undefined) return "-";
      // a count as it is; else its trailing zeros kept: as many digits wherever the cursor is
      var text = whole ? value.toFixed(0) : value.toPrecision(4);
      return text + (unit === "" ? "" : " " + unit);
    };
  }
  /**
   * @param {HTMLElement} element @param {ChartSpec} spec @param {number} width
   * @returns {uPlot.Options & {series: uPlot.Series[], axes: uPlot.Axis[],
   *   scales: ChartScales, hooks: {draw: ((chart: uPlot) => void)[]}}}
   */
  function chartOptions(element, spec, width) {
    var ink = resolveColor(element, "var(--color-base-content)");
    var background = resolveColor(element, "var(--color-base-100)");
    var faint = resolveColor(
      element, "color-mix(in oklch, var(--color-base-content) 12%, transparent)"
    );
    /** @param {ChartAxisSpec} side @returns {uPlot.Axis} */
    function axis(side) {
      return {
        label: side.label,
        stroke: ink,
        grid: { stroke: faint, width: 1 },
        ticks: { stroke: faint, width: 1 },
      };
    }
    var y2 = spec.y2;
    var series = spec.series.map(function (series, index) {
      // its own color, the same in every theme, or the theme's
      var color = series.color || resolveColor(
        element, "var(--color-" + SERIES_COLORS[index % SERIES_COLORS.length] + ")"
      );
      // on its y axis, in its unit
      var side = series.on_y2 && y2 !== undefined ? y2 : spec.y;
      /** @type {uPlot.Series} */
      var options = {
        label: series.name,
        stroke: color,
        scale: yScale(series),
        value: chartValue(side.unit, series.whole),
      };
      if (series.kind === "bar") {
        // its bar in the group at each x, by its left edge: offsets from the server
        /** @param {uPlot} chart */
        function lefts(chart) {
          return xs(chart).map(function (x) { return x + series.offset - series.width / 2; });
        }
        /** @param {uPlot} chart */
        function widths(chart) {
          return xs(chart).map(function () { return series.width; });
        }
        options.paths = /** @type {uPlot.Series.BarsPathBuilderFactory} */ (uPlot.paths.bars)({
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
        if (series.fill) options.fill = series.fill_color || color;
        // past the theme's colors, around again dashed
        options.dash = index < SERIES_COLORS.length ? undefined : [6, 4];
        options.spanGaps = false;
        options.points = { show: false };
        // each value held until the next point; its fill, a step area
        if (series.step) {
          var stepped = /** @type {uPlot.Series.SteppedPathBuilderFactory} */ (uPlot.paths.stepped);
          options.paths = stepped({ align: 1 });
        }
      }
      return options;
    });
    /** @type {uPlot.Series} */
    var x = { label: spec.x.label, value: chartValue(spec.x.unit) };
    var time = spec.x.time;
    if (time !== undefined) {
      // in UTC, as the times were given (see `Scale.TIME`), as precise as they are
      var format = uPlot.fmtDate(TIME_FORMATS[time]);
      x.value = function (chart, value) {
        return value === null || value === undefined ? "-" : format(utcDate(value));
      };
    }
    if (spec.x.label === "") {
      // no title: the value alone, rather than uPlot's "Value:" before it
      x.label = document.createElement("span");
      x.class = "chart-unnamed";
    }
    // a log scale: uPlot's distribution 3
    /** @type {ChartScales} */
    var scales = {
      x: { time: time !== undefined, distr: spec.x.log ? 3 : 1 }, y: { distr: spec.y.log ? 3 : 1 },
    };
    /** @type {[uPlot.Axis, uPlot.Axis, ...uPlot.Axis[]]} */
    var axes = [axis(spec.x), axis(spec.y)];
    if (y2 !== undefined) {
      scales.y2 = { distr: y2.log ? 3 : 1 };
      // at the right, its ticks without lines: the left axis' lines alone
      var right = axis(y2);
      right.scale = "y2";
      right.side = 1;
      right.grid = { show: false };
      axes.push(right);
    }
    var categories = spec.categories;
    if (categories !== undefined) {
      // a category's index stands for its name
      var names = categories;
      /** @param {uPlot} chart @param {number | null | undefined} index */
      var name = function (chart, index) {
        return index === null || index === undefined ? "-" : names[index] || "";
      };
      x.value = name;
      scales.x.range = function () { return [-0.5, names.length - 0.5]; };
      axes[0].splits = function () {
        return names.map(function (_, index) { return index; });
      };
      axes[0].values = function (chart, splits) {
        return splits.map(function (split) { return name(chart, split); });
      };
      axes[0].grid = { show: false };
    }
    var barStep = spec.bar_step;
    if (barStep !== undefined) {
      // the bars stand on 0, on a linear axis that has some
      [["y", spec.y], ["y2", y2]].forEach(function (pair) {
        var key = /** @type {"y" | "y2"} */ (pair[0]);
        var side = /** @type {ChartAxisSpec | undefined} */ (pair[1]);
        var scale = scales[key];
        var hasBars = spec.series.some(function (series) {
          return series.kind === "bar" && yScale(series) === key;
        });
        if (scale === undefined || side === undefined || side.log || !hasBars) return;
        scale.range = function (chart, min, max) {
          return uPlot.rangeNum(Math.min(0, min), Math.max(0, max), 0.1, true);
        };
      });
      if (categories === undefined) {
        var half = barStep / 2;
        // the whole data: half a bar's room past the first and the last x, so that their
        // bars show whole. A zoom as it is: a range widened at each draw would drift
        scales.x.range = function (chart, min, max) {
          var values = xs(chart);
          if (min === null || max === null) return [-half, half];
          if (min !== values[0] || max !== values[values.length - 1]) return [min, max];
          return [min - half, max + half];
        };
      }
    }
    // the ranges take the reference lines in, as they would points
    /** @type {number[]} */
    var lineXs = [];
    /** @type {number[]} */
    var lineYs = [];
    /** @type {number[]} */
    var lineY2s = [];
    spec.lines.forEach(function (line) {
      (line.vertical ? lineXs : line.on_y2 ? lineY2s : lineYs).push(line.value);
    });
    if (categories === undefined) {
      scales.x.range = rangeWith(rangeFunction(scales.x), lineXs, spec.x.log, false);
    }
    scales.y.range = rangeWith(rangeFunction(scales.y), lineYs, spec.y.log, true);
    if (scales.y2 !== undefined && y2 !== undefined) {
      scales.y2.range = rangeWith(rangeFunction(scales.y2), lineY2s, y2.log, true);
    }
    // the app's bounds, over all that: the x's not over the user's zoom
    if (categories === undefined) {
      scales.x.range = rangeBounded(rangeFunction(scales.x), spec.x, false, true);
    }
    scales.y.range = rangeBounded(rangeFunction(scales.y), spec.y, true, false);
    if (scales.y2 !== undefined && y2 !== undefined) {
      scales.y2.range = rangeBounded(rangeFunction(scales.y2), y2, true, false);
    }
    return {
      width: width,
      height: element.clientHeight,
      // a time axis' ticks in UTC too
      tzDate: utcDate,
      cursor: {
        dataIdx: heldIndex(spec),
        // a move within the slop is a click: no zoom (uPlot zooms from `dist` pixels)
        drag: { dist: CLICK_SLOP + 1 },
      },
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
  /* the scale of a series' y: its axis' */
  /** @param {{on_y2?: boolean}} item @returns {"y" | "y2"} */
  function yScale(item) {
    return item.on_y2 ? "y2" : "y";
  }
  /* a time axis' legend, by how precise its times are (uPlot's `fmtDate`) */
  /** @type {Record<NonNullable<ChartAxisSpec["time"]>, string>} */
  var TIME_FORMATS = {
    day: "{YYYY}-{MM}-{DD}", minute: "{YYYY}-{MM}-{DD} {HH}:{mm}",
    second: "{YYYY}-{MM}-{DD} {HH}:{mm}:{ss}",
  };
  /* a time of a time axis, seconds since 1970, as a date uPlot shows in UTC */
  /** @param {number} seconds */
  function utcDate(seconds) {
    return uPlot.tzDate(new Date(seconds * 1e3), "Etc/UTC");
  }
  /* the x of a chart's points */
  /** @param {uPlot} chart @returns {number[]} */
  function xs(chart) {
    return /** @type {number[]} */ (chart.data[0]);
  }
  /* a scale's range, which this script gives as a function, if any */
  /** @param {uPlot.Scale} scale */
  function rangeFunction(scale) {
    return /** @type {uPlot.Range.Function | undefined} */ (scale.range);
  }
  /* a scale's range, uPlot's own unless given, widened to `values`; as given without any */
  /**
   * @param {uPlot.Range.Function | undefined} range @param {number[]} values
   * @param {boolean} log @param {boolean} padded @returns {uPlot.Range.Function | undefined}
   */
  function rangeWith(range, values, log, padded) {
    if (values.length === 0) return range;
    var given = range !== undefined ? range : fittedRange(log, padded);
    var low = Math.min.apply(null, values);
    var high = Math.max.apply(null, values);
    return function (chart, min, max, key) {
      // no data: the lines alone
      return given(
        chart,
        min === null ? low : Math.min(min, low),
        max === null ? high : Math.max(max, high),
        key
      );
    };
  }
  /* uPlot's own range of a scale, fitting its values */
  /** @param {boolean} log @param {boolean} padded @returns {uPlot.Range.Function} */
  function fittedRange(log, padded) {
    return function (chart, min, max) {
      if (log) return uPlot.rangeLog(min, max, 10, padded);
      return padded || min === max ? uPlot.rangeNum(min, max, 0.1, true) : [min, max];
    };
  }
  /* a scale's range at its axis' bounds (see `Axis.bounded`); as given without any. A
     bound past the other end leaves a unit on its side, a power of 10 on a log axis.
     `keepsZoom`: the x's, which uPlot asks at a zoom too, left as the user put it */
  /**
   * @param {uPlot.Range.Function | undefined} range @param {ChartAxisSpec} side
   * @param {boolean} padded @param {boolean} keepsZoom
   * @returns {uPlot.Range.Function | undefined}
   */
  function rangeBounded(range, side, padded, keepsZoom) {
    var minimum = side.minimum;
    var maximum = side.maximum;
    if (minimum === undefined && maximum === undefined) return range;
    var given = range !== undefined ? range : fittedRange(side.log, padded);
    return function (chart, min, max, key) {
      var fitted = given(chart, min, max, key);
      if (keepsZoom && isZoom(chart, min, max)) return fitted;
      var low = minimum !== undefined ? minimum : /** @type {number} */ (fitted[0]);
      var high = maximum !== undefined ? maximum : /** @type {number} */ (fitted[1]);
      if (low < high) return [low, high];
      if (maximum === undefined) return [low, side.log ? low * 10 : low + 1];
      return [side.log ? high / 10 : high - 1, high];
    };
  }
  /* whether uPlot asks the x range at the user's zoom, rather than at all the data */
  /** @param {uPlot} chart @param {number | null} min @param {number | null} max */
  function isZoom(chart, min, max) {
    var values = xs(chart);
    if (min === null || max === null || values.length === 0) return false;
    return min !== values[0] || max !== values[values.length - 1];
  }
  /* a reference line's dash pattern, by its style, in CSS pixels */
  /** @type {Record<ChartLineSpec["style"], number[]>} */
  var LINE_DASHES = { solid: [], dashed: [6, 4], dotted: [2, 3], dash_dot: [6, 3, 2, 3] };
  /* the reference lines (see `ReferenceLine`): in their styles, over the series, each
     labeled at its end in the ticks' font, which an image's options enlarge */
  /** @param {ChartSpec} spec @param {string} ink */
  function drawReferenceLines(spec, ink) {
    /** @param {uPlot} chart */
    return function (chart) {
      var context = chart.ctx;
      var box = chart.bbox;  // the plot, in the canvas' pixels
      var gap = 4 * uPlot.pxRatio;
      context.save();
      // uPlot keeps an axis' font as [font, size]
      var yAxis = /** @type {uPlot.Axis} */ (chart.axes[1]);
      context.font = /** @type {[string, number]} */ (/** @type {unknown} */ (yAxis.font))[0];
      context.lineWidth = 1.5 * uPlot.pxRatio;
      context.textAlign = "right";
      spec.lines.forEach(function (line) {
        var position = chart.valToPos(line.value, line.vertical ? "x" : yScale(line), true);
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
  /** @param {ChartSpec} spec @returns {uPlot.Cursor.DataIdxRefiner} */
  function heldIndex(spec) {
    return function (chart, seriesIndex, nearest, x) {
      var series = spec.series[seriesIndex - 1];  // none for the x, at 0
      if (series === undefined || !series.step || series.kind !== "line" || nearest === null) {
        return nearest;
      }
      var xs = chart.data[0];
      var ys = /** @type {uPlot.AlignedData[number]} */ (chart.data[seriesIndex]);
      var index = nearest;
      // back over a later point, and over the other series' x, where it has no point
      while (index >= 0 && (/** @type {number} */ (xs[index]) > x || ys[index] === undefined)) {
        index--;
      }
      return index < 0 ? null : index;
    };
  }
  /** @param {ChartSpec} spec @returns {uPlot.AlignedData} */
  function chartData(spec) {
    if (spec.data !== undefined) return spec.data;
    // no series yet: the axes alone
    if (spec.pairs === undefined || spec.pairs.length === 0) return [[]];
    // each series by its own x: joined on every x, a series' own gaps kept
    return uPlot.join(spec.pairs);
  }
  /** @param {HTMLElement} element @param {ChartZoom | undefined} zoom */
  function drawChart(element, zoom) {
    /** @type {ChartSpec} */
    var spec = JSON.parse(/** @type {string} */ (element.dataset.chart));
    var options = chartOptions(element, spec, element.clientWidth);
    // the image's download follows the zoom
    var hooks = /** @type {uPlot.Hooks.Arrays} */ (options.hooks);
    hooks.setScale = [function (chart) { updateImageLink(element, chart); }];
    hooks.setLegend = [function () { keepLegendWidths(element.chartLegend); }];
    var chart = new uPlot(options, chartData(spec), element);
    if (zoom !== undefined) chart.setScale("x", zoom);
    charts.set(element, chart);
    updateImageLink(element, chart);
    postClicks(element, chart);
  }
  /* each value of the legend as wide as the widest it has shown: a value of other digits
     at the cursor, e.g. a minus sign or an exponent, would move its neighbours */
  /** @param {HTMLElement | undefined} legend */
  function keepLegendWidths(legend) {
    if (legend === undefined) return;
    legend.querySelectorAll(".u-value").forEach(function (element) {
      var cell = /** @type {HTMLElement} */ (element);
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
  /** @param {HTMLElement} element @param {uPlot} chart */
  function postClicks(element, chart) {
    /** @type {{x: number, y: number} | null} */
    var down = null;
    /** @param {MouseEvent} event @param {{x: number, y: number}} from */
    function moved(event, from) {
      return Math.abs(event.clientX - from.x) + Math.abs(event.clientY - from.y);
    }
    chart.over.addEventListener("mousedown", function (event) {
      down = { x: event.clientX, y: event.clientY };
    });
    // uPlot stops the click ending any move, a pixel too: only one past the slop, a drag
    /** @type {uPlot.Cursor.Drag} */ (chart.cursor.drag).click = function (_chart, event) {
      if (down !== null && moved(event, down) > CLICK_SLOP) {
        event.stopPropagation();
        event.stopImmediatePropagation();
      }
    };
    // a click, then: pressed here, and the mouse moved within the slop, if at all
    chart.over.addEventListener("click", function (event) {
      if (down === null) return;
      down = null;
      var figure = /** @type {HTMLElement} */ (element.closest("figure"));
      htmx.ajax("post", "/widget/" + figure.id, {
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
  /** @param {HTMLElement} element @param {uPlot | null | undefined} chart */
  function updateImageLink(element, chart) {
    var figure = element.closest("figure");
    var link = figure === null ? null : figure.querySelector("[data-chart-image]");
    if (figure === null || link === null) return;
    var format = /** @type {HTMLSelectElement} */ (figure.querySelector("[data-chart-format]"));
    var query = new URLSearchParams({ format: format.value });
    if (chart !== null && chart !== undefined && chartZoom(chart) !== undefined) {
      var scales = chartScales(chart);
      query.set("x_min", String(scales.x.min));
      query.set("x_max", String(scales.x.max));
      query.set("y_min", String(scales.y.min));
      query.set("y_max", String(scales.y.max));
      if (scales.y2 !== undefined) {
        query.set("y2_min", String(scales.y2.min));
        query.set("y2_max", String(scales.y2.max));
      }
    }
    var address = /** @type {string} */ (link.getAttribute("href"));
    link.setAttribute("href", address.split("?")[0] + "?" + query);
  }
  document.addEventListener("change", function (event) {
    var target = /** @type {HTMLElement} */ (event.target);
    if (!("chartFormat" in target.dataset)) return;
    var figure = /** @type {HTMLElement} */ (target.closest("figure"));
    var element = /** @type {HTMLElement} */ (figure.querySelector("[data-chart]"));
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
    var button = /** @type {Element} */ (event.target).closest("[data-chart-png]");
    if (!(button instanceof HTMLElement)) return;
    var figure = /** @type {HTMLElement} */ (button.closest("figure"));
    savePng(figure, /** @type {string} */ (button.dataset.chartPng));
  });
  /** @param {HTMLElement} figure @param {string} name */
  function savePng(figure, name) {
    var element = /** @type {HTMLElement} */ (figure.querySelector("[data-chart]"));
    /** @type {ChartSpec} */
    var spec = JSON.parse(/** @type {string} */ (element.dataset.chart));
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
      var points = /** @type {uPlot.Series.Points} */ (series.points);
      if (points.show) points.size = 14;
      else if (series.paths === undefined) series.width = 3;
    });
    if (zoom !== undefined) {
      var range = zoom;
      options.scales.x.range = function () { return [range.min, range.max]; };
    }
    // read before uPlot takes the options over
    var entries = options.series.slice(1).map(function (series, index) {
      // a bar's stroke is the background, and an area's fill may be paler than its line
      var own = /** @type {ChartSeriesSpec} */ (spec.series[index]);
      var color = /** @type {string} */ (own.kind === "bar" ? series.fill : series.stroke);
      return { name: own.name, color: color };
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
      canvas.toBlob(function (blob) { download(/** @type {Blob} */ (blob), name); });
    });
    new uPlot(options, chartData(spec), plot);
  }
  /**
   * @param {HTMLCanvasElement} plotCanvas @param {string} title
   * @param {{name: string, color: string}[]} entries @param {string} ink
   * @param {number} titleHeight
   */
  function composePng(plotCanvas, title, entries, ink, titleHeight) {
    var canvas = document.createElement("canvas");
    canvas.width = PNG_WIDTH;
    canvas.height = PNG_HEIGHT;
    var context = /** @type {CanvasRenderingContext2D} */ (canvas.getContext("2d"));
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
    var widths = entries.map(function (entry) {
      return 36 + context.measureText(entry.name).width;
    });
    var gap = 40;
    var total = widths.reduce(function (sum, width) { return sum + width; }, 0);
    var x = Math.max(0, (PNG_WIDTH - total - gap * (entries.length - 1)) / 2);
    var y = PNG_HEIGHT - PNG_LEGEND_HEIGHT / 2;
    entries.forEach(function (entry, index) {
      context.fillStyle = entry.color;
      context.fillRect(x, y - 12, 24, 24);
      context.fillStyle = ink;
      context.fillText(entry.name, x + 36, y);
      x += /** @type {number} */ (widths[index]) + gap;
    });
    return canvas;
  }
  /** @param {Blob} blob @param {string} name */
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
  /** @param {uPlot} chart @returns {ChartZoom | undefined} */
  function chartZoom(chart) {
    var xs = chart.data[0];
    var min = /** @type {number} */ (chartScales(chart).x.min);
    var max = /** @type {number} */ (chartScales(chart).x.max);
    if (xs.length === 0) return undefined;
    var first = /** @type {number} */ (xs[0]);
    var last = /** @type {number} */ (xs[xs.length - 1]);
    if (min <= first && max >= last) return undefined;
    // all the data at the axis' bounds, narrower than the data: no zoom either
    var range = rangeFunction(chartScales(chart).x);
    var full = range !== undefined ? range(chart, first, last, "x") : [first, last];
    if (min === full[0] && max === full[1]) return undefined;
    return { min: min, max: max };
  }
  /* a chart's scales: the x and the y, which every chart has, and the second y */
  /** @param {uPlot} chart @returns {ChartScales} */
  function chartScales(chart) {
    return /** @type {ChartScales} */ (chart.scales);
  }
  /** @param {HTMLElement} element */
  function destroyChart(element) {
    var chart = charts.get(element);
    charts.delete(element);
    /** @type {ResizeObserver} */ (element.chartObserver).disconnect();
    if (chart === null || chart === undefined) return;
    var zoom = chartZoom(chart);
    if (zoom !== undefined) chartZooms.set(element.id, zoom);
    chart.destroy();
  }
  /* the charts shown, or waiting for a width, and those swapped out destroyed */
  function syncCharts() {
    charts.forEach(function (chart, element) {
      if (!element.isConnected) destroyChart(element);
    });
    document.querySelectorAll("[data-chart]").forEach(function (element) {
      if (!(element instanceof HTMLElement) || charts.has(element)) return;
      charts.set(element, null);
      var observer = new ResizeObserver(function () {
        var chart = charts.get(element);
        var width = element.clientWidth;
        if (width === 0) return;
        if (chart === null) {
          drawChart(element, chartZooms.get(element.id));
          chartZooms.delete(element.id);
        } else if (chart !== undefined && chart.width !== width) {
          chart.setSize({ width: width, height: element.clientHeight });
        }
      });
      element.chartObserver = observer;
      observer.observe(element);
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
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redrawCharts);
  /* `drawn`: each element drawn, or waiting for a width (null), to its uPlot */
  window.ComposeUI.charts = {sync: syncCharts, redraw: redrawCharts, drawn: charts};
})();
