use std::env;
use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use crate::json::{parse_json, JsonVal};

pub const DEFAULT_TAB_ORDER: [&str; 4] = ["Dashboard", "Notifications", "Mouse Control", "Sync & Backup"];
pub const VALID_THEMES: [&str; 4] = ["System", "Dark", "Light", "Matrix"];
pub const VALID_ACCENT_MODES: [&str; 2] = ["Windows", "Default"];
pub const VALID_LANGUAGES: [&str; 2] = ["en", "ru"];
pub const VALID_ACCEL_MODES: [&str; 3] = ["Off", "On", "Auto"];
pub const VALID_SOUNDS: [&str; 6] = ["Default", "Reminder", "Alarm", "Chime", "Mail", "Silent"];

const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
const MOVEFILE_WRITE_THROUGH: u32 = 0x8;

#[link(name = "kernel32")]
extern "system" {
    fn MoveFileExW(existing: *const u16, new: *const u16, flags: u32) -> i32;
    fn GetCurrentProcessId() -> u32;
}

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

pub fn exe_dir() -> PathBuf {
    env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn config_path() -> PathBuf {
    exe_dir().join("config.json")
}

pub fn state_path() -> PathBuf {
    exe_dir().join("state.json")
}

pub fn history_path() -> PathBuf {
    exe_dir().join("history.jsonl")
}

pub fn atomic_write_text(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir failed: {}", e))?;
    }
    let pid = unsafe { GetCurrentProcessId() };
    let fname = path.file_name().and_then(|n| n.to_str()).unwrap_or("data");
    let tmp = path.with_file_name(format!(".{}.{}.tmp", fname, pid));

    {
        let mut f = File::create(&tmp).map_err(|e| format!("create temp failed: {}", e))?;
        f.write_all(content.as_bytes()).map_err(|e| format!("write temp failed: {}", e))?;
        let _ = f.sync_all();
    }

    let src_w = to_wide(&tmp.to_string_lossy());
    let dst_w = to_wide(&path.to_string_lossy());
    for attempt in 0..5 {
        let ok = unsafe {
            MoveFileExW(
                src_w.as_ptr(),
                dst_w.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        };
        if ok != 0 {
            return Ok(());
        }
        if attempt < 4 {
            thread::sleep(Duration::from_millis(45));
        }
    }
    let _ = fs::remove_file(&tmp);
    Err("atomic rename failed after 5 attempts".to_string())
}

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub device_filter: Option<String>,
    pub hidden_devices: Vec<String>,
    pub tab_order: Vec<String>,
    pub notifications_enabled: bool,
    pub poll_interval_minutes: i32,
    pub evening_hour: i32,
    pub low_battery_threshold: f64,
    pub critical_battery_threshold: f64,
    pub reserve_battery_pct: f64,
    pub cooldown_minutes: i32,
    pub critical_cooldown_minutes: i32,
    pub default_drain_rate_pct_per_hour: f64,
    pub max_history_days: i32,
    pub notification_sound: String,
    pub close_to_tray: bool,
    pub theme: String,
    pub accent_mode: String,
    pub complementary_accent: bool,
    pub language: String,
    pub calibration_style: String,
    pub accel_mode: String,
    pub auto_games: Vec<String>,
    pub report_rate: String,
    pub advertised_capacity_mah: i32,
    pub update_source: Option<String>,
    pub auto_fetch_mouse_icons: bool,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            device_filter: None,
            hidden_devices: Vec::new(),
            tab_order: DEFAULT_TAB_ORDER.iter().map(|s| (*s).to_string()).collect(),
            notifications_enabled: true,
            poll_interval_minutes: 5,
            evening_hour: 22,
            low_battery_threshold: 20.0,
            critical_battery_threshold: 10.0,
            reserve_battery_pct: 5.0,
            cooldown_minutes: 60,
            critical_cooldown_minutes: 20,
            default_drain_rate_pct_per_hour: 1.5,
            max_history_days: 30,
            notification_sound: "Default".to_string(),
            close_to_tray: true,
            theme: "Dark".to_string(),
            accent_mode: "Windows".to_string(),
            complementary_accent: true,
            language: "en".to_string(),
            calibration_style: "Combo".to_string(),
            accel_mode: "Off".to_string(),
            auto_games: Vec::new(),
            report_rate: "1000 Hz".to_string(),
            advertised_capacity_mah: 500,
            update_source: Some("github:Aleksa75/mouse-battery-control".to_string()),
            auto_fetch_mouse_icons: false,
        }
    }
}

