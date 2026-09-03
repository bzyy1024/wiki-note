# 第 08 章（节选）　JVM现场诊断与工具箱

> 本篇来自《Go 程序员的 Java 修炼之路》第 08 章「第 08 章　排错方法论：从异常栈到根因（一套能复用的 SOP）」。
> 返回：[第 08 章索引](./README.md)

## 08.4 JVM 现场诊断三板斧

第 04 章讲过 `jstack`/`jstat`/`jmap` 的输出怎么读。这一节不重复那些 —— 这一节讲**怎么把它们组合起来做推理**。

核心思想一句话：**单个工具给的是"症状"，多个工具交叉验证才能给出"诊断"。**

### 场景一：服务无响应

**第一动作永远是三连 jstack。** 理由第 04 章讲过（Java 的 jstack 不像 Go 的 `SIGQUIT` 那样告诉你"等了多久"），这里只强调操作纪律：

```bash
jstack 12345 > /tmp/s1.txt; sleep 5; jstack 12345 > /tmp/s2.txt; sleep 5; jstack 12345 > /tmp/s3.txt
# 看三次采样里，哪些线程的栈顶始终停在同一行
for f in s1 s2 s3; do echo "== $f"; grep -A 2 '"http-nio' /tmp/$f.txt | grep "at com\." | sort | uniq -c | sort -rn | head -5; done
```

**推理逻辑**：三次都停在同一行 → 这个等待持续了 10 秒以上 → 异常（正常业务不会在某一行停 10 秒）。三次停在不同地方 → 线程在正常工作 → 问题不在这里。

**第二动作：按状态统计。**

```bash
grep "java.lang.Thread.State" /tmp/s1.txt | sort | uniq -c
```

四种结果的解读：

| 统计结果 | 含义 | 下一步 |
|---|---|---|
| 大量 `BLOCKED` | 锁竞争（synchronized） | 找 `locked <0x...>` 反查持有者 |
| 大量 `WAITING (parking)` | 线程池在等任务（**可能正常**） | 结合 CPU 判断：CPU 低 + 无响应 = 上游没请求 or 死锁 |
| 大量 `TIMED_WAITING` | 在等超时（sleep/wait(timeout)/parkNanos） | 看等的是什么，超时时间合不合理 |
| 少量 `RUNNABLE` 但 CPU 很高 | 死循环 / 正则回溯 / 大对象序列化 | `top -Hp` 找具体线程 |

**第三动作：找锁的两端。** 这是 jstack 相对 Go 的一个真实优势 —— Go 的 `semacquire` 只告诉你"在等锁"，不告诉你"谁拿着锁"；Java 的 `locked <0x...>` 可以反查。

```bash
# 1. 找 BLOCKED 的线程在等哪把锁
grep -A 3 "BLOCKED" /tmp/s1.txt | grep "waiting to lock"
#  → - waiting to lock <0x00000000d7b3c210> (a com.example.InventoryService)

# 2. 反查谁持有这把锁
grep -B 15 "locked <0x00000000d7b3c210>" /tmp/s1.txt
```

**`jstack -l` 能看 ReentrantLock**：`synchronized` 的锁信息不需要 `-l`，但 `ReentrantLock`/`ReentrantReadWriteLock` 这些基于 AQS 的锁，只有 `-l`（或 `jcmd <pid> Thread.print -l`）才会显示 `Locked ownable synchronizers`。**看到大量 `parking to wait for` 但找不到持有者时，记得加 `-l`。**

**死锁不用你自己找**：jstack 输出的末尾会直接打印

```
Found one Java-level deadlock:
=============================
"Thread-A":
  waiting to lock monitor 0x... (object 0x00000000d7b3c210, a com.example.A),
  which is held by "Thread-B"
"Thread-B":
  waiting to lock monitor 0x... (object 0x00000000d7b3c310, a com.example.B),
  which is held by "Thread-A"
```

