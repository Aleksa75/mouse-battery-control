"""
Shared UI theme registry, Windows titlebar theming, and styled modal dialogs
for Mouse Battery & Control.
"""

from __future__ import annotations

import colorsys
import ctypes
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]

import customtkinter as ctk
import darkdetect

# Centralized Theme Registry (Dark / Light)
THEMES: dict[str, dict[str, str]] = {
    "Dark": {
        "BG": "#0F1117",
        "CARD": "#171A23",
        "CARD_ALT": "#1F2430",
        "BORDER": "#2A3040",
        "FG": "#F3F4F6",
        "FG_MUTED": "#94A3B8",
        "ACCENT": "#38BDF8",
        "ACCENT_HOVER": "#0EA5E9",
        "ACCENT_TEXT": "#0B1120",
        "GREEN": "#22C55E",
        "AMBER": "#F59E0B",
        "RED": "#F87171",
        "CHART_FILL": "#162A3A",
        "GRID_MAJOR": "#2A3040",
        "GRID_MINOR": "#1D222D",
        "PLAYHEAD": "#E2E8F0",
        "TIP_BG": "#171A23",
        "SEG_SELECTED": "#0369A1",
        "SEG_SELECTED_HOVER": "#075985",
        "SWITCH_BUTTON": "#F8FAFC",
        "SWITCH_BUTTON_HOVER": "#FFFFFF",
        "SWITCH_TRACK_OFF": "#475569",
    },
    "Light": {
        "BG": "#F0F4F9",
        "CARD": "#FFFFFF",
        "CARD_ALT": "#E9EEF6",
        "BORDER": "#DCE3EE",
        "FG": "#1F1F1F",
        "FG_MUTED": "#444746",
        "ACCENT": "#0B57D0",
        "ACCENT_HOVER": "#0842A0",
        "ACCENT_TEXT": "#FFFFFF",
        "GREEN": "#146C2E",
        "AMBER": "#9A5400",
        "RED": "#B3261E",
        "CHART_FILL": "#D3E3FD",
        "GRID_MAJOR": "#D8E0EC",
        "GRID_MINOR": "#E9EEF6",
        "PLAYHEAD": "#444746",
        "TIP_BG": "#FFFFFF",
        "SEG_SELECTED": "#D3E3FD",
        "SEG_SELECTED_HOVER": "#C2D7FA",
        "SWITCH_BUTTON": "#FFFFFF",
        "SWITCH_BUTTON_HOVER": "#F0F4F9",
        "SWITCH_TRACK_OFF": "#747775",
    },
    "Matrix": {
        "BG": "#040A06",
        "CARD": "#08140C",
        "CARD_ALT": "#0F2416",
        "BORDER": "#1B4328",
        "FG": "#DCFCE7",
        "FG_MUTED": "#6EE7B7",
        "ACCENT": "#22C55E",
        "ACCENT_HOVER": "#16A34A",
        "ACCENT_TEXT": "#041208",
        "GREEN": "#4ADE80",
        "AMBER": "#FACC15",
        "RED": "#F87171",
        "CHART_FILL": "#0D2B17",
        "GRID_MAJOR": "#1B4328",
        "GRID_MINOR": "#0E2114",
        "PLAYHEAD": "#86EFAC",
        "TIP_BG": "#08140C",
        "SEG_SELECTED": "#166534",
        "SEG_SELECTED_HOVER": "#14532D",
        "SWITCH_BUTTON": "#DCFCE7",
        "SWITCH_BUTTON_HOVER": "#FFFFFF",
        "SWITCH_TRACK_OFF": "#2D6A42",
    },
}


_ACTIVE_ACCENT_MODE: str = "Windows"


def set_accent_mode(mode: str) -> str:
    """Set module-level active accent mode ('Windows' or 'Default') for palettes and dialogs."""
    global _ACTIVE_ACCENT_MODE
    _ACTIVE_ACCENT_MODE = "Default" if str(mode) == "Default" else "Windows"
    return _ACTIVE_ACCENT_MODE


def get_accent_mode() -> str:
    """Return active accent mode ('Windows' or 'Default')."""
    return _ACTIVE_ACCENT_MODE


