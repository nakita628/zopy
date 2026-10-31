//! `zopy._core`: Rust validation engine for the `zopy` Python package.
//!
//! Python compiles a schema into a flat list of node dicts (see `python/zopy/_compile.py`),
//! `compile()` turns them into [`node::Node`]s once, and [`Compiled::run`] validates
//! inputs. Issues come back as raw dicts; Python resolves their messages.

mod formats;
mod messages;
mod node;
mod numeric;
mod run;

use std::sync::atomic::{AtomicBool, Ordering};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use run::{Engine, Helpers, RawIssue, State};

/// A compiled schema.
#[pyclass(frozen, module = "zopy._core")]
#[derive(Debug)]
pub struct Compiled {
    engine: Engine,
    root: usize,
}

/// The raw issues of a failed fast-path parse, kept as Rust data until `error.issues` is read.
/// It is the lazy `ZodError`'s pending build: calling it returns the finished issues (see
/// [`Compiled::build_issues`]). A failure nobody inspects never builds issue dicts.
#[pyclass(frozen, module = "zopy._core")]
#[derive(Debug)]
pub struct PendingIssues {
    compiled: Py<Compiled>,
    ctx: Py<PyAny>,
    issues: Vec<RawIssue>,
}

#[pymethods]
impl PendingIssues {
    fn __call__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let compiled = self.compiled.get();
        let ctx = self.ctx.bind(py);
        if !compiled.plain(py, ctx)? {
            let issues = compiled.issue_list(py, &self.issues)?;
            return compiled.finish_issues(py, issues, ctx);
        }
        // Default messages: each Rust-made issue goes straight to its finished dict; the rest
        // (Python-made, custom errors) take the usual dict route.
        let helpers = &compiled.engine.helpers;
        let issue_type = helpers.issue_type.bind(py);
        let report_input = ctx.getattr(pyo3::intern!(py, "reportInput"))?.is_truthy()?;
        let mut done = Vec::with_capacity(self.issues.len());
        for raw in &self.issues {
            if let Some(issue) = compiled.plain_issue(py, raw, report_input)? {
                done.push(issue.into_any());
                continue;
            }
            let issue = raw.to_dict(py, issue_type, &compiled.engine.nodes)?;
            if compiled.finalize_plain_dict(py, &issue, report_input)? {
                done.push(issue.into_any());
                continue;
            }
            let finished = helpers.finalize_one.bind(py).call1((issue, ctx))?;
            finished.call_method1(
                pyo3::intern!(py, "pop"),
                (pyo3::intern!(py, "continue"), py.None()),
            )?;
            done.push(finished);
        }
        Ok(PyList::new(py, done)?.into_any())
    }
}

impl std::fmt::Debug for Engine {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "Engine({} nodes)", self.nodes.len())
    }
}

impl Compiled {
    /// No error map can apply: `ctx.error` is unset and the global config is `plain`.
    fn plain(&self, py: Python<'_>, ctx: &Bound<'_, PyAny>) -> PyResult<bool> {
        Ok(ctx.getattr(pyo3::intern!(py, "error"))?.is_none()
            && self
                .engine
                .helpers
                .config
                .bind(py)
                .getattr(pyo3::intern!(py, "plain"))?
                .is_truthy()?)
    }

    /// Finish one issue dict in place with its default English message. `false`: Python must
    /// finish it (a custom error applies, or Rust has no exact message for it).
    fn finalize_plain_dict(
        &self,
        py: Python<'_>,
        issue: &Bound<'_, PyDict>,
        report_input: bool,
    ) -> PyResult<bool> {
        // Issues with nested `errors` / `issues` (unions, keys, elements) have codes
        // `en_message` leaves to Python, so they need no check here.
        let custom = match issue.get_item(pyo3::intern!(py, "_node"))? {
            Some(n) => self
                .engine
                .nodes
                .get(n.extract::<usize>()?)
                .map_or(true, |node| node.has_error),
            None => true,
        } || issue.contains(pyo3::intern!(py, "_check_error"))?
            || issue.contains(pyo3::intern!(py, "message"))?;
        if custom {
            return Ok(false);
        }
        let input = issue.get_item(pyo3::intern!(py, "input"))?;
        let date_types = self.engine.helpers.date_types.bind(py);
        let Some(message) = messages::en_message(issue, input.as_ref(), date_types) else {
            return Ok(false);
        };
        issue.del_item(pyo3::intern!(py, "_node"))?;
        if !report_input {
            issue.del_item(pyo3::intern!(py, "input"))?;
        }
        issue.set_item(pyo3::intern!(py, "message"), message)?;
        Ok(true)
    }

