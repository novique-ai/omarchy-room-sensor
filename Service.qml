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
  readonly property bool showHumidity: {
    if (!settings || settings.showHumidity === undefined || settings.showHumidity === null)
      return true
    return settings.showHumidity !== false && settings.showHumidity !== "false"
  }
  readonly property string label: Model.barLabel(reading, unit, showHumidity)
  readonly property string tooltip: Model.tooltip(reading, unit)
  readonly property string panelTitle: Model.panelTitle(reading, settings && settings.label)
  readonly property string statusMessage: Model.statusMessage(reading, stale)
  readonly property bool lowBattery: Model.lowBattery(reading)

  function applyText(text) {
    reading = Model.parseStatus(text, nowMs, staleSeconds)
    revision++
  }

  function tick() {
    nowMs = Date.now()
    if (reading && reading.available) {
      var payload = {
        temperature_f: reading.temperature_f,
        temperature_c: reading.temperature_c,
        humidity: reading.humidity,
        last_seen: reading.last_seen,
        address: reading.address,
        model: reading.model,
        reader_state: reading.reader_state
      }
      if (reading.battery !== null && reading.battery !== undefined)
        payload.battery = reading.battery
      if (reading.rssi !== null && reading.rssi !== undefined)
        payload.rssi = reading.rssi
      if (reading.co2 !== null && reading.co2 !== undefined)
        payload.co2 = reading.co2
      reading = Model.parseStatus(JSON.stringify(payload), nowMs, staleSeconds)
    }
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
