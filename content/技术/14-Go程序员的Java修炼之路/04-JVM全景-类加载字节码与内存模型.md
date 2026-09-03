# 第 04 章　JVM 全景：类加载、字节码与内存模型（读懂 JVM 说的人话）

> 线上服务卡死了。接口全超时，CPU 不高，日志里一句报错都没有。你登上机器，`jstack <pid>` 敲下去，屏幕上滚出几百行：
>
> ```
> "http-nio-8080-exec-1" #23 daemon prio=5 os_prio=0 tid=0x00007f8c4c0e8000 nid=0x1234 waiting on condition [0x00007f8b3a1fe000]
>    java.lang.Thread.State: WAITING (parking)
>         at sun.misc.Unsafe.park(Native Method)
>         at java.util.concurrent.locks.LockSupport.park(LockSupport.java:175)
>         at java.util.concurrent.LinkedBlockingQueue.take(LinkedBlockingQueue.java:442)
>         at java.util.concurrent.ThreadPoolExecutor.getTask(ThreadPoolExecutor.java:1074)
>         at java.util.concurrent.ThreadPoolExecutor.runWorker(ThreadPoolExecutor.java:1134)
>         at java.util.concurrent.ThreadPoolExecutor$Worker.run(ThreadPoolExecutor.java:624)
>         at java.lang.Thread.run(Thread.java:748)
> ```
>
> 每一行字你都认识，合起来你不知道它在说什么。更要命的是 —— 这一屏有 200 个这样的线程，你不知道该看哪一个。
>
> 这一章结束，你能逐行读懂它，知道哪个线程有问题、为什么，以及下一步该敲什么命令。

---

## 04.1 JVM 到底是什么：规范、实现、发行版

先看一个你在 Go 世界里永远见不到的现象。你去官网下载 Java，会看到这样一张列表：

| 发行版 | 提供方 | 定位 |
|---|---|---|
| Oracle JDK | Oracle | 商业授权，生产环境收费（按员工数计费），有订阅支持 |
| OpenJDK | 开源社区 | 源码仓库，本身不提供可直接安装的安装包 |
| Temurin | Eclipse Adoptium | 社区免费构建，TCK 认证，CI/生产都常用 |
| Amazon Corretto | AWS | 免费，AWS 环境深度优化，承诺长期支持 |
| Alibaba Dragonwell | 阿里巴巴 | 免费，针对电商场景调优，带 Wisp 协程等扩展 |
| Tencent Kona | 腾讯 | 免费，针对云上大规模部署调优 |
| BiSheng（毕昇） | 华为 | 免费，鲲鹏 ARM 架构优化 |
| Azul Zing | Azul | 商业，C4 无停顿收集器，低延迟场景 |
| GraalVM | Oracle / 社区 | 多语言运行时 + Native Image 提前编译 |

而在 Go 世界，你只有一条命令：`go install golang.org/dl/go1.22@latest`。一个官方工具链，没了。

**问题 1：** 这看起来很蠢对吧？一个语言搞出十个发行版，新人一进门就选择困难。为什么？

### 规范、实现、发行版：三层分层

先厘清三个词，这是理解一切的前提：

- **JVM 规范（Specification）**：一份文档，规定 `.class` 文件格式、字节码指令集、类加载、内存区域、线程模型的**语义**。它不规定怎么实现。任何人都可以写一个符合规范的东西，叫它 JVM。
- **JVM 实现（Implementation）**：真正跑起来的软件。HotSpot（Oracle/OpenJDK 官方实现，99% 的人用的都是它）、OpenJ9（IBM 捐给 Eclipse，内存占用小、启动快）、GraalVM、Azul Zing。
- **JDK 发行版（Distribution）**：把某个实现 + 类库 + 工具 + 安装包，打包成你能 `apt install` 或解压即用的东西，再配上支持周期。

所以它们的关系是：**一个规范 → 多个实现 → 每个实现多个发行版**。

对照 Go：Go 也有一份语言规范和内存模型文档，但**没有"运行时规范"** —— Go 的 runtime 就是唯一那份实现，规范是事后从实现里总结出来的描述，而不是反过来。所以 Go 世界不存在"第三方 Go 发行版"这个概念。

### JDK / JRE / JVM

```
JDK = JRE + 开发工具（javac、jar、jstack、jmap、jcmd、jps……）
JRE = JVM + 核心类库（java.*、javax.*）
JVM = 执行引擎 + 运行时数据区
```

**Java 9 之后 JRE 不再单独发行。** 配套的还有 JEP 220 的模块化改造 —— `rt.jar` 被拆成了 `jmods`，`tools.jar` 消失。所以你在老教程里看到的 `-XX:+TraceClassLoading` 之类输出里那句 `[Loaded java.lang.Object from /usr/lib/jvm/.../rt.jar]`，在新版 JDK 上会变成 `from java.base`。看到差异别慌，只是载体换了。

> 【思考】为什么会有这么多 JDK 发行版？Go 为什么一个都没有？
>
> 提示：想想 2010 年发生了什么（Oracle 收购 Sun），以及 Go 的许可证。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为治理模式（governance）不同，不是技术原因。**

**Java 这一边：** 2009 年 Oracle 收购 Sun。此前 Sun 已把 Java 开源（OpenJDK，GPL v2），但商标"Java"在 Oracle 手里。收购后 Oracle 逐步收紧授权：2019 年 JDK 8 公开更新停止（8u202 之后要商业许可），JDK 11 之后改为半年一版，生产使用超期按员工数付费。

商业公司面临一个现实问题：**我生产环境跑着的 Java 8，安全补丁从哪来？** 于是各家开始自己维护 OpenJDK 构建分支、自己打补丁、自己做 TCK 认证、自己承诺支持周期。Red Hat、AWS、阿里、腾讯、华为都这么干了。

所以发行版的本质不是"技术分叉"，而是**支持责任的重新分配**：Oracle 不免费兜底了，社区和云厂商各自接盘。

**Go 这一边：** Go 自开源起就是 BSD 许可，且只有一个官方仓库、一个团队、一个发布渠道。没有任何收购事件能把许可收回去。就算 Google 某天不管了，任何人都能 fork 继续走 —— 但**没有动机**，因为官方渠道一直在稳定供货。

**更深一层**：这是"公司控制的开源"和"社区控制的开源"两条路。Java 的规范（JCP）和实现（OpenJDK）分开、商标在商业公司手里，天生允许"规范免费、商业授权收费"；Go 是 Google 单方面控制但保持免费，风险和弹性都在一点上。

**对你的实际影响（这条最有用）：**

选发行版不要纠结性能 —— 这些发行版 99% 的代码是同一份 OpenJDK。真正要看三件事：**支持周期**（谁给你打补丁，选有 LTS 承诺的）、**是否通过 TCK 认证**（没过的在法律上不能叫 Java）、**团队熟悉度**。一句话建议：本地用 Temurin，云上用云厂商自己的版本（AWS 用 Corretto，阿里云用 Dragonwell），别碰 Oracle JDK 的商业条款。

**更深一层**：Go 换来了极低的认知成本（你永远不用问"该装哪个 Go"），代价是治理单点风险；Java 换来了竞争带来的创新（ZGC、Shenandoah、GraalVM、C4 都是不同实现卷出来的），代价是新手的选择困难。同一个取舍：**认知成本 vs 演进活力。**
</details>

### Go ↔ Java 工具链对照

| 维度 | Go | Java |
|---|---|---|
| 规范与实现 | 一份规范文档 + 一份官方实现（不可分） | JVM 规范 / 多个实现 / 多个发行版（三层） |
| 编译器 | `gc`（官方）+ `gccgo`（非主流） | HotSpot + C1/C2 JIT、OpenJ9、Graal |
| 部署产物 | 单个静态二进制 | `.class` / jar + 一个 JVM |
| 运行时可调项 | `GOMAXPROCS`、`GOGC`（后来加了 `GOMEMLIMIT`） | 几百个 `-XX:` 参数 |
| 版本管理 | `go.mod` 里写 `go 1.22` | `pom.xml` 里 `maven.compiler.release`，JDK 版本由环境决定 |

**Go 程序员容易踩的坑 #1：** 你会下意识地以为"Java 版本"是写在项目里的。它不是 —— **JDK 版本由运行环境决定**，`pom.xml` 只告诉编译器"生成什么版本的字节码"。所以"本地跑得好好的，上服务器就报 `UnsupportedClassVersionError`"是新人第一周必遇的：本地 JDK 17，服务器 JDK 8，字节码主版本号 61，JDK 8 只认到 52。

---

## 04.2 类加载机制：双亲委派

Go 里没有 ClassLoader 这个概念，因为 Go 编译期就把所有依赖静态链接进二进制了。Java 把"找类"这件事推迟到运行时，于是必须有一个东西负责找 —— 这就是 ClassLoader。

### 三层内置 ClassLoader

```
Bootstrap ClassLoader      C++ 实现，加载 java.base 等核心模块（java.lang.String、java.util.List…）
        ↑
Platform ClassLoader       Java 9 之前叫 Extension ClassLoader，加载 JDK 扩展模块
        ↑
Application ClassLoader   也叫 System ClassLoader，加载 classpath 上你的代码和依赖 jar
        ↑
  自定义 ClassLoader        Tomcat 的 WebAppClassLoader、Spring Boot 的 LaunchedURLClassLoader…
```

**注意一个细节**：Bootstrap 是 C++ 写的，Java 代码里拿不到它，`String.class.getClassLoader()` 返回 `null` —— 这个 `null` 不是"没有加载器"，是"Bootstrap 加载器"。这是实际排查时的判断依据（返回 null 就说明这个类在 JDK 核心里）。

**Java 9 的变化**：Extension ClassLoader 改名为 Platform ClassLoader（模块化后"扩展目录"机制没了），老资料里的 `ExtClassLoader` 就是它。

### 双亲委派的工作流程

流程只有一句话：**先问爸爸，爸爸搞不定自己来。**

```java
// java.lang.ClassLoader.loadClass 的简化逻辑
protected Class<?> loadClass(String name, boolean resolve) {
    synchronized (getClassLoadingLock(name)) {
        // 1. 先查自己有没有加载过（缓存）
        Class<?> c = findLoadedClass(name);
        if (c == null) {
            try {
                // 2. 有爸爸就先问爸爸
                if (parent != null) {
                    c = parent.loadClass(name, false);
                } else {
                    c = findBootstrapClassOrNull(name);  // 爸爸没了，问 Bootstrap
                }
            } catch (ClassNotFoundException e) {
                // 爸爸说找不到
            }
            if (c == null) {
                // 3. 爸爸搞不定，自己去 classpath 里找
                c = findClass(name);
            }
        }
        return c;
    }
}
```

**问题 2：** 这个"先问爸爸"的递归最终一定会走到 Bootstrap。那么如果 Bootstrap 也找不到 `com.mysql.cj.jdbc.Driver`，会发生什么？

一级一级返回 `ClassNotFoundException`，最后 Application ClassLoader 自己 `findClass` 去 classpath 找，找到了就加载，找不到就抛异常。

> 【思考】为什么叫"双亲"委派？这个设计解决了什么问题？
>
> 顺带想一下：如果我自己在项目里写一个 `package java.lang; public class String { ... }`，能被加载吗？

<details>
<summary><b>参考答案</b></summary>

**先说名字**：叫"双亲"是翻译问题，英文是 **parent delegation**，只有一层父加载器。理解成"父委派"就行。

**它解决两个问题：类的唯一性，和安全。**

**问题一：避免类重复加载。**

没有委派的话，A 和 B 各自加载一次 `com.example.User`，JVM 里就有两个 `User` 类：

```java
Class<?> c1 = loaderA.loadClass("com.example.User");
Class<?> c2 = loaderB.loadClass("com.example.User");
System.out.println(c1 == c2);  // false —— 是两个不同的类

// c2.cast(u1);  // ClassCastException: com.example.User cannot be cast to com.example.User
```

最后那行报错是最让人崩溃的那种：**类型名一模一样，强转失败。** 见过一次终身难忘。有了父委派就只有一份。

**问题二（更本质）：安全。**