**但要注意**：jstack 的死锁检测**只覆盖 `synchronized` 和 AQS 的 `ownable synchronizers`**。如果你的死锁发生在**数据库行锁**、**分布式锁**、或者**自定义 Condition** 上，jstack 检测不到 —— 那属于 08.7 案例一的范畴。

### 场景二：服务很慢但没报错

这是最难的一类，因为"慢"没有异常栈。核心技巧是**把 OS 线程和 Java 线程对应起来**。

**完整换算步骤（Linux）：**

```bash
# 步骤 1：找出进程内 CPU 最高的线程（注意 -H 参数：显示线程而非进程）
top -Hp 12345
#   PID   USER  %CPU  COMMAND
#   4676  app   98.3  java          ← 记住 4676，这是十进制的 OS 线程 ID

# 步骤 2：十进制转十六进制（jstack 里的 nid 是十六进制）
printf "%x\n" 4676
#   1234

# 步骤 3：在 jstack 输出里搜这个 nid
jstack 12345 | grep -A 30 "nid=0x1234"
```

**为什么必须换算？** 因为 `top -H` 显示的是**操作系统**的线程 ID（十进制），而 jstack 的 `nid` 是**同一个 OS 线程 ID 的十六进制表示**。这两个是同一个数。而 jstack 里的 `tid` 是**JVM 内部线程对象的内存地址**，跟 OS 线程毫无关系 —— **别拿 `tid` 去搜，那是新手最常犯的错。**

**拿到栈之后怎么推理：**

| 栈顶是什么 | 结论 | 下一步 |
|---|---|---|
| `GC task thread` / `VM Thread` | GC 线程在烧 CPU | `jstat -gcutil` 看 GC 频率 |
| `socketRead0(Native Method)` | **卡在等下游返回**，但 jstack 显示 RUNNABLE（误导） | 用 `top -Hp` 交叉验证：CPU 低 = 在等 IO |
| `java.util.regex.Pattern` | **正则回溯**（ catastrophic backtracking） | 检查正则是否有嵌套量词 `(a+)+` |
| `ObjectMapper.writeValueAsString` | 大对象 JSON 序列化 | 看序列化了多大的对象 |
| `HashMap.resize` / `putVal` | 大 Map 扩容 / 哈希碰撞攻击 | 看 Map 多大，key 是否可预测 |
| 你自己的业务方法 | 真在计算 | 用 Arthas `trace` 看内部耗时分布 |
| `C2 CompilerThread` | JIT 在编译（**正常，别慌**） | 预热期常见，持续不退要查 CodeCache |

**一个重要的交叉验证**：`RUNNABLE` **不等于在跑**。JVM 不知道线程阻塞在 OS 层的网络 IO 上，会把它标成 `RUNNABLE`。所以：

```
jstack 说是 RUNNABLE  +  top -Hp 显示 CPU 0%   =  卡在 IO（下游慢）
jstack 说是 RUNNABLE  +  top -Hp 显示 CPU 98%  =  真在计算（查算法）
```

**Go 程序员的直觉在这里会坑你**：Go 的 `goroutine [IO wait]` 直接告诉你状态，你不需要交叉验证。在 Java 里这个验证是必须的。

**如果 CPU 高的是 GC 线程：**

```bash
jstat -gcutil 12345 1000 10
# 看 FGC 列每秒涨多少次；GCT 除以运行时长 = GC 占比（健康线 < 1%，超过 10% 就是灾难）
```

### 场景三：内存持续增长

**推理链条是：先便宜后昂贵，先无创后有创。**

```bash
# 第一档（零成本，随时可用）：看老年代趋势
jstat -gcutil 12345 1000
#  关键：看 O 列。Full GC 后 O 不下降 = 泄漏；O 缓慢上升但 FGC 后能降回去 = 只是压力大
```

**判定泄漏的唯一标准**：**Full GC 之后老年代占用是否回落到基线。** 因为 Full GC 会回收所有不可达对象 —— 如果它回收完还是那么满，说明那些对象**全是可达的**，也就是有强引用链在持有它们。

