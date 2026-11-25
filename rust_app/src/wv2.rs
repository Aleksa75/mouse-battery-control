use std::ffi::c_void;
use std::path::Path;
use std::ptr::null_mut;
use std::sync::atomic::{AtomicU32, Ordering};

pub type HResult = i32;
pub type Handle = *mut c_void;
pub type Hwnd = Handle;
pub type Hmodule = Handle;

pub const S_OK: HResult = 0;
pub const E_NOINTERFACE: HResult = 0x80004002u32 as i32;
pub const E_POINTER: HResult = 0x80004003u32 as i32;
pub const LOAD_WITH_ALTERED_SEARCH_PATH: u32 = 0x00000008;

#[repr(C)]
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Guid {
    pub data1: u32,
    pub data2: u16,
    pub data3: u16,
    pub data4: [u8; 8],
}

pub const IID_IUNKNOWN: Guid = Guid {
    data1: 0x00000000,
    data2: 0x0000,
    data3: 0x0000,
    data4: [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46],
};
pub const IID_ENV_HANDLER: Guid = Guid {
    data1: 0x4e8a3389,
    data2: 0xc9d8,
    data3: 0x4bd2,
    data4: [0xb6, 0xb5, 0x12, 0x4f, 0xee, 0x6c, 0xc1, 0x4d],
};
pub const IID_CTRL_HANDLER: Guid = Guid {
    data1: 0x6c4819f3,
    data2: 0xc9b7,
    data3: 0x4260,
    data4: [0x81, 0x27, 0xc9, 0xf5, 0xbd, 0xe7, 0xf6, 0x8c],
};
pub const IID_MSG_HANDLER: Guid = Guid {
    data1: 0x57213f19,
    data2: 0x00e6,
    data3: 0x49fa,
    data4: [0x8e, 0x07, 0x89, 0x8e, 0xa0, 0x1e, 0xcb, 0xd2],
};

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct Rect {
    pub left: i32,
    pub top: i32,
    pub right: i32,
    pub bottom: i32,
}

#[repr(C)]
#[derive(Clone, Copy, Default)]
pub struct EventToken {
    pub value: i64,
}

#[allow(dead_code)]
pub type IUnknown = *mut *const IUnknownVtbl;
#[repr(C)]
pub struct IUnknownVtbl {
    pub query_interface: unsafe extern "system" fn(*mut c_void, *const Guid, *mut *mut c_void) -> HResult,
    pub add_ref: unsafe extern "system" fn(*mut c_void) -> u32,
    pub release: unsafe extern "system" fn(*mut c_void) -> u32,
}

pub type ICoreWebView2Settings = *mut *const ICoreWebView2SettingsVtbl;
#[repr(C)]
pub struct ICoreWebView2SettingsVtbl {
    pub unk: IUnknownVtbl,
    pub get_is_script_enabled: *const c_void,
    pub put_is_script_enabled: *const c_void,
    pub get_is_web_message_enabled: *const c_void,
    pub put_is_web_message_enabled: *const c_void,
    pub get_are_default_script_dialogs_enabled: *const c_void,
    pub put_are_default_script_dialogs_enabled: *const c_void,
    pub get_is_status_bar_enabled: *const c_void,
    pub put_is_status_bar_enabled: unsafe extern "system" fn(ICoreWebView2Settings, i32) -> HResult,
    pub get_are_dev_tools_enabled: *const c_void,
    pub put_are_dev_tools_enabled: unsafe extern "system" fn(ICoreWebView2Settings, i32) -> HResult,
    pub get_are_default_context_menus_enabled: *const c_void,
    pub put_are_default_context_menus_enabled: unsafe extern "system" fn(ICoreWebView2Settings, i32) -> HResult,
    pub get_is_zoom_control_enabled: *const c_void,
    pub put_is_zoom_control_enabled: unsafe extern "system" fn(ICoreWebView2Settings, i32) -> HResult,
}

pub type ICoreWebView2WebMessageReceivedEventArgs = *mut *const ICoreWebView2WebMessageReceivedEventArgsVtbl;
#[repr(C)]
pub struct ICoreWebView2WebMessageReceivedEventArgsVtbl {
    pub unk: IUnknownVtbl,
    pub get_source: unsafe extern "system" fn(ICoreWebView2WebMessageReceivedEventArgs, *mut *mut u16) -> HResult,
    pub get_web_message_as_json: unsafe extern "system" fn(ICoreWebView2WebMessageReceivedEventArgs, *mut *mut u16) -> HResult,
    pub try_get_web_message_as_string: unsafe extern "system" fn(ICoreWebView2WebMessageReceivedEventArgs, *mut *mut u16) -> HResult,
}

