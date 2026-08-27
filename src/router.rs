//! URL 路由：Flask/Werkzeug 风格规则（`/user/<int:id>`、`/files/<path:p>`）。
//!
//! 匹配策略：把原始（百分号编码的）路径按 `/` 切段，在 trie 上同时走
//! 静态段与参数段，收集全部候选（优先级：静态 > int > float > uuid >
//! any > string > path 尾段），由调用方按 HTTP 方法裁决。
//! 未命中时套用 Werkzeug 的重定向规则（合并斜杠、严格尾斜杠，308）。

use pyo3::prelude::*;

/// 路由参数在 FFI 边界上的表示：(变量名, URL 解码后的值, 转换器种类)。
/// 种类码沿用 `conv_key`：1=int 2=float 3=uuid 4=any 5=string 6=path。
pub type Param = (String, String, u8);

#[derive(Clone, Debug, PartialEq)]
pub enum Conv {
    Str,
    Int,
    Float,
    Path,
    Uuid,
    Any(Vec<String>),
}

#[derive(Clone)]
pub struct NativeResponse {
    pub status: u16,
    pub headers: Vec<(String, String)>,
    pub body: Vec<u8>,
}

pub struct Route {
    /// kept for debugging/`url_map` parity
    #[allow(dead_code)]
    pub rule: String,
    pub endpoint: String,
    pub methods: Vec<String>,
    pub view: Py<PyAny>,
    pub auto_options: bool,
    /// whether the rule itself ends with `/` (strict-slash semantics)
    pub strict_trailing: bool,
    /// Optional fully-Rust response; when present the route is served without Python.
    pub native_response: Option<NativeResponse>,
    /// When true and no native response, Rust uses the fast Python pipeline.
    pub fast: bool,
    /// Optional fully-Rust dynamic handler identifier (e.g. "db", "queries").
    pub native_handler: Option<String>,
}

#[derive(Default)]
pub struct Node {
    pub statics: Vec<(String, Node)>, // small fan-out, linear scan is fine
    pub params: Vec<(String, Conv, Box<Node>)>,
    pub tail: Option<(String, usize)>, // <path:...> catch-all, route index
    pub route: Option<usize>,
}

pub enum MatchOutcome {
    /// (路由下标, 参数列表) 候选，按优先级排序。
    Candidates(Vec<(usize, Vec<Param>)>),
    /// Werkzeug 语义的永久重定向（合并斜杠 / 严格尾斜杠）。
    Redirect(String),
}

pub struct Router {
    root: Node,
    pub routes: Vec<Route>,
}

fn parse_conv(spec: &str) -> Result<Conv, String> {
    let spec = spec.trim();
    let (name, args) = match spec.find('(') {
        Some(i) => {
            if !spec.ends_with(')') {
                return Err(format!("malformed converter `{spec}`"));
            }
            (&spec[..i], &spec[i + 1..spec.len() - 1])
        }
        None => (spec, ""),
    };
    match name {
        "string" | "" => Ok(Conv::Str),
        "int" => Ok(Conv::Int),
        "float" => Ok(Conv::Float),
        "path" => Ok(Conv::Path),
        "uuid" => Ok(Conv::Uuid),
        "any" => {
            if args.is_empty() {
                return Err("`any` converter requires arguments, e.g. <any(a, b):name>".into());
            }
            let choices = args
                .split(',')
                .map(|c| c.trim().to_string())
                .filter(|c| !c.is_empty())
                .collect();
            Ok(Conv::Any(choices))
        }
        other => Err(format!("unknown converter `{other}` (supported: string, int, float, path, uuid, any)")),
    }
}

fn parse_rule(rule: &str) -> Result<Vec<(bool, String)>, String> {
    if !rule.starts_with('/') {
        return Err("URL rules must start with a leading slash".into());
    }
    let mut segs = Vec::new();
    for seg in rule.split('/') {
        if seg.is_empty() {
            continue; // tolerate double slashes in rules
        }
        if seg.starts_with('<') && seg.ends_with('>') {
            let inner = &seg[1..seg.len() - 1];
            // <name>, <name:conv>, or new-style <conv(args):name>
            let (name, conv) = match inner.rfind(':') {
                Some(i) => {
                    let left = &inner[..i];
                    let right = &inner[i + 1..];
                    if left.contains('(') {
                        // new style: <string(length=2):name>
                        (right, parse_conv(left)?)
                    } else {
                        // old style: <converter:name>
                        (right, parse_conv(left)?)
                    }
                }
                None => (inner, Conv::Str),
            };
            if name.is_empty() {
                return Err(format!("converter in `{rule}` needs a variable name"));
            }
            segs.push((true, format!("{name}\u{1}{}", conv_key(&conv))));
            // store name + conv encoded; rebuilt below
            segs.last_mut().unwrap().1 = format!("{}\u{1}{}", name, conv_spec(&conv));
        } else {
            segs.push((false, seg.to_string()));
        }
    }
    Ok(segs)
}

