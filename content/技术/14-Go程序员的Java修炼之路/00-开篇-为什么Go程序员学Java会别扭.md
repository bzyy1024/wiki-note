# 第 00 章　开篇：为什么 Go 程序员学 Java 会别扭

> 这一章不教你写代码。这一章要解决一个更贵的问题：**你带着五年的 Go 经验坐到一台 Java 项目前，到底卡在哪儿？**
> 卡点找错了，后面二十三章你都会学得很累 —— 因为你在用学习一门新语言的力气，去解决一个根本不是语言的问题。

---

## 0.1 先别急着翻目录，我们来演一段

假设周一早上，你的 leader 走过来说：

> "Java 那边有个订单服务，线上偶尔超时，老张离职了，你接一下。代码在 GitLab，本地跑起来你自己想办法。"

你是 5 年 Go 后端。你写过 Gin，写过 gRPC，自己造过轮子，看过 Go 标准库的源码。你心里大概率是这么想的：

> "Java 嘛，语法我看半天就懂了。不就是更啰嗦一点的静态语言吗？给我三天，我就能改 bug。"

然后你 `git clone` 下来，`ls` 一下，看到了这个：

```
order-service/
├── order-api/
│   └── pom.xml
├── order-core/
│   └── pom.xml
├── order-dal/
│   └── pom.xml
├── order-web/
│   └── pom.xml
├── pom.xml
├── mvnw
├── mvnw.cmd
└── .mvn/
    └── wrapper/
        └── maven-wrapper.properties
```

**停。先回答我第一个问题：**

> 在 Go 项目里，你 `git clone` 完，接下来做的第一件事是什么？

大概是 `go mod download`，然后 `go run ./cmd/server`，然后看它起来没有。整个过程你心里是**有底的** —— 因为 `go.mod` 里那几十行依赖，你一眼能看完，任何一个包你不认识，`go doc` 一下就知道它是干嘛的。

现在你面对这个 Java 项目。你打开根目录的 `pom.xml`，看到的是：

```xml
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-dependencies</artifactId>
            <version>2.7.18</version>
            <type>pom</type>
            <scope>import</scope>
        </dependency>
    </dependencies>
</dependencyManagement>
```

然后你打开 `order-core/pom.xml`，看到：

```xml
<dependency>
    <groupId>org.mybatis</groupId>
    <artifactId>mybatis</artifactId>
</dependency>
```

**注意到了吗？这里没有版本号。**

第二个问题来了：

> 一个依赖不写版本号，你怎么知道它用的是哪个版本？如果它依赖的传递依赖里又有一个不同版本的 mybatis，最后进 classpath 的到底是哪个？

在 Go 里，这个问题几乎不存在 —— `go.mod` 里所有版本（包括间接依赖）都被拍平写死了，MVS（最小版本选择）算法是确定的，一份 `go.sum` 锁死一切。

但在 Java 里，版本是**运行时才知道**的。Maven 有一套叫"最近优先"（nearest wins）的仲裁规则，Gradle 有另一套"最高版本优先"的规则，两边算出来的结果还不一样。更狠的是：同一个 artifact 的不同版本，可能在 classpath 里**同时存在**，而 JVM 加载哪个，取决于**那个 jar 在 classpath 里的物理顺序**。

**这就是你第一天会撞上的第一堵墙 —— 它跟 Java 语法一点关系都没有。**

---

## 0.2 所以，Go 程序员学 Java，真正的卡点是什么？

我把答案直接摆出来，然后我们一章一章把它拆开：

> **卡点不在语法，在"生态的厚度"和"运行时的黑箱度"。**

具体展开成五条，这五条就是这本书的脊梁。

### 卡点一：Java 的"包"不是 Go 的包

Go 里，`package` 就是一个目录，一个目录一个包，导入路径 = 代码托管地址。简单、粗暴、可预测。

Java 里，**包名（package）和物理路径（目录）只是约定上的对应，编译后就没关系了**。真正决定"这个类在哪"的，是 **classpath**。

这意味着什么？意味着：

```java
import com.fasterxml.jackson.databind.ObjectMapper;
```

这行代码在编译期，编译器去 classpath 里找一个叫 `com/fasterxml/jackson/databind/ObjectMapper.class` 的东西。找到了就过。**编译器不关心它来自哪个版本的 jar，不关心它是从 Maven 仓库下载的，还是你从桌面拖进来的。**

所以 Java 世界里有一整套 Go 世界里根本不存在的词汇：

| 术语 | 它到底在解决什么问题 | Go 里的对应物 |
|---|---|---|
| Classpath | 类的寻址空间 | 无（编译期确定） |
| ClassLoader | 谁负责把字节码变成 Class 对象 | 无 |
| Jar Hell | 同一个类被多个版本的 jar 提供 | 无（`go.mod` 唯一版本） |
| Shade / Relocation | 把依赖的类改名后塞进自己的 jar | 无（Go 静态链接） |
| BOM (Bill of Materials) | 一堆依赖的版本清单 | 勉强像 `go.mod` 的 require 块 |
| 依赖仲裁 | 多版本冲突时选哪个 | MVS 算法 |

**问题三（先想三十秒再看下面）：**

> 为什么 Java 需要 Shade（把依赖的类重新打包改名），而 Go 完全不需要这个东西？

<details>
<summary><b>参考答案</b></summary>

因为 **Go 是静态链接的，Java 是运行时寻址的**。

Go 编译产物是一个自包含的二进制文件。你依赖 `github.com/xxx/json` 的 v1，我依赖 v2，编译的时候两份代码被分别重命名后塞进同一个二进制的不同符号空间里，运行时各走各的，井水不犯河水。编译期就定死了，没有"运行时找类"这一步。

Java 编译产物是 `.class` 文件，运行时由 ClassLoader 按**全限定名**（FQCN，如 `com.fasterxml.jackson.databind.ObjectMapper`）去 classpath 里查。全限定名是唯一的寻址依据，**没有版本概念**。

所以如果你的服务依赖 A 库（它要 Jackson 2.9），而你的应用代码要 Jackson 2.15，classpath 里就有两个 jar 都含 `com.fasterxml.jackson.databind.ObjectMapper` 这个类。ClassLoader 按 classpath 顺序找到第一个就加载，另一个被"屏蔽"（shadow）了。

