# 02 · 手写 Web 容器：从 Socket 到 MVC

> *"Web 框架的核心，就是'URL 到函数的映射'加'一串中间件'。"*

---

## 开场：Tomcat 做了什么

> **小林**：MiniTomcat 那门课要写 Servlet 容器。但 Go 已经有 `net/http` 了，为什么还要自己写？
>
> **老陈**：**你用 `net/http` 写过一个 hello world 吗？**
>
> **小林**：写过，三行。
>
> **老陈**：**那我问你：`http.ListenAndServe` 内部做了什么？**
>
> **小林**：……监听端口，accept 连接，处理请求？
>
> **老陈**：**具体点。HTTP 报文是怎么被解析的？路由是怎么匹配的？keep-alive 是怎么处理的？**
>
> **小林**：……不知道。
>
> **老陈**：**这就是问题。** 你每天都在用 HTTP，但你不知道：
> - 一个 HTTP 请求报文长什么样
> - 为什么 `Content-Length` 和 `Transfer-Encoding` 不能同时出现
> - 为什么有些路由用 radix tree 而有些用 map
> - 为什么 Go 的 `http.Server` 要单独设置 ReadTimeout / WriteTimeout
>
> **这些知识在你排查"请求卡住了"、"连接泄漏了"、"路由 404 了"这些问题时，是必需的。**

---

## 第一部分：HTTP 协议

### 请求报文格式

```
GET /api/users?id=123 HTTP/1.1\r\n          ← 请求行
Host: example.com\r\n                        ←
User-Agent: curl/7.68.0\r\n                  │
Accept: */*\r\n                              ├ 请求头
Content-Length: 25\r\n                       │
\r\n                                        ← 空行（分隔头部和 body）
{"name":"alice","age":30}                    ← 请求体（可选）
```

**请求行的三个部分：**

```
GET /api/users?id=123 HTTP/1.1
│    │                │
│    │                └─ 协议版本
│    └─ 请求 URI（含 query string）
└─ 方法（GET/POST/PUT/DELETE/...）
```

### 响应报文格式

```
HTTP/1.1 200 OK\r\n
Content-Type: application/json\r\n
Content-Length: 26\r\n
\r\n
{"id":123,"name":"alice"}
```

### ★ 为什么 Content-Length 和 Transfer-Encoding 不能同时用

**这是 HTTP 最容易出错的地方之一。**

```
两种确定 body 长度的方式：

① Content-Length: 直接告诉对方 body 有多少字节
   Content-Length: 25
   → 接收方读满 25 字节就认为消息结束

② Transfer-Encoding: chunked: 分块传输
   
   4\r\n         ← 第一块 4 字节
   Wiki\r\n
   5\r\n         ← 第二块 5 字节
   pedia\r\n
   0\r\n         ← 0 表示结束
   \r\n
   
   → 发送方不需要提前知道总长度（适合流式数据）
```

**为什么不能同时用？**

```
如果两个都发，接收方不知道该信哪个
→ 如果信 Content-Length，chunked 的数据会被截断或解析错误
→ 如果信 chunked，Content-Length 就是多余且矛盾的

★ HTTP/1.1 规范明确规定：两者不能同时出现
★ 如果同时出现，必须以 Transfer-Encoding 为准，
  并且忽略 Content-Length（RFC 7230 3.3.3）

★ 这也是"请求走私"（Request Smuggling）攻击的原理：
  前端代理信 Content-Length，后端服务器信 chunked
  → 两者对"请求边界"的理解不同
  → 攻击者可以"夹带"一个请求进去
```

### HTTP/1.1 的 keep-alive

```
HTTP/1.0:  每个请求都要新建 TCP 连接（三次握手 + 慢启动）
HTTP/1.1:  默认 keep-alive，一个连接可以复用

Connection: keep-alive    ← 默认
Connection: close         ← 告诉对方"处理完就关掉"
```

**keep-alive 的问题：队头阻塞（Head-of-Line Blocking）**

```
一个 TCP 连接上，请求必须串行:
  请求1 → 响应1 → 请求2 → 响应2 → ...

如果请求1 很慢（比如后端处理了 5 秒）
→ 请求2 即使只需要 1ms，也要等 5 秒
```

**HTTP/2 的解法：多路复用（Multiplexing）**