def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    h = hex_color.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if len(h) != 6:
        return (0.22, 0.74, 0.97)
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def _rgb01_to_hex(r: float, g: float, b: float) -> str:
    ri = max(0, min(255, int(round(r * 255))))
    gi = max(0, min(255, int(round(g * 255))))
    bi = max(0, min(255, int(round(b * 255))))
    return f"#{ri:02X}{gi:02X}{bi:02X}"


def _relative_luminance(hex_color: str) -> float:
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = _hex_to_rgb01(hex_color)
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(hex1: str, hex2: str) -> float:
    """Compute WCAG 2.1 contrast ratio between two hex colors (1.0 to 21.0)."""
    l1 = _relative_luminance(hex1)
    l2 = _relative_luminance(hex2)
    hi, lo = (l1, l2) if l1 >= l2 else (l2, l1)
    return (hi + 0.05) / (lo + 0.05)


def _blend_hex(fg_hex: str, bg_hex: str, alpha: float) -> str:
    a = max(0.0, min(1.0, float(alpha)))
    fr, fg, fb = _hex_to_rgb01(fg_hex)
    br, bg, bb = _hex_to_rgb01(bg_hex)
    return _rgb01_to_hex(fr * a + br * (1.0 - a), fg * a + bg * (1.0 - a), fb * a + bb * (1.0 - a))


def _hls_hex(h: float, l_val: float, s_val: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l_val)), max(0.0, min(1.0, s_val)))
    return _rgb01_to_hex(r, g, b)


def get_windows_accent_hex() -> str | None:
    """Read the user's Windows 10/11 accent color from DWM or Explorer Accent registry keys."""
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            for value_name, is_abgr in (("AccentColor", True), ("ColorizationColor", False)):
                try:
                    raw_val, _ = winreg.QueryValueEx(key, value_name)
                except OSError:
                    continue
                if isinstance(raw_val, int):
                    u32 = raw_val & 0xFFFFFFFF
                    if is_abgr:
                        r = u32 & 0xFF
                        g = (u32 >> 8) & 0xFF
                        b = (u32 >> 16) & 0xFF
                    else:
                        r = (u32 >> 16) & 0xFF
                        g = (u32 >> 8) & 0xFF
                        b = u32 & 0xFF
                    return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:
        pass

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent"
        ) as key:
            try:
                palette_blob, _ = winreg.QueryValueEx(key, "AccentPalette")
                if isinstance(palette_blob, (bytes, bytearray)) and len(palette_blob) >= 16:
                    # Windows AccentPalette stores 8 RGBA swatches; index 3 (bytes 12..14) is the primary accent.
                    r, g, b = palette_blob[12], palette_blob[13], palette_blob[14]
                    return f"#{r:02X}{g:02X}{b:02X}"
            except OSError:
                pass
            try:
                raw_val, _ = winreg.QueryValueEx(key, "AccentColorMenu")
                if isinstance(raw_val, int):
                    u32 = raw_val & 0xFFFFFFFF
                    return f"#{u32 & 0xFF:02X}{(u32 >> 8) & 0xFF:02X}{(u32 >> 16) & 0xFF:02X}"
            except OSError:
                pass
    except Exception:
        return None
    return None


