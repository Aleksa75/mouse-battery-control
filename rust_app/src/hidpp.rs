use std::collections::HashSet;
use std::ffi::c_void;
use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};

use crate::config::exe_dir;
use crate::mouse::to_wide;

pub type Handle = *mut c_void;

pub const LOGITECH_VID: u16 = 0x046D;
const HIDPP_LONG_REPORT_ID: u8 = 0x11;
const HIDPP_LONG_LEN: usize = 20;
const SW_ID: u8 = 0x0A;

const FEAT_FW_VERSION: u16 = 0x0003;
const FEAT_DEVICE_NAME: u16 = 0x0005;
const FEAT_BATTERY_STATUS: u16 = 0x1000;
const FEAT_UNIFIED_BATTERY: u16 = 0x1004;
const FEAT_ADJUSTABLE_DPI: u16 = 0x2201;
const FEAT_REPORT_RATE: u16 = 0x8060;
const FEAT_RGB_EFFECTS: u16 = 0x8071;
const FEAT_PERKEY_LIGHTING: u16 = 0x8081;
const FEAT_ONBOARD_PROFILES: u16 = 0x8100;

const DIGCF_PRESENT: u32 = 0x00000002;
const DIGCF_DEVICEINTERFACE: u32 = 0x00000010;
const GENERIC_READ: u32 = 0x80000000;
const GENERIC_WRITE: u32 = 0x40000000;
const FILE_SHARE_READ: u32 = 0x00000001;
const FILE_SHARE_WRITE: u32 = 0x00000002;
const OPEN_EXISTING: u32 = 3;
const FILE_FLAG_OVERLAPPED: u32 = 0x40000000;
const INVALID_HANDLE: Handle = (-1isize) as Handle;

#[repr(C)]
#[derive(Clone, Copy, Default)]
struct Guid {
    d1: u32,
    d2: u16,
    d3: u16,
    d4: [u8; 8],
}

#[repr(C)]
struct SpDeviceInterfaceData {
    cb_size: u32,
    interface_class_guid: Guid,
    flags: u32,
    reserved: usize,
}

#[repr(C)]
struct HiddAttributes {
    size: u32,
    vendor_id: u16,
    product_id: u16,
    version_number: u16,
}

#[repr(C)]
struct Overlapped {
    internal: usize,
    internal_high: usize,
    offset: u32,
    offset_high: u32,
    h_event: Handle,
}

#[link(name = "hid")]
extern "system" {
    fn HidD_GetHidGuid(hid_guid: *mut Guid);
    fn HidD_GetAttributes(hid_dev: Handle, attrs: *mut HiddAttributes) -> u8;
    fn HidD_GetPreparsedData(hid_dev: Handle, pp_data: *mut Handle) -> u8;
    fn HidD_FreePreparsedData(pp_data: Handle) -> u8;
    fn HidD_GetProductString(hid_dev: Handle, buf: *mut u16, buf_bytes: u32) -> u8;
    fn HidP_GetCaps(pp_data: Handle, caps_buf: *mut u16) -> i32;
}

#[link(name = "setupapi")]
extern "system" {
    fn SetupDiGetClassDevsW(class_guid: *const Guid, enumerator: *const u16, hwnd: Handle, flags: u32) -> Handle;
    fn SetupDiEnumDeviceInterfaces(info: Handle, dev_info: *mut c_void, guid: *const Guid, idx: u32, if_data: *mut SpDeviceInterfaceData) -> i32;
    fn SetupDiGetDeviceInterfaceDetailW(info: Handle, if_data: *const SpDeviceInterfaceData, detail: *mut u8, sz: u32, req_sz: *mut u32, dev_info: *mut c_void) -> i32;
    fn SetupDiDestroyDeviceInfoList(info: Handle) -> i32;
}

