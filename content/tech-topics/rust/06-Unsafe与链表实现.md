# Unsafe 与链表实现

> **本章目标:** 深入理解 Unsafe Rust,掌握原始指针操作,完整实现多种链表
> 
> **学习时间:** 10-14 天 (本课程最难的章节)
> 
> **前置知识:** 完成 `05-并发模型深度解析.md`

---

## 为什么链表在 Rust 中困难?

```
在 C/C++/Go 中:
链表节点 → 持有下一个节点的指针
没有所有权概念, 直接共享裸指针

在 Rust 中:
所有权: 每个节点只能有一个所有者
借用规则: 节点间的相互引用很麻烦
双向链表: 每个节点需要被前后两个节点"拥有" → 需要 Rc/RefCell 或 unsafe
```

链表是学习 Unsafe Rust 的完美练习场。

---

## 1. Unsafe Rust 基础

### 五种 Unsafe 超能力

```rust
unsafe {
    // 1. 解引用裸指针
    let raw = &42 as *const i32;
    let val = *raw;

    // 2. 调用 unsafe 函数或方法
    let v = std::slice::from_raw_parts(raw, 1);

    // 3. 访问或修改可变静态变量
    static mut COUNTER: i32 = 0;
    COUNTER += 1;

    // 4. 实现 unsafe Trait
    // (见下文)

    // 5. 访问 Union 的字段
    union MyUnion { i: i32, f: f32 }
    let u = MyUnion { i: 42 };
    let _ = u.i;
}
```

### 裸指针

```rust
fn raw_pointer_basics() {
    let mut x: i32 = 42;
    
    // 创建裸指针 (安全, 不解引用)
    let const_ptr: *const i32 = &x;
    let mut_ptr: *mut i32 = &mut x;
    
    unsafe {
        // 解引用裸指针 (unsafe)
        println!("const: {}", *const_ptr);
        
        // 修改
        *mut_ptr = 100;
        println!("after mut: {}", x);
        
        // 指针算术
        let arr = [1i32, 2, 3, 4, 5];
        let ptr = arr.as_ptr();
        
        for i in 0..5 {
            println!("arr[{}] = {}", i, *ptr.add(i));
        }
    }
}
```

### 何时使用 Unsafe?

```rust
// 合理的 unsafe 使用场景:
// 1. FFI (调用 C 函数)
extern "C" {
    fn abs(x: i32) -> i32;
}

// 2. 实现底层数据结构
// (链表、自定义集合等)

// 3. 性能优化 (消除不必要的边界检查)
fn fast_sum(data: &[i32]) -> i32 {
    let mut sum = 0;
    let mut ptr = data.as_ptr();
    let end = unsafe { ptr.add(data.len()) };
    
    unsafe {
        while ptr < end {
            sum += *ptr;
            ptr = ptr.add(1);
        }
    }
    sum
}

// 4. 与硬件交互
// 5. std 库内部实现
```

### 未定义行为 (UB) 的类型

```rust
// 永远不要做这些:
unsafe fn undefined_behavior_examples() {
    // 1. 解引用空指针
    // let null: *const i32 = std::ptr::null();
    // let _ = *null;  // UB!
    
    // 2. 越界访问
    // let arr = [1, 2, 3];
    // let ptr = arr.as_ptr();
    // let _ = *ptr.add(10);  // UB!
    
    // 3. 无效的内存对齐
    // let bytes: [u8; 8] = [0; 8];
    // let ptr = bytes.as_ptr().add(1) as *const u64;
    // let _ = *ptr;  // 可能 UB (取决于平台)
    
    // 4. 数据竞争
    // 两个线程同时修改同一内存
    
    // 5. 违反引用规则 (同时有可变和不可变引用)
}
```

---

## 2. Level 1: 单向链表 (Safe Rust + Box)

### 基础实现

