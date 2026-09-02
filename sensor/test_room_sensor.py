#!/usr/bin/env python3
"""Unit tests against captured and constructed SwitchBot T/H advertisements."""
from __future__ import annotations

import contextlib
import io
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
    LIVE_HISTORY = Path.home() / ".local/state/room-sensor/history.jsonl"

    def setUp(self):
        self._live_snapshots = {
            path: path.read_bytes() if path.exists() else None
            for path in (self.LIVE_CONFIG, self.LIVE_STATE)
        }
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.config_path = tmp / "config.json"
        self.state_path = tmp / "status.json"
        self.history_path = tmp / "history.jsonl"
        self._config_patcher = patch.object(rs, "CONFIG_PATH", self.config_path)
        self._state_patcher = patch.object(rs, "STATE_PATH", self.state_path)
        self._history_patcher = patch.object(rs, "HISTORY_PATH", self.history_path)
        self._config_patcher.start()
        self._state_patcher.start()
        self._history_patcher.start()

    def tearDown(self):
        self._history_patcher.stop()
        self._state_patcher.stop()
        self._config_patcher.stop()
        self.assertNoLiveHistoryWrite()
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

    def assertNoLiveHistoryWrite(self):
        """Rows this test produced must never appear in the real history file."""
        if not self.history_path.exists() or not self.LIVE_HISTORY.exists():
            return
        written = {ln for ln in self.history_path.read_text().splitlines() if ln.strip()}
        live = {ln for ln in self.LIVE_HISTORY.read_text().splitlines() if ln.strip()}
        self.assertFalse(
            written & live,
            "tests must not write ~/.local/state/room-sensor/history.jsonl",
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

    def test_cli_skips_missing_battery_rssi(self):
        last_seen = datetime(2026, 8, 31, 19, 54, 15, tzinfo=timezone(timedelta(hours=-5)))
        reading = {
            "address": CAPTURED_ADDR,
            "model": "Indoor/Outdoor Meter",
            "temperature_c": 23.3,
            "temperature_f": 73.9,
            "humidity": 47,
            "battery": None,
            "rssi": None,
            "last_seen": last_seen.isoformat(),
        }
        text = rs.format_cli(reading, now=last_seen, stale_seconds=120)
        self.assertIn("Temperature: 73.9°F / 23.3°C", text)
        self.assertNotIn("Battery:", text)
        self.assertNotIn("RSSI:", text)

    def test_status_json_includes_model_and_co2(self):
        last_seen = datetime(2026, 8, 31, 19, 54, 15, tzinfo=timezone(timedelta(hours=-5)))
        reading = {
            "address": CAPTURED_ADDR,
            "model": "Meter Pro CO2",
            "temperature_c": 23.3,
            "temperature_f": 73.9,
            "humidity": 47,
            "battery": 80,
            "rssi": -70,
            "co2": 842,
            "last_seen": last_seen.isoformat(),
            "reader_state": "ok",
        }
        payload = rs.format_status_json(reading, now=last_seen, stale_seconds=120)
        self.assertEqual(payload["model"], "Meter Pro CO2")
        self.assertEqual(payload["co2"], 842)
        self.assertEqual(payload["reader_state"], "ok")


class DiscoverBindTests(unittest.TestCase):
    def test_discover_table(self):
        text = rs.format_discover_table(
            [
                {
                    "address": CAPTURED_ADDR,
                    "model": "Meter Plus",
                    "temperature_f": 73.9,
                    "humidity": 47,
                    "rssi": -65,
                }
            ]
        )
        self.assertIn(CAPTURED_ADDR, text)
        self.assertIn("Meter Plus", text)
        self.assertIn("73.9", text)
        self.assertIn("47%", text)

    def test_discover_table_empty(self):
        self.assertIn("no SwitchBot", rs.format_discover_table([]))

    def test_bind_address_writes_config(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            cfg = rs.bind_address(OTHER_ADDR, path=path)
            self.assertEqual(cfg["address"], OTHER_ADDR)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["address"], OTHER_ADDR)


class ConfigTests(unittest.TestCase):
    def test_default_address_is_empty_and_http_off(self):
        self.assertEqual(rs.DEFAULT_CONFIG["address"], "")
        self.assertFalse(rs.DEFAULT_CONFIG.get("http", False))


def history_row_at(minutes_ago, temp_f=73.0, temp_c=22.8, humidity=50, battery=100):
    stamp = rs.now_local() - timedelta(minutes=minutes_ago)
    return {
        "time": stamp.isoformat(timespec="seconds"),
        "temperature_c": temp_c,
        "temperature_f": temp_f,
        "humidity": humidity,
        "battery": battery,
    }


class HistoryPathTestCase(unittest.TestCase):
    """Every history test writes to a temp file, never ~/.local/state."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.history_path = self.tmp / "history.jsonl"
        self._patcher = patch.object(rs, "HISTORY_PATH", self.history_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._tmpdir.cleanup()


class DurationTests(unittest.TestCase):
    def test_each_unit(self):
        self.assertEqual(rs.parse_duration("45s"), timedelta(seconds=45))
        self.assertEqual(rs.parse_duration("90m"), timedelta(minutes=90))
        self.assertEqual(rs.parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(rs.parse_duration("3d"), timedelta(days=3))

    def test_combined_and_sloppy_input(self):
        self.assertEqual(rs.parse_duration("1h30m"), timedelta(minutes=90))
        self.assertEqual(rs.parse_duration(" 1H 30M "), timedelta(minutes=90))

    def test_bare_number_means_minutes(self):
        self.assertEqual(rs.parse_duration("90"), timedelta(minutes=90))

    def test_rejects_junk(self):
        for bad in ("", "   ", "soon", "1w", "h", "-5m", "1h2x"):
            with self.assertRaises(ValueError):
                rs.parse_duration(bad)

    def test_rejects_zero(self):
        with self.assertRaises(ValueError):
            rs.parse_duration("0h")

    def test_window_label_spells_out_bare_minutes(self):
        self.assertEqual(rs.window_label("90"), "90m")
        self.assertEqual(rs.window_label("1h"), "1h")


class HistoryRowTests(unittest.TestCase):
    def test_keeps_present_fields_only(self):
        row = rs.history_row(
            {
                "last_seen": "2026-09-02T07:07:48-05:00",
                "temperature_c": 23.4,
                "temperature_f": 74.1,
                "humidity": 50,
                "battery": None,
                "rssi": -57,
                "reader_state": "ok",
            }
        )
        self.assertEqual(row["time"], "2026-09-02T07:07:48-05:00")
        self.assertEqual(row["temperature_f"], 74.1)
        self.assertEqual(row["humidity"], 50)
        for absent in ("battery", "co2", "rssi", "reader_state"):
            self.assertNotIn(absent, row)

    def test_carries_co2_when_the_meter_reports_it(self):
        row = rs.history_row({"last_seen": "2026-09-02T07:07:48-05:00", "co2": 842})
        self.assertEqual(row["co2"], 842)

    def test_falls_back_to_now_without_last_seen(self):
        self.assertIsNotNone(rs.row_time(rs.history_row({"humidity": 50})))


class HistoryStoreTests(HistoryPathTestCase):
    def test_append_then_read_round_trip(self):
        rs.append_history(history_row_at(10))
        rs.append_history(history_row_at(5))
        rows = rs.read_history()
        self.assertEqual(len(rows), 2)
        self.assertLess(rs.row_time(rows[0]), rs.row_time(rows[1]))

    def test_reads_nothing_when_the_file_is_absent(self):
        self.assertEqual(rs.read_history(), [])
        self.assertIsNone(rs.latest_history_time())

    def test_since_filters_the_window(self):
        for minutes in (200, 90, 30, 1):
            rs.append_history(history_row_at(minutes))
        self.assertEqual(len(rs.read_history(since=timedelta(hours=1))), 2)

    def test_out_of_order_rows_come_back_sorted(self):
        rs.append_history(history_row_at(1))
        rs.append_history(history_row_at(50))
        rows = rs.read_history()
        self.assertLess(rs.row_time(rows[0]), rs.row_time(rows[1]))

    def test_corrupt_lines_are_skipped_not_fatal(self):
        rs.append_history(history_row_at(5))
        with self.history_path.open("a") as f:
            f.write("not json at all\n")
            f.write('{"temperature_f": 70}\n')
            f.write('{"time": "yesterday"}\n')
            f.write('["not", "an", "object"]\n')
            f.write("\n")
        self.assertEqual(len(rs.read_history()), 1)

    def test_latest_history_time_is_the_newest_row(self):
        rs.append_history(history_row_at(10))
        newest = history_row_at(1)
        rs.append_history(newest)
        self.assertEqual(rs.latest_history_time(), rs.row_time(newest))


class HistoryPruneTests(HistoryPathTestCase):
    def test_drops_old_and_corrupt_rows(self):
        rs.append_history(history_row_at(60 * 24 * 9))
        rs.append_history(history_row_at(30))
        with self.history_path.open("a") as f:
            f.write("garbage\n")
        self.assertEqual(rs.prune_history(timedelta(hours=168)), 2)
        rows = rs.read_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(self.history_path.read_text().count("\n"), 1)

    def test_clean_file_is_left_byte_identical(self):
        rs.append_history(history_row_at(30))
        before = self.history_path.read_bytes()
        self.assertEqual(rs.prune_history(timedelta(hours=168)), 0)
        self.assertEqual(self.history_path.read_bytes(), before)

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(rs.prune_history(timedelta(hours=1)), 0)


class HistorySummaryTests(unittest.TestCase):
    BASE = datetime(2026, 9, 2, 6, 8, tzinfo=timezone(timedelta(hours=-5)))
    SAMPLES = [(73.2, 22.9, 52), (73.6, 23.1, 51), (74.3, 23.5, 50), (74.1, 23.4, 50)]

    def rows(self):
        return [
            {
                "time": (self.BASE + timedelta(minutes=20 * i)).isoformat(timespec="seconds"),
                "temperature_f": f,
                "temperature_c": c,
                "humidity": h,
                "battery": 100,
            }
            for i, (f, c, h) in enumerate(self.SAMPLES)
        ]

    def test_summary_maths(self):
        summary = rs.summarize_history(self.rows(), timedelta(hours=1))
        self.assertEqual(summary["samples"], 4)
        self.assertEqual(summary["window_seconds"], 3600)
        temp = summary["series"]["temperature_f"]
        self.assertEqual(temp["first"], 73.2)
        self.assertEqual(temp["last"], 74.1)
        self.assertEqual(temp["delta"], 0.9)
        self.assertEqual(temp["min"], 73.2)
        self.assertEqual(temp["max"], 74.3)
        self.assertEqual(temp["avg"], 73.8)
        self.assertEqual(summary["series"]["humidity"]["delta"], -2)

    def test_unsorted_input_is_ordered_first(self):
        summary = rs.summarize_history(list(reversed(self.rows())))
        self.assertEqual(summary["series"]["temperature_f"]["first"], 73.2)
        self.assertEqual(summary["series"]["temperature_f"]["last"], 74.1)

    def test_empty_and_timeless_rows_summarize_to_nothing(self):
        self.assertIsNone(rs.summarize_history([]))
        self.assertIsNone(rs.summarize_history([{"temperature_f": 70}]))

    def test_format_shape(self):
        text = rs.format_history(self.rows(), label="1h")
        self.assertIn("Last 1h — 4 samples, 06:08 → 07:08", text)
        self.assertIn("Temperature: 73.2°F → 74.1°F", text)
        self.assertIn("+0.9°F", text)
        self.assertIn("+0.5°C", text)
        self.assertIn("min 73.2°F  max 74.3°F  avg 73.8°F", text)
        self.assertIn("Humidity:    52% → 50%", text)
        self.assertIn("(-2%)", text)

    def test_format_stays_quiet_about_an_unchanged_battery(self):
        self.assertNotIn("Battery:", rs.format_history(self.rows(), label="1h"))

    def test_format_reports_a_battery_that_moved(self):
        rows = self.rows()
        rows[-1]["battery"] = 97
        self.assertIn("Battery:     100% → 97%", rs.format_history(rows, label="1h"))

    def test_format_reports_co2_when_present(self):
        rows = self.rows()
        for i, row in enumerate(rows):
            row["co2"] = 800 + i * 10
        self.assertIn("CO2:         800 ppm → 830 ppm", rs.format_history(rows, label="1h"))

    def test_format_single_sample_says_so(self):
        text = rs.format_history(self.rows()[:1], label="1h")
        self.assertIn("1 sample", text)
        self.assertIn("no earlier reading", text)
        self.assertIn("Temperature: 73.2°F / 22.9°C", text)
        self.assertIn("Humidity:    52%", text)

    def test_format_empty(self):
        self.assertEqual(rs.format_history([]), "")

    def test_multi_day_window_shows_dates(self):
        rows = self.rows()
        rows[-1]["time"] = (self.BASE + timedelta(days=2)).isoformat(timespec="seconds")
        self.assertIn("Sep 02 06:08 → Sep 04 06:08", rs.format_history(rows, label="3d"))


class SparklineTests(unittest.TestCase):
    def test_flat_series_sits_mid_scale(self):
        self.assertEqual(rs.sparkline([70, 70, 70]), rs.SPARK_CHARS[3] * 3)

    def test_rising_series_spans_the_ramp(self):
        line = rs.sparkline([1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(line[0], rs.SPARK_CHARS[0])
        self.assertEqual(line[-1], rs.SPARK_CHARS[-1])

    def test_long_series_downsamples_to_width(self):
        self.assertEqual(len(rs.sparkline(list(range(500)), width=48)), 48)

    def test_empty_series(self):
        self.assertEqual(rs.sparkline([]), "")


class HistoryRecordTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp = Path(self._tmpdir.name)
        self.history_path = tmp / "history.jsonl"
        self._patchers = [
            patch.object(rs, "HISTORY_PATH", self.history_path),
            patch.object(rs, "STATE_PATH", tmp / "status.json"),
            patch.object(rs, "CONFIG_PATH", tmp / "config.json"),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._tmpdir.cleanup()

    def reading(self, seconds_ago=0, temp_f=73.9):
        stamp = rs.now_local() - timedelta(seconds=seconds_ago)
        return {
            "address": CAPTURED_ADDR,
            "model": "Meter Plus",
            "temperature_c": 23.3,
            "temperature_f": temp_f,
            "humidity": 47,
            "battery": 100,
            "rssi": -65,
            "last_seen": stamp.isoformat(timespec="seconds"),
            "reader_state": "ok",
        }

    def test_first_sample_lands_then_the_interval_throttles(self):
        sensor = rs.RoomSensor({"address": CAPTURED_ADDR, "history_interval_seconds": 60})
        self.assertTrue(sensor.record_history(self.reading()))
        self.assertFalse(sensor.record_history(self.reading()))
        self.assertEqual(len(rs.read_history()), 1)

    def test_records_again_once_the_interval_passes(self):
        sensor = rs.RoomSensor({"address": CAPTURED_ADDR, "history_interval_seconds": 60})
        sensor.record_history(self.reading(seconds_ago=120))
        self.assertTrue(sensor.record_history(self.reading()))
        self.assertEqual(len(rs.read_history()), 2)

    def test_disabled_history_writes_nothing(self):
        sensor = rs.RoomSensor({"address": CAPTURED_ADDR, "history": False})
        self.assertFalse(sensor.record_history(self.reading()))
        self.assertFalse(self.history_path.exists())

    def test_a_restart_resumes_the_throttle_from_the_file(self):
        first = rs.RoomSensor({"address": CAPTURED_ADDR, "history_interval_seconds": 60})
        first.record_history(self.reading())
        second = rs.RoomSensor({"address": CAPTURED_ADDR, "history_interval_seconds": 60})
        self.assertFalse(second.record_history(self.reading()))
        self.assertEqual(len(rs.read_history()), 1)

    async def test_update_appends_exactly_one_row(self):
        sensor = rs.RoomSensor({"address": CAPTURED_ADDR, "history_interval_seconds": 60})
        await sensor.update(decode(CAPTURED_SERVICE, CAPTURED_MFR))
        rows = rs.read_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temperature_f"], 73.9)
        self.assertEqual(rows[0]["humidity"], 47)
        self.assertNotIn("rssi", rows[0])
        self.assertNotIn("address", rows[0])

    def test_the_append_counter_triggers_a_prune(self):
        sensor = rs.RoomSensor(
            {
                "address": CAPTURED_ADDR,
                "history_interval_seconds": 0,
                "history_retention_hours": 1,
            }
        )
        rs.append_history(
            {
                "time": (rs.now_local() - timedelta(days=9)).isoformat(timespec="seconds"),
                "temperature_f": 70.0,
            }
        )
        with patch.object(rs, "HISTORY_PRUNE_EVERY", 1):
            sensor.record_history(self.reading())
        rows = rs.read_history()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["temperature_f"], 73.9)


class HistoryCommandTests(HistoryPathTestCase):
    def run_command(self, *args, **kwargs):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rs.history_command(*args, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_bad_duration_exits_two(self):
        code, _, err = self.run_command("soon", config={"history": True})
        self.assertEqual(code, 2)
        self.assertIn("cannot read duration", err)

    def test_no_rows_exits_one_and_points_at_the_service(self):
        code, _, err = self.run_command("1h", config={"history": True})
        self.assertEqual(code, 1)
        self.assertIn("no readings recorded in the last 1h", err)
        self.assertIn("room-sensor.service", err)

    def test_recording_switched_off_says_so(self):
        code, _, err = self.run_command("1h", config={"history": False})
        self.assertEqual(code, 1)
        self.assertIn("history recording is off", err)

    def seed_two_samples(self):
        rs.append_history(history_row_at(50, temp_f=72.0, temp_c=22.2, humidity=52))
        rs.append_history(history_row_at(5, temp_f=74.0, temp_c=23.3, humidity=50))

    def test_text_output(self):
        self.seed_two_samples()
        code, out, _ = self.run_command("1h", config={"history": True})
        self.assertEqual(code, 0)
        self.assertIn("Last 1h — 2 samples", out)
        self.assertIn("Temperature: 72°F → 74°F  (+2°F / +1.1°C)", out)
        self.assertIn("Humidity:    52% → 50%  (-2%)", out)

    def test_json_output(self):
        self.seed_two_samples()
        code, out, _ = self.run_command("1h", as_json=True, config={"history": True})
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["samples"], 2)
        self.assertEqual(payload["window_seconds"], 3600)
        self.assertEqual(payload["series"]["temperature_f"]["delta"], 2)
        self.assertEqual(payload["series"]["humidity"]["delta"], -2)

    def test_bare_minutes_are_accepted(self):
        rs.append_history(history_row_at(5))
        code, out, _ = self.run_command("30", config={"history": True})
        self.assertEqual(code, 0)
        self.assertIn("Last 30m", out)


class HistoryArgparseTests(unittest.TestCase):
    def test_since_short_circuits_before_print(self):
        with patch.object(rs, "history_command", return_value=0) as called:
            self.assertEqual(rs.main(["--since", "1h"]), 0)
        called.assert_called_once_with("1h", as_json=False)

    def test_json_flag_reaches_the_command(self):
        with patch.object(rs, "history_command", return_value=0) as called:
            rs.main(["--since", "2h", "--json"])
        called.assert_called_once_with("2h", as_json=True)


class HistoryConfigTests(unittest.TestCase):
    def test_defaults(self):
        self.assertTrue(rs.DEFAULT_CONFIG["history"])
        self.assertEqual(rs.DEFAULT_CONFIG["history_interval_seconds"], 60)
        self.assertEqual(rs.DEFAULT_CONFIG["history_retention_hours"], 168)

    def test_saved_config_carries_the_history_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            rs.bind_address(OTHER_ADDR, path=path)
            saved = json.loads(path.read_text())
            self.assertTrue(saved["history"])
            self.assertEqual(saved["history_interval_seconds"], 60)
            self.assertEqual(saved["history_retention_hours"], 168)

    def test_retention_window_reads_config(self):
        self.assertEqual(
            rs.retention_window({"history_retention_hours": 24}), timedelta(hours=24)
        )
        self.assertEqual(rs.retention_window({}), timedelta(hours=168))


if __name__ == "__main__":
    unittest.main()
