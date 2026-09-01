import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// Headless owner of the latest room-sensor status.json. The bar pill and
// the popup both read from here so two monitors cannot drift.
Item {
  id: root

  visible: false
  width: 0
  height: 0

  property var shell: null
  property var manifest: null
  property var settings: ({})

  readonly property string pluginId: manifest && manifest.id
    ? String(manifest.id) : "novique.room"

  readonly property string statusPath: {
    var home = Quickshell.env("HOME") || ""
    var state = Quickshell.env("XDG_STATE_HOME")
    if (state && String(state).length > 0)
      return String(state) + "/room-sensor/status.json"
    return home + "/.local/state/room-sensor/status.json"
  }

  readonly property int staleSeconds: {
    var n = Number(settings && settings.staleSeconds)
    return isFinite(n) && n > 0 ? n : 120
  }

  property var reading: Model.emptyReading()
  property int nowMs: Date.now()
  property int revision: 0

  readonly property bool available: !!reading && reading.available === true
  readonly property bool stale: Model.isStale(reading, nowMs, staleSeconds)
  readonly property string unit: {
    var u = settings && settings.unit ? String(settings.unit) : "F"
    return u.toUpperCase() === "C" ? "C" : "F"
  }
  readonly property string label: Model.barLabel(reading, unit)
  readonly property string tooltip: Model.tooltip(reading, unit)

  function applyText(text) {
    reading = Model.parseStatus(text, nowMs, staleSeconds)
    revision++
  }

  function tick() {
    nowMs = Date.now()
    if (reading && reading.available)
      reading = Model.parseStatus(JSON.stringify({
        temperature_f: reading.temperature_f,
        temperature_c: reading.temperature_c,
        humidity: reading.humidity,
        battery: reading.battery,
        rssi: reading.rssi,
        last_seen: reading.last_seen,
        address: reading.address
      }), nowMs, staleSeconds)
  }

  FileView {
    id: file
    path: root.statusPath
    watchChanges: true
    printErrors: false
    onLoaded: root.applyText(text())
    onFileChanged: reload()
    onLoadFailed: root.applyText("")
  }

  Timer {
    interval: 15000
    running: true
    repeat: true
    onTriggered: root.tick()
  }
}
