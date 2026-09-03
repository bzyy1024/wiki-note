# 第 10 章　Java 并发模型：JMM、volatile 与锁升级（你写的 synchronized 到底发生了什么）

> 你写了一段 Java 代码，本地测试全过，一上压测就偶发数据错乱。你翻来覆去地看，逻辑没问题啊。最后发现是 `i++` 在多线程下不是原子的，加上 `synchronized` 就好了。
> 但你不甘心 —— 你给 Go 写过无数并发代码，从来没因为 `i++` 翻过车（Go 里你会用 `atomic.AddInt64`）。这一章要让你搞明白：Java 的并发，到底跟你熟悉的 Go 并发，差在那个最致命的地方。

---

## 10.1 先建立最大的认知框架：Go 的 M:N vs Java 的 1:1

你写 Go 时，`go func()` 已经刻进肌肉记忆。一千个 goroutine？一万个？都不是事儿。然后你写 Java，照着 muscle memory 来：

```java
for (int i = 0; i < 10000; i++) {
    new Thread(() -> handleRequest()).start();   // 错误：别这么干
}
```

跑了三秒，OOM 了。第 00 章讲过这个故事，这里把根因钉死：**Java 的 `Thread` 是 1:1 映射到 OS 线程的，而 goroutine 是用户态调度。**

Go 这边，runtime 自己管一套调度器（GMP 模型）：G 是 goroutine，M 是 OS 线程，P 是逻辑处理器。M 个 goroutine 跑在 N 个 OS 线程上，runtime 自己决定哪个 G 在哪个 M 上跑。关键点在于：**当一个 goroutine 阻塞在网络 IO 上时，runtime 把这个 P 让出去，挂到另一个空闲的 M 上继续跑别的 G**。阻塞被 runtime 在用户态吞掉了，OS 线程根本没被占着。

Java 这边，传统 `Thread` 就是 OS 线程的壳。你 `new Thread().start()`，内核就真给你起一个内核线程。它默认栈大小 1MB（`-Xss1m`，虽然是预留的虚拟内存，但线程对象本身 + 内核态的 `task_struct`/`thread_info` 是实打实的），上下文切换要陷入内核（用户态 → 内核态 → 用户态，寄存器全保存恢复，TLB 可能失效），而且一旦阻塞在一个 `socketRead0` 上，这个线程就死死占着，内核调度器也没法把它让给别人。

**问题 1：** 用一个数字对比，你就知道这个差异有多致命。

| 维度 | 1 万个 goroutine | 1 万个 Java 线程 |
|---|---|---|
| 初始内存占用 | 2KB × 10000 ≈ 20MB（按需增长） | 1MB × 10000 ≈ 10GB 虚拟地址（实际提交小一些，但线程元数据仍可观） |
| 创建速度 | 微秒级，纯用户态分配栈 | 毫秒级，要 syscall 建内核线程 |
| 调度开销 | runtime 用户态切换，几十纳秒 | 内核态切换，几百纳秒到微秒，且 TLB 抖动 |
| 阻塞的代价 | 让出 P，别的 G 顶上，线程不浪费 | 一个线程卡死，就少一个 worker |

数字不是重点，重点是**量级差异带来的工程后果**：goroutine 便宜到你可以"随便开"，所以 Go 的惯用法是"一个请求一个 goroutine"甚至"一次操作一个 goroutine"；Java 线程贵到你必须用**线程池**把它当稀缺资源管起来，于是有了队列、拒绝策略、`Executors` 的各种坑。

> 【思考】为什么这个差异如此致命？换句话说，Java 并发生态里那一大堆"麻烦事"（线程池、锁竞争、Reactor 模型、乃至虚拟线程），根子在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：根子在"线程是昂贵的 OS 资源"这一条事实上。** 它像多米诺骨牌的第一张，推倒了后面所有东西。

**第一块骨牌：线程贵 → 必须池化。**
Go 不需要线程池，因为 goroutine 不值钱，开一个就开一个。Java 开一个线程要 syscall、要 1MB 栈、要内核结构，开 1 万个就 OOM。所以 Java 必须预先建一小撮线程（比如 50 个），把任务排进队列慢慢消费 —— 这就是 `ThreadPoolExecutor`。线程池带来的问题（队列爆了怎么办？拒绝策略选哪个？核心/最大线程数怎么配？）全是"线程贵"的衍生品。第 11 章专讲这个。

**第二块骨牌：线程贵 + 阻塞占着线程 → 必须躲避阻塞。**
50 个线程，每个卡在 200ms 的网络调用上，吞吐量就被锁死在 `50 / 0.2s = 250 QPS`。而 goroutine 阻塞时 P 被让出去，完全不影响。于是 Java 生态发展出两条路来躲阻塞：一条是 Reactor（WebFlux / Project Reactor，用少量线程 + 事件循环扛高并发，思想接近 Node.js），一条是虚拟线程（Java 21，让 JVM 来扮演 Go runtime 的角色）。两条路都是被"线程贵"逼出来的。

**第三块骨牌：线程贵 → 竞争同一把锁时更容易雪崩。**
线程少，临界区短，锁竞争还不明显；一旦为了 throughput 把线程数堆到几百，一把粗粒度 `synchronized` 就成了瓶颈，所有线程 BLOCKED 排队 —— 第 04 章 04.9 的"短信雪崩"案例就是这么来的。于是有了锁升级、AQS、`ReentrantLock` 的 `tryLock` 这一大套优化，本章后面全在讲。

**更深一层**：这其实是语言设计里"把成本付在哪一层"的老问题。Go 在 runtime 层把调度成本付了（GMP + netpoller），换来"并发单位廉价、阻塞被自动接管"；Java 把线程直接交给 OS，换来"能利用 OS 的优先级、cgroup 配额、NUMA 亲和性"，代价是并发单位贵、阻塞要你自己管。当年 Java 设计 `Thread` 时（1995 年），"一个 Java 线程 = 一个 OS 线程"是最省事、最正确的选择；是二十年后多核 + 高并发 + 云原生把它的代价放大了。Java 21 的虚拟线程，本质就是承认"当年那张骨牌该重推一次"，让 JVM 在用户态做一遍 Go runtime 早就做的事。

**给老哥的一句话**：你带着 Go 经验写 Java，最容易犯的错误是"把线程当 goroutine 用"。记住这一章第一句 —— **线程是 OS 资源，不是 runtime 资源。** 这个认知差，是你后面踩的所有并发坑的共同源头：线程池配错、锁竞争雪崩、Reactor 看不懂，根子都在这。先把"线程贵"刻进骨头里，后面第十一章的线程池配置你才会真正懂"为什么核心线程数不能瞎填"。

</details>

**把这件事再钉实一层**：你写 Go 时，`http.Get` 阻塞了，那个 goroutine 停，但 P 立刻被别的 goroutine 顶上，承载它的 M 继续干活，OS 线程一个没浪费。你写 Java 时，`httpClient.execute` 阻塞了，那个线程就实实在在地卡在 `socketRead0` 上，OS 线程被占着，内核调度器也救不了它——除非你用异步客户端、Reactor、或虚拟线程把阻塞迁走。所以"线程是 OS 资源"不是一句口号，它直接决定了"你的服务能扛多少并发"的天花板。

