//! Default English messages (`zod/locales.py::en_error`) for the common issue codes.
//!
//! Used only when no custom error applies (see `Compiled::finalize_plain`). Every function
//! returns `None` for anything it does not reproduce exactly, and Python then finalizes that
//! issue the usual way.

use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyFloat, PyFrozenSet, PyInt, PyList, PySet, PyString, PyTuple};

/// An interned key: issue fields are read without allocating a key string each time.
macro_rules! key {
    ($issue:expr, $k:literal) => {
        pyo3::intern!($issue.py(), $k)
    };
}

const SIZABLE: &[(&str, &str, &str)] = &[
    ("string", "characters", "to have"),
    ("file", "bytes", "to have"),
    ("array", "items", "to have"),
    ("set", "items", "to have"),
    ("map", "entries", "to have"),
];

const NOUNS: &[(&str, &str)] = &[
    ("regex", "input"),
    ("email", "email address"),
    ("url", "URL"),
    ("emoji", "emoji"),
    ("uuid", "UUID"),
    ("uuidv4", "UUIDv4"),
    ("uuidv6", "UUIDv6"),
    ("uuidv7", "UUIDv7"),
    ("nanoid", "nanoid"),
    ("guid", "GUID"),
    ("cuid", "cuid"),
    ("cuid2", "cuid2"),
    ("ulid", "ULID"),
    ("xid", "XID"),
    ("ksuid", "KSUID"),
    ("datetime", "ISO datetime"),
    ("date", "ISO date"),
    ("time", "ISO time"),
    ("duration", "ISO duration"),
    ("ipv4", "IPv4 address"),
    ("ipv6", "IPv6 address"),
    ("mac", "MAC address"),
    ("cidrv4", "IPv4 range"),
    ("cidrv6", "IPv6 range"),
    ("base64", "base64-encoded string"),
    ("base64url", "base64url-encoded string"),
    ("json_string", "JSON string"),
    ("e164", "E.164 number"),
    ("currency_code", "currency code"),
    ("credit_card", "credit card number"),
    ("iban", "IBAN"),
    ("jwt", "JWT"),
    ("hostname", "hostname"),
    ("hex", "hexadecimal string"),
    ("template_literal", "input"),
    ("lowercase", "lowercase string"),
    ("uppercase", "uppercase string"),
];

fn text(issue: &Bound<'_, PyDict>, key: &Bound<'_, PyString>) -> Option<String> {
    let value = issue.get_item(key).ok()??;
    if value.is_none() {
        return None;
    }
    value
        .downcast::<PyString>()
        .ok()?
        .to_str()
        .ok()
        .map(str::to_owned)
}

fn flag(issue: &Bound<'_, PyDict>, key: &Bound<'_, PyString>) -> Option<bool> {
    match issue.get_item(key).ok()? {
        None => Some(false),
        Some(v) => v.is_truthy().ok(),
    }
}

/// `_util.get_parsed_type` for the types it can name without Python-level checks.
fn parsed_type(value: &Bound<'_, PyAny>, date_types: &Bound<'_, PyAny>) -> Option<&'static str> {
    Some(if value.is_none() {
        "undefined"
    } else if value.is_instance_of::<PyBool>() {
        "boolean"
    } else if value.is_instance_of::<PyInt>() {
        "number"
    } else if let Ok(f) = value.downcast::<PyFloat>() {
        if f.value().is_nan() {
            "NaN"
        } else {
            "number"
        }
    } else if value.is_instance_of::<PyString>() {
        "string"
    } else if value.is_instance_of::<PyList>() || value.is_instance_of::<PyTuple>() {
        "array"
    } else if value.is_instance(date_types).ok()? {
        "date"
    } else if value.is_instance_of::<PySet>() || value.is_instance_of::<PyFrozenSet>() {
        "set"
    } else if value.is_exact_instance_of::<PyDict>() {
        "object"
    } else {
        return None;
    })
}

/// `_util.format_number` (dates are left to Python).
fn format_number(value: &Bound<'_, PyAny>) -> Option<String> {
    if let Ok(f) = value.downcast::<PyFloat>() {
        let f = f.value();
        if f.is_finite() && f.fract() == 0.0 {
            // Python prints `str(int(value))`; beyond 2**53 leave the digits to Python.
            return (f.abs() < 9.0e15).then(|| format!("{}", f as i64));
        }
        return value.str().ok().map(|s| s.to_string());
    }
    if value.is_instance_of::<PyInt>() && !value.is_instance_of::<PyBool>() {
        if value.is_exact_instance_of::<PyInt>() {
            if let Ok(i) = value.extract::<i64>() {
                return Some(i.to_string());
            }
        }
        return value.str().ok().map(|s| s.to_string());
    }
    None
}

/// `_util.stringify` for `str` values: `json.dumps(value, ensure_ascii=False)`.
fn stringify_str(value: &Bound<'_, PyAny>) -> Option<String> {
    let s = value.downcast::<PyString>().ok()?.to_str().ok()?;
    serde_json::to_string(s).ok()
}

