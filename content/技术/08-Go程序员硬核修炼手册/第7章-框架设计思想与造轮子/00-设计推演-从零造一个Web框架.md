# 00 · 设计推演：从零造一个 Web 框架

> *"Web 框架的每个组件——epoll、路由树、中间件——都是为了干掉上一版里那几行重复代码。"*

---

## 开场：一个只会 echo 的服务器

> **老陈**：需求：写个 TCP 服务器，客户端发什么就回什么。
>
> **小林**：（写）
> ```go
> listener, _ := net.Listen("tcp", ":8080")
> for {
>     conn, _ := listener.Accept()
>     go func(c net.Conn) {
>         defer c.Close()
>         buf := make([]byte, 1024)
>         for {
>             n, err := c.Read(buf)   // 阻塞
>             if err != nil { return }
>             c.Write(buf[:n])
>         }
>     }(conn)
> }
> ```
>
> **老陈**：**很好，这能工作。现在一万个并发连接。**
>
> **小林**：……一万个 goroutine？
>
> **老陈**：**对，Go 里没问题。但你要知道为什么没问题——以及为什么在别的语言里这会死。**

---

## 第一部分：I/O 模型的演进

### v0：每连接一线程（阻塞 I/O）

这是 C/Java 早期的标准写法：

```c
while (1) {
    int clientfd = accept(listenfd, ...);
    pthread_create(&tid, NULL, handle_client, &clientfd);   // 一个连接一个线程
}

void* handle_client(void* arg) {
    char buf[1024];
    while (1) {
        read(fd, buf, sizeof(buf));   // ★ 阻塞在这里
        write(fd, buf, n);
    }
}
```

**失败**：

| # | 问题 | 数据 |
|:---|:---|:---|
| 1 | **内存** | 1 万线程 × 8MB 栈 = 80GB |
| 2 | **上下文切换** | 1 万个线程抢 8 个核，大部分时间在切换 |
| 3 | **调度开销** | 内核调度器 O(n) 复杂度 |

**这就是著名的 C10K 问题**（1999 年提出）。

### v1：非阻塞 + 忙轮询

**思路**：不阻塞，没数据就立即返回，循环问所有连接。

```c
fcntl(fd, F_SETFL, O_NONBLOCK);

while (1) {
    for (int i = 0; i < num_fds; i++) {
        int n = read(fds[i], buf, sizeof(buf));   // 立即返回
        if (n > 0) handle(fds[i], buf, n);
    }
}
```

**失败**：

```
CPU 100%（空转）
1 万连接 × 每秒轮询 1000 次 = 1000 万次系统调用/秒
★ 绝大部分调用是白费的（没数据）
```

### v2：select / poll（I/O 多路复用）

**思路**：一次系统调用问内核"哪些 fd 有数据了"。

```c
fd_set readfds;
FD_ZERO(&readfds);
for (int i = 0; i < num_fds; i++) FD_SET(fds[i], &readfds);

int ready = select(max_fd + 1, &readfds, NULL, NULL, NULL);

// 检查哪些就绪
for (int i = 0; i < num_fds; i++) {
    if (FD_ISSET(fds[i], &readfds)) { /* 处理 */ }
}
```

**改进**：不再空转，没数据就睡觉。

**失败**：

| # | 问题 | 说明 |
|:---|:---|:---|
| 1 | **fd 数量限制** | select 默认 1024 |
| 2 | ★ **每次都要拷贝整个 fd 集合** | O(n)，1 万个 fd 每次拷贝 1 万×8 字节 |
| 3 | ★ **返回后还要遍历所有 fd** | O(n)，不知道哪些就绪 |

**poll 改进了问题 1（链表，无限制），但 2、3 依然存在。**

### v3：epoll

**核心改动**：把"每次问一遍"改成"内核帮你记着，有事通知你"。