**关键结论先放在这**：Java 并发的几乎所有"麻烦"（线程池、锁竞争、Reactor 模型）都源于"线程是昂贵的 OS 资源"。而 Go 因为 goroutine 廉价，很多"随便开 goroutine"的写法，搬到 Java 直接用线程会炸。Java 21 虚拟线程（第 12 章详讲）本质上就是 JVM 来扮演 Go runtime 的角色 —— 先在这里埋下种子，但本章聚焦传统模型。

---

## 10.2 JMM（Java 内存模型）：为什么你的多线程代码会"看起来对但其实错"

第 04.7 节你已经见过可见性的最小 demo 了。这里不重复那个，换一个更能说明"重排序"问题的：

```java
class Shared {
    private boolean ready = false;
    private int value = 0;

    public void writer() {       // 线程 A
        value = 42;
        ready = true;
    }
    public void reader() {       // 线程 B
        while (!ready) { /* 自旋 */ }
        System.out.println(value);   // 可能永远自旋、可能打印 0
    }
}
```

两个线程，A 先写 `value` 再写 `ready`，B 等 `ready` 变成 `true` 后读 `value`。直觉上 B 看到 `ready==true` 时 `value` 一定是 42。错。两个独立的失效原因：

**原因一：可见性问题（缓存）。** 线程 A 跑在 CPU 核 0 上，线程 B 跑在核 3 上。核 0 写了 `ready=true`，先写进自己的 L1/L2 缓存，没及时刷到主存；核 3 读 `ready` 时从自己的 L1 读，根本没看到新值 → B 永远自旋。

**原因二：重排序问题（指令重排）。** 编译器和 CPU 为了性能，会重排指令，只要**单线程**语义不变就允许。`writer()` 里 `value=42` 和 `ready=true` 之间没有任何数据依赖，JIT 完全可能把它重排成"先 `ready=true`，后 `value=42`"。于是 B 看到 `ready==true`，冲进去读 `value`，读到的却是 0。

这两个原因不是一回事，但都归到 JMM 要解决的同一类问题：**"代码顺序" ≠ "执行顺序" ≠ "别的线程看到的顺序"。**

### JMM 的三个来源（知其所以然）

**1. CPU 缓存一致性。** 每个核有自己的 L1/L2（甚至 L3 是共享的），写操作先写缓存，何时刷到主存不确定。多级缓存让"一个核写了什么"对其他核不是立即可见的。这就是为什么需要"可见性"保证 —— 把缓存行刷出去、或让别的核的缓存行失效。

**2. 指令重排序。** 编译器（javac、JIT）和 CPU 都会重排指令。底层约束叫 **as-if-serial**：只要单线程执行结果不变，怎么重排都行。这对单线程是好事（更快），对多线程是噩梦（你依赖的"先后"可能根本不存在）。重排发生在三层：编译器层（javac 基本不排，JIT 会排）、CPU 层（乱序执行）、内存系统层（写缓冲、store buffer）。

**3. CPU 乱序执行 / 内存屏障。** 硬件层面，x86 用 `mfence`/`sfence`/`lfence`，或带 `lock` 前缀的指令（如 `lock xadd`、`lock cmpxchg`）来强制顺序；ARM 用 `dmb` 等。JMM 规定：某些操作之间必须插入内存屏障，禁止重排并强制可见性。这些屏障对程序员是透明的，但 `volatile` 和 `synchronized` 的语义就是靠它们实现的。

补充一句关键的底层细节：现代 CPU 还有一层**写缓冲（store buffer）**。核心写完一个变量，往往先放进自己的 store buffer，并不立刻对其他核可见，要等 buffer 被刷出去（这步叫"store 被其他核观察到"）才生效。这就是为什么"我明明写了，你怎么看不到"——不是没写，是写还躺在我这核的 buffer 里没出门。内存屏障的作用之一，就是强制把 store buffer 排空。这也解释了为什么 x86 虽然号称"强内存模型"（TSO），看起来不乱序，但**跨核的可见性延迟依然存在**，仍需要 `volatile`/`lock` 来保证别的核立刻看到。ARM 这类弱内存模型更狠，连普通读写都可能重排，所以 ARM 上内存屏障是保命的，不是可选的。

> 【思考】为什么 Go 没有这么多"可见性"的坑？Go 程序员写并发几乎不用操心缓存和重排，是 Go 内存模型更聪明吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不是 Go 内存模型更聪明，而是 Go 的并发哲学从根上换了一条路 —— 它不鼓励你"靠共享内存通信"，于是大部分可见性问题从起源上就被避免了。**

**Go 同样有缓存和重排序。** x86 上 Go 也跑在多核上，写也先进 store buffer，指令也会乱序。Go 内存模型（The Go Memory Model 文档）明确说："如果两个 goroutine 访问同一个变量，且至少有一个是写，且没有用同步原语排序，那就是数据竞争（data race）。" 跟 Java 的 JMM 说的是同一类风险。

**关键差异在"官方推荐的做法"：**
- Go 官方的铁律是 **"Do not communicate by sharing memory; instead, share memory by communicating."** 也就是用 channel 传递数据所有权，而不是多个 goroutine 抢同一个变量。channel 的收发操作在 Go 内存模型里建立 happens-before，自动带内存屏障。
- Java 这边没有这么强的"反共享内存"文化。Java 的一等公民并发原语是 `synchronized` / `volatile` / `Lock`，本质都是"在共享内存上手动加同步语义"。所以 Java 程序员天天要操心"这个字段要不要加 volatile"，Go 程序员大多时候把数据塞进 channel 就完事了。

**但当你真的要手动同步时，两者是对称的：**
- Go：`var done int32; atomic.StoreInt32(&done, 1)` —— 相当于 Java 的 `volatile boolean done = true` 写，底层都插了内存屏障（x86 上是 `lock` 前缀指令或 `mfence`）。
- Go：`atomic.LoadInt32(&done)` —— 相当于 Java 的 `volatile` 读。
- Go 的 `sync.Mutex` 的加解锁，对应 Java 的 `synchronized` 进入/退出 monitor，都建立 happens-before。

**更深一层**：Go 用 channel 把"可见性"问题封装掉了，让你**少犯错**；但一旦你绕开 channel 用 `sync/atomic` 或 `sync.Mutex` 手动搞共享内存，你面对的内存模型复杂度和 Java 是同一层级的。所以准确说法是：**Go 减少了你"需要直接理解 JMM"的场景，而不是消灭了 JMM 这件事。** 你作为 5 年 Go 老兵，转 Java 时最大的优势是：你已经懂 happens-before 的思维方式，只是换了一套关键字（`volatile`/`synchronized` 代替 `atomic`/`channel`）。

</details>

### happens-before 规则（本章的基石）