这就是"自己写 `java.lang.String`"的答案：Application ClassLoader 收到加载 `java.lang.String` 的请求 → 先问爸爸 → 一路问到 Bootstrap → **Bootstrap 在自己的地盘（java.base 模块）里找到了，直接返回 JDK 的那一个**。你写的那个**永远不会被加载**。

（补充：还有更硬的一层防护 —— `java.*` 是受保护包名，即使真去 `defineClass`，也会被 `SecurityException: Prohibited package name: java.lang` 拦下。双亲委派是第一道门，包名检查是第二道。）

**这个设计的本质是什么？**

**类的唯一性由「类加载器 + 全限定名」共同决定，而不是单靠全限定名。**

这是全章最重要的句子之一。JVM 里的"类型"是一个二元组 `(ClassLoader, FQCN)`，所有 ClassLoader 隔离技术（Tomcat 多应用隔离、OSGi 模块化、Arthas agent 隔离）全建立在这个语义之上。

```java
public class LoaderDemo {
    public static void main(String[] args) throws Exception {
        System.out.println(String.class.getClassLoader());   // null → Bootstrap
        System.out.println(LoaderDemo.class.getClassLoader());
        // jdk.internal.loader.ClassLoaders$AppClassLoader@…

        // 自己造一个加载器，故意不看爸爸
        ClassLoader rebel = new ClassLoader(null) {  // parent = null → 直接问 Bootstrap
            @Override
            protected Class<?> findClass(String name) throws ClassNotFoundException {
                byte[] bytes = readClassBytes(name);  // 自己从某个地方读字节码
                return defineClass(name, bytes, 0, bytes.length);
            }
        };
        Class<?> c1 = LoaderDemo.class.getClassLoader().loadClass("com.example.User");
        Class<?> c2 = rebel.loadClass("com.example.User");
        System.out.println(c1 == c2);  // false —— 同名不同类
    }
}
```

**更深一层**：Go 的类型是**编译期的符号**，链接完就固化，全局唯一；Java 的类型是**运行时的对象**，可以被不同的人造出来。所以 Java 能热部署、能插件化、能让 Tomcat 一个进程跑十个应用 —— 代价是你要理解"加载器命名空间"这件 Go 里不存在的事。
</details>

### 什么时候必须破坏双亲委派

这是本节最值钱的部分。**双亲委派不是教条，它解决的是"统一"，而很多场景需要的是"隔离"。** 一旦你要隔离，就得反着来。

**场景一：JDBC SPI（Java 6 起的标准做法）**

`java.sql.DriverManager` 在 `java.sql` 模块里由 **Bootstrap** 加载，但 MySQL 的 `com.mysql.cj.jdbc.Driver` 在 classpath 里只能由 **Application** 加载。Bootstrap 是爸爸，看不到儿子的 classpath —— 按双亲委派，`DriverManager` 永远加载不到 MySQL 驱动。

**问题 3：** 那 `Class.forName("com.mysql.cj.jdbc.Driver")` 之后 `DriverManager.getConnection()` 为什么能工作？

答案是 **线程上下文类加载器（TCCL，Thread Context ClassLoader）** —— 一个挂在 Thread 对象上的引用，允许"爸爸反向借用儿子的加载器"：

```java
// ServiceLoader / DriverManager 内部的逻辑简化
ClassLoader cl = Thread.currentThread().getContextClassLoader();  // 通常是 AppClassLoader
ClassLoader saved = Thread.currentThread().getContextClassLoader();
try {
    Thread.currentThread().setContextClassLoader(cl);
    ServiceLoader<Driver> loadedDrivers = ServiceLoader.load(Driver.class, cl);
    // 用儿子的加载器去加载儿子的类
} finally {
    Thread.currentThread().setContextClassLoader(saved);  // 用完一定要还原
}
```

这就是所谓的"反向委派"。所有 Java 的 SPI 机制 —— JDBC、JNDI、JAXP、SLF4J 的绑定、Dubbo 的扩展点 —— 底层都是这一招。

**Go 对照**：Go 里没有对应物，因为 Go 编译期就把驱动注册进去了（`import _ "github.com/go-sql-driver/mysql"` 的 `init()` 往全局 map 里塞）。**Go 用"编译期显式 import"解决了 Java 需要一套 SPI 机制才能解决的问题。**

**场景二：Tomcat 的应用隔离（反着来的典型）**

一个 Tomcat 跑三个 WebApp，A 用 Spring 5.3、B 用 6.0、C 用 4.3，三个版本的 `ResourceLoader` 必须共存。按双亲委派不可能（同名类父加载器只会加载第一个），所以 Tomcat 的 `WebAppClassLoader` **反着来**：

```
1. 先查自己的缓存
2. 先查 JVM 已有的（Bootstrap）
3. 【关键】自己先去 WEB-INF/classes 和 WEB-INF/lib 里找
4. 自己找不到，再委派给爸爸
```

第 3 步和第 4 步的顺序跟标准双亲委派**完全相反**。Tomcat 的 `delegate` 参数（默认 `false`）控制的就是这个顺序：

```xml
<!-- conf/context.xml，改成 true 就恢复标准双亲委派 -->
<Context>
  <Loader delegate="true"/>
</Context>
```

**但有个例外**：`java.*`、`javax.*`/`jakarta.*` 及 Servlet API 强制委派给父加载器。否则每个 WebApp 都加载一份自己的 `javax.servlet.Servlet`，Tomcat 就没法把请求交给你的 Servlet 了（跨加载器的类不兼容）。

**场景三：Spring Boot 的可执行 fat jar**

`java -jar app.jar` 的 jar 结构是：

```
app.jar
├── BOOT-INF/classes/        你的代码
├── BOOT-INF/lib/*.jar       嵌套的 jar（jar in jar！）
├── META-INF/MANIFEST.MF     Main-Class: org.springframework.boot.loader.JarLauncher
└── org/springframework/boot/loader/…
```

标准 JDK 的 `URLClassLoader` 不认识 `BOOT-INF/lib/` 里**嵌套的 jar**（`jar:` URL 协议不支持嵌套）。所以 Spring Boot 写了 `LaunchedURLClassLoader` + 自定义协议处理器 `org.springframework.boot.loader.jar.Handler`，让 `jar:file:/app.jar!/BOOT-INF/lib/spring-core-6.0.jar!/` 这种路径能被解析 —— 它要的也是隔离：fat jar 内部的依赖优先于外部容器。

**场景四：热部署与字节码增强**

Arthas、SkyWalking 这些 agent 要在运行时改字节码（用 ASM/ByteBuddy 改 `defineClass` 的输入），必须自定义加载器 + `Instrumentation` API。这是最激进的一种"破坏"。

### `ClassNotFoundException` vs `NoClassDefFoundError`

这两个你会反复遇到，表格收好：

| | `ClassNotFoundException` | `NoClassDefFoundError` |
|---|---|---|
| 类型 | checked **Exception**（必须 catch） | **Error**（不该 catch） |
| 谁抛的 | 你的代码 / `Class.forName` / `ClassLoader.loadClass` | JVM 在解析符号引用时抛 |
| 语义 | "我按名字去找，没找到这个类" | "我**以前见过**这个类，现在拿不到它的定义了" |
| 典型触发 | classpath 里确实没这个 jar；动态加载拼写错 | ① 编译时有、运行时 classpath 缺 jar ② **类初始化失败过一次**，后续访问直接抛这个 |
| 排查方向 | 检查 classpath / jar 是否在 | 往**日志最开头**翻，找第一次的 `ExceptionInInitializerError` |
| 常见度 | 高 | 高，且更容易被误判 |

**最坑的是 `NoClassDefFoundError` 的第二种情况：**

```java
public class Config {
    static {
        // 静态初始化块里读配置文件，文件不存在
        PROPS = loadFromFile("/etc/app.conf");  // 抛 RuntimeException
    }
}
// 第一次使用：ExceptionInInitializerError: 静态初始化失败
// 第二次及之后使用：NoClassDefFoundError: Could not initialize class Config
```

JVM 规范规定：一个类被标记为"初始化失败"后，后续任何使用它的尝试都直接抛 `NoClassDefFoundError`，**不会重新尝试初始化**。所以你翻到 `NoClassDefFoundError` 时，**真正的病根在几百行之前的那次 `ExceptionInInitializerError`**。（Go 里不存在这类问题：包级变量初始化失败就是 panic，没有"记一笔账后续换个错误"的机制。）

---

## 04.3 类的生命周期

一个 `.class` 文件从磁盘到可用，走七步：

```
加载 → 验证 → 准备 → 解析 → 初始化 → 使用 → 卸载
        └──────── 链接 ────────┘
```

前五步按顺序发生，但**解析可以在初始化之后才开始**（为了支持动态绑定）。

### 两步最容易混淆：准备 vs 初始化

```java
public class Counter {
    public static int count = 100;        // 准备阶段：count = 0；初始化阶段：count = 100
    public static final int MAX = 999;    // 准备阶段：MAX = 999（因为 ConstantValue 属性）
}
```

**准备阶段**给静态变量分配内存并赋**零值**（`0`、`false`、`null`），不是你写的 100；**初始化阶段**才执行编译器生成的 `<clinit>()` 把 100 赋进去。为什么 `MAX` 例外？因为 `static final` 的基本类型/String 字面量常量会被 javac 记成 `ConstantValue` 属性，准备阶段就直接写入。

### 五个触发初始化的时机

JVM 规范严格规定**有且仅有**这五种情况会触发初始化：`new` 一个实例 / 读写静态字段 / 调静态方法；反射调用（`Class.forName(name, true, loader)`）；初始化子类时先初始化父类；启动类（`main` 所在的类）；以及 `MethodHandle` 的某些情况。

### 三个"看起来会触发其实不会"的例子

这三个在面试里高频出现，而且**都对应着真实的坑**。

```java
class Parent {
    static int value = 10;
    static { System.out.println("Parent init"); }
}
class Child extends Parent {
    static { System.out.println("Child init"); }
}
```

**反例一：通过子类引用父类的静态字段**

```java
System.out.println(Child.value);
// 输出：Parent init / 10
// Child init 不打印！
```

只有**直接定义这个字段的类**会被初始化，子类不会被初始化（但会被加载）。

**反例二：数组定义**

```java
Parent[] arr = new Parent[10];
// 什么都不打印
```

数组的类是 JVM 动态生成的 `[Lcom.example.Parent;`，不是 `Parent` 本身，不触发初始化。

**反例三（最容易踩）：编译期常量**

```java
class Const {
    static final String NAME = "hello";     // 字面量，编译期内联
    static final int RANDOM = new Random().nextInt();  // 运行时才能算，不内联
    static { System.out.println("Const init"); }
}
// 另一个类里：
System.out.println(Const.NAME);    // 不打印 Const init
System.out.println(Const.RANDOM);  // 打印 Const init
```

因为 `Const.NAME` 在编译期就被**内联进了调用方的常量池**，调用方的字节码里根本没有"引用 Const 这个类"这个动作。**这个坑的实际形态**：你改了 `Const.NAME` 的值、只重新部署 `Const.class`，调用方行为不变 —— 它还内嵌着旧字符串，必须把所有引用方一起重新编译。

> 【思考】类的卸载条件是什么？为什么元空间（Metaspace）会 OOM？
>
> 提示：想想哪些框架会"大量生成类"。

<details>
<summary><b>参考答案</b></summary>

**类的卸载条件（三个必须同时满足，极其苛刻）：**

1. 该类的**所有实例**都已被回收（堆里没有 `new` 出来的对象）
2. 加载该类的 **ClassLoader 已被回收**
3. 该类的 **`java.lang.Class` 对象没有任何地方引用**（没有反射持有、没有静态变量持有）

第 2 条是最难满足的 —— Bootstrap / Platform / Application 三个内置加载器**永远不会被回收**（它们是 GC Roots），所以**由它们加载的类，永远不会被卸载**。

**换句话说**：类的卸载只发生在一个场景 —— **自定义 ClassLoader 被回收**（Tomcat 卸载 WebApp、OSGi 卸载 bundle 时）。

**那元空间为什么会 OOM？**

元空间（Metaspace）存的是**类的元数据**：类名、方法签名、字段描述、字节码、常量池、注解、JIT 用的类型信息。它用的是**本地内存**（native memory），Java 8 之前这块叫永久代（PermGen），Java 8 起改成元空间。

