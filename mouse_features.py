"""
Native Windows mouse settings control via Win32 API (ctypes) + Logitech G HUB launcher
and Windows Startup (HKCU Run) management.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import winreg
from pathlib import Path

user32 = ctypes.windll.user32

SPI_GETMOUSE = 0x0003
SPI_SETMOUSE = 0x0004
SPI_GETWHEELSCROLLLINES = 0x0068
SPI_SETWHEELSCROLLLINES = 0x0069
SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SM_SWAPBUTTON = 23

SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
SPIF_FLAGS = SPIF_UPDATEINIFILE | SPIF_SENDCHANGE

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "MouseBatteryTray"


def get_pointer_speed() -> int:
    speed = ctypes.c_int(10)
    user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(speed), 0)
    return int(speed.value)


def set_pointer_speed(speed: int) -> None:
    speed = max(1, min(20, int(speed)))
    user32.SystemParametersInfoW(SPI_SETMOUSESPEED, 0, ctypes.c_void_p(speed), SPIF_FLAGS)


def get_enhance_pointer_precision() -> bool:
    params = (ctypes.c_int * 3)()
    user32.SystemParametersInfoW(SPI_GETMOUSE, 0, params, 0)
    return bool(params[2])


def set_enhance_pointer_precision(enabled: bool) -> None:
    params = (ctypes.c_int * 3)()
    user32.SystemParametersInfoW(SPI_GETMOUSE, 0, params, 0)
    if enabled:
        params[0] = 6
        params[1] = 10
        params[2] = 1
    else:
        params[0] = 0
        params[1] = 0
        params[2] = 0
    user32.SystemParametersInfoW(SPI_SETMOUSE, 0, params, SPIF_FLAGS)


def get_wheel_scroll_lines() -> int:
    lines = ctypes.c_uint(3)
    user32.SystemParametersInfoW(SPI_GETWHEELSCROLLLINES, 0, ctypes.byref(lines), 0)
    return int(lines.value)


def set_wheel_scroll_lines(lines: int) -> None:
    lines = max(1, min(20, int(lines)))
    user32.SystemParametersInfoW(SPI_SETWHEELSCROLLLINES, lines, None, SPIF_FLAGS)


def get_swap_buttons() -> bool:
    return bool(user32.GetSystemMetrics(SM_SWAPBUTTON))


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint32)]


def get_idle_seconds() -> float:
    """Return seconds since the last keyboard/mouse input event via Win32 GetLastInputInfo."""
    try:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0
        tick = int(ctypes.windll.kernel32.GetTickCount()) & 0xFFFFFFFF
        elapsed_ms = (tick - int(lii.dwTime)) & 0xFFFFFFFF
        return elapsed_ms / 1000.0
    except Exception:
        return 0.0


def set_swap_buttons(swapped: bool) -> None:
    user32.SwapMouseButton(1 if swapped else 0)
    # Persist in registry as well
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Mouse", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "SwapMouseButtons", 0, winreg.REG_SZ, "1" if swapped else "0")
    except OSError:
        pass


def open_lghub() -> bool:
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LGHUB" / "lghub.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "LGHUB" / "lghub.exe",
    ]
    for path in candidates:
        if path.exists():
            subprocess.Popen([str(path)], close_fds=True)
            return True
    return False


def detect_connection_type(is_charging: bool = False) -> tuple[str, str]:
    """
    Detect mouse connection mode (LIGHTSPEED / USB Wired / Wireless).
    Returns (mode_key, tooltip_label).
    """
    # Check active raw input devices for Logitech Lightspeed receiver (PID_C547 / C548 / C539 / C53F)
    try:
        class RAWINPUTDEVICELIST(ctypes.Structure):
            _fields_ = [("hDevice", ctypes.c_void_p), ("dwType", ctypes.c_uint32)]

        num = ctypes.c_uint32(0)
        user32.GetRawInputDeviceList(None, ctypes.byref(num), ctypes.sizeof(RAWINPUTDEVICELIST))
        if num.value > 0:
            arr = (RAWINPUTDEVICELIST * num.value)()
            user32.GetRawInputDeviceList(arr, ctypes.byref(num), ctypes.sizeof(RAWINPUTDEVICELIST))
            RIDI_DEVICENAME = 0x20000007
            found_lightspeed = False
            found_wired = False
            for dev in arr:
                sz = ctypes.c_uint32(0)
                user32.GetRawInputDeviceInfoW(dev.hDevice, RIDI_DEVICENAME, None, ctypes.byref(sz))
                if sz.value > 0:
                    buf = ctypes.create_unicode_buffer(sz.value)
                    user32.GetRawInputDeviceInfoW(dev.hDevice, RIDI_DEVICENAME, buf, ctypes.byref(sz))
                    name = buf.value.upper()
                    if "VID_046D" in name:
                        if any(pid in name for pid in ("PID_C547", "PID_C548", "PID_C539", "PID_C53F", "PID_C541")):
                            found_lightspeed = True
                        elif any(pid in name for pid in ("PID_C094", "PID_C095", "PID_C092", "PID_C08B")):
                            found_wired = True
            if found_wired and not found_lightspeed:
                return "usb", "Connection: USB Wired"
            if found_lightspeed:
                if is_charging:
                    return "lightspeed", "Connection: LIGHTSPEED (Charging via USB)"
                return "lightspeed", "Connection: LIGHTSPEED"
    except Exception:
        pass
    return "lightspeed", "Connection: LIGHTSPEED"


GAME_PATH_MARKERS = (
    "steamapps\\common",
    "epic games\\",
    "riot games\\",
    "ubisoft game launcher\\",
    "ea games\\",
    "origin games\\",
    "gog galaxy\\games",
    "xboxgames\\",
    "battle.net\\",
)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
kernel32 = ctypes.windll.kernel32


def get_foreground_exe_path() -> str | None:
    """Return the full executable path of the currently focused Windows application."""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_uint32(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not hproc:
            return None
        try:
            buf_len = ctypes.c_uint32(1024)
            buf = ctypes.create_unicode_buffer(buf_len.value)
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(buf_len)):
                return buf.value
        finally:
            kernel32.CloseHandle(hproc)
    except Exception:
        return None
    return None


def is_game_process(exe_path: str | None, custom_games: list[str] | None = None) -> bool:
    """Detect whether exe_path belongs to a game (Steam/Epic/Riot/etc. or user's custom list)."""
    if not exe_path:
        return False
    low = exe_path.lower()
    exe_name = Path(exe_path).name.lower()

    if custom_games:
        for item in custom_games:
            target = str(item).strip().lower()
            if not target:
                continue
            if target == exe_name or target == low or low.endswith("\\" + target):
                return True

    return any(marker in low for marker in GAME_PATH_MARKERS)


def get_autostart() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, AUTOSTART_VALUE_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enabled: bool, base_dir: Path) -> None:
    if getattr(sys, "frozen", False):
        cmd = f'"{Path(sys.executable).resolve()}" --tray-only'
    else:
        exe_candidate = base_dir / "dist" / "MouseBatteryControl.exe"
        if exe_candidate.exists():
            cmd = f'"{exe_candidate}" --tray-only'
        else:
            pythonw = base_dir / ".venv" / "Scripts" / "pythonw.exe"
            tray_script = base_dir / "tray_app.py"
            cmd = f'"{pythonw}" "{tray_script}" --tray-only'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError:
        pass
