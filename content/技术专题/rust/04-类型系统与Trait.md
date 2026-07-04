# 类型系统与 Trait

> **本章目标:** 深入理解 Rust 的 Trait 系统,掌握静态/动态分派,能设计优雅的 API
> 
> **学习时间:** 5-7 天
> 
> **前置知识:** 完成 `03-借用检查器原理.md`

---

## Rust 类型系统概览

Rust 拥有强大的静态类型系统。与 Go 的隐式接口不同,Rust 的 Trait 需要显式实现,但提供了更强的类型安全保证和零成本抽象。

---

## 1. Trait 基础

### 定义和实现 Trait

```rust
// 定义 Trait
trait Greet {
    fn hello(&self) -> String;
    
    // 默认实现
    fn greet_with_name(&self, name: &str) -> String {
        format!("{}, {}!", self.hello(), name)
    }
}

struct English;
struct Chinese;

// 实现 Trait
impl Greet for English {
    fn hello(&self) -> String {
        String::from("Hello")
    }
}

impl Greet for Chinese {
    fn hello(&self) -> String {
        String::from("你好")
    }
    
    // 覆盖默认实现
    fn greet_with_name(&self, name: &str) -> String {
        format!("{}，{}！", self.hello(), name)
    }
}

fn main() {
    let e = English;
    let c = Chinese;
    
    println!("{}", e.greet_with_name("World"));
    println!("{}", c.greet_with_name("世界"));
}
```

### Trait vs Go Interface 对比

```
Go Interface:           Rust Trait:
- 隐式实现              - 显式 impl
- 运行时类型检查        - 编译期类型检查
- 只支持方法            - 支持方法、关联类型、关联常量
- 动态分派 (默认)       - 静态分派 (默认) / 动态分派 (dyn)
```

---

## 2. 静态分派 vs 动态分派

### 静态分派 (单态化)

```rust
trait Animal {
    fn speak(&self) -> &str;
}

struct Dog;
struct Cat;

impl Animal for Dog {
    fn speak(&self) -> &str { "Woof!" }
}

impl Animal for Cat {
    fn speak(&self) -> &str { "Meow!" }
}

// 泛型函数 - 编译期单态化
fn make_sound<A: Animal>(animal: &A) {
    println!("{}", animal.speak());
}

fn main() {
    let dog = Dog;
    let cat = Cat;
    
    make_sound(&dog);  // 编译生成 make_sound_dog 版本
    make_sound(&cat);  // 编译生成 make_sound_cat 版本
}
```

**单态化的结果:** 编译器为每种类型生成专门的函数版本,运行时零开销。

### 动态分派 (trait 对象)

```rust
// dyn Trait - 运行时分派
fn make_all_speak(animals: &[Box<dyn Animal>]) {
    for animal in animals {
        println!("{}", animal.speak());  // 运行时通过 vtable 查找
    }
}

fn main() {
    let animals: Vec<Box<dyn Animal>> = vec![
        Box::new(Dog),
        Box::new(Cat),
        Box::new(Dog),
    ];
    
    make_all_speak(&animals);
}
```

### vtable 的内存布局

```
Box<dyn Animal> 的内存布局:
┌─────────────────────────┐
│ data pointer → Dog/Cat  │  指向实际数据
│ vtable pointer → vtable │  指向虚函数表
└─────────────────────────┘

vtable for Dog:
┌──────────────────────────┐
│ drop function            │
│ size                     │
│ alignment                │
│ Animal::speak → Dog::speak│
└──────────────────────────┘
```

### 选择哪种分派?

```rust
// 使用静态分派的情况:
// - 性能关键代码
// - 类型在编译期已知
// - 不需要运行时多态
fn process_data<T: Serialize + Deserialize>(data: &T) { ... }

// 使用动态分派的情况:
// - 需要存储不同类型的集合
// - 类型在运行时才知道
// - 减少代码体积 (不生成多份单态化代码)
fn register_handlers(handlers: &mut Vec<Box<dyn EventHandler>>) { ... }
```