JMM 的核心就一句话：**如果操作 A happens-before 操作 B，那么 A 的结果对 B 可见，且 A 看起来在 B 之前发生。** 注意 —— happens-before **不是时间先后，是"可见性保证"**。下面六条是 JMM 的全部来源，记住它们，你就能判断"这段代码会不会出事"：

1. **程序顺序规则**：同一个线程内，写在前面的操作 happens-before 写在后面的操作。
2. **管程锁定规则**：对一个锁的 `unlock` happens-before 后续对这个锁的 `lock`。
3. **volatile 变量规则**：对一个 `volatile` 变量的写 happens-before 后续对这个变量的读。
4. **线程启动规则**：`Thread.start()` happens-before 该线程里的任何操作。
5. **线程终止规则**：线程里的所有操作 happens-before 其他线程检测到它终止（如 `join()` 返回）。
6. **传递性规则**：若 A happens-before B，且 B happens-before C，则 A happens-before C。

这六条是"公理"，所有复杂的可见性判断都能从它们推出来。**最关键的一句升华**：happens-before 不是"时间上 A 先于 B"，而是"JMM 保证 B 能看到 A 的写"。没有这层关系的两个操作，顺序全靠运气。

回到 10.2 开头的 demo：给 `ready` 加上 `volatile` 后，`writer()` 对 `ready` 的写（规则 3）happens-before `reader()` 对 `ready` 的读，而 `value=42` 在 `ready=true` 之前（规则 1 + 规则 3 + 规则 6 传递性），所以 `reader` 保证能看到 `value==42`。一个 `volatile` 关键字，补上了两道失效（可见性 + 重排序）。

---

## 10.3 volatile：它是万能的，直到你试过 i++

`volatile` 解决两件事：

1. **可见性**：写一个 `volatile` 变量时，JIT 在写后插入 `StoreStore` + `StoreLoad` 屏障，强制把写操作（及对之前所有变量的写）刷到主存；读一个 `volatile` 变量时，插入 `LoadLoad` + `LoadStore` 屏障，让本地缓存行失效，从主存重读。
2. **禁止重排序**：`volatile` 写之前的操作，不会被重排到写之后；读之后的操作不会被重排到读之前。这就是 10.2 demo 里 `value=42` 不会被推到 `ready=true` 之后的原因。

**最致命的误解：volatile 不保证原子性。**

```java
private volatile int i = 0;
public void inc() { i++; }
```

`i++` 表面上一行，编译成三条字节码指令：

```
   2: getfield      #2   // Field i:I        ← 第 1 步：从主存/缓存读 i 到操作数栈
   6: iadd                                   ← 第 2 步：在栈顶做 +1
   7: putfield      #2   // Field i:I        ← 第 3 步：写回 i
```

`getfield` 和 `putfield` 之间**有间隙**。两个线程可能这样交错：A 读 0 → B 读 0 → A 写 1 → B 写 1，丢了一次加法。volatile 保证每次读都看到最新值、每次写都刷主存，但**它管不了"读-改-写"三步合起来算一个原子操作**。这正是你 Go 里从不会犯的错，因为你会写 `atomic.AddInt64(&i, 1)`，编译成一条 `LOCK XADD`，硬件级原子。

对照一下：

```go
// Go：一条 LOCK XADD，原子
var i int64
atomic.AddInt64(&i, 1)
```

```java
// Java：要么 synchronized，要么原子类
private final AtomicLong i = new AtomicLong();
i.incrementAndGet();   // 内部是 volatile 字段 + CAS 循环
```

### 什么时候该用 volatile（明确场景）

**① 状态标志位。** 这是最典型、最安全的用法：

```java
private volatile boolean shutdownRequested = false;
public void shutdown() { shutdownRequested = true; }
public void doWork() { while (!shutdownRequested) { /* 干活 */ } }
```

单线程写、多线程读的一个 boolean，用 volatile 完美。10.8 的案例一就是这个。

**② 双重检查锁定（DCL）的单例模式。** 这是面试经典，也是 volatile 最体现"知其所以然"的地方：

```java
public class Singleton {
    private static volatile Singleton instance;   // 关键：volatile

    public static Singleton getInstance() {
        if (instance == null) {                    // 第一次检查（无锁，快）
            synchronized (Singleton.class) {
                if (instance == null) {            // 第二次检查（有锁，防重复创建）
                    instance = new Singleton();    // 第三步：赋值
                }
            }
        }
        return instance;
    }
}
```

**③ 一次性安全发布（safe publication）。** 一个对象构造完之后，通过 volatile 字段发布出去，保证其他线程拿到的是"完全构造好"的对象（见下面的 DCL 原理）。

### 什么时候**不该**用 volatile

计数器、累加器、任何"读-改-写"复合操作。用 `AtomicLong`（中等并发）或 `LongAdder`（高并发，第 04.7 已讲过分段计数原理）。

> 【思考】DCL 里 `instance = new Singleton()` 这句，为什么不加 volatile 会拿到"半初始化的对象"？volatile 到底是怎么修好的？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 `new Singleton()` 在字节码层面是三步，不加 volatile 时"初始化对象"和"赋值引用"这两步可能被重排；另一个线程看到 `instance != null` 时，对象可能还没初始化完。**

**拆解 `instance = new Singleton()` 的真实三步（JVM 层面）：**
1. 分配内存（在堆上划出 `Singleton` 大小的空间）
2. 调用构造器，初始化对象（把字段写成你设定的值）
3. 把 `instance` 引用指向这块内存

步骤 2 和 3 之间没有数据依赖。JIT 可以重排成 **1 → 3 → 2**。现在灾难场景来了：

- 线程 A 进入同步块，执行到"步骤 3"（instance 已非 null，但对象还没初始化完，字段还是默认值 0/null）。
- 此时线程 B 来到第一次检查 `if (instance == null)`，看到 `instance != null`，**直接返回了这个半初始化对象**。
- 线程 B 用这个对象，读到的字段全是默认值，业务逻辑炸了 —— 而且这种 bug 只在特定时序下偶发，极难复现。

**volatile 怎么修好的？** 靠 volatile 的**禁止重排序**语义：`instance` 是 volatile，那么"对 `instance` 的写"（步骤 3）之前的所有操作（步骤 2 的初始化），不会被重排到写之后。同时 volatile 写 happens-before 后续 volatile 读（规则 3），所以线程 B 看到 `instance != null` 时，一定也能看到步骤 2 已经完成的初始化结果。两步一起，拿到的是完全构造好的对象。

**代码锚点（字节码视角）：**

```
// 不加 volatile，可能重排为：
    new            // 1 分配
    dup
    invokespecial  // 2 构造（可能被推迟）
    putstatic      // 3 赋值引用（可能提前到构造前）

// 加了 volatile，JVM 在 putstatic 前后插入内存屏障，
// 保证 2 一定 happens-before 3，且对其他线程可见
```

