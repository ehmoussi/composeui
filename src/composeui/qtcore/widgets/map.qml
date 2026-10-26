import QtQuick
import QtLocation
import QtPositioning

Item {
    id: root
    property var points: []
    property bool tiles: true
    property real latitude: 0
    property real longitude: 0
    property alias zoom: map.zoomLevel
    focus: true
    signal viewportMoved(real latitude, real longitude, real zoom)
    signal pointClicked(real latitude, real longitude)

    function moved() {
        // Copy both numbers before changing the properties that bind map.center.
        const movedLatitude = map.center.latitude
        const movedLongitude = map.center.longitude
        latitude = Math.max(-85.05112878, Math.min(85.05112878, movedLatitude))
        longitude = movedLongitude
        viewportMoved(latitude, longitude, map.zoomLevel)
    }

    Keys.onPressed: (event) => {
        if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) zoom = Math.min(19, zoom + 1)
        else if (event.key === Qt.Key_Minus) zoom = Math.max(0, zoom - 1)
        else if (event.key === Qt.Key_Left) map.pan(-40, 0)
        else if (event.key === Qt.Key_Right) map.pan(40, 0)
        else if (event.key === Qt.Key_Up) map.pan(0, -40)
        else if (event.key === Qt.Key_Down) map.pan(0, 40)
        else return
        event.accepted = true
        moved()
    }

    Map {
        id: map
        center: QtPositioning.coordinate(root.latitude, root.longitude)
        anchors.fill: parent
        visible: root.tiles
        copyrightsVisible: root.tiles
        color: "#e5e7eb"
        plugin: tilePlugin
        onSupportedMapTypesChanged: {
            // The custom host is the last map type; never select a provider repository URL.
            if (root.tiles && supportedMapTypes.length)
                activeMapType = supportedMapTypes[supportedMapTypes.length - 1]
        }
        onCenterChanged: overlay.requestPaint()
        onZoomLevelChanged: overlay.requestPaint()
        onMapReadyChanged: overlay.requestPaint()
    }
    Plugin {
        id: tilePlugin
        name: root.tiles ? "osm" : "itemsoverlay"
        PluginParameter { name: "osm.useragent"; value: mapUserAgent }
        PluginParameter { name: "osm.mapping.providersrepository.disabled"; value: true }
        PluginParameter {
            name: "osm.mapping.custom.host"
            value: "https://tile.openstreetmap.org/"
        }
        PluginParameter {
            name: "osm.mapping.custom.mapcopyright"
            value: "© OpenStreetMap contributors"
        }
        PluginParameter { name: "osm.mapping.prefetching_style"; value: "NoPrefetching" }
    }
    Item {
        anchors.fill: parent
        DragHandler {
            target: null
            onTranslationChanged: (delta) => {
                map.pan(-delta.x, -delta.y)
                root.moved()
            }
        }
        WheelHandler {
            target: null
            onWheel: (event) => {
                map.zoomLevel = Math.max(0, Math.min(19, map.zoomLevel + event.angleDelta.y / 120))
                root.moved()
            }
        }
        TapHandler {
            onTapped: (eventPoint) => {
                const position = map.toCoordinate(eventPoint.position, false)
                root.pointClicked(position.latitude, position.longitude)
            }
        }
    }
    Canvas {
        id: overlay
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            ctx.fillStyle = "#2563eb"
            ctx.globalAlpha = 0.55
            ctx.beginPath()
            const world = 256 * Math.pow(2, root.zoom)
            function mercator(latitude) {
                const sine = Math.sin(latitude * Math.PI / 180)
                return 0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)
            }
            const centerY = mercator(root.latitude)
            for (let i = 0; i < root.points.length; ++i) {
                const p = root.points[i]
                let dx = (p[1] - root.longitude) / 360
                dx -= Math.round(dx)
                const pixel = { x: width / 2 + dx * world,
                    y: height / 2 + (mercator(p[0]) - centerY) * world }
                if (pixel.x < -3 || pixel.x > width + 3 || pixel.y < -3 || pixel.y > height + 3) continue
                ctx.moveTo(pixel.x + 3, pixel.y)
                ctx.arc(pixel.x, pixel.y, 3, 0, 2 * Math.PI)
            }
            ctx.fill()
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
    }
    onPointsChanged: overlay.requestPaint()
}
