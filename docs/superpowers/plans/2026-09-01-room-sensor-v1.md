# Room Sensor V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `novique.room` a stranger-installable Omarchy plugin that shows one local SwitchBot T/H meter (Meter, Plus, Outdoor, Pro, Pro CO2) on the bar, with the BLE reader shipped in-repo and installed by a documented `install.sh`.

**Architecture:** Quickshell never talks to BlueZ. A user systemd unit (`room-sensor.service`) decodes BLE advertisements with bleak + pyswitchbot and atomically writes `~/.local/state/room-sensor/status.json`. `Service.qml` watches that file; the bar pill and panel read from the service. `install.sh` copies the reader from the plugin tree into `~/.local/share/room-sensor/` so `omarchy plugin update` cannot trash the venv.

**Tech Stack:** Python 3, bleak, pyswitchbot, systemd --user, QML/Quickshell, Node `node:test` for `Model.js`.

**Spec:** `docs/superpowers/specs/2026-09-01-room-sensor-v1-design.md`

**Do not:** bind the second 2-pack Meter Plus, add `sensors[]`, set `allowMultiple`, enable HTTP by default, or talk to Hub 2 / Govee / Xiaomi.

---

## File map

| File | Role |
|---|---|
| `sensor/room_sensor.py` | BLE decode, daemon, CLI (`--print`, `--once`, `--discover`, `--bind`) |
| `sensor/test_room_sensor.py` | Captured-packet and format tests (no live scan in CI) |
| `sensor/requirements.txt` | `bleak==3.0.2` and `pyswitchbot==2.7.0` only |
| `sensor/room-sensor.service` | User unit template, ExecStart under XDG data |
| `install.sh` | Idempotent install / `--uninstall` / `--uninstall --purge` |
| `Model.js` | Parse status.json, bar label, tooltip, last-seen, panel copy |
| `tests/model.test.js` | Node tests for Model.js |
| `Service.qml` | FileView owner; `label`, `tooltip`, `panelTitle` |
| `BarWidget.qml` | Pill, hover tooltip, right-click notify from the service |
| `Panel.qml` | Details: model/label, both units, CO2, relative last-seen, MAC, errors |
| `manifest.json` | `1.1.0`, `label`, `showHumidity`, aliases include `ble` |
| `README.md` | Marketplace install story + hero screenshot |
| `preview.png` | Copy of `/home/clayton/Pictures/RoomTemp.png` |

Python tests run with the already-installed venv:

