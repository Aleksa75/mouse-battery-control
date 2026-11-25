#![cfg_attr(not(test), windows_subsystem = "windows")]

mod config;
mod hidpp;
mod json;
mod monitor;
mod mouse;
mod updater;
mod wv2;

use std::cell::RefCell;
use std::collections::HashMap;
use std::env;
use std::ffi::c_void;
use std::fs;
use std::io::{self, Write};
use std::mem::{size_of, zeroed};
use std::path::PathBuf;
use std::ptr::{null, null_mut};
use std::time::Instant;

use config::{
    atomic_write_text, exe_dir, load_config, load_state, normalize_tab_order, save_config,
    save_state, validate_config, AlertStateMap, AppConfig,
};
use hidpp::{HidppController, HidppSnapshot};
use json::{parse_json, JsonVal};
use monitor::{
    append_history_with_status, evaluate_device, format_device_name, load_history,
    parse_report_rate_hz, read_all_mouse_batteries, send_windows_toast, BatteryHealth,
    DeviceBattery, DischargeSession, HistoryRec,
};
use mouse::{
    detect_connection_type, get_autostart_enabled, get_idle_seconds, get_pointer_speed,
    get_swap_buttons, get_wheel_scroll_lines, is_foreground_game, is_windows_light_theme,
    open_folder, open_lghub, open_url, pick_file_dialog, read_windows_accent_hex,
    set_autostart_enabled, set_enhance_pointer_precision, set_pointer_speed, set_swap_buttons,
    set_wheel_scroll_lines, to_wide,
};
use updater::{check_for_update, APP_VERSION};
use wv2::{
    com_add_ref, com_release, find_embedded_browser_webview_dll, new_com_callback,
    CreateWv2EnvInternalFn, EventToken, HResult, Handle, Hmodule, Hwnd, ICoreWebView2,
    ICoreWebView2Controller, ICoreWebView2Environment, ICoreWebView2Settings,
    ICoreWebView2WebMessageReceivedEventArgs, Rect, IID_CTRL_HANDLER, IID_ENV_HANDLER,
    IID_MSG_HANDLER, LOAD_WITH_ALTERED_SEARCH_PATH,
};

static UI_HTML: &str = include_str!("ui.html");

const WM_DESTROY: u32 = 0x0002;
const WM_SIZE: u32 = 0x0005;
const WM_PAINT: u32 = 0x000F;
const WM_CLOSE: u32 = 0x0010;
const WM_COMMAND: u32 = 0x0111;
const WM_TIMER: u32 = 0x0113;
const WM_LBUTTONUP: u32 = 0x0202;
const WM_RBUTTONUP: u32 = 0x0205;
const WM_TRAYICON: u32 = 0x8001;

const TRAY_ID: u32 = 1;
const TIMER_TICK_1S: usize = 1;
const TIMER_POLL: usize = 2;
const CMD_TRAY_OPEN: usize = 5001;
const CMD_TRAY_REFRESH: usize = 5002;
const CMD_TRAY_TEST: usize = 5003;
const CMD_TRAY_GHUB: usize = 5004;
const CMD_TRAY_EXIT: usize = 5005;

const WS_OVERLAPPED: u32 = 0x00000000;
const WS_CAPTION: u32 = 0x00C00000;
const WS_SYSMENU: u32 = 0x00080000;
const WS_MINIMIZEBOX: u32 = 0x00020000;
const WS_THICKFRAME: u32 = 0x00040000;
const WS_MAXIMIZEBOX: u32 = 0x00010000;
const CW_USEDEFAULT: i32 = -2147483648i32;
const SW_HIDE: i32 = 0;
const SW_SHOWNORMAL: i32 = 1;
const SW_SHOW: i32 = 5;
const NIM_ADD: u32 = 0;
const NIM_MODIFY: u32 = 1;
const NIM_DELETE: u32 = 2;
const NIF_MESSAGE: u32 = 0x01;
const NIF_ICON: u32 = 0x02;
const NIF_TIP: u32 = 0x04;
const NIF_INFO: u32 = 0x10;
const NIIF_INFO: u32 = 0x01;
const MF_STRING: u32 = 0x0000;
const MF_SEPARATOR: u32 = 0x0800;
const TPM_RIGHTBUTTON: u32 = 0x0002;
const DWMWA_USE_IMMERSIVE_DARK_MODE: u32 = 20;
const TH32CS_SNAPPROCESS: u32 = 0x00000002;
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;

#[repr(C)]
#[derive(Default)]
struct WndClassExW {
    cb_size: u32,
    style: u32,
    lpfn_wnd_proc: Option<unsafe extern "system" fn(Hwnd, u32, usize, isize) -> isize>,
    cb_cls_extra: i32,
    cb_wnd_extra: i32,
    h_instance: Handle,
    h_icon: Handle,
    h_cursor: Handle,
    hbr_background: Handle,
    lpsz_menu_name: *const u16,
    lpsz_class_name: *const u16,
    h_icon_sm: Handle,
}

#[repr(C)]
#[derive(Default)]
struct Point {
    x: i32,
    y: i32,
}

#[repr(C)]
#[derive(Default)]
struct Msg {
    hwnd: Hwnd,
    message: u32,
    w_param: usize,
    l_param: isize,
    time: u32,
    pt: Point,
    l_private: u32,
}

#[repr(C)]
struct PaintStruct {
    hdc: Handle,
    f_erase: i32,
    rc_paint: Rect,
    f_restore: i32,
    f_inc_update: i32,
    rgb_reserved: [u8; 32],
}

#[repr(C)]
struct NotifyIconDataW {
    cb_size: u32,
    h_wnd: Hwnd,
    u_id: u32,
    u_flags: u32,
    u_callback_message: u32,
    h_icon: Handle,
    sz_tip: [u16; 128],
    dw_state: u32,
    dw_state_mask: u32,
    sz_info: [u16; 256],
    u_timeout_or_version: u32,
    sz_info_title: [u16; 64],
    dw_info_flags: u32,
    guid_item: [u8; 16],
    h_balloon_icon: Handle,
}

#[repr(C)]
struct ProcessMemoryCountersEx {
    cb: u32,
    page_fault_count: u32,
    peak_working_set_size: usize,
    working_set_size: usize,
    quota_peak_paged_pool_usage: usize,
    quota_paged_pool_usage: usize,
    quota_peak_non_paged_pool_usage: usize,
    quota_non_paged_pool_usage: usize,
    pagefile_usage: usize,
    peak_pagefile_usage: usize,
    private_usage: usize,
}

#[repr(C)]
struct ProcessEntry32W {
    dw_size: u32,
    cnt_usage: u32,
    th32_process_id: u32,
    th32_default_heap_id: usize,
    th32_module_id: u32,
    cnt_threads: u32,
    th32_parent_process_id: u32,
    pc_pri_class_base: i32,
    dw_flags: u32,
    sz_exe_file: [u16; 260],
}

#[repr(C)]
struct BitmapInfoHeader {
    bi_size: u32,
    bi_width: i32,
    bi_height: i32,
    bi_planes: u16,
    bi_bit_count: u16,
    bi_compression: u32,
    bi_size_image: u32,
    bi_x_pels_per_meter: i32,
    bi_y_pels_per_meter: i32,
    bi_clr_used: u32,
    bi_clr_important: u32,
}

#[repr(C)]
struct BitmapInfo {
    bmi_header: BitmapInfoHeader,
    bmi_colors: [u32; 1],
}

#[repr(C)]
struct IconInfo {
    f_icon: i32,
    x_hotspot: u32,
    y_hotspot: u32,
    hbm_mask: Handle,
    hbm_color: Handle,
}

#[link(name = "kernel32")]
extern "system" {
    fn GetModuleHandleW(name: *const u16) -> Hmodule;
    fn GetCurrentProcess() -> Handle;
    fn GetCurrentProcessId() -> u32;
    fn LoadLibraryExW(name: *const u16, file: Handle, flags: u32) -> Hmodule;
    fn GetProcAddress(hm: Hmodule, proc_name: *const u8) -> *const c_void;
    fn FreeLibrary(hm: Hmodule) -> i32;
    fn K32GetProcessMemoryInfo(process: Handle, pmc: *mut ProcessMemoryCountersEx, cb: u32) -> i32;
    fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> Handle;
    fn Process32FirstW(snap: Handle, entry: *mut ProcessEntry32W) -> i32;
    fn Process32NextW(snap: Handle, entry: *mut ProcessEntry32W) -> i32;
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
    fn CloseHandle(h: Handle) -> i32;
    fn SetProcessWorkingSetSize(h: Handle, min: usize, max: usize) -> i32;
}

