# 第 13 章　JVM 性能工程：GC 调优、内存泄漏与 JMH（看到 GC 日志能推理）

> 你接手了一个订单服务。每天凌晨 2 点，它的接口 P99 从 50ms 一路飙到 2s，持续十几秒，然后又恢复正常。你翻监控，发现那个时间点正好有一次 Full GC。你打开前任留下的 JVM 启动参数，看到两行：`-XX:+UseConcMarkSweepGC`，还有 `-Xmx2g`。
>
> 你的第一反应是"这参数谁配的"。但你马上发现，自己其实也配不出来——你不知道该选哪个 GC、不知道该给多大堆、不知道那十几秒的停顿到底从哪来。这一章不给你"调优模板"，给你一套推理框架：看到 GC 日志，你能自己推出来该调什么。

---

## 13.1 GC 算法全景：你必须知道有哪几类

调优的第一步不是背参数，是建立坐标系。你得先知道 JVM 手里有哪些牌，才能谈"选哪张"。

GC 要解决的根本问题只有两个。第一个是"怎么判定对象死了"——第 04 章讲过，Java 和 Go 都用可达性分析（从 GC Roots 出发顺着引用链走，走不到的就是垃圾），而不是引用计数（引用计数搞不定循环引用，第 04 章 04.7 有演示）。第二个是"怎么把死对象占的内存收回来"，这一步有三条路：

- **标记-清除**：先标出垃圾，再清掉。快，但会产生内存碎片，碎片多了之后大对象没地方放，被迫提前 Full GC。
- **标记-整理**：标完之后把所有活对象往一端挤，腾出连续空间。没有碎片，但移动对象要更新所有引用，成本高、STW 时间长。
- **复制**：把内存分成两半，活对象从一半拷到另一半，剩下的整块清空。没有碎片、速度快，但永远浪费一半空间。新生代的 Survivor 区就是这么干的。

这三条路没有谁绝对好，只有"在哪种内存布局下划算"。而把它们组织起来的核心思想，叫**分代假说**。

### 分代假说：现代 GC 的地基

**弱分代假说**：绝大多数对象朝生夕死。你写一个 `new ArrayList()` 处理一次请求，请求结束它就死了。这类对象占 99% 以上，但存活时间极短。

**强分代假说**：熬过越多次 GC 的对象，越难死。一个被塞进缓存的单例配置对象，活了三天，它大概率还能再活三天。

这两个观察合起来，直接推导出 JVM 的堆布局：**堆被分成新生代（Young，Eden + 两个 Survivor S0/S1）和老年代（Old）**。新对象先扔 Eden，熬过一次 Young GC 就晋级到 Survivor，再熬几轮就进老年代。新生代用"复制"算法（反正大部分都死了，要复制的很少），老年代用"标记-整理"或"标记-清除"（对象活得久，不值得频繁搬）。

记住这条线，后面所有 GC 都是在这个骨架上做变体。

### 主流 GC 逐个看

| GC | 引入版本 | 算法 | 特点 | 适用 |
|---|---|---|---|---|
| Serial | 远古（JDK 1.3 前） | 单线程标记整理 | 最慢，但实现简单、内存占用极小 | 客户端 / 嵌入式 / 单核 |
| Parallel (Throughput) | 默认（JDK8 及之前） | 多线程标记整理 | **吞吐高、停顿长** | 后台批处理、离线计算 |
| CMS | JDK 1.4 引入 / JDK 9 废弃 / JDK 14 移除 | 并发标记清除 | 停顿短，但**碎片 + 并发失败 → Full GC** | 老服务（已淘汰） |
| G1 | JDK 7 引入 / JDK 9 起默认 | 分区 + 增量整理 | **可预测停顿**（`MaxGCPauseMillis`） | 服务端默认 |
| ZGC | JDK 11 实验 / JDK 15 生产 | 着色指针 + 并发 | **亚毫秒停顿（<10ms），无论堆多大** | 大堆低延迟 |
| Shenandoah | JDK 12 引入 | 并发整理 | 低停顿（略逊 ZGC） | 低延迟备选 |

> 【思考】为什么 G1 成了默认？它比 CMS 好在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 CMS 有个致命缺陷——并发模式失败（concurrent mode failure）会触发一次 Stop-The-World 的 Serial Old 全量整理，停顿可能长达几十秒；而 G1 用"分区 + 增量并行整理"从根上避免了碎片和这种长停顿，还能按 `MaxGCPauseMillis` 目标动态调节。**

**CMS 的死穴在哪？** CMS 想做到"大部分回收与业务线程并发"，所以它用标记-清除（不整理）。问题来了：

1. **碎片**。标记-清除不移动对象，跑久了老年代全是空洞。某天要放一个大对象，连续空间不够，CMS 不得不退化成 Serial Old——一个**单线程、全堆、STW 的标记-整理**。在几十 GB 堆上，这一停就是十几秒甚至几十秒，期间整个应用无响应。这正是你接手那个服务凌晨 2 点 P99 飙到 2s 的同类事故。

2. **并发失败**。CMS 回收的同时业务线程还在分配对象。如果老年代涨得太快，回收速度赶不上分配速度，CMS 直接放弃并发、强制 Full GC（同样是 Serial Old）。这是个正反馈陷阱：堆越大、并发越容易失败、停顿越长。

**G1 怎么解决？** G1 把堆切成上千个大小相等的 Region（默认 1~32MB），不再物理分代，而是逻辑分代。它的核心是两点：

1. **增量并行整理**：每次只回收"收益最高"（垃圾最多）的一部分 Region，而不是整个老年代。这样单次停顿可控，不会像 Serial Old 那样一口气扫全堆。
2. **可预测停顿模型**：你设一个 `MaxGCPauseMillis=200`，G1 会根据历史数据**自己决定这次回收多少 Region** 来尽量满足这个目标。它是"吞吐和停顿的平衡点"——既不像 Parallel 那样只顾吞吐不顾停顿，也不像 CMS 那样用碎片换短暂喘息。

**更深一层**：默认参数的选择，本质是"对大多数场景不坏"的妥协。G1 不是最快的（ZGC 停顿更短，Parallel 吞吐更高），但它在"吞吐、停顿、内存开销"三角里最均衡，所以成了默认。**这呼应了第 00 章卡点四的核心认知：JVM 参数多不是设计烂，是因为场景跨度太大，只能给一个平衡默认值。** 反过来想：你的服务如果明确是"低延迟交易系统"，默认 G1 就不是最优解——该上 ZGC（见下一个思考）。

</details>

> 【思考】ZGC 怎么做到"无论堆多大都不超过 10ms"？跟 Go 的 GC 比怎么样？

<details>
<summary><b>参考答案</b></summary>

**直接答案：ZGC 的核心黑科技是着色指针（colored pointers）——把 GC 状态信息（如"对象是否被标记""是否被移动中"）编码进对象指针的几位里，再配合读屏障（load barrier），让"标记"和"移动对象"都能与业务线程完全并发完成。对象被挪位置时，业务线程通过读屏障在访问指针时自动修正引用，应用线程根本感知不到对象被挪了。**

