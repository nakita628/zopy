//! The validation engine: walks a compiled node tree over Python objects.

use std::borrow::Cow;

use pyo3::exceptions::{PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{
    PyBool, PyDict, PyFloat, PyFrozenSet, PyInt, PyList, PyMapping, PySet, PyString, PyTuple,
};
use pyo3::IntoPyObjectExt;
use unicode_normalization::UnicodeNormalization;

use crate::node::{
    Catchall, Check, CheckKind, Node, NodeKind, NumKind, OverwriteOp, RecordMode, Rung,
};

/// Python callables and classes the engine needs.
#[derive(Debug)]
pub struct Helpers {
    pub run_schema: Py<PyAny>,
    pub run_check: Py<PyAny>,
    pub catch_value: Py<PyAny>,
    pub coerce_number: Py<PyAny>,
    pub date_types: Py<PyAny>,
    pub enum_type: Py<PyAny>,
    pub object_base: Option<Py<PyAny>>,
    pub object_new: Py<PyAny>,
    pub object_setattr: Py<PyAny>,
    /// `BaseException.__new__`: an exception instance without running `__init__`.
    pub exception_new: Py<PyAny>,
    pub issue_type: Py<PyAny>,
    /// The global `zopy.errors._config`; its `plain` flag says no error map applies.
    pub config: Py<PyAny>,
    /// `CompiledSchema.finalize(raw, ctx)`: one issue finished in Python.
    pub finalize_one: Py<PyAny>,
    /// `CompiledSchema.build_slow(raw_issues, ctx)`: every issue finished in Python.
    pub build_slow: Py<PyAny>,
}

/// One step of an issue path. Indices stay Rust integers until an issue needs the path.
#[derive(Clone)]
pub enum PathSeg<'py> {
    Index(usize),
    Key(Bound<'py, PyAny>),
}

/// An issue field value. Rust scalars stay Rust values until the issue becomes a dict.
#[derive(Debug)]
pub enum FieldValue {
    Static(&'static str),
    Bool(bool),
    Int(i64),
    Obj(Py<PyAny>),
}

impl FieldValue {
    fn to_object<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(match self {
            FieldValue::Static(s) => PyString::new(py, s).into_any(),
            FieldValue::Bool(b) => PyBool::new(py, *b).to_owned().into_any(),
            FieldValue::Int(i) => i.into_bound_py_any(py)?,
            FieldValue::Obj(o) => o.bind(py).clone(),
        })
    }
}

/// Values accepted by [`Issue::f`].
trait IntoField {
    fn into_field(self, py: Python<'_>) -> PyResult<FieldValue>;
}

impl IntoField for &'static str {
    fn into_field(self, _py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Static(self))
    }
}

/// Origins and format names come from the compiled nodes; the common ones stay static.
impl IntoField for &String {
    fn into_field(self, py: Python<'_>) -> PyResult<FieldValue> {
        const KNOWN: &[&str] = &[
            "string",
            "number",
            "bigint",
            "array",
            "set",
            "map",
            "file",
            "date",
            "record",
            "int",
            "regex",
            "null",
            "undefined",
            "void",
        ];
        Ok(match KNOWN.iter().find(|k| **k == self.as_str()) {
            Some(k) => FieldValue::Static(k),
            None => FieldValue::Obj(PyString::new(py, self).into_any().unbind()),
        })
    }
}

impl IntoField for bool {
    fn into_field(self, _py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Bool(self))
    }
}

impl IntoField for i64 {
    fn into_field(self, _py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Int(self))
    }
}

impl IntoField for usize {
    fn into_field(self, py: Python<'_>) -> PyResult<FieldValue> {
        match i64::try_from(self) {
            Ok(i) => Ok(FieldValue::Int(i)),
            Err(_) => Ok(FieldValue::Obj(self.into_bound_py_any(py)?.unbind())),
        }
    }
}

impl IntoField for i128 {
    fn into_field(self, py: Python<'_>) -> PyResult<FieldValue> {
        match i64::try_from(self) {
            Ok(i) => Ok(FieldValue::Int(i)),
            Err(_) => Ok(FieldValue::Obj(self.into_bound_py_any(py)?.unbind())),
        }
    }
}

impl<T> IntoField for Vec<T>
where
    Vec<T>: for<'py> IntoPyObject<'py>,
{
    fn into_field(self, py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Obj(self.into_bound_py_any(py)?.unbind()))
    }
}

impl<T> IntoField for Bound<'_, T> {
    fn into_field(self, _py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Obj(self.into_any().unbind()))
    }
}

impl<T> IntoField for &Bound<'_, T> {
    fn into_field(self, _py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Obj(self.clone().into_any().unbind()))
    }
}

impl IntoField for &Py<PyAny> {
    fn into_field(self, py: Python<'_>) -> PyResult<FieldValue> {
        Ok(FieldValue::Obj(self.clone_ref(py)))
    }
}

/// The Python key for an issue field: the known keys are cached interned strings.
fn key_object<'py>(py: Python<'py>, key: &str) -> Bound<'py, PyString> {
    let cached = match key {
        "_check_error" => pyo3::intern!(py, "_check_error"),
        "discriminator" => pyo3::intern!(py, "discriminator"),
        "divisor" => pyo3::intern!(py, "divisor"),
        "errors" => pyo3::intern!(py, "errors"),
        "exact" => pyo3::intern!(py, "exact"),
        "expected" => pyo3::intern!(py, "expected"),
        "format" => pyo3::intern!(py, "format"),
        "includes" => pyo3::intern!(py, "includes"),
        "inclusive" => pyo3::intern!(py, "inclusive"),
        "issues" => pyo3::intern!(py, "issues"),
        "keys" => pyo3::intern!(py, "keys"),
        "matches" => pyo3::intern!(py, "matches"),
        "maximum" => pyo3::intern!(py, "maximum"),
        "minimum" => pyo3::intern!(py, "minimum"),
        "note" => pyo3::intern!(py, "note"),
        "options" => pyo3::intern!(py, "options"),
        "origin" => pyo3::intern!(py, "origin"),
        "pattern" => pyo3::intern!(py, "pattern"),
        "prefix" => pyo3::intern!(py, "prefix"),
        "received" => pyo3::intern!(py, "received"),
        "suffix" => pyo3::intern!(py, "suffix"),
        "values" => pyo3::intern!(py, "values"),
        other => return PyString::intern(py, other),
    };
    cached.clone()
}

/// A path step kept past the parse (in a [`RawIssue`]).
#[derive(Debug)]
pub enum OwnedSeg {
    Index(usize),
    Key(Py<PyAny>),
}

