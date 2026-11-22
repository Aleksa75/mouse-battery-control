"""
Lightweight Self-Updater for Mouse Battery & Control
Supports:
  1. GitHub Releases:  update_source = "github:owner/repo"
  2. Local folder:     update_source = "C:\\path\\to\\releases"  (containing latest.json + .zip / .exe)
  3. Direct JSON URL:  update_source = "https://example.com/latest.json"

latest.json format (for local folder or HTTP URL):
  {
    "version": "2.26.0",
    "package_url": "MouseBatteryControl.zip",
    "package_sha256": "<sha256>",
    "exe_url": "MouseBatteryControl.exe",
    "sha256": "<sha256>",
    "notes": "Bug fixes and improvements"
  }
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


def parse_version(v: str) -> tuple[int, ...]:
    cleaned = v.strip().lstrip("vV")
    parts: list[int] = []
    for token in cleaned.split("."):
        num = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(remote_version: str, current_version: str) -> bool:
    return parse_version(remote_version) > parse_version(current_version)


def check_for_update(current_version: str, update_source: str | None) -> dict[str, Any]:
    """
    Check update_source for a newer version.
    Returns dict:
      { "status": "up_to_date" | "update_available" | "not_configured" | "error",
        "latest_version": str, "download_url": str, "notes": str, "message": str }
    """
    if not update_source or not update_source.strip():
        return {
            "status": "not_configured",
            "message": "No update source configured in config.json (set 'update_source' to a GitHub repo or local folder).",
        }

    src = update_source.strip()
    try:
        package_type = "exe"
        if src.lower().startswith("github:"):
            repo = src.split(":", 1)[1].strip("/")
            api_url = f"https://api.github.com/repos/{repo}/releases/latest"
            req = urllib.request.Request(api_url, headers={"User-Agent": "MouseBatteryControl-Updater"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = str(data.get("tag_name", "")).lstrip("vV")
            notes = str(data.get("body", "")).strip()[:200]
            expected_sha256 = ""
            download_url = ""
            exe_fallback_url = ""
            for asset in data.get("assets", []):
                asset_name = str(asset.get("name", "")).lower()
                asset_url = str(asset.get("browser_download_url", ""))
                if asset_name.endswith(".zip") and not download_url:
                    download_url = asset_url
                    package_type = "zip"
                    break
                if asset_name.endswith(".exe") and not exe_fallback_url:
                    exe_fallback_url = asset_url
            if not download_url:
                download_url = exe_fallback_url
                package_type = "exe"
        elif src.lower().startswith(("http://", "https://")):
            req = urllib.request.Request(src, headers={"User-Agent": "MouseBatteryControl-Updater"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            latest = str(data.get("version", ""))
            notes = str(data.get("notes", ""))
            pkg_url = str(data.get("package_url", "")).strip()
            if pkg_url:
                download_url = pkg_url
                expected_sha256 = str(data.get("package_sha256") or data.get("sha256") or "").strip().lower()
                package_type = "zip"
            else:
                download_url = str(data.get("exe_url", ""))
                expected_sha256 = str(data.get("sha256", "")).strip().lower()
                package_type = "exe"
        else:
            # Local folder containing latest.json
            folder = Path(src)
            manifest = folder / "latest.json" if folder.is_dir() else folder
            data = json.loads(manifest.read_text(encoding="utf-8"))
            latest = str(data.get("version", ""))
            notes = str(data.get("notes", ""))
            pkg_url = str(data.get("package_url", "")).strip()
            if pkg_url:
                expected_sha256 = str(data.get("package_sha256") or data.get("sha256") or "").strip().lower()
                pkg_path = Path(pkg_url)
                if not pkg_path.is_absolute():
                    pkg_path = manifest.parent / pkg_path
                download_url = str(pkg_path)
                package_type = "zip"
            else:
                expected_sha256 = str(data.get("sha256", "")).strip().lower()
                raw_exe = str(data.get("exe_url", "MouseBatteryControl.exe"))
                exe_path = Path(raw_exe)
                if not exe_path.is_absolute():
                    exe_path = manifest.parent / exe_path
                download_url = str(exe_path)
                package_type = "exe"

        if not latest:
            return {"status": "error", "message": "Invalid release metadata (missing version)."}

        if is_newer(latest, current_version):
            return {
                "status": "update_available",
                "latest_version": latest,
                "download_url": download_url,
                "sha256": expected_sha256,
                "package_type": package_type,
                "notes": notes,
                "message": f"Version {latest} is available (you have {current_version}).",
            }
        return {
            "status": "up_to_date",
            "latest_version": latest,
            "message": f"You're up to date (v{current_version}).",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Update check failed: {exc}"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _fetch_update_file(download_url: str, dest_path: Path) -> tuple[bool, str]:
    """Download an HTTP/HTTPS release file or copy a local release file to dest_path."""
    if download_url.lower().startswith(("http://", "https://")):
        req = urllib.request.Request(download_url, headers={"User-Agent": "MouseBatteryControl-Updater"})
        with urllib.request.urlopen(req, timeout=30) as resp, dest_path.open("wb") as out:
            shutil.copyfileobj(resp, out)
        return True, ""

    src_path = Path(download_url)
    if not src_path.exists():
        return False, f"Update file not found: {src_path}"
    shutil.copy2(src_path, dest_path)
    return True, ""


def _extract_and_validate_zip(
    zip_path: Path,
    stage_dir: Path,
    exe_name: str = "MouseBatteryControl.exe",
) -> tuple[Path, Path]:
    """Safely extract a --onedir release .zip and return (staged_exe, staged_internal)."""
    stage_root = stage_dir.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if not members:
            raise ValueError("Update archive is empty.")
        for info in members:
            raw = info.filename
            norm = raw.replace("\\", "/")
            if (
                norm.startswith("/")
                or (len(norm) >= 2 and norm[1] == ":")
                or any(part == ".." for part in norm.split("/"))
            ):
                raise ValueError(f"Unsafe path in update archive: {raw}")
            dest = (stage_root / norm).resolve()
            try:
                dest.relative_to(stage_root)
            except ValueError as exc:
                raise ValueError(f"Path escapes staging directory: {raw}") from exc

        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(stage_dir)

    direct_exe = stage_dir / exe_name
    direct_internal = stage_dir / "_internal"
    if direct_exe.is_file() and direct_internal.is_dir():
        return direct_exe, direct_internal

    top_entries = list(stage_dir.iterdir())
    if len(top_entries) == 1 and top_entries[0].is_dir():
        sub_exe = top_entries[0] / exe_name
        sub_internal = top_entries[0] / "_internal"
        if sub_exe.is_file() and sub_internal.is_dir():
            return sub_exe, sub_internal

    raise ValueError(f"Update archive must contain {exe_name} and _internal/.")


def _spawn_update_batch(helper_bat: Path, app_dir: Path) -> None:
    """Spawn helper_bat with PyInstaller bootloader env variables stripped."""
    env = dict(os.environ)
    for key in (
        "_MEIPASS2",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_ARCHIVE_FILE",
        "_PYI_PARENT_PROCESS_LEVEL",
        "TCL_LIBRARY",
        "TK_LIBRARY",
    ):
        env.pop(key, None)

    meipass = getattr(sys, "_MEIPASS", None)
    meipass_norm = os.path.normcase(str(meipass)) if meipass else None
    for pkey in ("PATH", "Path"):
        if pkey in env:
            clean_parts = []
            for part in env[pkey].split(os.pathsep):
                norm = os.path.normcase(part)
                if meipass_norm and meipass_norm in norm:
                    continue
                if "\\_mei" in norm or "/_mei" in norm:
                    continue
                clean_parts.append(part)
            env[pkey] = os.pathsep.join(clean_parts)

    creationflags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )
    subprocess.Popen(
        ["cmd.exe", "/c", str(helper_bat)],
        cwd=str(app_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
        env=env,
    )


def download_and_apply_update(
    download_url: str,
    expected_sha256: str = "",
    package_type: str | None = None,
) -> tuple[bool, str]:
    """
    Download/copy the new release (.zip for --onedir or .exe for --onefile) and spawn
    a helper batch script that verifies integrity, waits for exit, swaps files atomically
    with rollback protection, clears PyInstaller env vars, relaunches, and self-deletes.
    """
    if not getattr(sys, "frozen", False):
        return False, "Self-update only applies when running the compiled MouseBatteryControl.exe."

    if not download_url:
        return False, "No update package URL found in the release."

    current_exe = Path(sys.executable).resolve()
    app_dir = current_exe.parent
    helper_bat = current_exe.with_name("_apply_update.bat")
    is_zip = (package_type == "zip") or (package_type is None and download_url.lower().endswith(".zip"))
    pid = os.getpid()

    try:
        if not is_zip:
            staged_exe = current_exe.with_name(current_exe.stem + "_update.exe")
            ok, err = _fetch_update_file(download_url, staged_exe)
            if not ok:
                return False, err

            if expected_sha256:
                actual_sha256 = _sha256_file(staged_exe)
                if actual_sha256 != expected_sha256.lower():
                    try:
                        staged_exe.unlink()
                    except OSError:
                        pass
                    return False, "Update file failed SHA-256 integrity check (possibly incomplete build)."

            bat_content = (
                "@echo off\r\n"
                ":wait\r\n"
                f"tasklist /FI \"PID eq {pid}\" 2>NUL | find /I \"{pid}\" >NUL\r\n"
                "if not errorlevel 1 (\r\n"
                "  ping -n 2 127.0.0.1 >NUL\r\n"
                "  goto wait\r\n"
                ")\r\n"
                "ping -n 2 127.0.0.1 >NUL\r\n"
                "set /a _tries=0\r\n"
                ":retry_move\r\n"
                f"move /Y \"{staged_exe}\" \"{current_exe}\" >NUL 2>&1\r\n"
                "if not errorlevel 1 goto launch\r\n"
                "set /a _tries+=1\r\n"
                "if %_tries% GEQ 15 goto launch\r\n"
                "ping -n 2 127.0.0.1 >NUL\r\n"
                "goto retry_move\r\n"
                ":launch\r\n"
                "set \"_MEIPASS2=\"\r\n"
                "set \"_PYI_APPLICATION_HOME_DIR=\"\r\n"
                "set \"_PYI_ARCHIVE_FILE=\"\r\n"
                "set \"_PYI_PARENT_PROCESS_LEVEL=\"\r\n"
                "set \"TCL_LIBRARY=\"\r\n"
                "set \"TK_LIBRARY=\"\r\n"
                f"start \"\" \"{current_exe}\"\r\n"
                "(goto) 2>nul & del \"%~f0\"\r\n"
            )
            helper_bat.write_text(bat_content, encoding="utf-8")
            _spawn_update_batch(helper_bat, app_dir)
            return True, "Update downloaded — restarting app..."

        staged_zip = app_dir / "_update_pkg.zip"
        stage_dir = app_dir / "_update_stage"
        ok, err = _fetch_update_file(download_url, staged_zip)
        if not ok:
            return False, err

        if expected_sha256:
            actual_sha256 = _sha256_file(staged_zip)
            if actual_sha256 != expected_sha256.lower():
                try:
                    staged_zip.unlink()
                except OSError:
                    pass
                return False, "Update archive failed SHA-256 integrity check (possibly incomplete build)."

        try:
            staged_exe, staged_internal = _extract_and_validate_zip(staged_zip, stage_dir, exe_name=current_exe.name)
        except Exception as exc:
            shutil.rmtree(stage_dir, ignore_errors=True)
            return False, f"Invalid update archive: {exc}"
        finally:
            try:
                staged_zip.unlink()
            except OSError:
                pass

        target_internal = app_dir / "_internal"
        internal_old = app_dir / "_internal_old"
        bat_content = (
            "@echo off\r\n"
            ":wait\r\n"
            f"tasklist /FI \"PID eq {pid}\" 2>NUL | find /I \"{pid}\" >NUL\r\n"
            "if not errorlevel 1 (\r\n"
            "  ping -n 2 127.0.0.1 >NUL\r\n"
            "  goto wait\r\n"
            ")\r\n"
            "ping -n 2 127.0.0.1 >NUL\r\n"
            f"if exist \"{internal_old}\" rmdir /S /Q \"{internal_old}\" >NUL 2>&1\r\n"
            f"if not exist \"{target_internal}\" goto move_new_internal\r\n"
            "set /a _tries=0\r\n"
            ":retry_old_internal\r\n"
            f"move /Y \"{target_internal}\" \"{internal_old}\" >NUL 2>&1\r\n"
            "if not errorlevel 1 goto move_new_internal\r\n"
            "set /a _tries+=1\r\n"
            "if %_tries% GEQ 15 goto cleanup_fail\r\n"
            "ping -n 2 127.0.0.1 >NUL\r\n"
            "goto retry_old_internal\r\n"
            ":move_new_internal\r\n"
            "set /a _tries=0\r\n"
            ":retry_new_internal\r\n"
            f"move /Y \"{staged_internal}\" \"{target_internal}\" >NUL 2>&1\r\n"
            "if not errorlevel 1 goto move_exe\r\n"
            "set /a _tries+=1\r\n"
            "if %_tries% GEQ 15 goto rollback_internal\r\n"
            "ping -n 2 127.0.0.1 >NUL\r\n"
            "goto retry_new_internal\r\n"
            ":move_exe\r\n"
            "set /a _tries=0\r\n"
            ":retry_exe\r\n"
            f"move /Y \"{staged_exe}\" \"{current_exe}\" >NUL 2>&1\r\n"
            "if not errorlevel 1 goto cleanup_ok\r\n"
            "set /a _tries+=1\r\n"
            "if %_tries% GEQ 15 goto rollback_exe\r\n"
            "ping -n 2 127.0.0.1 >NUL\r\n"
            "goto retry_exe\r\n"
            ":rollback_exe\r\n"
            f"if exist \"{target_internal}\" rmdir /S /Q \"{target_internal}\" >NUL 2>&1\r\n"
            ":rollback_internal\r\n"
            f"if exist \"{internal_old}\" if not exist \"{target_internal}\" move /Y \"{internal_old}\" \"{target_internal}\" >NUL 2>&1\r\n"
            ":cleanup_fail\r\n"
            f"if exist \"{stage_dir}\" rmdir /S /Q \"{stage_dir}\" >NUL 2>&1\r\n"
            "goto launch\r\n"
            ":cleanup_ok\r\n"
            f"if exist \"{internal_old}\" rmdir /S /Q \"{internal_old}\" >NUL 2>&1\r\n"
            f"if exist \"{stage_dir}\" rmdir /S /Q \"{stage_dir}\" >NUL 2>&1\r\n"
            ":launch\r\n"
            "set \"_MEIPASS2=\"\r\n"
            "set \"_PYI_APPLICATION_HOME_DIR=\"\r\n"
            "set \"_PYI_ARCHIVE_FILE=\"\r\n"
            "set \"_PYI_PARENT_PROCESS_LEVEL=\"\r\n"
            "set \"TCL_LIBRARY=\"\r\n"
            "set \"TK_LIBRARY=\"\r\n"
            f"start \"\" \"{current_exe}\"\r\n"
            "(goto) 2>nul & del \"%~f0\"\r\n"
        )
        helper_bat.write_text(bat_content, encoding="utf-8")
        _spawn_update_batch(helper_bat, app_dir)
        return True, "Update downloaded — restarting app..."
    except Exception as exc:
        return False, f"Failed to apply update: {exc}"