---

## 3. 关联类型 vs 泛型参数

### 关联类型 (Associated Types)

```rust
trait Iterator {
    type Item;  // 关联类型
    
    fn next(&mut self) -> Option<Self::Item>;
}

struct Counter {
    count: u32,
    max: u32,
}

impl Iterator for Counter {
    type Item = u32;  // 每个实现只能有一种 Item 类型
    
    fn next(&mut self) -> Option<u32> {
        if self.count < self.max {
            self.count += 1;
            Some(self.count)
        } else {
            None
        }
    }
}
```

### 泛型参数

```rust
// 可以为同一类型实现多个版本
trait Converter<T> {
    fn convert(&self) -> T;
}

struct Number(i32);

impl Converter<f64> for Number {
    fn convert(&self) -> f64 {
        self.0 as f64
    }
}

impl Converter<String> for Number {
    fn convert(&self) -> String {
        self.0.to_string()
    }
}
```

### 何时用关联类型,何时用泛型?

```
关联类型: 一个类型只有一种实现 (如 Iterator::Item)
泛型参数: 一个类型可以有多种实现 (如 From<T>)
```

---

## 4. Trait 约束与 where 子句

```rust
use std::fmt::{Debug, Display};

// 多重约束
fn print_debug<T: Debug + Display>(x: T) {
    println!("Debug: {:?}", x);
    println!("Display: {}", x);
}

// where 子句 (更清晰)
fn complex_function<T, U>(t: T, u: U) -> String
where
    T: Display + Clone,
    U: Debug + PartialOrd,
{
    format!("t={}, u={:?}", t.clone(), u)
}

// 返回实现了 Trait 的类型 (impl Trait)
fn make_greeting() -> impl Fn(String) -> String {
    |name| format!("Hello, {}!", name)
}

// Trait 约束在 impl 块上
struct Wrapper<T>(T);

impl<T: Display> Wrapper<T> {
    fn show(&self) {
        println!("{}", self.0);
    }
}
```

---

## 5. 标准库重要 Trait

### Display 和 Debug

```rust
use std::fmt;

struct Matrix {
    data: [[f64; 2]; 2],
}

// Display: 人类可读格式
impl fmt::Display for Matrix {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "[ {:.2} {:.2} ]\n[ {:.2} {:.2} ]",
               self.data[0][0], self.data[0][1],
               self.data[1][0], self.data[1][1])
    }
}

// Debug: 调试格式 (通常可以 derive)
impl fmt::Debug for Matrix {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "Matrix {{ data: {:?} }}", self.data)
    }
}
```

### From 和 Into

```rust
#[derive(Debug)]
struct Celsius(f64);

#[derive(Debug)]
struct Fahrenheit(f64);

impl From<Celsius> for Fahrenheit {
    fn from(c: Celsius) -> Self {
        Fahrenheit(c.0 * 9.0 / 5.0 + 32.0)
    }
}

fn main() {
    let boiling = Celsius(100.0);
    let f: Fahrenheit = boiling.into();  // Into 自动获得
    // 或
    let f = Fahrenheit::from(Celsius(100.0));
    
    println!("{:?}", f);  // Fahrenheit(212.0)
}
```

### Iterator Trait

```rust
struct Fibonacci {
    a: u64,
    b: u64,
}

impl Fibonacci {
    fn new() -> Self {
        Fibonacci { a: 0, b: 1 }
    }
}

impl Iterator for Fibonacci {
    type Item = u64;
    
    fn next(&mut self) -> Option<u64> {
        let next = self.a + self.b;
        self.a = self.b;
        self.b = next;
        Some(self.a)
    }
}

fn main() {
    let fibs: Vec<u64> = Fibonacci::new()
        .take(10)
        .collect();
    println!("{:?}", fibs);
    
    // Iterator 提供大量适配器方法
    let sum: u64 = Fibonacci::new()
        .take_while(|&n| n < 1000)
        .filter(|n| n % 2 == 0)
        .sum();
    println!("偶数斐波那契数之和 (< 1000): {}", sum);
}
```