**关键是：类不卸载，元数据就不释放。** 而下面这些技术会疯狂生成类：

| 技术 | 生成什么 | 规模 |
|---|---|---|
| CGLIB / ByteBuddy | `UserService$$EnhancerBySpringCGLIB$$a1b2c3` | 一个 Bean 一个 |
| JDK 动态代理 | `$Proxy0`、`$Proxy1`… | 一个代理一个 |
| 反射膨胀 | `GeneratedMethodAccessor1` 之类 | 按方法数量级 |
| Groovy / 规则引擎 | 每段脚本一个类 | **可能无限** |
| Lambda（**不生成类**） | `invokedynamic`，只链接一次 | 不占元空间 |

**最常见的元空间 OOM 来源**：Groovy 脚本或规则引擎在循环里 `eval()`，每次都生成一个新类。跑几天元空间就满了。

**顺带澄清一个错误认知**：lambda 不会在元空间里堆积类 —— 它用 `invokedynamic` 实现，同一个调用点只链接一次（题 4 详述）。真正会爆的是 `GroovyShell.evaluate(script)` 这种，因为它每次真的 `defineClass`。

**排查方法（一套 SOP）：**

```bash
# 1. 看元空间涨不涨（关注 M 列，持续上涨且 Full GC 后不降 → 类泄漏）
jstat -gcutil <pid> 1000

# 2. 按加载器统计类数量（最关键）
jcmd <pid> VM.classloader_stats

# 3. 打印类加载（一次性，生产慎用）
java -verbose:class -jar app.jar | grep -c "Loaded"
```

无侵入的话用 Arthas：`classloader -l` 看各加载器的类数量，`sc *EnhancerBySpringCGLIB*` 看 CGLIB 代理类。

如果你看到 `UserService$$EnhancerBySpringCGLIB$$1`、`$$2`、`$$3`……一路涨到几千，那就是 CGLIB 每次都新建代理类而没复用。

**修复与防护：**

```bash
-XX:MaxMetaspaceSize=512m    # 一定要设！默认不限制，会吃到物理内存耗尽
-XX:MetaspaceSize=256m       # 初始触发 GC 的阈值（注意这是"水位线"不是初始分配）
```

注意 `-XX:MetaspaceSize` 是**触发元空间 GC 的水位线**，不是初始大小。设太小会导致启动阶段频繁 Full GC（Spring Boot 启动要加载上万各类），建议 256m 起步。

**更深一层**：Go 编译期就固化了类型信息，**运行时不能新增类型**；Java 的 `defineClass` 是一等公民能力 —— 它让 Mockito 能 mock 一个没写过的类，代价是**你必须自己管理这块内存的生命周期**。**一句话记住**：堆泄漏是"对象没被回收"，元空间泄漏是"类没被卸载"。
</details>

---

## 04.4 字节码：JVM 的"汇编语言"

先看一段真实的 `javap -c -p -v` 输出。源码是这样的：

```java
public class Calc {
    public int add(int a, int b) {
        return a + b;
    }
}
```

```bash
javap -c -p -v Calc.class
```

```
public int add(int, int);
  descriptor: (II)I
  flags: (0x0001) ACC_PUBLIC
  Code:
    stack=2, locals=3, args_size=3
       0: iload_1
       1: iload_2
       2: iadd
       3: ireturn
    LineNumberTable:
      line 3: 0
```

逐行读：

| 内容 | 含义 |
|---|---|
| `descriptor: (II)I` | 方法描述符：两个 int 参数，返回 int |
| `stack=2` | 操作数栈最大深度 2 |
| `locals=3` | 局部变量表 3 个槽位：`this`(0)、`a`(1)、`b`(2) |
| `args_size=3` | **包括隐藏的 `this`**（实例方法第 0 号永远是 this） |
| `iload_1` / `iload_2` | 把局部变量表 1/2 号槽的 int 压入操作数栈 |
| `iadd` | 弹出栈顶两个 int 相加，结果压回栈 |
| `ireturn` | 弹出栈顶 int，返回 |

**注意 `args_size=3` 而源码只有两个参数** —— 这就是 01 章说的 `this` 是隐藏的第 0 号参数。Go 里方法接收者是显式写在签名上的，Java 把它藏进了局部变量表第 0 槽。

### 栈式指令集：三个部件怎么协作

每个 Java 方法在执行时有一个**栈帧（Stack Frame）**，包含三样东西：

| 部件 | 作用 | Go 里的对应 |
|---|---|---|
| 操作数栈（Operand Stack） | 指令的"工作台"，所有计算在这里做 | 无（直接用物理寄存器） |
| 局部变量表（Local Variable Table） | 存方法参数和局部变量，按索引访问 | 也是栈/寄存器分配 |
| 程序计数器（PC） | 当前执行到第几条指令 | rip 寄存器 |

再看一个带字段访问的（注意 `getfield` 也是栈式操作）：

```java
public int getAge(User u) { return u.age; }
```

```
   0: aload_1          # 把 u（局部变量1）压栈
   1: getfield      #7  // Field age:I     # 弹出 u，读 age 字段，结果压栈
   4: ireturn
```

**操作数栈是这套设计的核心**：指令本身**不带操作数**（零地址指令），操作数在栈上。`iadd` 不需要写"把 a 和 b 相加"，它默认就取栈顶两个。

> 【思考】为什么 JVM 选择基于栈，而不是基于寄存器？
>
> 提示：想想寄存器数量和 CPU 架构的关系，以及指令长度。

<details>
<summary><b>参考答案</b></summary>

**直接答案：三个好处（跨平台、指令紧凑、实现简单），一个代价（慢）。**

**好处一：跨平台。** x86-64 有 16 个通用寄存器，ARM64 有 31 个，老的 x86 只有 8 个 —— **如果字节码用寄存器，"寄存器编号"就没法统一**。栈是抽象的，任何架构上都能实现（用内存模拟，或者 JIT 时映射到物理寄存器）。

**好处二：指令紧凑。** `iadd` 是 1 字节零地址指令，不需要编码"从哪来到哪去"；寄存器式的 `add r1, r2, r3` 至少要编码三个寄存器编号，通常 2~4 字节。Java 早期的硬性目标之一是**小体积**（1995 年 Applet 要通过 56K 拨号下载），指令紧凑是刚需。

**好处三：编译器实现简单。** javac 只需要一个栈模拟表达式求值，不用做**寄存器分配**（一个 NP-困难的图着色问题），这让 Kotlin、Scala、Groovy 等第三方语言也能比较容易地编译到 JVM 字节码。

**代价：慢。**

```
计算 a + b：
  栈式：iload_1 / iload_2 / iadd / istore_3      4 条指令，4 次内存访问（栈是内存）
  寄存器式：add r3, r1, r2                       1 条指令，0 次内存访问
```

同样的计算，栈式需要**更多指令 + 更多内存访问**。这就是 Java 被说"慢"的最早的技术根因之一。

**那 Java 现在还慢吗？** 不慢 —— **JIT 会把栈式字节码编译成寄存器式的本地代码**。所以启动时（解释执行）慢，预热后（C2 编译）跟 C++ 同一量级；极端情况下 JIT 因为有运行时 profile，某些场景能做得比静态编译更好。

**代码锚点（对照 Go）：**

```go
// go tool compile -S main.go：Go 直接编译成本地代码，用的是真实寄存器
TEXT ·Add(SB)
    MOVQ a+0(FP), AX      // 参数从栈帧读进 AX
    ADDQ b+8(FP), AX      // 一次寄存器加法，没有栈
    RET
```

**更深一层**：这个取舍的本质是**"在哪一层付出复杂度"**。Go 把复杂度付在编译器（寄存器分配、多架构后端），换来产物简单、启动即巅峰；JVM 把复杂度付在运行时（解释器、JIT、去优化、分层编译），换来跨平台和"能根据真实运行数据优化"。三十年后云原生时代嫌弃 JVM 启动慢，于是有了 GraalVM Native Image 的提前编译（AOT）—— **技术史是个圈。**
</details>

### 方法调用的四种（五种）指令

| 指令 | 用在哪 | 绑定时机 | 能否多态 |
|---|---|---|---|
| `invokestatic` | static 方法 | 编译期 | 否 |
| `invokespecial` | 构造器 `<init>`、private 方法、`super.xxx()` | 编译期 | 否 |
| `invokevirtual` | 普通实例方法 | **运行时**（查虚方法表 vtable） | 是 |
| `invokeinterface` | 接口方法 | **运行时**（查接口方法表 itable） | 是 |
| `invokedynamic` | lambda、动态语言、record 的某些操作 | 运行时（第一次执行时链接） | 特殊 |

**关键区别在 `invokevirtual` 和 `invokeinterface`：**

`invokevirtual` 靠**虚方法表（vtable）**分派：每个类一张表，子类覆盖的方法放在**相同下标**，查表是 `O(1)` 数组索引，JIT 能做**内联缓存**。

`invokeinterface` 不行 —— 一个类可以实现多个接口，接口方法没有固定下标，只能按名字搜索，所以历史上比 `invokevirtual` 慢。现代 HotSpot 用 `itable` 缓存和 CHA 激进优化把这个差距基本抹平了，但"接口调用慢"的说法就源自这里。

**问题 5：** 为什么 Spring 的 `@Transactional` 在同类内部方法调用时会失效？因为代理对象是另一个类（CGLIB 子类或 JDK `$Proxy`），你从 `this` 调用走的是 `invokevirtual`/`invokespecial` 直接分发到目标方法，压根没经过代理对象（第 14 章展开）。

> 【思考】为什么 Java 的 private 方法不能重写（override）？
>
> 提示：从字节码指令的角度想。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为调用 private 方法用的是 `invokespecial`，编译期就绑定死了，不查虚方法表。**

看这段代码：

```java
class Parent {
    private void secret() { System.out.println("Parent"); }
    public void call() { secret(); }     // 编译成 invokespecial
}
class Child extends Parent {
    private void secret() { System.out.println("Child"); }  // 这不是重写，是新方法
}
// 调用 new Child().call() → 输出 "Parent"
```

`Parent.call()` 里的 `secret()` 编译成：

```
invokevirtual（或 invokespecial）  Parent.secret:()V
```

（注：JDK 11 起 `nestmate`（JEP 181）之后私有方法调用改为 `invokevirtual`，但**语义上仍是静态绑定、不参与多态分派** —— 因为 JVM 知道 private 方法不可能被重写。这是实现细节的变化，语义没变。）

**关键点**：`Child.secret()` 跟 `Parent.secret()` 是**两个完全无关的方法**。它们碰巧同名，就像你在一个类里写了两个重载方法一样。JVM 在分派时根本不会考虑"子类里有没有同名的 private 方法"。

对照一下：`Parent p = new Child(); p.hello();` 编译成 `invokevirtual`，运行时拿 `p` 的实际类型，查它的 vtable 找到 `hello` 再跳过去 —— 所以输出 "Child"。private 方法不走这条路。

**这个差异的实际危害（你会遇到）：**

```java
class Base {
    private void init() { doInit(); }
    protected void doInit() { System.out.println("base init"); }
}
class Sub extends Base {
    // 想"重写" init()，写了个同名的
    private void init() { System.out.println("sub init"); }
}
```

新手会以为 `Sub.init()` 覆盖了 `Base.init()`，实际上**什么都没发生**，编译器也不会报错（没有 `@Override`，编译器不知道你想重写）。

**这就是为什么 `@Override` 注解必须写** —— 它是唯一能让你在编译期发现"我以为我重写了其实没有"的手段。Go 里同类问题不存在，因为 Go 没有继承。

**更深一层**：private / final / static 方法都是**静态绑定**，JIT 可以无条件内联；虚方法调用要先做类型分析（CHA：当前 JVM 里只有一个实现时 JIT 就敢内联，假设失效则触发**去优化**回退）。**这套"乐观假设 + 去优化回退"是 HotSpot 能同时做到"支持多态"和"跑得快"的核心。** 顺带一个调优直觉：`final` 在 JIT 眼里是一张**内联许可证**。
</details>

### 异常处理：异常表

看这段代码编译后是什么样：

```java
public static int safeParse(String s) {
    try {
        return Integer.parseInt(s);
    } catch (NumberFormatException e) {
        return -1;
    }
}
```