```
一个连接上可以并发多个"流"（Stream）:
  流1: 请求1 ─────────► 响应1
  流2: 请求2 ──► 响应2
  流3: 请求3 ──────────────► 响应3
  
★ 互不阻塞
```

---

## 第二部分：手写 HTTP 服务器

### 版本 1：最简版（不用 net/http）

```go
package main

import (
	"bufio"
	"fmt"
	"io"
	"net"
	"strings"
	"time"
)

type Request struct {
	Method  string
	Path    string
	Query   string
	Proto   string
	Headers map[string]string
	Body    []byte
}

type Response struct {
	StatusCode int
	Headers    map[string]string
	Body       []byte
}

type Handler func(req *Request) *Response

// ============ 解析 HTTP 请求 ============

func parseRequest(reader *bufio.Reader) (*Request, error) {
	req := &Request{
		Headers: make(map[string]string),
	}

	// 1. 解析请求行
	line, err := reader.ReadString('\n')
	if err != nil {
		return nil, err
	}
	line = strings.TrimSpace(line)
	parts := strings.Split(line, " ")
	if len(parts) != 3 {
		return nil, fmt.Errorf("请求行格式错误: %q", line)
	}
	req.Method = parts[0]
	req.Proto = parts[2]

	// 分离 path 和 query
	uri := parts[1]
	if idx := strings.Index(uri, "?"); idx >= 0 {
		req.Path = uri[:idx]
		req.Query = uri[idx+1:]
	} else {
		req.Path = uri
	}

	// 2. 解析头部
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			return nil, err
		}
		line = strings.TrimSpace(line)
		if line == "" {
			break   // ★ 空行表示头部结束
		}
		idx := strings.Index(line, ":")
		if idx < 0 {
			continue
		}
		key := strings.TrimSpace(line[:idx])
		value := strings.TrimSpace(line[idx+1:])
		req.Headers[strings.ToLower(key)] = value   // ★ header 名不区分大小写
	}

	// 3. 解析 body
	if cl, ok := req.Headers["content-length"]; ok {
		var length int
		fmt.Sscanf(cl, "%d", &length)
		if length > 0 {
			body := make([]byte, length)
			if _, err := io.ReadFull(reader, body); err != nil {
				return nil, err
			}
			req.Body = body
		}
	}
	// TODO: 处理 Transfer-Encoding: chunked

	return req, nil
}

// ============ 序列化响应 ============

var statusText = map[int]string{
	200: "OK",
	201: "Created",
	400: "Bad Request",
	404: "Not Found",
	500: "Internal Server Error",
}

func writeResponse(w io.Writer, resp *Response) error {
	var sb strings.Builder

	// 状态行
	text := statusText[resp.StatusCode]
	if text == "" {
		text = "Unknown"
	}
	fmt.Fprintf(&sb, "HTTP/1.1 %d %s\r\n", resp.StatusCode, text)

	// 默认头部
	if resp.Headers == nil {
		resp.Headers = make(map[string]string)
	}
	if _, ok := resp.Headers["Content-Type"]; !ok {
		resp.Headers["Content-Type"] = "text/plain; charset=utf-8"
	}
	resp.Headers["Content-Length"] = fmt.Sprintf("%d", len(resp.Body))
	resp.Headers["Date"] = time.Now().UTC().Format(time.RFC1123)

	for k, v := range resp.Headers {
		fmt.Fprintf(&sb, "%s: %s\r\n", k, v)
	}
	sb.WriteString("\r\n")   // ★ 空行

	if _, err := w.Write([]byte(sb.String())); err != nil {
		return err
	}
	if len(resp.Body) > 0 {
		if _, err := w.Write(resp.Body); err != nil {
			return err
		}
	}
	return nil
}

// ============ 服务器 ============

type Server struct {
	addr    string
	handler Handler
}

func (s *Server) ListenAndServe() error {
	listener, err := net.Listen("tcp", s.addr)
	if err != nil {
		return err
	}
	defer listener.Close()

	fmt.Printf("服务器启动在 %s\n", s.addr)

	for {
		conn, err := listener.Accept()
		if err != nil {
			continue
		}
		go s.handleConn(conn)   // 每个连接一个 goroutine
	}
}

func (s *Server) handleConn(conn net.Conn) {
	defer conn.Close()

	reader := bufio.NewReader(conn)

	for {
		// ★ 设置读超时（防止慢连接攻击）
		conn.SetReadDeadline(time.Now().Add(30 * time.Second))

		req, err := parseRequest(reader)
		if err != nil {
			if err == io.EOF {
				return   // 客户端关闭连接
			}
			// 解析错误，返回 400
			writeResponse(conn, &Response{
				StatusCode: 400,
				Body:       []byte("Bad Request"),
			})
			return
		}

		resp := s.handler(req)

		// ★ 根据 Connection 头决定是否保持连接
		if strings.EqualFold(req.Headers["connection"], "close") {
			resp.Headers["Connection"] = "close"
			writeResponse(conn, resp)
			return
		}
		resp.Headers["Connection"] = "keep-alive"

		if err := writeResponse(conn, resp); err != nil {
			return
		}
	}
}

// ============ 演示 ============

func main() {
	server := &Server{
		addr: ":8080",
		handler: func(req *Request) *Response {
			if req.Path == "/" {
				return &Response{
					StatusCode: 200,
					Headers:    map[string]string{"Content-Type": "text/html"},
					Body:       []byte("<h1>Hello from hand-written server!</h1>"),
				}
			}
			if req.Path == "/echo" && req.Method == "POST" {
				return &Response{
					StatusCode: 200,
					Body:       req.Body,
				}
			}
			return &Response{
				StatusCode: 404,
				Body:       []byte("Not Found: " + req.Path),
			}
		},
	}
	if err := server.ListenAndServe(); err != nil {
		panic(err)
	}
}
```

