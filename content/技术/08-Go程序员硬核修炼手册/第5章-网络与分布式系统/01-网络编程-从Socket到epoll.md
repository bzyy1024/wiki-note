# 01 · 网络编程：从 Socket 到 epoll

> *"为什么 Go 能用同步阻塞的写法，撑起百万并发？答案在 netpoller 里。"*

---

## 开场：一个"不可能"的数字

> **老陈**：你的 Go 服务能撑多少并发连接？
>
> **小林**：我们线上跑过 5 万，应该还能更多。
>
> **老陈**：**如果每个连接一个线程，5 万个连接需要多少内存？**
>
> **小林**：……一个线程栈 8MB（Linux 默认），5 万 × 8MB = 400GB。**不可能。**
>
> **老陈**：那 Go 是怎么做到的？
>
> **小林**：goroutine 栈只有 2KB……
>
> **老陈**：**但线程数呢？** 5 万个 goroutine 映射到几个 OS 线程？
>
> **小林**：……GOMAXPROCS 个？也就是 8 个？
>
> **老陈**：**对。8 个线程管 5 万个连接。** 那我问你：**这 8 个线程怎么知道哪个连接有数据到了？**
>
> **小林**：……轮询？
>
> **老陈**：**轮询 5 万个连接，每次都要做 5 万次系统调用。你觉得延迟会是多少？**
>
> **小林**：…………不知道。
>
> **老陈**：**这就是 epoll 要解决的问题。** 我们从头来。

---

## I/O 模型的演进

### 模型 1：阻塞 I/O + 每连接一线程

```c
// 最简单的写法
while (1) {
    int clientfd = accept(listenfd, ...);
    pthread_create(&tid, NULL, handle_client, &clientfd);
}

void* handle_client(void* arg) {
    int fd = *(int*)arg;
    char buf[1024];
    while (1) {
        // ★ 阻塞在这里，直到有数据
        int n = read(fd, buf, sizeof(buf));
        if (n <= 0) break;
        write(fd, buf, n);   // echo
    }
    close(fd);
}
```

**问题：**
- 1 万个连接 = 1 万个线程
- 线程栈 8MB → 80GB（虚拟内存）
- 上下文切换开销巨大
- **C10K 问题**（1999 年提出）

### 模型 2：非阻塞 I/O + 轮询（忙等待）

```c
// 设置非阻塞
fcntl(fd, F_SETFL, O_NONBLOCK);

while (1) {
    for (int i = 0; i < num_fds; i++) {
        int n = read(fds[i], buf, sizeof(buf));   // ★ 立即返回
        if (n > 0) {
            handle_data(fds[i], buf, n);
        }
        // n == -1 且 errno == EAGAIN → 没数据
    }
}
```

**问题：**
- CPU 100%（空转）
- 每次 `read` 都是系统调用（即使没数据）
- 1 万个连接 × 每秒轮询 1000 次 = 1000 万次系统调用/秒

### 模型 3：I/O 多路复用（select / poll）

```c
fd_set readfds;
FD_ZERO(&readfds);
for (int i = 0; i < num_fds; i++) {
    FD_SET(fds[i], &readfds);
}

// ★ 一次系统调用，等待多个 fd
int ready = select(max_fd + 1, &readfds, NULL, NULL, NULL);

// 检查哪些 fd 就绪
for (int i = 0; i < num_fds; i++) {
    if (FD_ISSET(fds[i], &readfds)) {
        read(fds[i], buf, sizeof(buf));   // 这次 read 不会阻塞
    }
}
```

**进步**：一次系统调用等待多个 fd
**问题**：
1. **fd 数量限制**：`select` 默认 1024（`FD_SETSIZE`）
2. **每次都要拷贝整个 fd 集合**到内核（O(n)）
3. **返回后还要遍历所有 fd**才知道哪些就绪（O(n)）

`poll` 改进了第 1 点（用链表，无数量限制），但 2、3 依然存在。

### 模型 4：epoll

**epoll 的三个关键设计：**

```
① 内核维护一个"兴趣列表"（红黑树）
   · epoll_ctl(ADD/MOD/DEL) 增量维护
   · 不需要每次都传全部 fd

② 内核维护一个"就绪列表"（双向链表）
   · 有事件时，内核回调把 fd 加入就绪列表
   · 不需要遍历

③ epoll_wait 直接返回就绪列表
   · O(就绪数)，不是 O(总 fd 数)
```

**对比：**

| | select/poll | epoll |
|:---|:---|:---|
| **fd 数量** | 1024（select）/ 无限制（poll） | 无限制（约等于内存能装的 fd 数） |
| **每次调用的拷贝** | O(n) 全部 fd | **O(1)**（增量维护） |
| **返回后查找就绪** | O(n) 遍历 | **O(就绪数)** |
| **适合场景** | 连接少且活跃 | **连接多，少量活跃** ★ |

> **老陈**：**注意最后一行。epoll 的优势在"大量连接中只有少量活跃"的场景。**
>
> 如果 1 万个连接全都活跃，epoll 的优势就没了（因为就绪列表有 1 万个）。
>
> **而互联网应用的典型模式恰恰是"大量空闲连接 + 少量活跃"**——长连接、HTTP keep-alive、WebSocket。这就是为什么 epoll 这么重要。

---

## epoll 的三个 API

```c
#include <sys/epoll.h>

// 1. 创建 epoll 实例
int epfd = epoll_create1(0);
// 内核里创建一个 eventpoll 结构：
//   · rbr: 红黑树，存"我关心的 fd"
//   · rdllist: 双向链表，存"已就绪的 fd"

// 2. 注册/修改/删除关注的 fd
struct epoll_event ev;
ev.events = EPOLLIN | EPOLLET;   // 可读 + 边缘触发
ev.data.fd = clientfd;
epoll_ctl(epfd, EPOLL_CTL_ADD, clientfd, &ev);

// 3. 等待事件
struct epoll_event events[1024];
int n = epoll_wait(epfd, events, 1024, timeout_ms);
// n = 就绪的 fd 数量
// events[0..n-1] 是就绪的事件
```