### Deref 和 DerefMut

```rust
use std::ops::Deref;

struct MyBox<T>(T);

impl<T> MyBox<T> {
    fn new(x: T) -> Self {
        MyBox(x)
    }
}

impl<T> Deref for MyBox<T> {
    type Target = T;
    
    fn deref(&self) -> &T {
        &self.0
    }
}

fn hello(name: &str) {
    println!("Hello, {}!", name);
}

fn main() {
    let x = 5;
    let y = MyBox::new(x);
    
    assert_eq!(5, *y);  // 使用 Deref, 等同于 *(y.deref())
    
    let m = MyBox::new(String::from("Rust"));
    hello(&m);  // 自动 Deref: &MyBox<String> → &String → &str
}
```

---

## 6. Trait 对象的限制 (对象安全)

```rust
// 只有满足"对象安全"的 Trait 才能用作 dyn Trait

// 对象安全的 Trait:
trait Safe {
    fn method(&self) -> String;  // 没有泛型参数
    fn other(&self, x: i32);     // 参数不包含 Self
}

// 不是对象安全的 Trait:
trait NotSafe {
    fn clone_self(&self) -> Self;  // 返回 Self 类型
    fn generic<T>(&self, x: T);   // 泛型方法
}

// 如何处理不安全的 Trait?
// 方案 1: 添加 where Self: Sized 约束排除
trait PartiallyObjectSafe {
    fn clone_self(&self) -> Self where Self: Sized;  // 不包含在 vtable 中
    fn method(&self) -> String;  // 可以包含在 vtable 中
}

// 方案 2: 使用 Box<dyn Trait> 的替代
fn clone_box<T: Clone + 'static>(x: &T) -> Box<dyn std::any::Any> {
    Box::new(x.clone())
}
```

---

## 7. 高级 Trait 特性

### Blanket Implementation (毯子实现)

```rust
use std::fmt::Display;

// 为所有实现了 Display 的类型实现额外功能
trait PrintDebug {
    fn print_and_return(&self) -> String;
}

impl<T: Display> PrintDebug for T {
    fn print_and_return(&self) -> String {
        let s = format!("{}", self);
        println!("{}", s);
        s
    }
}

fn main() {
    let x = 42;
    let s = "hello";
    let v = 3.14f64;
    
    x.print_and_return();
    s.print_and_return();
    v.print_and_return();
}
```

### 运算符重载

```rust
use std::ops::{Add, Mul};

#[derive(Debug, Clone, Copy, PartialEq)]
struct Vec2 {
    x: f64,
    y: f64,
}

impl Add for Vec2 {
    type Output = Vec2;
    
    fn add(self, rhs: Vec2) -> Vec2 {
        Vec2 { x: self.x + rhs.x, y: self.y + rhs.y }
    }
}

impl Mul<f64> for Vec2 {
    type Output = Vec2;
    
    fn mul(self, scalar: f64) -> Vec2 {
        Vec2 { x: self.x * scalar, y: self.y * scalar }
    }
}

impl Vec2 {
    fn dot(&self, other: &Vec2) -> f64 {
        self.x * other.x + self.y * other.y
    }
    
    fn length(&self) -> f64 {
        (self.x * self.x + self.y * self.y).sqrt()
    }
}

fn main() {
    let v1 = Vec2 { x: 1.0, y: 2.0 };
    let v2 = Vec2 { x: 3.0, y: 4.0 };
    
    let sum = v1 + v2;
    let scaled = v1 * 2.0;
    
    println!("sum: {:?}", sum);
    println!("scaled: {:?}", scaled);
    println!("dot product: {}", v1.dot(&v2));
    println!("length of v2: {:.2}", v2.length());
}
```

### 完全限定语法 (UFCS)