结果就是：A 库调用了一个 2.15 里被删掉的方法 → `NoSuchMethodError`。或者更惨的：加载到了旧版，你用了新方法 → 同样 `NoSuchMethodError`。**而这个错误在编译期完全不会出现**，因为你本地编译时用的可能是新版本。

Shade 的做法是：把 A 库依赖的 Jackson 2.9 里的所有类，从 `com.fasterxml.jackson.**` 改成 `com.mycompany.shaded.jackson.**`，然后连 A 库的字节码里对这些类的引用一起改掉，最后打成一个 jar。这样 classpath 里就不冲突了。

Go 不需要这么做，是因为 Go 在**编译期**就完成了等价的符号隔离。

**更深一层想**：这其实反映了两种语言对"部署单元"的不同定义。Go 的部署单元是**一个二进制文件**，Java 的部署单元是**一组 jar + 一个 JVM**。前者在编译期把所有冲突解决掉，后者把冲突推迟到运行时，代价是你需要一整套工具（Maven/Gradle/Shade/ClassLoader 隔离）来管理它。
</details>

---

### 卡点二：Java 的"错误"不是值，是控制流

Go 程序员看 Java 的异常处理，第一反应通常是：

```java
try {
    doSomething();
} catch (IOException e) {
    // ...
} catch (SQLException e) {
    // ...
} finally {
    conn.close();
}
```

"这不就是 Go 里被大家嫌弃的、当年 Java 抄过去的那一套吗？我们的 `if err != nil` 明明更清晰。"

**先别急着下结论。第四个问题：**

> 在 Go 里，如果一个函数可能失败，函数签名上你能看出来吗？在 Java 里呢？

Go 里你看不出来 —— `func ReadFile(name string) ([]byte, error)` 和 `func ToUpper(s string) string`，从类型上你只能知道"返回值里有没有 error"。而 `error` 是个接口，它**不告诉你具体是什么错误**。

Java 的 checked exception（受检异常）恰恰相反 —— 它在**方法签名**上强制声明：

```java
public void readFile(String path) throws IOException, SQLException
```

调用方要么 catch，要么继续 throws。**编译器强制你面对失败的可能性。**

这就是设计哲学的分叉口：

| | Go | Java |
|---|---|---|
| 错误的本质 | 一个值（value） | 控制流跳转（control flow） |
| 是否强制处理 | 否（`_ = f()` 可忽略） | checked exception 强制，unchecked 不强制 |
| 错误信息载体 | 实现 `error` 接口的对象 | 异常对象 + 完整调用栈 |
| 错误上下文 | 靠 `fmt.Errorf("%w")` 手动包装 | 自动带栈，靠 `cause` 链手动补充 |
| 缺失信息 | 默认**没有调用栈** | 默认**有调用栈** |

第五个问题，这个是关键：

> Go 里你排查一个线上 nil pointer panic，最常抱怨的是什么？

—— "这破栈看不出来是哪个请求、哪条数据触发的。" 因为 Go 的 `error` 默认不带栈（虽然现在有 `pkg/errors`、有 `errors.Join`，但依然要你手动 wrap 每一层）。

而 Java 的异常天生带完整的栈帧。代价是：**抛异常的开销很大**（填充栈帧 `StackTraceElement` 数组），所以 Java 社区有一条铁律：**不要用异常做正常流程控制**。

第六个问题（这个会贯穿全书）：

> 如果一个 Java 项目里有人在 for 循环里 try-catch 然后吞掉异常（`catch (Exception e) {}`），这会造成什么后果？为什么比 Go 里 `if err != nil { return }` 吞掉错误更可怕？

<details>
<summary><b>参考答案</b></summary>

表面上看，两者都是"错误被静默忽略"。但危害程度差很多，原因有三：

**1. Java 的异常会跨多层栈传播，Go 的 err 只能一层层往上递。**

Go 里 `if err != nil { return nil }` 吞掉错误，影响范围是**这一条调用链**。但你也必须在每一层手写返回，中间任何一层忘了，编译器会报"未使用变量"或者返回值类型不匹配。

Java 里 `catch (Exception e) {}` 是在**栈的某一层**切断了传播。上面所有层都感知不到这里出过事，会拿着一个**处于半成品状态的对象**继续往下跑。比如你 catch 掉了事务提交异常，但 Connection 没还回池子，几小时后池子耗尽，整个服务不可用 —— 而报错的堆栈早就丢了。

**2. Java 的异常对象携带了大量"即将失效"的信息。**

`catch (Exception e) {}` 等于把一份完整的犯罪现场照片（栈帧、cause 链、suppressed 异常）直接扔进碎纸机。事后再想排查，只能靠日志里恰好有别的输出，或者靠 JVM 的 `-XX:-OmitStackTraceInFastThrow`。

顺带一提这个 JVM 参数，它是个真实的坑：JVM 对某些高频抛出的热点异常（NPE、ClassCastException、ArrayIndexOutOfBoundsException）会做优化 —— 抛出太多次以后，**栈帧会被省略**，你日志里会看到 `java.lang.NullPointerException` 后面一个栈帧都没有。

生产上见过太多次了：服务跑了三天，突然开始报无栈 NPE，运维以为日志框架坏了，其实是 JVM 认为"这个异常你已经抛过几千次了，栈就不用打了"。

要复现完整栈，得重启，或者加 `-XX:-OmitStackTraceInFastThrow`。

**3. 在 for 循环里 try-catch 还有一层性能陷阱。**

try-catch 块本身在 JVM 里是通过**异常表**（Exception Table）实现的，进入 try 块几乎零成本。但**抛出异常**的成本很高（构造异常对象 + 填充栈帧，通常是微秒级）。

如果循环里每次迭代都抛一次异常，比如把 `NumberFormatException` 当校验手段用：

```java
for (String s : list) {
    try { ints.add(Integer.parseInt(s)); }
    catch (NumberFormatException e) { /* 跳过非法值 */ }
}
```

当 list 里有一百万个元素、其中 5% 非法时，你要构造五万个异常对象。**这比 Go 里 `strconv.Atoi` 返回 err 慢两三个数量级**。Go 的 error 只是一个接口值，构造成本约等于一次小对象分配；Java 的异常要 `fillInStackTrace()`，那是 `native` 方法，要遍历整个栈。