```c
int epfd = epoll_create1(0);

// ★ 一次性注册，之后内核自己维护
struct epoll_event ev = {.events = EPOLLIN, .data.fd = clientfd};
epoll_ctl(epfd, EPOLL_CTL_ADD, clientfd, &ev);

while (1) {
    // ★ 只返回就绪的，O(就绪数) 而不是 O(总数)
    int n = epoll_wait(epfd, events, MAX_EVENTS, -1);
    for (int i = 0; i < n; i++) {
        handle(events[i].data.fd);
    }
}
```

**三个关键设计**：

```
① 红黑树存"我关心的 fd"
   → epoll_ctl 增量维护，不用每次传全部

② 就绪链表存"有事件的 fd"
   → epoll_wait 直接取，不用遍历

③ 回调机制
   → 数据到达时，内核的中断处理程序把 fd 加入就绪链表
   → ★ 事件驱动，不是轮询
```

**性能对比（1 万连接，100 个活跃）**：

| | 每次调用的开销 |
|:---|:---|
| select/poll | O(10000) 拷贝 + O(10000) 遍历 |
| **epoll** | **O(1) + O(100)** |

> **老陈**：**注意 epoll 的优势前提：大量连接，少量活跃。**
>
> **如果 1 万个连接全活跃，epoll 就没优势了（就绪链表也是 1 万个）。**
>
> **而互联网应用的典型模式恰好是"大量空闲长连接 + 少量活跃"——所以 epoll 才这么重要。**
>
> **这是"设计针对特定负载模式"的又一个例子。**

### ★ v4：Go 的做法——goroutine + netpoller

**epoll 解决了 I/O 效率，但引入了一个新问题：编程模型变复杂了。**

```c
// epoll 的写法：状态机
void handle_client(int fd) {
    // 读请求头 → 状态变成 READING_HEADER
    // 数据没到 → 返回，等下次事件
    // 数据到了 → 解析 → 状态变成 PARSING
    // ...
    // ★ 一个请求的处理被拆成多个回调，状态要自己维护
}
```

这就是**回调地狱**。Node.js 早期的问题，也是为什么有 Promise / async-await。

**★ Go 的解法：让你写阻塞式代码，runtime 在背后用 epoll。**

```go
// 你写的（看起来是阻塞的）
n, err := conn.Read(buf)

// 实际发生的：
//   ① 尝试非阻塞 read
//   ② 返回 EAGAIN（没数据）
//   ③ ★ 把这个 fd 注册到 netpoller，goroutine 挂起（gopark）
//   ④ 调度器去跑别的 goroutine，OS 线程不阻塞
//   ⑤ 数据到达，epoll 事件触发，goroutine 被唤醒（goready）
//   ⑥ 重新执行 read，这次有数据
```

**这是 Go 最重要的设计优势之一：**

```
用同步的写法，获得异步的性能。

对比:
  C + epoll:     你要自己维护状态机
  Node.js:       单线程 + 回调（不能写 CPU 密集代码）
  Java BIO:      每连接一线程（C10K 问题）
  Java NIO:      类似 epoll，复杂
  ★ Go:          同步写法 + runtime 自动异步化
```

> **老陈**：**Go 把复杂度从"用户代码"转移到了"runtime"。**
>
> **代价是 runtime 复杂（几万行）。收益是用户代码可以很朴素。**
>
> **这是第 8 章讲的"复杂度分布"的一个具体体现：Go 一贯选择"复杂度在运行时，简单留给用户"。**

---

## 第二部分：路由的演进

现在能处理连接了。下一个问题：**怎么把 URL 映射到处理函数？**

### v0：if-else

```go
func handle(req *Request) *Response {
	if req.Path == "/" {
		return home(req)
	} else if req.Path == "/users" {
		return listUsers(req)
	} else if req.Path == "/about" {
		return about(req)
	}
	// ...
	return notFound()
}
```

**能工作**（路由少的时候）。

**失败**：

