/* maps (see `WebMapRenderer`): deck.gl draws each `[data-map]` element from its JSON.
   The page loads this script and deck.gl only once it shows its first map, from a swap
   too (see `page.js`), which then calls `sync` at each change of the page. Tile
   fetches identify the page by its origin, never its path, and never carry credentials
   to the tile provider. */
(function () {
  /** @type {Map<HTMLElement, any>} each element drawn to its deck.gl `Deck` */
  var maps = new Map();
  /**
   * @param {HTMLElement} element @param {string} event
   * @param {{latitude: number, longitude: number, zoom?: number}} state
   */
  function mapPost(element, event, state) {
    state = Object.assign({}, state, {
      latitude: Math.max(-85.05112878, Math.min(85.05112878, state.latitude)),
      longitude: ((state.longitude + 180) % 360 + 360) % 360 - 180
    });
    htmx.ajax("post", "/_composeui/widget/" + element.dataset.widget, {
      source: element,
      values: Object.assign({event: event}, state),
      swap: "none"
    });
  }
  /** @param {HTMLElement} element @param {[number, number]} span */
  function fittedMapZoom(element, span) {
    if (span[0] === 0 && span[1] === 0) return 12;
    /** @type {number[]} */
    var scales = [];
    [element.clientWidth, element.clientHeight].forEach(function (size, index) {
      var extent = /** @type {number} */ (span[index]);
      if (extent > 0) scales.push(Math.max(1, size - 64) / (256 * extent));
    });
    return Math.max(0, Math.min(19, Math.log2(Math.min.apply(null, scales))));
  }
  /** @param {HTMLElement} element */
  function drawMap(element) {
    element.setAttribute("aria-busy", "true");
    /** @type {MapSpec} */
    var spec = JSON.parse(/** @type {string} */ (element.dataset.map));
    var autoFit = spec.zoom === null;
    /** @type {MapState} */
    var state = {
      latitude: spec.latitude, longitude: spec.longitude,
      zoom: (spec.zoom === null ? fittedMapZoom(element, spec.span) : spec.zoom) - 1
    };
    var layers = [];
    if (spec.tiles) {
      layers.push(new deck.TileLayer({
        id: "streets", data: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        tileSize: 256, minZoom: 0, maxZoom: 19,
        maxCacheSize: 128,
        onViewportLoad: function () { element.setAttribute("aria-busy", "false"); },
        /** @param {{url: string, signal: AbortSignal}} tile */
        getTileData: function (tile) {
          return fetch(tile.url, {
            signal: tile.signal, credentials: "omit", referrerPolicy: "origin"
          })
            .then(function (response) {
              if (!response.ok) throw new Error("Map tiles unavailable");
              return response.blob();
            }).then(function (blob) { return createImageBitmap(blob); });
        },
        /** @param {any} props */
        renderSubLayers: function (props) {
          var bounds = props.tile.boundingBox;
          return new deck.BitmapLayer(props, {
            data: null, image: props.data,
            bounds: [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]]
          });
        }
      }));
    }
    layers.push(new deck.ScatterplotLayer({
      id: "pickups", data: spec.points,
      getPosition: function (/** @type {[number, number]} */ point) { return point; },
      getRadius: 3, radiusUnits: "pixels", getFillColor: [37, 99, 235, 140]
    }));
    /** @type {number | undefined} */
    var timer;
    var map = new deck.Deck({
      parent: element, width: "100%", height: "100%",
      initialViewState: Object.assign({minZoom: -1, maxZoom: 18}, state),
      controller: spec.enabled ? {dragRotate: false, touchRotate: false, keyboard: false} : false,
      layers: layers,
      onAfterRender: function () {
        if (!spec.tiles) element.setAttribute("aria-busy", "false");
      },
      /** @param {{viewState: MapState, interactionState?: Record<string, boolean>}} event */
      onViewStateChange: function (event) {
        state = event.viewState;
        var interaction = event.interactionState || {};
        if (!interaction.isDragging && !interaction.isPanning && !interaction.isZooming &&
            !interaction.isRotating) return;
        autoFit = false;
        clearTimeout(timer);
        timer = setTimeout(function () {
          if (!element.isConnected) return;
          mapPost(element, "viewport", {
            latitude: state.latitude, longitude: state.longitude, zoom: state.zoom + 1
          });
        }, 150);
      },
      /** @param {{coordinate?: [number, number]}} info */
      onClick: function (info) {
        if (spec.enabled && info.coordinate) mapPost(element, "click", {
          longitude: info.coordinate[0], latitude: info.coordinate[1]
        });
      }
    });
    var observer = new ResizeObserver(function () {
      if (!autoFit || element.clientWidth === 0 || element.clientHeight === 0) return;
      state.zoom = fittedMapZoom(element, spec.span) - 1;
      map.setProps({initialViewState: Object.assign({minZoom: -1, maxZoom: 18}, state)});
    });
    element.mapObserver = observer;
    observer.observe(element);
    element.addEventListener("keydown", function (event) {
      if (!spec.enabled) return;
      var next = Object.assign({}, state);
      var step = 360 / Math.pow(2, state.zoom + 4);
      if (event.key === "+" || event.key === "=") next.zoom = Math.min(18, state.zoom + 1);
      else if (event.key === "-") next.zoom = Math.max(-1, state.zoom - 1);
      else if (event.key === "ArrowLeft") next.longitude -= step;
      else if (event.key === "ArrowRight") next.longitude += step;
      else if (event.key === "ArrowUp") next.latitude += step;
      else if (event.key === "ArrowDown") next.latitude -= step;
      else return;
      autoFit = false;
      event.preventDefault();
      next.latitude = Math.max(-85.05112878, Math.min(85.05112878, next.latitude));
      next.longitude = ((next.longitude + 180) % 360 + 360) % 360 - 180;
      state = next;
      map.setProps({initialViewState: Object.assign({minZoom: -1, maxZoom: 18}, next)});
      mapPost(element, "viewport", {
        latitude: next.latitude, longitude: next.longitude, zoom: next.zoom + 1
      });
    });
    return map;
  }
  /* the maps shown, and those swapped out finalized */
  function syncMaps() {
    maps.forEach(function (map, element) {
      if (!element.isConnected) {
        /** @type {ResizeObserver} */ (element.mapObserver).disconnect();
        map.finalize();
        maps.delete(element);
      }
    });
    document.querySelectorAll("[data-map]").forEach(function (element) {
      if (!(element instanceof HTMLElement)) return;
      if (!maps.has(element) && element.clientWidth > 0) maps.set(element, drawMap(element));
    });
  }
  window.ComposeUI.maps = {sync: syncMaps};
})();