    /// A Rust-made issue straight to its finished dict (no `_node`, `input` only when reported,
    /// the default message), or `None` when Python must finish it.
    fn plain_issue<'py>(
        &self,
        py: Python<'py>,
        raw: &RawIssue,
        report_input: bool,
    ) -> PyResult<Option<Bound<'py, PyDict>>> {
        let RawIssue::Built {
            node,
            fields,
            input,
            check,
            ..
        } = raw
        else {
            return Ok(None);
        };
        let Some(node_data) = self.engine.nodes.get(*node) else {
            return Ok(None);
        };
        let custom = node_data.has_error
            || fields.iter().any(|(key, _)| key == "_check_error")
            || check.is_some_and(|(index, _)| node_data.checks[index].error.is_some());
        if custom {
            return Ok(None);
        }
        let issue_type = self.engine.helpers.issue_type.bind(py);
        let issue = raw.to_dict_with(py, issue_type, &self.engine.nodes, report_input, false)?;
        let date_types = self.engine.helpers.date_types.bind(py);
        let Some(message) = messages::en_message(&issue, Some(input.bind(py)), date_types) else {
            return Ok(None);
        };
        issue.set_item(pyo3::intern!(py, "message"), message)?;
        Ok(Some(issue))
    }

    fn execute<'py>(
        &self,
        py: Python<'py>,
        data: Bound<'py, PyAny>,
        ctx: Bound<'py, PyAny>,
        backward: bool,
    ) -> PyResult<(Bound<'py, PyAny>, Vec<RawIssue>)> {
        let mut state = State {
            py,
            issues: Vec::new(),
            path: Vec::new(),
            ctx,
            backward,
            missing: false,
            issue_type: self.engine.helpers.issue_type.bind(py).clone(),
        };
        let value = self.engine.run_node(self.root, data, &mut state)?;
        Ok((
            value,
            state.issues.into_iter().map(|(issue, _)| issue).collect(),
        ))
    }

    /// Raw issues as a list of `ZodIssue` dicts.
    fn issue_list<'py>(
        &self,
        py: Python<'py>,
        issues: &[RawIssue],
    ) -> PyResult<Bound<'py, PyList>> {
        let issue_type = self.engine.helpers.issue_type.bind(py);
        PyList::new(
            py,
            issues
                .iter()
                .map(|issue| issue.to_dict(py, issue_type, &self.engine.nodes))
                .collect::<PyResult<Vec<_>>>()?,
        )
    }

    fn finish_issues<'py>(
        &self,
        py: Python<'py>,
        issues: Bound<'py, PyList>,
        ctx: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let helpers = &self.engine.helpers;
        if !self.plain(py, ctx)? {
            return helpers.build_slow.bind(py).call1((issues, ctx));
        }
        let report_input = ctx.getattr(pyo3::intern!(py, "reportInput"))?.is_truthy()?;
        for i in self.finalize_plain(py, &issues, report_input)? {
            let done = helpers
                .finalize_one
                .bind(py)
                .call1((issues.get_item(i)?, ctx))?;
            done.call_method1(
                pyo3::intern!(py, "pop"),
                (pyo3::intern!(py, "continue"), py.None()),
            )?;
            issues.set_item(i, done)?;
        }
        Ok(issues.into_any())
    }
}