```rust
// 使用 Box 的单向链表 - 完全安全!
#[derive(Debug)]
pub enum List<T> {
    Cons(T, Box<List<T>>),
    Nil,
}

impl<T: std::fmt::Debug> List<T> {
    pub fn new() -> Self {
        List::Nil
    }
    
    pub fn prepend(self, value: T) -> Self {
        List::Cons(value, Box::new(self))
    }
    
    pub fn len(&self) -> usize {
        match self {
            List::Nil => 0,
            List::Cons(_, tail) => 1 + tail.len(),
        }
    }
    
    pub fn head(&self) -> Option<&T> {
        match self {
            List::Nil => None,
            List::Cons(head, _) => Some(head),
        }
    }
}

fn main() {
    let list = List::new()
        .prepend(3)
        .prepend(2)
        .prepend(1);
    
    println!("{:?}", list);
    println!("Length: {}", list.len());
    println!("Head: {:?}", list.head());
}
```

### 更完整的栈式链表

```rust
pub struct Stack<T> {
    head: Link<T>,
}

type Link<T> = Option<Box<Node<T>>>;

struct Node<T> {
    elem: T,
    next: Link<T>,
}

impl<T> Stack<T> {
    pub fn new() -> Self {
        Stack { head: None }
    }
    
    pub fn push(&mut self, elem: T) {
        let new_node = Box::new(Node {
            elem,
            next: self.head.take(),
        });
        self.head = Some(new_node);
    }
    
    pub fn pop(&mut self) -> Option<T> {
        self.head.take().map(|node| {
            self.head = node.next;
            node.elem
        })
    }
    
    pub fn peek(&self) -> Option<&T> {
        self.head.as_ref().map(|node| &node.elem)
    }
    
    pub fn peek_mut(&mut self) -> Option<&mut T> {
        self.head.as_mut().map(|node| &mut node.elem)
    }
    
    pub fn is_empty(&self) -> bool {
        self.head.is_none()
    }
}

// 实现迭代器
pub struct IntoIter<T>(Stack<T>);

impl<T> Stack<T> {
    pub fn into_iter(self) -> IntoIter<T> {
        IntoIter(self)
    }
}

impl<T> Iterator for IntoIter<T> {
    type Item = T;
    
    fn next(&mut self) -> Option<T> {
        self.0.pop()
    }
}

// Drop: 手动迭代防止栈溢出 (深度递归会爆栈)
impl<T> Drop for Stack<T> {
    fn drop(&mut self) {
        let mut cur = self.head.take();
        while let Some(mut node) = cur {
            cur = node.next.take();
            // node 在这里 drop, 但 next 已经 take 出来了
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_push_pop() {
        let mut s = Stack::new();
        s.push(1);
        s.push(2);
        s.push(3);
        
        assert_eq!(s.pop(), Some(3));
        assert_eq!(s.pop(), Some(2));
        assert_eq!(s.pop(), Some(1));
        assert_eq!(s.pop(), None);
    }
    
    #[test]
    fn test_peek() {
        let mut s = Stack::new();
        s.push(42);
        
        assert_eq!(s.peek(), Some(&42));
        *s.peek_mut().unwrap() = 100;
        assert_eq!(s.peek(), Some(&100));
    }
    
    #[test]
    fn test_into_iter() {
        let mut s = Stack::new();
        s.push(1);
        s.push(2);
        s.push(3);
        
        let v: Vec<i32> = s.into_iter().collect();
        assert_eq!(v, vec![3, 2, 1]);
    }
}
```

---

## 3. Level 2: 持久化函数式链表 (Rc + 共享)

```rust
use std::rc::Rc;

pub struct FList<T> {
    head: FLink<T>,
}

type FLink<T> = Option<Rc<FNode<T>>>;

struct FNode<T> {
    elem: T,
    next: FLink<T>,
}

impl<T> FList<T> {
    pub fn new() -> Self {
        FList { head: None }
    }
    
    // 共享尾部, O(1) 复制
    pub fn prepend(&self, elem: T) -> FList<T> {
        FList {
            head: Some(Rc::new(FNode {
                elem,
                next: self.head.clone(),  // 增加引用计数, 不复制数据
            }))
        }
    }
    
    pub fn tail(&self) -> FList<T> {
        FList {
            head: self.head.as_ref()
                .and_then(|node| node.next.clone())
        }
    }
    
    pub fn head(&self) -> Option<&T> {
        self.head.as_ref().map(|node| &node.elem)
    }
}

impl<T> Drop for FList<T> {
    fn drop(&mut self) {
        let mut head = self.head.take();
        loop {
            let node = match head {
                None => break,
                Some(rc) => {
                    match Rc::try_unwrap(rc) {
                        Err(_) => break,  // 还有其他引用, 停止
                        Ok(node) => node,
                    }
                }
            };
            head = node.next;
        }
    }
}
```