#[link(name = "kernel32")]
extern "system" {
    fn CreateFileW(name: *const u16, access: u32, share: u32, sa: *mut c_void, disp: u32, flags: u32, tmpl: Handle) -> Handle;
    fn ReadFile(h: Handle, buf: *mut u8, to_read: u32, read: *mut u32, ov: *mut Overlapped) -> i32;
    fn WriteFile(h: Handle, buf: *const u8, to_write: u32, written: *mut u32, ov: *mut Overlapped) -> i32;
    fn CreateEventW(sa: *mut c_void, manual_reset: i32, initial: i32, name: *const u16) -> Handle;
    fn WaitForSingleObject(h: Handle, ms: u32) -> u32;
    fn GetOverlappedResult(h: Handle, ov: *mut Overlapped, bytes: *mut u32, wait: i32) -> i32;
    fn CancelIoEx(h: Handle, ov: *mut Overlapped) -> i32;
    fn CloseHandle(h: Handle) -> i32;
    fn GetLastError() -> u32;
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
struct HidInterfaceInfo {
    path_w: Vec<u16>,
    path_key: String,
    product_name: String,
    vendor_id: u16,
    product_id: u16,
    usage_page: u16,
    usage: u16,
}

fn enumerate_logitech_hidpp_interfaces() -> Vec<HidInterfaceInfo> {
    let mut out = Vec::new();
    unsafe {
        let mut hid_guid = Guid::default();
        HidD_GetHidGuid(&mut hid_guid);
        let hinfo = SetupDiGetClassDevsW(&hid_guid, null(), null_mut(), DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        if hinfo.is_null() || hinfo == INVALID_HANDLE {
            return out;
        }

        let mut idx = 0u32;
        loop {
            let mut if_data: SpDeviceInterfaceData = zeroed();
            if_data.cb_size = size_of::<SpDeviceInterfaceData>() as u32;
            if SetupDiEnumDeviceInterfaces(hinfo, null_mut(), &hid_guid, idx, &mut if_data) == 0 {
                break;
            }
            idx += 1;

            let mut req_sz = 0u32;
            SetupDiGetDeviceInterfaceDetailW(hinfo, &if_data, null_mut(), 0, &mut req_sz, null_mut());
            if req_sz <= 8 || req_sz > 4096 {
                continue;
            }
            let mut detail_buf = vec![0u8; req_sz as usize];
            // x64 SP_DEVICE_INTERFACE_DETAIL_DATA_W cbSize is 8 bytes
            detail_buf[0] = 8;
            if SetupDiGetDeviceInterfaceDetailW(
                hinfo,
                &if_data,
                detail_buf.as_mut_ptr(),
                req_sz,
                &mut req_sz,
                null_mut(),
            ) == 0
            {
                continue;
            }

            let path_u16_len = (detail_buf.len() - 4) / 2;
            let mut path_w = Vec::with_capacity(path_u16_len);
            for i in 0..path_u16_len {
                let code = u16::from_le_bytes([detail_buf[4 + i * 2], detail_buf[4 + i * 2 + 1]]);
                path_w.push(code);
                if code == 0 {
                    break;
                }
            }
            if path_w.last() != Some(&0) {
                path_w.push(0);
            }
            let path_key = String::from_utf16_lossy(&path_w[..path_w.len().saturating_sub(1)]);

            let h = CreateFileW(
                path_w.as_ptr(),
                0,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                null_mut(),
                OPEN_EXISTING,
                0,
                null_mut(),
            );
            if h.is_null() || h == INVALID_HANDLE {
                continue;
            }

            let mut attrs = HiddAttributes {
                size: size_of::<HiddAttributes>() as u32,
                vendor_id: 0,
                product_id: 0,
                version_number: 0,
            };
            let mut matched = false;
            let mut usage_page = 0u16;
            let mut usage = 0u16;
            let mut prod_name = String::new();

            if HidD_GetAttributes(h, &mut attrs) != 0 && attrs.vendor_id == LOGITECH_VID {
                let mut pp: Handle = null_mut();
                if HidD_GetPreparsedData(h, &mut pp) != 0 && !pp.is_null() {
                    let mut caps = [0u16; 64];
                    if HidP_GetCaps(pp, caps.as_mut_ptr()) >= 0 {
                        usage = caps[0];
                        usage_page = caps[1];
                        if usage_page >= 0xFF00 {
                            matched = true;
                        }
                    }
                    HidD_FreePreparsedData(pp);
                }
                if matched {
                    let mut pbuf = [0u16; 128];
                    if HidD_GetProductString(h, pbuf.as_mut_ptr(), (pbuf.len() * 2) as u32) != 0 {
                        let n = pbuf.iter().position(|&c| c == 0).unwrap_or(0);
                        prod_name = String::from_utf16_lossy(&pbuf[..n]).trim().to_string();
                    }
                }
            }
            CloseHandle(h);

            if matched {
                out.push(HidInterfaceInfo {
                    path_w,
                    path_key,
                    product_name: prod_name,
                    vendor_id: attrs.vendor_id,
                    product_id: attrs.product_id,
                    usage_page,
                    usage,
                });
            }
        }
        SetupDiDestroyDeviceInfoList(hinfo);
    }

    // Prefer usage == 2 (HID++ long reports) first
    out.sort_by_key(|i| if i.usage == 2 { 0 } else { 1 });
    out
}

fn open_overlapped_rw(path_w: &[u16]) -> Option<Handle> {
    let h = unsafe {
        CreateFileW(
            path_w.as_ptr(),
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            null_mut(),
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,
            null_mut(),
        )
    };
    if h.is_null() || h == INVALID_HANDLE {
        None
    } else {
        Some(h)
    }
}

fn write_packet_ov(h: Handle, pkt: &[u8; HIDPP_LONG_LEN], timeout_ms: u32) -> bool {
    unsafe {
        let ev = CreateEventW(null_mut(), 1, 0, null());
        if ev.is_null() {
            return false;
        }
        let mut ov: Overlapped = zeroed();
        ov.h_event = ev;
        let mut written = 0u32;
        let ok = WriteFile(h, pkt.as_ptr(), pkt.len() as u32, &mut written, &mut ov);
        let success = if ok != 0 {
            true
        } else if GetLastError() == 997 /*ERROR_IO_PENDING*/ {
            if WaitForSingleObject(ev, timeout_ms) == 0 {
                GetOverlappedResult(h, &mut ov, &mut written, 0) != 0
            } else {
                CancelIoEx(h, &mut ov);
                false
            }
        } else {
            false
        };
        CloseHandle(ev);
        success
    }
}

fn read_packet_ov(h: Handle, out: &mut [u8; HIDPP_LONG_LEN], timeout_ms: u32) -> Option<usize> {
    unsafe {
        let ev = CreateEventW(null_mut(), 1, 0, null());
        if ev.is_null() {
            return None;
        }
        let mut ov: Overlapped = zeroed();
        ov.h_event = ev;
        let mut read_n = 0u32;
        let ok = ReadFile(h, out.as_mut_ptr(), out.len() as u32, &mut read_n, &mut ov);
        let got = if ok != 0 {
            Some(read_n as usize)
        } else if GetLastError() == 997 {
            if WaitForSingleObject(ev, timeout_ms) == 0 && GetOverlappedResult(h, &mut ov, &mut read_n, 0) != 0 {
                Some(read_n as usize)
            } else {
                CancelIoEx(h, &mut ov);
                None
            }
        } else {
            None
        };
        CloseHandle(ev);
        got
    }
}

fn hidpp_request(h: Handle, dev_idx: u8, feat_idx: u8, func_id: u8, params: &[u8], timeout_ms: u32) -> Option<[u8; HIDPP_LONG_LEN]> {
    let mut pkt = [0u8; HIDPP_LONG_LEN];
    pkt[0] = HIDPP_LONG_REPORT_ID;
    pkt[1] = dev_idx;
    pkt[2] = feat_idx;
    pkt[3] = ((func_id & 0x0F) << 4) | SW_ID;
    for (i, &b) in params.iter().take(HIDPP_LONG_LEN - 4).enumerate() {
        pkt[4 + i] = b;
    }
    if !write_packet_ov(h, &pkt, timeout_ms) {
        return None;
    }
    for _ in 0..5 {
        let mut resp = [0u8; HIDPP_LONG_LEN];
        let Some(n) = read_packet_ov(h, &mut resp, timeout_ms) else {
            return None;
        };
        if n >= 4 && (resp[0] == 0x10 || resp[0] == 0x11) && resp[1] == dev_idx {
            if resp[2] == 0xFF {
                return None;
            }
            if resp[2] == feat_idx && (resp[3] & 0x0F) == SW_ID {
                return Some(resp);
            }
        }
    }
    None
}

fn read_device_name_0005(h: Handle, dev_idx: u8) -> (Option<String>, Option<u8>) {
    let Some(look) = hidpp_request(h, dev_idx, 0x00, 0x00, &[(FEAT_DEVICE_NAME >> 8) as u8, FEAT_DEVICE_NAME as u8], 100) else {
        return (None, None);
    };
    if look[4] == 0 {
        return (None, None);
    }
    let name_idx = look[4];
    let dev_type = hidpp_request(h, dev_idx, name_idx, 0x02, &[], 100).map(|r| r[4]);
    let Some(cnt_r) = hidpp_request(h, dev_idx, name_idx, 0x00, &[], 100) else {
        return (None, dev_type);
    };
    let char_count = (cnt_r[4] as usize).min(64);
    if char_count == 0 {
        return (None, dev_type);
    }
    let mut buf = Vec::new();
    let mut offset = 0u8;
    while buf.len() < char_count && (offset as usize) < 64 {
        let Some(cr) = hidpp_request(h, dev_idx, name_idx, 0x01, &[offset], 100) else {
            break;
        };
        let chunk = &cr[4..HIDPP_LONG_LEN];
        buf.extend_from_slice(chunk);
        offset = offset.saturating_add(chunk.len() as u8);
    }
    let limit = buf.len().min(char_count);
    let end = buf[..limit].iter().position(|&b| b == 0).unwrap_or(limit);
    let s = String::from_utf8_lossy(&buf[..end]).trim().to_string();
    (if s.is_empty() { None } else { Some(s) }, dev_type)
}

#[derive(Clone, Debug)]
pub struct HidppDeviceReading {
    pub slug: String,
    pub display_name: String,
    pub pct: f64,
    pub is_charging: bool,
    pub connection: String,
    pub product_id: u16,
}

pub fn scan_hidpp_batteries() -> Vec<HidppDeviceReading> {
    let mut results = Vec::new();
    let mut seen_slugs = HashSet::new();
    let mut seen_paths = HashSet::new();
    let non_mouse_types: [u8; 12] = [0, 1, 2, 6, 7, 8, 9, 10, 11, 12, 13, 14];

    for info in enumerate_logitech_hidpp_interfaces() {
        if !seen_paths.insert(info.path_key.clone()) {
            continue;
        }
        let Some(h) = open_overlapped_rw(&info.path_w) else {
            continue;
        };
        for &dev_idx in &[0xFFu8, 0x01, 0x02, 0x03, 0x04] {
            let mut pct: Option<u8> = None;
            let mut charging = false;

            if let Some(ul) = hidpp_request(h, dev_idx, 0x00, 0x00, &[(FEAT_UNIFIED_BATTERY >> 8) as u8, FEAT_UNIFIED_BATTERY as u8], 100) {
                if ul[4] != 0 {
                    if let Some(st) = hidpp_request(h, dev_idx, ul[4], 0x01, &[], 100) {
                        if st[4] <= 100 {
                            pct = Some(st[4]);
                            charging = matches!(st[6], 1 | 2 | 3);
                        }
                    }
                }
            }
            if pct.is_none() {
                if let Some(bl) = hidpp_request(h, dev_idx, 0x00, 0x00, &[(FEAT_BATTERY_STATUS >> 8) as u8, FEAT_BATTERY_STATUS as u8], 100) {
                    if bl[4] != 0 {
                        if let Some(st) = hidpp_request(h, dev_idx, bl[4], 0x00, &[], 100) {
                            if st[4] <= 100 {
                                pct = Some(st[4]);
                                charging = matches!(st[6], 1 | 2 | 3);
                            }
                        }
                    }
                }
            }
            let Some(p) = pct else { continue; };
            let (hw_name, dev_type) = read_device_name_0005(h, dev_idx);
            if let Some(dt) = dev_type {
                if non_mouse_types.contains(&dt) {
                    continue;
                }
            }
            let disp = hw_name
                .or_else(|| if info.product_name.is_empty() { None } else { Some(info.product_name.clone()) })
                .unwrap_or_else(|| format!("Logitech HID++ Mouse ({:04X})", info.product_id));
            let slug: String = disp
                .to_ascii_lowercase()
                .chars()
                .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
                .collect::<String>()
                .trim_matches('-')
                .to_string();
            let final_slug = if slug.is_empty() {
                format!("hidpp-{:04x}-{}", info.product_id, dev_idx)
            } else {
                slug
            };
            if !seen_slugs.insert(final_slug.clone()) {
                continue;
            }
            results.push(HidppDeviceReading {
                slug: final_slug,
                display_name: disp.to_ascii_uppercase(),
                pct: p as f64,
                is_charging: charging,
                connection: if dev_idx == 0xFF { "usb" } else { "lightspeed" }.to_string(),
                product_id: info.product_id,
            });
            if dev_idx == 0xFF {
                break;
            }
        }
        unsafe { CloseHandle(h); }
    }
    results
}

#[derive(Default, Clone, Debug)]
pub struct HidppSnapshot {
    pub connected: bool,
    pub firmware: String,
    pub dpi: Option<i32>,
    pub report_rate_hz: Option<i32>,
    pub onboard_mode: Option<i32>, // 1 = Onboard, 2 = Host
    pub onboard_profile: Option<i32>,
    pub profile_count: i32,
    pub has_rgb: bool,
}

pub struct HidppController {
    handle: Option<Handle>,
    dev_idx: u8,
    fw_feat: Option<u8>,
    dpi_feat: Option<u8>,
    rate_feat: Option<u8>,
    rgb_feat: Option<u8>,
    perkey_feat: Option<u8>,
    onboard_feat: Option<u8>,
    rgb_clusters: u8,
    profile_count: i32,
}

impl Default for HidppController {
    fn default() -> Self {
        Self {
            handle: None,
            dev_idx: 0x01,
            fw_feat: None,
            dpi_feat: None,
            rate_feat: None,
            rgb_feat: None,
            perkey_feat: None,
            onboard_feat: None,
            rgb_clusters: 0,
            profile_count: 5,
        }
    }
}

impl Drop for HidppController {
    fn drop(&mut self) {
        self.close();
    }
}

impl HidppController {
    pub fn close(&mut self) {
        if let Some(h) = self.handle.take() {
            unsafe { CloseHandle(h); }
        }
    }

    pub fn connect(&mut self) -> bool {
        self.close();
        for info in enumerate_logitech_hidpp_interfaces() {
            let Some(h) = open_overlapped_rw(&info.path_w) else {
                continue;
            };
            for &idx in &[0x01u8, 0xFF, 0x02] {
                if let Some(dr) = hidpp_request(h, idx, 0x00, 0x00, &[(FEAT_ADJUSTABLE_DPI >> 8) as u8, FEAT_ADJUSTABLE_DPI as u8], 120) {
                    if dr[4] != 0 {
                        self.handle = Some(h);
                        self.dev_idx = idx;
                        self.dpi_feat = Some(dr[4]);
                        self.rate_feat = hidpp_request(h, idx, 0x00, 0x00, &[(FEAT_REPORT_RATE >> 8) as u8, FEAT_REPORT_RATE as u8], 120)
                            .and_then(|r| if r[4] != 0 { Some(r[4]) } else { None });
                        self.rgb_feat = hidpp_request(h, idx, 0x00, 0x00, &[(FEAT_RGB_EFFECTS >> 8) as u8, FEAT_RGB_EFFECTS as u8], 120)
                            .and_then(|r| if r[4] != 0 { Some(r[4]) } else { None });
                        self.rgb_clusters = 0;
                        if let Some(rf) = self.rgb_feat {
                            if let Some(ci) = hidpp_request(h, idx, rf, 0x00, &[], 120) {
                                self.rgb_clusters = ci[4].min(4);
                            }
                        }
                        self.fw_feat = hidpp_request(h, idx, 0x00, 0x00, &[(FEAT_FW_VERSION >> 8) as u8, FEAT_FW_VERSION as u8], 120)
                            .and_then(|r| if r[4] != 0 { Some(r[4]) } else { None });
                        self.perkey_feat = hidpp_request(h, idx, 0x00, 0x00, &[(FEAT_PERKEY_LIGHTING >> 8) as u8, FEAT_PERKEY_LIGHTING as u8], 120)
                            .and_then(|r| if r[4] != 0 { Some(r[4]) } else { None });
                        self.onboard_feat = hidpp_request(h, idx, 0x00, 0x00, &[(FEAT_ONBOARD_PROFILES >> 8) as u8, FEAT_ONBOARD_PROFILES as u8], 120)
                            .and_then(|r| if r[4] != 0 { Some(r[4]) } else { None });
                        self.profile_count = 5;
                        if let Some(ob) = self.onboard_feat {
                            if let Some(desc) = hidpp_request(h, idx, ob, 0x00, &[], 120) {
                                if (1..=5).contains(&desc[7]) {
                                    self.profile_count = desc[7] as i32;
                                }
                            }
                        }
                        return true;
                    }
                }
            }
            unsafe { CloseHandle(h); }
        }
        false
    }

    fn req(&mut self, feat: Option<u8>, func_id: u8, params: &[u8]) -> Option<[u8; HIDPP_LONG_LEN]> {
        let f = feat?;
        if self.handle.is_none() && !self.connect() {
            return None;
        }
        let h = self.handle?;
        if let Some(r) = hidpp_request(h, self.dev_idx, f, func_id, params, 150) {
            return Some(r);
        }
        if self.connect() {
            let h2 = self.handle?;
            return hidpp_request(h2, self.dev_idx, f, func_id, params, 150);
        }
        None
    }

    pub fn read_snapshot(&mut self) -> HidppSnapshot {
        if self.handle.is_none() && !self.connect() {
            return HidppSnapshot::default();
        }
        let mut snap = HidppSnapshot {
            connected: true,
            profile_count: self.profile_count,
            has_rgb: self.rgb_feat.is_some() || self.perkey_feat.is_some(),
            ..Default::default()
        };
        if let Some(cnt_r) = self.req(self.fw_feat, 0x00, &[]) {
            for i in 0..cnt_r[4].min(8) {
                if let Some(fr) = self.req(self.fw_feat, 0x01, &[i]) {
                    if fr[4] == 0 {
                        let build = ((fr[10] as u16) << 8) | (fr[11] as u16);
                        snap.firmware = format!("{:x}.{:x}.{:x}", fr[8], fr[9], build);
                        break;
                    }
                }
            }
        }
        if let Some(dr) = self.req(self.dpi_feat, 0x02, &[0x00]) {
            snap.dpi = Some((((dr[5] as i32) << 8) | (dr[6] as i32)).clamp(100, 25600));
        }
        if let Some(rr) = self.req(self.rate_feat, 0x01, &[]) {
            if rr[4] > 0 {
                snap.report_rate_hz = Some((1000 / rr[4] as i32).max(125));
            }
        }
        if let Some(mr) = self.req(self.onboard_feat, 0x02, &[]) {
            snap.onboard_mode = Some(mr[4] as i32);
        }
        if let Some(pr) = self.req(self.onboard_feat, 0x04, &[]) {
            let slot = ((pr[4] as i32) << 8) | (pr[5] as i32);
            snap.onboard_profile = Some(if (1..=self.profile_count).contains(&slot) { slot } else { 1 });
        }
        snap
    }

    pub fn set_dpi(&mut self, dpi: i32, stage_idx: Option<usize>) -> bool {
        let clamped = dpi.clamp(100, 25600);
        if let Some(si) = stage_idx {
            if self.onboard_feat.is_some() {
                let _ = self.req(self.onboard_feat, 0x0B, &[(si.min(4)) as u8]);
            }
        }
        self.req(self.dpi_feat, 0x03, &[0x00, ((clamped >> 8) & 0xFF) as u8, (clamped & 0xFF) as u8]).is_some()
    }

    pub fn set_onboard_mode(&mut self, onboard: bool) -> bool {
        self.req(self.onboard_feat, 0x01, &[if onboard { 0x01 } else { 0x02 }]).is_some()
    }

    pub fn set_onboard_profile(&mut self, slot: i32) -> bool {
        let c = slot.clamp(1, self.profile_count) as u8;
        self.req(self.onboard_feat, 0x03, &[0x00, c]).is_some()
    }

    pub fn set_report_rate_hz(&mut self, hz: i32) -> bool {
        let ms = match hz {
            1000 => 1,
            500 => 2,
            250 => 4,
            _ => 8,
        };
        self.req(self.rate_feat, 0x02, &[ms]).is_some()
    }

    pub fn set_rgb_mode(&mut self, mode: &str, r: u8, g: u8, b: u8) -> bool {
        if self.rgb_feat.is_none() && self.perkey_feat.is_none() {
            return false;
        }
        let _ = self.req(self.onboard_feat, 0x01, &[0x02]); // Host mode for live RGB
        let (rr, gg, bb) = if mode == "Off" || mode == "Off (Eco)" { (0, 0, 0) } else { (r, g, b) };
        let mut ok = false;
        if let Some(rf) = self.rgb_feat {
            let count = self.rgb_clusters.max(1).min(4);
            for c_idx in 0..count {
                let params: [u8; 10] = match mode {
                    "Off" | "Off (Eco)" => [c_idx, 0x00, 0, 0, 0, 0, 0, 0, 0, 0],
                    "Breathing" => [c_idx, 0x02, rr, gg, bb, 0x0B, 0xB8, 0x00, 0x64, 0],
                    "Cycle" => [c_idx, 0x03, 0, 0, 0, 0, 0x13, 0x88, 0x64, 0],
                    _ => [c_idx, 0x01, rr, gg, bb, 0, 0, 0, 0, 0],
                };
                if self.req(Some(rf), 0x01, &params).is_some() {
                    ok = true;
                }
            }
        }
        let _ = exe_dir();
        let _ = to_wide;
        ok
    }
}
