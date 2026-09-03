import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "novique.room"
  ipcTarget: "novique.room"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var room: null
  property bool openedFromHotkey: false

  readonly property var barIdentity: hostWidget || root
  readonly property var reading: room ? room.reading : ({})
  readonly property bool available: room ? room.available : false
  readonly property bool stale: room ? room.stale : true

  function open() {
    openedFromHotkey = false
    root.controller.show()
  }

  function openFromHotkey() {
    openedFromHotkey = true
    root.controller.show()
  }

  function close() {
    root.controller.hide()
  }

  function toggle() {
    if (root.opened) root.close()
    else root.openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function line(label, value) {
    return label + "  " + value
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(280))
    contentHeight: panel.fittedContentHeight(body.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: body
        width: parent.width
        spacing: Style.space(10)

        Text {
          width: parent.width
          text: room && room.panelTitle ? room.panelTitle : "Room"
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
          font.bold: true
        }

        Text {
          width: parent.width
          visible: root.available && reading.temperature_f !== undefined && reading.temperature_f !== null
          text: {
            if (!root.available || reading.temperature_f === undefined || reading.temperature_f === null)
              return ""
            return Number(reading.temperature_f).toFixed(1) + "°F  /  " + Number(reading.temperature_c).toFixed(1) + "°C"
          }
          color: root.stale ? Color.muted : Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.title
        }

        Text {
          width: parent.width
          visible: root.available && reading.humidity !== undefined && reading.humidity !== null
          text: root.available && reading.humidity !== undefined && reading.humidity !== null
            ? "Humidity  " + reading.humidity + "%"
            : ""
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Text {
          width: parent.width
          visible: root.available && Model.trendCaption(reading).length > 0
          text: Model.trendCaption(reading)
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          visible: root.available && Model.trendSpark(reading).length > 0
          text: Model.trendSpark(reading)
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          visible: root.available && reading.co2 !== undefined && reading.co2 !== null
          text: root.available && reading.co2 !== undefined && reading.co2 !== null
            ? "CO₂  " + reading.co2 + " ppm"
            : ""
          color: Color.foreground
          font.family: Style.font.family
          font.pixelSize: Style.font.body
        }

        Text {
          width: parent.width
          visible: root.available && reading.battery !== undefined && reading.battery !== null
          text: root.available && reading.battery !== undefined && reading.battery !== null
            ? "Battery  " + reading.battery + "%"
            : ""
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          visible: room && room.lowBattery === true
          text: "Battery low"
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          visible: root.available && reading.rssi !== undefined && reading.rssi !== null
          text: root.available && reading.rssi !== undefined && reading.rssi !== null
            ? "RSSI  " + reading.rssi + " dBm"
            : ""
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          visible: reading.last_seen !== undefined && reading.last_seen !== null && reading.last_seen !== ""
          text: {
            if (!reading.last_seen) return ""
            var nowMs = room && room.nowMs ? room.nowMs : Date.now()
            return "Last seen  " + Model.formatLastSeen(reading.last_seen, nowMs)
          }
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }

        Text {
          width: parent.width
          visible: reading.address !== undefined && reading.address !== null && reading.address !== ""
          text: reading.address ? reading.address : ""
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }

        Text {
          width: parent.width
          visible: room && room.statusMessage && room.statusMessage.length > 0
          text: room && room.statusMessage ? room.statusMessage : ""
          color: Color.urgent
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          wrapMode: Text.Wrap
        }
      }
    }
  }
}