**先看传统 GC 为什么会被堆大小拖慢。** 标记阶段要扫所有活对象，整理阶段要移动对象并更新所有指向它的引用。堆越大，要扫、要搬的越多，STW 越长。G1 用"只搬一部分 Region"缓解，但单次仍然有 STW 的标记停顿。

**ZGC 的破局点：让"移动对象"这件事不再需要 STW。** 它把 64 位指针的高几位（在 Linux/x64 上用 44 位地址，留出 4 位做标记）拿来存 GC 状态。比如某一位表示"这个对象正在被移动"。当业务线程读到一个"正在移动中"的指针时，读屏障（一段在每次从堆里读对象引用时自动插入的小代码）会拦截这次读取，**顺便把指针修正到对象的新地址**，业务线程拿到的是修正后的有效引用。

```java
// 伪代码：读屏障在每次 "读取对象引用" 时自动发生
Object readBarrier(Object ptr) {
    if (isForwarded(ptr)) {          // 指针的"已移动"位被置位
        return getNewAddress(ptr);   // 返回新地址，业务线程无感知
    }
    return ptr;
}
```

因为标记和移动都在业务线程跑的同时做，STW 只剩下"扫描根集合"这一小步——而根集合大小跟堆大小无关，只跟线程数、栈深度有关。所以**无论堆是 2GB 还是 200GB，ZGC 的停顿都稳定在 10ms 内**。

**跟 Go 的 GC 对照（这是你最该记住的）：**

```go
// Go 的 GC 用三色标记 + 混合写屏障（hybrid write barrier）
// 业务 goroutine 分配对象时，写屏障记录指针变化，
// 标记线程并发地把灰色对象处理成黑色。
// STW 只有 "开启标记" 和 "结束标记" 两个极短窗口（<1ms）。
func main() {
    runtime.GC()            // 触发一次，但生产上由 runtime 自动按 GOGC 调度
    // Go 没有 "几十 GB 堆 + 亚毫秒" 的同等承诺
}
```

Go 的 GC 哲学是"**极短停顿优先**"——它用 tricolor + 写屏障把 STW 压到亚毫秒级，但**默认不分代、不移动对象**（对象是定点回收，靠 mcache 局部性），而且 Go 的堆通常比 JVM 服务小得多。Go 从不在"几十 GB 堆"上做性能承诺，因为它的典型场景是中小堆的云原生微服务。

**更深一层**：ZGC 和 Go GC 都在追求"停顿极短"，但走的是两条路。**ZGC 用"指针里塞状态 + 读屏障"换取"大堆下也能并发移动对象"**；**Go 用"不分代 + 写屏障"换取"实现简单、停顿稳定"**。这背后是目标场景的差异：JVM 要服务"几百 GB 堆、低延迟、长生命周期"的交易/大数据系统，Go 服务大多堆小、生命周期短、追求简单。两者没有谁更先进，只是**各自 optimized for 自己最常见的战场**。

</details>

### Go ↔ Java 性能工程对照表

把这一节讲的东西压缩成一张表，方便你随时回看：

| 维度 | Go | Java |
|---|---|---|
| GC 算法 | 非分代、三色标记 + 混合写屏障、不移动对象 | 分代（G1/ZGC）、可移动、多算法可选 |
| 停顿目标 | STW <1ms，长期稳定 | ZGC <10ms 与堆无关；G1 可预测；Parallel 长停顿高吞吐 |
| 调优旋钮 | `GOGC` / `GOMEMLIMIT`（极少，默认即对） | 几百个 `-XX:` 参数 |
| 进程的额外内存 | 无元空间/CodeCache/JIT，RSS ≈ 堆 + 栈 | 堆 + 元空间 + CodeCache + 直接内存 + 栈 + GC 结构 |
| 大堆低延迟 | 不擅长（典型堆较小） | ZGC 的强项（几百 GB 堆亚毫秒停顿） |
| 火焰图 | `go tool pprof` 标准库内置 | async-profiler / JFR 需另装 |
| 微基准 | `testing.B` 标准库 | JMH 独立框架 |
| 内存泄漏形态 | goroutine 泄漏、全局 map 累积 | static 集合、ThreadLocal 未 remove、资源未关 |

这张表是本章所有 Go 对照的汇总，也是你从 Go 思维切换到 JVM 思维的一张地图。

---

## 13.2 GC 日志：怎么读、怎么推理

GC 调优不是"调参数"，是"读日志 → 推理瓶颈类型 → 改一个变量 → 再读日志"。第一步永远是先把日志打开。

### 先把日志打开

JDK 9 之后是统一日志系统 `-Xlog`，别再用老掉牙的 `-XX:+PrintGCDetails` 了：

```bash
java -Xlog:gc*:file=gc.log:time,uptime,level:filecount=5,filesize=100M \
     -jar order-service.jar
```

拆解一下：`gc*` 表示所有 gc 相关标签；`time,uptime,level` 是日志装饰器（墙上时间、启动后时长、日志级别）；`filecount=5,filesize=100M` 是滚动文件，避免单个日志把磁盘写爆。`-Xlog:gc*` 是生产环境最基本的保险——出事后这是第一手现场。

**Go 程序员的对应物是 `GODEBUG=gctrace=1`**：设了之后每次 GC 会把摘要（耗时、堆增减、CPU 占比）打到 stderr，比如 `gc 1 @0.1s 2%: 0.2+0.3 ms clock, ... 4->4->2 MB`。它比 JVM 的 `-Xlog:gc*` 简陋得多（没有分代细节、没有暂停归类），但思路一样——**先把回收行为变成可读的数字**。你在 Go 里习惯看 `gctrace` 判断"是不是 GC 太频繁"，在 Java 里就是看 `-Xlog:gc*` 的 `Pause` 行和 `jstat -gcutil`。两种 runtime 都认同一件事：**GC 行为不可见，就无从调优**。

### 一次 Young GC 日志逐字段读

```
[0.123s] GC(0) Pause Young (Normal) (G1 Evacuation Pause) 45M->12M(256M) 3.2ms
```

别被它吓到，逐段拆：

- `[0.123s]`：启动后 0.123 秒发生。时间戳让你能把 GC 和监控上的 P99 毛刺对上号。
- `GC(0)`：第 0 次 GC 的编号，同一个编号贯穿这次 GC 的所有阶段日志。
- `Pause Young (Normal)`：一次普通的 Young GC，会 STW。
- `G1 Evacuation Pause`：G1 的"疏散停顿"——把 Eden 和 Survivor 里的活对象复制到新的 Survivor/老年代。
- `45M->12M(256M)`：**GC 前堆占用 45M，GC 后 12M，总堆容量 256M。** 这一组数字最关键：回收掉 33M，说明大部分对象死在了新生代（符合弱分代假说，健康）。
- `3.2ms`：**这次 STW 停顿时长。** 这是你最该盯的数。

### Full GC 的日志长什么样