fn conv_key(c: &Conv) -> u8 {
    match c {
        Conv::Int => 1,
        Conv::Float => 2,
        Conv::Uuid => 3,
        Conv::Any(_) => 4,
        Conv::Str => 5,
        Conv::Path => 6,
    }
}

fn conv_spec(c: &Conv) -> String {
    match c {
        Conv::Str => "s".into(),
        Conv::Int => "i".into(),
        Conv::Float => "f".into(),
        Conv::Path => "p".into(),
        Conv::Uuid => "u".into(),
        Conv::Any(v) => format!("a{}", v.join("\u{1}")),
    }
}

fn spec_to_conv(spec: &str) -> Conv {
    match spec.as_bytes()[0] {
        b'i' => Conv::Int,
        b'f' => Conv::Float,
        b'p' => Conv::Path,
        b'u' => Conv::Uuid,
        b'a' => Conv::Any(spec[1..].split('\u{1}').map(str::to_string).collect()),
        _ => Conv::Str,
    }
}

impl Router {
    pub fn new() -> Self {
        Router { root: Node::default(), routes: Vec::new() }
    }

    pub fn add(
        &mut self,
        rule: &str,
        methods: Vec<String>,
        view: Py<PyAny>,
        endpoint: String,
        auto_options: bool,
    ) -> Result<(), String> {
        let segs = parse_rule(rule)?;
        let idx = self.routes.len();
        self.routes.push(Route {
            rule: rule.to_string(),
            endpoint,
            methods,
            view,
            auto_options,
            strict_trailing: rule.len() > 1 && rule.ends_with('/'),
            native_response: None,
            fast: false,
            native_handler: None,
        });

        let mut node = &mut self.root;
        for (i, (is_param, val)) in segs.iter().enumerate() {
            let is_last = i + 1 == segs.len();
            if !is_param {
                let pos = node.statics.iter().position(|(s, _)| s == val);
                node = match pos {
                    Some(p) => &mut node.statics[p].1,
                    None => {
                        node.statics.push((val.clone(), Node::default()));
                        let n = node.statics.len() - 1;
                        &mut node.statics[n].1
                    }
                };
            } else {
                let mut parts = val.splitn(2, '\u{1}');
                let pname = parts.next().unwrap_or("");
                let pspec = parts.next().unwrap_or("s");
                let conv = spec_to_conv(pspec);
                if conv == Conv::Path {
                    if !is_last {
                        return Err("`path` converter must be the last segment".into());
                    }
                    // node becomes the tail holder
                    node.tail = Some((pname.to_string(), idx));
                    return Ok(());
                }
                let key = conv_key(&conv);
                let pos = node.params.iter().position(|(_, c, _)| conv_key(c) == key);
                node = match pos {
                    Some(p) => {
                        // same converter kind already registered here; reuse the
                        // slot (first registered name wins during matching)
                        &mut node.params[p].2
                    }
                    None => {
                        node.params.push((pname.to_string(), conv, Box::new(Node::default())));
                        let _n = node.params.len() - 1;
                        // keep priority order: int < float < uuid < any < string
                        node.params.sort_by_key(|(_, c, _)| conv_key(c));
                        let pos = node.params.iter().position(|(_, c, _)| conv_key(c) == key).unwrap();
                        &mut node.params[pos].2
                    }
                };
            }
        }
        if node.route.is_none() {
            node.route = Some(idx);
        }
        Ok(())
    }

    /// Attach a fully-Rust response to an existing route.
    pub fn set_native_response(
        &mut self,
        rule: &str,
        method: &str,
        native: NativeResponse,
    ) -> Result<(), String> {
        let method = method.to_ascii_uppercase();
        for route in self.routes.iter_mut() {
            if route.rule == rule && route.methods.iter().any(|m| m.eq_ignore_ascii_case(&method)) {
                route.native_response = Some(native);
                return Ok(());
            }
        }
        Err(format!("no route matching `{rule}` with method `{method}`"))
    }

    /// Mark an existing route as eligible for the fast Python pipeline.
    pub fn set_fast(&mut self, rule: &str, method: &str) -> Result<(), String> {
        let method = method.to_ascii_uppercase();
        for route in self.routes.iter_mut() {
            if route.rule == rule && route.methods.iter().any(|m| m.eq_ignore_ascii_case(&method)) {
                route.fast = true;
                return Ok(());
            }
        }
        Err(format!("no route matching `{rule}` with method `{method}`"))
    }

