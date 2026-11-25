use std::collections::HashMap;
use std::env;
use std::ffi::{c_void, CStr, CString};
use std::fs::{self, File};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::ptr::{null, null_mut};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::config::{
    atomic_write_text, exe_dir, history_path, AlertStateEntry, AlertStateMap, AppConfig,
};
use crate::hidpp::scan_hidpp_batteries;
use crate::json::{parse_json, JsonVal};
use crate::mouse::to_wide;

pub const SYSTEM_BASE_MW: f64 = 6.0;
pub const BATTERY_CAPACITY_MWH: f64 = 1900.0;
pub const NOMINAL_CELL_VOLTAGE: f64 = 3.8;

const CREATE_NO_WINDOW: u32 = 0x08000000;

#[link(name = "kernel32")]
extern "system" {
    fn LoadLibraryW(name: *const u16) -> *mut c_void;
    fn GetProcAddress(hm: *mut c_void, proc_name: *const u8) -> *const c_void;
    fn FreeLibrary(hm: *mut c_void) -> i32;
}

pub fn now_epoch_secs() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

pub fn parse_iso_timestamp(iso: &str) -> f64 {
    if iso.len() < 19 {
        return 0.0;
    }
    let b = iso.as_bytes();
    if b.get(4) != Some(&b'-') || b.get(7) != Some(&b'-') {
        return 0.0;
    }
    let p = |a: usize, c: usize| -> Option<i64> { iso.get(a..c)?.parse::<i64>().ok() };
    let (Some(y), Some(m), Some(d), Some(hh), Some(mm), Some(ss)) =
        (p(0, 4), p(5, 7), p(8, 10), p(11, 13), p(14, 16), p(17, 19))
    else {
        return 0.0;
    };
    let y_adj = y - if m <= 2 { 1 } else { 0 };
    let era = y_adj.div_euclid(400);
    let yoe = y_adj.rem_euclid(400);
    let m_adj = m + if m > 2 { -3 } else { 9 };
    let doy = (153 * m_adj + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146097 + doe - 719468;
    (days * 86400 + hh * 3600 + mm * 60 + ss) as f64
}

pub fn epoch_to_ymd_hms(epoch_secs: f64) -> (i64, u32, u32, u32, u32, u32) {
    let total = epoch_secs.floor() as i64;
    let days = total.div_euclid(86400);
    let rem = total.rem_euclid(86400) as u32;
    let hh = rem / 3600;
    let mm = (rem % 3600) / 60;
    let ss = rem % 60;

    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let mut y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (mp + if mp < 10 { 3 } else { -9 }) as u32;
    if m <= 2 {
        y += 1;
    }
    (y, m, d, hh, mm, ss)
}

pub fn format_iso_utc(epoch_secs: f64) -> String {
    let (y, m, d, hh, mm, ss) = epoch_to_ymd_hms(epoch_secs);
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}+00:00", y, m, d, hh, mm, ss)
}

pub fn parse_report_rate_hz(raw: &str) -> i32 {
    let digits: String = raw.chars().filter(|c| c.is_ascii_digit()).collect();
    let num = digits.parse::<i32>().unwrap_or(1000);
    [1000, 500, 250, 125]
        .into_iter()
        .min_by_key(|&hz| (hz - num).abs())
        .unwrap_or(1000)
}

pub fn estimate_power_mw(hz: i32) -> (f64, f64, f64) {
    let rate_mw = match parse_report_rate_hz(&hz.to_string()) {
        500 => 5.0,
        250 => 3.0,
        125 => 2.0,
        _ => 8.0,
    };
    (SYSTEM_BASE_MW + rate_mw, SYSTEM_BASE_MW, rate_mw)
}

pub fn report_rate_baseline_drain(hz: i32) -> f64 {
    let (tot, _, _) = estimate_power_mw(hz);
    ((tot / BATTERY_CAPACITY_MWH) * 100.0 * 100.0).round() / 100.0
}