**更深一层**：DCL 是 JMM 设计哲学的一个缩影。volatile 不是"让操作变原子"，而是"在 volatile 读写之间建立 happens-before，并禁止跨越它的重排序"。它修好 DCL 靠的是**重排序约束**，不是原子性。这也解释了为什么 Java 内存模型（JSR-133，2004 年）把 volatile 的语义从"仅可见性"强化到"带 happens-before 的禁止重排" —— 老规范（Java 1.4 及以前）下 volatile 修不了 DCL，正是因为那时候 volatile 不禁止重排。Java 5 之后才修好，这是 JMM 演进史上最值钱的一课。

**Go 对照**：Go 没有 volatile 关键字，靠 `sync/atomic` 包（Go 1.19+ 有类型化原子变量 `atomic.Bool` / `atomic.Int64` / `atomic.Pointer[T]`）。Go 的 `atomic.Pointer` 对应 Java 的 `volatile Object`（安全发布），且 Go 的 atomic 承诺**顺序一致性（sequential consistency）**，比 Java volatile 的 happens-before 更强一档。

</details>

---

## 10.4 synchronized：不止是"加锁"

最基础的用法你得会，但这里只点出 Go 里没对应的点：

```java
public synchronized void foo() { /* 锁的是 this */ }          // 方法级：锁当前实例
public static synchronized void bar() { /* 锁的是类对象 */ }    // 静态方法：锁 Class 对象
public void baz() {
    synchronized (lockObj) { /* 锁的是 lockObj 这个对象 */ }    // 代码块：锁指定对象
}
```

**本质**：进入 `synchronized` 块前自动获取锁，退出时（无论正常返回还是抛异常）自动释放。这点是它比 `ReentrantLock` 安全的地方 —— 你不会忘记 `unlock()`。

> 【思考】为什么 synchronized 块里抛异常也不会死锁？JVM 是怎么保证"异常路径也释放锁"的？对比 Go 的 `defer mu.Unlock()`，机制一样吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：靠字节码层面的 `monitorenter` / `monitorexit`，且异常表（Exception Table）保证异常路径也会执行 `monitorexit`。Go 的 `defer mu.Unlock()` 是语言结构保证，机制不同但效果等价。**

**看字节码：**

```java
public void foo() {
    synchronized (this) { doWork(); }
}
```

```
   0: aload_0
   1: astore_1
   2: monitorenter          ← 进入：抢锁
   3: aload_0
   4: invokevirtual  doWork
   7: aload_1
   8: monitorexit           ← 正常退出：释放锁
   9: goto          17
  12: astore_2              ← 异常分支
  13: aload_1
  14: monitorexit           ← 异常路径也释放锁！
  15: aload_2
  16: athrow                ← 重新抛出异常
  17: return
Exception table:
   from 3 to 9   target 12   any   ← 覆盖整个同步块，任何异常都跳到 12
```

注意异常表那行：`from 3 to 9` 这段（同步块主体）抛任何异常，都跳到 12，而 12→14 一定执行 `monitorexit`。所以**无论怎么抛，锁都会释放**，不会死锁。这是 JVM 在字节码生成阶段就钉死的结构保证，不是靠程序员记性。

**Go 的对照：**

```go
mu.Lock()
defer mu.Unlock()   // defer 保证函数退出（含 panic）时执行 Unlock
doWork()
```

`defer` 是 Go 语言的关键字，由编译器插入"函数返回前执行 defer 队列"的逻辑，panic 也会触发。所以两者**效果一样（异常/panic 都释放锁），机制不同**：synchronized 是 JVM 字节码结构（monitorenter/exit + 异常表），`defer` 是语言结构（defer 栈）。

**更深一层**：这正是两种语言"保证安全"的两种思路。Java 把"释放锁"做成了**块级结构的内禀语义**（进了 synchronized 就注定会出），Go 把它做成了一个**显式的、可组合的语句**（`defer`）。Go 的好处是 `defer` 能释放任何资源（锁、文件、连接），不局限于锁；Java 的好处是 synchronized 你"想忘都忘不掉"，而 `ReentrantLock` 一旦你忘了 `finally { unlock() }` 就真死锁了。所以经验法则：**能用 synchronized 解决的，就别上 ReentrantLock** —— 除非你需要 10.5 那几条 ReentrantLock 独有的能力。

</details>

### 可见性保证

`synchronized` 退出时，会把块内的写操作刷到主存；进入时，使本地缓存失效，从主存重读。所以：**synchronized 块内的写，对后续获取同一把锁的线程可见**。这就是 happens-before 的"管程规则"（10.2 第 2 条）。换句话说，`synchronized` 不只是互斥，它还隐含了可见性。

### synchronized 能禁止重排序吗？

能。它和 `volatile` 一样提供 happens-before 保证：进入 synchronized 之前的写 happens-before 后续获得锁的读。临界区内的操作不会被重排到临界区外、跨线程看到。所以 `synchronized` 同时保证**原子性 + 可见性 + 有序性**三件事；而 `volatile` 只保证可见性 + 有序性（单变量），不保证复合操作的原子性。

### 可重入性（一个真实的、Go 里没有的差异）

同一个线程可以重复获取同一把锁，JVM 内部用计数器记录重入次数，每退出一层减一，减到 0 才真释放。这就是 `ReentrantLock` 名字的由来。

**Go 的 `sync.Mutex` 不可重入。** 同一个 goroutine 在已经 `Lock()` 的 Mutex 上再 `Lock()`，会直接死锁（它不记录"谁持有"，只记录"是否被持有"）。这是你最容易踩的坑：从 Go 转过来，你默认"重入没事"，但在 Java 的 `synchronized` 里没事，在 Go 的 `sync.Mutex` 里炸。反过来也一样：你给 Go 写的可重入逻辑，搬到 Java 用 ReentrantLock 时得确认是不是真的想重入。

**问题 2：** synchronized 可重入，会有什么问题？

答案是**不会死锁，但会隐藏 bug**。典型场景：子类覆盖父类的 synchronized 方法并调用 `super`，因为可重入，不会死锁——但你以为"这个方法退出了锁就释放了"，其实还持有一层。这是可读性问题（锁的持有范围比你以为的大），不是死锁问题。Go 里没有继承，所以根本没有这个陷阱。

---

## 10.5 锁升级：synchronized 为什么"不慢了"

历史包袱得先讲清。Java 5 及之前，`synchronized` 是**重量级锁**：直接找 OS 的管程 mutex（`pthread_mutex`），涉及用户态/内核态切换，竞争激烈时慢得离谱。那时候并发老手都劝你用 `ReentrantLock`。

Java 6（Doug Lea 重写）引入了**锁升级**机制，把一把锁从"零成本"到"真内核锁"分了三级：

```
无锁 → 偏向锁 → 轻量级锁 → 重量级锁
```

1. **无锁**：对象刚创建，没人竞争。Mark Word 里锁标志位为 01。
2. **偏向锁**：只有一个线程访问这把锁。JVM 在对象头的 Mark Word 里记录这个线程的 ID（而不是真去抢锁）。该线程后续再进同步块，比对一下线程 ID 就过，**零竞争开销**，相当于"这把锁偏爱你了"。
3. **轻量级锁**：有多个线程**交替**访问（不是同时抢）。竞争发生时，线程用 CAS 把 Mark Word 改成指向自己栈里锁记录的指针，抢不到就**自旋**几次（在用户态空转等），避免陷入内核。适用于临界区极短的场景。
4. **重量级锁**：激烈竞争，自旋拿不到。线程被挂起，进入 OS 的阻塞队列（monitor 的 EntryList），等持锁线程释放后被唤醒。代价最大（涉及内核态切换 + 线程上下文切换），但最省 CPU。