def derive_accent_tokens(base_hex: str, resolved_theme: str) -> dict[str, str]:
    """Derive WCAG 2.1 AA-compliant accent UI tokens from an arbitrary #RRGGBB color."""
    if resolved_theme not in ("Dark", "Light"):
        return {}

    base = THEMES[resolved_theme]
    card = base["CARD"]
    card_alt = base["CARD_ALT"]
    fg = base["FG"]

    r, g, b = _hex_to_rgb01(base_hex)
    h, l_orig, s = colorsys.rgb_to_hls(r, g, b)
    s_acc = min(0.90, s) if s > 0.06 else 0.0

    def _pick_lightness(
        lo_i: int,
        hi_i: int,
        target_l: float,
        sat: float,
        predicate: Any,
        fallback_score: Any,
    ) -> tuple[float, str]:
        cands = [(i / 100.0, _hls_hex(h, i / 100.0, sat)) for i in range(lo_i, hi_i + 1)]
        valid = [item for item in cands if predicate(item[1])]
        if valid:
            return min(valid, key=lambda item: (abs(item[0] - target_l), -fallback_score(item[1])))
        return max(cands, key=lambda item: fallback_score(item[1]))

    if resolved_theme == "Dark":
        acc_target = max(0.58, min(0.72, l_orig))
        acc_l, acc = _pick_lightness(
            40,
            92,
            acc_target,
            s_acc,
            lambda c: (
                contrast_ratio(c, card) >= 4.5
                and contrast_ratio(c, card_alt) >= 4.5
                and max(contrast_ratio(c, "#0B1120"), contrast_ratio(c, "#FFFFFF")) >= 4.5
            ),
            lambda c: min(
                contrast_ratio(c, card_alt),
                max(contrast_ratio(c, "#0B1120"), contrast_ratio(c, "#FFFFFF")),
            ),
        )
        acc_text = "#0B1120" if contrast_ratio(acc, "#0B1120") >= contrast_ratio(acc, "#FFFFFF") else "#FFFFFF"

        _, acc_hover = _pick_lightness(
            35,
            95,
            acc_l - 0.07,
            s_acc,
            lambda c: (
                contrast_ratio(c, card) >= 4.5
                and contrast_ratio(c, card_alt) >= 4.5
                and contrast_ratio(c, acc_text) >= 4.5
            ),
            lambda c: min(contrast_ratio(c, card_alt), contrast_ratio(c, acc_text)),
        )

        s_seg = min(0.85, s) if s > 0.06 else 0.0
        seg_l, seg_sel = _pick_lightness(
            16,
            44,
            0.30,
            s_seg,
            lambda c: contrast_ratio(fg, c) >= 4.5,
            lambda c: contrast_ratio(fg, c),
        )
        _, seg_hover = _pick_lightness(
            12,
            max(12, min(44, int(round((seg_l - 0.03) * 100)))),
            max(0.12, seg_l - 0.05),
            s_seg,
            lambda c: contrast_ratio(fg, c) >= 4.5,
            lambda c: contrast_ratio(fg, c),
        )
        chart_fill = _blend_hex(acc, card, 0.18)
    else:
        s_acc_light = min(0.88, max(s, 0.62)) if s > 0.08 else 0.0
        acc_target = max(0.46, min(0.54, l_orig))
        acc_l, acc = _pick_lightness(
            24,
            62,
            acc_target,
            s_acc_light,
            lambda c: (
                contrast_ratio(c, "#FFFFFF") >= 4.5
                and contrast_ratio(c, card) >= 4.5
            ),
            lambda c: min(contrast_ratio(c, "#FFFFFF"), contrast_ratio(c, card)),
        )
        acc_text = "#FFFFFF"

        _, acc_hover = _pick_lightness(
            20,
            max(20, min(58, int(round((acc_l - 0.03) * 100)))),
            max(0.20, acc_l - 0.06),
            s_acc_light,
            lambda c: contrast_ratio(c, "#FFFFFF") >= 4.5 and contrast_ratio(c, card) >= 4.5,
            lambda c: min(contrast_ratio(c, "#FFFFFF"), contrast_ratio(c, card)),
        )

        s_seg = min(0.85, max(s, 0.50)) if s > 0.08 else 0.0
        seg_l, seg_sel = _pick_lightness(
            80,
            92,
            0.86,
            s_seg,
            lambda c: contrast_ratio(fg, c) >= 7.0,
            lambda c: contrast_ratio(fg, c),
        )
        _, seg_hover = _pick_lightness(
            74,
            max(74, min(88, int(round((seg_l - 0.04) * 100)))),
            max(0.74, seg_l - 0.06),
            s_seg,
            lambda c: contrast_ratio(fg, c) >= 5.5,
            lambda c: contrast_ratio(fg, c),
        )
        chart_fill = _blend_hex(acc, card, 0.16)

    return {
        "ACCENT": acc,
        "ACCENT_HOVER": acc_hover,
        "ACCENT_TEXT": acc_text,
        "SEG_SELECTED": seg_sel,
        "SEG_SELECTED_HOVER": seg_hover,
        "CHART_FILL": chart_fill,
    }


def resolve_theme(mode: str) -> str:
    """Resolve 'System' | 'Dark' | 'Light' into 'Dark' or 'Light'."""
    resolved = mode
    if mode == "System":
        try:
            resolved = "Dark" if darkdetect.isDark() else "Light"
        except Exception:
            resolved = "Dark"
    return resolved if resolved in THEMES else "Dark"


