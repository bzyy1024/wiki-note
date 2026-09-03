# 第 02 章（节选）　Java8遗产与坑

> 本篇来自《Go 程序员的 Java 修炼之路》第 02 章「第 02 章　Java 17 新特性与 Java 8 差异（现代 Java 长什么样）」。
> 返回：[第 02 章索引](./README.md)

## 02.7 Java 8 的遗产与坑（国内项目重灾区）

你大概率会同时面对两种项目：新的用 Java 17/21，老的卡在 Java 8。这一节讲老项目里你会撞上的东西。

### `Date` / `Calendar` 的灾难

`java.util.Date` 的问题（每一条都是真实存在的）：

```java
Date d = new Date();
d.setTime(d.getTime() + 86400000);   // ❌ 可变！任何人都能改你传进去的 Date
d.getYear();        // 返回 2026 - 1900 = 126，不是 2026
d.getMonth();       // 0-11，一月是 0
d.getDay();         // 星期几（0=周日）
d.toString();       // "Wed Sep 02 19:56:43 CST 2026" —— 格式里混着时区缩写，不可解析
// Date 这个名字本身也是错的：它表示的是"一个时刻"（instant），不是"一个日期"
```

`Calendar` 稍微好一点，但：

```java
Calendar c = Calendar.getInstance();
c.set(2026, Calendar.SEPTEMBER, 2);   // 至少有了常量，但月份仍然 0-based
c.set(2026, 8, 2);                    // 8 = 九月！每个月都有人在这里写错
c.get(Calendar.MONTH);                // 还是 0-based
c.set(Calendar.HOUR, 3);              // HOUR 是 12 小时制！HOUR_OF_DAY 才是 24 小时制
// Calendar 也是可变的
```

**真实事故案例：静态共享 `SimpleDateFormat`**

> **现象**：某订单服务的订单创建时间，偶尔会出现"1970-01-01"、"2038-01-19"这些离谱的值，偶尔还会出现两条订单的创建时间完全相同（毫秒级相同）。每天大概几十单，占总量的 0.1%。客诉来了但复现不了。
>
> **代码**：
>
> ```java
> public class DateUtils {
>     // "为了性能，只创建一个实例" —— 前任的注释
>     private static final SimpleDateFormat SDF = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
>
>     public static String format(Date d) {
>         return SDF.format(d);
>     }
>     public static Date parse(String s) throws ParseException {
>         return SDF.parse(s);
>     }
> }
> ```
>
> **排查**：
> 1. 本地压测，`format` 并发调用，很快复现出"两个线程返回同一个字符串"和"解析出错误日期"
> 2. 看 `SimpleDateFormat` 的源码（或者说它的父类 `DateFormat`），发现关键字段：
>
> ```java
> public abstract class DateFormat extends Format {
>     protected Calendar calendar;      // ← 就是这个
>     protected NumberFormat numberFormat;
> }
> ```
>
> **根因**：`SimpleDateFormat.format()` 的实现是这样的（简化）：
>
> ```java
> public StringBuffer format(Date date, StringBuffer toAppendTo, FieldPosition pos) {
>     calendar.setTime(date);      // 第一步：把共享的 calendar 设成目标时间
>     // ... 第二步：从 calendar 里一个字段一个字段地读，拼字符串
> }
> ```
>
> **第一步和第二步之间不是原子的。** 线程 A 调 `calendar.setTime(t1)`，还没开始读；线程 B 调 `calendar.setTime(t2)` 覆盖掉；线程 A 继续读，读出来的是 `t2` 的字段 —— 甚至更糟，读到一半被 B 覆盖，拼出一个"年来自 A、月来自 B"的畸形时间。
>
> `parse()` 同理：`ParsePosition` 和 `calendar` 都是共享状态。
>
> **修复**（三选一）：
>
> ```java
> // 方案 1（推荐，Java 8+）：换成 DateTimeFormatter，它是不可变且线程安全的
> private static final DateTimeFormatter FMT =
>         DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
> String s = FMT.format(LocalDateTime.now());
>
> // 方案 2：ThreadLocal（老代码过渡用）
> private static final ThreadLocal<SimpleDateFormat> TL =
>         ThreadLocal.withInitial(() -> new SimpleDateFormat("yyyy-MM-dd HH:mm:ss"));
>
> // 方案 3：每次 new（最简单，性能通常也够 —— 除非你在超高频循环里）
> ```
>
> **教训**：**"为了性能共享一个对象"这个优化，在有可变状态的对象上是致命的。** 判断标准很简单：**这个类的 javadoc 里有没有"线程安全"这句话？** 没有就别共享。JDK 里绝大多数"格式化器"类（SimpleDateFormat、NumberFormat、DecimalFormat）都不是线程安全的。
>
> 顺带一句：Go 里 `time.Time` 是**不可变的值类型**，`time.Format()` 不修改任何共享状态，所以 Go 程序员写 Java 时对这类问题天然没有警觉 —— 这是你的 Go 经验会坑你的地方之一。

