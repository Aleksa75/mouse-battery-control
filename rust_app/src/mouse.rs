use std::env;
use std::ffi::c_void;
use std::mem::size_of;
use std::path::{Path, PathBuf};
use std::ptr::{null, null_mut};

pub type Handle = *mut c_void;
pub type Hwnd = Handle;

#[allow(dead_code)]
const SPI_GETMOUSE: u32 = 0x0003;
const SPI_SETMOUSE: u32 = 0x0004;
const SPI_GETWHEELSCROLLLINES: u32 = 0x0068;
const SPI_SETWHEELSCROLLLINES: u32 = 0x0069;
const SPI_GETMOUSESPEED: u32 = 0x0070;
const SPI_SETMOUSESPEED: u32 = 0x0071;
const SPIF_FLAGS: u32 = 0x01 | 0x02;
const SM_SWAPBUTTON: i32 = 23;
const RIDI_DEVICENAME: u32 = 0x20000007;
const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;

const HKEY_CURRENT_USER: Handle = (-2147483647i32 as isize) as Handle;
const KEY_READ: u32 = 0x20019;
const KEY_SET_VALUE: u32 = 0x0002;
const REG_SZ: u32 = 1;
const REG_BINARY: u32 = 3;
const REG_DWORD: u32 = 4;

const GAME_PATH_MARKERS: [&str; 9] = [
    "steamapps\\common",
    "epic games\\",
    "riot games\\",
    "ubisoft game launcher\\",
    "ea games\\",
    "origin games\\",
    "gog galaxy\\games",
    "xboxgames\\",
    "battle.net\\",
];

#[repr(C)]
struct LastInputInfo {
    cb_size: u32,
    dw_time: u32,
}

#[repr(C)]
#[derive(Clone, Copy)]
struct RawInputDeviceList {
    h_device: Handle,
    dw_type: u32,
}

#[repr(C)]
struct OpenFileNameW {
    l_struct_size: u32,
    hwnd_owner: Hwnd,
    h_instance: Handle,
    lpstr_filter: *const u16,
    lpstr_custom_filter: *mut u16,
    n_max_cust_filter: u32,
    n_filter_index: u32,
    lpstr_file: *mut u16,
    n_max_file: u32,
    lpstr_file_title: *mut u16,
    n_max_file_title: u32,
    lpstr_initial_dir: *const u16,
    lpstr_title: *const u16,
    flags: u32,
    n_file_offset: u16,
    n_file_extension: u16,
    lpstr_def_ext: *const u16,
    l_cust_data: isize,
    lpfn_hook: *const c_void,
    lp_template_name: *const u16,
    pv_reserved: *mut c_void,
    dw_reserved: u32,
    flags_ex: u32,
}

#[link(name = "user32")]
extern "system" {
    fn SystemParametersInfoW(action: u32, param: u32, pv: *mut c_void, win_ini: u32) -> i32;
    fn GetSystemMetrics(idx: i32) -> i32;
    fn SwapMouseButton(swap: i32) -> i32;
    fn GetLastInputInfo(lii: *mut LastInputInfo) -> i32;
    fn GetRawInputDeviceList(list: *mut RawInputDeviceList, num: *mut u32, sz: u32) -> u32;
    fn GetRawInputDeviceInfoW(dev: Handle, cmd: u32, data: *mut u16, sz: *mut u32) -> u32;
    fn GetForegroundWindow() -> Hwnd;
    fn GetWindowThreadProcessId(hwnd: Hwnd, pid: *mut u32) -> u32;
}

#[link(name = "kernel32")]
extern "system" {
    fn GetTickCount() -> u32;
    fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
    fn QueryFullProcessImageNameW(proc_h: Handle, flags: u32, exe_name: *mut u16, sz: *mut u32) -> i32;
    fn CloseHandle(h: Handle) -> i32;
}

#[link(name = "advapi32")]
extern "system" {
    fn RegOpenKeyExW(hkey: Handle, subkey: *const u16, opts: u32, sam: u32, out: *mut Handle) -> i32;
    fn RegQueryValueExW(hkey: Handle, name: *const u16, res: *mut u32, rtype: *mut u32, data: *mut u8, sz: *mut u32) -> i32;
    fn RegSetValueExW(hkey: Handle, name: *const u16, res: u32, rtype: u32, data: *const u8, sz: u32) -> i32;
    fn RegDeleteValueW(hkey: Handle, name: *const u16) -> i32;
    fn RegCloseKey(hkey: Handle) -> i32;
}

#[link(name = "shell32")]
extern "system" {
    fn ShellExecuteW(hwnd: Hwnd, op: *const u16, file: *const u16, params: *const u16, dir: *const u16, show: i32) -> Handle;
}