每一步的代价递增、适用场景递减。核心认知：**无竞争时 synchronized 接近无开销；有竞争时退化但依然正确。** 这就是为什么现在没人劝你"别用 synchronized"了 —— 大多数业务代码临界区短、竞争不高，synchronized 跑得跟原子类一个量级。

> 【思考】既然 synchronized 现在这么快，为什么 Java 还需要 ReentrantLock？什么时候 synchronized 真的顶不住？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 ReentrantLock 有 5 种 synchronized 给不了的能力。synchronized 在"纯互斥"上已经够快，但快不等于够用。**

**能力一：定时锁 `tryLock(timeout)`。** synchronized 做不到"等锁最多 3 秒就放弃"。ReentrantLock 可以：

```java
if (lock.tryLock(3, TimeUnit.SECONDS)) {     // 等 3 秒拿不到就返回 false
    try { /* 临界区 */ } finally { lock.unlock(); }
} else {
    // 降级处理，而不是死等
}
```

这能避免"一把锁卡住，整个线程池跟着饿死"的雪崩（第 04.9 的短信雪崩案例，如果当时用 tryLock 就不会全 BLOCKED）。

**能力二：可中断 `lockInterruptibly()`。** 等待锁的过程中，别的线程调 `interrupt()` 能把它唤醒放弃等待。synchronized 一旦开始等，只能等到锁或被 `stop`（已废弃），无法中断。

**能力三：公平锁选项。** `new ReentrantLock(true)` 保证先来后到（FIFO），避免饥饿。synchronized 是**非公平**的，允许"插队"（刚释放锁的线程可能立刻又抢到，提高吞吐但可能饿死老等待者）。

**能力四：多个 Condition（多等待队列）。** 一个 ReentrantLock 可以 `newCondition()` 出多个等待队列，精确 `await`/`signal` 某一类等待者。synchronized 只有一个等待集（`wait()`/`notify()` 唤醒的是随机一个或所有，无法精准）。这是"按条件等待"的能力，Go 里你用 channel 分桶代替。

**能力五：能查询锁状态**（`isLocked()`、`getQueueLength()` 等），便于监控和诊断。

**更深一层**：synchronized 的设计目标是"够用且不会用错"（自动释放、语义简单），ReentrantLock 的设计目标是"给你全部控制权"。经验法则：**默认用 synchronized；当你需要超时、中断、公平、多 Condition 中任意一个时，才上 ReentrantLock。** 不要为了"显得专业"无脑用 ReentrantLock——忘写 `finally { unlock() }` 的代价比 synchronized 慢那点大得多。

</details>

**一个重要的演进**：偏向锁在 Java 15 被标记为废弃（JEP 374），Java 18 起默认禁用（`-XX:-UseBiasedLocking` 已成为历史）。原因很反直觉——**维护偏向锁的撤销（revoke）成本，在现代多核高竞争下反而高于它省下的那点开销**。大量线程频繁竞争时，偏向锁的"偏向记录 + 撤销"本身成了热点。这印证了一句老话：曾经的优化，在硬件演进后可能变成负担。Java 的锁优化从未停止。

**监视器（Monitor）的队列要记牢**，它解释了 `wait()`/`notify()` 的行为：

```
对象头
  └── Monitor
        ├── EntryList    ← 等锁的线程（对应 BLOCKED 状态）
        └── WaitSet      ← 调了 wait() 的线程（对应 WAITING 状态）
```

`wait()` 必须在 synchronized 内调用，它会**释放锁**、把自己挂进 WaitSet；被 `notify()` 唤醒后，要**重新抢锁**才能继续。`notify()` 只唤醒一个，`notifyAll()` 唤醒全部。这套语义和 Go 的 `sync.Cond`（`c.Wait()` / `c.Signal()` / `c.Broadcast()`）一一对应，只是 Go 的 `sync.Cond` 也要先 `c.L.Lock()`。

---

## 10.6 AQS：Java 并发的发动机（本章的理论高峰）

`ReentrantLock`、`Semaphore`、`CountDownLatch`、`ThreadPoolExecutor` 的 worker 队列、甚至 `ReentrantReadWriteLock`…… 它们的底层都是**同一个东西**。这个东西叫 **AQS（AbstractQueuedSynchronizer）**。理解它，等于理解了 Java 并发工具箱一半的底层。

### AQS 的核心三件套

1. **一个 `volatile int state`**：同步状态。比如 ReentrantLock 用它记重入次数（0=没锁，>0=被持有几次），Semaphore 用它记剩余许可数。
2. **一个 CLH 变体的等待队列**：一个双向链表，装着所有抢锁失败、被挂起的线程。为什么是双向链表而不是数组或单向队列？因为唤醒时需要从队头取、取消等待（超时/中断）时需要把自己从中间摘掉，双向链表能在 O(1) 完成"中间节点的删除"，单向做不到。CLH 原本是 Craig、Landin、Hagersten 提出的自旋锁队列，AQS 把它改成"自旋几次抢不到就 park"的变体——既保留了队列的 FIFO 公平性，又用 park 避免了纯自旋烧 CPU。
3. **CAS 修改 state**：用 `compareAndSetState` 原子地改 state，抢锁就是抢改 state 的权利。CAS 失败意味着有别人抢先了，于是走"入队 + park"的路径。

### 两种模式

- **独占模式（Exclusive）**：同一时刻只有一个线程能拿锁。`ReentrantLock` 是典型。
- **共享模式（Shared）**：多个线程可以同时拿。`Semaphore`（多个许可）、`CountDownLatch`（计数到 0 唤醒所有等待者）是典型。

### 用 ReentrantLock.lock() 走一遍

```
1. 线程调用 lock()
2. CAS 把 state 从 0 改成 1
     成功 → 拿到锁，记录自己为 owner，返回
     失败 → 进入第 3 步
3. 把自己包装成 Node，加入 CLH 队列尾部
4. 自旋几次尝试 CAS 抢锁（自适应自旋）
5. 还抢不到 → 调用 LockSupport.park() 挂起自己（让出 CPU）
6. 持锁线程 unlock()：
      CAS 把 state 减回 0（完全释放）
      unpark() 队列头部的线程
7. 被唤醒的线程回到第 2 步重新抢
```

这套"CAS 抢 + 抢不到进队列 + park 挂起 + 释放时 unpark 下一个"的流程，是 Java 并发工具的统一骨架。

> 【思考】AQS 用 `volatile state` + CAS，这不就是 Go 的 `atomic.Int64` + `runtime_Semacquire` 那一套吗？它俩到底是不是同一个思想？

<details>
<summary><b>参考答案</b></summary>

