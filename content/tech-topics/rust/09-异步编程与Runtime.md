# 异步编程与 Runtime

> **本章目标:** 深入理解 async/await 机制,掌握 Tokio 生态系统
> 
> **学习时间:** 7-10 天 (本课程第二难的章节)
> 
> **前置知识:** 完成 `08-宏系统与元编程.md`

---

## 为什么需要异步?

```
同步模型:
线程1: [任务A]────────[等IO]────────[任务A续]
线程2: [任务B]────────[等IO]────────[任务B续]
线程3: [任务C]────────[等IO]────────[任务C续]
问题: 等待IO时线程阻塞, 浪费资源

异步模型:
单线程: [任务A开始]─[切换到B]─[切换到C]─[A的IO到了,继续A]─[B继续]...
优势: 等待IO时执行其他任务, 高并发低内存
```

---

## 1. Future Trait

### Future 是什么?

```rust
// Future trait 简化版
pub trait Future {
    type Output;
    
    // poll 被 runtime 调用
    // 返回 Pending (还没好) 或 Ready(value)
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output>;
}

pub enum Poll<T> {
    Ready(T),    // 完成了!
    Pending,     // 还没好, 以后再来问
}
```

### 手动实现 Future

```rust
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

// 一个在特定时间后就绪的 Future
struct Delay {
    deadline: Instant,
}

impl Delay {
    fn new(duration: Duration) -> Self {
        Delay {
            deadline: Instant::now() + duration,
        }
    }
}

impl Future for Delay {
    type Output = ();
    
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<()> {
        if Instant::now() >= self.deadline {
            Poll::Ready(())
        } else {
            // 注册唤醒器 (waker)
            // 实际实现需要设置计时器触发 waker
            let waker = cx.waker().clone();
            let deadline = self.deadline;
            
            std::thread::spawn(move || {
                let now = Instant::now();
                if now < deadline {
                    std::thread::sleep(deadline - now);
                }
                waker.wake();
            });
            
            Poll::Pending
        }
    }
}
```

### async/await 的本质

```rust
// async fn 是语法糖
async fn fetch_data(url: &str) -> String {
    // ...实现
    url.to_string()
}

// 等价于:
fn fetch_data_desugared(url: &'_ str) 
    -> impl Future<Output = String> + '_ 
{
    async move {
        url.to_string()
    }
}

// async 块生成一个匿名的状态机类型
// 每个 .await 点是一个可能的挂起/恢复点
```

### 状态机展开

```rust
// 原始 async fn
async fn simple() {
    let x = step1().await;
    let y = step2(x).await;
    return y;
}

// 编译器生成的状态机 (概念上)
enum SimpleStateMachine {
    Start,
    WaitingStep1 { future: Step1Future },
    WaitingStep2 { x: i32, future: Step2Future },
    Done,
}

impl Future for SimpleStateMachine {
    type Output = i32;
    
    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<i32> {
        loop {
            match &mut *self {
                SimpleStateMachine::Start => {
                    let fut = step1();
                    *self = SimpleStateMachine::WaitingStep1 { future: fut };
                }
                SimpleStateMachine::WaitingStep1 { future } => {
                    match Pin::new(future).poll(cx) {
                        Poll::Pending => return Poll::Pending,
                        Poll::Ready(x) => {
                            let fut = step2(x);
                            *self = SimpleStateMachine::WaitingStep2 { x, future: fut };
                        }
                    }
                }
                SimpleStateMachine::WaitingStep2 { future, .. } => {
                    match Pin::new(future).poll(cx) {
                        Poll::Pending => return Poll::Pending,
                        Poll::Ready(y) => {
                            *self = SimpleStateMachine::Done;
                            return Poll::Ready(y);
                        }
                    }
                }
                SimpleStateMachine::Done => panic!("polled after completion"),
            }
        }
    }
}
```

---

## 2. Tokio Runtime

### Tokio 基础

```toml
# Cargo.toml
[dependencies]
tokio = { version = "1", features = ["full"] }
```

```rust
use tokio;

// #[tokio::main] 是宏, 创建 runtime 并运行 main
#[tokio::main]
async fn main() {
    println!("Hello from async main!");
    
    // await 异步操作
    let result = some_async_operation().await;
    println!("{}", result);
}

async fn some_async_operation() -> String {
    // 模拟 IO 操作
    tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
    "Done!".to_string()
}
```

### Tokio 的两种 Runtime

