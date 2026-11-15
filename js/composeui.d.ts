/* The globals of the page's scripts (`src/composeui/webcore/static`), for `make js-check`:
   the libraries the page loads, what its scripts share, the JSON the server gives them,
   and what they keep on elements. */
import type htmxApi from "./htmx";

declare global {
  const htmx: typeof htmxApi;
  /* deck.gl's bundle has no declarations: its classes, unchecked */
  const deck: any;

  interface ComposeUI {
    dispatch(target: EventTarget, type: string): void;
    /* added by `charts.js`; `drawn`: each element drawn, or waiting for a width (null) */
    charts?: { sync(): void; redraw(): void; drawn: Map<HTMLElement, uPlot | null> };
    /* added by `maps.js` */
    maps?: { sync(): void };
  }
  interface Window {
    ComposeUI: ComposeUI;
  }

  /* what the scripts keep on the elements they handle */
  interface HTMLElement {
    chartObserver?: ResizeObserver;
    chartLegend?: HTMLElement;
    mapObserver?: ResizeObserver;
    windowTimer?: number;
    widestValue?: number;
  }
  interface XMLHttpRequest {
    /* the page's number of the request (`page.js`) */
    composeuiNumber?: number;
  }

  /* the events of htmx that the scripts handle: their `detail`, in part */
  interface HtmxRequestDetail {
    elt: HTMLElement;
    xhr: XMLHttpRequest;
    requestConfig: { verb: string };
  }
  interface DocumentEventMap {
    "htmx:configRequest": CustomEvent<{
      elt: HTMLElement;
      parameters: Record<string, unknown>;
      headers: Record<string, string>;
      triggeringEvent: Event;
    }>;
    "htmx:beforeRequest": CustomEvent<HtmxRequestDetail>;
    "htmx:beforeSend": CustomEvent<HtmxRequestDetail>;
    "htmx:afterRequest": CustomEvent<HtmxRequestDetail>;
    "htmx:beforeSwap": CustomEvent<HtmxRequestDetail & { serverResponse: string }>;
    "htmx:oobBeforeSwap": CustomEvent<{ fragment: Element }>;
    "htmx:afterSettle": CustomEvent<{ elt: HTMLElement }>;
    "htmx:load": CustomEvent<{ elt: HTMLElement }>;
  }

  /* a chart's JSON (`WebChartRenderer._spec`) */
  interface ChartAxisSpec {
    label: string;
    unit: string;
    log: boolean;
  }
  interface ChartSeriesSpec {
    name: string;
    kind: "line" | "scatter" | "bar";
    color: string | null;
    fill: boolean;
    fill_color: string | null;
    step: boolean;
    whole: boolean;
    /* a bar's, in its category's group */
    offset: number;
    width: number;
  }
  interface ChartLineSpec {
    value: number;
    label: string;
    vertical: boolean;
    color: string | null;
    style: "solid" | "dashed" | "dotted" | "dash_dot";
  }
  interface ChartSpec {
    title: string;
    x: ChartAxisSpec;
    y: ChartAxisSpec;
    series: ChartSeriesSpec[];
    lines: ChartLineSpec[];
    /* uPlot's columns, or each series' own x and y, joined in the browser */
    data?: uPlot.AlignedData;
    pairs?: uPlot.AlignedData[];
    categories?: string[];
  }
  /* the x range the user zoomed into */
  interface ChartZoom {
    min: number;
    max: number;
  }

  /* a map's JSON (`WebMapRenderer.to_html`) */
  interface MapSpec {
    latitude: number;
    longitude: number;
    zoom: number | null;
    span: [number, number];
    points: [number, number][];
    tiles: boolean;
    enabled: boolean;
  }
  interface MapState {
    latitude: number;
    longitude: number;
    zoom: number;
  }
}