**直接答案：极其相似，是"同一个思想的两种实现"。** AQS 和 Go 的 `sync.Mutex` 在抽象层几乎一一对应。

**逐件对照：**

| AQS（Java） | Go `sync.Mutex` | 作用 |
|---|---|---|
| `volatile int state` | Mutex 内部的 `state` 字段（也是 atomic 访问） | 记录锁状态（0/1/重入） |
| CLH 变体等待队列（双向链表） | goroutine 等待队列（runtime 内部的 sudog 链表） | 存抢锁失败的线程 |
| `compareAndSetState`（CAS） | `atomic.CompareAndSwap` / `runtime_Semacquire` 前的 CAS | 抢锁的原子操作 |
| `LockSupport.park()` | `runtime.gopark()` | 抢不到就挂起自己 |
| `LockSupport.unpark()` | `runtime.goready()` | 释放时唤醒下一个 |

**Go 的 `sync.Mutex` 底层也是**：先 CAS 抢 state（0→1），抢不到就自旋几次，还不行就把自己排进等待队列，用信号量（`sema` 字段，本质是一个 `uint32` + 休眠/唤醒原语）挂起；释放时 CAS state→0，并 `ready` 队列里下一个 goroutine。跟 AQS 的流程逐字对应。

**那差异在哪？** 不在思想，在细节：
- AQS 是个**框架**，通过继承让 `ReentrantLock`/`Semaphore`/`CountDownLatch` 复用同一套队列逻辑；Go 的 Mutex 是个**具体实现**，没有"框架化"，每种同步原语各自写。
- AQS 的 state 是 `int`，用法由子类定义（ReentrantLock 当重入计数，Semaphore 当许可数）；Go 的 Mutex state 语义固定。

**更深一层**：这说明"用原子变量抢锁 + 抢不到就排队 + 挂起/唤醒"是**多核并发的正确通用解**，不分语言。你作为 Go 老兵，看懂 AQS 不需要新概念，只需要把 `state/CAS/park` 翻译成你已知的 `Mutex.state/CAS/gopark`。这也是为什么我说"你的 Go 经验是资产"——AQS 对你来说不是新知识，是老朋友换了张 Java 脸。

</details>

> 【思考】既然 CAS 能抢锁，为什么抢不到要"自旋几次 + 再排队"？直接阻塞不行吗？一直自旋不行吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：自旋和阻塞各有适用场景，AQS（和 Go Mutex）的策略是"先自旋试探，失败再 park"，把两种代价折中。**

**一直自旋的代价：** 自旋不放弃 CPU，适合**临界区极短**（几十纳秒）的场景——自旋几百个周期抢到了，比一次上下文切换（微秒级）便宜。但临界区长时，自旋线程空转烧 CPU，还占着核不让别人用，纯亏。

**直接阻塞的代价：** 阻塞（park）要陷入内核、线程上下文切换、唤醒时再来一次切换，每次几微秒到几十微秒。临界区极短时，一次切换的代价比"自旋抢到"高一个量级，不划算。但临界区长时，阻塞让出 CPU 是正确选择。

**所以两者结合：** AQS 在 CAS 抢锁失败后，先**自适应自旋**若干次（Java 6 之后是自旋次数自适应：上次抢到了就多旋几次，上次没抢到就少旋），期间如果持锁线程很快释放，就直接拿到，零切换；自旋还拿不到，说明临界区不短或竞争真激烈，才 `park` 挂起。这是 Java 6 之后锁优化的核心思路，也是 Go `sync.Mutex` 的思路（先自旋后 sema）。

**代码锚点（Go Mutex 的精炼版逻辑）：**

```go
func (m *Mutex) Lock() {
    // 快速路径：CAS 抢 state 0->1
    if atomic.CompareAndSwapInt32(&m.state, 0, mutexLocked) {
        return
    }
    // 慢路径：自旋 + 排队
    for {
        // 自旋几次（runtime 内部，基于 active_spin 参数）
        // 还抢不到 → 入等待队列，sema 休眠
        runtime_SemacquireMutex(&m.sema, ...)
    }
}
```

**更深一层**：这背后是并发工程里一个永恒的权衡——**"等"有两种成本，CPU 成本（自旋）和延迟成本（阻塞的唤醒延迟）**。最优解是"短等用自旋、长等用阻塞"，而"多短算短"无法静态知道，所以用自适应自旋去动态试探。Java 和 Go 的锁，最终都收敛到这个解法，又一次证明好设计会被不同语言独立发现。

</details>

---

## 10.7 常见并发工具：从 Go 的视角快速对应

这张表是本章的落点。每个 Java 工具，给你 Go 对照 + 关键注意点。建议存下来，写 Java 并发时对照着选。

| Java | Go 对照 | 注意点 |
|---|---|---|
| `synchronized` | `sync.Mutex`（但不可重入） | JVM 保证异常路径也释放锁 |
| `ReentrantLock` | 无直接对应（需自己实现可重入） | 有 tryLock/中断/公平/多 Condition |
| `volatile` | `atomic.Int64`/`atomic.Bool` 的读写 | Java 不保证读-改-写原子性 |
| `AtomicInteger` / `LongAdder` | `atomic.Int64` | LongAdder 分段计数，高并发更优 |
| `CountDownLatch` | `sync.WaitGroup` | 一次性，计数到 0 放行 |
| `CyclicBarrier` | 无（需 chan + 手动计数） | 可重用， cyclic 指能反复用 |
| `Semaphore` | 无直接对应（需 chan 限流） | 限流、控制并发数 |
| `LockSupport.park/unpark` | `runtime.gopark/goready`（底层） | 线程挂起/唤醒原语 |
| `Condition` | 无（chan 替代） | 多条件等待，synchronized 只有一个等待集 |
| `Phaser` | 无 | 分阶段栅栏，比 CyclicBarrier 灵活 |
| `StampedLock` | 无 | 乐观读锁，读多写少场景 |
| `ReadWriteLock` | 无（需 `sync` + 自己计数） | 读写分离，读共享写独占 |

注意这一列大量的"无直接对应"。原因你在 10.1 就懂了：Go 的并发原语少而精（channel + Mutex + atomic + WaitGroup + Once + Pool + Cond），靠组合解决问题；Java 因为线程贵、共享内存是主流，发展出了一整套细分工的并发类。你看这张表时，重点不是"背下来"，而是建立反射：**"我在 Go 里用 X 解决的，Java 里对应 Y，Y 的坑是 Z。"** 举个例子：`Semaphore` 在 Go 里你多半用 `chan struct{}` 当令牌桶实现（发请求前 `<-sem`，发完 `sem <- struct{}{}`），思路一致，但 Java 把它做成了带公平/非公平、可中断、可超时的成熟类——这就是"库内置"和"自己组合"的差别。

---

## 10.8 实战：四个并发 bug 案例

每个案例按 现象 → 根因 → 修复 → 教训 四件套走。前两个是本章核心，后两个补上死锁和 DCL。

**案例一（可见性）：关不掉的 worker。**