```
  Code:
    stack=1, locals=2, args_size=1
       0: aload_0
       1: invokestatic  #2   // Method java/lang/Integer.parseInt:(Ljava/lang/String;)I
       4: ireturn
       5: astore_1           // catch 分支：把异常对象存到局部变量 1
       6: iconst_m1          // 压入 -1
       7: ireturn
    Exception table:
       from    to  target type
           0     4     5   Class java/lang/NumberFormatException
```

**重点在 Exception table** —— 它是方法的元数据，不在执行路径上：`from=0, to=4` 监控字节码 0 到 4 这段，`target=5` 表示这段抛 `NumberFormatException` 就跳到 5，`type` 是匹配的异常类型。

**这解释了一个关键的性能特性：**

| 阶段 | 成本 | 原因 |
|---|---|---|
| **进入 try 块** | **几乎为零** | 只是记录一个范围，不执行任何指令 |
| **抛出异常** | **很高**（微秒级） | 查异常表 → 匹配 → 构造异常对象 → `fillInStackTrace()` 遍历整个栈 |
| try 块正常执行完 | 零额外成本 | 没有"退出 try"的指令 |

**Go 对照**：`if err != nil` 是纯分支跳转（一次 `cmp` + `jz`），比 Java 抛异常便宜两三个数量级。**所以 Java 有一条铁律**：不要用异常做正常的流程控制 —— 00 章讲过，这里你从字节码层面看到了原因。

---

## 04.5 运行时数据区：JVM 的内存地图

```
┌─────────────────────── 线程共享 ───────────────────────┐
│  堆 (Heap)        ← 对象实例，GC 主要战场             │
│  元空间 (Metaspace) ← 类元数据，本地内存               │
│  代码缓存 (CodeCache) ← JIT 编译后的本地代码           │
│  直接内存 (Direct Memory) ← Netty/ByteBuffer           │
└────────────────────────────────────────────────────────┘

┌─────────────────────── 线程私有 ───────────────────────┐
│  PC 寄存器      ← 当前执行到第几条字节码                │
│  虚拟机栈       ← 栈帧（局部变量表/操作数栈/返回地址）  │
│  本地方法栈     ← JNI 调用用                            │
└────────────────────────────────────────────────────────┘
```

### 方法区的演进史（这段必须知道，因为老资料里全是 PermGen）

| 版本 | 叫什么 | 在哪 | 控制参数 | 问题 |
|---|---|---|---|---|
| JDK 6 | 永久代 PermGen | **堆里** | `-XX:PermSize` / `-XX:MaxPermSize` | 大小难估，频繁 OOM |
| JDK 7 | 永久代（部分搬走） | 堆里 | 同上 | **字符串常量池移到堆**，符号引用移到 native |
| **JDK 8** | **元空间 Metaspace** | **本地内存** | `-XX:MetaspaceSize` / `-XX:MaxMetaspaceSize` | 默认无上限，会吃光物理内存 |

**这是 JDK 8 的分水岭。** 老项目里的 `-XX:MaxPermSize=256m` 在 JDK 8 上会得到警告：`ignoring option MaxPermSize=256m; support was removed in 8.0`。

**为什么要改？** ① 永久代大小难调优：一个应用要加载多少类，写配置的人猜不准；② 字符串常量池在永久代导致 GC 效率低（永久代的 GC 跟老年代绑定，回收条件苛刻），JDK 7 挪到堆里后字符串才能正常回收 —— 这也是 `String.intern()` 在 JDK 7 前后行为差异的根源；③ HotSpot 与 JRockit 合并：JRockit 本来就没有永久代，合并代码库时统一到了它的 Metaspace 方案。

**字符串常量池在哪？** JDK 7 起在**堆**里；运行时常量池在元空间（JDK 8+）。这两个不是一回事，别混。

### 直接内存：堆转储里看不见的内存

**为什么 Netty 用直接内存？** 网络 IO 时堆内 `byte[]` 要发给内核，JVM 得先**拷贝**到一块 native 内存（因为 GC 可能移动对象，内核拿着指针会失效），再 `write()`；用直接内存能**省掉这一次拷贝**（零拷贝）。

**为什么它导致的 OOM 在堆转储里看不见？**

因为 `ByteBuffer.allocateDirect` 分配的 `DirectByteBuffer` **对象本身在堆里，但只有几十字节** —— 它只是个壳，真正的 1MB 在堆外。所以：

- `jmap -histo` 里 `java.nio.DirectByteBuffer` 的"实例数"看着正常
- MAT 里的 Retained Heap 显示很小
- 但进程 RSS 一直在涨

错误长这样：

```
java.lang.OutOfMemoryError: Direct buffer memory
```

**控制参数：**

```bash
-XX:MaxDirectMemorySize=1g    # 默认值约等于 -Xmx（不设就跟堆一样大）
```

`DirectByteBuffer` 的回收靠**虚引用 + Cleaner**：对象被 GC 回收时触发 Cleaner 释放堆外内存，所以释放**滞后于 GC**，分配速度超过 GC 速度照样 OOM。**Go 对照**：Go 的 cgo 分配的 C 内存也是堆外，`pprof` 的 heap profile 也看不到，这一点两者一样坑。

> 【思考】`-Xmx` 设了 4G，为什么这个 Java 进程实际占用了 6G 内存？
>
> 这是运维最常问的问题，也是容器 OOMKilled 的第一大成因。把它算清楚。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 `-Xmx` 只管堆，而 JVM 进程的内存远不止堆。**

**完整构成（这是标准答案，背下来）：**

| 区域 | 典型大小 | 谁控制 | 说明 |
|---|---|---|---|
| **Java 堆** | 你设的 `-Xmx` | `-Xms` / `-Xmx` | 对象实例 |
| **元空间** | 100~500MB | `-XX:MaxMetaspaceSize` | 类元数据（本地内存） |
| **压缩类空间 CCS** | 最大 1G | `-XX:CompressedClassSpaceSize` | Klass 指针信息 |
| **CodeCache** | 上限 240MB | `-XX:ReservedCodeCacheSize` | JIT 编译后的本地代码 |
| **线程栈** | `线程数 × 1MB` | `-Xss1m` | **500 线程就是 500MB，最容易算漏** |
| **直接内存** | 默认 = `-Xmx` | `-XX:MaxDirectMemorySize` | Netty、NIO |
| **GC 数据结构** | 堆的百分之几 | 无 | G1 的 Remembered Set、Card Table |
| **glibc malloc arena** | 可能几百 MB | `MALLOC_ARENA_MAX` | **Linux 经典坑** |

**回到题目，典型 Spring Boot 应用（400 线程）：**

```
堆                    4096 MB   ← -Xmx 就是它
线程栈（400 × 1MB）     400 MB   ← 容易被忽略
直接内存（Netty）       512 MB   ← 容易被忽略
G1 的 Remembered Set   180 MB   ← 容易被忽略
元空间 + CCS            260 MB
CodeCache              120 MB
JVM 自身 + glibc        350 MB
─────────────────────────────
                      5918 MB   ≈ 6G
```

**算出来正好 6G。**

**Linux 特有的 glibc arena 坑**：glibc 的 `malloc` 在多核机器上为每个线程创建独立 arena（上限 `8 × CPU核数`），用过的内存不马上还给系统，导致 **RSS 虚高但堆没涨**。32 核机器上堆只用了 1G，RSS 却能涨到 6G 且降不下来。

```bash
pmap -x <pid> | tail -5          # 有没有大量 64MB 的匿名块
export MALLOC_ARENA_MAX=4        # 修复
LD_PRELOAD=/usr/lib/libjemalloc.so java ...   # 或者换 malloc 实现
```

**这一招救过很多次火**：32 核容器里的服务 RSS 一路涨到 OOMKilled，堆一点问题没有，加一行 `MALLOC_ARENA_MAX=4` 后 RSS 稳定在 2G。

**正确的排查工具：**

```bash
-XX:NativeMemoryTracking=summary    # 启动时加，约 5% 开销，建议只在排查期开
jcmd <pid> VM.native_memory summary
```

输出里直接能看到 `thread #417`、`stack: committed=427780KB` —— 417 个线程占了 418MB 栈，一眼看穿。

**容器的特殊注意事项**：JDK 8u191 之前 JVM 完全不知道自己在容器里，会按宿主机 CPU/内存算默认值；现代写法（JDK 11+）用 `-XX:MaxRAMPercentage=75.0` 让堆占容器限额的 75%，别写死 `-Xmx`。

**更深一层**：很少有人问 Go 的 RSS 为什么比堆大，因为 Go 没有 Class 元数据（编译期固化）、没有 CodeCache（没有 JIT）、通常也不用直接内存。**这是同一个根本取舍的又一次体现**：JVM 用"运行时做更多事"换来跨平台和动态性，账单就是**内存复杂度**。

**还有第三层，NMT 查不到**：JNI / 第三方 native 库（zstd-jni、OpenCV、AI 推理库）自己调 `malloc`，只能用 eBPF 跟踪（`/usr/share/bcc/tools/memleak -p <pid> 10`）。Go 服务通常不用 cgo，这一层几乎不存在；Java 用 JNI 的概率高得多。

**行动建议**：上线任何 Java 服务前，用 `-XX:NativeMemoryTracking=summary` 跑一遍压测，把真实 RSS 测出来再给容器设 limit。**容器的 memory limit 至少要是 `-Xmx` 的 1.5 倍**，否则第一次大促就会被 OOMKilled。

</details>

### 一个真实的排查案例：容器 OOMKilled，但堆很干净

**现象**：某订单服务部署在 K8s 上，limit 6G，`-Xmx4g`。每隔 30 小时左右被 OOMKilled 一次。GC 日志显示堆使用率一直在 40% 左右，从没接近 4G。

**排查过程**：

```bash
jstat -gcutil <pid> 1000
#    S0     S1     E      O      M     CCS    YGC     YGCT    FGC    FGCT     GCT
#    0.00  76.54  43.21  38.92  94.87  91.23   8421   58.341     3    0.812   59.153
#    堆才 38%，M（元空间）94.87% 有点高但不是主要矛盾

ps -o rss= -p <pid>     # 5832116 KB ≈ 5.6G，且持续上涨

# 用 NMT 定位（启动时已加 -XX:NativeMemoryTracking=summary）
jcmd <pid> VM.native_memory summary | grep -A5 "Direct\|Other"
# -                    Other (reserved= 2148271KB, committed=2148271KB)
#   (malloc=2148271KB #8421)      ← 2.1G 在 "Other" 里，堆外！
```

**根因**：业务代码里有个导出 Excel 的功能，用了 `ByteBuffer.allocateDirect()` 缓冲但**没有释放**，也没走池化。每导出一次泄漏一块。堆内 `DirectByteBuffer` 壳对象只有几十字节，被 GC 回收时 Cleaner 应该释放堆外内存 —— 但这些 buffer 被一个静态的 `List` 引用着，**壳对象一直活着，Cleaner 永远不会触发**。

**修复**：改成池化。

```java
// 用 Netty 的池化分配器（推荐）
ByteBuf buf = PooledByteBufAllocator.DEFAULT.directBuffer(8 * 1024 * 1024);
try { /* ... */ } finally { buf.release(); }   // 归还到池子，不还给 OS，但总量封顶
```

**教训**：

1. **`-XX:MaxDirectMemorySize` 一定要显式设**，别让它跟着 `-Xmx` 走
2. **堆内没问题 ≠ 内存没问题**。RSS 涨而堆不涨，第一反应就应该是堆外
3. **容器 limit 至少要是 `-Xmx` 的 1.5 倍**，并配 `-XX:+ExitOnOutOfMemoryError` 让 JVM 主动退出，而不是等 K8s 杀（这样能留下堆转储）

---

## 04.6 对象的内存布局

一个 Java 对象在堆里长这样：

```
┌────────────────────────────────┐
│ 对象头 (Object Header)          │
│  ├─ Mark Word       8 字节     │  哈希码、GC 分代年龄、锁状态标志、偏向线程ID
│  └─ Klass Pointer   4 字节★    │  指向类的元数据（压缩后 4 字节，否则 8 字节）
├────────────────────────────────┤
│ 实例数据 (Instance Data)        │  字段内容，按类型对齐排列
├────────────────────────────────┤
│ 对齐填充 (Padding)              │  补到 8 字节的倍数
└────────────────────────────────┘
```