/// An issue as the engine records it. Rust-made issues stay Rust data until Python reads them
/// ([`RawIssue::to_dict`]): a parse that fails without anyone reading `error.issues` (a raising
/// `parse`, a `safeParse(...).success` check, a losing union option) builds no Python dicts.
#[derive(Debug)]
pub enum RawIssue {
    Built {
        code: &'static str,
        path: Vec<OwnedSeg>,
        input: Py<PyAny>,
        node: usize,
        /// `received: "undefined"` (a missing key failing its type check).
        received_undefined: bool,
        /// Extra fields in insertion order (`expected`, `origin`, `minimum`, ...).
        fields: Vec<(Cow<'static, str>, FieldValue)>,
        /// A failed size / bound check: `(index in the node's checks, upper bound)`. Its fields
        /// (`origin`, `minimum` / `maximum`, `inclusive`, `exact`, `_check_error`) come from the
        /// check when the issue is read, so recording it allocates nothing.
        check: Option<(usize, bool)>,
        /// An `invalid_value` from a literal / enum node: its `values` list is built from the node
        /// when the issue is read.
        node_values: bool,
    },
    /// Issues made by Python (fallback schemas and checks) arrive as dicts.
    Dict(Py<PyDict>),
}

impl RawIssue {
    /// The issue as a `ZodIssue` dict (`issue_type`): `code`, `path`, `input`, `_node`, then fields.
    pub fn to_dict<'py>(
        &self,
        py: Python<'py>,
        issue_type: &Bound<'py, PyAny>,
        nodes: &[Node],
    ) -> PyResult<Bound<'py, PyDict>> {
        self.to_dict_with(py, issue_type, nodes, true, true)
    }

    /// [`RawIssue::to_dict`] leaving out `input` and / or `_node` (a finished issue has no
    /// `_node`, and `input` only with `reportInput`). A Python-made dict is returned as is.
    pub fn to_dict_with<'py>(
        &self,
        py: Python<'py>,
        issue_type: &Bound<'py, PyAny>,
        nodes: &[Node],
        with_input: bool,
        with_node: bool,
    ) -> PyResult<Bound<'py, PyDict>> {
        let (code, path, input, node, received_undefined, fields, check, node_values) = match self {
            RawIssue::Dict(dict) => return Ok(dict.bind(py).clone()),
            RawIssue::Built {
                code,
                path,
                input,
                node,
                received_undefined,
                fields,
                check,
                node_values,
            } => (
                code,
                path,
                input,
                node,
                received_undefined,
                fields,
                check,
                node_values,
            ),
        };
        let dict = issue_type.call0()?.downcast_into::<PyDict>()?;
        dict.set_item(pyo3::intern!(py, "code"), PyString::intern(py, code))?;
        let path = PyList::new(
            py,
            path.iter().map(|seg| match seg {
                OwnedSeg::Index(i) => match i.into_pyobject(py) {
                    Ok(n) => n.into_any(),
                    Err(never) => match never {},
                },
                OwnedSeg::Key(k) => k.bind(py).clone(),
            }),
        )?;
        dict.set_item(pyo3::intern!(py, "path"), path)?;
        if with_input {
            dict.set_item(pyo3::intern!(py, "input"), input.bind(py))?;
        }
        if with_node {
            dict.set_item(pyo3::intern!(py, "_node"), *node)?;
        }
        if *received_undefined {
            dict.set_item(
                pyo3::intern!(py, "received"),
                pyo3::intern!(py, "undefined"),
            )?;
        }
        for (key, value) in fields {
            dict.set_item(key_object(py, key), value.to_object(py)?)?;
        }
        if *node_values {
            if let NodeKind::Literal { values } | NodeKind::Enum { values, .. } = &nodes[*node].kind
            {
                dict.set_item(pyo3::intern!(py, "values"), PyList::new(py, values.iter())?)?;
            }
        }
        if let Some((index, upper)) = check {
            check_fields(py, &dict, &nodes[*node].checks[*index], *upper)?;
        }
        Ok(dict)
    }
}

/// The fields of a failed size / bound / format check, in the order the builder used to add them.
fn check_fields(
    py: Python<'_>,
    dict: &Bound<'_, PyDict>,
    check: &Check,
    upper: bool,
) -> PyResult<()> {
    let side = if upper { "maximum" } else { "minimum" };
    match &check.kind {
        CheckKind::Size {
            min,
            max,
            exact,
            origin,
        } => {
            let bound = if upper { max } else { min };
            dict.set_item(
                pyo3::intern!(py, "origin"),
                origin.into_field(py)?.to_object(py)?,
            )?;
            dict.set_item(key_object(py, side), *bound)?;
            dict.set_item(pyo3::intern!(py, "inclusive"), true)?;
            dict.set_item(pyo3::intern!(py, "exact"), *exact)?;
        }
        CheckKind::Bound {
            lower,
            upper: upper_limit,
            origin,
        } => {
            let limit = if upper { upper_limit } else { lower };
            let limit = limit.as_ref().expect("failed bound has a limit");
            dict.set_item(
                pyo3::intern!(py, "origin"),
                origin.into_field(py)?.to_object(py)?,
            )?;
            dict.set_item(key_object(py, side), limit.value.bind(py))?;
            dict.set_item(pyo3::intern!(py, "inclusive"), limit.inclusive)?;
            dict.set_item(pyo3::intern!(py, "exact"), false)?;
        }
        CheckKind::Format {
            name,
            pattern,
            extra,
            ..
        } => {
            dict.set_item(pyo3::intern!(py, "origin"), pyo3::intern!(py, "string"))?;
            dict.set_item(
                pyo3::intern!(py, "format"),
                name.into_field(py)?.to_object(py)?,
            )?;
            if let Some(p) = pattern {
                dict.set_item(pyo3::intern!(py, "pattern"), p)?;
            }
            for (k, v) in extra {
                dict.set_item(PyString::intern(py, k), v.bind(py))?;
            }
        }
        _ => unreachable!("only size, bound and format checks are recorded by index"),
    }
    if let Some(err) = &check.error {
        dict.set_item(pyo3::intern!(py, "_check_error"), err.bind(py))?;
    }
    Ok(())
}

pub struct State<'py> {
    pub py: Python<'py>,
    pub issues: Vec<(RawIssue, bool)>,
    pub path: Vec<PathSeg<'py>>,
    pub ctx: Bound<'py, PyAny>,
    pub backward: bool,
    pub missing: bool,
    /// `zopy.errors.ZodIssue`; issues are created as instances so they can be finished in place.
    pub issue_type: Bound<'py, PyAny>,
}

impl<'py> State<'py> {
    fn aborted(&self, start: usize) -> bool {
        self.issues[start..].iter().any(|(_, cont)| !cont)
    }

    /// Zod's `handlePipeResult`: any issue from one side of a pipe or codec stops it, and aborts
    /// the payload (the issues become non-continuable, so the pipe's own checks are skipped).
    fn stop_pipe(&mut self, start: usize) -> bool {
        if self.issues.len() <= start {
            return false;
        }
        for (_, cont) in &mut self.issues[start..] {
            *cont = false;
        }
        true
    }

    fn path_list(&self) -> PyResult<Bound<'py, PyList>> {
        let py = self.py;
        let items = self.path.iter().map(|seg| match seg {
            PathSeg::Index(i) => match i.into_pyobject(py) {
                Ok(n) => n.into_any(),
                Err(never) => match never {},
            },
            PathSeg::Key(k) => k.clone(),
        });
        PyList::new(py, items)
    }

    fn fork(&self) -> State<'py> {
        State {
            py: self.py,
            issues: Vec::new(),
            path: self.path.clone(),
            ctx: self.ctx.clone(),
            backward: self.backward,
            missing: false,
            issue_type: self.issue_type.clone(),
        }
    }

    fn merge(&mut self, other: State<'py>) {
        self.issues.extend(other.issues);
    }

    fn merge_py_issues(&mut self, issues: &Bound<'py, PyAny>) -> PyResult<()> {
        for issue in issues.try_iter()? {
            let issue = issue?.downcast_into::<PyDict>()?;
            let cont = issue
                .get_item("continue")?
                .map(|v| v.is_truthy())
                .transpose()?
                .unwrap_or(false);
            self.issues.push((RawIssue::Dict(issue.unbind()), cont));
        }
        Ok(())
    }
}

/// Builder for one issue. Fields are added with `.f()`, then `.push()`.
struct Issue<'py> {
    py: Python<'py>,
    code: &'static str,
    path: Vec<OwnedSeg>,
    input: Py<PyAny>,
    node: usize,
    received_undefined: bool,
    fields: Vec<(Cow<'static, str>, FieldValue)>,
    check: Option<(usize, bool)>,
    node_values: bool,
    cont: bool,
}

