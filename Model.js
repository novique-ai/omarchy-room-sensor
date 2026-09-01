.pragma library

// Parse the room-sensor status.json and format the bar pill.

function emptyReading() {
  return {
    temperature_f: null,
    temperature_c: null,
    humidity: null,
    battery: null,
    rssi: null,
    co2: null,
    last_seen: null,
    stale: true,
    address: "",
    model: "",
    reader_state: "",
    available: false
  }
}

function parseIsoMs(value) {
  if (!value) return null
  var ms = Date.parse(String(value))
  return isNaN(ms) ? null : ms
}

function isStale(reading, nowMs, staleSeconds) {
  if (!reading || !reading.last_seen) return true
  var seen = parseIsoMs(reading.last_seen)
  if (seen === null) return true
  var windowMs = Math.max(1, Number(staleSeconds) || 120) * 1000
  return (Number(nowMs) - seen) > windowMs
}

function parseStatus(text, nowMs, staleSeconds) {
  var reading = emptyReading()
  if (!text || String(text).trim() === "") return reading
  var raw
  try {
    raw = JSON.parse(text)
  } catch (e) {
    return reading
  }
  if (!raw || typeof raw !== "object") return reading

  reading.model = raw.model ? String(raw.model) : ""
  reading.reader_state = raw.reader_state ? String(raw.reader_state) : ""
  reading.address = raw.address ? String(raw.address) : ""

  var tf = Number(raw.temperature_f)
  var tc = Number(raw.temperature_c)
  var hum = Number(raw.humidity)
  if (!isFinite(tf) || !isFinite(tc) || !isFinite(hum)) return reading

  reading.temperature_f = Math.round(tf * 10) / 10
  reading.temperature_c = Math.round(tc * 10) / 10
  reading.humidity = Math.round(hum)
  reading.battery = isFinite(Number(raw.battery)) ? Math.round(Number(raw.battery)) : null
  reading.rssi = isFinite(Number(raw.rssi)) ? Math.round(Number(raw.rssi)) : null
  reading.co2 = isFinite(Number(raw.co2)) ? Math.round(Number(raw.co2)) : null
  reading.last_seen = raw.last_seen ? String(raw.last_seen) : null
  reading.available = true
  reading.stale = isStale(reading, nowMs, staleSeconds)
  return reading
}

function formatTemp(reading, unit) {
  if (!reading || !reading.available) return "—"
  var useC = String(unit || "F").toUpperCase() === "C"
  var value = useC ? reading.temperature_c : reading.temperature_f
  if (value === null || !isFinite(value)) return "—"
  return value.toFixed(1) + "°"
}

function barLabel(reading, unit, showHumidity) {
  if (!reading || !reading.available) return "—°"
  var temp = formatTemp(reading, unit)
  var show = showHumidity !== false
  if (!show || reading.humidity === null) return temp
  return temp + "  " + reading.humidity + "%"
}

function formatRelative(seenMs, nowMs) {
  var seconds = Math.max(0, Math.floor((Number(nowMs) - Number(seenMs)) / 1000))
  if (seconds < 60) return seconds + "s ago"
  if (seconds < 3600) return Math.floor(seconds / 60) + "m ago"
  if (seconds < 86400) return Math.floor(seconds / 3600) + "h ago"
  return Math.floor(seconds / 86400) + "d ago"
}

function pad2(n) {
  return n < 10 ? "0" + n : String(n)
}

function formatClock(ms) {
  var d = new Date(ms)
  var h = d.getHours()
  var am = h >= 12 ? "PM" : "AM"
  var h12 = h % 12
  if (h12 === 0) h12 = 12
  return h12 + ":" + pad2(d.getMinutes()) + " " + am
}

function formatLastSeen(iso, nowMs) {
  var seen = parseIsoMs(iso)
  if (seen === null) return ""
  return formatRelative(seen, nowMs) + "  " + formatClock(seen)
}

function panelTitle(reading, label) {
  var custom = label ? String(label).trim() : ""
  if (custom) return custom
  if (reading && reading.model) return reading.model
  return "Room"
}

function statusMessage(reading, stale) {
  if (!reading || !reading.available) {
    if (reading && reading.reader_state === "no_adapter") return "Bluetooth is off"
    if (reading && reading.reader_state === "unbound") return "No meter bound — run room-temp --discover"
    return "Start room-sensor.service"
  }
  if (stale) return "Stale — waiting for the next advertisement"
  return ""
}

function lowBattery(reading) {
  if (!reading || reading.battery === null || reading.battery === undefined) return false
  return Number(reading.battery) <= 15
}

function tooltip(reading, unit) {
  if (!reading || !reading.available) return "Room sensor — no reading yet"
  var lines = [
    "Room  " + formatTemp(reading, "F") + "F / " + formatTemp(reading, "C") + "C",
    "Humidity  " + reading.humidity + "%"
  ]
  if (reading.battery !== null) lines.push("Battery  " + reading.battery + "%")
  if (reading.rssi !== null) lines.push("RSSI  " + reading.rssi + " dBm")
  if (reading.co2 !== null && reading.co2 !== undefined) lines.push("CO2  " + reading.co2 + " ppm")
  if (reading.last_seen) lines.push("Last seen  " + formatLastSeen(reading.last_seen, Date.now()))
  if (reading.stale) lines.push("Stale")
  return lines.join("\n")
}
