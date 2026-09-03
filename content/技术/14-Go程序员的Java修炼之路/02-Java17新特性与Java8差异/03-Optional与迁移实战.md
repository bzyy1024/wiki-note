# 第 02 章（节选）　Optional与迁移实战

> 本篇来自《Go 程序员的 Java 修炼之路》第 02 章「第 02 章　Java 17 新特性与 Java 8 差异（现代 Java 长什么样）」。
> 返回：[第 02 章索引](./README.md)

## 02.6 `Optional`：Java 对 NPE 的官方答案（Java 8）

`Optional` 是 Java 8 引入的，不算"新特性"，但它是**争议最大、误用最多**的一个，而且跟 Go 的 `(T, error)` 有直接对照关系，所以放在这里讲。

### 先纠正一个定位错误

**错误理解**：`Optional<T>` 是"一个可能为 null 的 T"。

**正确理解**：`Optional<T>` 是"一个**容器**，它可能含有一个 T，也可能什么都没有"。

这个区别决定了所有用法。如果你的心智模型是前者，你会写出这种代码：

```java
// ❌ 完全错误，比不用 Optional 还糟
Optional<User> u = getUser(id);
if (u.isPresent()) {
    User user = u.get();
    // ...
} else {
    // ...
}
```

这段代码的**信息量跟 `if (user != null)` 一模一样**，只是多绕了一层。这叫 "Optional 当作 null 检查的语法糖"，是把 Optional 用成了 `null` 的复杂版。

正确写法是链式：

```java
String city = getUser(id)
        .map(User::getAddress)        // Optional<Address>
        .map(Address::getCity)        // Optional<String>
        .filter(c -> !c.isBlank())    // 条件过滤
        .orElse("未知");               // 兜底
```

**判据：如果你写了 `isPresent()` + `get()`，99% 的情况下你在用错。**

### 方法清单（按使用频率）

```java
Optional<User> opt = ...;

// 变换
opt.map(User::getName)              // Optional<String>，空则空
opt.flatMap(u -> findProfile(u))    // 用于"映射函数本身返回 Optional"的情况
opt.filter(u -> u.getAge() > 18)    // 条件不满足则变空

// 取值
opt.orElse(defaultUser)             // 空则返回默认值（默认值总是被求值）
opt.orElseGet(() -> loadDefault())  // 空则调用 Supplier（懒求值）
opt.orElseThrow()                   // 空则抛 NoSuchElementException
opt.orElseThrow(() -> new BizException("用户不存在"))

// 消费
opt.ifPresent(u -> send(u))         // 非空才执行
opt.ifPresentOrElse(u -> send(u), () -> log("没找到"))  // Java 9+

// 构造
Optional.of(x)                      // x 为 null 就 NPE（用于"这里绝不该是 null"）
Optional.ofNullable(x)              // x 为 null 就返回 Optional.empty()
Optional.empty()
```

`map` 和 `flatMap` 的区别是新手必踩：

```java
Optional<User> opt = getUser(1);

// ❌ 错：map 会把结果再包一层 → Optional<Optional<Profile>>
Optional<Optional<Profile>> bad = opt.map(u -> findProfile(u));  // findProfile 返回 Optional<Profile>

// ✅ 对：flatMap 会把两层压平
Optional<Profile> good = opt.flatMap(u -> findProfile(u));
```

**判据：映射函数返回 `Optional<X>` 就用 `flatMap`，返回普通 `X` 就用 `map`。**

### 禁止用法（这些是真的会让同事骂你的）

```java
// ❌ 1. 作字段
class User {
    private Optional<String> middleName;   // 错！
}
// 为什么错：Optional 没有实现 Serializable，字段用它会破坏序列化；
//          而且字段为 null 和字段为 Optional.empty() 是两种"空"，你给自己找了两套空值语义

// ❌ 2. 作方法参数
void process(Optional<String> name) {   // 错！
    // 调用方得写 process(Optional.of("x"))，丑陋；
    // 而且调用方仍然可以传 null，你防不住
}
// 正确做法：重载，或者传 null 并在文档里说明
void process(String name) { }

// ❌ 3. 作集合元素
List<Optional<User>> users;   // 错！
// 正确：List<User>，用空列表或者移除元素表达"没有"

// ❌ 4. Optional<List<T>>
Optional<List<Order>> orders;   // 错！
// 正确：List<Order>，没有就是空列表 Collections.emptyList()
// 理由：空集合已经完美表达了"没有"，再包一层 Optional 是冗余的
```

