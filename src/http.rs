//! HTTP/1.1 连接处理与请求调度管线。
//!
//! 模块布局：
//! - 日期工具（`http_date_now` 等，带 1 秒缓存）
//! - 请求头/查询串解析（`parse_query`）
//! - 静态文件服务（`serve_static`：canonicalize 防穿越、Last-Modified/304）
//! - 调度管线（`handle` → 路由匹配 → `dispatch_python` 跨 FFI 调 Python）
//! - 响应写出（`write_response`：统一补 Server/Date/Content-Length）
//! - 连接循环（`serve_conn`：keep-alive、chunked、100-continue、超时）
//!
//! 性能要点：解析、路由、静态文件、JSON 序列化、错误响应全部在 Rust
//! 侧完成；只有真正需要运行 Python 视图时才经 `spawn_blocking` 拿 GIL。

use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use percent_encoding::percent_decode_str;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple};
use rand::Rng;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::tcp::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::{TcpListener, TcpStream};

use crate::db;
use crate::json;
use crate::router::{MatchOutcome, Router};

pub const SERVER_NAME: &str = concat!("zan/", env!("CARGO_PKG_VERSION"));
const MAX_HEAD: usize = 64 * 1024;
const MAX_HEADER_COUNT: usize = 100;
const HDR_TIMEOUT: Duration = Duration::from_secs(60);
const BODY_TIMEOUT: Duration = Duration::from_secs(60);

/// 每次 run() 时冻结的不可变服务器状态。
pub struct Shared {
    pub router: Arc<Router>,
    /// 静态目录列表：(URL 前缀, 本地目录)
    pub static_cfg: Vec<(String, PathBuf)>,
    pub cc_max_age: i64, // -1 disables Cache-Control
    pub dispatch: Py<PyAny>,       // slow path: app._process(request)
    pub pipeline: Py<PyAny>,       // fast path: (request, view, kwargs) -> Response
    pub fast_pipeline: Option<Py<PyAny>>, // ultra-fast path: (request, view, kwargs) -> raw rv
    pub req_cls: Py<PyAny>,        // zan.wrappers.Request
    pub convert_slow: Py<PyAny>,   // rv -> Response for exotic return types
    pub debug_page: Py<PyAny>,     // exc -> Response, debug mode only
    pub http_exc: Py<PyAny>,       // zan.exceptions.HTTPException
    pub uuid_cls: Py<PyAny>,       // uuid.UUID（uuid 转换器实例化用）
    pub fast: bool,
    pub debug: bool,
    pub log: bool,
    /// TRAP_HTTP_EXCEPTIONS=True 时，HTTPException 也按未捕获错误处理
    pub trap_http: bool,
    pub max_body: usize,
}

/// A fully-read request as seen by the dispatch pipeline.
pub struct Req {
    pub method: String,
    pub path: String, // raw (percent-encoded), no query string
    pub query_raw: String,
    pub query_pairs: Vec<(String, String)>,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
    pub remote_addr: String,
}

#[derive(Debug)]
pub struct ResponseOut {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

impl ResponseOut {
    fn new(status: u16, headers: Vec<(String, String)>, body: Vec<u8>) -> Self {
        ResponseOut { status, headers, body }
    }
}

// ---------------------------------------------------------------------------
// date helpers
// ---------------------------------------------------------------------------

static DATE_CACHE: Mutex<Option<(u64, String)>> = Mutex::new(None);

pub fn http_date_now() -> String {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let mut cell = DATE_CACHE.lock().unwrap_or_else(|e| e.into_inner());
    if let Some((secs, s)) = cell.as_ref() {
        if *secs == now {
            return s.clone();
        }
    }
    let s = http_date_from_secs(now as i64);
    *cell = Some((now, s.clone()));
    s
}

const WDAY: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MON: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32;
    (y + if m <= 2 { 1 } else { 0 }, m, d)
}

fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = y - if m <= 2 { 1 } else { 0 };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = m as i64 + if m > 2 { -3 } else { 9 };
    let doy = (153 * mp + 2) / 5 + d as i64 - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

pub fn http_date_from_secs(secs: i64) -> String {
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    let (h, mi, s) = (rem / 3600, (rem % 3600) / 60, rem % 60);
    let (y, mo, d) = civil_from_days(days);
    let wd = (days + 4).rem_euclid(7) as usize; // 1970-01-01 was a Thursday
    format!(
        "{}, {:02} {} {:04} {:02}:{:02}:{:02} GMT",
        WDAY[wd], d, MON[(mo - 1) as usize], y, h, mi, s
    )
}

pub fn http_date_from_system(t: SystemTime) -> String {
    let secs = t
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    http_date_from_secs(secs)
}

/// Parse `Sun, 06 Nov 1994 08:49:37 GMT` into unix seconds.
pub fn parse_http_date(s: &str) -> Option<i64> {
    let parts: Vec<&str> = s.split_whitespace().collect();
    if parts.len() < 5 {
        return None;
    }
    let d: i64 = parts[1].parse().ok()?;
    let mo = MON.iter().position(|m| *m == parts[2])? as u32 + 1;
    let mut y: i64 = parts[3].parse().ok()?;
    if y < 100 {
        y += if y < 70 { 2000 } else { 1900 };
    }
    let hms: Vec<&str> = parts[4].split(':').collect();
    if hms.len() != 3 {
        return None;
    }
    let (h, mi, sec): (i64, i64, i64) =
        (hms[0].parse().ok()?, hms[1].parse().ok()?, hms[2].parse().ok()?);
    Some(days_from_civil(y, mo, d as u32) * 86_400 + h * 3600 + mi * 60 + sec)
}

