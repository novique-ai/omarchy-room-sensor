.pragma library

// Parse the room-sensor status.json and format the bar pill.

function emptyReading() {
  return {
    temperature_f: null,
    temperature_c: null,
    humidity: null,
    battery: null,
    rssi: null,
    last_seen: null,
    stale: true,
    address: "",
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

  var tf = Number(raw.temperature_f)
  var tc = Number(raw.temperature_c)
  var hum = Number(raw.humidity)
  if (!isFinite(tf) || !isFinite(tc) || !isFinite(hum)) return reading

  reading.temperature_f = Math.round(tf * 10) / 10
  reading.temperature_c = Math.round(tc * 10) / 10
  reading.humidity = Math.round(hum)
  reading.battery = isFinite(Number(raw.battery)) ? Math.round(Number(raw.battery)) : null
  reading.rssi = isFinite(Number(raw.rssi)) ? Math.round(Number(raw.rssi)) : null
  reading.last_seen = raw.last_seen ? String(raw.last_seen) : null
  reading.address = raw.address ? String(raw.address) : ""
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

function barLabel(reading, unit) {
  if (!reading || !reading.available) return "—°"
  var temp = formatTemp(reading, unit)
  if (reading.humidity === null) return temp
  return temp + "  " + reading.humidity + "%"
}

function tooltip(reading, unit) {
  if (!reading || !reading.available) return "Room sensor — no reading yet"
  var lines = [
    "Room  " + formatTemp(reading, "F") + "F / " + formatTemp(reading, "C") + "C",
    "Humidity  " + reading.humidity + "%"
  ]
  if (reading.battery !== null) lines.push("Battery  " + reading.battery + "%")
  if (reading.rssi !== null) lines.push("RSSI  " + reading.rssi + " dBm")
  if (reading.last_seen) lines.push("Last seen  " + reading.last_seen)
  if (reading.stale) lines.push("Stale")
  return lines.join("\n")
}