#[link(name = "user32")]
extern "system" {
    fn RegisterClassExW(wc: *const WndClassExW) -> u16;
    fn CreateWindowExW(ex: u32, cls: *const u16, title: *const u16, style: u32, x: i32, y: i32, w: i32, h: i32, parent: Hwnd, menu: Handle, inst: Handle, param: *mut c_void) -> Hwnd;
    fn DefWindowProcW(hwnd: Hwnd, msg: u32, wp: usize, lp: isize) -> isize;
    fn ShowWindow(hwnd: Hwnd, cmd: i32) -> i32;
    fn UpdateWindow(hwnd: Hwnd) -> i32;
    fn BeginPaint(hwnd: Hwnd, ps: *mut PaintStruct) -> Handle;
    fn EndPaint(hwnd: Hwnd, ps: *const PaintStruct) -> i32;
    fn GetClientRect(hwnd: Hwnd, rc: *mut Rect) -> i32;
    fn FillRect(hdc: Handle, rc: *const Rect, br: Handle) -> i32;
    fn DrawTextW(hdc: Handle, text: *const u16, len: i32, rc: *mut Rect, fmt: u32) -> i32;
    fn GetDC(hwnd: Hwnd) -> Handle;
    fn ReleaseDC(hwnd: Hwnd, hdc: Handle) -> i32;
    fn DestroyWindow(hwnd: Hwnd) -> i32;
    fn PostQuitMessage(code: i32);
    fn GetMessageW(msg: *mut Msg, hwnd: Hwnd, min_f: u32, max_f: u32) -> i32;
    fn TranslateMessage(msg: *const Msg) -> i32;
    fn DispatchMessageW(msg: *const Msg) -> isize;
    fn IsWindow(hwnd: Hwnd) -> i32;
    fn IsWindowVisible(hwnd: Hwnd) -> i32;
    fn InvalidateRect(hwnd: Hwnd, rc: *const Rect, erase: i32) -> i32;
    fn SetForegroundWindow(hwnd: Hwnd) -> i32;
    fn SetTimer(hwnd: Hwnd, id: usize, elapse: u32, func: *const c_void) -> usize;
    fn KillTimer(hwnd: Hwnd, id: usize) -> i32;
    fn GetCursorPos(pt: *mut Point) -> i32;
    fn CreatePopupMenu() -> Handle;
    fn AppendMenuW(menu: Handle, flags: u32, id: usize, item: *const u16) -> i32;
    fn TrackPopupMenu(menu: Handle, flags: u32, x: i32, y: i32, res: i32, hwnd: Hwnd, rc: *const Rect) -> i32;
    fn DestroyMenu(menu: Handle) -> i32;
    fn LoadCursorW(inst: Handle, name: *const u16) -> Handle;
    fn LoadIconW(inst: Handle, name: *const u16) -> Handle;
    fn DestroyIcon(icon: Handle) -> i32;
    fn CreateIconIndirect(info: *const IconInfo) -> Handle;
    fn AdjustWindowRectEx(rc: *mut Rect, style: u32, menu: i32, ex_style: u32) -> i32;
    fn MulDiv(num: i32, mul: i32, div: i32) -> i32;
}

#[link(name = "gdi32")]
extern "system" {
    fn CreateSolidBrush(color: u32) -> Handle;
    fn DeleteObject(obj: Handle) -> i32;
    fn CreateCompatibleDC(hdc: Handle) -> Handle;
    fn DeleteDC(hdc: Handle) -> i32;
    fn CreateDIBSection(hdc: Handle, bmi: *const BitmapInfo, usage: u32, bits: *mut *mut c_void, sec: Handle, off: u32) -> Handle;
    fn CreateBitmap(w: i32, h: i32, planes: u32, bpp: u32, bits: *const c_void) -> Handle;
    fn SelectObject(hdc: Handle, obj: Handle) -> Handle;
    fn CreateFontW(h: i32, w: i32, esc: i32, ori: i32, weight: i32, it: u32, ul: u32, so: u32, cs: u32, op: u32, cp: u32, q: u32, pf: u32, face: *const u16) -> Handle;
    fn SetBkMode(hdc: Handle, mode: i32) -> i32;
    fn SetTextColor(hdc: Handle, color: u32) -> u32;
}

#[link(name = "shell32")]
extern "system" {
    fn Shell_NotifyIconW(msg: u32, data: *const NotifyIconDataW) -> i32;
}

#[link(name = "ole32")]
extern "system" {
    fn CoInitializeEx(reserved: *mut c_void, coinit: u32) -> HResult;
    fn CoUninitialize();
    fn CoTaskMemFree(pv: *mut c_void);
}

#[link(name = "dwmapi")]
extern "system" {
    fn DwmSetWindowAttribute(hwnd: Hwnd, attr: u32, val: *const c_void, sz: u32) -> HResult;
}

struct AppState {
    hwnd: Hwnd,
    smoke_test: bool,
    cfg: AppConfig,
    alert_state: AlertStateMap,
    history: Vec<HistoryRec>,
    devices: Vec<DeviceBattery>,
    selected_slug: String,
    active_dev: DeviceBattery,
    hidpp: HidppController,
    hid_snap: HidppSnapshot,

    // Evaluated metrics
    drain_rate: f64,
    is_learned: bool,
    sessions_used: usize,
    total_discharge_pct: i32,
    time_left_str: String,
    power_mw: Option<f64>,
    evening_status: String,
    health: BatteryHealth,
    recent_sessions: Vec<DischargeSession>,
    pending_active_secs: f64,
    last_game_accel_state: Option<bool>,

    // Diagnostics & OS state
    pointer_speed: i32,
    scroll_lines: i32,
    swap_buttons: bool,
    autostart: bool,
    idle_seconds: f64,
    exe_bytes: u64,
    ws_kb: u64,
    priv_kb: u64,
    child_count: u64,
    child_ws_kb: u64,
    child_priv_kb: u64,
    start_instant: Option<Instant>,
    launch_ms: f64,
    launch_captured: bool,
    update_status: String,
    toast_msg: Option<String>,

    // Tray & WebView2
    tray_icon: Handle,
    tray_added: bool,
    last_tray_pct: i32,
    last_tray_col: String,
    wv2_module: Hmodule,
    wv2_env: ICoreWebView2Environment,
    wv2_ctrl: ICoreWebView2Controller,
    wv2_view: ICoreWebView2,
    msg_token: EventToken,
    has_msg_token: bool,
    wv2_creating: bool,
    wv2_last_hr: HResult,
}

impl Default for AppState {
    fn default() -> Self {
        Self {
            hwnd: null_mut(),
            smoke_test: false,
            cfg: AppConfig::default(),
            alert_state: Vec::new(),
            history: Vec::new(),
            devices: Vec::new(),
            selected_slug: String::new(),
            active_dev: DeviceBattery {
                device: "g502x-plus".into(),
                display_name: "G502 X PLUS".into(),
                percentage: Some(91.0),
                is_charging: false,
                source: "History".into(),
                connection: "LIGHTSPEED".into(),
                vendor_id: 0x046D,
                product_id: 0,
            },
            hidpp: HidppController::default(),
            hid_snap: HidppSnapshot::default(),
            drain_rate: 1.5,
            is_learned: false,
            sessions_used: 0,
            total_discharge_pct: 0,
            time_left_str: "~57h 20m".into(),
            power_mw: Some(14.0),
            evening_status: "will_last".into(),
            health: BatteryHealth {
                status: "calibrating".into(),
                advertised_mah: 500,
                advertised_mwh: 1900.0,
                charge_cycles: 0.0,
                active_cycles: 0.0,
                est_capacity_mah: None,
                est_capacity_mwh: None,
                health_pct: None,
            },
            recent_sessions: Vec::new(),
            pending_active_secs: 0.0,
            last_game_accel_state: None,
            pointer_speed: 10,
            scroll_lines: 3,
            swap_buttons: false,
            autostart: false,
            idle_seconds: 0.0,
            exe_bytes: 0,
            ws_kb: 0,
            priv_kb: 0,
            child_count: 0,
            child_ws_kb: 0,
            child_priv_kb: 0,
            start_instant: None,
            launch_ms: 0.0,
            launch_captured: false,
            update_status: String::new(),
            toast_msg: None,
            tray_icon: null_mut(),
            tray_added: false,
            last_tray_pct: -999,
            last_tray_col: String::new(),
            wv2_module: null_mut(),
            wv2_env: null_mut(),
            wv2_ctrl: null_mut(),
            wv2_view: null_mut(),
            msg_token: EventToken::default(),
            has_msg_token: false,
            wv2_creating: false,
            wv2_last_hr: 0,
        }
    }
}

thread_local! {
    static APP: RefCell<AppState> = RefCell::new(AppState::default());
}

fn resolve_theme(cfg: &AppConfig) -> String {
    if cfg.theme == "System" {
        if is_windows_light_theme() { "Light".into() } else { "Dark".into() }
    } else {
        cfg.theme.clone()
    }
}

fn tray_badge_hex(st: &AppState) -> &'static str {
    let pct = st.active_dev.percentage.unwrap_or(0.0);
    let light = resolve_theme(&st.cfg) == "Light";
    if pct <= st.cfg.critical_battery_threshold {
        if light { "#B3261E" } else { "#F87171" }
    } else if pct <= st.cfg.low_battery_threshold {
        if light { "#9A5400" } else if st.cfg.theme == "Matrix" { "#FACC15" } else { "#F59E0B" }
    } else if light {
        "#146C2E"
    } else if st.cfg.theme == "Matrix" {
        "#4ADE80"
    } else {
        "#22C55E"
    }
}