```rust
// 1. 多线程 Runtime (默认)
#[tokio::main]
async fn main() {
    // 等价于:
    // tokio::runtime::Builder::new_multi_thread()
    //     .worker_threads(num_cpus::get())
    //     .enable_all()
    //     .build()
    //     .unwrap()
    //     .block_on(async { ... })
}

// 2. 单线程 Runtime (适合嵌入式或测试)
#[tokio::main(flavor = "current_thread")]
async fn single_thread_main() {
    // 所有 task 在同一线程运行
}
```

### spawn 任务

```rust
use tokio::task;

#[tokio::main]
async fn main() {
    // spawn 创建新的异步任务 (绿色线程)
    let handle = task::spawn(async {
        println!("Task 1");
        42
    });
    
    // spawn_blocking: 阻塞操作放入线程池
    let blocking_handle = task::spawn_blocking(|| {
        // CPU 密集型或阻塞 IO
        std::thread::sleep(std::time::Duration::from_millis(100));
        "blocking done"
    });
    
    let result1 = handle.await.unwrap();
    let result2 = blocking_handle.await.unwrap();
    
    println!("Task 1 returned: {}", result1);
    println!("Blocking returned: {}", result2);
}
```

### 并发执行

```rust
use tokio::time::{sleep, Duration};

async fn task(id: u32, millis: u64) -> u32 {
    sleep(Duration::from_millis(millis)).await;
    id
}

#[tokio::main]
async fn main() {
    // 顺序执行 (慢)
    let start = std::time::Instant::now();
    let a = task(1, 100).await;
    let b = task(2, 100).await;
    let c = task(3, 100).await;
    println!("Sequential: {}ms, results: {},{},{}", start.elapsed().as_millis(), a, b, c);
    
    // 并发执行 (快)
    let start = std::time::Instant::now();
    let (a, b, c) = tokio::join!(
        task(1, 100),
        task(2, 100),
        task(3, 100),
    );
    println!("Concurrent: {}ms, results: {},{},{}", start.elapsed().as_millis(), a, b, c);
    
    // select! - 等待最先完成的
    let result = tokio::select! {
        v = task(1, 50) => format!("task 1 first: {}", v),
        v = task(2, 100) => format!("task 2 first: {}", v),
    };
    println!("{}", result);  // "task 1 first: 1"
}
```

---

## 3. Tokio IO

### 异步文件 IO

```rust
use tokio::fs;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 写文件
    let mut file = fs::File::create("test.txt").await?;
    file.write_all(b"Hello, async!").await?;
    file.flush().await?;
    
    // 读文件
    let mut file = fs::File::open("test.txt").await?;
    let mut contents = String::new();
    file.read_to_string(&mut contents).await?;
    println!("{}", contents);
    
    // 便捷函数
    let content = fs::read_to_string("test.txt").await?;
    println!("{}", content);
    
    Ok(())
}
```

### 异步网络

```rust
use tokio::net::{TcpListener, TcpStream};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

// TCP Echo 服务器
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let listener = TcpListener::bind("127.0.0.1:8080").await?;
    println!("Listening on :8080");
    
    loop {
        let (socket, addr) = listener.accept().await?;
        println!("New connection from {}", addr);
        
        // 为每个连接 spawn 一个任务
        tokio::spawn(async move {
            handle_connection(socket).await;
        });
    }
}

async fn handle_connection(mut socket: TcpStream) {
    let mut buf = vec![0u8; 1024];
    
    loop {
        let n = match socket.read(&mut buf).await {
            Ok(0) => break,  // 连接关闭
            Ok(n) => n,
            Err(_) => break,
        };
        
        // Echo 回去
        if socket.write_all(&buf[..n]).await.is_err() {
            break;
        }
    }
}
```

---

## 4. Channel 与通信