```bash
# 第二档（轻量，但要谨慎）：看对象分布
jmap -histo 12345 | head -20
#  注意：不加 :live 就不会触发 Full GC，生产相对安全
```

`jmap -histo` 和 `jmap -histo:live` 的区别非常关键：

| 命令 | 是否触发 Full GC | STW | 生产安全性 |
|---|---|---|---|
| `jmap -histo <pid>` | 否 | 有短暂 STW（遍历堆） | **相对安全**，可谨慎使用 |
| `jmap -histo:live <pid>` | **是** | 长（取决于堆大小） | 谨慎，低峰期用 |
| `jmap -dump <pid>` | 否 | **很长**（写整个堆） | **危险**，必须摘流量 |
| `jmap -dump:live <pid>` | **是** | **最长** | **最危险** |

**怎么读 `-histo` 输出**（第 04 章讲过方括号描述符，这里只讲推理）：

```
 num     #instances         #bytes  class name
   1:       1204843       38554976  [C                          ← char[]，通常是 String 的内部数组
   2:       1203821       28891704  java.lang.String            ← 120 万个 String
   3:        402311       12873952  java.util.HashMap$Node      ← 40 万个 Map 节点
  15:         12000        1920000  com.example.order.OrderDTO  ← 你的业务对象进前 20 = 在堆积
```

**推理规则**：
- `char[]` 和 `String` 数量接近 → String 在堆积，去找谁在缓存字符串
- `HashMap$Node` 数量巨大 → 找那个 Map（**静态 Map 是头号嫌疑犯**）
- 你的业务类（`com.example.*`）进前 20 → **铁证**，就是它在泄漏
- 实例数巨大但字节数不大 → 小对象爆炸（GC 压力大但内存不多，通常不是 OOM 主因）

```bash
# 第三档（重武器，必须摘流量）：堆转储
jcmd 12345 GC.heap_dump -gz=1 /data/dump/heap.hprof
#  -gz=1 压缩（JDK 11+），8G 堆能压到 2~3G，省磁盘省传输时间
#  默认不带 -all → 只 dump 存活对象，但会先触发一次 Full GC
```

**MAT 里怎么读"谁在持有这个对象"**（这是 MAT 最有价值的用法，也是最难讲清的）：

1. **Histogram**：按类名看实例数和占用，找到可疑类
2. **Dominator Tree**：按"支配关系"排序。**Dominator 的含义是"如果我把这个对象回收掉，下面这些内存就都释放了"** —— 它直接回答"谁真正占着内存"，而不只是"谁大"
3. **Path to GC Roots**（对可疑对象右键，选 **exclude weak/soft references**）：**显示从 GC Root 到这个对象的完整引用链**。这一步是"定罪"—— 你会看到类似

```
com.example.OrderCache.INSTANCE (static field)      ← 静态字段！GC Root
  └→ java.util.HashMap
       └→ table[142] → HashMap$Node
            └→ value → com.example.OrderDTO
```

看到 `static field` 在链的最顶端，案子就破了 —— **静态集合是内存泄漏的头号嫌疑犯**，因为静态字段的生命周期跟 ClassLoader 一样长（基本等于进程生命周期）。

**为什么必须 exclude weak/soft references？** 因为 `WeakHashMap`、`ThreadLocalMap` 的 key 都是弱引用。不排除弱引用的话，你会看到一堆"通过弱引用可达"的路径，但那些**不构成泄漏**（GC 时会被清理）。只有**强引用链**才是真凶。

### 场景四：偶发问题

偶发问题的本质是：**你不知道它什么时候发生，所以你不知道该在什么时候采样。** 解法是**常开录制**。

**JFR（Java Flight Recorder）—— JVM 的黑匣子：**

