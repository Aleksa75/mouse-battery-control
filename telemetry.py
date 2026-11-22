"""
Local Action Telemetry & Readback Verification for Mouse Battery & Control.
Records button/control interactions and detects false confirmations (cases where
an API call reported success but reading back the state did not match what was asked).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("MouseBatteryControl.telemetry")


class ActionTelemetry:
    """Thread-safe rotating JSONL action telemetry logger with readback verification."""

    def __init__(self, path: Path, max_bytes: int = 512_000) -> None:
        self.path = Path(path)
        self.max_bytes = max(64_000, int(max_bytes))
        self._lock = threading.Lock()

    def record(
        self,
        action: str,
        requested: Any = None,
        api_ok: bool | None = None,
        actual: Any = None,
        verified: bool | None = None,
        version: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record one user/control action and flag `false_confirmation` if api_ok=True yet verified=False."""
        false_confirmation = bool(api_ok is True and verified is False)
        rec: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "version": version,
            "action": str(action),
            "requested": requested,
            "api_ok": api_ok,
            "actual": actual,
            "verified": verified,
            "false_confirmation": false_confirmation,
        }
        if extra:
            for k, v in extra.items():
                if k not in rec:
                    rec[k] = v

        line = json.dumps(rec, default=str) + "\n"
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                    backup = self.path.with_name(self.path.name + ".1")
                    os.replace(self.path, backup)
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as exc:
                log.warning("Failed writing telemetry record (%s): %s", action, exc)

        if false_confirmation:
            log.warning(
                "FALSE_CONFIRMATION on action=%s: requested=%r api_ok=%s actual=%r",
                action,
                requested,
                api_ok,
                actual,
            )
        return rec

    def read_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent up to `limit` telemetry records safely."""
        with self._lock:
            if not self.path.exists():
                return []
            try:
                lines = self.path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                return []
        out: list[dict[str, Any]] = []
        for raw in lines[-max(1, int(limit)) :]:
            s = raw.strip()
            if not s:
                continue
            try:
                parsed = json.loads(s)
                if isinstance(parsed, dict):
                    out.append(parsed)
            except Exception:
                continue
        return out
