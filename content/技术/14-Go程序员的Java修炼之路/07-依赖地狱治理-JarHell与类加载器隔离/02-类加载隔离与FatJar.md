# 第 07 章（节选）　类加载隔离与FatJar

> 本篇来自《Go 程序员的 Java 修炼之路》第 07 章「第 07 章　依赖地狱治理：Jar Hell、ClassLoader 与 Shade（NoSuchMethodError 的三种死法）」。
> 返回：[第 07 章索引](./README.md)

## 07.3 ClassLoader 隔离：Jar Hell 的"架构级"解法

先回顾第 04 章那句最重要的话：

> **类的唯一性由「类加载器 + 全限定名」共同决定。**

这句话反过来用，就是隔离：**不同的 ClassLoader 加载的同名类，在 JVM 眼里是两个不同的类型。**

```java
Class<?> c1 = webappLoader1.loadClass("com.example.User");
Class<?> c2 = webappLoader2.loadClass("com.example.User");
c1 == c2;                    // false
c2.cast(new User());         // ClassCastException: com.example.User cannot be cast to com.example.User
```

最后那行报错是最让人崩溃的那种：**类型名一模一样，强转失败。** 见过一次终身难忘。看到它，第一个念头就应该是"跨 ClassLoader 传对象了"。

### 三种隔离模式

| 模式 | 怎么做 | 解决什么 | 代表 |
|---|---|---|---|
| **破坏双亲委派** | 先自己加载，加载不到再问爸爸 | 应用间隔离（各自一份依赖） | Tomcat `WebAppClassLoader`、Spring Boot `LaunchedURLClassLoader` |
| **线程上下文类加载器（TCCL）** | 父加载器反向借用子加载器 | "爸爸要用儿子的类"（SPI 场景） | JDBC `DriverManager`、SLF4J 绑定、Dubbo SPI |
| **平级隔离 + 显式导出** | 每个模块一个加载器，显式声明导入/导出包 | 真正的模块化 | OSGi、Java 9 JPMS |

前两种在第 04 章讲过。这里展开第一种的完整形态。

### Tomcat 的类加载器层次（最典型，必须看懂）

```
      Bootstrap            JDK 核心（java.base 等）
          ↑
       System              Tomcat 启动脚本里 -classpath 指定的
          ↑
       Common              $CATALINA_BASE/lib（Tomcat 自己 + 所有应用共享）
       ↗     ↖
  Catalina   Shared        默认配置下这两个是空的（见下）
                 ↖
          ┌──────┴──────┐
      WebApp1        WebApp2      各自的 /WEB-INF/classes + /WEB-INF/lib
```

**关键细节：现代 Tomcat 默认只有 Common。** 打开 `conf/catalina.properties` 你会看到：

```properties
common.loader="${catalina.base}/lib","${catalina.base}/lib/*.jar",...
server.loader=          # 空 → Catalina 层不启用，退回 Common
shared.loader=          # 空 → Shared 层不启用，退回 Common
```

所以**真实生效的层次是 `Bootstrap → System → Common → WebAppN`**。教科书上那张带 Catalina/Shared 的图是完整设计，不是默认配置。看到差异别以为自己记错了。

**WebAppClassLoader 的加载顺序（`delegate=false`，默认）：**

```
1. 查自己的本地缓存
2. 查 JVM Bootstrap（防覆盖 java.*）
3. 【关键】自己先找：/WEB-INF/classes → /WEB-INF/lib/*.jar
4. 自己找不到，才委派给父加载器
5. 父也没有 → ClassNotFoundException
```

第 3、4 步跟标准双亲委派**完全相反**。这就是"破坏双亲委派"的字面意思。

**但有三类强制委派给父加载器**：`java.*`、`javax.*`/`jakarta.*`、Servlet API。否则每个 WebApp 都加载自己的 `javax.servlet.Servlet`，Tomcat 拿到你的 Servlet 实例后强转不过去，请求根本分发不进来。**共享的部分必须共享，隔离的部分才隔离。**

> 【思考】如果两个 WebApp 都用 Spring 5，但这两份 Spring 被放在 Tomcat 的 `lib/` 目录下（Common/Shared ClassLoader），会怎样？
>
> 分两种情况想：① 两个 WebApp 自己不带 Spring，全靠 `lib/` 里那份 ② `lib/` 里有一份，WebApp 的 `WEB-INF/lib` 里又各带一份（且版本不同）。

<details>
<summary><b>参考答案</b></summary>

**情况一：两个 WebApp 共用 `lib/` 里那份 Spring —— 共享的代价是"静态状态串味"。**

表面上省内存，实际是把两个应用耦合进了同一个 JVM 命名空间：

