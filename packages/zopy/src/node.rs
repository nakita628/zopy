//! Compiled schema nodes and their construction from the Python-side node dicts.

use crate::formats::{Format, FormatOptions};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rung {
    Required,
    Optional,
    Defaulted,
}

#[derive(Debug)]
pub enum Catchall {
    Strip,
    Strict,
    Loose,
    Schema(usize),
}

#[derive(Debug)]
pub struct Field {
    pub name: Py<PyString>,
    pub key: String,
    pub node: usize,
    pub optin: Rung,
    pub optout_optional: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NumKind {
    Float,
    Int,
    BigInt,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RecordMode {
    Normal,
    Partial,
    Loose,
}

#[derive(Debug)]
pub enum OverwriteOp {
    Trim,
    Lower,
    Upper,
    Normalize(String),
}

#[derive(Debug)]
pub enum CheckKind {
    Size {
        min: Option<i64>,
        max: Option<i64>,
        exact: bool,
        origin: String,
    },
    Bound {
        lower: Option<Limit>,
        upper: Option<Limit>,
        origin: String,
    },
    MultipleOf {
        divisor: Py<PyAny>,
        origin: String,
    },
    Format {
        name: String,
        format: Format,
        pattern: Option<String>,
        extra: Vec<(String, Py<PyAny>)>,
    },
    Includes {
        needle: String,
        position: usize,
    },
    /// A user regex run natively; `fallback` is the Python check, used for values the two
    /// engines could disagree on (`dollar`: Python's `$` also matches before a final `\n`).
    Regex {
        name: String,
        format: Format,
        pattern: String,
        dollar: bool,
        fallback: Py<PyAny>,
    },
    StartsWith(String),
    EndsWith(String),
    Overwrite(OverwriteOp),
    Py(Py<PyAny>),
}

/// One side of a `gt` / `gte` / `lt` / `lte` check.
#[derive(Debug)]
pub struct Limit {
    pub value: Py<PyAny>,
    pub inclusive: bool,
    /// `value` as `i64` when it is an exact `int`, for comparing ints without Python calls.
    pub int: Option<i64>,
}

impl Limit {
    fn new(value: &Bound<'_, PyAny>, inclusive: bool) -> Limit {
        let int = if value.is_exact_instance_of::<pyo3::types::PyInt>() {
            value.extract::<i64>().ok()
        } else {
            None
        };
        Limit {
            value: value.clone().unbind(),
            inclusive,
            int,
        }
    }
}

#[derive(Debug)]
pub struct Check {
    pub kind: CheckKind,
    pub error: Option<Py<PyAny>>,
    pub abort: bool,
}

#[derive(Debug)]
pub enum NodeKind {
    Str {
        coerce: bool,
    },
    Num {
        kind: NumKind,
        coerce: bool,
        safeint: bool,
        int_error: Option<Py<PyAny>>,
    },
    Bool {
        coerce: bool,
    },
    Date {
        coerce: Option<Py<PyAny>>,
    },
    NoneValue {
        expected: String,
    },
    Any,
    Never,
    NaN,
    Literal {
        values: Vec<Py<PyAny>>,
    },
    Enum {
        values: Vec<Py<PyAny>>,
        members: Vec<Option<Py<PyAny>>>,
    },
    Array {
        element: usize,
    },
    Tuple {
        items: Vec<usize>,
        optional: Vec<bool>,
        rest: Option<usize>,
    },
    Object {
        fields: Vec<Field>,
        catchall: Catchall,
        cls: Option<Py<PyAny>>,
    },
    Record {
        key: usize,
        value: usize,
        mode: RecordMode,
        exhaustive: Option<Vec<Py<PyAny>>>,
    },
    Map {
        key: usize,
        value: usize,
    },
    Set {
        value: usize,
    },
    Union {
        options: Vec<usize>,
        exclusive: bool,
    },
    Discriminated {
        disc: Py<PyString>,
        options: Vec<(Vec<Py<PyAny>>, usize)>,
        all: Vec<Py<PyAny>>,
        fallback: bool,
    },
    Optional {
        inner: usize,
        exact: bool,
        defaulted: bool,
    },
    Nullable {
        inner: usize,
        defaulted: bool,
    },
    NonOptional {
        inner: usize,
    },
    Default {
        inner: usize,
        value: Py<PyAny>,
        callable: bool,
        prefault: bool,
    },
    Catch {
        inner: usize,
        value: Py<PyAny>,
        callable: bool,
    },
    Pipe {
        left: usize,
        right: usize,
    },
    /// `z.codec(in_, out, decode=..., encode=...)`: `left` is `in_`, `right` is `out`.
    Codec {
        left: usize,
        right: usize,
        decode: Py<PyAny>,
        encode: Py<PyAny>,
    },
    StringBool {
        truthy: Vec<String>,
        falsy: Vec<String>,
        sensitive: bool,
    },
    Python,
}

#[derive(Debug)]
pub struct Node {
    pub kind: NodeKind,
    pub checks: Vec<Check>,
    pub schema: Py<PyAny>,
    /// The schema has its own `error`, so its issues need Python's message resolution.
    pub has_error: bool,
}

// ---------------------------------------------------------------------------
// helpers for reading the Python dicts
// ---------------------------------------------------------------------------

fn get<'py>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    d.get_item(key)?
        .ok_or_else(|| PyValueError::new_err(format!("node is missing key {key:?}")))
}

fn opt<'py>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
    Ok(d.get_item(key)?.filter(|v| !v.is_none()))
}

