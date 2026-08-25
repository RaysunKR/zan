//! `_zan.Server`：Python 侧的路由/配置收集器与运行入口。
//!
//! ## 运行时模型（多实例与多核）
//!
//! - **全局共享 tokio 运行时**：整个进程只有一份多线程运行时
//!   （worker 线程数 = CPU 逻辑核数，至少 2）。多个 `Server` 实例
//!   （即多个 Flask 应用）可以同时 `start()`，各自持有独立的监听器
//!   与请求处理状态（`Shared`），互不干扰。
//! - **非阻塞生命周期**：`start()` 返回服务器 id，`stop(id)` 停止；
//!   经典的阻塞 `run()` 只是「start + 信号轮询 + stop」的组合。
//! - **多进程模式**：`run_balancer()` 在父进程对外端口 accept，把连接
//!   round-robin 转发给 N 个 worker 进程（见 `balancer.rs`），突破
//!   Python GIL 的单核限制。
//!
//! `start()` 之后主线程应进入自己的事件循环（sleep + 处理信号），
//! 睡眠期间 GIL 被释放，运行时的 Python 回调（视图/钩子）才能并行。

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::Duration;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyTuple;

use crate::balancer::serve_balancer;
use crate::http::{handle, parse_query, serve, Req, Shared};
use crate::router::Router;

// ---------------------------------------------------------------------------
// 全局共享运行时
// ---------------------------------------------------------------------------

static RUNTIME: OnceLock<tokio::runtime::Runtime> = OnceLock::new();

/// 进程级唯一的多线程 tokio 运行时；worker 数 = CPU 核数。
fn runtime() -> &'static tokio::runtime::Runtime {
    RUNTIME.get_or_init(|| {
        let cpus = std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(4);
        let workers = cpus.max(2);
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .worker_threads(workers)
            .thread_name("zan-io")
            .build()
            .expect("failed to build tokio runtime")
    })
}

/// 运行中的服务器句柄。
struct RunningServer {
    shutdown: tokio::sync::watch::Sender<bool>,
    addr: String,
    /// 任务结束（listener 关闭、连接排空）后置位。
    done: Arc<AtomicBool>,
}

static REGISTRY: OnceLock<Mutex<HashMap<u64, RunningServer>>> = OnceLock::new();

fn registry() -> &'static Mutex<HashMap<u64, RunningServer>> {
    REGISTRY.get_or_init(|| Mutex::new(HashMap::new()))
}

static NEXT_ID: AtomicU64 = AtomicU64::new(0);

/// 在共享运行时上绑定监听端口并开始服务。
/// 通过 `done_tx` 返回绑定结果；`Shared` 决定请求如何被处理。
fn spawn_server(
    host: String,
    port: u16,
    shared: Arc<Shared>,
    done: Arc<AtomicBool>,
) -> (tokio::sync::watch::Sender<bool>, std::sync::mpsc::Receiver<Result<String, String>>) {
    let (stx, srx) = tokio::sync::watch::channel(false);
    let (btx, brx) = std::sync::mpsc::channel::<Result<String, String>>();
    runtime().spawn(async move {
        let listener = match tokio::net::TcpListener::bind((host.as_str(), port)).await {
            Ok(l) => l,
            Err(e) => {
                let _ = btx.send(Err(format!("{e}")));
                return;
            }
        };
        let addr = listener
            .local_addr()
            .map(|a| a.to_string())
            .unwrap_or_else(|_| format!("{host}:{port}"));
        let _ = btx.send(Ok(addr));
        serve(listener, shared, srx).await;
        done.store(true, Ordering::SeqCst);
    });
    (stx, brx)
}

// ---------------------------------------------------------------------------
// Server 类
// ---------------------------------------------------------------------------

#[pyclass(module = "_zan")]
pub struct Server {
    /// 规则原文，按需重新编译为 trie。
    specs: Vec<RuleSpec>,
    built: Option<Arc<Router>>,
    static_cfg: Vec<(String, PathBuf)>,
    dispatch: Option<Py<PyAny>>,
    pipeline: Option<Py<PyAny>>,
    req_cls: Option<Py<PyAny>>,
    convert_slow: Option<Py<PyAny>>,
    debug_page: Option<Py<PyAny>>,
    http_exc: Option<Py<PyAny>>,
    uuid_cls: Option<Py<PyAny>>,
    fast: bool,
    debug: bool,
    log: bool,
    trap_http: bool,
    max_body: usize,
    cc_max_age: i64,
}