#[pymethods]
impl Compiled {
    /// Validate `data`. Returns `(value, raw_issues)`.
    fn run<'py>(
        &self,
        py: Python<'py>,
        data: Bound<'py, PyAny>,
        ctx: Bound<'py, PyAny>,
        backward: bool,
    ) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyList>)> {
        let (value, issues) = self.execute(py, data, ctx, backward)?;
        Ok((value, self.issue_list(py, &issues)?))
    }

    /// Finish raw issues in place with the default English message when no custom error can
    /// apply to them. Returns the indices left for Python's `finalize`.
    fn finalize_plain(
        &self,
        py: Python<'_>,
        issues: &Bound<'_, PyList>,
        report_input: bool,
    ) -> PyResult<Vec<usize>> {
        let mut pending = Vec::new();
        for (i, item) in issues.iter().enumerate() {
            if !self.finalize_plain_dict(py, item.downcast::<PyDict>()?, report_input)? {
                pending.push(i);
            }
        }
        Ok(pending)
    }

    /// `error.issues` of a failed fast-path parse, built on first access. With no error map
    /// (`ctx.error` unset and the global config `plain`), Rust writes the default English
    /// messages in place and Python only finishes what it cannot; otherwise `build_slow`.
    fn build_issues<'py>(
        &self,
        py: Python<'py>,
        issues: Bound<'py, PyList>,
        ctx: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyAny>> {
        self.finish_issues(py, issues, ctx)
    }

    #[getter]
    fn node_count(&self) -> usize {
        self.engine.nodes.len()
    }
}

/// Cleared by `zopy._compile.set_engine("python")`, so installed fast paths defer to Python.
static FAST_ENABLED: AtomicBool = AtomicBool::new(true);

#[pyfunction]
fn set_fast(enabled: bool) {
    FAST_ENABLED.store(enabled, Ordering::Relaxed);
}

/// `schema.parse` / `safeParse` / `encode` / `safeEncode` installed on a schema after its first
/// Rust compile.
///
/// A call without options runs the engine directly with the default forward context. Successes
/// return `on_ok(value)` (or the value itself). A failure wraps its raw issues in a
/// [`PendingIssues`] (the lazy `ZodError`'s pending build) and either raises `raises` with it or
/// returns `on_issues(pending)`. Anything else goes to `slow(data, params, **kwargs)`.
#[pyclass(frozen, module = "zopy._core")]
#[derive(Debug)]
pub struct FastParse {
    compiled: Py<Compiled>,
    ctx: Py<PyAny>,
    on_ok: Option<Py<PyAny>>,
    on_issues: Py<PyAny>,
    slow: Py<PyAny>,
    /// Set when installed on a `z.Object` class: only that class uses this entry point; a
    /// subclass reading the attribute gets `fallback.__get__(obj, subclass)` (the classmethod).
    owner: Option<Py<PyAny>>,
    fallback: Option<Py<PyAny>>,
    /// `encode` / `safeEncode`: run the schema backward (codecs encode, pipes reverse).
    backward: bool,
    /// `parse` / `encode`: raise this `ZodError` class directly (built in Rust with the pending
    /// issues) instead of calling `on_issues`.
    raises: Option<Py<PyAny>>,
}

