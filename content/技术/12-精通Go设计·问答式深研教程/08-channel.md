# 08 channel：CSP 落地、内存模型、select 的精妙

## 开篇提问

Go 有一句著名的口号：

> **不要通过共享内存来通信，而要通过通信来共享内存。**
> (Don't communicate by sharing memory; share memory by communicating.)

先别急着点头。这句话听起来很漂亮，但请你先回答一个更尖锐的问题：

**"通过 channel 通信"和"通过加锁共享内存"相比，channel 到底解决了什么？它真的比锁更安全、更简单吗？还是它只是把"锁的复杂"换成了"另一套复杂"？**

想清楚这个问题，你才算真正理解 channel，而不是人云亦云地背诵那句口号。

---

## 子主题一：channel 是 CSP 的 Go 落地

channel 的设计源头，是 1978 年 Tony Hoare 提出的 **CSP（Communicating Sequential Processes，通信顺序进程）** 理论。CSP 的核心思想是：

> 并发不是"多个线程共享可变状态"，而是"多个独立的顺序进程，通过显式的通信原语来协作"。

在 CSP 的世界观里，没有"共享变量 + 锁"，只有"进程 + 消息通道"。每个进程内部是顺序的、干净的，进程之间通过通道传递消息来同步和交换数据。

Go 把 CSP 落成了一个具体的语言特性——**channel**：

```go
ch := make(chan int)      // 无缓冲 channel
ch <- 42                  // 发送
v := <-ch                 // 接收
```

channel 有几个关键语义，你要死死记住：

1. **发送和接收是同步点。** 无缓冲 channel 上，发送方必须等到有接收方，接收方必须等到有发送方——它们在 channel 上"会合"。
2. **有缓冲 channel 是异步的。** 缓冲没满，发送立即返回；缓冲没空，接收立即返回；满了/空了才阻塞。
3. **channel 是并发安全的。** 多个 goroutine 可以安全地同时往一个 channel 收发，运行时保证不会撕裂数据。
4. **channel 可以被关闭。** 关闭后，还能把缓冲里的数据读完，读完之后再读会得到零值 + `ok=false`。

这四条语义，就是 channel 的全部"魔法"。它们不神秘，但组合起来，能表达几乎所有并发协作模式：信号、互斥、限流、扇出扇入、超时、取消……

---

## 子主题二：channel 到底解决了什么

回到开篇那个尖锐的问题。我的答案可能和教科书不太一样，你听听看：

**channel 没有消灭复杂性，它把复杂性从"数据层面"转移到了"协作层面"。**

锁解决的是"**互斥访问共享数据**"——它保护的是**数据**。你用锁保证"同一时刻只有一个 goroutine 改这块内存"。锁的问题在于：**锁和它保护的数据之间，没有语言层面的强制绑定。** 你得靠纪律和约定，记住"改这个字段前要加这把锁"。一旦忘了，或者加错锁，就是数据竞争。而且锁把"临界区"写得到处都是，程序的控制流里充满了加锁解锁，可读性差、容易死锁。

channel 换了个思路：**不让 goroutine 直接共享数据，而是把"数据的所有权"通过 channel 传递。** 当一个值被送进 channel，它的"所有权"就从发送方转移给了接收方——同一时刻，只有一个 goroutine 拥有这个值。**这本质上也是一种互斥，只是把"锁住数据"换成了"交接所有权"。**

所以 channel 真正的好处不是"更安全"（channel 用错了也会死锁、也会泄漏），而是：

1. **让"谁在什么时候拥有哪个数据"变得显式。** 数据所有权随消息流动，控制流更清晰。
2. **把"同步"和"数据传递"合并成一个操作。** 锁只做同步，数据还得另外传；channel 一次收发，既同步了，又传了数据。
3. **天然适合表达"数据流"。** 管道（pipeline）、扇出扇入、生产者消费者，用 channel 表达特别自然。

但也要诚实：**channel 不是银弹。** 对于"多个 goroutine 频繁读写同一份共享状态"（比如一个共享计数器、一个共享缓存），channel 反而别扭——你得把所有读写都封装成"发消息 + 等结果"，绕一大圈。这时用锁（Mutex）或原子操作（atomic）更直接。**Go 的设计者自己也说：channel 和锁各有适用场景，别迷信任何一边。** 那句口号是"推荐默认用 channel 表达协作"，不是"禁止用锁"。

---

## 子主题三：channel 的内存模型——happens-before

这部分是 channel 最硬核、也最容易出面试题的地方：**channel 到底提供了哪些内存可见性保证？**

内存模型（第 15 章会系统讲）的核心概念是 **happens-before（先于关系）**：如果操作 A happens-before 操作 B，那么 A 的结果对 B 可见。

channel 提供的关键 happens-before 规则：

1. **发送 happens-before 对应的接收完成。** 你在 `ch <- v` 之前写的所有内存操作，接收方 `<-ch` 返回后，一定都能看到。
2. **关闭 channel happens-before 接收到"零值 + ok=false"。** 关闭前的所有写入，对"读到 channel 已关闭"的接收方可见。
3. **第 N 次接收 happens-before 第 N+C 次发送完成**（C 是缓冲容量）。对无缓冲 channel（C=0），就是"接收 happens-before 发送"。

这些规则的意义在于：**只要数据是通过 channel 传递的，你就不需要额外的锁或 atomic，就能保证"发送方写入的值，接收方一定看到"。** channel 内部的锁和内存屏障，替你保证了跨 goroutine 的可见性。

举个经典例子：

```go
var data int
done := make(chan struct{})

// goroutine 1
data = 42
close(done)

// goroutine 2
<-done
fmt.Println(data)   // 一定是 42，因为 close(done) happens-before <-done
```

这里 `data = 42` 和 `<-done` 之间没有锁，但 `fmt.Println(data)` 一定打印 42。为什么？因为 `close(done)` 提供了 happens-before 保证——关闭前的写，对读到关闭的 goroutine 可见。**channel 是 Go 里最常用的"同步原语"，它的 happens-before 保证，是你写并发代码时最该依赖的东西。**

---

## 子主题四：select 的精妙

`select` 是 Go 并发里最精妙、也最容易被低估的构造。它解决的问题是：**同时等待多个 channel 的操作，哪个先就绪就执行哪个。**

```go
select {
case v := <-ch1:
    // ch1 有数据
case ch2 <- v:
    // ch2 能发送
case <-timeout:
    // 超时
default:
    // 都不就绪，立即执行（非阻塞）
}
```

select 的几个精妙之处：

**第一，随机选择。** 当多个 case 同时就绪，select **随机**选一个执行，而不是按代码顺序。为什么要随机？因为如果总是优先第一个 case，饥饿的 case 可能永远轮不到，而且"依赖 case 顺序"的代码会变成隐藏 bug。随机化，又是 Go 那个"用随机性打断坏依赖"的哲学（和 map 遍历随机化如出一辙）。

**第二，default 让 select 非阻塞。** 加 `default` 后，select 就不会阻塞等待，而是"有就绪就干，没就绪走 default"。这让"非阻塞收发"成为可能，也是很多"优雅退出""限流"模式的基石。

**第三，select 是"多路复用"的语言级表达。** 底层它对应的是调度器里的一次"多路等待"：goroutine 把自己挂到所有相关 channel 的等待队列上，哪个 channel 先有动静，就唤醒它执行对应 case。**一个 select，等于同时注册了 N 个等待，这是用锁/条件变量很难写对的逻辑。** 这也是 channel 相对锁的一个真实优势：多路等待用锁写起来极其繁琐、易错，用 select 就几行。

**第四，nil channel 在 select 里的妙用。** 一个 `nil` channel，收发都会**永久阻塞**。这听起来没用，但在 select 里它是宝贝——你可以通过"把某个 channel 设成 nil"来**动态关闭某个 case**：

```go
var ch chan int  // nil
select {
case v := <-ch:  // 永久阻塞，相当于这个 case 被"禁用"
case <-done:
}
```

通过运行时把某些 case 对应的 channel 置 nil，你就能动态地"开关"select 的分支，这在写状态机、优雅关闭时特别有用。这个 trick 是 Go 并发编程里的"隐藏技能"。

---

## 子主题五：channel 的坑——死锁、泄漏、关闭

channel 不只有甜，也有雷。三个最常见的坑：

**坑一：向已关闭的 channel 发送，会 panic。** `close(ch)` 之后再 `ch <- v`，直接 panic。所以要遵守一条铁律：**"只有发送方关闭 channel，绝不关闭接收方会用的 channel"**（除非你能保证没有并发的发送）。多个发送方时，更安全的做法是用 `sync.Once` 或专门的协调 goroutine 来关闭。

**坑二：从已关闭的 channel 接收，不会阻塞，而是得到零值。** `close` 后，缓冲里的数据还能读完，读完后再读就得到零值 + `ok=false`。所以接收方要用 `v, ok := <-ch` 来判断 channel 是否已关闭，别光看值。

**坑三：goroutine 泄漏。** 如果一个 goroutine 一直阻塞在 `ch <- v` 或 `<-ch` 上，而没人来接收或发送，这个 goroutine 就永远挂在那，**泄漏**了。大量泄漏的 goroutine 会占着内存、占着调度资源，最后拖垮程序。所以生产代码里，**凡是会阻塞的收发，都要想清楚"谁来解救我"**——通常靠 `select + done/超时` 来兜底。

---

## 子主题六：拆开 channel——hchan 内部到底有什么

前面我们把 channel 当黑盒用了五节。现在拆开看看。为什么值得拆？因为**你只有知道它内部有什么，才能解释它的一切性能特征和诡异行为**。

先问一个问题：如果让你用一把锁实现一个 channel，你会怎么做？

你大概会这么写：

```go
type MyChan struct {
    mu   sync.Mutex
    buf  []int
    cond *sync.Cond
}
```

不难。但你很快会发现三个麻烦：

1. 阻塞的发送方和阻塞的接收方，得分别排队，唤醒时要"精准投喂"——不能随便叫醒一个，否则它可能还是干不了活。
2. 唤醒一个挂起的 goroutine 是有成本的（要把它从等待队列摘下来、交给调度器、等待被调度），如果每次收发都要这么一遭，慢。
3. 多个 goroutine 同时收发同一条 channel 是常态，锁竞争会非常凶。

Go 运行时的 channel（内部叫 hchan）就是围绕这三个麻烦打磨出来的。它不神秘，概念上只有四样东西：

**第一样：环形缓冲 buf。**
有缓冲 channel 的数据区，是一块连续内存，按环形队列使用：有读下标和写下标（概念上就这么理解），写满回绕到开头。为什么是环形而不是链表或切片？因为 channel 是"先进先出"队列，容量固定，环形缓冲能做到**入队出队都是 O(1)、零额外分配、缓存局部性极好**。这也是为什么 `make(chan int, 100)` 之后，这 100 个槽位的内存是一次性申请好的，之后收发数据不再分配——**channel 的高性能，很大一部分来自"缓冲是一次性分配、之后只拷贝"**。

顺带解答一个常见误解：`len(ch)` 返回的是"缓冲里当前有多少个元素"，`cap(ch)` 是"缓冲容量"。**无缓冲 channel 的 cap 是 0，len 永远是 0**——它根本没有地方存东西。

**第二样：发送等待队列 sendq。**
当一个 goroutine 执行 `ch <- v` 而发不出去（无缓冲没人接，或有缓冲但满了），它会把自己**连同待发送的值**一起挂进这个队列，然后挂起（park），让出 CPU。等关键的是：等待者不只是"排队"，它已经**准备好了要交接的数据**，一旦对端出现，交接就能立刻发生。

**第三样：接收等待队列 recvq。**
对称地，执行 `<-ch` 但没东西可收的 goroutine，把自己连同"接收变量的地址"挂进 recvq 挂起。同样，它已经准备好了**接收目标**。

**第四样：互斥锁。**
保护上面所有结构的内部锁。注意：**这把锁只在 channel 内部极短的代码路径上持有**（改一下缓冲下标、搬一下数据、摘一个等待者），**绝不会在"阻塞等待"期间持有**。这一点是 channel 能扛住高并发的前提——如果锁会跨越阻塞期，channel 早就没法用了。

现在把这四样东西拼起来，看一次收发的完整流程。以有缓冲 channel 为例：

**发送 `ch <- v` 时：**
- 先看 recvq 里有没有已经等着的接收者。**有**——太好了，绕开缓冲，把值**直接交给那个接收者**，然后唤醒它。这就是"无缓冲 channel 上的直接交接"，也是为什么无缓冲发送在有接收者等待时并不慢：数据根本没进缓冲，走了一条"直达"快路径。
- recvq 空，但缓冲还有空位——把值写进环形缓冲的写位置，写下标前移，加锁解锁，直接返回，**不阻塞**。
- 缓冲也满了——把自己挂进 sendq，挂起等待。

**接收 `<-ch` 时，完全对称：**
- 先看 sendq 里有没有等着的发送者。**有**——直接从它手里拿值（如果是无缓冲 channel，这就是唯一路径），然后唤醒那个发送者。
- sendq 空，但缓冲里有数据——从读位置取一个，读下标前移，返回。
- 缓冲也空——把自己挂进 recvq，挂起。

看懂了吗？**"先查对端等待队列，再查缓冲"这个顺序，是 channel 语义的灵魂。** 它意味着：只要收发双方同时在场，数据就走"手递手"的直达路径，缓冲只是"一方没到场时的暂存区"。这也解释了一个反直觉的事实——**一个 `make(chan int, 100)` 的 channel，即使缓冲全空，只要有接收者在等，发送依然是直达的**；反过来，缓冲里即使还有数据，只要有发送者阻塞着（说明缓冲是满的），接收也会先从发送者手里拿。

还有一个细节值得说：**关闭 channel 时，运行时会把 recvq 里所有等待者全部唤醒，让它们拿到零值 + `ok=false`；同时把 sendq 里所有等待者全部唤醒，让它们 panic。** 这就是为什么"关闭 channel"是一个天然的**广播**机制——一次 close，唤醒所有人。这个特性是"优雅关闭""取消传播"的底层基础，我们后面会反复用到。

最后提醒一句：这些是实现层面的概念模型，**具体字段和代码路径随 Go 版本演进一直在优化**（在 `runtime/chan.go` 里）。你该记住的是这套概念模型，而不是任何字段名。

---

## 子主题七：无缓冲 vs 有缓冲——会合点与信箱

有了 hchan 的模型，现在可以真正回答那个被问烂了的问题：**什么时候用无缓冲，什么时候用有缓冲？**

先给两个比喻，够狠够准：

**无缓冲 channel 是"两人当面交接"——一个会合点（rendezvous）。** 你把一个包裹递给我，必须我伸手接了，你的手才能松开。交接完成的那一刻，你和我**同时**确定了一件事：包裹已经在我手上了。所以无缓冲 channel 的真正价值不是"传数据"，而是**"同步"**——它天然携带了"我方已完成到此处"的信息。**这是因果关系的传递，不是数据的传递。**

**有缓冲 channel 是"信箱/传送带"——一个异步队列。** 你把包裹放进信箱就走，我什么时候来取你不知道。它的价值是**解耦两侧的速度抖动**：生产者偶尔爆发一下，缓冲吸收掉；消费者偶尔卡顿一下，缓冲顶上。**但它也切断了因果**——你把包裹放进信箱的瞬间，什么都还没发生。

这个"切断因果"的代价，很多人没想清楚。举个例子：

```go
done := make(chan struct{}, 1)   // 错误示范：用有缓冲 channel 做"完成通知"
go func() {
    work()
    done <- struct{}{}
}()
<-done
fmt.Println("work 完成了")   // 真的完成了吗？
```

看起来没问题。但如果 `work()` 之后还有清理逻辑，或者你本意是"goroutine 已退出"，那 `done <- struct{}{} ` 之后 goroutine 还在跑——**缓冲让它不再是一个会合点，你听到的不是"我干完了"，只是"我投了个信"**。想表达"我干完了并且已经放手"，必须用无缓冲 channel，或者 `close(ch)`。

所以第一条经验法则：

> **要同步（传递因果关系、确认对端状态）→ 用无缓冲，或用 close 广播。**
> **要解耦（吞吐削峰、消除抖动）→ 用有缓冲。**

那缓冲容量该设多大？这是被问得最多、也最容易被神化的问题。说实话：**默认值应该是 0 或 1，除非你有具体理由。**

- **0（无缓冲）**：需要同步语义时。信号、通知、交接所有权。
- **1**：经典的"信号/最新值"容量。够用，且**不制造缓冲积压**。比如"只要有一个待处理信号就够了"的场景，`cap=1` 配合非阻塞发送，天然退化成一个"置位标志"。
- **N（较大）**：有明确的吞吐匹配需求时。比如生产者是"批量读磁盘"，消费者是"逐条处理"，N 取"一批的大小"或一个能吸收典型抖动的量级（几十到几百）。**N 不是越大越好**——缓冲是内存，缓冲里积压的数据是"延迟"，缓冲越大，你掩盖的问题越多，背压（backpressure）信号来得越晚。一个塞了 10 万条消息的缓冲，往往不是缓冲设计得好，而是下游早就崩了而你还不知道。

还有个容易忽略的点：**有缓冲 channel 会"吃掉"背压**。生产者发现"发送不阻塞"，就会一直生产，直到缓冲满。这在内存敏感的场景是灾难。无缓冲或 `cap=1` 的 channel，会让生产者在下游跟不上的第一时间就阻塞，**把压力传导回去**——这叫背压，是流式系统的生命线。所以当你不确定时，**选小缓冲，让问题早暴露**。

最后补一个纯实用性结论：信号类 channel 用 `chan struct{}`，不用 `chan bool`。`struct{}` 不占内存，语义上也更诚实——"我在意的只是事件发生了，不是值"。

---

## 子主题八：模式一——pipeline（管道）

channel 最自然的用法，是把程序组织成**数据流**：上游产出，中游变换，下游消费，每一段是一个独立 goroutine，段与段之间用 channel 连接。这就是 pipeline。

为什么 pipeline 值得单独讲？因为它同时解决了三件事：

1. **并发**：相邻阶段天然并行——第一阶段在处理第 N+1 条时，第二阶段在处理第 N 条。
2. **解耦**：每个阶段只认 channel 类型，不认上下游是谁，可以独立测试、独立替换。
3. **背压**：无缓冲或小缓冲会自动传导压力，下游慢了上游自然慢下来，不会撑爆内存。

看一个完整例子：从一个整数切片里，取出偶数，平方，再收集起来。

```go
// 阶段一：产生数据
func gen(nums ...int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)          // 铁律：谁发送谁关闭
        for _, n := range nums {
            out <- n
        }
    }()
    return out
}

// 阶段二：变换（过滤 + 映射）
func sq(in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for n := range in {       // channel 关闭时循环自动退出
            if n%2 == 0 {
                out <- n * n
            }
        }
    }()
    return out
}

func main() {
    for n := range sq(gen(1, 2, 3, 4, 5, 6)) {
        fmt.Println(n)   // 4, 16, 36
    }
}
```

这段代码里有四个必须内化的细节：

**细节一：`defer close(out)` 写在 goroutine 里，由发送方关闭。** 这是"谁发送谁关闭"铁律的直接体现。上游关闭了 `in`，中游的 `for range in` 就会退出，然后中游关闭 `out`，下游的 `for range` 也退出——**关闭动作沿着管道一级一级传播下去**，这是一种非常优雅的"流结束"信号。

**细节二：`for range ch` 会在 channel 关闭且取空后自动退出。** 没有它，你得写 `v, ok := <-ch; if !ok { break }`。能用 range 就用 range。

**细节三：返回类型用 `<-chan int`（只读方向）。** 这是 Go 类型系统送给你的礼物：`gen` 的调用方**在编译期就无法往返回的 channel 里写东西**，从根上杜绝了"接收方关闭 channel"这个经典事故。方向类型不是装饰品，**它是用类型表达的"所有权契约"**。这个习惯要刻进肌肉记忆。

**细节四：每个阶段都是"一进一出"的纯函数。** 输入 `<-chan T`，输出 `<-chan U`。这种形状的东西可以无限串联、自由组合。

现在，一个更尖锐的问题：**pipeline 里如果某个阶段出错，或者下游提前不想消费了，怎么办？**

上面这段代码有个隐蔽缺陷：如果 `main` 在读到一半就 `break` 了，那么上游所有 goroutine 都会**永久阻塞在发送上**——泄漏。管道越长，泄漏越多。这就是为什么生产级的 pipeline 必须带**取消信号**，也就是 `context`。这个课题我们留到子主题十四专门展开。

---

## 子主题九：模式二——fan-out / fan-in（扇出扇入）

pipeline 解决了"串联"，但如果某个阶段是 CPU 密集的，单 goroutine 处理会成为瓶颈。怎么办？**开多个 goroutine 同时处理同一个输入 channel**——这就是 fan-out（扇出）；然后把多个结果 channel **合并成一个**——这就是 fan-in（扇入）。

先别急着看代码，想一个问题：**多个 goroutine 同时从一个 channel 读，安全吗？需要加锁吗？**

答案是：**完全安全，不需要锁，而且这正是正确的做法。** channel 的接收操作本身是原子的——多个接收者竞争同一个 channel，运行时保证每条消息**只被其中一个**接收者拿到。这不是什么"碰巧能工作"，而是 channel 语义的一部分：**一条消息，恰好一个接收者**。

这个性质极其强大。它意味着你得到了一个**免费的、无锁的、负载均衡的任务队列**——多个 worker 从同一个 channel 取任务，天然实现"谁闲谁干"，比任何手写调度都公平。这就是 Go 里实现并发任务分发最地道的方式。

```go
// fan-out：启动 n 个 worker 共同消费 in，各自返回结果 channel
func sqWorkers(in <-chan int, n int) []<-chan int {
    outs := make([]<-chan int, 0, n)
    for i := 0; i < n; i++ {
        out := make(chan int)
        outs = append(outs, out)
        go func(out chan<- int) {
            defer close(out)
            for v := range in {
                out <- v * v
            }
        }(out)
    }
    return outs
}
```

注意 fan-out 的一个致命易错点：**循环变量捕获**。老版本 Go（1.22 之前）里 `for i := range` 的 `i` 是被所有迭代共享的，直接在闭包里用会踩坑。上面我把 `out` 作为参数传进去，就是最稳的写法。**Go 1.22 之后循环变量语义改了，但"显式传参"依然是值得保留的习惯**——它让代码意图不依赖语言版本。

fan-in 呢？把 `[]<-chan int` 合并成一个：

```go
func merge(cs ...<-chan int) <-chan int {
    var wg sync.WaitGroup
    out := make(chan int)

    // 每个输入 channel 起一个 goroutine，把数据搬进 out
    output := func(c <-chan int) {
        defer wg.Done()
        for n := range c {
            out <- n
        }
    }

    wg.Add(len(cs))
    for _, c := range cs {
        go output(c)
    }

    // 关键：等所有搬运工都干完，才关闭 out
    go func() {
        wg.Wait()
        close(out)
    }()

    return out
}
```

这段代码里最值钱的是最后那个 **"等待并关闭"的 goroutine**。为什么不能直接 `wg.Wait(); close(out); return out`？因为 `out <- n` 会阻塞，如果 merge 自己先 Wait，就死锁了——搬运工等着有人消费，merge 等着搬运工结束。**必须先 return 让下游开始消费，再用一个独立 goroutine 等所有人干完再关。**

这个 `WaitGroup + 独立 goroutine 关闭` 的组合，是**多发送方场景下的标准关闭姿势**，你会反复用到。把它背下来：

> **多个 goroutine 往同一个 channel 写 → 用 WaitGroup 计数，等全部 Done 后，由一个额外 goroutine 关闭该 channel。**

还有个优雅细节：`sync.WaitGroup` 在这里表达的是"还有 N 个发送方活着"。**关闭 channel 的前置条件，就是"确认没有任何发送方了"**。这两句话是同一件事的两种说法。

---

## 子主题十：模式三——worker pool（工作池）

fan-out/fan-in 已经很接近 worker pool 了，但 worker pool 有个额外诉求：**worker 是长期存活的，任务是不断投喂进来的**。它解决的是"控制并发度"这件事。

为什么需要控制并发度？问你个实际问题：你要抓取 10 万个 URL，开 10 万个 goroutine 一把梭，会怎样？

goroutine 很便宜（初始栈才几 KB），但**便宜不等于免费**。10 万个并发请求会：打满对端（可能被封 IP）、耗尽本地文件描述符、让 GC 扫描的对象图暴涨、让调度器在 10 万个可运行 goroutine 上疲于奔命。**这不是"用满资源"，这是"自我拒绝服务"。** 正确的做法是：固定 N 个 worker，任务排队，并发度严格等于 N。

```go
type Job struct {
    ID   int
    Data string
}
type Result struct {
    JobID int
    Out   string
}

func workerPool(jobs <-chan Job, results chan<- Result, n int) {
    var wg sync.WaitGroup
    for i := 0; i < n; i++ {
        wg.Add(1)
        go func(id int) {
            defer wg.Done()
            for job := range jobs {          // jobs 关闭时，for range 退出
                results <- Result{JobID: job.ID, Out: process(job.Data)}
            }
        }(i)
    }
    wg.Wait()        // 所有 worker 都退出了，说明没有发送方了
    close(results)   // 此时关闭 results 才安全
}
```

调用方：

```go
jobs := make(chan Job, 100)
results := make(chan Result, 100)

go workerPool(jobs, results, 8)   // 8 个 worker

go func() {
    defer close(jobs)             // 任务投喂完，关闭 jobs 广播"没活了"
    for i := 0; i < 10000; i++ {
        jobs <- Job{ID: i, Data: fmt.Sprintf("task-%d", i)}
    }
}()

for r := range results {          // results 被 workerPool 关闭后退出
    fmt.Println(r)
}
```

这套结构里有几个非常值得琢磨的设计：

**其一，并发度由 worker 数量决定，而不是由任务数量决定。** 10000 个任务，8 个 worker，内存占用恒定。这就是 worker pool 的全部意义——**把"任务数量"和"并发数量"解耦**。

**其二，worker 的退出靠 `close(jobs)` 广播。** 一次 close，8 个 `for range jobs` 同时退出，干净利落。你完全不需要给每个 worker 单独发退出信号。**close 的广播性质，是"一对多通知"最优雅的实现。**

**其三，`close(results)` 的时机是 `wg.Wait()` 之后。** 因为 8 个 worker 都是 results 的发送方，必须等**所有**发送方都结束了才能关。这又是那条铁律：**确认没有发送方了，才关闭。**

**其四，jobs/results 的缓冲大小是调优参数，不是语义参数。** 缓冲大一点，worker 不容易空转（投喂快一点）；缓冲小一点，背压更灵敏。改它不影响正确性——这是好的设计。

顺带说一个现代 Go 的更好选择：**`golang.org/x/sync/errgroup`**。它把"WaitGroup + 错误收集 + context 取消"打包好了：

```go
g, ctx := errgroup.WithContext(context.Background())
g.SetLimit(8)                      // 直接限制并发度，连 worker pool 都不用手写
for i := 0; i < 10000; i++ {
    i := i
    g.Go(func() error {
        return process(ctx, i)     // 任一任务返回 error，ctx 被取消，其余任务收到信号
    })
}
if err := g.Wait(); err != nil {
    log.Fatal(err)
}
```

`errgroup` 不是"官方标准库"，但它是 Go 团队维护的官方扩展库，**在生产代码里的地位基本等同于标准库**。能用就用，别重复造轮子——但你也得知道它内部就是 WaitGroup + channel + context 实现的，原理没变。

---

## 子主题十一：模式四——用有缓冲 channel 当信号量（限流）

这是一个极简、极优雅、但很多人第一次见会觉得"还能这样？"的技巧。

再问一个问题：**有缓冲 channel 的本质是什么？** 结合 hchan 模型想——它就是一个"容量固定的队列 + 满了就阻塞发送"的结构。

那如果我往这个 channel 里放的东西**毫无意义**呢？比如 `struct{}{}`。那么：

- **发送成功** = 队列还有空位 = 我成功占了一个名额。
- **发送阻塞** = 名额用完了 = 我得等。
- **接收一个** = 归还一个名额。

看清楚了吗？**一个有缓冲 channel，天然就是一个计数信号量。** 容量就是并发额度，发送就是 P 操作（acquire），接收就是 V 操作（release）。

```go
sem := make(chan struct{}, 10)   // 最多 10 个并发

func limited(task func()) {
    sem <- struct{}{}            // acquire：拿不到就在这等着
    defer func() { <-sem }()     // release：用 defer 保证一定归还
    task()
}
```

就这么几行。对比用 `sync.Mutex + 计数器 + sync.Cond` 手写一个信号量，channel 版本只有它的零头，而且**没有条件变量的 spurious wakeup 问题，没有忘解锁的风险**——`defer` 保证归还。

这里有几个必须注意的点：

**必须用 `defer` 归还。** 信号量泄漏比内存泄漏更难查——程序会莫名其妙地"变慢"然后"卡死"，因为额度被吃光了。`defer` 是唯一的保险。

**额度为 0 的 channel 做不了这件事。** `make(chan struct{}, 0)` 是无缓冲，发送必须等到有人接收，那不是信号量，那是互斥锁（其实互斥锁也可以这么实现，见下）。

**其实 `sync.Mutex` 就能用容量 1 的 channel 模拟：**

```go
type Mutex struct {
    ch chan struct{}
}
func NewMutex() *Mutex {
    m := &Mutex{ch: make(chan struct{}, 1)}
    m.ch <- struct{}{}      // 初始放一个"令牌"
    return m
}
func (m *Mutex) Lock()   { <-m.ch }        // 取走令牌
func (m *Mutex) Unlock() { m.ch <- struct{}{} }  // 归还令牌
```

能工作，但**别在生产代码里这么写**。标准库的 `sync.Mutex` 有自旋、饥饿模式、和调度器深度配合的优化，比这个玩具强得多。这个例子的价值在于**让你看清"互斥"和"信号量"和"channel"在概念上是同一件事的不同面**——都是"令牌的交接"。

**什么时候该用 channel 信号量，什么时候该用 `golang.org/x/sync/semaphore`？**
- 额度固定、逻辑简单 → channel 就够，零依赖。
- 需要**动态改额度**、需要**一次获取多个额度**（比如"这个大任务占 3 个名额"）、需要 `TryAcquire`（拿不到就走，不阻塞）→ 用 `semaphore.Weighted`，它专为这些场景设计。

还有一类限流场景 channel 信号量不合适：**需要按时间窗口限流**（比如"每秒最多 100 次"）。那是**速率限制（rate limiting）**，不是并发限制。用 `golang.org/x/time/rate`，它基于令牌桶算法，和信号量是两码事。搞混这两者，是限流代码里最常见的设计错误——**并发限制管"同时多少个"，速率限制管"单位时间多少个"**，一个管空间，一个管时间。

---

## 子主题十二：channel 的性能账——什么时候它比锁慢

前面夸了 channel 这么多，现在该算账了。这一节可能比前面所有内容加起来更影响你的日常决策。

先给结论，再论证：

> **channel 是"协作原语"，锁和 atomic 是"状态原语"。用错类别，性能差一个数量级。**

为什么 channel 单次操作比锁贵？回到 hchan 模型，一次收发要走过这些路：

1. 获取 channel 内部的互斥锁（有竞争时可能要自旋/阻塞）；
2. 检查对端等待队列；
3. 搬数据（可能拷贝进缓冲）；
4. 如果没有对端 → **把自己挂进等待队列、调用调度器 park 当前 goroutine**；
5. 之后被唤醒，还要经历一次**调度延迟**（不是立刻运行，是进入运行队列等待被调度）。

对比一次 `atomic.AddInt64`：一条 CPU 指令（`LOCK XADD` 之类），**没有锁、没有队列、没有调度、永远不阻塞**。一次无竞争的 `mutex.Lock()` 也只是一次原子 CAS，几十条指令的事。

**量级上的差距是这样的：atomic < mutex（无竞争）< channel（无竞争，走缓冲快路径）<< channel（有阻塞/唤醒）。** 前三者是"纳秒到几十纳秒"级别，涉及 goroutine park/unpark 的阻塞收发是"微秒甚至更久"级别——因为调度延迟本身就是微秒级的，而且它还要受"当前有多少 goroutine 在排队"影响。

（具体数字随硬件、Go 版本、竞争强度变化很大，别背数字，记住**相对关系**和**"是否涉及 goroutine 调度"这个分水岭**。）

那么，什么时候该用锁/atomic 而不是 channel？

**场景一：高频读写单一共享状态。** 最典型的是计数器。

```go
// 用 channel 做计数器：绕、慢、别扭
type counter struct {
    ch   chan int64
    incd chan struct{}
}
// 你要为每个操作发一条消息、等一个回包……

// 用 atomic：一条指令
var hits atomic.Int64
hits.Add(1)
```

真相是：**计数、统计、状态标志这类东西，用 atomic 又快又对。** 用 channel 把它包成"消息传递"，是典型的形式主义——你把一句话能说清的事，写成了三趟往返的快递。

**场景二：需要读"最新值"而不是"下一条消息"。** channel 是**队列语义**：你收到的是"接下来的一条"。但很多时候你要的是"当前是什么状态"——比如"当前配置""当前连接数""当前是否健康"。队列语义在这里是错配的：你想知道现在几点，channel 却给你一堆历史时刻表。这该用 `atomic.Value` 或 `RWMutex` 保护的字段。

**场景三：需要"条件更新"（CAS 语义）。** 比如"如果当前值是 A，就改成 B"。用 channel 你得发请求、服务端判断、回结果——一次往返。用 `atomic.CompareAndSwap`，一条指令。

**场景四：临界区极小、竞争不高。** 保护一个 map 的读写、更新几个字段——`sync.Mutex` 干净利落。

那反过来，**什么时候 channel 真的比锁快**？别以为它总是输：

**其一，需要"等待多个事件"时。** 用锁 + 条件变量写"等 N 个条件中任意一个满足"，是出了名的难写对（虚假唤醒、遗漏 broadcast、忘记在循环中检查条件）。`select` 几行搞定，而且**运行时帮你做了正确的多路等待**。这里 channel 赢的不是纳秒，是**正确性**和**可维护性**。

**其二，长临界区 + 数据交接。** 如果临界区里要干很多活，不如把数据通过 channel 交给一个**专属的 goroutine**（这个套路叫 "monitor goroutine" 或 "actor"）——让这个 goroutine 独占数据，其他人只能通过消息请它干活。这样完全不需要锁，**而且把长临界区变成了串行化处理**，避免了锁持有时间过长导致的争抢。

**其三，批量化降低竞争。** 这是最实用的一招：假设 100 个 goroutine 都要给同一个计数器加 1，如果都直接 `atomic.Add`，它们会在同一条缓存行上疯狂打架（**缓存行乒乓 / false sharing**）。改成：**每个 goroutine 在自己的局部变量里累加，攒够一批（或结束时）再通过一次 channel 发送总值，由汇总 goroutine 加上去**。竞争次数从 N 降到 N/batch。

```go
// 分片计数：每个 goroutine 本地累加，批量上报
func worker(id int, jobs <-chan Job, out chan<- int64) {
    var local int64
    for range jobs {
        local++
        if local%1000 == 0 {     // 每 1000 次上报一次
            out <- local
            local = 0
        }
    }
    if local > 0 {
        out <- local
    }
}
```

这个"本地累加 + 批量上报"的思路，和 `sync.Pool`、per-CPU 计数、Disruptor 里消除伪共享的思路是一脉相承的：**减少共享，而不是更快地去抢。**

最后给一条可操作的决策规则：

> **有"所有权交接"或"事件/数据流"→ channel。**
> **有"多个 goroutine 读写同一份状态"→ Mutex 或 atomic。**
> **只是个计数/标志 → atomic。**
> **拿不准 → 先写简单的那个，然后上 benchmark（`go test -bench`）和 race detector（`go test -race`）用数据说话。**

补充一句：Go 自带 race detector 和 pprof，这两个工具能把你从"我觉得这里慢"的臆测中解救出来。**在没测过之前争论 channel 和锁谁快，都是浪费时间。**

---

## 子主题十三：nil channel 与已关闭 channel 的完整语义表

这一节是"背下来就能少踩 80% 的坑"的硬知识。channel 有四种状态：**nil、正常、已关闭、被 GC**。其中 nil 和已关闭的行为，是最容易记混的。

先回答一个看似刁钻的问题：**一个 `var ch chan int`（nil）上做发送、接收、关闭，分别会怎样？**

大多数人的直觉是"会 panic"。错了。只有关闭会 panic，收发是**永久阻塞**。

完整语义表（建议截图保存）：

| 操作 | nil channel | 正常（有空间/有对端） | 已关闭 |
|---|---|---|---|
| `ch <- v` 发送 | **永久阻塞** | 成功；无对端且满则阻塞 | **panic: send on closed channel** |
| `<-ch` 接收 | **永久阻塞** | 成功；空且无发送方则阻塞 | 立即返回：先取完缓冲中的残留数据，之后返回**零值** |
| `v, ok := <-ch` | 永久阻塞 | `ok=true` | 残留数据 `ok=true`；取完后 `ok=false` |
| `close(ch)` | **panic: close of nil channel** | 成功 | **panic: close of closed channel** |
| `len(ch)` / `cap(ch)` | 0 / 0 | 缓冲内元素数 / 容量 | 剩余元素数 / 容量 |
| 在 `select` 中的 case | **该 case 永不就绪（等于禁用）** | 正常参与 | 接收 case **总是立即就绪**（返回零值） |

表格里有三个点必须展开讲，因为它们是"魔鬼在细节"：

**第一，"永久阻塞"不是"可能阻塞"，是真的永远。** 一个 goroutine 阻塞在 nil channel 上，**没有任何机制能救它**——不是超时，不是 close（nil 没法 close），也不是别人往里发数据（nil 不是有效的 channel）。唯一的出路是：这个 goroutine 所在的整条路径被 `select` 的其他 case 带走，或者整个程序退出。所以：**阻塞在 nil channel 上 = goroutine 泄漏。** 这通常来自一个 bug：你以为自己初始化了 channel，其实没有。

最常见的触发方式：

```go
var ch chan int          // 忘了 make！
if someCondition {
    ch = make(chan int)  // 只有某些分支才初始化
}
ch <- 42                 // 条件不满足时，永久阻塞，泄漏
```

**第二，已关闭 channel 的接收"总是立即就绪"——这在 `for-select` 里会造成 100% CPU 空转。** 这是一个生产中真实会炸的坑：

```go
for {
    select {
    case v := <-ch:      // ch 已关闭 → 这个 case 永远立刻就绪 → 疯狂空转
        handle(v)
    case <-ctx.Done():
        return
    }
}
```

一旦 `ch` 被关闭，`case v := <-ch` 会**每次都立即成功**（拿到零值），而 `ctx.Done()` 还没就绪，于是这个循环以 CPU 100% 的速度空转，`ctx.Done()` 那个 case 因为 select 的随机性偶尔才被选中——程序表现是"卡住 + CPU 打满"。

正确的写法是用 `v, ok := <-ch` 判断，并在 `ok == false` 时**把 channel 置为 nil**来禁用该 case：

```go
for ch != nil || done != nil {   // Go 1.22 之前没这个写法，可用标签+break
    select {
    case v, ok := <-ch:
        if !ok {
            ch = nil            // 禁用这个 case，精妙的 trick
            continue
        }
        handle(v)
    case <-ctx.Done():
        return
    }
}
```

**"把已关闭的 channel 置为 nil 来禁用 select 分支"**——这一招你一定要会。它把"这个数据源结束了"表达为"这个 case 不存在了"，比用一堆布尔标志干净得多。

**第三，`close` 的 panic 是运行时直接抛出的，recover 不了设计错误。** 向已关闭的 channel 发送、关闭 nil channel、重复关闭，这三个 panic 都说明**程序的结构设计有问题**（发送方和关闭方的职责没分清），不是可以靠 `recover` 兜住的"偶发异常"。正确做法是回到设计层面：**明确"谁有权关闭"**。

那么"谁有权关闭"这个问题，有没有一个可执行的判据？有，就一句话：

> **只有确认"不会再有任何发送"的一方，才有资格关闭。**

由此推出三条实践规则：
1. **单发送方**：发送方自己 `defer close(ch)`，最简单。
2. **多发送方**：用 `WaitGroup` 计数，全部结束后由协调者关闭（见子主题九的 merge）。或者用 `sync.Once` 包装 close，防止重复关闭。**千万不要让任何一个发送方自己关**——它关了，其他发送方就 panic 了。
3. **接收方想提前退出**：接收方**绝不关闭** channel（它不知道还有没有人在发）。正确做法是通过另一个 channel 或 `context` **通知发送方"别发了"**，让发送方去关。这是"反向通知"通道，下一节讲。

---

## 子主题十四：超时、取消、优雅关闭的正确姿势

前面所有模式都缺了最后一环：**怎么让它们停下来。** 这一节是"能跑"和"能上线"的分界线。

先问一个让很多人冷汗直流的问题：**你的服务收到 SIGTERM 正在优雅退出，此时有 5000 个 goroutine 阻塞在各种 channel 收发上。它们会怎样？**

答案是：**它们会一直阻塞到进程被 KILL。** 主 goroutine 的优雅退出逻辑管不到它们，Go 没有"关闭所有 goroutine"的按钮。这些 goroutine 拿着的连接没关、持有的锁没放、写了一半的缓冲区没落盘。**这就是为什么"优雅退出"不优雅。**

正确姿势分三层，从简单到完整。

### 第一层：超时——给每次阻塞加上限

最基础的形式是 `select` + 超时 channel：

```go
select {
case v := <-ch:
    handle(v)
case <-time.After(time.Second):
    log.Println("超时")
}
```

`time.After` 返回一个 channel，指定时间后收到一个值。简洁好用，但有个陷阱：**在循环里反复调用 `time.After`，会不断创建新的定时器。** 老版本 Go 里这些定时器在触发前不会被回收，高频循环下会累积（这是经典的 `time.After` 泄漏）。Go 1.23 改进了定时器实现，**不再被引用且未停止的定时器可以被 GC 回收**，情况好多了；但**显式管理依然是更稳、更可读的写法**：

```go
timer := time.NewTimer(time.Second)
defer timer.Stop()          // 显式停止并释放
select {
case v := <-ch:
    handle(v)
case <-timer.C:
    log.Println("超时")
}
```

注意 `defer timer.Stop()`。如果你复用 timer（循环场景），还要处理"timer 已触发但 channel 里的值没被取走"的情况，需要 `Stop()` + 排空——这正是用 `time.After` 省心的地方。**选哪个？一次性超时用 `time.After`，循环里的超时用 `NewTimer` + 手动 Reset。**

### 第二层：取消——用 context 传递"别干了"

超时只能管"一次操作"。但真实场景是：**一个请求触发了 10 个 goroutine、3 层 pipeline，请求取消了，这 10 个 goroutine 全都要停。** 一个一个加超时是不现实的。

这就是 `context.Context` 存在的意义。context 本身的实现，就是一个**只读的、可广播的关闭信号 channel**（`Done()` 返回 `<-chan struct{}`，内部靠 close 广播）+ 一对键值 + 一个截止时间。

正确姿势有三条铁律：

**铁律一：`ctx` 必须是函数的第一个参数，且只传下去，不存起来。**
```go
func doWork(ctx context.Context, job Job) error   // 对
// 不要把 ctx 存进 struct 字段
```

**铁律二：每个可能阻塞的操作，都要 select ctx.Done()。**
```go
func worker(ctx context.Context, jobs <-chan Job, results chan<- Result) {
    for {
        select {
        case <-ctx.Done():
            return ctx.Err()          // 被取消，立即退出
        case job, ok := <-jobs:
            if !ok {
                return nil
            }
            select {
            case results <- process(job):
            case <-ctx.Done():        // 发送也可能阻塞，同样要能退
                return ctx.Err()
            }
        }
    }
}
```

看清楚：**接收和发送两处都加了 `ctx.Done()` 分支。** 只加一处是不够的——发送照样会阻塞。这是新手最常见的疏漏。

**铁律三：取消是协作式的，不是强制的。** `ctx.Done()` 只是"通知"，goroutine 自己必须**主动检查并 return**。如果你的 goroutine 在做一个 10 秒的同步计算且不检查 ctx，它就是停不下来的。所以：**长任务内部要分段检查 ctx。**

### 第三层：优雅关闭——完整的关停序列

把前面拼起来，一个服务组件的完整关停序列是这样的：

```go
func (s *Server) Shutdown(ctx context.Context) error {
    close(s.stopCh)        // 1. 广播"停止接收新请求"（close 的广播性质）
    s.cancel()             // 2. 取消 context，通知所有 worker

    done := make(chan struct{})
    go func() {
        s.wg.Wait()        // 3. 等待所有 worker 自然退出
        close(done)
    }()

    select {
    case <-done:
        return nil         // 4a. 全部干净退出
    case <-ctx.Done():
        return ctx.Err()   // 4b. 外部给的宽限期也到了，超时退出
    }
}
```

这四步的顺序不能乱：**先关入口（不再收新活），再广播取消（在干活的停下），然后等待（给在干活的收尾时间），最后才是兜底超时。** 每一步都对应一个明确的语义：

- `close(s.stopCh)`：**一次性通知所有人**（广播）。
- `s.cancel()`：**沿着调用链传播**（context 树）。
- `s.wg.Wait()`：**确认所有人真的结束了**（而不是假设）。
- 外层 `ctx`：**给"等待"本身也设个上限**（防止某个 worker 卡死导致整个退出卡死）。

最后补一个"反向通知"的完整例子，回答子主题十三末尾留下的问题——**接收方想退出时，怎么让发送方停下**：

```go
func producer(ctx context.Context, out chan<- Item) {
    defer close(out)              // 发送方负责关闭
    for {
        item, err := fetch()
        if err != nil {
            return
        }
        select {
        case out <- item:
            // 成功投喂
        case <-ctx.Done():
            return                // 下游不要了，我走人，并负责关闭 out
        }
    }
}
```

下游只要 `cancel()`，producer 就会退出并关闭 `out`，下游的 `for range out` 随之结束。**职责清晰：发送方关闭 channel，接收方通过 ctx 表达"我不要了"。** 这是 Go 里处理"提前终止"的标准答案。

---

## 业界对照

**Erlang：** 进程间用邮箱（mailbox）+ 消息传递，和 channel 同源（都源自 CSP/Actor 思想）。Erlang 的"选择性接收"（pattern match 收件）比 Go 的 select 更灵活。Erlang 没有共享内存，通信是唯一手段，所以没有"channel vs 锁"的纠结。

**Clojure（core.async）：** 直接实现了类 Go 的 channel + `go` 宏，甚至支持 `<!`/`>!` 和 select（`alts!`）。core.async 明确承认借鉴了 Go 的 channel 模型。区别在于 Clojure 的 go 块是"反转控制"的宏变换，不是真正的 goroutine 栈。

**Rust（std::sync::mpsc / tokio）：** 标准库提供多生产者单消费者 channel；tokio 的 mpsc 支持异步收发。Rust 靠所有权系统，channel 传值就是"所有权转移"，比 Go 更彻底地杜绝了"发送后还继续用"的错误——但同样带来借用检查的约束。

**C#（Channel<T> / System.Threading.Channels）：** 提供了有界/无界 channel，配合 async/await 使用，语义和 Go 接近。C# 的 `Channel` 是库而非语言内建，用法上更显式。

---

## 子主题十五：业界对照补强——同一种思想，四种落地

上面那段对照太薄了。既然要"精通"，就得横向比一比：**同样是"通过通信共享内存"，别的语言怎么做？它们的取舍，反过来会照出 Go channel 的设计取向。**

### Clojure core.async：把 Go 的模型搬进 JVM，然后付了个代价

core.async 是 Rich Hickey 团队做的库，目标很直白：**在 Clojure 里复刻 Go 的 channel + goroutine 体验。** 它甚至把语法都搬了：

- `chan` 创建 channel，`(chan 10)` 是有缓冲的，`(chan)` 是无缓冲的；
- 在 `go` 块里用 `>!`（发送）和 `<!`（接收）；
- `alts!` 就是 Go 的 `select`——多路等待，随机选一个就绪的。

为什么说它"付了代价"？关键在于 **JVM 没有轻量级线程**（在 Loom 虚拟线程成熟前）。Go 的 goroutine 是运行时管理的、栈可增长的、创建成本极低的实体；JVM 的线程是 OS 线程，一个几 MB，开几千个就吃力。

core.async 的解法是**反转控制（inversion of control）**：`go` 是个宏，它把块内的代码**改写成一个状态机**，遇到 `<!`/`>!` 就把状态机"暂停"（park），交给线程池里的某个真实线程去执行；条件满足时再恢复。**`go` 块看起来是阻塞式的顺序代码，实际上被编译成了回调式的状态机。**

这个设计的后果，是两条必须遵守、否则就出事的纪律：

1. **不能在 `go` 块里做真正的线程阻塞操作**（比如 `Thread/sleep`、阻塞 IO、拿锁长期不放）。因为底下的线程池是有限的，一旦被真阻塞占住，所有 `go` 块都停摆。core.async 为此明确区分了 parking（状态机暂停，不占线程）和 blocking（真占线程），并提供 `thread` 宏/`pipeline-blocking` 来处理后者。**这个"看起来阻塞、实际不能阻塞"的认知负担，是移植 Go 模型到无协程运行时上的必然代价。**
2. `<!`/`>!` **只能写在 `go` 块内部**，不能写在普通函数里——因为宏变换的边界就是 `go` 块。这导致代码组织上出现了 Go 完全没有的限制：**你没法把一个"接收 channel"的逻辑抽成独立函数**（除非用 `async`/`<!!` 之类变形）。这被称为 "core.async 的函数颜色问题"。

反过来看 Go：**因为 goroutine 是真的一等公民（真正的栈、真正的调度、真正的阻塞语义），Go 里 channel 操作可以写在任何函数里，可以跨任意深的调用栈阻塞。** 这是"语言级支持"和"库级模拟"的根本差距。

一句话总结这次移植：**思想可以抄，运行时抄不了。** core.async 证明了 CSP 模型本身的普适价值，也证明了"没有廉价协程"时实现它有多别扭。

### Rust mpsc：所有权转移，比 Go 更狠

Rust 标准库的 `std::sync::mpsc`（multi-producer, single-consumer）也提供 channel，接口和 Go 神似：`Sender::send`、`Receiver::recv`、迭代 `Receiver`。但有一个本质区别，来自 Rust 的所有权系统：

**`send` 会转移（move）值的所有权。**

```rust
let (tx, rx) = std::sync::mpsc::channel();
let v = vec![1, 2, 3];
tx.send(v).unwrap();
// println!("{:?}", v);   // 编译错误！v 的所有权已经转移走了
```

**Go 做不到这一点。** 在 Go 里：

```go
v := []int{1, 2, 3}
ch <- v
fmt.Println(v[0])   // 完全合法，而且是 bug 温床：发送方还在用这份数据
```

Go 的 channel 传递的是**值的拷贝**（对 slice/map/pointer 而言，拷贝的是那个"引用"本身）。所以发送之后，发送方手里那份还在，**两个 goroutine 就能同时摸到同一块底层数据**——数据竞争回来了。**channel 保证的是"交接那一刻的同步"，不保证"交接之后发送方不再碰"。** 这是 Go channel 一个真实的安全缺口，靠程序员自觉（`go test -race` 是你的好朋友）。

Rust 用类型系统把这个洞焊死了：move 之后原变量不可用，编译器直接拒绝。这是"所有权"这个概念在 channel 上最漂亮的应用——**CSP 的"通过通信共享内存"，在 Rust 里被类型系统强制了，而不只是被鼓励。**

代价呢？当然是借用检查器的约束。另外注意 **mpsc 这个名字本身就是约束**：标准库版本是**多发送者、单接收者**——`Sender` 可以 `clone()` 出很多个，`Receiver` 不能。所以 Rust std 的 channel **天生不能做 fan-out**（多个消费者读同一个 channel）。要做工作池这种"多消费者"模式，得自己用 `Arc<Mutex<Receiver>>` 包一层互斥（于是又回到锁），或者用 `crossbeam` 这类第三方库。**而 Go 的 channel 原生就支持多发送者多接收者（MPMC），这是 Go 语义上更宽松、更"开箱可用"的地方。**

异步生态里，`tokio::sync::mpsc` 更进一步：提供**有界** channel，`send().await` 在满时异步等待，还提供了"预留配额"（permit）机制——这其实就是我们子主题十一讲的**信号量**，只不过被做成了显式 API。**你看，限流这件事，各家最后都收敛到同一个概念上。**

### C# Channel<T>：库级实现，但把"背压策略"做成了可选项

.NET 的 `System.Threading.Channels` 是库（不是语言特性），配合 async/await 使用：

```csharp
var ch = Channel.CreateBounded<int>(new BoundedChannelOptions(100) {
    FullMode = BoundedChannelFullMode.Wait,      // 满了怎么办：等
    SingleReader = false,
    SingleWriter = false,
});
await ch.Writer.WriteAsync(42);
int v = await ch.Reader.ReadAsync();
await foreach (var x in ch.Reader.ReadAllAsync()) { /* ... */ }
```

它和 Go 有几个有意思的差异：

**其一，`ChannelReader` / `ChannelWriter` 分离。** 这是把"发送权"和"接收权"作为**不同的对象**暴露，效果上类似 Go 的 `chan<-` / `<-chan` 方向类型，但更彻底——你拿到 `ChannelReader` 就根本没有写入的方法。channel 本体是 `Channel<T>`，但通常只把一侧传给协作者。**这是个值得借鉴的 API 设计：能力分离用类型表达，比用注释约定强。**

**其二，满了之后的策略是显式的枚举。** `BoundedChannelFullMode` 提供 `Wait`（阻塞等待，等价 Go 的有缓冲满）、`DropWrite`（丢弃最新，写入假装成功）、`DropOldest`（丢最老的）、`DropNewest`（丢最新的）。**这是 Go channel 完全没有的能力**——Go 的有缓冲 channel 满了只有一种行为：阻塞发送者。

这个差异很有意思，值得琢磨：在 Go 里想实现"满了就丢弃"，你得自己写：

```go
select {
case ch <- v:
    // 成功
default:
    // 满了，丢弃（非阻塞发送）
}
```

用 `select` + `default` 实现非阻塞发送，就能组合出任意丢弃策略。**Go 给的是原语（非阻塞收发 + 多路选择），策略由你组合；C# 给的是封装好的策略选项。** 这就是"语言原语"和"库"的典型分野：Go 的更灵活、更可组合，C# 的更不容易用错。

**其三，`await foreach` + `ReadAllAsync()` 对应 Go 的 `for range ch`。** 语义一致：写入方调用 `Writer.Complete()`（对应 `close(ch)`），读取方的循环自然结束。连"谁负责关闭"的约定都一样：**写入方完成写入后标记完成。**

### 横向对照小结

把这四种放在一张表上，你会看清 Go 的位置：

| 维度 | Go channel | Clojure core.async | Rust mpsc | C# Channel&lt;T&gt; |
|---|---|---|---|---|
| 层次 | 语言内建 | 库 + 宏 | 标准库 | 标准库 |
| 并发载体 | goroutine（真栈，可任意深度阻塞） | go 块状态机 + 线程池 | OS 线程 / async task | async task |
| 阻塞能否跨函数 | 能 | **不能**（宏边界限制） | 能 | 能 |
| 发送后所有权 | **不转移**（隐患） | 不转移 | **转移（编译期强制）** | 不转移 |
| 多消费者 | 原生支持 | 原生支持 | std 不支持（需第三方/加锁） | 原生支持 |
| 满时策略 | 只有阻塞（策略靠 select 组合） | 同 Go | 同 Go（tokio 有 permit） | 可配置（Wait/Drop*） |

读这张表，最该得出的结论不是"谁更好"，而是：**Go 把 CSP 做成了语言的一等公民，换取了极致的表达力和可组合性，代价是安全上更依赖程序员自觉（所有权不转移、可以泄漏 goroutine）。Rust 用类型系统换来了更强的保证，代价是灵活性和心智负担。C# 用库换来了更安全的默认策略，代价是表达力受限。Clojure 在错误的运行时上复刻了正确的模型，代价是"看起来阻塞实际不能阻塞"的割裂。**

这份对照反过来印证了子主题二的判断：**channel 不是"更安全"的锁，它是一种不同的复杂度分配方式。** 每种语言把复杂度放在了不同的地方——Go 放在程序员的纪律里，Rust 放在编译器的规则里，C# 放在库的默认选项里。

---

## 版本演进小结

- 早期：channel 模型就已确立（CSP 是 Go 的立身之本之一）。
- 持续优化：channel 内部的锁、等待队列、缓冲区实现不断打磨，减少锁竞争。
- 语义稳定：channel 的基本语义（同步/缓冲/关闭/happens-before）从早期至今高度稳定，这也是它成为 Go 并发"基石"的原因——**稳定到你可以依赖它的每一个细节。**

---

## 本章思考题

【思考题】

1. "不要通过共享内存通信，要通过通信共享内存"这句话，你现在的理解是什么？它和"用锁"到底是不是对立的？

2. 为什么"发送 happens-before 接收"能让你不用锁就保证可见性？请用 happens-before 解释那个 `data = 42; close(done)` 的例子。

3. select 多个 case 就绪时为什么随机选？这和 map 遍历随机化有什么共同的设计哲学？

4. 什么情况下 goroutine 会因 channel 泄漏？怎么用 select 兜底？

5. 结合 hchan 的概念模型（环形缓冲 buf、发送等待队列 sendq、接收等待队列 recvq、互斥锁），说明一次 `ch <- v` 在运行时会依次尝试哪几条路径？为什么"先查对端等待队列，再查缓冲"这个顺序很重要？

6. 无缓冲 channel 是"会合点"，有缓冲 channel 是"异步信箱"。请用这个区分解释：为什么用 `make(chan struct{}, 1)` 做"任务完成通知"是错的（或者说，语义上不精确）？

7. 缓冲容量该设多大？为什么说"缓冲越大不一定是好事"？背压（backpressure）在这里扮演什么角色？

8. fan-in 的 `merge` 函数里，为什么不能写成 `wg.Wait(); close(out); return out`？必须额外起一个 goroutine 来做"等待并关闭"？

9. 为什么"一个容量 N 的有缓冲 channel 天然就是一个计数信号量"？用 channel 实现信号量时，最关键的防御性写法是什么（漏了它就出事）？

10. 用 channel 做高频计数器为什么比 atomic 慢？请从"是否涉及 goroutine 调度"这个分水岭来解释，并给出"批量上报"这种优化思路为什么有效。

11. 一个 channel 被关闭后，在 `for { select { case v := <-ch: ...; case <-ctx.Done(): return } }` 里会发生什么？怎么修？这个修复手法叫什么？

12. 服务的优雅关闭（graceful shutdown）应该按什么顺序做？请说明"关闭入口 → 广播取消 → 等待结束 → 兜底超时"这四步各自的语义，以及为什么顺序不能乱。

【参考答案】

1. 它不是"禁止用锁"，而是"默认用所有权交接来表达协作"。channel 把"同步"和"数据传递"合并成一个操作，让"谁在何时拥有哪个数据"变得显式，控制流更清晰。但对"多个 goroutine 频繁读写同一份共享状态"（共享计数器、共享缓存），channel 反而别扭，用 Mutex 或 atomic 更直接。Go 设计者自己都说 channel 和锁各有适用场景。所以那句话是"推荐默认用 channel 表达协作"，不是"channel 一定比锁好"。

2. happens-before 是内存模型的可见性保证：若 A happens-before B，则 A 的写对 B 可见。channel 的规则是"发送/关闭 happens-before 对应的接收完成"。例子里，`data = 42` 在 `close(done)` 之前执行，而 `close(done)` happens-before `<-done`（接收方读到关闭），所以 `data = 42` 的写对接收方可见，`fmt.Println(data)` 必打印 42。channel 内部的锁和内存屏障替你保证了这条链，所以不需要额外的锁。

3. 因为如果总是优先第一个 case，靠后的 case 可能永远饥饿轮不到，而且程序员会依赖"case 的书写顺序"，写出脆弱代码。随机选择从根上掐断了这种依赖。这和 map 遍历随机化的哲学一致：**用随机性强迫开发者不要依赖一个不该依赖的细节**。

4. 一个 goroutine 永远阻塞在 `ch <- v`（无接收方）或 `<-ch`（无发送方）上，就会泄漏——占着内存和调度资源，永不退出。兜底做法是用 `select` 加 `done`/超时分支：`select { case v := <-ch: ...; case <-ctx.Done(): return }`，保证阻塞的收发有"出口"。生产代码里，凡会阻塞的收发都要想清楚"谁来解救我"，否则大量泄漏的 goroutine 会拖垮程序。

5. 一次发送依次尝试三条路径：① 先看接收等待队列 recvq 里有没有已挂起的接收者，有则**绕过缓冲**，把值直接交给它并唤醒它；② recvq 为空且环形缓冲还有空位，则把值写入缓冲的写位置、前移写下标，立即返回不阻塞；③ recvq 为空且缓冲已满，则把自己连同待发送的值挂进发送等待队列 sendq，park 挂起，让出 CPU。接收完全对称：先查 sendq，再查缓冲，都不行就进 recvq。这个顺序的重要性在于：只要收发双方同时在场，数据就走"手递手"的直达快路径，不需要进缓冲再出缓冲（少一次拷贝、少一次队列周转）；缓冲只是"一方没到场时的暂存区"。它也解释了一个反直觉的事实——即使缓冲里还有残留数据，只要 sendq 里有阻塞的发送者（说明缓冲必然是满的），接收也会优先从发送者手里直接拿值。另外，内部互斥锁只在改下标、搬数据、摘等待者这极短路径上持有，**绝不在阻塞等待期间持有**，这是 channel 能扛住高并发的前提。

6. 无缓冲 channel 上的一次成功发送，意味着"发送方和接收方在 channel 上会合了"——交接完成的那一刻，双方同时确定"值已送达"，它携带的是**因果关系的传递**。而 `make(chan struct{}, 1)` 是有缓冲的：发送方把信号放进缓冲就立即返回，**接收方还没出现，发送方就已经继续往下跑了**。所以 `done <- struct{}{}` 表达的不是"我干完了"，只是"我投了个信"。如果 `done <- struct{}{}` 之后 goroutine 还有清理逻辑，或者你本意是"goroutine 已退出"，这个缓冲 channel 就给了你错误的保证。想表达"干完了并且放手"，用无缓冲 channel（真正的会合）或 `close(ch)`（广播 + happens-before 保证）。规则很简单：**要同步/传递因果 → 无缓冲或 close；要解耦/削峰 → 有缓冲。**

7. 默认应该是 0 或 1，除非有具体理由。0 用于同步语义（信号、通知、所有权交接）；1 用于"只要有一个待处理信号就够了"的场景（配合非阻塞发送就退化成一个置位标志），且**不制造积压**；N（几十到几百）只在有明确吞吐匹配需求时用（比如生产者批量读、消费者逐条处理，N 取一批的大小）。缓冲越大越不好的三个原因：① 缓冲是实打实的内存；② 缓冲里积压的数据就是**延迟**，数据在缓冲里躺着的时间不算在"处理完成"里；③ **缓冲会吃掉背压**——生产者发现"发送不阻塞"就一直生产，直到缓冲满才感知到下游压力，此时下游可能早就崩了而你浑然不知。背压是流式系统的生命线：**下游跟不上的时候，压力必须能传导回上游，让上游慢下来**。无缓冲或 cap=1 会让生产者在第一时间阻塞，把压力立即传导回去，问题早暴露。所以拿不准时选小缓冲。

8. 因为会造成死锁。`merge` 为 N 个输入 channel 各起一个搬运 goroutine，每个都执行 `out <- n`；如果 `out` 是无缓冲（或缓冲已满）且还没有消费者，`out <- n` 就会阻塞，搬运工永远 Done 不了。此时如果 `merge` 自己先 `wg.Wait()`，就是"搬运工等有人消费 out，merge 等搬运工 Done"，循环等待 → 死锁。所以必须**先 `return out` 让调用方开始消费**，再起一个独立 goroutine 做 `wg.Wait(); close(out)`。这里 `WaitGroup` 计数的语义是"还有 N 个发送方活着"，而**关闭 channel 的前置条件正是"确认没有任何发送方了"**——所以"等所有 Done 后由一个额外 goroutine 关闭"是多发送方场景下的标准关闭姿势，会反复用到（worker pool 的 `wg.Wait(); close(results)` 也是同一个套路）。

9. 因为容量 N 的有缓冲 channel，语义恰好就是"最多 N 个名额"：`make(chan struct{}, N)` 里放的是毫无意义的 `struct{}`，于是"发送成功"＝占到名额，"发送阻塞"＝名额用完、需等待，"接收一个"＝归还名额。这不就是计数信号量的 P/V 操作吗？对比用 `Mutex + 计数器 + Cond` 手写信号量，channel 版本代码量是零头，且没有条件变量的虚假唤醒问题、没有忘解锁的风险。最关键的防御性写法是：**用 `defer func() { <-sem }()` 归还额度**。信号量泄漏比内存泄漏更难查——程序不会崩，只会"莫名变慢然后卡死"，因为额度被慢慢吃光了；`defer` 是唯一的保险。补充边界：额度为 0（无缓冲）做不了信号量；需要一次性获取多个额度、动态改额度或 `TryAcquire` 时，用 `golang.org/x/sync/semaphore.Weighted`；而"每秒最多 100 次"属于**速率限制**（`golang.org/x/time/rate`，令牌桶），和并发限制是完全不同的两件事——一个管空间，一个管时间。

10. 一次 channel 收发要：获取内部互斥锁（有竞争时自旋/阻塞）→ 检查对端等待队列 → 搬数据 → 若无对端则把自己挂进等待队列并 park **→ 之后还要经历一次调度延迟**（进入运行队列等待被调度，不是立刻运行）。而一次 `atomic.AddInt64` 只是一条带 LOCK 前缀的 CPU 指令：**无锁、无队列、无调度、永不阻塞**。分水岭就在于"是否涉及 goroutine park/unpark 与调度"——atomic 和无竞争 mutex 是纳秒到几十纳秒级，涉及阻塞唤醒的 channel 操作是微秒甚至更久级（调度延迟本身就是微秒级，还受可运行 goroutine 数量影响）。所以高频读写单一共享状态（计数器、状态标志、统计）用 atomic 又快又对，用 channel 包成消息传递是形式主义。但 channel 也有赢的时候：需要"等待多个事件"时（select 的多路等待，用锁+条件变量极难写对）、长临界区改为 monitor goroutine 串行化、以及批量化降竞争。"本地累加 + 攒够一批再通过 channel 上报总值"之所以有效，是因为它把对同一缓存行的竞争次数从 N 降到 N/batch，缓解了缓存行乒乓（false sharing）——**减少共享，而不是更快地去抢**。判定规则：有所有权交接或事件流 → channel；多 goroutine 读写同一份状态 → Mutex/atomic；只是计数或标志 → atomic；拿不准 → 先写简单的，再用 `go test -bench` 和 `go test -race` 用数据说话。

11. channel 一旦被关闭，`case v := <-ch` 会**每次都立即就绪**（返回零值），而 `ctx.Done()` 尚未就绪，于是这个 for-select 循环以 **CPU 100%** 的速度疯狂空转（只在 select 随机选中 `ctx.Done()` 分支时才退出）。这是生产中真实会炸的坑。修法分两步：① 用 `v, ok := <-ch` 形式接收，判断 `ok == false` 说明 channel 已关闭；② 此时**把该 channel 置为 `nil`**——nil channel 的收发永久阻塞，在 select 里就等价于"这个 case 永不就绪"，于是这个分支被动态禁用了。这个手法叫**"把已关闭的 channel 置 nil 来禁用 select 分支"**，它把"这个数据源结束了"表达成"这个 case 不存在了"，比堆一堆布尔标志干净得多，是 Go 并发的隐藏技能（配合外层判断所有 channel 都为 nil 时退出循环）。同时要记住：向已关闭的 channel 发送、关闭 nil channel、重复关闭，这三种 panic 都属于**结构设计错误**（发送方与关闭方职责没分清），不是能靠 `recover` 兜住的偶发异常。

12. 顺序是：① `close(stopCh)` 关闭入口，用 close 的广播性质一次性通知所有人"不再接收新请求"；② `cancel()` 取消 context，沿 context 树向下传播，通知所有在干活的 worker 停下；③ `wg.Wait()` 等待所有 worker 自然退出，**确认**它们真的结束了（而不是假设），这一步要放在独立 goroutine 里并把完成信号通过 channel 传回来；④ 外层再套一个带超时的 `select`，给"等待"本身也设上限，防止某个 worker 卡死导致整个退出流程卡死。顺序不能乱的原因：先关入口，否则取消期间还有新请求涌进来，越退越忙；先广播再等待，否则 worker 不知道该停，`wg.Wait()` 会永远等下去；等待之后必须有兜底超时，否则一个异常的 worker 就能让进程"优雅"到天荒地老，最终被 SIGKILL 强杀，反而更不优雅。另外要记住：**取消是协作式的，不是强制的**——`ctx.Done()` 只是通知，goroutine 必须主动 select 检查并 return，所以长任务内部要分段检查 ctx；而且**接收和发送两处都要加 `ctx.Done()` 分支**，只加一处不够，因为发送同样会阻塞。