### epoll 的内部结构

```c
struct eventpoll {
    // 等待队列：epoll_wait 阻塞的进程挂在这里
    wait_queue_head_t wq;

    // 就绪列表：有事件的 fd 挂在这里 ★ epoll_wait 直接取这个
    struct list_head rdllist;

    // 红黑树：所有被监控的 fd ★ epoll_ctl 操作这个
    struct rb_root_cached rbr;
};

struct epitem {
    // 红黑树节点
    struct rb_node rbn;

    // 就绪链表节点
    struct list_head rdllist;

    // 关注的 fd 和事件
    struct epoll_filefd ffd;
    struct epoll_event event;

    // ★ 关键：等待队列项，注册到 fd 对应设备的等待队列
    wait_queue_entry_t wq;
};
```

**事件到达的流程：**

```
① 网卡收到数据，DMA 写入内存
② 网卡触发硬件中断
③ 内核中断处理程序：
   · 收包，解析协议栈（eth → ip → tcp）
   · 找到对应的 socket
   · 把数据放入 socket 的接收队列
   · ★ 调用 socket 的等待队列上的回调函数
④ 这个回调函数就是 epoll 注册的 ep_poll_callback
   · 把对应的 epitem 加入 eventpoll 的 rdllist
   · 唤醒 epoll_wait 阻塞的进程
⑤ epoll_wait 返回，用户态拿到就绪列表
```

**关键：这是"事件驱动"（回调），不是"轮询"。**

---

## LT vs ET：本质区别在哪

### 水平触发（Level-Triggered, LT）

**默认模式。只要 fd 处于"可读"状态，每次 epoll_wait 都会返回它。**

```c
// LT 模式
ev.events = EPOLLIN;   // 不设 EPOLLET 就是 LT

// 例子：socket 收到 2KB 数据，但只读了 1KB
n = epoll_wait(epfd, events, 1024, -1);
read(fd, buf, 1024);    // 只读了 1KB，还剩 1KB 在缓冲区

// 下次 epoll_wait 还会返回这个 fd
// ★ 因为缓冲区还有数据，"可读"状态仍然成立
```

**特点**：
- 安全：没读完会反复通知
- 简单：不怕漏事件
- 可以用阻塞 I/O（但通常还是用非阻塞）

### 边缘触发（Edge-Triggered, ET）

**只在状态"从不可读变为可读"的那一刻通知一次。**

```c
// ET 模式
ev.events = EPOLLIN | EPOLLET;

// 例子：socket 收到 2KB 数据
n = epoll_wait(epfd, events, 1024, -1);   // 返回这个 fd
read(fd, buf, 1024);                       // 只读了 1KB

// ★ 下次 epoll_wait 不会返回这个 fd！
// 因为状态没有"再次变化"
// 除非有新的数据到达
```

**为什么 ET 必须配合非阻塞 I/O？**

```c
// ❌ 错误：ET + 阻塞 read
while (1) {
    n = epoll_wait(epfd, events, 1024, -1);
    for (每个就绪 fd) {
        read(fd, buf, sizeof(buf));   // ★ 如果数据读完，会阻塞！
        //    而 ET 不会再通知，这个 fd 就永久卡住了
    }
}

// ✅ 正确：ET + 非阻塞 read + 循环读到 EAGAIN
while (1) {
    n = epoll_wait(epfd, events, 1024, -1);
    for (每个就绪 fd) {
        while (1) {
            ssize_t count = read(fd, buf, sizeof(buf));
            if (count == -1) {
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    break;   // ★ 数据读完了
                }
                // 真正的错误
                close(fd);
                break;
            } else if (count == 0) {
                // 对端关闭
                close(fd);
                break;
            }
            // 处理 count 字节数据
        }
    }
}
```

### 本质区别在哪一层？

> **老陈**：**LT 和 ET 的区别，不在"触发次数"，而在"内核怎么维护就绪状态"。**

```
LT 的实现:
  epoll_wait 返回后，内核会检查：
    "这个 fd 还满足条件吗？"
  如果满足，把 epitem 重新加回 rdllist
  → 下次 epoll_wait 还会返回

ET 的实现:
  epoll_wait 返回后，内核直接把 epitem 从 rdllist 移除
  不检查状态
  → 只有状态再次"变化"（新数据到达）时才重新加入
```

**所以 ET 的性能优势是：减少了内核的重复检查和用户态的重复系统调用。**

**但代价是编程复杂度大幅上升。** 一旦漏读，连接就永久卡死。

> **老陈的建议**：
> **99% 的场景用 LT。** ET 的性能提升通常只有几个百分点，但出 bug 的概率高得多。
>
> **Go 的 netpoller 用的是 LT**（准确说是"一次性注册 + 按需重新注册"的模式）。
> **Nginx 用的是 ET**（因为它追求极致性能，且代码经过十几年打磨）。

---

## Go 的 netpoller

### Go 怎么做到"同步写法 + 异步性能"

```go
// 你写的代码
conn, _ := listener.Accept()
buf := make([]byte, 1024)
n, err := conn.Read(buf)   // ★ 看起来是阻塞的
```

**实际发生的事：**

```
① conn.Read()  → 调用 netFD.Read()
② 尝试非阻塞 read
③ 如果返回 EAGAIN（没数据）:
   · 调用 runtime_pollWait()
   · ★ 把当前 goroutine 挂起（gopark）
   · 把这个 fd 注册到 netpoller（epoll_ctl ADD）
   · 调度器去跑别的 goroutine
④ 数据到达:
   · epoll 事件触发
   · netpoller 的那个后台 goroutine（netpoll）被唤醒
   · 找到对应的 goroutine，标记为可运行（goready）
⑤ goroutine 被调度:
   · 重新执行 read
   · 这次有数据了，返回
```