impl<'py> Issue<'py> {
    fn new(
        st: &State<'py>,
        node: usize,
        code: &'static str,
        input: &Bound<'py, PyAny>,
        cont: bool,
    ) -> Self {
        let path = st
            .path
            .iter()
            .map(|seg| match seg {
                PathSeg::Index(i) => OwnedSeg::Index(*i),
                PathSeg::Key(k) => OwnedSeg::Key(k.clone().unbind()),
            })
            .collect();
        Issue {
            py: st.py,
            code,
            path,
            input: input.clone().unbind(),
            node,
            received_undefined: st.missing && input.is_none() && code == "invalid_type",
            fields: Vec::new(),
            check: None,
            node_values: false,
            cont,
        }
    }

    /// Keys are static: they become (interned) Python strings only when the issue is read.
    fn f<V: IntoField>(mut self, key: impl Into<Cow<'static, str>>, value: V) -> PyResult<Self> {
        let value = value.into_field(self.py)?;
        self.fields.push((key.into(), value));
        Ok(self)
    }

    fn extra_path(mut self, item: &Bound<'py, PyAny>) -> Self {
        self.path.push(OwnedSeg::Key(item.clone().unbind()));
        self
    }

    fn check_error(self, check: &Check) -> PyResult<Self> {
        match &check.error {
            Some(err) => {
                let py = self.py;
                self.f("_check_error", err.bind(py))
            }
            None => Ok(self),
        }
    }

    /// A failed size / bound check (`index` in the node's checks): its fields are read from the
    /// check when the issue becomes a dict.
    fn failed_check(mut self, index: usize, upper: bool) -> Self {
        self.check = Some((index, upper));
        self
    }

    /// An `invalid_value` whose `values` are the node's literal / enum values.
    fn node_values(mut self) -> Self {
        self.node_values = true;
        self
    }

    fn push(self, st: &mut State<'py>) {
        let issue = RawIssue::Built {
            code: self.code,
            path: self.path,
            input: self.input,
            node: self.node,
            received_undefined: self.received_undefined,
            fields: self.fields,
            check: self.check,
            node_values: self.node_values,
        };
        st.issues.push((issue, self.cont));
    }
}

fn issues_to_list<'py>(
    py: Python<'py>,
    issues: &[(RawIssue, bool)],
    issue_type: &Bound<'py, PyAny>,
    nodes: &[Node],
) -> PyResult<Bound<'py, PyList>> {
    PyList::new(
        py,
        issues
            .iter()
            .map(|(issue, _)| issue.to_dict(py, issue_type, nodes))
            .collect::<PyResult<Vec<_>>>()?,
    )
}

fn is_plain_number(v: &Bound<'_, PyAny>) -> bool {
    (v.is_instance_of::<PyInt>() || v.is_instance_of::<PyFloat>()) && !v.is_instance_of::<PyBool>()
}

/// Python's `_literal_equal`: bools never equal ints, numbers compare across int/float.
fn literal_equal(
    a: &Bound<'_, PyAny>,
    b: &Bound<'_, PyAny>,
    enum_type: &Bound<'_, PyAny>,
) -> PyResult<bool> {
    let a_bool = a.is_instance_of::<PyBool>();
    let b_bool = b.is_instance_of::<PyBool>();
    if a_bool || b_bool {
        return Ok(a_bool && b_bool && a.is(b));
    }
    if is_plain_number(a) && is_plain_number(b) {
        return a.eq(b);
    }
    if a.is_none() || b.is_none() {
        return Ok(a.is_none() && b.is_none());
    }
    if !a.get_type().is(b.get_type()) && !a.is_instance(enum_type)? && !b.is_instance(enum_type)? {
        return Ok(false);
    }
    Ok(a.eq(b).unwrap_or(false))
}

pub struct Engine {
    pub nodes: Vec<Node>,
    pub helpers: Helpers,
}

impl Engine {
    /// True when `value` passes `node` unchanged and without issues, decided without the general
    /// machinery (path tracking, issue bookkeeping). `false` only means "take the normal path".
    /// The node's type check rejects `value` before anything else runs: it can only fail.
    fn type_mismatch(node: &Node, value: &Bound<'_, PyAny>) -> bool {
        match &node.kind {
            NodeKind::Str { coerce: false } => !value.is_instance_of::<PyString>(),
            NodeKind::Bool { coerce: false } => !value.is_instance_of::<PyBool>(),
            NodeKind::Num {
                kind,
                coerce: false,
                ..
            } => {
                !is_plain_number(value)
                    || (*kind == NumKind::BigInt && !value.is_instance_of::<PyInt>())
            }
            _ => false,
        }
    }

    fn quick_ok(node: &Node, value: &Bound<'_, PyAny>) -> bool {
        let int = match &node.kind {
            NodeKind::Str { coerce: false } if value.is_exact_instance_of::<PyString>() => None,
            NodeKind::Bool { coerce: false } if value.is_exact_instance_of::<PyBool>() => None,
            NodeKind::Num {
                kind,
                coerce: false,
                safeint,
                ..
            } if *kind != NumKind::BigInt && value.is_exact_instance_of::<PyInt>() => {
                let Ok(i) = value.extract::<i64>() else {
                    return false;
                };
                if *kind == NumKind::Int
                    && *safeint
                    && !crate::numeric::is_safe_integer(i128::from(i))
                {
                    return false;
                }
                Some(i)
            }
            _ => return false,
        };
        node.checks.iter().all(|check| match &check.kind {
            CheckKind::Bound { lower, upper, .. } => {
                let Some(v) = int else { return false };
                let above = lower.as_ref().map_or(true, |l| match l.int {
                    Some(b) => {
                        if l.inclusive {
                            v >= b
                        } else {
                            v > b
                        }
                    }
                    None => false,
                });
                let below = upper.as_ref().map_or(true, |u| match u.int {
                    Some(b) => {
                        if u.inclusive {
                            v <= b
                        } else {
                            v < b
                        }
                    }
                    None => false,
                });
                above && below
            }
            CheckKind::Size { min, max, .. } if int.is_none() => {
                let Ok(len) = value.len() else { return false };
                let len = i64::try_from(len).unwrap_or(i64::MAX);
                min.map_or(true, |m| len >= m) && max.map_or(true, |m| len <= m)
            }
            _ => false,
        })
    }