struct RuleSpec {
    rule: String,
    methods: Vec<String>,
    view: Py<PyAny>,
    endpoint: String,
    auto_options: bool,
}

#[pymethods]
impl Server {
    #[new]
    fn new() -> Self {
        Server {
            specs: Vec::new(),
            built: None,
            static_cfg: Vec::new(),
            dispatch: None,
            pipeline: None,
            req_cls: None,
            convert_slow: None,
            debug_page: None,
            http_exc: None,
            uuid_cls: None,
            fast: true,
            debug: false,
            log: false,
            trap_http: false,
            max_body: 64 * 1024 * 1024,
            cc_max_age: 43200,
        }
    }

    fn add_rule(
        &mut self,
        py: Python<'_>,
        rule: String,
        methods: Vec<String>,
        view: Py<PyAny>,
        endpoint: String,
        auto_options: bool,
    ) -> PyResult<()> {
        // 立即编译一次以尽早暴露规则错误
        Router::new()
            .add(&rule, methods.clone(), view.clone_ref(py), endpoint.clone(), auto_options)
            .map_err(pyo3::exceptions::PyValueError::new_err)?;
        self.specs.push(RuleSpec { rule, methods, view, endpoint, auto_options });
        self.built = None;
        Ok(())
    }

    fn rule_count(&self) -> usize {
        self.specs.len()
    }

    fn set_static(&mut self, url_path: String, folder: PathBuf) {
        self.static_cfg.retain(|(p, _)| p != &url_path);
        self.static_cfg.push((url_path, folder));
    }

    fn set_request_class(&mut self, cls: Py<PyAny>) {
        self.req_cls = Some(cls);
    }

    fn set_dispatch(&mut self, f: Py<PyAny>) {
        self.dispatch = Some(f);
    }

    fn set_pipeline(&mut self, f: Py<PyAny>) {
        self.pipeline = Some(f);
    }

    fn set_convert_slow(&mut self, f: Py<PyAny>) {
        self.convert_slow = Some(f);
    }

    fn set_debug_page(&mut self, f: Py<PyAny>) {
        self.debug_page = Some(f);
    }

    fn set_http_exception(&mut self, cls: Py<PyAny>) {
        self.http_exc = Some(cls);
    }

    fn set_uuid_class(&mut self, cls: Py<PyAny>) {
        self.uuid_cls = Some(cls);
    }

    #[pyo3(signature = (fast, debug, log, max_body, cc_max_age, trap_http))]
    fn set_flags(&mut self, fast: bool, debug: bool, log: bool, max_body: usize, cc_max_age: i64, trap_http: bool) {
        self.fast = fast;
        self.debug = debug;
        self.log = log;
        self.max_body = max_body;
        self.cc_max_age = cc_max_age;
        self.trap_http = trap_http;
    }

    /// 运行时的 worker 线程数（= CPU 逻辑核数）。
    #[getter]
    fn runtime_workers(&self) -> usize {
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(1)
    }

    /// CPU 逻辑核数。
    #[getter]
    fn cpu_count(&self) -> usize {
        self.runtime_workers()
    }

    // ------------------------------------------------------------------
    // 非阻塞生命周期：多实例共存的基础
    // ------------------------------------------------------------------

    /// 绑定 `host:port` 并开始服务（非阻塞）。返回服务器 id，
    /// 供 `bound_addr` / `stop` 使用。
    fn start(&mut self, py: Python<'_>, host: String, port: u16) -> PyResult<u64> {
        let shared = self.build_shared(py)?;
        let id = NEXT_ID.fetch_add(1, Ordering::SeqCst) + 1;
        let done = Arc::new(AtomicBool::new(false));
        let (stx, brx) = spawn_server(host, port, shared, done.clone());
        // mpsc::Receiver 是 Send 但非 Sync；包进 Mutex 后可进 allow_threads
        let brx = std::sync::Mutex::new(brx);
        let addr = py.allow_threads(|| {
            let mut rx = brx.lock().unwrap();
            rx.recv_timeout(Duration::from_secs(10))
        });
        match addr {
            Ok(Ok(addr)) => {
                registry().lock().unwrap().insert(
                    id,
                    RunningServer { shutdown: stx, addr, done },
                );
                Ok(id)
            }
            Ok(Err(e)) => Err(PyRuntimeError::new_err(e)),
            Err(_) => Err(PyRuntimeError::new_err("server did not start in time")),
        }
    }