fn get_str(d: &Bound<'_, PyDict>, key: &str) -> PyResult<String> {
    get(d, key)?.extract()
}

fn get_bool(d: &Bound<'_, PyDict>, key: &str) -> PyResult<bool> {
    Ok(opt(d, key)?
        .map(|v| v.is_truthy())
        .transpose()?
        .unwrap_or(false))
}

fn get_usize(d: &Bound<'_, PyDict>, key: &str) -> PyResult<usize> {
    get(d, key)?.extract()
}

fn opt_usize(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<usize>> {
    opt(d, key)?.map(|v| v.extract()).transpose()
}

fn get_ids(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<usize>> {
    get(d, key)?.extract()
}

fn get_objs(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<Py<PyAny>>> {
    get(d, key)?
        .try_iter()?
        .map(|v| v.map(Bound::unbind))
        .collect::<PyResult<Vec<_>>>()
}

fn opt_obj(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<Py<PyAny>>> {
    Ok(opt(d, key)?.map(Bound::unbind))
}

fn strings(d: &Bound<'_, PyDict>, key: &str) -> PyResult<Vec<String>> {
    get(d, key)?.extract()
}

// ---------------------------------------------------------------------------
// construction
// ---------------------------------------------------------------------------

pub fn build_nodes(nodes: &Bound<'_, PyList>) -> PyResult<Vec<Node>> {
    nodes
        .iter()
        .map(|n| build_node(n.downcast::<PyDict>()?))
        .collect()
}

fn build_node(d: &Bound<'_, PyDict>) -> PyResult<Node> {
    let t = get_str(d, "t")?;
    let kind = match t.as_str() {
        "string" => NodeKind::Str {
            coerce: get_bool(d, "coerce")?,
        },
        "number" => NodeKind::Num {
            kind: match get_str(d, "kind")?.as_str() {
                "int" => NumKind::Int,
                "bigint" => NumKind::BigInt,
                _ => NumKind::Float,
            },
            coerce: get_bool(d, "coerce")?,
            safeint: get_bool(d, "safeint")?,
            int_error: opt_obj(d, "int_error")?,
        },
        "boolean" => NodeKind::Bool {
            coerce: get_bool(d, "coerce")?,
        },
        "date" => NodeKind::Date {
            coerce: opt_obj(d, "coerce")?,
        },
        "none" => NodeKind::NoneValue {
            expected: get_str(d, "expected")?,
        },
        "any" => NodeKind::Any,
        "never" => NodeKind::Never,
        "nan" => NodeKind::NaN,
        "literal" => NodeKind::Literal {
            values: get_objs(d, "values")?,
        },
        "enum" => NodeKind::Enum {
            values: get_objs(d, "values")?,
            members: get(d, "members")?
                .try_iter()?
                .map(|m| m.map(|m| if m.is_none() { None } else { Some(m.unbind()) }))
                .collect::<PyResult<Vec<_>>>()?,
        },
        "array" => NodeKind::Array {
            element: get_usize(d, "element")?,
        },
        "tuple" => NodeKind::Tuple {
            items: get_ids(d, "items")?,
            optional: get(d, "optional")?.extract()?,
            rest: opt_usize(d, "rest")?,
        },
        "object" => {
            let mut fields = Vec::new();
            for f in get(d, "fields")?.try_iter()? {
                let f = f?;
                let name: Bound<'_, PyString> = f.get_item(0)?.downcast_into()?;
                let node: usize = f.get_item(1)?.extract()?;
                let optin = match f.get_item(2)?.extract::<Option<String>>()?.as_deref() {
                    Some("optional") => Rung::Optional,
                    Some("defaulted") => Rung::Defaulted,
                    _ => Rung::Required,
                };
                let optout_optional = f.get_item(3)?.is_truthy()?;
                fields.push(Field {
                    key: name.to_string(),
                    name: name.unbind(),
                    node,
                    optin,
                    optout_optional,
                });
            }
            let catchall_raw = get(d, "catchall")?;
            let catchall = if let Ok(s) = catchall_raw.extract::<String>() {
                match s.as_str() {
                    "strict" => Catchall::Strict,
                    "loose" => Catchall::Loose,
                    _ => Catchall::Strip,
                }
            } else {
                Catchall::Schema(catchall_raw.extract()?)
            };
            NodeKind::Object {
                fields,
                catchall,
                cls: opt_obj(d, "cls")?,
            }
        }
        "record" => NodeKind::Record {
            key: get_usize(d, "key")?,
            value: get_usize(d, "value")?,
            mode: match get_str(d, "mode")?.as_str() {
                "partial" => RecordMode::Partial,
                "loose" => RecordMode::Loose,
                _ => RecordMode::Normal,
            },
            exhaustive: match opt(d, "exhaustive")? {
                Some(v) => Some(
                    v.try_iter()?
                        .map(|x| x.map(Bound::unbind))
                        .collect::<PyResult<Vec<_>>>()?,
                ),
                None => None,
            },
        },
        "map" => NodeKind::Map {
            key: get_usize(d, "key")?,
            value: get_usize(d, "value")?,
        },
        "set" => NodeKind::Set {
            value: get_usize(d, "value")?,
        },
        "union" => NodeKind::Union {
            options: get_ids(d, "options")?,
            exclusive: get_bool(d, "exclusive")?,
        },
        "discriminated" => {
            let mut options = Vec::new();
            for o in get(d, "options")?.try_iter()? {
                let o = o?;
                let values = o
                    .get_item(0)?
                    .try_iter()?
                    .map(|x| x.map(Bound::unbind))
                    .collect::<PyResult<Vec<_>>>()?;
                options.push((values, o.get_item(1)?.extract()?));
            }
            NodeKind::Discriminated {
                disc: get(d, "disc")?.downcast_into::<PyString>()?.unbind(),
                options,
                all: get_objs(d, "all")?,
                fallback: get_bool(d, "fallback")?,
            }
        }
        "optional" => NodeKind::Optional {
            inner: get_usize(d, "inner")?,
            exact: get_bool(d, "exact")?,
            defaulted: get_bool(d, "defaulted")?,
        },
        "nullable" => NodeKind::Nullable {
            inner: get_usize(d, "inner")?,
            defaulted: get_bool(d, "defaulted")?,
        },
        "nonoptional" => NodeKind::NonOptional {
            inner: get_usize(d, "inner")?,
        },
        "default" => NodeKind::Default {
            inner: get_usize(d, "inner")?,
            value: get(d, "value")?.unbind(),
            callable: get_bool(d, "callable")?,
            prefault: get_bool(d, "prefault")?,
        },
        "catch" => NodeKind::Catch {
            inner: get_usize(d, "inner")?,
            value: get(d, "value")?.unbind(),
            callable: get_bool(d, "callable")?,
        },
        "pipe" => NodeKind::Pipe {
            left: get_usize(d, "left")?,
            right: get_usize(d, "right")?,
        },
        "codec" => NodeKind::Codec {
            left: get_usize(d, "left")?,
            right: get_usize(d, "right")?,
            decode: get(d, "decode")?.unbind(),
            encode: get(d, "encode")?.unbind(),
        },
        "stringbool" => NodeKind::StringBool {
            truthy: strings(d, "truthy")?,
            falsy: strings(d, "falsy")?,
            sensitive: get_bool(d, "sensitive")?,
        },
        "python" => NodeKind::Python,
        other => {
            return Err(PyValueError::new_err(format!(
                "unknown node type {other:?}"
            )))
        }
    };
    let checks = match opt(d, "checks")? {
        Some(list) => list
            .try_iter()?
            .map(|c| build_check(c?.downcast::<PyDict>()?))
            .collect::<PyResult<Vec<_>>>()?,
        None => Vec::new(),
    };
    Ok(Node {
        kind,
        checks,
        schema: get(d, "schema")?.unbind(),
        has_error: get_bool(d, "has_error")?,
    })
}

fn build_check(d: &Bound<'_, PyDict>) -> PyResult<Check> {
    let k = get_str(d, "k")?;
    let kind = match k.as_str() {
        "size" => CheckKind::Size {
            min: opt(d, "min")?.map(|v| v.extract()).transpose()?,
            max: opt(d, "max")?.map(|v| v.extract()).transpose()?,
            exact: get_bool(d, "exact")?,
            origin: get_str(d, "origin")?,
        },
        "bound" => CheckKind::Bound {
            lower: opt(d, "min")?
                .map(|v| PyResult::Ok(Limit::new(&v, get_bool(d, "min_inclusive")?)))
                .transpose()?,
            upper: opt(d, "max")?
                .map(|v| PyResult::Ok(Limit::new(&v, get_bool(d, "max_inclusive")?)))
                .transpose()?,
            origin: get_str(d, "origin")?,
        },
        "multiple_of" => CheckKind::MultipleOf {
            divisor: get(d, "divisor")?.unbind(),
            origin: get_str(d, "origin")?,
        },
        "format" => {
            let name = get_str(d, "format")?;
            let mut fo = FormatOptions::default();
            if let Some(o) = opt(d, "opts")? {
                let o = o.downcast::<PyDict>()?;
                fo.version = opt(o, "version")?.map(|v| v.extract()).transpose()?;
                fo.precision = opt(o, "precision")?.map(|v| v.extract()).transpose()?;
                fo.offset = get_bool(o, "offset")?;
                fo.local = get_bool(o, "local")?;
                fo.alg = opt(o, "alg")?.map(|v| v.extract()).transpose()?;
                fo.enc = opt(o, "enc")?.map(|v| v.extract()).transpose()?;
                fo.delimiter = opt(o, "delimiter")?.map(|v| v.extract()).transpose()?;
            }
            let format = Format::new(&name, &fo).ok_or_else(|| {
                PyValueError::new_err(format!("format {name:?} is not supported natively"))
            })?;
            let mut extra = Vec::new();
            if let Some(e) = opt(d, "extra")? {
                for (key, value) in e.downcast::<PyDict>()?.iter() {
                    extra.push((key.extract::<String>()?, value.unbind()));
                }
            }
            CheckKind::Format {
                name,
                format,
                pattern: opt(d, "pattern")?.map(|v| v.extract()).transpose()?,
                extra,
            }
        }
        "includes" => CheckKind::Includes {
            needle: get_str(d, "needle")?,
            position: opt(d, "position")?
                .map(|v| v.extract())
                .transpose()?
                .unwrap_or(0),
        },
        "starts_with" => CheckKind::StartsWith(get_str(d, "needle")?),
        "ends_with" => CheckKind::EndsWith(get_str(d, "needle")?),
        "overwrite" => CheckKind::Overwrite(match get_str(d, "op")?.as_str() {
            "trim" => OverwriteOp::Trim,
            "lower" => OverwriteOp::Lower,
            "upper" => OverwriteOp::Upper,
            "normalize" => OverwriteOp::Normalize(
                opt(d, "form")?
                    .map(|v| v.extract())
                    .transpose()?
                    .unwrap_or_else(|| "NFC".into()),
            ),
            other => {
                return Err(PyValueError::new_err(format!(
                    "unknown overwrite op {other:?}"
                )))
            }
        }),
        "regex" => {
            let fallback = get(d, "fallback")?.unbind();
            match Format::pattern(&get_str(d, "source")?) {
                Some(format) => CheckKind::Regex {
                    name: get_str(d, "format")?,
                    format,
                    pattern: get_str(d, "pattern")?,
                    dollar: get_bool(d, "dollar")?,
                    fallback,
                },
                None => CheckKind::Py(fallback),
            }
        }
        "py" => CheckKind::Py(get(d, "check")?.unbind()),
        other => {
            return Err(PyValueError::new_err(format!(
                "unknown check kind {other:?}"
            )))
        }
    };
    Ok(Check {
        kind,
        error: opt_obj(d, "error")?,
        abort: get_bool(d, "abort")?,
    })
}