Full GC 在日志里特征明显：`Pause Full GC` 字样，而且停顿时间往往以"秒"计，堆前后数字变化不大（因为该回收的已经在 Young/Old GC 里回收过了，Full GC 多半是被逼无奈的"全堆整理"）。如果你在日志里看到 `Pause Full GC (Ergonomics)` 或 `(System.gc())`，或者更糟的 `Pause Full GC (Allocation Failure)`，并且停顿动辄几百毫秒到几十秒——那就是事故信号。

### 四个关键指标

| 指标 | 定义 | 健康方向 |
|---|---|---|
| **吞吐（Throughput）** | 应用线程运行时间 / 总运行时间 | 目标 > 95% |
| **停顿时长（Pause Time）** | 单次 STW 持续时间 | 看 P99、看最大停顿，越低越好 |
| **频率** | 单位时间内 GC 次数 | Young GC 频繁但短可接受，Full GC 频繁就是灾难 |
| **晋升失败 / 并发模式失败** | 对象该进老年代但老年代放不下，或并发回收赶不上分配 | **大坑前兆，必须重视** |

吞吐和停顿是一对矛盾：Parallel GC 吞吐能到 99% 但停顿可能几百毫秒；ZGC 停顿 <10ms 但吞吐会损失几个点（并发回收要业务线程分担一部分工作）。**调优的本质，就是在你这个业务的容忍度里，给这对矛盾找一个平衡点。**

> 【思考】Young GC 频繁但每次很短，和 Full GC 很少但每次很长，哪个更该担心？

<details>
<summary><b>参考答案</b></summary>

**直接答案：Full GC 长停顿更该担心。因为 Full GC 的 STW 期间整个应用完全无响应，直接、线性地体现在 P99 上；而 Young GC 频繁只要每次 <10ms，业务线程大部分时间还在跑，吞吐未必受损。**

**为什么这么判？** 你接手那个服务，凌晨 2 点 P99 从 50ms 飙到 2s，持续十几秒——这形状就是典型的 Full GC STW：一次长停顿把那一瞬间所有请求都卡住，停顿结束大家恢复，P99 回落。如果是 Young GC 频繁，你会看到的是 P99 轻微、持续地抖动，而不是"断崖式"的十几秒。

**量化一下**：假设 Young GC 每 2 秒一次、每次 5ms，那么 1 秒内应用有 2.5ms 在 STW，吞吐损失 0.25%，用户基本无感。但如果每天一次 Full GC 停顿 15 秒，那一分钟里服务"消失"了 15 秒，P99 直接被这根针顶上去——哪怕一天只发生一次，告警照样炸。

**更深一层**：这个判断直接指导你的排查优先级。看到监控"偶发超时"，**第一反应应该是查 Full GC 日志**，而不是去优化 Young GC 频率。绝大多数"偶发 P99 毛刺"都是长停顿型 GC（Full GC / G1 的 Mixed GC 失控 / CMS 退化成 Serial Old）造成的。Young GC 调优通常是"锦上添花"，Full GC 治理才是"雪中送炭"。

**代码锚点（一个会触发 Full GC 的反模式）：**

```java
// 错误：分配一个刚好比老年代剩余空间大的数组，或 System.gc() 强行召唤 Full GC
List<byte[]> huge = new ArrayList<>();
for (int i = 0; i < 100000; i++) {
    huge.add(new byte[1024 * 1024]);   // 每个 1MB，很快塞满老年代
}
// 老年代放不下 → Allocation Failure → Full GC，停顿从毫秒级跳到秒级
```

</details>

---

## 13.3 内存泄漏排查：从"老年代一直涨"到"找到那行代码"

Java 有 GC，所以"内存泄漏"在 Java 里的意思跟 C 语言不一样。C 的泄漏是"malloc 了没 free，指针丢了"。Java 的泄漏是**"对象还被某个强引用链牵着，GC 永远收不掉，而这条引用链本不该这么长"**。GC 在卖力工作，只是对象"可达"，所以收不掉。

### 诊断信号

第 04 章讲过 `jstat -gcutil`，这里不重复命令，只讲推理：看 **O 列（老年代占用）**。正常服务，Full GC 之后 O 会明显回落。如果**多次 Full GC 之后 O 几乎不降，而且还缓慢往上爬**，那就是泄漏的铁证——这些对象全是可达的，有强引用在养着它们。

### 排查 SOP（承接第 08 章）

1. **`jmap -histo:live <pid> | head`** 看实例最多的类。注意 `:live` 会触发一次 Full GC（生产环境低峰期、慎之又慎），它能让你看到"GC 之后还活着的都是谁"。如果 `com.example.order.OrderDTO` 排进前 20，那你业务对象在堆积。
2. **堆转储 + MAT**：`-XX:+HeapDumpOnOutOfMemoryError` 自动 dump，或者用 `jcmd <pid> GC.heap_dump`。MAT 里看 **Dominator Tree**（谁真正占着内存）和 **Path to GC Roots**（排除弱/软引用），找到引用链顶端。
3. **顺着引用链找到"谁持有大对象"**。最常见的藏身处：static 集合、缓存、线程池里的任务、ThreadLocal。

这套 SOP 的本质是"从现象（老年代涨）一路顺藤摸瓜到根因（哪行代码持有了引用）"。你在 Go 里用 `pprof` 的 `top` 找分配最多的函数、再 `list` 看具体行，是同一套"先量化、再下钻"的逻辑，只是 Java 多了一层"MAT 画引用链"的可视化。

### 五种 Java 内存泄漏经典模式

**模式一：static Map 当缓存，只 put 不清理。**

```java
// 错误：static 集合生命周期 = 类生命周期 = 进程生命周期
public class OrderCache {
    private static final Map<String, Order> CACHE = new HashMap<>();
    public void add(Order o) { CACHE.put(o.getId(), o); }  // 永远只增不减
}
```

第 08 章 MAT 那个例子（`OrderCache.INSTANCE` 静态字段在引用链顶端）就是它。**这是头号嫌疑犯。**

**模式二：ThreadLocal 没 remove。** 第 04 章 04.7 详细讲过机制（弱 key + 强 value + 线程池长生命周期线程），这里给完整泄漏案例：

```java
// 错误：线程池线程 + ThreadLocal 存大对象，不清理
private static final ThreadLocal<BigContext> CTX = new ThreadLocal<>();
void handle(Request req) {
    CTX.set(loadHugeContext(req));   // 线程池 200 个线程，每个都留下一份
    process(req);
    // 忘了 CTX.remove() —— 这个线程下次处理别的请求时，旧的大对象还在
}
```

**模式三：未关闭的资源。** InputStream / Connection / Session 没 close，或者用 `try` 没 `finally close`。修复用 try-with-resources：

```java
// 错误：
InputStream in = new FileInputStream(f);
parse(in);   // parse 抛异常 → in 永不关闭 → 文件句柄泄漏

// 正确：try-with-resources 自动 close，无论是否异常
try (InputStream in = new FileInputStream(f)) {
    parse(in);
}
```

**模式四：监听器/回调没注销。** 注册了回调但对象本该死了，引用链不释放：