**关键：步骤 ③ 的 gopark 和步骤 ⑤ 的 goready，对你完全透明。**

### 用一个最小实现理解它

```go
package main

// 这是 netpoller 的极简模拟
// 真实实现在 runtime/netpoll_epoll.go

import (
	"fmt"
	"sync"
	"syscall"
	"time"
)

// ============ 极简的 poller ============

type Poller struct {
	epfd     int
	mu       sync.Mutex
	// fd → 等待这个 fd 的 goroutine 的 channel
	waiters  map[int]chan struct{}
}

func NewPoller() (*Poller, error) {
	epfd, err := syscall.EpollCreate1(0)
	if err != nil {
		return nil, err
	}
	p := &Poller{
		epfd:    epfd,
		waiters: make(map[int]chan struct{}),
	}
	go p.loop()
	return p, nil
}

// 注册一个 fd，返回用于等待的 channel
func (p *Poller) AddFD(fd int) chan struct{} {
	// 设置为非阻塞
	syscall.SetNonblock(fd, true)

	p.mu.Lock()
	ch := make(chan struct{}, 1)
	p.waiters[fd] = ch
	p.mu.Unlock()

	// 注册到 epoll（LT 模式，关注可读）
	event := syscall.EpollEvent{
		Events: syscall.EPOLLIN,
		Fd:     int32(fd),
	}
	syscall.EpollCtl(p.epfd, syscall.EPOLL_CTL_ADD, fd, &event)

	return ch
}

// 事件循环（单个 goroutine）
func (p *Poller) loop() {
	events := make([]syscall.EpollEvent, 1024)
	for {
		// ★ 阻塞等待事件
		n, err := syscall.EpollWait(p.epfd, events, -1)
		if err != nil {
			if err == syscall.EINTR {
				continue
			}
			return
		}

		// 通知所有就绪的 fd 的等待者
		for i := 0; i < n; i++ {
			fd := int(events[i].Fd)

			p.mu.Lock()
			ch, ok := p.waiters[fd]
			p.mu.Unlock()

			if ok {
				// ★ 唤醒等待的 goroutine
				select {
				case ch <- struct{}{}:
				default:
				}
			}
		}
	}
}

// ============ 模拟 net.Conn 的 Read ============

type PollConn struct {
	fd     int
	poller *Poller
	waitCh chan struct{}
}

// Read 模拟 Go 的阻塞式 Read（内部是非阻塞 + goroutine 挂起）
func (c *PollConn) Read(buf []byte) (int, error) {
	for {
		// 1. 尝试非阻塞读
		n, err := syscall.Read(c.fd, buf)
		if err == nil {
			return n, nil   // 成功
		}

		if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK {
			// 2. 没数据，"挂起"等待
			if c.waitCh == nil {
				c.waitCh = c.poller.AddFD(c.fd)
			}
			// ★ 这里就是 gopark 的地方
			<-c.waitCh
			// 被唤醒，继续循环重试
			continue
		}

		return 0, err
	}
}

// ============ 演示：用同步写法处理并发连接 ============

func handleConn(conn *PollConn, id int) {
	buf := make([]byte, 1024)
	for {
		n, err := conn.Read(buf)   // ★ 看起来是阻塞的
		if err != nil || n == 0 {
			fmt.Printf("连接 %d 关闭\n", id)
			return
		}
		fmt.Printf("连接 %d 收到 %d 字节: %q\n", id, n, buf[:n])
		// echo 回去
		syscall.Write(conn.fd, buf[:n])
	}
}

func main() {
	fmt.Println("=== Go netpoller 原理模拟 ===\n")

	// 这只是原理演示，真实实现在 runtime 里
	// 真正用的时候直接用 net 包就好：
	//
	//   listener, _ := net.Listen("tcp", ":8080")
	//   for {
	//       conn, _ := listener.Accept()
	//       go handleConn(conn)    // ★ 一个 goroutine 一个连接
	//   }
	//
	// 底层的 netpoller 保证了：
	//   · 10 万个 goroutine 只需要几个 OS 线程
	//   · 阻塞的 Read 不会阻塞 OS 线程

	fmt.Println("关键点:")
	fmt.Println("  1. 一个 goroutine 一个连接（编程模型简单）")
	fmt.Println("  2. Read 阻塞时，goroutine 挂起，OS 线程去跑别的 goroutine")
	fmt.Println("  3. epoll 事件到达时，goroutine 被唤醒")
	fmt.Println("  4. ★ 整个过程对业务代码完全透明")

	time.Sleep(100 * time.Millisecond)
}
```

### Reactor 模式

真实的网络框架用 Reactor 模式组织代码：

```
单 Reactor 单线程:
┌──────────────────────────────┐
│  Reactor (epoll_wait)         │
│    ├─ accept                  │
│    ├─ read                    │
│    ├─ decode + compute        │  ← 所有事都在一个线程
│    └─ write                   │
└──────────────────────────────┘
  优点：无锁、简单
  缺点：无法利用多核；一个慢请求拖垮所有
  例子：Redis

单 Reactor 多线程:
┌──────────────────────────────┐
│  Reactor (epoll_wait)         │
│    ├─ accept                  │
│    └─ read → 丢给线程池        │
└──────────┬───────────────────┘
           ▼
   ┌───┬───┬───┬───┐
   │ W │ W │ W │ W │   ← 业务处理在线程池
   └───┴───┴───┴───┘
   优点：业务处理可并行
   缺点：Reactor 仍是单点

多 Reactor 多线程（主从）:
┌──────────────────┐
│  Main Reactor    │  ← 只负责 accept
│  (epoll_wait)    │
└────────┬─────────┘
         │ 分发连接
    ┌────┼────┬────┐
    ▼    ▼    ▼    ▼
┌─────┬─────┬─────┬─────┐
│Sub R│Sub R│Sub R│Sub R│   ← 每个 Sub Reactor 一个线程 + 一个 epoll
└─────┴─────┴─────┴─────┘
   优点：充分利用多核，无锁（每个连接只属于一个 Reactor）
   例子：Netty、Nginx、Memcached
```