**测试：**

```bash
go run server.go

# 另一个终端
curl -v http://localhost:8080/
curl -X POST -d 'hello' http://localhost:8080/echo
```

### ★ 四个必须处理的边界情况

**① 慢连接攻击（Slowloris）**

```
攻击方式：
  客户端建立连接，但极慢地发送请求头（比如每 10 秒发 1 字节）
  → 服务器线程/goroutine 被占住
  → 大量这样的连接耗尽服务器资源

防护：
  ★ 设置读超时
  conn.SetReadDeadline(time.Now().Add(30 * time.Second))
```

**② 请求体过大**

```
攻击方式：
  Content-Length: 10000000000  (10GB)
  → 服务器分配 10GB 内存 → OOM

防护：
  ★ 限制 body 大小
  const maxBodySize = 10 << 20   // 10MB
  if length > maxBodySize {
      return error
  }
  // 用 io.LimitReader
  body, err := io.ReadAll(io.LimitReader(reader, maxBodySize))
```

**③ 头部过大**

```
防护：
  reader := bufio.NewReaderSize(conn, 8192)   // 限制 buffer 大小
  // 或者限制头部总大小
```

**④ 连接泄漏**

```
场景：
  keep-alive 连接，客户端不关闭
  → goroutine 一直挂着
  → 大量连接累积

防护：
  ① 读超时（上面已做）
  ② 限制总连接数
  ③ 定期清理空闲连接
```

> **老陈**：**这就是为什么生产环境必须用成熟的 HTTP 服务器，而不是自己写的。**
>
> **Go 的 `http.Server` 提供了这些保护：**
> ```go
> srv := &http.Server{
>     ReadTimeout:       10 * time.Second,   // 读整个请求的最大时间
>     WriteTimeout:      10 * time.Second,   // 写响应的最大时间
>     IdleTimeout:       60 * time.Second,   // ★ keep-alive 的空闲超时
>     ReadHeaderTimeout: 5 * time.Second,    // ★ 只读头部的超时
>     MaxHeaderBytes:    1 << 20,            // 1MB
> }
> ```
>
> **★ `IdleTimeout` 是最容易被忽略的。** 不设置的话，空闲的 keep-alive 连接会永远挂着。

---

## 第三部分：路由树

### 为什么不用 map

```go
// 简单但不够
routes := map[string]Handler{
	"/users":      handler1,
	"/users/:id":  handler2,   // ★ 路径参数，map 做不了
}
```

**问题：**
- 不支持路径参数（`/users/123`）
- 不支持前缀匹配（`/static/*`）
- 无法高效找到"最长匹配"

### Radix Tree（压缩前缀树）

**普通的 Trie（前缀树）：**