> 【思考】为什么 `SimpleDateFormat` 非线程安全？它内部持有什么状态？
>
> 更进一步的追问：**为什么 JDK 不把它改造成线程安全的？** 明明加个锁或者改成不可变就行了。

<details>
<summary><b>参考答案</b></summary>

**直接答案：它继承了 `DateFormat` 的一个 `protected Calendar calendar` 字段，并在 `format`/`parse` 过程中把它当作"临时工作区"反复修改。**

**第一层：具体状态是什么。**

看类继承结构：

```
Format
  └─ DateFormat
       ├─ protected Calendar calendar        ← 可变共享状态
       ├─ protected NumberFormat numberFormat ← 可变共享状态
       └─ ...
         └─ SimpleDateFormat
              └─ private transient char[] compiledPattern  （编译后的模式，构造后不变）
```

`SimpleDateFormat.format(Date)` 的实际流程（JDK 源码简化）：

```java
public StringBuffer format(Date date, StringBuffer toAppendTo, FieldPosition pos) {
    pos.beginIndex = pos.endIndex = 0;
    // 关键：把共享的 calendar 对象"指向"传入的日期
    calendar.setTime(date);

    boolean useDateFormatSymbols = useDateFormatSymbols();
    for (int i = 0; i < compiledPattern.length; ) {
        int tag = compiledPattern[i] >>> 8;
        int count = compiledPattern[i++] & 0xff;
        if (count == 255) { /* 处理字面量 */ continue; }

        switch (tag) {
        case TAG_QUOTE_ASCII_CHAR: ...
        case TAG_QUOTE_CHARS: ...
        default:
            // 关键：从刚才 setTime 的 calendar 里读字段
            subFormat(tag, count, ...);
            break;
        }
    }
    return toAppendTo;
}

private void subFormat(...) {
    int value;
    switch (patternCharIndex) {
    case PATTERN_ERA:  value = calendar.get(Calendar.ERA); break;
    case PATTERN_YEAR: value = calendar.get(Calendar.YEAR); break;
    case PATTERN_MONTH: value = calendar.get(Calendar.MONTH) + 1; break;
    // ... 每个字段都是一次 calendar.get()
    }
}
```

**关键点：`calendar.setTime(date)` 和后面几十次 `calendar.get(...)` 是一个"设置-读取"的多步序列，中间没有任何同步。** 两个线程交错执行，就会出现：

- 线程 A `setTime(t1)` → 线程 B `setTime(t2)` → 线程 A `get(YEAR)` → 得到 `t2` 的年份
- 或者更混乱：A 读了年、B 改了、A 再读月 → 得到一个"混合时间"
- `parse()` 里还有 `CalendarBuilder` 和 `ParsePosition`，同样是实例级状态

**为什么会出现 `1970-01-01`？** 因为 `Calendar` 对象在 `setTime` 之前字段是未初始化/上一次的值；如果另一个线程刚好调用了 `calendar.clear()`（parse 流程里会调），A 读到的就是 0 → epoch → 1970-01-01。

**第二层：为什么 JDK 不修？**

三个方案，逐个看为什么都不可行：

**方案 A：加 `synchronized`。**

```java
public synchronized StringBuffer format(Date date, ...) { ... }
```