---

## 4. Level 3: 双向链表 (Rc + RefCell)

```rust
use std::rc::Rc;
use std::cell::RefCell;

type DLink<T> = Option<Rc<RefCell<DNode<T>>>>;

struct DNode<T> {
    value: T,
    prev: DLink<T>,
    next: DLink<T>,
}

pub struct DoublyLinkedList<T> {
    head: DLink<T>,
    tail: DLink<T>,
    len: usize,
}

impl<T> DoublyLinkedList<T> {
    pub fn new() -> Self {
        DoublyLinkedList { head: None, tail: None, len: 0 }
    }
    
    pub fn push_front(&mut self, value: T) {
        let new_node = Rc::new(RefCell::new(DNode {
            value,
            prev: None,
            next: self.head.take(),
        }));
        
        match new_node.borrow().next.clone() {
            None => {
                self.tail = Some(new_node.clone());
            }
            Some(ref old_head) => {
                old_head.borrow_mut().prev = Some(new_node.clone());
            }
        }
        
        self.head = Some(new_node);
        self.len += 1;
    }
    
    pub fn push_back(&mut self, value: T) {
        let new_node = Rc::new(RefCell::new(DNode {
            value,
            prev: self.tail.clone(),
            next: None,
        }));
        
        match self.tail.take() {
            None => {
                self.head = Some(new_node.clone());
            }
            Some(old_tail) => {
                old_tail.borrow_mut().next = Some(new_node.clone());
            }
        }
        
        self.tail = Some(new_node);
        self.len += 1;
    }
    
    pub fn pop_front(&mut self) -> Option<T> {
        self.head.take().map(|old_head| {
            match old_head.borrow_mut().next.take() {
                None => {
                    self.tail.take();
                }
                Some(new_head) => {
                    new_head.borrow_mut().prev.take();
                    self.head = Some(new_head);
                }
            }
            self.len -= 1;
            Rc::try_unwrap(old_head).ok().unwrap().into_inner().value
        })
    }
    
    pub fn pop_back(&mut self) -> Option<T> {
        self.tail.take().map(|old_tail| {
            match old_tail.borrow_mut().prev.take() {
                None => {
                    self.head.take();
                }
                Some(new_tail) => {
                    new_tail.borrow_mut().next.take();
                    self.tail = Some(new_tail);
                }
            }
            self.len -= 1;
            Rc::try_unwrap(old_tail).ok().unwrap().into_inner().value
        })
    }
    
    pub fn len(&self) -> usize {
        self.len
    }
    
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    
    pub fn peek_front(&self) -> Option<impl std::ops::Deref<Target = T> + '_> {
        self.head.as_ref().map(|node| {
            std::cell::Ref::map(node.borrow(), |n| &n.value)
        })
    }
}

impl<T> Drop for DoublyLinkedList<T> {
    fn drop(&mut self) {
        // 逐一 pop 以正确释放内存
        while self.pop_front().is_some() {}
    }
}
```

---

## 5. Level 4: 高性能双向链表 (Unsafe)

使用裸指针实现,零运行时开销:

```rust
use std::ptr::NonNull;
use std::marker::PhantomData;

struct Node<T> {
    elem: T,
    next: Option<NonNull<Node<T>>>,
    prev: Option<NonNull<Node<T>>>,
}

pub struct LinkedList<T> {
    front: Option<NonNull<Node<T>>>,
    back: Option<NonNull<Node<T>>>,
    len: usize,
    // 告诉编译器我们拥有 T 类型的数据
    _phantom: PhantomData<T>,
}

unsafe impl<T: Send> Send for LinkedList<T> {}
unsafe impl<T: Sync> Sync for LinkedList<T> {}

impl<T> LinkedList<T> {
    pub fn new() -> Self {
        LinkedList {
            front: None,
            back: None,
            len: 0,
            _phantom: PhantomData,
        }
    }
    
    pub fn push_front(&mut self, elem: T) {
        unsafe {
            // 在堆上分配节点
            let new = NonNull::new_unchecked(Box::into_raw(Box::new(Node {
                elem,
                next: self.front,
                prev: None,
            })));
            
            if let Some(old_front) = self.front {
                (*old_front.as_ptr()).prev = Some(new);
            } else {
                self.back = Some(new);
            }
            
            self.front = Some(new);
            self.len += 1;
        }
    }
    
    pub fn push_back(&mut self, elem: T) {
        unsafe {
            let new = NonNull::new_unchecked(Box::into_raw(Box::new(Node {
                elem,
                next: None,
                prev: self.back,
            })));
            
            if let Some(old_back) = self.back {
                (*old_back.as_ptr()).next = Some(new);
            } else {
                self.front = Some(new);
            }
            
            self.back = Some(new);
            self.len += 1;
        }
    }
    
    pub fn pop_front(&mut self) -> Option<T> {
        self.front.map(|node| unsafe {
            // 重新装箱, 确保内存正确释放
            let boxed_node = Box::from_raw(node.as_ptr());
            let result = boxed_node.elem;
            
            self.front = boxed_node.next;
            
            if let Some(new_front) = self.front {
                (*new_front.as_ptr()).prev = None;
            } else {
                self.back = None;
            }
            
            self.len -= 1;
            result
        })
    }
    
    pub fn pop_back(&mut self) -> Option<T> {
        self.back.map(|node| unsafe {
            let boxed_node = Box::from_raw(node.as_ptr());
            let result = boxed_node.elem;
            
            self.back = boxed_node.prev;
            
            if let Some(new_back) = self.back {
                (*new_back.as_ptr()).next = None;
            } else {
                self.front = None;
            }
            
            self.len -= 1;
            result
        })
    }
    
    pub fn front(&self) -> Option<&T> {
        unsafe {
            self.front.map(|node| &(*node.as_ptr()).elem)
        }
    }
    
    pub fn back(&self) -> Option<&T> {
        unsafe {
            self.back.map(|node| &(*node.as_ptr()).elem)
        }
    }
    
    pub fn len(&self) -> usize {
        self.len
    }
    
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    
    // 将节点移到最前面 (LRU 用)
    pub fn move_to_front(&mut self, node: NonNull<Node<T>>) {
        if self.front == Some(node) {
            return;  // 已经是头节点
        }
        
        unsafe {
            let node_ref = &*node.as_ptr();
            
            // 从当前位置断开
            if let Some(prev) = node_ref.prev {
                (*prev.as_ptr()).next = node_ref.next;
            }
            if let Some(next) = node_ref.next {
                (*next.as_ptr()).prev = node_ref.prev;
            } else {
                // 节点是尾节点
                self.back = node_ref.prev;
            }
            
            // 插入到头部
            (*node.as_ptr()).prev = None;
            (*node.as_ptr()).next = self.front;
            
            if let Some(old_front) = self.front {
                (*old_front.as_ptr()).prev = Some(node);
            }
            
            self.front = Some(node);
        }
    }
}

impl<T> Drop for LinkedList<T> {
    fn drop(&mut self) {
        while self.pop_front().is_some() {}
    }
}

// 迭代器
pub struct Iter<'a, T> {
    front: Option<NonNull<Node<T>>>,
    back: Option<NonNull<Node<T>>>,
    len: usize,
    _phantom: PhantomData<&'a T>,
}

impl<T> LinkedList<T> {
    pub fn iter(&self) -> Iter<'_, T> {
        Iter {
            front: self.front,
            back: self.back,
            len: self.len,
            _phantom: PhantomData,
        }
    }
}

impl<'a, T> Iterator for Iter<'a, T> {
    type Item = &'a T;
    
    fn next(&mut self) -> Option<&'a T> {
        if self.len == 0 {
            return None;
        }
        self.front.map(|node| unsafe {
            let node_ref = &*node.as_ptr();
            self.front = node_ref.next;
            self.len -= 1;
            &node_ref.elem
        })
    }
    
    fn size_hint(&self) -> (usize, Option<usize>) {
        (self.len, Some(self.len))
    }
}

impl<'a, T> DoubleEndedIterator for Iter<'a, T> {
    fn next_back(&mut self) -> Option<&'a T> {
        if self.len == 0 {
            return None;
        }
        self.back.map(|node| unsafe {
            let node_ref = &*node.as_ptr();
            self.back = node_ref.prev;
            self.len -= 1;
            &node_ref.elem
        })
    }
}
```