现象：一个后台 worker 线程 `while(running)` 死循环处理任务，主线程在收到退出信号时设 `running=false`，但 worker 永远不停止，进程关不掉。

```java
private boolean running = true;          // 错误：没有 volatile
public void start() {
    new Thread(() -> {
        while (running) { processOne(); }   // 永远读的是自己缓存里的 true
    }).start();
}
public void stop() { running = false; }  // 主线程改了，worker 看不到
```

根因：没有 volatile，`stop()` 的写对 worker 线程不可见（缓存没失效）。JIT 甚至能把 `while(running)` 提升成 `while(true)`（第 04.7 讲的提升优化）。

修复：`private volatile boolean running = false;` 或改用 `AtomicBoolean`。

教训：**多线程共享的标志位必须 volatile（或原子类）。** 这是并发代码里最高频的一类 bug。

**案例二（原子性）：丢更新的计数器。**

现象：一个 `@GetMapping` 接口统计总请求数（QPS 看板用），压测下计数永远比实际请求数少一大截。

```java
private int count = 0;                    // 错误：i++ 非原子
@GetMapping("/hit")
public void hit() { count++; }            // 多线程交叉，丢更新
```

根因：`count++` 是 `getfield`/`iadd`/`putfield` 三步，非原子，高并发下大量更新丢失（见 10.3）。

修复：

```java
private final AtomicLong count = new AtomicLong();        // 中等并发
// 或高并发 QPS 统计：
private final LongAdder count = new LongAdder();          // 分段计数，吞吐更高
public void hit() { count.increment(); }
```

教训：**任何 `count++`、累加、生成序号之类的"读-改-写"，在并发下必须用原子类。** 这是你 Go 里用 `atomic.AddInt64` 的同款纪律，搬到 Java 别松。

**案例三（死锁）：锁顺序不一致。**

现象：两个方法各自要锁 A、B 两把锁，偶尔整个服务卡死，jstack 末尾打印 `Found one Java-level deadlock`。

```java
// 线程 1：先锁 A 再锁 B
synchronized (lockA) { synchronized (lockB) { transfer(); } }
// 线程 2：先锁 B 再锁 A  ← 顺序反了
synchronized (lockB) { synchronized (lockA) { transfer(); } }
```

根因：线程 1 拿着 A 等 B，线程 2 拿着 B 等 A，互相等，死锁。

修复：统一全局锁顺序（永远先 A 后 B），或改用 `ReentrantLock.tryLock(timeout)` 避免永久死锁（见 10.5 能力一）。

教训：**按固定顺序获取多把锁；能用超时锁就用超时锁**。Go 的 `sync.Mutex` 没有 tryLock（虽然后来有 `TryLock`），死锁更难破，所以 Go 里更要靠"固定锁顺序 + 缩小临界区"规避。

**案例四（DCL 单例）：半初始化的对象。**

完整代码见 10.3 的 DCL 示例。`instance` 不加 `volatile` 时，另一个线程可能拿到 `instance != null` 但字段全默认值的对象。修复就是给 `instance` 加 `volatile`（原理见 10.3 的【思考】）。

教训：**单例的 DCL 必须 `volatile`。** 这是 Java 并发面试的钉子户，也是 happens-before + 重排序最经典的实战题。

---

## 10.9 本章核心结论

1. **Go 是 M:N 用户态调度，Java 传统线程是 1:1 内核线程。** 这个差异是 Java 所有并发"麻烦"（线程池、锁优化、Reactor、虚拟线程）的总根。
2. **JMM 要解决的不是"顺序"，是"可见性"与"有序性"。** 三个来源：CPU 缓存、指令重排序、内存屏障。happens-before 是判断可见性的唯一公理。
3. **`volatile` 保证可见性 + 禁止重排序，但不保证原子性。** `i++` 永远别用 volatile 裸写，用原子类或 LongAdder。
4. **`synchronized` 同时保证原子性 + 可见性 + 有序性**，且异常路径由 JVM 自动释放锁（monitorenter/exit + 异常表）。Go 的 `defer mu.Unlock()` 是等价机制但不同实现。
5. **synchronized 现在不慢了**，靠锁升级（无锁→偏向锁→轻量级锁→重量级锁）把无竞争开销压到极低；偏向锁在 Java 18 默认禁用，因现代多核下维护成本反超收益。
6. **AQS 是 Java 并发的发动机**，核心是 `volatile state` + CLH 队列 + CAS，和 Go 的 `sync.Mutex` 是同一思想的两种实现。
7. **ReentrantLock 不是用来替代 synchronized 抢性能，是用来补能力**：tryLock 超时、可中断、公平锁、多 Condition。
8. **Go 没有 Java 那一大票并发类，是因为 goroutine 廉价、共享内存非主流**；你转 Java 时要主动建"X 对应 Y"的反射，别照抄 Go 的"随便开 goroutine"写法。

---

## 10.10 深度思考题

### 题 1：volatile 和 synchronized 都能保证可见性，它们的本质区别是什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：volatile 只保证"单个变量的读写可见 + 禁止重排"，不保证复合操作原子；synchronized 保证"一段代码的原子性 + 可见性 + 有序性"（临界区整体）。volatile 是无锁的、开销小；synchronized 是加锁的、有竞争时线程挂起。**

**逐层对比：**

- **原子性**：`volatile int i; i++;` 仍然丢更新（读-改-写三步被插空）；`synchronized { i++; }` 三步被锁包成原子，不丢。这是最本质的区别。
- **可见性**：两者都保证"写对其他线程可见"。但 synchronized 的可见性范围是"整个临界区内的所有写"，volatile 只针对那一个变量。
- **有序性**：两者都禁止重排，但 synchronized 禁止的是"临界区内的操作被重排到临界区外 / 跨线程看到乱序"，粒度是整段代码；volatile 禁止的是"volatile 读写跨越彼此重排"。
- **开销**：volatile 是内存屏障（几纳秒到几十纳秒），无锁无阻塞；synchronized 在竞争激烈时涉及 park/unpark（微秒级上下文切换）。

**代码锚点：**

```java
// volatile：只管可见，不管原子
private volatile int a;
a++;                       // 仍然非线程安全

// synchronized：管原子 + 可见 + 有序
private int b;
public synchronized void inc() { b++; }   // 线程安全
```

**更深一层**：可以这样记——`volatile` 是"给一个变量贴'别缓存、别重排'的标签"，`synchronized` 是"给一段代码加'同一时刻只有我能进'的围栏"。前者解决"你看到了旧值"，后者解决"你和我同时改乱了"。很多并发 bug 的误诊是"加了 volatile 以为就安全了"，其实要的是原子性，该用锁或原子类。

</details>

### 题 2：为什么 Java 需要 LongAdder 而 Go 的 atomic.Int64 就够了？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不是 Go 不需要，是 Go 标准库没内置"分段计数"，而 Java 用 LongAdder 把"伪共享（false sharing）"问题在库层面解决了。高并发下两者都面临同一个物理瓶颈：缓存行争用。**