// ---------------------------------------------------------------------------
// small utilities
// ---------------------------------------------------------------------------

pub fn parse_query(q: &str) -> Vec<(String, String)> {
    q.split('&')
        .filter(|s| !s.is_empty())
        .map(|kv| match kv.split_once('=') {
            Some((k, v)) => (decode_query_component(k), decode_query_component(v)),
            None => (decode_query_component(kv), String::new()),
        })
        .collect()
}

fn decode_query_component(s: &str) -> String {
    percent_decode_str(&s.replace('+', " "))
        .decode_utf8_lossy()
        .into_owned()
}

fn decode_path(p: &str) -> String {
    percent_decode_str(p).decode_utf8_lossy().into_owned()
}

fn header_get<'a>(headers: &'a [(String, String)], name: &str) -> Option<&'a str> {
    headers
        .iter()
        .find(|(k, _)| k.eq_ignore_ascii_case(name))
        .map(|(_, v)| v.as_str())
}

fn reason_for(code: u16) -> &'static str {
    match code {
        200 => "OK",
        201 => "Created",
        202 => "Accepted",
        204 => "No Content",
        206 => "Partial Content",
        301 => "Moved Permanently",
        302 => "Found",
        303 => "See Other",
        304 => "Not Modified",
        307 => "Temporary Redirect",
        308 => "Permanent Redirect",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        405 => "Method Not Allowed",
        406 => "Not Acceptable",
        408 => "Request Timeout",
        409 => "Conflict",
        410 => "Gone",
        411 => "Length Required",
        413 => "Content Too Large",
        414 => "URI Too Long",
        415 => "Unsupported Media Type",
        416 => "Range Not Satisfiable",
        417 => "Expectation Failed",
        418 => "I'm a Teapot",
        422 => "Unprocessable Content",
        429 => "Too Many Requests",
        431 => "Request Header Fields Too Large",
        500 => "Internal Server Error",
        501 => "Not Implemented",
        502 => "Bad Gateway",
        503 => "Service Unavailable",
        504 => "Gateway Timeout",
        _ => "Unknown",
    }
}

fn simple_body(code: u16) -> &'static str {
    match code {
        400 => "<!doctype html>\n<html lang=en>\n<title>400 Bad Request</title>\n<h1>Bad Request</h1>\n<p>The browser (or proxy) sent a request that this server could not understand.</p>\n",
        404 => "<!doctype html>\n<html lang=en>\n<title>404 Not Found</title>\n<h1>Not Found</h1>\n<p>The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.</p>\n",
        405 => "<!doctype html>\n<html lang=en>\n<title>405 Method Not Allowed</title>\n<h1>Method Not Allowed</h1>\n<p>The method is not allowed for the requested URL.</p>\n",
        413 => "<!doctype html>\n<html lang=en>\n<title>413 Content Too Large</title>\n<h1>Content Too Large</h1>\n<p>The request body is too large.</p>\n",
        431 => "<!doctype html>\n<html lang=en>\n<title>431 Request Header Fields Too Large</title>\n<h1>Request Header Fields Too Large</h1>\n<p>The request header fields are too large.</p>\n",
        _ => "<!doctype html>\n<html lang=en>\n<title>500 Internal Server Error</title>\n<h1>Internal Server Error</h1>\n<p>The server encountered an internal error and was unable to complete your request.</p>\n",
    }
}

fn simple(code: u16) -> ResponseOut {
    ResponseOut::new(
        code,
        vec![("Content-Type".into(), "text/html; charset=utf-8".into())],
        simple_body(code).as_bytes().to_vec(),
    )
}

fn mime_for(ext: Option<&std::ffi::OsStr>) -> &'static str {
    let e = match ext.and_then(|e| e.to_str()) {
        Some(e) => e.to_ascii_lowercase(),
        None => return "application/octet-stream",
    };
    match e.as_str() {
        "html" | "htm" => "text/html; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "json" | "map" => "application/json",
        "txt" | "text" | "log" => "text/plain; charset=utf-8",
        "xml" => "application/xml; charset=utf-8",
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "svg" => "image/svg+xml",
        "webp" => "image/webp",
        "avif" => "image/avif",
        "ico" => "image/vnd.microsoft.icon",
        "bmp" => "image/bmp",
        "pdf" => "application/pdf",
        "zip" => "application/zip",
        "gz" => "application/gzip",
        "mp3" => "audio/mpeg",
        "mp4" => "video/mp4",
        "webm" => "video/webm",
        "woff" => "font/woff",
        "woff2" => "font/woff2",
        "ttf" => "font/ttf",
        "otf" => "font/otf",
        "wasm" => "application/wasm",
        "csv" => "text/csv; charset=utf-8",
        _ => "application/octet-stream",
    }
}

// ---------------------------------------------------------------------------
// static files
// ---------------------------------------------------------------------------