#[link(name = "comdlg32")]
extern "system" {
    fn GetOpenFileNameW(ofn: *mut OpenFileNameW) -> i32;
    fn GetSaveFileNameW(ofn: *mut OpenFileNameW) -> i32;
}

pub fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

pub fn get_pointer_speed() -> i32 {
    let mut spd = 10u32;
    unsafe { SystemParametersInfoW(SPI_GETMOUSESPEED, 0, &mut spd as *mut u32 as *mut c_void, 0); }
    (spd as i32).clamp(1, 20)
}

pub fn set_pointer_speed(spd: i32) {
    let v = spd.clamp(1, 20);
    unsafe { SystemParametersInfoW(SPI_SETMOUSESPEED, 0, v as usize as *mut c_void, SPIF_FLAGS); }
}

pub fn get_wheel_scroll_lines() -> i32 {
    let mut lines = 3u32;
    unsafe { SystemParametersInfoW(SPI_GETWHEELSCROLLLINES, 0, &mut lines as *mut u32 as *mut c_void, 0); }
    (lines as i32).clamp(1, 20)
}

pub fn set_wheel_scroll_lines(lines: i32) {
    let v = lines.clamp(1, 20);
    unsafe { SystemParametersInfoW(SPI_SETWHEELSCROLLLINES, v as u32, null_mut(), SPIF_FLAGS); }
}

#[allow(dead_code)]
pub fn get_enhance_pointer_precision() -> bool {
    let mut p = [0i32; 3];
    unsafe { SystemParametersInfoW(SPI_GETMOUSE, 0, p.as_mut_ptr() as *mut c_void, 0); }
    p[2] != 0
}

pub fn set_enhance_pointer_precision(enabled: bool) {
    let mut p = if enabled { [6i32, 10, 1] } else { [0i32, 0, 0] };
    unsafe { SystemParametersInfoW(SPI_SETMOUSE, 0, p.as_mut_ptr() as *mut c_void, SPIF_FLAGS); }
}

pub fn get_swap_buttons() -> bool {
    unsafe { GetSystemMetrics(SM_SWAPBUTTON) != 0 }
}

pub fn set_swap_buttons(swapped: bool) {
    unsafe { SwapMouseButton(if swapped { 1 } else { 0 }); }
    let sub = to_wide("Control Panel\\Mouse");
    let val = to_wide("SwapMouseButtons");
    let data = to_wide(if swapped { "1" } else { "0" });
    let mut hk: Handle = null_mut();
    unsafe {
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_SET_VALUE, &mut hk) == 0 {
            RegSetValueExW(hk, val.as_ptr(), 0, REG_SZ, data.as_ptr() as *const u8, (data.len() * 2) as u32);
            RegCloseKey(hk);
        }
    }
}

pub fn get_idle_seconds() -> f64 {
    unsafe {
        let mut lii = LastInputInfo {
            cb_size: size_of::<LastInputInfo>() as u32,
            dw_time: 0,
        };
        if GetLastInputInfo(&mut lii) != 0 {
            return GetTickCount().wrapping_sub(lii.dw_time) as f64 / 1000.0;
        }
    }
    0.0
}

pub fn get_foreground_exe_path() -> Option<String> {
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.is_null() {
            return None;
        }
        let mut pid = 0u32;
        GetWindowThreadProcessId(hwnd, &mut pid);
        if pid == 0 {
            return None;
        }
        let hp = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if hp.is_null() {
            return None;
        }
        let mut buf = [0u16; 512];
        let mut len = buf.len() as u32;
        let ok = QueryFullProcessImageNameW(hp, 0, buf.as_mut_ptr(), &mut len);
        CloseHandle(hp);
        if ok != 0 && len > 0 {
            return Some(String::from_utf16_lossy(&buf[..len as usize]));
        }
    }
    None
}

pub fn is_foreground_game(auto_games: &[String]) -> bool {
    let Some(exe) = get_foreground_exe_path() else {
        return false;
    };
    let low = exe.to_ascii_lowercase();
    if GAME_PATH_MARKERS.iter().any(|m| low.contains(m)) {
        return true;
    }
    let fname = Path::new(&low).file_name().and_then(|s| s.to_str()).unwrap_or("");
    auto_games.iter().any(|g| {
        let gl = g.to_ascii_lowercase();
        gl == low || gl == fname
    })
}