```rust
use tokio::sync::{mpsc, oneshot, broadcast, watch};

// mpsc: 多生产者, 单消费者
async fn mpsc_demo() {
    let (tx, mut rx) = mpsc::channel(100);  // 缓冲区大小
    
    // 生产者
    for i in 0..5 {
        let tx = tx.clone();
        tokio::spawn(async move {
            tx.send(i).await.unwrap();
        });
    }
    drop(tx);  // 关闭所有发送端
    
    // 消费者
    while let Some(val) = rx.recv().await {
        println!("Received: {}", val);
    }
}

// oneshot: 单次请求-响应
async fn oneshot_demo() {
    let (tx, rx) = oneshot::channel::<String>();
    
    tokio::spawn(async move {
        // 处理请求后发回响应
        tx.send("response".to_string()).unwrap();
    });
    
    let response = rx.await.unwrap();
    println!("Got: {}", response);
}

// broadcast: 广播
async fn broadcast_demo() {
    let (tx, mut rx1) = broadcast::channel(16);
    let mut rx2 = tx.subscribe();
    
    tokio::spawn(async move {
        tx.send("hello everyone".to_string()).unwrap();
    });
    
    let msg1 = rx1.recv().await.unwrap();
    let msg2 = rx2.recv().await.unwrap();
    
    assert_eq!(msg1, msg2);
}
```

---

## 5. 错误处理与取消

```rust
use tokio::time::{timeout, Duration};
use anyhow::{Result, Context};

// 超时控制
async fn with_timeout() -> Result<String> {
    let result = timeout(
        Duration::from_secs(5),
        some_slow_operation()
    ).await;
    
    match result {
        Ok(val) => Ok(val),
        Err(_) => Err(anyhow::anyhow!("operation timed out")),
    }
}

async fn some_slow_operation() -> String {
    tokio::time::sleep(Duration::from_secs(2)).await;
    "done".to_string()
}

// 优雅关闭
use tokio::signal;

async fn graceful_shutdown() {
    let (shutdown_tx, shutdown_rx) = tokio::sync::oneshot::channel::<()>();
    
    // 监听 Ctrl+C
    tokio::spawn(async move {
        signal::ctrl_c().await.expect("failed to listen for ctrl_c");
        println!("Shutdown signal received");
        let _ = shutdown_tx.send(());
    });
    
    // 主循环
    tokio::select! {
        _ = run_server() => {},
        _ = shutdown_rx => {
            println!("Shutting down...");
        }
    }
}

async fn run_server() {
    // 服务器逻辑
    loop {
        tokio::time::sleep(Duration::from_secs(1)).await;
    }
}
```

---

## 6. 异步 Trait (高级)

```rust
// 问题: async fn 在 trait 中复杂 (返回类型不统一)
// Rust 1.75+ 支持 async trait

trait AsyncProcessor {
    async fn process(&self, data: &str) -> String;
}

struct SimpleProcessor;

impl AsyncProcessor for SimpleProcessor {
    async fn process(&self, data: &str) -> String {
        format!("Processed: {}", data)
    }
}

// 旧方式: 使用 async-trait crate
// 或手动 Box<dyn Future>
trait OldStyle {
    fn process<'a>(&'a self, data: &'a str) 
        -> std::pin::Pin<Box<dyn std::future::Future<Output = String> + Send + 'a>>;
}
```

---

## 练习题

### 练习 1: 并发 HTTP 请求

```rust
use tokio;

// 模拟 HTTP 请求
async fn fetch_url(url: &str, delay_ms: u64) -> String {
    tokio::time::sleep(tokio::time::Duration::from_millis(delay_ms)).await;
    format!("Response from {}", url)
}

#[tokio::main]
async fn main() {
    let urls = vec![
        ("https://api1.example.com", 200),
        ("https://api2.example.com", 150),
        ("https://api3.example.com", 300),
    ];
    
    let start = std::time::Instant::now();
    
    // 并发请求所有 URL
    let futures: Vec<_> = urls.iter()
        .map(|(url, delay)| fetch_url(url, *delay))
        .collect();
    
    let results = futures::future::join_all(futures).await;
    
    println!("All done in {}ms:", start.elapsed().as_millis());
    for r in results {
        println!("  {}", r);
    }
}
```

---

### 练习 2: 实现限速器

```rust
use std::sync::Arc;
use tokio::sync::Semaphore;
use tokio::time::{sleep, Duration};

// 使用 Semaphore 限制并发度
pub struct RateLimiter {
    semaphore: Arc<Semaphore>,
    max_concurrent: usize,
}

impl RateLimiter {
    pub fn new(max_concurrent: usize) -> Self {
        RateLimiter {
            semaphore: Arc::new(Semaphore::new(max_concurrent)),
            max_concurrent,
        }
    }
    
    pub async fn run<F, Fut, T>(&self, task: F) -> T
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = T>,
    {
        let _permit = self.semaphore.acquire().await.unwrap();
        task().await
    }
}

#[tokio::main]
async fn main() {
    let limiter = Arc::new(RateLimiter::new(3));  // 最多3个并发
    
    let mut handles = vec![];
    
    for i in 0..10 {
        let l = Arc::clone(&limiter);
        let handle = tokio::spawn(async move {
            l.run(|| async move {
                println!("Task {} started", i);
                sleep(Duration::from_millis(100)).await;
                println!("Task {} done", i);
                i
            }).await
        });
        handles.push(handle);
    }
    
    let results: Vec<i32> = futures::future::join_all(handles)
        .await
        .into_iter()
        .map(|r| r.unwrap())
        .collect();
    
    println!("Results: {:?}", results);
}
```