**污染一：框架级的静态缓存变成进程级。** `lib/` 里的 Spring 类由 Common ClassLoader 加载，它的静态字段全局唯一（`ReflectionUtils` 缓存、CGLIB 代理类缓存、类型转换器注册表全被两个应用共享）。

**污染二（更常见）：静态状态藏在你自己的代码里。**

```java
public class OrderCache {
    private static final Map<String, Order> CACHE = new ConcurrentHashMap<>();
}
```

打进两个 war 由各自 WebAppClassLoader 加载 → 两份，没问题；放进 `lib/` 由 Common 加载 → **两个应用共享同一个 map**，订单数据串了，且只在并发下偶现。

**污染三：卸载时泄漏。** reload 时若 `lib/` 里的类持有了 WebApp 的类（典型是 JDBC 驱动注册进 `DriverManager`、`ThreadLocal`），整个 WebAppClassLoader 及它加载的所有类都无法卸载。反复部署十次元空间就满 —— 这就是 Tomcat 那句 `registered the JDBC driver [...] but failed to unregister it when the web application was stopped` 警告的来历。

**情况二：两份 Spring 共存 —— 这才会触发那个诡异的 ClassCastException。**

```
Common ClassLoader   → spring-core 5.3（在 lib/ 里）
WebApp1 ClassLoader  → spring-core 5.0（在 WEB-INF/lib 里，delegate=false 时它赢）
```

此时 JVM 里存在两个 `org.springframework.context.ApplicationContext` 类型。于是：

```java
// WebApp1 的 Servlet 里做了一个"看起来完全合理"的强转
ApplicationContext ctx = (ApplicationContext) request
        .getServletContext()
        .getAttribute(WebApplicationContext.ROOT_WEB_APPLICATION_CONTEXT_ATTRIBUTE);

// java.lang.ClassCastException:
//   org.springframework.context.support.GenericWebApplicationContext
//   cannot be cast to org.springframework.context.ApplicationContext
// —— 强转双方类型名一模一样，还是失败
```

**这就是"两份 Spring"的经典症状。** 同理还有那个更常见的变体：

```
java.lang.ClassCastException: com.example.MyController cannot be cast to javax.servlet.Servlet
```

根因是同一个：你的 war 里打进了一份 `servlet-api`（没配 `provided`），`MyController` 实现的是**你 war 里那个** `Servlet` 接口，而 Tomcat 要的是**它自己 `lib/` 里那个**。全限定名一样，ClassLoader 不一样，JVM 眼里就是两个类型。

**代码锚点 —— 三行代码验证是不是跨加载器：**

```java
Object obj = servletContext.getAttribute("ctx");
System.out.println(obj.getClass().getClassLoader());                       // WebAppClassLoader@1a2b3c
System.out.println(ApplicationContext.class.getClassLoader());             // WebAppClassLoader@4d5e6f
System.out.println(obj.getClass().getClassLoader() ==
                   ApplicationContext.class.getClassLoader());             // false ← 破案
```

**结论（实践建议，不是理论）：**

1. **应用自己的依赖放 `WEB-INF/lib`，别放 Tomcat 的 `lib/`** —— 共享加载器上只放你**明确想共享**的东西（Servlet API、公司统一 agent）
2. **`servlet-api` 必须是 `provided`** —— 这是"打进去就出诡异 ClassCastException"的第一大成因
3. **JDBC 驱动放 `lib/`**（`DriverManager` 在 Bootstrap，看不到 WebApp 的类），但要配 `ServletContextListener` 在应用停止时反注册

**更深一层**：Tomcat 的隔离是**逻辑隔离**，不是真隔离 —— 靠 JVM 命名空间"模拟"出来的，静态变量会串、JNI 库只能加载一次、内存泄漏是常态、两个应用的 GC 和 OOM 互相影响。

**这也是为什么现代 Java 部署（fat jar + Docker）抛弃了多应用模式** —— 一个容器一个 JVM，用操作系统做隔离。绕了一大圈回到 Go 的路线：**一个二进制一个进程，隔离交给 OS。**

</details>

### Java 9 模块系统（JPMS）为什么没能解决 Jar Hell

Java 9（2017）带来了 JPMS（Java Platform Module System，JSR 376 / JEP 261）。很多人以为它能解决依赖地狱。它不能，理由很清楚：

> **JPMS 解决的是「封装」（哪些包对外可见），不解决「版本冲突」（同一个模块系统里一个模块只能有一个版本）。**

具体来说：

