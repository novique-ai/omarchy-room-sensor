const test = require("node:test")
const assert = require("node:assert/strict")
const { load, deepEqual } = require("./load")

const Model = load("Model.js")
const NOW = Date.parse("2026-08-31T19:58:29-05:00")

const SAMPLE = JSON.stringify({
  temperature_f: 73.4,
  temperature_c: 23.0,
  humidity: 47,
  battery: 100,
  rssi: -59,
  last_seen: "2026-08-31T19:58:29-05:00",
  stale: false,
  address: "C8:92:04:06:1C:2C"
})

test("parses a live room-sensor status file", () => {
  const reading = Model.parseStatus(SAMPLE, NOW, 120)
  assert.equal(reading.available, true)
  assert.equal(reading.stale, false)
  assert.equal(reading.temperature_f, 73.4)
  assert.equal(reading.temperature_c, 23)
  assert.equal(reading.humidity, 47)
  assert.equal(reading.battery, 100)
  assert.equal(reading.rssi, -59)
  assert.equal(reading.address, "C8:92:04:06:1C:2C")
})

test("marks stale after the window", () => {
  const reading = Model.parseStatus(SAMPLE, NOW + 121000, 120)
  assert.equal(reading.available, true)
  assert.equal(reading.stale, true)
})

test("rejects junk and empty payloads", () => {
  deepEqual(Model.parseStatus("", NOW, 120).available, false)
  deepEqual(Model.parseStatus("{", NOW, 120).available, false)
  deepEqual(Model.parseStatus("{}", NOW, 120).available, false)
})

test("bar label uses F by default and C when asked", () => {
  const reading = Model.parseStatus(SAMPLE, NOW, 120)
  assert.equal(Model.barLabel(reading, "F"), "73.4°  47%")
  assert.equal(Model.barLabel(reading, "C"), "23.0°  47%")
  assert.equal(Model.barLabel(Model.emptyReading(), "F"), "—°")
})

test("tooltip carries the full reading", () => {
  const reading = Model.parseStatus(SAMPLE, NOW, 120)
  const tip = Model.tooltip(reading, "F")
  assert.match(tip, /73\.4°F/)
  assert.match(tip, /23\.0°C/)
  assert.match(tip, /Humidity  47%/)
  assert.match(tip, /Battery  100%/)
  assert.match(tip, /RSSI  -59 dBm/)
})

test("keeps reader_state when temperatures are missing", () => {
  const reading = Model.parseStatus(JSON.stringify({
    reader_state: "unbound"
  }), NOW, 120)
  assert.equal(reading.available, false)
  assert.equal(reading.reader_state, "unbound")
})

test("parses model, co2, and reader_state", () => {
  const reading = Model.parseStatus(JSON.stringify({
    temperature_f: 73.4,
    temperature_c: 23.0,
    humidity: 47,
    battery: 12,
    rssi: -59,
    last_seen: "2026-08-31T19:58:29-05:00",
    address: "C8:92:04:06:1C:2C",
    model: "Meter Pro CO2",
    co2: 842,
    reader_state: "ok"
  }), NOW, 120)
  assert.equal(reading.model, "Meter Pro CO2")
  assert.equal(reading.co2, 842)
  assert.equal(reading.reader_state, "ok")
  assert.equal(reading.battery, 12)
})

test("bar label can hide humidity", () => {
  const reading = Model.parseStatus(SAMPLE, NOW, 120)
  assert.equal(Model.barLabel(reading, "F"), "73.4°  47%")
  assert.equal(Model.barLabel(reading, "F", false), "73.4°")
})

test("formatLastSeen is relative", () => {
  const text = Model.formatLastSeen("2026-08-31T19:58:29-05:00", NOW + 12000)
  assert.match(text, /12s ago/)
})

test("panelTitle prefers label then model", () => {
  const reading = Model.parseStatus(JSON.stringify({
    temperature_f: 73.4,
    temperature_c: 23.0,
    humidity: 47,
    last_seen: "2026-08-31T19:58:29-05:00",
    model: "Meter Plus"
  }), NOW, 120)
  assert.equal(Model.panelTitle(reading, "Office"), "Office")
  assert.equal(Model.panelTitle(reading, "  "), "Meter Plus")
  assert.equal(Model.panelTitle(Model.emptyReading(), ""), "Room")
})

test("statusMessage covers empty, bluetooth, unbound, stale", () => {
  assert.equal(Model.statusMessage(Model.emptyReading(), true), "Start room-sensor.service")
  const bt = Model.emptyReading()
  bt.reader_state = "no_adapter"
  assert.equal(Model.statusMessage(bt, true), "Bluetooth is off")
  const unbound = Model.emptyReading()
  unbound.reader_state = "unbound"
  assert.equal(Model.statusMessage(unbound, true), "No meter bound — run room-temp --discover")
  const live = Model.parseStatus(SAMPLE, NOW, 120)
  assert.equal(Model.statusMessage(live, false), "")
  assert.equal(Model.statusMessage(live, true), "Stale — waiting for the next advertisement")
})

test("lowBattery at 15 percent", () => {
  const low = Model.parseStatus(JSON.stringify({
    temperature_f: 73.4,
    temperature_c: 23.0,
    humidity: 47,
    battery: 15,
    last_seen: "2026-08-31T19:58:29-05:00"
  }), NOW, 120)
  assert.equal(Model.lowBattery(low), true)
  const ok = Model.parseStatus(SAMPLE, NOW, 120)
  assert.equal(Model.lowBattery(ok), false)
})

test("null co2 battery rssi stay null", () => {
  const reading = Model.parseStatus(JSON.stringify({
    temperature_f: 73.4,
    temperature_c: 23.0,
    humidity: 47,
    battery: null,
    rssi: null,
    co2: null,
    last_seen: "2026-08-31T19:58:29-05:00"
  }), NOW, 120)
  assert.equal(reading.available, true)
  assert.equal(reading.co2, null)
  assert.equal(reading.battery, null)
  assert.equal(reading.rssi, null)
  assert.equal(Model.lowBattery(reading), false)
})
