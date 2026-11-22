"""
Secret Easter eggs for Mouse Battery & Control:
1. Secret 15s Aim & Reflex Trainer mini-game
2. Konami Code scuttling mouse + cheese + confetti strip animation
3. Harmless Gauge "overclock" helpers (purely cosmetic, real battery % intact)
4. Secret Retro Matrix theme key-sequence / click-burst detectors
"""

from __future__ import annotations

import math
import random
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from typing import Any

import customtkinter as ctk

import theme

KONAMI_SEQ: tuple[str, ...] = ("up", "up", "down", "down", "left", "right", "left", "right", "b", "a")
MATRIX_SEQ: tuple[str, ...] = ("m", "a", "t", "r", "i", "x")


def _normalize_key(keysym: str, keycode: int | None = None) -> str:
    ks = (keysym or "").strip().lower()
    if ks in ("up", "down", "left", "right"):
        return ks
    if len(ks) == 1 and "a" <= ks <= "z":
        return ks
    if keycode is not None and 65 <= int(keycode) <= 90:
        return chr(int(keycode) + 32)
    return ks


class KeySequenceTracker:
    """Tracks recent normalized keypresses to match KONAMI_SEQ or MATRIX_SEQ."""

    def __init__(self, maxlen: int = 12) -> None:
        self._buf: deque[str] = deque(maxlen=maxlen)

    def push(self, keysym: str, keycode: int | None = None) -> str | None:
        key = _normalize_key(keysym, keycode)
        if not key:
            return None
        self._buf.append(key)
        seq = tuple(self._buf)
        if len(seq) >= len(KONAMI_SEQ) and seq[-len(KONAMI_SEQ) :] == KONAMI_SEQ:
            self._buf.clear()
            return "konami"
        if len(seq) >= len(MATRIX_SEQ) and seq[-len(MATRIX_SEQ) :] == MATRIX_SEQ:
            self._buf.clear()
            return "matrix"
        return None


class ClickBurstTracker:
    """Detects rapid multi-clicks within a rolling time window."""

    def __init__(self) -> None:
        self._taps: list[float] = []

    def tap(self, now: float | None = None, required: int = 5, window_s: float = 2.5) -> int:
        ts = time.monotonic() if now is None else float(now)
        self._taps = [t for t in self._taps if (ts - t) <= window_s]
        self._taps.append(ts)
        count = len(self._taps)
        if count >= required:
            self._taps.clear()
        return count


def play_mouse_chase_overlay(win: Any, palette: dict[str, str], on_done: Any = None) -> tk.Canvas | None:
    """Animate a scurrying little mouse chasing a wedge of cheese + confetti across the bottom of `win`."""
    try:
        if not win or not win.winfo_exists():
            return None
    except Exception:
        return None

    ov = tk.Canvas(
        win,
        height=58,
        bg=palette["CARD"],
        highlightthickness=1,
        highlightbackground=palette["ACCENT"],
    )
    ov.place(relx=0.0, rely=1.0, anchor="sw", relwidth=1.0)
    try:
        ov.lift()
    except Exception:
        pass

    rng = random.Random(42)
    confetti_colors = [palette["ACCENT"], palette["GREEN"], palette["AMBER"], "#EC4899", "#A855F7"]
    confetti = [
        {
            "x_frac": rng.uniform(0.05, 0.95),
            "y": rng.uniform(-10, 48),
            "vy": rng.uniform(1.0, 2.4),
            "vx": rng.uniform(-0.8, 0.8),
            "sz": rng.randint(4, 7),
            "color": rng.choice(confetti_colors),
        }
        for _ in range(24)
    ]

    total_frames = 60

    def _draw_frame(frame: int = 0) -> None:
        try:
            if not win.winfo_exists() or not ov.winfo_exists():
                return
        except Exception:
            return

        if frame >= total_frames:
            try:
                ov.destroy()
            except Exception:
                pass
            if on_done:
                on_done()
            return

        ov.delete("all")
        w = max(480, ov.winfo_width() if ov.winfo_width() > 20 else 600)
        prog = frame / float(total_frames - 1)

        # Confetti particles
        for c in confetti:
            cx = (c["x_frac"] * w + c["vx"] * frame * 2) % w
            cy = (c["y"] + c["vy"] * frame * 1.4) % 58
            sz = c["sz"]
            ov.create_rectangle(cx, cy, cx + sz, cy + max(3, sz - 1), fill=c["color"], outline="")

        # Cheese wedge sliding left -> right
        chx = -30 + prog * (w + 90)
        chy = 34 + math.sin(frame * 0.45) * 3
        ov.create_polygon(
            chx - 12, chy + 8,
            chx + 14, chy + 8,
            chx + 10, chy - 7,
            fill="#FACC15",
            outline="#CA8A04",
            width=1.5,
        )
        ov.create_oval(chx + 1, chy + 1, chx + 5, chy + 5, fill="#CA8A04", outline="")
        ov.create_oval(chx - 5, chy + 3, chx - 2, chy + 6, fill="#CA8A04", outline="")

        # Scurrying mouse right behind cheese
        mx = chx - 54
        my = 35 + math.cos(frame * 0.65) * 2
        tail_wave = math.sin(frame * 0.8) * 5
        # Tail
        ov.create_line(
            mx - 14, my + 2,
            mx - 26, my - 3 + tail_wave,
            mx - 36, my + 2 - tail_wave * 0.5,
            smooth=True,
            fill="#F472B6",
            width=2.5,
        )
        # Body & head
        ov.create_oval(mx - 16, my - 8, mx + 12, my + 9, fill=palette["FG_MUTED"], outline=palette["FG"], width=1.2)
        ov.create_oval(mx + 2, my - 13, mx + 10, my - 4, fill=palette["FG_MUTED"], outline=palette["FG"], width=1.2)
        ov.create_oval(mx + 4, my - 11, mx + 8, my - 6, fill="#F472B6", outline="")
        # Eye & pink nose
        ov.create_oval(mx + 7, my - 3, mx + 10, my, fill="#0F172A", outline="")
        ov.create_oval(mx + 11, my + 1, mx + 15, my + 5, fill="#FB7185", outline="")
        # Tiny running feet
        step = math.sin(frame * 0.9) * 4
        ov.create_line(mx - 8 + step, my + 8, mx - 5 + step, my + 13, fill=palette["FG"], width=2)
        ov.create_line(mx + 4 - step, my + 8, mx + 7 - step, my + 13, fill=palette["FG"], width=2)

        win.after(35, _draw_frame, frame + 1)

    _draw_frame(0)
    return ov


