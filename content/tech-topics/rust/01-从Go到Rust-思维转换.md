# 从 Go 到 Rust: 思维转换

> **本章目标:** 建立正确的 Rust 思维模型,避免用 Go 的思维方式写 Rust 代码
> 
> **学习时间:** 2-3 天
> 
> **前置知识:** 熟悉 Go 编程

---

## 为什么需要思维转换?

Go 和 Rust 虽然都是现代系统编程语言,但设计哲学完全不同:

**Go 的哲学:**
- 简单至上,宁可冗余也不要复杂
- 运行时 GC,内存管理自动化
- 隐式接口,鸭子类型
- 轻量级并发(goroutine)

**Rust 的哲学:**
- 零成本抽象,性能与安全兼得
- 编译期内存管理,无 GC
- 显式 Trait,类型安全
- 系统级控制,所有权保证

**核心差异:**
```
Go: 运行时正确性 → 简单易用但有性能开销
Rust: 编译期正确性 → 学习曲线陡但零开销
```

---

## 核心概念对比表

| 概念 | Go | Rust | 思维转换 |
|------|-----|------|----------|
| **内存管理** | GC 自动回收 | 所有权系统 | 从"用完就忘"到"明确生命周期" |
| **错误处理** | error + panic | Result + panic | 从"返回值检查"到"类型强制" |
| **并发模型** | goroutine + channel | thread + async | 从"轻量级"到"零开销" |
| **类型系统** | interface{} | Trait + 泛型 | 从"隐式"到"显式" |
| **空值处理** | nil | Option\<T\> | 从"运行时检查"到"编译期保证" |
| **可变性** | 默认可变 | 默认不可变 | 从"可变优先"到"不可变优先" |

---

## 1. 内存管理: GC vs 所有权

### Go 的方式

```go
package main

func processData() *Data {
    data := &Data{value: 42}  // 堆分配
    // GC 会在未来某时回收
    return data
}

func main() {
    d1 := processData()
    d2 := d1  // 两个指针指向同一块内存
    d2.value = 100
    fmt.Println(d1.value)  // 输出: 100 (共享可变状态)
}
```

**Go 特点:**
- 内存分配随意,GC 自动清理
- 多个引用可以指向同一内存
- 共享可变状态很容易
- 运行时开销: GC 暂停

### Rust 的方式

```rust
struct Data {
    value: i32,
}

fn process_data() -> Data {
    let data = Data { value: 42 };  // 栈分配(或移动到调用方)
    data  // 移动所有权
}

fn main() {
    let d1 = process_data();
    let d2 = d1;  // d1 的所有权移动到 d2, d1 不再可用!
    // println!("{}", d1.value);  // 编译错误: borrow of moved value
    println!("{}", d2.value);  // 输出: 42
}
```

**Rust 特点:**
- 每个值有且仅有一个所有者
- 所有者离开作用域,值自动释放
- 共享和可变二选一
- 零运行时开销: 无 GC

### 思维转换

❌ **Go 思维:** "我创建了一个对象,到处传递指针,GC 会搞定一切"

✅ **Rust 思维:** "我创建了一个值,需要明确谁拥有它,什么时候释放"

**实践建议:**
1. 默认使用移动语义,而不是 Go 的指针传递
2. 需要共享时使用借用(&T)
3. 需要共享+修改时使用 Arc<Mutex<T>>

---

## 2. 错误处理: error vs Result

### Go 的方式

```go
func readFile(path string) ([]byte, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return nil, err
    }
    return data, nil
}

func main() {
    data, err := readFile("file.txt")
    if err != nil {  // 容易忘记检查!
        log.Fatal(err)
    }
    process(data)
}
```

**Go 特点:**
- 错误是返回值,手动检查
- 容易忘记检查(编译器不强制)
- nil 表示无错误

### Rust 的方式

```rust
use std::fs;
use std::io;

fn read_file(path: &str) -> Result<Vec<u8>, io::Error> {
    let data = fs::read(path)?;  // ? 操作符自动传播错误
    Ok(data)
}

fn main() -> Result<(), io::Error> {
    let data = read_file("file.txt")?;  // 必须处理 Result!
    process(data);
    Ok(())
}
```