```
插入: /user, /users, /user/:id

        root
         │
         u
         │
         s
         │
         e
         │
         r ──── (结束: /user)
         │
         s ──── (结束: /users)
         │
         /
         │
         : ──── (结束: /user/:id)
```

**问题：每个字符一个节点，树很深，浪费空间。**

**Radix Tree（压缩路径上没有分叉的节点）：**

```
插入: /user, /users, /user/:id

        root
         │
      "/user"           ← 压缩成一个节点
         │
    ┌────┴────┐
    │         │
  (结束)     "s"        ← 继续分叉
    │         │
  /user   (结束)
              │
            "/"
              │
            ":id"
              │
           (结束)
```

**优势：**
- 节点数大幅减少
- 查找是 O(路径长度)，与路由数量无关
- 天然支持前缀匹配和路径参数

### Go 实现

```go
package main

import (
	"fmt"
	"strings"
)

type nodeType int

const (
	nodeStatic   nodeType = 0   // 静态路径
	nodeParam    nodeType = 1   // 参数路径 :id
	nodeCatchAll nodeType = 2   // 通配路径 *filepath
)

type node struct {
	typ      nodeType
	path     string        // 这个节点代表的路段
	indices  string        // 子节点首字母索引（加速查找）
	children []*node
	handler  Handler
	paramName string       // 参数名（param 节点用）
}

type Router struct {
	trees map[string]*node   // 每个 method 一棵树
}

func NewRouter() *Router {
	return &Router{
		trees: make(map[string]*node),
	}
}

func (r *Router) AddRoute(method, path string, h Handler) {
	if r.trees[method] == nil {
		r.trees[method] = &node{path: "/"}
	}
	r.trees[method].insert(path, h)
}

func (n *node) insert(path string, h Handler) {
	fullPath := path

	for {
		// 1. 找到与当前节点 path 的公共前缀
		commonLen := 0
		maxLen := min(len(n.path), len(path))
		for commonLen < maxLen && n.path[commonLen] == path[commonLen] {
			commonLen++
		}

		// 2. 如果公共前缀小于当前节点的路径，需要分裂
		if commonLen < len(n.path) {
			// 分裂当前节点
			child := &node{
				typ:      n.typ,
				path:     n.path[commonLen:],
				indices:  n.indices,
				children: n.children,
				handler:  n.handler,
			}
			n.path = n.path[:commonLen]
			n.indices = string(child.path[0])
			n.children = []*node{child}
			n.handler = nil
			n.typ = nodeStatic
		}

		// 3. 路径已经完全匹配
		if commonLen == len(path) {
			n.handler = h
			return
		}

		// 4. 继续处理剩余路径
		path = path[commonLen:]

		// 查找是否有匹配的子节点
		if idx := strings.IndexByte(n.indices, path[0]); idx >= 0 {
			n = n.children[idx]
			continue
		}

		// 5. 创建新子节点
		//    判断是不是参数节点
		typ := nodeStatic
		paramName := ""

		if path[0] == ':' {
			typ = nodeParam
			end := strings.IndexByte(path, '/')
			if end < 0 {
				end = len(path)
			}
			paramName = path[1:end]
		} else if path[0] == '*' {
			typ = nodeCatchAll
			paramName = path[1:]
		}

		child := &node{
			typ:       typ,
			path:      path,
			paramName: paramName,
		}
		n.indices += string(path[0])
		n.children = append(n.children, child)
		n = child
	}
}

// 查找
type MatchResult struct {
	Handler Handler
	Params  map[string]string
}

func (r *Router) Lookup(method, path string) (*MatchResult, bool) {
	root, ok := r.trees[method]
	if !ok {
		return nil, false
	}

	params := make(map[string]string)
	n := root
	remaining := path

	for {
		if len(remaining) == 0 {
			if n.handler != nil {
				return &MatchResult{n.handler, params}, true
			}
			return nil, false
		}

		// 1. 匹配当前节点的 path
		if len(n.path) > 0 {
			if !strings.HasPrefix(remaining, n.path) {
				return nil, false
			}
			remaining = remaining[len(n.path):]

			if len(remaining) == 0 && n.handler != nil {
				return &MatchResult{n.handler, params}, true
			}
		}

		// 2. 找子节点
		if len(remaining) == 0 {
			return nil, false
		}

		// 优先精确匹配静态节点
		if idx := strings.IndexByte(n.indices, remaining[0]); idx >= 0 {
			child := n.children[idx]
			if child.typ == nodeStatic {
				n = child
				continue
			}
		}

		// 其次尝试参数节点
		for _, child := range n.children {
			if child.typ == nodeParam {
				// 提取参数值（到下一个 / 为止）
				end := strings.IndexByte(remaining, '/')
				if end < 0 {
					end = len(remaining)
				}
				params[child.paramName] = remaining[:end]

				rest := remaining[end:]
				if len(rest) == 0 && child.handler != nil {
					return &MatchResult{child.handler, params}, true
				}
				// 继续在子树里找
				n = child
				remaining = rest
				if len(n.path) > 0 {
					// 跳过 child 自己的 path
				}
				goto nextIter
			}
			if child.typ == nodeCatchAll {
				params[child.paramName] = remaining
				return &MatchResult{child.handler, params}, true
			}
		}

		return nil, false

	nextIter:
	}
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// ============ 演示 ============

func demoRouter() {
	r := NewRouter()

	r.AddRoute("GET", "/", func(req *Request) *Response {
		return &Response{200, nil, []byte("首页")}
	})
	r.AddRoute("GET", "/users", func(req *Request) *Response {
		return &Response{200, nil, []byte("用户列表")}
	})
	r.AddRoute("GET", "/users/:id", func(req *Request) *Response {
		return &Response{200, nil, []byte("单个用户")}
	})
	r.AddRoute("GET", "/users/:id/posts", func(req *Request) *Response {
		return &Response{200, nil, []byte("用户的文章")}
	})
	r.AddRoute("GET", "/static/*filepath", func(req *Request) *Response {
		return &Response{200, nil, []byte("静态文件")}
	})

	tests := []struct{ method, path string }{
		{"GET", "/"},
		{"GET", "/users"},
		{"GET", "/users/123"},
		{"GET", "/users/123/posts"},
		{"GET", "/static/css/main.css"},
		{"GET", "/notfound"},
		{"POST", "/users"},
	}

	for _, t := range tests {
		result, ok := r.Lookup(t.method, t.path)
		if ok {
			resp := result.Handler(nil)
			fmt.Printf("%-6s %-25s → %s  params=%v\n",
				t.method, t.path, resp.Body, result.Params)
		} else {
			fmt.Printf("%-6s %-25s → 404\n", t.method, t.path)
		}
	}
}

func main() {
	demoRouter()
}
```

