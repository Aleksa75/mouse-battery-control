"""
Direct Logitech HID++ 2.0 Hardware Driver (via hidapi)
Reads & writes live hardware DPI (feature 0x2201) and Report Rate / Polling Rate (feature 0x8060)
directly on Logitech Lightspeed / USB mice (e.g. G502 X Plus).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("MouseBatteryControl.hidpp")

try:
    import hid  # type: ignore
except ImportError:
    hid = None

LOGITECH_VID = 0x046D
HIDPP_LONG_REPORT_ID = 0x11
HIDPP_LONG_LEN = 20

FEATURE_DEVICE_FW_VERSION = 0x0003
FEATURE_DEVICE_NAME = 0x0005
FEATURE_BATTERY_STATUS = 0x1000
FEATURE_UNIFIED_BATTERY = 0x1004
FEATURE_ADJUSTABLE_DPI = 0x2201
FEATURE_REPORT_RATE = 0x8060
FEATURE_RGB_EFFECTS = 0x8071
FEATURE_PERKEY_LIGHTING = 0x8081
FEATURE_ONBOARD_PROFILES = 0x8100
SW_ID = 0x0A  # arbitrary software ID (1..15) so we can match our own replies


class HidppMouse:
    def __init__(self) -> None:
        self._dev: Any = None
        self._device_index: int = 0x01
        self._fw_feat_idx: int | None = None
        self._dpi_feat_idx: int | None = None
        self._rate_feat_idx: int | None = None
        self._rgb_feat_idx: int | None = None
        self._perkey_feat_idx: int | None = None
        self._onboard_feat_idx: int | None = None
        self._rgb_cluster_count: int = 0
        self._profile_count: int = 5
        self._last_error_code: int | None = None

    def _find_hidpp_paths(self) -> list[bytes]:
        if hid is None:
            return []
        paths: list[bytes] = []
        # Prefer usage_page 0xFF00, usage 0x0002 (HID++ long reports)
        all_devs = hid.enumerate(LOGITECH_VID, 0)
        long_devs = [d for d in all_devs if d.get("usage_page", 0) >= 0xFF00 and d.get("usage") == 2]
        other_devs = [d for d in all_devs if d.get("usage_page", 0) >= 0xFF00 and d not in long_devs]
        for d in long_devs + other_devs:
            p = d.get("path")
            if p and p not in paths:
                paths.append(p)
        return paths

    def _hidpp_request(self, dev: Any, dev_idx: int, feat_idx: int, func_id: int, params: list[int] | None = None, timeout_ms: int = 250) -> list[int] | None:
        self._last_error_code = None
        pkt = [HIDPP_LONG_REPORT_ID, dev_idx, feat_idx, ((func_id & 0x0F) << 4) | SW_ID]
        if params:
            pkt.extend(params)
        pkt.extend([0] * (HIDPP_LONG_LEN - len(pkt)))
        try:
            dev.write(pkt[:HIDPP_LONG_LEN])
        except Exception as exc:
            log.warning("HID++ write failed (feat=0x%02x fn=%d): %s", feat_idx, func_id, exc)
            return None

        # Read up to 6 packets looking for our matching response
        for _ in range(6):
            try:
                resp = dev.read(HIDPP_LONG_LEN, timeout_ms)
            except Exception as exc:
                log.warning("HID++ read failed (feat=0x%02x fn=%d): %s", feat_idx, func_id, exc)
                return None
            if not resp:
                log.debug("HID++ read timeout (feat=0x%02x fn=%d)", feat_idx, func_id)
                return None
            if len(resp) >= 4 and resp[0] in (0x10, 0x11) and resp[1] == dev_idx:
                # Error response (feature 0xFF)
                if resp[2] == 0xFF:
                    self._last_error_code = resp[5] if len(resp) > 5 else 0xFF
                    log.warning("HID++ error resp (feat=0x%02x fn=%d): %s", feat_idx, func_id, [hex(b) for b in resp[:8]])
                    return None
                if resp[2] == feat_idx and (resp[3] & 0x0F) == SW_ID:
                    return list(resp)
        return None

    def _request_with_retry(self, feat_idx: int | None, func_id: int, params: list[int] | None = None) -> list[int] | None:
        if feat_idx is None:
            return None
        if not self._dev and not self.connect():
            return None
        resp = self._hidpp_request(self._dev, self._device_index, feat_idx, func_id, params)
        if resp is None and self._last_error_code is None:
            log.info("HID++ retrying after reconnect (feat=0x%02x fn=%d)", feat_idx, func_id)
            if self.connect():
                resp = self._hidpp_request(self._dev, self._device_index, feat_idx, func_id, params)
        return resp

    def connect(self) -> bool:
        if hid is None:
            return False
        self.close()
        for path in self._find_hidpp_paths():
            dev = hid.device()
            try:
                dev.open_path(path)
                dev.set_nonblocking(0)
            except Exception:
                continue

            # Try device index 1 (Lightspeed receiver paired mouse) and 0xFF (direct USB)
            for dev_idx in (0x01, 0xFF, 0x02):
                dpi_resp = self._hidpp_request(
                    dev, dev_idx, 0x00, 0x00, [(FEATURE_ADJUSTABLE_DPI >> 8) & 0xFF, FEATURE_ADJUSTABLE_DPI & 0xFF]
                )
                if dpi_resp and dpi_resp[4] != 0:
                    self._dev = dev
                    self._device_index = dev_idx
                    self._dpi_feat_idx = dpi_resp[4]

                    rate_resp = self._hidpp_request(
                        dev, dev_idx, 0x00, 0x00, [(FEATURE_REPORT_RATE >> 8) & 0xFF, FEATURE_REPORT_RATE & 0xFF]
                    )
                    self._rate_feat_idx = rate_resp[4] if (rate_resp and rate_resp[4] != 0) else None

                    rgb_resp = self._hidpp_request(
                        dev, dev_idx, 0x00, 0x00, [(FEATURE_RGB_EFFECTS >> 8) & 0xFF, FEATURE_RGB_EFFECTS & 0xFF]
                    )
                    self._rgb_feat_idx = rgb_resp[4] if (rgb_resp and rgb_resp[4] != 0) else None
                    self._rgb_cluster_count = 0
                    if self._rgb_feat_idx is not None:
                        info = self._hidpp_request(dev, dev_idx, self._rgb_feat_idx, 0x00, [])
                        if info and len(info) >= 5:
                            self._rgb_cluster_count = min(int(info[4]), 4)

                    fw_resp = self._hidpp_request(
                        dev, dev_idx, 0x00, 0x00, [(FEATURE_DEVICE_FW_VERSION >> 8) & 0xFF, FEATURE_DEVICE_FW_VERSION & 0xFF]
                    )
                    self._fw_feat_idx = fw_resp[4] if (fw_resp and fw_resp[4] != 0) else None

                    perkey_resp = self._hidpp_request(
                        dev, dev_idx, 0x00, 0x00, [(FEATURE_PERKEY_LIGHTING >> 8) & 0xFF, FEATURE_PERKEY_LIGHTING & 0xFF]
                    )
                    self._perkey_feat_idx = perkey_resp[4] if (perkey_resp and perkey_resp[4] != 0) else None

                    onboard_resp = self._hidpp_request(
                        dev, dev_idx, 0x00, 0x00, [(FEATURE_ONBOARD_PROFILES >> 8) & 0xFF, FEATURE_ONBOARD_PROFILES & 0xFF]
                    )
                    self._onboard_feat_idx = onboard_resp[4] if (onboard_resp and onboard_resp[4] != 0) else None
                    self._profile_count = 5
                    if self._onboard_feat_idx is not None:
                        ob_desc = self._hidpp_request(dev, dev_idx, self._onboard_feat_idx, 0x00, [])
                        if ob_desc and len(ob_desc) >= 8 and 1 <= ob_desc[7] <= 5:
                            self._profile_count = int(ob_desc[7])

                    log.info(
                        "HID++ connected (dev_idx=0x%02x, fw_feat=%s, dpi_feat=%s, rate_feat=%s, rgb_feat=%s, perkey_feat=%s, onboard_feat=%s, clusters=%d, profiles=%d)",
                        dev_idx,
                        self._fw_feat_idx,
                        self._dpi_feat_idx,
                        self._rate_feat_idx,
                        self._rgb_feat_idx,
                        self._perkey_feat_idx,
                        self._onboard_feat_idx,
                        self._rgb_cluster_count,
                        self._profile_count,
                    )
                    return True
            try:
                dev.close()
            except Exception:
                pass
        return False

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None

    def get_dpi(self) -> int | None:
        """Read current live hardware DPI from sensor 0."""
        if not self._dev or self._dpi_feat_idx is None:
            if not self.connect():
                return None
        # Feature 0x2201, function 2 = getSensorDpi(sensorIdx=0)
        resp = self._hidpp_request(self._dev, self._device_index, self._dpi_feat_idx, 0x02, [0x00])
        if resp and len(resp) >= 7:
            return (resp[5] << 8) | resp[6]
        return None

    def set_dpi(self, dpi: int, stage_index: int | None = None) -> bool:
        """Set live hardware DPI on sensor 0 (and sync 0x8100 onboard stage index if available)."""
        if not self._dev or self._dpi_feat_idx is None:
            if not self.connect():
                return False
        dpi = max(100, min(25600, int(dpi)))
        if stage_index is not None and self._onboard_feat_idx is not None:
            if self.set_onboard_dpi_index(stage_index):
                actual = self.get_dpi()
                if actual == dpi:
                    return True
        # Feature 0x2201, function 3 = setSensorDpi(sensorIdx=0, dpiHi, dpiLo)
        resp = self._request_with_retry(
            self._dpi_feat_idx,
            0x03,
            [0x00, (dpi >> 8) & 0xFF, dpi & 0xFF],
        )
        return resp is not None

    def get_report_rate_hz(self) -> int | None:
        """Read current live hardware polling rate in Hz (1000 / 500 / 250 / 125)."""
        if not self._dev:
            if not self.connect():
                return None
        if self._rate_feat_idx is None:
            return None
        # Feature 0x8060, function 1 = getReportRate() -> resp[4] = interval in ms
        resp = self._hidpp_request(self._dev, self._device_index, self._rate_feat_idx, 0x01, [])
        if resp and len(resp) >= 5 and resp[4] > 0:
            return int(round(1000 / resp[4]))
        return None

    def get_onboard_mode(self) -> int | None:
        """Read 0x8100 (OnboardProfiles) current mode: 1 = Onboard, 2 = Host, or None."""
        if not self._dev and not self.connect():
            return None
        if self._onboard_feat_idx is None:
            return None
        resp = self._request_with_retry(self._onboard_feat_idx, 0x02, [])
        if resp and len(resp) >= 5:
            return int(resp[4])
        return None

    def set_onboard_mode(self, onboard: bool = True) -> bool:
        """Switch 0x8100 (OnboardProfiles) between Onboard Mode (1) and Host Mode (2)."""
        if not self._dev and not self.connect():
            log.warning("set_onboard_mode(onboard=%s): HID++ not connected", onboard)
            return False
        if self._onboard_feat_idx is None:
            log.warning("set_onboard_mode(onboard=%s): 0x8100 feature unavailable", onboard)
            return False
        mode_val = 0x01 if onboard else 0x02
        resp = self._request_with_retry(self._onboard_feat_idx, 0x01, [mode_val])
        ok = resp is not None
        log.info("set_onboard_mode(onboard=%s -> mode=%d): ok=%s", onboard, mode_val, ok)
        return ok

    def get_firmware_version(self) -> str | None:
        """Read main application firmware version from 0x0003 DeviceFwVersion."""
        if not self._dev and not self.connect():
            return None
        if self._fw_feat_idx is None:
            return None
        cnt_resp = self._request_with_retry(self._fw_feat_idx, 0x00, [])
        if not cnt_resp or len(cnt_resp) < 5:
            return None
        count = int(cnt_resp[4])
        for i in range(min(count, 16)):
            resp = self._request_with_retry(self._fw_feat_idx, 0x01, [i])
            if resp and len(resp) >= 12 and resp[4] == 0:
                build = (resp[10] << 8) | resp[11]
                return f"{resp[8]:x}.{resp[9]:x}.{build:x}"
        return None

    def get_onboard_profile(self) -> int | None:
        """Read active onboard memory profile slot (1.._profile_count) via 0x8100 fn=4."""
        if not self._dev and not self.connect():
            return None
        if self._onboard_feat_idx is None:
            return None
        resp = self._request_with_retry(self._onboard_feat_idx, 0x04, [])
        if resp and len(resp) >= 6:
            slot = (resp[4] << 8) | resp[5]
            return slot if 1 <= slot <= self._profile_count else 1
        return None

    def set_onboard_profile(self, slot: int) -> bool:
        """Switch active onboard memory profile slot (1.._profile_count) via 0x8100 fn=3."""
        if not self._dev and not self.connect():
            log.warning("set_onboard_profile(%d): HID++ not connected", slot)
            return False
        if self._onboard_feat_idx is None:
            log.warning("set_onboard_profile(%d): 0x8100 feature unavailable", slot)
            return False
        clamped = max(1, min(self._profile_count, int(slot)))
        resp = self._request_with_retry(self._onboard_feat_idx, 0x03, [0x00, clamped])
        ok = resp is not None
        log.info("set_onboard_profile(slot=%d): ok=%s", clamped, ok)
        return ok

    def set_onboard_dpi_index(self, idx: int) -> bool:
        """Set active onboard DPI stage index (0..4) via 0x8100 fn=11."""
        if not self._dev and not self.connect():
            log.warning("set_onboard_dpi_index(%d): HID++ not connected", idx)
            return False
        if self._onboard_feat_idx is None:
            log.warning("set_onboard_dpi_index(%d): 0x8100 feature unavailable", idx)
            return False
        clamped = max(0, min(4, int(idx)))
        resp = self._request_with_retry(self._onboard_feat_idx, 0x0B, [clamped])
        ok = resp is not None
        log.info("set_onboard_dpi_index(idx=%d): ok=%s", clamped, ok)
        return ok

    def _ensure_host_mode(self) -> None:
        """Switch 0x8100 (OnboardProfiles) to Host mode (0x02) so host settings take effect."""
        if self._onboard_feat_idx is not None:
            self._request_with_retry(self._onboard_feat_idx, 0x01, [0x02])

    def set_report_rate_hz(self, hz: int, allow_host_switch: bool = False) -> bool:
        """Set live hardware polling rate in Hz (1000 / 500 / 250 / 125)."""
        if not self._dev:
            if not self.connect():
                return False
        if self._rate_feat_idx is None:
            return False
        if allow_host_switch:
            self._ensure_host_mode()
        ms_map = {1000: 1, 500: 2, 250: 4, 125: 8}
        ms = ms_map.get(int(hz), 1)
        # Feature 0x8060, function 2 = setReportRate(ms)
        resp = self._request_with_retry(self._rate_feat_idx, 0x02, [ms])
        log.info("set_report_rate_hz(%d -> %dms, host_switch=%s): ok=%s", hz, ms, allow_host_switch, resp is not None)
        return resp is not None

    def set_rgb_mode(
        self,
        mode: str,
        r: int = 56,
        g: int = 189,
        b: int = 248,
        allow_host_switch: bool = False,
    ) -> bool:
        """
        Control LIGHTSYNC RGB via HID++ 2.0 (0x8081 PerKeyLighting or 0x8071 RGBEffects fallback).
        mode: 'Off' | 'Fixed' | 'Breathing' | 'Cycle'
        """
        if not self._dev:
            if not self.connect():
                log.warning("set_rgb_mode(%s): HID++ not connected (hid=%s)", mode, hid is not None)
                return False
        if self._rgb_feat_idx is None and self._perkey_feat_idx is None:
            log.warning("set_rgb_mode(%s): no RGB features found", mode)
            return False

        if allow_host_switch:
            self._ensure_host_mode()

        rr, gg, bb = (0, 0, 0) if mode == "Off" else (r & 0xFF, g & 0xFF, b & 0xFF)

        if self._perkey_feat_idx is not None:
            if mode == "Cycle":
                if self._rgb_feat_idx is not None:
                    resp = self._request_with_retry(self._rgb_feat_idx, 0x07, [0x00])
                    ok = resp is not None
                else:
                    ok = False
                log.info("set_rgb_mode(Cycle -> hardware control, host_switch=%s): ok=%s", allow_host_switch, ok)
                return ok

            if self._rgb_feat_idx is not None:
                self._request_with_retry(self._rgb_feat_idx, 0x07, [0x01])
            p1 = [0, rr, gg, bb, 1, rr, gg, bb, 2, rr, gg, bb, 3, rr, gg, bb]
            p2 = [4, rr, gg, bb, 5, rr, gg, bb, 6, rr, gg, bb, 7, rr, gg, bb]
            r1 = self._request_with_retry(self._perkey_feat_idx, 0x01, p1)
            r2 = self._request_with_retry(self._perkey_feat_idx, 0x01, p2)
            r_commit = self._request_with_retry(self._perkey_feat_idx, 0x04, [0x00])
            ok = (r1 is not None) and (r2 is not None) and (r_commit is not None)
            log.info(
                "set_rgb_mode(%s via PerKeyLighting, rgb=(%d,%d,%d), host_switch=%s): ok=%s",
                mode,
                rr,
                gg,
                bb,
                allow_host_switch,
                ok,
            )
            return ok

        ok_cluster = False
        if self._rgb_feat_idx is not None and self._rgb_cluster_count > 0:
            self._request_with_retry(self._rgb_feat_idx, 0x07, [0x01])
            for cluster in range(self._rgb_cluster_count):
                if mode == "Off":
                    params = [cluster, 0x00]
                elif mode == "Fixed":
                    params = [cluster, 0x01, rr, gg, bb, 0x00, 0x00]
                elif mode == "Cycle":
                    params = [cluster, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x13, 0x88, 0x64]
                elif mode == "Breathing":
                    params = [cluster, 0x0A, rr, gg, bb, 0x0B, 0xB8, 0x00, 0x64]
                else:
                    params = [cluster, 0x00]
                resp = self._request_with_retry(self._rgb_feat_idx, 0x01, params)
                if resp is not None:
                    ok_cluster = True

        log.info(
            "set_rgb_mode(%s via RGBEffects, rgb=(%d,%d,%d), host_switch=%s): ok=%s",
            mode,
            rr,
            gg,
            bb,
            allow_host_switch,
            ok_cluster,
        )
        return ok_cluster


def _probe_request(
    dev: Any,
    dev_idx: int,
    feat_idx: int,
    func_id: int,
    params: list[int] | None = None,
    timeout_ms: int = 120,
) -> list[int] | None:
    """Perform a short-timeout HID++ 2.0 request without mutating any instance state."""
    pkt = [HIDPP_LONG_REPORT_ID, dev_idx, feat_idx, ((func_id & 0x0F) << 4) | SW_ID]
    if params:
        pkt.extend(params)
    pkt.extend([0] * (HIDPP_LONG_LEN - len(pkt)))
    try:
        dev.write(pkt[:HIDPP_LONG_LEN])
    except Exception:
        return None
    for _ in range(5):
        try:
            resp = dev.read(HIDPP_LONG_LEN, timeout_ms)
        except Exception:
            return None
        if not resp:
            return None
        if len(resp) >= 4 and resp[0] in (0x10, 0x11) and resp[1] == dev_idx:
            if resp[2] == 0xFF:
                return None
            if resp[2] == feat_idx and (resp[3] & 0x0F) == SW_ID:
                return list(resp)
    return None


def _read_device_name_0005(dev: Any, dev_idx: int) -> tuple[str | None, int | None]:
    """Query HID++ feature 0x0005 for (device_name, device_type). Returns (None, None) if unsupported."""
    look = _probe_request(
        dev, dev_idx, 0x00, 0x00, [(FEATURE_DEVICE_NAME >> 8) & 0xFF, FEATURE_DEVICE_NAME & 0xFF]
    )
    if not look or look[4] == 0:
        return None, None
    name_idx = look[4]
    dev_type: int | None = None
    type_resp = _probe_request(dev, dev_idx, name_idx, 0x02)
    if type_resp:
        dev_type = int(type_resp[4])

    cnt_resp = _probe_request(dev, dev_idx, name_idx, 0x00)
    if not cnt_resp:
        return None, dev_type
    char_count = max(0, min(64, int(cnt_resp[4])))
    if char_count == 0:
        return None, dev_type

    buf = bytearray()
    offset = 0
    while len(buf) < char_count and offset < 64:
        chunk_resp = _probe_request(dev, dev_idx, name_idx, 0x01, [offset])
        if not chunk_resp:
            break
        chunk = bytes(chunk_resp[4:HIDPP_LONG_LEN])
        if not chunk:
            break
        buf.extend(chunk)
        offset += len(chunk)
    name = buf[:char_count].split(b"\x00", 1)[0].decode("utf-8", errors="ignore").strip()
    return (name or None), dev_type


def scan_hidpp_batteries() -> list[dict[str, Any]]:
    """
    Scan connected Logitech HID++ 2.0 interfaces (USB direct or Lightspeed/Unifying/Bolt receivers)
    for pointing devices reporting 0x1004 UnifiedBattery or 0x1000 BatteryLevelStatus.
    """
    if hid is None:
        return []
    try:
        all_devs = hid.enumerate(LOGITECH_VID, 0)
    except Exception:
        return []

    long_devs = [d for d in all_devs if d.get("usage_page", 0) >= 0xFF00 and d.get("usage") == 2]
    other_devs = [d for d in all_devs if d.get("usage_page", 0) >= 0xFF00 and d not in long_devs]

    devices: list[dict[str, Any]] = []
    seen_paths: set[Any] = set()
    seen_slugs: set[str] = set()
    non_mouse_types = {0, 1, 2, 6, 7, 8, 9, 10, 11, 12, 13, 14}

    for info in long_devs + other_devs:
        path = info.get("path")
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)

        dev = hid.device()
        try:
            dev.open_path(path)
            dev.set_nonblocking(0)
        except Exception:
            continue

        try:
            prod_str = str(info.get("product_string") or "").strip()
            pid = int(info.get("product_id") or 0)
            for dev_idx in (0xFF, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06):
                pct: int | None = None
                charging = False

                ubat_look = _probe_request(
                    dev,
                    dev_idx,
                    0x00,
                    0x00,
                    [(FEATURE_UNIFIED_BATTERY >> 8) & 0xFF, FEATURE_UNIFIED_BATTERY & 0xFF],
                )
                if ubat_look and ubat_look[4] != 0:
                    st = _probe_request(dev, dev_idx, ubat_look[4], 0x01)
                    if st and 0 <= int(st[4]) <= 100:
                        pct = int(st[4])
                        charging = int(st[6]) in (1, 2, 3)

                if pct is None:
                    bat_look = _probe_request(
                        dev,
                        dev_idx,
                        0x00,
                        0x00,
                        [(FEATURE_BATTERY_STATUS >> 8) & 0xFF, FEATURE_BATTERY_STATUS & 0xFF],
                    )
                    if bat_look and bat_look[4] != 0:
                        st = _probe_request(dev, dev_idx, bat_look[4], 0x00)
                        if st and 0 <= int(st[4]) <= 100:
                            pct = int(st[4])
                            charging = int(st[6]) in (1, 2, 3)

                if pct is None:
                    continue

                hw_name, dev_type = _read_device_name_0005(dev, dev_idx)
                if dev_type in non_mouse_types:
                    continue

                display_name = (hw_name or prod_str or f"Logitech HID++ Mouse ({pid:04X})").strip()
                slug = "".join(ch if ch.isalnum() else "-" for ch in display_name.lower()).strip("-") or f"hidpp-{pid:04x}-{dev_idx}"
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                devices.append(
                    {
                        "device": slug,
                        "display_name": display_name.upper(),
                        "percentage": float(pct),
                        "is_charging": charging,
                        "source": "hidpp",
                        "connection": "usb" if dev_idx == 0xFF else "lightspeed",
                        "vendor_id": LOGITECH_VID,
                        "product_id": pid,
                    }
                )
                # Stop probing receiver indices once a direct USB interface answers on 0xFF
                if dev_idx == 0xFF:
                    break
        except Exception:
            pass
        finally:
            try:
                dev.close()
            except Exception:
                pass

    return devices


if __name__ == "__main__":
    m = HidppMouse()
    ok = m.connect()
    print("Connected:", ok, "dpi_feat:", m._dpi_feat_idx, "rate_feat:", m._rate_feat_idx)
    if ok:
        print("Live Hardware DPI:", m.get_dpi())
        print("Live Hardware Report Rate (Hz):", m.get_report_rate_hz())
        m.close()