```rust
trait Pilot {
    fn fly(&self);
}

trait Wizard {
    fn fly(&self);
}

struct Person;

impl Pilot for Person {
    fn fly(&self) {
        println!("This is your captain speaking.");
    }
}

impl Wizard for Person {
    fn fly(&self) {
        println!("Up!");
    }
}

impl Person {
    fn fly(&self) {
        println!("*waving arms furiously*");
    }
}

fn main() {
    let person = Person;
    
    person.fly();              // 调用 Person 自身的 fly
    Pilot::fly(&person);       // 调用 Pilot Trait 的 fly
    Wizard::fly(&person);      // 调用 Wizard Trait 的 fly
    
    // 完全限定语法
    <Person as Pilot>::fly(&person);
}
```

---

## 8. derive 宏与常用 Trait

```rust
// 常用的 derive Trait
#[derive(
    Debug,      // 格式化输出: {:?}
    Clone,      // Clone::clone()
    Copy,       // 隐式复制 (需要所有字段都是 Copy)
    PartialEq,  // == 和 != 操作符
    Eq,         // 完全等价关系 (需要 PartialEq)
    PartialOrd, // <, >, <=, >= 操作符
    Ord,        // 全序关系 (需要 PartialOrd + Eq)
    Hash,       // 用作 HashMap/HashSet 的 key
    Default,    // Default::default() → 0/false/None...
)]
struct Config {
    timeout: u32,
    retries: u8,
    verbose: bool,
}

fn main() {
    let c1 = Config { timeout: 30, retries: 3, verbose: false };
    let c2 = c1.clone();
    
    println!("{:?}", c1);
    println!("Equal: {}", c1 == c2);
    
    // Default
    let c3 = Config::default();
    println!("{:?}", c3);
    
    // 使用 ..Default::default() 语法
    let c4 = Config { timeout: 60, ..Config::default() };
    println!("{:?}", c4);
}
```

---

## 9. Trait 设计模式

### Builder 模式

```rust
#[derive(Debug)]
struct HttpRequest {
    url: String,
    method: String,
    headers: Vec<(String, String)>,
    body: Option<String>,
    timeout: u32,
}

struct HttpRequestBuilder {
    url: String,
    method: String,
    headers: Vec<(String, String)>,
    body: Option<String>,
    timeout: u32,
}

impl HttpRequestBuilder {
    fn new(url: &str) -> Self {
        HttpRequestBuilder {
            url: url.to_string(),
            method: "GET".to_string(),
            headers: vec![],
            body: None,
            timeout: 30,
        }
    }
    
    fn method(mut self, method: &str) -> Self {
        self.method = method.to_string();
        self
    }
    
    fn header(mut self, key: &str, value: &str) -> Self {
        self.headers.push((key.to_string(), value.to_string()));
        self
    }
    
    fn body(mut self, body: &str) -> Self {
        self.body = Some(body.to_string());
        self
    }
    
    fn timeout(mut self, secs: u32) -> Self {
        self.timeout = secs;
        self
    }
    
    fn build(self) -> HttpRequest {
        HttpRequest {
            url: self.url,
            method: self.method,
            headers: self.headers,
            body: self.body,
            timeout: self.timeout,
        }
    }
}

fn main() {
    let req = HttpRequestBuilder::new("https://api.example.com/users")
        .method("POST")
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer token123")
        .body(r#"{"name": "Alice"}"#)
        .timeout(60)
        .build();
    
    println!("{:#?}", req);
}
```

### 类型状态模式 (Typestate Pattern)