```java
// 错误：把自己注册成监听器，但忘了在销毁时 remove
eventBus.register(this);   // this 被 eventBus 强引用，永远收不掉
// 正确：提供 unregister，在生命周期结束时调用（或用弱引用版的事件总线）
```

**模式五：第三方库缓存在元空间。** 动态类生成（反射/CGLIB/规则引擎）导致 Metaspace OOM。第 04 章 04.3 讲过：类不卸载，元数据就不释放。常见于在循环里 `GroovyShell.evaluate(script)` 每次生成一个新类。

> 【思考】为什么 Go 很少听说"内存泄漏"？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不是 Go 不会泄漏，而是 Go 的引用关系更直白、没有"生命周期模糊"的机制，所以"该释放却没释放"的情况少得多。但 Go 有自己特色的泄漏——goroutine 泄漏和全局 map 累积。**

**Java 内存泄漏的高发性，根子在几个"生命周期模糊"的机制：**

1. **static 可变全局状态**。一个 `static Map` 想当缓存，忘了清理就永远涨。Go 没有"静态可变全局集合"这个普遍习惯——Go 的包级变量能改，但要你显式去改，且社区文化强烈反对隐式全局状态。
2. **finalize / 虚引用 / 软引用**这些延迟回收机制。对象的死亡时机被这些机制拖长，引用关系变得不直观。Go 没有 finalize，对象不可达就直接回收。
3. **ThreadLocal** 这种"线程级隐式状态"（第 04 章讲过）。Go 用 `context.Context` 显式传参，goroutine 结束栈上变量自动消失，物理上不可能泄漏。

**但 Go 的泄漏一样真实，只是换了形态：**

```go
// goroutine 泄漏：永久阻塞在 channel 上，永不退出
func leak() {
    ch := make(chan int)
    go func() {
        val := <-ch          // ch 永远没人有机会 send，这个 goroutine 永远阻塞
        fmt.Println(val)
    }()
    // 函数返回，但那个 goroutine 还在等 ch —— 泄漏了
}

// 全局 map 只增不减（对应 Java 的 static Map 缓存）
var cache = map[string]*User{}
func Add(u *User) { cache[u.ID] = u }   // 永远不删
```

**goroutine 泄漏**是 Go 里最典型的"生命周期比预期长的引用"——goroutine 持有它栈上/闭包捕获的所有变量，而 goroutine 自己不退，那些变量就跟着活。这跟 Java 的"static 集合泄漏"本质完全一样：**都是"有一条本不该存在的长生命周期引用链"**。

**更深一层**：Java 和 Go 的"泄漏"本质相同，差异只在**表现形式和排查难度**。Java 泄漏往往藏在框架的隐式状态里（ThreadLocal、Spring 单例、static 缓存），需要 MAT 顺藤摸瓜；Go 泄漏往往是**你亲手写的 goroutine 没退出**，用 `go tool pprof` 的 goroutine profile 一眼就能看到几千个卡在同一个 `<-ch` 上。所以 Go 泄漏"更容易被自己写出来并自己发现"，Java 泄漏"更容易被框架偷偷制造"。

**给老哥的实战建议**：在 Java 里看到"老年代只增不减"，先全局搜 `static` + `Map`/`List`/`Cache`，再搜 `ThreadLocal` 有没有配对的 `remove()`。这两类占了 Java 内存泄漏的八成。

</details>

---

## 13.4 火焰图：找到"最烫"的那段代码

CPU 高、响应慢，但你不知道卡在哪。这时候光看 GC 日志没用——GC 正常，问题在应用代码本身。火焰图就是干这个的。

### async-profiler：生产可用的采样器

```bash
# 下载 async-profiler，attach 到目标进程，无需重启、无需改代码
./async-profiler/profiler.sh -d 30 -f flamegraph.html <pid>
# 默认 -e cpu：采样 CPU 热点，30 秒，输出 HTML 火焰图
```

它开销极低（基于 AsyncGetCallTrace + perf_events，不需要 safepoint 对齐），生产可以放心用。第 08 章 08.4 也提过它，这里讲"怎么读"和"选哪种模式"。

### 怎么读火焰图

**横向是采样占比，纵向是调用栈深度。** 最底下的框是入口（main、线程 run），往上每一层是被谁调用的。一个框越宽，说明它在采样里出现的比例越高——也就是越"烫"。

**找"又宽又平"的框。** 宽表示占比高，平表示它没有再往下分叉（或者分叉很少）——也就是说，时间就耗在这一层本身，而不是它的子调用。那个框对应的函数，就是你要优化的热点。

### 三种 profiler 模式（极其实用）

| 模式 | 采样什么 | 能看到 | 看不到 |
|---|---|---|---|
| **CPU** | 只在 CPU 上执行的样本 | 计算热点：算法、序列化、正则、JSON | **等锁、等 IO（它们不在 CPU 上）** |
| **wall（墙钟）** | 所有时间样本（含阻塞） | 卡在等什么：等锁、等 DB、等网络 | 无（全都要看） |
| **alloc** | 对象分配点 | 哪个代码分配最多内存（即使被 GC 了也记） | 无 |

**CPU 模式的盲区是它最大的坑**：它只采"正在 CPU 上跑"的样本。如果你的接口慢是因为在等数据库连接、等锁、等下游 HTTP，那段时间线程不在 CPU 上，CPU 火焰图里**根本看不到**——你会看到一张几乎全平的图，误以为"CPU 没问题，代码没热点"，然后茫然。

> 【思考】接口慢但 CPU 不高，火焰图用 CPU 模式会看到什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：几乎全平——所有样本都散落在"等 IO / 等锁"的薄框里，看不出任何热点。这时候你必须换 `wall` 模式，才能看到卡在"等数据库连接 / 等锁"的那段调用链。**

**为什么会这样？** CPU 模式的采样逻辑是"线程此刻正在执行指令吗？在执行就记一笔"。等数据库返回时，线程阻塞在内核的网络读（`socketRead0`）上，它不在 CPU 上跑，所以采样器在这一刻**什么也采不到**。结果是：火焰图顶部的业务方法框都很"薄"（只在真正处理数据的那几毫秒被采到），而真正吞噬时间的"等待"完全隐形。

**这恰恰是线上"慢"问题最常见的认知错误**：看到 CPU 不高，就以为不是代码问题，去查网络、查数据库。其实可能就是一段代码在**串行地等锁**或**同步调了慢下游**，而 CPU 火焰图把这件事藏起来了。

**正确做法——换 wall 模式：**

```bash
./async-profiler/profiler.sh -e wall -d 30 -f wall.html <pid>
# wall 模式按"墙钟时间"采样，无论线程在不在 CPU 上
# 这时你会看到顶部的框变宽，且框的调用链指向
# com.example.OrderService.query -> jdbc -> socketRead0（等 DB）
# 或 com.example.LockService -> ReentrantLock.lock（等锁）
```

