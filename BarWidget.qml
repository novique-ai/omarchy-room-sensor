import QtQuick
import qs.Commons
import qs.Ui

// Compact temperature + humidity pill for the Omarchy bar.
BarWidget {
  id: root
  moduleName: "novique.room"

  readonly property var room: bar && bar.shell ? bar.shell.serviceFor("novique.room") : null
  readonly property color defaultForeground: bar ? bar.barForeground : Color.foreground
  readonly property string displayText: room ? room.label : "—°"
  readonly property bool stale: room ? room.stale : true

  function syncService() {
    if (root.room && "settings" in root.room) root.room.settings = root.settings
  }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
    if ("hostWidget" in target) target.hostWidget = root
    if ("room" in target) target.room = root.room
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false

  function open() {
    if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey()
  }

  function close() {
    if (panelLoader.item && panelLoader.item.close) panelLoader.item.close()
  }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false

  function closeForPopoutSwitch() {
    if (panelLoader.item) panelLoader.item.closeForPopoutSwitch()
  }

  readonly property real openPanelIndicatorWidth: button.labelWidth

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  onSettingsChanged: { injectPanel(); syncService() }
  onRoomChanged: { injectPanel(); syncService() }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.displayText
    dimmed: root.stale
    tooltipText: ""
    horizontalMargin: 8.75
    verticalPadding: 8.75
    foreground: root.stale ? Color.muted : root.defaultForeground

    onPressed: function(b) {
      if (b === Qt.RightButton && root.bar)
        root.bar.run("omarchy-notification-send \"$(room-temp 2>/dev/null || echo 'Room sensor unavailable')\"")
      else
        root.togglePanel()
    }
  }
}