**所以结论是**：Go 的 `if err != nil` 强制你在**每一层**做决定（要么处理，要么包装后上抛），代价是啰嗦；Java 的异常让你可以在**任何一层**决定"到此为止"，代价是静默失败的风险和性能陷阱。

这本书后面会给你一套 Java 的异常处理规范（第 08 章会详细讲），核心原则只有一句：**要么处理，要么包装后上抛，永远不要只 catch 不记录。**
</details>

---

### 卡点三：Java 的"并发"和 Go 的"并发"根本不是一回事

你是 Go 程序员，`go func()` 已经刻进肌肉记忆了。一千个 goroutine？一万个？都不是事儿。

然后你写 Java：

```java
for (int i = 0; i < 10000; i++) {
    new Thread(() -> handleRequest()).start();
}
```

跑了三秒，OOM 了。

**第七个问题：**

> 为什么？你明明只是起了"一万个并发"，跟 Go 里一模一样啊。

因为 **Java 的 `Thread` 是操作系统线程（1:1 模型）**，Go 的 goroutine 是用户态调度（M:N 模型）。

具体数字：一个 Java 线程默认栈大小是 1MB（`-Xss1m`，虽然这是"预留"的虚拟内存不是实际占用，但线程对象本身 + 内核态数据结构是实打实的），加上线程切换需要陷入内核。一万个线程意味着：

- 一万个内核线程（kernel thread），内核调度器压力陡增
- 上下文切换成本：用户态 → 内核态 → 用户态，寄存器保存恢复，TLB 可能失效
- 大部分时间在切换，而不是在干活

而 goroutine 初始栈 2KB，按需增长，切换在用户态完成，Go runtime 自己调度。

所以 Java 世界的标准答案是**线程池**：

```java
ExecutorService pool = Executors.newFixedThreadPool(50);
for (int i = 0; i < 10000; i++) {
    pool.submit(() -> handleRequest());
}
```

一万个任务，五十个线程慢慢跑。

**第八个问题（这个很关键，想清楚它能省你半年的坑）：**

> 现在有了线程池，五十个线程。如果 `handleRequest()` 里有一个**阻塞的 HTTP 调用**（比如下游服务响应要 200ms），会发生什么？

答案是：五十个线程全卡在等 HTTP 响应上，剩下的 9950 个任务在队列里排着。吞吐量直接被锁死在 `50 / 0.2s = 250 QPS`。

而在 Go 里，这根本不是问题 —— goroutine 阻塞在网络 IO 上时，Go runtime 会把这个 P 上的其他 goroutine 挪走继续执行，网络就绪事件由 netpolitor（epoll/kqueue）通知。**阻塞被 runtime 吞掉了。**

**这就是 Java 生态里 WebFlux / Reactor / CompletableFuture / 以及 Java 21 虚拟线程（Virtual Thread）存在的全部理由。**

虚拟线程做的事，本质上就是：**让 JVM 来扮演 Go runtime 的角色** —— 线程阻塞时，自动把底层的载体线程（carrier thread）让出去给别人用。

这本书会用整整两章（第 10、11 章）讲传统并发模型，第 12 章专门讲虚拟线程，并且**逐条对照 goroutine**。到时候你会发现一件很有意思的事：虚拟线程和 goroutine 长得像，但骨子里有几个致命差别，踩了就线上事故。

---

### 卡点四：Java 的"运行时"是可调的，而可调意味着要调

Go 的 runtime 给你几个旋钮：`GOMAXPROCS`、`GOGC`。就这几个。剩下的 runtime 自己搞定，而且**默认配置在绝大多数场景下就是对的**。

Java 的 JVM 给你几百个参数。随便举几个：

```bash
-Xms4g -Xmx4g                    # 堆初始/最大
-Xmn2g                            # 新生代大小
-XX:SurvivorRatio=8               # Eden/Survivor 比例
-XX:+UseG1GC                      # 垃圾收集器选择
-XX:MaxGCPauseMillis=200          # GC 停顿目标
-XX:InitiatingHeapOccupancyPercent=45
-Xss1m                            # 线程栈
-XX:MetaspaceSize=256m            # 元空间
-XX:+HeapDumpOnOutOfMemoryError   # OOM 时自动 dump
```

**第九个问题：**

> 为什么 Go 只需要两个旋钮，JVM 需要几百个？是 JVM 设计得烂吗？

恰恰相反 —— **因为 JVM 要服务的场景跨度太大了。**

Go 的目标场景相对聚焦：网络服务、CLI 工具、云原生基础设施。所以它敢给你一个"够好"的默认配置，然后关上调参的大门。

JVM 要跑的东西包括：

- 一个跑在安卓上的 app（内存 256MB，要低延迟）
- 一个批处理作业（内存 64GB，吞吐量优先，停顿多久无所谓）
- 一个交易系统（延迟必须 < 10ms，且 P99 要稳）
- 一个大数据计算节点（几百 GB 堆，一次 GC 停顿几秒也能忍）

这些场景的最优配置是**互相矛盾**的。所以 JVM 的策略是：给你一堆默认值（还带自动优化，叫 Ergonomics），同时把旋钮都留着。

这带来一个直接后果：**你接手的每个 Java 项目的启动参数，都是前任工程师跟 JVM 搏斗过的战果。** `-XX:MaxGCPauseMillis=200` 为什么要设 200？可能是因为他们压测时发现设 100 会导致 GC 过于频繁、吞吐掉一半。

所以这本书第 13 章讲的不是"背下这些参数"，而是**给你一套推理框架**：看到 GC 日志，你能自己推出该调什么。

---

### 卡点五：Java 的"框架"是有魔法的，而 Go 的框架是显式的

你在 Go 里用 Gin：

```go
r := gin.Default()
r.GET("/user/:id", func(c *gin.Context) {
    c.JSON(200, getUser(c.Param("id")))
})
r.Run(":8080")
```

所有的路由注册都是**你写的、显式的、可以跳转过去的**。

Java 里你写：

```java
@RestController
public class UserController {
    @GetMapping("/user/{id}")
    public User getUser(@PathVariable Long id) {
        return userService.findById(id);
    }
}
```

**第十个问题：**

> 这个 `UserController` 是谁 `new` 出来的？`userService` 是哪个对象？谁给它赋的值？如果我想在测试里换一个 mock 的 userService，我该怎么做？