pub fn normalize_tab_order(order: &[String]) -> Vec<String> {
    let mut cleaned = Vec::new();
    for item in order {
        if DEFAULT_TAB_ORDER.contains(&item.as_str()) && !cleaned.contains(item) {
            cleaned.push(item.clone());
        }
    }
    for &def in &DEFAULT_TAB_ORDER {
        if !cleaned.iter().any(|x| x == def) {
            cleaned.push(def.to_string());
        }
    }
    cleaned
}

fn val_int_range(v: &JsonVal, name: &str, lo: i32, hi: i32, fb: i32, strict: bool) -> Result<i32, String> {
    let Some(iv) = v.as_i64() else {
        if strict {
            return Err(format!("{} must be an integer between {} and {}", name, lo, hi));
        }
        return Ok(fb);
    };
    if iv < lo as i64 || iv > hi as i64 {
        if strict {
            return Err(format!("{} must be between {} and {}", name, lo, hi));
        }
        return Ok(fb);
    }
    Ok(iv as i32)
}

fn val_num_range(v: &JsonVal, name: &str, lo: f64, hi: f64, fb: f64, strict: bool) -> Result<f64, String> {
    let Some(fv) = v.as_f64() else {
        if strict {
            return Err(format!("{} must be a number between {} and {}", name, lo, hi));
        }
        return Ok(fb);
    };
    if !fv.is_finite() || fv < lo || fv > hi {
        if strict {
            return Err(format!("{} must be between {} and {}", name, lo, hi));
        }
        return Ok(fb);
    }
    Ok(fv)
}

fn val_bool(v: &JsonVal, name: &str, fb: bool, strict: bool) -> Result<bool, String> {
    match v.as_bool() {
        Some(b) => Ok(b),
        None => {
            if strict {
                Err(format!("{} must be a boolean", name))
            } else {
                Ok(fb)
            }
        }
    }
}

fn val_enum(v: &JsonVal, name: &str, allowed: &[&str], fb: &str, strict: bool) -> Result<String, String> {
    match v.as_str() {
        Some(s) if allowed.contains(&s) => Ok(s.to_string()),
        _ => {
            if strict {
                Err(format!("{} must be one of {:?}", name, allowed))
            } else {
                Ok(fb.to_string())
            }
        }
    }
}