问题：
1. **性能**：`SimpleDateFormat` 是出了名的慢（每次 format 要跑一遍模式解析 + Calendar 字段计算），再加锁，吞吐量只会更差
2. **治标不治本**：加在 `format` 上，那 `parse` 呢？两个方法访问同一个 `calendar`，得锁同一个对象 —— 可以做到（锁 `this`），但这样"为了线程安全引入的全局锁"会让所有日期格式化串行化
3. **语义破坏**：有人依赖 `DateFormat` 的 `calendar` 字段做定制（比如设置一个特殊的 `Calendar` 子类来处理佛历），加锁改变了这个扩展点的行为

**方案 B：改成不可变。**

做不到。`DateFormat` 的设计里，`calendar` 字段是 `protected` 的 —— 意味着**它是公开 API 的一部分**：

```java
public class MyFormat extends SimpleDateFormat {
    { calendar.setFirstDayOfWeek(Calendar.MONDAY); }   // 子类可以改
}
```

改成不可变就是破坏性变更，所有继承 `DateFormat` 的代码全炸。

**方案 C：废弃它，提供新的 API。**

**这才是 JDK 实际做的。** Java 8（2014）引入了 `java.time`（JSR-310），里面的 `DateTimeFormatter` 从设计上就是**不可变 + 线程安全**的：

```java
public final class DateTimeFormatter {
    // 所有字段都是 final，类也是 final
    private final DecimalStyle decimalStyle;
    private final ResolverStyle resolverStyle;
    private final Chronology chrono;
    private final ZoneId zone;
    // ...
}
```

而且 `java.time` 里所有核心类（`LocalDateTime`、`Instant`、`ZonedDateTime`、`Duration`）都是**不可变的值类型** —— 每个"修改"操作都返回一个新对象。

**注意：JDK 没有把 `SimpleDateFormat` 标记为 `@Deprecated`。** 为什么？因为标记了会有几十亿行代码冒出编译警告，而 `@Deprecated` 的语义是"这个类会被移除"，JDK 团队的判断是它在可预见的未来不会移除（兼容性承诺）。所以它处于一个尴尬状态：**不推荐使用，但不算废弃。**

**第三层：Go 里为什么没这个问题。**

```go
t := time.Now()
s := t.Format("2006-01-02 15:04:05")   // time.Time 是值类型，不可变
```

Go 的 `time.Time` 内部是：

```go
type Time struct {
    wall uint64
    ext  int64
    loc  *Location
}
```

`Format` 方法不修改 `t`（没有指针接收者），也不依赖任何包级可变状态 —— Go 的 `time` 包里没有"可变的全局格式化器"这种东西。

**根本差异：Go 从设计上就没有"格式化器对象"这个概念**，`Format` 是一个方法，布局是一个字符串参数。Java 把"格式化"建模成一个**有状态的对象**（`Format` 的子类体系），这是 1990 年代面向对象设计的典型产物。

**代码锚点 —— 自己复现这个 bug：**

```java
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.concurrent.*;

public class SdfBug {
    static final SimpleDateFormat SDF = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss");
    static final long BASE = 1700000000000L;   // 固定基准时间

    public static void main(String[] args) throws Exception {
        ExecutorService pool = Executors.newFixedThreadPool(10);
        CountDownLatch latch = new CountDownLatch(1000);
        ConcurrentSkipListSet<String> results = new ConcurrentSkipListSet<>();

        for (int i = 0; i < 1000; i++) {
            final long t = BASE + i * 1000L;
            pool.submit(() -> {
                try {
                    // 所有线程格式化"同一个"时间，理论上结果必须一致
                    results.add(SDF.format(new Date(t)));
                } catch (Exception e) {
                    results.add("EX:" + e);
                } finally { latch.countDown(); }
            });
        }
        latch.await();
        pool.shutdown();
        System.out.println("不同结果的数量: " + results.size());   // 应该 > 1，说明出错了
        results.stream().limit(5).forEach(System.out::println);
    }
}
```

跑到 `results.size() > 1`，你就亲眼看到了线程安全问题。

**更深一层 — 这个案例揭示的是"可变状态"和"共享"的组合毒性：**

单独看，`SimpleDateFormat` 可变不是问题（你 new 一个用完就扔），共享也不是问题（共享不可变对象没事）。**两个加一起才是毒药。**