在 Go 里，这三个问题你闭着眼都能答：是你在 `main()` 里 new 的，是你在 `main()` 里手动注入的依赖，测试里你自己传个 mock 进去。

在 Java Spring 里，答案是：

1. **没人 new 它** —— Spring 容器在启动时扫描 classpath，找到带 `@RestController` 的类，用反射创建实例
2. `userService` 的值由 **IoC 容器注入**（`@Autowired` 或者构造器注入），具体是哪个实现类，取决于 classpath 里有几个 `UserService` 的实现、有没有 `@Primary`、有没有 `@Qualifier`、有没有 `@Profile` 激活
3. 测试里换成 mock，靠 `@MockBean` 或者 Spring Test 的上下文替换机制

**注意第二点的恐怖之处：运行时到底注入了哪个实现，你在编译期无法确定。**

这跟 Go 的 wire/DI 是完全相反的哲学：

| | Go (wire) | Java (Spring) |
|---|---|---|
| 依赖图解析时机 | **编译期**（wire 生成代码） | **运行时**（容器反射扫描） |
| 看依赖图 | 打开 `wire_gen.go` 一目了然 | 要看运行时日志 / Actuator `/beans` |
| 出错时机 | 编译失败 | 启动失败（或者更糟：启动成功但注入了错误的实现） |
| 灵活性 | 低（改依赖要重新生成代码） | 高（换 jar 就能换实现，不用改代码） |

**第十一个问题（这一条很值钱）：**

> 为什么说 Spring 的运行时 DI "更糟的情况是启动成功但注入了错误的实现"？举个真实场景。

<details>
<summary><b>参考答案</b></summary>

一个真实的例子：

你有一个 `OrderRepository` 接口，有两个实现：

```java
public interface OrderRepository { ... }

@Repository
public class MySQLOrderRepository implements OrderRepository { ... }

@Repository
@Profile("test")
public class InMemoryOrderRepository implements OrderRepository { ... }
```

`InMemoryOrderRepository` 是前任为了跑单测方便写的内存实现，加了 `@Profile("test")` 限制只在测试环境激活。

某天，运维在部署生产的时候，启动参数里带了 `--spring.profiles.active=test`（可能是从测试环境的启动脚本复制过来忘了改）。

结果：**服务正常启动，所有接口正常响应，但订单数据全写进了内存，重启就丢。**

这类问题在编译期完全不可见 —— 代码一模一样，jar 一模一样，只是启动参数不同。

再举一个更常见的：classpath 里同时有两个 `ObjectMapper` 的 Bean 定义（你自己的配置类定义了一个，某个 starter 又定义了一个）。没有 `@Primary`，启动时直接 `NoUniqueBeanDefinitionException` 失败 —— 这还算好的，**启动失败是最仁慈的失败方式**。

最坑的是这种情况：你依赖了一个 starter，它注册了一个 `RestTemplate` 的 Bean，而你自己的配置类也注册了一个同名的 Bean，且你的配置类被 `@ConditionalOnMissingBean` 覆盖掉了 —— 于是你的超时配置、拦截器等全部失效，HTTP 调用用的是默认配置（无限超时）。

服务跑得好好的，直到某天下游卡死，你的线程池被全部占满，整个服务雪崩。而你去查配置，配置明明写得对 —— 只是那个 `@Configuration` 类**根本没生效**。

**这就是为什么 Spring Boot 有一整套排查工具**：
- `spring-boot-actuator` 的 `/actuator/beans` 端点：列出容器里所有 Bean 及其来源
- `/actuator/conditions`：告诉你哪些自动配置类**匹配了、哪些没匹配、为什么没匹配**（这个端点是排查 Spring Boot "魔法" 的核武器）
- 启动日志加 `--debug`：打印完整的自动配置决策报告

这本书第 15 章会带你把自动装配的原理拆开，到时候你就不会再觉得它是魔法了。

**核心认知**：Spring 的"魔法"本质是**把编译期的确定性换成了运行时的灵活性**。这笔交易在大型项目里是划算的（插件化、可替换实现、无需重编译），但代价是你需要一整套工具来恢复"可观测性"。Go 的编译期 DI 放弃了灵活性，换来的是"代码就是真相"。
</details>

---

## 0.3 这本书怎么读

写到这里，你应该已经感觉到这本书跟你看过的 Java 教程不太一样了。说明一下规则。

### 它不是什么

- **不是语法手册。** 第 01 章一章过完语法，剩下的篇幅全部给"语法之外"的东西。
- **不是面试题集。** 我不关心 `HashMap` 初始容量是 16 还是别的什么（虽然我会讲，但讲的是为什么是 16）。
- **不是 API 文档。** 需要精确签名的地方，我会直接让你去看 javadoc。

### 它是什么

**一本"为什么"的书。** 每个知识点我都会先问问题，逼你想一下，再展开。因为我的经验是：

> **你知道一个东西怎么用时，你只是记住了它。你知道它为什么这么设计时，你才能推导出它的边界在哪。**

推导出边界，是"会用"和"精通"之间唯一的分界线。

### 每个章节的固定结构

1. **开场场景** —— 一个你真的会遇到的问题，不是 `Animal animal = new Dog()` 这种
2. **追问链** —— 我提问，你先想。重要问题带【思考】标记，**强烈建议先自己想三十秒再往下看**
3. **参考答案** —— 用折叠块包起来（`<details>`），想完再展开对答案
4. **代码锚点** —— 少而准的代码，用来钉住理解，不是让你抄
5. **Go 对照表** —— 每章都有，因为你的 Go 经验是你最大的资产，不是需要克服的障碍
6. **深层追问** —— 一章最后会有 3~5 个"更深一层"的问题，配完整参考答案
7. **动手清单** —— 可以立即验证的事情

### 关于【思考】标记的正确用法

我知道你会忍不住直接展开答案。这很正常，但**你亏了**。

给你一个数据：认知科学里有个结论叫**"必要难度"（desirable difficulty）**——学习时越费力，提取时越容易。你花三十秒猜一个答案，哪怕猜错，看到正确答案时大脑的编码强度也比直接看高得多。

**猜错的那三十秒，不是浪费，是投资。**

---

## 0.4 全书路线图

这本书 24 个文件，分成五个部分。你可以顺着读，也可以跳着读 —— 但第三部分（并发）和第四部分（生态）建议按顺序。