**更深一层**：CPU 模式和 wall 模式的差异，本质是在回答两个不同的问题——**"我的 CPU 时间花在哪"（优化计算效率）vs "我的响应时间花在哪"（优化延迟）**。绝大多数"接口慢"是延迟问题（等东西），不是计算问题。所以排查"慢"的第一反应应该是 wall，排查"CPU 100%"才用 cpu。这个顺序搞反，你会浪费一下午。

**Go 对照**：Go 的 `pprof` 同样有这三种——

```bash
go tool pprof -http=:8080 cpu.prof    # 等价 CPU 模式
go tool pprof -http=:8080 trace.prof  # 等价 wall 模式（采集 goroutine 阻塞）
go tool pprof -http=:8080 mem.prof    # 等价 alloc 模式
```

Go 的 `runtime/pprof` 还能采样 goroutine 栈，直接看到几千个 goroutine 卡在同一个 `<-ch` 上（第 13.3 讲过的 goroutine 泄漏）。两者哲学一致，只是 Go 把 profiler 做进了标准库，开箱即用；Java 要额外装 async-profiler。

</details>

---

## 13.5 JMH：科学地做微基准测试（不要被自己骗了）

你写了一段代码，想"量一下它快不快"。直觉做法是 `System.currentTimeMillis()` 包一下，跑一万次取平均。这是新手最常踩的坑——**你量出来的根本不是那段代码的性能**。

### 为什么 System.currentTimeMillis 直接测是骗自己

```java
// 错误：这样测出来的数字没有任何意义
long start = System.currentTimeMillis();
for (int i = 0; i < 10000; i++) {
    int r = a + b;          // 想测加法
}
long cost = System.currentTimeMillis() - start;
```

至少有五个坑把它废掉：

1. **死代码消除**：`a + b` 的结果没人用，JIT 会直接把整个循环优化掉，你测的是"空转"。
2. **JIT 预热**：前几千次是解释执行，慢；后面才编译成本地代码。你没区分，平均值是混的。
3. **GC 干扰**：测量期间 GC 跑了一次，时间算进去了。
4. **CPU 频率变化**：现代 CPU 会降频/升频，墙上时钟不准。
5. **循环本身的开销**混进了被测代码。

### JMH 的基本结构

```java
import org.openjdk.jmh.annotations.*;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.AverageTime)
@OutputTimeUnit(TimeUnit.NANOSECONDS)
@State(Scope.Thread)              // 每个线程一份状态，避免共享干扰
public class AddBenchmark {
    private int a = 1, b = 2;

    @Setup(Level.Iteration)       // 每次测量迭代前准备
    public void setup() { a = 1; b = 2; }

    @Benchmark
    public int add(Blackhole bh) {
        int r = a + b;
        return r;                  // 这里故意返回，但更好的做法是下面
    }

    // 正确的写法：用 Blackhole 消费掉结果，防止死代码消除
    @Benchmark
    public void addBlackhole(Blackhole bh) {
        bh.consume(a + b);
    }

    public static void main(String[] args) throws Exception {
        org.openjdk.jmh.runner.options.Options opt =
            new org.openjdk.jmh.runner.options.OptionsBuilder()
                .include(AddBenchmark.class.getSimpleName())
                .forks(1)
                .build();
        new org.openjdk.jmh.runner.Runner(opt).run();
    }
}
```

### JMH 帮你处理的那些坑（知其所以然）

| 坑 | JMH 怎么解决 | 对应注解 |
|---|---|---|
| **死代码消除** | 返回值必须 `Blackhole.consume` 掉，JIT 不敢删"被消费"的计算 | `Blackhole` |
| **预热不足** | 先跑几轮让 JIT 编译好再测量 | `@Warmup` |
| **单次噪声** | 多次测量取统计值 | `@Measurement` |
| **相互污染** | 每个基准在独立 JVM 里跑，避免上一个的 GC/编译状态影响下一个 | `@Fork` |
| **伪共享** | `@State(Scope.Thread)` 隔离 + `@Contended` 避免多个变量挤在同一个缓存行打架 | `@Contended` |

**伪共享**这点值得停一下：两个线程各写一个 `long`，如果这俩 `long` 落在同一个 CPU 缓存行（64 字节）里，一个核写会让另一个核的缓存行失效，俩核互相 invalidate，性能暴跌。JMH 的 `@Contended` 会在字段前后塞 padding 把它独占一行——这跟第 04 章讲的 `LongAdder` 的 `Cell@Contended` 是同一招。

> 【思考】为什么测 `a + b` 的性能，JMH 测出来可能比真实代码慢 10 倍？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为真实代码里 `a + b` 会被内联进调用方、和周围代码一起被 JIT 优化（循环展开、SIMD、公共子表达式消除），而 JMH 把它隔离成一个独立方法，失去了上下文优化。所以微基准测的是"这个操作被孤立时的固有成本"，往往比它在真实调用现场更慢。反过来，某些情况下微基准也可能更快（被测代码太简单，JIT 优化得比真实场景激进）。**

**核心认知：微基准测的是"固有成本"，不是"真实性能"。** 真实代码里，`a + b` 大概率长这样：

```java
// 真实场景：a+b 只是循环里的一步，JIT 看到整个循环
long sum = 0;
for (Order o : orders) {
    sum += o.getAmount();     // a+b 被内联、循环展开、向量化
}
```

JIT 在编译这个循环时，会把 `getAmount()` 内联进来、`sum +=` 展开成几次一组、甚至用 SIMD 指令一次处理多个元素。而 JMH 把 `a + b` 单独拎成一个 `@Benchmark` 方法，**JIT 看不到它的上下文，只能老老实实做一次独立加法**——没有内联、没有展开、没有向量化。于是你测出的"加法成本"比真实环境高了一个数量级。

**这引出微基准 vs 宏基准的分工：**

- **微基准（JMH）**：回答"这个操作的固有成本是多少""两个实现哪个理论上更优"。适合对比算法、对比数据结构、验证某个优化是否生效。**结论不能直接外推到真实性能。**
- **宏基准（压测）**：用 wrk / k6 / Gatling 打真实接口，或者用 APM 看生产火焰图。回答"这个服务在真实负载下 P99 多少"。这才是你接手那个订单服务该用的。

**更深一层**：微基准最大的危险不是"不准"，是"它给你的数字看起来很精确，于是你误以为它能代表真实"。一个经典的翻车：有人用 JMH 证明"用 `StringBuilder` 比字符串拼接快 5 倍"，于是在一个一天只调用三次的配置加载函数里也换成了 `StringBuilder`——收益忽略不计，代码反而难读。**微基准的结论只在"这个操作会被高频执行"时才有工程意义。**

**Go 对照（这是你应该熟悉的）：**

```go
// Go 内置 benchmark，语言级支持，不需要额外框架
func BenchmarkAdd(b *testing.B) {
    a, c := 1, 2
    b.ReportAllocs()              // 看分配次数，对应 JMH 的 alloc 模式
    for i := 0; i < b.N; i++ {
        _ = a + c                  // Go 的 testing 也会做死代码消除防护
    }
}
// 运行：go test -bench=. -benchmem
```