**伪共享是什么：** 现代 CPU 缓存以"缓存行"为单位（通常 64 字节）在核间搬运。如果 `AtomicLong` 的 value 和别的频繁写的变量落在**同一个缓存行**，一个核改了 value，会让其他核的这行缓存全部失效，被迫从主存重读——即使它们改的是行里另一个字段。这叫"伪共享"，名字的讽刺在于：两个核其实没共享同一个变量，却被缓存一致性协议当成共享了。

**LongAdder 的解法：** 内部维护一个 `base` 加一个 `Cell[]` 数组，每个 Cell 用 `@Contended` 注解**独占一个缓存行**（padding 把 Cell 撑满 64 字节，避免和邻居伪共享）。无竞争时直接加 base；有竞争时，线程被哈希到不同 Cell 各自累加；`sum()` 时把所有 Cell + base 加起来。这样高并发下各线程写不同缓存行，没有 ping-pong，吞吐暴涨。

**Go 这边：** `atomic.Int64` 在 AMD64 上同样有缓存行争用问题。Go 高性能代码里靠**手动分片**规避：

```go
type ShardCounter struct {
    counters []atomic.Int64   // 每 CPU 一个，减少争用
}
func (c *ShardCounter) Inc() {
    c.counters[getCPUID()%len(c.counters)].Add(1)
}
```

所以不是"Go 不需要"，是 Go 把这个优化交给了你（库作者/你手写），Java 把它做进了 `LongAdder` 这个开箱即用的类。两种取向：Java 标准库更"全"（把常见并发优化都内置），Go 标准库更"少"（给你积木，组合是你的事）。

**更深一层**：伪共享是**多核架构的物理事实**，不分语言。LongAdder vs 分片计数，是"库内置优化" vs "用户手动优化"的哲学差异，不是能力差异。QPS 统计用 LongAdder（不需要精确），生成全局递增 ID 用 AtomicLong（必须精确）——这个选择 Go 里也一样。

</details>

### 题 3：synchronized 块里能不能用 Thread.sleep()？会有什么后果？

<details>
<summary><b>参考答案</b></summary>

**直接答案：语法上能，工程上是灾难。synchronized 块里的 `Thread.sleep()` 会**带着锁睡觉**，期间所有想进同一把锁的线程全部 BLOCKED，临界区被无意义地拉长几十上百毫秒。**

看代码：

```java
public synchronized void handle() {
    doLocalWork();          // 毫秒级
    Thread.sleep(1000);     // 错误：抱着锁睡 1 秒
    doMoreWork();
}
```

`sleep()` **不会释放锁**（它只是让当前线程暂停，锁还握在手里）。这 1 秒里，这把锁被独占，其他线程全卡在门口。如果这是个 HTTP 请求处理入口，50 个线程的池子，5 个线程同时进这个方法 → 5 把锁各睡 1 秒 → 这 1 秒内最多 5 个请求在推进，其余 45 个全 BLOCKED。吞吐直接塌方。

**和 `wait()` 的关键区别**：`wait()` 会**释放锁**再睡，醒来重新抢；`sleep()` 不释放。很多人混淆这两者。Go 里没有这个坑（goroutine 没有"持锁睡觉"的概念，你 `time.Sleep` 时 Mutex 要么没 Lock 要么已经 Unlock）。

**更深一层**：这条规则可以推广成一句铁律——**synchronized / 任何锁的临界区里，绝对不要做任何"慢操作"（sleep、网络 IO、磁盘 IO、长循环）**。锁的持有时间要按"微秒"算。第 04.9 的"短信雪崩"就是同步 HTTP 调用抱锁 30 秒，本质和这道题一模一样。

</details>

### 题 4：一个方法 synchronized，另一个方法没 synchronized，两个线程一个调同步的一个调不同步的，会怎样？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不同步的那个方法完全不受保护——synchronized 保护的是"锁"，不是"方法"或"对象的数据"。两个线程会同时操作同一份数据，照样数据竞争。**

这是最经典的误解："我给方法加了 synchronized，这个类就线程安全了。"

```java
class Counter {
    private int n = 0;
    public synchronized void inc() { n++; }   // 持锁
    public void get() { return n; }            // 错误：没持锁，随便读
    public void set(int v) { n = v; }          // 错误：没持锁，随便写
}
```

线程 A 调 `inc()`（持锁改 n），线程 B 调 `set(100)`（**不持锁**直接改 n）—— 两者没有任何互斥，B 的写会插在 A 的 `getfield`/`putfield` 之间，结果错乱。`get()` 同理：A 正在 `n++` 的三步中间，B 的 `get()` 读到一个半成品值。

**本质**：synchronized 的互斥语义建立在"大家都去抢**同一把锁**"上。只要有人不抢这把锁（方法没加 synchronized、或锁了不同的对象），互斥就破了。线程安全要求**所有访问共享可变状态的路径都受同一把锁保护**，漏一个就前功尽弃。

**更深一层**：这就是为什么"给某个方法加 synchronized 就线程安全"是新手幻觉。正确做法是：把"哪些字段是可变的、谁会改、谁会读"列清楚，确保**每一条读写路径都进入同一个 synchronized 块（或同一个原子类 / 同一把 Lock）**。Go 里没有 synchronized 方法，你用 `mu.Lock()` 保护，反而更不容易产生"方法自动安全"的错觉——但 Go 同样要求"所有路径都 Lock"，漏一个 `defer mu.Unlock()` 的读路径，一样竞争。

</details>

### 题 5（开放题，无标准答案）：如果你是 JVM 设计者，你会怎么让 Go 式 goroutine 在 JVM 上跑起来？

> 这道是承上启下。给你方向，别急着看第 12 章，自己推一遍：用户态调度（M:N）+ 载体线程（carrier thread）+ 阻塞时让出——思路清晰。但真正的难点是：**synchronized 和 native 阻塞怎么处理？** 一个虚拟线程卡在 `synchronized` 上是占着载体线程还是让出？卡在 JNI 的 C 代码里（OS 根本不知道它是虚拟线程）还能让出吗？这正是 Project Loom 踩了十年的坑。先想清楚你的取舍，第 12 章我们逐条对照 goroutine 验证。

---

## 下一章预告

这一章你建立了 Java 并发的完整心智模型：从 JMM 的可见性/有序性，到 volatile 的"只管可见不管原子"，到 synchronized 的锁升级和自动释放，再到 AQS 这台发动机——而且你发现 AQS 和 Go 的 `sync.Mutex` 是同一思想的两种实现。

但有两个最常用、最容易被配错的东西本章只提了名字：**线程池**和**CompletableFuture**。你一定会问："线程池核心/最大线程数怎么配才不会雪崩？队列用 `LinkedBlockingQueue` 还是 `SynchronousQueue`？`CompletableFuture` 的回调到底跑在哪个线程上？" 第 11 章《并发工具箱》专门回答这些，并且承接本章的"线程是昂贵 OS 资源"——告诉你怎么把有限的线程喂得刚刚好，以及 Future/CompletionStage 这套"回调地狱"在 Java 里怎么写才不像地狱。
