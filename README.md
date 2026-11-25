<div align="center">

<img src="docs/assets/app_icon.png" alt="Mouse Battery &amp; Control icon" width="64" />

# Mouse Battery & Control

**Know your wireless mouse battery at a glance — right by the Windows clock.**

[Website](https://aleksa75.github.io/mouse-battery-control/) &bull; [Download v2.30.0 (.zip)](https://github.com/Aleksa75/mouse-battery-control/releases/latest/download/MouseBatteryControl.zip) &bull; [All Releases](https://github.com/Aleksa75/mouse-battery-control/releases)

</div>

---

![Mouse Battery & Control Preview](docs/assets/readme-preview.svg)

## What Is This For?

Wireless mice are great until they die in the middle of a call or game. **Mouse Battery & Control** is a tiny, ad-free Windows tray app built to fix that without installing a heavy driver suite:

- **See your exact battery percentage anytime** in the Windows system tray next to the clock.
- **Know how much time is actually left** — the app learns from your real active usage instead of guessing wildly.
- **Get notified before it's too late** with native Windows alerts when battery drops low or won't last until evening.
- **Tweak mouse settings in seconds** without digging through Windows menus (plus live DPI and polling rate for Logitech wireless mice).

## Key Features

| Feature | What it gives you |
| :--- | :--- |
| **Live System Tray Badge** | Color-coded battery percentage in the taskbar tray (green, amber, red, or charging). |
| **Smart Forecast & Battery Health** | Tracks real active-use drain, plots zoomable battery history, and shows an experimental battery health estimate over cycles. |
| **Timely Windows Notifications** | Alerts you at customizable low/critical levels or when remaining charge won't reach your evening cutoff. |
| **Mouse & Logitech Controls** | Pointer speed, scroll speed, and left/right button swap for **any mouse** — plus live DPI, report rate (`125–1000 Hz`), and onboard profile controls for Logitech HID++ mice. Battery tracking works with Logitech wireless mice (G HUB / HID++) and Bluetooth/BLE mice exposing the Windows GATT Battery Service; generic wired/USB mice get pointer controls only. |
| **Clean, Customizable UI** | Dark mode, Material 3 Light mode, Windows OS accent matching, drag-to-reorder tabs, and full **English / Russian** switch. |
| **Fast, Portable & Private** | Unpacked portable folder for instant startup, zero ads, all data stored locally, Windows DPAPI-encrypted optional Google Drive tokens, and opt-in online mouse icon lookup (off by default). |

## How to Download & Install (30 Seconds)

You don't need Python, Git, or any coding tools to use the app:

1. **Download** [`MouseBatteryControl.zip`](https://github.com/Aleksa75/mouse-battery-control/releases/latest/download/MouseBatteryControl.zip) (~19.6 MB) and [`SHA256SUMS.txt`](https://github.com/Aleksa75/mouse-battery-control/releases/latest) from the [Latest Release](https://github.com/Aleksa75/mouse-battery-control/releases/latest).
2. **Verify & Extract:** Optional (recommended before running): verify the zip checksum with `Get-FileHash MouseBatteryControl.zip -Algorithm SHA256` against `SHA256SUMS.txt`. Then right-click the `.zip` &rarr; **Extract All…** into a permanent folder such as `Documents\MouseBatteryControl`, keeping `MouseBatteryControl.exe` and `_internal` together.
3. **Double-click `MouseBatteryControl.exe`** to open the app and place the battery badge in your system tray.
4. *(Optional)* Open **Notifications** &rarr; turn on **Start with Windows** so it starts automatically when you turn on your PC.

> [!NOTE]
> **First-time launch on Windows?** Because this is a free personal utility without a paid Microsoft developer certificate, Windows Defender SmartScreen may show *"Windows protected your PC"* the first time you open it. Verify the file came from the official GitHub Release (and matches `SHA256SUMS.txt`), then click **More info** &rarr; **Run anyway**.

## Automatic Updates

Automatic updates from **GitHub Releases** are built in out of the box — no `config.json` edits required. Just click **Check for Updates** at the bottom of the app whenever a new version is posted (the updater verifies the release SHA-256 digest before installing).

---

<details>
<summary><strong>For Developers: Run or Build from Source</strong></summary>

Requires **Windows 10 / 11 (64-bit)** and **Python 3.12+**.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python tray_app.py
```

### Build Portable `--onedir` Release

```powershell
.venv\Scripts\pyinstaller.exe --clean --noconfirm MouseBatteryControl.spec
```

### Project Layout

- `tray_app.py` — System tray icon, CustomTkinter UI, Dashboard chart, Notifications, Mouse Control, Sync & Backup
- `monitor.py` — Mouse battery discovery (Logitech G HUB, direct HID++, Bluetooth/BLE), drain learning & forecasting
- `hidpp_mouse.py` — Logitech HID++ 2.0 protocol support (DPI, report rate, LIGHTSYNC RGB, onboard/host mode)
- `mouse_features.py` — Win32 pointer speed, acceleration, scroll lines, button swap & Windows Startup toggle
- `theme.py` — Dark / Soft Light / Matrix themes & WCAG AA Windows accent color derivation
- `i18n.py` — English and Russian localization strings
- `updater.py` — Safe `.zip` (`--onedir`) and legacy `.exe` self-updater with SHA-256 verification & rollback
- `telemetry.py` — Local rotating JSONL action verification log
- `cloud_sync.py` — Optional Google Drive configuration & history backup
- `docs/` — Source for the [GitHub Pages site](https://aleksa75.github.io/mouse-battery-control/)

</details>