---

## 6. 实战: LRU Cache

LRU (Least Recently Used) 缓存是链表 + HashMap 的经典组合:

```rust
use std::collections::HashMap;
use std::ptr::NonNull;

struct LruNode<K, V> {
    key: K,
    value: V,
    prev: Option<NonNull<LruNode<K, V>>>,
    next: Option<NonNull<LruNode<K, V>>>,
}

pub struct LruCache<K: std::hash::Hash + Eq + Clone, V> {
    capacity: usize,
    map: HashMap<K, NonNull<LruNode<K, V>>>,
    head: Option<NonNull<LruNode<K, V>>>,  // 最近使用
    tail: Option<NonNull<LruNode<K, V>>>,  // 最久未使用
}

unsafe impl<K: Send + std::hash::Hash + Eq + Clone, V: Send> Send for LruCache<K, V> {}

impl<K: std::hash::Hash + Eq + Clone, V> LruCache<K, V> {
    pub fn new(capacity: usize) -> Self {
        assert!(capacity > 0);
        LruCache {
            capacity,
            map: HashMap::new(),
            head: None,
            tail: None,
        }
    }
    
    pub fn get(&mut self, key: &K) -> Option<&V> {
        if let Some(&node_ptr) = self.map.get(key) {
            self.move_to_front(node_ptr);
            Some(unsafe { &(*node_ptr.as_ptr()).value })
        } else {
            None
        }
    }
    
    pub fn put(&mut self, key: K, value: V) {
        if let Some(&node_ptr) = self.map.get(&key) {
            // 更新已有节点
            unsafe { (*node_ptr.as_ptr()).value = value; }
            self.move_to_front(node_ptr);
            return;
        }
        
        // 创建新节点
        let new_node = unsafe {
            NonNull::new_unchecked(Box::into_raw(Box::new(LruNode {
                key: key.clone(),
                value,
                prev: None,
                next: self.head,
            })))
        };
        
        // 更新 head
        if let Some(old_head) = self.head {
            unsafe { (*old_head.as_ptr()).prev = Some(new_node); }
        } else {
            self.tail = Some(new_node);
        }
        
        self.head = Some(new_node);
        self.map.insert(key, new_node);
        
        // 如果超出容量, 删除最久未使用的
        if self.map.len() > self.capacity {
            if let Some(old_tail) = self.tail {
                let key_to_remove = unsafe { (*old_tail.as_ptr()).key.clone() };
                self.remove_node(old_tail);
                self.map.remove(&key_to_remove);
                unsafe { drop(Box::from_raw(old_tail.as_ptr())); }
            }
        }
    }
    
    fn move_to_front(&mut self, node: NonNull<LruNode<K, V>>) {
        if self.head == Some(node) {
            return;
        }
        
        self.detach(node);
        
        unsafe {
            (*node.as_ptr()).prev = None;
            (*node.as_ptr()).next = self.head;
            
            if let Some(old_head) = self.head {
                (*old_head.as_ptr()).prev = Some(node);
            } else {
                self.tail = Some(node);
            }
            
            self.head = Some(node);
        }
    }
    
    fn detach(&mut self, node: NonNull<LruNode<K, V>>) {
        unsafe {
            let node_ref = &*node.as_ptr();
            
            if let Some(prev) = node_ref.prev {
                (*prev.as_ptr()).next = node_ref.next;
            } else {
                self.head = node_ref.next;
            }
            
            if let Some(next) = node_ref.next {
                (*next.as_ptr()).prev = node_ref.prev;
            } else {
                self.tail = node_ref.prev;
            }
        }
    }
    
    fn remove_node(&mut self, node: NonNull<LruNode<K, V>>) {
        self.detach(node);
        unsafe {
            (*node.as_ptr()).prev = None;
            (*node.as_ptr()).next = None;
        }
    }
    
    pub fn len(&self) -> usize {
        self.map.len()
    }
    
    pub fn capacity(&self) -> usize {
        self.capacity
    }
}

impl<K: std::hash::Hash + Eq + Clone, V> Drop for LruCache<K, V> {
    fn drop(&mut self) {
        let mut current = self.head;
        while let Some(node) = current {
            let next = unsafe { (*node.as_ptr()).next };
            unsafe { drop(Box::from_raw(node.as_ptr())); }
            current = next;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_lru_basic() {
        let mut cache = LruCache::new(3);
        
        cache.put("a", 1);
        cache.put("b", 2);
        cache.put("c", 3);
        
        assert_eq!(cache.get(&"a"), Some(&1));  // a 移到最前
        
        cache.put("d", 4);  // b 被淘汰 (最久未使用)
        
        assert_eq!(cache.get(&"b"), None);  // b 已被淘汰
        assert_eq!(cache.get(&"c"), Some(&3));
        assert_eq!(cache.len(), 3);
    }
    
    #[test]
    fn test_lru_capacity_1() {
        let mut cache = LruCache::new(1);
        
        cache.put("key1", 1);
        cache.put("key2", 2);
        
        assert_eq!(cache.get(&"key1"), None);
        assert_eq!(cache.get(&"key2"), Some(&2));
    }
    
    #[test]
    fn test_lru_update() {
        let mut cache = LruCache::new(2);
        
        cache.put("a", 1);
        cache.put("b", 2);
        cache.put("a", 10);  // 更新 a
        cache.put("c", 3);   // b 被淘汰
        
        assert_eq!(cache.get(&"a"), Some(&10));
        assert_eq!(cache.get(&"b"), None);
        assert_eq!(cache.get(&"c"), Some(&3));
    }
}
```