/// 服务一个静态文件。
///
/// 安全性：先 canonicalize 再检查是否仍在根目录内，阻断 `..` 穿越。
/// 缓存：Last-Modified + If-Modified-Since → 304；可选 Cache-Control。
async fn serve_static(
    root: &Path,
    rel_raw: &str,
    headers: &[(String, String)],
    cc_max_age: i64,
) -> Option<ResponseOut> {
    let decoded = percent_decode_str(rel_raw).decode_utf8_lossy().into_owned();
    if decoded.contains('\0') {
        return None;
    }
    let rel = decoded.replace('\\', "/");
    if rel.split('/').any(|p| p == "..") {
        return None;
    }
    let full = root.join(&rel);
    let canon = tokio::fs::canonicalize(&full).await.ok()?;
    if !canon.starts_with(root) {
        return None;
    }
    let meta = tokio::fs::metadata(&canon).await.ok()?;
    if !meta.is_file() {
        return None;
    }
    let mtime = meta.modified().ok()?;
    let msecs = mtime
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);
    if let Some(ims) = header_get(headers, "if-modified-since").and_then(parse_http_date) {
        if msecs <= ims {
            return Some(ResponseOut::new(304, Vec::new(), Vec::new()));
        }
    }
    let data = tokio::fs::read(&canon).await.ok()?;
    let mut hdrs = vec![
        ("Content-Type".to_string(), mime_for(canon.extension()).to_string()),
        ("Last-Modified".to_string(), http_date_from_system(mtime)),
    ];
    if cc_max_age >= 0 {
        hdrs.push(("Cache-Control".to_string(), format!("public, max-age={cc_max_age}")));
    }
    Some(ResponseOut::new(200, hdrs, data))
}

// ---------------------------------------------------------------------------
// dispatch pipeline
// ---------------------------------------------------------------------------

/// 处理一个已完整读取的请求，返回待写出的响应。
///
/// 分派顺序：
/// 1. 静态目录（最长前缀匹配，纯 Rust 完成，不碰 GIL）
/// 2. 路由 trie 匹配（重定向 → 308；未命中 → Python 404 管线；
///    方法不符 → OPTIONS 自动响应 / 405 + Allow → Python 管线）
/// 3. 命中 → `dispatch_python`（fast path 直达视图，slow path 全量管线）
pub async fn handle(shared: &Arc<Shared>, req: Req) -> ResponseOut {
    // 与 socket 读取路径一致的请求体上限检查（test_request 等直构 Req 的入口也会走到这里）
    if req.body.len() > shared.max_body {
        return simple(413);
    }
    // 静态文件完全在 Rust 侧服务，不触碰 GIL。多个前缀时最长前缀优先。
    if !shared.static_cfg.is_empty() {
        let mut best: Option<(&(String, PathBuf), usize)> = None;
        for entry in &shared.static_cfg {
            let prefix = &entry.0;
            if req.path == prefix.as_str() || req.path.starts_with(&format!("{prefix}/")) {
                let len = prefix.len();
                if best.map_or(true, |(_, l)| len > l) {
                    best = Some((entry, len));
                }
            }
        }
        if let Some(((prefix, dir), _)) = best {
            let rel = if req.path.len() > prefix.len() {
                &req.path[prefix.len() + 1..]
            } else {
                ""
            };
            return match serve_static(dir, rel, &req.headers, shared.cc_max_age).await {
                Some(r) => r,
                None => {
                    dispatch_python(shared, req, None, Vec::new(), String::new(), "404".into(), Vec::new(), false).await
                }
            };
        }
    }

    let router = shared.router.clone();
    match router.find(&req.path) {
        MatchOutcome::Redirect(loc) => {
            let target = if req.query_raw.is_empty() {
                loc
            } else {
                format!("{loc}?{}", req.query_raw)
            };
            ResponseOut::new(308, vec![("Location".into(), target)], Vec::new())
        }
        MatchOutcome::Candidates(cands) => {
            if cands.is_empty() {
                return dispatch_python(shared, req, None, Vec::new(), String::new(), "404".into(), Vec::new(), false).await;
            }
            let m = req.method.as_str();
            let mut allowed: Vec<String> = Vec::new();
            let mut chosen: Option<(usize, &Vec<crate::router::Param>)> = None;
            for (idx, params) in &cands {
                let r = &router.routes[*idx];
                let mut ok = r.methods.iter().any(|x| x == m);
                if !ok && m == "HEAD" && r.methods.iter().any(|x| x == "GET") {
                    ok = true;
                }
                if ok && chosen.is_none() {
                    chosen = Some((*idx, params));
                }
                for x in &r.methods {
                    if !allowed.iter().any(|a| a == x) {
                        allowed.push(x.clone());
                    }
                }
                if r.methods.iter().any(|x| x == "GET")
                    && !allowed.iter().any(|a| a == "HEAD")
                {
                    allowed.push("HEAD".into());
                }
                if r.auto_options && !allowed.iter().any(|a| a == "OPTIONS") {
                    allowed.push("OPTIONS".into());
                }
            }
            if let Some((idx, params)) = chosen {
                let route = &router.routes[idx];
                if let Some(native) = &route.native_response {
                    return ResponseOut::new(native.status, native.headers.clone(), native.body.clone());
                }
                if let Some(handler_id) = &route.native_handler {
                    return native_handler(&req,
                        handler_id.as_str()).await;
                }
                let fast = route.fast;
                dispatch_python(shared, req, Some(idx), params.clone(), route.endpoint.clone(), String::new(), Vec::new(), fast)
                    .await
            } else if m == "OPTIONS" {
                allowed.sort();
                ResponseOut::new(
                    200,
                    vec![
                        ("Allow".into(), allowed.join(", ")),
                        ("Content-Type".into(), "text/html; charset=utf-8".into()),
                    ],
                    Vec::new(),
                )
            } else {
                allowed.sort();
                dispatch_python(shared, req, None, Vec::new(), String::new(), "405".into(), allowed, false).await
            }
        }
    }
}