```bash
# 启动时就开（推荐：常开，开销 < 1%）
java -XX:StartFlightRecording=disk=true,maxage=24h,maxsize=1g,filename=/data/rec.jfr \
     -XX:FlightRecorderOptions:stackdepth=128 \
     -jar order-service.jar

# 或者运行时动态开启（不用重启）
jcmd 12345 JFR.start name=rec duration=300s filename=/tmp/rec.jfr settings=profile
jcmd 12345 JFR.check          # 看录制状态
jcmd 12345 JFR.dump name=rec filename=/tmp/snapshot.jfr   # 中途抓一份
jcmd 12345 JFR.stop name=rec
```

**JFR 能记录什么**（这些是 jstack 给不了的）：

| 事件类型 | 内容 | 解决什么问题 |
|---|---|---|
| `Java Monitor Blocked` / `Java Monitor Wait` | 锁竞争的**等待时长**（含持锁线程的栈） | 偶发卡顿 |
| `Execution Sample` | 定期采样的方法栈 | CPU 热点 |
| `Allocation in new TLAB` / `Object Count` | 对象分配位置 | 内存分配热点 |
| `GC Pause` / `GC Phase` | 每次 GC 的**精确停顿时长** | P99 毛刺 |
| `Socket Read` / `File Read` | IO 耗时 | 外部依赖抖动 |
| `Java Error` / `Java Exception` | **所有抛出的异常（含被 catch 的）** | 静默失败 |

**倒数第二行是杀手锏**：JFR 能看到**被 catch 掉、没打到日志里的异常**。多少"莫名其妙"的问题，其实是一个被 `catch (Exception e) {}` 吞掉的异常在作祟 —— jstack 看不到，日志看不到，JFR 看得到。

**JMC（JDK Mission Control）** 是官方的 JFR 分析器（独立下载，不在 JDK 里），能自动给出"可疑问题"报告。

**async-profiler —— 火焰图：**

```bash
# 下载后直接 attach，不需要改启动参数，不需要重启
./profiler.sh -d 60 -e cpu 12345 -f /tmp/cpu.html      # CPU 火焰图，采 60 秒
./profiler.sh -d 60 -e alloc 12345 -f /tmp/alloc.html  # 内存分配火焰图
./profiler.sh -d 60 -e wall -t 12345 -f /tmp/wall.html # wall clock（含阻塞，看等待）
```

**三种模式怎么选**（这是 async-profiler 相对 JFR 更好用的地方）：

| 模式 | 采样对象 | 用途 |
|---|---|---|
| `-e cpu` | 只在 CPU 上执行的样本 | 找**计算**热点（算法、序列化、正则） |
| `-e alloc` | 对象分配点 | 找**内存分配**热点（GC 压力的来源） |
| `-e wall` | 墙钟时间（**包括在等待的**） | 找**延迟**热点（等锁、等 IO） |

**`-e wall` 是最被低估的**：CPU 火焰图看不出"线程在等什么"，而线上"慢"的问题 90% 是在等待。Arthas 的 `profiler` 命令内部就是 async-profiler。

### Go ↔ Java 诊断工具对照表

| 需求 | Go | Java | 差异点评 |
|---|---|---|---|
| 打所有栈 | `kill -QUIT <pid>` | `jstack` / `jcmd Thread.print` | **Go 输出带等待时长**，Java 要靠多次采样模拟 |
| CPU 火焰图 | `pprof -http` 内置 | async-profiler / JFR | Go 零成本（标准库自带），Java 要额外装 |
| 堆 profile | `pprof -heap` | `jmap -histo` / `-dump` + MAT | **Go 有精确分配点**；Java 的 MAT 有支配树和 GC Root 路径 |
| 锁竞争 | `pprof -mutex`（只能看等待时长，**拿不到持有者**） | jstack 的 `locked <0x...>` 可反查持有者 | **Java 赢**，这一条很实用 |
| 执行追踪 | `runtime/trace` | **JFR** | JFR 更强大（常开开销 < 1%，事件类型丰富） |
| 运行时插桩 | 无（要改代码重编译） | **Arthas**（`watch`/`trace`/`tt`） | **Java 生态的真正优势**，见 08.5 |
| 数据竞争检测 | `go test -race`（**生产可用**） | 无官方工具 | **Go 赢**，Java 只能靠 JFR + 代码审查 |
| 死锁检测 | 只在"所有 goroutine 都睡着"时报错退出 | jstack 自动打印死锁 | Java 赢 |