第 4 条对 Go 程序员特别重要，因为 Go 里你会写：

```go
orders, err := repo.FindByUser(id)   // orders 可能是 nil slice
// 但 nil slice 完全可用！
for _, o := range orders { }   // nil slice 上 range 是安全的，循环 0 次
len(orders)                    // 0
```

**Go 的 nil slice 是一个"可用的空值"**，Java 的 `null` 是一个"毒药"（调用任何方法都 NPE）。所以 Go 里返回 `nil, nil` 是常见且无害的，Java 里返回 `null` 列表就是给别人埋雷。

**Java 的正确做法：永远返回空集合，不返回 null。** 这条是 Effective Java 里的建议，也是几乎所有现代 Java 代码库的规范。

### `orElse` vs `orElseGet` 的坑

```java
// ❌ 危险：expensiveCall() 无论 empty 与否都会执行
User u = opt.orElse(expensiveCall());

// ✅ 正确：只有 empty 时才调用
User u = opt.orElseGet(() -> expensiveCall());
```

**问题 7：** 为什么 `orElse` 一定会执行参数？

因为 `orElse(T other)` 的参数类型是 `T`，Java 的方法调用语义是**先求值参数，再调用方法**。编译器在调用 `orElse` 之前就必须把 `expensiveCall()` 的结果算出来。`orElseGet(Supplier<? extends T>)` 传的是一个函数对象，函数体推迟到 `orElseGet` 内部需要时才执行 —— 这是**惰性求值**。

Go 里没有这个问题，因为 Go 没有默认参数，也没有这种"传值 vs 传 Supplier"的重载选择。但 Go 有个类似的心智陷阱：

```go
// Go：这个 default 值在函数返回前就会被计算
v := getOrElse(m, "key", computeDefault())   // computeDefault 总是被调用
```

一样的道理，只是 Go 里更明显（你能看到这是个函数调用）。

**真实事故案例：`orElse` 里的慢查询**

> **现象**：某用户中心的"查询用户详情"接口 P99 从 20ms 涨到 800ms，而且跟数据量无关，跟是否命中缓存也无关 —— 无论用户存不存在，都慢。
>
> **排查**：Arthas `trace` 打在接口方法上，发现 `loadFromRemote()` 被调用了两次。一次在缓存未命中分支，一次……在缓存命中分支？看代码：
>
> ```java
> User user = cache.get(id)
>         .orElse(loadFromRemote(id));   // 每次都查了一次远程！
> ```
>
> **根因**：`orElse` 的参数是值语义，无论 `Optional` 是否有值，`loadFromRemote(id)` 都会执行。缓存命中率 95%，但仍然 100% 的请求都在打远程服务。
>
> **修复**：
>
> ```java
> User user = cache.get(id)
>         .orElseGet(() -> loadFromRemote(id));
> ```
>
> **教训**：`orElse` 和 `orElseGet` 的区别不是"写法风格"，是**是否执行**。`orElse` 的参数里出现任何方法调用，都要立刻警觉 —— 除非那个调用是廉价的（比如一个常量、一个已有对象）。
>
> 顺带：这类 bug 在本地测试很难发现（本地缓存命中率低，两次调用看起来都必要），在压测下也不明显（本地 mock 的远程调用很快）。**它只在生产的真实延迟下暴露。**

### 性能代价

`Optional` 是一个对象，每次 `map`/`filter` 都会产生新的 `Optional` 实例。这带来：