```
100 条路由 → 平均 50 次字符串比较
每次都是完整的字符串比较（几十到几百字节）
★ O(n)，且常数不小
```

### v1：map

```go
routes := map[string]Handler{
	"/":        home,
	"/users":   listUsers,
	"/about":   about,
}

func handle(req *Request) *Response {
	if h, ok := routes[req.Path]; ok {
		return h(req)
	}
	return notFound()
}
```

**改进**：O(1)。

**失败**：

| # | 问题 | 例子 |
|:---|:---|:---|
| 1 | ★ **不支持路径参数** | `/users/123` —— id 是变的，map 装不下 |
| 2 | 不支持前缀匹配 | `/static/*` |
| 3 | 无法找"最长匹配" | `/a/b/c` 该匹配 `/a/b/c` 还是 `/a/*`？ |

### v2：正则列表

```go
type Route struct {
	pattern *regexp.Regexp
	handler Handler
}

var routes = []Route{
	{regexp.MustCompile(`^/$`), home},
	{regexp.MustCompile(`^/users$`), listUsers},
	{regexp.MustCompile(`^/users/(\d+)$`), getUser},   // ★ 支持参数
}

func handle(req *Request) *Response {
	for _, r := range routes {
		if m := r.pattern.FindStringSubmatch(req.Path); m != nil {
			return r.handler(req, m[1:])
		}
	}
	return notFound()
}
```

**改进**：支持参数了。

**失败**：

```
★ O(n) × 正则匹配开销
  100 条路由，每条都要试一次正则
  正则匹配本身是 O(路径长度) 且有回溯风险

实测: 100 条路由，每次匹配约几微秒
     QPS 10 万 → 光路由匹配就吃掉不少 CPU
```

### v3：Radix Tree（压缩前缀树）

**思路**：把路由组织成树，按路径前缀查找，O(路径长度)。

```
路由: /user, /users, /user/:id, /user/:id/posts, /static/*filepath

普通 Trie（每字符一节点）:
    root → / → u → s → e → r → (end) → s → (end)
                              → / → : → i → d → (end)
    ★ 节点多、树深

Radix Tree（压缩无分叉路径）:
    root
      │
    "/user"              ← 压缩成一个节点
      │
   ┌──┴──┐
 (end)  "s"              ← 继续分叉
   │      │
 /user  (end)
          │
        "/"
          │
        ":id"
          │
       ┌──┴───┐
     (end)  "/posts"
              │
            (end)

★ 节点数从几十降到十几个
★ 查找是 O(路径长度)，与路由数量无关
```

**查找 `/user/123/posts`：**

```
① 匹配 "/user"        → 剩余 "/123/posts"
② 找子节点:
   · 静态匹配 "s"?     → "/123/posts" 不以 "s" 开头，跳过
   · 参数节点 ":id"?   → 匹配！提取 id="123"，剩余 "/posts"
③ 在 :id 的子节点找 "/posts" → 匹配
④ 找到 handler
```

**★ 关键：查找复杂度与路由总数无关。**

```
map:        O(1) 但不支持参数
正则列表:   O(n × 路径长度)
Radix Tree: O(路径长度) 且支持参数  ★
```

> **老陈**：**Radix Tree 是"用空间换时间"和"用结构换灵活性"的结合。**
>
> **它的设计精髓是"压缩"——把没有分叉的路径合成一个节点。**
>
> **这个"压缩"思想你之前见过：**
> - 第 1 章的多级页表（稀疏树）
> - 第 4 章的 SSTable（有序 + 稀疏索引）
>
> **都是：当数据有局部性/结构性时，压缩掉冗余部分。**

---

## 第三部分：中间件的演进

路由解决了。下一个问题：**每个 handler 都要做日志、鉴权、错误处理。**

### v0：每个 handler 重复写