> **老陈**：**Go 的做法更简单——它不需要显式的 Reactor。**
>
> 因为 **goroutine + netpoller = 隐式的多 Reactor**：
> - netpoller 是一个后台 goroutine（相当于 Main Reactor）
> - 每个连接一个 goroutine（相当于轻量级的 Sub Reactor）
> - 调度器自动把 goroutine 分配到多个 P（多核）
>
> **这就是为什么 Go 的网络编程这么舒服——你写最简单的阻塞式代码，runtime 帮你实现了一个高效的多 Reactor。**

---

## 动手：手写一个 epoll 网络框架

不用 `net` 包，直接用 syscall 实现一个能跑的 echo 服务器：

```go
package main

import (
	"fmt"
	"net"
	"os"
	"syscall"
)

const (
	MaxEvents = 1024
	BufferSize = 4096
)

type EpollServer struct {
	listenFd int
	epfd     int
	// fd → 连接信息
	conns map[int]*Conn
}

type Conn struct {
	fd   int
	addr net.Addr  // 简化处理
	// 读缓冲区（处理 TCP 粘包）
	readBuf []byte
	// 写缓冲区（处理写不完整）
	writeBuf []byte
}

func NewEpollServer(addr string) (*EpollServer, error) {
	// 1. 创建监听 socket
	//    简化：用 net.Listen 创建，然后取出 fd
	listener, err := net.Listen("tcp", addr)
	if err != nil {
		return nil, err
	}
	file, err := listener.(*net.TCPListener).File()
	if err != nil {
		return nil, err
	}
	listenFd := int(file.Fd())

	// 2. 设置为非阻塞
	if err := syscall.SetNonblock(listenFd, true); err != nil {
		return nil, err
	}

	// 3. 创建 epoll
	epfd, err := syscall.EpollCreate1(0)
	if err != nil {
		return nil, err
	}

	s := &EpollServer{
		listenFd: listenFd,
		epfd:     epfd,
		conns:    make(map[int]*Conn),
	}

	// 4. 注册监听 socket
	event := &syscall.EpollEvent{
		Events: syscall.EPOLLIN,
		Fd:     int32(listenFd),
	}
	if err := syscall.EpollCtl(epfd, syscall.EPOLL_CTL_ADD, listenFd, event); err != nil {
		return nil, err
	}

	return s, nil
}

func (s *EpollServer) Run() error {
	events := make([]syscall.EpollEvent, MaxEvents)
	buf := make([]byte, BufferSize)

	fmt.Printf("服务器启动，监听中...\n")

	for {
		// ★ 核心：一次等待多个 fd
		n, err := syscall.EpollWait(s.epfd, events, -1)
		if err != nil {
			if err == syscall.EINTR {
				continue
			}
			return err
		}

		for i := 0; i < n; i++ {
			fd := int(events[i].Fd)

			if fd == s.listenFd {
				// 新连接
				s.accept()
			} else {
				// 已连接 socket 有事件
				if events[i].Events&syscall.EPOLLIN != 0 {
					s.handleRead(fd, buf)
				}
				if events[i].Events&syscall.EPOLLOUT != 0 {
					s.handleWrite(fd)
				}
				if events[i].Events&(syscall.EPOLLERR|syscall.EPOLLHUP) != 0 {
					s.closeConn(fd)
				}
			}
		}
	}
}

func (s *EpollServer) accept() {
	for {
		// ★ 非阻塞 accept，循环直到 EAGAIN
		//   （ET 模式必须循环；LT 模式可以只 accept 一次）
		nfd, _, err := syscall.Accept(s.listenFd)
		if err != nil {
			if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK {
				break   // 没有更多新连接了
			}
			fmt.Println("accept 错误:", err)
			break
		}

		// 设置为非阻塞
		syscall.SetNonblock(nfd, true)

		// 注册到 epoll
		event := &syscall.EpollEvent{
			Events: syscall.EPOLLIN | syscall.EPOLLET,   // ★ ET 模式
			Fd:     int32(nfd),
		}
		if err := syscall.EpollCtl(s.epfd, syscall.EPOLL_CTL_ADD, nfd, event); err != nil {
			syscall.Close(nfd)
			continue
		}

		s.conns[nfd] = &Conn{
			fd:      nfd,
			readBuf: make([]byte, 0, BufferSize),
		}
		fmt.Printf("新连接: fd=%d, 当前连接数=%d\n", nfd, len(s.conns))
	}
}

func (s *EpollServer) handleRead(fd int, buf []byte) {
	conn, ok := s.conns[fd]
	if !ok {
		return
	}

	for {
		// ★ ET 模式：必须循环读到 EAGAIN
		n, err := syscall.Read(fd, buf)
		if err != nil {
			if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK {
				break   // 数据读完了
			}
			// 真正的错误
			s.closeConn(fd)
			return
		}
		if n == 0 {
			// 对端关闭连接
			s.closeConn(fd)
			return
		}

		conn.readBuf = append(conn.readBuf, buf[:n]...)
	}

	// 处理完整的请求（简化：按行分割）
	for {
		idx := -1
		for i, b := range conn.readBuf {
			if b == '\n' {
				idx = i
				break
			}
		}
		if idx == -1 {
			break   // 没有完整的行
		}

		line := string(conn.readBuf[:idx])
		conn.readBuf = conn.readBuf[idx+1:]

		// 业务处理：echo
		response := append([]byte(line), '\n')
		conn.writeBuf = append(conn.writeBuf, response...)
	}

	// 尝试写回
	if len(conn.writeBuf) > 0 {
		s.tryWrite(conn)
	}
}

func (s *EpollServer) tryWrite(conn *Conn) {
	// 直接尝试写（大部分情况能一次写完）
	total := 0
	for total < len(conn.writeBuf) {
		n, err := syscall.Write(conn.fd, conn.writeBuf[total:])
		if err != nil {
			if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK {
				// 写缓冲区满了，剩余部分要等 EPOLLOUT
				conn.writeBuf = conn.writeBuf[total:]
				s.modifyEvent(conn.fd, syscall.EPOLLIN|syscall.EPOLLET|syscall.EPOLLOUT)
				return
			}
			s.closeConn(conn.fd)
			return
		}
		total += n
	}
	// 全部写完
	conn.writeBuf = conn.writeBuf[:0]
	// 取消关注 EPOLLOUT（否则会一直触发）
	s.modifyEvent(conn.fd, syscall.EPOLLIN|syscall.EPOLLET)
}

func (s *EpollServer) handleWrite(fd int) {
	conn, ok := s.conns[fd]
	if !ok {
		return
	}
	s.tryWrite(conn)
}

func (s *EpollServer) modifyEvent(fd int, events uint32) {
	event := &syscall.EpollEvent{
		Events: events,
		Fd:     int32(fd),
	}
	syscall.EpollCtl(s.epfd, syscall.EPOLL_CTL_MOD, fd, event)
}

func (s *EpollServer) closeConn(fd int) {
	delete(s.conns, fd)
	syscall.EpollCtl(s.epfd, syscall.EPOLL_CTL_DEL, fd, nil)
	syscall.Close(fd)
	fmt.Printf("连接关闭: fd=%d, 当前连接数=%d\n", fd, len(s.conns))
}

func main() {
	server, err := NewEpollServer(":8080")
	if err != nil {
		fmt.Fprintln(os.Stderr, "启动失败:", err)
		os.Exit(1)
	}
	if err := server.Run(); err != nil {
		fmt.Fprintln(os.Stderr, "运行错误:", err)
		os.Exit(1)
	}
}
```

