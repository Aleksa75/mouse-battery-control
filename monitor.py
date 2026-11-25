"""
Mouse Battery Notifier
Reads Logitech G HUB battery data, learns usage/drain patterns over time,
and sends native Windows Toast notifications if the mouse battery is low
or projected not to last until the evening.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import xml.sax.saxutils as saxutils
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import hid  # type: ignore
except ImportError:
    hid = None

import hidpp_mouse

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
HISTORY_PATH = BASE_DIR / "history.jsonl"
STATE_PATH = BASE_DIR / "state.json"

DEFAULT_TAB_ORDER: list[str] = ["Dashboard", "Notifications", "Mouse Control", "Sync & Backup"]


def normalize_tab_order(order: Any) -> list[str]:
    """Return a valid, deduplicated 4-tab canonical order falling back to DEFAULT_TAB_ORDER."""
    valid_set = set(DEFAULT_TAB_ORDER)
    cleaned: list[str] = []
    if isinstance(order, (list, tuple)):
        for item in order:
            key = str(item)
            if key in valid_set and key not in cleaned:
                cleaned.append(key)
    for key in DEFAULT_TAB_ORDER:
        if key not in cleaned:
            cleaned.append(key)
    return cleaned


DEFAULT_CONFIG: dict[str, Any] = {
    "device_filter": None,
    "hidden_devices": [],
    "tab_order": list(DEFAULT_TAB_ORDER),
    "notifications_enabled": True,
    "poll_interval_minutes": 5,
    "evening_hour": 22,
    "low_battery_threshold": 20,
    "critical_battery_threshold": 10,
    "reserve_battery_pct": 5,
    "cooldown_minutes": 60,
    "critical_cooldown_minutes": 20,
    "default_drain_rate_pct_per_hour": 1.5,
    "max_history_days": 30,
    "notification_sound": "Default",
    "close_to_tray": True,
    "theme": "Dark",
    "accent_mode": "Windows",
    "calibration_style": "Combo",
    "advertised_capacity_mah": 500,
    "update_source": "github:Aleksa75/mouse-battery-control",
    "auto_fetch_mouse_icons": False,
}

_CONFIG_LOCK = threading.RLock()
_STATE_LOCK = threading.RLock()
_HISTORY_LOCK = threading.RLock()

VALID_THEMES = {"System", "Dark", "Light", "Matrix"}
VALID_ACCENT_MODES = {"Windows", "Default"}
VALID_LANGUAGES = {"en", "ru"}
VALID_CALIBRATION_STYLES = {"Combo", "Bar", "Badge", "Minimal"}
VALID_ACCEL_MODES = {"Off", "On", "Auto"}

SOUND_EVENTS: dict[str, str | None] = {
    "Default": "ms-winsoundevent:Notification.Default",
    "Reminder": "ms-winsoundevent:Notification.Reminder",
    "Alarm": "ms-winsoundevent:Notification.Looping.Alarm",
    "Chime": "ms-winsoundevent:Notification.IM",
    "Mail": "ms-winsoundevent:Notification.Mail",
    "Silent": None,
}

# Approximate G HUB Wireless Power Consumption Model (RGB off, ~1900 mWh cell)
SYSTEM_BASE_MW: float = 6.0
REPORT_RATE_MW: dict[int, float] = {1000: 8.0, 500: 5.0, 250: 3.0, 125: 2.0}
BATTERY_CAPACITY_MWH: float = 1900.0
DEFAULT_ADVERTISED_CAPACITY_MAH: int = 500
NOMINAL_CELL_VOLTAGE: float = 3.8


def parse_report_rate_hz(val: Any, default: int = 1000) -> int:
    """Parse an int or string like '500 Hz' into the nearest supported polling rate (125/250/500/1000)."""
    fallback = default if default in REPORT_RATE_MW else 1000
    if val is None or isinstance(val, bool):
        return fallback
    num: int | None = None
    if isinstance(val, (int, float)):
        num = int(round(val))
    else:
        m = re.search(r"(\d+)", str(val))
        if m:
            num = int(m.group(1))
    if num is None or num <= 0:
        return fallback
    return min(REPORT_RATE_MW.keys(), key=lambda hz: (abs(hz - num), -hz))


def estimate_power_mw(report_rate_hz: int) -> tuple[float, float, float]:
    """Return (total_mw, system_mw, rate_mw) for a given polling rate with RGB Off."""
    hz = parse_report_rate_hz(report_rate_hz)
    rate_mw = REPORT_RATE_MW[hz]
    return SYSTEM_BASE_MW + rate_mw, SYSTEM_BASE_MW, rate_mw


def report_rate_baseline_drain_pct_per_hour(report_rate_hz: int) -> float:
    """Approximate %/hr baseline drain derived from total mW draw on a 1900 mWh nominal cell."""
    total_mw, _, _ = estimate_power_mw(report_rate_hz)
    return round((total_mw / BATTERY_CAPACITY_MWH) * 100.0, 2)


def atomic_write_text(path: Path, text: str) -> None:
    """Atomically replace a file via sibling temp file + fsync + retry on transient locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tf:
            tmp_path = Path(tf.name)
            tf.write(text)
            tf.flush()
            try:
                os.fsync(tf.fileno())
            except OSError:
                pass

        for attempt in range(5):
            try:
                os.replace(tmp_path, path)
                tmp_path = None
                return
            except PermissionError:
                if attempt >= 4:
                    raise
                time.sleep(0.05)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _validate_int_range(val: Any, name: str, lo: int, hi: int, fallback: int, strict: bool) -> int:
    if isinstance(val, bool) or not isinstance(val, int):
        if strict:
            raise ValueError(f"{name} must be an integer between {lo} and {hi}")
        return fallback
    if val < lo or val > hi:
        if strict:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return fallback
    return val