**这张表最该记住的一行是"运行时插桩"。** 这是 Java 生态对 Go 的一个**真实且难以复制的优势**，下一节展开。

---


## 08.8 排错工具箱清单

按场景分类的速查表。**"生产安全性"这一列是这张表的价值所在** —— 它告诉你每个动作的代价，让你能按"先便宜后昂贵"的顺序排优先级。

### 看进程

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `jps -l` | 列出 Java 进程 + 主类名 | 安全（只读） |
| `ps -ef \| grep java` | 找不到 jps 时用（容器里 `/tmp` 被清空的情况） | 安全 |
| `jcmd -l` | 等价于 `jps -l`，现代写法 | 安全 |
| `dmesg -T \| grep -i oom` | **查是否被 OOM killer 干掉**（进程消失时第一件事） | 安全 |
| `cat /proc/<pid>/status` | 看线程数、内存、fd 数量 | 安全 |

### 看线程

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `jstack <pid>` | 线程栈快照 | 安全（有极短 STW，安全点采样） |
| `jstack -l <pid>` | **额外显示 AQS 锁（ReentrantLock）持有者** | 安全 |
| `jcmd <pid> Thread.print -l` | 等价 `jstack -l` | 安全 |
| `top -Hp <pid>` | 进程内各线程的 CPU | 安全 |
| Arthas `thread -n 3` | CPU 最高的 3 个线程 | 安全 |
| Arthas `thread -b` | **找阻塞他人的线程**（仅支持 synchronized） | 安全 |
| Arthas `thread --state BLOCKED` | 所有阻塞线程 | 安全 |
| `kill -QUIT <pid>`（Go） | 打印 goroutine 栈到 stdout | 安全 |

### 看内存

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `jstat -gcutil <pid> 1000` | 堆各区使用率 + GC 次数/耗时 | **安全**（最常用，放心用） |
| `jmap -histo <pid>` | 对象分布，**不触发 Full GC** | 相对安全（短暂 STW） |
| `jmap -histo:live <pid>` | 只统计存活对象 | ⚠️ **触发 Full GC**，低峰期用 |
| `jcmd <pid> GC.heap_info` | 堆概览 | 安全，快 |
| `jcmd <pid> GC.heap_dump -gz=1 <file>` | 堆转储（默认只 dump 存活对象，**会 Full GC**） | 🔴 **危险**，必须摘流量 |
| `-XX:+HeapDumpOnOutOfMemoryError` | OOM 时自动 dump | 建议**常开** |
| `jcmd <pid> VM.native_memory summary` | NMT，查堆外内存去哪了 | 需要启动时开 `-XX:NativeMemoryTracking=summary`，有 5~10% 开销 |
| `jcmd <pid> VM.classloader_stats` | 类加载器统计（查元空间泄漏） | 安全 |
| Arthas `vmtool --action getInstances` | 拿某个类的实例，看里面装了啥 | 相对安全，比 dump 轻得多 |
| Arthas `memory` | JVM 内存分区概览 | 安全 |

### 看 GC

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `jstat -gcutil <pid> 1000` | 实时 GC 统计 | 安全 |
| `-Xlog:gc*:file=...`（JDK 9+） | GC 日志落盘 | 建议**常开**，开销极低 |
| `-Xloggc` + `-XX:+PrintGCDetails`（JDK 8） | 老版本 GC 日志 | 同上 |
| JFR 的 GC Pause 事件 | **精确的 GC 停顿时长**（含 STW 起止时刻） | 常开开销 < 1% |
| GCViewer / GCeasy | GC 日志分析（上传日志，出报告） | 离线分析 |
| Arthas `gc` | 显示最近 GC 次数和耗时 | 安全 |