```rust
// 使用类型确保状态机的正确行为
struct Locked;
struct Unlocked;

struct Safe<State> {
    content: String,
    _state: std::marker::PhantomData<State>,
}

impl Safe<Locked> {
    fn new(content: &str) -> Self {
        Safe {
            content: content.to_string(),
            _state: std::marker::PhantomData,
        }
    }
    
    fn unlock(self, password: &str) -> Result<Safe<Unlocked>, Safe<Locked>> {
        if password == "secret" {
            Ok(Safe {
                content: self.content,
                _state: std::marker::PhantomData,
            })
        } else {
            Err(self)
        }
    }
}

impl Safe<Unlocked> {
    fn get_content(&self) -> &str {
        &self.content
    }
    
    fn lock(self) -> Safe<Locked> {
        Safe {
            content: self.content,
            _state: std::marker::PhantomData,
        }
    }
}

fn main() {
    let safe = Safe::<Locked>::new("secret treasure");
    
    // safe.get_content();  // 编译错误! Locked 状态没有 get_content
    
    match safe.unlock("wrong") {
        Err(locked_safe) => {
            println!("Wrong password!");
            match locked_safe.unlock("secret") {
                Ok(unlocked) => println!("Content: {}", unlocked.get_content()),
                Err(_) => println!("Still locked"),
            }
        }
        Ok(_) => unreachable!(),
    }
}
```

---

## 练习题

### 练习 1 (基础): 实现 Display

为以下结构体实现 `Display` trait:

```rust
struct Color {
    red: u8,
    green: u8,
    blue: u8,
}

// 实现 Display, 输出格式: "RGB(255, 128, 0)"
// 同时实现十六进制格式: "#FF8000"
```

**答案:**
```rust
use std::fmt;

struct Color { red: u8, green: u8, blue: u8 }

impl fmt::Display for Color {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "RGB({}, {}, {})", self.red, self.green, self.blue)
    }
}

impl fmt::LowerHex for Color {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(f, "#{:02x}{:02x}{:02x}", self.red, self.green, self.blue)
    }
}

fn main() {
    let c = Color { red: 255, green: 128, blue: 0 };
    println!("{}", c);     // RGB(255, 128, 0)
    println!("{:x}", c);   // #ff8000
}
```

---

### 练习 2 (基础): Trait 继承

```rust
// 实现以下 Trait 层次结构:
// Animal → Pet → Dog
// Animal: name() 方法
// Pet: Animal + owner() 方法
// Dog: Pet + breed() 方法

trait Animal {
    fn name(&self) -> &str;
    fn sound(&self) -> &str;
}

trait Pet: Animal {
    fn owner(&self) -> &str;
}

struct Dog {
    name: String,
    owner: String,
    breed: String,
}

// 实现所有需要的 Trait
impl Animal for Dog {
    fn name(&self) -> &str { &self.name }
    fn sound(&self) -> &str { "Woof" }
}

impl Pet for Dog {
    fn owner(&self) -> &str { &self.owner }
}

fn introduce_pet(pet: &dyn Pet) {
    println!("{} 是 {} 的宠物, 叫声 '{}'",
             pet.name(), pet.owner(), pet.sound());
}
```

---

### 练习 3 (中等): 自定义迭代器

实现一个范围迭代器,步进值可以指定:

```rust
struct StepRange {
    current: i32,
    end: i32,
    step: i32,
}

impl StepRange {
    fn new(start: i32, end: i32, step: i32) -> Self {
        StepRange { current: start, end, step }
    }
}

impl Iterator for StepRange {
    type Item = i32;
    
    fn next(&mut self) -> Option<i32> {
        if (self.step > 0 && self.current < self.end) ||
           (self.step < 0 && self.current > self.end) {
            let val = self.current;
            self.current += self.step;
            Some(val)
        } else {
            None
        }
    }
}

fn main() {
    // 正向
    let v: Vec<i32> = StepRange::new(0, 10, 2).collect();
    println!("{:?}", v);  // [0, 2, 4, 6, 8]
    
    // 反向
    let v: Vec<i32> = StepRange::new(10, 0, -3).collect();
    println!("{:?}", v);  // [10, 7, 4, 1]
}
```

---

### 练习 4 (中等): From/Into 转换

为错误类型实现 From 转换:

```rust
#[derive(Debug)]
enum AppError {
    Io(std::io::Error),
    Parse(std::num::ParseIntError),
    Custom(String),
}

impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::Io(e)
    }
}

impl From<std::num::ParseIntError> for AppError {
    fn from(e: std::num::ParseIntError) -> Self {
        AppError::Parse(e)
    }
}

// 使用 ? 操作符自动转换错误类型
fn read_number(path: &str) -> Result<i32, AppError> {
    let content = std::fs::read_to_string(path)?;  // io::Error → AppError
    let num: i32 = content.trim().parse()?;         // ParseIntError → AppError
    Ok(num)
}
```