unsafe fn create_numeric_tray_icon(pct: i32, hex_col: &str) -> Handle {
    let rgb = u32::from_str_radix(hex_col.trim_start_matches('#'), 16).unwrap_or(0x22C55E);
    let size = 32i32;
    let bmi = BitmapInfo {
        bmi_header: BitmapInfoHeader {
            bi_size: size_of::<BitmapInfoHeader>() as u32,
            bi_width: size,
            bi_height: -size,
            bi_planes: 1,
            bi_bit_count: 32,
            bi_compression: 0,
            bi_size_image: 0,
            bi_x_pels_per_meter: 0,
            bi_y_pels_per_meter: 0,
            bi_clr_used: 0,
            bi_clr_important: 0,
        },
        bmi_colors: [0],
    };

    let mut bits: *mut c_void = null_mut();
    let hdc_screen = GetDC(null_mut());
    let hdc_mem = CreateCompatibleDC(hdc_screen);
    let hbm_color = CreateDIBSection(hdc_screen, &bmi, 0, &mut bits, null_mut(), 0);
    let hbm_mask = CreateBitmap(size, size, 1, 1, null());
    let old_bmp = SelectObject(hdc_mem, hbm_color);

    if !bits.is_null() {
        let px = std::slice::from_raw_parts_mut(bits as *mut u32, (size * size) as usize);
        let (rr, gg, bb) = ((rgb >> 16) & 0xFF, (rgb >> 8) & 0xFF, rgb & 0xFF);
        for y in 0..size {
            for x in 0..size {
                let (dx, dy) = ((x as f32 + 0.5) - 16.0, (y as f32 + 0.5) - 16.0);
                px[(y * size + x) as usize] = if (dx * dx + dy * dy).sqrt() <= 14.5 {
                    (0xFFu32 << 24) | (rr << 16) | (gg << 8) | bb
                } else {
                    0
                };
            }
        }
    }

    SetBkMode(hdc_mem, 1);
    SetTextColor(hdc_mem, 11 | (17 << 8) | (32 << 16));
    let face = to_wide("Segoe UI");
    let hf = CreateFontW(-15, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 5, 32, face.as_ptr());
    let old_font = SelectObject(hdc_mem, hf);
    let num_w = to_wide(&pct.clamp(0, 100).to_string());
    let mut tr = Rect { left: 0, top: 0, right: size, bottom: size };
    DrawTextW(hdc_mem, num_w.as_ptr(), -1, &mut tr, 0x01 | 0x04 | 0x20);
    if !bits.is_null() {
        let px = std::slice::from_raw_parts_mut(bits as *mut u32, (size * size) as usize);
        for p in px.iter_mut() {
            if (*p & 0x00FFFFFF) != 0 && (*p >> 24) == 0 {
                *p |= 0xFF000000;
            }
        }
    }
    SelectObject(hdc_mem, old_font);
    DeleteObject(hf);
    SelectObject(hdc_mem, old_bmp);

    let ii = IconInfo { f_icon: 1, x_hotspot: 0, y_hotspot: 0, hbm_mask, hbm_color };
    let hicon = CreateIconIndirect(&ii);
    DeleteObject(hbm_mask);
    DeleteObject(hbm_color);
    DeleteDC(hdc_mem);
    ReleaseDC(null_mut(), hdc_screen);
    if hicon.is_null() { LoadIconW(null_mut(), 32512usize as *const u16) } else { hicon }
}

fn sync_tray_icon(st: &mut AppState, remove_now: bool) {
    unsafe {
        let mut nid: NotifyIconDataW = zeroed();
        nid.cb_size = size_of::<NotifyIconDataW>() as u32;
        nid.h_wnd = st.hwnd;
        nid.u_id = TRAY_ID;
        if remove_now {
            if st.tray_added {
                Shell_NotifyIconW(NIM_DELETE, &nid);
                st.tray_added = false;
            }
            if !st.tray_icon.is_null() {
                DestroyIcon(st.tray_icon);
                st.tray_icon = null_mut();
            }
            return;
        }

        let ipct = st.active_dev.percentage.unwrap_or(0.0).round() as i32;
        let col = tray_badge_hex(st).to_string();
        if st.tray_icon.is_null() || st.last_tray_pct != ipct || st.last_tray_col != col {
            let next = create_numeric_tray_icon(ipct, &col);
            if !st.tray_icon.is_null() {
                DestroyIcon(st.tray_icon);
            }
            st.tray_icon = next;
            st.last_tray_pct = ipct;
            st.last_tray_col = col;
        }
        nid.u_flags = NIF_ICON | NIF_TIP | NIF_MESSAGE;
        nid.u_callback_message = WM_TRAYICON;
        nid.h_icon = st.tray_icon;
        let tip = format!("{}: {}% • ~{} left", st.active_dev.display_name, ipct, st.time_left_str);
        for (i, code) in to_wide(&tip).into_iter().take(128).enumerate() {
            nid.sz_tip[i] = code;
        }
        if !st.tray_added {
            if Shell_NotifyIconW(NIM_ADD, &nid) != 0 {
                st.tray_added = true;
            }
        } else {
            Shell_NotifyIconW(NIM_MODIFY, &nid);
        }
    }
}

fn send_tray_balloon(st: &mut AppState, title: &str, body: &str) {
    if !st.tray_added {
        sync_tray_icon(st, false);
    }
    unsafe {
        let mut nid: NotifyIconDataW = zeroed();
        nid.cb_size = size_of::<NotifyIconDataW>() as u32;
        nid.h_wnd = st.hwnd;
        nid.u_id = TRAY_ID;
        nid.u_flags = NIF_INFO;
        nid.dw_info_flags = NIIF_INFO;
        for (i, c) in to_wide(title).into_iter().take(64).enumerate() {
            nid.sz_info_title[i] = c;
        }
        for (i, c) in to_wide(body).into_iter().take(256).enumerate() {
            nid.sz_info[i] = c;
        }
        Shell_NotifyIconW(NIM_MODIFY, &nid);
    }
}

fn measure_memory(st: &mut AppState) {
    st.child_count = 0;
    st.child_ws_kb = 0;
    st.child_priv_kb = 0;
    unsafe {
        let mut pmc: ProcessMemoryCountersEx = zeroed();
        pmc.cb = size_of::<ProcessMemoryCountersEx>() as u32;
        if K32GetProcessMemoryInfo(GetCurrentProcess(), &mut pmc, pmc.cb) != 0 {
            st.ws_kb = (pmc.working_set_size / 1024) as u64;
            st.priv_kb = (pmc.private_usage / 1024) as u64;
        }

        let snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
        if snap.is_null() || snap == (-1isize as Handle) {
            return;
        }
        let mut children_map: HashMap<u32, Vec<u32>> = HashMap::new();
        let mut pe: ProcessEntry32W = zeroed();
        pe.dw_size = size_of::<ProcessEntry32W>() as u32;
        if Process32FirstW(snap, &mut pe) != 0 {
            loop {
                children_map.entry(pe.th32_parent_process_id).or_default().push(pe.th32_process_id);
                if Process32NextW(snap, &mut pe) == 0 {
                    break;
                }
            }
        }
        CloseHandle(snap);

        let root = GetCurrentProcessId();
        let mut frontier = vec![root];
        let mut desc = Vec::new();
        let mut i = 0;
        while i < frontier.len() {
            if let Some(kids) = children_map.get(&frontier[i]) {
                for &k in kids {
                    if k != frontier[i] && !frontier.contains(&k) {
                        frontier.push(k);
                        desc.push(k);
                    }
                }
            }
            i += 1;
        }
        for pid in desc {
            let hp = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if !hp.is_null() {
                let mut cpmc: ProcessMemoryCountersEx = zeroed();
                cpmc.cb = size_of::<ProcessMemoryCountersEx>() as u32;
                if K32GetProcessMemoryInfo(hp, &mut cpmc, cpmc.cb) != 0 {
                    st.child_count += 1;
                    st.child_ws_kb += (cpmc.working_set_size / 1024) as u64;
                    st.child_priv_kb += (cpmc.private_usage / 1024) as u64;
                }
                CloseHandle(hp);
            }
        }
    }
}

fn read_os_mouse_state(st: &mut AppState) {
    st.pointer_speed = get_pointer_speed();
    st.scroll_lines = get_wheel_scroll_lines();
    st.swap_buttons = get_swap_buttons();
    st.autostart = get_autostart_enabled();
    st.idle_seconds = get_idle_seconds();
}