    pub fn run_node<'py>(
        &self,
        id: usize,
        value: Bound<'py, PyAny>,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let node = &self.nodes[id];
        let start = st.issues.len();
        let value = self.parse_kind(id, node, value, st)?;
        if node.checks.is_empty() {
            return Ok(value);
        }
        self.run_checks(id, node, value, start, st)
    }

    fn py_fallback<'py>(
        &self,
        id: usize,
        value: &Bound<'py, PyAny>,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = st.py;
        let node = &self.nodes[id];
        let result = self.helpers.run_schema.bind(py).call1((
            node.schema.bind(py),
            value,
            st.path_list()?,
            &st.ctx,
            st.missing,
        ))?;
        let out = result.get_item(0)?;
        st.merge_py_issues(&result.get_item(1)?)?;
        Ok(out)
    }

    #[allow(clippy::too_many_lines)]
    fn parse_kind<'py>(
        &self,
        id: usize,
        node: &Node,
        value: Bound<'py, PyAny>,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = st.py;
        match &node.kind {
            NodeKind::Str { coerce } => {
                if *coerce && !value.is_none() {
                    let text = if value.is_instance_of::<PyBool>() {
                        if value.is_truthy()? {
                            "true".to_string()
                        } else {
                            "false".to_string()
                        }
                    } else if let Ok(f) = value.downcast::<PyFloat>() {
                        let f = f.value();
                        if f.fract() == 0.0 && f.is_finite() {
                            format!("{}", f as i128)
                        } else {
                            value.str()?.to_string()
                        }
                    } else {
                        value.str()?.to_string()
                    };
                    return Ok(PyString::new(py, &text).into_any());
                }
                if value.is_instance_of::<PyString>() {
                    return Ok(value);
                }
                invalid_type(id, "string", &value, st)?;
                Ok(value)
            }
            NodeKind::Num {
                kind,
                coerce,
                safeint,
                int_error,
            } => {
                // Fast path: an exact `int` needs no coercion, float handling or type error.
                if !*coerce && *kind != NumKind::BigInt && value.is_exact_instance_of::<PyInt>() {
                    if !(*kind == NumKind::Int && *safeint) {
                        return Ok(value);
                    }
                    if let Ok(i) = value.extract::<i64>() {
                        if crate::numeric::is_safe_integer(i128::from(i)) {
                            return Ok(value);
                        }
                    }
                }
                let mut value = value;
                let expected = if *kind == NumKind::BigInt {
                    "bigint"
                } else {
                    "number"
                };
                if *coerce {
                    value = match coerce_number_fast(&value, *kind == NumKind::BigInt) {
                        Some(coerced) => coerced,
                        None => self
                            .helpers
                            .coerce_number
                            .bind(py)
                            .call1((&value, expected))?,
                    };
                }
                if !is_plain_number(&value)
                    || (*kind == NumKind::BigInt && !value.is_instance_of::<PyInt>())
                {
                    invalid_type(id, expected, &value, st)?;
                    return Ok(value);
                }
                if let Ok(f) = value.downcast::<PyFloat>() {
                    let f = f.value();
                    if !f.is_finite() {
                        let received = if f.is_nan() {
                            "NaN"
                        } else if f > 0.0 {
                            "Infinity"
                        } else {
                            "-Infinity"
                        };
                        Issue::new(st, id, "invalid_type", &value, false)
                            .f("expected", expected)?
                            .f("received", received)?
                            .push(st);
                        return Ok(value);
                    }
                    if *kind == NumKind::Int {
                        if f.fract() != 0.0 {
                            let mut issue = Issue::new(st, id, "invalid_type", &value, false)
                                .f("expected", "int")?;
                            if let Some(err) = int_error {
                                issue = issue.f("_check_error", err)?;
                            }
                            issue.push(st);
                            return Ok(value);
                        }
                        value = if f.abs() < 9.0e18 {
                            (f as i64).into_pyobject(py)?.into_any()
                        } else {
                            py.get_type::<PyInt>().call1((f,))?
                        };
                    }
                }
                if *kind == NumKind::Int && *safeint {
                    // `i64` extraction is a direct C call; `i128` goes through `int.to_bytes` under abi3.
                    let wide = match value.extract::<i64>() {
                        Ok(i) => Some(i128::from(i)),
                        Err(_) => value.extract::<i128>().ok(),
                    };
                    if let Some(i) = wide {
                        if !crate::numeric::is_safe_integer(i) {
                            let limit = crate::numeric::MAX_SAFE_INTEGER;
                            let (code, key, bound) = if i > 0 {
                                ("too_big", "maximum", limit)
                            } else {
                                ("too_small", "minimum", -limit)
                            };
                            let mut issue = Issue::new(st, id, code, &value, true)
                                .f("origin", "number")?
                                .f(key, bound)?
                                .f("inclusive", true)?;
                            if let Some(err) = int_error {
                                issue = issue.f("_check_error", err)?;
                            }
                            issue.push(st);
                        }
                    }
                }
                Ok(value)
            }
            NodeKind::Bool { coerce } => {
                if *coerce {
                    return Ok(PyBool::new(py, value.is_truthy()?).to_owned().into_any());
                }
                if value.is_instance_of::<PyBool>() {
                    return Ok(value);
                }
                invalid_type(id, "boolean", &value, st)?;
                Ok(value)
            }
            NodeKind::Date { coerce } => {
                let value = match coerce {
                    Some(fn_) => fn_.bind(py).call1((&value,))?,
                    None => value,
                };
                if value.is_instance(self.helpers.date_types.bind(py))? {
                    return Ok(value);
                }
                invalid_type(id, "date", &value, st)?;
                Ok(value)
            }
            NodeKind::NoneValue { expected } => {
                if !value.is_none() {
                    invalid_type(id, expected, &value, st)?;
                }
                Ok(value)
            }
            NodeKind::Any => Ok(value),
            NodeKind::Never => {
                invalid_type(id, "never", &value, st)?;
                Ok(value)
            }
            NodeKind::NaN => {
                if value
                    .downcast::<PyFloat>()
                    .is_ok_and(|f| f.value().is_nan())
                {
                    return Ok(value);
                }
                invalid_type(id, "nan", &value, st)?;
                Ok(value)
            }
            NodeKind::Literal { values } => {
                let enum_type = self.helpers.enum_type.bind(py);
                for v in values {
                    if literal_equal(&value, v.bind(py), enum_type)? {
                        return Ok(value);
                    }
                }
                Issue::new(st, id, "invalid_value", &value, false)
                    .node_values()
                    .push(st);
                Ok(value)
            }
            NodeKind::Enum { values, members } => {
                let enum_type = self.helpers.enum_type.bind(py);
                let is_member = value.is_instance(enum_type)?;
                for (raw, member) in values.iter().zip(members) {
                    if let Some(member) = member {
                        let member = member.bind(py);
                        if value.is(member)
                            || (!is_member && literal_equal(&value, raw.bind(py), enum_type)?)
                        {
                            return Ok(member.clone());
                        }
                    } else if literal_equal(&value, raw.bind(py), enum_type)? {
                        return Ok(value);
                    }
                }
                Issue::new(st, id, "invalid_value", &value, false)
                    .node_values()
                    .push(st);
                Ok(value)
            }
            NodeKind::Array { element } => {
                if !(value.is_instance_of::<PyList>() || value.is_instance_of::<PyTuple>()) {
                    invalid_type(id, "array", &value, st)?;
                    return Ok(value);
                }
                let saved_missing = std::mem::replace(&mut st.missing, false);
                let mut out = Vec::with_capacity(value.len()?);
                if let Ok(list) = value.downcast::<PyList>() {
                    let element_node = &self.nodes[*element];
                    for (i, item) in list.iter().enumerate() {
                        if Self::quick_ok(element_node, &item) {
                            out.push(item);
                            continue;
                        }
                        st.path.push(PathSeg::Index(i));
                        let r = self.run_node(*element, item, st);
                        st.path.pop();
                        out.push(r?);
                    }
                } else {
                    for (i, item) in value.try_iter()?.enumerate() {
                        st.path.push(PathSeg::Index(i));
                        let r = self.run_node(*element, item?, st);
                        st.path.pop();
                        out.push(r?);
                    }
                }
                st.missing = saved_missing;
                Ok(PyList::new(py, out)?.into_any())
            }
            NodeKind::Tuple {
                items,
                optional,
                rest,
            } => {
                if !(value.is_instance_of::<PyList>() || value.is_instance_of::<PyTuple>()) {
                    invalid_type(id, "tuple", &value, st)?;
                    return Ok(value);
                }
                let input: Vec<Bound<'py, PyAny>> = value.try_iter()?.collect::<PyResult<_>>()?;
                let optional_tail = optional.iter().rev().take_while(|o| **o).count();
                if input.len() > items.len() && rest.is_none() {
                    Issue::new(st, id, "too_big", &value, true)
                        .f("origin", "array")?
                        .f("maximum", items.len())?
                        .f("inclusive", true)?
                        .push(st);
                }
                if input.len() < items.len() - optional_tail {
                    Issue::new(st, id, "too_small", &value, true)
                        .f("origin", "array")?
                        .f("minimum", items.len() - optional_tail)?
                        .f("inclusive", true)?
                        .push(st);
                    return Ok(value);
                }
                let mut out = Vec::with_capacity(input.len());
                let saved_missing = std::mem::replace(&mut st.missing, false);
                for (i, item_node) in items.iter().enumerate() {
                    st.path.push(PathSeg::Index(i));
                    let r = if i < input.len() {
                        st.missing = false;
                        self.run_node(*item_node, input[i].clone(), st)
                    } else if optional[i] {
                        st.path.pop();
                        continue;
                    } else {
                        st.missing = true;
                        let r = self.run_node(*item_node, py.None().into_bound(py), st);
                        st.missing = false;
                        r
                    };
                    st.path.pop();
                    out.push(r?);
                }
                if let Some(rest) = rest {
                    for (i, item) in input.iter().enumerate().skip(items.len()) {
                        st.path.push(PathSeg::Index(i));
                        let r = self.run_node(*rest, item.clone(), st);
                        st.path.pop();
                        out.push(r?);
                    }
                }
                st.missing = saved_missing;
                Ok(PyTuple::new(py, out)?.into_any())
            }
            NodeKind::Object {
                fields,
                catchall,
                cls,
            } => {
                let Some(input) = self.as_mapping(&value, st)? else {
                    invalid_type(id, "object", &value, st)?;
                    return Ok(value);
                };
                let dict = input.downcast::<PyDict>().ok();
                let out = PyDict::new(py);
                let start = st.issues.len();
                let saved_missing = std::mem::replace(&mut st.missing, false);
                let mut present_fields = 0usize;
                for field in fields {
                    let name = field.name.bind(py);
                    let present = match dict {
                        Some(d) => d.get_item(name)?,
                        None => {
                            if input.contains(name)? {
                                Some(input.get_item(name)?)
                            } else {
                                None
                            }
                        }
                    };
                    if let Some(child) = &present {
                        present_fields += 1;
                        if Self::quick_ok(&self.nodes[field.node], child) {
                            out.set_item(name, child)?;
                            continue;
                        }
                    }
                    let missing = present.is_none();
                    if missing && field.optin == Rung::Optional && field.optout_optional {
                        continue;
                    }
                    let child = present.unwrap_or_else(|| py.None().into_bound(py));
                    st.path.push(PathSeg::Key(name.clone().into_any()));
                    st.missing = missing;
                    let r = self.run_node(field.node, child, st);
                    st.missing = false;
                    st.path.pop();
                    let r = r?;
                    if missing && r.is_none() {
                        continue;
                    }
                    out.set_item(name, r)?;
                }
                // Every input key is a field when the counts match, so most inputs skip the scan.
                if !matches!(catchall, Catchall::Strip) && input.len()? != present_fields {
                    let is_field = |key: &Bound<'py, PyAny>| {
                        key.downcast::<PyString>()
                            .ok()
                            .and_then(|k| k.to_str().ok())
                            .is_some_and(|k| fields.iter().any(|f| f.key == k))
                    };
                    let mut extra: Vec<(Bound<'py, PyAny>, Bound<'py, PyAny>)> = Vec::new();
                    if let Some(d) = dict {
                        for (key, v) in d.iter() {
                            if !is_field(&key) {
                                extra.push((key, v));
                            }
                        }
                    } else {
                        for item in input.items()?.iter() {
                            let key = item.get_item(0)?;
                            if !is_field(&key) {
                                extra.push((key, item.get_item(1)?));
                            }
                        }
                    }
                    if !extra.is_empty() {
                        match catchall {
                            Catchall::Strict => {
                                let keys = PyList::new(py, extra.iter().map(|(k, _)| k))?;
                                Issue::new(st, id, "unrecognized_keys", &value, false)
                                    .f("keys", keys)?
                                    .push(st);
                            }
                            Catchall::Loose => {
                                for (k, v) in extra {
                                    out.set_item(k, v)?;
                                }
                            }
                            Catchall::Schema(node) => {
                                for (k, v) in extra {
                                    st.path.push(PathSeg::Key(k.clone()));
                                    let r = self.run_node(*node, v, st);
                                    st.path.pop();
                                    out.set_item(k, r?)?;
                                }
                            }
                            Catchall::Strip => {}
                        }
                    }
                }
                st.missing = saved_missing;
                match cls {
                    // Same result as ``Object._from_dict``, without a Python call per object. An
                    // aborted object stays a dict (as in the Python engine): its value is discarded.
                    Some(cls) if !st.aborted(start) => {
                        let instance = self.helpers.object_new.bind(py).call1((cls.bind(py),))?;
                        self.helpers.object_setattr.bind(py).call1((
                            &instance,
                            pyo3::intern!(py, "__dict__"),
                            out,
                        ))?;
                        Ok(instance)
                    }
                    _ => Ok(out.into_any()),
                }
            }
            NodeKind::Record {
                key,
                value: value_node,
                mode,
                exhaustive,
            } => {
                let Some(input) = self.as_mapping(&value, st)? else {
                    invalid_type(id, "record", &value, st)?;
                    return Ok(value);
                };
                let out = PyDict::new(py);
                let saved_missing = std::mem::replace(&mut st.missing, false);
                let enum_type = self.helpers.enum_type.bind(py);
                if let (Some(values), false) = (exhaustive, *mode == RecordMode::Partial) {
                    for k in values {
                        let k = k.bind(py);
                        let present = input.contains(k)?;
                        let child = if present {
                            input.get_item(k)?
                        } else {
                            py.None().into_bound(py)
                        };
                        st.path.push(PathSeg::Key(k.clone()));
                        st.missing = !present;
                        let r = self.run_node(*value_node, child, st);
                        st.missing = false;
                        st.path.pop();
                        let r = r?;
                        if !present && r.is_none() {
                            continue;
                        }
                        out.set_item(k, r)?;
                    }
                    let mut extra = Vec::new();
                    for item in input.items()?.iter() {
                        let k = item.get_item(0)?;
                        let mut known = false;
                        for v in values {
                            if literal_equal(&k, v.bind(py), enum_type)? {
                                known = true;
                                break;
                            }
                        }
                        if !known {
                            extra.push((k, item.get_item(1)?));
                        }
                    }
                    if !extra.is_empty() {
                        if *mode == RecordMode::Loose {
                            for (k, v) in extra {
                                out.set_item(k, v)?;
                            }
                        } else {
                            let keys = PyList::new(py, extra.iter().map(|(k, _)| k))?;
                            Issue::new(st, id, "unrecognized_keys", &value, false)
                                .f("keys", keys)?
                                .push(st);
                        }
                    }
                    st.missing = saved_missing;
                    return Ok(out.into_any());
                }
                let entries: Vec<(Bound<'py, PyAny>, Bound<'py, PyAny>)> =
                    if let Ok(d) = value.downcast::<PyDict>() {
                        d.iter().collect()
                    } else {
                        input
                            .items()?
                            .iter()
                            .map(|item| Ok((item.get_item(0)?, item.get_item(1)?)))
                            .collect::<PyResult<_>>()?
                    };
                let (key_node, value_node_ref) = (&self.nodes[*key], &self.nodes[*value_node]);
                for (k, v) in entries {
                    if Self::quick_ok(key_node, &k) && Self::quick_ok(value_node_ref, &v) {
                        out.set_item(&k, &v)?;
                        continue;
                    }
                    // Key issues are collected apart (as in a forked state) without cloning the path.
                    let before = st.issues.len();
                    let key_out = self.run_node(*key, k.clone(), st)?;
                    if st.issues.len() != before {
                        let key_issues = st.issues.split_off(before);
                        if *mode == RecordMode::Loose {
                            out.set_item(&k, &v)?;
                            continue;
                        }
                        let nested = issues_to_list(py, &key_issues, &st.issue_type, &self.nodes)?;
                        Issue::new(st, id, "invalid_key", &k, false)
                            .f("origin", "record")?
                            .f("issues", nested)?
                            .extra_path(&k)
                            .push(st);
                        out.set_item(&k, &v)?;
                        continue;
                    }
                    st.path.push(PathSeg::Key(k.clone()));
                    let r = self.run_node(*value_node, v, st);
                    st.path.pop();
                    out.set_item(key_out, r?)?;
                }
                st.missing = saved_missing;
                Ok(out.into_any())
            }
            NodeKind::Map {
                key,
                value: value_node,
            } => {
                let Some(input) = self.as_mapping(&value, st)? else {
                    invalid_type(id, "map", &value, st)?;
                    return Ok(value);
                };
                let out = PyDict::new(py);
                let saved_missing = std::mem::replace(&mut st.missing, false);
                for item in input.items()?.iter() {
                    let k = item.get_item(0)?;
                    let v = item.get_item(1)?;
                    st.path.push(PathSeg::Key(k.clone()));
                    let mut key_state = st.fork();
                    let key_out = self.run_node(*key, k.clone(), &mut key_state);
                    let mut value_state = st.fork();
                    let value_out = self.run_node(*value_node, v, &mut value_state);
                    st.path.pop();
                    let (key_out, value_out) = (key_out?, value_out?);
                    if !key_state.issues.is_empty() {
                        let nested =
                            issues_to_list(py, &key_state.issues, &st.issue_type, &self.nodes)?;
                        Issue::new(st, id, "invalid_key", &value, false)
                            .f("origin", "map")?
                            .f("issues", nested)?
                            .extra_path(&k)
                            .push(st);
                    }
                    let value_ok = value_state.issues.is_empty();
                    st.merge(value_state);
                    if key_state.issues.is_empty() && value_ok {
                        out.set_item(key_out, value_out)?;
                    }
                }
                st.missing = saved_missing;
                Ok(out.into_any())
            }
            NodeKind::Set { value: value_node } => {
                let is_frozen = value.is_instance_of::<PyFrozenSet>();
                if !(value.is_instance_of::<PySet>() || is_frozen) {
                    invalid_type(id, "set", &value, st)?;
                    return Ok(value);
                }
                let mut out = Vec::new();
                for item in value.try_iter()? {
                    let mut sub = st.fork();
                    let r = self.run_node(*value_node, item?, &mut sub)?;
                    if sub.issues.is_empty() {
                        out.push(r);
                    } else {
                        let nested = issues_to_list(py, &sub.issues, &st.issue_type, &self.nodes)?;
                        Issue::new(st, id, "invalid_element", &value, false)
                            .f("origin", "set")?
                            .f("issues", nested)?
                            .push(st);
                    }
                }
                if is_frozen {
                    Ok(PyFrozenSet::new(py, out.iter())?.into_any())
                } else {
                    Ok(PySet::new(py, out.iter())?.into_any())
                }
            }
            NodeKind::Union { options, exclusive } => {
                self.run_union(id, options, *exclusive, value, st)
            }
            NodeKind::Discriminated {
                disc,
                options,
                all,
                fallback,
            } => {
                let Some(input) = self.as_mapping(&value, st)? else {
                    invalid_type(id, "object", &value, st)?;
                    return Ok(value);
                };
                let disc = disc.bind(py);
                let disc_value = if input.contains(disc)? {
                    input.get_item(disc)?
                } else {
                    py.None().into_bound(py)
                };
                let enum_type = self.helpers.enum_type.bind(py);
                for (values, option) in options {
                    for v in values {
                        if literal_equal(&disc_value, v.bind(py), enum_type)? {
                            st.missing = false;
                            return self.run_node(*option, value, st);
                        }
                    }
                }
                if *fallback {
                    let ids: Vec<usize> = options.iter().map(|(_, o)| *o).collect();
                    return self.run_union(id, &ids, false, value, st);
                }
                Issue::new(st, id, "invalid_union", &value, false)
                    .f("errors", PyList::empty(py))?
                    .f("note", "No matching discriminator")?
                    .f("discriminator", disc)?
                    .f("options", PyList::new(py, all.iter())?)?
                    .extra_path(&disc.clone().into_any())
                    .push(st);
                Ok(value)
            }
            NodeKind::Optional {
                inner,
                exact,
                defaulted,
            } => {
                if !*exact && value.is_none() && !*defaulted {
                    return Ok(value);
                }
                self.run_node(*inner, value, st)
            }
            NodeKind::Nullable { inner, defaulted } => {
                if value.is_none() && !*defaulted {
                    return Ok(value);
                }
                self.run_node(*inner, value, st)
            }
            NodeKind::NonOptional { inner } => {
                let start = st.issues.len();
                let r = self.run_node(*inner, value, st)?;
                if r.is_none() && st.issues.len() == start {
                    invalid_type(id, "nonoptional", &r, st)?;
                }
                Ok(r)
            }
            NodeKind::Default {
                inner,
                value: default,
                callable,
                prefault,
            } => {
                if st.backward {
                    return self.run_node(*inner, value, st);
                }
                let resolve = |py: Python<'py>| -> PyResult<Bound<'py, PyAny>> {
                    if *callable {
                        default.bind(py).call0()
                    } else {
                        Ok(default.bind(py).clone())
                    }
                };
                if *prefault {
                    let input = if value.is_none() { resolve(py)? } else { value };
                    return self.run_node(*inner, input, st);
                }
                if value.is_none() {
                    return resolve(py);
                }
                let r = self.run_node(*inner, value, st)?;
                if r.is_none() {
                    return resolve(py);
                }
                Ok(r)
            }
            NodeKind::Catch {
                inner,
                value: catch,
                callable,
            } => {
                if st.backward {
                    return self.run_node(*inner, value, st);
                }
                let mut sub = st.fork();
                let r = self.run_node(*inner, value.clone(), &mut sub)?;
                if sub.issues.is_empty() {
                    return Ok(r);
                }
                if *callable {
                    let nested = issues_to_list(py, &sub.issues, &st.issue_type, &self.nodes)?;
                    return self.helpers.catch_value.bind(py).call1((
                        catch.bind(py),
                        nested,
                        &value,
                    ));
                }
                Ok(catch.bind(py).clone())
            }
            NodeKind::Pipe { left, right } => {
                let (first, second) = if st.backward {
                    (*right, *left)
                } else {
                    (*left, *right)
                };
                let start = st.issues.len();
                let r = self.run_node(first, value, st)?;
                if st.stop_pipe(start) {
                    return Ok(r);
                }
                self.run_node(second, r, st)
            }
            NodeKind::Codec {
                left,
                right,
                decode,
                encode,
            } => {
                // Forward (parse / decode): in_ -> decode -> out. Backward (encode): the reverse.
                let (first, second, convert) = if st.backward {
                    (*right, *left, encode)
                } else {
                    (*left, *right, decode)
                };
                let start = st.issues.len();
                let r = self.run_node(first, value, st)?;
                if st.stop_pipe(start) {
                    return Ok(r);
                }
                let converted = convert.bind(py).call1((r,))?;
                self.run_node(second, converted, st)
            }
            NodeKind::StringBool {
                truthy,
                falsy,
                sensitive,
            } => {
                if st.backward {
                    if value.is_instance_of::<PyBool>() {
                        return Ok(PyString::new(
                            py,
                            if value.is_truthy()? { "true" } else { "false" },
                        )
                        .into_any());
                    }
                    invalid_type(id, "boolean", &value, st)?;
                    return Ok(value);
                }
                let Ok(s) = value.downcast::<PyString>() else {
                    invalid_type(id, "string", &value, st)?;
                    return Ok(value);
                };
                let text = s.to_str()?;
                let key = if *sensitive {
                    text.to_string()
                } else {
                    text.to_lowercase()
                };
                if truthy.contains(&key) {
                    return Ok(PyBool::new(py, true).to_owned().into_any());
                }
                if falsy.contains(&key) {
                    return Ok(PyBool::new(py, false).to_owned().into_any());
                }
                let all: Vec<&str> = truthy
                    .iter()
                    .chain(falsy.iter())
                    .map(String::as_str)
                    .collect();
                Issue::new(st, id, "invalid_value", &value, false)
                    .f("expected", "stringbool")?
                    .f("values", all)?
                    .push(st);
                Ok(value)
            }
            NodeKind::Python => self.py_fallback(id, &value, st),
        }
    }

    fn as_mapping<'py>(
        &self,
        value: &Bound<'py, PyAny>,
        st: &State<'py>,
    ) -> PyResult<Option<Bound<'py, PyMapping>>> {
        if let Ok(d) = value.downcast::<PyDict>() {
            return Ok(Some(d.clone().into_any().downcast_into::<PyMapping>()?));
        }
        if let Some(base) = &self.helpers.object_base {
            if value.is_instance(base.bind(st.py))? {
                let d = value.call_method1("to_dict", (false,))?;
                return Ok(Some(d.downcast_into::<PyMapping>()?));
            }
        }
        match value.downcast::<PyMapping>() {
            Ok(m) => Ok(Some(m.clone())),
            Err(_) => Ok(None),
        }
    }

    fn run_union<'py>(
        &self,
        id: usize,
        options: &[usize],
        exclusive: bool,
        value: Bound<'py, PyAny>,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = st.py;
        // Each option runs at most once; `None` marks one not run yet.
        let mut ran: Vec<Option<(State<'py>, Bound<'py, PyAny>)>> =
            Vec::with_capacity(options.len());
        if exclusive {
            ran.resize_with(options.len(), || None);
        } else {
            // First success wins. Options whose type check rejects `value` outright are skipped
            // (no issue objects built and thrown away); they only run if every option fails,
            // to report their issues.
            for option in options {
                let node = &self.nodes[*option];
                if Self::type_mismatch(node, &value) {
                    ran.push(None);
                    continue;
                }
                if Self::quick_ok(node, &value) {
                    return Ok(value);
                }
                let mut sub = st.fork();
                let r = self.run_node(*option, value.clone(), &mut sub)?;
                if sub.issues.is_empty() {
                    return Ok(r);
                }
                ran.push(Some((sub, r)));
            }
        }
        let mut results: Vec<(State<'py>, Bound<'py, PyAny>)> = Vec::with_capacity(options.len());
        for (option, done) in options.iter().zip(ran) {
            let done = if let Some(done) = done {
                done
            } else {
                let mut sub = st.fork();
                let r = self.run_node(*option, value.clone(), &mut sub)?;
                (sub, r)
            };
            results.push(done);
        }
        if exclusive {
            let matches: Vec<usize> = results
                .iter()
                .enumerate()
                .filter(|(_, (s, _))| s.issues.is_empty())
                .map(|(i, _)| i)
                .collect();
            if matches.len() == 1 {
                return Ok(results.swap_remove(matches[0]).1);
            }
            if matches.len() > 1 {
                Issue::new(st, id, "invalid_union", &value, false)
                    .f("errors", PyList::empty(py))?
                    .f("inclusive", false)?
                    .f("matches", matches)?
                    .push(st);
                return Ok(value);
            }
        } else {
            let nonaborted: Vec<usize> = results
                .iter()
                .enumerate()
                .filter(|(_, (s, _))| !s.aborted(0))
                .map(|(i, _)| i)
                .collect();
            if nonaborted.len() == 1 {
                let (sub, r) = results.swap_remove(nonaborted[0]);
                st.merge(sub);
                return Ok(r);
            }
        }
        let errors = PyList::new(
            py,
            results
                .iter()
                .map(|(s, _)| issues_to_list(py, &s.issues, &st.issue_type, &self.nodes))
                .collect::<PyResult<Vec<_>>>()?,
        )?;
        Issue::new(st, id, "invalid_union", &value, false)
            .f("errors", errors)?
            .push(st);
        Ok(value)
    }

    fn run_checks<'py>(
        &self,
        id: usize,
        node: &Node,
        mut value: Bound<'py, PyAny>,
        start: usize,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut is_aborted = st.aborted(start);
        for (index, check) in node.checks.iter().enumerate() {
            if is_aborted {
                break;
            }
            let before = st.issues.len();
            value = self.run_check(id, node, index, check, value, st)?;
            if st.issues.len() != before && !is_aborted {
                is_aborted = st.aborted(before);
            }
        }
        Ok(value)
    }

    fn run_check<'py>(
        &self,
        id: usize,
        node: &Node,
        index: usize,
        check: &Check,
        value: Bound<'py, PyAny>,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = st.py;
        let cont = !check.abort;
        match &check.kind {
            CheckKind::Size { min, max, .. } => {
                // For `str` this is the code-point count, i.e. Python's `len()`.
                let raw_size = value.len()?;
                let size = i64::try_from(raw_size).unwrap_or(i64::MAX);
                if let Some(min) = min {
                    if size < *min {
                        Issue::new(st, id, "too_small", &value, cont)
                            .failed_check(index, false)
                            .push(st);
                    }
                }
                if let Some(max) = max {
                    if size > *max {
                        Issue::new(st, id, "too_big", &value, cont)
                            .failed_check(index, true)
                            .push(st);
                    }
                }
                Ok(value)
            }
            CheckKind::Bound { lower, upper, .. } => {
                let int_value = exact_i64(&value);
                if let Some(limit) = lower {
                    let inclusive = &limit.inclusive;
                    let fails = match (int_value, limit.int) {
                        (Some(v), Some(b)) => {
                            if *inclusive {
                                v < b
                            } else {
                                v <= b
                            }
                        }
                        _ if *inclusive => compare_lt(&value, limit.value.bind(py))?,
                        _ => compare_le(&value, limit.value.bind(py))?,
                    };
                    if fails {
                        Issue::new(st, id, "too_small", &value, cont)
                            .failed_check(index, false)
                            .push(st);
                    }
                }
                if let Some(limit) = upper {
                    let inclusive = &limit.inclusive;
                    let fails = match (int_value, limit.int) {
                        (Some(v), Some(b)) => {
                            if *inclusive {
                                b < v
                            } else {
                                b <= v
                            }
                        }
                        _ if *inclusive => compare_lt(limit.value.bind(py), &value)?,
                        _ => compare_le(limit.value.bind(py), &value)?,
                    };
                    if fails {
                        Issue::new(st, id, "too_big", &value, cont)
                            .failed_check(index, true)
                            .push(st);
                    }
                }
                Ok(value)
            }
            CheckKind::MultipleOf { divisor, origin } => {
                let divisor = divisor.bind(py);
                let ints = match (exact_i64(&value), exact_i64(divisor)) {
                    (Some(v), Some(d)) => Some((i128::from(v), i128::from(d))),
                    _ => None,
                };
                let ok = match ints.map_or_else(
                    || (value.extract::<i128>(), divisor.extract::<i128>()),
                    |(v, d)| (Ok(v), Ok(d)),
                ) {
                    (Ok(v), Ok(d))
                        if !value.is_instance_of::<PyFloat>()
                            && !divisor.is_instance_of::<PyFloat>() =>
                    {
                        d != 0 && v % d == 0
                    }
                    _ => crate::numeric::is_multiple_of(
                        value.extract::<f64>()?,
                        divisor.extract::<f64>()?,
                    ),
                };
                if !ok {
                    Issue::new(st, id, "not_multiple_of", &value, cont)
                        .f("origin", origin)?
                        .f("divisor", divisor)?
                        .check_error(check)?
                        .push(st);
                }
                Ok(value)
            }
            CheckKind::Format { format, .. } => {
                let text = value
                    .downcast::<PyString>()
                    .map_err(|_| PyTypeError::new_err("format check on non-string"))?
                    .to_str()?;
                if !format.is_match(text) {
                    Issue::new(st, id, "invalid_format", &value, cont)
                        .failed_check(index, false)
                        .push(st);
                }
                Ok(value)
            }
            CheckKind::Includes { needle, position } => {
                let text = value.downcast::<PyString>()?.to_str()?;
                let haystack: String = text.chars().skip(*position).collect();
                if !haystack.contains(needle.as_str()) {
                    Issue::new(st, id, "invalid_format", &value, cont)
                        .f("origin", "string")?
                        .f("format", "includes")?
                        .f("includes", needle)?
                        .check_error(check)?
                        .push(st);
                }
                Ok(value)
            }
            CheckKind::StartsWith(prefix) => {
                let text = value.downcast::<PyString>()?.to_str()?;
                if !text.starts_with(prefix.as_str()) {
                    Issue::new(st, id, "invalid_format", &value, cont)
                        .f("origin", "string")?
                        .f("format", "starts_with")?
                        .f("prefix", prefix)?
                        .check_error(check)?
                        .push(st);
                }
                Ok(value)
            }
            CheckKind::EndsWith(suffix) => {
                let text = value.downcast::<PyString>()?.to_str()?;
                if !text.ends_with(suffix.as_str()) {
                    Issue::new(st, id, "invalid_format", &value, cont)
                        .f("origin", "string")?
                        .f("format", "ends_with")?
                        .f("suffix", suffix)?
                        .check_error(check)?
                        .push(st);
                }
                Ok(value)
            }
            CheckKind::Overwrite(op) => {
                let text = value.downcast::<PyString>()?.to_str()?;
                let out = match op {
                    OverwriteOp::Trim => text.trim().to_string(),
                    OverwriteOp::Lower => text.to_lowercase(),
                    OverwriteOp::Upper => text.to_uppercase(),
                    OverwriteOp::Normalize(form) => match form.as_str() {
                        "NFD" => text.nfd().collect(),
                        "NFKC" => text.nfkc().collect(),
                        "NFKD" => text.nfkd().collect(),
                        _ => text.nfc().collect(),
                    },
                };
                Ok(PyString::new(py, &out).into_any())
            }
            CheckKind::Regex {
                name,
                format,
                pattern,
                dollar,
                fallback,
            } => {
                let text = value
                    .downcast::<PyString>()
                    .map_err(|_| PyTypeError::new_err("format check on non-string"))?
                    .to_str()?;
                if *dollar && text.ends_with('\n') {
                    return self.run_py_check(node, fallback, &value, st);
                }
                if !format.is_match(text) {
                    Issue::new(st, id, "invalid_format", &value, cont)
                        .f("origin", "string")?
                        .f("format", name)?
                        .f("pattern", pattern)?
                        .check_error(check)?
                        .push(st);
                }
                Ok(value)
            }
            CheckKind::Py(check_obj) => self.run_py_check(node, check_obj, &value, st),
        }
    }

    fn run_py_check<'py>(
        &self,
        node: &Node,
        check_obj: &Py<PyAny>,
        value: &Bound<'py, PyAny>,
        st: &mut State<'py>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = st.py;
        let result = self.helpers.run_check.bind(py).call1((
            node.schema.bind(py),
            check_obj.bind(py),
            value,
            st.path_list()?,
            &st.ctx,
        ))?;
        let out = result.get_item(0)?;
        st.merge_py_issues(&result.get_item(1)?)?;
        Ok(out)
    }
}

