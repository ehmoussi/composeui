# Maps

A `MapView` shows geographic points over an interactive street map. Use it for pickup
locations or other measurements with latitude and longitude. Use `ChartView` for plots
with numeric axes.

```python
from composeui.core.view import MainView, MapPoint, MapView, child, define_view


@define_view
class PickupsMainView(MainView):
    app_title = "Pickup locations"
    extension = ".pickups"

    pickups: MapView = child(
        MapView,
        title="Pickup locations",
        center=MapPoint(40.73, -73.98),
        zoom=11,
        points=[MapPoint(40.74, -73.99), MapPoint(40.72, -73.97)],
        user_agent="MyPickupsApp/1.0 (+https://example.org)",
    )
```

## Coordinates, points, and viewport

- **Coordinates.** `MapPoint(latitude, longitude)` takes degrees, latitude first.
  Longitude must be between -180 and 180. Latitude must be between -85.05112878 and
  85.05112878, the range of a Web Mercator map. Non-finite coordinates are refused.
- **Points.** Assign a new `points` list to redraw the blue dots. This keeps the user's
  center and zoom. The view does not limit the list; applications must bound large datasets.
- **Viewport.** `center` is a `MapPoint`. `zoom` takes OpenStreetMap zoom levels from 0
  to 19. Qt can raise the minimum zoom to fit the widget. `height` is in pixels, 400 by default.
- **Interaction.** Drag to pan and use the mouse wheel to zoom. Focus the map and use
  arrow keys to pan, or `+` and `-` to zoom.
- **Signals.** `clicked` emits latitude then longitude. `viewport_changed` emits no
  arguments after a user action updates `center` and `zoom`. Programmatic changes do not
  emit either signal.
- **State.** The study saves `center` and `zoom`. It does not save `points`, `height`,
  `tiles`, `user_agent`, or the title. Rebuild points from the model after loading a study.

## Tiles and network access

The first implementation uses OpenStreetMap's standard raster tiles at
`https://tile.openstreetmap.org/{z}/{x}/{y}.png`. No API key is needed. Tiles need internet
access. Set `tiles=False` to draw only the points, without tile requests.

Follow the [OpenStreetMap tile usage policy](https://operations.osmfoundation.org/policies/tiles/):

- Keep the visible **© OpenStreetMap contributors** attribution.
- Set `user_agent` to identify your native application and provide a contact URL.
  On the web, the browser identifies itself and sends the page's origin as its referrer.
- Respect HTTP caching. Neither backend offers bulk downloading or offline prefetching.
- Do not rely on the public tile server for guaranteed availability or unrestricted traffic.

The tile provider receives the client's IP address and the requested map area. Pickup
coordinates are drawn locally, not uploaded to the provider. An offline street map or
another tile provider is not supported yet.

## What each backend draws

- **Qt** embeds the Qt Location QML plugin in `QQuickWidget`. PySide6 includes the plugin;
  no extra mapping dependency, browser engine, or QWebEngine is needed. One canvas draws
  the points rather than one QML item per point. Include `map.qml`, the Qt Location and
  Qt Positioning QML modules, and the location plugins when packaging an executable.
- **The web** loads the bundled deck.gl 9.2.6 script when the page first shows a map.
  A raster tile layer supplies streets, and a GPU-rendered scatterplot draws points.
  The browser needs WebGL2. Changing points rebuilds the map at the saved viewport.
- **Textual** does not render `MapView`. Other views remain available.

The [Uber pickups example](../../src/examples/uberpickups.py) shows up to 10,000 sampled
pickup locations. Its hourly chart counts all rows. Run it with
`uv run python -m examples.uberpickups --backend qt`, or `--backend web`.