**Rust 特点:**
- Result<T, E> 是类型,编译器强制处理
- ? 操作符简化错误传播
- 不处理会产生警告/错误

### 思维转换

❌ **Go 思维:** "记得检查 err != nil"

✅ **Rust 思维:** "Result 强制我处理错误,编译器是我的安全网"

**常用模式对比:**

| 场景 | Go | Rust |
|------|-----|------|
| 传播错误 | `if err != nil { return err }` | `?` |
| 默认值 | `if err != nil { return defaultValue }` | `.unwrap_or(default)` |
| panic | `panic(err)` | `.unwrap()` / `.expect("msg")` |
| 忽略错误 | `_, _ = someFunc()` | `let _ = result` (不推荐) |

---

## 3. 并发模型: goroutine vs thread/async

### Go 的方式

```go
func main() {
    ch := make(chan int)
    
    // 启动 goroutine
    go func() {
        result := compute()
        ch <- result
    }()
    
    // 接收结果
    result := <-ch
    fmt.Println(result)
}
```

**Go 特点:**
- goroutine 非常轻量(2KB 栈)
- 运行时调度
- channel 内置语法
- 适合大量并发任务

### Rust 的方式 (线程)

```rust
use std::thread;
use std::sync::mpsc;

fn main() {
    let (tx, rx) = mpsc::channel();
    
    // 启动线程
    thread::spawn(move || {
        let result = compute();
        tx.send(result).unwrap();
    });
    
    // 接收结果
    let result = rx.recv().unwrap();
    println!("{}", result);
}
```

**Rust 线程特点:**
- OS 线程(较重,1MB+ 栈)
- 零运行时开销
- 类型系统保证线程安全(Send/Sync)

### Rust 的方式 (异步)

```rust
use tokio;

#[tokio::main]
async fn main() {
    let result = tokio::spawn(async {
        compute().await
    }).await.unwrap();
    
    println!("{}", result);
}
```

**Rust async 特点:**
- 类似 goroutine 的轻量级
- 编译期转换为状态机
- 需要运行时(tokio/async-std)
- 零成本抽象

### 思维转换

❌ **Go 思维:** "启动 10000 个 goroutine 没问题"

✅ **Rust 思维:** 
- CPU 密集: 用线程池(rayon)
- I/O 密集: 用 async
- 少量任务: 用 OS 线程

---

## 4. 类型系统: interface vs Trait

### Go 的方式

```go
type Writer interface {
    Write([]byte) (int, error)
}

type FileWriter struct{}

func (f *FileWriter) Write(data []byte) (int, error) {
    // 实现...
    return len(data), nil
}

// 隐式实现接口
func save(w Writer) {
    w.Write([]byte("hello"))
}
```

**Go 特点:**
- 隐式接口,鸭子类型
- 运行时动态分派
- 灵活但有性能开销

### Rust 的方式

```rust
use std::io;

trait Writer {
    fn write(&mut self, data: &[u8]) -> io::Result<usize>;
}

struct FileWriter;

impl Writer for FileWriter {
    fn write(&mut self, data: &[u8]) -> io::Result<usize> {
        // 实现...
        Ok(data.len())
    }
}

// 静态分派(泛型)
fn save<W: Writer>(mut w: W) {
    w.write(b"hello").unwrap();
}

// 动态分派(trait 对象)
fn save_dyn(w: &mut dyn Writer) {
    w.write(b"hello").unwrap();
}
```

**Rust 特点:**
- 显式 Trait,类型安全
- 默认静态分派(零开销)
- 可选动态分派(dyn Trait)

### 思维转换

❌ **Go 思维:** "只要有 Write 方法就是 Writer"

✅ **Rust 思维:** 
- 默认用泛型(<T: Trait>),编译期单态化
- 需要运行时多态才用 trait 对象(dyn Trait)

---

## 5. 空值处理: nil vs Option

### Go 的方式

```go
func findUser(id int) *User {
    // 可能返回 nil
    if id == 0 {
        return nil
    }
    return &User{id: id}
}

func main() {
    user := findUser(0)
    if user != nil {  // 容易忘记检查!
        fmt.Println(user.id)
    }
}
```

**Go 特点:**
- nil 可以表示"无值"
- 容易忘记检查导致 panic