#[pymethods]
impl FastParse {
    #[new]
    #[pyo3(signature = (compiled, ctx, on_ok, on_issues, slow, owner=None, fallback=None, backward=false, raises=None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        compiled: Py<Compiled>,
        ctx: Py<PyAny>,
        on_ok: Option<Py<PyAny>>,
        on_issues: Py<PyAny>,
        slow: Py<PyAny>,
        owner: Option<Py<PyAny>>,
        fallback: Option<Py<PyAny>>,
        backward: bool,
        raises: Option<Py<PyAny>>,
    ) -> Self {
        FastParse {
            compiled,
            ctx,
            on_ok,
            on_issues,
            slow,
            owner,
            fallback,
            backward,
            raises,
        }
    }

    fn __get__<'py>(
        slf: Bound<'py, Self>,
        obj: Option<Bound<'py, PyAny>>,
        owner: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let py = slf.py();
        let this = slf.get();
        if let (Some(bound), Some(fallback), Some(owner)) = (&this.owner, &this.fallback, owner) {
            if !owner.is(bound.bind(py)) {
                let obj = obj.unwrap_or_else(|| py.None().into_bound(py));
                return fallback
                    .bind(py)
                    .call_method1(pyo3::intern!(py, "__get__"), (obj, owner));
            }
        }
        Ok(slf.into_any())
    }

    #[pyo3(signature = (data, params=None, **kwargs))]
    fn __call__<'py>(
        &self,
        py: Python<'py>,
        data: Bound<'py, PyAny>,
        params: Option<Bound<'py, PyAny>>,
        kwargs: Option<&Bound<'py, PyDict>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let has_options =
            params.as_ref().is_some_and(|p| !p.is_none()) || kwargs.is_some_and(|k| !k.is_empty());
        if has_options || !FAST_ENABLED.load(Ordering::Relaxed) {
            let params = params.unwrap_or_else(|| py.None().into_bound(py));
            return self.slow.bind(py).call((data, params), kwargs);
        }
        let (value, issues) =
            self.compiled
                .get()
                .execute(py, data, self.ctx.bind(py).clone(), self.backward)?;
        if issues.is_empty() {
            return match &self.on_ok {
                Some(f) => f.bind(py).call1((value,)),
                None => Ok(value),
            };
        }
        let pending = Bound::new(
            py,
            PendingIssues {
                compiled: self.compiled.clone_ref(py),
                ctx: self.ctx.clone_ref(py),
                issues,
            },
        )?;
        if let Some(error_type) = &self.raises {
            // `ZodError._lazy(pending)` without the Python calls: no `__init__`, issues pending.
            let helpers = &self.compiled.get().engine.helpers;
            let error = helpers
                .exception_new
                .bind(py)
                .call1((error_type.bind(py),))?;
            helpers.object_setattr.bind(py).call1((
                &error,
                pyo3::intern!(py, "_pending"),
                pending,
            ))?;
            return Err(PyErr::from_value(error));
        }
        self.on_issues.bind(py).call1((pending,))
    }
}

fn helper(helpers: &Bound<'_, PyDict>, key: &str) -> PyResult<Py<PyAny>> {
    helpers
        .get_item(key)?
        .ok_or_else(|| PyValueError::new_err(format!("missing helper {key:?}")))
        .map(Bound::unbind)
}

/// Compile node dicts produced by `zopy._compile`.
#[pyfunction]
#[pyo3(name = "compile")]
fn compile_py(
    nodes: &Bound<'_, PyList>,
    root: usize,
    helpers: &Bound<'_, PyDict>,
) -> PyResult<Compiled> {
    let nodes = node::build_nodes(nodes)?;
    if root >= nodes.len() {
        return Err(PyValueError::new_err("root node out of range"));
    }
    let helpers = Helpers {
        run_schema: helper(helpers, "run_schema")?,
        run_check: helper(helpers, "run_check")?,
        catch_value: helper(helpers, "catch_value")?,
        coerce_number: helper(helpers, "coerce_number")?,
        date_types: helper(helpers, "date_types")?,
        enum_type: helper(helpers, "enum_type")?,
        object_new: helper(helpers, "object_new")?,
        object_setattr: helper(helpers, "object_setattr")?,
        exception_new: helper(helpers, "exception_new")?,
        issue_type: helper(helpers, "issue_type")?,
        config: helper(helpers, "config")?,
        finalize_one: helper(helpers, "finalize_one")?,
        build_slow: helper(helpers, "build_slow")?,
        object_base: helpers
            .get_item("object_base")?
            .filter(|v| !v.is_none())
            .map(Bound::unbind),
    };
    Ok(Compiled {
        engine: Engine { nodes, helpers },
        root,
    })
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<Compiled>()?;
    m.add_class::<FastParse>()?;
    m.add_class::<PendingIssues>()?;
    m.add_function(wrap_pyfunction!(compile_py, m)?)?;
    m.add_function(wrap_pyfunction!(set_fast, m)?)?;
    m.add("engine", "rust")?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