def open_aim_trainer(
    parent: Any,
    resolved_theme: str,
    t_fn: Any,
    best_hits: int,
    on_new_best: Any,
    icon_path: Path | None = None,
) -> theme.StyledDialog:
    """Open the secret 15-second Aim & Reflex Trainer mini-game."""
    dlg = theme.StyledDialog(parent, t_fn("ee_aim_title"), resolved_theme, width=480, icon_path=icon_path)
    p = dlg.palette

    outer = ctk.CTkFrame(dlg, fg_color=p["BG"])
    outer.pack(fill="both", expand=True, padx=20, pady=16)

    ctk.CTkLabel(
        outer,
        text=t_fn("ee_aim_title"),
        font=ctk.CTkFont("Segoe UI", 16, "bold"),
        text_color=p["FG"],
        anchor="w",
    ).pack(fill="x")
    ctk.CTkLabel(
        outer,
        text=t_fn("ee_aim_sub"),
        font=ctk.CTkFont("Segoe UI", 11),
        text_color=p["FG_MUTED"],
        anchor="w",
    ).pack(fill="x", pady=(2, 10))

    stats_bar = ctk.CTkFrame(outer, fg_color=p["CARD"], border_color=p["BORDER"], border_width=1, corner_radius=10)
    stats_bar.pack(fill="x", pady=(0, 10))
    stats_inner = ctk.CTkFrame(stats_bar, fg_color=p["CARD"])
    stats_inner.pack(fill="x", padx=12, pady=8)

    timer_lbl = ctk.CTkLabel(stats_inner, text="15.0s", font=ctk.CTkFont("Segoe UI", 13, "bold"), text_color=p["ACCENT"])
    timer_lbl.pack(side="left")

    hits_lbl = ctk.CTkLabel(stats_inner, text=f"{t_fn('ee_aim_hits')}: 0", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=p["FG"])
    hits_lbl.pack(side="left", padx=(18, 0))

    avg_lbl = ctk.CTkLabel(stats_inner, text=f"{t_fn('ee_aim_avg')}: —", font=ctk.CTkFont("Segoe UI", 11), text_color=p["FG_MUTED"])
    avg_lbl.pack(side="left", padx=(18, 0))

    best_state = {"val": int(best_hits)}
    best_lbl = ctk.CTkLabel(
        stats_inner, text=f"{t_fn('ee_aim_best')}: {best_state['val']}", font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=p["GREEN"]
    )
    best_lbl.pack(side="right")

    cw, ch = 436, 250
    arena = tk.Canvas(
        outer,
        width=cw,
        height=ch,
        bg=p["CARD"],
        highlightthickness=1,
        highlightbackground=p["BORDER"],
        cursor="crosshair",
    )
    arena.pack(fill="x", pady=(0, 12))

    game: dict[str, Any] = {
        "active": False,
        "hits": 0,
        "rts": [],
        "end_ts": 0.0,
        "spawn_ts": 0.0,
        "tx": cw / 2.0,
        "ty": ch / 2.0,
        "r": 18.0,
        "after_id": None,
    }

    def _spawn_target() -> None:
        arena.delete("target")
        r = game["r"]
        pad = int(r) + 12
        tx = random.randint(pad, cw - pad)
        ty = random.randint(pad, ch - pad)
        game["tx"] = float(tx)
        game["ty"] = float(ty)
        game["spawn_ts"] = time.perf_counter()
        arena.create_oval(tx - r, ty - r, tx + r, ty + r, fill=p["ACCENT"], outline=p["FG"], width=2, tags="target")
        arena.create_oval(tx - 10, ty - 10, tx + 10, ty + 10, fill=p["CARD"], outline="", tags="target")
        arena.create_oval(tx - 5, ty - 5, tx + 5, ty + 5, fill=p["RED"], outline="", tags="target")

    def _finish_game() -> None:
        game["active"] = False
        game["after_id"] = None
        arena.delete("all")
        hits = game["hits"]
        rts = game["rts"]
        timer_lbl.configure(text="0.0s", text_color=p["AMBER"])
        if hits > 0 and rts:
            avg_ms = int(round(sum(rts) / len(rts)))
            hps = hits / 15.0
            summary = t_fn("ee_aim_done", hits=hits, hps=hps, avg=avg_ms)
        else:
            summary = t_fn("ee_aim_done_zero")
        arena.create_text(cw / 2, ch / 2, text=summary, fill=p["FG"], font=("Segoe UI", 12, "bold"))
        start_btn.configure(text=t_fn("ee_aim_again"), state="normal")
        if hits > best_state["val"]:
            best_state["val"] = hits
            best_lbl.configure(text=f"{t_fn('ee_aim_best')}: {hits}")
            on_new_best(hits)

    def _tick() -> None:
        if not game["active"] or not dlg.winfo_exists():
            return
        rem = game["end_ts"] - time.perf_counter()
        if rem <= 0:
            _finish_game()
            return
        timer_lbl.configure(text=f"{rem:.1f}s")
        game["after_id"] = dlg.after(50, _tick)

    def _on_hit(ev: Any) -> None:
        if not game["active"]:
            return
        if math.hypot(ev.x - game["tx"], ev.y - game["ty"]) <= game["r"] + 4.0:
            rt_ms = (time.perf_counter() - game["spawn_ts"]) * 1000.0
            game["hits"] += 1
            game["rts"].append(rt_ms)
            hx, hy, hr = game["tx"], game["ty"], game["r"] + 5
            ring_id = arena.create_oval(hx - hr, hy - hr, hx + hr, hy + hr, outline=p["GREEN"], width=2)
            dlg.after(110, lambda i=ring_id: arena.delete(i) if arena.winfo_exists() else None)
            hits_lbl.configure(text=f"{t_fn('ee_aim_hits')}: {game['hits']}")
            avg_ms = int(round(sum(game["rts"]) / len(game["rts"])))
            avg_lbl.configure(text=f"{t_fn('ee_aim_avg')}: {avg_ms} ms")
            _spawn_target()

    def _start_game() -> None:
        if game["after_id"] is not None:
            try:
                dlg.after_cancel(game["after_id"])
            except Exception:
                pass
        arena.delete("all")
        game["active"] = True
        game["hits"] = 0
        game["rts"] = []
        game["end_ts"] = time.perf_counter() + 15.0
        timer_lbl.configure(text="15.0s", text_color=p["ACCENT"])
        hits_lbl.configure(text=f"{t_fn('ee_aim_hits')}: 0")
        avg_lbl.configure(text=f"{t_fn('ee_aim_avg')}: —")
        start_btn.configure(state="disabled")
        _spawn_target()
        _tick()

    arena.bind("<Button-1>", _on_hit)

    btn_row = ctk.CTkFrame(outer, fg_color=p["BG"])
    btn_row.pack(fill="x")
    start_btn = ctk.CTkButton(
        btn_row,
        text=t_fn("ee_aim_start"),
        width=130,
        height=34,
        corner_radius=8,
        fg_color=p["ACCENT"],
        hover_color=p["ACCENT_HOVER"],
        text_color=p["ACCENT_TEXT"],
        font=ctk.CTkFont("Segoe UI", 12, "bold"),
        command=_start_game,
    )
    start_btn.pack(side="left")

    orig_close = dlg._close

    def _cleanup_close() -> None:
        game["active"] = False
        if game["after_id"] is not None:
            try:
                dlg.after_cancel(game["after_id"])
            except Exception:
                pass
            game["after_id"] = None
        orig_close()

    dlg._close = _cleanup_close  # type: ignore[method-assign]
    dlg.protocol("WM_DELETE_WINDOW", _cleanup_close)
    dlg.bind("<Escape>", lambda _e: _cleanup_close())

    ctk.CTkButton(
        btn_row,
        text=t_fn("close"),
        width=100,
        height=34,
        corner_radius=8,
        fg_color=p["CARD_ALT"],
        hover_color=p["BORDER"],
        text_color=p["FG"],
        font=ctk.CTkFont("Segoe UI", 12, "bold"),
        command=_cleanup_close,
    ).pack(side="right")

    dlg.center_on_parent()
    dlg.wait_window()
    return dlg