---

## 练习题

### 练习 1 (基础): 裸指针操作

实现一个使用裸指针的数组求和:

```rust
fn sum_raw(data: &[i32]) -> i64 {
    if data.is_empty() { return 0; }
    
    let mut sum: i64 = 0;
    let mut ptr = data.as_ptr();
    let end = unsafe { ptr.add(data.len()) };
    
    unsafe {
        while ptr < end {
            sum += *ptr as i64;
            ptr = ptr.add(1);
        }
    }
    
    sum
}

fn main() {
    let data = vec![1i32, 2, 3, 4, 5, 6, 7, 8, 9, 10];
    assert_eq!(sum_raw(&data), 55);
    println!("Sum: {}", sum_raw(&data));
}
```

---

### 练习 2 (基础): 实现 Box

实现一个简化版的 `Box<T>`:

```rust
pub struct MyBox<T> {
    ptr: std::ptr::NonNull<T>,
}

impl<T> MyBox<T> {
    pub fn new(value: T) -> Self {
        let ptr = Box::into_raw(Box::new(value));
        MyBox {
            ptr: unsafe { std::ptr::NonNull::new_unchecked(ptr) }
        }
    }
}

impl<T> std::ops::Deref for MyBox<T> {
    type Target = T;
    fn deref(&self) -> &T {
        unsafe { self.ptr.as_ref() }
    }
}

impl<T> std::ops::DerefMut for MyBox<T> {
    fn deref_mut(&mut self) -> &mut T {
        unsafe { self.ptr.as_mut() }
    }
}

impl<T> Drop for MyBox<T> {
    fn drop(&mut self) {
        unsafe { drop(Box::from_raw(self.ptr.as_ptr())); }
    }
}

fn main() {
    let mut b = MyBox::new(42);
    *b = 100;
    println!("{}", *b);
}
```

---

### 练习 3 (中等): 带迭代器的单向链表

为 Level 1 的单向链表添加完整的迭代器支持:

```rust
// 实现 Iter (不可变迭代)、IterMut (可变迭代)、IntoIter (消费迭代)
// 所有迭代器都实现 DoubleEndedIterator
```