    /// Attach a fully-Rust dynamic handler to an existing route.
    pub fn set_native_handler(&mut self, rule: &str, method: &str, handler_id: String,
    ) -> Result<(), String> {
        let method = method.to_ascii_uppercase();
        for route in self.routes.iter_mut() {
            if route.rule == rule && route.methods.iter().any(|m| m.eq_ignore_ascii_case(&method)) {
                route.native_handler = Some(handler_id);
                return Ok(());
            }
        }
        Err(format!("no route matching `{rule}` with method `{method}`"))
    }

    /// Find matching candidates for a decoded-check path. `raw_path` is the
    /// percent-encoded request path (no query string).
    pub fn find(&self, raw_path: &str) -> MatchOutcome {
        // merge-slashes: `//a///b` -> `/a/b`
        if raw_path.len() > 1 && raw_path.contains("//") {
            let mut c = String::with_capacity(raw_path.len());
            let mut prev_slash = false;
            for ch in raw_path.chars() {
                if ch == '/' {
                    if !prev_slash {
                        c.push(ch);
                    }
                    prev_slash = true;
                } else {
                    c.push(ch);
                    prev_slash = false;
                }
            }
            if c != raw_path {
                return MatchOutcome::Redirect(c);
            }
        }
        let base = raw_path;

        let segs: Vec<&str> = base.split('/').filter(|s| !s.is_empty()).collect();
        let req_trailing = base.len() > 1 && base.ends_with('/');
        let mut out = Vec::new();
        let mut params = Vec::new();
        self.walk(&self.root, &segs, &mut params, &mut out);
        // strict-slash: only keep candidates whose trailing-slash matches
        out.retain(|(idx, _)| self.routes[*idx].strict_trailing == req_trailing);
        if !out.is_empty() {
            return MatchOutcome::Candidates(out);
        }

        // trailing-slash redirect, both directions
        let alt_target = if base.len() > 1 && base.ends_with('/') {
            base[..base.len() - 1].to_string()
        } else {
            format!("{base}/")
        };
        {
            let segs: Vec<&str> = alt_target.split('/').filter(|s| !s.is_empty()).collect();
            let mut alt = Vec::new();
            let alt_trailing = alt_target.len() > 1 && alt_target.ends_with('/');
            self.walk(&self.root, &segs, &mut params, &mut alt);
            alt.retain(|(idx, _)| self.routes[*idx].strict_trailing == alt_trailing);
            if !alt.is_empty() {
                return MatchOutcome::Redirect(alt_target);
            }
        }
        MatchOutcome::Candidates(Vec::new())
    }

    fn walk(
        &self,
        node: &Node,
        segs: &[&str],
        params: &mut Vec<Param>,
        out: &mut Vec<(usize, Vec<Param>)>,
    ) {
        if segs.is_empty() {
            if let Some(i) = node.route {
                out.push((i, params.clone()));
            }
            return;
        }
        let s = segs[0];
        // 1. 静态段优先
        if let Some(child) = node.statics.iter().find(|(st, _)| st == s) {
            self.walk(&child.1, &segs[1..], params, out);
        }
        // 2. 类型化参数（插入时已按特异性排序）
        for (name, conv, child) in &node.params {
            if conv_match(conv, s) {
                params.push((name.clone(), decode_seg(s), conv_key(conv)));
                self.walk(child, &segs[1..], params, out);
                params.pop();
            }
        }
        // 3. path 兜底段
        if let Some((name, idx)) = &node.tail {
            params.push((name.clone(), decode_seg(&segs.join("/")), conv_key(&Conv::Path)));
            out.push((*idx, params.clone()));
            params.pop();
        }
    }
}

/// Check a *raw* (still percent-encoded) segment against a converter.
fn conv_match(conv: &Conv, raw: &str) -> bool {
    match conv {
        Conv::Str => !raw.is_empty(),
        Conv::Int => !raw.is_empty() && raw.bytes().all(|b| b.is_ascii_digit()),
        Conv::Float => {
            let mut saw_digit = false;
            let mut saw_dot = false;
            let bytes = raw.as_bytes();
            for (i, &b) in bytes.iter().enumerate() {
                match b {
                    b'0'..=b'9' => saw_digit = true,
                    b'.' if !saw_dot && i > 0 => saw_dot = true,
                    b'-' if i == 0 => {}
                    _ => return false,
                }
            }
            saw_digit
        }
        Conv::Uuid => {
            let b = raw.as_bytes();
            b.len() == 36
                && b[8] == b'-'
                && b[13] == b'-'
                && b[18] == b'-'
                && b[23] == b'-'
                && b.iter().enumerate().all(|(i, &c)| {
                    i == 8 || i == 13 || i == 18 || i == 23 || c.is_ascii_hexdigit()
                })
        }
        Conv::Any(choices) => choices.iter().any(|c| c == raw),
        Conv::Path => !raw.is_empty(),
    }
}

fn decode_seg(raw: &str) -> String {
    percent_encoding::percent_decode_str(raw).decode_utf8_lossy().into_owned()
}