pub fn validate_config(raw: &JsonVal, base: &AppConfig, strict: bool) -> Result<AppConfig, String> {
    if raw.as_obj().is_none() {
        if strict {
            return Err("Configuration must be a JSON object.".to_string());
        }
        return Ok(base.clone());
    }
    let mut cfg = base.clone();

    if let Some(v) = raw.get("evening_hour") {
        cfg.evening_hour = val_int_range(v, "evening_hour", 0, 23, base.evening_hour, strict)?;
    }
    if let Some(v) = raw.get("poll_interval_minutes") {
        cfg.poll_interval_minutes = val_int_range(v, "poll_interval_minutes", 1, 1440, base.poll_interval_minutes, strict)?;
    }
    if let Some(v) = raw.get("cooldown_minutes") {
        cfg.cooldown_minutes = val_int_range(v, "cooldown_minutes", 1, 1440, base.cooldown_minutes, strict)?;
    }
    if let Some(v) = raw.get("critical_cooldown_minutes") {
        cfg.critical_cooldown_minutes = val_int_range(v, "critical_cooldown_minutes", 1, 1440, base.critical_cooldown_minutes, strict)?;
    }
    if let Some(v) = raw.get("max_history_days") {
        cfg.max_history_days = val_int_range(v, "max_history_days", 1, 365, base.max_history_days, strict)?;
    }
    if let Some(v) = raw.get("advertised_capacity_mah") {
        cfg.advertised_capacity_mah = val_int_range(v, "advertised_capacity_mah", 50, 10000, base.advertised_capacity_mah, strict)?;
    }
    if let Some(v) = raw.get("low_battery_threshold") {
        cfg.low_battery_threshold = val_num_range(v, "low_battery_threshold", 1.0, 100.0, base.low_battery_threshold, strict)?;
    }
    if let Some(v) = raw.get("critical_battery_threshold") {
        cfg.critical_battery_threshold = val_num_range(v, "critical_battery_threshold", 1.0, 100.0, base.critical_battery_threshold, strict)?;
    }
    if cfg.critical_battery_threshold > cfg.low_battery_threshold {
        if strict {
            return Err("critical_battery_threshold cannot exceed low_battery_threshold".to_string());
        }
        cfg.critical_battery_threshold = cfg.low_battery_threshold;
    }
    if let Some(v) = raw.get("reserve_battery_pct") {
        cfg.reserve_battery_pct = val_num_range(v, "reserve_battery_pct", 0.0, 50.0, base.reserve_battery_pct, strict)?;
    }
    if let Some(v) = raw.get("default_drain_rate_pct_per_hour") {
        cfg.default_drain_rate_pct_per_hour = val_num_range(v, "default_drain_rate_pct_per_hour", 0.05, 50.0, base.default_drain_rate_pct_per_hour, strict)?;
    }

    if let Some(v) = raw.get("notifications_enabled") {
        cfg.notifications_enabled = val_bool(v, "notifications_enabled", base.notifications_enabled, strict)?;
    }
    if let Some(v) = raw.get("close_to_tray") {
        cfg.close_to_tray = val_bool(v, "close_to_tray", base.close_to_tray, strict)?;
    }
    if let Some(v) = raw.get("auto_fetch_mouse_icons") {
        cfg.auto_fetch_mouse_icons = val_bool(v, "auto_fetch_mouse_icons", base.auto_fetch_mouse_icons, strict)?;
    }
    if let Some(v) = raw.get("complementary_accent") {
        cfg.complementary_accent = val_bool(v, "complementary_accent", base.complementary_accent, strict)?;
    }

    if let Some(v) = raw.get("notification_sound") {
        cfg.notification_sound = val_enum(v, "notification_sound", &VALID_SOUNDS, &base.notification_sound, strict)?;
    }
    if let Some(v) = raw.get("theme") {
        cfg.theme = val_enum(v, "theme", &VALID_THEMES, &base.theme, strict)?;
    }
    if let Some(v) = raw.get("accent_mode") {
        cfg.accent_mode = val_enum(v, "accent_mode", &VALID_ACCENT_MODES, &base.accent_mode, strict)?;
    }
    if let Some(v) = raw.get("language") {
        cfg.language = val_enum(v, "language", &VALID_LANGUAGES, &base.language, strict)?;
    }
    if let Some(v) = raw.get("accel_mode") {
        cfg.accel_mode = val_enum(v, "accel_mode", &VALID_ACCEL_MODES, &base.accel_mode, strict)?;
    }
    if let Some(v) = raw.get("calibration_style") {
        if let Some(s) = v.as_str() {
            cfg.calibration_style = s.to_string();
        }
    }

    if let Some(v) = raw.get("tab_order") {
        if let Some(arr) = v.as_arr() {
            let strs: Vec<String> = arr.iter().filter_map(|x| x.as_str().map(str::to_string)).collect();
            if strict && strs.len() != arr.len() {
                return Err("tab_order must be a list of strings".to_string());
            }
            cfg.tab_order = normalize_tab_order(&strs);
        } else if strict {
            return Err("tab_order must be a list of strings".to_string());
        }
    }
    if let Some(v) = raw.get("hidden_devices") {
        if let Some(arr) = v.as_arr() {
            let strs: Vec<String> = arr.iter().filter_map(|x| x.as_str().map(str::to_string)).collect();
            if strict && strs.len() != arr.len() {
                return Err("hidden_devices must be a list of strings".to_string());
            }
            cfg.hidden_devices = strs;
        } else if strict {
            return Err("hidden_devices must be a list of strings".to_string());
        }
    }
    if let Some(v) = raw.get("auto_games") {
        if let Some(arr) = v.as_arr() {
            let strs: Vec<String> = arr.iter().filter_map(|x| x.as_str().map(str::to_string)).collect();
            if strict && strs.len() != arr.len() {
                return Err("auto_games must be a list of strings".to_string());
            }
            cfg.auto_games = strs;
        } else if strict {
            return Err("auto_games must be a list of strings".to_string());
        }
    }

    if let Some(v) = raw.get("device_filter") {
        match v {
            JsonVal::Null => cfg.device_filter = None,
            JsonVal::Str(s) => cfg.device_filter = Some(s.clone()),
            _ if strict => return Err("device_filter must be a string or null".to_string()),
            _ => {}
        }
    }
    if let Some(v) = raw.get("update_source") {
        match v {
            JsonVal::Null => cfg.update_source = None,
            JsonVal::Str(s) => cfg.update_source = Some(s.clone()),
            _ if strict => return Err("update_source must be a string or null".to_string()),
            _ => {}
        }
    }
    if let Some(v) = raw.get("report_rate") {
        match v {
            JsonVal::Num(n) if *n > 0.0 => cfg.report_rate = format!("{} Hz", n.round() as i32),
            JsonVal::Str(s) if s.chars().any(|c| c.is_ascii_digit()) => cfg.report_rate = s.clone(),
            _ if strict => return Err("report_rate must be a valid polling rate".to_string()),
            _ => {}
        }
    }

    Ok(cfg)
}