/// 完全绕过 Python 的 Rust 原生动态处理器。
/// 用于 TFB 等已知路径：直接执行异步 DB + JSON/HTML 序列化。
async fn native_handler(req: &Req, handler_id: &str) -> ResponseOut {
    match handler_id {
        "db" => native_db().await,
        "queries" => native_queries(req).await,
        "updates" => native_updates(req).await,
        "fortunes" => native_fortunes().await,
        _ => simple(500),
    }
}

fn random_world_id() -> i32 {
    rand::thread_rng().gen_range(1..=10000)
}

fn parse_queries(req: &Req) -> usize {
    let n: i32 = req
        .query_pairs
        .iter()
        .find(|(k, _)| k == "queries")
        .and_then(|(_, v)| v.parse().ok())
        .unwrap_or(1);
    (n.max(1).min(500)) as usize
}

async fn native_db() -> ResponseOut {
    match db::get_world(random_world_id()).await {
        Ok((id, num)) => ResponseOut::new(
            200,
            vec![("Content-Type".into(), "application/json".into())],
            format!(r#"{{"id":{},"randomNumber":{}}}"#, id, num).into_bytes(),
        ),
        Err(_) => simple(500),
    }
}

async fn native_queries(req: &Req) -> ResponseOut {
    let n = parse_queries(req);
    let ids: Vec<i32> = (0..n).map(|_| random_world_id()).collect();
    match db::get_worlds(ids).await {
        Ok(rows) => {
            let mut body = String::with_capacity(rows.len() * 32 + 2);
            body.push('[');
            for (i, (id, num)) in rows.iter().enumerate() {
                if i > 0 {
                    body.push(',');
                }
                body.push_str(&format!(r#"{{"id":{},"randomNumber":{}}}"#, id, num));
            }
            body.push(']');
            ResponseOut::new(200, vec![("Content-Type".into(), "application/json".into())], body.into_bytes())
        }
        Err(_) => simple(500),
    }
}

async fn native_updates(req: &Req) -> ResponseOut {
    let n = parse_queries(req);
    let ids: Vec<i32> = (0..n).map(|_| random_world_id()).collect();
    match db::get_worlds(ids).await {
        Ok(rows) => {
            let updates: Vec<(i32, i32)> = rows
                .iter()
                .map(|(id, _)| (random_world_id(), *id))
                .collect();
            if db::update_worlds(updates.clone()).await.is_err() {
                return simple(500);
            }
            let mut body = String::with_capacity(updates.len() * 32 + 2);
            body.push('[');
            for (i, (new, id)) in updates.iter().enumerate() {
                if i > 0 {
                    body.push(',');
                }
                body.push_str(&format!(r#"{{"id":{},"randomNumber":{}}}"#, id, new));
            }
            body.push(']');
            ResponseOut::new(200, vec![("Content-Type".into(), "application/json".into())], body.into_bytes())
        }
        Err(_) => simple(500),
    }
}

fn escape_html(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(ch),
        }
    }
    out
}

async fn native_fortunes() -> ResponseOut {
    match db::get_fortunes().await {
        Ok(mut rows) => {
            rows.push((0, "Additional fortune added at request time.".to_string()));
            rows.sort_by(|a, b| a.1.cmp(&b.1));
            let mut body = String::with_capacity(1024);
            body.push_str("<!doctype html>\n<html>\n<head><title>Fortunes</title></head>\n");
            body.push_str("<body><table><tr><th>id</th><th>message</th></tr>\n");
            for (id, msg) in rows {
                body.push_str(&format!(
                    "<tr><td>{}</td><td>{}</td></tr>\n",
                    id,
                    escape_html(&msg)
                ));
            }
            body.push_str("</table></body></html>");
            ResponseOut::new(
                200,
                vec![("Content-Type".into(), "text/html; charset=utf-8".into())],
                body.into_bytes(),
            )
        }
        Err(_) => simple(500),
    }
}

/// Cross the FFI boundary: build the Python Request, call the view (fast) or
/// `_process` (full dispatch), convert the result to bytes.
#[allow(clippy::too_many_arguments)]
async fn dispatch_python(
    shared: &Arc<Shared>,
    req: Req,
    view_idx: Option<usize>,
    params: Vec<crate::router::Param>,
    endpoint: String,
    hint: String,
    allowed: Vec<String>,
    fast: bool,
) -> ResponseOut {
    let shared2 = shared.clone();
    let joined = tokio::task::spawn_blocking(move || {
        Python::with_gil(|py| {
            let view = view_idx
                .and_then(|i| shared2.router.routes.get(i))
                .map(|r| r.view.clone_ref(py));
            let view_ref = view.as_ref();
            run_python(py, shared2.as_ref(), &req, view_ref, &params, &endpoint, &hint, &allowed, fast)
                .unwrap_or_else(|e| python_error_response(py, shared2.as_ref(), e))
        })
    })
    .await;
    match joined {
        Ok(r) => r,
        Err(_) => simple(500), // panic in a handler task
    }
}

fn run_python(
    py: Python<'_>,
    shared: &Shared,
    req: &Req,
    view: Option<&Py<PyAny>>,
    params: &[crate::router::Param],
    endpoint: &str,
    hint: &str,
    allowed: &[String],
    fast: bool,
) -> PyResult<ResponseOut> {
    let qp = PyList::new_bound(
        py,
        req.query_pairs.iter().map(|(a, b)| (a.as_str(), b.as_str())),
    );
    let hp = PyList::new_bound(
        py,
        req.headers.iter().map(|(a, b)| (a.as_str(), b.as_str())),
    );
    let body = PyBytes::new_bound(py, &req.body);
    let kwargs = PyDict::new_bound(py);
    for (k, v, kind) in params {
        // 按转换器种类传 Python 原生类型（与 Flask/Werkzeug 对齐）：
        // 1=int -> int, 2=float -> float, 3=uuid -> uuid.UUID, 其余 -> str
        match *kind {
            1 => {
                if let Ok(i) = v.parse::<i64>() {
                    kwargs.set_item(k, i)?;
                } else {
                    kwargs.set_item(k, v)?;
                }
            }
            2 => {
                if let Ok(f) = v.parse::<f64>() {
                    kwargs.set_item(k, f)?;
                } else {
                    kwargs.set_item(k, v)?;
                }
            }
            3 => {
                let uuid_obj = shared.uuid_cls.bind(py).call1((v,)).map_err(|e| e)?;
                kwargs.set_item(k, uuid_obj)?;
            }
            _ => {
                kwargs.set_item(k, v)?;
            }
        }
    }
    let rq = shared.req_cls.call_bound(
        py,
        (
            req.method.as_str(),
            decode_path(&req.path),
            req.query_raw.as_str(),
            qp,
            hp,
            &body,
            req.remote_addr.as_str(),
            if endpoint.is_empty() { None } else { Some(endpoint) },
            Some(kwargs.clone()),
            if hint.is_empty() { None } else { Some(hint) },
            if allowed.is_empty() { None } else { Some(allowed.to_vec()) },
        ),
        None,
    )?;

    let rv = if fast {
        if let (Some(view), Some(fast_pipeline)) = (view, shared.fast_pipeline.as_ref()) {
            fast_pipeline.bind(py).call1((rq, view, &kwargs))?
        } else {
            shared.dispatch.bind(py).call1((rq,))?
        }
    } else if shared.fast {
        if let Some(view) = view {
            shared.pipeline.bind(py).call1((rq, view, &kwargs))?
        } else {
            shared.dispatch.bind(py).call1((rq,))?
        }
    } else {
        shared.dispatch.bind(py).call1((rq,))?
    };
    convert(py, &rv, shared)
}

fn python_error_response(py: Python<'_>, shared: &Shared, err: PyErr) -> ResponseOut {
    let val = err.value_bound(py).clone();
    let is_http_exc = val.is_instance(shared.http_exc.bind(py)).unwrap_or(false);
    // 非 HTTP 异常，或 TRAP_HTTP_EXCEPTIONS 模式下，走 500 处理链
    if !is_http_exc || shared.trap_http {
        if shared.debug {
            if let Ok(resp) = shared.debug_page.bind(py).call1((val,)) {
                if let Ok(out) = parse_fast_tuple(py, &resp) {
                    return out;
                }
            }
        }
        err.print(py);
        return simple(500);
    }
    if is_http_exc {
        if let Ok(resp) = val.call_method0("get_response") {
            if let Ok(out) = parse_fast_tuple(py, &resp) {
                return out;
            }
        }
        return simple(500);
    }
    err.print(py);
    simple(500)
}

fn parse_fast_tuple(py: Python<'_>, obj: &Bound<'_, PyAny>) -> PyResult<ResponseOut> {
    let t = obj
        .getattr("_fast")?
        .call0()?
        .downcast_into::<PyTuple>()
        .map_err(|_| PyErr::new::<pyo3::exceptions::PyTypeError, _>("_fast() must return a tuple"))?;
    let status = t.get_item(0)?.extract::<u16>()?;
    let headers = headers_from_py(py, &t.get_item(1)?)?;
    let body_item = t.get_item(2)?;
    let body = if body_item.downcast::<PyBytes>().is_ok() {
        body_item.downcast::<PyBytes>().unwrap().as_bytes().to_vec()
    } else if let Ok(s) = body_item.extract::<String>() {
        s.into_bytes()
    } else {
        Vec::new()
    };
    Ok(ResponseOut::new(status, headers, body))
}

fn headers_from_py(py: Python<'_>, o: &Bound<'_, PyAny>) -> PyResult<Vec<(String, String)>> {
    let _ = py;
    let mut out = Vec::new();
    if o.is_instance_of::<PyDict>() {
        for (k, v) in o.downcast::<PyDict>().unwrap().iter() {
            out.push((k.extract::<String>()?, v.extract::<String>()?));
        }
    } else if o.is_instance_of::<PyList>() || o.is_instance_of::<PyTuple>() {
        let seq = if o.is_instance_of::<PyList>() {
            o.downcast::<PyList>().unwrap().iter().collect::<Vec<_>>()
        } else {
            o.downcast::<PyTuple>().unwrap().iter().collect::<Vec<_>>()
        };
        for item in seq {
            let pair = item.downcast::<PyTuple>().map_err(|_| {
                PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                    "response headers must be a list of (name, value) tuples",
                )
            })?;
            out.push((pair.get_item(0)?.extract::<String>()?, pair.get_item(1)?.extract::<String>()?));
        }
    } else if let Ok(method) = o.getattr("to_list") {
        let list = method.call0()?;
        return headers_from_py(py, &list);
    }
    Ok(out)
}

fn convert(py: Python<'_>, rv: &Bound<'_, PyAny>, shared: &Shared) -> PyResult<ResponseOut> {
    if rv.is_none() {
        return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            "The view function did not return a valid response. The function either returned None or ended without a return statement.",
        ));
    }
    // str -> text/html
    if rv.is_instance_of::<pyo3::types::PyString>() {
        let s = rv.extract::<String>()?;
        return Ok(ResponseOut::new(
            200,
            vec![("Content-Type".into(), "text/html; charset=utf-8".into())],
            s.into_bytes(),
        ));
    }
    // bytes -> application/octet-stream
    if let Ok(b) = rv.downcast::<PyBytes>() {
        return Ok(ResponseOut::new(
            200,
            vec![("Content-Type".into(), "application/octet-stream".into())],
            b.as_bytes().to_vec(),
        ));
    }
    // dict/list -> JSON (sorted keys, ensure_ascii, like Flask's provider)
    if rv.is_instance_of::<PyDict>() || rv.is_instance_of::<PyList>() {
        let s = json::dumps(py, rv).map_err(pyo3::exceptions::PyValueError::new_err)?;
        return Ok(ResponseOut::new(
            200,
            vec![("Content-Type".into(), "application/json".into())],
            s.into_bytes(),
        ));
    }
    // (body, status[, headers]) tuple
    if rv.is_instance_of::<PyTuple>() {
        let t = rv.downcast::<PyTuple>().unwrap();
        if !(2..=3).contains(&t.len()) {
            return Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
                "The view function did not return a valid response tuple",
            ));
        }
        let mut resp = convert_part(py, &t.get_item(0)?, shared)?;
        if t.len() >= 2 {
            let st = t.get_item(1)?;
            if let Ok(i) = st.extract::<i64>() {
                resp.status = i as u16;
            } else if let Ok(s) = st.extract::<String>() {
                let digits: String = s.chars().take_while(|c| c.is_ascii_digit()).collect();
                resp.status = digits.parse::<u16>().unwrap_or(resp.status);
            }
        }
        if t.len() == 3 {
            for (k, v) in headers_from_py(py, &t.get_item(2)?)? {
                resp.headers.retain(|(ek, _)| !ek.eq_ignore_ascii_case(&k));
                resp.headers.push((k, v));
            }
        }
        return Ok(resp);
    }
    // anything with _fast() (zan.Response, zan.HTTPException.get_response())
    if let Ok(m) = rv.getattr("_fast") {
        if m.is_callable() {
            return parse_fast_tuple(py, rv);
        }
    }
    // fallback: let Python convert (make_response)
    let resp = shared.convert_slow.bind(py).call1((rv,))?;
    parse_fast_tuple(py, &resp)
}

