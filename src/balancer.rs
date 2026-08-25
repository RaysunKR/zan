//! 多进程模式的 TCP 负载均衡器。
//!
//! 父进程在对外端口 accept，把每条连接按 round-robin 分配给 N 个
//! worker 进程（每个 worker 是独立的 Python 进程、独立 GIL，真正
//! 利用多核）。转发方式是纯字节级 pipe：
//!
//! 1. 建立到 worker 的连接后，先写入一行
//!    ``X-Forwarded-For: <客户端IP>\r\n`` ——它会被 worker 的请求头
//!    解析器当作第一条 header 收下，从而保留真实客户端地址；
//! 2. 之后 ``copy_bidirectional`` 双向搬运字节（连接级亲和，worker 上
//!    的 keep-alive 语义完全保留）。
//!
//! 为什么不用 SO_REUSEPORT：Windows 没有该选项；端口竞争接受也不均匀。
//! 这一层代理的代价只有一次 loopback TCP 连接建立，而换来的是 Python
//! 视图执行的线性多核扩展。

use std::net::SocketAddr;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

const COPY_BUF: usize = 64 * 1024;

/// 对外监听并把连接 round-robin 转发给 workers（"ip:port" 列表）。
pub async fn serve_balancer(
    listener: TcpListener,
    workers: Vec<String>,
    mut shutdown: tokio::sync::watch::Receiver<bool>,
) {
    let next = Arc::new(AtomicUsize::new(0));
    let mut children: Vec<tokio::task::JoinHandle<()>> = Vec::new();
    loop {
        tokio::select! {
            acc = listener.accept() => {
                let (client, peer) = match acc {
                    Ok(x) => x,
                    Err(_) => continue,
                };
                if workers.is_empty() {
                    continue;
                }
                let idx = next.fetch_add(1, Ordering::Relaxed) % workers.len();
                let target = workers[idx].clone();
                children.push(tokio::spawn(forward(client, peer, target)));
                // 防止长时间运行时任务句柄无限累积
                children.retain(|t| !t.is_finished());
            }
            _ = shutdown.changed() => break,
        }
    }
}

/// 转发一条连接：读出首条请求行，在其后注入 XFF 头，再双向搬运
/// （keep-alive 的后续请求直接透传——连接级 round-robin 已保证
/// 落在同一 worker）。
async fn forward(mut client: TcpStream, peer: SocketAddr, target: String) {
    let mut upstream = match TcpStream::connect(&target).await {
        Ok(s) => s,
        Err(_) => return,
    };
    // 带缓冲地读到第一行结束（请求行），避免逐字节 read 的系统调用风暴
    let mut buf = Vec::with_capacity(1024);
    let mut chunk = [0u8; 1024];
    let line_end;
    loop {
        match client.read(&mut chunk).await {
            Ok(0) | Err(_) => return,
            Ok(n) => {
                let start = buf.len();
                buf.extend_from_slice(&chunk[..n]);
                match buf[start..].iter().position(|&b| b == b'\n') {
                    Some(i) => {
                        line_end = start + i + 1;
                        break;
                    }
                    None => {
                        if buf.len() > 8192 {
                            return; // 异常请求行
                        }
                    }
                }
            }
        }
    }
    let xff = format!("X-Forwarded-For: {}\r\n", peer.ip());
    if upstream.write_all(&buf[..line_end]).await.is_err() {
        return;
    }
    if upstream.write_all(xff.as_bytes()).await.is_err() {
        return;
    }
    // 请求行之后已经读进 buf 的剩余字节先冲给 worker
    if line_end < buf.len() {
        let rest = buf[line_end..].to_vec();
        if upstream.write_all(&rest).await.is_err() {
            return;
        }
    }
    let _ = copy_bidirectional(&mut client, &mut upstream).await;
}

/// tokio::io::copy_bidirectional 的等价实现（避免依赖版本差异）。
async fn copy_bidirectional(a: &mut TcpStream, b: &mut TcpStream) -> std::io::Result<(u64, u64)> {
    let mut buf_a = vec![0u8; COPY_BUF];
    let mut buf_b = vec![0u8; COPY_BUF];
    let mut a_done = false;
    let mut b_done = false;
    let mut a_to_b: u64 = 0;
    let mut b_to_a: u64 = 0;
    loop {
        if a_done && b_done {
            return Ok((a_to_b, b_to_a));
        }
        let a_readable = !a_done;
        let b_readable = !b_done;
        tokio::select! {
            n = a.read(&mut buf_a), if a_readable => {
                match n {
                    Ok(0) | Err(_) => {
                        a_done = true;
                        let _ = b.shutdown().await;
                    }
                    Ok(n) => {
                        b.write_all(&buf_a[..n]).await?;
                        a_to_b += n as u64;
                    }
                }
            }
            n = b.read(&mut buf_b), if b_readable => {
                match n {
                    Ok(0) | Err(_) => {
                        b_done = true;
                        let _ = a.shutdown().await;
                    }
                    Ok(n) => {
                        a.write_all(&buf_b[..n]).await?;
                        b_to_a += n as u64;
                    }
                }
            }
        }
    }
}