Go 的 `testing.B` 同样是"预热（自动跑够次数）+ 测量 + 报告分配"，哲学跟 JMH 一致。差别是 Go 把它做进了标准库，零依赖；JVM 因为历史原因，JMH 是个独立项目（而且因为 JIT 太复杂，JMH 比 `testing.B` 要重得多——它要考虑分叉 JVM、黑盒消费、编译层级等）。但**两者要防的坑一模一样**：死代码消除、预热、GC 干扰。你从 Go 转过来，这套思维直接迁移。

</details>

---

## 13.6 性能工程方法论：一套可复用的推理框架

到这你应该看出来了：这一章真正的产出不是"记住 ZGC 比 G1 好"，而是一套**观察 → 假设 → 验证**的推理框架。不要抄调优模板——网上的"银弹参数"在你这个业务上多半是毒药。

### 四步框架

1. **先量化**。吞吐、P99、GC 停顿、CPU、内存——全变成数字。没有数字的调优是巫术，是"我觉得应该调一下"。
2. **找瓶颈类型**。是 CPU bound（算不过来）、IO bound（等下游）、内存 bound（GC 压力大 / 泄漏）、锁竞争（线程互相等），还是 GC bound（停顿长）？
3. **针对性的工具**。CPU 高 → 火焰图（cpu 模式）；GC 停顿 → GC 日志；内存涨 → heap dump + MAT；锁 → jstack 找 `locked` / Arthas `thread -b`；延迟（慢但 CPU 不高）→ 火焰图（wall 模式）/ JFR。
4. **改一个变量，再量化，对比**。一次只动一个参数，否则你不知道是哪个改动起了作用。

**这套框架跟你写 Go 时排查性能问题的思路完全同构**：Go 里也是"先 `pprof` 量化 CPU/内存/goroutine → 看火焰图定位热点 → 改一处 → 再压测对比"。区别只在工具名字和旋钮数量，推理逻辑一模一样。所以这一章你真正要带走的不是某个参数，而是"**让数字说话、一次只变一个量**"这个纪律——它在任何语言都成立。

### Heap 大小怎么给（实用经验，不是公式）

- **`-Xms == -Xmx`**：避免运行时扩容导致停顿；容器环境能防止被 OOMKilled（JVM 一开始就按上限申请，cgroup 看得见）。
- **一般给到"老年代常驻数据量的 3~4 倍"**：留足 Young GC 的空间，让短命对象在新生代就死掉，少晋升。
- **容器里注意 `-XX:+UseContainerSupport`**：JDK 8u191 之前 JVM 不读 cgroup 限制，会按宿主机内存（比如 64G）去设堆默认值，结果容器 limit 才 4G，直接被 K8s 杀掉。JDK 10+ 这个参数默认开启，但老 JDK 要显式加。配合 `-XX:MaxRAMPercentage=75.0` 让堆占容器限额的 75%。
- **32G 指针压缩陷阱**：第 04 章讲过，堆超过约 32GB 时压缩指针失效，对象平均变大 15%~20%。所以堆要么 <30G，要么一步跨到 48G+，**别在 32~40G 之间晃悠**。

> 【思考】GC 调优的"第一性原则"是什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：减少 STW 停顿的频率和时长。所有 GC 调优动作，最终都该落到这两个指标上。具体抓手有五条：① 让对象尽快死（缩短生命周期，减少晋升）② 选对 GC（低延迟用 ZGC/G1）③ 给够堆（减少 GC 频率）④ 避免大对象（直接进入老年代，打乱分代节奏）⑤ 避免 Finalize（延迟回收，拖慢 GC）。**

**展开说每条为什么有效：**

1. **让对象尽快死**。弱分代假说说 99% 对象短命。如果你能把对象生命周期压在"一次请求内"，它们死在 Eden，Young GC 一清就走，根本不进老年代。反之，如果你把对象塞进一个跨请求的 Map（模式一那种），它就晋级老年代，只能等 Full GC 才收——停顿就来了。
2. **选对 GC**。低延迟交易系统，G1 的 `MaxGCPauseMillis` 在大堆下会"为了达标而更频繁 GC"，反而吞吐掉；直接上 ZGC，停顿硬顶在 10ms 内。
3. **给够堆**。堆越大，同样分配速率下 GC 触发越稀。但别越过 32G 指针压缩线（见上）。
4. **避免大对象**。大数组/大字符串会直接进老年代（G1 里超过 Region 一半就算 humongous），绕过了新生代的"复制"保护，加剧老年代碎片化。
5. **避免 Finalize**。带 `finalize()` 的对象，GC 时不能直接回收，要先排队等 Finalizer 线程跑完，回收延迟一个数量级，还容易堆积。

**最关键的一条认知（写进肌肉记忆）：大多数服务用 G1 默认参数就够了。**

```java
// 一个"过度调优"的反面教材：抄了一堆网上参数，反而更糟
// -XX:MaxGCPauseMillis=50   // 设太激进 → G1 为了达标疯狂提前 GC → 吞吐暴跌
// -Xmn4g                    // 新生代硬设太大 → 老年代被挤小 → 晋升失败变多
// 真相：这套参数在别人的 8G 堆上测过，到你 32G 堆上可能全错
```

**更深一层**：GC 调优的第一性原理其实是"**先证明有问题，再动手**"。JVM 的 Ergonomics（自适应调优）已经很强，G1 默认就能自我平衡。**过度调优是反模式**——你动了一个参数，副作用可能在另一个指标上爆发，而你没监控那个指标。所以框架的最后一步"改一个变量、再量化、对比"不是废话，是防止你把生产环境当实验室的保险绳。只在 GC 日志确实显示长停顿、频繁 Full GC、泄漏时，才按这五条去推理着调。

**给老哥的 Go 类比，帮你建立直觉**：Go 这边你只需要一个 `GOGC`（默认 100，意思是"堆涨到上次 GC 后的 2 倍就触发下一次"）就能管住大部分场景，新版本还加了 `GOMEMLIMIT` 防 OOM。Java 这边把"什么时候 GC、回收多少、停顿多长"全部暴露成旋钮，代价是你要会调，收益是你能为特定场景精细优化。这套"默认旋钮少 vs 旋钮全开放"的差别，正是第 00 章卡点四说的——**不是 JVM 设计烂，是它要服务的场景跨度太大，只能把决定权交还给你**。你从 Go 转过来，最该改掉的习惯是"默认即对、懒得看"；在 JVM 上，读日志、量化、再动手，是基本功。

</details>

---

## 13.7 实战：两个完整的性能问题案例

光讲方法不够，看两个完整闭环。每个都是"现象 → 取证 → 推理 → 修复 → 量化验证"。

### 案例一：GC 停顿导致偶发超时

**现象**：订单服务每天凌晨 2 点（跑批量对账任务）P99 从 50ms 飙到 2s，持续十几秒后恢复。其他时间正常。前任参数：`-XX:+UseConcMarkSweepGC -Xmx2g`。

**取证**：拉 GC 日志，定位到 2 点的时间段：