def get_palette(resolved: str, accent_mode: str | None = None) -> dict[str, str]:
    """Return color tokens dictionary for the resolved theme, optionally tinted with Windows accent."""
    pal = dict(THEMES.get(resolved, THEMES["Dark"]))
    effective_mode = accent_mode if accent_mode is not None else _ACTIVE_ACCENT_MODE
    if effective_mode == "Windows" and resolved in ("Dark", "Light"):
        win_hex = get_windows_accent_hex()
        if win_hex:
            pal.update(derive_accent_tokens(win_hex, resolved))
    return pal


def apply_win_titlebar_theme(win: Any, resolved_theme: str) -> None:
    """Update Windows 11 title bar dark/light mode in-place and force immediate frame repaint."""
    try:
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(1 if resolved_theme != "Light" else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))
        # SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
        # RDW_INVALIDATE | RDW_UPDATENOW | RDW_FRAME
        ctypes.windll.user32.RedrawWindow(hwnd, None, None, 0x0001 | 0x0100 | 0x0400)
    except Exception:
        pass


class StyledDialog(ctk.CTkToplevel):
    """Themed modal dialog matching the main application's slate palette and card layout."""

    def __init__(
        self,
        parent: Any,
        title: str,
        resolved_theme: str,
        width: int = 430,
        height: int | None = None,
        icon_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._parent_win = parent
        self._resolved_theme = resolve_theme(resolved_theme)
        self.palette = get_palette(self._resolved_theme)
        self._target_width = width
        self._target_height = height

        self.title(title)
        self.configure(fg_color=self.palette["BG"])
        self.resizable(False, False)
        apply_win_titlebar_theme(self, self._resolved_theme)
        self.after(50, lambda: apply_win_titlebar_theme(self, self._resolved_theme) if self.winfo_exists() else None)

        if icon_path and Path(icon_path).exists():
            try:
                self.after(150, lambda p=str(icon_path): self.iconbitmap(p) if self.winfo_exists() else None)
            except Exception:
                pass

        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

        if parent is not None and parent.winfo_exists():
            try:
                if parent.state() != "withdrawn":
                    self.transient(parent)
            except Exception:
                pass

        try:
            self.grab_set()
        except Exception:
            pass

    def _close(self) -> None:
        try:
            self.grab_release()
        except Exception:
            pass
        if self.winfo_exists():
            self.destroy()

    def center_on_parent(self) -> None:
        """Size and center the dialog over its parent window (or screen if parent is hidden)."""
        self.update_idletasks()
        w = self._target_width or max(380, self.winfo_reqwidth())
        h = self._target_height or max(180, self.winfo_reqheight())

        parent = self._parent_win
        use_parent = False
        if parent is not None and parent.winfo_exists():
            try:
                if parent.state() != "withdrawn" and parent.winfo_width() > 20:
                    use_parent = True
            except Exception:
                pass

        if use_parent:
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2
        else:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2

        x = max(20, min(x, self.winfo_screenwidth() - w - 20))
        y = max(20, min(y, self.winfo_screenheight() - h - 40))
        self.geometry(f"{w}x{h}+{x}+{y}")
        apply_win_titlebar_theme(self, self._resolved_theme)
        self.lift()
        self.focus_force()


def _build_message_body(
    dlg: StyledDialog,
    title: str,
    message: str,
    accent_color: str,
    subtitle: str | None = None,
) -> ctk.CTkFrame:
    p = dlg.palette
    outer = ctk.CTkFrame(dlg, fg_color=p["BG"])
    outer.pack(fill="both", expand=True, padx=20, pady=18)

    hdr = ctk.CTkFrame(outer, fg_color=p["BG"])
    hdr.pack(fill="x", pady=(0, 12))

    ctk.CTkFrame(hdr, width=4, height=22, corner_radius=2, fg_color=accent_color).pack(
        side="left", padx=(0, 10)
    )
    title_col = ctk.CTkFrame(hdr, fg_color=p["BG"])
    title_col.pack(side="left", fill="x", expand=True)
    ctk.CTkLabel(
        title_col,
        text=title,
        font=ctk.CTkFont("Segoe UI", 15, "bold"),
        text_color=p["FG"],
        anchor="w",
    ).pack(anchor="w")
    if subtitle:
        ctk.CTkLabel(
            title_col,
            text=subtitle,
            font=ctk.CTkFont("Segoe UI", 11),
            text_color=p["FG_MUTED"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

    card = ctk.CTkFrame(
        outer,
        fg_color=p["CARD"],
        border_color=p["BORDER"],
        border_width=1,
        corner_radius=12,
    )
    card.pack(fill="both", expand=True, pady=(0, 14))
    ctk.CTkLabel(
        card,
        text=message,
        font=ctk.CTkFont("Segoe UI", 12),
        text_color=p["FG"],
        justify="left",
        anchor="w",
        wraplength=365,
    ).pack(fill="both", expand=True, padx=16, pady=14)

    btn_row = ctk.CTkFrame(outer, fg_color=p["BG"])
    btn_row.pack(fill="x")
    return btn_row


def show_info(
    parent: Any,
    title: str,
    message: str,
    resolved_theme: str,
    icon_path: Path | None = None,
    subtitle: str | None = None,
) -> None:
    """Display a themed informational modal dialog."""
    dlg = StyledDialog(parent, title, resolved_theme, width=430, icon_path=icon_path)
    p = dlg.palette
    btn_row = _build_message_body(dlg, title, message, p["ACCENT"], subtitle=subtitle)
    ok_btn = ctk.CTkButton(
        btn_row,
        text="OK",
        width=100,
        height=34,
        corner_radius=8,
        fg_color=p["ACCENT"],
        hover_color=p["ACCENT_HOVER"],
        text_color=p["ACCENT_TEXT"],
        font=ctk.CTkFont("Segoe UI", 12, "bold"),
        command=dlg._close,
    )
    ok_btn.pack(side="right")
    dlg.bind("<Return>", lambda _e: dlg._close())
    dlg.center_on_parent()
    dlg.wait_window()


def show_error(
    parent: Any,
    title: str,
    message: str,
    resolved_theme: str,
    icon_path: Path | None = None,
) -> None:
    """Display a themed error modal dialog."""
    dlg = StyledDialog(parent, title, resolved_theme, width=430, icon_path=icon_path)
    p = dlg.palette
    btn_row = _build_message_body(dlg, title, message, p["RED"])
    ok_btn = ctk.CTkButton(
        btn_row,
        text="Close",
        width=100,
        height=34,
        corner_radius=8,
        fg_color=p["RED"],
        hover_color=p["BORDER"],
        text_color="#FFFFFF",
        font=ctk.CTkFont("Segoe UI", 12, "bold"),
        command=dlg._close,
    )
    ok_btn.pack(side="right")
    dlg.bind("<Return>", lambda _e: dlg._close())
    dlg.center_on_parent()
    dlg.wait_window()


def ask_yes_no(
    parent: Any,
    title: str,
    message: str,
    resolved_theme: str,
    icon_path: Path | None = None,
    yes_text: str = "Yes",
    no_text: str = "Cancel",
) -> bool:
    """Display a themed Yes/No confirmation dialog and return True if confirmed."""
    result = {"val": False}
    dlg = StyledDialog(parent, title, resolved_theme, width=440, icon_path=icon_path)
    p = dlg.palette
    btn_row = _build_message_body(dlg, title, message, p["ACCENT"])

    def _on_yes() -> None:
        result["val"] = True
        dlg._close()

    yes_btn = ctk.CTkButton(
        btn_row,
        text=yes_text,
        width=116,
        height=34,
        corner_radius=8,
        fg_color=p["ACCENT"],
        hover_color=p["ACCENT_HOVER"],
        text_color=p["ACCENT_TEXT"],
        font=ctk.CTkFont("Segoe UI", 12, "bold"),
        command=_on_yes,
    )
    yes_btn.pack(side="right", padx=(8, 0))

    no_btn = ctk.CTkButton(
        btn_row,
        text=no_text,
        width=96,
        height=34,
        corner_radius=8,
        fg_color=p["CARD_ALT"],
        hover_color=p["BORDER"],
        text_color=p["FG"],
        font=ctk.CTkFont("Segoe UI", 12, "bold"),
        command=dlg._close,
    )
    no_btn.pack(side="right")

    dlg.bind("<Return>", lambda _e: _on_yes())
    dlg.center_on_parent()
    dlg.wait_window()
    return bool(result["val"])