    /// 停止一个运行中的服务器；等待至多 `timeout_secs` 让连接排空。
    /// 返回是否在超时前完成。
    #[pyo3(signature = (server_id, timeout_secs = 5))]
    fn stop(&self, py: Python<'_>, server_id: u64, timeout_secs: u64) -> bool {
        let entry = registry().lock().unwrap().remove(&server_id);
        let entry = match entry {
            Some(e) => e,
            None => return false, // 不存在（或已停止）
        };
        let _ = entry.shutdown.send(true);
        let deadline = std::time::Instant::now() + Duration::from_secs(timeout_secs);
        py.allow_threads(|| {
            while !entry.done.load(Ordering::SeqCst) {
                if std::time::Instant::now() >= deadline {
                    return false;
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            true
        })
    }

    /// 查询运行中服务器的绑定地址（端口 0 时有用）。不存在返回 None。
    fn bound_addr(&self, server_id: u64) -> Option<String> {
        registry()
            .lock()
            .unwrap()
            .get(&server_id)
            .map(|e| e.addr.clone())
    }

    /// 当前运行中的服务器数量（本进程）。
    #[getter]
    fn running_servers(&self) -> usize {
        registry().lock().unwrap().len()
    }

    // ------------------------------------------------------------------
    // 阻塞入口（兼容）
    // ------------------------------------------------------------------

    /// 阻塞服务直到收到 KeyboardInterrupt。返回绑定地址。
    #[pyo3(signature = (host, port, threads = 0, banner = None))]
    fn run(
        &mut self,
        py: Python<'_>,
        host: String,
        port: u16,
        threads: usize,
        banner: Option<Py<PyAny>>,
    ) -> PyResult<String> {
        let _ = threads; // 运行时 worker 数现在全局固定为 CPU 核数，参数保留以兼容
        let id = self.start(py, host.clone(), port)?;
        let addr = self.bound_addr(id).unwrap_or_else(|| format!("{host}:{port}"));
        if let Some(b) = &banner {
            let _ = b.bind(py).call1((addr.as_str(),));
        }
        // 睡眠时释放 GIL；周期性醒来处理信号（Ctrl+C）与存活检查
        let mut interrupted: PyResult<()> = Ok(());
        loop {
            py.allow_threads(|| std::thread::sleep(Duration::from_millis(120)));
            if let Err(e) = py.check_signals() {
                interrupted = Err(e);
                break;
            }
            if self.bound_addr(id).is_none() {
                break; // 服务器自行退出（如端口错误后）
            }
        }
        self.stop(py, id, 5);
        interrupted?;
        Ok(addr)
    }

    // ------------------------------------------------------------------
    // 多进程负载均衡（父进程侧）
    // ------------------------------------------------------------------

    /// 阻塞运行 TCP 负载均衡器：对外监听 `host:port`，把连接
    /// round-robin 转发给 `workers`（"ip:port" 列表，即各 worker 的
    /// 实际监听地址）。用于 `Flask.run(processes=N)`。
    fn run_balancer(
        &self,
        py: Python<'_>,
        host: String,
        port: u16,
        workers: Vec<String>,
    ) -> PyResult<String> {
        if workers.is_empty() {
            return Err(PyRuntimeError::new_err("run_balancer 需要至少一个 worker 地址"));
        }
        let (stx, mut srx) = tokio::sync::watch::channel(false);
        let (btx, brx) = std::sync::mpsc::channel::<Result<String, String>>();
        runtime().spawn(async move {
            let listener = match tokio::net::TcpListener::bind((host.as_str(), port)).await {
                Ok(l) => l,
                Err(e) => {
                    let _ = btx.send(Err(format!("{e}")));
                    return;
                }
            };
            let addr = listener
                .local_addr()
                .map(|a| a.to_string())
                .unwrap_or_else(|_| format!("{host}:{port}"));
            let _ = btx.send(Ok(addr));
            serve_balancer(listener, workers, srx).await;
        });
        let brx = std::sync::Mutex::new(brx);
        let addr = match py.allow_threads(|| {
            let mut rx = brx.lock().unwrap();
            rx.recv_timeout(Duration::from_secs(10))
        }) {
            Ok(Ok(a)) => a,
            Ok(Err(e)) => return Err(PyRuntimeError::new_err(e)),
            Err(_) => return Err(PyRuntimeError::new_err("balancer did not start in time")),
        };
        let mut interrupted: PyResult<()> = Ok(());
        loop {
            py.allow_threads(|| std::thread::sleep(Duration::from_millis(120)));
            if let Err(e) = py.check_signals() {
                interrupted = Err(e);
                break;
            }
            // balancer 无自退出路径；仅由信号（Ctrl+C / 进程终止）结束
        }
        let _ = stx.send(true);
        interrupted?;
        Ok(addr)
    }

    // ------------------------------------------------------------------
    // 测试辅助
    // ------------------------------------------------------------------

    /// 在进程内处理单个请求（无 socket）。`test_client()` 与集成测试用。
    #[pyo3(signature = (method, path, headers = None, body = None))]
    fn test_request(
        &mut self,
        py: Python<'_>,
        method: String,
        path: String,
        headers: Option<Vec<(String, String)>>,
        body: Option<Vec<u8>>,
    ) -> PyResult<Py<PyAny>> {
        let shared = self.build_shared(py)?;
        let (p, q) = match path.split_once('?') {
            Some((a, b)) => (a.to_string(), b.to_string()),
            None => (path, String::new()),
        };
        let is_head = method == "HEAD";
        let req = Req {
            method,
            path: p,
            query_raw: q.clone(),
            query_pairs: parse_query(&q),
            headers: headers.unwrap_or_default(),
            body: body.unwrap_or_default(),
            remote_addr: "127.0.0.1".to_string(),
        };
        let resp = py.allow_threads(|| {
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("failed to init tokio runtime");
            rt.block_on(async move { handle(&shared, req).await })
        });
        let body = if is_head { Vec::new() } else { resp.body };
        let bytes = pyo3::types::PyBytes::new_bound(py, &body).unbind();
        let tup = PyTuple::new_bound(py, [resp.status.to_object(py), resp.headers.to_object(py), bytes.into_any()]);
        Ok(tup.to_object(py))
    }

    #[getter]
    fn version(&self) -> &'static str {
        env!("CARGO_PKG_VERSION")
    }
}

impl Server {
    /// 把注册的规则与回调冻结为不可变的 `Shared`（带构建缓存）。
    fn build_shared(&mut self, py: Python<'_>) -> PyResult<Arc<Shared>> {
        if self.built.is_none() {
            let mut router = Router::new();
            for spec in &self.specs {
                router
                    .add(&spec.rule, spec.methods.clone(), spec.view.clone_ref(py), spec.endpoint.clone(), spec.auto_options)
                    .map_err(pyo3::exceptions::PyValueError::new_err)?;
            }
            self.built = Some(Arc::new(router));
        }
        let router = self.built.as_ref().unwrap().clone();
        let req_cls = self.req_cls.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("request class not configured (call set_request_class)")
        })?;
        let dispatch = self.dispatch.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("dispatch not configured (call set_dispatch)")
        })?;
        let pipeline = self.pipeline.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("pipeline not configured (call set_pipeline)")
        })?;
        let convert_slow = self.convert_slow.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("converter not configured (call set_convert_slow)")
        })?;
        let debug_page = self.debug_page.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("debug page not configured (call set_debug_page)")
        })?;
        let http_exc = self.http_exc.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("HTTPException not configured (call set_http_exception)")
        })?;
        let uuid_cls = self.uuid_cls.as_ref().map(|p| p.clone_ref(py)).ok_or_else(|| {
            PyRuntimeError::new_err("uuid.UUID not configured (call set_uuid_class)")
        })?;
        let static_cfg = self
            .static_cfg
            .iter()
            .map(|(prefix, dir)| {
                let canonical = std::fs::canonicalize(dir).unwrap_or_else(|_| dir.clone());
                (prefix.clone(), canonical)
            })
            .collect();
        Ok(Arc::new(Shared {
            router,
            static_cfg,
            cc_max_age: self.cc_max_age,
            dispatch,
            pipeline,
            req_cls,
            convert_slow,
            debug_page,
            http_exc,
            uuid_cls,
            fast: self.fast,
            debug: self.debug,
            log: self.log,
            trap_http: self.trap_http,
            max_body: self.max_body,
        }))
    }
}