fn convert_part(py: Python<'_>, o: &Bound<'_, PyAny>, shared: &Shared) -> PyResult<ResponseOut> {
    if o.is_instance_of::<pyo3::types::PyString>()
        || o.is_instance_of::<PyBytes>()
        || o.is_instance_of::<PyDict>()
        || o.is_instance_of::<PyList>()
    {
        convert(py, o, shared)
    } else if let Ok(r) = convert_slow_response(py, o, shared) {
        Ok(r)
    } else {
        Err(PyErr::new::<pyo3::exceptions::PyTypeError, _>(
            "invalid response body element in tuple",
        ))
    }
}

fn convert_slow_response(py: Python<'_>, o: &Bound<'_, PyAny>, shared: &Shared) -> PyResult<ResponseOut> {
    if let Ok(m) = o.getattr("_fast") {
        if m.is_callable() {
            return parse_fast_tuple(py, o);
        }
    }
    let resp = shared.convert_slow.bind(py).call1((o,))?;
    parse_fast_tuple(py, &resp)
}

// ---------------------------------------------------------------------------
// connection serving
// ---------------------------------------------------------------------------

pub async fn serve(listener: TcpListener, shared: Arc<Shared>, mut shutdown: tokio::sync::watch::Receiver<bool>) {
    loop {
        tokio::select! {
            acc = listener.accept() => match acc {
                Ok((stream, peer)) => {
                    let sh = shared.clone();
                    tokio::spawn(serve_conn(stream, sh, peer));
                }
                Err(_) => break,
            },
            _ = shutdown.changed() => break,
        }
    }
}