fn refresh_battery_and_eval(st: &mut AppState, send_alerts: bool, save_history_sample: bool) {
    st.history = load_history(st.cfg.max_history_days);
    let mut all = read_all_mouse_batteries();
    all.retain(|d| !st.cfg.hidden_devices.contains(&d.device));
    st.devices = all;

    let chosen = if !st.selected_slug.is_empty() {
        st.devices.iter().find(|d| d.device == st.selected_slug).cloned()
    } else if let Some(ref f) = st.cfg.device_filter {
        st.devices.iter().find(|d| d.device.contains(f.as_str())).cloned()
    } else {
        None
    }
    .or_else(|| st.devices.first().cloned());

    if let Some(dev) = chosen {
        st.selected_slug = dev.device.clone();
        st.active_dev = dev;
    } else if let Some(last) = st.history.last() {
        st.active_dev = DeviceBattery {
            device: last.device.clone(),
            display_name: format_device_name(&last.device),
            percentage: Some(last.pct),
            is_charging: last.charging,
            source: "History".into(),
            connection: detect_connection_type(last.charging).1,
            vendor_id: 0x046D,
            product_id: 0,
        };
    }

    if !st.smoke_test {
        st.hid_snap = st.hidpp.read_snapshot();
    }
    let eff_hz = st.hid_snap.report_rate_hz.or_else(|| Some(parse_report_rate_hz(&st.cfg.report_rate)));

    if save_history_sample && !st.smoke_test {
        let hz_val = eff_hz.unwrap_or(1000);
        if append_history_with_status(&st.active_dev, &mut st.history, st.cfg.max_history_days, hz_val, st.pending_active_secs) {
            st.pending_active_secs = 0.0;
        }
    }

    let ev = evaluate_device(&st.active_dev, &st.cfg, &st.history, &mut st.alert_state, eff_hz, send_alerts);
    st.drain_rate = ev.drain_rate;
    st.is_learned = ev.is_learned;
    st.sessions_used = ev.sessions_used;
    st.total_discharge_pct = ev.total_discharge_pct;
    st.time_left_str = ev.time_left_str;
    st.power_mw = ev.est_power_mw.map(|x| x.0);
    st.evening_status = ev.evening_status;
    st.health = ev.health;
    st.recent_sessions = ev.recent_sessions;
    if ev.notified {
        save_state(&st.alert_state);
    }

    read_os_mouse_state(st);
    measure_memory(st);
    sync_tray_icon(st, false);
}

fn sync_titlebar_theme(st: &AppState) {
    if st.hwnd.is_null() {
        return;
    }
    let dark: i32 = if resolve_theme(&st.cfg) != "Light" { 1 } else { 0 };
    unsafe { DwmSetWindowAttribute(st.hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark as *const i32 as *const c_void, 4); }
}

fn build_ui_state_json(st: &mut AppState) -> String {
    measure_memory(st);
    let dev_slug = &st.active_dev.device;
    let mut dev_hist: Vec<&HistoryRec> = st.history.iter().filter(|h| &h.device == dev_slug).collect();
    if dev_hist.is_empty() {
        dev_hist = st.history.iter().collect();
    }
    if dev_hist.len() > 240 {
        dev_hist = dev_hist.split_off(dev_hist.len() - 240);
    }
    let hist_arr: Vec<JsonVal> = dev_hist
        .iter()
        .map(|h| {
            let label = if h.ts.len() >= 16 { format!("{} {}", &h.ts[5..10], &h.ts[11..16]) } else { h.ts.clone() };
            JsonVal::Obj(vec![
                ("pct".into(), JsonVal::Num(h.pct)),
                ("ts_sec".into(), JsonVal::Num(h.ts_sec)),
                ("label".into(), JsonVal::Str(label)),
            ])
        })
        .collect();

    let devs_arr: Vec<JsonVal> = st
        .devices
        .iter()
        .map(|d| {
            JsonVal::Obj(vec![
                ("slug".into(), JsonVal::Str(d.device.clone())),
                ("display_name".into(), JsonVal::Str(d.display_name.clone())),
                ("pct".into(), JsonVal::Num(d.percentage.unwrap_or(0.0).round())),
            ])
        })
        .collect();

    let sess_arr: Vec<JsonVal> = st
        .recent_sessions
        .iter()
        .map(|s| {
            JsonVal::Obj(vec![
                ("end_label".into(), JsonVal::Str(s.end_label.clone())),
                ("start_pct".into(), JsonVal::Num(s.start_pct as f64)),
                ("end_pct".into(), JsonVal::Num(s.end_pct as f64)),
                ("duration_h".into(), JsonVal::Num(s.duration_h)),
                ("rate".into(), JsonVal::Num(s.rate)),
            ])
        })
        .collect();

    let health_obj = JsonVal::Obj(vec![
        ("status".into(), JsonVal::Str(st.health.status.clone())),
        ("charge_cycles".into(), JsonVal::Num(st.health.charge_cycles)),
        ("active_cycles".into(), JsonVal::Num(st.health.active_cycles)),
        (
            "est_capacity_mah".into(),
            st.health.est_capacity_mah.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null),
        ),
        (
            "est_capacity_mwh".into(),
            st.health.est_capacity_mwh.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null),
        ),
        (
            "health_pct".into(),
            st.health.health_pct.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null),
        ),
    ]);

    let hid_obj = JsonVal::Obj(vec![
        ("connected".into(), JsonVal::Bool(st.hid_snap.connected)),
        ("firmware".into(), JsonVal::Str(st.hid_snap.firmware.clone())),
        ("dpi".into(), st.hid_snap.dpi.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null)),
        (
            "report_rate_hz".into(),
            st.hid_snap.report_rate_hz.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null),
        ),
        (
            "onboard_mode".into(),
            st.hid_snap.onboard_mode.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null),
        ),
        (
            "onboard_profile".into(),
            st.hid_snap.onboard_profile.map(|v| JsonVal::Num(v as f64)).unwrap_or(JsonVal::Null),
        ),
        ("profile_count".into(), JsonVal::Num(st.hid_snap.profile_count.max(1) as f64)),
        ("has_rgb".into(), JsonVal::Bool(st.hid_snap.has_rgb)),
    ]);

    let conn_str = detect_connection_type(st.active_dev.is_charging).1;
    let win_acc = read_windows_accent_hex()
        .map(JsonVal::Str)
        .unwrap_or(JsonVal::Null);
    let toast_val = st.toast_msg.take().map(JsonVal::Str).unwrap_or(JsonVal::Null);

    JsonVal::Obj(vec![
        ("config".into(), st.cfg.to_json_val()),
        ("resolved_theme".into(), JsonVal::Str(resolve_theme(&st.cfg))),
        ("custom_accent_hex".into(), win_acc),
        ("device_name".into(), JsonVal::Str(st.active_dev.display_name.clone())),
        ("battery_pct".into(), JsonVal::Num(st.active_dev.percentage.unwrap_or(0.0))),
        ("charging".into(), JsonVal::Bool(st.active_dev.is_charging)),
        ("source".into(), JsonVal::Str(st.active_dev.source.clone())),
        ("connection".into(), JsonVal::Str(conn_str)),
        ("evening_status".into(), JsonVal::Str(st.evening_status.clone())),
        ("time_left_str".into(), JsonVal::Str(st.time_left_str.clone())),
        ("drain_rate".into(), JsonVal::Num(st.drain_rate)),
        ("is_learned".into(), JsonVal::Bool(st.is_learned)),
        ("sessions_used".into(), JsonVal::Num(st.sessions_used as f64)),
        ("total_discharge_pct".into(), JsonVal::Num(st.total_discharge_pct as f64)),
        ("power_mw".into(), st.power_mw.map(JsonVal::Num).unwrap_or(JsonVal::Null)),
        ("idle_seconds".into(), JsonVal::Num(st.idle_seconds)),
        ("pointer_speed".into(), JsonVal::Num(st.pointer_speed as f64)),
        ("scroll_lines".into(), JsonVal::Num(st.scroll_lines as f64)),
        ("swap_buttons".into(), JsonVal::Bool(st.swap_buttons)),
        ("autostart".into(), JsonVal::Bool(st.autostart)),
        ("exe_bytes".into(), JsonVal::Num(st.exe_bytes as f64)),
        ("ws_kb".into(), JsonVal::Num(st.ws_kb as f64)),
        ("priv_kb".into(), JsonVal::Num(st.priv_kb as f64)),
        ("child_count".into(), JsonVal::Num(st.child_count as f64)),
        ("child_ws_kb".into(), JsonVal::Num(st.child_ws_kb as f64)),
        ("child_priv_kb".into(), JsonVal::Num(st.child_priv_kb as f64)),
        ("launch_ms".into(), JsonVal::Num(st.launch_ms)),
        ("update_status".into(), JsonVal::Str(st.update_status.clone())),
        ("toast".into(), toast_val),
        ("devices".into(), JsonVal::Arr(devs_arr)),
        ("history".into(), JsonVal::Arr(hist_arr)),
        ("recent_sessions".into(), JsonVal::Arr(sess_arr)),
        ("health".into(), health_obj),
        ("hidpp".into(), hid_obj),
    ])
    .to_compact_string()
}

fn push_state_to_webview(st: &mut AppState) {
    if st.wv2_view.is_null() {
        return;
    }
    let payload = build_ui_state_json(st);
    let w = to_wide(&payload);
    unsafe {
        ((*(*st.wv2_view)).post_web_message_as_json)(st.wv2_view, w.as_ptr());
    }
}

fn reset_poll_timer(st: &AppState) {
    if !st.hwnd.is_null() {
        let ms = (st.cfg.poll_interval_minutes.clamp(1, 1440) as u32) * 60_000;
        unsafe {
            KillTimer(st.hwnd, TIMER_POLL);
            SetTimer(st.hwnd, TIMER_POLL, ms, null());
        }
    }
}