**测试：**

```bash
# 终端 1：启动服务器
go run server.go

# 终端 2：测试
echo "hello" | nc localhost 8080
# 输出: hello

# 压测
for i in $(seq 1 10000); do
    (echo "test$i" | nc localhost 8080) &
done
```

### 关键实现的四个细节

**细节 1 · ET 模式必须循环读写到 EAGAIN**

```go
// ❌ 只读一次 → 可能漏数据 → 连接永久卡住
n, _ := syscall.Read(fd, buf)

// ✅ 循环读
for {
    n, err := syscall.Read(fd, buf)
    if err == syscall.EAGAIN { break }
    // ...
}
```

**细节 2 · 监听 socket 也要循环 accept**

```
ET 模式下，多个连接同时到达可能只通知一次
→ 必须循环 accept 直到 EAGAIN
```

**细节 3 · EPOLLOUT 要按需注册**

```
如果一直关注 EPOLLOUT，而写缓冲区总是空的
→ epoll_wait 会一直返回 → CPU 100%

正确做法：
  · 默认只关注 EPOLLIN
  · 有数据要写时，先直接尝试 write
  · 写不完（EAGAIN）才注册 EPOLLOUT
  · 写完后取消 EPOLLOUT
```

**细节 4 · TCP 粘包处理**

```
TCP 是字节流，没有消息边界
发送方发 3 次 10 字节，接收方可能一次收到 30 字节

解决：
  ① 定长消息
  ② 分隔符（\n）
  ③ 长度前缀（最常用）
     [length:4][payload]
     length 用大端序，明确字节序
```

---

## 第三层追问：为什么 Go 不需要这些复杂处理

> **小林**：这个框架好复杂，又要注意 ET、又要处理写缓冲、又要处理粘包。
>
> **老陈**：**所以你平时用 `net` 包就好了。** 我问你：`net.Conn.Read` 帮你做了什么？
>
> **小林**：……把非阻塞 read 包装成了阻塞的？
>
> **老陈**：对，还有呢？
>
> **小林**：缓冲？
>
> **老陈**：**`bufio.Reader` 才是缓冲。`net.Conn` 提供的是：**
> ① **goroutine 安全的**读写（多个 goroutine 可以并发读写同一个 Conn）
> ② **自动的 netpoller 集成**（阻塞 = goroutine 挂起，不是线程阻塞）
> ③ **deadline 机制**（`SetReadDeadline`，超时返回 error）
> ④ **优雅的关闭**（Close 会唤醒所有阻塞的读写）
>
> **这四点，如果自己用 epoll 实现，每一个都要几百行。**
>
> **小林**：那我什么时候需要自己写 epoll？
>
> **老陈**：**几乎不需要。** 除非：
> ① 你在写 Go runtime 本身
> ② 你需要绕过 netpoller 做一些特殊优化（比如 busy polling 降低延迟）
> ③ 你在写一个网络中间件，需要精细控制
>
> **但理解它怎么工作，能让你写出更好的 Go 网络代码。** 比如：

### 从 netpoller 原理推导出的四条实践

**① 不要在一个 goroutine 里读，另一个 goroutine 里写同一个 Conn？**

**错，这恰恰是推荐做法。**

```go
conn, _ := listener.Accept()

// 读 goroutine
go func() {
    buf := make([]byte, 4096)
    for {
        n, err := conn.Read(buf)
        if err != nil { break }
        handle(buf[:n])
    }
}()

// 写 goroutine
go func() {
    for msg := range sendCh {
        conn.Write(msg)
    }
}()
```

**因为 `net.Conn` 的 Read 和 Write 是独立的**，各自有自己的 netpoller 注册。**两个方向的阻塞互不干扰。**