这给你一条可复用的判据：**当你打算把一个对象做成 `static final`（全局共享）之前，先确认它不可变。** 这条判据在 Java 里适用面远超日期格式化 —— `ArrayList`、`HashMap`、`StringBuilder`、`ObjectMapper`（这个反而是线程安全的）、`Random`…… 见到 `static final` 就要问一句"它可变吗"。

**Go 程序员在这里的优势**：Go 里 `sync.Pool`、包级变量的共享很常见，但 Go 的标准库类型大多设计成"值语义或者显式指针"，加上数据竞争检测器（`-race`），这类问题暴露得更早。Java 没有 `-race`（JMM 的复杂性让静态/动态竞争检测都很难做），所以**只能靠你自己的判据**。
</details>

### `java.time`（JSR-310）：正确的时间 API

Java 8 引入，作者是 Stephen Colebourne（Joda-Time 的作者），基本是 Joda-Time 的官方版本。

| 类 | 表示什么 | 用它替代 |
|---|---|---|
| `Instant` | 时间线上的一个点（UTC，纳秒精度） | `Date` |
| `LocalDateTime` | 本地日期时间，**不含时区** | `Calendar` |
| `LocalDate` | 只有日期 | — |
| `LocalTime` | 只有时间 | — |
| `ZonedDateTime` | 带时区的日期时间 | `Calendar` + `TimeZone` |
| `Duration` | 时间段（秒/纳秒） | `long` 毫秒数 |
| `Period` | 日期段（年/月/日） | — |
| `DateTimeFormatter` | 格式化器，**不可变、线程安全** | `SimpleDateFormat` |

选型的判据（这一条很多人搞混）：

```java
Instant.now();          // 存数据库、跨系统传递、记录日志时间戳 → 用这个
LocalDateTime.now();    // 表示"墙上时间"（比如"每天早上 9 点"，不关心是哪个时区）→ 用这个
ZonedDateTime.now();    // 需要展示给特定时区的用户，或者做跨时区计算 → 用这个
```

**问题 8：** 用户下单时间是 `2026-09-02 20:00:00`，用 `LocalDateTime` 存对不对？

不对（大多数情况下）。因为"下单时间"是一个**时间线上的点**，它应该是 `Instant` 或者 `ZonedDateTime`。用 `LocalDateTime` 存储，你的服务部署到另一个时区的机房，或者数据库换了时区配置，所有历史时间的含义就变了。**判据：如果这个时间需要跟"另一个时刻"比较先后，或者需要被不同时区的人看到"同一个瞬间"，就用 `Instant`。**

常用操作：

```java
Instant now = Instant.now();
Instant later = now.plus(Duration.ofHours(2));

// Instant 没有"时区"概念，要格式化成人类可读的，必须给它时区
DateTimeFormatter FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
        .withZone(ZoneId.of("Asia/Shanghai"));
String s = FMT.format(now);

// LocalDateTime 的格式化（不需要时区）
LocalDateTime ldt = LocalDateTime.now();
String s2 = ldt.format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));

// 解析
LocalDateTime parsed = LocalDateTime.parse("2026-09-02 20:00:00",
        DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));

// Instant ↔ LocalDateTime
LocalDateTime ldt2 = LocalDateTime.ofInstant(now, ZoneId.of("Asia/Shanghai"));
Instant back = ldt2.atZone(ZoneId.of("Asia/Shanghai")).toInstant();

// 时间戳
long epochMilli = now.toEpochMilli();
Instant fromMilli = Instant.ofEpochMilli(epochMilli);
```

**跟 Go 的对照：**

```go
// Go
now := time.Now()                              // ≈ ZonedDateTime（带 Location）
utc := now.UTC()                               // ≈ Instant
fmt.Println(now.Format("2006-01-02 15:04:05")) // 布局串，无状态
d := time.Since(start)                         // ≈ Duration
parsed, err := time.ParseInLocation("2006-01-02 15:04:05", s, time.Local)
```

| 维度 | Go `time` | Java `java.time` |
|---|---|---|
| 类型数量 | 1 个（`time.Time`）+ `Duration` | 8+ 个（Instant/LocalDate/.../Period） |
| 可变性 | 不可变值类型 | 不可变 |
| 线程安全 | 是 | 是（所有类都是 final + 字段 final） |
| 格式化 | 方法 + 布局串，无状态对象 | `DateTimeFormatter` 对象（不可变，可共享） |
| 精度 | 纳秒 | 纳秒 |
| 布局语法 | `"2006-01-02 15:04:05"`（记忆点：1 2 3 4 5 6） | `"yyyy-MM-dd HH:mm:ss"`（注意 `MM` 是月，`mm` 是分） |