impl AppConfig {
    pub fn to_json_val(&self) -> JsonVal {
        let mut entries = Vec::new();
        entries.push((
            "device_filter".into(),
            self.device_filter.as_ref().map(|s| JsonVal::Str(s.clone())).unwrap_or(JsonVal::Null),
        ));
        entries.push((
            "hidden_devices".into(),
            JsonVal::Arr(self.hidden_devices.iter().map(|s| JsonVal::Str(s.clone())).collect()),
        ));
        entries.push((
            "tab_order".into(),
            JsonVal::Arr(self.tab_order.iter().map(|s| JsonVal::Str(s.clone())).collect()),
        ));
        entries.push(("notifications_enabled".into(), JsonVal::Bool(self.notifications_enabled)));
        entries.push(("poll_interval_minutes".into(), JsonVal::Num(self.poll_interval_minutes as f64)));
        entries.push(("evening_hour".into(), JsonVal::Num(self.evening_hour as f64)));
        entries.push(("low_battery_threshold".into(), JsonVal::Num(self.low_battery_threshold)));
        entries.push(("critical_battery_threshold".into(), JsonVal::Num(self.critical_battery_threshold)));
        entries.push(("reserve_battery_pct".into(), JsonVal::Num(self.reserve_battery_pct)));
        entries.push(("cooldown_minutes".into(), JsonVal::Num(self.cooldown_minutes as f64)));
        entries.push(("critical_cooldown_minutes".into(), JsonVal::Num(self.critical_cooldown_minutes as f64)));
        entries.push(("default_drain_rate_pct_per_hour".into(), JsonVal::Num(self.default_drain_rate_pct_per_hour)));
        entries.push(("max_history_days".into(), JsonVal::Num(self.max_history_days as f64)));
        entries.push(("notification_sound".into(), JsonVal::Str(self.notification_sound.clone())));
        entries.push(("close_to_tray".into(), JsonVal::Bool(self.close_to_tray)));
        entries.push(("theme".into(), JsonVal::Str(self.theme.clone())));
        entries.push(("accent_mode".into(), JsonVal::Str(self.accent_mode.clone())));
        entries.push(("complementary_accent".into(), JsonVal::Bool(self.complementary_accent)));
        entries.push(("language".into(), JsonVal::Str(self.language.clone())));
        entries.push(("calibration_style".into(), JsonVal::Str(self.calibration_style.clone())));
        entries.push(("accel_mode".into(), JsonVal::Str(self.accel_mode.clone())));
        entries.push((
            "auto_games".into(),
            JsonVal::Arr(self.auto_games.iter().map(|s| JsonVal::Str(s.clone())).collect()),
        ));
        entries.push(("report_rate".into(), JsonVal::Str(self.report_rate.clone())));
        entries.push(("advertised_capacity_mah".into(), JsonVal::Num(self.advertised_capacity_mah as f64)));
        entries.push((
            "update_source".into(),
            self.update_source.as_ref().map(|s| JsonVal::Str(s.clone())).unwrap_or(JsonVal::Null),
        ));
        entries.push(("auto_fetch_mouse_icons".into(), JsonVal::Bool(self.auto_fetch_mouse_icons)));
        JsonVal::Obj(entries)
    }
}