### 第一部分：认知地基（第 01-03 章）

| 章节 | 讲什么 | 你会获得什么能力 |
|---|---|---|
| 01 语言速通 | 一章过完 Java 语法，重点讲 Go 里没有的东西 | 能读懂任何 Java 代码的字面意思 |
| 02 Java 17 新特性与 Java 8 差异 | record、sealed、switch 模式匹配、var、Optional | 能看懂现代 Java 代码，也能看懂老项目 |
| 03 类型系统深水区 | 泛型擦除、通配符、协变逆变、桥接方法 | 看到 `List<? super T>` 不再心慌 |

### 第二部分：工程能力（第 04-09 章）

**这是这本书最"值钱"的部分**，因为市面上的 Java 教程几乎都不讲，而它恰恰是你每天要面对的。

| 章节 | 讲什么 | 你会获得什么能力 |
|---|---|---|
| 04 JVM 全景 | 类加载、字节码、内存模型、GC 基础 | 看得懂 `jstack` 输出，知道 `.class` 里有什么 |
| 05 Maven 深水区 | 坐标、仓库、依赖仲裁、BOM、多模块、私服 | 能自己搭多模块项目，知道依赖从哪来 |
| 06 Gradle 与构建选型 | Groovy/Kotlin DSL、增量构建、与 Maven 对比 | 两种构建工具都不怵，知道怎么选 |
| 07 依赖地狱治理 | 冲突、Jar Hell、ClassLoader、Shade | 遇到 `NoSuchMethodError` 能三分钟定位 |
| 08 排错方法论 | 异常体系、日志、Arthas、jstack/jmap/JFR | 有一套可复用的排查 SOP |
| 09 单元测试 | JUnit 5、Mockito、Testcontainers、给老代码加测试 | 敢改别人的代码 |

### 第三部分：并发与性能（第 10-13 章）

| 章节 | 讲什么 | 你会获得什么能力 |
|---|---|---|
| 10 Java 并发模型 | JMM、volatile、synchronized、AQS、锁升级 | 知道 `volatile` 到底解决了什么问题 |
| 11 并发工具箱 | 线程池、CompletableFuture、并发容器 | 能正确配置线程池（大部分人配错了） |
| 12 虚拟线程与结构化并发 | Project Loom、goroutine 对照、迁移陷阱 | 知道虚拟线程什么时候**不能**用 |
| 13 JVM 性能工程 | GC 调优、内存泄漏、火焰图、JMH | 能自己分析 GC 日志并给出结论 |

### 第四部分：生态与框架（第 14-19 章）

| 章节 | 讲什么 | 你会获得什么能力 |
|---|---|---|
| 14 Spring 核心 | IoC/DI、AOP、Bean 生命周期、循环依赖 | 知道 `@Transactional` 什么时候会失效 |
| 15 Spring Boot 工程化 | 自动装配、Starter、配置体系、启动流程 | 会写自己的 Starter，能排查自动配置 |
| 16 Web 层 | 一次请求的一生、拦截器、参数绑定、WebFlux | 知道请求在哪一层被卡住 |
| 17 数据访问 | JDBC 本质、HikariCP、MyBatis、JPA、事务传播 | 能排查连接池耗尽、事务不回滚 |
| 18 数据库与缓存 | MySQL 索引/事务/锁、Redis 缓存三兄弟 | 知道慢 SQL 和缓存穿透怎么治 |
| 19 消息与分布式 | Kafka/RocketMQ、分布式锁、分布式事务、RPC | 能选型，知道每种方案的代价 |

### 第五部分：源码阅读与收尾（第 20-22 章 + 附录）

| 章节 | 讲什么 | 你会获得什么能力 |
|---|---|---|
| 20 如何读懂开源 Java 项目 | 方法论 + 实操（Netty / Spring / 一个真实项目） | 拿到陌生项目知道从哪下口 |
| 21 上线与运维 | 打包、Docker、可观测性 | 知道 jar 是怎么跑起来的 |
| 22 避坑总集与反哺 Go | 60 个真实坑 + 学 Java 怎么让你 Go 写得更好 | 双向收益 |
| 附录 | Go ↔ Java 速查表、命令速查 | 随时可查 |

---

## 0.5 出发前，最后一个问题

这是本章最重要的问题。花一分钟想。

> 【思考】假设你只有**两周**时间，必须接手那个订单服务的线上问题（超时、偶发、找不到根因），你会怎么安排这两周？
>
> 换句话说：**这 24 章里，哪些是你现在就必须会的，哪些是可以往后放的？**

<details>
<summary><b>参考答案（这是你的学习优先级清单）</b></summary>

我的排法，供你对照：

**第一周：能跑起来 + 能看懂错误（生存线）**

优先级从高到低：
1. **第 05 章 Maven** —— 跑不起来的项目，其他一切都免谈。重点看：依赖仲裁、多模块、本地仓库在哪、`mvn dependency:tree`
2. **第 08 章排错方法论** —— 你要能在日志里找到线索。重点看：异常体系、日志配置、Arthas 的 `watch`/`trace`/`thread`
3. **第 04 章 JVM 全景（挑着看）** —— 只需要看：类加载 + 内存区域 + 线程栈。GC 细节先跳过
4. **第 14/15 章 Spring（挑着看）** —— 只需看：Bean 是怎么创建的、配置是怎么加载的。AOP 先跳过

这一周结束时，你应该能：本地启动项目、复现问题、在日志里找到异常栈、定位到大致是哪个模块。

**第二周：定位根因 + 敢改（战斗线）**

5. **第 10/11 章 并发模型与线程池** —— "偶发超时"八成跟线程池/锁有关。重点看：线程池参数、队列选择、`CompletableFuture`
6. **第 17 章 数据访问** —— 超时嘛，大概率是慢 SQL 或者连接池耗尽。重点看：HikariCP 参数、事务传播
7. **第 18 章 数据库与缓存（挑着看）** —— 慢 SQL 分析、索引失效场景
8. **第 13 章 性能工程（挑着看）** —— 如果怀疑是 GC 停顿导致的超时，看这一章。重点：`jstat`、`jmap`、GC 日志

这一周结束时，你应该能给出根因，并且有能力验证自己的猜测。