pub fn format_device_name(slug: &str) -> String {
    let s: String = slug
        .chars()
        .map(|c| if c == '-' || c == '_' { ' ' } else { c.to_ascii_uppercase() })
        .collect();
    if s.trim().is_empty() {
        "WIRELESS MOUSE".to_string()
    } else {
        s
    }
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct DeviceBattery {
    pub device: String,
    pub display_name: String,
    pub percentage: Option<f64>,
    pub is_charging: bool,
    pub source: String,
    pub connection: String,
    pub vendor_id: u16,
    pub product_id: u16,
}

type SqliteOpenV2 = unsafe extern "C" fn(*const i8, *mut *mut c_void, i32, *const i8) -> i32;
type SqlitePrepareV2 = unsafe extern "C" fn(*mut c_void, *const i8, i32, *mut *mut c_void, *mut *const i8) -> i32;
type SqliteStep = unsafe extern "C" fn(*mut c_void) -> i32;
type SqliteColumnText = unsafe extern "C" fn(*mut c_void, i32) -> *const i8;
type SqliteFinalize = unsafe extern "C" fn(*mut c_void) -> i32;
type SqliteClose = unsafe extern "C" fn(*mut c_void) -> i32;

fn query_settings_db(hsql: *mut c_void, db_path: &Path) -> Option<String> {
    unsafe {
        let open: SqliteOpenV2 = std::mem::transmute(GetProcAddress(hsql, b"sqlite3_open_v2\0".as_ptr()));
        let prep: SqlitePrepareV2 = std::mem::transmute(GetProcAddress(hsql, b"sqlite3_prepare_v2\0".as_ptr()));
        let step: SqliteStep = std::mem::transmute(GetProcAddress(hsql, b"sqlite3_step\0".as_ptr()));
        let col: SqliteColumnText = std::mem::transmute(GetProcAddress(hsql, b"sqlite3_column_text\0".as_ptr()));
        let fin: SqliteFinalize = std::mem::transmute(GetProcAddress(hsql, b"sqlite3_finalize\0".as_ptr()));
        let close: SqliteClose = std::mem::transmute(GetProcAddress(hsql, b"sqlite3_close\0".as_ptr()));

        let c_path = CString::new(db_path.to_string_lossy().as_bytes()).ok()?;
        let mut db: *mut c_void = null_mut();
        if open(c_path.as_ptr(), &mut db, 1, null()) != 0 || db.is_null() {
            if !db.is_null() {
                close(db);
            }
            return None;
        }
        let mut stmt: *mut c_void = null_mut();
        let sql = b"SELECT file FROM data ORDER BY _id DESC LIMIT 1\0";
        let mut out = None;
        if prep(db, sql.as_ptr() as *const i8, -1, &mut stmt, null_mut()) == 0 && !stmt.is_null() {
            if step(stmt) == 100 {
                let txt = col(stmt, 0);
                if !txt.is_null() {
                    let s = CStr::from_ptr(txt).to_string_lossy().into_owned();
                    if !s.is_empty() {
                        out = Some(s);
                    }
                }
            }
            fin(stmt);
        }
        close(db);
        out
    }
}

pub fn read_lghub_batteries() -> Vec<DeviceBattery> {
    let mut devs = Vec::new();
    let Ok(la) = env::var("LOCALAPPDATA") else {
        return devs;
    };
    let db_path = PathBuf::from(la).join("LGHUB").join("settings.db");
    if !db_path.is_file() {
        return devs;
    }

    let wsql = to_wide("winsqlite3.dll");
    let hsql = unsafe { LoadLibraryW(wsql.as_ptr()) };
    if hsql.is_null() {
        return devs;
    }

    let mut raw_json = query_settings_db(hsql, &db_path);
    if raw_json.is_none() {
        let tmp_dir = env::temp_dir().join("mbc_v3_lghub");
        let _ = fs::create_dir_all(&tmp_dir);
        let copy_db = tmp_dir.join("settings.db");
        let _ = fs::copy(&db_path, &copy_db);
        for sfx in ["-wal", "-shm"] {
            let s = PathBuf::from(format!("{}{}", db_path.display(), sfx));
            let d = PathBuf::from(format!("{}{}", copy_db.display(), sfx));
            if s.is_file() {
                let _ = fs::copy(s, d);
            }
        }
        raw_json = query_settings_db(hsql, &copy_db);
    }
    unsafe { FreeLibrary(hsql); }

    let Some(json_str) = raw_json else {
        return devs;
    };
    let Ok(JsonVal::Obj(entries)) = parse_json(&json_str) else {
        return devs;
    };
    for (k, v) in entries {
        if let Some(slug) = k.strip_prefix("battery/").and_then(|s| s.strip_suffix("/percentage")) {
            if let Some(pct) = v.get("percentage").and_then(|x| x.as_f64()) {
                let chg = v.get("isCharging").and_then(|x| x.as_bool()).unwrap_or(false);
                devs.push(DeviceBattery {
                    device: slug.to_string(),
                    display_name: format_device_name(slug),
                    percentage: Some(pct.clamp(0.0, 100.0)),
                    is_charging: chg,
                    source: "lghub".to_string(),
                    connection: "lightspeed".to_string(),
                    vendor_id: 0x046D,
                    product_id: 0,
                });
            }
        }
    }
    devs
}

fn norm_alnum(s: &str) -> String {
    s.chars().filter(|c| c.is_ascii_alphanumeric()).map(|c| c.to_ascii_lowercase()).collect()
}

fn is_same_mouse(a: &DeviceBattery, b: &DeviceBattery) -> bool {
    let sa = norm_alnum(&a.device);
    let sb = norm_alnum(&b.device);
    let na = norm_alnum(&a.display_name);
    let nb = norm_alnum(&b.display_name);
    if !sa.is_empty() && sa == sb {
        return true;
    }
    if !na.is_empty() && !nb.is_empty() && (na == nb || (na.len() >= 5 && nb.contains(&na)) || (nb.len() >= 5 && na.contains(&nb))) {
        return true;
    }
    false
}

pub fn read_all_mouse_batteries() -> Vec<DeviceBattery> {
    let mut merged = read_lghub_batteries();
    for hr in scan_hidpp_batteries() {
        let cand = DeviceBattery {
            device: hr.slug,
            display_name: hr.display_name,
            percentage: Some(hr.pct),
            is_charging: hr.is_charging,
            source: "hidpp".to_string(),
            connection: hr.connection,
            vendor_id: 0x046D,
            product_id: hr.product_id,
        };
        if let Some(ex) = merged.iter_mut().find(|e| is_same_mouse(e, &cand)) {
            if ex.percentage.is_none() && cand.percentage.is_some() {
                ex.percentage = cand.percentage;
                ex.is_charging = cand.is_charging;
            }
            if ex.product_id == 0 {
                ex.product_id = cand.product_id;
            }
        } else {
            merged.push(cand);
        }
    }
    merged
}

#[derive(Clone, Debug)]
pub struct HistoryRec {
    pub ts: String,
    pub ts_sec: f64,
    pub device: String,
    pub pct: f64,
    pub charging: bool,
    pub rate_hz: Option<i32>,
    pub active_s: Option<f64>,
}

pub fn ensure_history_seeded() -> PathBuf {
    let hp = history_path();
    if !hp.is_file() {
        let fallback = exe_dir().join("..").join("history.jsonl");
        if fallback.is_file() {
            let _ = fs::copy(fallback, &hp);
        }
    }
    hp
}

pub fn load_history(max_days: i32) -> Vec<HistoryRec> {
    let hp = ensure_history_seeded();
    let Ok(file) = File::open(hp) else {
        return Vec::new();
    };
    let cutoff = now_epoch_secs() - (max_days.max(1) as f64) * 86400.0;
    let mut out = Vec::new();
    for line in BufReader::new(file).lines().map_while(Result::ok) {
        let t = line.trim();
        if t.is_empty() {
            continue;
        }
        let Ok(v) = parse_json(t) else {
            continue;
        };
        let Some(ts) = v.get("ts").and_then(|x| x.as_str()) else { continue; };
        let Some(dev) = v.get("device").and_then(|x| x.as_str()) else { continue; };
        let Some(pct) = v.get("pct").and_then(|x| x.as_f64()) else { continue; };
        let ts_sec = parse_iso_timestamp(ts);
        if ts_sec <= 0.0 || ts_sec < cutoff {
            continue;
        }
        let chg = v.get("charging").and_then(|x| x.as_bool()).unwrap_or(false);
        let rate_hz = v.get("rate_hz").and_then(|x| x.as_i64()).map(|n| n as i32);
        let active_s = v.get("active_s").and_then(|x| x.as_f64());
        out.push(HistoryRec {
            ts: ts.to_string(),
            ts_sec,
            device: dev.to_string(),
            pct,
            charging: chg,
            rate_hz,
            active_s,
        });
    }
    out.sort_by(|a, b| a.ts.cmp(&b.ts));
    out
}

pub fn append_history_with_status(
    device: &DeviceBattery,
    history: &mut Vec<HistoryRec>,
    max_days: i32,
    rate_hz: i32,
    active_seconds: f64,
) -> bool {
    let Some(pct) = device.percentage else {
        return false;
    };
    let now_s = now_epoch_secs();
    if let Some(last) = history.iter().rev().find(|h| h.device == device.device) {
        if (now_s - last.ts_sec) < 240.0
            && (last.pct - pct).abs() < 0.01
            && last.charging == device.is_charging
        {
            return false;
        }
    }
    history.push(HistoryRec {
        ts: format_iso_utc(now_s),
        ts_sec: now_s,
        device: device.device.clone(),
        pct: (pct * 10.0).round() / 10.0,
        charging: device.is_charging,
        rate_hz: Some(parse_report_rate_hz(&rate_hz.to_string())),
        active_s: if active_seconds > 0.0 {
            Some((active_seconds * 10.0).round() / 10.0)
        } else {
            None
        },
    });
    let cutoff = now_s - (max_days.max(1) as f64) * 86400.0;
    history.retain(|h| h.ts_sec >= cutoff);

    let mut payload = String::new();
    for h in history.iter() {
        let mut entries = vec![
            ("ts".into(), JsonVal::Str(h.ts.clone())),
            ("device".into(), JsonVal::Str(h.device.clone())),
            ("pct".into(), JsonVal::Num(h.pct)),
            ("charging".into(), JsonVal::Bool(h.charging)),
        ];
        if let Some(hz) = h.rate_hz {
            entries.push(("rate_hz".into(), JsonVal::Num(hz as f64)));
        }
        if let Some(a) = h.active_s {
            if a > 0.0 {
                entries.push(("active_s".into(), JsonVal::Num(a)));
            }
        }
        payload.push_str(&JsonVal::Obj(entries).to_compact_string());
        payload.push('\n');
    }
    atomic_write_text(&history_path(), &payload).is_ok()
}

pub fn compute_total_discharge(samples: &[&HistoryRec]) -> f64 {
    let mut total = 0.0;
    for w in samples.windows(2) {
        let (prev, cur) = (w[0], w[1]);
        if !cur.charging && !prev.charging {
            let drop = prev.pct - cur.pct;
            if drop > 0.0 && drop <= 25.0 {
                total += drop;
            }
        }
    }
    total
}

#[derive(Clone, Debug)]
pub struct DischargeSession {
    pub t1_sec: f64,
    pub end_label: String,
    pub duration_h: f64,
    pub start_pct: i32,
    pub end_pct: i32,
    pub rate: f64,
    pub rate_hz: i32,
}

pub fn extract_discharge_sessions(samples: &[&HistoryRec]) -> Vec<DischargeSession> {
    let mut segs: Vec<Vec<&HistoryRec>> = Vec::new();
    let mut cur: Vec<&HistoryRec> = Vec::new();

    for &s in samples {
        if s.charging {
            if !cur.is_empty() {
                segs.push(cur);
                cur = Vec::new();
            }
            continue;
        }
        if let Some(&prev) = cur.last() {
            let dt_h = (s.ts_sec - prev.ts_sec) / 3600.0;
            if dt_h > 6.0 || s.pct > prev.pct + 1.0 {
                segs.push(cur);
                cur = vec![s];
            } else {
                cur.push(s);
            }
        } else {
            cur.push(s);
        }
    }
    if !cur.is_empty() {
        segs.push(cur);
    }

    let mut valid = Vec::new();
    for seg in segs {
        if seg.len() < 2 {
            continue;
        }
        let first = seg[0];
        let last = seg[seg.len() - 1];
        let duration_h = (last.ts_sec - first.ts_sec) / 3600.0;
        let drop = first.pct - last.pct;
        if duration_h < 0.25 || drop < 1.0 {
            continue;
        }
        let rate = drop / duration_h;
        if !(0.1..=25.0).contains(&rate) {
            continue;
        }
        let (_, m, d, hh, mm, _) = epoch_to_ymd_hms(last.ts_sec);
        valid.push(DischargeSession {
            t1_sec: last.ts_sec,
            end_label: format!("{:02}-{:02} {:02}:{:02}", m, d, hh, mm),
            duration_h,
            start_pct: first.pct.round() as i32,
            end_pct: last.pct.round() as i32,
            rate,
            rate_hz: last.rate_hz.unwrap_or(1000),
        });
    }
    valid
}

pub fn estimate_drain_rate(
    slug: &str,
    history: &[HistoryRec],
    default_rate: f64,
    current_rate_hz: Option<i32>,
) -> (f64, bool, usize) {
    let mut samples: Vec<&HistoryRec> = history.iter().filter(|h| h.device == slug).collect();
    samples.sort_by(|a, b| a.ts.cmp(&b.ts));
    let valid = extract_discharge_sessions(&samples);
    if valid.is_empty() {
        if let Some(hz) = current_rate_hz {
            return (report_rate_baseline_drain(hz), false, 0);
        }
        return (default_rate, false, 0);
    }

    let now_s = now_epoch_secs();
    let cur_total_mw = current_rate_hz.map(|hz| estimate_power_mw(hz).0);
    let mut w_sum = 0.0;
    let mut w_tot = 0.0;
    for s in &valid {
        let age_days = ((now_s - s.t1_sec) / 86400.0).max(0.0);
        let weight = (-age_days / 10.0).exp().max(1e-9) * s.duration_h.min(12.0);
        let mut r = s.rate;
        if let Some(ct) = cur_total_mw {
            let smw = estimate_power_mw(s.rate_hz).0;
            if smw > 0.0 {
                r *= ct / smw;
            }
        }
        w_sum += r * weight;
        w_tot += weight;
    }
    if w_tot <= 0.0 {
        return (default_rate, false, 0);
    }
    (((w_sum / w_tot) * 100.0).round() / 100.0, true, valid.len())
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct BatteryHealth {
    pub status: String,
    pub advertised_mah: i32,
    pub advertised_mwh: f64,
    pub charge_cycles: f64,
    pub active_cycles: f64,
    pub est_capacity_mah: Option<i32>,
    pub est_capacity_mwh: Option<i32>,
    pub health_pct: Option<i32>,
}

pub fn compute_battery_health(slug: &str, history: &[HistoryRec], adv_mah: i32, is_logitech: bool) -> BatteryHealth {
    let mut samples: Vec<&HistoryRec> = history.iter().filter(|h| h.device == slug).collect();
    samples.sort_by(|a, b| a.ts.cmp(&b.ts));
    let total_drop = compute_total_discharge(&samples);
    let adv_clamped = adv_mah.max(50);
    let adv_mwh = (adv_clamped as f64) * NOMINAL_CELL_VOLTAGE;

    let mut active_drop_pct = 0.0;
    let mut active_energy_mwh = 0.0;
    let mut pending_mwh = 0.0;
    let mut has_active = false;

    for w in samples.windows(2) {
        let (prev, cur) = (w[0], w[1]);
        if cur.charging || prev.charging {
            pending_mwh = 0.0;
            has_active = false;
            continue;
        }
        let dt_h = (cur.ts_sec - prev.ts_sec) / 3600.0;
        let drop = prev.pct - cur.pct;
        if dt_h > 6.0 || drop < -1.0 || drop > 25.0 {
            pending_mwh = 0.0;
            has_active = false;
            continue;
        }
        if let Some(a_s) = cur.active_s {
            if a_s > 0.0 {
                let total_mw = estimate_power_mw(cur.rate_hz.unwrap_or(1000)).0;
                pending_mwh += (a_s / 3600.0) * total_mw;
                has_active = true;
            }
        }
        if drop > 0.0 && has_active && pending_mwh > 0.0 {
            active_drop_pct += drop;
            active_energy_mwh += pending_mwh;
            pending_mwh = 0.0;
            has_active = false;
        }
    }

    let charge_cycles = (total_drop / 100.0 * 100.0).round() / 100.0;
    let active_cycles = (active_drop_pct / 100.0 * 100.0).round() / 100.0;
    if is_logitech && active_drop_pct >= 200.0 && active_energy_mwh > 0.0 {
        let est_mwh = active_energy_mwh / (active_drop_pct / 100.0);
        let est_mah = (est_mwh / NOMINAL_CELL_VOLTAGE).round() as i32;
        let hpct = ((est_mwh / adv_mwh) * 100.0).round().clamp(1.0, 100.0) as i32;
        BatteryHealth {
            status: "estimated".into(),
            advertised_mah: adv_clamped,
            advertised_mwh: adv_mwh,
            charge_cycles,
            active_cycles,
            est_capacity_mah: Some(est_mah),
            est_capacity_mwh: Some(est_mwh.round() as i32),
            health_pct: Some(hpct),
        }
    } else {
        BatteryHealth {
            status: if is_logitech { "calibrating" } else { "unavailable" }.into(),
            advertised_mah: adv_clamped,
            advertised_mwh: adv_mwh,
            charge_cycles,
            active_cycles,
            est_capacity_mah: None,
            est_capacity_mwh: None,
            health_pct: None,
        }
    }
}

pub fn format_duration(hours: f64) -> String {
    if hours <= 0.0 {
        return "< 5m".into();
    }
    let total_m = (hours * 60.0).round() as i64;
    let h = total_m / 60;
    let m = total_m % 60;
    if h >= 24 {
        format!("{}h", h)
    } else if h > 0 {
        format!("{}h {}m", h, m)
    } else {
        format!("{}m", m)
    }
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

pub fn send_windows_toast(title: &str, line1: &str, line2: &str, sound: &str) -> bool {
    let audio_xml = match sound {
        "Silent" => "<audio silent='true'/>".to_string(),
        "Reminder" => "<audio src='ms-winsoundevent:Notification.Reminder'/>".to_string(),
        "Alarm" => "<audio src='ms-winsoundevent:Notification.Looping.Alarm'/>".to_string(),
        "Chime" => "<audio src='ms-winsoundevent:Notification.IM'/>".to_string(),
        "Mail" => "<audio src='ms-winsoundevent:Notification.Mail'/>".to_string(),
        _ => "<audio src='ms-winsoundevent:Notification.Default'/>".to_string(),
    };

    let toast_xml = format!(
        "<toast><visual><binding template='ToastGeneric'><text>{}</text><text>{}</text><text>{}</text></binding></visual>{}</toast>",
        xml_escape(title),
        xml_escape(line1),
        xml_escape(line2),
        audio_xml
    );

    let ps = format!(
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n\
         [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n\
         $xml = New-Object Windows.Data.Xml.Dom.XmlDocument\n\
         $xml.LoadXml(@'\n{}\n'@)\n\
         $toast = New-Object Windows.UI.Notifications.ToastNotification $xml\n\
         $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Microsoft.Windows.Explorer')\n\
         $notifier.Show($toast)",
        toast_xml
    );

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        Command::new("powershell.exe")
            .args(["-NoProfile", "-WindowStyle", "Hidden", "-Command", &ps])
            .creation_flags(CREATE_NO_WINDOW)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|st| st.success())
            .unwrap_or(false)
    }
}

#[allow(dead_code)]
pub struct EvalResult {
    pub hours_left: f64,
    pub time_left_str: String,
    pub drain_rate: f64,
    pub is_learned: bool,
    pub sessions_used: usize,
    pub total_discharge_pct: i32,
    pub est_power_mw: Option<(f64, f64, f64, i32)>,
    pub evening_status: String, // "charging" | "wont_last" | "will_last"
    pub reason: Option<String>,
    pub notified: bool,
    pub health: BatteryHealth,
    pub recent_sessions: Vec<DischargeSession>,
}

pub fn evaluate_device(
    dev: &DeviceBattery,
    cfg: &AppConfig,
    history: &[HistoryRec],
    state: &mut AlertStateMap,
    live_rate_hz: Option<i32>,
    send_alerts: bool,
) -> EvalResult {
    let eff_hz = if let Some(hz) = live_rate_hz {
        Some(parse_report_rate_hz(&hz.to_string()))
    } else if dev.source == "lghub" || dev.source == "hidpp" {
        Some(parse_report_rate_hz(&cfg.report_rate))
    } else {
        None
    };

    let (drain_rate, is_learned, sessions_used) = estimate_drain_rate(
        &dev.device,
        history,
        cfg.default_drain_rate_pct_per_hour,
        eff_hz,
    );
    let mut samples: Vec<&HistoryRec> = history.iter().filter(|h| h.device == dev.device).collect();
    samples.sort_by(|a, b| a.ts.cmp(&b.ts));
    let total_drop = compute_total_discharge(&samples).round() as i32;
    let is_logi = dev.vendor_id == 0x046D || dev.source == "lghub" || dev.source == "hidpp";
    let health = compute_battery_health(&dev.device, history, cfg.advertised_capacity_mah, is_logi);
    let mut recent_sessions = extract_discharge_sessions(&samples);
    if recent_sessions.len() > 5 {
        recent_sessions = recent_sessions.split_off(recent_sessions.len() - 5);
    }
    recent_sessions.reverse();

    let pct = dev.percentage.unwrap_or(0.0);
    let usable = (pct - cfg.reserve_battery_pct).max(0.0);
    let hours_left = if drain_rate > 0.0 { usable / drain_rate } else { 999.0 };
    let time_left_str = if dev.percentage.is_some() {
        format_duration(hours_left)
    } else {
        "Unknown".into()
    };

    let reason = if dev.percentage.is_some() && !dev.is_charging {
        if pct <= cfg.critical_battery_threshold {
            Some("critical".to_string())
        } else if pct <= cfg.low_battery_threshold {
            Some("low".to_string())
        } else {
            None
        }
    } else {
        None
    };

    // Approximate evening forecast using local UTC offset heuristic or simple hours remaining
    let evening_status = if dev.is_charging {
        "charging".to_string()
    } else if hours_left < 4.0 && reason.is_some() {
        "wont_last".to_string()
    } else {
        "will_last".to_string()
    };

    let mut notified = false;
    if send_alerts && cfg.notifications_enabled {
        if let Some(ref rsn) = reason {
            let now_s = now_epoch_secs();
            let mut allow = true;
            if let Some((_, prev)) = state.iter().find(|(d, _)| d == &dev.device) {
                let cd_sec = (if rsn == "critical" {
                    cfg.critical_cooldown_minutes
                } else {
                    cfg.cooldown_minutes
                }) as f64
                    * 60.0;
                if !(rsn == "critical" && prev.last_reason != "critical") && (now_s - prev.last_notified_ts) < cd_sec {
                    allow = false;
                }
            }
            if allow {
                let title = if rsn == "critical" {
                    format!("Critical Mouse Battery: {}%", pct.round() as i32)
                } else {
                    format!("Low Mouse Battery: {}%", pct.round() as i32)
                };
                let line1 = format!("{}: ~{} left", dev.display_name, time_left_str);
                let line2 = format!("Usage rate: {:.1}%/hr ({})", drain_rate, if is_learned { "learned" } else { "est." });
                if send_windows_toast(&title, &line1, &line2, &cfg.notification_sound) {
                    notified = true;
                    let entry = AlertStateEntry {
                        last_notified_ts: now_s,
                        last_reason: rsn.clone(),
                        last_pct: pct,
                    };
                    if let Some(pos) = state.iter().position(|(d, _)| d == &dev.device) {
                        state[pos].1 = entry;
                    } else {
                        state.push((dev.device.clone(), entry));
                    }
                }
            }
        }
    }

    let power = eff_hz.map(|hz| {
        let (t, s, r) = estimate_power_mw(hz);
        (t, s, r, hz)
    });

    let _ = HashMap::<String, ()>::new();
    EvalResult {
        hours_left,
        time_left_str,
        drain_rate,
        is_learned,
        sessions_used,
        total_discharge_pct: total_drop,
        est_power_mw: power,
        evening_status,
        reason,
        notified,
        health,
        recent_sessions,
    }
}
