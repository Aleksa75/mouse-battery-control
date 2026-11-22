"""
Mouse Battery & Control — Modern Windows System Tray Application
- Live color-coded battery percentage icon in the Windows system tray
- Sleek dark-mode Dashboard with circular battery gauge & interactive Battery History chart
- Notification settings with custom Windows Toast sounds & live preview
- Mouse Control with one-click presets (Gaming / Precision / Productivity) & Win32 pointer tuning
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import math
import sys
import textwrap
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw, ImageFont, ImageGrab, ImageTk

import easter_eggs
import hidpp_mouse
import i18n
import icon_fetcher
import monitor
import mouse_features
import telemetry
import theme
import updater

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
APP_VERSION = "2.28.0"
LOG_PATH = BASE_DIR / "app.log"


def _short_device_name(name: str, max_len: int = 24) -> str:
    clean = " ".join(str(name or "").split()).strip()
    if len(clean) <= max_len:
        return clean
    return clean[: max(1, max_len - 1)].rstrip() + "…"


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    a = max(0, min(255, int(alpha)))
    if len(h) != 6:
        return (148, 163, 184, a)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def compute_chart_time_ticks(
    pad_l: float,
    plot_w: float,
    t_view_min: float,
    t_view_max: float,
    label_w: float,
    min_gap_px: float = 80.0,
) -> list[tuple[float, float, str]]:
    """
    Compute dynamically spaced (x_px, timestamp_s, tk_anchor) X-axis time spots
    so labels never overlap and maintain >= min_gap_px edge-to-edge clearance.
    """
    span_t = float(t_view_max) - float(t_view_min)
    pw = max(1.0, float(plot_w))
    min_step = max(40.0, 1.5 * float(label_w) + float(min_gap_px))
    n_intervals = max(1, int(pw // min_step))

    ticks: list[tuple[float, float, str]] = [(float(pad_l), float(t_view_min), "w")]
    for k in range(1, n_intervals):
        frac = k / n_intervals
        ticks.append((float(pad_l) + frac * pw, float(t_view_min) + frac * span_t, "center"))
    ticks.append((float(pad_l) + pw, float(t_view_max), "e"))
    return ticks


def _monotone_smooth(pts: list[tuple[float, float]], samples_per_seg: int = 6) -> list[tuple[float, float]]:
    """Clamped Fritsch-Carlson monotone cubic Hermite interpolation for overshoot-free smooth curves."""
    n = len(pts)
    if n <= 2 or samples_per_seg <= 1:
        return list(pts)

    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    hs = [xs[i + 1] - xs[i] for i in range(n - 1)]
    ds = [((ys[i + 1] - ys[i]) / hs[i]) if hs[i] > 1e-6 else 0.0 for i in range(n - 1)]

    ms = [0.0] * n
    ms[0] = ds[0]
    ms[n - 1] = ds[n - 2]
    for i in range(1, n - 1):
        if ds[i - 1] * ds[i] <= 0.0 or hs[i - 1] <= 1e-6 or hs[i] <= 1e-6:
            ms[i] = 0.0
        else:
            ms[i] = 0.5 * (ds[i - 1] + ds[i])

    for i in range(n - 1):
        if abs(ds[i]) < 1e-9 or hs[i] <= 1e-6:
            ms[i] = 0.0
            ms[i + 1] = 0.0
        else:
            a = ms[i] / ds[i]
            b = ms[i + 1] / ds[i]
            s = a * a + b * b
            if s > 9.0:
                t = 3.0 / math.sqrt(s)
                ms[i] = t * a * ds[i]
                ms[i + 1] = t * b * ds[i]

    out: list[tuple[float, float]] = []
    for i in range(n - 1):
        h = hs[i]
        y0, y1 = ys[i], ys[i + 1]
        m0, m1 = ms[i], ms[i + 1]
        y_lo, y_hi = (y0, y1) if y0 <= y1 else (y1, y0)
        for k in range(samples_per_seg):
            u = k / samples_per_seg
            u2 = u * u
            u3 = u2 * u
            h00 = 2.0 * u3 - 3.0 * u2 + 1.0
            h10 = u3 - 2.0 * u2 + u
            h01 = -2.0 * u3 + 3.0 * u2
            h11 = u3 - u2
            x = xs[i] + u * h
            y = h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1
            y = max(y_lo, min(y_hi, y))
            out.append((x, y))
    out.append((xs[-1], ys[-1]))
    return out


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("MouseBatteryControl")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        try:
            fh = RotatingFileHandler(LOG_PATH, maxBytes=512_000, backupCount=2, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            logger.addHandler(fh)
        except Exception:
            pass
    return logger


log = _setup_logging()

RGB_MODES = ["Off (Eco)", "Fixed", "Breathing", "Cycle"]
RGB_SWATCHES = [
    ("Cyan", "#38BDF8", (56, 189, 248)),
    ("Green", "#22C55E", (34, 197, 94)),
    ("Purple", "#A855F7", (168, 85, 247)),
    ("Red", "#EF4444", (239, 68, 68)),
    ("Amber", "#F59E0B", (245, 158, 11)),
    ("White", "#F8FAFC", (255, 255, 255)),
]

DPI_STAGES = [
    (800, "#E2E8F0"),
    (1200, "#F97316"),
    (1600, "#2DD4BF"),
    (2400, "#FACC15"),
    (3200, "#C084FC"),
]
DPI_STAGES_LIGHT = [
    (800, "#334155"),
    (1200, "#C2410C"),
    (1600, "#0F766E"),
    (2400, "#854D0E"),
    (3200, "#7E22CE"),
]
REPORT_RATES = ["1000 Hz", "500 Hz", "250 Hz", "125 Hz"]

# Centralized Theme Registry (shared via theme.py)
THEMES = theme.THEMES
apply_win_titlebar_theme = theme.apply_win_titlebar_theme

BG = THEMES["Dark"]["BG"]
CARD = THEMES["Dark"]["CARD"]
CARD_ALT = THEMES["Dark"]["CARD_ALT"]
BORDER = THEMES["Dark"]["BORDER"]
FG = THEMES["Dark"]["FG"]
FG_MUTED = THEMES["Dark"]["FG_MUTED"]
ACCENT = THEMES["Dark"]["ACCENT"]
ACCENT_HOVER = THEMES["Dark"]["ACCENT_HOVER"]
ACCENT_TEXT = THEMES["Dark"]["ACCENT_TEXT"]
GREEN = THEMES["Dark"]["GREEN"]
AMBER = THEMES["Dark"]["AMBER"]
RED = THEMES["Dark"]["RED"]
CHART_FILL = THEMES["Dark"]["CHART_FILL"]
GRID_MAJOR = THEMES["Dark"]["GRID_MAJOR"]
GRID_MINOR = THEMES["Dark"]["GRID_MINOR"]
PLAYHEAD = THEMES["Dark"]["PLAYHEAD"]
TIP_BG = THEMES["Dark"]["TIP_BG"]
SEG_SELECTED = THEMES["Dark"]["SEG_SELECTED"]
SEG_SELECTED_HOVER = THEMES["Dark"]["SEG_SELECTED_HOVER"]
SWITCH_BUTTON = THEMES["Dark"]["SWITCH_BUTTON"]
SWITCH_BUTTON_HOVER = THEMES["Dark"]["SWITCH_BUTTON_HOVER"]
SWITCH_TRACK_OFF = THEMES["Dark"]["SWITCH_TRACK_OFF"]


def apply_theme_tokens(mode: str, update_ctk_mode: bool = True, accent_mode: str | None = None) -> str:
    """Resolve 'System' | 'Dark' | 'Light' | 'Matrix' and update global design tokens."""
    if accent_mode is not None:
        theme.set_accent_mode(accent_mode)
    resolved = theme.resolve_theme(mode)
    if update_ctk_mode:
        ctk.set_appearance_mode("light" if resolved == "Light" else "dark")
    globals().update(theme.get_palette(resolved))
    return resolved

MOUSE_PRESETS: dict[str, dict[str, Any]] = {
    "Gaming": {
        "desc": "Raw input • Accel OFF",
        "speed": 10,
        "accel": False,
        "scroll": 3,
        "tooltip": (
            "Gaming Preset\n"
            "• Pointer Speed: 10 (1:1 Windows default)\n"
            "• Acceleration: OFF (raw, predictable aim)\n"
            "• Scroll: 3 lines per notch\n"
            "Best for FPS and fast-paced games."
        ),
    },
    "Precision": {
        "desc": "Fine control • Accel OFF",
        "speed": 8,
        "accel": False,
        "scroll": 3,
        "tooltip": (
            "Precision Preset\n"
            "• Pointer Speed: 8 (slower, finer control)\n"
            "• Acceleration: OFF (consistent movement)\n"
            "• Scroll: 3 lines per notch\n"
            "Best for design, photo editing, and pixel-accurate work."
        ),
    },
    "Productivity": {
        "desc": "Fast travel • Accel ON",
        "speed": 14,
        "accel": True,
        "scroll": 6,
        "tooltip": (
            "Productivity Preset\n"
            "• Pointer Speed: 14 (faster cursor travel)\n"
            "• Acceleration: ON (quick across multi-monitors)\n"
            "• Scroll: 6 lines per notch (faster scrolling)\n"
            "Best for browsing, coding, and wide/multi-monitor setups."
        ),
    },
}


class DelayedTooltip:
    """Dark-themed floating tooltip that appears after a configurable hover delay."""

    def __init__(self, widget: Any, text: str, delay_ms: int = 1600) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._tip_win: tk.Toplevel | None = None

        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._cancel, add="+")
        widget.bind("<ButtonPress>", self._cancel, add="+")

    def _schedule(self, event: Any = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self, event: Any = None) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip_win is not None:
            try:
                self._tip_win.destroy()
            except Exception:
                pass
            self._tip_win = None

    def _show(self) -> None:
        if self._tip_win is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        except Exception:
            return

        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_attributes("-topmost", True)
        chroma = "#010203"
        tw.configure(bg=chroma)
        try:
            tw.wm_attributes("-transparentcolor", chroma)
        except Exception:
            pass

        card = ctk.CTkFrame(
            tw,
            fg_color=TIP_BG,
            border_color=BORDER,
            border_width=1,
            corner_radius=10,
            bg_color=chroma,
        )
        card.pack()

        ctk.CTkLabel(
            card,
            text=self.text,
            justify="left",
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11),
        ).pack(padx=12, pady=8)

        tw.update_idletasks()
        tip_w = tw.winfo_reqwidth()
        tip_h = tw.winfo_reqheight()
        screen_w = tw.winfo_screenwidth()
        screen_h = tw.winfo_screenheight()
        if x + tip_w > screen_w - 12:
            x = max(12, screen_w - tip_w - 12)
        if y + tip_h > screen_h - 48:
            y = max(12, self.widget.winfo_rooty() - tip_h - 8)

        tw.wm_geometry(f"+{x}+{y}")
        self._tip_win = tw


class DraggableTabBar(ctk.CTkFrame):
    """Equal-width tab bar supporting hold-and-drag live reordering and right-click reset."""

    DRAG_THRESHOLD_PX = 8

    def __init__(
        self,
        master: Any,
        items: list[tuple[str, str]],
        active_key: str,
        on_select: Callable[[str], None] | None = None,
        on_reorder: Callable[[list[str]], None] | None = None,
        on_reset: Callable[[], None] | None = None,
        palette: dict[str, str] | None = None,
        height: int = 36,
    ) -> None:
        pal = palette or {
            "CARD": CARD,
            "BORDER": BORDER,
            "SEG_SELECTED": SEG_SELECTED,
            "SEG_SELECTED_HOVER": SEG_SELECTED_HOVER,
            "FG": FG,
            "ACCENT": ACCENT,
        }
        super().__init__(
            master,
            fg_color=pal["CARD"],
            border_color=pal["BORDER"],
            border_width=1,
            corner_radius=10,
            height=height,
        )
        self.grid_propagate(False)
        self.grid_rowconfigure(0, weight=1)

        self._pal = pal
        self._items_map: dict[str, str] = {k: lbl for k, lbl in items}
        self._order: list[str] = [k for k, _ in items]
        self._active_key: str = active_key if active_key in self._items_map else (self._order[0] if self._order else "")
        self._on_select = on_select
        self._on_reorder = on_reorder
        self._on_reset = on_reset

        self._buttons: dict[str, ctk.CTkButton] = {}
        self._drag_key: str | None = None
        self._press_x_root: int = 0
        self._orig_order: list[str] = list(self._order)
        self._dragging: bool = False
        self._tooltip: DelayedTooltip | None = None

        btn_h = max(26, height - 6)
        tab_font = ctk.CTkFont("Segoe UI", 11, "bold")
        for col, (key, label) in enumerate(items):
            self.grid_columnconfigure(col, weight=1, uniform="tabs")
            btn = ctk.CTkButton(
                self,
                text=label,
                command=None,
                font=tab_font,
                height=btn_h,
                corner_radius=8,
                text_color=pal["FG"],
                fg_color=pal["CARD"],
                hover_color=pal["BORDER"],
                cursor="hand2",
                border_width=0,
            )
            self._buttons[key] = btn
            for target in (btn, getattr(btn, "_canvas", None), getattr(btn, "_text_label", None)):
                if target is None:
                    continue
                target.bind("<ButtonPress-1>", lambda e, k=key: self._on_press(k, e), add="+")
                target.bind("<B1-Motion>", lambda e, k=key: self._on_motion(e), add="+")
                target.bind("<ButtonRelease-1>", lambda e, k=key: self._on_release(e), add="+")
                target.bind("<Button-3>", lambda e: self._on_right_click(e), add="+")

        self._layout_tabs()
        self._apply_styles()

        try:
            top = self.winfo_toplevel()
            top.bind("<Escape>", lambda _e: self.cancel_drag(), add="+")
        except Exception:
            pass

    def attach_tooltip(self, tooltip: DelayedTooltip) -> None:
        """Forward hover/press events from child tab buttons to a shared DelayedTooltip."""
        self._tooltip = tooltip
        for btn in self._buttons.values():
            for target in (btn, getattr(btn, "_canvas", None), getattr(btn, "_text_label", None)):
                if target is None:
                    continue
                target.bind("<Enter>", tooltip._schedule, add="+")
                target.bind("<Leave>", tooltip._cancel, add="+")
                target.bind("<ButtonPress>", tooltip._cancel, add="+")

    def get_order(self) -> list[str]:
        return list(self._order)

    def set_order(self, order: list[str]) -> None:
        valid = [k for k in order if k in self._buttons]
        for k in self._order:
            if k not in valid:
                valid.append(k)
        if valid != self._order:
            self._order = valid
            self._layout_tabs()
            self._apply_styles()

    def set_active(self, key: str) -> None:
        if key in self._buttons and key != self._active_key:
            self._active_key = key
            self._apply_styles()

    def reorder_by_slot(self, key: str, target_idx: int) -> bool:
        """Move tab `key` to `target_idx` (0..n-1) and re-grid live. Returns True if order changed."""
        if key not in self._order or not self._order:
            return False
        clamped = max(0, min(len(self._order) - 1, int(target_idx)))
        cur_idx = self._order.index(key)
        if clamped == cur_idx:
            return False
        self._order.pop(cur_idx)
        self._order.insert(clamped, key)
        self._layout_tabs()
        return True

    def _layout_tabs(self) -> None:
        n = len(self._order)
        for col, key in enumerate(self._order):
            btn = self._buttons[key]
            btn.grid(
                row=0,
                column=col,
                sticky="nsew",
                padx=(3 if col == 0 else 2, 3 if col == n - 1 else 2),
                pady=3,
            )

    def _apply_styles(self) -> None:
        pal = self._pal
        for key, btn in self._buttons.items():
            is_active = key == self._active_key
            is_dragged = self._dragging and key == self._drag_key
            try:
                btn.configure(
                    fg_color=pal["SEG_SELECTED"] if is_active else pal["CARD"],
                    hover_color=pal["SEG_SELECTED_HOVER"] if is_active else pal["BORDER"],
                    text_color=pal["FG"],
                    border_width=2 if is_dragged else 0,
                    border_color=pal["ACCENT"] if is_dragged else pal["CARD"],
                    cursor="sb_h_double_arrow" if self._dragging else "hand2",
                )
            except Exception:
                pass
        try:
            self.configure(cursor="sb_h_double_arrow" if self._dragging else "hand2")
        except Exception:
            pass

    def _on_press(self, key: str, event: Any) -> None:
        if self._tooltip is not None:
            self._tooltip._cancel()
        self._drag_key = key
        self._press_x_root = int(getattr(event, "x_root", 0))
        self._orig_order = list(self._order)
        self._dragging = False

    def _on_motion(self, event: Any) -> None:
        if not self._drag_key or not self._order:
            return
        xr = int(getattr(event, "x_root", self._press_x_root))
        if not self._dragging:
            if abs(xr - self._press_x_root) < self.DRAG_THRESHOLD_PX:
                return
            self._dragging = True
            self._apply_styles()

        try:
            bar_x = self.winfo_rootx()
            bar_w = max(1, self.winfo_width())
        except Exception:
            return
        n = len(self._order)
        slot_w = bar_w / n
        target_idx = max(0, min(n - 1, int((xr - bar_x) / slot_w)))
        self.reorder_by_slot(self._drag_key, target_idx)

    def _on_release(self, event: Any = None) -> None:
        key = self._drag_key
        was_dragging = self._dragging
        changed = was_dragging and (self._order != self._orig_order)
        self._drag_key = None
        self._dragging = False
        self._apply_styles()

        if was_dragging:
            if changed and callable(self._on_reorder):
                self._on_reorder(list(self._order))
        elif key:
            self.set_active(key)
            if callable(self._on_select):
                self._on_select(key)

    def cancel_drag(self) -> None:
        if not self._dragging:
            return
        self._order = list(self._orig_order)
        self._drag_key = None
        self._dragging = False
        self._layout_tabs()
        self._apply_styles()

    def _on_right_click(self, _event: Any = None) -> None:
        if callable(self._on_reset) and self._order != monitor.DEFAULT_TAB_ORDER:
            self._on_reset()


def render_tray_icon(pct: int | None, is_charging: bool = False) -> Image.Image:
    """Render a crisp 64x64 system tray icon showing the battery percentage."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if pct is None:
        fill = "#64748B"
        label = "?"
    else:
        label = str(int(round(pct)))
        if is_charging:
            fill = ACCENT
        elif pct <= 20:
            fill = RED
        elif pct <= 40:
            fill = AMBER
        else:
            fill = GREEN

    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=15, fill="#0F1117", outline=fill, width=4)
    if is_charging:
        draw.rounded_rectangle((18, 7, size - 19, 12), radius=2, fill=ACCENT)

    font_size = 23 if len(label) >= 3 else 30
    font = None
    for font_name in ("segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), label, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1] + (2 if is_charging else 0)
    draw.text((tx, ty), label, fill=fill, font=font)
    return img


class MouseBatteryTrayApp:
    def __init__(self) -> None:
        self.cfg: dict[str, Any] = monitor.load_config()
        raw_lang = str(self.cfg.get("language", "en"))
        self._lang: str = raw_lang if raw_lang in i18n.LANG_LABELS else "en"
        self._resolved_theme: str = apply_theme_tokens(
            str(self.cfg.get("theme", "Dark")),
            accent_mode=str(self.cfg.get("accent_mode", "Windows")),
        )
        ctk.set_default_color_theme("blue")
        saved_state = monitor.load_state()
        raw_snap = saved_state.get("_last_ui_snapshot")
        hidden_init = set(self.cfg.get("hidden_devices", []))
        snap = raw_snap if isinstance(raw_snap, dict) and raw_snap.get("device_slug") not in hidden_init else None
        self.latest_result: dict[str, Any] | None = snap if isinstance(snap, dict) else None
        self.all_results: list[dict[str, Any]] = [snap] if isinstance(snap, dict) else []
        self.selected_device_idx: int = 0
        self._selected_device_slug: str | None = snap.get("device_slug") if isinstance(snap, dict) else None
        self._device_popover: ctk.CTkToplevel | None = None
        self._device_pill_tooltip: DelayedTooltip | None = None
        self._icon_fetch_attempted: set[str] = set()
        self.stop_event = threading.Event()
        self.poll_wakeup = threading.Event()
        self.chart_range_hours = 24

        # Hidden CTk root on main thread
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.title("Mouse Battery & Control")

        self.win: ctk.CTkToplevel | None = None
        self.pages: dict[str, ctk.CTkFrame] = {}
        self._vars: dict[str, Any] = {}
        self._widgets: dict[str, Any] = {}
        self._gauge_canvas: tk.Canvas | None = None
        self._chart_canvas: tk.Canvas | None = None
        self._gauge_photo: Any = None
        self._chart_photo: Any = None
        self._conn_canvas: tk.Canvas | None = None
        self._conn_tooltip: DelayedTooltip | None = None
        self._chart_meta: dict[str, Any] = {}
        self._chart_zoom: tuple[float, float] | None = None
        self._chart_resize_after_id: str | None = None
        self._last_chart_size: tuple[int, int] = (0, 0)
        self._axis_font: tkfont.Font | None = None
        self._dpi_buttons: dict[int, ctk.CTkButton] = {}
        self._dpi_underlines: dict[int, ctk.CTkFrame] = {}
        self._accel_to_lbl: dict[str, str] = {}
        self._mode_to_lbl: dict[str, str] = {}
        self._rgb_to_lbl: dict[str, str] = {}
        self._active_page = "Dashboard"
        self.hidpp = hidpp_mouse.HidppMouse()
        self._hidpp_lock = threading.Lock()
        self._hidpp_mode_synced: bool = False
        self._hidpp_hw_mode: int | None = None
        self._hidpp_fw_version: str | None = None
        self._last_polled_dpi: int | None = None
        self._cloud: Any = None
        self._built_pages: set[str] = set()
        self._icon_cache: dict[tuple[str, str], ctk.CTkImage] = {}
        self._gauge_cache_key: tuple[Any, ...] | None = None
        self.telemetry = telemetry.ActionTelemetry(BASE_DIR / "telemetry.jsonl")
        self._active_seconds_accum: float = 0.0
        self._active_lock = threading.Lock()
        self._toast_label: ctk.CTkLabel | None = None
        self._toast_after_id: str | None = None
        self._transition_overlay: tk.Toplevel | None = None
        self._transition_photo: Any = None
        self._transition_after_id: str | None = None
        self._key_seq = easter_eggs.KeySequenceTracker()
        self._gauge_clicks = easter_eggs.ClickBurstTracker()
        self._title_clicks = easter_eggs.ClickBurstTracker()
        self._about_ver_clicks = easter_eggs.ClickBurstTracker()
        self._gauge_spin_after_id: str | None = None
        self._konami_canvas: tk.Canvas | None = None
        self._available_update: dict[str, Any] | None = None
        self._update_tooltip: DelayedTooltip | None = None
        self._last_update_check_ts: float = 0.0

        self.icon = pystray.Icon(
            "MouseBatteryTray",
            render_tray_icon(None, False),
            "Mouse Battery & Control — Loading...",
            menu=self._build_menu(),
        )

    @property
    def cloud(self) -> Any:
        if self._cloud is None:
            import cloud_sync

            self._cloud = cloud_sync.GoogleCloudSync(BASE_DIR)
        return self._cloud

    def _record_telemetry(
        self,
        action: str,
        requested: Any = None,
        api_ok: bool | None = None,
        actual: Any = None,
        verified: bool | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Record a user/hardware action into telemetry.jsonl without interrupting UI responsiveness."""
        try:
            return self.telemetry.record(
                action=action,
                requested=requested,
                api_ok=api_ok,
                actual=actual,
                verified=verified,
                version=APP_VERSION,
                extra=extra,
            )
        except Exception:
            return None

    def _t(self, key: str, /, **kwargs: Any) -> str:
        return i18n.tr(self._lang, key, **kwargs)

    def _dpi_stages(self) -> list[tuple[int, str]]:
        return DPI_STAGES_LIGHT if self._resolved_theme == "Light" else DPI_STAGES

    def _icon_path(self) -> Path | None:
        for candidate in (RESOURCE_DIR / "app.ico", BASE_DIR / "app.ico"):
            if candidate.exists():
                return candidate
        return None

    def _dialog_parent(self) -> Any:
        return self.win if (self.win and self.win.winfo_exists()) else self.root

    def _status_summary_text(self) -> str:
        if not self.latest_result:
            return self._t("no_battery_data")
        r = self.latest_result
        if r.get("percentage") is None:
            return f"{r['device']}: {self._t('battery_unavailable')}"
        chg = self._t("tray_charging") if r["is_charging"] else ""
        return self._t("tray_left_fmt", device=r["device"], pct=r["percentage"], chg=chg, time=r["time_left_str"])

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda _: self._status_summary_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: self._t("tray_open"), self._on_open_settings, default=True),
            pystray.MenuItem(lambda _: self._t("tray_refresh"), self._on_refresh_now),
            pystray.MenuItem(lambda _: self._t("tray_test_notify"), self._on_test_notify),
            pystray.MenuItem(lambda _: self._t("tray_open_ghub"), self._on_open_lghub),
            pystray.MenuItem(
                lambda _: (
                    self._t("tray_update_available", version=self._available_update.get("latest_version", ""))
                    if self._available_update and self._available_update.get("status") == "update_available"
                    else self._t("tray_check_updates")
                ),
                self._on_check_updates,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: self._t("tray_quit"), self._on_quit),
        )

    # --- Tray Callbacks ---
    def _on_open_settings(self, icon: Any = None, item: Any = None) -> None:
        self.root.after(0, self.show_window)

    def _on_refresh_now(self, icon: Any = None, item: Any = None) -> None:
        threading.Thread(target=self.check_battery, kwargs={"force_notify": False}, daemon=True).start()

    def _on_test_notify(self, icon: Any = None, item: Any = None) -> None:
        threading.Thread(target=self.check_battery, kwargs={"force_notify": True}, daemon=True).start()

    def _on_open_lghub(self, icon: Any = None, item: Any = None) -> None:
        mouse_features.open_lghub()

    def _check_updates_silent_if_due(self, min_interval_s: float = 900.0) -> None:
        now = time.monotonic()
        if (now - self._last_update_check_ts) < min_interval_s:
            return
        self._last_update_check_ts = now
        threading.Thread(target=self._run_update_check, kwargs={"silent": True}, daemon=True).start()

    def _on_check_updates(self, icon: Any = None, item: Any = None) -> None:
        self.root.after(0, lambda: self._flash_status(self._t("checking_updates"), ACCENT))
        threading.Thread(target=self._run_update_check, kwargs={"silent": False}, daemon=True).start()

    def _run_update_check(self, silent: bool = False) -> None:
        self._last_update_check_ts = time.monotonic()
        cfg = monitor.load_config()
        src = cfg.get("update_source")
        if silent and (not src or not str(src).strip()):
            return
        res = updater.check_for_update(APP_VERSION, src)
        self.root.after(0, self._handle_update_result, res, silent)

    def _refresh_update_button(self) -> None:
        btn = self._widgets.get("update_btn")
        if not btn:
            return
        upd = self._available_update
        if upd and upd.get("status") == "update_available":
            btn.configure(
                text=self._t("update_available_btn"),
                fg_color=CARD_ALT,
                hover_color=BORDER,
                text_color=GREEN,
            )
            ver = str(upd.get("latest_version", "")).strip()
            raw_notes = str(upd.get("notes") or self._t("update_default_notes")).strip()
            wrapped_lines = [textwrap.fill(line.strip(), width=54) for line in raw_notes.splitlines() if line.strip()]
            wrapped_notes = "\n".join(wrapped_lines)
            if len(wrapped_notes) > 300:
                wrapped_notes = wrapped_notes[:297].rstrip() + "..."
            tip = f"{self._t('update_tip_header', version=ver)}\n\n{wrapped_notes}\n\n{self._t('update_tip_click')}"
        else:
            btn.configure(
                text=self._t("check_updates"),
                fg_color="transparent",
                hover_color=CARD_ALT,
                text_color=ACCENT,
            )
            tip = self._t("check_updates_tip")
        if self._update_tooltip:
            self._update_tooltip.text = tip

    def _handle_update_result(self, res: dict[str, Any], silent: bool = False) -> None:
        status = res.get("status")
        msg = res.get("message", "")
        if status == "update_available":
            self._available_update = res
            self._refresh_update_button()
            if self.icon:
                try:
                    self.icon.update_menu()
                except Exception:
                    pass
            if silent:
                return
            notes = res.get("notes") or self._t("update_default_notes")
            prompt = f"{msg}\n\n{notes}\n\n{self._t('update_prompt_tail')}"
            parent = self._dialog_parent()
            if theme.ask_yes_no(
                parent,
                self._t("update_avail_title"),
                prompt,
                self._resolved_theme,
                icon_path=self._icon_path(),
                yes_text=self._t("update_now"),
                no_text=self._t("later"),
            ):
                ok, info = updater.download_and_apply_update(
                    res.get("download_url", ""),
                    expected_sha256=res.get("sha256", ""),
                    package_type=res.get("package_type"),
                )
                if ok:
                    self._flash_status(info, GREEN)
                    self.root.after(300, self._on_quit)
                else:
                    theme.show_error(
                        parent,
                        self._t("update_failed_title"),
                        info,
                        self._resolved_theme,
                        icon_path=self._icon_path(),
                    )
        elif status == "up_to_date":
            self._available_update = None
            self._refresh_update_button()
            if self.icon:
                try:
                    self.icon.update_menu()
                except Exception:
                    pass
            if not silent:
                self._flash_status(f"✓ {msg}", GREEN)
        elif not silent:
            if status == "not_configured":
                self._flash_status(self._t("updates_not_configured"), AMBER)
            else:
                self._flash_status(msg[:65], RED)

    def _cancel_easter_eggs(self) -> None:
        if self._gauge_spin_after_id is not None:
            try:
                self.root.after_cancel(self._gauge_spin_after_id)
            except Exception:
                pass
            self._gauge_spin_after_id = None
        kc = self._konami_canvas
        self._konami_canvas = None
        if kc is not None:
            try:
                if kc.winfo_exists():
                    kc.destroy()
            except Exception:
                pass
        dp = getattr(self, "_device_popover", None)
        self._device_popover = None
        if dp is not None:
            try:
                if dp.winfo_exists():
                    dp.destroy()
            except Exception:
                pass

    def _on_window_close(self) -> None:
        self._cancel_theme_transition()
        self._cancel_easter_eggs()
        if self.cfg.get("close_to_tray", True):
            if self.win and self.win.winfo_exists():
                self.win.withdraw()
        else:
            self._on_quit()

    def _on_quit(self, icon: Any = None, item: Any = None) -> None:
        self._cancel_theme_transition()
        self._cancel_easter_eggs()
        self.stop_event.set()
        self.poll_wakeup.set()
        try:
            self.hidpp.close()
        except Exception:
            pass
        try:
            self.icon.stop()
        except Exception:
            pass
        self.root.after(0, self.root.quit)

    # --- Background Polling (2-Stage: Fast Local + Async PnP/Bluetooth) ---
    def check_battery(self, force_notify: bool = False) -> None:
        cfg = monitor.load_config()
        self.cfg = cfg
        filt = cfg.get("device_filter")

        def _apply_filter(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not filt:
                return items
            f_low = str(filt).lower()
            return [d for d in items if f_low in str(d.get("device", "")).lower()]

        # Stage 1: Fast local sources (G HUB SQLite + direct HID++ + standard USB HID)
        lghub_devs = _apply_filter(monitor.read_lghub_batteries())
        with self._hidpp_lock:
            hidpp_devs = _apply_filter(hidpp_mouse.scan_hidpp_batteries())
            live_hz = self.hidpp.get_report_rate_hz()
        if live_hz is not None:
            cfg["report_rate"] = f"{live_hz} Hz"
        hid_devs = _apply_filter(monitor.read_hid_mice())

        fast_devices = monitor.merge_discovered_mice(lghub_devs, hidpp_devs, hid_devs)
        if fast_devices:
            self._process_and_publish_devices(
                fast_devices, cfg, force_notify=force_notify, report_rate_hz=live_hz
            )

        # Stage 2: Native Windows Bluetooth/BLE/PnP ContainerId discovery
        bt_devs = _apply_filter(monitor.read_bluetooth_mouse_batteries())
        merged = monitor.merge_discovered_mice(lghub_devs, hidpp_devs, bt_devs, hid_devs)

        if merged:
            if bt_devs or not fast_devices:
                self._process_and_publish_devices(
                    merged, cfg, force_notify=force_notify, report_rate_hz=live_hz
                )
        else:
            self.all_results = []
            self.latest_result = None
            self.root.after(0, self._update_tray_and_ui, None)

    def _process_and_publish_devices(
        self,
        devices: list[dict[str, Any]],
        cfg: dict[str, Any],
        force_notify: bool = False,
        report_rate_hz: int | None = None,
    ) -> None:
        hidden = set(cfg.get("hidden_devices", []))
        devices = [d for d in devices if d.get("device") not in hidden]
        if not devices:
            self.all_results = []
            self.selected_device_idx = 0
            self.latest_result = None
            self._selected_device_slug = None
            self.root.after(0, self._update_tray_and_ui, None)
            return

        history = monitor.load_history(int(cfg.get("max_history_days", 30)))
        state = monitor.load_state()
        notifications_enabled = bool(cfg.get("notifications_enabled", True))
        cfg_hz = monitor.parse_report_rate_hz(cfg.get("report_rate", 1000))
        with self._active_lock:
            active_delta = self._active_seconds_accum
            self._active_seconds_accum = 0.0

        results: list[dict[str, Any]] = []
        for dev in devices:
            dev_hz = (
                (report_rate_hz if report_rate_hz is not None else cfg_hz)
                if dev.get("source") in ("lghub", "hidpp")
                else None
            )
            history = monitor.append_history(
                dev,
                history,
                int(cfg.get("max_history_days", 30)),
                report_rate_hz=dev_hz,
                active_seconds=(active_delta if active_delta > 0 else None),
            )
            res = monitor.evaluate_device(
                dev,
                cfg,
                history,
                state,
                force_notify=force_notify,
                dry_run=(not notifications_enabled and not force_notify),
                report_rate_hz=dev_hz,
            )
            results.append(res)

        if results:
            state["_last_ui_snapshot"] = results[0]
        monitor.save_state(state)
        self.all_results = results
        if results and self._selected_device_slug:
            match_idx = next(
                (i for i, item in enumerate(results) if item.get("device_slug") == self._selected_device_slug),
                None,
            )
            if match_idx is not None:
                self.selected_device_idx = match_idx
        if self.selected_device_idx >= len(results):
            self.selected_device_idx = 0
        self.latest_result = results[self.selected_device_idx] if results else None
        if self.latest_result:
            self._selected_device_slug = self.latest_result.get("device_slug")
        self.root.after(0, self._update_tray_and_ui, self.latest_result)

    def _poll_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.check_battery(force_notify=False)
                self._check_updates_silent_if_due(min_interval_s=900.0)
            except Exception:
                pass
            interval_min = max(1, int(self.cfg.get("poll_interval_minutes", 5)))
            self.poll_wakeup.wait(timeout=interval_min * 60)
            self.poll_wakeup.clear()

    def _update_tray_and_ui(self, res: dict[str, Any] | None) -> None:
        if res:
            self.icon.icon = render_tray_icon(res["percentage"], res["is_charging"])
            self.icon.title = self._status_summary_text()[:120]
        else:
            self.icon.icon = render_tray_icon(None, False)
            self.icon.title = "Mouse Battery & Control — No device"
        try:
            self.icon.update_menu()
        except Exception:
            pass

        if self.win and self.win.winfo_exists():
            self._refresh_dashboard()

    # --- Inline Toast Feedback ---
    def _flash_status(self, message: str, color: str = GREEN) -> None:
        if not self._toast_label or not self.win or not self.win.winfo_exists():
            return
        if self._toast_after_id:
            try:
                self.win.after_cancel(self._toast_after_id)
            except Exception:
                pass
        self._toast_label.configure(text=message, text_color=color)
        self._toast_after_id = self.win.after(3000, lambda: self._toast_label.configure(text=""))

    # --- Main Window ---
    def show_window(self) -> None:
        if self.win and self.win.winfo_exists():
            self._refresh_dashboard()
            self._load_mouse_values()
            self._refresh_update_button()
            self._check_updates_silent_if_due(min_interval_s=900.0)
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return

        win_w, win_h = 600, 795
        win = ctk.CTkToplevel(self.root)
        win.title(f"Mouse Battery & Control v{APP_VERSION}")
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        pos_x = max(20, screen_w - win_w - 20)
        pos_y = max(20, screen_h - win_h - 64)
        win.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
        win.resizable(True, True)
        win.minsize(600, 795)
        win.configure(fg_color=BG)
        win.protocol("WM_DELETE_WINDOW", self._on_window_close)
        win.bind("<Control-MouseWheel>", self._on_chart_wheel)
        win.bind("<KeyPress>", self._on_secret_keypress)
        win.bind("<Control-Shift-G>", lambda _e: self._open_aim_trainer_egg())
        win.bind("<Control-Shift-g>", lambda _e: self._open_aim_trainer_egg())
        apply_win_titlebar_theme(win, self._resolved_theme)
        ico_path = self._icon_path()
        if ico_path:
            try:
                win.after(200, lambda p=str(ico_path): win.iconbitmap(p))
            except Exception:
                pass
        self.win = win
        self._build_window_contents(initial_page="Dashboard")
        self._check_updates_silent_if_due(min_interval_s=900.0)

    def _build_window_contents(self, initial_page: str = "Dashboard") -> None:
        win = self.win
        if not win or not win.winfo_exists():
            return
        for child in win.winfo_children():
            child.destroy()
        win.configure(fg_color=BG)
        self.pages = {}
        self._widgets = {}
        self._built_pages = set()
        self._gauge_cache_key = None
        self._dpi_buttons = {}
        self._dpi_underlines = {}

        # Top Header
        header = ctk.CTkFrame(win, fg_color=BG)
        header.pack(side="top", fill="x", padx=22, pady=(16, 10))

        title_col = ctk.CTkFrame(header, fg_color=BG)
        title_col.pack(side="left")
        app_title_lbl = ctk.CTkLabel(
            title_col,
            text=self._t("app_title"),
            font=ctk.CTkFont("Segoe UI", 20, "bold"),
            text_color=FG,
        )
        app_title_lbl.pack(anchor="w")
        app_title_lbl.bind("<Button-1>", self._on_title_egg_click)
        ctk.CTkLabel(
            title_col,
            text=self._t("app_subtitle"),
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=FG_MUTED,
        ).pack(anchor="w")

        right_hdr = ctk.CTkFrame(header, fg_color=BG)
        right_hdr.pack(side="right", anchor="center")

        self._conn_canvas = tk.Canvas(
            right_hdr, width=30, height=28, bg=BG, highlightthickness=0, cursor="hand2"
        )
        self._conn_canvas.pack(side="left", padx=(0, 8))
        self._conn_tooltip = DelayedTooltip(self._conn_canvas, "Connection: LIGHTSPEED", delay_ms=250)

        mouse_ctk_img = self._resolve_mouse_icon(
            self.latest_result.get("device_slug", "") if self.latest_result else "g502x-plus",
            self.latest_result.get("device", "") if self.latest_result else "",
        )

        self._widgets["device_pill"] = ctk.CTkLabel(
            right_hdr,
            text=f"  {self._t('detecting')}",
            image=mouse_ctk_img,
            compound="left",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=ACCENT,
            fg_color=CARD_ALT,
            corner_radius=12,
            padx=12,
            pady=5,
        )
        self._widgets["device_pill"].pack(side="left")
        self._widgets["device_pill"].bind("<Button-1>", self._open_device_menu)
        self._widgets["device_pill"].bind("<Button-3>", self._pick_custom_mouse_icon)
        self._device_pill_tooltip = DelayedTooltip(self._widgets["device_pill"], self._t("device_pill_tip"), delay_ms=1400)

        # Draggable Tab Navigation (canonical page keys mapped to localized labels)
        tab_labels = {
            "Dashboard": self._t("tab_dashboard"),
            "Notifications": self._t("tab_notifications"),
            "Mouse Control": self._t("tab_mouse"),
            "Sync & Backup": self._t("tab_sync"),
        }
        ordered_keys = monitor.normalize_tab_order(self.cfg.get("tab_order"))
        nav_pairs = [(k, tab_labels[k]) for k in ordered_keys]
        pal_now = theme.get_palette(self._resolved_theme)
        nav = DraggableTabBar(
            win,
            items=nav_pairs,
            active_key=initial_page,
            on_select=self._switch_page,
            on_reorder=self._on_tab_order_change,
            on_reset=self._on_tab_order_reset,
            palette=pal_now,
            height=36,
        )
        nav.pack(side="top", fill="x", padx=22, pady=(4, 14))
        self._widgets["nav_bar"] = nav
        nav.attach_tooltip(DelayedTooltip(nav, self._t("tab_bar_tip"), delay_ms=1200))

        # Pinned Bottom Footer (packed BEFORE content so it NEVER shifts between tabs!)
        footer = ctk.CTkFrame(win, fg_color=BG, height=30)
        footer.pack(side="bottom", fill="x", padx=22, pady=(4, 12))
        footer.pack_propagate(False)

        self._toast_label = ctk.CTkLabel(
            footer, text="", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=GREEN
        )
        self._toast_label.pack(side="left")

        self._widgets["version_btn"] = ctk.CTkButton(
            footer,
            text=f"v{APP_VERSION}",
            command=self._show_about_dialog,
            fg_color="transparent",
            hover_color=CARD_ALT,
            text_color=FG_MUTED,
            font=ctk.CTkFont("Segoe UI", 10),
            height=24,
            width=48,
            corner_radius=6,
        )
        self._widgets["version_btn"].pack(side="right", padx=(8, 0))
        DelayedTooltip(self._widgets["version_btn"], self._t("about_tip"), delay_ms=800)

        self._widgets["gear_btn"] = ctk.CTkButton(
            footer,
            text="⚙",
            command=self._open_gear_menu,
            fg_color="transparent",
            hover_color=CARD_ALT,
            text_color=FG_MUTED,
            font=ctk.CTkFont("Segoe UI", 13),
            height=24,
            width=28,
            corner_radius=6,
        )
        self._widgets["gear_btn"].pack(side="right", padx=(4, 0))
        DelayedTooltip(self._widgets["gear_btn"], self._t("gear_tip"), delay_ms=800)

        self._widgets["update_btn"] = ctk.CTkButton(
            footer,
            text=self._t("check_updates"),
            command=self._on_check_updates,
            fg_color="transparent",
            hover_color=CARD_ALT,
            text_color=ACCENT,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            height=24,
            width=158,
            corner_radius=6,
        )
        self._widgets["update_btn"].pack(side="right")
        self._update_tooltip = DelayedTooltip(
            self._widgets["update_btn"], self._t("check_updates_tip"), delay_ms=250
        )
        self._refresh_update_button()

        # Content Container (fills remaining space between nav and pinned footer)
        container = ctk.CTkFrame(win, fg_color=BG)
        container.pack(side="top", fill="both", expand=True, padx=22, pady=(0, 4))

        for name in ("Dashboard", "Notifications", "Mouse Control", "Sync & Backup"):
            frame = ctk.CTkFrame(container, fg_color=BG)
            self.pages[name] = frame

        self._switch_page(initial_page)
        if initial_page != "Dashboard":
            self._refresh_dashboard()

    def _show_about_dialog(self) -> None:
        log.info("UI_CLICK: open_about_dialog (v%s)", APP_VERSION)
        r = self.latest_result or {}
        device = str(r.get("device", self._t("no_mouse_detected")))
        pct = r.get("percentage")
        chg = bool(r.get("is_charging", False))
        conn = str(r.get("connection", "lightspeed")).upper()
        state_lbl = self._t("charging_word") if chg else self._t("battery_word")
        bat_str = f"{pct}% ({state_lbl}, {conn})" if pct is not None else self._t("unknown")

        h = self.hidpp
        dpi_on = getattr(h, "_dpi_feat_idx", None) is not None
        rate_on = getattr(h, "_rate_feat_idx", None) is not None
        rgb_on = (getattr(h, "_rgb_feat_idx", None) is not None) or (getattr(h, "_perkey_feat_idx", None) is not None)

        dlg = theme.StyledDialog(
            self._dialog_parent(),
            self._t("about_title"),
            self._resolved_theme,
            width=450,
            icon_path=self._icon_path(),
        )
        p = dlg.palette
        mode_val = self._hidpp_hw_mode
        if mode_val == 1:
            mode_str, mode_color = self._t("mode_onboard_active"), p["GREEN"]
        elif mode_val == 2:
            mode_str, mode_color = self._t("mode_host_active"), p["ACCENT"]
        else:
            mode_str, mode_color = self._t("mode_unknown"), p["FG_MUTED"]

        outer = ctk.CTkFrame(dlg, fg_color=p["BG"])
        outer.pack(fill="both", expand=True, padx=20, pady=18)

        hdr = ctk.CTkFrame(outer, fg_color=p["BG"])
        hdr.pack(fill="x", pady=(0, 12))
        title_row = ctk.CTkFrame(hdr, fg_color=p["BG"])
        title_row.pack(fill="x")
        ctk.CTkLabel(
            title_row,
            text=self._t("app_title"),
            font=ctk.CTkFont("Segoe UI", 17, "bold"),
            text_color=p["FG"],
        ).pack(side="left")
        ver_badge = ctk.CTkLabel(
            title_row,
            text=f" v{APP_VERSION} ",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=p["ACCENT"],
            fg_color=p["CARD_ALT"],
            corner_radius=8,
            padx=8,
            pady=2,
            cursor="hand2",
        )
        ver_badge.pack(side="left", padx=(10, 0))
        sub_lbl = ctk.CTkLabel(
            hdr,
            text=self._t("app_subtitle"),
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=p["FG_MUTED"],
        )
        sub_lbl.pack(anchor="w", pady=(2, 0))

        def _on_about_ver_tap(_ev: Any = None) -> None:
            cnt = self._about_ver_clicks.tap(required=7, window_s=4.0)
            if 4 <= cnt < 7:
                hint = self._t("ee_version_countdown", left=7 - cnt)
                sub_lbl.configure(text=hint, text_color=p["ACCENT"])
            elif cnt >= 7:
                dlg._close()
                self.root.after(20, self._open_aim_trainer_egg)

        ver_badge.bind("<Button-1>", _on_about_ver_tap)

        def _make_card(card_title: str) -> ctk.CTkFrame:
            card = ctk.CTkFrame(
                outer, fg_color=p["CARD"], border_color=p["BORDER"], border_width=1, corner_radius=12
            )
            card.pack(fill="x", pady=(0, 10))
            inner = ctk.CTkFrame(card, fg_color=p["CARD"])
            inner.pack(fill="x", padx=14, pady=10)
            ctk.CTkLabel(
                inner,
                text=card_title,
                font=ctk.CTkFont("Segoe UI", 12, "bold"),
                text_color=p["FG"],
            ).pack(anchor="w", pady=(0, 6))
            return inner

        def _add_kv_row(parent_frame: ctk.CTkFrame, label: str, val_text: str, val_color: str) -> None:
            row = ctk.CTkFrame(parent_frame, fg_color=p["CARD"])
            row.pack(fill="x", pady=1)
            ctk.CTkLabel(
                row, text=label, font=ctk.CTkFont("Segoe UI", 11), text_color=p["FG_MUTED"]
            ).pack(side="left")
            ctk.CTkLabel(
                row, text=val_text, font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=val_color
            ).pack(side="right")

        dev_card = _make_card(self._t("active_device"))
        _add_kv_row(dev_card, self._t("model"), device, p["FG"])
        _add_kv_row(dev_card, self._t("status"), bat_str, p["ACCENT"] if chg else p["FG"])
        _add_kv_row(
            dev_card,
            self._t("firmware"),
            self._hidpp_fw_version or self._t("unknown"),
            p["FG"] if self._hidpp_fw_version else p["FG_MUTED"],
        )

        feat_card = _make_card(self._t("hidpp_features"))
        _add_kv_row(
            feat_card,
            "DPI Control (0x2201)",
            self._t("active_dot") if dpi_on else self._t("pending_dot"),
            p["GREEN"] if dpi_on else p["FG_MUTED"],
        )
        _add_kv_row(
            feat_card,
            "Report Rate (0x8060)",
            self._t("active_dot") if rate_on else self._t("pending_dot"),
            p["GREEN"] if rate_on else p["FG_MUTED"],
        )
        _add_kv_row(
            feat_card,
            "LIGHTSYNC RGB (0x8071 / 0x8081)",
            self._t("active_dot") if rgb_on else self._t("pending_dot"),
            p["GREEN"] if rgb_on else p["FG_MUTED"],
        )
        _add_kv_row(feat_card, "Mouse Mode (0x8100)", mode_str, mode_color)

        notes_card = _make_card(self._t("recent_highlights"))
        highlights = [
            ("v2.28.0", self._t("hl_v2280")),
            ("v2.27.0", self._t("hl_v2270")),
            ("v2.26.0", self._t("hl_v2260")),
            ("v2.25.0", self._t("hl_v2250")),
            ("v2.24.0", self._t("hl_v2240")),
            ("v2.23.0", self._t("hl_v2230")),
            ("v2.22.0", self._t("hl_v2220")),
            ("v2.21.0", self._t("hl_v2210")),
            ("v2.20.0", self._t("hl_v2200")),
            ("v2.19.0", self._t("hl_v2190")),
            ("v2.18.0", self._t("hl_v2180")),
            ("v2.17.0", self._t("hl_v2170")),
            ("v2.16.0", self._t("hl_v2160")),
            ("v2.15.0", self._t("hl_v2150")),
            ("v2.14.0", self._t("hl_v2140")),
            ("v2.13.0", self._t("hl_v2130")),
            ("v2.12.0", self._t("hl_v2120")),
            ("v2.11.0", self._t("hl_v2110")),
            ("v2.10.0", self._t("hl_v2100")),
            ("v2.9.5", self._t("hl_v295")),
            ("v2.9.4", self._t("hl_v294")),
        ]
        recent_highlights = highlights[:4]
        earlier_highlights = highlights[4:]

        def _add_hl_row(parent_box: Any, ver: str, desc: str) -> None:
            hrow = ctk.CTkFrame(parent_box, fg_color=p["CARD"])
            hrow.pack(fill="x", pady=2)
            ctk.CTkLabel(
                hrow,
                text=ver,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
                text_color=p["ACCENT"],
                width=52,
                anchor="nw",
            ).pack(side="left", anchor="n")
            ctk.CTkLabel(
                hrow,
                text=desc,
                font=ctk.CTkFont("Segoe UI", 10),
                text_color=p["FG_MUTED"],
                anchor="nw",
                justify="left",
                wraplength=310,
            ).pack(side="left", fill="x", expand=True)

        for ver, desc in recent_highlights:
            _add_hl_row(notes_card, ver, desc)

        dlg._hl_recent_count = len(recent_highlights)
        dlg._hl_earlier_count = len(earlier_highlights)
        if earlier_highlights:
            expanded = [False]
            built_earlier = [False]
            earlier_box = ctk.CTkScrollableFrame(
                notes_card, fg_color=p["CARD"], height=185, corner_radius=6
            )
            toggle_btn = ctk.CTkButton(
                notes_card,
                text=self._t("highlights_show_more", count=len(earlier_highlights)),
                fg_color="transparent",
                hover_color=p["CARD_ALT"],
                text_color=p["ACCENT"],
                anchor="w",
                height=26,
                corner_radius=6,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
            )
            toggle_btn.pack(fill="x", pady=(6, 0))

            def _toggle_earlier() -> None:
                expanded[0] = not expanded[0]
                if expanded[0]:
                    if not built_earlier[0]:
                        for ver, desc in earlier_highlights:
                            _add_hl_row(earlier_box, ver, desc)
                        built_earlier[0] = True
                    earlier_box.pack(fill="x", pady=(4, 0))
                    toggle_btn.configure(text=self._t("highlights_show_less"))
                else:
                    earlier_box.pack_forget()
                    toggle_btn.configure(text=self._t("highlights_show_more", count=len(earlier_highlights)))

                dlg.update_idletasks()
                w = dlg._target_width or max(380, dlg.winfo_reqwidth())
                max_h = max(320, dlg.winfo_screenheight() - 80)
                h = min(max_h, max(180, dlg.winfo_reqheight()))
                x = max(20, min(dlg.winfo_x(), dlg.winfo_screenwidth() - w - 20))
                y = max(20, min(dlg.winfo_y(), dlg.winfo_screenheight() - h - 40))
                dlg.geometry(f"{w}x{h}+{x}+{y}")

            toggle_btn.configure(command=_toggle_earlier)
            dlg._hl_toggle = _toggle_earlier
            dlg._hl_toggle_btn = toggle_btn
            dlg._hl_earlier_box = earlier_box

        btn_row = ctk.CTkFrame(outer, fg_color=p["BG"])
        btn_row.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(
            btn_row,
            text=self._t("close"),
            width=110,
            height=34,
            corner_radius=8,
            fg_color=p["ACCENT"],
            hover_color=p["ACCENT_HOVER"],
            text_color=p["ACCENT_TEXT"],
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            command=dlg._close,
        ).pack(side="right")

        dlg.bind("<Return>", lambda _e: dlg._close())
        dlg.center_on_parent()
        dlg.wait_window()

    def _open_gear_menu(self) -> None:
        if not self.win or not self.win.winfo_exists():
            return
        btn = self._widgets.get("gear_btn")
        if not btn:
            return

        # Close existing popover if already open (toggle behavior)
        existing = getattr(self, "_gear_popover", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()
            self._gear_popover = None
            return

        pop = tk.Toplevel(self.win)
        pop.wm_overrideredirect(True)
        pop.wm_attributes("-topmost", True)
        chroma = "#010203"
        pop.configure(bg=chroma)
        try:
            pop.wm_attributes("-transparentcolor", chroma)
        except Exception:
            pass

        card = ctk.CTkFrame(
            pop,
            fg_color=CARD,
            border_color=BORDER,
            border_width=1,
            corner_radius=10,
            bg_color=chroma,
        )
        card.pack()

        def _run_and_close(fn: Any) -> None:
            try:
                pop.destroy()
            except Exception:
                pass
            self._gear_popover = None
            fn()

        items = [
            (self._t("gear_test_notify"), lambda: (self._on_test_notify(), self._flash_status(self._t("toast_test_sent"), ACCENT))),
            (self._t("gear_refresh"), lambda: (self._on_refresh_now(), self._flash_status(self._t("toast_refreshed"), ACCENT))),
            None,
            (
                self._t("gear_open_log"),
                lambda: __import__("os").startfile(str(LOG_PATH))
                if LOG_PATH.exists()
                else self._flash_status(self._t("toast_no_log"), FG_MUTED),
            ),
            (
                self._t("gear_open_telemetry"),
                lambda: __import__("os").startfile(str(self.telemetry.path))
                if self.telemetry.path.exists()
                else self._flash_status(self._t("toast_no_telemetry"), FG_MUTED),
            ),
            (self._t("gear_open_folder"), lambda: __import__("os").startfile(str(BASE_DIR))),
        ]
        for idx, item in enumerate(items):
            if item is None:
                ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=10, pady=4)
                continue
            label, cb = item
            ctk.CTkButton(
                card,
                text=label,
                anchor="w",
                command=lambda f=cb: _run_and_close(f),
                fg_color="transparent",
                hover_color=CARD_ALT,
                text_color=FG,
                font=ctk.CTkFont("Segoe UI", 11),
                height=30,
                width=205,
                corner_radius=7,
            ).pack(fill="x", padx=6, pady=(6 if idx == 0 else 2, 6 if idx == len(items) - 1 else 2))

        pop.update_idletasks()
        pw = pop.winfo_reqwidth()
        ph = pop.winfo_reqheight()
        x = btn.winfo_rootx() + btn.winfo_width() - pw
        y = btn.winfo_rooty() - ph - 6
        pop.wm_geometry(f"+{x}+{y}")
        pop.focus_force()
        pop.bind("<FocusOut>", lambda _: pop.after(50, lambda: pop.destroy() if pop.winfo_exists() else None))
        self._gear_popover = pop

    def _on_tab_order_change(self, order: list[str]) -> None:
        normalized = monitor.normalize_tab_order(order)
        cfg = monitor.load_config()
        cfg["tab_order"] = normalized
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self._record_telemetry("reorder_tabs", requested=order, api_ok=True, actual=normalized, verified=True)
        self._flash_status(self._t("tab_order_saved"), GREEN)

    def _on_tab_order_reset(self) -> None:
        default_order = list(monitor.DEFAULT_TAB_ORDER)
        cfg = monitor.load_config()
        cfg["tab_order"] = default_order
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        nav = self._widgets.get("nav_bar")
        if nav is not None:
            nav.set_order(default_order)
        self._record_telemetry("reset_tabs", requested=default_order, api_ok=True, actual=default_order, verified=True)
        self._flash_status(self._t("tab_order_reset"), ACCENT)

    def _ensure_page_built(self, name: str) -> None:
        if name in self._built_pages or name not in self.pages:
            return
        self._built_pages.add(name)
        builders = {
            "Dashboard": self._build_dashboard_page,
            "Notifications": self._build_notifications_page,
            "Mouse Control": self._build_mouse_page,
            "Sync & Backup": self._build_sync_page,
        }
        builder = builders.get(name)
        if builder is not None:
            builder(self.pages[name])

    def _switch_page(self, name: str) -> None:
        log.info("UI_CLICK: switch_tab -> %s", name)
        self._active_page = name
        self._ensure_page_built(name)
        nav = self._widgets.get("nav_bar")
        if nav is not None:
            nav.set_active(name)
        for k, frame in self.pages.items():
            if k == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self._record_telemetry("switch_tab", requested=name, api_ok=True, actual=name, verified=True)
        if name == "Dashboard":
            self._refresh_dashboard()
        elif name == "Mouse Control":
            self._load_mouse_values()
            self._poll_hidpp_once()

    # ==================== PAGE 1: DASHBOARD ====================
    def _build_dashboard_page(self, parent: ctk.CTkFrame) -> None:
        # Hero Card
        hero = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        hero.pack(fill="x", pady=(0, 14))

        hero_inner = ctk.CTkFrame(hero, fg_color=CARD)
        hero_inner.pack(fill="x", padx=18, pady=16)

        # Left: Circular Battery Gauge
        self._gauge_canvas = tk.Canvas(
            hero_inner, width=136, height=136, bg=CARD, highlightthickness=0
        )
        self._gauge_canvas.pack(side="left", padx=(0, 18))
        self._gauge_canvas.bind("<Button-1>", self._on_gauge_click)

        # Right: Metrics Grid
        metrics = ctk.CTkFrame(hero_inner, fg_color=CARD)
        metrics.pack(side="left", fill="both", expand=True)

        self._widgets["evening_pill"] = ctk.CTkLabel(
            metrics,
            text=self._t("evening_checking"),
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=GREEN,
            fg_color=CARD_ALT,
            corner_radius=8,
            padx=10,
            pady=4,
        )
        self._widgets["evening_pill"].pack(anchor="w", pady=(0, 10))

        # Row 1: Battery Remaining: ~62h [Learning] ⓘ
        rem_row = ctk.CTkFrame(metrics, fg_color=CARD)
        rem_row.pack(fill="x", pady=5)
        ctk.CTkLabel(
            rem_row, text=self._t("battery_remaining"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED, width=132, anchor="w"
        ).pack(side="left")

        self._widgets["time_left"] = ctk.CTkLabel(
            rem_row, text="—", font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=FG
        )
        self._widgets["time_left"].pack(side="left", padx=(4, 0))

        self._widgets["learning_pill"] = ctk.CTkLabel(
            rem_row,
            text=self._t("learning"),
            font=ctk.CTkFont("Segoe UI", 9, "bold"),
            text_color=AMBER,
            fg_color=CARD_ALT,
            corner_radius=6,
            padx=7,
            pady=1,
            cursor="hand2",
        )
        pill_w = self._widgets["learning_pill"]
        pill_w.bind("<Button-1>", lambda _e: self._show_learning_summary_dialog(), add="+")
        pill_w.bind("<Enter>", lambda _e: pill_w.configure(fg_color=BORDER), add="+")
        pill_w.bind("<Leave>", lambda _e: pill_w.configure(fg_color=CARD_ALT), add="+")
        self._pill_tooltip = DelayedTooltip(
            pill_w,
            f"{self._t('estimating_life')}\n{self._t('click_to_inspect')}",
            delay_ms=250,
        )

        # Row 2: Usage Drain Rate: 1.2%/hr (1 sess.)
        drain_row = ctk.CTkFrame(metrics, fg_color=CARD)
        drain_row.pack(fill="x", pady=5)
        ctk.CTkLabel(
            drain_row, text=self._t("usage_drain_rate"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED, width=132, anchor="w"
        ).pack(side="left")
        self._widgets["drain_rate"] = ctk.CTkLabel(
            drain_row, text="—", font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=FG
        )
        self._widgets["drain_rate"].pack(side="left", padx=(4, 0))

        # Row 3: Est. Power Draw: ~14 mW (6 sys + 8 @ 1000 Hz)
        power_row = ctk.CTkFrame(metrics, fg_color=CARD)
        self._widgets["power_row"] = power_row
        ctk.CTkLabel(
            power_row, text=self._t("est_power_draw"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED, width=132, anchor="w"
        ).pack(side="left")
        self._widgets["est_power"] = ctk.CTkLabel(
            power_row, text="—", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=FG
        )
        self._widgets["est_power"].pack(side="left", padx=(4, 0))
        power_row.pack(fill="x", pady=5)

        # Battery History Chart Card
        chart_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        chart_card.pack(fill="both", expand=True, pady=(0, 14))

        chart_hdr = ctk.CTkFrame(chart_card, fg_color=CARD)
        chart_hdr.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(
            chart_hdr,
            text=self._t("battery_history"),
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            text_color=FG,
        ).pack(side="left")

        range_pairs = [
            (24, self._t("range_24h")),
            (168, self._t("range_7d")),
            (720, self._t("range_30d")),
        ]
        lbl_to_hrs = {lbl: hrs for hrs, lbl in range_pairs}
        hrs_to_lbl = {hrs: lbl for hrs, lbl in range_pairs}

        range_seg = ctk.CTkSegmentedButton(
            chart_hdr,
            values=[lbl for _, lbl in range_pairs],
            command=lambda lbl: self._on_chart_range_change(lbl_to_hrs.get(lbl, 24)),
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=26,
            width=120,
        )
        range_seg.set(hrs_to_lbl.get(self.chart_range_hours, range_pairs[0][1]))
        range_seg.pack(side="right")

        self._widgets["reset_zoom_btn"] = ctk.CTkButton(
            chart_hdr,
            text=self._t("reset_zoom"),
            command=self._reset_chart_zoom,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG_MUTED,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            height=26,
            width=98,
            corner_radius=7,
            state="disabled",
        )
        self._widgets["reset_zoom_btn"].pack(side="right", padx=(0, 8))
        DelayedTooltip(
            self._widgets["reset_zoom_btn"],
            self._t("reset_zoom_tip"),
            delay_ms=250,
        )

        self._chart_canvas = tk.Canvas(
            chart_card, width=500, height=240, bg=CARD, highlightthickness=0, cursor="crosshair"
        )
        self._chart_canvas.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._chart_canvas.bind("<Motion>", self._on_chart_hover)
        self._chart_canvas.bind("<Leave>", self._on_chart_leave)
        self._chart_canvas.bind("<Configure>", self._on_chart_resize)

    def _on_chart_resize(self, event: Any) -> None:
        size = (int(getattr(event, "width", 0)), int(getattr(event, "height", 0)))
        if size[0] < 50 or size == self._last_chart_size:
            return
        self._last_chart_size = size
        if self._chart_resize_after_id is not None:
            try:
                self.root.after_cancel(self._chart_resize_after_id)
            except Exception:
                pass
        self._chart_resize_after_id = self.root.after(40, self._draw_history_chart)

    def _on_chart_range_change(self, val: int | str) -> None:
        if isinstance(val, int):
            self.chart_range_hours = val
        else:
            self.chart_range_hours = {"24h": 24, "7d": 168, "30d": 720}.get(str(val), 24)
        self._chart_zoom = None
        self._draw_history_chart()

    def _update_zoom_btn(self) -> None:
        btn = self._widgets.get("reset_zoom_btn")
        if not btn:
            return
        meta = self._chart_meta
        t_full_min = meta.get("t_full_min")
        t_full_max = meta.get("t_full_max")
        if self._chart_zoom and t_full_min is not None and t_full_max is not None and t_full_max > t_full_min:
            view_span = max(60.0, self._chart_zoom[1] - self._chart_zoom[0])
            full_span = t_full_max - t_full_min
            zoom_x = max(1.0, full_span / view_span)
            btn.configure(text=self._t("reset_zoom_x", zoom=zoom_x), state="normal", text_color=ACCENT)
        else:
            btn.configure(text=self._t("reset_zoom"), state="disabled", text_color=FG_MUTED)

    def _reset_chart_zoom(self) -> None:
        self._chart_zoom = None
        self._update_zoom_btn()
        self._draw_history_chart()

    def _on_chart_wheel(self, event: Any) -> str | None:
        if self._active_page != "Dashboard":
            return None
        c = self._chart_canvas
        meta = self._chart_meta
        if not c or not c.winfo_exists() or not meta:
            return None
        cx = event.x_root - c.winfo_rootx()
        cy = event.y_root - c.winfo_rooty()
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cx < 0 or cy < 0 or cx > cw or cy > ch:
            return None

        t_full_min = meta.get("t_full_min")
        t_full_max = meta.get("t_full_max")
        t_view_min = meta.get("t_view_min")
        t_view_max = meta.get("t_view_max")
        pad_l = meta.get("pad_l", 38)
        pad_r = meta.get("pad_r", 16)
        w = meta.get("w", cw)
        if t_full_min is None or t_full_max is None or t_view_min is None or t_view_max is None:
            return None

        full_span = t_full_max - t_full_min
        view_span = t_view_max - t_view_min
        plot_w = max(1.0, float(w - pad_l - pad_r))
        if full_span <= 300.0 or view_span <= 0.0:
            return "break"

        frac = max(0.0, min(1.0, (cx - pad_l) / plot_w))
        t_cursor = t_view_min + frac * view_span

        delta = getattr(event, "delta", 0)
        if delta == 0:
            return None
        factor = 0.78 if delta > 0 else (1.0 / 0.78)
        min_span = max(300.0, full_span * 0.03)
        new_span = max(min_span, min(full_span, view_span * factor))

        if new_span >= full_span * 0.99:
            self._chart_zoom = None
        else:
            new_min = t_cursor - frac * new_span
            new_max = new_min + new_span
            if new_min < t_full_min:
                new_min = t_full_min
                new_max = new_min + new_span
            if new_max > t_full_max:
                new_max = t_full_max
                new_min = max(t_full_min, new_max - new_span)
            self._chart_zoom = (new_min, new_max)

        self._draw_history_chart()
        return "break"

    def _refresh_dashboard(self) -> None:
        r = self.latest_result
        if "device_pill" in self._widgets:
            if not r:
                self._widgets["device_pill"].configure(text=f"  {self._t('detecting')}", image="")
            else:
                short_title = _short_device_name(r["device"], 24)
                pill_img = self._resolve_mouse_icon(r.get("device_slug", ""), r.get("device", ""))
                self._widgets["device_pill"].configure(
                    text=f"  {short_title}" + (f" ({self.selected_device_idx + 1}/{len(self.all_results)}) ▾" if len(self.all_results) > 1 else ""),
                    image=pill_img if pill_img is not None else "",
                )
                if self._device_pill_tooltip is not None:
                    self._device_pill_tooltip.text = f"{r['device']}\n{self._t('device_pill_tip')}"
                self._draw_connection_icon(bool(r.get("is_charging", False)), r.get("connection", "lightspeed"))

        if "time_left" not in self._widgets:
            return
        if not r:
            self._widgets["time_left"].configure(text=self._t("unknown"))
            self._widgets["drain_rate"].configure(text=self._t("unknown"))
            pill_w = self._widgets.get("learning_pill")
            if pill_w:
                pill_w.pack_forget()
            power_row = self._widgets.get("power_row")
            if power_row:
                power_row.pack_forget()
            self._widgets["evening_pill"].configure(text=self._t("no_battery_data"), text_color=FG_MUTED)
            self._draw_gauge(None, False, FG_MUTED)
            self._draw_history_chart()
            self._sync_mouse_control_visibility()
            return
        pct = r.get("percentage")
        chg = bool(r.get("is_charging", False))
        color = (
            FG_MUTED
            if pct is None
            else (ACCENT if chg else (RED if pct <= 20 else (AMBER if pct <= 40 else GREEN)))
        )

        pill_w = self._widgets.get("learning_pill")
        power_row = self._widgets.get("power_row")
        if pct is None:
            self._widgets["time_left"].configure(text=self._t("unknown"))
            self._widgets["drain_rate"].configure(text=self._t("unknown"))
            if pill_w:
                pill_w.pack_forget()
            if power_row:
                power_row.pack_forget()
            self._widgets["evening_pill"].configure(text=self._t("battery_unavailable"), text_color=FG_MUTED)
        else:
            self._widgets["time_left"].configure(text=f"~{r['time_left_str']}")
            src = f"{r['sessions_used']} {self._t('sess_short')}" if r["is_learned"] else self._t("est_short")
            self._widgets["drain_rate"].configure(text=f"{r['drain_rate_pct_per_hour']:.1f}%/hr ({src})")

            if power_row and "est_power" in self._widgets:
                est_mw = r.get("est_power_mw")
                if est_mw is not None and r.get("report_rate_hz") is not None:
                    self._widgets["est_power"].configure(
                        text=self._t(
                            "est_power_fmt",
                            total=est_mw,
                            sys=r.get("est_sys_mw", monitor.SYSTEM_BASE_MW),
                            rate=r.get("est_rate_mw", 0.0),
                            hz=r["report_rate_hz"],
                        )
                    )
                    power_row.pack(fill="x", pady=5)
                else:
                    power_row.pack_forget()

            # Calibration pill (transitions from Learning -> Calibrating -> Learned, always clickable)
            total_drop = int(r.get("total_discharge_pct", 0))
            is_calibrated = total_drop >= 80
            pct_cycle = min(99, int(round(total_drop / 80.0 * 100)))
            if is_calibrated:
                tip_text = f"{self._t('learned_calibrated_fmt', drop=total_drop)}\n{self._t('click_to_inspect')}"
            else:
                tip_text = f"{self._t('early_est_tip', pct=pct_cycle)}\n{self._t('click_to_inspect')}"
            if hasattr(self, "_pill_tooltip"):
                self._pill_tooltip.text = tip_text

            if pill_w:
                if is_calibrated:
                    pill_w.configure(text=self._t("learned_pill"), text_color=GREEN)
                else:
                    pill_w.configure(
                        text=self._t("learning") if total_drop < 35 else self._t("calibrating"),
                        text_color=AMBER,
                    )
                pill_w.pack(side="left", padx=(8, 0))

            ev_hour = int(self.cfg.get("evening_hour", 22))
            if chg:
                self._widgets["evening_pill"].configure(text=self._t("evening_charging"), text_color=ACCENT)
            elif r["wont_last_till_evening"]:
                self._widgets["evening_pill"].configure(text=self._t("evening_wont_last", hour=ev_hour), text_color=AMBER)
            else:
                self._widgets["evening_pill"].configure(text=self._t("evening_will_last", hour=ev_hour), text_color=GREEN)

        self._draw_connection_icon(chg, r.get("connection", "lightspeed"))
        self._draw_gauge(pct, chg, color)
        self._draw_history_chart()
        self._sync_mouse_control_visibility()

    def _show_learning_summary_dialog(self) -> None:
        r = self.latest_result or {}
        slug = str(r.get("device_slug", "")).strip()
        if not slug and r.get("device"):
            slug = str(r["device"]).lower().replace(" ", "-")
        display_name = str(r.get("device", self._t("no_mouse_detected")))
        log.info("UI_CLICK: open_learned_summary (%s)", slug or "none")

        history = monitor.load_history(int(self.cfg.get("max_history_days", 30)))
        default_rate = float(self.cfg.get("default_drain_rate_pct_per_hour", 1.5))
        adv_mah = int(self.cfg.get("advertised_capacity_mah", 500))
        is_logi = r.get("source") in ("lghub", "hidpp") if r else True
        summary = monitor.summarize_learning(slug, history, default_rate, advertised_mah=adv_mah, is_logitech=is_logi)

        dlg = theme.StyledDialog(
            self._dialog_parent(),
            self._t("learned_title"),
            self._resolved_theme,
            width=480,
            icon_path=self._icon_path(),
        )
        p = dlg.palette
        u = self._t("unit_pct_hr")
        no_data = self._t("learned_no_data")

        outer = ctk.CTkFrame(dlg, fg_color=p["BG"])
        outer.pack(fill="both", expand=True, padx=20, pady=18)

        # Header row: Device title + stage pill
        hdr = ctk.CTkFrame(outer, fg_color=p["BG"])
        hdr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            hdr,
            text=display_name,
            font=ctk.CTkFont("Segoe UI", 16, "bold"),
            text_color=p["FG"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        stage = summary["stage"]
        if stage == "calibrated":
            badge_text, badge_color = self._t("learned_calibrated_badge"), p["GREEN"]
        elif stage == "calibrating":
            badge_text, badge_color = self._t("calibrating"), p["AMBER"]
        else:
            badge_text, badge_color = self._t("learning"), p["AMBER"]
        ctk.CTkLabel(
            hdr,
            text=badge_text,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            text_color=badge_color,
            fg_color=p["CARD_ALT"],
            corner_radius=8,
            padx=10,
            pady=3,
        ).pack(side="right")

        # Calibration progress bar & caption
        prog_bar = ctk.CTkProgressBar(
            outer,
            height=8,
            corner_radius=4,
            fg_color=p["CARD_ALT"],
            progress_color=p["GREEN"] if stage == "calibrated" else p["AMBER"],
        )
        prog_bar.set(min(1.0, max(0.0, summary["total_discharge_pct"] / 80.0)))
        prog_bar.pack(fill="x", pady=(0, 4))

        prog_text = (
            self._t("learned_calibrated_fmt", drop=summary["total_discharge_pct"])
            if stage == "calibrated"
            else self._t("learned_progress_fmt", drop=summary["total_discharge_pct"], pct=summary["calibration_pct"])
        )
        ctk.CTkLabel(
            outer,
            text=prog_text,
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=p["FG_MUTED"],
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        def _make_card(title: str) -> ctk.CTkFrame:
            card = ctk.CTkFrame(
                outer,
                fg_color=p["CARD"],
                border_color=p["BORDER"],
                border_width=1,
                corner_radius=12,
            )
            card.pack(fill="x", pady=(0, 10))
            inner = ctk.CTkFrame(card, fg_color=p["CARD"])
            inner.pack(fill="x", padx=14, pady=10)
            ctk.CTkLabel(
                inner,
                text=title,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                text_color=p["FG"],
                anchor="w",
            ).pack(fill="x", pady=(0, 6))
            return inner

        def _add_kv_row(parent_card: ctk.CTkFrame, key: str, val: str, val_color: str | None = None) -> None:
            row = ctk.CTkFrame(parent_card, fg_color=p["CARD"])
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row, text=key, font=ctk.CTkFont("Segoe UI", 10), text_color=p["FG_MUTED"], anchor="w"
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=val,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
                text_color=val_color or p["FG"],
                anchor="e",
            ).pack(side="right")

        # Card 1: Key Learned Metrics
        metrics_card = _make_card(self._t("learned_title"))
        n_sess = summary["sessions_used"]
        rate_str = (
            self._t("learned_rate_learned_fmt", rate=summary["drain_rate_pct_per_hour"], n=n_sess)
            if summary["is_learned"]
            else self._t("learned_rate_default_fmt", rate=summary["drain_rate_pct_per_hour"])
        )
        _add_kv_row(
            metrics_card,
            self._t("learned_active_rate"),
            rate_str,
            p["GREEN"] if summary["is_learned"] else p["FG_MUTED"],
        )

        n_samples = summary["sample_count"]
        since = summary["first_sample_local"]
        samples_str = (
            self._t("learned_samples_fmt", n=n_samples, since=since)
            if (n_samples > 0 and since)
            else (str(n_samples) if n_samples > 0 else self._t("learned_none_yet"))
        )
        _add_kv_row(metrics_card, self._t("learned_samples"), samples_str)

        meas_str = (
            self._t("learned_measured_fmt", dur=monitor.format_duration(summary["total_session_hours"]), n=n_sess)
            if n_sess > 0
            else self._t("learned_not_enough")
        )
        _add_kv_row(
            metrics_card,
            self._t("learned_measured_time"),
            meas_str,
            p["FG"] if n_sess > 0 else p["FG_MUTED"],
        )

        min_r, max_r = summary["min_rate"], summary["max_rate"]
        range_str = (
            f"{min_r:.1f} – {max_r:.1f}{u}"
            if (min_r is not None and max_r is not None)
            else self._t("learned_not_enough")
        )
        _add_kv_row(
            metrics_card,
            self._t("learned_observed_range"),
            range_str,
            p["FG"] if (min_r is not None and max_r is not None) else p["FG_MUTED"],
        )

        wd_r, we_r = summary["weekday_rate"], summary["weekend_rate"]
        if wd_r is None and we_r is None:
            wk_str, wk_col = self._t("learned_not_enough"), p["FG_MUTED"]
        else:
            wd_txt = f"{wd_r:.1f}{u}" if wd_r is not None else no_data
            we_txt = f"{we_r:.1f}{u}" if we_r is not None else no_data
            wk_str, wk_col = f"{wd_txt} / {we_txt}", p["FG"]
        _add_kv_row(metrics_card, self._t("learned_weekday_weekend"), wk_str, wk_col)

        # Card 2: Battery Capacity & Health
        health = summary.get("health") or {}
        health_card = _make_card(self._t("health_card_title"))
        adv_mah_v = health.get("advertised_mah")
        adv_mwh_v = health.get("advertised_mwh")
        if adv_mah_v is not None and adv_mwh_v is not None:
            _add_kv_row(
                health_card,
                self._t("health_advertised"),
                self._t("health_adv_fmt", mah=adv_mah_v, mwh=adv_mwh_v),
            )
        else:
            _add_kv_row(health_card, self._t("health_advertised"), self._t("unknown"), p["FG_MUTED"])

        _add_kv_row(
            health_card,
            self._t("health_cycles"),
            self._t("health_cycles_fmt", cycles=float(health.get("charge_cycles", 0.0))),
        )
        h_status = health.get("status")
        if h_status == "estimated" and health.get("health_pct") is not None:
            est_mah_v = health["est_capacity_mah"]
            est_mwh_v = health["est_capacity_mwh"]
            h_pct = int(health["health_pct"])
            h_col = p["GREEN"] if h_pct >= 85 else (p["AMBER"] if h_pct >= 70 else p["RED"])
            _add_kv_row(
                health_card,
                self._t("health_est_cap"),
                self._t("health_est_fmt", mah=est_mah_v, mwh=est_mwh_v),
            )
            _add_kv_row(health_card, self._t("health_est_pct"), f"~{h_pct}%", h_col)
        elif h_status == "unavailable":
            _add_kv_row(health_card, self._t("health_est_pct"), self._t("health_unavail"), p["FG_MUTED"])
        else:
            _add_kv_row(
                health_card,
                self._t("health_est_pct"),
                self._t("health_calibrating_fmt", cur=float(health.get("active_cycles", 0.0))),
                p["AMBER"],
            )

        # Card 3: Time of Day Breakdown (Night / Morning / Day / Evening)
        tod_card = _make_card(self._t("learned_tod_title"))
        tod_grid = ctk.CTkFrame(tod_card, fg_color=p["CARD"])
        tod_grid.pack(fill="x", pady=(2, 0))
        tod_specs = [(0, "tod_night"), (1, "tod_morning"), (2, "tod_afternoon"), (3, "tod_evening")]
        bucket_rates = summary["bucket_rates"]
        for col_idx, (bucket_id, label_key) in enumerate(tod_specs):
            tod_grid.grid_columnconfigure(col_idx, weight=1, uniform="tod")
            tile = ctk.CTkFrame(tod_grid, fg_color=p["CARD_ALT"], corner_radius=8)
            tile.grid(row=0, column=col_idx, sticky="ew", padx=(0 if col_idx == 0 else 6, 0))
            ctk.CTkLabel(
                tile,
                text=self._t(label_key),
                font=ctk.CTkFont("Segoe UI", 9),
                text_color=p["FG_MUTED"],
            ).pack(pady=(6, 1))
            b_rate = bucket_rates.get(bucket_id)
            ctk.CTkLabel(
                tile,
                text=f"{b_rate:.1f}{u}" if b_rate is not None else "—",
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                text_color=p["ACCENT"] if b_rate is not None else p["FG_MUTED"],
            ).pack(pady=(0, 6))

        # Card 3: Recent Measured Sessions
        sess_card = _make_card(self._t("learned_recent_title"))
        recent = summary["recent_sessions"]
        if recent:
            for sess in recent:
                srow = ctk.CTkFrame(sess_card, fg_color=p["CARD"])
                srow.pack(fill="x", pady=2)
                ctk.CTkLabel(
                    srow,
                    text=f"{sess['end_local']}   •   {sess['start_pct']}% → {sess['end_pct']}%",
                    font=ctk.CTkFont("Segoe UI", 10),
                    text_color=p["FG_MUTED"],
                    anchor="w",
                ).pack(side="left")
                ctk.CTkLabel(
                    srow,
                    text=f"{sess['duration_str']}  ({sess['rate']:.1f}{u})",
                    font=ctk.CTkFont("Segoe UI", 10, "bold"),
                    text_color=p["FG"],
                    anchor="e",
                ).pack(side="right")
        else:
            ctk.CTkLabel(
                sess_card,
                text=self._t("learned_no_sessions_msg"),
                font=ctk.CTkFont("Segoe UI", 10),
                text_color=p["FG_MUTED"],
                justify="left",
                anchor="w",
                wraplength=415,
            ).pack(fill="x", pady=(2, 2))

        btn_row = ctk.CTkFrame(outer, fg_color=p["BG"])
        btn_row.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(
            btn_row,
            text=self._t("close"),
            width=110,
            height=34,
            corner_radius=8,
            fg_color=p["ACCENT"],
            hover_color=p["ACCENT_HOVER"],
            text_color=p["ACCENT_TEXT"],
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            command=dlg._close,
        ).pack(side="right")

        dlg.bind("<Return>", lambda _e: dlg._close())
        dlg.bind("<Escape>", lambda _e: dlg._close())
        dlg.center_on_parent()
        dlg.wait_window()

    def _load_cached_icon(self, cache_key: str, path: Path) -> ctk.CTkImage | None:
        key = (cache_key, str(path))
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached
        try:
            pil_img = Image.open(path)
            img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(15, 25))
            self._icon_cache[key] = img
            return img
        except Exception:
            return None

    def _invalidate_icon_cache(self, norm: str) -> None:
        for k in [k for k in self._icon_cache if k[0] == norm]:
            self._icon_cache.pop(k, None)

    def _resolve_mouse_icon(self, slug: str, display_name: str = "") -> ctk.CTkImage | None:
        """Pick cached/custom model PNG, or auto-fetch from web in background with generic fallback."""
        norm = slug.lower().replace(" ", "_").replace("-", "_")
        cache_path = BASE_DIR / "icons" / f"{norm}.png" if norm else None

        candidates: list[Path] = []
        if cache_path:
            candidates.append(cache_path)
            candidates.append(BASE_DIR / f"{norm}.png")
        if "g502x" in norm:
            candidates.append(RESOURCE_DIR / "g502x_plus.png")
            candidates.append(BASE_DIR / "g502x_plus.png")

        for p in candidates:
            if p.exists():
                loaded = self._load_cached_icon(norm or "mouse", p)
                if loaded is not None:
                    return loaded

        # No model-specific icon found yet -> auto-fetch once in background
        if norm and cache_path and display_name and norm not in self._icon_fetch_attempted:
            self._icon_fetch_attempted.add(norm)

            def _fetch_worker() -> None:
                if icon_fetcher.fetch_mouse_icon_from_web(display_name, cache_path):
                    self._invalidate_icon_cache(norm)
                    self.root.after(0, self._refresh_dashboard)

            threading.Thread(target=_fetch_worker, daemon=True).start()

        # Instant generic mouse fallback while fetching (or if offline)
        for p in (RESOURCE_DIR / "generic_mouse.png", BASE_DIR / "generic_mouse.png"):
            if p.exists():
                loaded = self._load_cached_icon("_generic", p)
                if loaded is not None:
                    return loaded
        return None

    def _pick_custom_mouse_icon(self, event: Any = None) -> None:
        if not self.latest_result:
            return
        slug = self.latest_result.get("device_slug", "mouse")
        norm = slug.lower().replace(" ", "_").replace("-", "_") or "mouse"
        path = filedialog.askopenfilename(
            parent=self.win,
            title=self._t("custom_icon_title", device=self.latest_result.get("device", "Mouse")),
            filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp")],
        )
        if not path:
            return
        dest = BASE_DIR / "icons" / f"{norm}.png"
        if icon_fetcher.save_custom_icon(Path(path), dest):
            self._invalidate_icon_cache(norm)
            self._refresh_dashboard()
            self._flash_status(self._t("custom_icon_saved"), GREEN)
        else:
            self._flash_status(self._t("custom_icon_err"), RED)

    def _select_device(self, idx: int) -> None:
        if not self.all_results or idx < 0 or idx >= len(self.all_results):
            return
        self.selected_device_idx = idx
        self.latest_result = self.all_results[idx]
        self._selected_device_slug = self.latest_result.get("device_slug")
        self._chart_zoom = None
        self._record_telemetry(
            "select_device",
            requested=self._selected_device_slug,
            api_ok=True,
            actual=self._selected_device_slug,
            verified=True,
            extra={"display": self.latest_result.get("device"), "source": self.latest_result.get("source")},
        )
        self._update_tray_and_ui(self.latest_result)
        self._flash_status(self._t("switched_device", device=_short_device_name(self.latest_result["device"], 24)), ACCENT)

    def _hide_device(self, slug: str, display_name: str = "") -> None:
        """Persist device slug into hidden_devices config and remove it from the active switcher list."""
        if not slug:
            return
        cfg = monitor.load_config()
        hidden = list(cfg.get("hidden_devices", []))
        if slug not in hidden:
            hidden.append(slug)
        cfg["hidden_devices"] = hidden
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self._record_telemetry("hide_device", requested=slug, api_ok=True, actual=hidden, verified=(slug in hidden))

        remaining = [item for item in (self.all_results or []) if item.get("device_slug") != slug]
        self.all_results = remaining
        if remaining:
            if self._selected_device_slug == slug or self.selected_device_idx >= len(remaining):
                self.selected_device_idx = 0
            else:
                match = next((i for i, d in enumerate(remaining) if d.get("device_slug") == self._selected_device_slug), 0)
                self.selected_device_idx = match
            self.latest_result = remaining[self.selected_device_idx]
            self._selected_device_slug = self.latest_result.get("device_slug")
        else:
            self.selected_device_idx = 0
            self.latest_result = None
            self._selected_device_slug = None
        self._chart_zoom = None
        self._update_tray_and_ui(self.latest_result)
        self._flash_status(self._t("device_hidden_toast", device=_short_device_name(display_name or slug, 24)), AMBER)

    def _restore_hidden_devices(self) -> None:
        """Clear hidden_devices list and trigger immediate rediscovery."""
        cfg = monitor.load_config()
        cfg["hidden_devices"] = []
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self._on_refresh_now()
        self._flash_status(self._t("device_restored_toast"), GREEN)

    def _open_device_menu(self, event: Any = None) -> None:
        if not self.win or not self.win.winfo_exists():
            return
        pill = self._widgets.get("device_pill")
        if not pill:
            return

        existing = getattr(self, "_device_popover", None)
        if existing is not None and existing.winfo_exists():
            existing.destroy()
            self._device_popover = None
            return

        pop = ctk.CTkToplevel(self.win)
        pop.wm_overrideredirect(True)
        pop.wm_attributes("-topmost", True)
        chroma = "#010203"
        pop.configure(bg=chroma)
        try:
            pop.wm_attributes("-transparentcolor", chroma)
        except Exception:
            pass

        card = ctk.CTkFrame(
            pop,
            fg_color=CARD,
            border_color=BORDER,
            border_width=1,
            corner_radius=10,
            bg_color=chroma,
        )
        card.pack()

        def _choose(index: int) -> None:
            if pop.winfo_exists():
                pop.destroy()
            self._device_popover = None
            self._select_device(index)

        def _hide_item(slug: str, name: str) -> None:
            if pop.winfo_exists():
                pop.destroy()
            self._device_popover = None
            self._hide_device(slug, name)

        items = self.all_results or []
        for idx, item in enumerate(items):
            is_sel = (idx == self.selected_device_idx)
            pct = item.get("percentage")
            short_name = _short_device_name(item["device"], 30)
            prefix = "✓ " if is_sel else "   "
            label_txt = f"{prefix}{short_name}  •  {int(round(pct))}%" if pct is not None else f"{prefix}{short_name}"
            row_frame = ctk.CTkFrame(
                card,
                fg_color=CARD_ALT if is_sel else "transparent",
                corner_radius=7,
            )
            row_frame.pack(fill="x", padx=6, pady=(6 if idx == 0 else 2, 2))
            ctk.CTkButton(
                row_frame,
                text=label_txt,
                anchor="w",
                command=lambda i=idx: _choose(i),
                fg_color="transparent",
                hover_color=BORDER,
                text_color=ACCENT if is_sel else FG,
                font=ctk.CTkFont("Segoe UI", 11, "bold" if is_sel else "normal"),
                height=30,
                width=235,
                corner_radius=7,
            ).pack(side="left", fill="x", expand=True)
            slug_val = str(item.get("device_slug", ""))
            del_btn = ctk.CTkButton(
                row_frame,
                text="✕",
                command=lambda s=slug_val, n=str(item["device"]): _hide_item(s, n),
                fg_color="transparent",
                hover_color=BORDER,
                text_color=FG_MUTED,
                font=ctk.CTkFont("Segoe UI", 10, "bold"),
                width=26,
                height=26,
                corner_radius=6,
            )
            del_btn.pack(side="right", padx=(2, 2))
            DelayedTooltip(del_btn, self._t("device_hide_tip"), delay_ms=400)

        if items:
            ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(fill="x", padx=10, pady=4)

        def _do_refresh() -> None:
            if pop.winfo_exists():
                pop.destroy()
            self._device_popover = None
            self._on_refresh_now()
            self._flash_status(self._t("toast_refreshed"), ACCENT)

        def _do_restore() -> None:
            if pop.winfo_exists():
                pop.destroy()
            self._device_popover = None
            self._restore_hidden_devices()

        hidden_count = len(self.cfg.get("hidden_devices", []))
        ctk.CTkButton(
            card,
            text=f"⟳  {self._t('device_menu_refresh')}",
            anchor="w",
            command=_do_refresh,
            fg_color="transparent",
            hover_color=CARD_ALT,
            text_color=FG_MUTED,
            font=ctk.CTkFont("Segoe UI", 11),
            height=30,
            width=265,
            corner_radius=7,
        ).pack(fill="x", padx=6, pady=(2, 2 if hidden_count > 0 else 6))

        if hidden_count > 0:
            ctk.CTkButton(
                card,
                text=f"↺  {self._t('device_restore_hidden', n=hidden_count)}",
                anchor="w",
                command=_do_restore,
                fg_color="transparent",
                hover_color=CARD_ALT,
                text_color=FG_MUTED,
                font=ctk.CTkFont("Segoe UI", 11),
                height=30,
                width=265,
                corner_radius=7,
            ).pack(fill="x", padx=6, pady=(0, 6))

        pop.update_idletasks()
        pw = pop.winfo_reqwidth()
        x = max(12, pill.winfo_rootx() + pill.winfo_width() - pw)
        y = pill.winfo_rooty() + pill.winfo_height() + 6
        pop.wm_geometry(f"+{x}+{y}")
        pop.focus_force()
        pop.bind("<FocusOut>", lambda _: pop.after(50, lambda: pop.destroy() if pop.winfo_exists() else None))
        self._device_popover = pop

    def _cycle_device(self, event: Any = None) -> None:
        if len(self.all_results) <= 1:
            return
        self._select_device((self.selected_device_idx + 1) % len(self.all_results))

    def _draw_connection_icon(self, is_charging: bool, conn_hint: str = "lightspeed") -> None:
        c = self._conn_canvas
        if not c:
            return
        c.delete("all")
        if conn_hint == "bluetooth":
            mode, tooltip = "bluetooth", self._t("conn_bluetooth")
        else:
            mode, tooltip = mouse_features.detect_connection_type(is_charging=is_charging)
        if self._conn_tooltip:
            self._conn_tooltip.text = tooltip

        if mode == "bluetooth":
            # Crisp Bluetooth rune icon
            c.create_line(15, 4, 15, 24, fill=ACCENT, width=2)
            c.create_line(15, 4, 21, 9, fill=ACCENT, width=2)
            c.create_line(21, 9, 9, 19, fill=ACCENT, width=2)
            c.create_line(9, 9, 21, 19, fill=ACCENT, width=2)
            c.create_line(21, 19, 15, 24, fill=ACCENT, width=2)
        elif mode == "usb":
            # Minimalist USB plug icon
            c.create_rectangle(10, 5, 20, 12, outline=ACCENT, width=1.8)
            c.create_rectangle(8, 12, 22, 21, fill=CARD_ALT, outline=ACCENT, width=1.8)
            c.create_line(15, 21, 15, 26, fill=ACCENT, width=2)
        else:
            # G HUB style LIGHTSPEED wireless arcs + center lightning bolt
            arc_color = ACCENT if is_charging else FG_MUTED
            c.create_arc(2, 6, 28, 30, start=42, extent=96, style="arc", outline=arc_color, width=2)
            c.create_arc(6, 11, 24, 27, start=42, extent=96, style="arc", outline=arc_color, width=2)
            bolt = [(16, 11), (12, 18), (15, 18), (14, 25), (19, 17), (16, 17)]
            c.create_polygon(bolt, fill=ACCENT if is_charging else FG)

    def _draw_gauge(self, pct: int | None, is_charging: bool, color: str) -> None:
        c = self._gauge_canvas
        if not c:
            return
        cache_key = (pct, is_charging, color, CARD, CARD_ALT, FG, FG_MUTED, self._lang)
        if cache_key == self._gauge_cache_key and self._gauge_photo is not None and c.find_withtag("gauge_real"):
            return
        c.delete("all")
        w = 136
        pad = 12
        stroke = 12
        scale = 4
        s = w * scale
        st = stroke * scale
        op = (pad - stroke / 2.0) * scale
        bbox = [op, op, s - op, s - op]
        cx = s / 2.0
        cy = s / 2.0
        r_mid = (s - 2.0 * op) / 2.0 - st / 2.0
        cap_r = st / 2.0

        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        def _draw_capped_arc(start_deg: float, end_deg: float, rgba: tuple[int, int, int, int]) -> None:
            draw.arc(bbox, start=start_deg, end=end_deg, fill=rgba, width=st)
            for deg in (start_deg, end_deg):
                rad = math.radians(deg)
                ex = cx + r_mid * math.cos(rad)
                ey = cy + r_mid * math.sin(rad)
                draw.ellipse([ex - cap_r, ey - cap_r, ex + cap_r, ey + cap_r], fill=rgba)

        # Track ring (270 deg sweep from bottom-left 135° clockwise to bottom-right 405°)
        _draw_capped_arc(135.0, 405.0, _hex_to_rgba(CARD_ALT, 255))

        # Active progress arc (only drawn when battery telemetry is available)
        if pct is not None:
            clamped = max(0, min(100, int(pct)))
            if clamped > 0:
                sweep = 270.0 * clamped / 100.0
                _draw_capped_arc(135.0, 135.0 + sweep, _hex_to_rgba(color, 255))

        img_1x = img.resize((w, w), Image.Resampling.LANCZOS)
        self._gauge_photo = ImageTk.PhotoImage(img_1x)
        c.create_image(0, 0, anchor="nw", image=self._gauge_photo, tags=("gauge_real",))

        # Center text
        if pct is None:
            c.create_text(w / 2, w / 2 - 4, text="—", fill=FG_MUTED, font=("Segoe UI", 24, "bold"))
            c.create_text(w / 2, w / 2 + 22, text=self._t("unknown").upper(), fill=FG_MUTED, font=("Segoe UI", 8, "bold"))
        else:
            c.create_text(w / 2, w / 2 - 4, text=f"{pct}%", fill=FG, font=("Segoe UI", 24, "bold"))
            sub = self._t("gauge_charging") if is_charging else self._t("gauge_battery")
            c.create_text(w / 2, w / 2 + 22, text=sub, fill=color, font=("Segoe UI", 8, "bold"))
        self._gauge_cache_key = cache_key

    def _draw_history_chart(self) -> None:
        c = self._chart_canvas
        if not c:
            return
        c.delete("all")
        self._chart_meta = {}
        w = max(460, c.winfo_width() if c.winfo_width() > 10 else 500)
        h = max(190, c.winfo_height() if c.winfo_height() > 10 else 205)
        pad_l, pad_r, pad_t, pad_b = 38, 16, 16, 28
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        # Horizontal gridlines every 10% (major labels every 20%, subtle minor lines at 10/30/50/70/90)
        for y_pct in range(0, 101, 10):
            y = pad_t + plot_h * (1 - y_pct / 100.0)
            is_major = (y_pct % 20 == 0)
            line_color = GRID_MAJOR if is_major else GRID_MINOR
            c.create_line(pad_l, y, w - pad_r, y, fill=line_color, dash=(3, 3) if is_major else (2, 4))

        active_slug = (self.latest_result or {}).get("device_slug")
        active_pct = (self.latest_result or {}).get("percentage")
        if self.latest_result is not None and active_pct is None:
            for y_pct in range(0, 101, 20):
                y = pad_t + plot_h * (1 - y_pct / 100.0)
                c.create_text(pad_l - 6, y, text=f"{y_pct}%", fill=FG_MUTED, anchor="e", font=("Segoe UI", 8))
            msg = self._t("battery_unavailable")
            c.create_text(pad_l + plot_w / 2, pad_t + plot_h / 2, text=msg, fill=FG_MUTED, font=("Segoe UI", 9))
            self._chart_zoom = None
            self._update_zoom_btn()
            return

        history = monitor.load_history(int(self.cfg.get("max_history_days", 30)))
        if active_slug:
            history = [p for p in history if p.get("device") == active_slug]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.chart_range_hours)
        pts = [p for p in history if datetime.fromisoformat(p["ts"]) >= cutoff]
        pts.sort(key=lambda x: x["ts"])

        if len(pts) < 2:
            for y_pct in range(0, 101, 20):
                y = pad_t + plot_h * (1 - y_pct / 100.0)
                c.create_text(pad_l - 6, y, text=f"{y_pct}%", fill=FG_MUTED, anchor="e", font=("Segoe UI", 8))
            msg = self._t("collecting_samples")
            c.create_text(pad_l + plot_w / 2, pad_t + plot_h / 2, text=msg, fill=FG_MUTED, font=("Segoe UI", 9))
            self._chart_zoom = None
            self._update_zoom_btn()
            return

        t_min = datetime.fromisoformat(pts[0]["ts"]).timestamp()
        t_now = datetime.fromisoformat(pts[-1]["ts"]).timestamp()

        # Forecast window: project forward using learned drain rate
        raw_rate = self.latest_result.get("drain_rate_pct_per_hour") if self.latest_result else None
        drain_rate = (
            float(raw_rate)
            if raw_rate is not None
            else float(self.cfg.get("default_drain_rate_pct_per_hour", 1.5))
        )
        last_pct = max(0.0, min(100.0, float(pts[-1]["pct"])))
        hours_to_zero = (last_pct / drain_rate) if drain_rate > 0 else 48.0
        # Cap forecast horizon nicely relative to the selected view
        max_forecast_h = {24: 12.0, 168: 72.0, 720: 120.0}.get(self.chart_range_hours, 24.0)
        forecast_h = max(2.0, min(hours_to_zero, max_forecast_h))
        t_max = t_now + forecast_h * 3600.0

        t_full_min = t_min
        t_full_max = max(t_full_min + 60.0, t_max)
        t_view_min = t_full_min
        t_view_max = t_full_max
        if self._chart_zoom is not None:
            z_min = max(t_full_min, float(self._chart_zoom[0]))
            z_max = min(t_full_max, float(self._chart_zoom[1]))
            if (z_max - z_min) >= 60.0 and (z_max - z_min) < (t_full_max - t_full_min) * 0.995:
                t_view_min, t_view_max = z_min, z_max
                self._chart_zoom = (t_view_min, t_view_max)
            else:
                self._chart_zoom = None
        t_view_span = max(60.0, t_view_max - t_view_min)

        # Historical points: (x, y, is_charging, pct, ts, is_forecast)
        coords: list[tuple[float, float, bool, float, float, bool]] = []
        for p in pts:
            t = datetime.fromisoformat(p["ts"]).timestamp()
            x = pad_l + ((t - t_view_min) / t_view_span) * plot_w
            pct_val = max(0.0, min(100.0, float(p["pct"])))
            y = pad_t + plot_h * (1 - pct_val / 100.0)
            coords.append((x, y, bool(p.get("charging", False)), pct_val, t, False))

        # Forecast endpoint
        end_pct = max(0.0, last_pct - drain_rate * forecast_h)
        fx = pad_l + ((t_full_max - t_view_min) / t_view_span) * plot_w
        fy = pad_t + plot_h * (1 - end_pct / 100.0)
        now_x, now_y = coords[-1][0], coords[-1][1]
        now_visible = (pad_l <= now_x <= (w - pad_r))

        # Subtle vertical "Now" divider behind the smooth curve layer
        if now_visible:
            c.create_line(now_x, pad_t, now_x, pad_t + plot_h, fill=GRID_MAJOR, dash=(2, 3), width=1)

        # Smooth monotone cubic curve + 4x supersampled anti-aliased rendering
        samples = 6
        raw_xy = [(x, y) for x, y, _, _, _, _ in coords]
        smooth_xy = [
            (sx, max(float(pad_t), min(float(pad_t + plot_h), sy)))
            for sx, sy in _monotone_smooth(raw_xy, samples_per_seg=samples)
        ]

        scale = 4
        sw, sh = w * scale, h * scale
        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))

        # Translucent vertical gradient fill under smoothed curve
        bottom_px = int(round((pad_t + plot_h) * scale))
        top_px = max(0, min(bottom_px - 1, int(min(sy for _, sy in smooth_xy) * scale)))
        mask = Image.new("L", (sw, sh), 0)
        mdraw = ImageDraw.Draw(mask)
        poly = (
            [(smooth_xy[0][0] * scale, float(bottom_px))]
            + [(sx * scale, sy * scale) for sx, sy in smooth_xy]
            + [(smooth_xy[-1][0] * scale, float(bottom_px))]
        )
        mdraw.polygon(poly, fill=255)

        fill_rgb = _hex_to_rgba(ACCENT, 255)[:3]
        col_img = Image.new("RGBA", (1, sh), (0, 0, 0, 0))
        col_px = col_img.load()
        span_px = max(1, bottom_px - top_px)
        for yy in range(top_px, min(sh, bottom_px + 1)):
            frac_y = (yy - top_px) / span_px
            alpha_y = int(round(88 - 78 * frac_y))
            col_px[0, yy] = (fill_rgb[0], fill_rgb[1], fill_rgb[2], max(8, min(92, alpha_y)))
        grad_full = col_img.resize((sw, sh), Image.Resampling.NEAREST)
        img.paste(grad_full, (0, 0), mask)

        draw = ImageDraw.Draw(img)

        # Smooth colored historical segments with rounded joins
        line_w = max(2, int(round(2.6 * scale)))
        cap_r = line_w / 2.0
        for j in range(len(smooth_xy) - 1):
            x1, y1 = smooth_xy[j]
            x2, y2 = smooth_xy[j + 1]
            orig_i = min(j // samples, len(coords) - 2)
            chg1, pct1 = coords[orig_i][2], coords[orig_i][3]
            chg2 = coords[orig_i + 1][2]
            seg_color = ACCENT if (chg1 or chg2) else (RED if pct1 <= 20 else (AMBER if pct1 <= 40 else GREEN))
            seg_rgba = _hex_to_rgba(seg_color, 255)
            sx1, sy1, sx2, sy2 = x1 * scale, y1 * scale, x2 * scale, y2 * scale
            if j == 0:
                draw.ellipse([sx1 - cap_r, sy1 - cap_r, sx1 + cap_r, sy1 + cap_r], fill=seg_rgba)
            draw.line([(sx1, sy1), (sx2, sy2)], fill=seg_rgba, width=line_w)
            draw.ellipse([sx2 - cap_r, sy2 - cap_r, sx2 + cap_r, sy2 + cap_r], fill=seg_rgba)

        # Anti-aliased dashed amber forecast line
        fc_dist = math.hypot(fx - now_x, fy - now_y)
        if fc_dist > 1e-3:
            fc_rgba = _hex_to_rgba(AMBER, 240)
            fc_w = max(2, int(round(2.0 * scale)))
            fc_r = fc_w / 2.0
            ux = (fx - now_x) / fc_dist
            uy = (fy - now_y) / fc_dist
            d_pos = 0.0
            while d_pos < fc_dist:
                d_end = min(d_pos + 6.0, fc_dist)
                p1x = (now_x + ux * d_pos) * scale
                p1y = (now_y + uy * d_pos) * scale
                p2x = (now_x + ux * d_end) * scale
                p2y = (now_y + uy * d_end) * scale
                draw.line([(p1x, p1y), (p2x, p2y)], fill=fc_rgba, width=fc_w)
                draw.ellipse([p1x - fc_r, p1y - fc_r, p1x + fc_r, p1y + fc_r], fill=fc_rgba)
                draw.ellipse([p2x - fc_r, p2y - fc_r, p2x + fc_r, p2y + fc_r], fill=fc_rgba)
                d_pos += 11.0

        # Anti-aliased latest point dot ("Now")
        lx, ly, lchg, lpct, _, _ = coords[-1]
        dot_color = ACCENT if lchg else (RED if lpct <= 20 else (AMBER if lpct <= 40 else GREEN))
        dr = 4.6 * scale
        draw.ellipse(
            [lx * scale - dr, ly * scale - dr, lx * scale + dr, ly * scale + dr],
            fill=_hex_to_rgba(dot_color, 255),
            outline=_hex_to_rgba(FG, 255),
            width=max(1, int(round(1.6 * scale))),
        )

        # Clip 4x plot horizontally to [pad_l, w - pad_r] so zoomed lines/dots never overlap Y-axis labels
        left_clip = max(0, int(round(pad_l * scale)))
        right_clip = min(sw, int(round((w - pad_r) * scale)))
        if right_clip > left_clip:
            clipped = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            clipped.paste(img.crop((left_clip, 0, right_clip, sh)), (left_clip, 0))
            img = clipped

        chart_1x = img.resize((w, h), Image.Resampling.LANCZOS)
        self._chart_photo = ImageTk.PhotoImage(chart_1x)
        c.create_image(0, 0, anchor="nw", image=self._chart_photo)

        # Crisp ClearType axis & forecast labels on top
        for y_pct in range(0, 101, 20):
            y = pad_t + plot_h * (1 - y_pct / 100.0)
            c.create_text(pad_l - 6, y, text=f"{y_pct}%", fill=FG_MUTED, anchor="e", font=("Segoe UI", 8))

        if now_visible and ((w - pad_r) - now_x) > 54:
            c.create_text(
                min(w - pad_r - 4, now_x + 6),
                pad_t + 6,
                text=self._t("forecast"),
                fill=AMBER,
                anchor="nw",
                font=("Segoe UI", 8, "bold"),
            )

        # Build smoothed hover coordinates (preserving 6-tuple shape for _on_chart_hover)
        hover_coords: list[tuple[float, float, bool, float, float, bool]] = []
        last_sm_idx = len(smooth_xy) - 1
        for k, (sx, sy) in enumerate(smooth_xy):
            if k == last_sm_idx:
                hover_coords.append(coords[-1])
            else:
                orig_i = min(k // samples, len(coords) - 2)
                frac = (k % samples) / samples
                chg_k = coords[orig_i][2]
                pct_k = max(0.0, min(100.0, (1.0 - (sy - pad_t) / plot_h) * 100.0))
                ts_k = coords[orig_i][4] + frac * (coords[orig_i + 1][4] - coords[orig_i][4])
                hover_coords.append((sx, sy, chg_k, pct_k, ts_k, False))
        hover_coords.append((fx, fy, False, end_pct, t_full_max, True))

        # X-axis dynamic non-overlapping timestamps (local time, unclipped at h - 11)
        view_hours = t_view_span / 3600.0
        if self.chart_range_hours <= 24:
            fmt = "%H:%M"
        elif view_hours < 36.0:
            fmt = "%b %d %H:%M"
        else:
            fmt = "%b %d"

        if self._axis_font is None:
            self._axis_font = tkfont.Font(family="Segoe UI", size=8)
        t0_lbl = datetime.fromtimestamp(t_view_min, tz=timezone.utc).astimezone().strftime(fmt)
        t_end_lbl = datetime.fromtimestamp(t_view_max, tz=timezone.utc).astimezone().strftime(fmt)
        label_w = max(self._axis_font.measure(t0_lbl), self._axis_font.measure(t_end_lbl), 28)

        ticks = compute_chart_time_ticks(pad_l, plot_w, t_view_min, t_view_max, label_w, min_gap_px=80.0)
        placed_spans: list[tuple[float, float]] = []
        for idx, (tx, ts_val, anchor) in enumerate(ticks):
            lbl = datetime.fromtimestamp(ts_val, tz=timezone.utc).astimezone().strftime(fmt)
            lbl_w = self._axis_font.measure(lbl)
            tick_color = AMBER if ts_val > (t_now + 60.0) else FG_MUTED
            if 0 < idx < len(ticks) - 1:
                c.create_line(tx, pad_t + plot_h, tx, pad_t + plot_h + 3, fill=BORDER, width=1)
            c.create_text(tx, h - 11, text=lbl, fill=tick_color, anchor=anchor, font=("Segoe UI", 8))
            if anchor == "w":
                placed_spans.append((tx, tx + lbl_w))
            elif anchor == "e":
                placed_spans.append((tx - lbl_w, tx))
            else:
                placed_spans.append((tx - lbl_w / 2.0, tx + lbl_w / 2.0))

        if now_visible:
            now_lbl = self._t("now")
            now_w = self._axis_font.measure(now_lbl)
            now_left, now_right = now_x - now_w / 2.0, now_x + now_w / 2.0
            min_clear = min(
                max(0.0, max(s_left - now_right, now_left - s_right))
                for s_left, s_right in placed_spans
            ) if placed_spans else 999.0
            if min_clear >= 36.0 and now_left >= pad_l and now_right <= (w - pad_r):
                c.create_text(
                    now_x, h - 11, text=now_lbl, fill=FG_MUTED, anchor="center", font=("Segoe UI", 8, "bold")
                )
            elif (now_x - pad_l) > (now_w + 10):
                c.create_text(
                    now_x - 5, pad_t + 6, text=now_lbl, fill=FG_MUTED, anchor="ne", font=("Segoe UI", 8, "bold")
                )

        self._chart_meta = {
            "pad_l": pad_l,
            "pad_r": pad_r,
            "pad_t": pad_t,
            "pad_b": pad_b,
            "w": w,
            "h": h,
            "plot_h": plot_h,
            "coords": hover_coords,
            "t_full_min": t_full_min,
            "t_full_max": t_full_max,
            "t_view_min": t_view_min,
            "t_view_max": t_view_max,
        }
        self._update_zoom_btn()

    def _on_chart_leave(self, event: Any = None) -> None:
        if self._chart_canvas:
            self._chart_canvas.delete("hover")

    def _on_chart_hover(self, event: Any) -> None:
        c = self._chart_canvas
        meta = self._chart_meta
        if not c or not meta or not meta.get("coords"):
            return
        c.delete("hover")

        pad_l = meta["pad_l"]
        pad_t = meta["pad_t"]
        plot_h = meta["plot_h"]
        w = meta["w"]
        pad_r = meta["pad_r"]
        coords = meta["coords"]

        mx = event.x
        if mx < pad_l or mx > (w - pad_r):
            return

        # Smoothly clamp playhead X to the data range and linearly interpolate along the curve
        x_start = coords[0][0]
        x_end = coords[-1][0]
        nx = max(x_start, min(x_end, float(mx)))

        ny, nchg, npct, nts, nis_fc = coords[-1][1], coords[-1][2], coords[-1][3], coords[-1][4], coords[-1][5]
        for i in range(len(coords) - 1):
            x1, y1, chg1, pct1, t1, fc1 = coords[i]
            x2, y2, chg2, pct2, t2, fc2 = coords[i + 1]
            if x1 <= nx <= x2:
                frac = (nx - x1) / (x2 - x1) if (x2 - x1) > 1e-6 else 0.0
                ny = y1 + frac * (y2 - y1)
                npct = pct1 + frac * (pct2 - pct1)
                nts = t1 + frac * (t2 - t1)
                nchg = chg1 if frac < 0.5 else chg2
                nis_fc = fc2
                break

        # Audacity-style vertical playhead line + top marker cap
        c.create_line(nx, pad_t, nx, pad_t + plot_h, fill=AMBER if nis_fc else PLAYHEAD, width=1.5, tags="hover")
        c.create_polygon(
            nx - 5, pad_t - 8,
            nx + 5, pad_t - 8,
            nx + 5, pad_t - 3,
            nx, pad_t + 1,
            nx - 5, pad_t - 3,
            fill=AMBER if nis_fc else PLAYHEAD,
            outline=BG,
            width=1,
            tags="hover",
        )

        # Highlight point on the curve
        dot_color = AMBER if nis_fc else (ACCENT if nchg else (RED if npct <= 20 else (AMBER if npct <= 40 else GREEN)))
        c.create_oval(nx - 5, ny - 5, nx + 5, ny + 5, fill=dot_color, outline=FG, width=2, tags="hover")

        # Floating tooltip pill (auto-flips left/right so it never clips)
        time_fmt = "%H:%M" if self.chart_range_hours <= 24 else "%b %d %H:%M"
        time_str = datetime.fromtimestamp(nts, tz=timezone.utc).astimezone().strftime(time_fmt)
        if nis_fc:
            label_text = self._t("hover_est_fmt", pct=int(round(npct)), time=time_str)
            box_w = max(152 if self.chart_range_hours <= 24 else 178, len(label_text) * 7 + 20)
        else:
            chg_str = " ⚡" if nchg else ""
            label_text = self._t("hover_hist_fmt", pct=int(round(npct)), chg=chg_str, time=time_str)
            box_w = max(118 if self.chart_range_hours <= 24 else 144, len(label_text) * 7 + 20)
        box_h = 26
        tx = nx + 10 if (nx + 10 + box_w) <= (w - pad_r) else (nx - 10 - box_w)
        ty = max(pad_t + 4, min(pad_t + plot_h - box_h - 4, ny - box_h / 2))

        c.create_rectangle(
            tx, ty, tx + box_w, ty + box_h,
            fill=TIP_BG,
            outline=BORDER,
            width=1.5,
            tags="hover",
        )
        c.create_text(
            tx + box_w / 2,
            ty + box_h / 2,
            text=label_text,
            fill=FG,
            font=("Segoe UI", 9, "bold"),
            tags="hover",
        )

    # ==================== PAGE 2: NOTIFICATIONS ====================
    def _build_notifications_page(self, parent: ctk.CTkFrame) -> None:
        cfg = monitor.load_config()
        self._vars["notifications_enabled"] = tk.BooleanVar(value=bool(cfg.get("notifications_enabled", True)))
        self._vars["close_to_tray"] = tk.BooleanVar(value=bool(cfg.get("close_to_tray", True)))
        self._vars["autostart"] = tk.BooleanVar(value=mouse_features.get_autostart())
        self._vars["notification_sound"] = tk.StringVar(value=str(cfg.get("notification_sound", "Default")))
        self._vars["evening_hour"] = tk.IntVar(value=int(cfg.get("evening_hour", 22)))
        self._vars["low_battery_threshold"] = tk.IntVar(value=int(cfg.get("low_battery_threshold", 20)))
        self._vars["critical_battery_threshold"] = tk.IntVar(value=int(cfg.get("critical_battery_threshold", 10)))
        self._vars["cooldown_minutes"] = tk.IntVar(value=int(cfg.get("cooldown_minutes", 60)))
        self._vars["poll_interval_minutes"] = tk.IntVar(value=int(cfg.get("poll_interval_minutes", 5)))

        # Card 1: General & Sound
        card1 = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        card1.pack(fill="x", pady=(0, 12))
        c1 = ctk.CTkFrame(card1, fg_color=CARD)
        c1.pack(fill="x", padx=16, pady=14)

        ctk.CTkSwitch(
            c1,
            text=self._t("enable_notifs"),
            variable=self._vars["notifications_enabled"],
            command=self._save_notification_settings,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            text_color=FG,
            switch_width=40,
            switch_height=20,
            fg_color=SWITCH_TRACK_OFF,
            progress_color=ACCENT,
            button_color=SWITCH_BUTTON,
            button_hover_color=SWITCH_BUTTON_HOVER,
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkSwitch(
            c1,
            text=self._t("close_to_tray"),
            variable=self._vars["close_to_tray"],
            command=self._on_toggle_close_to_tray,
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=FG,
            switch_width=40,
            switch_height=20,
            fg_color=SWITCH_TRACK_OFF,
            progress_color=ACCENT,
            button_color=SWITCH_BUTTON,
            button_hover_color=SWITCH_BUTTON_HOVER,
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkSwitch(
            c1,
            text=self._t("start_with_windows"),
            variable=self._vars["autostart"],
            command=self._on_toggle_autostart,
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=FG,
            switch_width=40,
            switch_height=20,
            fg_color=SWITCH_TRACK_OFF,
            progress_color=ACCENT,
            button_color=SWITCH_BUTTON,
            button_hover_color=SWITCH_BUTTON_HOVER,
        ).pack(anchor="w", pady=(0, 10))

        sound_row = ctk.CTkFrame(c1, fg_color=CARD)
        sound_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            sound_row, text=self._t("notif_sound"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        ctk.CTkButton(
            sound_row,
            text=self._t("preview"),
            width=82,
            height=28,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            command=self._preview_sound,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkOptionMenu(
            sound_row,
            values=list(monitor.SOUND_EVENTS.keys()),
            variable=self._vars["notification_sound"],
            command=lambda _: self._save_notification_settings(),
            width=132,
            height=28,
            fg_color=CARD_ALT,
            button_color=BORDER,
            button_hover_color=ACCENT,
            text_color=FG,
            dropdown_fg_color=CARD,
            dropdown_hover_color=CARD_ALT,
            dropdown_text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11),
        ).pack(side="right")

        theme_row = ctk.CTkFrame(c1, fg_color=CARD)
        theme_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            theme_row, text=self._t("appearance_theme"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        theme_pairs = [
            ("System", self._t("theme_system")),
            ("Dark", self._t("theme_dark")),
            ("Light", self._t("theme_light")),
        ]
        saved_theme = str(cfg.get("theme", "Dark"))
        if cfg.get("matrix_unlocked") or saved_theme == "Matrix":
            theme_pairs.append(("Matrix", "Matrix"))
        self._theme_to_lbl = {k: lbl for k, lbl in theme_pairs}
        self._lbl_to_theme = {lbl: k for k, lbl in theme_pairs}
        theme_seg = ctk.CTkSegmentedButton(
            theme_row,
            values=[lbl for _, lbl in theme_pairs],
            command=self._on_theme_change,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=28,
            width=268 if len(theme_pairs) > 3 else 222,
        )
        canonical_theme = saved_theme if saved_theme in self._theme_to_lbl else "Dark"
        theme_seg.set(self._theme_to_lbl[canonical_theme])
        theme_seg.pack(side="right")

        accent_row = ctk.CTkFrame(c1, fg_color=CARD)
        accent_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            accent_row, text=self._t("accent_color"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        accent_pairs = [
            ("Windows", self._t("accent_windows")),
            ("Default", self._t("accent_default")),
        ]
        self._accent_to_lbl = {k: lbl for k, lbl in accent_pairs}
        self._lbl_to_accent = {lbl: k for k, lbl in accent_pairs}
        accent_seg = ctk.CTkSegmentedButton(
            accent_row,
            values=[lbl for _, lbl in accent_pairs],
            command=self._on_accent_change,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=28,
            width=222,
        )
        saved_accent = str(cfg.get("accent_mode", "Windows"))
        canonical_accent = saved_accent if saved_accent in self._accent_to_lbl else "Windows"
        accent_seg.set(self._accent_to_lbl[canonical_accent])
        accent_seg.pack(side="right")

        lang_row = ctk.CTkFrame(c1, fg_color=CARD)
        lang_row.pack(fill="x")
        ctk.CTkLabel(
            lang_row, text=self._t("language"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        lang_seg = ctk.CTkSegmentedButton(
            lang_row,
            values=list(i18n.LANG_LABELS.values()),
            command=self._on_language_change,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=28,
            width=222,
        )
        lang_seg.set(i18n.LANG_LABELS.get(self._lang, "English"))
        lang_seg.pack(side="right")

        # Card 2: Sliders
        card2 = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        card2.pack(fill="x", pady=(0, 14))
        c2 = ctk.CTkFrame(card2, fg_color=CARD)
        c2.pack(fill="x", padx=16, pady=12)

        min_u = self._t("min_unit")
        sliders = [
            (self._t("slider_evening"), "evening_hour", 12, 23, lambda v: f"{int(v):02d}:00"),
            (self._t("slider_low"), "low_battery_threshold", 5, 50, lambda v: f"{int(v)}%"),
            (self._t("slider_critical"), "critical_battery_threshold", 3, 25, lambda v: f"{int(v)}%"),
            (self._t("slider_cooldown"), "cooldown_minutes", 5, 240, lambda v, u=min_u: f"{int(v)} {u}"),
            (self._t("slider_poll"), "poll_interval_minutes", 1, 60, lambda v, u=min_u: f"{int(v)} {u}"),
        ]
        for label_text, key, lo, hi, fmt in sliders:
            row = ctk.CTkFrame(c2, fg_color=CARD)
            row.pack(fill="x", pady=5)
            hdr = ctk.CTkFrame(row, fg_color=CARD)
            hdr.pack(fill="x")
            ctk.CTkLabel(hdr, text=label_text, font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED).pack(side="left")
            val_lbl = ctk.CTkLabel(
                hdr, text=fmt(self._vars[key].get()), font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=ACCENT
            )
            val_lbl.pack(side="right")

            def _make_cb(k: str, lbl: ctk.CTkLabel, f: Any):
                def _cb(val: float) -> None:
                    self._vars[k].set(int(round(val)))
                    lbl.configure(text=f(round(val)))
                    self._save_notification_settings(quiet=True)
                return _cb

            sl = ctk.CTkSlider(
                row,
                from_=lo,
                to=hi,
                number_of_steps=hi - lo,
                command=_make_cb(key, val_lbl, fmt),
                fg_color=SWITCH_TRACK_OFF,
                progress_color=ACCENT,
                button_color=ACCENT,
                button_hover_color=ACCENT_HOVER,
                height=16,
            )
            sl.set(self._vars[key].get())
            sl.pack(fill="x", pady=(2, 0))

    def _preview_sound(self) -> None:
        sound = self._vars["notification_sound"].get()
        threading.Thread(
            target=monitor.send_windows_toast,
            args=(
                self._t("sound_preview_title"),
                self._t("sound_preview_body", sound=sound),
                self._t("app_title"),
                sound,
            ),
            daemon=True,
        ).start()
        self._flash_status(self._t("previewing_sound", sound=sound), ACCENT)

    def _on_toggle_close_to_tray(self) -> None:
        enabled = bool(self._vars["close_to_tray"].get())
        cfg = monitor.load_config()
        cfg["close_to_tray"] = enabled
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        msg = self._t("close_to_tray_on") if enabled else self._t("close_to_tray_off")
        self._flash_status(msg, GREEN)

    def _on_toggle_autostart(self) -> None:
        enabled = bool(self._vars["autostart"].get())
        mouse_features.set_autostart(enabled, BASE_DIR)
        msg = self._t("autostart_on") if enabled else self._t("autostart_off")
        self._flash_status(msg, GREEN)

    def _cancel_theme_transition(self) -> None:
        if self._transition_after_id is not None:
            try:
                self.root.after_cancel(self._transition_after_id)
            except Exception:
                pass
            self._transition_after_id = None
        ov = self._transition_overlay
        self._transition_overlay = None
        self._transition_photo = None
        if ov is not None:
            try:
                if ov.winfo_exists():
                    ov.destroy()
            except Exception:
                pass
        if self.win and self.win.winfo_exists():
            try:
                self.win.attributes("-alpha", 1.0)
            except Exception:
                pass

    def _capture_window_client_snapshot(self, win: ctk.CTkToplevel) -> Image.Image | None:
        try:
            if not win or not win.winfo_exists() or win.state() == "withdrawn":
                return None
            rw = win.winfo_width()
            rh = win.winfo_height()
            if rw < 20 or rh < 20:
                return None

            bbox: tuple[int, int, int, int] | None = None
            if sys.platform == "win32":
                try:
                    hwnd = int(win.winfo_id())
                    rect = ctypes.wintypes.RECT()
                    pt = ctypes.wintypes.POINT(0, 0)
                    user32 = ctypes.windll.user32
                    if user32.GetClientRect(hwnd, ctypes.byref(rect)) and user32.ClientToScreen(hwnd, ctypes.byref(pt)):
                        cw = int(rect.right - rect.left)
                        ch = int(rect.bottom - rect.top)
                        if cw >= 20 and ch >= 20:
                            bbox = (int(pt.x), int(pt.y), int(pt.x) + cw, int(pt.y) + ch)
                except Exception:
                    bbox = None

            if bbox is None:
                rx = win.winfo_rootx()
                ry = win.winfo_rooty()
                bbox = (rx, ry, rx + rw, ry + rh)

            snap = ImageGrab.grab(bbox=bbox, all_screens=True)
            if snap.size != (rw, rh):
                snap = snap.resize((rw, rh), Image.Resampling.LANCZOS)
            return snap
        except Exception:
            return None

    def _transition_theme_rebuild(self, apply_fn: Any, on_done: Any = None) -> None:
        self._cancel_theme_transition()
        win = self.win
        if not win or not win.winfo_exists():
            apply_fn()
            if on_done:
                on_done()
            return
        try:
            is_withdrawn = (win.state() == "withdrawn")
        except Exception:
            is_withdrawn = True
        if is_withdrawn:
            apply_fn()
            if on_done:
                on_done()
            return

        snap = self._capture_window_client_snapshot(win)
        if snap is not None:
            try:
                rx = win.winfo_rootx()
                ry = win.winfo_rooty()
                rw = win.winfo_width()
                rh = win.winfo_height()
                if rw < 20 or rh < 20:
                    raise ValueError("Window too small for overlay")
                ov = tk.Toplevel(self.root)
                ov.wm_overrideredirect(True)
                ov.wm_attributes("-topmost", True)
                ov.wm_attributes("-alpha", 1.0)
                ov.geometry(f"{rw}x{rh}+{rx}+{ry}")
                photo = ImageTk.PhotoImage(snap)
                tk.Label(ov, image=photo, bd=0, highlightthickness=0).pack(fill="both", expand=True)
                self._transition_overlay = ov
                self._transition_photo = photo
                ov.update()

                apply_fn()
                win.update_idletasks()
                if ov.winfo_exists():
                    ov.lift()

                total_steps = 10

                def _fade_step(step: int = 1) -> None:
                    if self._transition_overlay is not ov or not ov.winfo_exists():
                        return
                    if step >= total_steps:
                        self._cancel_theme_transition()
                        if on_done and self.win and self.win.winfo_exists():
                            on_done()
                        return
                    alpha = max(0.0, (1.0 - step / float(total_steps)) ** 1.6)
                    try:
                        ov.wm_attributes("-alpha", alpha)
                    except Exception:
                        self._cancel_theme_transition()
                        return
                    self._transition_after_id = self.root.after(16, _fade_step, step + 1)

                self._transition_after_id = self.root.after(16, _fade_step, 1)
                return
            except Exception:
                self._cancel_theme_transition()

        # Fallback #2: Smooth Window Alpha Dip-Fade
        down_steps = 4
        up_steps = 5

        def _fade_up(step: int = 1) -> None:
            if not self.win or not self.win.winfo_exists():
                self._transition_after_id = None
                return
            if step >= up_steps:
                try:
                    self.win.attributes("-alpha", 1.0)
                except Exception:
                    pass
                self._transition_after_id = None
                if on_done:
                    on_done()
                return
            alpha = 0.15 + 0.85 * (step / float(up_steps))
            try:
                self.win.attributes("-alpha", alpha)
            except Exception:
                self._transition_after_id = None
                return
            self._transition_after_id = self.root.after(16, _fade_up, step + 1)

        def _fade_down(step: int = 1) -> None:
            if not self.win or not self.win.winfo_exists():
                self._transition_after_id = None
                return
            if step < down_steps:
                alpha = max(0.15, 1.0 - 0.85 * (step / float(down_steps)))
                try:
                    self.win.attributes("-alpha", alpha)
                except Exception:
                    pass
                self._transition_after_id = self.root.after(15, _fade_down, step + 1)
                return
            try:
                self.win.attributes("-alpha", 0.15)
            except Exception:
                pass
            apply_fn()
            try:
                self.win.update_idletasks()
            except Exception:
                pass
            self._transition_after_id = self.root.after(16, _fade_up, 1)

        self._transition_after_id = self.root.after(15, _fade_down, 1)

    def _on_theme_change(self, label: str, flash_msg: str | None = None) -> None:
        mode = getattr(self, "_lbl_to_theme", {}).get(label, label)
        cfg = monitor.load_config()
        cfg["theme"] = mode
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        resolved = theme.resolve_theme(mode)
        self._resolved_theme = resolved
        prev_page = self._active_page

        def _apply() -> None:
            apply_theme_tokens(mode, update_ctk_mode=False)
            self._build_window_contents(initial_page=prev_page)
            if self.win and self.win.winfo_exists():
                apply_win_titlebar_theme(self.win, resolved)

        msg = flash_msg if flash_msg is not None else self._t("switched_theme", theme=label)
        self._record_telemetry("set_theme", requested=mode, api_ok=True, actual=resolved, verified=True)
        self._transition_theme_rebuild(_apply, on_done=lambda: self._flash_status(msg, GREEN))

    def _on_accent_change(self, label: str) -> None:
        accent_mode = getattr(self, "_lbl_to_accent", {}).get(label, "Windows")
        cfg = monitor.load_config()
        cfg["accent_mode"] = accent_mode
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        theme_mode = str(cfg.get("theme", "Dark"))
        resolved = theme.resolve_theme(theme_mode)
        self._resolved_theme = resolved
        prev_page = self._active_page

        def _apply() -> None:
            apply_theme_tokens(theme_mode, update_ctk_mode=False, accent_mode=accent_mode)
            self._build_window_contents(initial_page=prev_page)
            if self.win and self.win.winfo_exists():
                apply_win_titlebar_theme(self.win, resolved)

        msg = self._t("switched_accent", mode=label)
        self._record_telemetry(
            "set_accent_mode", requested=accent_mode, api_ok=True, actual=theme.get_accent_mode() or accent_mode, verified=True
        )
        self._transition_theme_rebuild(_apply, on_done=lambda: self._flash_status(msg, GREEN))

    def _on_secret_keypress(self, event: Any) -> None:
        match = self._key_seq.push(getattr(event, "keysym", ""), getattr(event, "keycode", None))
        if match == "konami" and self.win and self.win.winfo_exists():
            kc = self._konami_canvas
            if kc is not None:
                try:
                    if kc.winfo_exists():
                        kc.destroy()
                except Exception:
                    pass
            pal = theme.get_palette(self._resolved_theme)
            self._konami_canvas = easter_eggs.play_mouse_chase_overlay(
                self.win,
                pal,
                on_done=lambda: (
                    setattr(self, "_konami_canvas", None),
                    self._flash_status(self._t("ee_konami_toast"), GREEN),
                ),
            )
        elif match == "matrix":
            self._unlock_or_toggle_matrix(force_matrix=True)

    def _on_title_egg_click(self, _event: Any = None) -> None:
        if self._title_clicks.tap(required=5, window_s=2.5) >= 5:
            self._unlock_or_toggle_matrix(force_matrix=False)

    def _unlock_or_toggle_matrix(self, force_matrix: bool = False) -> None:
        cfg = monitor.load_config()
        cfg["matrix_unlocked"] = True
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        cur = str(cfg.get("theme", "Dark"))
        if force_matrix or cur != "Matrix":
            self._on_theme_change("Matrix", flash_msg=self._t("ee_matrix_unlocked"))
        else:
            self._on_theme_change(self._t("theme_dark"))

    def _open_aim_trainer_egg(self) -> None:
        cfg = monitor.load_config()
        best = int(cfg.get("aim_best_hits", 0))

        def _save_best(hits: int) -> None:
            latest = monitor.load_config()
            if hits > int(latest.get("aim_best_hits", 0)):
                latest["aim_best_hits"] = int(hits)
                monitor.CONFIG_PATH.write_text(json.dumps(latest, indent=2), encoding="utf-8")
                self.cfg = latest

        easter_eggs.open_aim_trainer(
            self._dialog_parent(),
            self._resolved_theme,
            self._t,
            best,
            _save_best,
            icon_path=self._icon_path(),
        )

    def _on_gauge_click(self, _event: Any = None) -> None:
        if self._gauge_clicks.tap(required=5, window_s=2.5) >= 5:
            self._trigger_gauge_overclock()

    def _trigger_gauge_overclock(self) -> None:
        c = self._gauge_canvas
        if not c or not c.winfo_exists():
            return
        if self._gauge_spin_after_id is not None:
            try:
                self.root.after_cancel(self._gauge_spin_after_id)
            except Exception:
                pass
            self._gauge_spin_after_id = None

        r = self.latest_result
        raw_pct = r.get("percentage") if r else None
        pct = int(raw_pct) if raw_pct is not None else None
        pct_text = f"{pct}%" if pct is not None else "—"
        chg = bool(r.get("is_charging", False)) if r else False
        sub = self._t("unknown").upper() if pct is None else (self._t("gauge_charging") if chg else self._t("gauge_battery"))
        rainbow = ("#38BDF8", "#22C55E", "#FACC15", "#F97316", "#EC4899", "#A855F7")
        total_steps = 16

        def _spin_step(step: int = 0) -> None:
            if not self._gauge_canvas or not self._gauge_canvas.winfo_exists():
                self._gauge_spin_after_id = None
                return
            if step >= total_steps:
                self._gauge_spin_after_id = None
                self._refresh_dashboard()
                toast = self._t("battery_unavailable") if pct is None else self._t("ee_gauge_toast", pct=pct)
                self._flash_status(toast, ACCENT)
                return
            ring_color = rainbow[step % len(rainbow)]
            cv = self._gauge_canvas
            cv.delete("all")
            w = 136
            pad = 12
            cv.create_arc(
                pad, pad, w - pad, w - pad,
                start=135 - step * 24,
                extent=270,
                style="arc",
                outline=ring_color,
                width=12,
            )
            cv.create_text(w / 2, w / 2 - 4, text=pct_text, fill=FG, font=("Segoe UI", 24, "bold"))
            cv.create_text(w / 2, w / 2 + 22, text=sub, fill=ring_color, font=("Segoe UI", 8, "bold"))
            self._gauge_spin_after_id = self.root.after(28, _spin_step, step + 1)

        _spin_step(0)

    def _on_language_change(self, label: str) -> None:
        lang = i18n.LABEL_TO_LANG.get(label, "en")
        if lang == self._lang:
            return
        self._lang = lang
        cfg = monitor.load_config()
        cfg["language"] = lang
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self._record_telemetry("set_language", requested=lang, api_ok=True, actual=self._lang, verified=True)
        prev_page = self._active_page
        self._build_window_contents(initial_page=prev_page)
        if self.win and self.win.winfo_exists():
            apply_win_titlebar_theme(self.win, self._resolved_theme)
        if self.icon:
            try:
                self.icon.menu = self._build_menu()
                self.icon.update_menu()
            except Exception:
                pass
        self._flash_status(self._t("switched_lang", lang=label), GREEN)

    def _on_calibration_style_change(self, style: str) -> None:
        cfg = monitor.load_config()
        cfg["calibration_style"] = style
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self._refresh_dashboard()
        self._flash_status(f"✓ Estimate indicator: {style}", GREEN)

    def _save_notification_settings(self, quiet: bool = False) -> None:
        cfg = monitor.load_config()
        cfg["notifications_enabled"] = bool(self._vars["notifications_enabled"].get())
        cfg["close_to_tray"] = bool(self._vars["close_to_tray"].get())
        cfg["notification_sound"] = str(self._vars["notification_sound"].get())
        cfg["evening_hour"] = int(self._vars["evening_hour"].get())
        cfg["low_battery_threshold"] = int(self._vars["low_battery_threshold"].get())
        cfg["critical_battery_threshold"] = int(self._vars["critical_battery_threshold"].get())
        cfg["cooldown_minutes"] = int(self._vars["cooldown_minutes"].get())
        cfg["poll_interval_minutes"] = int(self._vars["poll_interval_minutes"].get())
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg

        self.poll_wakeup.set()
        self._flash_status(self._t("saved_short") if quiet else self._t("settings_saved"), GREEN)

    # ==================== PAGE 3: MOUSE CONTROL ====================
    def _build_mouse_page(self, parent: ctk.CTkFrame) -> None:
        self._vars["pointer_speed"] = tk.IntVar(value=10)
        self._vars["scroll_lines"] = tk.IntVar(value=3)
        self._vars["enhance_precision"] = tk.BooleanVar(value=False)
        self._vars["swap_buttons"] = tk.BooleanVar(value=False)

        # Card 1: One-Click Presets
        preset_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        preset_card.pack(fill="x", pady=(0, 8))
        p_inner = ctk.CTkFrame(preset_card, fg_color=CARD)
        p_inner.pack(fill="x", padx=16, pady=10)

        ctk.CTkLabel(
            p_inner, text=self._t("quick_presets"), font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=FG
        ).pack(anchor="w", pady=(0, 6))

        preset_i18n = {
            "Gaming": ("preset_gaming", "preset_gaming_desc", "preset_gaming_tip"),
            "Precision": ("preset_precision", "preset_precision_desc", "preset_precision_tip"),
            "Productivity": ("preset_productivity", "preset_productivity_desc", "preset_productivity_tip"),
        }
        p_row = ctk.CTkFrame(p_inner, fg_color=CARD)
        p_row.pack(fill="x")
        for idx, (pname, pdata) in enumerate(MOUSE_PRESETS.items()):
            t_k, d_k, tip_k = preset_i18n.get(pname, ("", "", ""))
            lbl_name = self._t(t_k) if t_k else pname
            lbl_desc = self._t(d_k) if d_k else pdata["desc"]
            lbl_tip = self._t(tip_k) if tip_k else pdata["tooltip"]
            btn = ctk.CTkButton(
                p_row,
                text=f"{lbl_name}\n{lbl_desc}",
                command=lambda n=pname: self._apply_preset(n),
                fg_color=CARD_ALT,
                hover_color=BORDER,
                text_color=FG,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                height=44,
                corner_radius=10,
            )
            btn.pack(side="left", fill="x", expand=True, padx=(0 if idx == 0 else 6, 0))
            DelayedTooltip(btn, lbl_tip, delay_ms=1600)

        # Card 2: Pointer & Scroll Fine-Tuning
        tune_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        tune_card.pack(fill="x", pady=(0, 8))
        t_inner = ctk.CTkFrame(tune_card, fg_color=CARD)
        t_inner.pack(fill="x", padx=16, pady=10)

        # Pointer Speed
        sp_hdr = ctk.CTkFrame(t_inner, fg_color=CARD)
        sp_hdr.pack(fill="x")
        ctk.CTkLabel(sp_hdr, text=self._t("pointer_speed"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED).pack(side="left")
        self._widgets["speed_val"] = ctk.CTkLabel(sp_hdr, text="10", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=ACCENT)
        self._widgets["speed_val"].pack(side="right")

        self._widgets["speed_slider"] = ctk.CTkSlider(
            t_inner,
            from_=1,
            to=20,
            number_of_steps=19,
            command=lambda v: (
                self._vars["pointer_speed"].set(int(round(v))),
                self._widgets["speed_val"].configure(text=str(int(round(v)))),
                mouse_features.set_pointer_speed(int(round(v))),
            ),
            fg_color=SWITCH_TRACK_OFF,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            height=16,
        )
        self._widgets["speed_slider"].pack(fill="x", pady=(2, 12))

        # Scroll Lines
        sc_hdr = ctk.CTkFrame(t_inner, fg_color=CARD)
        sc_hdr.pack(fill="x")
        ctk.CTkLabel(sc_hdr, text=self._t("wheel_scroll"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED).pack(side="left")
        self._widgets["scroll_val"] = ctk.CTkLabel(sc_hdr, text="3", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=ACCENT)
        self._widgets["scroll_val"].pack(side="right")

        self._widgets["scroll_slider"] = ctk.CTkSlider(
            t_inner,
            from_=1,
            to=20,
            number_of_steps=19,
            command=lambda v: (
                self._vars["scroll_lines"].set(int(round(v))),
                self._widgets["scroll_val"].configure(text=str(int(round(v)))),
                mouse_features.set_wheel_scroll_lines(int(round(v))),
            ),
            fg_color=SWITCH_TRACK_OFF,
            progress_color=ACCENT,
            button_color=ACCENT,
            button_hover_color=ACCENT_HOVER,
            height=16,
        )
        self._widgets["scroll_slider"].pack(fill="x", pady=(2, 14))

        accel_row = ctk.CTkFrame(t_inner, fg_color=CARD)
        accel_row.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(
            accel_row,
            text=self._t("mouse_accel"),
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=FG,
        ).pack(side="left")

        accel_info = ctk.CTkLabel(
            accel_row,
            text="ⓘ",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=FG_MUTED,
            cursor="hand2",
        )
        accel_info.pack(side="left", padx=(6, 0))
        DelayedTooltip(accel_info, self._t("accel_tip"), delay_ms=250)

        ctk.CTkButton(
            accel_row,
            text=self._t("add_game"),
            width=74,
            height=26,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            corner_radius=7,
            command=self._add_custom_game,
        ).pack(side="right", padx=(6, 0))

        accel_pairs = [
            ("Off", self._t("accel_off")),
            ("Auto", self._t("accel_auto")),
            ("On", self._t("accel_on")),
        ]
        self._accel_to_lbl = {k: lbl for k, lbl in accel_pairs}
        self._lbl_to_accel = {lbl: k for k, lbl in accel_pairs}
        saved_accel_mode = str(monitor.load_config().get("accel_mode", ""))
        if saved_accel_mode not in self._accel_to_lbl:
            saved_accel_mode = "On" if mouse_features.get_enhance_pointer_precision() else "Off"
        self._widgets["accel_seg"] = ctk.CTkSegmentedButton(
            accel_row,
            values=[lbl for _, lbl in accel_pairs],
            command=self._on_accel_mode_change,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=26,
            width=168,
        )
        self._widgets["accel_seg"].set(self._accel_to_lbl[saved_accel_mode])
        self._widgets["accel_seg"].pack(side="right")

        ctk.CTkSwitch(
            t_inner,
            text=self._t("swap_buttons"),
            variable=self._vars["swap_buttons"],
            command=self._on_toggle_swap_buttons,
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=FG,
            switch_width=40,
            switch_height=20,
            fg_color=SWITCH_TRACK_OFF,
            progress_color=ACCENT,
            button_color=SWITCH_BUTTON,
            button_hover_color=SWITCH_BUTTON_HOVER,
        ).pack(anchor="w")

        # Card 3: DPI Speeds & Polling Rate (G HUB Style)
        dpi_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        self._widgets["dpi_card"] = dpi_card
        dpi_card.pack(fill="x", pady=(0, 12))
        d_inner = ctk.CTkFrame(dpi_card, fg_color=CARD)
        d_inner.pack(fill="x", padx=16, pady=12)

        dpi_hdr = ctk.CTkFrame(d_inner, fg_color=CARD)
        dpi_hdr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            dpi_hdr,
            text=self._t("dpi_card_title"),
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            text_color=FG,
        ).pack(side="left")

        self._widgets["live_dpi_lbl"] = ctk.CTkLabel(
            dpi_hdr,
            text=self._t("hidpp_live"),
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            text_color=ACCENT,
        )
        self._widgets["live_dpi_lbl"].pack(side="left", padx=(10, 0))

        ctk.CTkButton(
            dpi_hdr,
            text=self._t("open_ghub"),
            width=108,
            height=26,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            command=self._on_open_lghub,
        ).pack(side="right")

        cfg = monitor.load_config()
        active_dpi = int(cfg.get("active_dpi", 2400))
        self._vars["active_dpi"] = tk.IntVar(value=active_dpi)
        self._dpi_buttons = {}
        self._dpi_underlines = {}

        dpi_row = ctk.CTkFrame(d_inner, fg_color=CARD)
        dpi_row.pack(fill="x", pady=(0, 10))
        for idx, (dpi_val, color) in enumerate(self._dpi_stages()):
            dpi_row.grid_columnconfigure(idx, weight=1, uniform="dpi")
            col = ctk.CTkFrame(dpi_row, fg_color=CARD, width=1)
            col.grid(row=0, column=idx, sticky="ew", padx=(0 if idx == 0 else 5, 0))

            is_active = (dpi_val == active_dpi)
            btn = ctk.CTkButton(
                col,
                text=str(dpi_val),
                width=40,
                command=lambda v=dpi_val: self._select_dpi(v),
                fg_color=CARD_ALT,
                hover_color=BORDER,
                text_color=color,
                border_width=1 if is_active else 0,
                border_color=color,
                font=ctk.CTkFont("Segoe UI", 11, "bold"),
                height=30,
                corner_radius=7,
            )
            btn.pack(fill="x")

            # G HUB style accent underline indicator beneath the active DPI stop
            underline = ctk.CTkFrame(
                col,
                height=3,
                width=1,
                corner_radius=2,
                fg_color=ACCENT if is_active else CARD,
            )
            underline.pack(fill="x", padx=6, pady=(3, 0))

            self._dpi_buttons[dpi_val] = btn
            self._dpi_underlines[dpi_val] = underline

        mode_row = ctk.CTkFrame(d_inner, fg_color=CARD)
        mode_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            mode_row, text=self._t("mouse_mode"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        mode_info = ctk.CTkLabel(
            mode_row,
            text="ⓘ",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=FG_MUTED,
            cursor="hand2",
        )
        mode_info.pack(side="left", padx=(6, 0))
        DelayedTooltip(mode_info, self._t("mouse_mode_tip"), delay_ms=250)

        mode_pairs = [
            ("Onboard", self._t("mode_onboard")),
            ("Host", self._t("mode_host")),
        ]
        self._mode_to_lbl = {k: lbl for k, lbl in mode_pairs}
        self._lbl_to_mode = {lbl: k for k, lbl in mode_pairs}
        saved_mouse_mode = str(cfg.get("mouse_mode", "Onboard"))
        if saved_mouse_mode not in self._mode_to_lbl:
            saved_mouse_mode = "Onboard"
        self._widgets["mouse_mode_seg"] = ctk.CTkSegmentedButton(
            mode_row,
            values=[lbl for _, lbl in mode_pairs],
            command=self._on_mouse_mode_change,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=26,
            width=196,
        )
        self._widgets["mouse_mode_seg"].set(self._mode_to_lbl[saved_mouse_mode])
        self._widgets["mouse_mode_seg"].pack(side="right")

        profile_row = ctk.CTkFrame(d_inner, fg_color=CARD)
        profile_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            profile_row, text=self._t("onboard_profile"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        profile_info = ctk.CTkLabel(
            profile_row,
            text="ⓘ",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=FG_MUTED,
            cursor="hand2",
        )
        profile_info.pack(side="left", padx=(6, 0))
        DelayedTooltip(profile_info, self._t("onboard_profile_tip"), delay_ms=250)

        try:
            saved_slot = int(cfg.get("onboard_slot", 1))
        except (TypeError, ValueError):
            saved_slot = 1
        saved_slot = max(1, min(5, saved_slot))
        slot_vals = [self._t("slot_fmt", n=n) for n in range(1, 6)]
        self._widgets["profile_seg"] = ctk.CTkSegmentedButton(
            profile_row,
            values=slot_vals,
            command=self._on_profile_slot_change,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=26,
            width=292,
        )
        self._widgets["profile_seg"].set(self._t("slot_fmt", n=saved_slot))
        self._widgets["profile_seg"].pack(side="right")

        rate_row = ctk.CTkFrame(d_inner, fg_color=CARD)
        rate_row.pack(fill="x")
        ctk.CTkLabel(
            rate_row, text=self._t("report_rate"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        rate_info = ctk.CTkLabel(
            rate_row,
            text="ⓘ",
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=FG_MUTED,
            cursor="hand2",
        )
        rate_info.pack(side="left", padx=(6, 0))
        DelayedTooltip(rate_info, self._t("report_rate_tip"), delay_ms=250)

        saved_rate = str(cfg.get("report_rate", "1000 Hz"))
        if saved_rate not in REPORT_RATES:
            saved_rate = "1000 Hz"
        self._widgets["rate_seg"] = ctk.CTkSegmentedButton(
            rate_row,
            values=REPORT_RATES,
            command=self._select_report_rate,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=28,
            width=292,
        )
        self._widgets["rate_seg"].set(saved_rate)
        self._widgets["rate_seg"].pack(side="right")

        # LIGHTSYNC RGB Controls (HID++ 2.0 feature 0x8071)
        ctk.CTkFrame(d_inner, height=1, fg_color=BORDER).pack(fill="x", pady=(10, 8))

        rgb_row = ctk.CTkFrame(d_inner, fg_color=CARD)
        rgb_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(
            rgb_row, text=self._t("lightsync_rgb"), font=ctk.CTkFont("Segoe UI", 11), text_color=FG_MUTED
        ).pack(side="left")

        rgb_pairs = [
            ("Off (Eco)", self._t("rgb_off")),
            ("Fixed", self._t("rgb_fixed")),
            ("Breathing", self._t("rgb_breathing")),
            ("Cycle", self._t("rgb_cycle")),
        ]
        self._rgb_to_lbl = {k: lbl for k, lbl in rgb_pairs}
        self._lbl_to_rgb = {lbl: k for k, lbl in rgb_pairs}
        saved_rgb_mode = str(cfg.get("rgb_mode", "Cycle"))
        if saved_rgb_mode not in self._rgb_to_lbl:
            saved_rgb_mode = "Cycle"
        self._widgets["rgb_seg"] = ctk.CTkSegmentedButton(
            rgb_row,
            values=[lbl for _, lbl in rgb_pairs],
            command=self._select_rgb_mode,
            font=ctk.CTkFont("Segoe UI", 10, "bold"),
            fg_color=CARD_ALT,
            selected_color=SEG_SELECTED,
            selected_hover_color=SEG_SELECTED_HOVER,
            unselected_color=CARD_ALT,
            unselected_hover_color=BORDER,
            text_color=FG,
            height=26,
            width=292,
        )
        self._widgets["rgb_seg"].set(self._rgb_to_lbl[saved_rgb_mode])
        self._widgets["rgb_seg"].pack(side="right")

        swatch_row = ctk.CTkFrame(d_inner, fg_color=CARD)
        swatch_row.pack(fill="x")
        ctk.CTkLabel(
            swatch_row, text=self._t("color_lbl"), font=ctk.CTkFont("Segoe UI", 10), text_color=FG_MUTED
        ).pack(side="left")
        sw_box = ctk.CTkFrame(swatch_row, fg_color=CARD)
        sw_box.pack(side="right")
        for cname, hex_c, rgb_tuple in RGB_SWATCHES:
            ctk.CTkButton(
                sw_box,
                text="",
                width=22,
                height=18,
                corner_radius=9,
                fg_color=hex_c,
                hover_color=hex_c,
                border_width=1,
                border_color=BORDER,
                command=lambda n=cname, rgb=rgb_tuple: self._select_rgb_color(n, rgb),
            ).pack(side="left", padx=(6, 0))

        # Alternate info card when a non-Logitech mouse is selected
        dpi_unavail_card = ctk.CTkFrame(
            parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14
        )
        self._widgets["dpi_unavail_card"] = dpi_unavail_card
        u_inner = ctk.CTkFrame(dpi_unavail_card, fg_color=CARD)
        u_inner.pack(fill="x", padx=16, pady=12)
        ctk.CTkLabel(
            u_inner,
            text=self._t("dpi_card_title"),
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            text_color=FG,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(
            u_inner,
            text=self._t("hidpp_unavail_msg"),
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=FG_MUTED,
            justify="left",
            anchor="w",
            wraplength=510,
        ).pack(fill="x")
        self._sync_mouse_control_visibility()

    def _is_hidpp_selected(self) -> bool:
        """Return True if the selected mouse (or default) is a Logitech HID++ / G HUB device."""
        if not self.latest_result:
            return True
        return self.latest_result.get("source") in ("lghub", "hidpp")

    def _sync_mouse_control_visibility(self) -> None:
        """Show Logitech HID++ card only when a Logitech device is active; otherwise show info notice."""
        dpi_card = self._widgets.get("dpi_card")
        unavail = self._widgets.get("dpi_unavail_card")
        if not dpi_card or not unavail:
            return
        if self._is_hidpp_selected():
            unavail.pack_forget()
            if dpi_card.winfo_manager() != "pack":
                dpi_card.pack(fill="x", pady=(0, 12))
        else:
            dpi_card.pack_forget()
            if unavail.winfo_manager() != "pack":
                unavail.pack(fill="x", pady=(0, 12))

    def _sync_mouse_mode_locked(self) -> None:
        """One-time startup sync of saved mouse_mode (default Onboard) to 0x8100 hardware. Must hold _hidpp_lock."""
        if self._hidpp_fw_version is None:
            fw = self.hidpp.get_firmware_version()
            if fw:
                self._hidpp_fw_version = fw
        if self._hidpp_mode_synced:
            return
        want_onboard = str(self.cfg.get("mouse_mode", "Onboard")) != "Host"
        cur_mode = self.hidpp.get_onboard_mode()
        if cur_mode is not None:
            want_val = 1 if want_onboard else 2
            if cur_mode != want_val:
                if self.hidpp.set_onboard_mode(onboard=want_onboard):
                    cur_mode = want_val
            self._hidpp_hw_mode = cur_mode
            self._hidpp_mode_synced = True

    def _on_profile_slot_change(self, slot_label: str) -> None:
        log.info("UI_CLICK: set_onboard_profile -> %s", slot_label)
        try:
            slot = int(slot_label.split()[-1])
        except (ValueError, IndexError):
            return
        cfg = monitor.load_config()
        cfg["onboard_slot"] = slot
        if str(cfg.get("mouse_mode", "Onboard")) != "Onboard":
            cfg["mouse_mode"] = "Onboard"
            if "mouse_mode_seg" in self._widgets:
                self._widgets["mouse_mode_seg"].set(self._mode_to_lbl.get("Onboard", "Onboard"))
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg

        def _worker() -> None:
            with self._hidpp_lock:
                if self._hidpp_hw_mode != 1:
                    if self.hidpp.set_onboard_mode(onboard=True):
                        self._hidpp_hw_mode = 1
                        self._hidpp_mode_synced = True
                ok = self.hidpp.set_onboard_profile(slot)
                actual = self.hidpp.get_onboard_profile()
            verified = (actual == slot) if actual is not None else False
            self._record_telemetry(
                "set_onboard_profile", requested=slot, api_ok=ok, actual=actual, verified=verified
            )
            log.info("UI_RESULT: set_onboard_profile(%d) -> ok=%s actual=%s", slot, ok, actual)
            if ok:
                self.root.after(0, self._flash_status, self._t("slot_active", slot=slot), GREEN)
                self._poll_hidpp_once()
            else:
                self.root.after(0, self._flash_status, self._t("slot_busy", slot=slot), AMBER)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_mouse_mode_change(self, mode_lbl: str) -> None:
        mode_str = getattr(self, "_lbl_to_mode", {}).get(mode_lbl, mode_lbl)
        log.info("UI_CLICK: set_mouse_mode -> %s", mode_str)
        cfg = monitor.load_config()
        cfg["mouse_mode"] = mode_str
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        want_onboard = (mode_str == "Onboard")
        want_val = 1 if want_onboard else 2

        def _worker() -> None:
            with self._hidpp_lock:
                ok = self.hidpp.set_onboard_mode(onboard=want_onboard)
                actual_val = self.hidpp.get_onboard_mode()
                if ok:
                    self._hidpp_hw_mode = want_val
                    self._hidpp_mode_synced = True
            verified = (actual_val == want_val) if actual_val is not None else False
            actual_str = "Onboard" if actual_val == 1 else ("Host" if actual_val == 2 else actual_val)
            self._record_telemetry(
                "set_mouse_mode", requested=mode_str, api_ok=ok, actual=actual_str, verified=verified
            )
            log.info("UI_RESULT: set_mouse_mode(%s) -> ok=%s actual=%s", mode_str, ok, actual_str)
            if ok:
                msg = self._t("mode_set_onboard") if want_onboard else self._t("mode_set_host")
                self.root.after(0, self._flash_status, msg, GREEN)
                self._poll_hidpp_once()
            else:
                self.root.after(0, self._flash_status, self._t("mode_busy", mode=mode_lbl), AMBER)

        threading.Thread(target=_worker, daemon=True).start()

    def _select_rgb_mode(self, mode_lbl: str) -> None:
        mode_key = getattr(self, "_lbl_to_rgb", {}).get(mode_lbl, mode_lbl)
        log.info("UI_CLICK: set_rgb_mode -> %s", mode_key)
        cfg = monitor.load_config()
        cfg["rgb_mode"] = mode_key
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        r, g, b = cfg.get("rgb_color", [56, 189, 248])
        api_mode = "Off" if mode_key.startswith("Off") else mode_key
        allow_host = str(cfg.get("mouse_mode", "Onboard")) == "Host"

        def _worker() -> None:
            with self._hidpp_lock:
                ok = self.hidpp.set_rgb_mode(api_mode, int(r), int(g), int(b), allow_host_switch=allow_host)
            self._record_telemetry("set_rgb_mode", requested=mode_key, api_ok=ok, actual=None, verified=None)
            log.info("UI_RESULT: set_rgb_mode(%s) -> ok=%s", mode_key, ok)
            msg = self._t("rgb_set_ok", mode=mode_lbl) if ok else self._t("rgb_set_busy", mode=mode_lbl)
            self.root.after(0, self._flash_status, msg, GREEN if ok else AMBER)

        threading.Thread(target=_worker, daemon=True).start()

    def _select_rgb_color(self, color_name: str, rgb: tuple[int, int, int]) -> None:
        log.info("UI_CLICK: set_rgb_color -> %s %s", color_name, rgb)
        cfg = monitor.load_config()
        cfg["rgb_color"] = list(rgb)
        mode_key = str(cfg.get("rgb_mode", "Fixed"))
        if mode_key.startswith("Off") or mode_key == "Cycle":
            mode_key = "Fixed"
            cfg["rgb_mode"] = mode_key
            if "rgb_seg" in self._widgets:
                self._widgets["rgb_seg"].set(self._rgb_to_lbl.get(mode_key, mode_key))
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        allow_host = str(cfg.get("mouse_mode", "Onboard")) == "Host"
        mode_lbl = self._rgb_to_lbl.get(mode_key, mode_key)

        def _worker() -> None:
            with self._hidpp_lock:
                ok = self.hidpp.set_rgb_mode(mode_key, rgb[0], rgb[1], rgb[2], allow_host_switch=allow_host)
            self._record_telemetry(
                "set_rgb_color", requested={"color": color_name, "mode": mode_key}, api_ok=ok, actual=None, verified=None
            )
            log.info("UI_RESULT: set_rgb_color(%s, %s) -> ok=%s", color_name, mode_key, ok)
            msg = (
                self._t("rgb_color_ok", color=color_name, mode=mode_lbl)
                if ok
                else self._t("rgb_color_busy", color=color_name)
            )
            self.root.after(0, self._flash_status, msg, GREEN if ok else AMBER)

        threading.Thread(target=_worker, daemon=True).start()

    def _update_dpi_ui(
        self,
        dpi_val: int | None,
        rate_hz: int | None,
        from_poll: bool = False,
        onboard_slot: int | None = None,
    ) -> None:
        if dpi_val is not None:
            if from_poll and self._last_polled_dpi is not None and dpi_val != self._last_polled_dpi:
                self._flash_status(self._t("dpi_mouse_changed", dpi=dpi_val), ACCENT)
            self._last_polled_dpi = dpi_val

            if "active_dpi" in self._vars:
                self._vars["active_dpi"].set(dpi_val)
            for val, color in self._dpi_stages():
                is_active = (val == dpi_val)
                btn = self._dpi_buttons.get(val)
                ul = self._dpi_underlines.get(val)
                if btn:
                    btn.configure(border_width=1 if is_active else 0, border_color=color)
                if ul:
                    ul.configure(fg_color=ACCENT if is_active else CARD)

        if rate_hz is not None and "rate_seg" in self._widgets:
            rate_str = f"{rate_hz} Hz"
            if rate_str in REPORT_RATES:
                prev_rate = self.cfg.get("report_rate")
                self._widgets["rate_seg"].set(rate_str)
                self.cfg["report_rate"] = rate_str
                if prev_rate != rate_str:
                    self.poll_wakeup.set()

        if onboard_slot is not None and 1 <= onboard_slot <= 5 and "profile_seg" in self._widgets:
            self._widgets["profile_seg"].set(self._t("slot_fmt", n=onboard_slot))

        if "live_dpi_lbl" in self._widgets:
            parts = []
            if dpi_val is not None:
                parts.append(f"{dpi_val} DPI")
            if rate_hz is not None:
                parts.append(f"{rate_hz} Hz")
            if parts:
                self._widgets["live_dpi_lbl"].configure(text="• " + "  /  ".join(parts))

    def _poll_hidpp_once(self) -> None:
        if not self._is_hidpp_selected():
            return

        def _worker() -> None:
            with self._hidpp_lock:
                self._sync_mouse_mode_locked()
                dpi = self.hidpp.get_dpi()
                hz = self.hidpp.get_report_rate_hz()
                slot = self.hidpp.get_onboard_profile()
            if dpi is not None or hz is not None or slot is not None:
                self.root.after(0, self._update_dpi_ui, dpi, hz, True, slot)

        threading.Thread(target=_worker, daemon=True).start()

    def _hidpp_live_loop(self) -> None:
        try:
            with self._hidpp_lock:
                self._sync_mouse_mode_locked()
        except Exception:
            pass

        tick = 0
        last_seen_dpi: int | None = None
        while not self.stop_event.is_set():
            visible_mouse = False
            try:
                if (
                    self.win
                    and self.win.winfo_exists()
                    and self.win.state() != "withdrawn"
                    and self._active_page == "Mouse Control"
                    and self._is_hidpp_selected()
                ):
                    visible_mouse = True
                    with self._hidpp_lock:
                        self._sync_mouse_mode_locked()
                        dpi = self.hidpp.get_dpi()
                        hz = self.hidpp.get_report_rate_hz() if (tick % 10 == 0) else None
                    if (dpi is not None and dpi != last_seen_dpi) or hz is not None:
                        self.root.after(0, self._update_dpi_ui, dpi, hz, True)
                    if dpi is not None:
                        last_seen_dpi = dpi
                    tick += 1
                else:
                    tick = 0
            except Exception:
                pass
            self.stop_event.wait(timeout=0.15 if visible_mouse else 1.0)

    def _select_dpi(self, dpi_val: int) -> None:
        log.info("UI_CLICK: set_dpi -> %d", dpi_val)
        self._update_dpi_ui(dpi_val, None, from_poll=False)
        cfg = monitor.load_config()
        cfg["active_dpi"] = dpi_val
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        stage_vals = [v for v, _ in DPI_STAGES]
        stage_idx = stage_vals.index(dpi_val) if dpi_val in stage_vals else None

        def _worker() -> None:
            with self._hidpp_lock:
                ok = self.hidpp.set_dpi(dpi_val, stage_index=stage_idx)
                actual = self.hidpp.get_dpi()
            verified = (actual == dpi_val) if actual is not None else False
            self._record_telemetry("set_dpi", requested=dpi_val, api_ok=ok, actual=actual, verified=verified)
            log.info("UI_RESULT: set_dpi(%d, stage=%s) -> ok=%s actual=%s", dpi_val, stage_idx, ok, actual)
            msg = self._t("dpi_set_ok", dpi=dpi_val) if ok else self._t("dpi_set_busy", dpi=dpi_val)
            self.root.after(0, self._flash_status, msg, GREEN if ok else AMBER)

        threading.Thread(target=_worker, daemon=True).start()

    def _select_report_rate(self, rate_str: str) -> None:
        log.info("UI_CLICK: set_report_rate -> %s", rate_str)
        if str(self.cfg.get("mouse_mode", "Onboard")) != "Host":
            self._record_telemetry(
                "set_report_rate", requested=rate_str, api_ok=False, actual=self.cfg.get("mouse_mode"), verified=False
            )
            self._flash_status(self._t("rate_need_host"), AMBER)
            self._poll_hidpp_once()
            return
        cfg = monitor.load_config()
        cfg["report_rate"] = rate_str
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        hz = int(rate_str.split()[0])

        def _worker() -> None:
            with self._hidpp_lock:
                ok = self.hidpp.set_report_rate_hz(hz, allow_host_switch=True)
                actual = self.hidpp.get_report_rate_hz()
            verified = (actual == hz) if actual is not None else False
            self._record_telemetry("set_report_rate", requested=hz, api_ok=ok, actual=actual, verified=verified)
            log.info("UI_RESULT: set_report_rate(%s) -> ok=%s actual=%s", rate_str, ok, actual)
            if ok:
                self.poll_wakeup.set()
            msg = self._t("rate_set_ok", rate=rate_str) if ok else self._t("rate_set_busy", rate=rate_str)
            self.root.after(0, self._flash_status, msg, GREEN if ok else AMBER)

        threading.Thread(target=_worker, daemon=True).start()

    # ==================== PAGE 4: SYNC & BACKUP ====================
    def _build_sync_page(self, parent: ctk.CTkFrame) -> None:
        # Card 1: Local Preferences
        local_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        local_card.pack(fill="x", pady=(0, 14))
        lc = ctk.CTkFrame(local_card, fg_color=CARD)
        lc.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(
            lc, text=self._t("local_prefs"), font=ctk.CTkFont("Segoe UI", 13, "bold"), text_color=FG
        ).pack(anchor="w")
        ctk.CTkLabel(
            lc,
            text=self._t("local_prefs_desc"),
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=FG_MUTED,
        ).pack(anchor="w", pady=(2, 12))

        l_row = ctk.CTkFrame(lc, fg_color=CARD)
        l_row.pack(fill="x")
        ctk.CTkButton(
            l_row,
            text=self._t("export_prefs"),
            command=self._export_prefs,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=10,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            l_row,
            text=self._t("import_prefs"),
            command=self._import_prefs,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=10,
        ).pack(side="right", fill="x", expand=True, padx=(6, 0))

        # Card 2: Google SSO Cloud Sync
        cloud_card = ctk.CTkFrame(parent, fg_color=CARD, border_color=BORDER, border_width=1, corner_radius=14)
        cloud_card.pack(fill="x", pady=(0, 14))
        cc = ctk.CTkFrame(cloud_card, fg_color=CARD)
        cc.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(
            cc, text=self._t("cloud_sync"), font=ctk.CTkFont("Segoe UI", 13, "bold"), text_color=FG
        ).pack(anchor="w")
        ctk.CTkLabel(
            cc,
            text=self._t("cloud_sync_desc"),
            font=ctk.CTkFont("Segoe UI", 10),
            text_color=FG_MUTED,
        ).pack(anchor="w", pady=(2, 10))

        self._widgets["cloud_status"] = ctk.CTkButton(
            cc,
            text="",
            command=self._show_google_setup_guide,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            text_color=FG_MUTED,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            corner_radius=8,
            height=34,
        )
        self._widgets["cloud_status"].pack(fill="x", pady=(0, 12))

        auth_row = ctk.CTkFrame(cc, fg_color=CARD)
        auth_row.pack(fill="x", pady=(0, 10))
        self._widgets["google_auth_btn"] = ctk.CTkButton(
            auth_row,
            text=self._t("sign_in_google"),
            command=self._on_google_auth,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color=ACCENT_TEXT,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=10,
        )
        self._widgets["google_auth_btn"].pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            auth_row,
            text=self._t("add_google_key"),
            command=self._load_client_secret,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=10,
        ).pack(side="right", fill="x", expand=True, padx=(6, 0))

        sync_row = ctk.CTkFrame(cc, fg_color=CARD)
        sync_row.pack(fill="x")
        ctk.CTkButton(
            sync_row,
            text=self._t("backup_drive"),
            command=self._on_cloud_upload,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=10,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(
            sync_row,
            text=self._t("restore_drive"),
            command=self._on_cloud_download,
            fg_color=CARD_ALT,
            hover_color=BORDER,
            text_color=FG,
            font=ctk.CTkFont("Segoe UI", 11, "bold"),
            height=36,
            corner_radius=10,
        ).pack(side="right", fill="x", expand=True, padx=(6, 0))

        self._refresh_cloud_ui()

    def _refresh_cloud_ui(self) -> None:
        if "cloud_status" not in self._widgets:
            return
        if self.cloud.is_signed_in():
            email = self.cloud.get_user_email() or "Google Account"
            self._widgets["cloud_status"].configure(
                text=self._t("cloud_connected", email=email), text_color=GREEN, state="disabled"
            )
            self._widgets["google_auth_btn"].configure(text=self._t("sign_out"), fg_color=CARD_ALT, text_color=FG)
        else:
            has_creds = self.cloud.has_client_secret()
            if has_creds:
                self._widgets["cloud_status"].configure(
                    text=self._t("cloud_ready"), text_color=ACCENT, state="disabled"
                )
            else:
                self._widgets["cloud_status"].configure(
                    text=self._t("cloud_setup_prompt"),
                    text_color=AMBER,
                    state="normal",
                )
            self._widgets["google_auth_btn"].configure(
                text=self._t("sign_in_google"), fg_color=ACCENT, text_color=ACCENT_TEXT
            )

    def _show_google_setup_guide(self) -> None:
        if theme.ask_yes_no(
            self._dialog_parent(),
            self._t("connect_drive_title"),
            self._t("google_guide_msg"),
            self._resolved_theme,
            icon_path=self._icon_path(),
            yes_text=self._t("connect"),
            no_text=self._t("cancel"),
        ):
            import webbrowser
            webbrowser.open("https://console.cloud.google.com/apis/credentials")

    def _export_prefs(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.win,
            title=self._t("export_title"),
            defaultextension=".json",
            initialfile="mouse_battery_preferences.json",
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        cfg = monitor.load_config()
        Path(path).write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self._flash_status(self._t("prefs_exported"), GREEN)

    def _import_prefs(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title=self._t("import_title"),
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            cfg = monitor.load_config()
            cfg.update(data)
            monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            self.cfg = cfg
            self._flash_status(self._t("prefs_imported"), GREEN)
        except Exception as exc:
            self._flash_status(self._t("import_failed", err=exc), RED)

    def _load_client_secret(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title=self._t("select_secret_title"),
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            content = Path(path).read_text(encoding="utf-8")
            json.loads(content)
            self.cloud.client_secret_path.write_text(content, encoding="utf-8")
            self._refresh_cloud_ui()
            self._flash_status(self._t("creds_loaded"), GREEN)
        except Exception as exc:
            self._flash_status(self._t("invalid_json", err=exc), RED)

    def _on_google_auth(self) -> None:
        if self.cloud.is_signed_in():
            self.cloud.sign_out()
            self._refresh_cloud_ui()
            self._flash_status(self._t("signed_out"), FG_MUTED)
            return
        self._flash_status(self._t("opening_signin"), ACCENT)

        def _worker() -> None:
            ok, msg = self.cloud.sign_in()
            self.root.after(0, lambda: (self._refresh_cloud_ui(), self._flash_status(msg, GREEN if ok else AMBER)))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_cloud_upload(self) -> None:
        self._flash_status(self._t("uploading_drive"), ACCENT)

        def _worker() -> None:
            ok, msg = self.cloud.upload_config(monitor.load_config())
            self.root.after(0, lambda: self._flash_status(msg, GREEN if ok else AMBER))

        threading.Thread(target=_worker, daemon=True).start()

    def _on_cloud_download(self) -> None:
        self._flash_status(self._t("restoring_drive"), ACCENT)

        def _worker() -> None:
            ok, res = self.cloud.download_config()
            if ok and isinstance(res, dict):
                cfg = monitor.load_config()
                cfg.update(res)
                monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                self.cfg = cfg
                self.root.after(0, lambda: self._flash_status(self._t("restored_drive"), GREEN))
            else:
                self.root.after(0, lambda: self._flash_status(str(res), AMBER))

        threading.Thread(target=_worker, daemon=True).start()

    def _load_mouse_values(self) -> None:
        if "speed_slider" not in self._widgets:
            return
        sp = mouse_features.get_pointer_speed()
        sc = mouse_features.get_wheel_scroll_lines()
        self._vars["pointer_speed"].set(sp)
        self._vars["scroll_lines"].set(sc)
        self._vars["enhance_precision"].set(mouse_features.get_enhance_pointer_precision())
        self._vars["swap_buttons"].set(mouse_features.get_swap_buttons())
        self._widgets["speed_slider"].set(sp)
        self._widgets["speed_val"].configure(text=str(sp))
        self._widgets["scroll_slider"].set(sc)
        self._widgets["scroll_val"].configure(text=str(sc))
        self._sync_mouse_control_visibility()

    def _on_toggle_swap_buttons(self) -> None:
        want = bool(self._vars["swap_buttons"].get())
        mouse_features.set_swap_buttons(want)
        actual = mouse_features.get_swap_buttons()
        self._record_telemetry("swap_buttons", requested=want, api_ok=True, actual=actual, verified=(actual == want))
        self._flash_status(self._t("buttons_updated"), GREEN)

    def _on_accel_mode_change(self, mode_lbl: str) -> None:
        mode = getattr(self, "_lbl_to_accel", {}).get(mode_lbl, mode_lbl)
        cfg = monitor.load_config()
        cfg["accel_mode"] = mode
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        if mode == "Off":
            want_accel = False
            mouse_features.set_enhance_pointer_precision(False)
            self._flash_status(self._t("accel_set_off"), GREEN)
        elif mode == "On":
            want_accel = True
            mouse_features.set_enhance_pointer_precision(True)
            self._flash_status(self._t("accel_set_on"), GREEN)
        else:
            # Auto: enable for desktop immediately, watcher turns OFF when game focused
            exe = mouse_features.get_foreground_exe_path()
            in_game = mouse_features.is_game_process(exe, cfg.get("auto_games", []))
            want_accel = not in_game
            mouse_features.set_enhance_pointer_precision(want_accel)
            self._flash_status(self._t("accel_set_auto"), GREEN)
        actual_accel = mouse_features.get_enhance_pointer_precision()
        self._record_telemetry(
            "set_accel_mode",
            requested={"mode": mode, "accel": want_accel},
            api_ok=True,
            actual=actual_accel,
            verified=(actual_accel == want_accel),
        )

    def _add_custom_game(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.win,
            title=self._t("select_game_title"),
            filetypes=[("Executables", "*.exe")],
        )
        if not path:
            return
        exe_name = Path(path).name
        cfg = monitor.load_config()
        games: list[str] = list(cfg.get("auto_games", []))
        if exe_name not in games:
            games.append(exe_name)
            cfg["auto_games"] = games
            monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            self.cfg = cfg
        self._flash_status(self._t("added_game", exe=exe_name), GREEN)

    def _game_watch_loop(self) -> None:
        last_applied: bool | None = None
        while not self.stop_event.is_set():
            try:
                if mouse_features.get_idle_seconds() < 60.0:
                    with self._active_lock:
                        self._active_seconds_accum += 2.0
                if self.cfg.get("accel_mode") == "Auto":
                    exe = mouse_features.get_foreground_exe_path()
                    in_game = mouse_features.is_game_process(exe, self.cfg.get("auto_games", []))
                    desired_accel = not in_game
                    if desired_accel != last_applied:
                        mouse_features.set_enhance_pointer_precision(desired_accel)
                        last_applied = desired_accel
                else:
                    last_applied = None
            except Exception:
                pass
            self.stop_event.wait(timeout=2.0)

    def _apply_preset(self, name: str) -> None:
        p = MOUSE_PRESETS[name]
        self._vars["pointer_speed"].set(p["speed"])
        self._vars["scroll_lines"].set(p["scroll"])
        self._vars["enhance_precision"].set(p["accel"])
        self._widgets["speed_slider"].set(p["speed"])
        self._widgets["speed_val"].configure(text=str(p["speed"]))
        self._widgets["scroll_slider"].set(p["scroll"])
        self._widgets["scroll_val"].configure(text=str(p["scroll"]))
        mode = "On" if p["accel"] else "Off"
        if "accel_seg" in self._widgets:
            self._widgets["accel_seg"].set(self._accel_to_lbl.get(mode, mode))
        cfg = monitor.load_config()
        cfg["accel_mode"] = mode
        monitor.CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg
        self._apply_mouse_settings(preset_name=name)

    def _apply_mouse_settings(self, preset_name: str | None = None) -> None:
        req = {
            "speed": int(self._vars["pointer_speed"].get()),
            "accel": bool(self._vars["enhance_precision"].get()),
            "scroll": int(self._vars["scroll_lines"].get()),
            "swap": bool(self._vars["swap_buttons"].get()),
        }
        mouse_features.set_pointer_speed(req["speed"])
        mouse_features.set_enhance_pointer_precision(req["accel"])
        mouse_features.set_wheel_scroll_lines(req["scroll"])
        mouse_features.set_swap_buttons(req["swap"])
        actual = {
            "speed": mouse_features.get_pointer_speed(),
            "accel": mouse_features.get_enhance_pointer_precision(),
            "scroll": mouse_features.get_wheel_scroll_lines(),
            "swap": mouse_features.get_swap_buttons(),
        }
        self._record_telemetry(
            f"apply_preset:{preset_name}" if preset_name else "apply_mouse_settings",
            requested=req,
            api_ok=True,
            actual=actual,
            verified=(actual == req),
        )
        preset_key_map = {
            "Gaming": "preset_gaming",
            "Precision": "preset_precision",
            "Productivity": "preset_productivity",
        }
        if preset_name:
            loc_name = self._t(preset_key_map[preset_name]) if preset_name in preset_key_map else preset_name
            msg = self._t("preset_applied", name=loc_name)
        else:
            msg = self._t("mouse_applied")
        self._flash_status(msg, GREEN)

    def run(self, show_on_start: bool = False) -> None:
        def _setup(icon: pystray.Icon) -> None:
            icon.visible = True

        threading.Thread(target=self.icon.run, kwargs={"setup": _setup}, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        threading.Thread(target=self._hidpp_live_loop, daemon=True).start()
        threading.Thread(target=self._game_watch_loop, daemon=True).start()
        if show_on_start:
            self.root.after(0, self.show_window)
        self.root.after(2500, self._check_updates_silent_if_due)
        self.root.mainloop()


if __name__ == "__main__":
    app = MouseBatteryTrayApp()
    app.run(show_on_start=("--tray-only" not in sys.argv))