**输出：**

```
GET    /                         → 首页  params=map[]
GET    /users                    → 用户列表  params=map[]
GET    /users/123                → 单个用户  params=map[id:123]
GET    /users/123/posts          → 用户的文章  params=map[id:123]
GET    /static/css/main.css      → 静态文件  params=map[filepath:css/main.css]
GET    /notfound                 → 404
POST   /users                    → 404
```

---

## 第四部分：完整的 MVC 框架

把我们学的所有东西组合起来：

```go
type Context struct {
	Req    *Request
	Resp   *Response
	Params map[string]string
	values map[string]interface{}
	index  int           // 中间件链的当前位置
	chain  []Middleware
}

type Middleware func(c *Context, next func())

type Engine struct {
	router *Router
	mws    []Middleware
	pool   sync.Pool
}

func New() *Engine {
	e := &Engine{router: NewRouter()}
	e.pool = sync.Pool{
		New: func() interface{} {
			return &Context{values: make(map[string]interface{}, 8)}
		},
	}
	return e
}

func (e *Engine) Use(mw ...Middleware) {
	e.mws = append(e.mws, mw...)
}

func (e *Engine) GET(path string, h Handler) {
	e.router.AddRoute("GET", path, h)
}

func (e *Engine) ServeHTTP(req *Request) *Response {
	// 1. 路由匹配
	result, ok := e.router.Lookup(req.Method, req.Path)
	if !ok {
		return &Response{404, nil, []byte("404 Not Found")}
	}

	// 2. 从池里取 Context
	c := e.pool.Get().(*Context)
	defer func() {
		// 重置并归还
		for k := range c.values {
			delete(c.values, k)
		}
		c.index = 0
		e.pool.Put(c)
	}()

	c.Req = req
	c.Params = result.Params
	c.Resp = &Response{Headers: make(map[string]string)}

	// 3. 构建中间件链（全局中间件 + 最终 handler）
	c.chain = make([]Middleware, 0, len(e.mws)+1)
	c.chain = append(c.chain, e.mws...)
	c.chain = append(c.chain, func(c *Context, next func()) {
		resp := result.Handler(c.Req)
		c.Resp = resp
	})

	// 4. 执行链
	c.Next()

	return c.Resp
}

func (c *Context) Next() {
	if c.index >= len(c.chain) {
		return
	}
	i := c.index
	c.index++
	c.chain[i](c, c.Next)
}

// 中间件示例
func Logger() Middleware {
	return func(c *Context, next func()) {
		start := time.Now()
		next()
		log.Printf("%s %s cost=%v", c.Req.Method, c.Req.Path, time.Since(start))
	}
}

func Recovery() Middleware {
	return func(c *Context, next func()) {
		defer func() {
			if r := recover(); r != nil {
				log.Printf("panic: %v\n%s", r, debug.Stack())
				c.Resp = &Response{500, nil, []byte("Internal Server Error")}
			}
		}()
		next()
	}
}
```