### Rust 的方式

```rust
fn find_user(id: i32) -> Option<User> {
    if id == 0 {
        None
    } else {
        Some(User { id })
    }
}

fn main() {
    let user = find_user(0);
    match user {  // 编译器强制处理 Option!
        Some(u) => println!("{}", u.id),
        None => println!("User not found"),
    }
    
    // 或使用链式调用
    find_user(1)
        .map(|u| u.id)
        .unwrap_or(0);
}
```

**Rust 特点:**
- Option<T> 是类型,无 null
- 编译器强制处理 None

### 思维转换

❌ **Go 思维:** "返回 nil 表示失败"

✅ **Rust 思维:** 
- 可能无值: Option<T>
- 可能失败: Result<T, E>
- 编译器保证我处理所有情况

---

## 6. 可变性: 默认可变 vs 默认不可变

### Go 的方式

```go
func main() {
    x := 42
    x = 100  // 默认可变
    
    user := User{name: "Alice"}
    user.name = "Bob"  // 默认可变
}
```

### Rust 的方式

```rust
fn main() {
    let x = 42;
    // x = 100;  // 编译错误: cannot assign twice to immutable variable
    
    let mut y = 42;
    y = 100;  // OK: 显式声明可变
    
    let user = User { name: "Alice".to_string() };
    // user.name = "Bob".to_string();  // 编译错误
    
    let mut user2 = User { name: "Alice".to_string() };
    user2.name = "Bob".to_string();  // OK
}
```

### 思维转换

❌ **Go 思维:** "变量默认可变,需要时才考虑不可变"

✅ **Rust 思维:** 
- 默认不可变,减少 bug
- 需要修改时显式 `mut`
- 不可变引用可以多个,可变引用只能一个

---

## 7. 完整示例对比

### 示例: HTTP 服务器读取配置文件

**Go 版本:**

```go
package main

import (
    "encoding/json"
    "fmt"
    "net/http"
    "os"
)

type Config struct {
    Port int    `json:"port"`
    Host string `json:"host"`
}

func loadConfig(path string) (*Config, error) {
    data, err := os.ReadFile(path)
    if err != nil {
        return nil, err
    }
    
    var config Config
    err = json.Unmarshal(data, &config)
    if err != nil {
        return nil, err
    }
    
    return &config, nil
}

func main() {
    config, err := loadConfig("config.json")
    if err != nil {
        panic(err)
    }
    
    addr := fmt.Sprintf("%s:%d", config.Host, config.Port)
    fmt.Printf("Listening on %s\n", addr)
    
    http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
        fmt.Fprintf(w, "Hello, World!")
    })
    
    http.ListenAndServe(addr, nil)
}
```

**Rust 版本:**

```rust
use serde::{Deserialize, Serialize};
use std::fs;
use std::io;
use axum::{routing::get, Router};

#[derive(Debug, Deserialize, Serialize)]
struct Config {
    port: u16,
    host: String,
}

fn load_config(path: &str) -> Result<Config, io::Error> {
    let data = fs::read_to_string(path)?;
    let config: Config = serde_json::from_str(&data)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    Ok(config)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = load_config("config.json")?;
    let addr = format!("{}:{}", config.host, config.port);
    println!("Listening on {}", addr);
    
    let app = Router::new().route("/", get(|| async { "Hello, World!" }));
    
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;
    
    Ok(())
}
```

**关键差异分析:**

| 方面 | Go | Rust |
|------|-----|------|
| 错误处理 | `if err != nil` | `?` 操作符 |
| 内存管理 | 返回指针,GC 清理 | 所有权移动 |
| 异步 | 不需要 async | 需要 async runtime |
| 类型安全 | interface{} | 泛型约束 |
| 序列化 | struct tags | derive 宏 |

---

## 8. 常见陷阱与避免方法

### 陷阱 1: Go 式的到处传指针

❌ **错误代码:**

```rust
// 试图模仿 Go 的指针传递
fn process(data: &mut Vec<i32>) {
    data.push(42);
}

fn main() {
    let mut vec = Vec::new();
    process(&mut vec);  // 过度使用可变借用
}
```

✅ **正确做法:**

