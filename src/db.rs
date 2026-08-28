//! Rust 侧异步 PostgreSQL 访问层。
//!
//! 通过全局 `deadpool-postgres` 连接池执行查询；对 Python 暴露同步阻塞 API，
//! 内部在 Tokio runtime 上异步执行，并在等待 IO 时释放 GIL。
//! 同时暴露给 Rust HTTP 处理器的原生异步接口，完全绕过 Python。

use std::sync::Mutex;

use deadpool_postgres::{Config, Pool, Runtime};
use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};

use crate::pyapi::runtime;

static POOL: Mutex<Option<Pool>> = Mutex::new(None);

fn db_url() -> String {
    std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "postgresql://tfb:tfb@localhost:5432/tfb".into())
}

fn pool_size() -> usize {
    // 优先允许环境变量覆盖；缺省按 CPU*8，保证高并发下不必排队等连接。
    std::env::var("ZAN_DB_POOL_SIZE")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or_else(|| {
            std::thread::available_parallelism()
                .map(|n| n.get() * 8)
                .unwrap_or(32)
                .max(32)
        })
}

fn create_pool() -> Result<Pool, String> {
    let mut cfg = Config::default();
    cfg.url = Some(db_url());
    cfg.pool = Some(deadpool_postgres::PoolConfig {
        max_size: pool_size(),
        timeouts: deadpool_postgres::Timeouts {
            wait: Some(std::time::Duration::from_secs(5)),
            create: Some(std::time::Duration::from_secs(5)),
            recycle: Some(std::time::Duration::from_secs(5)),
        },
        ..Default::default()
    });
    cfg.manager = Some(deadpool_postgres::ManagerConfig {
        recycling_method: deadpool_postgres::RecyclingMethod::Fast,
    });
    cfg.create_pool(Some(Runtime::Tokio1), tokio_postgres::NoTls)
        .map_err(|e| format!("failed to create DB pool: {e}"))
}

fn pool() -> Result<Pool, String> {
    let mut guard = POOL.lock().map_err(|e| format!("DB pool lock poisoned: {e}"))?;
    if let Some(p) = guard.as_ref() {
        return Ok(p.clone());
    }
    let p = create_pool()?;
    *guard = Some(p.clone());
    Ok(p)
}

// ---------------------------------------------------------------------------
// 核心异步查询（Rust 原生接口）
// ---------------------------------------------------------------------------

pub async fn get_world(id: i32) -> Result<(i32, i32), String> {
    let pool = pool()?;
    let client = pool.get().await.map_err(|e| format!("DB pool error: {e}"))?;
    let row = client
        .query_one("SELECT id, randomnumber FROM world WHERE id = $1", &[&id])
        .await
        .map_err(|e| format!("DB query error: {e}"))?;
    Ok((row.get(0), row.get(1)))
}

pub async fn get_worlds(ids: Vec<i32>) -> Result<Vec<(i32, i32)>, String> {
    let pool = pool()?;
    let client = pool.get().await.map_err(|e| format!("DB pool error: {e}"))?;
    // unnest 保持输入数组顺序与重复项
    let rows = client
        .query(
            "SELECT w.id, w.randomnumber FROM world w JOIN unnest($1::int[]) AS t(id) ON w.id = t.id",
            &[&ids],
        )
        .await
        .map_err(|e| format!("DB query error: {e}"))?;
    Ok(rows.into_iter().map(|r| (r.get(0), r.get(1))).collect())
}

pub async fn update_worlds(rows: Vec<(i32, i32)>) -> Result<(), String> {
    let pool = pool()?;
    let client = pool.get().await.map_err(|e| format!("DB pool error: {e}"))?;
    let ids: Vec<i32> = rows.iter().map(|r| r.1).collect();
    let new_nums: Vec<i32> = rows.iter().map(|r| r.0).collect();
    client
        .execute(
            "UPDATE world SET randomnumber = t.num FROM (SELECT unnest($1::int[]) AS num, unnest($2::int[]) AS id) AS t WHERE world.id = t.id",
            &[&new_nums, &ids],
        )
        .await
        .map_err(|e| format!("DB update error: {e}"))?;
    Ok(())
}