---

## 思考题 ·【应用层】

**你的 Go Web 服务用的是 gin。某天发现：`GET /api/v1/users/:id` 这个路由的 P99 延迟突然从 10ms 涨到 500ms，但其他路由正常。CPU 和内存都正常。请分析可能的原因，给出诊断方法。**

<details>
<summary>参考答案</summary>

### 现象的关键

```
★ 只有一个路由慢，其他正常
★ CPU 和内存正常

这排除了：
  · 全局的 GC 问题（会影响所有路由）
  · 全局的锁竞争（会影响所有路由）
  · CPU 瓶颈

剩下可能：
  · 这个路由的处理逻辑本身慢
  · 这个路由依赖的某个资源慢
  · 路由匹配本身慢（★ 容易忽略）
```

---

### 可能原因 1：路由冲突导致的匹配变慢

**这是 gin/httprouter 特有的坑。**

```
场景：你后来加了一个新路由

  原有: GET /api/v1/users/:id
  新增: GET /api/v1/users/me      ← 冲突！

gin 的 radix tree 遇到这种情况会：
  · 把 :id 节点分裂
  · 或者报 panic: "conflicts with existing wildcard"

★ 如果没 panic，而是走了"回溯"路径：
  匹配 /api/v1/users/123 时:
    1. 先尝试匹配 "me" → 不匹配
    2. 回溯，尝试匹配 :id → 匹配
  ★ 多了一次回溯
```

**但一次回溯只有几纳秒，不会造成 500ms。**

**更严重的场景：大量冲突**

```
如果你有这些路由:
  /api/v1/users/:id
  /api/v1/users/me
  /api/v1/users/:id/posts
  /api/v1/users/me/posts      ← 又一个冲突
  ...

★ 树的形状会变得复杂，匹配路径变长
★ 但仍然只是微秒级
```

**所以路由冲突不太可能是 500ms 的原因。** 但值得检查。

**诊断：**
```go
// 打印所有路由，检查冲突
routes := router.Routes()
for _, r := range routes {
	fmt.Printf("%-6s %s\n", r.Method, r.Path)
}
```

---

### 可能原因 2：这个路由的处理逻辑里有串行 IO ★ 最可能

```go
// ❌ 典型问题：N+1 查询
func GetUser(c *gin.Context) {
	id := c.Param("id")

	// 1. 查用户
	user, _ := db.GetUser(id)

	// 2. 查用户的订单
	orders, _ := db.GetOrders(user.ID)

	// 3. ★ 对每个订单查详情
	for _, o := range orders {
		o.Items, _ = db.GetOrderItems(o.ID)   // ★ N 次查询！
	}

	// 4. 查用户的权限
	perms, _ := db.GetPermissions(user.ID)

	// 5. 查用户的统计
	stats, _ := db.GetStats(user.ID)

	c.JSON(200, gin.H{"user": user, "orders": orders})
}
```

**问题**：5 类查询串行执行，每个 2ms，总共 10ms。**看起来还行。**

**但如果某个用户的订单特别多（比如 1000 个）**：
- 1000 次 `GetOrderItems` × 2ms = 2 秒！
- **这就是 P99 500ms 的来源——少数"大用户"**

**诊断：**

