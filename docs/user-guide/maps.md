# Maps

A `MapView` shows geographic points over a street map that the user pans and zooms, for
example the places of pickups or of measurements. For a plot on numeric axes, use a
[`ChartView`](charts.md).

```python
from composeui.core.view import MainView, MapPoint, MapView, child, define_view


@define_view
class PickupsMainView(MainView):
    app_title = "Pickup locations"
    extension = ".pickups"

    pickups: MapView = child(
        MapView,
        title="Pickup locations",
        points=[
            MapPoint(latitude=40.74, longitude=-73.99),
            MapPoint(latitude=40.72, longitude=-73.97),
        ],
    )
```

## Coordinates, points, and viewport

- **Coordinates.** `MapPoint(latitude=..., longitude=...)` takes degrees, as keyword
  arguments. The longitude goes from -180 to 180. The latitude goes from -85.05112878 to
  85.05112878, the range of a Web Mercator map. A point out of range, or with a coordinate
  that is not finite, raises an error.
- **Points of a dataframe.** With the `dataframe` extra, `points_of(frame, latitude,
  longitude)` from `composeui.core.dataframesource` gives the points of two columns of a
  pandas, Polars, or PyArrow frame. It leaves out the rows that miss a coordinate, or that
  are out of the map's range.
- **Points.** Assign a new `points` list to draw the blue dots again. The view does not
  limit the number of points: the app keeps a large dataset to a size that the map can show.
- **Automatic fit.** `center` and `zoom` are `None` by default. The map then fits the
  points, with 32 pixels of padding on each side. It fits again when the points or the size
  of the map change. Points on both sides of the date line fit together. Without points,
  the map shows the world around latitude 0 and longitude 0. A single point shows at zoom
  12.
- **Your own center or zoom.** Set `center` to a `MapPoint` to fix the center, or set `zoom`
  to fix the zoom. Each one is independent: the other one still fits the points. The zoom
  goes from 0 to 19, the levels of OpenStreetMap. Qt can raise the minimum zoom to fill
  its widget, so a zoom limit or a very small map can stop the points from all fitting.
- **The user's viewport.** After the user pans or zooms, `center` and `zoom` hold the
  user's viewport. New points and a new size then keep it. To fit the points again, set
  both `center` and `zoom` to `None`.
- **Height.** `height` is in pixels, 400 by default.
- **Pan and zoom.** The user drags to pan and turns the mouse wheel to zoom. On a map that
  has the focus, the arrow keys pan, and `+` and `-` zoom.
- **Signals.** `clicked` emits the latitude, then the longitude. `viewport_changed` emits
  no arguments, after a pan or a zoom of the user sets `center` and `zoom`. When code sets
  them, neither signal emits. The automatic fit emits no signal either, and leaves
  `center` and `zoom` at `None`.
- **State.** The study saves `center` and `zoom`, and a saved `None` fits the points again.
  The study does not save `points`, `height`, `tiles`, `user_agent`, or the title. After
  a study opens, build the points again from the model: the automatic fit follows them.

## Tiles and network access

The map draws the streets from the standard raster tiles of OpenStreetMap,
`https://tile.openstreetmap.org/{z}/{x}/{y}.png`. They need no API key, but they need
internet access. Set `tiles=False` to draw only the points, with no tile requests.

Follow the [tile usage policy of OpenStreetMap](https://operations.osmfoundation.org/policies/tiles/):

- **Keep the attribution.** The map shows **© OpenStreetMap contributors**.
- **Identify the app.** `user_agent` is optional. By default, it gives the name and the
  project address of ComposeUI. On Qt, set it to the name of your app and an address to
  contact you. On the web, the browser sends its own identity, and the page's origin as its
  referrer.
- **Keep the HTTP caching.** Neither backend downloads tiles in bulk or ahead of use.
- **Don't count on the public server.** It does not promise to be available, or to accept
  all traffic.

The tile server receives the IP address of the user and the area of the map that it
shows. The points are drawn on the user's machine, and are never sent to the tile server.
ComposeUI has no offline street map yet, and no other tile server.

## What each backend draws

- **Qt** shows the Qt Location QML plugin in a `QQuickWidget`. PySide6 includes the
  plugin: no other mapping package, browser engine, or QWebEngine is needed. One canvas
  draws all the points, not a QML item per point. When you package the app as an
  executable, include `map.qml`, the Qt Location and Qt Positioning QML modules, and the
  location plugins.
- **The web** loads [deck.gl](https://deck.gl/), which ComposeUI serves itself, when the
  page first shows a map. A raster tile layer draws the streets, and a scatterplot layer
  draws the points on the GPU. The browser needs WebGL2. New points build the map again:
  it fits the points, or keeps the viewport of the user.
- **Textual** does not show a `MapView`. The other views of the app still show.

The [Uber pickups example](../../src/examples/uberpickups.py) shows up to 10,000 pickups
for the hour that a slider picks (`uv run python -m examples.uberpickups --backend qt`, or
`web`).