★ Klass Pointer 的大小取决于是否开启指针压缩。

### 指针压缩（Compressed Oops）

64 位 JVM 上一个引用本来是 8 字节，意味着**缓存里能放的引用少一半**。`compressed oops` 的做法是：**引用里存的不是字节地址，是"第几个 8 字节块"** —— 对象默认按 8 字节对齐，地址末 3 位永远是 0 可以省掉，于是 32 位能表示 `2^32 × 8 = 32GB` 的地址空间。

```bash
-XX:+UseCompressedOops             # 默认开启（堆 < 32GB 时）
-XX:+UseCompressedClassPointers    # 默认开启，压缩 Klass 指针
-XX:ObjectAlignmentInBytes=8       # 默认 8。改成 16 可以把上限提到 64GB，但浪费内存
```

**这就是"32G 陷阱"**：堆超过约 32GB 时指针压缩自动失效，引用从 4 字节变回 8 字节，对象平均变大 15%~20% —— **你把堆从 30G 加到 34G，可用内存反而可能变少**。所以：**堆要么设 30G 以下，要么一步跨到 48G 以上，别在 32~40G 之间晃悠。**

### 几个具体数字（用 JOL 验证）

JOL（Java Object Layout，OpenJDK 官方工具）：

```java
import org.openjdk.jol.info.ClassLayout;
System.out.println(ClassLayout.parseInstance(new Object()).toPrintable());
System.out.println(ClassLayout.parseInstance(Integer.valueOf(1)).toPrintable());
System.out.println(ClassLayout.parseInstance(Long.valueOf(1L)).toPrintable());
```

| 对象 | Mark Word | Klass Ptr | 实例数据 | 填充 | **总计** |
|---|---|---|---|---|---|
| `new Object()` | 8 | 4 | 0 | 4 | **16 字节** |
| `Integer` | 8 | 4 | 4 (int) | 0 | **16 字节** |
| `Long` | 8 | 4 | 8 (long) | 4 | **24 字节** |

**注意 `Integer` 是 16 字节** —— int 值本身只要 4 字节，包装成对象翻了 4 倍。

> 【思考】为什么 Java 对象比 Go 结构体占更多内存？
>
> 对比一下：一个存 100 万个 int64 的集合，Go 和 Java 各占多少？

<details>
<summary><b>参考答案</b></summary>

**直接答案：三个原因 —— 对象头、引用间接、包装类。**

**算一笔账：存 100 万个 int64。**

```go
// Go：紧凑数组，零额外开销
ids := make([]int64, 1_000_000)
// 内存 = 1,000,000 × 8 = 8 MB，就这么多
```

```java
// Java：List<Long>，每个元素是一个独立对象
//   Long 对象：1,000,000 × 24 字节            = 24 MB
//   ArrayList 内部的 Object[]（压缩指针）      =  4 MB
//                                        合计 ≈ 28 MB
```

**同样的数据，28MB vs 8MB，差 3.5 倍。** 而且一百万个独立对象意味着一百万次分配、GC 要遍历一百万个对象，且**散落在堆里、缓存局部性极差** —— Go 的 `[]int64` 是连续内存，CPU 预取器完美工作，遍历速度能快 5~10 倍。

**原因一：对象头。** 每个 Java 对象至少 12 字节头（Mark Word 8 + Klass 4），对齐后最少 16 字节。Go 的 struct 没有对象头。

```go
type Point struct{ X, Y int64 }   // unsafe.Sizeof = 16 字节
```

```java
class Point { long x, y; }        // 8+4+8+8 = 28 → 对齐到 32 字节
```

**同样是 (int64, int64)，Go 16 字节，Java 32 字节。**

**原因二：引用间接。** Go 的 `[]Point` 是连续内存；Java 的 `Point[]` 是**装着 1000 个引用的数组**，每个引用指向堆里某个位置的 Point，GC 移动后就散了。后果不只是内存，更是速度：遍历 `Point[]` 要 1000 次指针解引用、每次可能 cache miss（约 100ns）；Go 是顺序扫描（约 1ns）。

**原因三：包装类。** Java 泛型不支持原始类型（类型擦除的代价，第 03 章讲过）。`List<long>` 不能写，只能 `List<Long>`。

**Java 的应对方案：**

```java
long[] ids = new long[1_000_000];        // 方案一：原始类型数组，8 MB，跟 Go 一样紧凑
LongArrayList ids = new LongArrayList(); // 方案二：fastutil / Eclipse Collections，内部是 long[]
// 方案三：等 Valhalla 的 Value Types（JEP 401/402，尚未正式发布）
```

**Go 程序员容易踩的坑 #2（反向的）**：Java 8 的**逃逸分析 + 标量替换**能优化掉一部分：

```java
public long distance() {
    Point p = new Point(3, 4);   // 没逃出方法 → 可能被拆成两个 long 局部变量
    return p.x * p.x + p.y * p.y;
}
```

**但这个优化很脆弱** —— 对象被存进数组、被返回、被传给没内联的方法，就失效了。不要指望它。

**更深一层**：根源是**"一切皆对象" vs "值类型优先"**。C# 早就补上了值类型 `struct`，Go 天生就有，Java 到今天还在等 Valhalla —— 这是 Java 语言设计上**为数不多的、公认的历史包袱**。**实践建议**：数量大（>10 万）且类型固定的集合，先问一句"能不能用原始类型数组或 fastutil"。

</details>

---

## 04.7 对象创建与死亡

### 创建流程

```
1. 类加载检查    遇到 new，先看这个类有没有被加载/解析/初始化
2. 分配内存      从堆里划一块（指针碰撞 或 空闲列表）
3. 零值初始化    字段置 0/false/null（这就是"Java 字段有默认值"的原因）
4. 设置对象头    Mark Word、Klass 指针、GC 年龄设为 0
5. 执行 <init>   你写的构造器
```

第 2 步有两种方式，取决于 GC 器有没有**整理（compact）**能力：

| 方式 | 用在哪 | 怎么做 |
|---|---|---|
| **指针碰撞** | Serial、ParNew、G1 | 堆规整，分配就是把指针往空闲方向挪，一次加法 |
| **空闲列表** | CMS、Shenandoah | 维护一张表记录空块，分配时找一块够大的 |

**并发问题：TLAB。** 多线程同时 `new` 都要动分配指针，加锁就串行了。HotSpot 的答案是 **TLAB（Thread Local Allocation Buffer）**：每个线程在 Eden 区预申请一小块私有空间，线程内分配就是自己 TLAB 里的指针碰撞，**完全无锁**，用完才去申请新的（这时才需要同步）。相关参数 `-XX:+UseTLAB`（默认开）、`-XX:TLABSize`。

**Go 对照**：这就是 Go 的 **mcache / per-P span cache** 的同一个思路。**两个 runtime 在这里收敛到了同一个设计 —— 因为这个问题的正确答案就只有这么一个。**

### 死亡判定：为什么不用引用计数

**引用计数法**：每个对象记一个数，有人引用就 +1，断开就 -1，为 0 就死。优点是简单、即时（计数归零立刻回收，无停顿），但**致命缺点是循环引用**：

```java
class Node { Node parent; Node child; }
a.child = b; b.parent = a;    // 互相引用
a = null; b = null;
// 这两个对象已经没人能访问了，但计数都是 1，永远回收不掉
```

所以 Java 和 Go **都用可达性分析（Reachability Analysis）**：从一组叫 **GC Roots** 的根出发，沿着引用链走，走不到的就是垃圾。

**GC Roots 包括：**

- 虚拟机栈（栈帧的局部变量表）里的引用
- 方法区里 **static 字段**引用的对象
- 方法区里**常量**引用的对象（如字符串常量池）
- **JNI**（native 方法）持有的引用
- Java 虚拟机内部引用（Class 对象、异常对象、系统 ClassLoader）
- 被同步锁（`synchronized`）持有的对象

**Go 的 GC Roots**：全局变量、每个 goroutine 的栈、runtime 内部结构。Go 用**三色标记 + 混合写屏障**，Java 分代收集器用三色标记 + SATB，ZGC 用**染色指针**。**关键差别**：Go 的 GC 是**非分代、非移动**的；Java 主流 GC 是**分代 + 移动**。

### 四种引用类型

| 类型 | 类 | 回收时机 | 典型用途 |
|---|---|---|---|
| **强引用** | 普通赋值 `Object o = new Object()` | 永不回收（只要可达） | 99% 的情况 |
| **软引用** | `SoftReference<T>` | **内存不足时**（OOM 之前）回收 | **缓存**（内存够就留着，不够就扔） |
| **弱引用** | `WeakReference<T>` | **下一次 GC** 就回收 | `ThreadLocal` 的 key、WeakHashMap、规范化映射 |
| **虚引用** | `PhantomReference<T>` | 随时（拿不到对象本身） | **堆外内存回收的回调**（Netty、DirectByteBuffer 的 Cleaner） |

软引用做缓存：`Map<String, SoftReference<BufferedImage>>`，内存够就命中，OOM 前自动清掉；存活时间受 `-XX:SoftRefLRUPolicyMSPerMB` 影响（默认 1000，即"堆里每有 1MB 空闲，软引用就多活 1 秒"）。

虚引用拿不到对象（`ref.get()` 永远返回 null，这是设计如此），唯一作用是：**对象被回收时 JVM 把它塞进你关联的 `ReferenceQueue`**，你收到通知后释放堆外资源 —— 这就是 `DirectByteBuffer` 的 Cleaner 机制。

> 【思考】为什么说 `ThreadLocal` 会内存泄漏？
>
> 提示：想想线程池里的线程有什么特点。

<details>
<summary><b>参考答案</b></summary>

**直接答案：ThreadLocalMap 的 key 是弱引用，value 是强引用。key 被回收后留下 `null` key 的 entry，value 还强引用着对象，而线程池里的线程永不结束 —— 于是 value 永远不释放。**

**先看清数据结构：**

```
Thread
  └── ThreadLocalMap threadLocals
        └── Entry extends WeakReference<ThreadLocal<?>>
              ├── key   → 弱引用指向 ThreadLocal 对象
              └── value → 强引用指向你存的值
```

**泄漏的四步：**

1. `UserContext.set(bigUser)` → entry = (弱引用 HOLDER → 强引用 bigUser)
2. 方法结束，局部变量消失；但线程活着，ThreadLocalMap 还挂着 entry
3. HOLDER 这个 ThreadLocal 对象本身不再被引用（非 static、或类被卸载）→ GC 后 key 被回收 → entry 变成 `(null → 强引用 bigUser)`
4. 线程不结束 → **这个 value 永远不释放**

**为什么线程池是放大器？** HTTP 服务器的 200 个线程**生命周期跟进程一样长**。每个处理过请求的线程都可能在自己的 Map 里留下一个脏 entry。跑一个月就是几百兆甚至几个 G。

**而在 Go 里？** 没有对应问题。你想传上下文就用 `context.Context` 显式当参数传，goroutine 结束栈上变量自动消失。**Go 用"显式传参"替代了 Java 的"线程级隐式状态"。**

**ThreadLocalMap 的自愈机制（以及为什么不够）：**

JDK 在 `set()`/`get()`/`remove()` 里都调用了 `expungeStaleEntry()` 清理 `null` key 的 entry。**但这是惰性的** —— 只有你**再次访问这个 Map** 时才触发。线程处理完请求后再也不碰这个 ThreadLocal，脏 entry 就一直在。

**正确用法（必须背下来）：**

```java
// 错误：设了不清理
UserContext.set(currentUser);
chain.doFilter(request, response);

// 正确：finally 里清理，一定执行
try {
    UserContext.set(currentUser);
    chain.doFilter(request, response);
} finally {
    UserContext.remove();   // 关键！
}
```

**修复方案（三选一）：**

1. **规范层面**（根本解）：`finally { threadLocal.remove(); }` 写进团队规范，用 SonarQube 卡住
2. **框架层面**：优先用 Spring 的 `RequestContextHolder`（请求结束自动 `reset()`）
3. **替代方案**：Java 21+ 的**虚拟线程 + ScopedValue**（JEP 506，预览特性）—— 不可变、有作用域，用完自动失效，**物理上不可能泄漏**。这才是 Go 的 `context.Context` 在 Java 里的对应物