```go
// 加详细的耗时日志
func GetUser(c *gin.Context) {
	start := time.Now()
	defer func() {
		log.Infof("GetUser total=%v", time.Since(start))
	}()

	t1 := time.Now()
	user, _ := db.GetUser(id)
	log.Infof("  GetUser=%v", time.Since(t1))

	t2 := time.Now()
	orders, _ := db.GetOrders(user.ID)
	log.Infof("  GetOrders=%v count=%d", time.Since(t2), len(orders))  // ★ 看 count

	t3 := time.Now()
	// ...
	log.Infof("  GetOrderItems=%v", time.Since(t3))

	// ...
}
```

**或者用 trace：**

```go
import "golang.org/x/net/context"
import "go.opentelemetry.io/otel"

func GetUser(c *gin.Context) {
	ctx, span := tracer.Start(c.Request.Context(), "GetUser")
	defer span.End()

	// 每个子操作也加 span
	// → 在 Jaeger 里能看到完整的火焰图
}
```

**解决：**

**方案 A：批量查询（最重要）**

```go
// ❌ N+1
for _, o := range orders {
	o.Items, _ = db.GetOrderItems(o.ID)
}

// ✅ 批量
orderIDs := make([]int64, len(orders))
for i, o := range orders {
	orderIDs[i] = o.ID
}
itemsMap, _ := db.GetOrderItemsBatch(orderIDs)   // 一次查询
for _, o := range orders {
	o.Items = itemsMap[o.ID]
}
```

**方案 B：并行查询（无依赖的操作）**

```go
// 用户、权限、统计之间没有依赖 → 可以并行
var wg sync.WaitGroup
var perms []Permission
var stats Stats

wg.Add(2)
go func() {
	defer wg.Done()
	perms, _ = db.GetPermissions(user.ID)
}()
go func() {
	defer wg.Done()
	stats, _ = db.GetStats(user.ID)
}()
wg.Wait()

// 10ms → 4ms
```

**方案 C：分页 / 限制**

```go
// 订单只返回最近 20 条
orders, _ := db.GetOrders(user.ID, 20)

// 或者异步加载详情
```

**方案 D：缓存**

```go
// 用户信息缓存
func GetUser(id int64) (*User, error) {
	key := fmt.Sprintf("user:%d", id)
	if cached, ok := cache.Get(key); ok {
		return cached.(*User), nil
	}
	user, err := db.GetUser(id)
	if err == nil {
		cache.Set(key, user, 5*time.Minute)
	}
	return user, err
}
```

---

### 可能原因 3：慢查询（数据库层面）

```
场景：
  大部分用户的数据量小，查询快
  少数用户的数据量大（比如有几万条订单）
  → 索引失效 / 扫描行数暴增
  → 查询从 1ms 变成 500ms
```

**诊断：**

```sql
-- MySQL 慢查询日志
SHOW VARIABLES LIKE 'slow_query_log';
SET GLOBAL slow_query_log = 'ON';
SET GLOBAL long_query_time = 0.1;   -- 100ms

-- 分析
EXPLAIN SELECT * FROM orders WHERE user_id = 123;
-- ★ 看 type、rows、Extra
--   type=ALL    → 全表扫描，没有索引！
--   rows=100000 → 扫描 10 万行
```

**解决：**

```sql
-- 加索引
CREATE INDEX idx_orders_user_id ON orders(user_id);

-- 复合索引（如果查询是 WHERE user_id=? AND status=?）
CREATE INDEX idx_orders_user_status ON orders(user_id, status);
```

---

### 可能原因 4：下游服务超时

```
如果这个路由调用了其他微服务:
  · 下游服务偶发慢
  · 没有超时控制 → 一直等
```

**诊断：**
- 链路追踪（Jaeger / SkyWalking）
- 看下游服务的 P99

**解决：**

```go
// ★ 必须设置超时
ctx, cancel := context.WithTimeout(ctx, 50*time.Millisecond)
defer cancel()

resp, err := client.GetUser(ctx, id)
if err != nil {
	if errors.Is(err, context.DeadlineExceeded) {
		// 降级：返回部分数据或缓存
		return cachedUser, nil
	}
	return nil, err
}
```

**★ 超时预算（Timeout Budget）：**

