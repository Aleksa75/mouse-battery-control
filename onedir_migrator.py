"""
One-time bridge executable to migrate legacy --onefile installs (<= v2.25.0)
into the unpacked --onedir v2.28.0+ layout automatically via MouseBatteryControl.zip.
"""

from __future__ import annotations

import ctypes
import json
import sys
import time
from pathlib import Path

import updater

DEFAULT_UPDATE_SOURCE = r"C:\Users\Infer\.gemini\antigravity\scratch\mouse-battery-notifier\releases"


def _show_error(msg: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, msg, "Mouse Battery & Control — Update", 0x10)
    except Exception:
        pass


def main() -> int:
    app_dir = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )

    # Give the previous --onefile updater's _apply_update.bat time to self-delete cleanly.
    time.sleep(0.6)
    prev_bat = app_dir / "_apply_update.bat"
    deadline = time.monotonic() + 3.0
    while prev_bat.exists() and time.monotonic() < deadline:
        time.sleep(0.2)

    update_source = DEFAULT_UPDATE_SOURCE
    cfg_path = app_dir / "config.json"
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw_src = str(cfg.get("update_source") or "").strip()
            if raw_src:
                update_source = raw_src
        except Exception:
            pass

    res = updater.check_for_update("0.0.0", update_source)
    if (
        res.get("status") != "update_available"
        or res.get("package_type") != "zip"
        or not res.get("download_url")
    ):
        err = res.get("message") or "Could not locate --onedir .zip release package."
        _show_error(str(err))
        return 1

    ok, info = updater.download_and_apply_update(
        str(res["download_url"]),
        expected_sha256=str(res.get("sha256") or ""),
        package_type="zip",
    )
    if not ok:
        _show_error(str(info))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