---

### 练习 5 (中等): 泛型排序

实现一个通用的快速排序:

```rust
fn quicksort<T: PartialOrd>(arr: &mut [T]) {
    if arr.len() <= 1 {
        return;
    }
    
    let pivot = arr.len() - 1;
    let mut store = 0;
    
    for i in 0..pivot {
        if arr[i] <= arr[pivot] {
            arr.swap(i, store);
            store += 1;
        }
    }
    
    arr.swap(store, pivot);
    
    let (left, right) = arr.split_at_mut(store);
    quicksort(left);
    if right.len() > 1 {
        quicksort(&mut right[1..]);
    }
}

fn main() {
    let mut v = vec![3, 1, 4, 1, 5, 9, 2, 6, 5, 3];
    quicksort(&mut v);
    println!("{:?}", v);
    
    let mut words = vec!["banana", "apple", "cherry", "date"];
    quicksort(&mut words);
    println!("{:?}", words);
}
```

---

### 练习 6 (中等): Trait 对象集合

实现一个插件系统:

```rust
trait Plugin {
    fn name(&self) -> &str;
    fn execute(&self, input: &str) -> String;
}

struct UpperCasePlugin;
struct ReversePlugin;
struct LengthPlugin;

impl Plugin for UpperCasePlugin {
    fn name(&self) -> &str { "uppercase" }
    fn execute(&self, input: &str) -> String { input.to_uppercase() }
}

impl Plugin for ReversePlugin {
    fn name(&self) -> &str { "reverse" }
    fn execute(&self, input: &str) -> String { input.chars().rev().collect() }
}

impl Plugin for LengthPlugin {
    fn name(&self) -> &str { "length" }
    fn execute(&self, input: &str) -> String { input.len().to_string() }
}

struct PluginManager {
    plugins: Vec<Box<dyn Plugin>>,
}

impl PluginManager {
    fn new() -> Self {
        PluginManager { plugins: vec![] }
    }
    
    fn register(&mut self, plugin: Box<dyn Plugin>) {
        self.plugins.push(plugin);
    }
    
    fn run(&self, input: &str) -> Vec<(String, String)> {
        self.plugins.iter()
            .map(|p| (p.name().to_string(), p.execute(input)))
            .collect()
    }
}

fn main() {
    let mut mgr = PluginManager::new();
    mgr.register(Box::new(UpperCasePlugin));
    mgr.register(Box::new(ReversePlugin));
    mgr.register(Box::new(LengthPlugin));
    
    for (name, result) in mgr.run("hello world") {
        println!("[{}]: {}", name, result);
    }
}
```

---

### 练习 7 (挑战): 泛型数据结构

实现一个泛型栈:

```rust
pub struct Stack<T> {
    elements: Vec<T>,
}

impl<T> Stack<T> {
    pub fn new() -> Self {
        Stack { elements: vec![] }
    }
    
    pub fn push(&mut self, item: T) {
        self.elements.push(item);
    }
    
    pub fn pop(&mut self) -> Option<T> {
        self.elements.pop()
    }
    
    pub fn peek(&self) -> Option<&T> {
        self.elements.last()
    }
    
    pub fn is_empty(&self) -> bool {
        self.elements.is_empty()
    }
    
    pub fn size(&self) -> usize {
        self.elements.len()
    }
}

// 为 Stack 实现 Iterator (消费栈)
impl<T> IntoIterator for Stack<T> {
    type Item = T;
    type IntoIter = std::iter::Rev<std::vec::IntoIter<T>>;
    
    fn into_iter(self) -> Self::IntoIter {
        self.elements.into_iter().rev()
    }
}

// 测试: 括号匹配
fn is_balanced(s: &str) -> bool {
    let mut stack = Stack::new();
    
    for c in s.chars() {
        match c {
            '(' | '[' | '{' => stack.push(c),
            ')' => if stack.pop() != Some('(') { return false; },
            ']' => if stack.pop() != Some('[') { return false; },
            '}' => if stack.pop() != Some('{') { return false; },
            _ => {}
        }
    }
    
    stack.is_empty()
}

fn main() {
    println!("{}", is_balanced("({[]})"));   // true
    println!("{}", is_balanced("({[})"));    // false
    println!("{}", is_balanced("((()))"));   // true
}
```