1. **它把 classpath 换成了 module path，但没有引入版本寻址。** `module-info.java` 里你写 `requires com.fasterxml.jackson.databind;` —— **没有版本号**。模块解析时，module path 上同一个模块名只能出现一次，出现两次直接报错：`module jackson.databind reads package ... from both A and B`。它的处理方式是**拒绝启动**，而不是"让两个版本并存"。
2. **它不做版本协商。** 没有 `requires jackson >= 2.15`，没有 MVS，没有 nearest wins。模块图里每个模块名唯一。
3. **它跟反射/动态代理冲突。** 强封装（Strong Encapsulation）默认禁止反射访问非导出的包。JDK 9~15 用 `--illegal-access=permit` 作为默认过渡值（放宽），**JDK 16（JEP 396）起默认值变成 `deny`** —— 大量依赖反射的框架（Spring、Hibernate、MyBatis）在 JDK 16+ 上开始报 `InaccessibleObjectException`。

**采用率低的三条真实原因：**

| 原因 | 具体表现 |
|---|---|
| **迁移成本高** | 要写 `module-info.java`，而你的每个依赖都得有它。Maven 中央仓库里带 `module-info`（或 `Automatic-Module-Name`）的比例长期不高 —— 大量库至今没有，只能用自动模块（名字从 jar 文件名推导，脆得很） |
| **跟主流框架冲突** | Spring Boot 长期不支持把应用本身模块化；反射、CGLIB、字节码增强跟强封装天然打架 |
| **收益不对等** | JPMS 最大的收益是"能裁剪出更小的运行时"（`jlink`），这对**部署 CLI 工具**有价值，对**跑在服务器上的 Spring 应用**几乎没价值 |

**问题 2：** 那么 JPMS 完全没用吗？不是。它在两个场景是真有价值的：① 用 `jlink` 裁剪出只包含所需模块的 JRE（容器镜像能小很多）② 强封装让 `java.*` 的内部 API（比如 `sun.misc.Unsafe`）不再被随意调用 —— 这是**安全与可维护性**的收益，不是依赖管理的收益。

> 【思考】Go 没有模块系统，为什么没有这些问题？
>
> 提示：想想 Go 的"导出"靠什么、版本冲突在哪个阶段解决、以及 `github.com/foo/bar/v2` 这个路径里的 `/v2` 到底起了什么作用。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 Go 用三个"土办法"分别解决了封装、版本协商、版本共存 —— 三个问题都解决了，而且没有一个需要"模块系统"这种重机制。**

**办法一：封装靠大小写，不需要模块声明。** Go 里首字母大写即导出、小写即包内私有，这是**语言级**规则，编译器强制。JPMS 要解决的"我想让 `com.foo.internal` 对外不可见"，Go 用命名规则解决了，代价是没法表达"这个包只对 A 模块可见"（JPMS 的 `exports ... to ...` 能表达）。**Go 放弃精细控制，换来零配置。**

**办法二：版本协商靠 MVS，在编译期解决。**

```go
require github.com/foo/bar v1.9.1
// MVS：选版本集合里最高的那个，顺序无关、单调、可重现
```

没有运行时寻址环节，所以不存在"classpath 顺序"这个变量，也不存在"选错了但能启动"。

**办法三（最关键）：版本共存靠「路径里带版本号」。**

这是 Go 最漂亮的一招：

```go
require (
    github.com/foo/bar    v1.9.1
    github.com/foo/bar/v2 v2.3.0   // ← 两个版本同时依赖，完全合法！
)
```

在 Go 的语义里，`github.com/foo/bar` 和 `github.com/foo/bar/v2` 是**两个不同的模块路径**，也就是**两个不同的包**。编译器眼里它们跟 `github.com/foo/bar` 和 `github.com/baz/qux` 没有区别 —— 名字不同，符号不同，静态链接时各走各的。

**这实际上就是 Shade！** 只不过 Shade 是构建工具事后改写字节码，Go 是**让作者从一开始就把版本号写进模块路径**。前者是补丁，后者是约定。

**三者的对照：**

| 问题 | Go | Java |
|---|---|---|
| 封装 | 大小写导出（语言级，零配置） | 包可见性 + JPMS 的 `exports`（需要 module-info） |
| 版本协商 | MVS，编译期 | nearest wins / 最高版本，构建期 |
| 版本共存 | `/v2` 路径后缀（**天然支持**） | Shade 重定位 / ClassLoader 隔离 / OSGi（都要额外机制） |
| 冲突暴露 | 编译期 | 运行时 |

**更深一层 —— 这也是全章最反直觉的一个结论：**

**Go 用"路径里带版本号"这个土办法，反而比 JPMS 的模块系统更实用。**