Java 那套 `yyyy-MM-dd HH:mm:ss` 的坑：`MM` = 月，`mm` = 分；`HH` = 24 小时制，`hh` = 12 小时制；`YYYY`（大写）是"基于周的年份"，在跨年那一周会给你一个错误的年份 —— **每年年底都有人踩 `YYYY` 这个坑**。用 `yyyy`。

### `Stream` 在 Java 8 里的误用

Stream 是 Java 8 的好东西，但它被用坏了。三种典型误用：

**误用一：为了用 Stream 而用 Stream**

```java
// ❌ 这样写的人大概觉得"函数式"更高级
int sum = list.stream().mapToInt(Integer::intValue).sum();

// ✅ 这样更简单更快（虽然没有 Stream 好看）
int sum = 0;
for (int x : list) sum += x;
```

**判据：如果 for 循环版本更易读，就用 for 循环。** Stream 的价值在于"链式表达数据转换流水线"，不在于"看起来现代"。

**误用二：在 Stream 里修改外部变量**

```java
// ❌ 编译能过（用数组绕过 effectively final 限制），但这是灾难
List<String> errors = new ArrayList<>();
items.stream().forEach(item -> {
    if (!validate(item)) {
        errors.add("invalid: " + item);   // 如果这是 parallelStream，ArrayList 会数据损坏
    }
});

// ✅ 正确：让 Stream 自己收集
List<String> errors = items.stream()
        .filter(item -> !validate(item))
        .map(item -> "invalid: " + item)
        .toList();   // Java 16+ 的 Stream.toList()，返回不可变列表
```

**误用三：`forEach` + 受检异常**

```java
// ❌ 编译错误：Consumer 的 accept 方法没有声明 throws
files.forEach(f -> {
    Files.readAllLines(f);   // 编译错误：unreported exception IOException
});

// 常见但错误的"绕过"：包一层 RuntimeException，然后在外面 catch
// 这样栈信息被包了两层，排查时很痛苦

// ✅ 如果只是要遍历并处理异常，用 for 循环，让异常自然抛出
for (Path f : files) {
    Files.readAllLines(f);
}
```

**判据：`forEach` 适合做"无异常的终端消费"（打印、发送、写入已经打开的资源）。一旦 lambda 里需要抛受检异常，就回到 for 循环。**

### `parallelStream` 的公共池问题

第 01 章提过，这里给完整的事故案例。