### 看类（依赖冲突 / Jar Hell）

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `mvn dependency:tree -Dverbose` | 依赖树 + 冲突标记（编译期视角） | 本地 |
| Arthas `sc -d <类名>` | **★ 看类从哪个 jar 加载**（运行时视角，最准） | 安全 |
| Arthas `sm -d <类名> <方法>` | 看方法签名 | 安全 |
| Arthas `jad --source-only <类名>` | **★ 反编译，确认线上版本** | 安全（只读） |
| `jcmd <pid> VM.class_hierarchy` | 类继承关系 | 安全 |
| `-verbose:class` | 打印类加载过程 | ⚠️ 输出量巨大，**生产慎用** |

### 看方法执行（运行时插桩）

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| Arthas `watch` | 看入参/返回值/异常/耗时 | ⚠️ **有开销**，避免 `-x 4` 和高频方法 |
| Arthas `trace` | 方法内部调用链耗时 | ⚠️ 开销较大，加条件过滤 |
| Arthas `stack` | 调用路径（谁调了它） | ⚠️ 同 trace |
| Arthas `tt` | 记录历史调用 + 回放 | ⚠️ **持有对象引用，用完必须 `tt --delete-all`** |
| Arthas `monitor` | 统计调用次数/成功率/平均 RT | 开销小，可长时间挂 |
| Arthas `profiler` | 火焰图（async-profiler） | ⚠️ 采样期有开销，避开高峰 |
| async-profiler | 独立版火焰图 | ⚠️ 同上，但比 JFR 更易用 |

### 看网络 / 磁盘 IO

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `ss -antp \| grep <port>` | 连接状态统计（TIME_WAIT 多少？ESTABLISHED 多少？） | 安全 |
| `netstat -s` | 协议栈统计（重传、丢包） | 安全 |
| `tcpdump -i any -w /tmp/cap.pcap` | 抓包 | ⚠️ 有 CPU 和磁盘开销，限制时间和大小 |
| `iostat -x 1` | 磁盘 IO 使用率、await | 安全 |
| `iotop` | 哪个进程在读写磁盘 | 安全 |
| `lsof -p <pid> \| wc -l` | 进程打开的 fd 数量（对比 `ulimit -n`） | 安全 |
| `iftop` / `nethogs` | 实时流量 | 轻量开销 |

### 看 JVM 参数 / 运行时配置

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| `jcmd <pid> VM.flags` | **★ 实际生效的 JVM 参数**（含 JVM 自动设置的 Ergonomics 值） | 安全 |
| `jinfo -flags <pid>` | 同上，但**容器里容易失败** | 安全 |
| `jcmd <pid> VM.system_properties` | 系统属性（`-D` 参数） | 安全 |
| `jcmd <pid> VM.command_line` | 启动命令行 | 安全 |
| Arthas `jvm` / `jvm -X` | JVM 信息总览 / 只看参数 | 安全 |
| Arthas `sysprop` / `sysenv` | 系统属性 / 环境变量 | 安全 |
| Spring Actuator `/actuator/env` | Spring 的配置（含各配置源的优先级） | 注意**会暴露敏感信息**，生产要鉴权 |

### 看日志

| 工具 | 用途 | 生产安全性 |
|---|---|---|
| Arthas `logger --name ROOT --level debug` | **运行时动态改日志级别，不用重启** | 改完记得调回去 |
| Spring Actuator `/actuator/loggers` | 同上（HTTP 接口） | 需要鉴权 |
| `grep -c "ERROR" app.log` | 错误计数 | 安全 |
| `grep "traceId" app.log` | **按 traceId 捞一个请求的全部日志** | 安全（前提是你配了 MDC） |

---