参考答案在补充练习文件中。

---

### 练习 4 (中等): 检测链表是否有环

```rust
pub fn has_cycle<T>(head: &Option<Box<ListNode<T>>>) -> bool {
    // 使用快慢指针 (Floyd 算法)
    // 注意: Safe Rust 中需要使用引用
    
    let mut slow = head.as_deref();
    let mut fast = head.as_deref();
    
    loop {
        match (slow, fast) {
            (Some(s), Some(f)) => {
                slow = s.next.as_deref();
                fast = f.next.as_deref()
                    .and_then(|n| n.next.as_deref());
                
                if std::ptr::eq(slow?, fast?) {
                    return true;
                }
            }
            _ => return false,
        }
    }
}
```

---

### 练习 5 (挑战): 实现跳表 (Skip List)

```rust
use std::ptr::NonNull;

const MAX_LEVEL: usize = 16;

struct SkipNode<K, V> {
    key: K,
    value: V,
    forward: Vec<Option<NonNull<SkipNode<K, V>>>>,
}

pub struct SkipList<K: Ord, V> {
    head: Box<SkipNode<K, V>>,
    len: usize,
    level: usize,
}

impl<K: Ord + Default, V: Default> SkipList<K, V> {
    pub fn new() -> Self {
        SkipList {
            head: Box::new(SkipNode {
                key: K::default(),
                value: V::default(),
                forward: vec![None; MAX_LEVEL],
            }),
            len: 0,
            level: 0,
        }
    }
    
    fn random_level() -> usize {
        let mut level = 1;
        while level < MAX_LEVEL && rand::random::<bool>() {
            level += 1;
        }
        level
    }
    
    pub fn insert(&mut self, key: K, value: V) {
        // ... 实现插入
    }
    
    pub fn get(&self, key: &K) -> Option<&V> {
        // ... 实现查找
        None
    }
}
```

---

### 练习 6 (挑战): 验证 unsafe 代码安全性

分析以下 unsafe 代码,找出潜在的 UB:

```rust
// 分析这段代码是否安全
fn potentially_unsafe(data: &[i32], idx: usize) -> i32 {
    unsafe {
        // 问题1: 可能越界
        *data.as_ptr().add(idx)
    }
}

// 如何添加安全检查?
fn safe_version(data: &[i32], idx: usize) -> Option<i32> {
    if idx < data.len() {
        Some(unsafe { *data.as_ptr().add(idx) })
    } else {
        None
    }
}

// 更好的方式
fn idiomatic(data: &[i32], idx: usize) -> Option<i32> {
    data.get(idx).copied()  // 完全安全, 无需 unsafe
}
```

---

### 练习 7 (挑战): 实现 Vec 的部分功能

```rust
use std::alloc::{self, Layout};
use std::ptr;

pub struct MyVec<T> {
    ptr: std::ptr::NonNull<T>,
    len: usize,
    cap: usize,
}

unsafe impl<T: Send> Send for MyVec<T> {}
unsafe impl<T: Sync> Sync for MyVec<T> {}

impl<T> MyVec<T> {
    pub fn new() -> Self {
        MyVec {
            ptr: std::ptr::NonNull::dangling(),
            len: 0,
            cap: 0,
        }
    }
    
    pub fn push(&mut self, elem: T) {
        if self.len == self.cap {
            self.grow();
        }
        
        unsafe {
            ptr::write(self.ptr.as_ptr().add(self.len), elem);
        }
        
        self.len += 1;
    }
    
    pub fn pop(&mut self) -> Option<T> {
        if self.len == 0 {
            None
        } else {
            self.len -= 1;
            Some(unsafe { ptr::read(self.ptr.as_ptr().add(self.len)) })
        }
    }
    
    fn grow(&mut self) {
        let new_cap = if self.cap == 0 { 1 } else { self.cap * 2 };
        let new_layout = Layout::array::<T>(new_cap).unwrap();
        
        let new_ptr = if self.cap == 0 {
            unsafe { alloc::alloc(new_layout) }
        } else {
            let old_layout = Layout::array::<T>(self.cap).unwrap();
            unsafe { alloc::realloc(self.ptr.as_ptr() as *mut u8, old_layout, new_layout.size()) }
        };
        
        self.ptr = std::ptr::NonNull::new(new_ptr as *mut T)
            .expect("Allocation failed");
        self.cap = new_cap;
    }
    
    pub fn len(&self) -> usize { self.len }
    pub fn capacity(&self) -> usize { self.cap }
}

impl<T> Drop for MyVec<T> {
    fn drop(&mut self) {
        if self.cap != 0 {
            while self.pop().is_some() {}
            let layout = Layout::array::<T>(self.cap).unwrap();
            unsafe { alloc::dealloc(self.ptr.as_ptr() as *mut u8, layout); }
        }
    }
}

impl<T> std::ops::Deref for MyVec<T> {
    type Target = [T];
    fn deref(&self) -> &[T] {
        unsafe { std::slice::from_raw_parts(self.ptr.as_ptr(), self.len) }
    }
}

fn main() {
    let mut v: MyVec<i32> = MyVec::new();
    v.push(1);
    v.push(2);
    v.push(3);
    
    println!("len={}, cap={}", v.len(), v.capacity());
    println!("{:?}", &*v);
    
    assert_eq!(v.pop(), Some(3));
}
```