struct HeadInfo {
    method: String,
    path: String, // includes query
    version11: bool,
    headers: Vec<(String, String)>,
}

impl HeadInfo {
    fn keep_alive(&self) -> bool {
        match header_get(&self.headers, "connection") {
            Some(v) if v.eq_ignore_ascii_case("close") => false,
            Some(v) if v.eq_ignore_ascii_case("keep-alive") => true,
            _ => self.version11,
        }
    }
}

enum ConnErr {
    Closed,
    Respond(u16),
}

async fn fill(read: &mut OwnedReadHalf, buf: &mut Vec<u8>, timeout: Duration) -> Result<usize, ConnErr> {
    let mut tmp = [0u8; 16384];
    let n = match tokio::time::timeout(timeout, read.read(&mut tmp)).await {
        Ok(Ok(n)) => n,
        Ok(Err(_)) => return Err(ConnErr::Closed),
        Err(_) => return Err(ConnErr::Respond(408)),
    };
    if n == 0 {
        return Err(ConnErr::Closed);
    }
    buf.extend_from_slice(&tmp[..n]);
    Ok(n)
}

/// Read `n` bytes starting at `*pos` (consuming from buf, refilling from the
/// socket as needed). Advances `*pos` on success.
async fn read_n(
    read: &mut OwnedReadHalf,
    buf: &mut Vec<u8>,
    pos: &mut usize,
    n: usize,
    max: usize,
) -> Result<Vec<u8>, ConnErr> {
    if n > max {
        return Err(ConnErr::Respond(413));
    }
    while buf.len() < *pos + n {
        fill(read, buf, BODY_TIMEOUT).await?;
    }
    let out = buf[*pos..*pos + n].to_vec();
    *pos += n;
    Ok(out)
}