/// Update rows and return the new `(id, randomnumber)` pairs in a single round-trip.
/// Input rows must already be sorted by id for deadlock-free execution.
pub async fn update_worlds_returning(rows: Vec<(i32, i32)>) -> Result<Vec<(i32, i32)>, String> {
    let pool = pool()?;
    let client = pool.get().await.map_err(|e| format!("DB pool error: {e}"))?;
    let ids: Vec<i32> = rows.iter().map(|r| r.1).collect();
    let new_nums: Vec<i32> = rows.iter().map(|r| r.0).collect();
    let updated = client
        .query(
            "UPDATE world SET randomnumber = t.num FROM (SELECT unnest($1::int[]) AS num, unnest($2::int[]) AS id) AS t WHERE world.id = t.id RETURNING world.id, world.randomnumber",
            &[&new_nums, &ids],
        )
        .await
        .map_err(|e| format!("DB update error: {e}"))?;
    Ok(updated.into_iter().map(|r| (r.get(0), r.get(1))).collect())
}

pub async fn get_fortunes() -> Result<Vec<(i32, String)>, String> {
    let pool = pool()?;
    let client = pool.get().await.map_err(|e| format!("DB pool error: {e}"))?;
    let rows = client
        .query("SELECT id, message FROM fortune", &[])
        .await
        .map_err(|e| format!("DB query error: {e}"))?;
    Ok(rows.into_iter().map(|r| (r.get(0), r.get(1))).collect())
}

// ---------------------------------------------------------------------------
// Python 同步包装（释放 GIL）
// ---------------------------------------------------------------------------

fn row_to_tuple(py: Python<'_>, row: (i32, i32)) -> PyResult<PyObject> {
    Ok(PyTuple::new_bound(py, [row.0.to_object(py), row.1.to_object(py)]).into())
}

fn fortune_row_to_tuple(py: Python<'_>, row: (i32, String)) -> PyResult<PyObject> {
    Ok(PyTuple::new_bound(py, [row.0.to_object(py), row.1.to_object(py)]).into())
}

#[pyfunction]
fn db_get_world(py: Python<'_>, id: i32) -> PyResult<PyObject> {
    let row = py.allow_threads(|| runtime().block_on(get_world(id)))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
    row_to_tuple(py, row)
}

#[pyfunction]
fn db_get_worlds(py: Python<'_>, ids: Vec<i32>) -> PyResult<PyObject> {
    let rows = py.allow_threads(|| runtime().block_on(get_worlds(ids)))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
    let tuples: Vec<PyObject> = rows
        .into_iter()
        .map(|r| row_to_tuple(py, r))
        .collect::<PyResult<_>>()?;
    let list = PyList::new_bound(py, tuples);
    Ok(list.into())
}

#[pyfunction]
fn db_update_worlds(py: Python<'_>, rows: Vec<(i32, i32)>) -> PyResult<()> {
    py.allow_threads(|| runtime().block_on(update_worlds(rows)))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))
}

#[pyfunction]
fn db_get_fortunes(py: Python<'_>) -> PyResult<PyObject> {
    let rows = py.allow_threads(|| runtime().block_on(get_fortunes()))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e))?;
    let tuples: Vec<PyObject> = rows
        .into_iter()
        .map(|r| fortune_row_to_tuple(py, r))
        .collect::<PyResult<_>>()?;
    let list = PyList::new_bound(py, tuples);
    Ok(list.into())
}

pub fn register_module(py: Python<'_>, m: &Bound<'_, PyModule>) -> PyResult<()> {
    let db = PyModule::new_bound(py, "_db")?;
    db.add_function(wrap_pyfunction!(db_get_world, &db)?)?;
    db.add_function(wrap_pyfunction!(db_get_worlds, &db)?)?;
    db.add_function(wrap_pyfunction!(db_update_worlds, &db)?)?;
    db.add_function(wrap_pyfunction!(db_get_fortunes, &db)?)?;
    m.add_submodule(&db)?;
    Ok(())
}