```go
func createOrder(req *Request) *Response {
	// 1. 鉴权
	user, err := authenticate(req)
	if err != nil { return unauthorized() }

	// 2. 日志
	log.Infof("createOrder: %+v", req)

	// 3. 计时
	start := time.Now()
	defer func() { metrics.Observe("create_order", time.Since(start)) }()

	// 4. 错误恢复
	defer func() {
		if r := recover(); r != nil { /* ... */ }
	}()

	// ★★ 真正的业务逻辑只有几行
	return doCreateOrder(req, user)
}
```

**失败**：

```
每加一个新接口，就要复制粘贴这 30 行样板代码
★ 违反 DRY，改一处要改 N 处
```

### v1：提取成函数

```go
func createOrder(req *Request) *Response {
	user, err := authenticate(req)      // 还是显式调用
	if err != nil { return unauthorized() }

	logRequest(req)                     // 还是显式调用
	defer observe("create_order")       // 还是显式调用

	return doCreateOrder(req, user)
}
```

**改进**：样板代码少了，但**还是要显式调用**。

**失败**：

```
① 忘了调用鉴权 → 安全漏洞（这是真实事故来源！）
② 顺序容易搞错
③ 每个 handler 还是要写这几行
```

### v2：中间件链（洋葱模型）★

**核心思路：控制反转——不是 handler 调用中间件，而是中间件包住 handler。**

```go
type Handler func(*Context) error
type Middleware func(Handler) Handler

// ★ 组合：从后往前包
func Chain(h Handler, mws ...Middleware) Handler {
	for i := len(mws) - 1; i >= 0; i-- {
		h = mws[i](h)
	}
	return h
}

// 中间件示例
func Auth() Middleware {
	return func(next Handler) Handler {
		return func(c *Context) error {
			user, err := validateToken(c.Header("Authorization"))
			if err != nil {
				return ErrUnauthorized   // ★ 可以中断
			}
			c.Set("user", user)
			return next(c)               // ★ 继续
		}
	}
}

// 使用
handler := Chain(createOrder, Recovery(), Logger(), Auth())
```

**执行流程（洋葱模型）：**

```
请求 ──► ┌─ Recovery ─────────────────────┐
         │ ┌─ Logger ──────────────────┐  │
         │ │ ┌─ Auth ───────────────┐  │  │
         │ │ │   业务逻辑           │  │  │
         │ │ └──────────────────────┘  │  │
         │ └───────────────────────────┘  │
         └────────────────────────────────┘ ──► 响应
```

**为什么这个设计好：**

| 优点 | 说明 |
|:---|:---|
| **不会忘** | 中间件在注册时就绑定了，忘不掉 |
| **顺序明确** | `Chain` 的参数顺序就是执行顺序 |
| **可中断** | 中间件可以不调用 `next`（比如鉴权失败） |
| **可组合** | 不同路由可以配不同的中间件组合 |
| **前后都能做** | 在 `next()` 前后都可以加逻辑（如计时） |

> **老陈**：**中间件的本质是"装饰器模式 + 控制反转"。**
>
> **注意它跟 IoC 的关系（第 7 章第 01 节）：**
> - 不用中间件：handler 调用中间件（你控制流程）
> - 用中间件：中间件包住 handler（框架控制流程）
>
> **同一个思路的两个应用。**

### v3：性能优化——扁平化

**洋葱模型的问题**：10 个中间件 = 10 层嵌套闭包调用。

```
每层闭包都要捕获变量（堆分配）
每次调用都是间接跳转（难以内联）
```

**优化：区分 Before / After**

```go
type Plugin interface {
	Before(c *Context) error   // 请求前，可中断
	After(c *Context)          // 请求后，不可中断
}

func (c *FlatChain) Handle(ctx *Context) error {
	for _, p := range c.plugins {
		if err := p.Before(ctx); err != nil {
			return err
		}
	}
	// 业务逻辑
	for i := len(c.plugins) - 1; i >= 0; i-- {
		c.plugins[i].After(ctx)
	}
	return nil
}
```