/// `_util.stringify` for the primitives it prints exactly (other floats use Python's `repr`).
fn stringify(value: &Bound<'_, PyAny>) -> Option<String> {
    if value.is_none() {
        return Some("undefined".to_owned());
    }
    if let Ok(b) = value.downcast::<PyBool>() {
        return Some(if b.is_true() { "true" } else { "false" }.to_owned());
    }
    if value.is_instance_of::<PyString>() {
        return stringify_str(value);
    }
    if let Ok(f) = value.downcast::<PyFloat>() {
        let f = f.value();
        return if f.is_nan() {
            Some("NaN".to_owned())
        } else if f.is_infinite() {
            Some(if f > 0.0 { "Infinity" } else { "-Infinity" }.to_owned())
        } else if f.fract() == 0.0 {
            format_number(value)
        } else {
            None
        };
    }
    if value.is_exact_instance_of::<PyInt>() {
        return format_number(value);
    }
    None
}

fn size_message(issue: &Bound<'_, PyDict>, big: bool) -> Option<String> {
    let adj = if flag(issue, key!(issue, "exact"))? {
        "exactly "
    } else if flag(issue, key!(issue, "inclusive"))? {
        if big {
            "<="
        } else {
            ">="
        }
    } else if big {
        "<"
    } else {
        ">"
    };
    let origin = match issue.get_item(key!(issue, "origin")).ok()? {
        Some(o) if o.is_truthy().ok()? => o.downcast::<PyString>().ok()?.to_str().ok()?.to_owned(),
        _ => "value".to_owned(),
    };
    let bound = format_number(
        &issue
            .get_item(if big {
                key!(issue, "maximum")
            } else {
                key!(issue, "minimum")
            })
            .ok()??,
    )?;
    let head = if big { "Too big" } else { "Too small" };
    Some(match SIZABLE.iter().find(|(o, _, _)| *o == origin) {
        Some((_, unit, verb)) => format!("{head}: expected {origin} {verb} {adj}{bound} {unit}"),
        None => format!("{head}: expected {origin} to be {adj}{bound}"),
    })
}

/// The default English message for `issue`, or `None` to let Python build it. `input` is the
/// issue's input, passed separately: the finished dict may leave it out.
pub fn en_message(
    issue: &Bound<'_, PyDict>,
    input: Option<&Bound<'_, PyAny>>,
    date_types: &Bound<'_, PyAny>,
) -> Option<String> {
    let code = issue.get_item(key!(issue, "code")).ok()??;
    match code.downcast::<PyString>().ok()?.to_str().ok()? {
        "invalid_type" => {
            let expected = text(issue, key!(issue, "expected"))?;
            let received = match issue
                .get_item(key!(issue, "received"))
                .ok()?
                .filter(|r| !r.is_none())
            {
                Some(r) => r.downcast::<PyString>().ok()?.to_str().ok()?.to_owned(),
                None => parsed_type(input?, date_types)?.to_owned(),
            };
            Some(format!(
                "Invalid input: expected {expected}, received {received}"
            ))
        }
        "too_big" => size_message(issue, true),
        "too_small" => size_message(issue, false),
        "invalid_format" => {
            let fmt = text(issue, key!(issue, "format"))?;
            let needle = |k: &Bound<'_, PyString>| stringify_str(&issue.get_item(k).ok()??);
            Some(match fmt.as_str() {
                "starts_with" => format!(
                    "Invalid string: must start with {}",
                    needle(key!(issue, "prefix"))?
                ),
                "ends_with" => format!(
                    "Invalid string: must end with {}",
                    needle(key!(issue, "suffix"))?
                ),
                "includes" => format!(
                    "Invalid string: must include {}",
                    needle(key!(issue, "includes"))?
                ),
                "regex" => format!(
                    "Invalid string: must match pattern {}",
                    text(issue, key!(issue, "pattern"))?
                ),
                other => {
                    let noun = NOUNS
                        .iter()
                        .find(|(f, _)| *f == other)
                        .map_or(other, |(_, n)| n);
                    format!("Invalid {noun}")
                }
            })
        }
        "invalid_value" => {
            let values = issue.get_item(key!(issue, "values")).ok()??;
            let parts = values
                .downcast::<PyList>()
                .ok()?
                .iter()
                .map(|v| stringify(&v))
                .collect::<Option<Vec<_>>>()?;
            Some(match parts.as_slice() {
                [only] => format!("Invalid input: expected {only}"),
                _ => format!("Invalid option: expected one of {}", parts.join("|")),
            })
        }
        "not_multiple_of" => Some(format!(
            "Invalid number: must be a multiple of {}",
            format_number(&issue.get_item(key!(issue, "divisor")).ok()??)?
        )),
        "unrecognized_keys" => {
            let keys = issue.get_item(key!(issue, "keys")).ok()??;
            let keys = keys.downcast::<PyList>().ok()?;
            let parts = keys
                .iter()
                .map(|k| stringify_str(&k))
                .collect::<Option<Vec<_>>>()?;
            let plural = if parts.len() > 1 { "s" } else { "" };
            Some(format!("Unrecognized key{plural}: {}", parts.join(", ")))
        }
        _ => None,
    }
}