pub fn load_config() -> AppConfig {
    let p = config_path();
    let base = AppConfig::default();
    if let Ok(raw_text) = fs::read_to_string(&p) {
        if let Ok(parsed) = parse_json(&raw_text) {
            if let Ok(cfg) = validate_config(&parsed, &base, false) {
                return cfg;
            }
        }
    }
    base
}

pub fn save_config(cfg: &AppConfig) {
    let _ = atomic_write_text(&config_path(), &(cfg.to_json_val().to_pretty_string() + "\n"));
}

#[derive(Debug, Clone, Default)]
pub struct AlertStateEntry {
    pub last_notified_ts: f64,
    pub last_reason: String,
    pub last_pct: f64,
}

pub type AlertStateMap = Vec<(String, AlertStateEntry)>;

pub fn load_state() -> AlertStateMap {
    let mut map = Vec::new();
    let Ok(raw_text) = fs::read_to_string(state_path()) else {
        return map;
    };
    let Ok(JsonVal::Obj(entries)) = parse_json(&raw_text) else {
        return map;
    };
    for (dev, val) in entries {
        let ts_num = val
            .get("last_notified_epoch")
            .and_then(|v| v.as_f64())
            .or_else(|| {
                val.get("last_notified")
                    .and_then(|v| v.as_str())
                    .map(crate::monitor::parse_iso_timestamp)
            })
            .unwrap_or(0.0);
        let reason = val.get("last_reason").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let pct = val.get("last_pct").and_then(|v| v.as_f64()).unwrap_or(0.0);
        if ts_num > 0.0 {
            map.push((
                dev,
                AlertStateEntry {
                    last_notified_ts: ts_num,
                    last_reason: reason,
                    last_pct: pct,
                },
            ));
        }
    }
    map
}

pub fn save_state(map: &AlertStateMap) {
    let entries: Vec<(String, JsonVal)> = map
        .iter()
        .map(|(k, e)| {
            (
                k.clone(),
                JsonVal::Obj(vec![
                    ("last_notified".into(), JsonVal::Str(crate::monitor::format_iso_utc(e.last_notified_ts))),
                    ("last_notified_epoch".into(), JsonVal::Num(e.last_notified_ts)),
                    ("last_reason".into(), JsonVal::Str(e.last_reason.clone())),
                    ("last_pct".into(), JsonVal::Num(e.last_pct)),
                ]),
            )
        })
        .collect();
    let _ = atomic_write_text(&state_path(), &(JsonVal::Obj(entries).to_pretty_string() + "\n"));
}