- 一次堆分配（`Optional` 对象本身）
- JIT 的**逃逸分析**（escape analysis）在多数情况下能把它优化掉（标量替换），所以短生命周期的 Optional 通常不产生真实分配
- 但在**超高频路径**（比如每请求调用几万次的序列化、编解码）上，Optional 会成为 GC 压力来源，而且逃逸分析不是总能生效（比如 Optional 被存进字段、被放进集合、或者方法太大导致内联失败）

**判据：业务代码随便用，框架/序列化/热循环路径谨慎用。** 如果你不确定，用 JMH 测（第 13 章会讲）。

### 跟 Go 的 `(T, error)` 对比

| 维度 | Go `(T, error)` | Java `Optional<T>` |
|---|---|---|
| 表达能力 | "没有值" **+ "为什么没有"** | 只有"没有值" |
| 错误上下文 | `error` 可以是任意实现，可 wrap、可 `errors.Is` | 无，空就是空 |
| 强制处理 | 不强制（`_` 可忽略） | 不强制（可以 `.get()` 直接炸） |
| 链式处理 | 无语法支持，手写 `if err != nil` | `map`/`flatMap`/`filter` 完整支持 |
| 组合多个 | 手写，一层层判断 | `flatMap` 可以串起来 |

**这是 `Optional` 最本质的局限：它只能表达"没有"，不能表达"为什么没有"。**

```java
// 这段代码的错误信息丢失了
Optional<User> findUser(long id);
// 调用方只知道"没找到"，不知道是"数据库连不上"还是"确实没这个人"
// 而这两种情况的处理方式完全不同：前者要重试/告警，后者要返回 404
```

**所以 Java 的实践中，`Optional` 的正确定位是：**

- ✅ **用于"查询类"方法的返回值**：`Optional<User> findById(long id)` —— 语义是"可能有也可能没有这个人"，两种情况都是正常的业务结果
- ❌ **不用于"操作类"方法**：`processOrder()` 失败应该抛异常，因为失败是异常状态，且需要错误信息

这个边界，恰好对应 Go 里的一个约定：**返回 `nil, nil` 表示"没有"，返回 `nil, err` 表示"出错了"。** 只是 Go 用两个值的组合表达了三种情况，Java 的 `Optional` 只有一种。

> 【思考】为什么 Java 不干脆把 `null` 干掉？像 Kotlin 那样做可空类型（`String?`），或者像 Rust 那样用 `Option<T>` 彻底替代 null。
>
> 提示：想想 Java 8 在 2014 年发布时，世界上已经有多少行 Java 代码。

<details>
<summary><b>参考答案</b></summary>

**直接答案：向后兼容。不是"不愿意"，是"做不到"——代价高到无法承受。**

**第一层：数字上的不可行。**

2014 年 Java 8 发布时，业界估计有超过 1000 万 Java 开发者、数十亿行 Java 代码在生产环境运行，以及一个海量的、发布到 Maven Central 的库生态。

Kotlin 能做可空类型，是因为它是**新语言**，2011 年发布时代码量是零，而且它设计了完整的 Java 互操作层（Kotlin 调用 Java 时，Java 的类型都是"平台类型" `String!`，可空性未知 —— 这恰恰说明连 Kotlin 都绕不开 Java 的 null）。

**Java 不能这么做，因为它的核心承诺是"20 年前编译的代码，今天还能跑"。** 这个承诺是 Java 在企业市场能活下来的唯一原因。

**第二层：技术上要改什么。**

假设 Java 要消灭 null，至少需要：

1. **区分 `T` 和 `T?`** —— 类型系统加一层，所有旧代码里未标注的类型算哪个？算 `T?`（全部可空，等于没改）还是算 `T`（所有旧代码立刻报几百万个编译错误）？两条路都是死路。
2. **改字节码验证器** —— JVM 规范里，引用类型的默认值就是 `null`。字段如果声明为不可空，那对象构造时要怎么初始化？要引入新的字节码校验规则。
3. **改所有 JDK API** —— `Map.get()` 返回什么？现在是 `null`，改成 `Optional<V>` 就是破坏性变更，全世界的代码都编译不过。
4. **改序列化格式** —— `null` 在 Java 序列化协议里有明确编码。