因为 JPMS 试图在一个**运行时系统**里解决版本共存（那需要运行时支持按版本寻址，07.1 那个思考题已经论证了为什么 JVM 没做）；而 Go 把版本塞进**名字**里 —— 名字是编译期的概念，不需要运行时任何支持。

**这是一个"在正确的层解决问题"的范例。** 版本共存本质上是"命名"问题，解法就该在命名层（路径字符串），而不是运行时层（模块系统）。Go 团队看穿了这一点；JPMS 的设计者被"运行时模块化"这个既定目标绑住了。

**代价呢？** Go 的方案要求**库作者手动改模块路径**（发布 v2 要改所有 import，这是 Go 社区的公认痛点，也是很多库宁可永远停在 v1 或用 `+incompatible` 的原因）。Java 的方案不要求作者做任何事，代价是问题没解决。

**又一次：把复杂度付给作者（Go）还是付给使用者（Java）。**

</details>

---


## 07.5 Spring Boot 的 Fat Jar：另一种解法

### 结构（跟 Shade 完全不同，这是本节重点）

Shade 是把所有依赖**解压后平铺**进一个 jar。Spring Boot 的做法是**不解压**：

```
app.jar
├── BOOT-INF/classes/                        # 你的代码
├── BOOT-INF/lib/*.jar                       # 嵌套的完整 jar（jar in jar！）
├── META-INF/MANIFEST.MF                     # Main-Class / Start-Class
└── org/springframework/boot/loader/         # Spring Boot 自己的加载器代码
```

`MANIFEST.MF` 的关键两行：

```
Main-Class: org.springframework.boot.loader.JarLauncher
Start-Class: com.example.order.OrderApplication
```

（Spring Boot 3.2 起加载器包路径改成了 `org.springframework.boot.loader.launch.JarLauncher`，2.x 是 `org.springframework.boot.loader.JarLauncher`。看到差异别慌。）

**问题 4：** JVM 原生不支持"jar 里的 jar" —— 标准 `URLClassLoader` 解析不了 `jar:file:/app.jar!/BOOT-INF/lib/xxx.jar!/` 这种嵌套 URL。那 Spring Boot 怎么办？

自己写一套：

```
JarLauncher（main 方法入口）
    └── 创建 LaunchedURLClassLoader
            └── 注册自定义 URLStreamHandler: org.springframework.boot.loader.jar.Handler
                    └── 识别 "!/" 分隔符，支持任意层嵌套的 jar URL
```

`Handler` 是核心 —— 它实现了 JDK 的 `URLStreamHandler` 接口，能处理 `jar:file:/app.jar!/BOOT-INF/lib/guava-32.jar!/com/google/common/...` 这种路径，把内层 jar 当作一个随机访问的字节流来读。

### 为什么选"嵌套 jar + 自定义 ClassLoader"，而不是 Shade

| 维度 | Shade（打平） | Spring Boot Fat Jar（嵌套） |
|---|---|---|
| 依赖边界 | **消失** —— 所有 class 混在一起 | **保留** —— 每个依赖还是独立 jar |
| 反射 | 会挂（字符串类名） | **不受影响**（类根本没被改） |
| SPI 资源 | 会覆盖，要 transformer | **不覆盖**（多个 jar 各自的 `META-INF/services` 都还在） |
| 同名资源 | 只能保留一份 | 各保留各的 |
| 冲突时能定位吗 | 难（都平铺了） | **容易**（`BOOT-INF/lib/` 里直接看 jar 名和版本） |
| jar 体积 | 可能更大（无法去重、无法压缩对齐） | 依赖以原样存储，可优化 |
| 需要运行时支持 | 不需要（普通 AppClassLoader 就行） | **需要**（自定义 ClassLoader） |

> 【思考】为什么 Spring Boot 选择"保留结构"而不是"打平"？
>
> 提示：除了上面表里那些技术坑，再想想 Docker 时代的构建优化。

<details>
<summary><b>参考答案</b></summary>

**直接答案：三个理由，从技术到工程到生态，一层比一层硬。**

**理由一：Shade 的所有坑，Spring Boot 一个都不想背。**

07.4 那张"Shade 的其他坑"清单，对 Spring Boot 来说**每一条都是致命的**：

- Spring 本身是**反射密集**的框架（Bean 创建、依赖注入、AOP 代理全靠反射）→ shade 会大面积挂
- Spring Boot 的自动配置完全依赖 `META-INF/spring.factories`（2.x）/ `AutoConfiguration.imports`（3.x）→ 这是**同名资源合并**问题，shade 必须靠 `AppendingTransformer`，漏一个就少一批自动配置
- 生态里有几百个 starter，每个都可能带 SPI 文件