fn handle_web_message(raw_json: &str) {
    let Ok(msg) = parse_json(raw_json) else { return; };
    let Some(cmd) = msg.get("cmd").and_then(|v| v.as_str()) else { return; };

    // Commands that run modal Win32 dialogs, external processes, or network I/O must not hold APP borrow
    // because modal loops / COM callbacks pump WM_TIMER / WM_PAINT and would re-enter APP.
    match cmd {
        "add_game" => {
            let hwnd = APP.with(|cell| cell.borrow().hwnd);
            if let Some(p) = pick_file_dialog(hwnd, false, "Select Game Executable (.exe)", &[("Executables", "*.exe")], "", "exe") {
                if let Some(fname) = p.file_name().and_then(|s| s.to_str()) {
                    APP.with(|cell| {
                        let mut st = cell.borrow_mut();
                        if !st.cfg.auto_games.iter().any(|g| g.eq_ignore_ascii_case(fname)) {
                            st.cfg.auto_games.push(fname.to_string());
                            save_config(&st.cfg);
                        }
                        st.toast_msg = Some(format!("Added {} to Auto Game list", fname));
                        push_state_to_webview(&mut st);
                    });
                }
            }
            return;
        }
        "export_cfg" => {
            let hwnd = APP.with(|cell| cell.borrow().hwnd);
            if let Some(p) = pick_file_dialog(hwnd, true, "Export Preferences", &[("JSON files", "*.json")], "mouse_battery_preferences.json", "json") {
                APP.with(|cell| {
                    let mut st = cell.borrow_mut();
                    let txt = st.cfg.to_json_val().to_pretty_string() + "\n";
                    st.toast_msg = Some(if atomic_write_text(&p, &txt).is_ok() { "Preferences exported!".into() } else { "Export failed".into() });
                    push_state_to_webview(&mut st);
                });
            }
            return;
        }
        "import_cfg" => {
            let hwnd = APP.with(|cell| cell.borrow().hwnd);
            if let Some(p) = pick_file_dialog(hwnd, false, "Import Preferences", &[("JSON files", "*.json")], "", "json") {
                let raw = fs::read_to_string(&p).map_err(|e| e.to_string()).and_then(|r| parse_json(&r));
                APP.with(|cell| {
                    let mut st = cell.borrow_mut();
                    match raw.and_then(|v| validate_config(&v, &st.cfg, true)) {
                        Ok(next) => {
                            st.cfg = next;
                            save_config(&st.cfg);
                            sync_titlebar_theme(&st);
                            reset_poll_timer(&st);
                            refresh_battery_and_eval(&mut st, false, false);
                            st.toast_msg = Some("Preferences imported & validated!".into());
                        }
                        Err(err) => {
                            st.toast_msg = Some(format!("Rejected invalid config: {}", err));
                        }
                    }
                    push_state_to_webview(&mut st);
                });
            }
            return;
        }
        "check_update" => {
            let (hwnd, src) = APP.with(|cell| {
                let st = cell.borrow();
                (st.hwnd, st.cfg.update_source.clone())
            });
            let res = check_for_update(APP_VERSION, src.as_deref());
            if res.status == "update_available" && !res.download_url.is_empty() {
                open_url(hwnd, &res.download_url);
            }
            APP.with(|cell| {
                let mut st = cell.borrow_mut();
                st.update_status = res.message.clone();
                st.toast_msg = Some(res.message);
                push_state_to_webview(&mut st);
            });
            return;
        }
        "lghub" => {
            let hwnd = APP.with(|cell| cell.borrow().hwnd);
            let ok = open_lghub(hwnd);
            APP.with(|cell| {
                let mut st = cell.borrow_mut();
                st.toast_msg = Some(if ok { "Launched Logitech G HUB".into() } else { "Logitech G HUB not found".into() });
                push_state_to_webview(&mut st);
            });
            return;
        }
        "open_folder" => {
            let hwnd = APP.with(|cell| cell.borrow().hwnd);
            open_folder(hwnd, &exe_dir());
            return;
        }
        "test_toast" => {
            let (title, l1, l2, sound) = APP.with(|cell| {
                let st = cell.borrow();
                let pct = st.active_dev.percentage.unwrap_or(0.0).round() as i32;
                let title = format!("{} Battery: {}%", st.active_dev.display_name, pct);
                let l1 = format!("Estimated remaining: ~{}", st.time_left_str);
                let l2 = format!("Usage rate: {:.1}%/hr • Sound: {}", st.drain_rate, st.cfg.notification_sound);
                (title, l1, l2, st.cfg.notification_sound.clone())
            });
            let sent = send_windows_toast(&title, &l1, &l2, &sound);
            APP.with(|cell| {
                let mut st = cell.borrow_mut();
                if !sent {
                    send_tray_balloon(&mut st, &title, &l1);
                }
                st.toast_msg = Some("Test notification sent!".into());
                push_state_to_webview(&mut st);
            });
            return;
        }
        _ => {}
    }

    APP.with(|cell| {
        let mut st = cell.borrow_mut();
        match cmd {
            "ready" => {
                if !st.launch_captured {
                    if let Some(t0) = st.start_instant {
                        st.launch_ms = t0.elapsed().as_secs_f64() * 1000.0;
                    }
                    st.launch_captured = true;
                }
                push_state_to_webview(&mut st);
            }
            "refresh" => {
                refresh_battery_and_eval(&mut st, false, false);
                st.toast_msg = Some("Refreshed battery status".into());
                push_state_to_webview(&mut st);
            }
            "set_cfg" => {
                let key = msg.get("key").and_then(|v| v.as_str()).unwrap_or("");
                let val = msg.get("value");
                match (key, val) {
                    ("theme", Some(v)) => {
                        if let Some(s) = v.as_str() {
                            st.cfg.theme = s.to_string();
                            sync_titlebar_theme(&st);
                            sync_tray_icon(&mut st, false);
                        }
                    }
                    ("accent_mode", Some(v)) => if let Some(s) = v.as_str() { st.cfg.accent_mode = s.to_string(); },
                    ("language", Some(v)) => if let Some(s) = v.as_str() { st.cfg.language = s.to_string(); },
                    ("notification_sound", Some(v)) => if let Some(s) = v.as_str() { st.cfg.notification_sound = s.to_string(); },
                    ("evening_hour", Some(v)) => if let Some(n) = v.as_i64() { st.cfg.evening_hour = (n as i32).clamp(0, 23); },
                    ("low_battery_threshold", Some(v)) => if let Some(n) = v.as_f64() {
                        st.cfg.low_battery_threshold = n.clamp(st.cfg.critical_battery_threshold + 1.0, 100.0);
                        sync_tray_icon(&mut st, false);
                    },
                    ("critical_battery_threshold", Some(v)) => if let Some(n) = v.as_f64() {
                        st.cfg.critical_battery_threshold = n.clamp(1.0, st.cfg.low_battery_threshold - 1.0);
                        sync_tray_icon(&mut st, false);
                    },
                    ("cooldown_minutes", Some(v)) => if let Some(n) = v.as_i64() { st.cfg.cooldown_minutes = (n as i32).clamp(1, 1440); },
                    ("poll_interval_minutes", Some(v)) => if let Some(n) = v.as_i64() {
                        st.cfg.poll_interval_minutes = (n as i32).clamp(1, 1440);
                        reset_poll_timer(&st);
                    },
                    ("accel_mode", Some(v)) => if let Some(s) = v.as_str() {
                        st.cfg.accel_mode = s.to_string();
                        if s == "Off" { set_enhance_pointer_precision(false); }
                        else if s == "On" { set_enhance_pointer_precision(true); }
                        else { set_enhance_pointer_precision(!is_foreground_game(&st.cfg.auto_games)); }
                    },
                    _ => {}
                }
                save_config(&st.cfg);
                refresh_battery_and_eval(&mut st, false, false);
                push_state_to_webview(&mut st);
            }
            "toggle" => {
                match msg.get("key").and_then(|v| v.as_str()).unwrap_or("") {
                    "notifications_enabled" => st.cfg.notifications_enabled = !st.cfg.notifications_enabled,
                    "close_to_tray" => st.cfg.close_to_tray = !st.cfg.close_to_tray,
                    "complementary_accent" => st.cfg.complementary_accent = !st.cfg.complementary_accent,
                    "auto_fetch_mouse_icons" => st.cfg.auto_fetch_mouse_icons = !st.cfg.auto_fetch_mouse_icons,
                    "autostart" => {
                        let next = !st.autostart;
                        if set_autostart_enabled(next) { st.autostart = next; }
                    }
                    "swap_buttons" => {
                        let next = !st.swap_buttons;
                        set_swap_buttons(next);
                        st.swap_buttons = get_swap_buttons();
                    }
                    _ => {}
                }
                save_config(&st.cfg);
                push_state_to_webview(&mut st);
            }
            "set_tab_order" => {
                if let Some(arr) = msg.get("order").and_then(|v| v.as_arr()) {
                    let next: Vec<String> = arr.iter().filter_map(|x| x.as_str().map(str::to_string)).collect();
                    st.cfg.tab_order = normalize_tab_order(&next);
                    save_config(&st.cfg);
                    st.toast_msg = Some("Tab order saved".into());
                    push_state_to_webview(&mut st);
                }
            }
            "reset_tab_order" => {
                st.cfg.tab_order = normalize_tab_order(&[]);
                save_config(&st.cfg);
                st.toast_msg = Some("Tab order reset to default".into());
                push_state_to_webview(&mut st);
            }
            "select_device" => {
                if let Some(slug) = msg.get("slug").and_then(|v| v.as_str()) {
                    st.selected_slug = slug.to_string();
                    refresh_battery_and_eval(&mut st, false, false);
                    push_state_to_webview(&mut st);
                }
            }
            "hide_device" => {
                if let Some(slug) = msg.get("slug").and_then(|v| v.as_str()) {
                    if !st.cfg.hidden_devices.iter().any(|x| x == slug) {
                        st.cfg.hidden_devices.push(slug.to_string());
                        save_config(&st.cfg);
                    }
                    refresh_battery_and_eval(&mut st, false, false);
                    push_state_to_webview(&mut st);
                }
            }
            "restore_hidden" => {
                st.cfg.hidden_devices.clear();
                save_config(&st.cfg);
                refresh_battery_and_eval(&mut st, false, false);
                push_state_to_webview(&mut st);
            }
            "preset" => {
                if let Some(name) = msg.get("name").and_then(|v| v.as_str()) {
                    match name {
                        "gaming" => { set_pointer_speed(10); set_enhance_pointer_precision(false); set_wheel_scroll_lines(3); st.cfg.accel_mode = "Off".into(); }
                        "precision" => { set_pointer_speed(8); set_enhance_pointer_precision(false); set_wheel_scroll_lines(3); st.cfg.accel_mode = "Off".into(); }
                        "productivity" => { set_pointer_speed(14); set_enhance_pointer_precision(true); set_wheel_scroll_lines(6); st.cfg.accel_mode = "On".into(); }
                        _ => {}
                    }
                    save_config(&st.cfg);
                    read_os_mouse_state(&mut st);
                    st.toast_msg = Some(format!("Applied '{}' preset", name));
                    push_state_to_webview(&mut st);
                }
            }
            "mouse_spd" => {
                if let Some(v) = msg.get("value").and_then(|x| x.as_i64()) {
                    set_pointer_speed(v as i32);
                    read_os_mouse_state(&mut st);
                    push_state_to_webview(&mut st);
                }
            }
            "mouse_scr" => {
                if let Some(v) = msg.get("value").and_then(|x| x.as_i64()) {
                    set_wheel_scroll_lines(v as i32);
                    read_os_mouse_state(&mut st);
                    push_state_to_webview(&mut st);
                }
            }
            "hid_mode" => {
                let onboard = msg.get("mode").and_then(|v| v.as_str()) == Some("onboard");
                let ok = st.hidpp.set_onboard_mode(onboard);
                st.hid_snap = st.hidpp.read_snapshot();
                st.toast_msg = Some(if ok { format!("Mouse Mode: {}", if onboard { "Onboard" } else { "Host" }) } else { "HID++ mode switch unavailable".into() });
                push_state_to_webview(&mut st);
            }
            "hid_slot" => {
                if let Some(slot) = msg.get("slot").and_then(|v| v.as_i64()) {
                    let ok = st.hidpp.set_onboard_profile(slot as i32);
                    st.hid_snap = st.hidpp.read_snapshot();
                    st.toast_msg = Some(if ok { format!("Active Onboard Profile: Slot {}", slot) } else { "HID++ slot switch unavailable".into() });
                    push_state_to_webview(&mut st);
                }
            }
            "hid_dpi" => {
                if let Some(dpi) = msg.get("dpi").and_then(|v| v.as_i64()) {
                    let stage = msg.get("stage").and_then(|v| v.as_i64()).map(|n| n as usize);
                    let ok = st.hidpp.set_dpi(dpi as i32, stage);
                    st.hid_snap = st.hidpp.read_snapshot();
                    st.toast_msg = Some(if ok { format!("Hardware DPI set to {}", dpi) } else { "HID++ DPI unavailable".into() });
                    push_state_to_webview(&mut st);
                }
            }
            "hid_rate" => {
                if let Some(hz) = msg.get("hz").and_then(|v| v.as_i64()) {
                    let ok = st.hidpp.set_report_rate_hz(hz as i32);
                    if ok {
                        st.cfg.report_rate = format!("{} Hz", hz);
                        save_config(&st.cfg);
                    }
                    st.hid_snap = st.hidpp.read_snapshot();
                    st.toast_msg = Some(if ok { format!("Hardware Report Rate: {} Hz", hz) } else { "Switch to Host mode first to set rate".into() });
                    push_state_to_webview(&mut st);
                }
            }
            "hid_rgb" => {
                let mode = msg.get("mode").and_then(|v| v.as_str()).unwrap_or("Fixed");
                let hex = msg.get("color").and_then(|v| v.as_str()).unwrap_or("#38BDF8").trim_start_matches('#');
                let rgb = u32::from_str_radix(hex, 16).unwrap_or(0x38BDF8);
                let ok = st.hidpp.set_rgb_mode(mode, ((rgb >> 16) & 0xFF) as u8, ((rgb >> 8) & 0xFF) as u8, (rgb & 0xFF) as u8);
                st.toast_msg = Some(if ok { format!("RGB set to {}", mode) } else { "HID++ RGB unavailable".into() });
                push_state_to_webview(&mut st);
            }
            _ => {}
        }
    });
}