> **现象**：某商品服务，接口 A（商品详情）的 P99 偶发飙到 10 秒以上，一天几次，没有规律。同时，后台有一个每 5 分钟跑一次的批量任务（商品打标），跑的时候接口 A 就明显变慢。
>
> **排查**：
> 1. 接口 A 的耗时打点显示，慢的时候不是慢在 DB 查询，而是慢在"一段看起来很快的内存计算"上
> 2. 看代码，那段计算用了 `parallelStream`：
>
> ```java
> // 商品详情接口里
> List<Promotion> promos = promoList.parallelStream()
>         .map(p -> calcPromotion(p, user))   // 内部有 RPC 调用！
>         .toList();
>
> // 批量任务里（另一个类，另一个同学写的）
> items.parallelStream().forEach(this::doHeavyWork);
> ```
>
> 3. `jstack` 抓线程栈，发现 `ForkJoinPool.commonPool-worker-N` 线程全部处于 `WAITING` 状态，在等 RPC 响应
>
> **根因**：三个因素叠加：
> 1. **`parallelStream` 用的是 JVM 全局唯一的 `ForkJoinPool.commonPool()`**，所有 `parallelStream`、所有 `CompletableFuture` 的默认异步执行、所有使用它的第三方库，**共享同一个池**
> 2. 这个池的并行度默认是 `Runtime.getRuntime().availableProcessors() - 1`。4 核机器上就是 **3 个线程**
> 3. `calcPromotion` 里有**阻塞的 RPC 调用**。3 个线程全被阻塞，接口 A 的后续 `parallelStream` 任务只能在队列里排队
>
> 更糟的是批量任务也用同一个池，所以批量任务一跑，接口 A 的并行度直接归零 —— 而且**这两段代码没有任何一行是耦合的**，写批量任务的人完全不知道自己会影响接口 A。
>
> **额外一层坑**：在容器里跑（Docker/K8s），老版本 JDK（8u191 之前）对 CPU limit 无感知，`availableProcessors()` 返回的是**宿主机的核数**（比如 64），于是公共池开 63 个线程，跟容器限制的 2 核 CPU 严重不匹配，上下文切换把 CPU 打满。
>
> **修复**（从好到次好）：
>
> ```java
> // 方案 1（最好）：不要用 parallelStream 做 IO 密集的事
> // parallelStream 只适合纯 CPU 密集、且数据量足够大（通常上万条以上）的场景
> List<Promotion> promos = promoList.stream()
>         .map(p -> calcPromotion(p, user))
>         .toList();
>
> // 方案 2：如果确实要并行，用自己控制的线程池，不污染公共池
> // （Java 里"把 parallelStream 提交给自定义 ForkJoinPool"是个 hack，不推荐）
> List<CompletableFuture<Promotion>> futures = promoList.stream()
>         .map(p -> CompletableFuture.supplyAsync(() -> calcPromotion(p, user), MY_POOL))
>         .toList();
>
> // 方案 3（临时止血）：调大公共池，但这是全局的，治标不治本
> -Djava.util.concurrent.ForkJoinPool.common.parallelism=16
> ```
>
> **教训（三条）**：
> 1. **`parallelStream` 里绝对不能放阻塞 IO。** 公共池是为 CPU 密集计算设计的，它的并行度假设是"线程会一直占着 CPU 干活"，不是"线程会阻塞等待"
> 2. **共享池意味着故障会跨模块传播。** 你引入的一个第三方 jar 里用了 `parallelStream`，就能拖垮你的服务 —— 而你甚至不知道它在用
> 3. **并行不等于更快。** `parallelStream` 有拆分、调度、合并的固定开销，数据量小（几千条以内）或者每个元素的处理很轻时，它比串行还慢
>
> **Go 对照**：Go 里 `go func()` 完全没这个问题，因为 goroutine 阻塞时 Go runtime 会把 P 让给其他 goroutine，且阻塞不消耗 OS 线程。这正是 Java 21 虚拟线程要解决的问题（第 12 章会详细对比）。**但要注意：虚拟线程也解决不了"CPU 密集型任务"的并行问题 —— 那种场景你该用的从来都是 `parallelStream` 或者显式线程池。**

### 为什么国内大量项目卡在 Java 8

这不是技术问题，是经济问题。四个原因，按权重排：

**1. Oracle 商业授权变更（2019 年 1 月）**

Oracle JDK 8 的免费公开更新止于 **8u202**（2019 年 1 月）。之后的版本（8u211 起）用于生产环境需要商业订阅。这件事的直接后果是：

- 很多公司被迫在两个方向二选一：买 Oracle 订阅，或者迁移到 OpenJDK 发行版（Adoptium/Temurin、Azul Zulu、Amazon Corretto、阿里 Dragonwell、腾讯 Kona、华为毕昇）
- 而"迁移到 OpenJDK"这件事本身需要评估和测试 —— 很多公司就在评估阶段又拖了两年

（顺带：Oracle JDK 17 及以后采用了 NFTC 授权，可以免费商用，包括生产环境。所以现在这个障碍已经基本消失了。）

**2. Spring Boot 2.x 的兼容矩阵**

- Spring Boot 2.x 支持 Java 8 ~ 19（2.7 支持 8~21），大量公司停留在 Spring Boot 2.x
- **Spring Boot 3.0（2022 年 11 月）把基线提到了 Java 17**，并切换到 `jakarta.*` 命名空间
- 这意味着"升 Spring Boot 3"和"升 Java 17"和"改所有 `javax.*` 导入"是**同一件事**，成本叠加

一个公司的技术栈通常是：Spring Boot 2.7 + MyBatis + 一堆自研 starter + 一堆内部二方库。**任何一个二方库不支持 Java 17，整条链就卡住。**

