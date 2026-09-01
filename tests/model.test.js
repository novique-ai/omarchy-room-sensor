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