```
总预算 100ms:
  ├─ 数据库查询:  30ms
  ├─ 下游服务 A:  30ms
  ├─ 下游服务 B:  20ms
  └─ 缓冲:        20ms

★ 每个环节都要设置超时，且总和 < 总预算
★ 否则级联超时会导致雪崩
```

---

### 可能原因 5：Gin 的 Context 对象池问题（Go 特有）

```
Gin 用 sync.Pool 复用 Context
★ 如果你在 handler 里保存了 Context 的引用，
  并在 handler 返回后继续使用 → 数据竞争 / 读到脏数据
```

```go
// ❌ 危险
func GetUser(c *gin.Context) {
	go func() {
		time.Sleep(time.Second)
		// ★ 此时 c 已经被放回池子，可能被其他请求复用！
		log.Info(c.Param("id"))   // 读到的是别人的数据！
	}()
	c.JSON(200, user)
}

// ✅ 正确：复制一份
func GetUser(c *gin.Context) {
	cp := c.Copy()   // ★ 返回一个"脱离池子"的副本
	go func() {
		time.Sleep(time.Second)
		log.Info(cp.Param("id"))   // 安全
	}()
	c.JSON(200, user)
}
```

---

### 诊断流程（我的建议）

```
第 1 步: 加详细的耗时日志 / 链路追踪        10 分钟
         目的：确认时间花在哪个子操作

第 2 步: 如果是数据库慢 → EXPLAIN           5 分钟

第 3 步: 检查是否有 N+1 查询                15 分钟

第 4 步: 检查下游服务是否设置了超时          10 分钟

第 5 步: 检查是否有"大用户"（数据倾斜）      10 分钟
         SELECT user_id, COUNT(*) FROM orders
         GROUP BY user_id ORDER BY COUNT(*) DESC LIMIT 10;
```

---

### 一句话总结

**"单个路由慢，其他正常"几乎总是"这个路由的数据/依赖有问题"，而不是框架或运行时的问题。**

最常见的三个：
1. **N+1 查询**（最常见）
2. **数据倾斜**（少数用户的数据量特别大）
3. **缺少索引**或**下游缺超时**

**诊断的关键是把"端到端延迟"拆成"每个子操作的延迟"。** 这一步做不到，后面都是猜。

</details>

---

## 小结：这一节你应该带走的东西

1. **HTTP 报文的格式**：请求行、头部、空行、body。`Content-Length` 和 `Transfer-Encoding` 不能同时用（这是请求走私的原理）。

2. **手写 HTTP 服务器的四个防护**：读超时（防 Slowloris）、限制 body 大小、限制头部大小、IdleTimeout（防连接泄漏）。

3. **Radix Tree 是路由的标准数据结构**：压缩无分叉的路径，查找 O(路径长度)，支持参数路径。

4. **Web 框架 = 路由树 + 中间件链 + Context**。就这么简单。

5. **Context 对象池的陷阱**：异步使用必须 `Copy()`。

6. **Go 的 `http.Server` 必须设置四个超时**：ReadTimeout、WriteTimeout、IdleTimeout、ReadHeaderTimeout。

---

## 第 7 章总结

### 三个核心认知

1. **IoC 是思想，DI 是技术**。Go 用构造函数注入，因为它有编译期检查、不可变、明确。

2. **wire vs dig = 编译期 vs 运行期**。这是"把信息提前到编译期"原则在框架层面的体现。

3. **框架的本质是"控制反转"**：框架调用你，你只填回调。**复杂度要么在框架，要么在用户代码**——Go 选择了后者。

### 你现在拥有的

```
ch07-framework/
├── di/          反射版 DI 容器（依赖图解析、循环依赖检测）
├── aop/         中间件链 + 装饰器
├── http/        手写 HTTP 服务器（协议解析、keep-alive、超时防护）
├── router/      Radix Tree 路由
└── mvc/         完整的迷你 Web 框架
```

---

## 下一章

[第 8 章 · 架构心法与多媒体系统](../第8章-架构心法与多媒体系统/README.md)

最后一章。我们要回答两个问题：

> **① 什么情况下，我应该自己造？**（架构决策的核心判断）
> **② 音视频系统是怎么工作的？**（攻克视频技术 + 搞定音频技术）

> **老陈的预告**：造轮子的时机判断，比造轮子的能力更稀缺。**这一章结束，你要能对着一个需求，说出"这里该用什么、为什么、以及什么时候该自己写"。**