```rust
// Rust 风格: 消费并返回
fn process(mut data: Vec<i32>) -> Vec<i32> {
    data.push(42);
    data
}

fn main() {
    let vec = Vec::new();
    let vec = process(vec);  // 所有权移动
}
```

### 陷阱 2: 忽略 Result/Option

❌ **错误代码:**

```rust
// 编译器会产生 unused Result 警告
let result = some_operation();
// 忘记处理 Result,直接继续
println!("done");
```

✅ **正确做法:**

```rust
let value = some_operation()?;  // 错误传播
// 或
let value = some_operation().unwrap_or_default();  // 提供默认值
// 或  
match some_operation() {
    Ok(v) => handle(v),
    Err(e) => eprintln!("Error: {}", e),
}
```

### 陷阱 3: 过度使用 clone

❌ **错误代码:**

```rust
fn process(data: Vec<i32>) {
    for item in data.clone() {  // 不必要的克隆!
        println!("{}", item);
    }
    // data 在这里还可以使用
}
```

✅ **正确做法:**

```rust
fn process(data: &[i32]) {  // 借用切片
    for item in data {
        println!("{}", item);
    }
}
```

### 陷阱 4: 用 Go 的方式处理字符串

❌ **错误代码:**

```rust
let s1: String = String::from("hello");
let s2: String = s1;  // 移动了!
println!("{}", s1);  // 编译错误!
```

✅ **正确做法:**

```rust
let s1: String = String::from("hello");
let s2: &str = &s1;  // 借用,不移动
println!("{} {}", s1, s2);  // 两者都可用

// 或克隆
let s3 = s1.clone();
println!("{} {}", s1, s3);
```

---

## 9. 学习建议

### 第 1 周重点

1. **接受不适感:** Rust 的编译器会频繁报错,这是正常的
2. **理解所有权:** 这是最核心的概念,其他都建立在此基础上
3. **对比 Go:** 每学一个概念,思考 Go 如何实现

### 实践练习

**练习 1: 重写 Go 代码**

选择一个简单的 Go 程序,用 Rust 重写:
- 文件读写工具
- JSON 解析
- HTTP 客户端

**练习 2: 修复编译错误**

故意写有问题的代码,练习理解编译器错误信息:

```rust
// 尝试编译这段代码,理解错误信息
fn broken_code() {
    let s = String::from("hello");
    let s2 = s;
    println!("{}", s);  // 错误在哪?
    
    let x = 5;
    x = 10;  // 错误在哪?
    
    let r: &str;
    {
        let owned = String::from("test");
        r = &owned;  // 错误在哪?
    }
    println!("{}", r);
}
```

### 进阶学习

完成本章后,继续学习:
- `02-所有权与内存模型.md` - 深入理解所有权
- `03-借用检查器原理.md` - 借用检查器如何工作

---

## 10. 章节练习题

### 练习 1 (基础): 类型识别

以下 Rust 代码会编译吗?为什么?

```rust
fn main() {
    let v1 = vec![1, 2, 3];
    let v2 = v1;
    println!("{:?}", v1);
}
```

**答案:** 不会编译。`v1` 的所有权已经 move 到 `v2`。应改为:
```rust
let v2 = v1.clone();  // 克隆
// 或
let v2 = &v1;  // 借用
```

---

### 练习 2 (基础): 错误处理

将以下 Go 代码转换为 Rust:
```go
func divide(a, b int) (int, error) {
    if b == 0 {
        return 0, errors.New("division by zero")
    }
    return a / b, nil
}
```

**答案:**
```rust
fn divide(a: i32, b: i32) -> Result<i32, String> {
    if b == 0 {
        Err(String::from("division by zero"))
    } else {
        Ok(a / b)
    }
}
```

---

### 练习 3 (中等): 并发计算

用 Rust 实现一个并发求和:启动 4 个线程,每个线程计算一部分数据的和,最后汇总。