**② 一定要设置 deadline**

```go
// ❌ 没有 deadline，对端一直不发送数据，goroutine 永久挂起
conn.Read(buf)

// ✅ 设置 deadline
conn.SetReadDeadline(time.Now().Add(30 * time.Second))
n, err := conn.Read(buf)
if err != nil {
    if netErr, ok := err.(net.Error); ok && netErr.Timeout() {
        // 超时处理
    }
}
```

**③ 避免大量短连接的 goroutine 泄漏**

```go
// ❌ 如果客户端不关闭连接，goroutine 永久挂起
go handleConn(conn)

// ✅ 用 context + deadline 控制生命周期
func handleConn(ctx context.Context, conn net.Conn) {
    defer conn.Close()
    go func() {
        <-ctx.Done()
        conn.Close()   // ★ Close 会唤醒阻塞的 Read
    }()
    // ...
}
```

**④ 理解 `SetReadDeadline` 的性能陷阱**

```go
// ❌ 每次 Read 前都 SetReadDeadline
for {
    conn.SetReadDeadline(time.Now().Add(30 * time.Second))   // ★ 系统调用！
    conn.Read(buf)
}
// 每次 SetReadDeadline 是一次 timer 操作，有锁竞争

// ✅ 只在必要时更新，或者用更长的 deadline
```

> **老陈**：**据我所知，很多 Go 服务的性能问题就出在这里。** 高频调用 `SetReadDeadline` 会导致 timer 的锁竞争。
>
> 如果你的 QPS 是 10 万，每秒就有 10 万次 timer 操作。

---

## 更深层的发问

### 问题 A：为什么 epoll 用红黑树而不是哈希表？

**哈希表查询是 O(1)，红黑树是 O(log n)。为什么 epoll 选红黑树？**

```
理由 1 · 内存效率
  红黑树节点按需分配，只存实际监控的 fd
  哈希表要预分配桶数组，fd 稀疏时浪费大
  （fd 通常是稀疏的：3, 7, 12, 19, 26...）

理由 2 · 无锁遍历友好
  红黑树可以中序遍历（有序）
  哈希表遍历顺序不确定

理由 3 · 历史原因
  epoll 在 2002 年进入 Linux 2.5.44
  当时内核里红黑树的实现刚稳定（2001 年引入）
  而且内核的内存分配（slab）对红黑树节点很友好

理由 4 · 实际性能差异小
  即使 10 万个 fd，log₂(100000) ≈ 17
  红黑树查找 17 次比较 vs 哈希表 1 次
  但 epoll_ctl 的调用频率远低于 epoll_wait
  ★ 瓶颈在 epoll_wait 的返回和事件处理，不在 epoll_ctl 的查找
```

> **老陈**：**这个问题的价值在于：它提醒你"理论复杂度"和"实际性能"不是一回事。**
>
> **epoll 的性能瓶颈从来不是"查找 fd 有多快"，而是：**
> - epoll_wait 的系统调用开销
> - 就绪事件的数量
> - 用户态处理每个事件的成本
>
> **所以优化的方向是减少系统调用次数、批量处理事件，而不是优化查找结构。**

### 问题 B：如果让你设计一个支持百万连接的网络框架？

> **老陈的提示**：想想这几个瓶颈——

**瓶颈 1 · 文件描述符限制**

```bash
# 系统级
cat /proc/sys/fs/file-max          # 可能需要调到几百万

# 进程级
ulimit -n                           # 默认 1024！

# 修改
# /etc/security/limits.conf
* soft nofile 1000000
* hard nofile 1000000
```

**瓶颈 2 · 内存**

```
每个连接:
  · 内核 socket 缓冲区: 读 16KB + 写 16KB = 32KB
  · Go 的 goroutine 栈: 2KB（最小）
  · 应用层缓冲区: 4-64KB

100 万连接 × 50KB = 50 GB   ★ 内存是主要瓶颈

优化：
  · 调小内核缓冲区（SO_RCVBUF / SO_SNDBUF）
  · 应用层用共享的 buffer pool
  · ★ 用边缘触发减少事件数
```

**瓶颈 3 · CPU**

```
每次 epoll_wait 返回 N 个事件，要处理 N 次
如果 100 万连接中有 10 万活跃，每秒处理 10 万次事件

优化：
  ① 批量读写（readv/writev，减少系统调用）
  ② 避免内存拷贝（sendfile、mmap）
  ③ 多 Reactor（每核一个 epoll）
  ④ busy polling（牺牲 CPU 换延迟）
```

**瓶颈 4 · Go 特有的：GC 压力**

```go
// ❌ 每个连接一个 buffer，100 万个 buffer
buf := make([]byte, 4096)

// ✅ 用共享的 buffer pool
var bufPool = sync.Pool{
	New: func() any {
		b := make([]byte, 4096)
		return &b
	},
}
```

---

## 思考题 ·【应用层】

**你的 Go 服务是长连接网关，维持 50 万 WebSocket 连接。发现：**
- **内存占用 40GB（远超预期）**
- **GC 频繁，STW 达到 50ms**
- **P99 延迟 200ms**

**请分析原因，给出优化方案，并估算优化后的效果。**

<details>
<summary>参考答案</summary>

### 先算账：40GB 内存从哪来

```
50 万连接，40GB 内存 → 平均每连接 80KB

拆解:
  ① 内核 socket 缓冲区:  读 16KB + 写 16KB = 32KB   ← 占 40%
  ② Go goroutine 栈:     2-8KB                       ← 占 5%
  ③ 应用层读缓冲:        4-64KB                      ← 占 40%★
  ④ 业务对象:            几 KB                        ← 占 15%

★ 主要问题在 ① 和 ③
```

**用工具验证：**