```
[7200.5s] GC(1234) Pause Full GC (Allocation Failure) 1900M->1850M 18.2s
```

注意 `Pause Full GC` + 18.2 秒 + 回收前后几乎没差（1900M→1850M）。这正是第 13.1 讲的 CMS 死穴——并发模式失败退化成 Serial Old。

**推理**：CMS 并发回收赶不上对账任务的分配速率，老年代碎片积累到一定程度，触发 Serial Old 全堆整理。18 秒 STW 期间所有请求卡住，P99 被顶上去。堆只有 2G 也加剧了碎片问题。

**修复**：

```bash
# 升级到 G1（JDK 9+ 默认，但若还跑老 JDK 显式指定）
-XX:+UseG1GC
-Xms4g -Xmx4g                 # 堆翻倍，给新生代更多空间，减少晋升
-XX:MaxGCPauseMillis=200      # 合理的停顿目标，不激进
```

**量化验证**：上线后同时间段拉 GC 日志，再也没有 `Pause Full GC`，只有 `Pause Young` 平均 5ms；P99 曲线在 2 点不再有尖峰，稳定 50ms 附近。

### 案例二：内存泄漏导致每天重启

**现象**：服务每隔一天左右就因为 OOM 重启，运维设了定时重启当止血。老年代监控显示"锯齿只上不下"。

**取证**：

```bash
jmap -histo:live <pid> | head -20
# 15:      482311      15433792  com.example.order.Order
# HashMap$Node 也异常多
```

`Order` 进前 20，且在堆积。MAT 的 Dominator Tree 指向一个 `OrderCache.INSTANCE`（static 字段），Path to GC Roots 显示 `static Map` 持有几十万个 `Order`。

**推理**：第 04 章讲的经典模式一——static Map 当缓存，只 put 不清理。对账任务每天往里塞订单，从不淘汰，老年代被慢慢填满。

**修复**：换成有容量上限和过期策略的 Caffeine 缓存，而不是裸 `HashMap`：

```java
// 错误：无界 static HashMap
private static final Map<String, Order> CACHE = new HashMap<>();

// 正确：有容量上限 + 写入后过期
private static final Cache<String, Order> CACHE = Caffeine.newBuilder()
    .maximumSize(10_000)                 // 硬上限，超出按 LRU 淘汰
    .expireAfterWrite(1, TimeUnit.HOURS) // 1 小时过期
    .build();
```

**量化验证**：`jstat -gcutil` 看 O 列，Full GC 后稳定回落到基线（比如 40%），不再单调上升；服务连续运行两周无重启。

**两个案例的共同教训**：都是"先量化（GC 日志 / jstat）→ 定位瓶颈类型（GC bound / 内存 bound）→ 针对性工具（GC 日志 / MAT）→ 改一个变量再量化"。这套框架不依赖任何"调优模板"。

---

## 13.8 本章核心结论

1. **GC 调优的前提是建立坐标系**：分代假说（弱/强分代）是堆布局的根，Serial/Parallel/CMS/G1/ZGC/Shenandoah 都是在这个骨架上做变体。
2. **G1 因"分区 + 增量整理 + 可预测停顿"成为默认；CMS 因"碎片 + 并发失败退化成 Serial Old"被淘汰。**
3. **ZGC 靠着色指针 + 读屏障，把"移动对象"变成并发操作，停顿与堆大小无关，稳定 <10ms**——这是 JVM 在"大堆低延迟"场景的强项。
4. **GC 日志四个核心指标：吞吐、停顿时长、频率、晋升/并发失败。** Full GC 长停顿比 Young GC 频繁更该担心。
5. **Java 内存泄漏 = "该释放的对象被长生命周期强引用链牵着"**，头号嫌疑是 static 集合和没 remove 的 ThreadLocal。
6. **火焰图：横向是采样占比，纵向是调用栈；找"又宽又平"的框。CPU 模式看不到等待，慢问题先用 wall 模式。**
7. **JMH 防的是死代码消除/预热/GC 干扰/伪共享；微基准只量固有成本，真实性能要靠压测和 APM。**
8. **GC 调优第一性原则：减少 STW 的频率和时长。大多数服务 G1 默认就够，过度调优是反模式。**

---

## 13.9 深度思考题

### 题 1：一个 8GB 堆、低延迟要求的交易系统，你会选哪个 GC？为什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：优先 ZGC（或 Shenandoah）。** 8GB 堆 + 低延迟（交易系统通常要求 P99 < 10ms 甚至更低）正好是 ZGC 的主场——它保证停顿 <10ms 且与堆大小无关。G1 的 `MaxGCPauseMillis=10` 在大堆、高分配速率下**未必稳**，因为 G1 仍有"混合 GC"要扫描部分老年代 Region，极端情况会突破目标；而 ZGC 的停顿不随堆增长，是硬上限。

**为什么不无脑选 ZGC？** 两点权衡：① ZGC 的并发回收会让业务线程分担一点工作，吞吐比 G1 略低几个点（交易系统通常吞吐不是瓶颈，延迟才是）；② JDK 版本要求高（ZGC 生产就绪在 JDK 15，推荐 JDK 17+）。如果你还在 JDK 8 老环境，那只能用 G1 + 保守的 `MaxGCPauseMillis`，并接受偶尔超标的停顿。

**更深一层**：这道题考的是"场景匹配"而非"技术崇拜"。低延迟 + 中堆 → ZGC；高吞吐 + 大堆 + 不计停顿 → Parallel；均衡默认 → G1。**选 GC 的本质是选"你愿意牺牲什么"**：ZGC 牺牲一点吞吐换停顿确定性，Parallel 牺牲停顿换吞吐。没有最好的 GC，只有最匹配你业务 SLO 的 GC。

</details>

### 题 2：你的服务在容器里被 OOMKilled（K8s 重启），但 JVM 堆才用了 1G / 限定 4G。为什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 `-Xmx` 只管堆，而 JVM 进程总内存 = 堆 + 元空间 + 线程栈 + 直接内存 + CodeCache + GC 结构 + JVM 自身。堆 1G，但 400 个线程栈就 400MB，Netty 直接内存可能 512MB，元空间+CCS 200MB+，GC 结构几百 MB——加起来轻松超 4G，被 cgroup 杀掉。**

**更隐蔽的版本**：如果你跑的是**老 JDK（8u191 之前）**，JVM 根本不读 cgroup 限制，会按宿主机内存（比如 64G）去算堆默认值，堆可能默默涨到十几 G，远超容器 4G limit，直接 OOMKilled。这是第 04 章 04.5 详细算过的一笔账。

**修复方向（呼应第 04 章的"32G 陷阱"思维）：**

```bash
-XX:+UseContainerSupport          # JDK 10+ 默认开，老 JDK 必须显式加
-XX:MaxRAMPercentage=75.0         # 堆占容器限额 75%，别写死 -Xmx
-XX:MaxDirectMemorySize=512m      # 直接内存一定要显式限，别让它跟着 -Xmx 走
-XX:MaxMetaspaceSize=512m         # 元空间一定要限，否则吃光物理内存
# 容器 limit 至少要是 -Xmx 的 1.5 倍，留足非堆余量
```