```java
private static final ScopedValue<User> CURRENT_USER = ScopedValue.newInstance();
ScopedValue.where(CURRENT_USER, user).run(() -> handleRequest());
```

**更深一层**：ThreadLocal 泄漏不是一个 bug，是**"线程级隐式状态"这个设计的必然代价**。

这个设计的诱惑在于：它让你不用改方法签名就能往下传参数。想在日志里自动打 traceId？`ThreadLocal` 一塞，所有地方都能拿到。这跟 Go 社区强烈反对的"不要往 context 里塞非请求级数据"是同一个问题的两面。

**代价是什么？** 数据生命周期脱离控制（谁清理？什么时候清理？）、异步/线程池场景下传递会断（ `@Async`、CompletableFuture 里拿不到，要靠 `TransmittableThreadLocal`）、泄漏是隐式累积的且难排查。

Go 选了显式传 `ctx`，代价是**每个函数签名都要多一个参数**（Go 程序员天天抱怨这个），换来的是生命周期清晰、无泄漏可能。

**这一次，我站 Go 这边。** ThreadLocal 是 Java 生态里少数几个我认为"设计上就该被废弃"的东西 —— 而 ScopedValue 的出现，说明 JDK 团队也是这么想的。

</details>

---

## 04.8 内存模型（JMM）速览

先看一个反直觉的现象：

```java
public class VisibilityDemo {
    private static boolean running = true;   // 注意：没有 volatile

    public static void main(String[] args) throws Exception {
        new Thread(() -> {
            System.out.println("worker start");
            while (running) { /* 空转 */ }
            System.out.println("worker stop");
        }).start();

        Thread.sleep(1000);
        running = false;
        System.out.println("main set running = false");
    }
}
```

**问题 6：** "worker stop" 会被打印吗？

大概率**不会**，程序会永远卡住。因为 JIT 发现 `running` 在这个循环里从没被改过，会把它**提升成寄存器变量**，或者一直从本地缓存读，主线程改的值它永远看不到。这就是**可见性**问题。

### 为什么需要 JMM

硬件上 CPU 有 L1/L2/L3 多级缓存（L1 每核私有），还有**指令重排序**（编译器重排 + CPU 乱序执行）。所以"代码顺序" ≠ "执行顺序" ≠ "别的线程看到的顺序"。JMM 的作用就是定义：在什么条件下，一个线程的写对另一个线程可见。

### happens-before 规则

JMM 的核心就一句话：**如果操作 A happens-before 操作 B，那么 A 的结果对 B 可见。**

八条规则，挑重点的四条：

| 规则 | 内容 |
|---|---|
| **程序顺序规则** | 同一个线程内，前面的操作 happens-before 后面的操作 |
| **volatile 规则** | 对一个 volatile 变量的**写**，happens-before 后续对这个变量的**读** |
| **锁规则** | 解锁（`unlock`）happens-before 后续的加锁（`lock`） |
| **线程启动/终止** | `Thread.start()` happens-before 线程内所有操作；线程内所有操作 happens-before 线程终止的检测（`join()` 返回） |
| **传递性** | A hb B，B hb C，则 A hb C |

### volatile 的两个语义

```java
private volatile boolean flag = false;
private int value = 0;

// 线程 A
value = 42;        // 1
flag = true;       // 2  volatile 写

// 线程 B
if (flag) {        // 3  volatile 读
    System.out.println(value);   // 4
}
```

1. **可见性**：线程 B 看到 `flag == true` 时，一定能看到 `value == 42`。因为 volatile 写会插入 `StoreStore` + `StoreLoad` 内存屏障，把之前的所有写刷到主存；volatile 读会插入 `LoadLoad` + `LoadStore` 屏障，让本地缓存失效。
2. **禁止重排序**：`1` 不会被重排到 `2` 之后（volatile 写前的操作不能跑到写之后）。

**问题 7：** 那 `volatile` 能替代锁吗？不能 —— 见下一个思考题。

### Go ↔ Java 内存模型对照

| 维度 | Go | Java |
|---|---|---|
| 模型核心 | happens-before（Go Memory Model 文档） | happens-before（JMM，JSR-133） |
| 可见性手段 | channel 收发、`sync.Mutex`、`sync/atomic` | `volatile`、`synchronized`、`Lock`、`Atomic*` |
| 原子操作语义 | **`sync/atomic` 是顺序一致性（sequential consistency）** | `volatile` 只保证 happens-before；`VarHandle` 提供 opaque/release/acquire 可选语义 |
| 无锁编程 | `atomic.Value`、`atomic.Pointer[T]`（1.19+） | `AtomicReference`、`VarHandle`、`StampedLock` |
| 禁止重排 | `atomic` 操作 / channel | 内存屏障（`Unsafe.loadFence` 等，内部用） |
| 数据竞争检测 | `go test -race`（生产可用，开销 ~10x） | 无官方等价物（JFR 只能事后统计，靠 code review） |

**这里有一个重要的差异要记住**：Go 的 `sync/atomic` 承诺**顺序一致性** —— 所有 goroutine 看到所有 atomic 操作的**同一个全局顺序**。Java 的 `volatile` 只承诺 happens-before（不保证全局顺序，历史上它源自顺序一致性的弱化）。

但实际上，**Go 的 atomic 底层编译成的是跟 Java 的 volatile 差不多的 CPU 指令**（x86 上都是 `lock` 前缀指令或 `mfence`）。所以理论差异存在，实践上你在 x86 上很难观察到区别 —— 但在 ARM 上会（Go 会在 ARM 上插入 `dmb` 指令保证 SC）。

**`AtomicInteger` 靠什么？** 是"volatile 字段 + CAS 指令"两件套：

```java
public class AtomicInteger extends Number {
    private volatile int value;    // ← 关键：volatile 保证可见性

    public final int incrementAndGet() {
        return U.getAndAddInt(this, VALUE, 1) + 1;
        // Unsafe.getAndAddInt 内部是一个 CAS 循环：
        //   do { v = getIntVolatile(obj, offset); }
        //   while (!compareAndSwapInt(obj, offset, v, v + delta));
        // CAS 在 x86 上编译成 lock cmpxchg，天然带 full barrier
    }
}
```

**所以是"volatile 字段 + CAS 指令"两件套**：volatile 管可见性，CAS 管原子性。

> 【思考】`volatile int i; i++;` 线程安全吗？
>
> 如果不安全，怎么改？为什么 `AtomicLong` 在高并发下会被 `LongAdder` 吊打？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不安全。`i++` 是"读-改-写"三步，volatile 只保证每一步的可见性，不保证三步合起来的原子性。**

**看字节码就明白了：**

```java
volatile int i = 0;
i++;
```

```
   2: getfield      #2   // Field i:I        ← 第 1 步：读
   6: iadd                                   ← 第 2 步：在操作数栈上改，不是在原变量上
   7: putfield      #2   // Field i:I        ← 第 3 步：写
```

`getfield` 和 `putfield` 之间**有间隙**。两个线程可能：A 读到 0 → B 读到 0 → A 写回 1 → B 写回 1，**丢了一次加法**。

**修复方案（三种，各有适用场景）：**

```java
// 方案一：synchronized（最朴素，低并发够用）
public synchronized void inc() { i++; }

// 方案二：AtomicInteger（无锁，中等并发）
private final AtomicInteger i = new AtomicInteger();

// 方案三：LongAdder（高并发计数的标准答案）
private final LongAdder counter = new LongAdder();
public void inc() { counter.increment(); }
public long get() { return counter.sum(); }   // 注意：sum() 不是原子快照
```

**为什么 LongAdder 在高并发下比 AtomicLong 快？**

`AtomicLong` 的本质是所有线程抢**同一个** `volatile long` 的 CAS。100 个线程同时自增：只有 1 个成功，99 个失败重试；更糟的是每次 CAS 成功都会让**其他所有 CPU 核上对应的缓存行失效**（cache line ping-pong）。结果是线程越多，单个操作越慢，吞吐量甚至下降。

`LongAdder` 的解法是**分段累加**（跟你写 Go 时的 shard 计数器一模一样）：

```
LongAdder
  ├── base: long                    ← 无竞争时直接加到这
  └── Cell[] cells                  ← 有竞争时，每个线程映射到某个 Cell
        ├── Cell@0  (padded)        ← @Contended：一个 Cell 独占一个缓存行
        └── Cell@1  (padded)        ← 竞争激烈时数组翻倍扩容
```

**真实数据（8 核，32 线程，各累加 1 亿次）：`AtomicLong` 约 12 秒，`LongAdder` 约 0.8 秒，差 15 倍。**

**但 LongAdder 不是万能的**：`sum()` 在并发写入时得到的是"某个时刻的大概值"。**QPS 统计用 LongAdder（不需要精确）；生成全局递增 ID 用 AtomicLong（必须精确）。**

**Go 对照：**

```go
type ShardCounter struct {
    counters []atomic.Int64   // 每个 CPU 一个，减少争用
}
func (c *ShardCounter) Inc() { c.counters[getCPUID()].Add(1) }
```

Go 的 `atomic.Int64` 在 AMD64 上也有同样的缓存行争用问题，所以 Go 高性能代码里也能看到分片计数。**这是所有多核架构的共性，不是 Java 独有的问题。**

**更深一层**：`LongAdder` 体现了 Java 8 的一次思想转变 —— **从"保证强一致性"转向"允许牺牲精确性换吞吐"**（`ConcurrentHashMap.size()` 返回估计值、`StampedLock` 的乐观读也是同一思路）。而 Go 从第一天起就是实用主义 —— 这大概也是你读 Go 标准库觉得"这很合理"、读老 Java 代码觉得"太教条"的原因。

</details>

**JMM 的完整内容（volatile 的内存屏障实现、synchronized 的锁升级、AQS、伪共享）在第 10 章展开。** 这一章你只需要建立起一个直觉：**多线程下，你看到的顺序不一定是你写的顺序，需要显式的同步语义来建立 happens-before。**

---

## 04.9 实战：读懂 JVM 给你的输出

这一节是本章的落点。每个命令给真实输出 + 逐行解读。

### 找进程：`jps -l`

```bash
$ jps -l
12345 com.example.order.OrderApplication
12888 org.jetbrains.idea.maven.server.RemoteMavenServer36
```

`-l` 显示主类全限定名（不加只显示类名，分不清是哪个服务）。

**容器里的坑**：`jps` 靠读 `/tmp/hsperfdata_<user>/` 发现进程，容器的 `/tmp` 被清空它就什么都看不到，这时用 `ps -ef | grep java`。

### 看线程栈：`jstack`

| 字段 | 含义 | 怎么用 |
|---|---|---|
| `"http-nio-8080-exec-1"` | 线程名 | **给线程池起好名字在这一刻价值连城** |
| `daemon` | 守护线程 | 不阻止 JVM 退出 |
| `prio=5` / `os_prio=0` | Java / OS 优先级 | 基本没用 |
| `tid=0x00007f8c...` | JVM 内线程对象的内存地址 | **不是 OS 线程 ID**，别搞混 |
| `nid=0x1234` | **OS 线程 ID（十六进制）** | **最有用**，见下 |
| `waiting on condition` | 等待原因提示 | 配合 Thread.State 看 |
| `Locked ownable synchronizers` | AQS 锁（ReentrantLock）持有信息 | **只有 `jstack -l` 才显示** |

**`nid` 的用法 —— 跟 `top -H` 对应：**

```bash
top -H -p 12345          # 1. 找出 CPU 最高的线程（比如 4676，十进制）
printf "%x\n" 4676       # 2. 转十六进制 → 1234（jstack 里是十六进制）
jstack 12345 | grep -A 20 "nid=0x1234"    # 3. 在栈里搜
```

**这一招是"Java 服务 CPU 飙高"的标准解法。**

### 六种线程状态

