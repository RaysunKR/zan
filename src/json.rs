//! Python 对 JSON 的快速序列化，对齐 CPython
//! `json.dumps(obj, sort_keys=True, ensure_ascii=True)` 在常见类型
//! （None/bool/int/float/str/dict/list/tuple）上的输出。
//! 遇到不支持的类型（非 str 的 dict 键、大整数等）返回 Err，
//! 由调用方回退到 Python 的 `json` 模块。

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyList, PyString, PyTuple};

pub fn dumps(py: Python<'_>, obj: &Bound<'_, PyAny>) -> Result<String, String> {
    let mut out = String::with_capacity(64);
    write_value(py, obj, &mut out, 0)?;
    Ok(out)
}

fn write_value(
    py: Python<'_>,
    o: &Bound<'_, PyAny>,
    out: &mut String,
    depth: usize,
) -> Result<(), String> {
    if depth > 200 {
        return Err("JSON nesting too deep".into());
    }
    if o.is_none() {
        out.push_str("null");
    } else if o.is_instance_of::<PyBool>() {
        out.push_str(if o.extract::<bool>().unwrap_or(true) { "true" } else { "false" });
    } else if let Ok(i) = o.extract::<i64>() {
        out.push_str(&i.to_string());
    } else if let Ok(u) = o.extract::<u64>() {
        out.push_str(&u.to_string());
    } else if o.is_instance_of::<PyFloat>() {
        let f = o.extract::<f64>().map_err(|e| e.to_string())?;
        write_float(f, out);
    } else if o.is_instance_of::<PyString>() {
        let s: String = o.extract().map_err(|e| e.to_string())?;
        write_string(&s, out);
    } else if o.is_instance_of::<PyList>() {
        out.push('[');
        let mut first = true;
        for item in o.downcast::<PyList>().unwrap().iter() {
            if !first {
                out.push(',');
            }
            first = false;
            write_value(py, &item, out, depth + 1)?;
        }
        out.push(']');
    } else if o.is_instance_of::<PyTuple>() {
        out.push('[');
        let mut first = true;
        for item in o.downcast::<PyTuple>().unwrap().iter() {
            if !first {
                out.push(',');
            }
            first = false;
            write_value(py, &item, out, depth + 1)?;
        }
        out.push(']');
    } else if o.is_instance_of::<PyDict>() {
        let d = o.downcast::<PyDict>().unwrap();
        let mut entries: Vec<(String, Bound<'_, PyAny>)> = Vec::with_capacity(d.len());
        for (k, v) in d.iter() {
            // JSON keys must be strings; CPython json coerces int keys to
            // strings. Support exact str; anything else -> Python fallback.
            if !k.is_instance_of::<PyString>() {
                return Err("non-str dict key".into());
            }
            let key: String = k.extract().map_err(|e| e.to_string())?;
            entries.push((key, v));
        }
        entries.sort_by(|a, b| a.0.cmp(&b.0));
        out.push('{');
        let mut first = true;
        for (k, v) in entries {
            if !first {
                out.push(',');
            }
            first = false;
            write_string(&k, out);
            out.push(':');
            write_value(py, &v, out, depth + 1)?;
        }
        out.push('}');
    } else {
        return Err(format!("unsupported type {}", o.get_type().name().map_err(|e| e.to_string())?));
    }
    Ok(())
}

fn write_float(f: f64, out: &mut String) {
    if f.is_nan() {
        out.push_str("NaN");
    } else if f.is_infinite() {
        out.push_str(if f > 0.0 { "Infinity" } else { "-Infinity" });
    } else if f == f.trunc() && f.abs() < 1e16 {
        // CPython emits `1.0` rather than `1`
        out.push_str(&format!("{:.1}", f));
    } else if f.abs() >= 1e16 || (f != 0.0 && f.abs() < 1e-4) {
        // exponent form, CPython style: 1e+20
        let s = format!("{:e}", f); // e.g. "1e20", "-1.5e-7"
        let (mant, exp) = s.split_once('e').unwrap();
        let (sign, digits) = match exp.strip_prefix('-') {
            Some(d) => ('-', d),
            None => ('+', exp),
        };
        out.push_str(mant);
        out.push('e');
        out.push(sign);
        out.push_str(digits);
    } else {
        out.push_str(&format!("{}", f));
    }
}

fn write_string(s: &str, out: &mut String) {
    out.push('"');
    for c in s.chars() {
        match c {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c if (c as u32) > 0x7f => {
                // ensure_ascii: emit \uXXXX (surrogate pair for astral planes)
                let cp = c as u32;
                if cp > 0xffff {
                    let v = cp - 0x10000;
                    let hi = 0xd800 + (v >> 10);
                    let lo = 0xdc00 + (v & 0x3ff);
                    out.push_str(&format!("\\u{:04x}\\u{:04x}", hi, lo));
                } else {
                    out.push_str(&format!("\\u{:04x}", cp));
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}