**用一个"会破坏框架核心机制"的方案来做打包，是自找麻烦。** Spring Boot 的目标是"任何依赖都能安全打进 fat jar"，shade 做不到这个承诺。

**理由二：保留边界 = 保留信息，而冲突排查需要的就是信息。**

打平之后，`com/google/common/base/Preconditions.class` 就是那么一个文件，你不知道它来自哪个 jar、哪个版本。嵌套之后：

```bash
unzip -l app.jar | grep guava
# BOOT-INF/lib/guava-32.1.3-jre.jar
```

一个命令，版本清清楚楚。配合 07.2 那套 `-verbose:class` 或者 `sc -d`，输出会是这样的：

```
[Loaded com.google.common.base.Preconditions from jar:file:/app.jar!/BOOT-INF/lib/guava-32.1.3-jre.jar!/]
```

**jar 路径里带着版本号 —— 这就是"保留结构"的价值。** 排 Jar Hell 时，信息就是一切。

**理由三（工程上最值钱）：分层（layer）—— Docker 构建优化的基础。**

这是 shade 想做也做不到的。因为依赖是独立 jar，Spring Boot 可以**按变更频率给它们分组**：

```xml
<plugin>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-maven-plugin</artifactId>
    <configuration>
        <layers>
            <enabled>true</enabled>
        </layers>
    </configuration>
</plugin>
```

默认分四层（`BOOT-INF/lib` 里的依赖 + snapshot 依赖 + 资源 + 应用类）。配合 `layertools`：

```bash
java -Djarmode=layertools -jar app.jar extract --destination target/extracted
# target/extracted/
#   ├── dependencies/           ← 第三方依赖（几乎不变）
#   ├── spring-boot-loader/
#   ├── snapshot-dependencies/  ← 内部 SNAPSHOT（经常变）
#   └── application/            ← 你的代码（每次都变）
```

Dockerfile 多阶段构建：

```dockerfile
FROM eclipse-temurin:17-jre-alpine AS builder
WORKDIR /app
ARG JAR_FILE=target/*.jar
COPY ${JAR_FILE} app.jar
RUN java -Djarmode=layertools -jar app.jar extract --destination extracted

FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
# 按"变更频率从低到高"的顺序 COPY —— 这是 Docker 层缓存的关键
COPY --from=builder /app/extracted/dependencies/ ./
COPY --from=builder /app/extracted/spring-boot-loader/ ./
COPY --from=builder /app/extracted/snapshot-dependencies/ ./
COPY --from=builder /app/extracted/application/ ./
ENTRYPOINT ["java","org.springframework.boot.loader.JarLauncher"]
```

**效果：改一行业务代码，只需要重新推几十 KB 的 application 层，而不是整个 100MB 的 jar。** Docker 的层缓存按 COPY 顺序失效，所以必须把最稳定的放在最前面。

这个优化**完全建立在"依赖是独立文件、可以按文件分组"之上**。shade 打平后所有 class 混在一起，你没法区分"哪个 class 属于哪个依赖"，也就没法分层。

**更深一层：这是"保留结构 vs 打平"这个永恒取舍的一个漂亮案例。**

打平（shade）的好处是**自包含、零运行时依赖**，代价是**信息丢失**；保留结构（fat jar）的好处是**信息完整、可优化**，代价是**需要额外的运行时机制**（自定义 ClassLoader）。

**Spring Boot 的判断是：运行时的复杂度是一次性的（写一次 `Handler` 就完了），信息丢失的代价是持续的（每次排查都要付）。** 这个判断在 2014 年做出来，到 Docker 时代被证明是超前的 —— 分层构建是意外收获，不是当初的设计目标，但因为"保留了结构"这个决定，收益自动落袋。

**对照 Go**：Go 的二进制是**彻底打平**的（静态链接），但它不丢信息 —— 因为 `go version -m` 能从二进制里读出完整的模块版本清单。**Go 选择了"打平 + 把元数据塞进产物"，Java 选择了"保留结构"。两条路都通，关键在于你有没有把"哪个版本在跑"这个信息留住。**

**这也是给所有打包方案的一个评价标准：不要只看产物大小和运行效率，要看"出事故时能不能 10 秒内回答线上跑的是什么版本"。**

</details>

**补充：** Gradle 的 `bootJar` 用的是同一套机制（同一个 `spring-boot-loader` 代码），只是由 Gradle 插件驱动。Java 11+ 的多版本 jar（MR-JAR，`Multi-Release: true` 让同一个 jar 对不同 JDK 提供不同实现）是另一个维度的事，不解决冲突 —— 它解决的是"一份产物适配多个 JDK 版本"。

---