pub fn detect_connection_type(is_charging: bool) -> (String, String) {
    unsafe {
        let mut num = 0u32;
        let sz_s = size_of::<RawInputDeviceList>() as u32;
        GetRawInputDeviceList(null_mut(), &mut num, sz_s);
        if num > 0 && num <= 256 {
            let mut list = vec![RawInputDeviceList { h_device: null_mut(), dw_type: 0 }; num as usize];
            if GetRawInputDeviceList(list.as_mut_ptr(), &mut num, sz_s) != u32::MAX {
                let mut found_ls = false;
                let mut found_wired = false;
                for d in &list {
                    let mut sz = 0u32;
                    GetRawInputDeviceInfoW(d.h_device, RIDI_DEVICENAME, null_mut(), &mut sz);
                    if sz > 0 && sz <= 1024 {
                        let mut buf = vec![0u16; sz as usize];
                        if GetRawInputDeviceInfoW(d.h_device, RIDI_DEVICENAME, buf.as_mut_ptr(), &mut sz) > 0 {
                            let up = String::from_utf16_lossy(&buf).to_ascii_uppercase();
                            if up.contains("VID_046D") {
                                if ["PID_C547", "PID_C548", "PID_C539", "PID_C53F", "PID_C541"]
                                    .iter()
                                    .any(|p| up.contains(p))
                                {
                                    found_ls = true;
                                } else if ["PID_C094", "PID_C095", "PID_C092", "PID_C08B"]
                                    .iter()
                                    .any(|p| up.contains(p))
                                {
                                    found_wired = true;
                                }
                            }
                        }
                    }
                }
                if found_wired && !found_ls {
                    return ("usb".into(), "USB Wired".into());
                }
                if found_ls {
                    return (
                        "lightspeed".into(),
                        if is_charging {
                            "LIGHTSPEED (Charging via USB)".into()
                        } else {
                            "LIGHTSPEED".into()
                        },
                    );
                }
            }
        }
    }
    ("lightspeed".into(), if is_charging { "LIGHTSPEED (Charging via USB)".into() } else { "LIGHTSPEED".into() })
}

pub fn get_autostart_enabled() -> bool {
    let sub = to_wide("Software\\Microsoft\\Windows\\CurrentVersion\\Run");
    let val = to_wide("MouseBatteryTray");
    let mut hk: Handle = null_mut();
    unsafe {
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_READ, &mut hk) == 0 {
            let mut sz = 0u32;
            let rc = RegQueryValueExW(hk, val.as_ptr(), null_mut(), null_mut(), null_mut(), &mut sz);
            RegCloseKey(hk);
            return rc == 0 && sz > 0;
        }
    }
    false
}

pub fn set_autostart_enabled(enabled: bool) -> bool {
    let sub = to_wide("Software\\Microsoft\\Windows\\CurrentVersion\\Run");
    let val = to_wide("MouseBatteryTray");
    let mut hk: Handle = null_mut();
    unsafe {
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_SET_VALUE, &mut hk) != 0 {
            return false;
        }
        let ok = if enabled {
            let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("MouseBatteryControl.exe"));
            let cmd = format!("\"{}\"", exe.to_string_lossy());
            let wcmd = to_wide(&cmd);
            RegSetValueExW(hk, val.as_ptr(), 0, REG_SZ, wcmd.as_ptr() as *const u8, (wcmd.len() * 2) as u32) == 0
        } else {
            let rc = RegDeleteValueW(hk, val.as_ptr());
            rc == 0 || rc == 2 // ERROR_FILE_NOT_FOUND
        };
        RegCloseKey(hk);
        ok
    }
}

pub fn is_windows_light_theme() -> bool {
    let sub = to_wide("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize");
    let val = to_wide("AppsUseLightTheme");
    let mut hk: Handle = null_mut();
    unsafe {
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub.as_ptr(), 0, KEY_READ, &mut hk) == 0 {
            let mut dw = 0u32;
            let mut rtype = 0u32;
            let mut sz = 4u32;
            let rc = RegQueryValueExW(hk, val.as_ptr(), null_mut(), &mut rtype, &mut dw as *mut u32 as *mut u8, &mut sz);
            RegCloseKey(hk);
            if rc == 0 && rtype == REG_DWORD {
                return dw != 0;
            }
        }
    }
    false
}