**收益**：直接方法调用（可内联），实测快 30-50%。

**代价**：中间件不能在"中间"做复杂的事（只能在 Before 或 After）。

> **老陈**：**这是一个典型的"用表达能力换性能"的交易。**
>
> **大部分中间件只需要 Before/After，所以这个交易划算。**
> **但如果你的中间件需要在 next 前后共享复杂状态，扁平化就不合适了。**

---

## ★ 这一节真正的收获

三条独立的推导链：

**I/O 模型：**
```
v0 每连接一线程  → 失败: C10K（80GB 栈、上下文切换）
v1 非阻塞轮询    → 失败: CPU 100%、1000 万次无用系统调用
v2 select/poll   → 失败: O(n) 拷贝 + O(n) 遍历
v3 epoll         → 事件驱动，O(就绪数)
v4 +goroutine    → ★ 同步写法，异步性能（复杂度转移到 runtime）
```

**路由：**
```
v0 if-else    → 失败: O(n) 字符串比较
v1 map        → 失败: 不支持路径参数
v2 正则列表   → 失败: O(n) × 正则开销
v3 radix tree → ★ O(路径长度)，与路由数无关
```

**中间件：**
```
v0 重复样板    → 失败: 违反 DRY
v1 提取函数    → 失败: 还是要显式调用，忘了就出安全漏洞
v2 洋葱模型    → ★ 控制反转，不会忘、可组合、可中断
v3 扁平化      → 快 30-50%，牺牲部分表达能力
```

### 五个可以迁移的思维模式

**① 从"轮询"到"通知"**

epoll 的核心是事件驱动。
**通用模式：与其反复问"好了吗"，不如注册一个回调，好了通知我。**

**② 数据结构要匹配访问模式**

map 适合精确查找，Radix Tree 适合前缀查找 + 参数。
**先明确"查询模式"，再选结构。第 2 章第 00 篇的同一个道理。**

**③ 样板代码的终极解法是控制反转**

不是"提取函数"，而是"让框架调用你"。
**这样就不会忘、顺序也不会错。**

**④ 复杂度可以转移，不能消失**

Go 把 I/O 复杂度从用户代码转移到 runtime。
**问自己："这个复杂度我可以转移到哪里？"**

**⑤ 每次优化都是一次交易**

扁平化快 30-50%，代价是中间件不能在中间做复杂事。
**明确说出"我放弃了什么"。**

---

## 现在，轮到你了

**练习**：我们已经有路由和中间件了。还差一个关键能力——**请求级别的状态共享**。

需求：中间件之间要传递数据（比如 Auth 中间件解析出 user，后续 handler 要用）。

**v0 会怎么做？会失败在哪？**

提示（不要用，先自己想）：
- v0 可能是全局 map（key 是连接 ID）？失败在哪？
- 用 Context 对象？它怎么在 goroutine 之间传递？
- 如果 handler 里起了新 goroutine，Context 还能用吗？（★ 这是 gin 的经典陷阱）
- 异步使用时为什么要 `c.Copy()`？

> **老陈**：**答案是 Context 对象 + sync.Pool 复用。**
>
> **陷阱是：如果你在 handler 里启动 goroutine 并持有 Context，**
> **handler 返回后 Context 会被放回池子，被下一个请求复用——你读到的就是别人的数据。**
>
> **解法是 `c.Copy()`（脱离池子的副本）。**
>
> **如果你来设计，有没有更好的方案？比如：**
> **能不能让框架自动检测"Context 逃逸到 goroutine"？**

---

## 下一节

[01-IoC 与 AOP：依赖注入与横切关注点](./01-IoC与AOP-依赖注入与横切关注点.md)

这一节我们推导了 Web 框架的骨架，下一节看更上层的东西——依赖注入和 AOP 是怎么从"测试困难"和"样板代码"这两个失败里长出来的。