**答案:**
```rust
use std::thread;
use std::sync::{Arc, Mutex};

fn parallel_sum(data: Vec<i32>) -> i32 {
    let chunk_size = data.len() / 4;
    let data = Arc::new(data);
    let mut handles = vec![];
    
    for i in 0..4 {
        let data = Arc::clone(&data);
        let handle = thread::spawn(move || {
            let start = i * chunk_size;
            let end = if i == 3 { data.len() } else { start + chunk_size };
            data[start..end].iter().sum::<i32>()
        });
        handles.push(handle);
    }
    
    handles.into_iter().map(|h| h.join().unwrap()).sum()
}

fn main() {
    let data: Vec<i32> = (1..=100).collect();
    let sum = parallel_sum(data);
    println!("Sum: {}", sum);  // 5050
}
```

---

### 练习 4 (中等): Trait 实现

实现一个 `Shape` trait,包含 `area()` 方法,分别为 `Circle` 和 `Rectangle` 实现。

**答案:**
```rust
use std::f64::consts::PI;

trait Shape {
    fn area(&self) -> f64;
    fn name(&self) -> &str;
}

struct Circle {
    radius: f64,
}

struct Rectangle {
    width: f64,
    height: f64,
}

impl Shape for Circle {
    fn area(&self) -> f64 {
        PI * self.radius * self.radius
    }
    
    fn name(&self) -> &str {
        "Circle"
    }
}

impl Shape for Rectangle {
    fn area(&self) -> f64 {
        self.width * self.height
    }
    
    fn name(&self) -> &str {
        "Rectangle"
    }
}

fn print_shape_info(shapes: &[&dyn Shape]) {
    for shape in shapes {
        println!("{}: area = {:.2}", shape.name(), shape.area());
    }
}

fn main() {
    let c = Circle { radius: 3.0 };
    let r = Rectangle { width: 4.0, height: 5.0 };
    
    print_shape_info(&[&c, &r]);
}
```

---

### 练习 5 (挑战): 重写简单的 Go 工具

将以下 Go 版本的单词计数工具转换为 Rust:

```go
package main

import (
    "bufio"
    "fmt"
    "os"
    "strings"
)

func countWords(filename string) (map[string]int, error) {
    f, err := os.Open(filename)
    if err != nil {
        return nil, err
    }
    defer f.Close()
    
    counts := make(map[string]int)
    scanner := bufio.NewScanner(f)
    for scanner.Scan() {
        for _, word := range strings.Fields(scanner.Text()) {
            counts[strings.ToLower(word)]++
        }
    }
    return counts, scanner.Err()
}
```

**答案:**
```rust
use std::collections::HashMap;
use std::fs::File;
use std::io::{self, BufRead, BufReader};

fn count_words(filename: &str) -> Result<HashMap<String, usize>, io::Error> {
    let file = File::open(filename)?;
    let reader = BufReader::new(file);
    let mut counts: HashMap<String, usize> = HashMap::new();
    
    for line in reader.lines() {
        let line = line?;
        for word in line.split_whitespace() {
            let word = word.to_lowercase();
            *counts.entry(word).or_insert(0) += 1;
        }
    }
    
    Ok(counts)
}

fn main() -> Result<(), io::Error> {
    let counts = count_words("input.txt")?;
    
    let mut pairs: Vec<(&String, &usize)> = counts.iter().collect();
    pairs.sort_by(|a, b| b.1.cmp(a.1));
    
    for (word, count) in pairs.iter().take(10) {
        println!("{}: {}", word, count);
    }
    
    Ok(())
}
```

---

## 小结

### Go → Rust 思维转换核心

| 从 Go | 到 Rust |
|-------|---------|
| GC 自动管理 | 所有权手动控制 |
| 运行时检查 | 编译期保证 |
| 隐式灵活 | 显式严格 |
| 简单优先 | 性能优先 |
| 运行时代价 | 零成本抽象 |

### 关键要点

1. **所有权是核心:** 理解它,其他都好理解
2. **编译器是朋友:** 错误信息帮你避免 bug
3. **显式优于隐式:** Rust 要求明确意图
4. **性能无妥协:** 抽象不带来运行时开销

### 下一步

- [ ] 完成本章练习题(见 `练习题与解答.md` 第 1 章)
- [ ] 阅读 `02-所有权与内存模型.md`
- [ ] 用 Rust 重写一个简单的 Go 程序

---

**准备好接受挑战了吗? Rust 的学习曲线陡峭,但登顶后的风景无限美好! 🦀**