def _validate_num_range(val: Any, name: str, lo: float, hi: float, fallback: float, strict: bool) -> float:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        if strict:
            raise ValueError(f"{name} must be a number between {lo} and {hi}")
        return fallback
    fval = float(val)
    if not math.isfinite(fval) or fval < lo or fval > hi:
        if strict:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        return fallback
    return fval


def validate_config(
    raw: Any,
    base: dict[str, Any] | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Validate and sanitize configuration dict; raises ValueError in strict mode on bad fields."""
    fallback = dict(base if base is not None else DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("Configuration must be a JSON object.")
        return fallback

    cfg = dict(fallback)
    for k, v in raw.items():
        if k not in {
            "evening_hour",
            "poll_interval_minutes",
            "low_battery_threshold",
            "critical_battery_threshold",
            "reserve_battery_pct",
            "cooldown_minutes",
            "critical_cooldown_minutes",
            "default_drain_rate_pct_per_hour",
            "max_history_days",
            "advertised_capacity_mah",
            "notifications_enabled",
            "close_to_tray",
            "auto_fetch_mouse_icons",
            "notification_sound",
            "theme",
            "accent_mode",
            "language",
            "calibration_style",
            "accel_mode",
            "tab_order",
            "hidden_devices",
            "auto_games",
            "device_filter",
            "update_source",
            "report_rate",
        }:
            cfg[k] = v

    int_specs = (
        ("evening_hour", 0, 23, int(fallback.get("evening_hour", 22))),
        ("poll_interval_minutes", 1, 1440, int(fallback.get("poll_interval_minutes", 5))),
        ("cooldown_minutes", 1, 1440, int(fallback.get("cooldown_minutes", 60))),
        ("critical_cooldown_minutes", 1, 1440, int(fallback.get("critical_cooldown_minutes", 20))),
        ("max_history_days", 1, 365, int(fallback.get("max_history_days", 30))),
        ("advertised_capacity_mah", 50, 10000, int(fallback.get("advertised_capacity_mah", 500))),
    )
    for key, lo, hi, fb in int_specs:
        if key in raw:
            cfg[key] = _validate_int_range(raw[key], key, lo, hi, fb, strict)

    num_specs = (
        ("low_battery_threshold", 1.0, 100.0, float(fallback.get("low_battery_threshold", 20))),
        ("critical_battery_threshold", 1.0, 100.0, float(fallback.get("critical_battery_threshold", 10))),
        ("reserve_battery_pct", 0.0, 50.0, float(fallback.get("reserve_battery_pct", 5))),
        ("default_drain_rate_pct_per_hour", 0.05, 50.0, float(fallback.get("default_drain_rate_pct_per_hour", 1.5))),
    )
    for key, lo, hi, fb in num_specs:
        if key in raw:
            cfg[key] = _validate_num_range(raw[key], key, lo, hi, fb, strict)

    if float(cfg.get("critical_battery_threshold", 10)) > float(cfg.get("low_battery_threshold", 20)):
        if strict:
            raise ValueError("critical_battery_threshold cannot exceed low_battery_threshold")
        cfg["critical_battery_threshold"] = cfg["low_battery_threshold"]

    for bkey in ("notifications_enabled", "close_to_tray", "auto_fetch_mouse_icons"):
        if bkey in raw:
            val = raw[bkey]
            if not isinstance(val, bool):
                if strict:
                    raise ValueError(f"{bkey} must be a boolean")
                cfg[bkey] = bool(fallback.get(bkey, False))
            else:
                cfg[bkey] = val

    enum_specs = (
        ("notification_sound", set(SOUND_EVENTS.keys()), str(fallback.get("notification_sound", "Default"))),
        ("theme", VALID_THEMES, str(fallback.get("theme", "Dark"))),
        ("accent_mode", VALID_ACCENT_MODES, str(fallback.get("accent_mode", "Windows"))),
        ("language", VALID_LANGUAGES, str(fallback.get("language", "en"))),
        ("calibration_style", VALID_CALIBRATION_STYLES, str(fallback.get("calibration_style", "Combo"))),
        ("accel_mode", VALID_ACCEL_MODES, str(fallback.get("accel_mode", "Off"))),
    )
    for key, allowed, fb in enum_specs:
        if key in raw:
            val = raw[key]
            if not isinstance(val, str) or val not in allowed:
                if strict:
                    raise ValueError(f"{key} must be one of {sorted(allowed)}")
                cfg[key] = fb
            else:
                cfg[key] = val

    if "tab_order" in raw:
        val = raw["tab_order"]
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            if strict:
                raise ValueError("tab_order must be a list of strings")
            cfg["tab_order"] = normalize_tab_order(fallback.get("tab_order"))
        else:
            cfg["tab_order"] = normalize_tab_order(val)

    for lkey in ("hidden_devices", "auto_games"):
        if lkey in raw:
            val = raw[lkey]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                if strict:
                    raise ValueError(f"{lkey} must be a list of strings")
                cfg[lkey] = list(fallback.get(lkey, []))
            else:
                cfg[lkey] = list(val)

    for skey in ("device_filter", "update_source"):
        if skey in raw:
            val = raw[skey]
            if val is not None and not isinstance(val, str):
                if strict:
                    raise ValueError(f"{skey} must be a string or null")
                cfg[skey] = fallback.get(skey)
            else:
                cfg[skey] = val

    if "report_rate" in raw:
        val = raw["report_rate"]
        ok_rate = False
        if not isinstance(val, bool):
            if isinstance(val, int) and val > 0:
                ok_rate = True
            elif isinstance(val, str):
                m = re.search(r"(\d+)", val)
                if m and int(m.group(1)) > 0:
                    ok_rate = True
        if not ok_rate:
            if strict:
                raise ValueError("report_rate must be a valid polling rate")
            cfg["report_rate"] = fallback.get("report_rate", "1000 Hz")
        else:
            cfg["report_rate"] = val

    return cfg


def load_config() -> dict[str, Any]:
    with _CONFIG_LOCK:
        if CONFIG_PATH.exists():
            try:
                raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                return validate_config(raw, base=DEFAULT_CONFIG, strict=False)
            except Exception:
                pass
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    clean = validate_config(cfg, base=DEFAULT_CONFIG, strict=False)
    with _CONFIG_LOCK:
        atomic_write_text(CONFIG_PATH, json.dumps(clean, indent=2))
    return clean


def load_state() -> dict[str, Any]:
    with _STATE_LOCK:
        if STATE_PATH.exists():
            try:
                raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                return raw if isinstance(raw, dict) else {}
            except Exception:
                pass
        return {}


def save_state(state: dict[str, Any]) -> None:
    with _STATE_LOCK:
        atomic_write_text(STATE_PATH, json.dumps(state, indent=2))


def read_lghub_batteries() -> list[dict[str, Any]]:
    """Read battery/*/percentage entries from Logitech G HUB settings.db."""
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    db_path = Path(local_app_data) / "LGHUB" / "settings.db"
    if not db_path.exists():
        return []

    raw_json = _query_settings_db(db_path)
    if raw_json is None:
        # Fallback: copy db + wal/shm to a temporary directory and read there
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = Path(tmpdir) / "settings.db"
            for suffix in ("", "-wal", "-shm"):
                src = Path(f"{db_path}{suffix}")
                if src.exists():
                    shutil.copy2(src, Path(f"{tmp_db}{suffix}"))
            raw_json = _query_settings_db(tmp_db)

    if not raw_json:
        return []

    data = json.loads(raw_json)
    devices: list[dict[str, Any]] = []
    for key, val in data.items():
        if key.startswith("battery/") and key.endswith("/percentage") and isinstance(val, dict):
            parts = key.split("/")
            device_slug = parts[1] if len(parts) >= 3 else "mouse"
            pct = val.get("percentage")
            if pct is None:
                continue
            devices.append(
                {
                    "device": device_slug,
                    "display_name": format_device_name(device_slug),
                    "percentage": float(pct),
                    "is_charging": bool(val.get("isCharging", False)),
                    "reported_time": val.get("time"),
                    "observed_time": datetime.now(timezone.utc).isoformat(),
                    "source": "lghub",
                    "connection": "lightspeed",
                }
            )
    return devices


def read_bluetooth_mouse_batteries() -> list[dict[str, Any]]:
    """
    Discover active Bluetooth/BLE/PnP mice via Windows DEVPKEY_Device_ContainerId
    joined with DEVPKEY_Bluetooth_Battery ({104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2),
    without hardcoding brand names.
    """
    ps = r"""
$containerKey = '{8C7ED206-3F8A-4827-B3AB-AE9E1FAEFC6C} 2'
$batKey = '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2'
$genericNames = @(
    'hid-compliant mouse',
    'usb input device',
    'hid-compliant vendor-defined device',
    'hid-compliant consumer control device',
    'hid-compliant system controller',
    'bluetooth device',
    'microsoft bluetooth le enumerator',
    'bluetooth low energy gatt compliant hid device'
)

$mouseContainers = @{}
Get-PnpDevice -Class Mouse -Status OK -ErrorAction SilentlyContinue | ForEach-Object {
    $cProp = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $containerKey -ErrorAction SilentlyContinue
    if ($cProp -and $cProp.Data) {
        $cid = $cProp.Data.ToString()
        $mouseContainers[$cid] = $true
    }
}

$byContainer = @{}
$seenBtIds = @{}
Get-PnpDevice -Class Bluetooth,HIDClass,Mouse -Status OK -ErrorAction SilentlyContinue | ForEach-Object {
    $cProp = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $containerKey -ErrorAction SilentlyContinue
    $cid = if ($cProp -and $cProp.Data) { $cProp.Data.ToString() } else { '' }
    $fn = if ($_.FriendlyName) { $_.FriendlyName.Trim() } else { '' }
    $isMouseContainer = $cid -and $mouseContainers.ContainsKey($cid)
    $isBtClass = ($_.Class -eq 'Bluetooth') -or ($_.InstanceId -match '^BTH')

    $bProp = $null
    if ($isMouseContainer -or $isBtClass) {
        $bProp = Get-PnpDeviceProperty -InstanceId $_.InstanceId -KeyName $batKey -ErrorAction SilentlyContinue
    }
    $pct = if ($bProp -and $bProp.Data -ne $null) { [int]$bProp.Data } else { $null }

    if ($isMouseContainer) {
        if (-not $byContainer.ContainsKey($cid)) {
            $byContainer[$cid] = @{ name = ''; fallback = ''; pct = $null; is_bt = $false }
        }
        $entry = $byContainer[$cid]
        if ($isBtClass) { $entry.is_bt = $true }
        if ($pct -ne $null -and ($entry.pct -eq $null -or $isBtClass)) { $entry.pct = $pct }
        if ($fn) {
            $isGeneric = $genericNames -contains $fn.ToLower()
            if (-not $isGeneric) {
                if (-not $entry.name -or $isBtClass) { $entry.name = $fn }
            } elseif (-not $entry.fallback) {
                $entry.fallback = $fn
            }
        }
    } elseif ($isBtClass -and $pct -ne $null -and ($fn -match '(?i)mouse|trackball')) {
        if (-not $seenBtIds.ContainsKey($_.InstanceId)) {
            $seenBtIds[$_.InstanceId] = $true
            $byContainer['bt_' + $_.InstanceId] = @{ name = $fn; fallback = $fn; pct = $pct; is_bt = $true }
        }
    }
}

$out = @()
foreach ($k in $byContainer.Keys) {
    $e = $byContainer[$k]
    $best = if ($e.name) { $e.name } else { $e.fallback }
    if ($best -and ($genericNames -notcontains $best.ToLower())) {
        $out += [PSCustomObject]@{ name = $best; pct = $e.pct; is_bt = [bool]$e.is_bt }
    } elseif ($e.pct -ne $null -and $best) {
        $out += [PSCustomObject]@{ name = $best; pct = $e.pct; is_bt = [bool]$e.is_bt }
    }
}
$out | ConvertTo-Json -Compress
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            creationflags=creationflags,
        )
        raw = (proc.stdout or "").strip()
        if not raw:
            return []
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        devices: list[dict[str, Any]] = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in parsed:
            name = _clean_device_display_name("", str(item.get("name", "Mouse")))
            if not name:
                continue
            raw_pct = item.get("pct")
            pct = float(raw_pct) if raw_pct is not None else None
            is_bt = bool(item.get("is_bt", True))
            slug = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")
            devices.append(
                {
                    "device": slug or ("bt-mouse" if is_bt else "pnp-mouse"),
                    "display_name": name.upper(),
                    "percentage": pct,
                    "is_charging": False,
                    "reported_time": now_iso,
                    "observed_time": now_iso,
                    "source": "bluetooth" if is_bt else "pnp",
                    "connection": "bluetooth" if is_bt else "usb",
                }
            )
        return devices
    except Exception:
        return []


_IGNORED_MFG_NAMES = {
    "",
    "standard system devices",
    "microsoft",
    "generic",
    "usb",
    "hid",
    "unknown",
    "none",
    "default",
}


def _clean_device_display_name(mfg: str, prod: str) -> str:
    """Strip generic Windows INF prefixes like '(Standard system devices)' and merge vendor cleanly."""
    clean_p = re.sub(r"^\(\s*standard\b[^)]*\)\s*", "", str(prod or "").strip(), flags=re.IGNORECASE).strip()
    clean_m = re.sub(r"^\(\s*standard\b[^)]*\)\s*", "", str(mfg or "").strip(), flags=re.IGNORECASE).strip()
    if clean_m.lower() in _IGNORED_MFG_NAMES or (clean_m.startswith("(") and clean_m.endswith(")")):
        clean_m = ""
    if clean_m and clean_p and clean_m.lower() not in clean_p.lower():
        out = f"{clean_m} {clean_p}"
    else:
        out = clean_p or clean_m
    return " ".join(out.split()).strip()


def read_hid_mice() -> list[dict[str, Any]]:
    """Discover any standard USB/wireless HID pointing mouse (usage_page=0x0001, usage=0x0002), excluding keyboards."""
    if hid is None:
        return []
    try:
        all_devs = hid.enumerate()
    except Exception:
        return []

    keyboard_vid_pids: set[tuple[int, int]] = set()
    for info in all_devs:
        if info.get("usage_page") == 0x0001 and info.get("usage") == 0x0006:
            vid_k = int(info.get("vendor_id") or 0)
            pid_k = int(info.get("product_id") or 0)
            if vid_k or pid_k:
                keyboard_vid_pids.add((vid_k, pid_k))

    mouse_keywords = ("mouse", "trackball", "trackpad", "receiver", "dongle", "combo", "unifying", "bolt", "lightspeed")
    devices: list[dict[str, Any]] = []
    seen_hw: set[tuple[int, int, str]] = set()
    now_iso = datetime.now(timezone.utc).isoformat()

    for info in all_devs:
        if info.get("usage_page") != 0x0001 or info.get("usage") != 0x0002:
            continue
        prod = str(info.get("product_string") or "").strip()
        mfg = str(info.get("manufacturer_string") or "").strip()
        display = _clean_device_display_name(mfg, prod)
        if not display:
            continue

        vid = int(info.get("vendor_id") or 0)
        pid = int(info.get("product_id") or 0)
        low = display.lower()
        has_mouse_kw = any(k in low for k in mouse_keywords)
        if any(k in low for k in ("keyboard", "keypad", "numpad")) and not any(k in low for k in ("mouse", "combo")):
            continue
        if (vid, pid) in keyboard_vid_pids and not has_mouse_kw:
            continue

        serial = str(info.get("serial_number") or "").strip()
        norm_name = "".join(ch for ch in display.lower() if ch.isalnum())
        hw_key = (vid, pid, serial or norm_name)
        if hw_key in seen_hw:
            continue
        seen_hw.add(hw_key)

        slug = "".join(ch if ch.isalnum() else "-" for ch in display.lower()).strip("-") or f"hid-{vid:04x}-{pid:04x}"
        devices.append(
            {
                "device": slug,
                "display_name": display.upper(),
                "percentage": None,
                "is_charging": False,
                "reported_time": now_iso,
                "observed_time": now_iso,
                "source": "hid",
                "connection": "usb",
                "vendor_id": vid,
                "product_id": pid,
            }
        )
    return devices


def _norm_alnum(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _is_same_mouse(existing: dict[str, Any], cand: dict[str, Any]) -> bool:
    slug_a = _norm_alnum(existing.get("device", ""))
    slug_b = _norm_alnum(cand.get("device", ""))
    name_a = _norm_alnum(existing.get("display_name", ""))
    name_b = _norm_alnum(cand.get("display_name", ""))

    if slug_a and slug_b and slug_a == slug_b:
        return True
    if name_a and name_b:
        if name_a == name_b or (len(name_a) >= 5 and name_a in name_b) or (len(name_b) >= 5 and name_b in name_a):
            return True
    if slug_a and name_b and len(slug_a) >= 5 and slug_a in name_b:
        return True
    if slug_b and name_a and len(slug_b) >= 5 and slug_b in name_a:
        return True

    # Suppress generic Logitech USB/Lightspeed/Bolt/Unifying receiver HID entry when G HUB/HID++ already found Logitech mouse
    cand_name_low = str(cand.get("display_name", "")).lower()
    is_generic_rx = ("receiver" in cand_name_low or "dongle" in cand_name_low) and cand.get("percentage") is None
    if is_generic_rx and cand.get("vendor_id") == 0x046D:
        if existing.get("source") in ("lghub", "hidpp") or existing.get("vendor_id") == 0x046D:
            return True
    return False


def merge_discovered_mice(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge mouse lists in priority order (lghub -> hidpp -> bluetooth/pnp -> hid),
    deduplicating same-device entries while preserving distinct mice from any vendor.
    """
    merged: list[dict[str, Any]] = []
    for group in groups:
        for dev in group:
            dup = next((ex for ex in merged if _is_same_mouse(ex, dev)), None)
            if dup is None:
                merged.append(dict(dev))
            elif dup.get("percentage") is None and dev.get("percentage") is not None:
                dup["percentage"] = dev["percentage"]
                dup["is_charging"] = bool(dev.get("is_charging", False))
                dup["source"] = dev.get("source", dup.get("source"))
                dup["connection"] = dev.get("connection", dup.get("connection"))
    return merged


def read_all_mouse_batteries() -> list[dict[str, Any]]:
    """Discover mice across G HUB, HID++ 2.0, Windows Bluetooth/BLE ContainerId PnP, and USB HID."""
    return merge_discovered_mice(
        read_lghub_batteries(),
        hidpp_mouse.scan_hidpp_batteries(),
        read_bluetooth_mouse_batteries(),
        read_hid_mice(),
    )


def _query_settings_db(db_path: Path) -> str | None:
    try:
        uri = f"file:{db_path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=3.0)
        try:
            row = con.execute("SELECT file FROM data ORDER BY _id DESC LIMIT 1").fetchone()
            return row[0] if row else None
        finally:
            con.close()
    except sqlite3.Error:
        return None


def format_device_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").upper()


def load_history(max_days: int) -> list[dict[str, Any]]:
    with _HISTORY_LOCK:
        if not HISTORY_PATH.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
        entries: list[dict[str, Any]] = []
        with HISTORY_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    ts = datetime.fromisoformat(rec["ts"])
                    if ts >= cutoff:
                        entries.append(rec)
                except Exception:
                    continue
        return entries


def append_history_with_status(
    device: dict[str, Any],
    history: list[dict[str, Any]],
    max_days: int,
    report_rate_hz: int | None = None,
    active_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    if device.get("percentage") is None:
        return history, False
    with _HISTORY_LOCK:
        now_utc = datetime.now(timezone.utc)
        rec: dict[str, Any] = {
            "ts": now_utc.isoformat(),
            "device": device["device"],
            "pct": device["percentage"],
            "charging": device["is_charging"],
        }
        if report_rate_hz is not None:
            rec["rate_hz"] = parse_report_rate_hz(report_rate_hz)
        if active_seconds is not None and active_seconds > 0:
            rec["active_s"] = round(float(active_seconds), 1)

        # Avoid writing redundant entries within 4 minutes if nothing changed
        dev_hist = [h for h in history if h.get("device") == device["device"]]
        if dev_hist:
            last = dev_hist[-1]
            last_ts = datetime.fromisoformat(last["ts"])
            if (
                (now_utc - last_ts) < timedelta(minutes=4)
                and last.get("pct") == rec["pct"]
                and last.get("charging") == rec["charging"]
            ):
                return history, False

        history.append(rec)
        cutoff = now_utc - timedelta(days=max_days)
        pruned = [h for h in history if datetime.fromisoformat(h["ts"]) >= cutoff]
        payload = "\n".join(json.dumps(item) for item in pruned) + ("\n" if pruned else "")
        atomic_write_text(HISTORY_PATH, payload)
        return pruned, True


def append_history(
    device: dict[str, Any],
    history: list[dict[str, Any]],
    max_days: int,
    report_rate_hz: int | None = None,
    active_seconds: float | None = None,
) -> list[dict[str, Any]]:
    pruned, _ = append_history_with_status(
        device,
        history,
        max_days,
        report_rate_hz=report_rate_hz,
        active_seconds=active_seconds,
    )
    return pruned


def _compute_total_discharge(samples: list[dict[str, Any]]) -> float:
    total = 0.0
    for i in range(1, len(samples)):
        prev, cur = samples[i - 1], samples[i]
        if not cur.get("charging") and not prev.get("charging"):
            drop = float(prev["pct"]) - float(cur["pct"])
            if 0 < drop <= 25:
                total += drop
    return total


def _extract_discharge_sessions(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract qualifying contiguous discharging sessions from chronologically sorted samples."""
    segments: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []

    for s in samples:
        if s.get("charging"):
            if current:
                segments.append(current)
                current = []
            continue

        if not current:
            current = [s]
            continue

        prev = current[-1]
        dt_hours = (datetime.fromisoformat(s["ts"]) - datetime.fromisoformat(prev["ts"])).total_seconds() / 3600.0
        if dt_hours > 6.0 or s["pct"] > prev["pct"] + 1.0:
            segments.append(current)
            current = [s]
        else:
            current.append(s)

    if current:
        segments.append(current)

    valid: list[dict[str, Any]] = []
    for seg in segments:
        if len(seg) < 2:
            continue
        t0 = datetime.fromisoformat(seg[0]["ts"])
        t1 = datetime.fromisoformat(seg[-1]["ts"])
        duration_h = (t1 - t0).total_seconds() / 3600.0
        start_pct = float(seg[0]["pct"])
        end_pct = float(seg[-1]["pct"])
        drop_pct = start_pct - end_pct
        if duration_h < 0.25 or drop_pct < 1.0:
            continue
        rate = drop_pct / duration_h
        if rate < 0.1 or rate > 25.0:
            continue
        t1_local = t1.astimezone()
        valid.append(
            {
                "t0": t0,
                "t1": t1,
                "t1_local": t1_local,
                "duration_h": duration_h,
                "start_pct": int(round(start_pct)),
                "end_pct": int(round(end_pct)),
                "drop_pct": drop_pct,
                "rate": rate,
                "rate_hz": parse_report_rate_hz(seg[-1].get("rate_hz", 1000)),
                "is_weekend": t1_local.weekday() >= 5,
                "bucket": t1_local.hour // 6,  # 0=night, 1=morning, 2=afternoon, 3=evening
            }
        )
    return valid


def estimate_drain_rate(
    device_slug: str,
    history: list[dict[str, Any]],
    default_rate: float,
    current_rate_hz: int | None = None,
) -> tuple[float, bool, int]:
    """
    Estimate battery drain rate (% per hour) from historical discharging sessions,
    scaling by polling-rate power draw when current_rate_hz is known.
    Returns (drain_rate_pct_per_hour, is_learned, session_count).
    """
    samples = sorted([h for h in history if h.get("device") == device_slug], key=lambda x: x["ts"])
    valid = _extract_discharge_sessions(samples)

    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone()
    now_is_weekend = now_local.weekday() >= 5
    now_bucket = now_local.hour // 6  # 0=night, 1=morning, 2=afternoon, 3=evening

    cur_total_mw = estimate_power_mw(current_rate_hz)[0] if current_rate_hz is not None else None
    weighted_sum = 0.0
    weight_total = 0.0

    for sess in valid:
        age_days = max(0.0, (now_utc - sess["t1"]).total_seconds() / 86400.0)
        day_boost = 1.6 if sess["is_weekend"] == now_is_weekend else 1.0
        time_boost = 1.5 if sess["bucket"] == now_bucket else 1.0
        weight = math.exp(-age_days / 10.0) * min(sess["duration_h"], 12.0) * day_boost * time_boost
        sess_rate = sess["rate"]
        if cur_total_mw is not None:
            sess_mw = estimate_power_mw(sess.get("rate_hz", 1000))[0]
            if sess_mw > 0:
                sess_rate = sess_rate * (cur_total_mw / sess_mw)
        weighted_sum += sess_rate * weight
        weight_total += weight

    if not valid or weight_total <= 0:
        if current_rate_hz is not None:
            return report_rate_baseline_drain_pct_per_hour(current_rate_hz), False, 0
        return default_rate, False, 0

    return round(weighted_sum / weight_total, 2), True, len(valid)


def compute_battery_health(
    device_slug: str,
    history: list[dict[str, Any]],
    advertised_mah: int = DEFAULT_ADVERTISED_CAPACITY_MAH,
    is_logitech: bool = True,
) -> dict[str, Any]:
    """
    Estimate real battery capacity (mAh / mWh) and health % from active-use discharging cycles.
    Requires >= 2.0 full cycles (>= 200% cumulative discharge) with `active_s` data and Logitech
    polling-rate power model before reporting health; otherwise reports 'calibrating' / 'unavailable'.
    """
    samples = sorted([h for h in history if h.get("device") == device_slug], key=lambda x: x["ts"])
    total_drop = _compute_total_discharge(samples)
    charge_cycles = round(total_drop / 100.0, 2)
    adv_mah_val = max(50, int(advertised_mah))
    advertised_mwh = round(adv_mah_val * NOMINAL_CELL_VOLTAGE, 0) if is_logitech else None

    active_drop_pct = 0.0
    active_energy_mwh = 0.0
    pending_energy_mwh = 0.0
    has_active_in_seg = False

    for i in range(1, len(samples)):
        prev, cur = samples[i - 1], samples[i]
        if cur.get("charging") or prev.get("charging"):
            pending_energy_mwh = 0.0
            has_active_in_seg = False
            continue
        try:
            dt_hours = (datetime.fromisoformat(cur["ts"]) - datetime.fromisoformat(prev["ts"])).total_seconds() / 3600.0
        except Exception:
            dt_hours = 0.0
        drop = float(prev["pct"]) - float(cur["pct"])
        if dt_hours > 6.0 or drop < -1.0 or drop > 25.0:
            pending_energy_mwh = 0.0
            has_active_in_seg = False
            continue
        act_s = cur.get("active_s")
        if act_s is not None and float(act_s) > 0:
            total_mw = estimate_power_mw(cur.get("rate_hz", 1000))[0]
            pending_energy_mwh += (float(act_s) / 3600.0) * total_mw
            has_active_in_seg = True
        if drop > 0 and has_active_in_seg and pending_energy_mwh > 0:
            active_drop_pct += drop
            active_energy_mwh += pending_energy_mwh
            pending_energy_mwh = 0.0
            has_active_in_seg = False

    active_cycles = round(active_drop_pct / 100.0, 2)
    if is_logitech and active_drop_pct >= 200.0 and active_energy_mwh > 0 and advertised_mwh:
        est_capacity_mwh = round(active_energy_mwh / (active_drop_pct / 100.0), 0)
        est_capacity_mah = int(round(est_capacity_mwh / NOMINAL_CELL_VOLTAGE))
        health_pct = max(1, min(100, int(round((est_capacity_mwh / advertised_mwh) * 100.0))))
        status = "estimated"
    else:
        est_capacity_mwh = None
        est_capacity_mah = None
        health_pct = None
        status = "calibrating" if is_logitech else "unavailable"

    return {
        "advertised_mah": adv_mah_val if is_logitech else None,
        "advertised_mwh": advertised_mwh,
        "charge_cycles": charge_cycles,
        "active_cycles": active_cycles,
        "est_capacity_mwh": est_capacity_mwh,
        "est_capacity_mah": est_capacity_mah,
        "health_pct": health_pct,
        "status": status,
    }


def summarize_learning(
    device_slug: str,
    history: list[dict[str, Any]],
    default_rate: float,
    advertised_mah: int = DEFAULT_ADVERTISED_CAPACITY_MAH,
    is_logitech: bool = True,
) -> dict[str, Any]:
    """Compute real observed battery learning statistics for display in the Learned So Far dialog."""
    samples = sorted([h for h in history if h.get("device") == device_slug], key=lambda x: x["ts"])
    valid = _extract_discharge_sessions(samples)
    drain_rate, is_learned, sessions_used = estimate_drain_rate(device_slug, history, default_rate)
    health = compute_battery_health(
        device_slug, history, advertised_mah=advertised_mah, is_logitech=is_logitech
    )

    first_sample_local: str | None = None
    if samples:
        try:
            first_sample_local = datetime.fromisoformat(samples[0]["ts"]).astimezone().strftime("%b %d, %H:%M")
        except Exception:
            first_sample_local = None

    total_drop = int(round(_compute_total_discharge(samples)))
    calibration_pct = min(100, int(round(total_drop / 80.0 * 100)))
    if total_drop < 35:
        stage = "learning"
    elif total_drop < 80:
        stage = "calibrating"
    else:
        stage = "calibrated"

    total_session_hours = round(sum(s["duration_h"] for s in valid), 2)
    min_rate = round(min(s["rate"] for s in valid), 2) if valid else None
    max_rate = round(max(s["rate"] for s in valid), 2) if valid else None

    def _duration_weighted_avg(items: list[dict[str, Any]]) -> float | None:
        if not items:
            return None
        w_sum = sum(s["rate"] * s["duration_h"] for s in items)
        d_sum = sum(s["duration_h"] for s in items)
        return round(w_sum / d_sum, 2) if d_sum > 0 else None

    weekday_rate = _duration_weighted_avg([s for s in valid if not s["is_weekend"]])
    weekend_rate = _duration_weighted_avg([s for s in valid if s["is_weekend"]])
    bucket_rates = {
        b: _duration_weighted_avg([s for s in valid if s["bucket"] == b])
        for b in range(4)
    }

    recent_sessions = [
        {
            "end_local": s["t1_local"].strftime("%b %d, %H:%M"),
            "start_pct": s["start_pct"],
            "end_pct": s["end_pct"],
            "duration_str": format_duration(s["duration_h"]),
            "rate": round(s["rate"], 2),
        }
        for s in reversed(valid[-5:])
    ]

    return {
        "device_slug": device_slug,
        "sample_count": len(samples),
        "first_sample_local": first_sample_local,
        "total_discharge_pct": total_drop,
        "calibration_pct": calibration_pct,
        "stage": stage,
        "drain_rate_pct_per_hour": drain_rate,
        "is_learned": is_learned,
        "sessions_used": sessions_used,
        "default_rate": round(float(default_rate), 2),
        "total_session_hours": total_session_hours,
        "min_rate": min_rate,
        "max_rate": max_rate,
        "weekday_rate": weekday_rate,
        "weekend_rate": weekend_rate,
        "bucket_rates": bucket_rates,
        "recent_sessions": recent_sessions,
        "health": health,
    }


def format_duration(hours: float) -> str:
    if hours <= 0:
        return "< 5m"
    total_minutes = int(round(hours * 60))
    h, m = divmod(total_minutes, 60)
    if h >= 24:
        return f"{h}h"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def send_windows_toast(title: str, line1: str, line2: str, sound_name: str = "Default") -> bool:
    """Display a native Windows 10/11 Toast Notification via PowerShell WinRT."""
    xml_title = saxutils.escape(title)
    xml_line1 = saxutils.escape(line1)
    xml_line2 = saxutils.escape(line2)

    sound_uri = SOUND_EVENTS.get(sound_name, SOUND_EVENTS["Default"])
    if sound_uri is None:
        audio_xml = "<audio silent='true'/>"
    else:
        audio_xml = f"<audio src='{sound_uri}'/>"

    toast_xml = (
        f"<toast>"
        f"<visual><binding template='ToastGeneric'>"
        f"<text>{xml_title}</text>"
        f"<text>{xml_line1}</text>"
        f"<text>{xml_line2}</text>"
        f"</binding></visual>"
        f"{audio_xml}"
        f"</toast>"
    )

    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@'
{toast_xml}
'@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.Windows.Explorer')
$notifier.Show($toast)
"""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_script],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=creationflags,
        )
        if getattr(proc, "returncode", 1) != 0:
            err_msg = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[:300]
            logging.getLogger("MouseBatteryTray").warning(
                "Windows toast notification failed (exit=%s): %s",
                getattr(proc, "returncode", None),
                err_msg,
            )
            return False
        return True
    except Exception as exc:
        logging.getLogger("MouseBatteryTray").warning("Windows toast notification error: %s", exc)
        return False


def evaluate_device(
    device: dict[str, Any],
    cfg: dict[str, Any],
    history: list[dict[str, Any]],
    state: dict[str, Any],
    force_notify: bool = False,
    dry_run: bool = False,
    report_rate_hz: int | None = None,
) -> dict[str, Any]:
    if report_rate_hz is not None:
        eff_rate_hz: int | None = parse_report_rate_hz(report_rate_hz)
    elif device.get("source") in ("lghub", "hidpp"):
        eff_rate_hz = parse_report_rate_hz(cfg.get("report_rate", 1000))
    else:
        eff_rate_hz = None

    drain_rate, is_learned, sessions = estimate_drain_rate(
        device["device"],
        history,
        float(cfg["default_drain_rate_pct_per_hour"]),
        current_rate_hz=eff_rate_hz,
    )
    pct = device.get("percentage")
    if pct is None:
        return {
            "device": device["display_name"],
            "device_slug": device["device"],
            "source": device.get("source", "hid"),
            "connection": device.get("connection", "usb"),
            "percentage": None,
            "is_charging": False,
            "drain_rate_pct_per_hour": None,
            "is_learned": False,
            "sessions_used": 0,
            "total_discharge_pct": 0,
            "hours_left": None,
            "time_left_str": "Unknown",
            "projected_depletion_local": None,
            "wont_last_till_evening": False,
            "report_rate_hz": None,
            "est_power_mw": None,
            "est_sys_mw": None,
            "est_rate_mw": None,
            "reason": None,
            "notified": False,
        }
    reserve = float(cfg["reserve_battery_pct"])
    usable_pct = max(0.0, pct - reserve)
    hours_left = usable_pct / drain_rate if drain_rate > 0 else 999.0

    now_local = datetime.now().astimezone()
    depletion_local = now_local + timedelta(hours=hours_left)
    evening_hour = int(cfg["evening_hour"])
    evening_target = now_local.replace(hour=evening_hour, minute=0, second=0, microsecond=0)

    wont_last_till_evening = (now_local < evening_target) and (depletion_local < evening_target)
    is_critical = pct <= float(cfg["critical_battery_threshold"])
    is_low = pct <= float(cfg["low_battery_threshold"])

    reason = None
    if not device["is_charging"]:
        if is_critical:
            reason = "critical"
        elif wont_last_till_evening:
            reason = "evening"
        elif is_low:
            reason = "low"

    should_notify = force_notify or (reason is not None)

    # Check cooldown
    dev_state = state.get(device["device"], {})
    last_notified_str = dev_state.get("last_notified")
    last_reason = dev_state.get("last_reason")
    if should_notify and not force_notify and last_notified_str:
        last_notified = datetime.fromisoformat(last_notified_str)
        cooldown_min = (
            int(cfg["critical_cooldown_minutes"])
            if reason == "critical"
            else int(cfg["cooldown_minutes"])
        )
        # Allow immediate notification if escalating to critical
        if not (reason == "critical" and last_reason != "critical"):
            if (datetime.now(timezone.utc) - last_notified) < timedelta(minutes=cooldown_min):
                should_notify = False

    time_left_str = format_duration(hours_left)
    depletion_str = depletion_local.strftime("%I:%M %p").lstrip("0")
    rate_label = f"{drain_rate:.1f}%/hr ({'learned' if is_learned else 'est.'})"

    # Estimate cumulative discharge % across history for calibration progress
    dev_samples = sorted(
        [h for h in history if h.get("device") == device["device"]],
        key=lambda x: x["ts"],
    )
    total_discharge = _compute_total_discharge(dev_samples)

    power_info = estimate_power_mw(eff_rate_hz) if eff_rate_hz is not None else None
    result = {
        "device": device["display_name"],
        "device_slug": device["device"],
        "source": device.get("source", "lghub"),
        "connection": device.get("connection", "lightspeed"),
        "percentage": int(round(pct)),
        "is_charging": device["is_charging"],
        "drain_rate_pct_per_hour": drain_rate,
        "is_learned": is_learned,
        "sessions_used": sessions,
        "total_discharge_pct": int(round(total_discharge)),
        "hours_left": round(hours_left, 2),
        "time_left_str": time_left_str,
        "projected_depletion_local": depletion_local.strftime("%Y-%m-%d %H:%M"),
        "wont_last_till_evening": wont_last_till_evening,
        "report_rate_hz": eff_rate_hz,
        "est_power_mw": power_info[0] if power_info else None,
        "est_sys_mw": power_info[1] if power_info else None,
        "est_rate_mw": power_info[2] if power_info else None,
        "reason": reason,
        "notified": False,
    }

    if should_notify and not dry_run:
        if force_notify and device["is_charging"]:
            title = f"{device['display_name']} Battery: {int(round(pct))}% (Charging)"
            line1 = f"Projected runtime on battery: ~{time_left_str} (until ~{depletion_str})"
            line2 = f"Usage rate: {rate_label} • Test notification"
        elif reason == "critical":
            title = f"Critical Mouse Battery: {int(round(pct))}%"
            line1 = f"{device['display_name']} has ~{time_left_str} left (until ~{depletion_str})"
            line2 = f"Plug in soon • Drain rate: {rate_label}"
        elif reason == "evening":
            title = f"Mouse Battery Won't Last Till Evening ({int(round(pct))}%)"
            line1 = f"{device['display_name']}: ~{time_left_str} left (runs out ~{depletion_str})"
            line2 = f"Based on usage rate: {rate_label}"
        else:
            title = f"Low Mouse Battery: {int(round(pct))}%"
            line1 = f"{device['display_name']}: ~{time_left_str} left (until ~{depletion_str})"
            line2 = f"Usage rate: {rate_label}"

        toast_ok = send_windows_toast(
            title, line1, line2, sound_name=str(cfg.get("notification_sound", "Default"))
        )
        if toast_ok:
            result["notified"] = True
            if not force_notify:
                state[device["device"]] = {
                    "last_notified": datetime.now(timezone.utc).isoformat(),
                    "last_reason": reason,
                    "last_pct": pct,
                }
        else:
            result["notify_failed"] = True

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Mouse Battery Notifier")
    parser.add_argument("--status", action="store_true", help="Print current battery status without notifying")
    parser.add_argument("--test-notify", action="store_true", help="Send a test Windows Toast notification now")
    args = parser.parse_args()

    cfg = load_config()
    devices = read_lghub_batteries()
    if cfg.get("device_filter"):
        devices = [d for d in devices if cfg["device_filter"].lower() in d["device"].lower()]

    if not devices:
        if args.status or args.test_notify:
            print("No Logitech G HUB mouse battery data found.")
        return

    history = load_history(int(cfg["max_history_days"]))
    state = load_state()

    for dev in devices:
        history = append_history(dev, history, int(cfg["max_history_days"]))
        res = evaluate_device(
            dev,
            cfg,
            history,
            state,
            force_notify=args.test_notify,
            dry_run=args.status,
        )
        if args.status or args.test_notify:
            print(json.dumps(res, indent=2))

    if not args.status:
        save_state(state)


if __name__ == "__main__":
    main()