**任何一条都是"重写整个平台"级别的工程。** 而收益是什么？是"消灭 NPE" —— 一个可以通过代码规范、静态检查（`@Nullable` 注解 + IDE 检查）缓解 80% 的问题。

**投入产出比不成立。**

**第三层：Go 的 nil 为什么没这么痛 —— 这是设计差异的根源。**

Go 也有 nil，也有 nil pointer panic。但 Go 的 nil 没有 Java 的 null 那么痛，原因是**Go 的"零值"设计让 nil 变得可用**：

```go
var s []int          // nil slice
len(s)               // 0        ✅ 可用
for _, v := range s {}  // 循环 0 次  ✅ 可用
s = append(s, 1)     // ✅ 可用

var m map[string]int // nil map
len(m)               // 0  ✅
v, ok := m["x"]      // 0, false  ✅ 读是安全的
m["y"] = 1           // ❌ panic（写不行）

var c chan int       // nil channel
// 在 select 里，nil channel 永远阻塞 —— 这是被有意利用的特性

var mu *sync.Mutex
// 这是唯一真正危险的情况：nil 指针解引用
```

**Go 的核心设计：nil 是每种类型的合法零值，且运行时为最常见的 nil 值（slice、map、interface）提供了安全的操作语义。**

Java 完全相反：

```java
String s = null;
s.length();      // NPE
List<String> l = null;
l.size();        // NPE
l.isEmpty();     // NPE
```

**Java 的 null 是一个"所有引用类型的公共毒值"** —— 它不属于任何类型，却能赋给任何引用类型，且对它做任何操作都是未定义（抛 NPE）。

**这个差异的根源是两种语言对"零值"的态度：**

- **Go：每个类型都有有意义的零值。** 这是 Go 的显式设计原则（"Make the zero value useful"）。所以 nil slice ≈ 空 slice，nil map ≈ 只读的空 map。nil 不是一个"错误状态"，是一个"初始状态"。
- **Java：引用类型没有零值，`null` 是一个特例值。** 它不表示"空的 List"，它表示"这里根本没有对象"。所以任何操作都必然失败。

**第四层：那 Java 做了什么？**

Java 选择了**渐进改良**而不是革命：

1. **Java 8（2014）**：`Optional` —— 提供一个"更好的表达空的方式"，但不强制
2. **Java 14（2020，JEP 358）**：Helpful NullPointerExceptions —— NPE 的错误信息告诉你**具体是哪个变量是 null**：

```
Exception in thread "main" java.lang.NullPointerException:
    Cannot invoke "User.getAddress().getCity()" because the return value of "User.getAddress()" is null
```

这个改进的价值被严重低估了。以前你只能看到 `at OrderService.lambda$0(OrderService.java:42)`，还得自己猜那一行里三个点号哪个是 null。现在 JVM 直接告诉你。

3. **注解方案**：`@Nullable` / `@NonNull`（JSR 305 一直没正式通过，但 Spring 的 `@Nullable`、JetBrains 的 `@NotNull`、Checker Framework 都在用），配合 IDE 和静态检查工具（SpotBugs、ErrorProne、IntelliJ 的 inspections）在编译期发现大部分问题

4. **Java 的未来方向**：Project Valhalla 的 value types 可能会引入"隐式可空/不可空"的能力，但那是以后的事了

**更深一层 — 这是"存量"对"增量"的战争：**

一个新语言（Kotlin、Rust、Go）可以自由地做正确的事，因为它的存量是零。一个成熟语言的每次演进，都是在跟自己的存量做交易。

**Java 的每一次"改良而非革命"，都是在为 1995 年的一个设计决定付利息。** 而这个利息之所以值得付，是因为存量本身就是价值 —— 全世界跑在 JVM 上的金融交易、电信系统、企业 ERP，就是 Java 的护城河。

**对你的实际意义**：不要期待 Java 会变成 Kotlin。接受 `null` 存在这个事实，然后用这三件事管理它：
1. 自己的 API 里，查询类方法返回 `Optional`，其他方法不返回 `null`
2. 外部 API（尤其是老库）的返回值，进系统时立刻做 null 检查或者 `Optional.ofNullable()` 包一层
3. 打开 Helpful NullPointerExceptions（Java 14+ 默认开启）