/// Read one CRLF-terminated line starting at `*pos`.
async fn take_line(
    read: &mut OwnedReadHalf,
    buf: &mut Vec<u8>,
    pos: &mut usize,
    cap: usize,
) -> Result<Vec<u8>, ConnErr> {
    loop {
        if let Some(idx) = buf[*pos..].iter().position(|&b| b == b'\n') {
            let abs = *pos + idx;
            let mut line = buf[*pos..abs].to_vec();
            if line.last() == Some(&b'\r') {
                line.pop();
            }
            *pos = abs + 1;
            return Ok(line);
        }
        if buf.len() - *pos > cap {
            return Err(ConnErr::Respond(400));
        }
        fill(read, buf, BODY_TIMEOUT).await?;
    }
}

async fn write_simple(write: &mut OwnedWriteHalf, code: u16) -> std::io::Result<()> {
    let r = simple(code);
    write_response(write, &r, false, false).await
}

async fn write_response(
    write: &mut OwnedWriteHalf,
    resp: &ResponseOut,
    keep_alive: bool,
    is_head: bool,
) -> std::io::Result<()> {
    let mut head = String::with_capacity(256 + resp.headers.len() * 48);
    head.push_str("HTTP/1.1 ");
    head.push_str(&resp.status.to_string());
    head.push(' ');
    head.push_str(reason_for(resp.status));
    head.push_str("\r\nServer: ");
    head.push_str(SERVER_NAME);
    head.push_str("\r\nDate: ");
    head.push_str(&http_date_now());
    head.push_str("\r\nContent-Length: ");
    head.push_str(&resp.body.len().to_string());
    head.push_str(if keep_alive {
        "\r\nConnection: keep-alive\r\n"
    } else {
        "\r\nConnection: close\r\n"
    });
    for (k, v) in &resp.headers {
        let lk = k.to_ascii_lowercase();
        if matches!(
            lk.as_str(),
            "content-length" | "connection" | "transfer-encoding" | "keep-alive" | "date" | "server"
        ) {
            continue;
        }
        head.push_str(k);
        head.push_str(": ");
        head.push_str(v);
        head.push_str("\r\n");
    }
    head.push_str("\r\n");
    let mut out = head.into_bytes();
    if !is_head {
        out.extend_from_slice(&resp.body);
    }
    write.write_all(&out).await?;
    write.flush().await
}