pub type ICoreWebView2 = *mut *const ICoreWebView2Vtbl;
#[repr(C)]
pub struct ICoreWebView2Vtbl {
    pub unk: IUnknownVtbl,
    pub get_settings: unsafe extern "system" fn(ICoreWebView2, *mut ICoreWebView2Settings) -> HResult,
    pub get_source: *const c_void,
    pub navigate: unsafe extern "system" fn(ICoreWebView2, *const u16) -> HResult,
    pub navigate_to_string: unsafe extern "system" fn(ICoreWebView2, *const u16) -> HResult,
    pub add_navigation_starting: *const c_void,
    pub remove_navigation_starting: *const c_void,
    pub add_content_loading: *const c_void,
    pub remove_content_loading: *const c_void,
    pub add_source_changed: *const c_void,
    pub remove_source_changed: *const c_void,
    pub add_history_changed: *const c_void,
    pub remove_history_changed: *const c_void,
    pub add_navigation_completed: *const c_void,
    pub remove_navigation_completed: *const c_void,
    pub add_frame_navigation_starting: *const c_void,
    pub remove_frame_navigation_starting: *const c_void,
    pub add_frame_navigation_completed: *const c_void,
    pub remove_frame_navigation_completed: *const c_void,
    pub add_script_dialog_opening: *const c_void,
    pub remove_script_dialog_opening: *const c_void,
    pub add_permission_requested: *const c_void,
    pub remove_permission_requested: *const c_void,
    pub add_process_failed: *const c_void,
    pub remove_process_failed: *const c_void,
    pub add_script_to_execute_on_document_created: *const c_void,
    pub remove_script_to_execute_on_document_created: *const c_void,
    pub execute_script: *const c_void,
    pub capture_preview: *const c_void,
    pub reload: *const c_void,
    pub post_web_message_as_json: unsafe extern "system" fn(ICoreWebView2, *const u16) -> HResult,
    pub post_web_message_as_string: *const c_void,
    pub add_web_message_received: unsafe extern "system" fn(ICoreWebView2, *mut c_void, *mut EventToken) -> HResult,
    pub remove_web_message_received: unsafe extern "system" fn(ICoreWebView2, EventToken) -> HResult,
}

pub type ICoreWebView2Controller = *mut *const ICoreWebView2ControllerVtbl;
#[repr(C)]
pub struct ICoreWebView2ControllerVtbl {
    pub unk: IUnknownVtbl,
    pub get_is_visible: *const c_void,
    pub put_is_visible: unsafe extern "system" fn(ICoreWebView2Controller, i32) -> HResult,
    pub get_bounds: *const c_void,
    pub put_bounds: unsafe extern "system" fn(ICoreWebView2Controller, *const Rect) -> HResult,
    pub get_zoom_factor: *const c_void,
    pub put_zoom_factor: *const c_void,
    pub add_zoom_factor_changed: *const c_void,
    pub remove_zoom_factor_changed: *const c_void,
    pub set_bounds_and_zoom_factor: *const c_void,
    pub move_focus: *const c_void,
    pub add_move_focus_requested: *const c_void,
    pub remove_move_focus_requested: *const c_void,
    pub add_got_focus: *const c_void,
    pub remove_got_focus: *const c_void,
    pub add_lost_focus: *const c_void,
    pub remove_lost_focus: *const c_void,
    pub add_accelerator_key_pressed: *const c_void,
    pub remove_accelerator_key_pressed: *const c_void,
    pub get_parent_window: *const c_void,
    pub put_parent_window: *const c_void,
    pub notify_parent_window_position_changed: *const c_void,
    pub close: unsafe extern "system" fn(ICoreWebView2Controller) -> HResult,
    pub get_core_webview2: unsafe extern "system" fn(ICoreWebView2Controller, *mut ICoreWebView2) -> HResult,
}

pub type ICoreWebView2Environment = *mut *const ICoreWebView2EnvironmentVtbl;
#[repr(C)]
pub struct ICoreWebView2EnvironmentVtbl {
    pub unk: IUnknownVtbl,
    pub create_core_webview2_controller: unsafe extern "system" fn(ICoreWebView2Environment, Hwnd, *mut c_void) -> HResult,
}

pub type CreateWv2EnvInternalFn = unsafe extern "system" fn(
    check_running: u8,
    runtime_type: i32,
    user_data_folder: *const u16,
    env_options: *mut c_void,
    handler: *mut c_void,
) -> HResult;

#[repr(C)]
pub struct CallbackVtbl {
    pub query_interface: unsafe extern "system" fn(*mut c_void, *const Guid, *mut *mut c_void) -> HResult,
    pub add_ref: unsafe extern "system" fn(*mut c_void) -> u32,
    pub release: unsafe extern "system" fn(*mut c_void) -> u32,
    pub invoke: unsafe extern "system" fn(*mut c_void, *mut c_void, *mut c_void) -> HResult,
}

#[repr(C)]
pub struct ComCallback {
    pub vtbl: *const CallbackVtbl,
    pub refs: AtomicU32,
    pub iid: Guid,
    pub user_fn: fn(*mut c_void, *mut c_void) -> HResult,
}

