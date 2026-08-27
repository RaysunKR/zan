mod balancer;
mod db;
mod http;
mod json;
mod pyapi;
mod router;

use pyo3::prelude::*;

#[pymodule]
fn _zan(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("_version", env!("CARGO_PKG_VERSION"))?;
    m.add_class::<pyapi::Server>()?;
    db::register_module(m.py(), m)?;
    Ok(())
}
