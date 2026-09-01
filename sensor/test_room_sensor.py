#!/usr/bin/env python3
"""Unit tests against live-captured SwitchBot Meter Plus advertisements."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import room_sensor as rs

# Captured 2026-08-31T19:54:15-05:00 from C8:92:04:06:1C:2C
CAPTURED_SERVICE = "6900e40397af"
CAPTURED_MFR = "c89204061c2c2e030397af"
CAPTURED_ADDR = "C8:92:04:06:1C:2C"


class DecodeTests(unittest.TestCase):
    def test_captured_meter_plus_packet(self):
        reading = rs.decode_advertisement(
            address=CAPTURED_ADDR,
            rssi=-65,
            service_data={"0000fd3d-0000-1000-8000-00805f9b34fb": bytes.fromhex(CAPTURED_SERVICE)},
            manufacturer_data={0x0969: bytes.fromhex(CAPTURED_MFR)},
        )
        self.assertIsNotNone(reading)
        self.assertEqual(reading["address"], CAPTURED_ADDR)
        self.assertEqual(reading["model"], "Meter Plus")
        self.assertEqual(reading["temperature_c"], 23.3)
        self.assertEqual(reading["temperature_f"], 73.9)
        self.assertEqual(reading["humidity"], 47)
        self.assertEqual(reading["battery"], 100)
        self.assertEqual(reading["rssi"], -65)
        self.assertTrue(reading["fahrenheit_display"])

    def test_ignores_encrypted_cc_uuid_device(self):
        reading = rs.decode_advertisement(
            address="7B:E6:AD:F0:A4:AB",
            rssi=-67,
            service_data={},
            manufacturer_data={0x06B1: bytes.fromhex("a7e765d7fda886b9")},
        )
        self.assertIsNone(reading)

    def test_matches_configured_address_or_meter_plus(self):
        self.assertTrue(rs.is_target("C8:92:04:06:1C:2C", "Meter Plus"))
        self.assertTrue(rs.is_target("AA:BB:CC:DD:EE:FF", "Meter Plus"))
        self.assertFalse(rs.is_target("7B:E6:AD:F0:A4:AB", None))
        self.assertFalse(rs.is_target("4D:30:66:C0:51:A7", None))


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
        self.assertIn("Last seen:   2026-08-31T19:54:15-05:00", text)
        self.assertNotIn("STALE", text)

        payload = rs.format_status_json(reading, now=last_seen, stale_seconds=120)
        self.assertEqual(
            payload,
            {
                "temperature_f": 73.9,
                "temperature_c": 23.3,
                "humidity": 47,
                "battery": 100,
                "rssi": -65,
                "last_seen": "2026-08-31T19:54:15-05:00",
                "stale": False,
                "address": CAPTURED_ADDR,
            },
        )

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
        payload = rs.format_status_json(reading, now=later, stale_seconds=120)
        self.assertTrue(payload["stale"])
        text = rs.format_cli(reading, now=later, stale_seconds=120)
        self.assertIn("STALE", text)


if __name__ == "__main__":
    unittest.main()