**可以往后放的（虽然很重要，但不救火）**

- 第 02 章 Java 17 新特性 —— 看老项目用不上，看新项目再查不迟
- 第 03 章 泛型深水区 —— 除非你要写框架代码
- 第 06 章 Gradle —— 等项目真用 Gradle 再说
- 第 12 章 虚拟线程 —— Java 21 才有，老项目大概率用不上
- 第 19 章 分布式 —— 单体都还没搞定，先别想分布式
- 第 20 章 源码阅读 —— 这是"有余力"才做的事

**但如果你是系统学习（不是为了救火），我建议严格按顺序读。**

为什么？因为这本书的章节之间有依赖：不懂 ClassLoader（第 04 章），你就看不懂为什么会有 `NoSuchMethodError`（第 07 章）；不懂 `synchronized` 的内存语义（第 10 章），你就看不懂 Spring 的单例 Bean 为什么需要小心（第 14 章）；不懂 classpath（第 05 章），你就完全无法理解 Spring Boot 自动装配扫描的是什么（第 15 章）。

**救火按优先级跳读；想精通，按顺序啃。**

顺便说一句：你现在选的是"系统学习"，所以我会按完整顺序写。但如果你中途真的遇到了线上问题 —— 随时跳到对应章节，这本书就是这么设计的。
</details>

---

## 0.6 本章核心结论（浓缩版）

如果你时间紧，只看这一段：

1. **Go 程序员学 Java 的卡点不在语法，在生态厚度和运行时黑箱度。** 语法一章就能过，生态要三个月。

2. **Java 的编译单元是 `.class`，部署单元是 `classpath + JVM`。** 这决定了 Java 世界里有一整套 Go 里不存在的概念：ClassLoader、Jar Hell、依赖仲裁、Shade。

3. **Go 把冲突在编译期解决（静态链接 + MVS），Java 把冲突推迟到运行时（classpath 寻址）。** 前者更安全，后者更灵活。

4. **Go 的错误是值，Java 的错误是控制流。** 各有代价：Go 啰嗦但显式，Java 简洁但容易静默失败。

5. **Go 的并发是 M:N 用户态调度，Java 传统线程是 1:1 内核线程。** 这解释了线程池、Reactor、虚拟线程存在的全部理由。

6. **Go 的 DI 在编译期（wire），Java 的 DI 在运行时（Spring 反射）。** 前者"代码即真相"，后者"需要工具恢复可观测性"。

7. **JVM 参数多不是设计烂，是因为服务场景跨度太大。** 学调优要学推理框架，不是背参数。

---

## 0.7 动手清单

读完这一章，做这三件事（都有明确产出）：

**1. 装环境，跑通一个最小 Spring Boot 项目（30 分钟）**

```bash
# 确认 JDK 版本（要 17 或 21）
java -version
# 确认 Maven
mvn -version
```

然后去 <https://start.spring.io> 生成一个最小项目：Java 17、Maven、Spring Web 依赖。下载解压后：

```bash
mvn spring-boot:run
```

看到 `Started DemoApplication in X seconds` 就成了。**这一步的目标是打破"Java 项目很重"的心理障碍。**

**2. 看一眼依赖树（10 分钟）**

```bash
mvn dependency:tree
```

你会看到几十行甚至上百行依赖。**不要试图全部看懂**，只看一件事：你明明只在 `pom.xml` 里写了 1 个依赖（`spring-boot-starter-web`），为什么最后出现了 30 个？

这个观察，就是第 05 章的起点。

**3. 故意制造一个依赖冲突（20 分钟，很有意思）**

在刚才那个项目里，手动加一个低版本的 Jackson：

```xml
<dependency>
    <groupId>com.fasterxml.jackson.core</groupId>
    <artifactId>jackson-databind</artifactId>
    <version>2.9.0</version>
</dependency>
```

然后跑 `mvn dependency:tree -Dverbose`，看看 Maven 是怎么处理冲突的。再把它删掉。

**做完这三件事，你已经比只看书不动手的人领先一大截了。**

---

## 0.8 深度思考题（带参考答案）

### 题 1：为什么 Java 项目普遍比 Go 项目"启动慢"？

<details>
<summary><b>参考答案</b></summary>

至少有五层原因，从浅到深：

**第一层：JVM 自身启动开销。** JVM 要初始化堆、元空间、JIT 编译器线程、GC 线程，加载几千个 JDK 自身的类（rt modules）。这部分大概 0.5~2 秒，跟你的代码无关。

**第二层：字节码解释执行 + JIT 预热。** Java 代码一开始是解释执行的，跑够次数（默认 10000 次调用，C2 编译器）才编译成本地代码。所以 Java 服务的"性能"要跑几分钟才达到峰值，而 Go 编译出来就是本地代码，第一毫秒就是峰值。

这有个实际影响：**压测 Java 服务必须先预热**，否则你测的是解释器的性能。

**第三层：classpath 扫描。** Spring Boot 启动时要扫描 classpath 里所有 jar 的 `META-INF/spring.factories`（Spring Boot 2.x）或 `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`（3.x），还要扫描你指定的包路径下所有类找注解。jar 越多、类越多，越慢。

一个典型的 Spring Boot 项目 classpath 里有 50~150 个 jar，几万个类。

**第四层：反射和动态代理的大量使用。** Spring 创建 Bean 用反射，`@Transactional`、`@Cacheable` 这些靠动态代理，MyBatis 的 Mapper 靠 JDK 动态代理生成实现类。反射和代理生成都要消耗时间，且生成的类要被 JVM 加载和验证。

**第五层（最本质）：Java 选择了"运行时灵活性"，启动时间就是这个选择的账单。**

Go 在编译期就把所有依赖链接成一个二进制，启动时只是 `mmap` 到内存、初始化 runtime、跳到 `main`。Java 在启动时才做"链接"——解析 classpath、加载类、装配 Bean、建立代理。

**这笔交易划算吗？** 对于要跑几个月不停的服务，摊薄后启动时间无所谓，运行时的灵活性和可优化性（JIT 能根据真实运行 profile 做优化，甚至能做得比静态编译更好）更值钱。对于 Serverless/FaaS 这种频繁冷启动的场景，就很痛 —— 这也是为什么 GraalVM Native Image 会存在（把 Java 提前编译成本地二进制，启动时间降到几十毫秒，代价是失去运行时动态性、编译要几分钟）。