**3. 升级成本无法量化收益**

升 Java 17 的收益是什么？"代码更简洁"、"性能略好"（G1 的改进、ZGC）、"能招到人"。这些都不好写成 KPI。

而成本是明确的：全量回归测试、改 `javax.*`、处理反射告警、处理废弃 API、可能的性能回退排查。**"没坏就别修"在工程管理上是理性选择。**

**4. JDK 8 的"够用主义"**

诚实地说，Java 8（2014）的三个特性 —— lambda、Stream、`Optional` —— 已经覆盖了 90% 的日常需求。`record` 省的是样板代码，`var` 省的是打字，`sealed` 是建模能力。**这些都是"更好"，不是"能用和不能用"的区别。**

加上 JDK 8 的 JVM 在多年优化后性能相当稳定，很多服务的瓶颈根本不在 JDK 版本上，在慢 SQL 和架构上。

**我的判断**：现在（2026 年）新项目一律 Java 17 或 21（21 是 LTS，且是虚拟线程的首个 LTS）。老项目的升级，触发点通常是"要升 Spring Boot 3"或者"要用到某个只在 17+ 的库"，而不是"为了升级而升级"。

### Java 9 模块系统（JPMS）为什么没被广泛采用

JEP 261（Java 9，2017）引入的模块系统，是 Java 历史上投入最大、回报最低的一次改动。

它的目标：

```
module com.example.order {
    requires com.example.user;
    requires java.sql;
    exports com.example.order.api;   // 只导出这个包，其他包外部看不到
}
```

解决的问题：真正的**封装边界**（`exports` 之外的包，包外代码访问不了，哪怕它是 public）、可靠的依赖声明、更小的运行时镜像（`jlink`）。

**为什么没火起来？**

| 障碍 | 具体 |
|---|---|
| 迁移成本 | 要把 classpath 改成 module path，所有依赖都得有模块描述符（或者当自动模块处理） |
| 生态没跟上 | 大量库没有 `module-info.java`，只能当"自动模块"（automatic module），名字从 jar 名推导，脆弱且不可靠 |
| 反射被卡 | 框架（Spring、Hibernate、MyBatis）大量用反射访问非导出包，模块化后全部要加 `opens` |
| 收益不明显 | "强封装"这个收益，对于单体应用来说，用代码规范和架构分层也能达到 80% |
| 与构建工具摩擦 | Maven/Gradle 对 module path 的支持长期不完善 |

**Go 对照（这是本节的重点）：**

**Go 天然有包级封装，所以根本不需要模块系统。**

```go
// Go：小写开头 = 包外不可见，编译器强制，零配置
package order
type internalHelper struct{}     // 包外看不到
func PublicAPI() {}              // 包外可见
```

Java 里最接近的东西是 `package-private`（不加修饰符），但 02.3 讲过 —— **Java 的包是开放的，任何人都能写 `package com.example.order;` 混进来**。所以 Java 的包级私有拦不住人。

**这解释了为什么 Java 需要 JPMS 而 Go 不需要模块系统来做封装**：

| | Go | Java |
|---|---|---|
| 封装边界 | 包（= 目录 = 编译单元），编译器强制 | JPMS 模块（需要 `module-info.java`，可选配置） |
| 边界强度 | 强（无法绕过） | 强（但只在模块化之后，且可用 `--add-opens` 打开） |
| 配置成本 | 零 | 要写 `module-info.java`，要改构建，要处理依赖的模块描述符 |
| 依赖声明 | `go.mod`（版本 + MVS） | `requires`（只声明模块名，**不管版本**） |

**最后一行的对比特别有意思**：Java 的 `requires` 只声明"我需要这个模块"，**不管版本**。版本管理仍然是 Maven/Gradle 的事（第 05 章）。所以 JPMS 解决的不是"依赖地狱"（Go 的 `go.mod` 解决的那个），而是"封装"和"运行时镜像裁剪"。

**结果就是**：JPMS 今天的主要价值在两处 —— （1）JDK 自身被模块化了（`java.base`、`java.sql` 等，这让 `jlink` 能裁剪出几十 MB 的运行时）；（2）少数对启动体积/安全隔离有强要求的场景。普通业务应用，`module-info.java` 你大概率一辈子都用不上。

---