```bash
cd /home/clayton/.config/omarchy/plugins/novique.room
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

JS tests:

```bash
cd /home/clayton/.config/omarchy/plugins/novique.room
node --test tests/*.test.js
```

---

### Task 1: Vendor the BLE reader into `sensor/`

**Files:**
- Create: `sensor/room_sensor.py`
- Create: `sensor/test_room_sensor.py`
- Create: `sensor/requirements.txt`
- Create: `sensor/room-sensor.service`

Copy the working local reader **unchanged** so existing tests still pass. Do not fix the Meter-Plus-only decoder yet.

- [ ] **Step 1: Copy the four files**

```bash
cd /home/clayton/.config/omarchy/plugins/novique.room
mkdir -p sensor
cp ~/.local/share/room-sensor/room_sensor.py sensor/room_sensor.py
cp ~/.local/share/room-sensor/test_room_sensor.py sensor/test_room_sensor.py
cp ~/.local/share/room-sensor/requirements.txt sensor/requirements.txt
```

Write `sensor/room-sensor.service` as:

```ini
[Unit]
Description=SwitchBot T/H room sensor (BLE advertisements)
After=bluetooth.service
Wants=bluetooth.service

[Service]
Type=simple
ExecStart=%h/.local/share/room-sensor/.venv/bin/python %h/.local/share/room-sensor/room_sensor.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
WorkingDirectory=%h/.local/share/room-sensor

[Install]
WantedBy=default.target
```

- [ ] **Step 2: Run the existing Python tests from the repo copy**

```bash
cd /home/clayton/.config/omarchy/plugins/novique.room
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: PASS (captured Meter Plus packet, ignore encrypted device, format/stale).

- [ ] **Step 3: Commit**

```bash
git add sensor/room_sensor.py sensor/test_room_sensor.py sensor/requirements.txt sensor/room-sensor.service
git commit -m "Add the BLE reader to the plugin repository."
```

---

### Task 2: Decode the SwitchBot T/H family

**Files:**
- Modify: `sensor/room_sensor.py` (`decode_advertisement`, imports)
- Modify: `sensor/test_room_sensor.py`

Fixtures are the live Plus capture with the type byte (and, for CO2, manufacturer length) changed. pyswitchbot reads temp/humidity from manufacturer bytes `[8:11]` and CO2 from `[13:15]`; it does not care about the type byte. We do.

- [ ] **Step 1: Write the failing family tests**

Replace `sensor/test_room_sensor.py` with:

```python
#!/usr/bin/env python3
"""Unit tests against captured and constructed SwitchBot T/H advertisements."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

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
    def test_matches_configured_address_or_meter_plus(self):
        # Kept until Task 3 rewrites is_target. Still the old "any Plus" behaviour.
        self.assertTrue(rs.is_target("C8:92:04:06:1C:2C", "Meter Plus"))
        self.assertTrue(rs.is_target("AA:BB:CC:DD:EE:FF", "Meter Plus"))
        self.assertFalse(rs.is_target("7B:E6:AD:F0:A4:AB", None))


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
```

- [ ] **Step 2: Run tests — family cases fail**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: FAIL `test_meter_type_t` / `test_outdoor_type_w` / `test_meter_pro_co2` / `test_ignores_switchbot_bot` (decoder still only accepts `i`/`I` and always sets model to `"Meter Plus"`). Plus capture still passes.

- [ ] **Step 3: Implement family decode**

In `sensor/room_sensor.py`:

1. Change the import to:

```python
from switchbot.adv_parsers.meter import process_wosensorth, process_wosensorth_c
```

2. Replace the Meter-Plus-only type check and hard-coded `"Meter Plus"` with:

```python
TH_TYPES: dict[int, tuple[str, bool]] = {
    0x54: ("Meter", False),
    0x74: ("Meter", False),
    0x69: ("Meter Plus", False),
    0x49: ("Meter Plus", False),
    0x77: ("Indoor/Outdoor Meter", False),
    0x57: ("Indoor/Outdoor Meter", False),
    0x34: ("Meter Pro", False),
    0x14: ("Meter Pro", False),
    0x35: ("Meter Pro CO2", True),
    0x15: ("Meter Pro CO2", True),
}


def decode_advertisement(
    address: str,
    rssi: int | None,
    service_data: dict[str, bytes],
    manufacturer_data: dict[int, bytes],
) -> dict[str, Any] | None:
    """Decode a SwitchBot T/H advertisement. Returns None if it is not one."""
    sd = None
    for uuid, data in service_data.items():
        if uuid.lower().endswith("fd3d") or uuid.lower().endswith("0d00"):
            sd = data
            break
    if sd is None and service_data:
        sd = next(iter(service_data.values()))

    mfr = manufacturer_data.get(SWITCHBOT_COMPANY_ID)
    if mfr is None:
        mfr = manufacturer_data.get(2409)

    if not sd and not mfr:
        return None

    model = "Meter"
    has_co2 = False
    if sd:
        mapped = TH_TYPES.get(sd[0] & 0b01111111)
        if mapped is None:
            return None
        model, has_co2 = mapped

    parsed = process_wosensorth_c(sd, mfr) if has_co2 else process_wosensorth(sd, mfr)
    if not parsed:
        return None

    reading = {
        "address": address.upper(),
        "model": model,
        "temperature_c": round_temp(parsed["temperature"]),
        "temperature_f": round_temp(parsed["temp"]["f"]),
        "humidity": int(parsed["humidity"]),
        "battery": int(parsed["battery"]) if parsed.get("battery") is not None else None,
        "rssi": int(rssi) if rssi is not None else None,
        "fahrenheit_display": bool(parsed.get("fahrenheit")),
        "last_seen": now_local().isoformat(timespec="seconds"),
        "reader_state": "ok",
    }
    if parsed.get("co2") is not None:
        reading["co2"] = int(parsed["co2"])
    return reading
```

Leave `is_target` alone in this task.

- [ ] **Step 4: Re-run Python tests**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: PASS, including Meter / Outdoor / Pro CO2 / ignore Bot. `TargetTests` still describe the old last-wins behaviour.

- [ ] **Step 5: Commit**

```bash
git add sensor/room_sensor.py sensor/test_room_sensor.py
git commit -m "Decode Meter, Outdoor, and Pro CO2 advertisements."
```

---

### Task 3: Bind one MAC

**Files:**
- Modify: `sensor/room_sensor.py` (`is_target`, `RoomSensor.update`, `save_config`)
- Modify: `sensor/test_room_sensor.py` (`TargetTests`)

Once a MAC is configured, a second Meter Plus must not overwrite `status.json`. Empty config accepts the first T/H meter and persists that MAC.

- [ ] **Step 1: Replace TargetTests with the new contract**

Delete `test_matches_configured_address_or_meter_plus`. Add:

```python
class TargetTests(unittest.TestCase):
    def test_configured_mac_only(self):
        self.assertTrue(rs.is_target(CAPTURED_ADDR, CAPTURED_ADDR))
        self.assertFalse(rs.is_target(OTHER_ADDR, CAPTURED_ADDR))
        self.assertFalse(rs.is_target(OTHER_ADDR, "Meter Plus"))

    def test_empty_config_accepts_first_meter(self):
        self.assertTrue(rs.is_target(CAPTURED_ADDR, ""))
        self.assertTrue(rs.is_target(OTHER_ADDR, None))
        self.assertTrue(rs.is_target(OTHER_ADDR, "  "))
```

- [ ] **Step 2: Run — TargetTests fail**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest sensor.test_room_sensor.TargetTests -v
```

Expected: FAIL (`is_target` still treats `model == "Meter Plus"` as a match and uses `DEFAULT_CONFIG["address"]` when configured is missing).

- [ ] **Step 3: Implement single-MAC bind**

Replace `is_target` with:

```python
def is_target(address: str, configured_address: str | None = None) -> bool:
    configured = str(configured_address or "").strip().upper()
    if not configured:
        return True
    return address.upper() == configured
```

Add `save_config` next to `load_config`:

```python
def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        CONFIG_PATH,
        {
            "address": str(cfg.get("address") or "").upper(),
            "listen": cfg.get("listen", DEFAULT_CONFIG["listen"]),
            "port": int(cfg.get("port", DEFAULT_CONFIG["port"])),
            "stale_seconds": int(cfg.get("stale_seconds", DEFAULT_CONFIG["stale_seconds"])),
            "scanner_restart_seconds": int(
                cfg.get("scanner_restart_seconds", DEFAULT_CONFIG["scanner_restart_seconds"])
            ),
            "http": bool(cfg.get("http", False)),
        },
    )
```

In `load_config`, replace the forced-uppercase of a missing address with:

```python
    cfg["address"] = str(cfg.get("address") or "").upper()
    cfg["http"] = bool(cfg.get("http", False))
    return cfg
```

In `RoomSensor.consider`, pass only the address (drop model):

```python
        if not is_target(address, self.config.get("address")):
            return None
```

In `RoomSensor.update`, persist the first MAC:

```python
    async def update(self, reading: dict[str, Any]) -> None:
        async with self._lock:
            if not str(self.config.get("address") or "").strip():
                self.config["address"] = reading["address"]
                save_config(self.config)
            self.reading = reading
            self._last_packet_monotonic = asyncio.get_running_loop().time()
            atomic_write_json(STATE_PATH, reading)
```

Do **not** change `DEFAULT_CONFIG["address"]` yet (Task 6). This machine’s `~/.config/room-sensor/config.json` already has `C8:92:04:06:1C:2C`, so the live unit stays bound even with the old default.

- [ ] **Step 4: Re-run all Python tests**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sensor/room_sensor.py sensor/test_room_sensor.py
git commit -m "Bind a single meter MAC instead of any Meter Plus."
```

---

### Task 4: Null-safe CLI and richer status JSON

**Files:**
- Modify: `sensor/room_sensor.py` (`format_cli`, `format_status_json`)
- Modify: `sensor/test_room_sensor.py` (`FormatTests`)

- [ ] **Step 1: Add failing format tests**

Append to `FormatTests`:

```python
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
```

- [ ] **Step 2: Run FormatTests — new cases fail**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest sensor.test_room_sensor.FormatTests -v
```

Expected: FAIL `test_cli_skips_missing_battery_rssi` (`TypeError` on `None%`) and `test_status_json_includes_model_and_co2` (keys missing).

- [ ] **Step 3: Implement**

Replace `format_cli` and `format_status_json` with:

```python
def format_cli(reading: dict[str, Any], now: datetime | None = None, stale_seconds: int = 120) -> str:
    now = now or now_local()
    stale = is_stale(reading, now, stale_seconds)
    lines = [
        f"Temperature: {reading['temperature_f']:.1f}°F / {reading['temperature_c']:.1f}°C",
        f"Humidity:    {reading['humidity']}%",
    ]
    if reading.get("co2") is not None:
        lines.append(f"CO2:         {reading['co2']} ppm")
    if reading.get("battery") is not None:
        lines.append(f"Battery:     {reading['battery']}%")
    if reading.get("rssi") is not None:
        lines.append(f"RSSI:        {reading['rssi']} dBm")
    if reading.get("model"):
        lines.append(f"Model:       {reading['model']}")
    if reading.get("address"):
        lines.append(f"Address:     {reading['address']}")
    if reading.get("last_seen"):
        lines.append(f"Last seen:   {reading['last_seen']}")
    if stale:
        lines.append("Status:      STALE")
    return "\n".join(lines) + "\n"


def format_status_json(reading: dict[str, Any], now: datetime | None = None, stale_seconds: int = 120) -> dict[str, Any]:
    now = now or now_local()
    body: dict[str, Any] = {
        "temperature_f": reading.get("temperature_f"),
        "temperature_c": reading.get("temperature_c"),
        "humidity": reading.get("humidity"),
        "battery": reading.get("battery"),
        "rssi": reading.get("rssi"),
        "last_seen": reading.get("last_seen"),
        "stale": is_stale(reading, now, stale_seconds),
        "address": reading.get("address"),
        "model": reading.get("model"),
        "reader_state": reading.get("reader_state") or "ok",
    }
    if reading.get("co2") is not None:
        body["co2"] = reading["co2"]
    return body
```

- [ ] **Step 4: Re-run Python tests**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: PASS. `test_cli_and_json_shape` still finds Temperature/Humidity/Battery/RSSI lines.

- [ ] **Step 5: Commit**

```bash
git add sensor/room_sensor.py sensor/test_room_sensor.py
git commit -m "Tolerate missing battery and RSSI in CLI output."
```

---

### Task 5: `--discover` and `--bind`

**Files:**
- Modify: `sensor/room_sensor.py` (`format_discover_table`, `bind_address`, `main`)
- Modify: `sensor/test_room_sensor.py`

Live BLE is not tested here. Table formatting and config writes are.

- [ ] **Step 1: Write failing tests**

Append:

```python
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
```

Add `import json` at the top of the test file if it is not already there.

- [ ] **Step 2: Run — fail on missing symbols**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest sensor.test_room_sensor.DiscoverBindTests -v
```

Expected: FAIL `AttributeError: format_discover_table` / `bind_address`.

- [ ] **Step 3: Implement**

```python
def format_discover_table(readings: list[dict[str, Any]]) -> str:
    if not readings:
        return "no SwitchBot T/H meters found\n"
    header = f"{'ADDRESS':<17}  {'MODEL':<22}  {'TEMP':<7}  {'HUM':<4}  {'RSSI'}"
    lines = [header]
    for reading in readings:
        temp = reading.get("temperature_f")
        temp_s = f"{temp:.1f}°F" if isinstance(temp, (int, float)) else "—"
        hum = reading.get("humidity")
        hum_s = f"{hum}%" if hum is not None else "—"
        rssi = reading.get("rssi")
        rssi_s = str(rssi) if rssi is not None else "—"
        lines.append(
            f"{reading.get('address', ''):<17}  {str(reading.get('model') or ''):<22}  {temp_s:<7}  {hum_s:<4}  {rssi_s}"
        )
    return "\n".join(lines) + "\n"


def bind_address(address: str, path: Path | None = None) -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    target = path or CONFIG_PATH
    if target.exists():
        cfg.update(json.loads(target.read_text()))
    cfg["address"] = str(address).strip().upper()
    if path is None:
        save_config(cfg)
        return cfg
    atomic_write_json(
        target,
        {
            "address": cfg["address"],
            "listen": cfg.get("listen", DEFAULT_CONFIG["listen"]),
            "port": int(cfg.get("port", DEFAULT_CONFIG["port"])),
            "stale_seconds": int(cfg.get("stale_seconds", DEFAULT_CONFIG["stale_seconds"])),
            "scanner_restart_seconds": int(
                cfg.get("scanner_restart_seconds", DEFAULT_CONFIG["scanner_restart_seconds"])
            ),
            "http": bool(cfg.get("http", False)),
        },
    )
    return cfg
```

Add `async def run_discover(timeout: float) -> int` that scans like `scan_once` but collects unique addresses for `timeout` seconds, then prints `format_discover_table`. Change the scanner log line from `"scanning for Meter Plus advertisements"` to `"scanning for SwitchBot T/H advertisements"`. Change the `--once` timeout error from `"no Meter Plus advertisement in time"` to `"no SwitchBot T/H advertisement in time"`.

Extend `main()`:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SwitchBot T/H room sensor")
    parser.add_argument("--print", action="store_true", help="print last reading and exit")
    parser.add_argument("--once", action="store_true", help="scan until one reading, then print")
    parser.add_argument("--discover", action="store_true", help="list nearby SwitchBot T/H meters")
    parser.add_argument("--bind", metavar="MAC", help="bind this meter MAC and write config")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    if args.print:
        return print_cli()
    if args.bind:
        cfg = bind_address(args.bind)
        print(f"bound {cfg['address']}")
        return 0
    if args.discover:
        return asyncio.run(run_discover(args.timeout))
    if args.once:
        return asyncio.run(scan_once(args.timeout))
    asyncio.run(run_daemon())
    return 0
```

`run_discover`:

```python
async def run_discover(timeout: float = 20.0) -> int:
    found: dict[str, dict[str, Any]] = {}

    def callback(device, adv) -> None:
        reading = decode_advertisement(
            device.address,
            adv.rssi,
            adv.service_data or {},
            adv.manufacturer_data or {},
        )
        if reading is None:
            return
        found[reading["address"]] = reading

    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        await asyncio.sleep(timeout)
    finally:
        await scanner.stop()
    sys.stdout.write(format_discover_table(list(found.values())))
    return 0 if found else 1
```

- [ ] **Step 4: Re-run Python tests**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sensor/room_sensor.py sensor/test_room_sensor.py
git commit -m "Add discover and bind commands for the BLE reader."
```

---

### Task 6: Empty default MAC and HTTP opt-in

**Files:**
- Modify: `sensor/room_sensor.py` (`DEFAULT_CONFIG`, `run_daemon`, `run_http`)

New users must not inherit `C8:92:04:06:1C:2C`. HTTP must not start unless `http` is true. `aiohttp` is imported only inside `run_http`.

- [ ] **Step 1: Write a failing test for defaults**

Append:

```python
class ConfigTests(unittest.TestCase):
    def test_default_address_is_empty_and_http_off(self):
        self.assertEqual(rs.DEFAULT_CONFIG["address"], "")
        self.assertFalse(rs.DEFAULT_CONFIG.get("http", False))
```

- [ ] **Step 2: Run — fail**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest sensor.test_room_sensor.ConfigTests -v
```

Expected: FAIL (`DEFAULT_CONFIG["address"]` is still the live Plus MAC, and there is no `http` key).

- [ ] **Step 3: Implement**

Replace `DEFAULT_CONFIG` with:

```python
DEFAULT_CONFIG = {
    "address": "",
    "listen": "127.0.0.1",
    "port": 18787,
    "stale_seconds": 120,
    "scanner_restart_seconds": 90,
    "http": False,
}
```

Replace `run_daemon` with:

```python
async def run_daemon() -> None:
    config = load_config()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(config)
    sensor = RoomSensor(config)
    if not str(config.get("address") or "").strip() and not sensor.reading:
        write_reader_state(sensor, "unbound")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    tasks = [run_scanner(sensor, stop)]
    if config.get("http"):
        tasks.append(run_http(sensor, stop))
    await asyncio.gather(*tasks)
```

Replace `run_http` so a missing `aiohttp` cannot kill the scanner:

```python
async def run_http(sensor: RoomSensor, stop: asyncio.Event) -> None:
    try:
        from aiohttp import web
    except ImportError:
        print("http enabled but aiohttp is not installed; skipping status server", file=sys.stderr)
        await stop.wait()
        return

    async def status(_request: web.Request) -> web.Response:
        body, code = sensor.status_payload()
        return web.json_response(body, status=code)

    app = web.Application()
    app.router.add_get("/status", status)
    app.router.add_get("/", status)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, sensor.config["listen"], int(sensor.config["port"]))
    await site.start()
    print(f"http://{sensor.config['listen']}:{sensor.config['port']}/status", flush=True)
    try:
        await stop.wait()
    finally:
        await runner.cleanup()
```

On scanner adapter failures, and when the daemon is running with no MAC and no reading, write `reader_state` without inventing temperatures. Add this helper and call it from `run_scanner`’s `except Exception` and from `run_daemon` after constructing `RoomSensor` if there is no address and no reading:

```python
def write_reader_state(sensor: RoomSensor, state: str) -> None:
    payload = dict(sensor.reading or {})
    payload["reader_state"] = state
    if sensor.reading:
        sensor.reading = payload
    atomic_write_json(STATE_PATH, payload)
```

In `run_scanner`’s `except Exception as exc` block, after the print:

```python
            err = str(exc).lower()
            if "adapter" in err or "bluetooth" in err:
                write_reader_state(sensor, "no_adapter")
```

Existing `~/.config/room-sensor/config.json` already has `address`. `load_config` merges it over the empty default, so this desk does not re-bind. Missing `http` key → `load_config` sets `False`.

- [ ] **Step 4: Re-run all Python tests**

```bash
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sensor/room_sensor.py sensor/test_room_sensor.py
git commit -m "Default to no bound MAC and keep HTTP off."
```

---

### Task 7: `install.sh`

**Files:**
- Create: `install.sh`

No sudo. Idempotent. Keep this machine’s existing MAC. Paths match the spec.

- [ ] **Step 1: Write `install.sh` as this complete file, then `chmod +x install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

plugin_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/room-sensor"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/room-sensor"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/room-sensor"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
bin_dir="$HOME/.local/bin"
venv_dir="$data_dir/.venv"
python_bin="$venv_dir/bin/python"
unit_path="$unit_dir/room-sensor.service"
bindir_link="$bin_dir/room-temp"
config_file="$config_dir/config.json"

usage() {
  printf 'Usage: %s [--uninstall] [--purge] [--non-interactive] [--timeout N]\n' "$(basename "$0")"
}

uninstall=false
purge=false
non_interactive=false
timeout=20

while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall) uninstall=true; shift ;;
    --purge) purge=true; shift ;;
    --non-interactive) non_interactive=true; shift ;;
    --timeout) timeout="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if $purge && ! $uninstall; then
  printf '%s\n' '--purge requires --uninstall' >&2
  exit 2
fi

if $uninstall; then
  systemctl --user disable --now room-sensor.service 2>/dev/null || true
  rm -f "$unit_path" "$bindir_link"
  systemctl --user daemon-reload 2>/dev/null || true
  if $purge; then
    rm -rf "$data_dir" "$config_dir" "$state_dir"
  fi
  printf '%s\n' 'room-sensor stopped.'
  exit 0
fi

if ! command -v python3 >/dev/null; then
  printf '%s\n' 'python3 is required.' >&2
  exit 1
fi
if [[ ! -d /sys/class/bluetooth ]]; then
  printf '%s\n' 'No Bluetooth adapter found under /sys/class/bluetooth.' >&2
  exit 1
fi

mkdir -p "$data_dir" "$config_dir" "$state_dir" "$unit_dir" "$bin_dir"
cp "$plugin_dir/sensor/room_sensor.py" "$data_dir/room_sensor.py"
cp "$plugin_dir/sensor/requirements.txt" "$data_dir/requirements.txt"
cp "$plugin_dir/sensor/room-sensor.service" "$unit_path"

if [[ ! -x $python_bin ]]; then
  python3 -m venv "$venv_dir"
fi
"$python_bin" -m pip install -q -r "$data_dir/requirements.txt"

cat > "$bindir_link" <<EOF
#!/usr/bin/env bash
if [[ \$# -eq 0 ]]; then
  exec "$python_bin" "$data_dir/room_sensor.py" --print
fi
exec "$python_bin" "$data_dir/room_sensor.py" "\$@"
EOF
chmod +x "$bindir_link"

have_mac=false
if [[ -f $config_file ]] && grep -qE '"address": *"[A-Fa-f0-9:]{17}"' "$config_file"; then
  have_mac=true
fi

if ! $have_mac && [[ -t 0 ]] && ! $non_interactive; then
  printf '%s\n' "Scanning ${timeout}s for SwitchBot T/H meters…"
  "$python_bin" "$data_dir/room_sensor.py" --discover --timeout "$timeout" || true
  printf '%s' 'MAC to bind (blank = first meter seen): '
  read -r mac
  if [[ -n ${mac:-} ]]; then
    "$python_bin" "$data_dir/room_sensor.py" --bind "$mac"
  fi
fi

systemctl --user daemon-reload
systemctl --user enable --now room-sensor.service
printf '%s\n' "room-sensor.service is running. CLI: room-temp"
```

- [ ] **Step 2: Syntax-check**

```bash
bash -n /home/clayton/.config/omarchy/plugins/novique.room/install.sh
```

Expected: no output, exit 0.

- [ ] **Step 3: Commit** (do **not** run `--purge` on this machine)

```bash
git add install.sh
git commit -m "Add a user-level installer for the BLE reader."
```

---

### Task 8: `Model.js` — parse extras, last-seen, pill options

**Files:**
- Modify: `Model.js`
- Modify: `tests/model.test.js`

- [ ] **Step 1: Add failing tests**

Append to `tests/model.test.js`:

```javascript
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
```

- [ ] **Step 2: Run JS tests — new cases fail**

```bash
node --test tests/*.test.js
```

Expected: FAIL on missing `formatLastSeen` / `panelTitle` / `statusMessage` / `lowBattery` and on `reading.model` undefined.

- [ ] **Step 3: Implement Model.js**

Update `emptyReading`:

```javascript
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
```

In `parseStatus`, copy identity fields **before** the temperature early-return, so `{"reader_state":"unbound"}` still surfaces in the panel:

```javascript
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
```

Replace `barLabel` and add the helpers:

```javascript
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
```

In `tooltip`, push CO2 when present and use `formatLastSeen` for the last-seen line:

```javascript
  if (reading.co2 !== null && reading.co2 !== undefined) lines.push("CO2  " + reading.co2 + " ppm")
  if (reading.last_seen) lines.push("Last seen  " + formatLastSeen(reading.last_seen, Date.now()))
```

- [ ] **Step 4: Re-run JS tests**

```bash
node --test tests/*.test.js
```

Expected: PASS (existing parse/stale/label/tooltip tests included).

- [ ] **Step 5: Commit**

```bash
git add Model.js tests/model.test.js
git commit -m "Format last-seen, CO2, and pill humidity in the model."
```

---

### Task 9: Service, bar, and panel

**Files:**
- Modify: `Service.qml`
- Modify: `BarWidget.qml`
- Modify: `Panel.qml`

- [ ] **Step 1: Service.qml — expose new fields and stop dropping them on tick**

Change `label` to honor `showHumidity`. Add `panelTitle`. Pass `model`, `co2`, `reader_state` through `tick()`.

```qml
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

  function tick() {
    nowMs = Date.now()
    if (reading && reading.available)
      reading = Model.parseStatus(JSON.stringify({
        temperature_f: reading.temperature_f,
        temperature_c: reading.temperature_c,
        humidity: reading.humidity,
        battery: reading.battery,
        rssi: reading.rssi,
        co2: reading.co2,
        last_seen: reading.last_seen,
        address: reading.address,
        model: reading.model,
        reader_state: reading.reader_state
      }), nowMs, staleSeconds)
  }
```

- [ ] **Step 2: BarWidget.qml — tooltip and in-process notify**

```qml
    tooltipText: room && room.tooltip ? room.tooltip : "Room sensor — no reading yet"

    onPressed: function(b) {
      if (b === Qt.RightButton && root.bar) {
        var msg = root.room && root.room.tooltip ? root.room.tooltip : "Room sensor unavailable"
        root.bar.run("omarchy-notification-send " + JSON.stringify(msg))
      } else {
        root.togglePanel()
      }
    }
```

- [ ] **Step 3: Panel.qml — title, CO2, last-seen, MAC, errors, low battery**

Replace the `Column` body (keep `KeyboardPanel` / `PanelKeyCatcher` as they are). Add `import "Model.js" as Model` at the top.

```qml
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
```

Remove the old humidity `"No reading yet"` branch; empty state is `statusMessage` only.

- [ ] **Step 4: Commit**

```bash
git add Service.qml BarWidget.qml Panel.qml
git commit -m "Drive the pill and panel from the richer status model."
```

---

### Task 10: Manifest 1.1.0

**Files:**
- Modify: `manifest.json`

- [ ] **Step 1: Update manifest fields**

```json
{
  "schemaVersion": 1,
  "id": "novique.room",
  "name": "Room",
  "version": "1.1.0",
  "author": "Novique",
  "license": "MIT",
  "description": "Indoor temperature and humidity from a local SwitchBot BLE meter.",
  "kinds": [
    "service",
    "bar-widget"
  ],
  "entryPoints": {
    "service": "Service.qml",
    "barWidget": "BarWidget.qml"
  },
  "barWidget": {
    "displayName": "Room",
    "description": "Show indoor temperature and humidity from a local SwitchBot meter.",
    "category": "Info",
    "aliases": [
      "room",
      "temperature",
      "humidity",
      "meter",
      "switchbot",
      "ble"
    ],
    "allowMultiple": false,
    "defaultSection": "center",
    "defaults": {
      "unit": "F",
      "staleSeconds": 120,
      "label": "",
      "showHumidity": true
    },
    "schema": [
      {
        "key": "unit",
        "type": "enum",
        "label": "Temperature unit",
        "options": ["F", "C"],
        "defaultValue": "F",
        "description": "Unit shown on the bar pill. The popup always lists both."
      },
      {
        "key": "staleSeconds",
        "type": "integer",
        "label": "Stale after (seconds)",
        "min": 30,
        "max": 600,
        "step": 30,
        "defaultValue": 120,
        "description": "Dim the pill when the local room-sensor service has not published a new reading in this long."
      },
      {
        "key": "label",
        "type": "string",
        "label": "Room name",
        "defaultValue": "",
        "description": "Title in the details panel. Leave blank to use the meter model."
      },
      {
        "key": "showHumidity",
        "type": "boolean",
        "label": "Show humidity on the pill",
        "defaultValue": true,
        "description": "Include relative humidity next to the temperature on the bar."
      }
    ]
  }
}
```

- [ ] **Step 2: Validate**

```bash
cd /home/clayton/.config/omarchy/plugins/novique.room
omarchy plugin validate .
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add manifest.json
git commit -m "Bump the plugin to 1.1.0 with label and humidity settings."
```

---

### Task 11: README and preview

**Files:**
- Create: `preview.png`
- Modify: `README.md`

- [ ] **Step 1: Copy the screenshot**

```bash
cp /home/clayton/Pictures/RoomTemp.png /home/clayton/.config/omarchy/plugins/novique.room/preview.png
```

- [ ] **Step 2: Replace README.md**

```markdown
# Room

Indoor temperature and humidity on the Omarchy bar, from a local SwitchBot meter over Bluetooth LE. No cloud, no hub.

![Room temperature on the Omarchy bar](preview.png)

The pill sits in the **center** of the bar and shows something like `73.6°  52%`. Click it for both units, humidity, battery, RSSI, and last-seen. A dimmed pill means the last reading is older than two minutes.

Works with SwitchBot Meter, Meter Plus, Indoor/Outdoor Meter, Meter Pro, and Meter Pro CO2. One meter per install.

## Install

```bash
omarchy plugin add https://github.com/novique-ai/omarchy-room-sensor.git --enable
```

That clones the plugin into `~/.config/omarchy/plugins/novique.room/` and places **Room** in the center of the bar. Then install the local BLE reader (Python venv + user systemd unit, no sudo):

```bash
~/.config/omarchy/plugins/novique.room/install.sh
```

On a TTY with no meter bound yet, the installer scans for about 20 seconds and asks which MAC to use. If you already have `~/.config/room-sensor/config.json`, that address is kept.

## Bind a meter

```bash
room-temp --discover
room-temp --bind AA:BB:CC:DD:EE:FF
```

No pairing and no SwitchBot hub. The meter must be powered and in range.

## Use

| Action | How |
|---|---|
| Read | Look at the bar: `73.6°  52%` |
| Details | Click the pill |
| Notify | Right-click the pill |
| CLI | `room-temp` |

## Settings

| Setting | Default | Meaning |
|---|---|---|
| Temperature unit | `F` | Pill unit. The panel always lists °F and °C. |
| Stale after | `120` seconds | Dim the pill when advertisements stop. |
| Room name | empty | Panel title. Blank uses the meter model. |
| Show humidity on the pill | on | Hide it if you want a shorter pill. |

Move the pill if you want it somewhere else:

```bash
omarchy bar move novique.room --section right
```

## Remove

```bash
omarchy plugin remove novique.room
```

That only drops the bar plugin. To stop the reader:

```bash
~/.config/omarchy/plugins/novique.room/install.sh --uninstall
```

Add `--purge` to also delete config, last reading, and the venv.

## Requirements

Omarchy Quattro, a Bluetooth adapter, Python 3, and one supported SwitchBot T/H meter.

## Develop

```bash
node --test tests/*.test.js
python -m unittest discover -s sensor -v
omarchy plugin validate .
```

Edits under `~/.config/omarchy/plugins/novique.room/` reload the QML in the running shell. After changing `sensor/room_sensor.py`, re-run `install.sh` and `systemctl --user restart room-sensor.service`.
```

Do not mention `omarchy bar put --after omarchy.clock`. Do not mention HTTP in the default use table.

- [ ] **Step 3: Commit**

```bash
git add preview.png README.md
git commit -m "Add marketplace README and preview screenshot."
```

---

### Task 12: Validate and live upgrade

**Files:** none new. This is the desk check.

- [ ] **Step 1: Tests and lint**

```bash
cd /home/clayton/.config/omarchy/plugins/novique.room
node --test tests/*.test.js
~/.local/share/room-sensor/.venv/bin/python -m unittest discover -s sensor -v
omarchy plugin validate .
qmllint -I "$OMARCHY_PATH/shell" BarWidget.qml Panel.qml Service.qml
```

Expected: tests PASS, validate exit 0. `qmllint` may warn on `qs.*` imports; fail only on real errors, not missing-type warnings from the stub environment.

- [ ] **Step 2: Upgrade this machine in place (no purge, do not bind the second Plus)**

```bash
~/.config/omarchy/plugins/novique.room/install.sh --non-interactive
systemctl --user restart room-sensor.service
sleep 3
room-temp
cat ~/.local/state/room-sensor/status.json
```

Expected:

- `config.json` address is still `C8:92:04:06:1C:2C`
- `room-temp` prints a live temperature
- `status.json` has `"model": "Meter Plus"`
- bar pill still shows temp + humidity
- hover tooltip is no longer empty
- panel last-seen is `Ns ago`, not the raw ISO stamp

If the pill does not refresh: `omarchy restart shell`.

- [ ] **Step 3: Commit only if Step 1–2 forced a fix**

No commit if nothing changed. If a fix was required, commit that fix with a message that says what broke on the live Plus.

---

## Spec coverage

| Spec item | Task |
|---|---|
| Vendor reader into `sensor/` | 1 |
| T/H family decode (Meter, Plus, Outdoor, Pro CO2) | 2 |
| Ignore other SwitchBot types | 2 |
| One bound MAC; no last-wins | 3 |
| Persist first meter if unbound | 3 |
| Optional `co2`; null battery/rssi | 4 |
| `--discover` / `--bind` | 5 |
| Empty default MAC | 6 |
| HTTP off; lazy aiohttp | 6 |
| `install.sh` / `--uninstall` / `--purge` | 7 |
| Keep this machine’s MAC | 3, 6, 7, 12 |
| `formatLastSeen`, `showHumidity`, tooltip | 8 |
| Panel title, CO2, MAC, errors, low battery | 8, 9 |
| Right-click without `room-temp` PATH | 9 |
| Manifest 1.1.0, `ble` alias, settings | 10 |
| README + `preview.png`; no clock-specific `bar put` | 11 |
| `omarchy plugin validate` + live Plus | 12 |
| V2 2-pack / `sensors[]` / `allowMultiple` | not built |

## Out of scope (do not implement)

- Binding or displaying the second 2-pack Meter Plus
- `sensors[]` in config or status.json
- `allowMultiple: true`
- HTTP on by default / adding aiohttp to `requirements.txt`
- Hub 2, Weather Station, Govee, Xiaomi
- Temperature-threshold notifications
- Marketplace GitHub issue submission (human, after push)