**这个思路本身也是从 Go 学来的：Go 的 nil 也没被消灭，Go 的做法是"让 nil 可用 + 显式检查"。** 两种语言在这一点上其实是同一个思路，只是 Java 因为历史包袱，做起来更费劲。
</details>

---


## 02.8 迁移实战：Java 8 → 17 会撞上什么

这一节给一份可执行的清单。先说清楚一个常见误解：

**`javax.*` → `jakarta.*` 不是 JDK 的锅。** JDK 从来没改过 `javax.*` 的包名（`javax.sql`、`javax.crypto` 在 Java 17 里还好好的）。这个断裂点是 **Jakarta EE 9** 做的事 —— Oracle 把 Java EE 捐给 Eclipse 基金会时，`javax.*` 这个命名空间的使用权没给出去，所以 Eclipse 基金会改名成 `jakarta.*`。**Spring Boot 3.0 跟随 Jakarta EE 9，才把这事儿带到了每个 Java 应用面前。**

但因为你"迁 Java 17"和"升 Spring Boot 3"通常是同一件事，所以这里一起讲。

### 断裂点一：`javax.*` → `jakarta.*`

```java
// Spring Boot 2.x / Java EE 8
import javax.servlet.http.HttpServletRequest;
import javax.persistence.Entity;
import javax.validation.constraints.NotNull;
import javax.annotation.Resource;

// Spring Boot 3.x / Jakarta EE 9+
import jakarta.servlet.http.HttpServletRequest;
import jakarta.persistence.Entity;
import jakarta.validation.constraints.NotNull;
import jakarta.annotation.Resource;
```

受影响的包：`javax.servlet.*`、`javax.persistence.*`、`javax.validation.*`、`javax.annotation.*`、`javax.transaction.*`、`javax.mail.*`、`javax.xml.bind.*` 等。

**注意 `javax.xml.bind`（JAXB）是个特殊情况**：它在 Java 11 就**从 JDK 里被移除了**（JEP 320），不是改名。要用得手动加依赖：

```xml
<dependency>
    <groupId>jakarta.xml.bind</groupId>
    <artifactId>jakarta.xml.bind-api</artifactId>
    <version>4.0.2</version>
</dependency>
<dependency>
    <groupId>com.sun.xml.bind</groupId>
    <artifactId>jaxb-impl</artifactId>
    <version>4.0.5</version>
</dependency>
```

**批量改的办法**（IDE 全局替换有风险，容易误伤 `javax.crypto`、`javax.net.ssl` 这些**没改**的包）：

```bash
# 精确替换：只改那些确实迁移了的包前缀
find src -name "*.java" -exec sed -i \
  -e 's/javax\.servlet/jakarta.servlet/g' \
  -e 's/javax\.persistence/jakarta.persistence/g' \
  -e 's/javax\.validation/jakarta.validation/g' \
  -e 's/javax\.transaction/jakarta.transaction/g' \
  {} +
```

或者用 IDE 的 "Migrate to Jakarta EE" 功能（IntelliJ IDEA 有内置的迁移重构，比 sed 安全）。

**最容易漏的地方**：不是 `.java` 文件，是：

- MyBatis 的 XML 里写的 `javaType`（如果是 `javax.validation` 的类型）
- 配置文件里的类名字符串（比如 `spring.mvc` 相关的、`@Bean` 里写死的类名）
- 二方库的 `pom.xml`（它们也要同步升）

### 断裂点二：反射访问 JDK 内部 API 被封

```java
// 这种代码在 Java 8 能跑（有警告），Java 9-15 有警告，Java 16+ 默认拒绝
Field f = Class.forName("java.lang.String").getDeclaredField("value");
f.setAccessible(true);   // Java 17: InaccessibleObjectException
```

演进时间线：

