#!/usr/bin/env python3
"""Unit tests against captured and constructed SwitchBot T/H advertisements."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import room_sensor as rs

FD3D = "0000fd3d-0000-1000-8000-00805f9b34fb"
CAPTURED_SERVICE = "6900e40397af"
CAPTURED_MFR = "c89204061c2c2e030397af"
CAPTURED_ADDR = "C8:92:04:06:1C:2C"
OTHER_ADDR = "AA:BB:CC:DD:EE:FF"


def decode(service_hex: str, mfr_hex: str, address: str = CAPTURED_ADDR, rssi: int = -65):
    return rs.decode_advertisement(
        address=address,
        rssi=rssi,
        service_data={FD3D: bytes.fromhex(service_hex)},
        manufacturer_data={0x0969: bytes.fromhex(mfr_hex)},
    )


class DecodeTests(unittest.TestCase):
    def test_captured_meter_plus_packet(self):
        reading = decode(CAPTURED_SERVICE, CAPTURED_MFR)
        self.assertIsNotNone(reading)
        self.assertEqual(reading["address"], CAPTURED_ADDR)
        self.assertEqual(reading["model"], "Meter Plus")
        self.assertEqual(reading["temperature_c"], 23.3)
        self.assertEqual(reading["temperature_f"], 73.9)
        self.assertEqual(reading["humidity"], 47)
        self.assertEqual(reading["battery"], 100)
        self.assertEqual(reading["rssi"], -65)
        self.assertTrue(reading["fahrenheit_display"])
        self.assertNotIn("co2", reading)
        self.assertEqual(reading["reader_state"], "ok")

    def test_meter_type_t(self):
        reading = decode("5400e40397af", CAPTURED_MFR)
        self.assertIsNotNone(reading)
        self.assertEqual(reading["model"], "Meter")
        self.assertEqual(reading["temperature_c"], 23.3)

    def test_outdoor_type_w(self):
        reading = decode("7700e4", CAPTURED_MFR)
        self.assertIsNotNone(reading)
        self.assertEqual(reading["model"], "Indoor/Outdoor Meter")
        self.assertEqual(reading["humidity"], 47)

    def test_meter_pro_co2(self):
        mfr = CAPTURED_MFR + "0000034a"  # bytes 11-12 pad, 13-14 = 842 ppm
        reading = decode("3500e40397af", mfr)
        self.assertIsNotNone(reading)
        self.assertEqual(reading["model"], "Meter Pro CO2")
        self.assertEqual(reading["co2"], 842)

    def test_ignores_switchbot_bot(self):
        reading = decode("4800e40397af", CAPTURED_MFR)
        self.assertIsNone(reading)

    def test_ignores_encrypted_cc_uuid_device(self):
        reading = rs.decode_advertisement(
            address="7B:E6:AD:F0:A4:AB",
            rssi=-67,
            service_data={},
            manufacturer_data={0x06B1: bytes.fromhex("a7e765d7fda886b9")},
        )
        self.assertIsNone(reading)


class TargetTests(unittest.TestCase):
    def test_configured_mac_only(self):
        self.assertTrue(rs.is_target(CAPTURED_ADDR, CAPTURED_ADDR))
        self.assertFalse(rs.is_target(OTHER_ADDR, CAPTURED_ADDR))
        self.assertFalse(rs.is_target(OTHER_ADDR, "Meter Plus"))

    def test_empty_config_accepts_first_meter(self):
        self.assertTrue(rs.is_target(CAPTURED_ADDR, ""))
        self.assertTrue(rs.is_target(OTHER_ADDR, None))
        self.assertTrue(rs.is_target(OTHER_ADDR, "  "))


class BindTests(unittest.IsolatedAsyncioTestCase):
    """consider/update bind behaviour must never write the live config/state files."""

    LIVE_CONFIG = Path.home() / ".config/room-sensor/config.json"
    LIVE_STATE = Path.home() / ".local/state/room-sensor/status.json"

    def setUp(self):
        self._live_snapshots = {
            path: path.read_bytes() if path.exists() else None
            for path in (self.LIVE_CONFIG, self.LIVE_STATE)
        }
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.config_path = tmp / "config.json"
        self.state_path = tmp / "status.json"
        self._config_patcher = patch.object(rs, "CONFIG_PATH", self.config_path)
        self._state_patcher = patch.object(rs, "STATE_PATH", self.state_path)
        self._config_patcher.start()
        self._state_patcher.start()

    def tearDown(self):
        self._state_patcher.stop()
        self._config_patcher.stop()
        self._tmpdir.cleanup()
        live_config = self.LIVE_CONFIG.read_bytes() if self.LIVE_CONFIG.exists() else None
        self.assertEqual(
            live_config,
            self._live_snapshots[self.LIVE_CONFIG],
            "tests must not write ~/.config/room-sensor/config.json",
        )
        if self.LIVE_STATE.exists():
            payload = json.loads(self.LIVE_STATE.read_text())
            self.assertNotEqual(
                payload.get("address"),
                OTHER_ADDR,
                "tests must not write a second MAC to ~/.local/state/room-sensor/status.json",
            )

    def test_consider_drops_second_plus_when_bound(self):
        sensor = rs.RoomSensor({"address": CAPTURED_ADDR})
        other = sensor.consider(
            OTHER_ADDR,
            -65,
            {FD3D: bytes.fromhex(CAPTURED_SERVICE)},
            {0x0969: bytes.fromhex(CAPTURED_MFR)},
        )
        self.assertIsNone(other)
        self.assertFalse(self.config_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_consider_accepts_captured_addr_when_configured(self):
        sensor = rs.RoomSensor({"address": CAPTURED_ADDR})
        reading = sensor.consider(
            CAPTURED_ADDR,
            -65,
            {FD3D: bytes.fromhex(CAPTURED_SERVICE)},
            {0x0969: bytes.fromhex(CAPTURED_MFR)},
        )
        self.assertIsNotNone(reading)
        self.assertEqual(reading["address"], CAPTURED_ADDR)
        self.assertEqual(reading["model"], "Meter Plus")
        self.assertFalse(self.config_path.exists())
        self.assertFalse(self.state_path.exists())

    async def test_update_binds_first_then_rejects_second_address(self):
        sensor = rs.RoomSensor({"address": ""})
        first = decode(CAPTURED_SERVICE, CAPTURED_MFR, address=CAPTURED_ADDR)
        second = decode(CAPTURED_SERVICE, CAPTURED_MFR, address=OTHER_ADDR)
        await sensor.update(first)
        await sensor.update(second)
        payload = json.loads(self.state_path.read_text())
        self.assertEqual(payload["address"], CAPTURED_ADDR)
        self.assertEqual(sensor.config["address"], CAPTURED_ADDR)
        self.assertEqual(sensor.reading["address"], CAPTURED_ADDR)
        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved["address"], CAPTURED_ADDR)
        self.assertNotEqual(self.config_path, self.LIVE_CONFIG)
        self.assertNotEqual(self.state_path, self.LIVE_STATE)


class FormatTests(unittest.TestCase):
    def test_cli_and_json_shape(self):
        last_seen = datetime(2026, 8, 31, 19, 54, 15, tzinfo=timezone(timedelta(hours=-5)))
        reading = {
            "address": CAPTURED_ADDR,
            "model": "Meter Plus",
            "temperature_c": 23.3,
            "temperature_f": 73.9,
            "humidity": 47,
            "battery": 100,
            "rssi": -65,
            "fahrenheit_display": True,
            "last_seen": last_seen.isoformat(),
        }
        text = rs.format_cli(reading, now=last_seen, stale_seconds=120)
        self.assertIn("Temperature: 73.9°F / 23.3°C", text)
        self.assertIn("Humidity:    47%", text)
        self.assertIn("Battery:     100%", text)
        self.assertIn("RSSI:        -65 dBm", text)
        self.assertNotIn("STALE", text)

        payload = rs.format_status_json(reading, now=last_seen, stale_seconds=120)
        self.assertEqual(payload["temperature_f"], 73.9)
        self.assertEqual(payload["address"], CAPTURED_ADDR)
        self.assertFalse(payload["stale"])

    def test_stale_flag(self):
        last_seen = datetime(2026, 8, 31, 19, 54, 15, tzinfo=timezone(timedelta(hours=-5)))
        later = last_seen + timedelta(seconds=200)
        reading = {
            "address": CAPTURED_ADDR,
            "temperature_c": 23.3,
            "temperature_f": 73.9,
            "humidity": 47,
            "battery": 100,
            "rssi": -65,
            "last_seen": last_seen.isoformat(),
        }
        self.assertTrue(rs.format_status_json(reading, now=later, stale_seconds=120)["stale"])
        self.assertIn("STALE", rs.format_cli(reading, now=later, stale_seconds=120))


if __name__ == "__main__":
    unittest.main()