| 状态 | 含义 | 典型栈 |
|---|---|---|
| `RUNNABLE` | **运行中 或 就绪 或 阻塞在 native IO** | `socketRead0(Native Method)` ← 注意！ |
| `BLOCKED` | 等 `synchronized` 的 monitor 锁 | 有 `waiting to lock <0x...>` |
| `WAITING` | 无限期等待 | `Object.wait()`、`park()`、`join()` |
| `TIMED_WAITING` | 带超时等待 | `sleep()`、`wait(timeout)`、`parkNanos()` |

**这里有个巨坑**：**`RUNNABLE` 不代表在跑，它还包括"阻塞在 OS IO 上"。**

```
"http-nio-8080-exec-5" nid=0x2a3b runnable
   java.lang.Thread.State: RUNNABLE
        at java.net.SocketInputStream.socketRead0(Native Method)   ← 卡在网络读
        at com.mysql.cj.protocol.a.NativeProtocol.readMessage(...)
```

这个线程**卡在等 MySQL 返回**，但 jstack 说它是 `RUNNABLE` —— JVM 不知道它在等网络。**怎么区分？** 用 `top -H` 交叉验证：CPU 0% 就是在等 IO，98% 才是真的在计算。

### 锁信息的三种写法

```
- locked <0x...> (a com.example.OrderService)              # 持有 synchronized 锁
- waiting to lock <0x...> (a com.example.OrderService)     # BLOCKED
- parking to wait for  <0x...> (a ...AQS$ConditionObject)  # AQS（ReentrantLock 等）
```

**同一个地址同时出现在 "locked" 和 "waiting to lock" 里，就找到了锁竞争的两端。** jstack 还会自动检测死锁，在末尾打印 `Found one Java-level deadlock:`。

### 实战技巧：三次采样

**单次 jstack 是快照，意义有限。要连续采三次，看哪些线程"没动"。**

```bash
for i in 1 2 3; do jstack 12345 > /tmp/stack_$i.txt; sleep 5; done
# 比对三次都停在哪一行
for i in 1 2 3; do grep -A 3 '"http-nio' /tmp/stack_$i.txt | grep "at com.example" | sort | uniq -c; done
```

**判定**：三次停在同一行 → 等待持续了 10 秒以上，**有问题**；三次停在不同地方 → 正常在干活。

**Arthas 更省事**：`thread -n 3` 给 CPU 最高的 3 个线程及栈；`thread -b` 自动找出阻塞其他所有线程的罪魁祸首；`thread --state BLOCKED` 列出所有阻塞线程。

### 看 GC：`jstat -gcutil`

```bash
$ jstat -gcutil 12345 1000
  S0     S1     E      O      M     CCS    YGC     YGCT    FGC    FGCT     GCT
  0.00  98.43  76.21  63.45  95.12  92.87   1423   12.845    17    3.921   16.766
```

| 列 | 含义 | 关注点 |
|---|---|---|
| `S0`/`S1` | Survivor 0/1 使用率 % | 一个为 0 正常；**两个都长期 100% = 晋升过快** |
| `E` | Eden 使用率 % | 涨到 100% 触发 Young GC |
| `O` | Old 使用率 % | **只涨不跌（Full GC 后也不降）= 泄漏** |
| `M` | **Metaspace 使用率 %** | 接近 100% = 元空间要爆 |
| `YGC`/`YGCT` | Young GC 次数 / 累计耗时（秒） | 相除 = 平均单次耗时 |
| `FGC`/`FGCT` | Full GC 次数 / 累计耗时 | **频繁 Full GC 是最严重的信号** |
| `GCT` | GC 总耗时 | 除以运行时长 = GC 占比（**健康线 < 1%**） |

**这份输出读出了什么**：平均 Young GC 9ms（健康）、平均 Full GC 230ms（偏高）、**M = 95.12% 完全不降（异常，去查类加载）**、O 从 63.45% 涨到 64.02% 且 Full GC 后没降（轻微泄漏迹象）。（G1 上 `S0`/`S1` 恒为 0，看 E 和 O 就行。）

### 看对象分布：`jmap -histo`

```bash
$ jmap -histo:live 12345 | head -20
 num     #instances         #bytes  class name
   1:       1204843       38554976  [C
   2:       1203821       28891704  java.lang.String
   3:        402311       12873952  java.util.HashMap$Node
```

**方括号是类型描述符**：`[C` = `char[]`、`[B` = `byte[]`、`[I` = `int[]`、`[J` = `long[]`、`[Ljava.lang.String;` = `String[]`、`[[I` = `int[][]`。

**怎么读**：两个字段都大 → 真占内存；实例数极大但字节不大 → 小对象爆炸（GC 压力大但内存不多）；**`com.example.*` 排进前 20 = 你的业务对象在堆积**。（`:live` 会触发一次 Full GC，生产慎用。）

### 堆转储：`jmap -dump` + MAT

```bash
jmap -dump:live,format=b,file=/tmp/heap.hprof 12345    # 触发 Full GC + STW
jcmd 12345 GC.heap_dump /tmp/heap.hprof                # 现代写法，同样 STW
```

**生产环境的正确姿势**：别在出事时手动 dump，一开始就配好 `-XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/data/dump/` 和 `-XX:+ExitOnOutOfMemoryError`（OOM 后主动退出让容器重启）。

**三个警告**：① 触发 Full GC，堆越大停越久（8G 堆可能停 10 秒以上）；② dump 文件约等于堆已用大小；③ dump 期间服务无响应，负载均衡会摘掉它。

**MAT 里怎么看**：先打开首页的 **Leak Suspects**（MAT 自动猜的泄漏点），再用 **Dominator Tree** 按"谁真正占着内存"排序往上找到 GC Root，最后对可疑对象右键 **Path to GC Roots** 看谁在引用它。

### `jcmd`：现代的多功能工具

JDK 7 之后推出，目标是取代 jstack/jmap/jinfo。**记住这一个就够了。**

```bash
jcmd 12345 help                          # 列出支持的所有命令
jcmd 12345 Thread.print                  # 等价 jstack（加 -l 显示 ownable synchronizers）
jcmd 12345 GC.heap_info                  # 堆概览（快，不 STW）
jcmd 12345 GC.heap_dump /tmp/heap.hprof  # 堆转储
jcmd 12345 GC.class_histogram            # 等价 jmap -histo
jcmd 12345 VM.classloader_stats          # 查元空间泄漏
jcmd 12345 VM.native_memory summary      # NMT，查 RSS 去哪了
jcmd 12345 VM.flags                      # JVM 参数（jinfo 在容器里容易失败，用这个）
jcmd 12345 JFR.start duration=60s filename=/tmp/rec.jfr   # 飞行记录器
```

**JFR（Java Flight Recorder）是 JVM 的 pprof** —— 能录制 60 秒内所有 GC、锁、IO、异常、方法采样，开销低于 1%，**生产可以常开**。这是 Java 生态里最被低估的工具（第 13 章详述）。

### Go ↔ Java 诊断工具对照表

| 需求 | Go | Java | 备注 |
|---|---|---|---|
| 找进程 | `ps aux \| grep` | `jps -l` | |
| 打所有栈 | `kill -QUIT <pid>` | `jstack` / `jcmd Thread.print` | **Go 输出含等待时长** |
| 堆 profile | pprof heap | `jmap -histo` / `-dump` + MAT | **Go 有精确分配点** |
| CPU 火焰图 | `pprof -http` 内置 | async-profiler / JFR | Java 要多装工具 |
| 运行时插桩 | 无（要改代码重编译） | **Arthas**（`watch`/`trace`/`tt`） | **Java 生态的真正优势** |
| 数据竞争检测 | `go test -race`（**生产可用**） | 无官方工具 | **Go 胜出** |
| GC 调优旋钮 | `GOGC` / `GOMEMLIMIT` | 几百个 `-XX:` 参数 | |

> 【思考】Go 程序卡死时你会 `kill -QUIT <pid>` 打出所有 goroutine 栈。Java 里对应的做法是什么？两者输出的信息量差在哪？
>
> 提示：想想 Go 的 goroutine 栈里有一行 Java 没有的关键信息。

<details>
<summary><b>参考答案</b></summary>

**直接答案：Java 的对应做法是 `jstack <pid>`（或 `jcmd <pid> Thread.print`）。核心差异是 —— Go 的输出会告诉你每个 goroutine 等了多久，Java 的 jstack 不会。**

**Go 的输出（关键行已标注）：**

```
goroutine 42 [chan receive, 10 minutes]:        ← 【10 minutes】这一行 Java 没有
  main.worker(0xc000100000)
      /app/worker.go:23 +0x4f
  created by main.main
      /app/main.go:11 +0x3d

goroutine 44 [semacquire, 2 minutes]:            ← 等互斥锁 2 分钟
  sync.runtime_SemaquireMutex(...)
```

**Java 的 jstack 输出：**

```
"http-nio-8080-exec-1" #23 daemon prio=5 os_prio=0 nid=0x1234 waiting on condition
   java.lang.Thread.State: WAITING (parking)
        at sun.misc.Unsafe.park(Native Method)
```

**没有"等多久"这个信息。一次都没有。**

**这个差异为什么重要？**

Go 里，一次 `SIGQUIT` 扫一眼就能找出所有 `[xxx, 10 minutes]` 的 goroutine —— **它们就是卡住的那批**；单次采样就能定位，因为"等了 10 分钟"本身足以证明异常。

Java 里，一次 jstack 看到 200 个 `WAITING (parking)`，**你不知道哪些等了 1 毫秒、哪些等了 10 分钟**。因为线程池里的线程**本来就应该是 WAITING**（在等任务队列，这是正常的）。

**这就是"必须连续采样三次"的根本原因 —— 单次采样缺少时间维度，只能用多次采样来模拟。**

| 信息 | Go `SIGQUIT` | Java `jstack` |
|---|---|---|
| 等待时长 | **有** | 无 |
| OS 线程 ID | 无（不需要） | 有（nid，能跟 `top -H` 对应） |
| 锁的持有者 | 无（只知道在等，不知道谁持有） | **有**（`locked <0x...>` 可交叉比对） |
| 死锁检测 | 无（只在"所有 goroutine 都睡着"时报错退出） | **有**（自动打印 `Found one Java-level deadlock`） |
| IO 阻塞状态 | 有（`[IO wait]`） | 无（显示成 `RUNNABLE`，误导性强） |

**各有一个杀手锏**：Go 赢在"等待时长"和"创建点"，一次采样定位问题；Java 赢在"锁的持有者"和"死锁检测" —— `locked <0x...>` 能顺着地址找到持锁线程，这是 Go 完全做不到的（只知道卡在 `semacquire`，不知道谁拿着锁，连 pprof 的 mutex profile 也拿不到）。

**Arthas 补上了这个短板**：`thread -b` 直接告诉你"线程 X 持有锁 0x...，阻塞了 197 个线程"，相当于把"三次采样 + 人工比对"自动化了。

**更深一层**：根源是**调度器的可见性**。Go runtime 就是调度器本身，goroutine 挂了多久它全知道；JVM 不是线程的调度器（OS 才是），拿不到 OS 层面的等待时长 —— 换来的是能利用 OS 的线程优先级、cgroup 配额、NUMA 亲和性。

（顺带一提：Java 的 **JFR 能**记录锁等待时长 —— `Java Monitor Blocked` 事件里有 duration。JVM 有这个数据，只是 `jstack` 没暴露它。）

**给你的实践建议**：如果你习惯了 Go 的"一次 SIGQUIT 解决问题"，在 Java 里必须改掉这个习惯。**直接上 Arthas 的 `thread -b` 和 `thread -n 3`**，它们把"三次采样"自动化了，体验上最接近 Go。

</details>

### 第二个真实案例：线程池打满，接口全超时

**现象**：订单服务下午 3 点起，所有接口 P99 从 50ms 涨到 30s，然后大面积超时。CPU 30%（不高），GC 正常，无报错日志。

**排查过程**：

```bash
# 1. 按状态统计线程
jstack 12345 > /tmp/s1.txt
grep "java.lang.Thread.State" /tmp/s1.txt | sort | uniq -c
#   3   BLOCKED (on object monitor)
#   197 WAITING (parking)

# 2. 看那 3 个 BLOCKED 的
grep -B5 -A 15 "BLOCKED" /tmp/s1.txt
```

```
"http-nio-8080-exec-77" nid=0x1f8a waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
        at com.example.order.InventoryService.deduct(InventoryService.java:88)
        - waiting to lock <0x00000000d7b3c210> (a com.example.order.InventoryService)
```