---

### 练习 3: 异步流处理

```rust
use tokio_stream::StreamExt;
use tokio_stream::wrappers::ReceiverStream;
use tokio::sync::mpsc;

async fn stream_demo() {
    let (tx, rx) = mpsc::channel(10);
    
    // 生产数据
    tokio::spawn(async move {
        for i in 0..10 {
            tx.send(i).await.unwrap();
            tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
        }
    });
    
    // 消费流
    let mut stream = ReceiverStream::new(rx);
    
    while let Some(val) = stream.next().await {
        println!("Got: {}", val);
    }
}
```

---

### 练习 4: Actor 模式

```rust
use tokio::sync::mpsc;

// Actor 模式: 通过消息传递实现并发状态管理
enum CounterMsg {
    Increment,
    Decrement,
    Get(tokio::sync::oneshot::Sender<i64>),
    Reset,
}

struct CounterActor {
    count: i64,
    rx: mpsc::Receiver<CounterMsg>,
}

impl CounterActor {
    fn new(rx: mpsc::Receiver<CounterMsg>) -> Self {
        CounterActor { count: 0, rx }
    }
    
    async fn run(mut self) {
        while let Some(msg) = self.rx.recv().await {
            match msg {
                CounterMsg::Increment => self.count += 1,
                CounterMsg::Decrement => self.count -= 1,
                CounterMsg::Get(reply) => { let _ = reply.send(self.count); },
                CounterMsg::Reset => self.count = 0,
            }
        }
    }
}

#[derive(Clone)]
struct CounterHandle {
    tx: mpsc::Sender<CounterMsg>,
}

impl CounterHandle {
    fn new() -> Self {
        let (tx, rx) = mpsc::channel(32);
        let actor = CounterActor::new(rx);
        tokio::spawn(actor.run());
        CounterHandle { tx }
    }
    
    async fn increment(&self) {
        self.tx.send(CounterMsg::Increment).await.unwrap();
    }
    
    async fn get(&self) -> i64 {
        let (tx, rx) = tokio::sync::oneshot::channel();
        self.tx.send(CounterMsg::Get(tx)).await.unwrap();
        rx.await.unwrap()
    }
}

#[tokio::main]
async fn main() {
    let counter = CounterHandle::new();
    
    let c1 = counter.clone();
    let c2 = counter.clone();
    
    let h1 = tokio::spawn(async move {
        for _ in 0..50 { c1.increment().await; }
    });
    
    let h2 = tokio::spawn(async move {
        for _ in 0..50 { c2.increment().await; }
    });
    
    h1.await.unwrap();
    h2.await.unwrap();
    
    println!("Final count: {}", counter.get().await);  // 100
}
```

---

### 练习 5: 自定义 Future

```rust
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::sync::{Arc, Mutex};

// 实现一个手动完成的 Future
struct ManualFuture {
    inner: Arc<Mutex<ManualFutureInner>>,
}

struct ManualFutureInner {
    result: Option<String>,
    waker: Option<std::task::Waker>,
}

struct ManualFutureCompleter {
    inner: Arc<Mutex<ManualFutureInner>>,
}

impl ManualFutureCompleter {
    fn complete(self, value: String) {
        let mut inner = self.inner.lock().unwrap();
        inner.result = Some(value);
        if let Some(waker) = inner.waker.take() {
            waker.wake();
        }
    }
}

fn manual_future_pair() -> (ManualFuture, ManualFutureCompleter) {
    let inner = Arc::new(Mutex::new(ManualFutureInner {
        result: None,
        waker: None,
    }));
    
    (
        ManualFuture { inner: Arc::clone(&inner) },
        ManualFutureCompleter { inner },
    )
}

impl Future for ManualFuture {
    type Output = String;
    
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<String> {
        let mut inner = self.inner.lock().unwrap();
        
        if let Some(result) = inner.result.take() {
            Poll::Ready(result)
        } else {
            inner.waker = Some(cx.waker().clone());
            Poll::Pending
        }
    }
}

#[tokio::main]
async fn main() {
    let (future, completer) = manual_future_pair();
    
    tokio::spawn(async move {
        tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;
        completer.complete("Hello from completer!".to_string());
    });
    
    let result = future.await;
    println!("{}", result);
}
```

