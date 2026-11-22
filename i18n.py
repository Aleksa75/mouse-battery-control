"""
Localization module (English / Russian) for Mouse Battery & Control.
Provides STRINGS dictionary and tr(lang, key, **kwargs) lookup helper.
"""

from __future__ import annotations

from typing import Any

LANG_LABELS: dict[str, str] = {"en": "English", "ru": "Русский"}
LABEL_TO_LANG: dict[str, str] = {"English": "en", "Русский": "ru"}

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # App header, nav & footer
        "app_title": "Mouse Battery & Control",
        "app_subtitle": "Smart battery forecasting & Windows mouse tuning",
        "detecting": "DETECTING...",
        "no_battery_data": "No mouse battery data yet",
        "device_pill_tip": "Left-click: choose mouse\nRight-click: choose custom mouse icon",
        "device_menu_refresh": "Refresh Connected Mice",
        "device_hide_tip": "Hide this device",
        "device_hidden_toast": "✓ Hidden {device}",
        "device_restore_hidden": "Restore Hidden ({n})",
        "device_restored_toast": "✓ Restored hidden devices",
        "battery_unavailable": "Battery telemetry unavailable",
        "conn_bluetooth": "Connection: Bluetooth",
        "tab_dashboard": "Dashboard",
        "tab_notifications": "Notifications",
        "tab_mouse": "Mouse Control",
        "tab_sync": "Sync & Backup",
        "tab_bar_tip": "Click to switch • Hold & drag to reorder • Right-click to reset",
        "tab_order_saved": "✓ Tab order saved",
        "tab_order_reset": "✓ Tab order reset to default",
        "check_updates": "Check for Updates",
        "update_available_btn": "Update Available",
        "check_updates_tip": "Check for a newer version",
        "update_tip_header": "Update v{version} available",
        "update_tip_click": "Click to install update.",
        "checking_updates": "Checking for updates...",
        "updates_not_configured": "Set 'update_source' in config.json to enable updates",
        "about_tip": "About & Version Info",
        "gear_tip": "Tools & Test Notification",
        "gear_test_notify": "Send Test Notification",
        "gear_refresh": "Refresh Battery Now",
        "gear_open_log": "Open Diagnostic Log",
        "gear_open_telemetry": "Open Action Telemetry",
        "gear_open_folder": "Open App Folder",
        "toast_test_sent": "Test notification sent!",
        "toast_refreshed": "Refreshed battery status",
        "toast_no_log": "No log entries yet",
        "toast_no_telemetry": "No action telemetry recorded yet",

        # Tray menu
        "tray_open": "Open Dashboard & Settings",
        "tray_refresh": "Refresh Now",
        "tray_test_notify": "Send Test Notification",
        "tray_open_ghub": "Open Logitech G HUB",
        "tray_check_updates": "Check for Updates",
        "tray_update_available": "Update Available (v{version})",
        "tray_quit": "Quit",
        "tray_charging": " (Charging)",
        "tray_left_fmt": "{device}: {pct}%{chg} • ~{time} left",

        # Dashboard
        "gauge_battery": "BATTERY",
        "gauge_charging": "CHARGING",
        "evening_checking": "Checking evening forecast...",
        "evening_charging": "⚡ Charging Now",
        "evening_wont_last": "⚠ Won't last till {hour:02d}:00",
        "evening_will_last": "✓ Will last past {hour:02d}:00",
        "battery_remaining": "Battery Remaining:",
        "usage_drain_rate": "Usage Drain Rate:",
        "est_power_draw": "Est. Power Draw:",
        "est_power_fmt": "~{total:.0f} mW ({sys:.0f} sys + {rate:.0f} @ {hz} Hz)",
        "learning": "Learning",
        "calibrating": "Calibrating",
        "learned_pill": "Learned",
        "click_to_inspect": "Click to see what has been learned so far.",
        "early_est_tip": "Early estimate ({pct}% of first cycle measured).\nAccuracy improves automatically after 1–2 full charge/discharge cycles.",
        "estimating_life": "Estimating battery life...",
        "battery_history": "Battery History",
        "range_24h": "24h",
        "range_7d": "7d",
        "range_30d": "30d",
        "reset_zoom": "Reset Zoom",
        "reset_zoom_x": "Reset ({zoom:.1f}x)",
        "reset_zoom_tip": "Hold Ctrl + Scroll over chart to zoom in/out.\nClick here to reset to full range.",
        "collecting_samples": "Collecting battery samples — your usage curve will appear here automatically.",
        "forecast": "Forecast",
        "now": "Now",
        "est_short": "est.",
        "sess_short": "sess.",
        "hover_est_fmt": "~{pct}% (est.)  •  {time}",
        "hover_hist_fmt": "{pct}%{chg}  •  {time}",
        "switched_device": "Switched to {device}",
        "custom_icon_title": "Choose Custom Icon for {device}",
        "custom_icon_saved": "✓ Custom mouse icon saved!",
        "custom_icon_err": "Could not load selected image",

        # Notifications & Appearance
        "enable_notifs": "Enable Battery Notifications",
        "close_to_tray": "Close to System Tray (keep running in background)",
        "start_with_windows": "Start Automatically with Windows",
        "notif_sound": "Notification Sound",
        "preview": "Preview",
        "appearance_theme": "Appearance Theme",
        "theme_system": "System",
        "theme_dark": "Dark",
        "theme_light": "Light",
        "accent_color": "Accent Color",
        "accent_windows": "Windows",
        "accent_default": "Default",
        "language": "Language",
        "slider_evening": "Evening Target Hour",
        "slider_low": "Low Battery Warning",
        "slider_critical": "Critical Battery Warning",
        "slider_cooldown": "Notification Cooldown",
        "slider_poll": "Background Check Interval",
        "min_unit": "min",
        "sound_preview_title": "Sound Preview",
        "sound_preview_body": "Selected notification sound: {sound}",
        "previewing_sound": "Previewing '{sound}' notification sound",
        "close_to_tray_on": "✓ Window will minimize to tray on close",
        "close_to_tray_off": "✓ Window will quit app on close",
        "autostart_on": "✓ Start with Windows enabled",
        "autostart_off": "✓ Start with Windows disabled",
        "switched_theme": "✓ Switched to {theme} theme",
        "switched_accent": "✓ Accent color: {mode}",
        "switched_lang": "✓ Language switched to {lang}",
        "saved_short": "✓ Saved",
        "settings_saved": "✓ Settings saved",

        # Mouse Control
        "quick_presets": "Quick Mouse Presets",
        "preset_gaming": "Gaming",
        "preset_gaming_desc": "Raw input • Accel OFF",
        "preset_gaming_tip": (
            "Gaming Preset\n"
            "• Pointer Speed: 10 (1:1 Windows default)\n"
            "• Acceleration: OFF (raw, predictable aim)\n"
            "• Scroll: 3 lines per notch\n"
            "Best for FPS and fast-paced games."
        ),
        "preset_precision": "Precision",
        "preset_precision_desc": "Fine control • Accel OFF",
        "preset_precision_tip": (
            "Precision Preset\n"
            "• Pointer Speed: 8 (slower, finer control)\n"
            "• Acceleration: OFF (consistent movement)\n"
            "• Scroll: 3 lines per notch\n"
            "Best for design, photo editing, and pixel-accurate work."
        ),
        "preset_productivity": "Productivity",
        "preset_productivity_desc": "Fast travel • Accel ON",
        "preset_productivity_tip": (
            "Productivity Preset\n"
            "• Pointer Speed: 14 (faster cursor travel)\n"
            "• Acceleration: ON (quick across multi-monitors)\n"
            "• Scroll: 6 lines per notch (faster scrolling)\n"
            "Best for browsing, coding, and wide/multi-monitor setups."
        ),
        "pointer_speed": "Pointer Speed (1–20)",
        "wheel_scroll": "Scroll Wheel Lines per Notch",
        "mouse_accel": "Mouse Acceleration",
        "accel_tip": (
            "Windows 'Enhance Pointer Precision' (Mouse Acceleration):\n"
            "Moving your hand faster makes the cursor travel farther.\n\n"
            "• Off: 1:1 predictable movement (best for gaming & design).\n"
            "• Auto: ON for desktop, automatically turns OFF when a game\n"
            "  is in focus (auto-detects Steam/Epic/Riot/etc. + custom games).\n"
            "• On: Always enabled (easy across wide/dual monitors)."
        ),
        "add_game": "+ Game",
        "select_game_title": "Select Game Executable (.exe)",
        "added_game": "✓ Added {exe} to Auto Game list",
        "accel_off": "Off",
        "accel_auto": "Auto",
        "accel_on": "On",
        "accel_set_off": "✓ Mouse Acceleration: Off (Raw 1:1)",
        "accel_set_on": "✓ Mouse Acceleration: On",
        "accel_set_auto": "✓ Mouse Acceleration: Auto (Off in games)",
        "swap_buttons": "Swap Primary & Secondary Buttons (Left-Handed)",
        "buttons_updated": "✓ Mouse buttons updated",
        "preset_applied": "✓ Applied '{name}' preset",
        "mouse_applied": "✓ Mouse settings applied",
        "dpi_card_title": "DPI Speeds & Report Rate",
        "hidpp_live": "HID++ Live",
        "hidpp_unavail_msg": "Hardware DPI, polling rate, and RGB controls are unavailable for this mouse (Logitech HID++ 2.0 required). Windows pointer settings above still apply.",
        "open_ghub": "Open G HUB",
        "mouse_mode": "Mouse Mode:",
        "mouse_mode_tip": (
            "Hardware Mode (Logitech 0x8100 OnboardProfiles):\n\n"
            "• Onboard (Recommended): Physical DPI buttons & onboard LED\n"
            "  flashes on the mouse work natively without G HUB; app DPI\n"
            "  buttons & live DPI readout also work. Report Rate uses the\n"
            "  onboard profile (typically 1000 Hz).\n\n"
            "• Host: Unlocks live Report Rate (125–1000 Hz) & direct\n"
            "  software RGB control, but Logitech firmware disables\n"
            "  physical DPI button cycling while G HUB is closed."
        ),
        "mode_onboard": "Onboard",
        "mode_host": "Host",
        "mode_set_onboard": "✓ Mouse Mode: Onboard (physical DPI buttons active)",
        "mode_set_host": "✓ Mouse Mode: Host (live Report Rate unlocked)",
        "mode_busy": "Saved Mouse Mode '{mode}' (HID++ busy)",
        "onboard_profile": "Onboard Profile:",
        "onboard_profile_tip": (
            "Onboard Memory Profiles (Slot 1–5):\n\n"
            "Each slot stores its own saved DPI stages, button bindings,\n"
            "report rate, and lighting directly inside the mouse's flash memory\n"
            "(configured in Logitech G HUB).\n\n"
            "• Switching slots works natively without G HUB running\n"
            "  (e.g., Slot 1 for work/desktop, Slot 2 for FPS gaming).\n"
            "• Automatically uses Onboard Mode so physical DPI buttons keep working."
        ),
        "slot_fmt": "Slot {n}",
        "slot_active": "✓ Active Onboard Profile: Slot {slot}",
        "slot_busy": "Saved Slot {slot} (HID++ busy)",
        "report_rate": "Report Rate (Polling):",
        "report_rate_tip": (
            "USB / LIGHTSPEED Polling Rate:\n"
            "How often per second the mouse reports movement & clicks to PC.\n\n"
            "Examples:\n"
            "• 1000 Hz (1 ms interval): Lowest latency & smoothest cursor — best\n"
            "  for FPS/competitive gaming and 144Hz+ monitors.\n"
            "• 500 Hz (2 ms interval): Smooth everyday feel with lower radio overhead.\n"
            "• 250 / 125 Hz (4–8 ms interval): Lower CPU/wireless overhead for office or travel.\n\n"
            "Note: Reports only send while moving (slow motion tests lower).\n"
            "Live changes require switching Mouse Mode to Host."
        ),
        "rate_need_host": "Switch Mouse Mode to Host to change Report Rate",
        "rate_set_ok": "✓ Hardware Report Rate set to {rate}",
        "rate_set_busy": "Saved {rate} (HID++ busy)",
        "dpi_mouse_changed": "Mouse DPI: {dpi}",
        "dpi_set_ok": "✓ Hardware DPI set to {dpi}",
        "dpi_set_busy": "Saved {dpi} DPI (HID++ busy)",
        "lightsync_rgb": "LIGHTSYNC RGB:",
        "rgb_off": "Off (Eco)",
        "rgb_fixed": "Fixed",
        "rgb_breathing": "Breathing",
        "rgb_cycle": "Cycle",
        "rgb_set_ok": "✓ RGB set to {mode}",
        "rgb_set_busy": "Saved RGB '{mode}' (HID++ busy)",
        "rgb_color_ok": "✓ RGB color: {color} ({mode})",
        "rgb_color_busy": "Saved {color} (HID++ busy)",
        "color_lbl": "Color:",

        # Sync & Backup
        "local_prefs": "Local Preferences",
        "local_prefs_desc": "Settings auto-save to config.json. Export or import a backup anytime.",
        "export_prefs": "Export Preferences (.json)",
        "import_prefs": "Import Preferences (.json)",
        "export_title": "Export Preferences",
        "import_title": "Import Preferences",
        "prefs_exported": "✓ Preferences exported",
        "prefs_imported": "✓ Preferences imported!",
        "import_failed": "Import failed: {err}",
        "cloud_sync": "Google Drive Sync",
        "cloud_sync_desc": "Back up and restore your mouse settings privately with your Google account.",
        "sign_in_google": "Sign in with Google",
        "sign_out": "Sign Out",
        "add_google_key": "Add Google Key File",
        "backup_drive": "Backup to Google Drive",
        "restore_drive": "Restore from Google Drive",
        "cloud_connected": "✓ Connected as {email}",
        "cloud_ready": "Ready to sign in with Google",
        "cloud_setup_prompt": "First time? Click here for 3-step Google Drive setup →",
        "select_secret_title": "Select Google OAuth Desktop client_secret.json",
        "creds_loaded": "✓ Google OAuth credentials loaded",
        "invalid_json": "Invalid JSON: {err}",
        "signed_out": "Signed out of Google",
        "opening_signin": "Opening browser for Google Sign-In...",
        "uploading_drive": "Uploading preferences to Google Drive...",
        "restoring_drive": "Restoring preferences from Google Drive...",
        "restored_drive": "✓ Restored preferences from Google Drive!",
        "google_guide_msg": (
            "To back up your settings to Google Drive (one-time setup):\n\n"
            "1. Open Google Cloud Console → APIs & Services → Credentials\n"
            "   (enable 'Google Drive API' first).\n"
            "2. Click 'Create Credentials' → 'OAuth client ID' → 'Desktop app',\n"
            "   then download the JSON key file.\n"
            "3. Click 'Add Google Key File' in this app and select that file,\n"
            "   then click 'Sign in with Google'.\n\n"
            "Would you like to open Google Cloud Console in your browser now?"
        ),

        # About & Modals
        "about_title": "About Mouse Battery & Control",
        "active_device": "Active Device",
        "model": "Model",
        "status": "Status",
        "firmware": "Firmware",
        "no_mouse_detected": "No mouse detected",
        "charging_word": "Charging",
        "battery_word": "Battery",
        "unknown": "Unknown",
        "hidpp_features": "HID++ 2.0 Features",
        "recent_highlights": "Recent Highlights",
        "close": "Close",
        "active_dot": "● Active",
        "pending_dot": "○ Pending / Unavailable",
        "mode_onboard_active": "● Onboard (physical DPI active)",
        "mode_host_active": "● Host (live Rate/RGB mode)",
        "mode_unknown": "Unknown (HID++ not connected)",
        "update_avail_title": "Update Available",
        "update_now": "Update Now",
        "later": "Later",
        "update_prompt_tail": "Download, replace, and relaunch now?",
        "update_default_notes": "New version ready to install.",
        "update_failed_title": "Update Failed",
        "connect_drive_title": "Connect Google Drive",
        "connect": "Connect",
        "cancel": "Cancel",
        "hl_v2280": "Collapsible Recent Highlights in About (latest 4 shown, earlier releases expandable)",
        "hl_v2270": "Softer cool-slate Light theme, crisp switch knobs & vivid Windows accent colors",
        "hl_v2260": "One-dir packaging (instant startup, no %TEMP% unpacking) & .zip auto-updater",
        "hl_v2250": "Faster startup, active-use battery capacity/health & action telemetry verification",
        "hl_v2240": "Hold & drag navigation tabs to rearrange (saved automatically; right-click to reset)",
        "hl_v2230": "Device-aware Mouse Control: hides Logitech HID++ DPI/polling controls for other mice",
        "hl_v2220": "Polling-rate power model (8/5/3/2 mW) scaling remaining battery time live",
        "hl_v2210": "Per-mouse battery history, cleaner device names, keyboard filter & hide device (✕)",
        "hl_v2200": "Light theme polish: high-contrast toggle switches, crisper cards & segmented pills",
        "hl_v2190": "Match Windows OS accent color with automatic WCAG AA contrast",
        "hl_v2180": "Universal mouse discovery (Bluetooth/BLE, HID++, USB HID) & mouse switcher menu",
        "hl_v2170": "WCAG AA contrast overhaul for Light/Dark themes & instant Win11 Light title bar",
        "hl_v2160": "Added 4 secret Easter eggs (Aim Trainer, Konami chase, Gauge spin, Matrix theme)",
        "hl_v2150": "Smooth Dark/Light theme crossfade transition",
        "hl_v2140": "Footer 'Update Available' indicator with hover changelog tooltip",
        "hl_v2130": "Dynamic Battery History X-axis time spots & resizable window",
        "hl_v2120": "Clickable Learning pill on Dashboard with 'Learned So Far' summary",
        "hl_v2110": "Added English / Russian language switch across the entire app",
        "hl_v2100": "Battery History Ctrl+Scroll zoom & Reset Zoom button",
        "hl_v295": "Removed decorative/estimated power draw; real hardware data only",
        "hl_v294": "Fast 150ms live DPI sync & onboard DPI stage sync (0x8100)",
        "highlights_show_more": "▸ Show earlier releases ({count})",
        "highlights_show_less": "▾ Hide earlier releases",

        # Learned So Far dialog
        "learned_title": "Learned So Far",
        "learned_calibrated_badge": "Calibrated",
        "learned_progress_fmt": "{drop}% / 80% discharged ({pct}% calibrated)",
        "learned_calibrated_fmt": "{drop}% total discharged • Calibrated",
        "learned_active_rate": "Active Drain Rate",
        "learned_rate_learned_fmt": "{rate:.1f}%/hr (learned from {n} sess.)",
        "learned_rate_default_fmt": "{rate:.1f}%/hr (default — not enough data)",
        "learned_samples": "Samples Recorded",
        "learned_samples_fmt": "{n} samples (since {since})",
        "learned_none_yet": "None yet",
        "learned_measured_time": "Measured Discharge",
        "learned_measured_fmt": "{dur} across {n} sess.",
        "learned_observed_range": "Observed Range",
        "learned_not_enough": "Not enough data yet",
        "learned_weekday_weekend": "Weekday / Weekend",
        "learned_no_data": "No data",
        "unit_pct_hr": "%/hr",
        "learned_tod_title": "By Time of Day",
        "tod_night": "Night",
        "tod_morning": "Morning",
        "tod_afternoon": "Day",
        "tod_evening": "Evening",
        "learned_recent_title": "Recent Measured Sessions",
        "learned_no_sessions_msg": "No qualifying discharge sessions yet. A session is logged after ≥15 min and ≥1% drop while unplugged.",
        "health_card_title": "Battery Capacity & Health",
        "health_advertised": "Advertised Capacity",
        "health_cycles": "Recorded Charge Cycles",
        "health_est_cap": "Est. Real Capacity",
        "health_est_pct": "Est. Battery Health",
        "health_calibrating_fmt": "Calibrating ({cur:.1f} / 2.0 active cycles)",
        "health_cycles_fmt": "{cycles:.2f} cycles",
        "health_adv_fmt": "{mah} mAh (~{mwh:.0f} mWh)",
        "health_est_fmt": "~{mah} mAh (~{mwh:.0f} mWh)",
        "health_unavail": "Unavailable (non-Logitech / no power model)",

        # Easter Eggs
        "ee_konami_toast": "🧀 Konami Code! The mouse caught the cheese!",
        "ee_gauge_toast": "⚡ Nice try — still {pct}% battery! (+0% overclock)",
        "ee_matrix_unlocked": "🟩 Matrix mode unlocked! Welcome to the terminal.",
        "ee_version_countdown": "Secret game in {left} more taps...",
        "ee_aim_title": "Secret Aim & Reflex Trainer",
        "ee_aim_sub": "Click the targets as fast as you can in 15 seconds!",
        "ee_aim_start": "Start (15s)",
        "ee_aim_again": "Play Again",
        "ee_aim_hits": "Hits",
        "ee_aim_avg": "Avg Reaction",
        "ee_aim_best": "Best",
        "ee_aim_done": "Time's up! {hits} hits • {hps:.2f}/s • Avg {avg} ms",
        "ee_aim_done_zero": "Time's up! 0 hits — give it another shot!",
    },
    "ru": {
        # App header, nav & footer
        "app_title": "Mouse Battery & Control",
        "app_subtitle": "Умный прогноз заряда и настройка мыши Windows",
        "detecting": "ПОИСК...",
        "no_battery_data": "Нет данных о батарее мыши",
        "device_pill_tip": "ЛКМ: выбрать мышь\nПКМ: выбрать свою иконку мыши",
        "device_menu_refresh": "Обновить список мышей",
        "device_hide_tip": "Скрыть это устройство",
        "device_hidden_toast": "✓ Скрыто: {device}",
        "device_restore_hidden": "Восстановить скрытые ({n})",
        "device_restored_toast": "✓ Скрытые устройства восстановлены",
        "battery_unavailable": "Данные о заряде недоступны",
        "conn_bluetooth": "Подключение: Bluetooth",
        "tab_dashboard": "Обзор",
        "tab_notifications": "Уведомления",
        "tab_mouse": "Управление",
        "tab_sync": "Бэкап",
        "tab_bar_tip": "Клик — переключить • Удерживайте и перетащите — порядок • ПКМ — сброс",
        "tab_order_saved": "✓ Порядок вкладок сохранён",
        "tab_order_reset": "✓ Порядок вкладок сброшен",
        "check_updates": "Проверить обновления",
        "update_available_btn": "Доступно обновление",
        "check_updates_tip": "Проверить наличие новой версии",
        "update_tip_header": "Доступно обновление v{version}",
        "update_tip_click": "Нажмите, чтобы установить.",
        "checking_updates": "Проверка обновлений...",
        "updates_not_configured": "Укажите 'update_source' в config.json для обновлений",
        "about_tip": "О программе и версия",
        "gear_tip": "Инструменты и тест уведомлений",
        "gear_test_notify": "Отправить тест-уведомление",
        "gear_refresh": "Обновить заряд сейчас",
        "gear_open_log": "Открыть лог диагностики",
        "gear_open_telemetry": "Открыть телеметрию действий",
        "gear_open_folder": "Открыть папку приложения",
        "toast_test_sent": "Тестовое уведомление отправлено!",
        "toast_refreshed": "Статус батареи обновлён",
        "toast_no_log": "Записей в логе пока нет",
        "toast_no_telemetry": "Телеметрия действий пока пуста",

        # Tray menu
        "tray_open": "Открыть окно настроек",
        "tray_refresh": "Обновить сейчас",
        "tray_test_notify": "Тестовое уведомление",
        "tray_open_ghub": "Открыть Logitech G HUB",
        "tray_check_updates": "Проверить обновления",
        "tray_update_available": "Доступно обновление (v{version})",
        "tray_quit": "Выход",
        "tray_charging": " (Зарядка)",
        "tray_left_fmt": "{device}: {pct}%{chg} • ~{time} ост.",

        # Dashboard
        "gauge_battery": "БАТАРЕЯ",
        "gauge_charging": "ЗАРЯДКА",
        "evening_checking": "Проверка прогноза на вечер...",
        "evening_charging": "⚡ Идёт зарядка",
        "evening_wont_last": "⚠ Не хватит до {hour:02d}:00",
        "evening_will_last": "✓ Хватит до {hour:02d}:00+",
        "battery_remaining": "Осталось заряда:",
        "usage_drain_rate": "Расход заряда:",
        "est_power_draw": "Расход (прибл.):",
        "est_power_fmt": "~{total:.0f} мВт ({sys:.0f} сист. + {rate:.0f} @ {hz} Гц)",
        "learning": "Обучение",
        "calibrating": "Калибровка",
        "learned_pill": "Обучено",
        "click_to_inspect": "Нажмите, чтобы посмотреть собранные данные.",
        "early_est_tip": "Ранняя оценка (измерено {pct}% первого цикла).\nТочность вырастет автоматически после 1–2 полных циклов.",
        "estimating_life": "Расчёт времени работы...",
        "battery_history": "История заряда",
        "range_24h": "24ч",
        "range_7d": "7д",
        "range_30d": "30д",
        "reset_zoom": "Сброс зума",
        "reset_zoom_x": "Сброс ({zoom:.1f}x)",
        "reset_zoom_tip": "Удерживайте Ctrl + Колёсико мыши на графике для масштаба.\nНажмите, чтобы сбросить масштаб.",
        "collecting_samples": "Сбор замеров батареи — кривая расхода появится автоматически.",
        "forecast": "Прогноз",
        "now": "Сейчас",
        "est_short": "оц.",
        "sess_short": "сесс.",
        "hover_est_fmt": "~{pct}% (прогн.)  •  {time}",
        "hover_hist_fmt": "{pct}%{chg}  •  {time}",
        "switched_device": "Выбрана мышь: {device}",
        "custom_icon_title": "Выбрать иконку для {device}",
        "custom_icon_saved": "✓ Своя иконка мыши сохранена!",
        "custom_icon_err": "Не удалось загрузить изображение",

        # Notifications & Appearance
        "enable_notifs": "Включить уведомления о заряде",
        "close_to_tray": "Сворачивать в трей при закрытии окна",
        "start_with_windows": "Запускать автоматически с Windows",
        "notif_sound": "Звук уведомления",
        "preview": "Тест",
        "appearance_theme": "Тема оформления",
        "theme_system": "Система",
        "theme_dark": "Тёмная",
        "theme_light": "Светлая",
        "accent_color": "Акцентный цвет",
        "accent_windows": "Windows",
        "accent_default": "Стандартный",
        "language": "Язык / Language",
        "slider_evening": "Вечерний ориентир",
        "slider_low": "Предупреждение о низком заряде",
        "slider_critical": "Критическое предупреждение",
        "slider_cooldown": "Пауза между уведомлениями",
        "slider_poll": "Интервал фоновой проверки",
        "min_unit": "мин",
        "sound_preview_title": "Проверка звука",
        "sound_preview_body": "Выбранный звук: {sound}",
        "previewing_sound": "Тест звука '{sound}'",
        "close_to_tray_on": "✓ При закрытии окно свернётся в трей",
        "close_to_tray_off": "✓ При закрытии приложение завершится",
        "autostart_on": "✓ Автозапуск с Windows включён",
        "autostart_off": "✓ Автозапуск с Windows отключён",
        "switched_theme": "✓ Включена тема: {theme}",
        "switched_accent": "✓ Акцентный цвет: {mode}",
        "switched_lang": "✓ Язык переключён: {lang}",
        "saved_short": "✓ Сохранено",
        "settings_saved": "✓ Настройки сохранены",

        # Mouse Control
        "quick_presets": "Быстрые профили мыши",
        "preset_gaming": "Игры",
        "preset_gaming_desc": "1:1 ввод • Ускор. ВЫКЛ",
        "preset_gaming_tip": (
            "Игровой профиль\n"
            "• Скорость указателя: 10 (стандарт Windows 1:1)\n"
            "• Ускорение: ВЫКЛ (предсказуемый прицел 1:1)\n"
            "• Прокрутка: 3 строки за шаг\n"
            "Оптимально для шутеров и динамичных игр."
        ),
        "preset_precision": "Точность",
        "preset_precision_desc": "Плавность • Ускор. ВЫКЛ",
        "preset_precision_tip": (
            "Профиль точности\n"
            "• Скорость указателя: 8 (ниже, точнее наведение)\n"
            "• Ускорение: ВЫКЛ (равномерное движение)\n"
            "• Прокрутка: 3 строки за шаг\n"
            "Отлично для дизайна, ретуши и работы с текстом."
        ),
        "preset_productivity": "Работа",
        "preset_productivity_desc": "Быстро • Ускор. ВКЛ",
        "preset_productivity_tip": (
            "Профиль для работы\n"
            "• Скорость указателя: 14 (быстрее перемещение)\n"
            "• Ускорение: ВКЛ (удобно на широких и мультимониторах)\n"
            "• Прокрутка: 6 строк за шаг (быстрый скролл)\n"
            "Удобно для браузера, кода и офисной работы."
        ),
        "pointer_speed": "Скорость указателя (1–20)",
        "wheel_scroll": "Строк прокрутки за щелчок колеса",
        "mouse_accel": "Ускорение мыши (Повыш. точность)",
        "accel_tip": (
            "Параметр Windows «Включить повышенную точность установки указателя»:\n"
            "При быстром движении рукой курсор проходит большее расстояние.\n\n"
            "• Выкл: честное 1:1 движение (лучше для игр и дизайна).\n"
            "• Авто: ВКЛ на рабочем столе и автоматически ВЫКЛ в игре\n"
            "  (распознаёт Steam/Epic/Riot и ваши игры).\n"
            "• Вкл: всегда включено (удобно на широких мониторах)."
        ),
        "add_game": "+ Игра",
        "select_game_title": "Выберите исполняемый файл игры (.exe)",
        "added_game": "✓ Игра {exe} добавлена в Авто-список",
        "accel_off": "Выкл",
        "accel_auto": "Авто",
        "accel_on": "Вкл",
        "accel_set_off": "✓ Ускорение мыши: Выкл (1:1)",
        "accel_set_on": "✓ Ускорение мыши: Вкл",
        "accel_set_auto": "✓ Ускорение: Авто (Выкл в играх)",
        "swap_buttons": "Поменять местами ЛКМ и ПКМ (для левшей)",
        "buttons_updated": "✓ Кнопки мыши обновлены",
        "preset_applied": "✓ Применён профиль «{name}»",
        "mouse_applied": "✓ Настройки мыши применены",
        "dpi_card_title": "Уровни DPI и частота опроса",
        "hidpp_live": "HID++ Live",
        "open_ghub": "Открыть G HUB",
        "mouse_mode": "Режим мыши:",
        "mouse_mode_tip": (
            "Аппаратный режим (Logitech 0x8100 OnboardProfiles):\n\n"
            "• Память (Рекомендуется): Физические кнопки DPI и родная\n"
            "  подсветка индикатора DPI работают без G HUB; кнопки DPI\n"
            "  и быстрый статус в приложении тоже работают.\n"
            "  Частота опроса берётся из встроенного профиля (обычно 1000 Hz).\n\n"
            "• ПК (Host): Открывает смену частоты опроса (125–1000 Hz)\n"
            "  и прямое управление RGB, но прошивка отключает\n"
            "  переключение DPI кнопкой на мыши, пока закрыт G HUB."
        ),
        "mode_onboard": "Память",
        "mode_host": "ПК (Host)",
        "mode_set_onboard": "✓ Режим: Память мыши (кнопки DPI активны)",
        "mode_set_host": "✓ Режим: ПК / Host (частота опроса разблокирована)",
        "mode_busy": "Сохранён режим «{mode}» (HID++ занят)",
        "onboard_profile": "Встроенный профиль:",
        "onboard_profile_tip": (
            "Профили во встроенной памяти мыши (Слот 1–5):\n\n"
            "Каждый слот хранит свои уровни DPI, назначения кнопок,\n"
            "частоту опроса и эффект подсветки прямо в памяти мыши\n"
            "(настраиваются один раз через Logitech G HUB).\n\n"
            "• Слоты переключаются напрямую без запущенного G HUB\n"
            "  (например, Слот 1 для работы, Слот 2 для шутеров).\n"
            "• Автоматически использует режим Памяти мыши."
        ),
        "slot_fmt": "Слот {n}",
        "slot_active": "✓ Активный встроенный профиль: Слот {slot}",
        "slot_busy": "Сохранён Слот {slot} (HID++ занят)",
        "report_rate": "Частота опроса:",
        "report_rate_tip": (
            "Частота опроса USB / LIGHTSPEED:\n"
            "Сколько раз в секунду мышь отправляет координаты и клики ПК.\n\n"
            "Примеры:\n"
            "• 1000 Hz (интервал 1 мс): минимальная задержка — лучше\n"
            "  для шутеров и мониторов от 144 Гц.\n"
            "• 500 Hz (интервал 2 мс): плавная работа при меньшей нагрузке.\n"
            "• 250 / 125 Hz (4–8 мс): ниже нагрузка на радио/CPU для офиса и поездок.\n\n"
            "Важно: отчёты идут только при движении (медленно в тестах ниже).\n"
            "Для смены частоты переключите режим мыши на «ПК (Host)»."
        ),
        "rate_need_host": "Переключите Режим мыши в «ПК (Host)» для смены частоты",
        "rate_set_ok": "✓ Частота опроса установлена: {rate}",
        "rate_set_busy": "Сохранено: {rate} (HID++ занят)",
        "dpi_mouse_changed": "DPI на мыши: {dpi}",
        "dpi_set_ok": "✓ Аппаратный DPI установлен: {dpi}",
        "dpi_set_busy": "Сохранено {dpi} DPI (HID++ занят)",
        "lightsync_rgb": "Подсветка RGB:",
        "hidpp_unavail_msg": "Аппаратный DPI, частота опроса и подсветка RGB недоступны для этой мыши (требуется Logitech HID++ 2.0). Настройки указателя Windows выше продолжают работать.",
        "rgb_off": "Выкл",
        "rgb_fixed": "Статика",
        "rgb_breathing": "Дыхание",
        "rgb_cycle": "Цикл",
        "rgb_set_ok": "✓ Режим RGB: {mode}",
        "rgb_set_busy": "Сохранён RGB «{mode}» (HID++ занят)",
        "rgb_color_ok": "✓ Цвет RGB: {color} ({mode})",
        "rgb_color_busy": "Сохранён цвет {color} (HID++ занят)",
        "color_lbl": "Цвет:",

        # Sync & Backup
        "local_prefs": "Локальные настройки",
        "local_prefs_desc": "Настройки сохраняются в config.json. Экспорт и импорт в любой момент.",
        "export_prefs": "Экспорт настроек (.json)",
        "import_prefs": "Импорт настроек (.json)",
        "export_title": "Экспорт настроек",
        "import_title": "Импорт настроек",
        "prefs_exported": "✓ Настройки экспортированы",
        "prefs_imported": "✓ Настройки импортированы!",
        "import_failed": "Ошибка импорта: {err}",
        "cloud_sync": "Синхронизация Google Drive",
        "cloud_sync_desc": "Храните и восстанавливайте настройки мыши в своём Google-аккаунте.",
        "sign_in_google": "Войти через Google",
        "sign_out": "Выйти",
        "add_google_key": "Добавить JSON-ключ Google",
        "backup_drive": "Сохранить в Google Drive",
        "restore_drive": "Восстановить из Google Drive",
        "cloud_connected": "✓ Подключён аккаунт {email}",
        "cloud_ready": "Готово к входу через Google",
        "cloud_setup_prompt": "Впервые? Нажмите для инструкции по настройке Google Drive →",
        "select_secret_title": "Выберите Google OAuth Desktop client_secret.json",
        "creds_loaded": "✓ Ключ Google OAuth загружен",
        "invalid_json": "Неверный JSON: {err}",
        "signed_out": "Вышли из Google-аккаунта",
        "opening_signin": "Открываю браузер для входа в Google...",
        "uploading_drive": "Выгрузка настроек в Google Drive...",
        "restoring_drive": "Загрузка настроек из Google Drive...",
        "restored_drive": "✓ Настройки восстановлены из Google Drive!",
        "google_guide_msg": (
            "Для резервного копирования настроек в Google Drive (однократно):\n\n"
            "1. Откройте Google Cloud Console → APIs & Services → Credentials\n"
            "   (сначала включите 'Google Drive API').\n"
            "2. Нажмите 'Create Credentials' → 'OAuth client ID' → 'Desktop app'\n"
            "   и скачайте JSON-файл ключа.\n"
            "3. Нажмите «Добавить JSON-ключ Google» в приложении и выберите файл,\n"
            "   затем нажмите «Войти через Google».\n\n"
            "Открыть Google Cloud Console в браузере сейчас?"
        ),

        # About & Modals
        "about_title": "О программе Mouse Battery & Control",
        "active_device": "Активное устройство",
        "model": "Модель",
        "status": "Статус",
        "firmware": "Прошивка",
        "no_mouse_detected": "Мышь не обнаружена",
        "charging_word": "Зарядка",
        "battery_word": "Батарея",
        "unknown": "Неизвестно",
        "hidpp_features": "Функции HID++ 2.0",
        "recent_highlights": "Последние изменения",
        "close": "Закрыть",
        "active_dot": "● Активно",
        "pending_dot": "○ Ожидание / Недоступно",
        "mode_onboard_active": "● Память мыши (кнопки DPI активны)",
        "mode_host_active": "● ПК / Host (частота / RGB)",
        "mode_unknown": "Неизвестно (HID++ не подключён)",
        "update_avail_title": "Доступно обновление",
        "update_now": "Обновить",
        "later": "Позже",
        "update_prompt_tail": "Скачать, заменить и перезапустить сейчас?",
        "update_default_notes": "Новая версия готова к установке.",
        "update_failed_title": "Ошибка обновления",
        "connect_drive_title": "Подключение Google Drive",
        "connect": "Открыть",
        "cancel": "Отмена",
        "hl_v2280": "Сворачиваемый список изменений в «О программе» (4 последних, остальные — по клику)",
        "hl_v2270": "Мягкая светлая тема в сланцевых тонах, чёткие переключатели и яркие акценты Windows",
        "hl_v2260": "Сборка --onedir (мгновенный запуск без распаковки в %TEMP%) и автообновление .zip",
        "hl_v2250": "Ускоренный запуск, оценка ёмкости/здоровья батареи и проверка действий (телеметрия)",
        "hl_v2240": "Перетаскивание вкладок для смены порядка (сохраняется; ПКМ — сброс)",
        "hl_v2230": "Адаптивная вкладка «Управление»: скрывает HID++ DPI/опрос для других мышей",
        "hl_v2220": "Учёт энергопотребления частоты опроса (8/5/3/2 мВт) в прогнозе заряда",
        "hl_v2210": "Раздельная история заряда по мышам, фильтр клавиатур и скрытие устройств (✕)",
        "hl_v2200": "Улучшена светлая тема: чёткие переключатели, контрастные карточки и кнопки",
        "hl_v2190": "Синхронизация акцентного цвета с Windows и авто-контрастом WCAG AA",
        "hl_v2180": "Универсальный поиск мышей (Bluetooth/BLE, HID++, USB HID) и меню выбора мыши",
        "hl_v2170": "Улучшенный контраст светлой/тёмной тем (WCAG AA) и светлая рамка окна Win11",
        "hl_v2160": "Добавлены 4 пасхалки (Тир на реакцию, код Конами, спин индикатора, тема Matrix)",
        "hl_v2150": "Плавный переход между тёмной и светлой темой",
        "hl_v2140": "Кнопка «Доступно обновление» внизу с подсказкой изменений при наведении",
        "hl_v2130": "Динамические метки времени на графике заряда и изменение размера окна",
        "hl_v2120": "Кнопка «Обучение» на Главной открывает сводку «Изучено на данный момент»",
        "hl_v2110": "Добавлен переключатель языка English / Русский во всём интерфейсе",
        "hl_v2100": "Зум графика заряда (Ctrl + Колёсико) и кнопка сброса",
        "hl_v295": "Убраны примерные значения мВт; только реальные данные с мыши",
        "hl_v294": "Быстрый опрос DPI (150 мс) и синхронизация стадий (0x8100)",
        "highlights_show_more": "▸ Показать ранние версии ({count})",
        "highlights_show_less": "▾ Скрыть ранние версии",

        # Learned So Far dialog
        "learned_title": "Изучено на данный момент",
        "learned_calibrated_badge": "Откалибровано",
        "learned_progress_fmt": "Разряд: {drop}% / 80% (калибровка {pct}%)",
        "learned_calibrated_fmt": "Всего разряжено: {drop}% • Откалибровано",
        "learned_active_rate": "Текущий расход",
        "learned_rate_learned_fmt": "{rate:.1f}%/ч (по {n} сесс.)",
        "learned_rate_default_fmt": "{rate:.1f}%/ч (по умолч. — мало данных)",
        "learned_samples": "Записано замеров",
        "learned_samples_fmt": "{n} замеров (с {since})",
        "learned_none_yet": "Пока нет",
        "learned_measured_time": "Измеренный разряд",
        "learned_measured_fmt": "{dur} за {n} сесс.",
        "learned_observed_range": "Диапазон расхода",
        "learned_not_enough": "Пока недостаточно данных",
        "learned_weekday_weekend": "Будни / Выходные",
        "learned_no_data": "Нет данных",
        "unit_pct_hr": "%/ч",
        "learned_tod_title": "По времени суток",
        "tod_night": "Ночь",
        "tod_morning": "Утро",
        "tod_afternoon": "День",
        "tod_evening": "Вечер",
        "learned_recent_title": "Недавние сессии разряда",
        "learned_no_sessions_msg": "Подходящих сессий разряда пока нет. Сессия учитывается после ≥15 мин и снижения ≥1% без зарядки.",
        "health_card_title": "Ёмкость и здоровье батареи",
        "health_advertised": "Заявленная ёмкость",
        "health_cycles": "Записано циклов разряда",
        "health_est_cap": "Оценка реальной ёмкости",
        "health_est_pct": "Оценка здоровья",
        "health_calibrating_fmt": "Калибровка ({cur:.1f} / 2.0 акт. циклов)",
        "health_cycles_fmt": "{cycles:.2f} циклов",
        "health_adv_fmt": "{mah} мА·ч (~{mwh:.0f} мВт·ч)",
        "health_est_fmt": "~{mah} мА·ч (~{mwh:.0f} мВт·ч)",
        "health_unavail": "Недоступно (нет модели мощности)",

        # Easter Eggs
        "ee_konami_toast": "🧀 Код Конами! Мышь поймала сыр!",
        "ee_gauge_toast": "⚡ Хорошая попытка — всё ещё {pct}%! (+0% разгона)",
        "ee_matrix_unlocked": "🟩 Режим Matrix разблокирован! Добро пожаловать в терминал.",
        "ee_version_countdown": "Секретная игра через {left} нажатий...",
        "ee_aim_title": "Секретный тренажёр реакции",
        "ee_aim_sub": "Кликайте по мишеням как можно быстрее за 15 секунд!",
        "ee_aim_start": "Старт (15с)",
        "ee_aim_again": "Ещё раз",
        "ee_aim_hits": "Попадания",
        "ee_aim_avg": "Реакция",
        "ee_aim_best": "Рекорд",
        "ee_aim_done": "Время вышло! {hits} попад. • {hps:.2f}/с • Ср. {avg} мс",
        "ee_aim_done_zero": "Время вышло! 0 попаданий — попробуйте ещё раз!",
    },
}


def tr(lang: str, key: str, /, **kwargs: Any) -> str:
    """Look up localized string for `lang` ('en'|'ru'), falling back to English and formatting kwargs."""
    table = STRINGS.get(lang, STRINGS["en"])
    text = table.get(key)
    if text is None:
        text = STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