**对照 Go**：Go 的启动快，是因为它把成本付在了**编译期**。Go 编译一个中型项目几十秒到几分钟，Java 编译同样的项目几秒 —— 但 Java 每次启动都要重新付一次"链接"的代价。
</details>

---

### 题 2：如果让你给 Go 加一个"类似 Spring 的运行时 DI 容器"，你会遇到什么根本性障碍？

<details>
<summary><b>参考答案</b></summary>

这道题是反着想，很有意思。答案：**Go 能做，但做出来会很难用，因为缺两样东西。**

**障碍一：Go 没有"扫描 classpath"的能力。**

Spring 的 DI 核心机制之一是 **classpath scanning** —— 扫描所有类，找带 `@Component`/`@Service` 注解的，自动注册成 Bean。

Go 里没有等价物。Go 的包在编译期就确定了依赖关系：你 `import` 了什么，编译器就链接什么。你没法在运行时问"当前二进制里有哪些类型实现了 `OrderRepository` 接口"。

（硬要做的话有 `go:embed` + 代码生成，或者用 `go/packages` 在编译前分析 AST 生成注册表 —— 但这已经不是"运行时"了，是编译期代码生成，也就是 wire 的路子。）

**障碍二：Go 的反射能力弱于 Java。**

Java 的反射能拿到：类的完整结构、注解（Annotation，运行时可读）、泛型信息（部分）、构造器、私有字段（setAccessible）。

Go 的 reflect 能拿到：类型信息、结构体字段和 tag、方法集。但**拿不到**：
- 函数参数的**名字**（只能拿到类型和数量）
- 方法上的注解（Go 只有 struct tag，且是字符串，没有结构化注解系统）
- 哪些类型实现了某接口（除非显式注册）

Java 的注解是**一等公民**：`@Autowired`、`@Value("${timeout}")` 可以在运行时被读取，`@Value` 里还能写 SpEL 表达式由 Spring 求值。Go 的 struct tag 只能是个字符串，还得自己解析。

**障碍三：Go 的哲学不鼓励"隐式魔法"。**

这条不是技术障碍，是文化障碍。Go 社区有一条不成文的规矩：**代码应该显式、可追踪**。`go to definition` 应该能跳到真实的实现。

Spring 那种"加个注解就自动生效"的做法，在 Go 社区会被认为"看不出代码在干什么"。uber-go 的 `fx`（一个 DI 框架）比 Spring 收敛得多，而且仍然是**显式注册 provider** 的：

```go
fx.Provide(NewOrderRepository, NewOrderService)
```

你还是得自己写清楚依赖从哪来。

**所以结论是**：不是技术上完全不可能，而是 Go 的**类型系统 + 编译模型 + 社区文化**三件事一起，把"运行时魔法 DI"这条路堵得性价比很低。

反过来看，这也正是 Go 程序员读 Spring 代码会觉得"邪门"的原因 —— 你找不到 `new` 在哪，找不到依赖在哪注入的，一切都是运行时决定的。

**等到你读完第 14、15 章，你就能把这套"魔法"翻译成你能理解的模型了。** 核心认知只有一句：**Spring 容器本质上就是一个 `map<String, Object>` 加上一套基于注解的填充规则。**
</details>

---

### 题 3：为什么 Go 的 `interface` 是隐式实现（duck typing），而 Java 的 `interface` 必须显式 `implements`？这给两个生态带来了什么不同？

<details>
<summary><b>参考答案</b></summary>

**先说设计取舍本身：**

Go 的隐式接口（structural typing）：
```go
type Reader interface { Read(p []byte) (n int, err error) }
// os.File 不需要声明自己实现了 Reader，只要方法签名匹配就行
```

Java 的显式接口（nominal typing）：
```java
public interface Reader { int read(byte[] b) throws IOException; }
public class MyReader implements Reader { ... }  // 必须写明
```

**Go 这么设计得到了什么：**

1. **第三方类型可以适配你的接口。** 你没法改 `os.File` 的源码，但你可以定义自己的 `Reader` 接口，`os.File` 自动满足。这在 Java 里要写适配器类（或者用 `Adapter` 模式包一层）。

2. **接口可以后置定义。** 先用具体类型写代码，等需要抽象了再抽接口。Go 社区的口号："接受接口，返回结构体"（Accept interfaces, return structs）。

3. **接口可以更小、更精确。** `io.Reader` 只有一个方法。因为实现成本为零，所以大家愿意定义小接口。Java 里 `implements` 一个接口是有心理成本的（要写关键字、要实现所有方法）。

**代价是什么：**

1. **你不知道一个类型实现了哪些接口。** 看 `*os.File` 的定义，你看不出它实现了 `io.Reader`。IDE 能帮你，但阅读代码时是缺失的信息。

2. **重构风险。** 改一个方法签名，可能悄悄破坏了某个隐式接口实现，编译期可能不报错（如果那个接口没被用到的地方）。

3. **无法表达"我就是要实现这个接口"的意图。** 有时候方法签名匹配只是巧合，语义上根本不是一回事。

**Java 这么设计得到了什么：**

1. **意图明确。** `class OrderServiceImpl implements OrderService` —— 一眼就知道这是什么。这对**读代码**极有价值，尤其是大型项目。

2. **接口可以演进（有代价）。** Java 8 的 default method 允许给接口加方法而不破坏实现类。

3. **IDE 和工具链友好。** 找所有实现类是一步操作。

**代价：**

1. **适配器地狱。** 想让两个不相关的库协作，经常要写一堆 `XXXAdapter`。

2. **接口倾向于被设计得很大。** 因为 `implements` 有成本，所以设计者倾向于"一次设计到位"，于是出现 `List` 这种 30 多个方法的接口（虽然 Java 8 之后用 default method 缓解了）。

3. **侵入性。** 你依赖的接口必须定义在某个你能 import 的包里。

**这个差异对你读 Java 开源项目的实际影响（重点）：**

Java 项目里，你会看到大量的 `XxxInterface` + `XxxImpl` 一对一组合：

```java
public interface OrderService { ... }
public class OrderServiceImpl implements OrderService { ... }
```

Go 程序员第一次看到会觉得很蠢："就一个实现，要接口干嘛？"

答案是：**为了 AOP 代理**。

