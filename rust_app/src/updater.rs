use std::ffi::c_void;
use std::fs;
use std::path::Path;
use std::ptr::{null, null_mut};

use crate::json::parse_json;
use crate::mouse::to_wide;

pub const APP_VERSION: &str = "3.0.0";

const WINHTTP_ACCESS_TYPE_DEFAULT_PROXY: u32 = 0;
const WINHTTP_FLAG_SECURE: u32 = 0x00800000;
const INTERNET_DEFAULT_HTTPS_PORT: u16 = 443;

#[link(name = "winhttp")]
extern "system" {
    fn WinHttpOpen(ua: *const u16, access_type: u32, proxy: *const u16, bypass: *const u16, flags: u32) -> *mut c_void;
    fn WinHttpConnect(sess: *mut c_void, server: *const u16, port: u16, res: u32) -> *mut c_void;
    fn WinHttpOpenRequest(conn: *mut c_void, verb: *const u16, obj: *const u16, ver: *const u16, ref_p: *const u16, acc: *const *const u16, flags: u32) -> *mut c_void;
    fn WinHttpSendRequest(req: *mut c_void, hdrs: *const u16, hdr_len: u32, opt: *const c_void, opt_len: u32, total: u32, ctx: usize) -> i32;
    fn WinHttpReceiveResponse(req: *mut c_void, res: *mut c_void) -> i32;
    fn WinHttpQueryDataAvailable(req: *mut c_void, avail: *mut u32) -> i32;
    fn WinHttpReadData(req: *mut c_void, buf: *mut u8, to_read: u32, read: *mut u32) -> i32;
    fn WinHttpCloseHandle(h: *mut c_void) -> i32;
}

#[link(name = "bcrypt")]
#[allow(dead_code)]
extern "system" {
    fn BCryptOpenAlgorithmProvider(alg: *mut *mut c_void, id: *const u16, imp: *const u16, flags: u32) -> i32;
    fn BCryptCloseAlgorithmProvider(alg: *mut c_void, flags: u32) -> i32;
    fn BCryptCreateHash(alg: *mut c_void, hash: *mut *mut c_void, obj: *mut u8, obj_len: u32, sec: *const u8, sec_len: u32, flags: u32) -> i32;
    fn BCryptHashData(hash: *mut c_void, input: *const u8, in_len: u32, flags: u32) -> i32;
    fn BCryptFinishHash(hash: *mut c_void, out: *mut u8, out_len: u32, flags: u32) -> i32;
    fn BCryptDestroyHash(hash: *mut c_void) -> i32;
}

#[allow(dead_code)]
pub fn sha256_hex(data: &[u8]) -> Option<String> {
    unsafe {
        let alg_id = to_wide("SHA256");
        let mut h_alg: *mut c_void = null_mut();
        if BCryptOpenAlgorithmProvider(&mut h_alg, alg_id.as_ptr(), null(), 0) < 0 || h_alg.is_null() {
            return None;
        }
        let mut h_hash: *mut c_void = null_mut();
        let ok = if BCryptCreateHash(h_alg, &mut h_hash, null_mut(), 0, null(), 0, 0) >= 0 && !h_hash.is_null() {
            let mut digest = [0u8; 32];
            let res = if BCryptHashData(h_hash, data.as_ptr(), data.len() as u32, 0) >= 0
                && BCryptFinishHash(h_hash, digest.as_mut_ptr(), 32, 0) >= 0
            {
                let mut s = String::with_capacity(64);
                for b in digest {
                    s.push_str(&format!("{:02x}", b));
                }
                Some(s)
            } else {
                None
            };
            BCryptDestroyHash(h_hash);
            res
        } else {
            None
        };
        BCryptCloseAlgorithmProvider(h_alg, 0);
        ok
    }
}

fn https_get(host: &str, path: &str) -> Result<Vec<u8>, String> {
    unsafe {
        let ua = to_wide("MouseBatteryControl-Updater/3.0");
        let sess = WinHttpOpen(ua.as_ptr(), WINHTTP_ACCESS_TYPE_DEFAULT_PROXY, null(), null(), 0);
        if sess.is_null() {
            return Err("WinHttpOpen failed".into());
        }
        let whost = to_wide(host);
        let conn = WinHttpConnect(sess, whost.as_ptr(), INTERNET_DEFAULT_HTTPS_PORT, 0);
        if conn.is_null() {
            WinHttpCloseHandle(sess);
            return Err("WinHttpConnect failed".into());
        }
        let wverb = to_wide("GET");
        let wpath = to_wide(path);
        let req = WinHttpOpenRequest(conn, wverb.as_ptr(), wpath.as_ptr(), null(), null(), null(), WINHTTP_FLAG_SECURE);
        let result = if req.is_null() {
            Err("WinHttpOpenRequest failed".into())
        } else {
            let whdr = to_wide("User-Agent: MouseBatteryControl-Updater/3.0\r\nAccept: application/vnd.github+json\r\n");
            let mut body = Vec::new();
            if WinHttpSendRequest(req, whdr.as_ptr(), whdr.len() as u32 - 1, null(), 0, 0, 0) != 0
                && WinHttpReceiveResponse(req, null_mut()) != 0
            {
                loop {
                    let mut avail = 0u32;
                    if WinHttpQueryDataAvailable(req, &mut avail) == 0 || avail == 0 {
                        break;
                    }
                    let mut chunk = vec![0u8; avail as usize];
                    let mut read_n = 0u32;
                    if WinHttpReadData(req, chunk.as_mut_ptr(), avail, &mut read_n) != 0 && read_n > 0 {
                        body.extend_from_slice(&chunk[..read_n as usize]);
                    } else {
                        break;
                    }
                }
                Ok(body)
            } else {
                Err("HTTPS request failed".into())
            }
        };
        if !req.is_null() {
            WinHttpCloseHandle(req);
        }
        WinHttpCloseHandle(conn);
        WinHttpCloseHandle(sess);
        result
    }
}