| JDK | 行为 | JEP |
|---|---|---|
| 9-15 | 默认 `permit`，首次非法访问打印警告 | JEP 261（relaxed strong encapsulation） |
| 16 | 默认 `deny`，可用 `--illegal-access=permit` 打开 | JEP 396 |
| **17** | **`--illegal-access` 已过时**，写了只打印警告且**不生效** | JEP 403 |

JEP 403 的原文（JDK 17 Release Notes）：

> With this change, the `java` launcher option `--illegal-access` is obsolete. If used on the command line it causes a warning message to be issued, and otherwise has no effect.

**修复办法**：显式 `--add-opens`。

```bash
# 语法：--add-opens <源模块>/<包>=<目标模块>
# ALL-UNNAMED 表示"所有在 classpath 上的未命名模块"（也就是你的应用代码和所有非模块化 jar）
java --add-opens java.base/java.lang=ALL-UNNAMED \
     --add-opens java.base/java.util=ALL-UNNAMED \
     -jar app.jar
```

或者写进 jar 的 manifest（这样不用改启动脚本）：

```
Add-Opens: java.base/java.lang java.base/java.util
```

**注意：这是止血，不是治疗。** 用 `--add-opens` 打开的每一个包，都是一处技术债 —— 你依赖了 JDK 的内部实现，下次 JDK 重构它还得炸。**正确做法是找到那个库，升级到不依赖内部 API 的版本。**

常见的"我知道它在用内部 API"的库：老版本的 Netty（用 `sun.misc.Unsafe`）、老版本的 Kryo、老版本的 Mockito（用 `sun.reflect`）、老版本的 CGLIB、Lombok。

`sun.misc.Unsafe` 是特例：**它属于"critical internal APIs"，JEP 403 明确不封装它**（封装了整个生态会炸）。但它正在被逐步替代 —— 官方路径是 `VarHandle`（Java 9+）和 Foreign Function & Memory API（Java 22 正式，JEP 454）。

### 断裂点三：GC 相关

```bash
# ❌ Java 14 起：CMS 被移除（JEP 363）
-XX:+UseConcMarkSweepGC          # Unrecognized VM option

# ❌ Java 14 起：ParallelScavenge + SerialOld 组合被废弃（JEP 366）
#    相关的 -XX:UseParallelOldGC 也不应再单独指定
-XX:+UseParallelOldGC

# ❌ Java 17 起：实验性 AOT/JIT 编译器被移除（JEP 410）
#    用了会报 Unrecognized VM option
-XX:+UseAOT

# ✅ 现在的选择
-XX:+UseG1GC          # 默认，绝大多数场景
-XX:+UseParallelGC    # 吞吐量优先的批处理
-XX:+UseSerialGC      # 小内存/嵌入式
-XX:+UseZGC           # 低延迟，Java 15 起生产可用（JEP 377）
-XX:+UseShenandoahGC  # 低延迟，Java 15 起生产可用（JEP 379），注意：不是所有发行版都带
```

另外两个 Java 17 的行为变化：

- **`-XX:ParallelRefProcEnabled` 默认开启**（Parallel GC 的并行引用处理）
- **偏向锁被默认禁用并废弃**（JEP 374）—— 这个是好事，偏向锁在现代应用里基本是负优化

### 断裂点四：其他移除项

| 移除的东西 | 版本 | JEP | 影响 |
|---|---|---|---|
| Nashorn JS 引擎 + `jjs` 工具 | 15 | 372 | 用了 JS 脚本引擎的项目要换 GraalVM JS 或 Rhino |
| Pack200 工具和 API | 14 | 367 | 基本无人使用 |
| RMI Activation + `rmid` | 17 | 407 | 用 RMI Activation 的老系统（罕见） |
| Solaris/SPARC 移植 | 15 | 381 | — |
| Applet API | 17 废弃 | 398 | — |
| Security Manager | 17 废弃 | 411 | 有代码用 `System.setSecurityManager` 的要注意 |

**Nashorn 这一条对老项目真的会中招** —— 国内不少老系统里有"动态脚本"功能（规则引擎、公式计算），用的是 `ScriptEngineManager().getEngineByName("nashorn")`。Java 15 之后这个引擎没了。