Spring 的 `@Transactional` 是靠动态代理实现的。JDK 动态代理**只能代理接口**（这是 JDK 的限制，`Proxy.newProxyInstance` 要求传入接口数组）。所以如果你想让一个类的所有方法都带事务，这个类必须实现接口，否则 Spring 得用 CGLIB（通过生成子类来代理，要求类不能是 final、方法不能是 final）。

这不是设计洁癖，是**技术约束的产物**。

（第 14 章会详细讲这个，包括 CGLIB 代理的坑：`@Transactional` 在同一个类内部方法调用时会失效，原因就在这儿。）

**一句话总结**：Go 的隐式接口优化了"写"的体验和组合能力，Java 的显式接口优化了"读"的清晰度和工具链支持。当你从 Go 转过来读 Java 项目时，你会发现**代码更啰嗦但更自解释** —— 这是一笔你很快会开始欣赏的交易。
</details>

---

### 题 4：有个说法是"Java 是给普通人设计的，Go 是给聪明人设计的"，你怎么看？

<details>
<summary><b>参考答案</b></summary>

这句话我听过很多次，它有一点道理，但更多是情绪表达。我给你拆开看。

**这个说法有道理的部分：**

Java 确实做了很多"防呆设计"：
- 强制面向对象（连 `main` 都得包在类里）—— 逼着你组织代码
- Checked exception —— 逼着你处理错误
- 强类型 + 显式泛型 —— 逼着你声明意图
- 访问修饰符（public/protected/private）—— 逼着你定义边界

Go 则把决定权交给你：
- 错误处理靠约定（`if err != nil`），你可以不写
- 接口隐式实现，你可以不声明
- 没泛型之前（1.18 前）你可以用 `interface{}` 糊弄过去
- 大小写决定导出，没有 `private` 关键字

从这个角度看，Go 假设你**知道自己在干什么**，Java 假设你**可能会犯错所以需要护栏**。

**这个说法没道理的部分：**

**第一，"防呆"和"表达能力"不是对立的。**

Java 的护栏是有代价的，但换来的是**大规模协作下的可维护性**。一个 200 人的团队写 Java，代码风格的下限被语言拉住了。一个 200 人的团队写 Go，代码质量的下限取决于最弱的那个人 —— 因为 Go 允许你写出很多"能跑但很糟"的代码。

这不是说 Go 不好，是说**两种语言对"团队"这个变量的假设不同**。

**第二，现代 Java 已经不"防呆"了，反而相当灵活。**

如果你还停留在"Java 8 的 Java"的印象里，你会觉得 Java 很笨重。但 Java 17 有：
- `record`（一行定义一个不可变数据类）
- `var`（局部变量类型推导）
- `switch` 模式匹配
- `sealed` 接口（限制谁能实现，兼顾封闭与开放）
- Stream API（函数式）
- 虚拟线程（Java 21）

这些特性加一起，Java 的表达能力已经不比 Go 差多少了。

**第三（最关键的）：这句话混淆了"语言"和"生态"。**

人们说"Java 笨重"，往往不是在说语法，是在说：
- 启动一个项目要配一堆 XML/注解
- 依赖管理复杂
- 框架有魔法
- JVM 参数要调

但这些是**生态和历史包袱**的问题，不是语言本身的问题。一个精简的 Java 17 项目，用虚拟线程 + record + 少量依赖，可以写得跟 Go 一样干净。

**我的真实看法：**

这个说法真正的价值在于指出了一件事：**Go 让你更快达到 80 分，Java 让你更容易达到 95 分。**

- 写一个小工具、一个微服务、一个 CLI —— Go 更快、更爽、部署更简单
- 写一个要维护十年、几十人协作、需要插件化和热替换的系统 —— Java 的"啰嗦"变成了资产

你现在学 Java，不是为了放弃 Go，是为了**在你的工具箱里加一把不同的锤子**。学了 Java 之后回头写 Go，你会更清楚 Go 那些设计选择背后的取舍 —— 第 22 章专门讲这个。

**顺带一个追问**：你觉得 Go 的 `if err != nil` 真的比 Java 的 checked exception 好吗？还是说你只是习惯了？

（这个没有标准答案。但如果你觉得"显然更好"，我建议你读一下 Go 社区自己关于错误处理改进的讨论 —— 从 Go 1.13 的 `errors.Is/As`，到 1.20 的 `errors.Join`，再到社区对 `try()` 提案的激烈反对。你会发现，Go 社区其实一直在悄悄补 Java 早就有的东西。）
</details>

---

### 题 5（开放题，无标准答案）：你这辈子写过最"邪门"的一个 Go 代码是什么？如果它要用 Java 实现，会怎么写？

> 这道题是给你自己的，不是给我。
>
> 但如果你愿意，可以顺着这几个方向想：
> - 你用过 `unsafe` 吗？Java 里对应的东西叫什么？（提示：`sun.misc.Unsafe`，以及 Java 9 之后的 `VarHandle`）
> - 你写过基于 `reflect` 的通用序列化/校验逻辑吗？Java 里这类事情通常怎么解决？（提示：注解 + 运行时反射，或者编译期注解处理器）
> - 你用过 build tag 做条件编译吗？Java 里没有这个，那 Java 怎么解决"不同环境不同实现"？（提示：classpath + 依赖替换 + `@Profile`）
> - 你用 `go generate` 生成过代码吗？Java 里对应的东西叫什么？（提示：APT 注解处理器、Lombok、MapStruct、以及 GraalVM 的那套）
>
> **想清楚这几个映射关系，你就已经有了一个"Java 思维模型"的骨架。** 剩下的章节只是在这个骨架上填肉。

---

## 下一章预告

第 01 章，我们用一章的时间把 Java 语法过完。

但注意 —— 我说的"过完"，不是把《Java 核心技术》压缩成一章。我会重点讲：

- **Go 里没有的东西**：类、继承、重载、注解、反射、内部类、lambda
- **Java 里没有的东西**：多返回值、结构体、defer、goroutine、channel、组合
- **看起来一样其实完全不一样的东西**：`interface`、泛型、`error`、`string`、数组和切片

一章讲完，你就能读懂任何 Java 代码的**字面意思**。读不懂的只是"这段代码为什么这么写"—— 那是后面 21 章的事。

---

**现在，翻到下一章。**