pub fn parse_version(v: &str) -> (u32, u32, u32) {
    let clean = v.trim().trim_start_matches(['v', 'V']);
    let mut parts = [0u32; 3];
    for (i, tok) in clean.split('.').take(3).enumerate() {
        let digits: String = tok.chars().filter(|c| c.is_ascii_digit()).collect();
        parts[i] = digits.parse::<u32>().unwrap_or(0);
    }
    (parts[0], parts[1], parts[2])
}

#[derive(Clone, Debug)]
#[allow(dead_code)]
pub struct UpdateCheckResult {
    pub status: String, // "up_to_date" | "update_available" | "not_configured" | "error"
    pub latest_version: String,
    pub download_url: String,
    pub message: String,
}

pub fn check_for_update(current_ver: &str, source: Option<&str>) -> UpdateCheckResult {
    let Some(src) = source.map(str::trim).filter(|s| !s.is_empty()) else {
        return UpdateCheckResult {
            status: "not_configured".into(),
            latest_version: String::new(),
            download_url: String::new(),
            message: "No update source configured.".into(),
        };
    };

    if let Some(repo_raw) = src.strip_prefix("github:").or_else(|| src.strip_prefix("GITHUB:")) {
        let repo = repo_raw.trim_matches('/');
        let path = format!("/repos/{}/releases/latest", repo);
        let bytes = match https_get("api.github.com", &path) {
            Ok(b) => b,
            Err(e) => {
                return UpdateCheckResult {
                    status: "error".into(),
                    latest_version: String::new(),
                    download_url: String::new(),
                    message: format!("Update check failed: {}", e),
                };
            }
        };
        let text = String::from_utf8_lossy(&bytes);
        let Ok(v) = parse_json(&text) else {
            return UpdateCheckResult {
                status: "error".into(),
                latest_version: String::new(),
                download_url: String::new(),
                message: "Invalid GitHub release JSON response.".into(),
            };
        };
        let tag = v.get("tag_name").and_then(|x| x.as_str()).unwrap_or("").trim_start_matches(['v', 'V']).to_string();
        if tag.is_empty() {
            let msg = v.get("message").and_then(|x| x.as_str()).unwrap_or("No releases found");
            return UpdateCheckResult {
                status: "error".into(),
                latest_version: String::new(),
                download_url: String::new(),
                message: msg.to_string(),
            };
        }
        let html_url = v
            .get("html_url")
            .and_then(|x| x.as_str())
            .map(str::to_string)
            .unwrap_or_else(|| format!("https://github.com/{}/releases/latest", repo));

        if parse_version(&tag) > parse_version(current_ver) {
            return UpdateCheckResult {
                status: "update_available".into(),
                latest_version: tag.clone(),
                download_url: html_url,
                message: format!("Update v{} available on GitHub Releases!", tag),
            };
        }
        return UpdateCheckResult {
            status: "up_to_date".into(),
            latest_version: tag.clone(),
            download_url: html_url,
            message: format!("Up to date (v{}).", current_ver),
        };
    }

    let local_manifest = Path::new(src).join("latest.json");
    if local_manifest.is_file() {
        if let Ok(raw) = fs::read_to_string(&local_manifest) {
            if let Ok(v) = parse_json(&raw) {
                let ver = v.get("version").and_then(|x| x.as_str()).unwrap_or("").to_string();
                if parse_version(&ver) > parse_version(current_ver) {
                    return UpdateCheckResult {
                        status: "update_available".into(),
                        latest_version: ver.clone(),
                        download_url: src.to_string(),
                        message: format!("Update v{} found in local folder.", ver),
                    };
                }
                return UpdateCheckResult {
                    status: "up_to_date".into(),
                    latest_version: ver,
                    download_url: String::new(),
                    message: format!("Up to date (v{}).", current_ver),
                };
            }
        }
    }

    UpdateCheckResult {
        status: "up_to_date".into(),
        latest_version: current_ver.to_string(),
        download_url: String::new(),
        message: format!("Running v{}.", current_ver),
    }
}