fn invalid_type<'py>(
    id: usize,
    expected: impl IntoField,
    value: &Bound<'py, PyAny>,
    st: &mut State<'py>,
) -> PyResult<()> {
    Issue::new(st, id, "invalid_type", value, false)
        .f("expected", expected)?
        .push(st);
    Ok(())
}

/// `z.coerce.number()` / `z.coerce.bigint()` for the inputs Rust can convert exactly as
/// `zopy.schemas._coerce_number` would: numbers, bools, and ASCII integer strings (`-?[0-9]+`,
/// e.g. path and query parameters). `None` defers to the Python helper (whitespace, floats,
/// exponents, non-ASCII digits, ...).
fn coerce_number_fast<'py>(value: &Bound<'py, PyAny>, bigint: bool) -> Option<Bound<'py, PyAny>> {
    let py = value.py();
    if value.is_exact_instance_of::<PyInt>() || (!bigint && value.is_exact_instance_of::<PyFloat>())
    {
        return Some(value.clone());
    }
    if let Ok(b) = value.downcast::<PyBool>() {
        return Some(i64::from(b.is_true()).into_pyobject(py).ok()?.into_any());
    }
    let text = value.downcast::<PyString>().ok()?.to_str().ok()?;
    let digits = text.strip_prefix('-').unwrap_or(text);
    if digits.is_empty() || digits.len() > 18 || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some(text.parse::<i64>().ok()?.into_pyobject(py).ok()?.into_any())
}