fn on_web_message(_sender: *mut c_void, args_ptr: *mut c_void) -> HResult {
    if args_ptr.is_null() {
        return 0;
    }
    unsafe {
        let args = args_ptr as ICoreWebView2WebMessageReceivedEventArgs;
        let mut json_w: *mut u16 = null_mut();
        let hr = ((*(*args)).get_web_message_as_json)(args, &mut json_w);
        if hr >= 0 && !json_w.is_null() {
            let mut len = 0usize;
            while *json_w.add(len) != 0 {
                len += 1;
            }
            let s = String::from_utf16_lossy(std::slice::from_raw_parts(json_w, len));
            CoTaskMemFree(json_w as *mut c_void);
            handle_web_message(&s);
        }
    }
    0
}

fn on_ctrl_created(hr_ptr: *mut c_void, ctrl_ptr: *mut c_void) -> HResult {
    let err = hr_ptr as usize as i32;
    APP.with(|cell| {
        let mut st = cell.borrow_mut();
        st.wv2_creating = false;
        if err < 0 || ctrl_ptr.is_null() {
            st.wv2_last_hr = if err < 0 { err } else { -1 };
            unsafe { InvalidateRect(st.hwnd, null(), 1); }
            return;
        }
        unsafe {
            let ctrl = ctrl_ptr as ICoreWebView2Controller;
            com_add_ref(ctrl_ptr);
            st.wv2_ctrl = ctrl;

            let mut rc = Rect::default();
            GetClientRect(st.hwnd, &mut rc);
            ((*(*ctrl)).put_bounds)(ctrl, &rc);
            ((*(*ctrl)).put_is_visible)(ctrl, 1);

            let mut view: ICoreWebView2 = null_mut();
            if ((*(*ctrl)).get_core_webview2)(ctrl, &mut view) >= 0 && !view.is_null() {
                st.wv2_view = view;
                let mut settings: ICoreWebView2Settings = null_mut();
                if ((*(*view)).get_settings)(view, &mut settings) >= 0 && !settings.is_null() {
                    ((*(*settings)).put_are_default_context_menus_enabled)(settings, 0);
                    ((*(*settings)).put_are_dev_tools_enabled)(settings, 0);
                    ((*(*settings)).put_is_status_bar_enabled)(settings, 0);
                    ((*(*settings)).put_is_zoom_control_enabled)(settings, 0);
                    com_release(settings as *mut c_void);
                }

                let mh = new_com_callback(IID_MSG_HANDLER, on_web_message);
                if ((*(*view)).add_web_message_received)(view, mh, &mut st.msg_token) >= 0 {
                    st.has_msg_token = true;
                }
                com_release(mh);

                let html_w = to_wide(UI_HTML);
                ((*(*view)).navigate_to_string)(view, html_w.as_ptr());
            }
        }
    });
    0
}

fn on_env_created(hr_ptr: *mut c_void, env_ptr: *mut c_void) -> HResult {
    let err = hr_ptr as usize as i32;
    let next: Option<(Hwnd, ICoreWebView2Environment)> = APP.with(|cell| {
        let mut st = cell.borrow_mut();
        unsafe {
            if err < 0 || env_ptr.is_null() || IsWindow(st.hwnd) == 0 {
                st.wv2_creating = false;
                st.wv2_last_hr = if err < 0 { err } else { -1 };
                InvalidateRect(st.hwnd, null(), 1);
                return None;
            }
            com_add_ref(env_ptr);
            let env = env_ptr as ICoreWebView2Environment;
            st.wv2_env = env;
            Some((st.hwnd, env))
        }
    });
    if let Some((hwnd, env)) = next {
        unsafe {
            let ch = new_com_callback(IID_CTRL_HANDLER, on_ctrl_created);
            let hr = ((*(*env)).create_core_webview2_controller)(env, hwnd, ch);
            com_release(ch);
            if hr < 0 {
                APP.with(|cell| {
                    let mut st = cell.borrow_mut();
                    st.wv2_creating = false;
                    st.wv2_last_hr = hr;
                });
                InvalidateRect(hwnd, null(), 1);
            }
        }
    }
    0
}