/// 单个连接的服务循环：循环「读请求头 → 读 body → 调度 → 写响应」。
///
/// 支持 keep-alive（按 Connection 头与 HTTP 版本判定）、请求间把
/// 未消费的字节留给下一个请求（管线化兼容）、chunked body、
/// Expect: 100-continue，以及头部/主体的超时与大小上限。
pub async fn serve_conn(stream: TcpStream, shared: Arc<Shared>, peer: SocketAddr) {
    let ip = peer.ip().to_string();
    let (mut read, mut write) = stream.into_split();
    let mut buf: Vec<u8> = Vec::with_capacity(8192);

    'conn: loop {
        // ---- request head ----
        let (head_len, info) = loop {
            let mut hdrs = [httparse::EMPTY_HEADER; MAX_HEADER_COUNT];
            let mut preq = httparse::Request::new(&mut hdrs);
            match preq.parse(&buf) {
                Ok(httparse::Status::Complete(n)) => {
                    let method = preq.method.unwrap_or("GET").to_string();
                    let raw_target = preq.path.unwrap_or("/").to_string();
                    let version11 = preq.version.unwrap_or(1) == 1;
                    let mut headers = Vec::with_capacity(preq.headers.len());
                    for h in preq.headers.iter() {
                        if h.name.is_empty() {
                            continue;
                        }
                        headers.push((
                            h.name.to_string(),
                            String::from_utf8_lossy(h.value).into_owned(),
                        ));
                    }
                    break (
                        n,
                        HeadInfo { method, path: raw_target, version11, headers },
                    );
                }
                Ok(httparse::Status::Partial) => {
                    if buf.len() > MAX_HEAD {
                        let _ = write_simple(&mut write, 431).await;
                        return;
                    }
                    if fill(&mut read, &mut buf, HDR_TIMEOUT).await.is_err() {
                        return;
                    }
                }
                Err(_) => {
                    let _ = write_simple(&mut write, 400).await;
                    return;
                }
            }
        };

        // ---- validate target ----
        let raw_target = info.path.clone();
        let path_only = if raw_target.starts_with("http://") || raw_target.starts_with("https://") {
            match raw_target[8..].find('/') {
                Some(i) => &raw_target[8 + i..],
                None => "/",
            }
        } else if raw_target.starts_with('/') {
            &raw_target[..]
        } else {
            let _ = write_simple(&mut write, 400).await;
            return;
        };
        let (path, query_raw) = match path_only.split_once('?') {
            Some((p, q)) => (p.to_string(), q.to_string()),
            None => (path_only.to_string(), String::new()),
        };
        if path.len() > 8192 {
            let _ = write_simple(&mut write, 414).await;
            return;
        }

        // ---- body ----
        let mut pos = head_len;
        let chunked = header_get(&info.headers, "transfer-encoding")
            .map(|v| v.to_ascii_lowercase().contains("chunked"))
            .unwrap_or(false);
        if header_get(&info.headers, "expect")
            .map(|v| v.to_ascii_lowercase().contains("100-continue"))
            .unwrap_or(false)
        {
            let _ = write.write_all(b"HTTP/1.1 100 Continue\r\n\r\n").await;
        }
        let body = if chunked {
            let mut body = Vec::new();
            loop {
                let line = match take_line(&mut read, &mut buf, &mut pos, 1024).await {
                    Ok(l) => l,
                    Err(_) => {
                        let _ = write_simple(&mut write, 400).await;
                        return;
                    }
                };
                let size_str = String::from_utf8_lossy(&line);
                let size_hex = size_str.split(';').next().unwrap_or("").trim();
                let size = match usize::from_str_radix(size_hex, 16) {
                    Ok(s) => s,
                    Err(_) => {
                        let _ = write_simple(&mut write, 400).await;
                        return;
                    }
                };
                if size == 0 {
                    // trailers until blank line
                    loop {
                        match take_line(&mut read, &mut buf, &mut pos, 1024).await {
                            Ok(l) if l.is_empty() => break,
                            Ok(_) => continue,
                            Err(_) => {
                                let _ = write_simple(&mut write, 400).await;
                                return;
                            }
                        }
                    }
                    break;
                }
                if body.len() + size > shared.max_body {
                    let _ = write_simple(&mut write, 413).await;
                    return;
                }
                match read_n(&mut read, &mut buf, &mut pos, size, shared.max_body).await {
                    Ok(chunk) => body.extend_from_slice(&chunk),
                    Err(_) => {
                        let _ = write_simple(&mut write, 400).await;
                        return;
                    }
                }
                // trailing CRLF after each chunk
                if read_n(&mut read, &mut buf, &mut pos, 2, shared.max_body).await.is_err() {
                    let _ = write_simple(&mut write, 400).await;
                    return;
                }
            }
            body
        } else if let Some(cl) = header_get(&info.headers, "content-length")
            .and_then(|v| v.trim().parse::<usize>().ok())
        {
            if cl > shared.max_body {
                let _ = write_simple(&mut write, 413).await;
                return;
            }
            match read_n(&mut read, &mut buf, &mut pos, cl, shared.max_body).await {
                Ok(b) => b,
                Err(ConnErr::Respond(code)) => {
                    let _ = write_simple(&mut write, code).await;
                    return;
                }
                Err(ConnErr::Closed) => return,
            }
        } else {
            Vec::new()
        };

        // ---- dispatch ----
        let req = Req {
            method: info.method.clone(),
            path,
            query_raw: query_raw.clone(),
            query_pairs: parse_query(&query_raw),
            headers: info.headers.clone(),
            body,
            remote_addr: ip.clone(),
        };
        let is_head = req.method == "HEAD";
        let resp = handle(&shared, req).await;
        if shared.log {
            eprintln!(
                "{} - - [{}] \"{} {}\" {} {}",
                ip,
                http_date_now(),
                info.method,
                raw_target,
                resp.status,
                if is_head { 0 } else { resp.body.len() }
            );
        }
        let keep = info.keep_alive();
        if write_response(&mut write, &resp, keep, is_head).await.is_err() {
            return;
        }
        if !keep {
            return;
        }
        // keep any pipelined bytes for the next request
        if pos > 0 {
            if pos >= buf.len() {
                buf.clear();
            } else {
                buf.drain(..pos);
            }
        }
        continue 'conn;
    }
}