/// The value of an exact `int` (not `bool`) that fits in `i64`.
fn exact_i64(v: &Bound<'_, PyAny>) -> Option<i64> {
    if v.is_exact_instance_of::<PyInt>() {
        v.extract::<i64>().ok()
    } else {
        None
    }
}

/// A value that cannot be compared with the bound (a naive vs an aware datetime, a date vs a
/// datetime) fails the check, so `safeParse` reports an issue instead of raising.
fn incomparable_fails(py: Python<'_>, e: &PyErr) -> PyResult<bool> {
    if e.is_instance_of::<PyTypeError>(py) {
        Ok(true)
    } else {
        Err(PyRuntimeError::new_err(format!("comparison failed: {e}")))
    }
}

fn compare_lt(a: &Bound<'_, PyAny>, b: &Bound<'_, PyAny>) -> PyResult<bool> {
    if let (Some(x), Some(y)) = (exact_i64(a), exact_i64(b)) {
        return Ok(x < y);
    }
    if let (Ok(x), Ok(y)) = (a.extract::<f64>(), b.extract::<f64>()) {
        if !a.is_instance_of::<PyBool>() {
            return Ok(x < y);
        }
    }
    a.lt(b).or_else(|e| incomparable_fails(a.py(), &e))
}

fn compare_le(a: &Bound<'_, PyAny>, b: &Bound<'_, PyAny>) -> PyResult<bool> {
    if let (Some(x), Some(y)) = (exact_i64(a), exact_i64(b)) {
        return Ok(x <= y);
    }
    if let (Ok(x), Ok(y)) = (a.extract::<f64>(), b.extract::<f64>()) {
        if !a.is_instance_of::<PyBool>() {
            return Ok(x <= y);
        }
    }
    a.le(b).or_else(|e| incomparable_fails(a.py(), &e))
}