**更深一层**：这是"JVM 参数多不是设计烂"（第 00 章卡点四）的另一个佐证。容器时代 JVM 必须"知道自己被关在多大笼子里"，而这件事在不同 JDK 版本、不同容器运行时的行为都不一样。排查 OOMKilled 的第一动作不是看堆，是用 `jcmd <pid> VM.native_memory summary`（NMT）把真实 RSS 拆开——你会看到堆可能只占三分之一，剩下全是"看不见的非堆"。

</details>

### 题 3：为什么 JMH 测出来 HashMap.get 比真实代码快那么多？

<details>
<summary><b>参考答案</b></summary>

**直接答案：跟 13.5 那个 `a+b` 的思考同源——微基准把操作孤立，失去了真实调用上下文的优化；但 HashMap.get 还有另一层：JMH 基准里 Map 通常刚构建、缓存命中率理想、没有真实业务的复杂 key 分布和哈希碰撞，于是测出来偏快。反过来，如果真实代码里 key 分布极差导致哈希碰撞，真实性能会比 JMH 测的慢得多。**

**关键认知：微基准的两个方向偏差都要警惕。**

1. **偏快（上下文优化丢失的反面）**：JMH 里你构造一个"完美热身过"的 HashMap，JDK 8 的树化（链表转红黑树）、缓存预取都处在最佳状态；真实代码里 Map 可能边写边读、大小浮动、触发扩容，性能不同。
2. **偏慢（如 13.5 所述）**：被孤立的方法失去内联和向量化。

**更深一层**：这道题真正想提醒的是——**微基准适合"比较两个实现的相对优劣"，不适合"估绝对值"**。想知道 HashMap.get 在你的真实流量下到底多快，正确做法是用真实数据跑压测（`wrk`/`k6`），或者用 JFR/async-profiler 的 alloc + cpu 模式看它在生产火焰图里的真实占比。JMH 告诉你"A 比 B 快 20%"，压测告诉你"A 在你的系统里占 5% 的 CPU、值不值得优化"。两者缺一不可。

</details>

### 题 4：对比 Go 和 Java 的 GC 哲学，各自最适合什么场景？

<details>
<summary><b>参考答案</b></summary>

**直接答案：Go 的 GC 为"短生命周期、中小堆、云原生微服务"优化——STW <1ms，但大堆下吞吐不如分代 GC；JVM 的分代 GC（尤其 G1/ZGC）在"大堆、低延迟、长生命周期服务"场景更强。这是两种 runtime 目标场景的差异，不是优劣。**

**Go GC 的设计取舍：**

- 不分代（所有对象一视同仁）、不移动（定点回收，靠 mcache 局部性）、三色标记 + 混合写屏障。
- 目标：**极短且可预测的停顿**，代价是吞吐略低、内存碎片靠 mcache 缓解但不如整理型 GC。
- 最适：API 网关、微服务、CLI——堆通常几百 MB 到几 GB，延迟敏感但对象生命周期短。

**JVM GC 的设计取舍：**

- 分代（新生代复制 + 老年代整理）、移动对象（G1/ZGC 都搬）、多种算法可选。
- 目标：**在"吞吐、停顿、堆大小"三角里按场景选平衡点**。ZGC 把停顿压到与堆无关，Parallel 把吞吐拉满。
- 最适：交易系统、大数据节点、长生命周期的大内存服务——堆几十到几百 GB，还要低延迟。

**更深一层**：这个差异可以一路推回到第 00 章卡点四——**Go 的 runtime 敢给"够好"的默认并关上调参大门，因为它服务的是聚焦的场景；JVM 给你几百个旋钮，因为它要服务从 256MB 安卓 app 到 几百GB 计算节点的全部跨度。** 你作为 Go 程序员学 Java，最大的认知转变是：在 JVM 上"选对 GC + 给够堆 + 读懂日志"本身就是一项能力，而 Go 里这件事 runtime 替你做了。两种哲学没有高下，只有"你的业务落在哪个战场"。

</details>

### 题 5（开放题，无标准答案）：如果让你给新项目定一套 JVM 参数基线，你会怎么定？

> 不急着看下面，先自己列一份。考虑：GC 选哪个、堆怎么给、容器环境要不要特殊处理、出事了能不能留现场、日志开不开。
>
> 一个可参考的基线（JDK 17+，容器部署，常规服务端）：
>
> ```bash
> -XX:+UseG1GC                      # 默认也行，显式写出更清晰
> -Xms4g -Xmx4g                     # 堆初始=最大，避免运行时扩容停顿；按老年代常驻量 3~4 倍给
> -XX:MaxGCPauseMillis=200          # 合理目标，不激进
> -XX:+UseContainerSupport          # 容器里读 cgroup 限制（JDK 10+ 默认开，写出来当保险）
> -XX:MaxRAMPercentage=75.0         # 堆占容器限额 75%
> -XX:MaxDirectMemorySize=512m      # 直接内存显式限
> -XX:MaxMetaspaceSize=512m         # 元空间显式限
> -Xlog:gc*:file=/data/gc.log:time,uptime,level:filecount=5,filesize=100M  # GC 日志，排障第一现场
> -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump/  # OOM 自动留现场
> -XX:+ExitOnOutOfMemoryError       # OOM 后主动退出，让容器重启并留 dump，别等 K8s 强杀
> -XX:NativeMemoryTracking=summary  # 排查期开，量化非堆内存（注意约 5% 开销）
> ```
>
> **核心原则一句话：默认够用，按需调。先让 G1 默认参数跑起来、把日志和 OOM dump 打开留好现场，等 GC 日志真的显示长停顿或频繁 Full GC 时，再按 13.6 的第一性原则去推理着调——而不是一上来就抄一堆"优化参数"。** 你接手那个凌晨 2 点 P99 飙升的服务，前任留下的恰恰是没有基线、盲配了 CMS 的反面教材。

---

## 下一章预告

这一章你拿到了"看到 GC 日志能推理"的能力：知道该选哪个 GC、能从日志读出停顿从哪来、能用火焰图定位热点、能用 JMH 科学地量微基准、有一套"量化 → 假设 → 验证"的方法论。

但 GC 和内存只是 JVM 这一层的性能问题。真正决定你写 Java 顺不顺手的，是**框架层**——你第 00 章卡点五提到的那个问题："`UserController` 是谁 new 的？`userService` 是哪个对象赋的值？"

第 14 章《Spring 核心：IoC/DI/AOP》，我们进到 Spring 的世界。你会搞懂 IoC 容器本质上就是"一个 `Map<String, Object>` 加一套基于注解的填充规则"；会明白 `@Autowired` 是怎么把依赖塞进来的、`@Transactional` 为什么在同一个类内部调用会失效、`@Transactional`/`@Cacheable` 这种"魔法"背后是动态代理在作祟。这章是第四部分生态框架的入口，也是你从"能跑 Java"到"懂 Java 生态"的分水岭。