```bash
# 看 socket 缓冲区占用
cat /proc/net/sockstat
# sockets: used 500000
# TCP: inuse 500000 orphan 0 tw 0 alloc 500000 mem 300000
#                                                  ↑ 单位是页！
#                                                  300000 页 × 4KB = 1.2GB

# 看进程内存
cat /proc/<pid>/status | grep -E "VmRSS|VmSize"

# Go 层面
curl http://localhost:6060/debug/pprof/heap > heap.prof
go tool pprof -http=:8080 heap.prof
```

---

### 优化 1：调小内核 socket 缓冲区

```go
// 接受连接后设置
conn, _ := listener.Accept()
if tcpConn, ok := conn.(*net.TCPConn); ok {
    // ★ 设置较小的缓冲区
    //   默认可能是 16KB-64KB，我们设成 4KB
    tcpConn.SetReadBuffer(4096)
    tcpConn.SetWriteBuffer(4096)

    // 关闭 Nagle（WebSocket 场景通常要关）
    tcpConn.SetNoDelay(true)

    // 开启 keepalive
    tcpConn.SetKeepAlive(true)
    tcpConn.SetKeepAlivePeriod(60 * time.Second)
}
```

**效果**：
```
内核缓冲区从 32KB/连接 → 8KB/连接
50 万 × 24KB = 12GB 节省
★ 内存从 40GB 降到 28GB
```

**代价**：
- 吞吐量下降（缓冲区小，需要更频繁的系统调用）
- 如果单个消息很大，可能需要多次 read

**注意**：Linux 有自动调优机制（tcp_rmem / tcp_wmem），手动设置会禁用它。

```bash
# 看默认值
cat /proc/sys/net/ipv4/tcp_rmem
# 4096    131072  6291456
# ↑min    ↑default ↑max
```

---

### 优化 2：用共享 buffer pool（Go 特有的大头）

```go
// ❌ 当前做法：每个连接独立 buffer
func handleConn(conn net.Conn) {
	buf := make([]byte, 65536)   // ★ 50 万 × 64KB = 32GB！
	for {
		n, _ := conn.Read(buf)
		process(buf[:n])
	}
}

// ✅ 优化：分级 buffer pool
type BufferPool struct {
	pools []sync.Pool   // 4KB, 16KB, 64KB 三档
}

var bufferPool = &BufferPool{
	pools: []sync.Pool{
		{New: func() any { b := make([]byte, 4096); return &b }},
		{New: func() any { b := make([]byte, 16384); return &b }},
		{New: func() any { b := make([]byte, 65536); return &b }},
	},
}

func (p *BufferPool) Get(size int) *[]byte {
	idx := 0
	if size > 16384 {
		idx = 2
	} else if size > 4096 {
		idx = 1
	}
	return p.pools[idx].Get().(*[]byte)
}

func (p *BufferPool) Put(buf *[]byte) {
	size := cap(*buf)
	idx := 0
	if size > 16384 {
		idx = 2
	} else if size > 4096 {
		idx = 1
	}
	*buf = (*buf)[:cap(*buf)]   // 重置长度
	p.pools[idx].Put(buf)
}

func handleConn(conn net.Conn) {
	for {
		bufp := bufferPool.Get(65536)
		n, _ := conn.Read(*bufp)
		process((*bufp)[:n])
		bufferPool.Put(bufp)   // ★ 归还
	}
}
```

**为什么能省这么多？**

```
关键：WebSocket 连接的消息是"突发"的

一个连接在 1 秒内的消息:
  · 大部分时间：0 条消息（空闲）
  · 偶尔：1-2 条消息

如果每个连接常驻 64KB buffer:
  → 50 万 × 64KB = 32GB，但 99% 的时间是浪费的

如果用 pool:
  → 只有活跃的连接有 buffer
  → 假设 1% 的连接同时活跃（5000 个）
  → 5000 × 64KB = 320MB
  ★ 省了 100 倍
```

**但要注意 Go 的 GC 问题**：

`sync.Pool` 里的对象在 GC 时会被清空。如果你的 buffer pool 很大，反而会增加 GC 压力。

**更好的方案：用大块的 `[]byte` 自己切分**

```go
// ★ 一次性分配一大块，自己管理
//   GC 只看到一个 []byte，完全不扫描
type Arena struct {
	data []byte
	free []int   // 空闲块列表
}

var globalArena = &Arena{
	data: make([]byte, 2<<30),   // 2GB 一次性分配
	// 切成 64KB 的块
}

// 分配一个块
func (a *Arena) Alloc() []byte {
	if len(a.free) == 0 {
		return nil   // 满了
	}
	idx := a.free[len(a.free)-1]
	a.free = a.free[:len(a.free)-1]
	offset := idx * 65536
	return a.data[offset : offset+65536]
}
```

**效果**：
```
应用层缓冲从 32GB 降到 2GB（预分配）+ 少量活跃 buffer
★ 内存从 28GB 降到 10GB 左右
```

---

### 优化 3：减少 goroutine 数量（降低 GC 压力）

**这是 STW 50ms 的根源。**

```
STW #1 要扫描所有 goroutine 的栈
50 万个 goroutine × 平均 4KB 栈 = 2GB 要扫描
→ STW 几十 ms
```

**方案 A：合并 goroutine（用事件驱动）**

```go
// ❌ 每连接 2 个 goroutine（读 + 写）= 100 万个
go readLoop(conn)
go writeLoop(conn)

// ✅ 用单 goroutine + select 处理一个连接
//    还是 50 万个，但少了一半
func handleConn(conn net.Conn) {
	for {
		select {
		case msg := <-sendCh:
			conn.Write(msg)
		default:
			conn.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
			n, _ := conn.Read(buf)
			if n > 0 { process(buf[:n]) }
		}
	}
}
```

**方案 B：多连接复用 goroutine（真正的解法）**