---

### 练习 8 (综合): LRU Cache 压力测试

为 LRU Cache 编写压力测试和基准测试:

```rust
#[cfg(test)]
mod stress_tests {
    use super::*;
    
    #[test]
    fn stress_test() {
        let mut cache = LruCache::new(100);
        
        // 插入 1000 个元素
        for i in 0..1000 {
            cache.put(i, i * i);
        }
        
        // 容量限制
        assert_eq!(cache.len(), 100);
        
        // 最近插入的应该存在
        for i in 900..1000 {
            assert!(cache.get(&i).is_some());
        }
        
        // 最早的已被淘汰
        for i in 0..900 {
            assert!(cache.get(&i).is_none());
        }
    }
    
    #[test]
    fn test_access_pattern() {
        let mut cache = LruCache::new(3);
        cache.put(1, "a");
        cache.put(2, "b");
        cache.put(3, "c");
        
        // 访问 1, 使其最近使用
        cache.get(&1);
        
        // 插入 4, 应该淘汰 2 (最久未使用的是 2, 因为 3 是最近插入, 1 是最近访问)
        cache.put(4, "d");
        
        assert!(cache.get(&1).is_some(), "1 should still exist");
        assert!(cache.get(&2).is_none(), "2 should be evicted");
        assert!(cache.get(&3).is_some(), "3 should still exist");
        assert!(cache.get(&4).is_some(), "4 should exist");
    }
}
```

---

## 标准库源码导读

### `std::collections::LinkedList`

Rust 标准库中的 `LinkedList` 使用了与我们类似的 unsafe 实现:

```rust
// 简化的标准库 LinkedList 结构 (实际更复杂)
pub struct LinkedList<T> {
    head: Option<NonNull<Node<T>>>,
    tail: Option<NonNull<Node<T>>>,
    len: usize,
    alloc: A,  // 分配器
    marker: PhantomData<Box<Node<T>>>,
}
```

**阅读建议:**
1. 寻找 `Cursor` 实现,理解链表位置的表示
2. 查看 `DrainFilter` 实现,理解链表过滤的复杂性
3. 对比我们的实现与标准库的差异

---

## 小结

| 级别 | 实现 | 特点 |
|------|------|------|
| Level 1: Box | 枚举链表 | 最简单,完全安全 |
| Level 2: Rc | 持久化链表 | 不可变共享 |
| Level 3: Rc+RefCell | 双向链表 | 安全但有运行时开销 |
| Level 4: unsafe | 高性能双向链表 | 零开销,LRU 实现 |

### 下一步

- [ ] 完成本章所有练习题
- [ ] 实现完整的 LRU Cache 并通过所有测试
- [ ] 阅读 `07-智能指针与内存管理.md`
- [ ] 尝试阅读标准库的 `LinkedList` 源码

---

**征服了链表, 你就证明了自己驾驭 unsafe Rust 的能力! 🦀**