---

### 练习 8 (挑战): 实现 Clone 和 Default

```rust
// 为这个复杂结构体手动实现克隆和默认值
struct Config {
    name: String,
    values: Vec<i32>,
    enabled: bool,
    callback: Option<Box<dyn Fn(i32) -> i32 + Send>>,
}

// 注意: callback 不能自动 Clone, 需要特殊处理
impl Clone for Config {
    fn clone(&self) -> Self {
        Config {
            name: self.name.clone(),
            values: self.values.clone(),
            enabled: self.enabled,
            callback: None,  // 函数不能 clone, 设为 None
        }
    }
}

impl Default for Config {
    fn default() -> Self {
        Config {
            name: String::from("default"),
            values: vec![],
            enabled: true,
            callback: None,
        }
    }
}
```

---

### 练习 9 (综合): 事件系统

实现一个类型安全的事件系统:

```rust
use std::collections::HashMap;

trait Event: 'static {
    fn name() -> &'static str;
}

struct UserCreated { pub user_id: u64, pub username: String }
struct OrderPlaced { pub order_id: u64, pub amount: f64 }

impl Event for UserCreated {
    fn name() -> &'static str { "user.created" }
}

impl Event for OrderPlaced {
    fn name() -> &'static str { "order.placed" }
}

struct EventBus {
    handlers: HashMap<&'static str, Vec<Box<dyn Fn(&dyn std::any::Any)>>>,
}

impl EventBus {
    fn new() -> Self {
        EventBus { handlers: HashMap::new() }
    }
    
    fn subscribe<E: Event>(&mut self, handler: impl Fn(&E) + 'static) {
        let name = E::name();
        let boxed: Box<dyn Fn(&dyn std::any::Any)> = Box::new(move |any| {
            if let Some(event) = any.downcast_ref::<E>() {
                handler(event);
            }
        });
        self.handlers.entry(name).or_insert_with(Vec::new).push(boxed);
    }
    
    fn publish<E: Event + std::any::Any>(&self, event: E) {
        if let Some(handlers) = self.handlers.get(E::name()) {
            for handler in handlers {
                handler(&event);
            }
        }
    }
}

fn main() {
    let mut bus = EventBus::new();
    
    bus.subscribe::<UserCreated>(|e| {
        println!("New user: {} (id: {})", e.username, e.user_id);
    });
    
    bus.subscribe::<OrderPlaced>(|e| {
        println!("Order {} placed: ${:.2}", e.order_id, e.amount);
    });
    
    bus.publish(UserCreated { user_id: 1, username: "Alice".to_string() });
    bus.publish(OrderPlaced { order_id: 100, amount: 99.99 });
}
```

---

## 小结

| 概念 | 要点 |
|------|------|
| Trait | 显式定义行为契约,类似 Go interface 但更强大 |
| 静态分派 | 泛型+单态化,零运行时开销 |
| 动态分派 | dyn Trait+vtable,运行时多态 |
| 关联类型 | 一种实现,用 `type Item` |
| 泛型参数 | 多种实现,用 `<T>` |

### 下一步

- [ ] 完成本章所有练习题
- [ ] 阅读 `05-并发模型深度解析.md`
- [ ] 尝试为一个实际问题设计 Trait 层次结构

---

**Trait 是 Rust 类型系统的灵魂,掌握它就掌握了 Rust 设计哲学的精髓! 🦀**