### 升级检查清单（按顺序执行）

**阶段 0：确认现状**

```bash
java -version
mvn -version
# 记下当前 JDK 版本、构建工具版本、Spring Boot 版本
```

**阶段 1：扫废弃 API（先扫，不用改代码）**

```bash
# jdeprscan 是 JDK 自带的，扫描你的 jar 用了哪些废弃 API
jdeprscan --release 17 target/your-app.jar

# 或者在 JDK 8 上先扫一遍 JDK 8 的废弃项
jdeprscan --release 8 target/your-app.jar
```

**阶段 2：扫 JDK 内部 API 依赖（这一步最关键）**

```bash
# jdeps --jdk-internals 会列出你（和你的依赖）用了哪些 JDK 内部 API
jdeps --jdk-internals -R --class-path 'target/lib/*' target/your-app.jar
# 输出里每一行的 "JDK internal API" 都是一处待处理的点
```

**阶段 3：升级构建配置**

```xml
<!-- pom.xml -->
<properties>
    <java.version>17</java.version>
    <maven.compiler.release>17</maven.compiler.release>
</properties>
```

注意：用 `maven.compiler.release` 而不是 `source`/`target`。`release` 会同时限制"能用到的 JDK API 范围"，防止你用了 17 新增的 API 却要跑在 8 上 —— 这是 `source`/`target` 拦不住的经典坑。

**阶段 4：依赖升级**

```bash
mvn versions:display-dependency-updates
mvn versions:display-plugin-updates
```

重点关注：Lombok、Netty、Kryo、Mockito、CGLIB、ByteBuddy、javassist。这些库跟字节码和 JDK 内部 API 打交道，版本太老必炸。

**阶段 5：编译，打开所有警告**

```bash
mvn clean compile -Dmaven.compiler.showDeprecation=true
# 或者在编译器参数里加 -Xlint:all
# 这一步会一次性暴露所有 deprecated API 的使用
```

**阶段 6：跑起来，抓非法反射**

```bash
java -jar target/your-app.jar 2>&1 | grep -i "inaccessible\|illegal\|WARNING"
```

Java 17 上默认就是 `deny`，不需要加任何参数 —— 出现 `InaccessibleObjectException` 就是踩中了。逐个用 `--add-opens` 止血并记录：

```bash
java --add-opens java.base/java.lang=ALL-UNNAMED \
     --add-opens java.base/java.util=ALL-UNNAMED \
     -jar target/your-app.jar
```

**阶段 7：`javax` → `jakarta`（如果同时升 Spring Boot 3）**

用 IDE 的 "Migrate to Jakarta EE" 重构，比 sed 安全。改完重点检查非 `.java` 文件：MyBatis 的 XML、配置里写死的类名字符串、二方库的 `pom.xml`。

**阶段 8：GC 和启动参数清理**

```bash
# 检查启动脚本里有没有这些（在 Java 17 上会直接起不来）
grep -E "UseConcMarkSweepGC|UseParallelOldGC|UseAOT|PermSize|MaxPermSize" start.sh
```

建议：**先删掉所有 GC 相关参数，让 JVM 用默认值跑一轮压测，再按需加回。** 很多人保留了 Java 8 时代调好的一堆参数，而 G1 在 17 上的默认行为已经完全不同，那些老参数反而成了负优化。

**阶段 9：压测 + 观察**

至少对比四个指标：吞吐量、P99、GC 停顿、内存占用。Java 17 的默认 GC 仍是 G1，但实现改了很多（可中止的 mixed collection、NUMA 感知、及时归还内存）。

**一个实战建议**：**先只升 JDK，不升 Spring Boot。** 把 `<maven.compiler.release>` 从 8 改成 17，用 JDK 17 编译并运行，但保持在 Spring Boot 2.7（它支持 Java 17）。跑通了、压测过了，再单独做 Spring Boot 3 的迁移（改 `jakarta.*`）。**把两件事拆开，出问题时你能立刻知道是哪一件的锅。**

---