pub fn read_windows_accent_hex() -> Option<String> {
    let sub_acc = to_wide("Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Accent");
    let val_pal = to_wide("AccentPalette");
    let mut hk: Handle = null_mut();
    unsafe {
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub_acc.as_ptr(), 0, KEY_READ, &mut hk) == 0 {
            let mut buf = [0u8; 64];
            let mut rtype = 0u32;
            let mut sz = buf.len() as u32;
            let rc = RegQueryValueExW(hk, val_pal.as_ptr(), null_mut(), &mut rtype, buf.as_mut_ptr(), &mut sz);
            RegCloseKey(hk);
            if rc == 0 && rtype == REG_BINARY && sz >= 15 {
                return Some(format!("#{:02X}{:02X}{:02X}", buf[12], buf[13], buf[14]));
            }
        }
        let sub_dwm = to_wide("Software\\Microsoft\\Windows\\DWM");
        let val_dwm = to_wide("AccentColor");
        if RegOpenKeyExW(HKEY_CURRENT_USER, sub_dwm.as_ptr(), 0, KEY_READ, &mut hk) == 0 {
            let mut dw = 0u32;
            let mut rtype = 0u32;
            let mut sz = 4u32;
            let rc = RegQueryValueExW(hk, val_dwm.as_ptr(), null_mut(), &mut rtype, &mut dw as *mut u32 as *mut u8, &mut sz);
            RegCloseKey(hk);
            if rc == 0 && rtype == REG_DWORD {
                let r = dw & 0xFF;
                let g = (dw >> 8) & 0xFF;
                let b = (dw >> 16) & 0xFF;
                return Some(format!("#{:02X}{:02X}{:02X}", r, g, b));
            }
        }
    }
    None
}

pub fn open_lghub(hwnd: Hwnd) -> bool {
    let mut cands = Vec::new();
    if let Ok(pf) = env::var("ProgramFiles") {
        cands.push(PathBuf::from(pf).join("LGHUB").join("lghub.exe"));
    }
    if let Ok(la) = env::var("LOCALAPPDATA") {
        cands.push(PathBuf::from(la).join("LGHUB").join("lghub.exe"));
    }
    for c in cands {
        if c.is_file() {
            let op = to_wide("open");
            let file = to_wide(&c.to_string_lossy());
            unsafe { ShellExecuteW(hwnd, op.as_ptr(), file.as_ptr(), null(), null(), 1); }
            return true;
        }
    }
    false
}

pub fn open_folder(hwnd: Hwnd, dir: &Path) {
    let op = to_wide("open");
    let path = to_wide(&dir.to_string_lossy());
    unsafe { ShellExecuteW(hwnd, op.as_ptr(), path.as_ptr(), null(), null(), 1); }
}

pub fn open_url(hwnd: Hwnd, url: &str) {
    let op = to_wide("open");
    let u = to_wide(url);
    unsafe { ShellExecuteW(hwnd, op.as_ptr(), u.as_ptr(), null(), null(), 1); }
}

pub fn pick_file_dialog(hwnd: Hwnd, save: bool, title: &str, filter_pairs: &[(&str, &str)], default_name: &str, def_ext: &str) -> Option<PathBuf> {
    let mut filter_w: Vec<u16> = Vec::new();
    for (desc, pat) in filter_pairs {
        filter_w.extend(desc.encode_utf16());
        filter_w.push(0);
        filter_w.extend(pat.encode_utf16());
        filter_w.push(0);
    }
    filter_w.push(0);

    let mut file_buf = [0u16; 1024];
    for (i, ch) in default_name.encode_utf16().take(1000).enumerate() {
        file_buf[i] = ch;
    }
    let title_w = to_wide(title);
    let ext_w = to_wide(def_ext);

    let mut ofn = OpenFileNameW {
        l_struct_size: size_of::<OpenFileNameW>() as u32,
        hwnd_owner: hwnd,
        h_instance: null_mut(),
        lpstr_filter: filter_w.as_ptr(),
        lpstr_custom_filter: null_mut(),
        n_max_cust_filter: 0,
        n_filter_index: 1,
        lpstr_file: file_buf.as_mut_ptr(),
        n_max_file: file_buf.len() as u32,
        lpstr_file_title: null_mut(),
        n_max_file_title: 0,
        lpstr_initial_dir: null(),
        lpstr_title: title_w.as_ptr(),
        flags: if save { 0x00000002 | 0x00000800 } else { 0x00001000 | 0x00000800 }, // OVERWRITEPROMPT / FILEMUSTEXIST | PATHMUSTEXIST
        n_file_offset: 0,
        n_file_extension: 0,
        lpstr_def_ext: ext_w.as_ptr(),
        l_cust_data: 0,
        lpfn_hook: null(),
        lp_template_name: null(),
        pv_reserved: null_mut(),
        dw_reserved: 0,
        flags_ex: 0,
    };

    let ok = unsafe {
        if save {
            GetSaveFileNameW(&mut ofn)
        } else {
            GetOpenFileNameW(&mut ofn)
        }
    };
    if ok == 0 {
        return None;
    }
    let len = file_buf.iter().position(|&c| c == 0).unwrap_or(file_buf.len());
    Some(PathBuf::from(String::from_utf16_lossy(&file_buf[..len])))
}