---

### 练习 6: 异步迭代器 (Stream)

```rust
use std::pin::Pin;
use std::task::{Context, Poll};
use futures::Stream;

// 实现一个计数 Stream
struct CountStream {
    current: u64,
    max: u64,
}

impl CountStream {
    fn new(max: u64) -> Self {
        CountStream { current: 0, max }
    }
}

impl Stream for CountStream {
    type Item = u64;
    
    fn poll_next(mut self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<Option<u64>> {
        if self.current < self.max {
            self.current += 1;
            Poll::Ready(Some(self.current - 1))
        } else {
            Poll::Ready(None)  // Stream 结束
        }
    }
}

#[tokio::main]
async fn main() {
    use futures::StreamExt;
    
    let stream = CountStream::new(5);
    
    let sum: u64 = stream.fold(0, |acc, x| async move { acc + x }).await;
    println!("Sum: {}", sum);  // 10 (0+1+2+3+4)
}
```

---

### 练习 7: 错误处理与重试

```rust
use tokio::time::{sleep, Duration};

async fn unreliable_operation(attempt: u32) -> Result<String, String> {
    if attempt < 3 {
        Err(format!("Temporary error on attempt {}", attempt))
    } else {
        Ok("Success!".to_string())
    }
}

async fn with_retry<F, Fut, T, E>(
    mut op: F,
    max_attempts: u32,
    delay: Duration,
) -> Result<T, E>
where
    F: FnMut(u32) -> Fut,
    Fut: std::future::Future<Output = Result<T, E>>,
    E: std::fmt::Debug,
{
    let mut attempt = 0;
    
    loop {
        attempt += 1;
        
        match op(attempt).await {
            Ok(val) => return Ok(val),
            Err(e) => {
                if attempt >= max_attempts {
                    return Err(e);
                }
                eprintln!("Attempt {} failed: {:?}, retrying...", attempt, e);
                sleep(delay).await;
            }
        }
    }
}

#[tokio::main]
async fn main() {
    let result = with_retry(
        |attempt| unreliable_operation(attempt),
        5,
        Duration::from_millis(100),
    ).await;
    
    println!("{:?}", result);  // Ok("Success!")
}
```

---

### 练习 8: 异步 TCP 聊天服务器

```rust
use tokio::net::TcpListener;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::sync::broadcast;
use std::net::SocketAddr;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let listener = TcpListener::bind("127.0.0.1:3000").await?;
    let (tx, _rx) = broadcast::channel::<(String, SocketAddr)>(16);
    
    println!("Chat server on :3000");
    
    loop {
        let (socket, addr) = listener.accept().await?;
        let tx = tx.clone();
        let mut rx = tx.subscribe();
        
        tokio::spawn(async move {
            let (reader, mut writer) = socket.into_split();
            let mut lines = BufReader::new(reader).lines();
            
            // 读取循环
            let tx_clone = tx.clone();
            let read_task = tokio::spawn(async move {
                while let Ok(Some(line)) = lines.next_line().await {
                    let _ = tx_clone.send((line, addr));
                }
            });
            
            // 写入循环  
            let write_task = tokio::spawn(async move {
                while let Ok((msg, sender)) = rx.recv().await {
                    if sender != addr {
                        let line = format!("{}: {}\n", sender, msg);
                        if writer.write_all(line.as_bytes()).await.is_err() {
                            break;
                        }
                    }
                }
            });
            
            let _ = tokio::join!(read_task, write_task);
        });
    }
}
```

---

### 练习 9: 构建简单的异步任务调度器