unsafe extern "system" fn cb_query_interface(this: *mut c_void, riid: *const Guid, ppv: *mut *mut c_void) -> HResult {
    if ppv.is_null() {
        return E_POINTER;
    }
    if riid.is_null() {
        *ppv = null_mut();
        return E_POINTER;
    }
    let obj = &*(this as *const ComCallback);
    let wanted = *riid;
    if wanted == IID_IUNKNOWN || wanted == obj.iid {
        *ppv = this;
        cb_add_ref(this);
        S_OK
    } else {
        *ppv = null_mut();
        E_NOINTERFACE
    }
}

unsafe extern "system" fn cb_add_ref(this: *mut c_void) -> u32 {
    let obj = &*(this as *const ComCallback);
    obj.refs.fetch_add(1, Ordering::Relaxed) + 1
}

unsafe extern "system" fn cb_release(this: *mut c_void) -> u32 {
    let obj = &*(this as *const ComCallback);
    let prev = obj.refs.fetch_sub(1, Ordering::Release);
    if prev == 1 {
        std::sync::atomic::fence(Ordering::Acquire);
        drop(Box::from_raw(this as *mut ComCallback));
    }
    prev - 1
}

unsafe extern "system" fn cb_invoke(this: *mut c_void, arg1: *mut c_void, arg2: *mut c_void) -> HResult {
    let obj = &*(this as *const ComCallback);
    (obj.user_fn)(arg1, arg2)
}

static CB_VTBL: CallbackVtbl = CallbackVtbl {
    query_interface: cb_query_interface,
    add_ref: cb_add_ref,
    release: cb_release,
    invoke: cb_invoke,
};

pub fn new_com_callback(iid: Guid, user_fn: fn(*mut c_void, *mut c_void) -> HResult) -> *mut c_void {
    let boxed = Box::new(ComCallback {
        vtbl: &CB_VTBL,
        refs: AtomicU32::new(1),
        iid,
        user_fn,
    });
    Box::into_raw(boxed) as *mut c_void
}

pub unsafe fn com_add_ref(ptr: *mut c_void) {
    if !ptr.is_null() {
        let vtbl = *(ptr as *const *const IUnknownVtbl);
        ((*vtbl).add_ref)(ptr);
    }
}

pub unsafe fn com_release(ptr: *mut c_void) {
    if !ptr.is_null() {
        let vtbl = *(ptr as *const *const IUnknownVtbl);
        ((*vtbl).release)(ptr);
    }
}

#[link(name = "advapi32")]
extern "system" {
    fn RegOpenKeyExW(hkey: Handle, subkey: *const u16, opts: u32, sam: u32, out: *mut Handle) -> i32;
    fn RegQueryValueExW(hkey: Handle, name: *const u16, res: *mut u32, rtype: *mut u32, data: *mut u8, sz: *mut u32) -> i32;
    fn RegCloseKey(hkey: Handle) -> i32;
}

const HKEY_LOCAL_MACHINE: Handle = (-2147483646i32 as isize) as Handle;
const KEY_READ: u32 = 0x20019;

fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

fn from_wide_buf(buf: &[u16]) -> String {
    let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
    String::from_utf16_lossy(&buf[..len])
}

pub fn find_embedded_browser_webview_dll() -> Option<String> {
    let subkey = to_wide("SOFTWARE\\WOW6432Node\\Microsoft\\EdgeUpdate\\Clients\\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}");
    let mut hkey: Handle = null_mut();
    unsafe {
        if RegOpenKeyExW(HKEY_LOCAL_MACHINE, subkey.as_ptr(), 0, KEY_READ, &mut hkey) == 0 {
            let mut loc_buf = [0u16; 260];
            let mut pv_buf = [0u16; 64];
            let mut loc_sz = (loc_buf.len() * 2) as u32;
            let mut pv_sz = (pv_buf.len() * 2) as u32;
            let loc_name = to_wide("location");
            let pv_name = to_wide("pv");
            let r1 = RegQueryValueExW(hkey, loc_name.as_ptr(), null_mut(), null_mut(), loc_buf.as_mut_ptr() as *mut u8, &mut loc_sz);
            let r2 = RegQueryValueExW(hkey, pv_name.as_ptr(), null_mut(), null_mut(), pv_buf.as_mut_ptr() as *mut u8, &mut pv_sz);
            RegCloseKey(hkey);
            if r1 == 0 && r2 == 0 {
                let loc = from_wide_buf(&loc_buf);
                let pv = from_wide_buf(&pv_buf);
                let cand = format!("{}\\{}\\EBWebView\\x64\\EmbeddedBrowserWebView.dll", loc.trim_end_matches('\\'), pv);
                if Path::new(&cand).exists() {
                    return Some(cand);
                }
            }
        }
    }

    let base = Path::new(r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application");
    if let Ok(entries) = std::fs::read_dir(base) {
        for ent in entries.flatten() {
            if let Some(name) = ent.file_name().to_str() {
                if name.starts_with(|c: char| c.is_ascii_digit()) {
                    let cand = ent.path().join("EBWebView").join("x64").join("EmbeddedBrowserWebView.dll");
                    if cand.exists() {
                        return Some(cand.to_string_lossy().into_owned());
                    }
                }
            }
        }
    }
    None
}
