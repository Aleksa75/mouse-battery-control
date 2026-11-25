"""
Local Preferences Export/Import + Google SSO (OAuth 2.0 PKCE) Cloud Sync
Uses Google Drive's private `appDataFolder` scope (drive.appdata) with zero external SDKs.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import http.server
import json
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import monitor

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://www.googleapis.com/oauth2/v3/userinfo"
DRIVE_FILES_URI = "https://www.googleapis.com/drive/v3/files"
DRIVE_UPLOAD_URI = "https://www.googleapis.com/upload/drive/v3/files"

SCOPES = "openid email profile https://www.googleapis.com/auth/drive.appdata"
REMOTE_FILENAME = "mouse_battery_control_config.json"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _dpapi_protect(data: bytes) -> bytes:
    """Encrypt bytes with Windows DPAPI (current-user scope)."""
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI is only supported on Windows.")
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "MouseBatteryControl",
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


def _dpapi_unprotect(cipher: bytes) -> bytes:
    """Decrypt bytes protected by Windows DPAPI (current-user scope)."""
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI is only supported on Windows.")
    buf = ctypes.create_string_buffer(cipher, len(cipher))
    blob_in = _DATA_BLOB(len(cipher), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    blob_out = _DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB),
        ctypes.POINTER(ctypes.wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    if not crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        if blob_out.pbData:
            kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))


class GoogleCloudSync:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.client_secret_path = base_dir / "client_secret.json"
        self.token_path = base_dir / "google_token.json"

    def has_client_secret(self) -> bool:
        return self.client_secret_path.exists()

    def _load_client_config(self) -> tuple[str, str]:
        data = json.loads(self.client_secret_path.read_text(encoding="utf-8"))
        block = data.get("installed") or data.get("web") or data
        return str(block["client_id"]), str(block.get("client_secret", ""))

    def _save_token(self, tok: dict[str, Any]) -> None:
        cipher = _dpapi_protect(json.dumps(tok).encode("utf-8"))
        wrapper = {"dpapi_v1": base64.b64encode(cipher).decode("ascii")}
        monitor.atomic_write_text(self.token_path, json.dumps(wrapper, indent=2))

    def load_token(self) -> dict[str, Any] | None:
        if not self.token_path.exists():
            return None
        try:
            raw = json.loads(self.token_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            if "dpapi_v1" in raw:
                cipher = base64.b64decode(str(raw["dpapi_v1"]).encode("ascii"))
                plain = _dpapi_unprotect(cipher).decode("utf-8")
                parsed = json.loads(plain)
                return parsed if isinstance(parsed, dict) else None
            if raw.get("access_token") or raw.get("refresh_token"):
                # Migrate legacy plaintext token file transparently on load.
                self._save_token(raw)
                return raw
            return None
        except Exception:
            return None

    def is_signed_in(self) -> bool:
        tok = self.load_token()
        return bool(tok and (tok.get("access_token") or tok.get("refresh_token")))

    def get_user_email(self) -> str | None:
        tok = self.load_token()
        return tok.get("email") if tok else None

    def sign_out(self) -> None:
        if self.token_path.exists():
            self.token_path.unlink()

    def sign_in(self) -> tuple[bool, str]:
        """Run Google OAuth 2.0 PKCE loopback flow in the user's browser."""
        if not self.has_client_secret():
            return (
                False,
                "Add your Google key file first to connect your account.",
            )

        try:
            client_id, client_secret = self._load_client_config()
        except Exception as exc:
            return False, f"Invalid client_secret.json: {exc}"

        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        state = secrets.token_urlsafe(24)
        result_box: dict[str, str] = {}
        done_evt = threading.Event()

        class _CallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                if params.get("state", [""])[0] == state and "code" in params:
                    result_box["code"] = params["code"][0]
                    body = b"<html><body style='font-family:Segoe UI;background:#0F1117;color:#F3F4F6;text-align:center;padding:40px;'><h2>Signed in to Mouse Battery &amp; Control!</h2><p>You can close this browser tab.</p></body></html>"
                else:
                    result_box["error"] = params.get("error", ["cancelled"])[0]
                    body = b"<html><body style='font-family:Segoe UI;background:#0F1117;color:#F3F4F6;text-align:center;padding:40px;'><h2>Sign-in cancelled</h2><p>You can close this tab.</p></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
                done_evt.set()

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        port = server.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}"
        srv_thread = threading.Thread(target=server.handle_request, daemon=True)
        srv_thread.start()

        auth_params = urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": SCOPES,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        webbrowser.open(f"{AUTH_URI}?{auth_params}")

        if not done_evt.wait(timeout=120):
            server.server_close()
            return False, "Google sign-in timed out."
        server.server_close()

        if "code" not in result_box:
            return False, f"Google sign-in failed: {result_box.get('error', 'unknown')}"

        # Exchange authorization code for tokens
        payload = {
            "client_id": client_id,
            "code": result_box["code"],
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        if client_secret:
            payload["client_secret"] = client_secret

        try:
            req = urllib.request.Request(
                TOKEN_URI,
                data=urllib.parse.urlencode(payload).encode("utf-8"),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                tok = json.loads(resp.read().decode("utf-8"))

            # Fetch user email
            u_req = urllib.request.Request(
                USERINFO_URI, headers={"Authorization": f"Bearer {tok['access_token']}"}
            )
            with urllib.request.urlopen(u_req, timeout=10) as u_resp:
                uinfo = json.loads(u_resp.read().decode("utf-8"))
            tok["email"] = uinfo.get("email", "Google Account")
            self._save_token(tok)
            return True, f"Signed in as {tok['email']}"
        except Exception as exc:
            return False, f"Token exchange failed: {exc}"

    def _get_valid_access_token(self) -> str | None:
        tok = self.load_token()
        if not tok:
            return None
        # Refresh if we have a refresh_token
        if tok.get("refresh_token") and self.has_client_secret():
            try:
                client_id, client_secret = self._load_client_config()
                payload = {
                    "client_id": client_id,
                    "refresh_token": tok["refresh_token"],
                    "grant_type": "refresh_token",
                }
                if client_secret:
                    payload["client_secret"] = client_secret
                req = urllib.request.Request(
                    TOKEN_URI,
                    data=urllib.parse.urlencode(payload).encode("utf-8"),
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    refreshed = json.loads(resp.read().decode("utf-8"))
                tok["access_token"] = refreshed["access_token"]
                self._save_token(tok)
            except Exception:
                pass
        return tok.get("access_token")

    def _find_remote_file_id(self, access_token: str) -> str | None:
        q = urllib.parse.urlencode(
            {
                "spaces": "appDataFolder",
                "q": f"name='{REMOTE_FILENAME}' and trashed=false",
                "fields": "files(id,name,modifiedTime)",
            }
        )
        req = urllib.request.Request(
            f"{DRIVE_FILES_URI}?{q}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            files = json.loads(resp.read().decode("utf-8")).get("files", [])
        return files[0]["id"] if files else None

    def upload_config(self, cfg: dict[str, Any]) -> tuple[bool, str]:
        access_token = self._get_valid_access_token()
        if not access_token:
            return False, "Please sign in with Google first."
        try:
            file_id = self._find_remote_file_id(access_token)
            body_bytes = json.dumps(cfg, indent=2).encode("utf-8")
            if file_id:
                req = urllib.request.Request(
                    f"{DRIVE_UPLOAD_URI}/{file_id}?uploadType=media",
                    data=body_bytes,
                    method="PATCH",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                )
            else:
                boundary = "----MBCBoundary7MA4YWxkTrZu0gW"
                meta = json.dumps({"name": REMOTE_FILENAME, "parents": ["appDataFolder"]})
                multipart = (
                    f"--{boundary}\r\n"
                    "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                    f"{meta}\r\n"
                    f"--{boundary}\r\n"
                    "Content-Type: application/json\r\n\r\n"
                    f"{body_bytes.decode('utf-8')}\r\n"
                    f"--{boundary}--\r\n"
                ).encode("utf-8")
                req = urllib.request.Request(
                    f"{DRIVE_UPLOAD_URI}?uploadType=multipart",
                    data=multipart,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": f"multipart/related; boundary={boundary}",
                    },
                )
            with urllib.request.urlopen(req, timeout=15):
                pass
            return True, "Preferences backed up to Google Drive!"
        except Exception as exc:
            return False, f"Cloud upload failed: {exc}"

    def download_config(self) -> tuple[bool, dict[str, Any] | str]:
        access_token = self._get_valid_access_token()
        if not access_token:
            return False, "Please sign in with Google first."
        try:
            file_id = self._find_remote_file_id(access_token)
            if not file_id:
                return False, "No cloud backup found yet."
            req = urllib.request.Request(
                f"{DRIVE_FILES_URI}/{file_id}?alt=media",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return True, data
        except Exception as exc:
            return False, f"Cloud download failed: {exc}"