```rust
use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll, Waker, RawWaker, RawWakerVTable};
use std::sync::{Arc, Mutex};
use std::collections::VecDeque;

type Task = Pin<Box<dyn Future<Output = ()> + Send>>;

struct SimpleExecutor {
    tasks: Mutex<VecDeque<Task>>,
}

impl SimpleExecutor {
    fn new() -> Arc<Self> {
        Arc::new(SimpleExecutor {
            tasks: Mutex::new(VecDeque::new()),
        })
    }
    
    fn spawn(self: &Arc<Self>, task: impl Future<Output = ()> + Send + 'static) {
        self.tasks.lock().unwrap().push_back(Box::pin(task));
    }
    
    fn run(self: &Arc<Self>) {
        use std::task::Wake;
        
        struct NoopWaker;
        impl Wake for NoopWaker {
            fn wake(self: Arc<Self>) {}
        }
        
        let waker = Arc::new(NoopWaker).into();
        let mut cx = Context::from_waker(&waker);
        
        loop {
            let task = self.tasks.lock().unwrap().pop_front();
            match task {
                None => break,
                Some(mut t) => {
                    if t.as_mut().poll(&mut cx).is_pending() {
                        // 简化版: 直接放回队列 (实际应该注册 waker)
                        self.tasks.lock().unwrap().push_back(t);
                    }
                }
            }
        }
    }
}
```

---

### 练习 10: 异步缓存

```rust
use std::sync::Arc;
use std::collections::HashMap;
use tokio::sync::RwLock;
use tokio::time::{Instant, Duration};

struct CacheEntry<V> {
    value: V,
    expires_at: Instant,
}

pub struct AsyncCache<K, V> {
    store: Arc<RwLock<HashMap<K, CacheEntry<V>>>>,
    ttl: Duration,
}

impl<K: Eq + std::hash::Hash + Clone, V: Clone> AsyncCache<K, V> {
    pub fn new(ttl: Duration) -> Self {
        AsyncCache {
            store: Arc::new(RwLock::new(HashMap::new())),
            ttl,
        }
    }
    
    pub async fn get(&self, key: &K) -> Option<V> {
        let store = self.store.read().await;
        store.get(key).and_then(|entry| {
            if Instant::now() < entry.expires_at {
                Some(entry.value.clone())
            } else {
                None
            }
        })
    }
    
    pub async fn set(&self, key: K, value: V) {
        let mut store = self.store.write().await;
        store.insert(key, CacheEntry {
            value,
            expires_at: Instant::now() + self.ttl,
        });
    }
    
    pub async fn get_or_insert_with<F, Fut>(&self, key: K, f: F) -> V
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = V>,
    {
        if let Some(v) = self.get(&key).await {
            return v;
        }
        
        let value = f().await;
        self.set(key, value.clone()).await;
        value
    }
}

#[tokio::main]
async fn main() {
    let cache: AsyncCache<String, String> = AsyncCache::new(Duration::from_secs(60));
    
    let val = cache.get_or_insert_with("key1".to_string(), || async {
        println!("Computing...");
        "computed_value".to_string()
    }).await;
    
    println!("Got: {}", val);
    
    // 第二次从缓存获取
    let val2 = cache.get_or_insert_with("key1".to_string(), || async {
        println!("This shouldn't print!");
        "other".to_string()
    }).await;
    
    println!("Got: {}", val2);  // 从缓存获取
}
```

---

## 标准库与生态导读

### Future 标准库

- `std::future::Future` - 核心 trait
- `std::task::Poll` - 轮询结果
- `std::task::Context` / `Waker` - 唤醒机制
- `std::pin::Pin` - 防止移动

### Tokio 生态

| Crate | 用途 |
|-------|------|
| `tokio` | 异步运行时 |
| `tokio-stream` | 异步迭代器 |
| `futures` | Future 组合器 |
| `async-std` | 标准库异步版本 |
| `reqwest` | 异步 HTTP 客户端 |
| `sqlx` | 异步数据库 |
| `tonic` | 异步 gRPC |
| `axum` | 异步 Web 框架 |

---

## 小结

| 概念 | 说明 |
|------|------|
| `Future` | 可异步完成的计算 |
| `async fn` | 返回 `impl Future` 的语法糖 |
| `.await` | 等待 Future 完成 |
| `tokio::spawn` | 创建并发任务 |
| `tokio::join!` | 并发等待多个 Future |
| `tokio::select!` | 等待最先完成的 Future |
| `mpsc::channel` | 异步消息传递 |
| `Semaphore` | 并发限制 |

### 下一步

- [ ] 完成 10 道练习题
- [ ] 用 Tokio 实现一个简单的 TCP 服务器
- [ ] 阅读 `10-高级主题与源码阅读.md`

---

**掌握异步编程,你就能构建高性能的网络服务! 🦀**