fn destroy_webview_host_detached() {
    let (view, has_tok, tok, ctrl, env) = APP.with(|cell| {
        let mut st = cell.borrow_mut();
        let v = st.wv2_view;
        let ht = st.has_msg_token;
        let tk = st.msg_token;
        let c = st.wv2_ctrl;
        let e = st.wv2_env;
        st.wv2_view = null_mut();
        st.has_msg_token = false;
        st.wv2_ctrl = null_mut();
        st.wv2_env = null_mut();
        st.wv2_creating = false;
        (v, ht, tk, c, e)
    });
    unsafe {
        if !view.is_null() {
            if has_tok {
                ((*(*view)).remove_web_message_received)(view, tok);
            }
            com_release(view as *mut c_void);
        }
        if !ctrl.is_null() {
            ((*(*ctrl)).close)(ctrl);
            com_release(ctrl as *mut c_void);
        }
        if !env.is_null() {
            com_release(env as *mut c_void);
        }
        SetProcessWorkingSetSize(GetCurrentProcess(), usize::MAX, usize::MAX);
    }
    APP.with(|cell| measure_memory(&mut cell.borrow_mut()));
}

fn create_webview_host_detached() {
    let setup: Option<(Hwnd, CreateWv2EnvInternalFn)> = APP.with(|cell| {
        let mut st = cell.borrow_mut();
        if !st.wv2_view.is_null() || st.wv2_creating {
            return None;
        }
        let Some(dll) = find_embedded_browser_webview_dll() else {
            st.wv2_last_hr = 0x80070002u32 as i32;
            return None;
        };
        unsafe {
            if st.wv2_module.is_null() {
                let wdll = to_wide(&dll);
                st.wv2_module = LoadLibraryExW(wdll.as_ptr(), null_mut(), LOAD_WITH_ALTERED_SEARCH_PATH);
            }
            if st.wv2_module.is_null() {
                st.wv2_last_hr = -1;
                return None;
            }
            let p = GetProcAddress(st.wv2_module, b"CreateWebViewEnvironmentWithOptionsInternal\0".as_ptr());
            if p.is_null() {
                st.wv2_last_hr = 0x8007007Fu32 as i32;
                return None;
            }
            st.wv2_creating = true;
            st.wv2_last_hr = 0;
            Some((st.hwnd, std::mem::transmute::<*const c_void, CreateWv2EnvInternalFn>(p)))
        }
    });

    let Some((hwnd, create_fn)) = setup else { return; };
    let base_udf = env::var("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(|_| env::temp_dir());
    let udf = base_udf.join("MouseBatteryControl_v3_WebView2");
    let _ = fs::create_dir_all(&udf);
    let udf_w = to_wide(&udf.to_string_lossy());
    unsafe {
        let eh = new_com_callback(IID_ENV_HANDLER, on_env_created);
        let hr = create_fn(1, 0, udf_w.as_ptr(), null_mut(), eh);
        com_release(eh);
        if hr < 0 {
            APP.with(|cell| {
                let mut st = cell.borrow_mut();
                st.wv2_creating = false;
                st.wv2_last_hr = hr;
            });
            InvalidateRect(hwnd, null(), 1);
        }
    }
}

unsafe fn show_tray_context_menu(hwnd: Hwnd) {
    let mut pt = Point::default();
    GetCursorPos(&mut pt);
    let menu = CreatePopupMenu();
    let s1 = to_wide("Open Dashboard & Settings");
    let s2 = to_wide("Refresh Now");
    let s3 = to_wide("Send Test Notification");
    let s4 = to_wide("Open Logitech G HUB");
    let s5 = to_wide("Quit");
    AppendMenuW(menu, MF_STRING, CMD_TRAY_OPEN, s1.as_ptr());
    AppendMenuW(menu, MF_STRING, CMD_TRAY_REFRESH, s2.as_ptr());
    AppendMenuW(menu, MF_STRING, CMD_TRAY_TEST, s3.as_ptr());
    AppendMenuW(menu, MF_STRING, CMD_TRAY_GHUB, s4.as_ptr());
    AppendMenuW(menu, MF_SEPARATOR, 0, null());
    AppendMenuW(menu, MF_STRING, CMD_TRAY_EXIT, s5.as_ptr());
    SetForegroundWindow(hwnd);
    TrackPopupMenu(menu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, null());
    DestroyMenu(menu);
}

unsafe extern "system" fn wnd_proc(hwnd: Hwnd, msg: u32, wp: usize, lp: isize) -> isize {
    match msg {
        WM_SIZE => {
            APP.with(|cell| {
                let st = cell.borrow();
                if !st.wv2_ctrl.is_null() {
                    let rc = Rect {
                        left: 0,
                        top: 0,
                        right: (lp & 0xFFFF) as i16 as i32,
                        bottom: ((lp >> 16) & 0xFFFF) as i16 as i32,
                    };
                    ((*(*st.wv2_ctrl)).put_bounds)(st.wv2_ctrl, &rc);
                }
            });
            0
        }
        WM_PAINT => {
            let mut ps: PaintStruct = zeroed();
            let hdc = BeginPaint(hwnd, &mut ps);
            let mut rc = Rect::default();
            GetClientRect(hwnd, &mut rc);
            let bg = CreateSolidBrush(15 | (17 << 8) | (23 << 16));
            FillRect(hdc, &rc, bg);
            DeleteObject(bg);
            SetBkMode(hdc, 1);
            SetTextColor(hdc, 243 | (244 << 8) | (246 << 16));
            let hr = APP.with(|cell| cell.borrow().wv2_last_hr);
            let txt = if hr < 0 {
                format!("WebView2 initialization failed (HRESULT 0x{:08X}).", hr as u32)
            } else {
                "Loading Mouse Battery & Control v3.0.0...".to_string()
            };
            let w = to_wide(&txt);
            DrawTextW(hdc, w.as_ptr(), -1, &mut rc, 0x01 | 0x04 | 0x10);
            EndPaint(hwnd, &ps);
            0
        }
        WM_TIMER => {
            APP.with(|cell| {
                let mut st = cell.borrow_mut();
                if wp == TIMER_TICK_1S {
                    read_os_mouse_state(&mut st);
                    if st.idle_seconds < 15.0 {
                        st.pending_active_secs += 1.0;
                    }
                    if st.cfg.accel_mode == "Auto" {
                        let desired_accel = !is_foreground_game(&st.cfg.auto_games);
                        if st.last_game_accel_state != Some(desired_accel) {
                            set_enhance_pointer_precision(desired_accel);
                            st.last_game_accel_state = Some(desired_accel);
                        }
                    }
                    if IsWindowVisible(hwnd) != 0 && !st.wv2_view.is_null() {
                        push_state_to_webview(&mut st);
                    }
                } else if wp == TIMER_POLL {
                    refresh_battery_and_eval(&mut st, true, true);
                    if IsWindowVisible(hwnd) != 0 && !st.wv2_view.is_null() {
                        push_state_to_webview(&mut st);
                    }
                }
            });
            0
        }
        WM_TRAYICON => {
            let ev = (lp & 0xFFFF) as u32;
            if ev == WM_LBUTTONUP {
                if IsWindowVisible(hwnd) != 0 {
                    destroy_webview_host_detached();
                    ShowWindow(hwnd, SW_HIDE);
                } else {
                    ShowWindow(hwnd, SW_SHOW);
                    SetForegroundWindow(hwnd);
                    create_webview_host_detached();
                }
            } else if ev == WM_RBUTTONUP {
                show_tray_context_menu(hwnd);
            }
            0
        }
        WM_COMMAND => {
            let cmd = wp & 0xFFFF;
            match cmd {
                CMD_TRAY_OPEN => {
                    ShowWindow(hwnd, SW_SHOW);
                    SetForegroundWindow(hwnd);
                    create_webview_host_detached();
                }
                CMD_TRAY_REFRESH => {
                    APP.with(|cell| {
                        let mut st = cell.borrow_mut();
                        refresh_battery_and_eval(&mut st, false, false);
                        if IsWindowVisible(hwnd) != 0 && !st.wv2_view.is_null() {
                            push_state_to_webview(&mut st);
                        }
                    });
                }
                CMD_TRAY_TEST => handle_web_message("{\"cmd\":\"test_toast\"}"),
                CMD_TRAY_GHUB => { open_lghub(hwnd); }
                CMD_TRAY_EXIT => {
                    destroy_webview_host_detached();
                    APP.with(|cell| sync_tray_icon(&mut cell.borrow_mut(), true));
                    DestroyWindow(hwnd);
                }
                _ => {}
            }
            0
        }
        WM_CLOSE => {
            let hide = APP.with(|cell| {
                let st = cell.borrow();
                !st.smoke_test && st.cfg.close_to_tray
            });
            destroy_webview_host_detached();
            if hide {
                ShowWindow(hwnd, SW_HIDE);
            } else {
                APP.with(|cell| sync_tray_icon(&mut cell.borrow_mut(), true));
                DestroyWindow(hwnd);
            }
            0
        }
        WM_DESTROY => {
            destroy_webview_host_detached();
            APP.with(|cell| sync_tray_icon(&mut cell.borrow_mut(), true));
            PostQuitMessage(0);
            0
        }
        _ => DefWindowProcW(hwnd, msg, wp, lp),
    }
}

fn main() {
    let start_instant = Instant::now();
    let smoke_test = env::args().any(|a| a == "--smoke-test");

    unsafe {
        CoInitializeEx(null_mut(), 2);
        let user32_name = to_wide("user32.dll");
        let u32_mod = GetModuleHandleW(user32_name.as_ptr());
        if !u32_mod.is_null() {
            let p_dpi = GetProcAddress(u32_mod, b"SetProcessDpiAwarenessContext\0".as_ptr());
            if !p_dpi.is_null() {
                let set_dpi: unsafe extern "system" fn(Handle) -> i32 = std::mem::transmute(p_dpi);
                set_dpi((-4isize) as Handle);
            }
        }
    }

    let exe_bytes = env::current_exe().ok().and_then(|p| fs::metadata(p).ok()).map(|m| m.len()).unwrap_or(0);

    APP.with(|cell| {
        let mut st = cell.borrow_mut();
        st.smoke_test = smoke_test;
        st.exe_bytes = exe_bytes;
        st.start_instant = Some(start_instant);
        st.cfg = load_config();
        st.alert_state = load_state();
        refresh_battery_and_eval(&mut st, false, false);
    });

    let hwnd = unsafe {
        let hinst = GetModuleHandleW(null());
        let cls = to_wide("MBC_v3_RustWebView2_Wnd");
        let app_ico = LoadIconW(hinst, 1usize as *const u16);
        let icon = if app_ico.is_null() { LoadIconW(null_mut(), 32512usize as *const u16) } else { app_ico };
        let wc = WndClassExW {
            cb_size: size_of::<WndClassExW>() as u32,
            lpfn_wnd_proc: Some(wnd_proc),
            h_instance: hinst,
            h_icon: icon,
            h_icon_sm: icon,
            h_cursor: LoadCursorW(null_mut(), 32512usize as *const u16),
            lpsz_class_name: cls.as_ptr(),
            ..zeroed()
        };
        RegisterClassExW(&wc);

        let style = WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_THICKFRAME | WS_MAXIMIZEBOX;
        let mut dpi = 96i32;
        let user32_name = to_wide("user32.dll");
        let u32_mod = GetModuleHandleW(user32_name.as_ptr());
        if !u32_mod.is_null() {
            let p_sys = GetProcAddress(u32_mod, b"GetDpiForSystem\0".as_ptr());
            if !p_sys.is_null() {
                let get_dpi: unsafe extern "system" fn() -> u32 = std::mem::transmute(p_sys);
                dpi = get_dpi() as i32;
            }
        }
        let mut wr = Rect {
            left: 0,
            top: 0,
            right: MulDiv(680, dpi, 96),
            bottom: MulDiv(820, dpi, 96),
        };
        AdjustWindowRectEx(&mut wr, style, 0, 0);

        let title = to_wide("Mouse Battery & Control v3.0.0");
        CreateWindowExW(
            0,
            cls.as_ptr(),
            title.as_ptr(),
            style,
            if smoke_test { 5000 } else { CW_USEDEFAULT },
            if smoke_test { 5000 } else { CW_USEDEFAULT },
            wr.right - wr.left,
            wr.bottom - wr.top,
            null_mut(),
            null_mut(),
            hinst,
            null_mut(),
        )
    };

    APP.with(|cell| {
        let mut st = cell.borrow_mut();
        st.hwnd = hwnd;
        sync_titlebar_theme(&st);
        sync_tray_icon(&mut st, false);
    });

    if smoke_test {
        let dll = find_embedded_browser_webview_dll();
        let wv2_found = dll.is_some();
        let mut wv2_entry = false;
        if let Some(dpath) = dll {
            unsafe {
                let wd = to_wide(&dpath);
                let hm = LoadLibraryExW(wd.as_ptr(), null_mut(), LOAD_WITH_ALTERED_SEARCH_PATH);
                if !hm.is_null() {
                    wv2_entry = !GetProcAddress(hm, b"CreateWebViewEnvironmentWithOptionsInternal\0".as_ptr()).is_null();
                    FreeLibrary(hm);
                }
            }
        }
        APP.with(|cell| {
            let mut st = cell.borrow_mut();
            measure_memory(&mut st);
            let pct = st.active_dev.percentage.unwrap_or(0.0);
            let line = format!(
                "{{\"variant\": \"MouseBatteryControl_v3_Rust_WebView2\", \"version\": \"{}\", \"exe_bytes\": {}, \"ws_kb\": {}, \"priv_kb\": {}, \"battery_pct\": {:.1}, \"samples\": {}, \"wv2_dll_found\": {}, \"wv2_entry_found\": {}, \"ok\": true}}",
                APP_VERSION, st.exe_bytes, st.ws_kb, st.priv_kb, pct, st.history.len(), wv2_found, wv2_entry
            );
            let mut out = io::stdout().lock();
            let _ = writeln!(out, "{}", line);
            let _ = out.flush();
            sync_tray_icon(&mut st, true);
        });
        unsafe { DestroyWindow(hwnd); }
    } else {
        unsafe {
            ShowWindow(hwnd, SW_SHOWNORMAL);
            UpdateWindow(hwnd);
        }
        create_webview_host_detached();
        APP.with(|cell| reset_poll_timer(&cell.borrow()));
        unsafe {
            SetTimer(hwnd, TIMER_TICK_1S, 1000, null());
            let mut msg: Msg = zeroed();
            while GetMessageW(&mut msg, null_mut(), 0, 0) > 0 {
                TranslateMessage(&msg);
                DispatchMessageW(&msg);
            }
        }
    }

    APP.with(|cell| {
        let mut st = cell.borrow_mut();
        st.hidpp.close();
        if !st.wv2_module.is_null() {
            unsafe { FreeLibrary(st.wv2_module); }
            st.wv2_module = null_mut();
        }
    });
    unsafe { CoUninitialize(); }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_roundtrip_escapes() {
        let obj = JsonVal::Obj(vec![
            ("msg".into(), JsonVal::Str("hello \"world\"\nline2".into())),
            ("num".into(), JsonVal::Num(85.5)),
            ("ok".into(), JsonVal::Bool(true)),
        ]);
        let s = obj.to_compact_string();
        let parsed = parse_json(&s).expect("parse");
        assert_eq!(parsed.get("msg").and_then(|v| v.as_str()), Some("hello \"world\"\nline2"));
        assert_eq!(parsed.get("num").and_then(|v| v.as_f64()), Some(85.5));
        assert_eq!(parsed.get("ok").and_then(|v| v.as_bool()), Some(true));
    }

    #[test]
    fn config_strict_rejects_bad_evening_hour_and_nonnumeric_poll() {
        let base = AppConfig::default();
        let bad_hr = parse_json("{\"evening_hour\": 24}").unwrap();
        assert!(validate_config(&bad_hr, &base, true).is_err());

        let bad_poll = parse_json("{\"poll_interval_minutes\": \"five\"}").unwrap();
        assert!(validate_config(&bad_poll, &base, true).is_err());

        let bad_crit = parse_json("{\"low_battery_threshold\": 15, \"critical_battery_threshold\": 25}").unwrap();
        assert!(validate_config(&bad_crit, &base, true).is_err());
    }

    #[test]
    fn atomic_write_preserves_valid_content() {
        let tmp = env::temp_dir().join("mbc_rust_atomic_test.json");
        atomic_write_text(&tmp, "{\"ok\":true}\n").expect("write 1");
        atomic_write_text(&tmp, "{\"ok\":false}\n").expect("write 2");
        let got = fs::read_to_string(&tmp).expect("read");
        let _ = fs::remove_file(&tmp);
        assert_eq!(got, "{\"ok\":false}\n");
    }

    #[test]
    fn drain_rate_and_health_calculations() {
        let t1 = monitor::now_epoch_secs();
        let t0 = t1 - 7200.0;
        let hist = vec![
            HistoryRec { ts: "2026-11-20T10:00:00+00:00".into(), ts_sec: t0, device: "g502".into(), pct: 90.0, charging: false, rate_hz: Some(1000), active_s: None },
            HistoryRec { ts: "2026-11-20T12:00:00+00:00".into(), ts_sec: t1, device: "g502".into(), pct: 86.0, charging: false, rate_hz: Some(1000), active_s: Some(3600.0) },
        ];
        let (rate, learned, sess) = monitor::estimate_drain_rate("g502", &hist, 1.5, Some(1000));
        assert!(learned);
        assert_eq!(sess, 1);
        assert!((rate - 2.0).abs() < 0.05);

        let health = monitor::compute_battery_health("g502", &hist, 500, true);
        assert_eq!(health.status, "calibrating");
        assert!((health.charge_cycles - 0.04).abs() < 0.001);
    }

    #[test]
    fn version_ordering() {
        assert!(updater::parse_version("v3.0.1") > updater::parse_version("3.0.0"));
        assert_eq!(updater::parse_version("3.0.0"), updater::parse_version("v3.0.0"));
    }
}