```bash
# 3. 关键：谁持有这把锁？反查 locked <0x00000000d7b3c210>
grep -B10 "locked <0x00000000d7b3c210>" /tmp/s1.txt
```

```
"http-nio-8080-exec-12" nid=0x1a2b runnable
   java.lang.Thread.State: RUNNABLE
        at java.net.SocketInputStream.socketRead0(Native Method)
        at com.example.order.SmsClient.send(SmsClient.java:63)     ← 发短信！
        - locked <0x00000000d7b3c210> (a com.example.order.InventoryService)
```

**根因**：`InventoryService.deduct()` 是 `synchronized` 方法，第 92 行调用了一个**同步 HTTP 短信接口**，而该短信服务商当天下午响应变得极慢（30 秒超时）。一个线程拿着锁卡在 HTTP 上 30 秒，所有需要 `deduct()` 的请求全部 BLOCKED，200 个线程迅速耗尽 —— **雪崩**。

**修复**：

```java
// 错误：synchronized 方法里做同步 HTTP 调用（锁的粒度覆盖了整个远程调用）
public synchronized void deduct(String sku, int n) {
    smsClient.send(...);      // 同步 HTTP，30 秒超时 —— 锁被一路持有
}

// 正确方案一：把远程调用移出锁，锁只保护本地状态
public void deduct(String sku, int n) {
    synchronized (this) { /* 只做内存/DB 里的检查和扣减，毫秒级 */ }
    smsClient.sendAsync(...);   // 异步发短信，不占锁
}

// 正确方案二（最关键）：给远程调用超时 —— 从"无超时"改成 1 秒
smsClient.setConnectTimeout(1000);
smsClient.setReadTimeout(1000);

// 正确方案三：信号量隔离（Hystrix/Resilience4j 的思路）
Semaphore smsPermit = new Semaphore(10);   // 最多 10 个并发调短信
```

**教训**：

1. **所有远程调用必须有超时。** 这一条能防住 80% 的雪崩。Go 里你习惯了 `context.WithTimeout`，但 Java 的 HTTP 客户端（`HttpURLConnection`）**默认没有超时**，必须显式设置
2. **`synchronized` 方法里绝不能做 IO。** 锁的持有时间要按"微秒"算，不是"秒"
3. **`RUNNABLE` + `socketRead0` 是"下游慢"的信号**，看到这个别去查 CPU
4. **先找 `BLOCKED`，再用 `locked <0x...>` 反查持有者** —— 这套动作要练成肌肉记忆
## 04.10 本章核心结论

1. **JVM 是规范，HotSpot 是实现，Temurin/Corretto/Dragonwell 是发行版。** 三层分开是 Java 生态独有的治理结构，Go 没有这一层。

2. **类的唯一性由「类加载器 + 全限定名」共同决定。** 这一句解释了双亲委派、Tomcat 隔离、OSGi、Arthas agent 的全部原理。

3. **双亲委派解决"统一"，破坏双亲委派解决"隔离"。** JDBC 用 TCCL 反向委派，Tomcat 反着加载，Spring Boot 用 `LaunchedURLClassLoader` 处理嵌套 jar。

5. **`-Xmx` 只管堆。** 进程实际内存 = 堆 + 元空间 + CodeCache + 线程栈 + 直接内存 + GC 结构 + JVM 自身。容器 limit 至少是 `-Xmx` 的 1.5 倍。

6. **JDK 8 把 PermGen 换成 Metaspace（本地内存）。** 看到 `-XX:MaxPermSize` 就是老配置；`MaxMetaspaceSize` 必须显式设，否则吃光物理内存。

7. **对象 = 12 字节头 + 字段 + 对齐；指针压缩在堆超过约 32GB 时失效**，别把堆设在 32~40G 之间。

8. **`ThreadLocal` 泄漏的根源是"弱 key + 强 value + 长生命周期线程"。** 必须 `finally remove()`，或用 Java 21+ 的 `ScopedValue`。

9. **jstack 单次采样意义有限，要连续三次看哪些线程"没动"。** Go 的 `SIGQUIT` 直接告诉你等了多久 —— 那是 Go runtime 作为调度器的信息优势，Java 靠 Arthas 或 JFR 补上。
## 04.11 深度思考题

### 题 2：为什么 Tomcat 要破坏双亲委派？如果两个 WebApp 都用 Spring，各自用自己的版本，JVM 怎么保证不串？

<details>
<summary><b>参考答案</b></summary>

**第一问：因为 Tomcat 的产品定义就是"一个 JVM 跑多个独立应用"。**

Go 世界里你不会想做这件事 —— 三个服务就起三个容器，隔离彻底。但 2000 年代内存金贵，一个 JVM 自身开销就 100MB+，起十个 JVM 白扔 1G。所以 Tomcat 的目标是**共享一个 JVM，逻辑上隔离多个应用** —— 这跟双亲委派"全 JVM 共用一份类"的语义直接冲突，只能破坏。

**第二问：靠 `(ClassLoader, FQCN)` 二元组。**

```
Application ClassLoader (Tomcat 的 lib)
    ├── WebAppClassLoader@1a2b3c  →  app1（Spring 5.3）
    ├── WebAppClassLoader@4d5e6f  →  app2（Spring 6.0）
    └── WebAppClassLoader@7g8h9i  →  app3
```

app1 的 `ApplicationContext` 是 `(WebAppClassLoader@1a2b3c, org.springframework...ApplicationContext)`，app2 的是 `(WebAppClassLoader@4d5e6f, ...)` —— **JVM 眼里是两个完全不同的类型**，静态字段各自独立，各自的 Spring 容器单例互不干扰。

跨加载器传对象的后果：

```java
MyBean bean = (MyBean) session.getAttribute("app1Bean");
//   java.lang.ClassCastException:
//   com.example.MyBean cannot be cast to com.example.MyBean
```

类型名一模一样却强转失败 —— 看到这句，第一个念头就应该是"跨 ClassLoader 传对象了"。

**Tomcat 的加载顺序（`delegate=false`，默认）：**

```
1. 查自己的本地缓存
2. 查 JVM Bootstrap（防覆盖 java.*）
3. 【关键】自己找：WEB-INF/classes → WEB-INF/lib/*.jar
4. 自己找不到，才委派给父加载器
5. 父也没有 → ClassNotFoundException
```

**但有三类强制委派**：`java.*`、`javax.*`/`jakarta.*`、Servlet API、Tomcat 自己的类。否则 Tomcat 拿到你的 Servlet 实例后无法强转成它认识的接口，请求就分发不进去。**共享的部分必须共享，隔离的部分才隔离。**

**热部署泄漏的根源**：reload 时 Tomcat 丢弃旧加载器、新建一个。但若 JDK 或 Tomcat 自己的类持有了 WebApp 的某个类（最常见的是 JDBC 驱动注册到 `DriverManager`），整个旧加载器及它加载的所有类都无法卸载，反复部署十次元空间就满。这就是 Tomcat 那句 `failed to unregister it when the web application was stopped` 警告的来历。

**更深一层**：Tomcat 的隔离是**逻辑隔离**，靠 JVM 命名空间模拟，不是真隔离（静态变量会串、JNI 库不能重复加载、内存泄漏是常态）。这也是现代 Java 部署（fat jar + Docker）抛弃多应用模式的原因 —— 一个容器一个 JVM，用操作系统做隔离，**回到了 Go 的路线**。三十年后绕了一圈，发现 Go 一开始就走对了。

</details>

---

### 题 3：`ThreadLocal` 在线程池里的泄漏，你会怎么排查和修复？给一套完整 SOP。

<details>
<summary><b>参考答案</b></summary>

**Step 1：确认是不是它** —— `jstat -gcutil <pid> 5000` 看 O 列是否锯齿上升、Full GC 后降得很少；`jmap -histo:live <pid> | head -20` 里 `ThreadLocalMap$Entry` 排前面 → 基本实锤。

**Step 2：找出泄漏的是哪个（堆转储 + MAT）** —— Histogram 搜 `ThreadLocalMap$Entry` → List Objects，展开 entry：`referent` 是 `null` 说明 key 已被回收（这就是脏 entry），`value` 就是泄漏对象。对 value 右键 "Path to GC Roots"（排除弱引用）会看到：

```
Entry.value → ThreadLocalMap.table → Thread.threadLocals → Thread → ThreadPool
```

看到这条链，100% 确认。

**Step 3：定位业务代码** —— 拿 value 的类名全局搜 `.set(` 调用，检查有没有配对的 `remove()`。四种典型可疑模式：

```java
// 模式 1：set 了不 remove
public void doFilter(...) { UserContext.set(user); chain.doFilter(req, resp); }

// 模式 2：remove 写在 try 里而不是 finally 里（抛异常就跳过）
try { UserContext.set(user); chain.doFilter(...); UserContext.remove(); } catch (Exception e) {}

// 模式 3：ThreadLocal 不是 static 的（每个实例一个，key 更容易被回收）
private ThreadLocal<Order> current = new ThreadLocal<>();

// 模式 4：用 InheritableThreadLocal + 线程池
//   线程池里的线程只创建一次 → 继承的是"创建线程池时"的值，永不更新 → 数据错乱 + 泄漏双杀
```

**Step 4：修复（三档）**

```java
// 档位一：规范写法（治标，必须做）
try { UserContext.set(user); chain.doFilter(req, resp); }
finally { UserContext.remove(); }      // 一定在 finally 里

// 档位二：用框架机制（治本，RequestContextHolder 请求结束自动 reset）
RequestContextHolder.getRequestAttributes();

// 档位三：Java 21+ ScopedValue（彻底根治，预览特性）
ScopedValue.where(CURRENT_USER, user).run(() -> handleRequest());
```

**Step 5：异步场景（很多人漏掉）** —— `ThreadLocal` 在 `@Async` / `CompletableFuture` 里会丢失，错误地用 `InheritableThreadLocal` 会更糟。正确做法是用阿里的 `TransmittableThreadLocal` + `TtlExecutors.getTtlExecutorService(...)` 包装线程池：它在任务执行前"重放"父线程的值、执行后自动清理，顺便解决了泄漏。

**更深一层**：这不是 ThreadLocal 的 bug，是**"隐式状态 + 无作用域"的组合必然导致泄漏**。Go 的 `context.Context` 不泄漏，是因为它有明确作用域 + `defer cancel()` 自动清理。**这一次我站 Go 这边**：ScopedValue 的出现说明 JDK 团队也是这么想的。

</details>

---

### 题 5（开放题，无标准答案）：把 Go runtime 和 JVM 放在一起，你觉得最大的三个设计差异是什么？各自的代价是什么？

> 先自己想五分钟，几个方向：一个在编译期做决定、一个在运行时做决定 —— 沿着这条线能推出多少个差异？一个自己当调度器、一个把调度交给 OS —— 各自换来了什么？
>
> **如果只能留一句话**：这两种 runtime 的差异，几乎全部可以归因于**"复杂度和成本付在哪一层"**这一个选择。想清楚自己的答案，写下来；等读完第 22 章再回来看这一题，你会想改答案。
## 下一章预告

你现在能读懂 `jstack` 的每一行，知道 `NoClassDefFoundError` 要去日志开头翻根因，也知道 6G 的 RSS 里 2G 从哪来。

但你还有一件事没解决：**那个 200 个 jar 的 classpath，到底是怎么来的？**

你在 `pom.xml` 里明明只写了一个依赖，`mvn dependency:tree` 却吐出 150 行。这些 jar 从哪来？两个版本的同一个库同时在 classpath 里，JVM 加载了哪一个？为什么本地跑得好好的，上了服务器就 `NoSuchMethodError`？

第 05 章《Maven 深水区：坐标、仓库与依赖仲裁》，我们把这个黑箱拆开 —— 从 Maven 坐标的本质讲到依赖仲裁的"最近优先"规则，从本地仓库的目录结构讲到私服配置，最后给你一套 `NoSuchMethodError` 的三分钟定位 SOP。

**这一章的 ClassLoader 知识，会在第 05 章直接派上用场** —— 因为"classpath 里有什么"和"ClassLoader 先加载谁"，本来就是同一件事的两面。