```go
// ★ 一个 goroutine 处理 N 个连接
//   用 epoll 或者 Go 的 netpoller 批量等待
type ConnGroup struct {
	conns  map[int]*Conn
	sendCh chan SendTask
}

func (g *ConnGroup) Run() {
	// 用 syscall.EpollWait 或者更简单的：
	// 轮询 + 短 timeout（但这样 CPU 会高）

	// Go 的做法：每个连接一个 goroutine，但用更少的内存
}
```

**方案 C：分离"连接管理"和"业务处理"**

```
架构调整:
  连接层（50 万 goroutine，极轻量，只做收发）
      ↓ channel
  业务层（几百个 goroutine，做实际处理）

★ 连接层的 goroutine 栈要保持很小（不要有深调用）
★ 业务层的 goroutine 少，GC 扫描快
```

**方案 D：最直接——升级 Go 版本 + 调参**

```go
// Go 1.19+
debug.SetMemoryLimit(20 << 30)   // 20GB 软限制
// 效果：GC 更频繁但每次更快，避免长时间 STW

// 或者
debug.SetGCPercent(400)   // 减少 GC 频率
```

---

### 优化 4：减少分配（治本）

```go
// ❌ 每个消息都分配
func process(msg []byte) {
	header := parseHeader(msg)          // 分配
	body := msg[header.Len:]            // 切片（不分配，但引用大 buffer！）
	json.Unmarshal(body, &req)          // ★ 分配很多
	resp := buildResponse(&req)         // 分配
	data, _ := json.Marshal(resp)       // ★ 分配很多
	sendCh <- data
}

// ✅ 优化
func process(msg []byte, scratch *Scratch) {
	// 1. 用 json.Decoder 复用
	// 2. 用 easyjson / msgpack 代替 encoding/json（快 3-5 倍，分配少 80%）
	// 3. 用 scratch buffer 复用响应对象
	// 4. 避免在热路径上用 fmt.Sprintf
}
```

**具体建议：**

```go
// ① 用 msgpack/protobuf 代替 JSON
//    JSON:  解析 1KB 消息，约 20 次分配
//    MsgPack: 约 3 次分配

// ② 用 sync.Pool 复用请求/响应对象
var reqPool = sync.Pool{
	New: func() any { return new(Request) },
}

// ③ 避免在热路径用 fmt
//    ❌ fmt.Sprintf("user:%d", id)     → 3 次分配
//    ✅ 用 strconv.AppendInt 到复用的 buffer

// ④ 用 strings.Builder 代替字符串拼接
var sb strings.Builder
sb.Grow(256)
```

---

### 优化效果估算

| 优化项 | 内存节省 | GC 改善 | 工作量 |
|:---|:---|:---|:---|
| **调小 socket 缓冲** | 12 GB | 无 | 1 小时 |
| **buffer pool** | 20 GB | 大 | 2 天 |
| **减少 goroutine** | 2 GB | **极大** | 1 周 |
| **减少分配** | 5 GB | 大 | 3 天 |
| **MemoryLimit 调参** | 0 | 中 | 10 分钟 |

**预期结果：**

```
优化前:
  内存 40GB, STW 50ms, P99 200ms

优化后（做完前两项）:
  内存 12GB, STW 20ms, P99 100ms

优化后（做完全部）:
  内存 8GB, STW < 5ms, P99 < 30ms
  ★ 提升 6-7 倍
```

---

### 执行顺序

```
第 1 步: MemoryLimit 调参        10 分钟，立刻见效
第 2 步: 调小 socket 缓冲区      1 小时，省 12GB
第 3 步: pprof 找分配热点        半天，定位真正的元凶
第 4 步: buffer pool + arena     2 天，省 20GB
第 5 步: 减少分配（换序列化）     3 天，改善 GC
第 6 步: 架构调整（减少 goroutine）1 周，彻底解决 STW
```

**每一步之后都要测量。** 因为瓶颈会转移。

---

### 一句话总结

**长连接网关的内存问题，90% 是"每个连接常驻资源"造成的。**

核心思路：
1. **共享 > 独占**：buffer 用 pool 而不是每连接一个
2. **按需 > 预留**：只有活跃连接才占资源
3. **减少 goroutine**：这是 Go 特有的问题，STW 与 goroutine 数量直接相关
4. **减少分配**：GC 压力是一切性能问题的放大器

**这四条，本质上都是第 1 章讲的"按需分配"和第 3 章讲的"GC 友好"的应用。**

</details>

---

## 小结：这一节你应该带走的东西

1. **I/O 模型的演进是"减少无效等待"的历史**：阻塞+多线程 → 非阻塞轮询 → select/poll → epoll。

2. **epoll 的三个设计**：红黑树存兴趣列表、就绪链表存事件、回调机制通知。优势在"大量连接少量活跃"。

3. **LT 和 ET 的本质区别在"内核是否重新检查状态"**。ET 必须循环读写到 EAGAIN，否则永久卡死。**99% 的场景用 LT。**

4. **Go 的 netpoller = 隐式的多 Reactor**：netpoller 后台 goroutine + 每连接 goroutine + 调度器多核分发。你写最简单的阻塞代码，runtime 帮你实现高性能。

5. **手写 epoll 框架的四个细节**：ET 循环读写、监听 socket 循环 accept、EPOLLOUT 按需注册、TCP 粘包处理。

6. **长连接网关的优化核心**：共享 buffer、按需分配、减少 goroutine、减少分配。

---

## 下一节

[02 · 分布式共识：Raft 完整实现](./02-分布式共识-Raft完整实现.md)

这是本章的重头戏，也是你"给行业提供解决方案"能力的又一个体现。

> **老陈的预告**：Raft 的论文只有 18 页，但真正理解它需要你亲手实现一遍。
>
> 特别是那个著名的问题：**"为什么 leader 只能提交当前 term 的日志？"** —— 我会带你亲手构造出那个反例，而不是告诉你结论。
