#!/usr/bin/env python3
"""Local SwitchBot Meter Plus reader: BLE advertisements → CLI + HTTP /status."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from bleak import BleakScanner
from switchbot.adv_parsers.meter import process_wosensorth, process_wosensorth_c

HOME = Path.home()
CONFIG_PATH = HOME / ".config/room-sensor/config.json"
STATE_PATH = HOME / ".local/state/room-sensor/status.json"

DEFAULT_CONFIG = {
    # Live capture 2026-08-31: this is the Meter Plus (type 0x69, UUID 0xfd3d).
    # 4D:30:66:C0:51:A7 / 7B:E6:AD:F0:A4:AB (name 866f8f94) is a different
    # rotating-address device with UUID 000000cc and no environmental payload.
    "address": "C8:92:04:06:1C:2C",
    "listen": "127.0.0.1",
    "port": 18787,
    "stale_seconds": 120,
    "scanner_restart_seconds": 90,
}

FD3D = "0000fd3d-0000-1000-8000-00805f9b34fb"
SWITCHBOT_COMPANY_ID = 0x0969


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text()))
    cfg["address"] = str(cfg.get("address") or "").upper()
    cfg["http"] = bool(cfg.get("http", False))
    return cfg


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


def now_local() -> datetime:
    return datetime.now().astimezone()


def round_temp(value: float) -> float:
    return round(float(value) * 10) / 10


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


def is_target(address: str, configured_address: str | None = None) -> bool:
    configured = str(configured_address or "").strip().upper()
    if not configured:
        return True
    return address.upper() == configured


def _parse_last_seen(reading: dict[str, Any]) -> datetime | None:
    raw = reading.get("last_seen")
    if not raw:
        return None
    return datetime.fromisoformat(raw)


def is_stale(reading: dict[str, Any], now: datetime, stale_seconds: int) -> bool:
    seen = _parse_last_seen(reading)
    if seen is None:
        return True
    return (now - seen).total_seconds() > stale_seconds


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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="status.", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return None


class RoomSensor:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.reading: dict[str, Any] | None = read_state()
        self._last_packet_monotonic = 0.0
        self._lock = asyncio.Lock()

    def consider(self, address: str, rssi: int | None, service_data, manufacturer_data) -> dict[str, Any] | None:
        decoded = decode_advertisement(address, rssi, service_data, manufacturer_data)
        if decoded is None:
            return None
        if not is_target(address, self.config.get("address")):
            return None
        return decoded

    async def update(self, reading: dict[str, Any]) -> None:
        async with self._lock:
            if not str(self.config.get("address") or "").strip():
                self.config["address"] = reading["address"]
                save_config(self.config)
            if not is_target(reading["address"], self.config.get("address")):
                return
            self.reading = reading
            self._last_packet_monotonic = asyncio.get_running_loop().time()
            atomic_write_json(STATE_PATH, reading)

    def status_payload(self) -> tuple[dict[str, Any] | None, int]:
        if not self.reading:
            return {"error": "no reading yet"}, 503
        body = format_status_json(self.reading, stale_seconds=int(self.config["stale_seconds"]))
        return body, 200


async def run_scanner(sensor: RoomSensor, stop: asyncio.Event) -> None:
    restart_after = float(sensor.config["scanner_restart_seconds"])

    def callback(device, adv) -> None:
        try:
            reading = sensor.consider(
                device.address,
                adv.rssi,
                adv.service_data or {},
                adv.manufacturer_data or {},
            )
        except Exception as exc:
            print(f"decode error: {exc}", file=sys.stderr)
            return
        if reading is None:
            return
        asyncio.get_running_loop().create_task(sensor.update(reading))

    while not stop.is_set():
        scanner = BleakScanner(callback)
        try:
            await scanner.start()
            print("scanning for Meter Plus advertisements", flush=True)
            while not stop.is_set():
                await asyncio.sleep(1)
                loop_time = asyncio.get_running_loop().time()
                if sensor._last_packet_monotonic and (loop_time - sensor._last_packet_monotonic) > restart_after:
                    print("no advertisements recently; restarting scanner", flush=True)
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"scanner error: {exc}", file=sys.stderr)
        finally:
            try:
                await scanner.stop()
            except Exception:
                pass
        if not stop.is_set():
            await asyncio.sleep(2)


async def run_http(sensor: RoomSensor, stop: asyncio.Event) -> None:
    from aiohttp import web

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


async def run_daemon() -> None:
    config = load_config()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    sensor = RoomSensor(config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await asyncio.gather(run_scanner(sensor, stop), run_http(sensor, stop))


def print_cli() -> int:
    config = load_config()
    reading = read_state()
    if not reading:
        print("no reading yet (is room-sensor.service running?)", file=sys.stderr)
        return 1
    sys.stdout.write(format_cli(reading, stale_seconds=int(config["stale_seconds"])))
    if is_stale(reading, now_local(), int(config["stale_seconds"])):
        return 2
    return 0


async def scan_once(timeout: float = 20.0) -> int:
    config = load_config()
    sensor = RoomSensor(config)
    got = asyncio.Event()

    def callback(device, adv) -> None:
        reading = sensor.consider(
            device.address,
            adv.rssi,
            adv.service_data or {},
            adv.manufacturer_data or {},
        )
        if reading is None:
            return
        atomic_write_json(STATE_PATH, reading)
        sensor.reading = reading
        got.set()

    scanner = BleakScanner(callback)
    await scanner.start()
    try:
        try:
            await asyncio.wait_for(got.wait(), timeout=timeout)
        except TimeoutError:
            print("no Meter Plus advertisement in time", file=sys.stderr)
            return 1
    finally:
        await scanner.stop()
    sys.stdout.write(format_cli(sensor.reading, stale_seconds=int(config["stale_seconds"])))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SwitchBot Meter Plus room sensor")
    parser.add_argument("--print", action="store_true", help="print last reading and exit")
    parser.add_argument("--once", action="store_true", help="scan until one reading, then print")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    if args.print:
        return print_cli()
    if args.once:
        return asyncio.run(scan_once(args.timeout))
    asyncio.run(run_daemon())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
