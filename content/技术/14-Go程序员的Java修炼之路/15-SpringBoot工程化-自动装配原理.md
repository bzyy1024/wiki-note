# 第 15 章　Spring Boot 工程化：自动装配、Starter 与配置体系（约定优于配置的代价）

> 你在 `pom.xml` 里加了一行 `<artifactId>spring-boot-starter-web</artifactId>`，没了。然后 `main` 方法上加个 `@SpringBootApplication`，项目就能起一个内嵌 Tomcat 的 HTTP 服务。你没配置 Tomcat、没配 DispatcherServlet、没配 Jackson、没配字符集——它们“自动”就有了。
>
> 在 Go 里你要 `r := gin.Default(); r.Run()` 显式搭起来，每一行你都看得见。在 Java 里，那一行依赖背后藏着几十个类的自动装配。这一章回答两件事：那些“自动”是从哪来的？以及当你改了一个配置它不生效时，你怎么知道到底是哪一层没接住。

---

## 15.1 为什么需要 Spring Boot：它解决了什么痛点

先把时间拨回 Spring Boot 出现之前。那时候搭一个 Web 项目长这样：写一个 `web.xml`（注册 `DispatcherServlet`、配字符编码过滤器、配监听器），写一个 `applicationContext.xml`（声明 Service/Repository 的 Bean），写一个 `spring-mvc.xml`（开注解驱动、配视图解析器），再来一份 `xxx-servlet.xml`。然后你要手动声明每一个 Bean，手动管依赖版本，最后打成一个 `war`，丢进一个你单独安装配置好的外部 Tomcat。

老 Spring（XML 时代）有四个公认的痛：

1. **配置量大且分散**。一个 Web 项目至少有三四个 XML 文件，Bean 的装配关系靠手写 `<bean>` 或者后来靠注解 + 包扫描，但容器、视图解析器、消息转换器这些“基础设施 Bean”全都得你自己配。
2. **依赖版本要手配且易冲突**。你写 `spring-web` 5.2.3，写 `spring-context` 5.2.3，写 `spring-tx` 5.2.3——版本必须对齐，对不齐就 `NoSuchMethodError`（呼应 05 章的 Jar Hell）。
3. **没有内嵌容器，要打 war 部署到外部 Tomcat**。本地跑起来要装 Tomcat，部署要打 war，环境不一致就“我本地能跑”。
4. **每个项目重复搭一套基础配置**。十个项目十份几乎一样的 `web.xml` 和 `spring-mvc.xml`，只有包名不同。

Spring Boot 的三个承诺，正好一一对上这四个痛：

- **自动配置（Auto-configuration）**：根据 classpath 上有什么，自动把该有的 Bean 配好。
- **起步依赖（Starter）**：一个依赖名把一组相关依赖和它们的版本一起拉进来，你不用管版本对齐。
- **内嵌容器（Embedded Tomcat）**：Tomcat 作为依赖打进 fat jar，一个 `java -jar` 自包含启动，不再依赖外部 Tomcat。

> 【思考】“约定优于配置”（Convention over Configuration）到底是省事还是藏雷？

<details>
<summary><b>参考答案</b></summary>

**直接答案：两面都有。省事的一面是 80% 的场景用默认就够了；藏雷的一面是剩下 20% 需要定制时，你得先理解那 80% 默认是怎么来的，才能改对。**

**为什么省事**：你写一个订单服务，要的就是一个 HTTP 入口 + JSON 序列化 + 一个内嵌容器。这东西 99% 的项目都一样，凭什么每个项目都手写一遍？Spring Boot 把“大家都这么配”的部分固化成默认，你省下的不是一行配置，是一整套“知道怎么配才对”的经验。

**为什么藏雷**：当你要改默认时，问题来了——那个默认在哪？它不是一个 `web.xml` 里你能 `go to definition` 跳过去的地方，而是散在几十个自动配置类里的一个 `@ConditionalOnClass` 判断。比如你想把 Tomcat 换成 Undertow，或者想改 Jackson 的日期格式，你得先知道“是谁在默认情况下装配了 Tomcat”“是谁在默认情况下配了 Jackson”。**不把默认摸清楚，你的定制要么不生效（被默认覆盖），要么覆盖了不该覆盖的。**

**Go 对照**：Go 的 `gin.Default()` 也是“约定”，但它是显式的约定。`gin.Default()` 里干了什么，`go to definition` 能看全：注册了日志、恢复 panic 的中间件，返回一个 `*gin.Engine`。你一眼能看到它默认带了什么，想去掉就 `gin.New()` 自己加。Spring Boot 的默认是“散在 classpath 上几十个 jar 的自动配置类里、靠条件注解动态决定”的，要看全，靠的是 Actuator（`/actuator/conditions`）和 `--debug` 启动日志——不是靠代码跳转。**这正是 00 章卡点五说的：Spring 把编译期的确定性换成了运行时的灵活性，代价是你得用工具恢复可观测性。**

**更深一层**：约定优于配置不是免费午餐，它是一笔“把基础设施的复杂度从每个项目转移到框架”的交易。框架替你做了决定，你就不用每个项目再做一遍；但框架的决定一旦不合你意，你要付出的理解成本，比当初手写那几行配置高得多。所以老哥你的心态应该是：先用默认跑起来，等真要定制时，再带着“默认是什么、在哪、怎么覆盖”的问题来看这一章后面的内容。

</details>

**Go 对照一：框架级约定是否存在**

| 维度 | Go | Java（Spring Boot） |
|---|---|---|
| 有没有“框架级约定优于配置” | 没有。Go 没有运行时 DI/AOP 这套机制来承载约定 | 有。`@Conditional` + 自动配置类组成了框架级约定 |
| 约定的载体 | 社区层面：项目布局（`cmd/`、`internal/`）、包命名 | 框架层面：`spring-boot-autoconfigure` 里几百个自动配置类 |
| 想看默认干了什么 | `go to definition` 直接读源码 | 看 `--debug` 报告或 `/actuator/conditions` |
| “改默认”的入口 | 直接改代码，所见即所得 | 写 `@Configuration` 或配 `application.properties` + 理解优先级 |

Go 不是没有约定，是约定的强制力来源不同：Go 的约定是“社区默认做法”，你不照做顶多被 code review 怼；Spring Boot 的约定是“框架在运行时替你做的决定”，你不照做，框架照样替你做，只是结果可能不是你想要的。

---

## 15.2 自动装配原理：@EnableAutoConfiguration 背后发生了什么

`@SpringBootApplication` 这个注解你天天贴，但它是个三合一。展开来看：

```java
@SpringBootApplication
// 等价于下面三个：
@SpringBootConfiguration   // 本质是 @Configuration，标记这是个配置类
@EnableAutoConfiguration   // 自动装配的总开关
@ComponentScan             // 扫你自己的包，把 @Component/@Service/@Controller 注册成 Bean
public class OrderApplication { ... }
```

第 14 章你学了 IoC/DI：容器是个 `Map<String, Object>`，`@Component` 扫出来、`@Autowired` 注进去。但那章有个没说清的空白：**那些你没写 `@Component` 的框架类（Tomcat、Jackson 的 `ObjectMapper`、Redis 的 `RedisTemplate`）是谁放进 Map 的？**

这就是 `@EnableAutoConfiguration` 的工作。

### 机制（本章核心，看清这四步）

第一步，启动时 Spring Boot 扫描**所有 jar** 里的一个固定文件：`META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`。

> 注意路径：**Spring Boot 2.7 之前**用的是 `META-INF/spring.factories`（里面有个 `org.springframework.boot.autoconfigure.EnableAutoConfiguration` 键，值是候选类列表）；**2.7 及之后**改成了专门的 `AutoConfiguration.imports` 文件，每行一个候选自动配置类的全限定名。学新不学旧，但老项目你还会看到 `spring.factories`，知道是一回事就行。

这份文件在 `spring-boot-autoconfigure` 这个 jar 里，列了几百个候选自动配置类。比如：

```
org.springframework.boot.autoconfigure.web.servlet.WebMvcAutoConfiguration
org.springframework.boot.autoconfigure.web.servlet.DispatcherServletAutoConfiguration
org.springframework.boot.autoconfigure.jackson.JacksonAutoConfiguration
org.springframework.boot.autoconfigure.data.redis.RedisAutoConfiguration
org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration
```

第二步，对每个候选类，计算它上面挂的 `@ConditionalOnXxx` 条件是否满足。满足才真正把它注册成配置类。

第三步，满足条件的自动配置类里，用 `@Bean` 定义的方法把框架对象（Tomcat、`ObjectMapper`、`RedisTemplate`……）放进容器。

第四步，这些 Bean 和你自己写的 `@Component` Bean 一起，都在同一个 `ApplicationContext` 里，互相可注入。

一句话：**自动装配 = 启动时扫描一份候选清单 + 按条件过滤 + 把通过的类里的 Bean 注册进容器。** 它不是魔法，是“条件化的批量注册 BeanDefinition”。

### @Conditional 家族（理解自动配置的总钥匙）

为什么有的自动配置类装配了、有的没有？全看这张表上的条件注解。这张表你必须记住：

| 条件注解 | 含义 |
|---|---|
| `@ConditionalOnClass` | classpath 上有这个类（存在）才装配 |
| `@ConditionalOnMissingClass` | classpath 上没有这个类才装配 |
| `@ConditionalOnBean` | 容器里已经有某 Bean 才装配 |
| `@ConditionalOnMissingBean` | **容器里还没有某 Bean 才装配（这是“自定义覆盖默认”的开关）** |
| `@ConditionalOnProperty` | 某个配置项满足条件才装配（如 `server.servlet.enabled=true`） |
| `@ConditionalOnWebApplication` | 是 Web 应用才装配 |
| `@ConditionalOnSingleCandidate` | 某类型只有一个候选 Bean 才装配 |

看一个真实例子，Tomcat 的自动配置为什么只在你引入了 Tomcat 依赖时才生效：

```java
@AutoConfiguration
@ConditionalOnClass({ Servlet.class, Tomcat.class, UpgradeProtocol.class })
@ConditionalOnWebApplication(type = Type.SERVLET)
public class ServletWebServerFactoryAutoConfiguration {
    // classpath 有 Tomcat 且是 Servlet Web 应用 => 装配内嵌 Tomcat
}
```

你加了 `spring-boot-starter-web`，它传递引入了 `tomcat-embed-core`，于是 `Tomcat.class` 在 classpath 上，`@ConditionalOnClass` 满足，内嵌 Tomcat 被装配。你换成 `spring-boot-starter-webflux` 引入的是 Netty，Tomcat 条件不满足，就装配 Netty reactor 容器。这整套逻辑，你一行配置都没写，全靠 classpath 上有什么来“探测环境、决定装配”。

> 【思考】为什么你的自定义 Bean 能“覆盖”Spring Boot 的默认 Bean？

<details>
<summary><b>参考答案</b></summary>

**直接答案：靠 `@ConditionalOnMissingBean`。** Spring Boot 的自动配置类在装配默认 Bean 时，几乎都挂在“容器里还没有这个 Bean 才装配”的条件上。你一自定义，条件不满足，默认让位，你的生效。这是“用户的显式配置优先于框架默认”的实现机制。

**看代码锚点——以 DataSource 为例：**

```java
@AutoConfiguration
public class DataSourceAutoConfiguration {

    @Configuration(proxyBeanMethods = false)
    @ConditionalOnMissingBean(DataSource.class)   // 关键：容器里没有 DataSource 才配
    @ConditionalOnProperty(prefix = "spring.datasource", name = "url")
    static class DataSourceConfiguration {
        @Bean
        DataSource dataSource(...) {
            return new HikariDataSource(...);   // Spring Boot 的默认 DataSource
        }
    }
}
```

你自己的配置：

```java
@Configuration
public class MyDataSourceConfig {
    @Bean
    public DataSource dataSource() {           // 你配了 DataSource
        return new MySpecialDataSource(...);
    }
}
```

启动解析顺序上，Spring Boot 先解析自动配置类，看到 `dataSource` 想注册，但条件 `@ConditionalOnMissingBean(DataSource.class)`——此时你的 `MyDataSourceConfig.dataSource()` 已经更早或更早被扫到并注册了（具体顺序有细节，后面 15.9 题 2 展开），于是“容器里已有 DataSource”成立，默认的 `dataSource` 方法被跳过。**结果：容器里是 `MySpecialDataSource`，不是 HikariDataSource。这就是“自定义覆盖默认”。**

**Go 对照**：Go 里没有这种机制，因为 Go 没有“框架默认装配”这回事。你自己 `main()` 里写了什么 `DataSource` 就是什么，不存在“一个默认 DataSource 被你无意中覆盖”。Go 的显式装配里，覆盖只有一种方式：你显式地改 `main()` 里的那行 `NewXxx(...)`。代价是你得自己记住“我之前默认用的是哪个”，但好处是“谁生效”在代码里一眼可见，没有运行时条件的弯弯绕。

**更深一层**：`@ConditionalOnMissingBean` 是 Spring Boot 整个“约定优于配置可定制”能力的支点。它把一句设计哲学变成了代码现实——“框架给默认，但用户一旦显式声明，框架立刻闭嘴”。这比 XML 时代“默认总是生效、你得手动 exclude”友好太多。但你要注意它的前提：**你的 Bean 必须真的先被注册到容器里**，否则条件判断时“容器里还没有”仍为真，默认又装配上了。这引出了 15.9 题 2 那个坑：顺序。

</details>

**问题 1**：如果自动配置类和你的配置类都定义了同类型 Bean，但你的配置类没被提前扫到，默认先装配了，会怎样？这个坑我们放在 15.9 题 2 彻底讲透，因为它直接决定“你的配置到底能不能赢”。

### @ConditionalOnClass 和 @ConditionalOnBean 的执行时机（经典坑）

这两个注解看着像，都是“有某个东西才装配”，但判断的层面和时机完全不同，混淆了就会写出不生效的自动配置。

- `@ConditionalOnClass` 判断的是 **classpath 层面**：这个类在不在类路径上。它在**配置类解析阶段**（很早期，Bean 还没开始创建）就计算了。它只关心“字节码在不在”，不关心“这个类的实例有没有被创建成 Bean”。
- `@ConditionalOnBean` 判断的是 **容器层面**：容器里是不是已经有一个该类型的 Bean 实例。它在**Bean 创建阶段**计算，而且依赖“在那个时刻之前，这个 Bean 到底被注册了没有”。

> 【思考】为什么 `@ConditionalOnBean` 对“同一配置类内”的 Bean 判断不可靠？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 `@ConditionalOnBean` 的判断依赖“当时容器里已有的 Bean 注册”，而同一配置类里 Bean 的创建顺序不确定。你写“如果容器里有 A 才注册 B”，但若 B 比 A 先被解析，那一刻 A 还不存在，条件就判假，B 不注册——哪怕 A 随后也会被注册。结果和你预期的相反。**

**展开看机制**：

Spring 解析 `@Configuration` 类时，里面的 `@Bean` 方法默认按方法在类里的**声明顺序**逐个处理，但整个容器里几百个配置类的处理顺序、以及它们之间 Bean 的依赖关系，由依赖图拓扑排序决定，不是你写代码的顺序能完全控制的。于是：

```java
@Configuration
public class MyConfig {
    @Bean
    @ConditionalOnBean(DataSource.class)   // 想：有 DataSource 才配 logRepo
    public LogRepository logRepository() { return new LogRepository(); }

    @Bean
    public DataSource dataSource() { return new HikariDataSource(); }
}
```

如果 `logRepository` 方法排在 `dataSource` 前面（或 `logRepository` 所在配置类比 `dataSource` 先处理），那么计算 `@ConditionalOnBean(DataSource.class)` 那一刻，`dataSource` 还没注册，条件为假，`logRepository` 被跳过。随后 `dataSource` 注册了，但 `logRepository` 不会再被重新评估。**你以为“有 DataSource 就有 logRepository”，实际两者都没问题却偏偏少了一个。**

**规则**：`@ConditionalOnBean` / `@ConditionalOnMissingBean` 这类“依赖其他 Bean 存在性”的条件，只在判断**跨配置类、且被依赖的 Bean 一定更早注册**时才可靠。Spring Boot 官方的自动配置类之间用 `@AutoConfigureAfter` / `@AutoConfigureBefore` 显式排了顺序，就是为了解决这个问题。你自己在业务配置里想用 `@ConditionalOnBean`，要格外小心顺序；多数情况下，想表达“用户没配我才配”，用 `@ConditionalOnMissingBean` 比用 `@ConditionalOnBean` 安全，因为“缺失”不依赖顺序。

**Go 对照**：Go 完全没有这个时机的烦恼。你在 `main()` 里 `db := NewDB(); repo := NewLogRepository(db)`，顺序就是你写的顺序，编译期就定死。`repo` 依赖 `db`，`db` 一定先构造。没有“运行时按条件判断某个 Bean 存不存在”，也就没有“条件判断时机不对导致装配失败”。这是编译期 DI 在“依赖顺序确定性”上的结构性优势——你 14.7 的【思考】里见过同样结论。

**更深一层**：这个坑的本质是“运行时装配的副作用”——装配顺序成了隐性变量。Spring Boot 用 `@AutoConfigureBefore/After/Order` 这些注解把顺序显式化来止血，但只要你写自己的自动配置，就得自己管理顺序。再次印证全书基调：运行时灵活性换来的，是“顺序、时机、条件”这些编译期不存在的变量，你得额外操心。

</details>

---

## 15.3 Starter：依赖 + 自动配置的打包

自动配置解释了“Bean 怎么自动进容器”，但还有半截没解释：你只加了一行 `spring-boot-starter-web`，它怎么知道要带来 Tomcat、Jackson、`DispatcherServlet`？答案在 Starter。

**Starter 的本质就两件事**：

1. 在 `pom.xml` 里 `import` 一堆相关依赖（并且靠 BOM 把版本对齐，呼应 05.5）。
2. 提供一个自动配置类（带 `@Conditional`），把你引入的那些库“接上电”。

它是“依赖集合”和“自动配置”的打包单位。一个 Starter 通常对应一个功能栈。

### spring-boot-starter-web 实际引入了什么

你只写了一行，但它展开后至少带上这一组（精简树，省略版本，版本由 `spring-boot-dependencies` BOM 统一管理）：

```
spring-boot-starter-web
├── spring-boot-starter            （核心：自动配置支持、日志、YAML）
│   └── spring-boot-autoconfigure  （那几百个自动配置类就在这）
├── spring-boot-starter-json
│   └── jackson-databind / jackson-core / jackson-annotations
├── spring-boot-starter-tomcat     （内嵌 Tomcat：tomcat-embed-core 等）
├── spring-web                     （HTTP 基础抽象：HttpMessageConverter 等）
├── spring-webmvc                  （DispatcherServlet、Controller 映射）
└── spring-boot-starter-validation （参数校验：hibernate-validator）
└── (传递) spring-expression 等
```

每一个子树背后都有一个对应的自动配置类：`WebMvcAutoConfiguration`、`DispatcherServletAutoConfiguration`、`HttpMessageConvertersAutoConfiguration`（配 Jackson）、`ServletWebServerFactoryAutoConfiguration`（配 Tomcat）。所以你加一个 Starter，等于同时加了一组“被条件接上电”的自动配置。

为什么叫“starter”？因为它“启动”了整个功能栈——你引入它就获得了跑一个 Web 应用需要的一切，从容器到序列化器。

> 【思考】为什么 Starter 依赖通常用传递引入，而不是你自己一个个引？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 Starter 帮你管了两件事——版本一致性（通过 `spring-boot-dependencies` BOM）和依赖组合（哪些库放一起才兼容）。你自己一个个引，很容易引出版本冲突，而且你很难保证组合是“经过官方验证”的。**

**版本一致性**：`spring-boot-starter-web` 的传递依赖里，`spring-web` 和 `spring-webmvc` 必须是同一个 Spring 版本，`jackson-databind` 和 `jackson-core` 也必须对齐。这些版本号你一个都不用写，因为 Starter 的父链上 import 了 `spring-boot-dependencies` 这个 BOM（05.5 讲过，它就是一份“上千个第三方库版本清单”）。你自己引 `spring-webmvc:5.3.0` 却忘了 `spring-web` 也是 5.3.0，只差一个小版本就可能 `NoSuchMethodError`。用 Starter，版本这层大脑由 Spring 团队替你用 BOM 管好了。

**依赖组合**：Starter 维护的是“互相兼容的一组依赖”。比如 `spring-boot-starter-data-redis` 同时带了 `spring-data-redis` 和 `lettuce`（默认 Redis 客户端），这两者版本要对齐、API 要对得上，Spring 团队测过。你自己引 `spring-data-redis` 随便配个 lettuce 版本，组合没被测过，踩坑概率高。

**Go 对照（依赖传递视角）**：Go 里你 `go get github.com/gin-gonic/gin`，gin 的传递依赖（`go.mod` 里的 `// indirect`）也被 MVS 拍平写进你的 `go.mod`，且版本确定。区别是：**Go 的间接依赖版本是显式写进 `go.mod` 的快照**（05 章讲的），你一眼能看到；Maven 的间接依赖版本是每次构建现场算的、且被 BOM 这个“规则”覆盖，不在你的 pom 里。Go 不需要“BOM”这种额外机制，因为 `go.mod` 本身就是解析结果；Maven 需要 BOM，因为 pom 只写“规则”不写“结果”。所以 Starter 这套“靠 BOM 管版本”的设计，是 Maven 生态特有的补丁，不是本质需求。

**更深一层**：Starter 是 Spring Boot 对“依赖地狱”的二次治理（第一次是 BOM，05.5）。它把“功能栈 = 一组版本对齐的依赖 + 一份自动配置”封装成一个名词。你作为 Go 老哥，可以把它类比成 Go 里的一个“模块组”：一个 `go.mod` require 了一堆协同工作的库。但 Starter 多了一层 Go 没有的——它还会自动把那些库接进运行时容器。这是 Starter 和“普通依赖集合”的根本区别：**Starter = 依赖 + 约定（自动配置）**。

</details>

### 自己写一个 Starter（实战）

光知道原理不够，写一遍才踏实。假设团队有个内部 SDK `my-lib`，提供 `MyService`，你想让所有人加一个 `my-starter` 依赖就自动能用 `MyService`。结构长这样：

```
my-starter-project/
├── my-autoconfigure/              ← 自动配置模块（真正干活的）
│   ├── pom.xml
│   └── src/main/java/com/example/autoconfigure/
│       └── MyServiceAutoConfiguration.java
│   └── src/main/resources/
│       └── META-INF/spring/
│           └── org.springframework.boot.autoconfigure.AutoConfiguration.imports
└── my-starter/                    ← starter 模块（空壳，只做依赖聚合）
    ├── pom.xml                    ← 只依赖 my-autoconfigure + my-lib
    └── src/main/java/             ← 通常没有 Java 代码
```

自动配置类的写法：

```java
// my-autoconfigure 模块里
@AutoConfiguration                 // Spring Boot 2.7+ 推荐用 @AutoConfiguration
@ConditionalOnClass(MyService.class)   // classpath 有 MyService 才装配
public class MyServiceAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean      // 用户没自己配 MyService 才用默认
    public MyService myService(MyServiceProperties props) {
        return new MyService(props.getEndpoint());
    }
}
```

`AutoConfiguration.imports` 文件内容（一行一个类）：

```
com.example.autoconfigure.MyServiceAutoConfiguration
```

starter 模块的 `pom.xml` 只做聚合：

```xml
<dependencies>
    <dependency>
        <groupId>com.example</groupId>
        <artifactId>my-autoconfigure</artifactId>
        <version>1.0.0</version>
    </dependency>
    <dependency>
        <groupId>com.example</groupId>
        <artifactId>my-lib</artifactId>      <!-- 真正提供 MyService 的库 -->
        <version>1.0.0</version>
    </dependency>
</dependencies>
```

**关键问题：为什么“自动配置”和“starter”要分成两个模块？** 因为如果你让业务代码直接依赖 `my-autoconfigure` 模块，那个模块就被打进了业务代码的 classpath，它的自动配置类会被 `@ComponentScan` 扫到——破坏了“按需装配”的隔离（自动配置应该只通过 `AutoConfiguration.imports` 机制加载，而不是被业务包的组件扫描顺带扫进去）。分成两个模块后：业务代码只依赖轻量的 `my-starter`（它只传依赖、不带自动配置逻辑），自动配置逻辑在 `my-autoconfigure` 里、只通过 imports 文件被 Spring Boot 加载。职责清晰，按需生效。

**Go 对照**：Go 里没有“自动配置模块”这层概念。你想给团队封装一个可复用的初始化，通常是写一个 `NewMyService(...)` 函数，大家在自己的 `main()` 里调用。没有“加个依赖就自动注册进容器”的能力，因为 Go 没有运行时容器。所以这整套 Starter 机制，是 Spring 运行时 DI 生态独有的产物——再一次印证 00 章卡点五：Go 的 DI 在编译期，Java 的在运行时，Starter 就是运行时装配的“积木打包方式”。

---

## 15.4 配置体系：外部化配置的优先级

自动配置解决了“Bean 哪来的”，配置体系解决另一个问题：**同一份代码打一次，在 dev/test/prod 用不同配置**。这就是外部化配置（Externalized Configuration）。

为什么需要它？因为把数据库地址、超时、开关写死在代码里，换个环境就要改代码重新编译——这违反了“一次构建、到处部署”。所以配置要外置：从环境变量、命令行、配置文件、配置中心读。

### 完整的配置来源优先级（从高到低）

Spring Boot 把配置来源排了一条优先级链。**位置越靠上，优先级越高，会覆盖下面的。** 这份清单不同版本略有出入，但主体的高低关系是稳定的，我按从高到低列出常用且重要的来源：

| 优先级 | 配置来源 | 说明 |
|---|---|---|
| 1（最高） | 命令行参数（`--server.port=9000`） | 直接跟在 `java -jar` 后面的 `--key=value` |
| 2 | `SPRING_APPLICATION_JSON` | 环境变量或系统属性里的一段内联 JSON |
| 3 | `ServletConfig` 初始化参数 | Servlet 容器配置 |
| 4 | `ServletContext` 初始化参数 | Servlet 上下文参数 |
| 5 | JNDI 属性（`java:comp/env`） | 老式应用服务器注入 |
| 6 | Java System Properties（`-Dkey=value`） | JVM 系统属性 |
| 7 | OS 环境变量（`DB_PASSWORD` 等） | 操作系统环境变量 |
| 8 | `random.*` 属性源 | 随机值（如 `random.int`） |
| 9 | `application-{profile}.properties`（jar 包外） | 指定 profile 的、包外的配置，最高 |
| 10 | `application-{profile}.properties`（jar 包内） | 指定 profile 的、包内的配置 |
| 11 | `application.properties`（jar 包外） | 通用配置、包外 |
| 12 | `application.properties`（jar 包内） | 通用配置、包内（你打进 jar 的默认） |
| 13 | `@PropertySource` 注解 | 你代码里显式指定的配置文件 |
| 14（最低） | 默认属性（`SpringApplication.setDefaultProperties`） | 代码里写死的兜底默认值 |

几个要点必须记牢：

- **命令行参数 > 配置文件**：所以 `java -jar app.jar --server.port=9000` 一定能覆盖 `application.properties` 里的 `server.port`。
- **profile 专属文件 > 通用文件**：`application-prod.properties` 里的值覆盖 `application.properties` 里同名的值（同位置比较，如都在 jar 内或都在 jar 外）。
- **包外 > 包内**：同样 `application.properties`，jar 外面的那份覆盖 jar 里面打进去的那份。这很重要——你可以在不重新打包的情况下，用一个外部的 `application.properties` 覆盖 jar 里的默认值。

> 【思考】为什么“环境变量”能覆盖“配置文件”？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 12-factor 应用原则认为“配置应该来自环境（环境变量），不写进代码或配置”。容器化部署时，K8s 注入的环境变量要能覆盖 jar 内的 `application.properties`，否则“外部化配置”就名不副实。这是云原生部署的基础。**

**展开**：12-factor（十二要素）的第一条“基准代码”之外，第三条明确说“配置存储在环境中”（config stored in the environment）。含义是：同一份构建产物，在不同环境靠环境变量区分行为，而不是靠不同的配置文件或重新编译。如果你的环境变量覆盖不了 `application.properties`，那你在 K8s 里配的 `DB_URL` 环境变量就毫无意义，得为每个环境打不同的包——这正好违背了“一次构建、到处部署”。

Spring Boot 把 OS 环境变量排在 application.properties 之上（看上表第 7 高于第 11/12），就是落实这个原则。于是 K8s 的 Deployment 里：

```yaml
env:
  - name: DB_URL
    valueFrom:
      secretKeyRef: { name: order-db, key: url }
```

这个 `DB_URL` 环境变量能覆盖 jar 内 `application.properties` 的 `db.url`（注意环境变量名到配置项的映射，Spring Boot 会把 `DB_URL` 宽松匹配成 `db.url`，下划线转点、大小写不敏感）。**密码不进 jar，运维改环境就能改配置，不用重新构建——这是云原生时代的标准做法。**

**Go 对照**：Go 这边天然就是这个哲学。Go 没有“配置文件覆盖环境变量”的层级游戏，因为 Go 的标准做法就是 `os.Getenv("DB_URL")`，配置直接来自环境，根本没有“更高优先级的来源”这个概念——环境就是最高。Go 的 `viper` 库如果用了，也支持“环境变量 > 配置文件”，但 Go 社区的默认习惯是“配置走环境变量”，比 Spring Boot 还彻底（Spring Boot 还得兼容一堆 legacy 来源，所以层级多）。

**更深一层**：优先级链的本质是“运行环境的意志高于构建产物的意志”。越靠近运行环境注入的来源（命令行、环境变量、外部文件）优先级越高，越靠近代码写死的（默认属性）越低。这条线划在哪，决定了你的系统“多容易被运维改变行为”。Spring Boot 给了十几层，是历史包袱（要兼容 JNDI、Servlet 参数这些上古来源）和灵活性的折中；Go 只有一层（环境变量），是“约定简单”的选择。两者没有谁更对，但你要清楚：当你在 K8s 里发现配置不生效，第一反应该是“是不是被更高优先级的来源（环境变量/命令行）覆盖了”——这正是 15.6 的核心排查思路。

</details>

### 两种读取配置的方式

配置有了，代码怎么读？两条路。

第一种，`@Value`：

```java
@Value("${order.timeout:3000}")        // 读 order.timeout，没有就用默认值 3000
private int orderTimeout;
```

第二种，`@ConfigurationProperties`：

```java
@ConfigurationProperties(prefix = "order")   // 绑定所有 order.* 配置到这个对象
@Component
public class OrderProperties {
    private int timeout = 3000;              // order.timeout 自动绑进来
    private String endpoint;                // order.endpoint
    // getter / setter 必须有
}
```

> 【思考】`@Value` 和 `@ConfigurationProperties` 该用哪个？

<details>
<summary><b>参考答案</b></summary>

**直接答案：零散的单个值用 `@Value` 图方便；一组相关的配置用 `@ConfigurationProperties`。推荐后者，因为它是类型安全的、IDE 有补全、启动时能校验、还能生成配置元数据。**

**`@Value` 的三个短板**：

1. **不支持元数据补全**：你写 `@Value("${order.tiemout}")` 拼错了（应该是 `timeout`），IDE 不会报错，运行时静默用默认值，你根本不知道 key 拼错了。这正是 15.7 案例一要讲的事故。
2. **不绑定类型安全的对象**：每个字段单独写 `@Value`，散落各处，没有“这是一组 order 相关配置”的聚合感，重构时改名字找不到引用。
3. **缺少启动时校验**：`@Value` 读不到值就用默认值或报错，但没法优雅地“这组配置必须是合法 URL 否则启动失败”。

**`@ConfigurationProperties` 的三个长项**：

1. **类型安全 + 对象绑定**：`order.timeout` / `order.endpoint` 自动绑进一个 `OrderProperties` 对象，字段类型由 Java 类型决定（`int` 自动转、`Duration` 支持 `10s` 这种写法）。
2. **IDE 补全 + 元数据**：配合 `spring-boot-configuration-processor` 这个注解处理器，编译期生成 `META-INF/spring-configuration-metadata.json`，IDE 能提示你有哪些 `order.*` 配置项、类型是什么。你拼错 key，IDE 直接标黄。
3. **启动时校验**：加 `@Validated` + `jakarta.validation` 注解，应用一启动就校验配置合法性，不合法直接启动失败（fail fast），而不是等到运行时才炸。

```java
@ConfigurationProperties(prefix = "order")
@Validated
public class OrderProperties {
    @NotNull                               // 没有就启动失败
    private String endpoint;
    @Min(100)
    private int timeout = 3000;
}
```

**Go 对照**：Go 没有“运行时绑定配置到对象”的框架级能力。`viper` + `envconfig` 勉强能做（envconfig 用 struct tag 把环境变量绑到 struct），但它是显式的：你 `envconfig.Process(..., &cfg)` 把环境变量读进 struct，没有“容器在启动时自动把配置注入你的对象”这层。Go 更常见的写法：`os.Getenv("DB_URL")` 或 `viper.GetString("db.url")` 在 `main()` 里显式读、显式填进 config struct。好处是“配置从哪来、怎么绑”你一眼看见；代价是样板代码多、没有 Spring 那种“写个 `@ConfigurationProperties` 类就有配置”的省事。

**更深一层**：选 `@ConfigurationProperties` 不是因为它“高级”，是因为它把“配置契约”显式化了——哪个 key 合法、什么类型、能不能为空，都在这个类里，IDE 和启动校验都能用上。而 `@Value` 把配置契约打散成无数个字符串字面量，既不可见也不可校验。老哥你的直觉应该是对的：**凡是成组的配置，用类型安全的对象绑定，别用散落的 `@Value`。**

</details>

---

## 15.5 启动流程：SpringApplication.run 里发生了什么

你每天敲 `SpringApplication.run(OrderApplication.class, args)`，它返回之前，容器已经把几百个 Bean 造好了，Tomcat 也起来了。这节讲清它内部的关键阶段，不展开源码，但讲清“钱花在哪了”。

### 10 步启动概览

1. **推断应用类型**：判断是 Servlet Web（用 Tomcat/Netty）、Reactive Web、还是普通 None（如一个批处理任务）。这决定后面用哪种 ApplicationContext。
2. **加载 `ApplicationContextInitializer` 和 `ApplicationListener`**：从 `spring.factories` / imports 里找到这些扩展点，准备在启动各阶段回调它们。
3. **推断主类**：通过栈帧找到带 `main` 方法的那个类（你的 `OrderApplication`）。
4. **启动计时**：`SpringApplicationRunListener` 广播“启动开始”，并开计时（你日志里看到的 `Started X in Y seconds` 来自这里）。
5. **准备 Environment**：加载所有配置来源（命令行、环境变量、`application.properties`、profile），把 15.4 那十几层配置合并成一个 `Environment` 对象。
6. **打印 Banner**：就是启动时那个 Spring 图标（可关）。
7. **创建 ApplicationContext**：根据第 1 步的类型，选 `AnnotationConfigServletWebServerApplicationContext`（Servlet Web 的默认）。
8. **准备 Context（prepareContext）**：把你的主类、各 `BeanDefinition` 加载进容器，调用第 2 步加载的 `ApplicationContextInitializer`。
9. **刷新 Context（refresh）**：**最重的一步**。里面依次做：`invokeBeanFactoryPostProcessors`（处理 `@Configuration` / `@ComponentScan` / `@Import`，把候选类变成 BeanDefinition）、`registerBeanPostProcessors`（注册 AOP/事务等后处理器）、`instantiate singletons`（实例化所有非懒加载单例 Bean，**AOP 代理在此生成——呼应 14.5**）、最后**启动内嵌 Tomcat**（Servlet 容器初始化、绑定端口、开始监听）。
10. **调用 `ApplicationRunner` / `CommandLineRunner`**：所有 Bean 就绪后，执行你注册的这些“启动完成后一次性任务”钩子。

第 9 步是绝对瓶颈——classpath 扫描、条件计算、反射建 Bean、代理生成、Tomcat 启动，全在这。理解了它，你才知道“启动慢”慢在哪。

### 启动慢的元凶（呼应 00 章 0.8 题 1）

1. **classpath 扫描**：`@ComponentScan` 默认扫你主类所在包及子包的所有类，几千上万个类逐个判定有没有注解。
2. **自动配置类数量多**：几百个候选自动配置类，每个都要算 `@Conditional` 条件（有的条件还涉及 classpath 探测）。
3. **Bean 数量多**：每个单例 Bean 用反射创建，数量上千时反射开销累加。
4. **Tomcat 启动**：内嵌容器初始化、连接器绑定端口，本身要几百毫秒。
5. **代理生成**：`@Transactional`/`@Cacheable` 等 AOP 代理在 refresh 阶段批量生成，ASM 改字节码有成本。

优化方向（给实际可用的）：
- **懒加载**：`@Lazy` 或 `spring.main.lazy-initialization=true`，把非关键 Bean 推迟到首次使用时创建，启动变快但“第一个请求变慢”。
- **排除不需要的自动配置**：`spring.autoconfigure.exclude=org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration`，少算几个条件。
- **缩小 `@ComponentScan` 范围**：别用默认扫全包，明确指定 `basePackages`，少扫很多类。

> 【思考】为什么 `CommandLineRunner` / `ApplicationRunner` 在启动完成后才跑，而且如果它阻塞了启动就卡住？

<details>
<summary><b>参考答案</b></summary>

**直接答案：它们是“启动完成后执行一次性任务”的钩子（数据预热、缓存加载、建表），但它们在 SpringApplication.run 的**主线程**里执行。所以一旦阻塞，主线程卡住，`run()` 不返回，应用一直“启动中”，健康检查不过，流量进不来——整个服务卡死在就绪之前。**

**代码锚点——一个危险写法：**

```java
@Component
public class WarmUpRunner implements CommandLineRunner {
    @Override
    public void run(String... args) throws Exception {
        loadAllCacheFromDb();          // 如果这张表几千万行，这里跑几分钟
        // run() 没返回 => SpringApplication.run 不返回 => 应用没就绪
    }
}
```

启动日志会一直停在 `Started OrderApplication in ...`，但你的“几分钟缓存预热”在主线程同步跑，期间容器已经建好、端口也绑了（Tomcat 在第 9 步就起了），但 `run()` 没结束，框架认为启动流程没完，就绪探针（`/actuator/health`）可能还没暴露或返回还没启动完。结果是：进程在，但“应用没起来”。

**正确做法**：

```java
@Component
public class WarmUpRunner implements CommandLineRunner {
    private final ExecutorService pool = Executors.newSingleThreadExecutor();
    @Override
    public void run(String... args) {
        pool.submit(() -> loadAllCacheFromDb());  // 丢到异步线程，不阻塞启动
    }
}
```

或者把重任务放到 `@PostConstruct` + 异步线程，或用 `@Async`。原则是：**启动钩子里只做轻量的、必须启动成功的检查；重活要么异步，要么接受它拉长启动时间并明确告知运维。**

**Go 对照**：Go 里你在 `main()` 里显式做这些事，位置一目了然：

```go
func main() {
    db := connectDB()
    svc := NewService(db)
    go warmUpCache(db)        // 想要不阻塞，自己加 go 关键字，肉眼可见
    r := gin.New()
    r.GET("/order/:id", svc.Get)
    r.Run(":8080")
}
```

`go warmUpCache(db)` 还是 `warmUpCache(db)` 同步调，你写的时候自己决定，调用关系就摆在那。Spring 的 `CommandLineRunner` 把“启动后任务”抽象成一个钩子，但钩子在主线程跑这件事是隐式的——你不看文档不知道它会阻塞启动。这又是一次“Spring 的隐式 vs Go 的显式”：Go 让你自己决定同步异步，Spring 把“启动后做事”封装成接口，但接口是否阻塞启动这个关键事实藏在框架行为里。**读到这你应该形成条件反射：任何 Spring 的“自动调用”钩子，都先问一句“它在哪个线程跑、会不会阻塞”。**

**更深一层**：`CommandLineRunner` 阻塞这个问题，本质上是“框架替你安排执行时机，但时机的代价（阻塞主线程）你不一定看得到”。Go 把执行时机完全交给你，代价是样板，收益是“阻塞不阻塞你写的瞬间就定了”。这是显式/隐式权衡在启动流程上的再次现身。

</details>

---

## 15.6 排查自动配置：你的配置到底生效了没

这一节是工具箱，也是本章的“保命符”。前面讲了那么多原理，但实战里你最常问的是：“我配了，但它为什么不生效？”Spring Boot 给了三件套排错神器，必须会用。

**排错三件套（必会）**：

1. **`--debug` 启动**：在启动命令加 `--debug`（或 `debug=true`），启动日志会打印一整段自动配置决策报告，分成三块：
   - `Positive matches`：哪些自动配置类条件满足、被装配了。
   - `Negative matches`：哪些没匹配、为什么没匹配（`@ConditionalOnClass` 缺哪个类、`@ConditionalOnProperty` 哪个属性不满足）。
   - `Exclusions`：被你显式排除的。
   
   这是最便宜的排查入口——不用改代码，加个参数看日志。

2. **Actuator `/actuator/conditions`**：和 `--debug` 等价的 Web 版，返回 JSON，可在运行时查。前提是你引入了 `spring-boot-starter-actuator` 并开放了端点（`management.endpoints.web.exposure.include=conditions`）。

3. **Actuator `/actuator/beans`**：列出容器里**所有 Bean** 及其类型、来源（哪个 `@Configuration` 注册的）。查“到底注入了哪个实现”的核武器——呼应 00 章卡点五那个“启动成功却注入了内存实现”的事故。

   再加一个：**Actuator `/actuator/configprops`**：列出所有 `@ConfigurationProperties` 的**实际绑定值**，看你的配置到底有没有被正确读进去、被哪层来源覆盖。

> 【思考】“我的配置不生效”最常见的 5 个原因？

<details>
<summary><b>参考答案</b></summary>

**直接答案：按出现频率排序——① key 拼错被静默忽略 ② 被更高优先级的来源覆盖 ③ 在错误的 profile ④ 被 `@ConditionalOnMissingBean` 让位 ⑤ `@PropertySource` 加载顺序问题。**

**逐个拆：**

1. **key 拼错（最常见，且最隐蔽）**：你写 `order.tiemout=5000`（拼成 `tiemout`），没有 `@ConfigurationProperties` 的元数据校验时，Spring Boot 根本不报错——它只是没找到 `order.timeout` 这个 key，静默用了默认值 3000。你以为配了，实际没配上。急救：用 `@ConfigurationProperties` 让 IDE 提示正确 key（15.7 案例一详讲）。

2. **被更高优先级来源覆盖**：你在 `application.properties` 写 `server.port=8080`，但启动命令带了 `--server.port=9000`，或 K8s 注入了环境变量 `SERVER_PORT=9000`。命令行/环境变量优先级高，你的配置“赢了但没完全赢”。排查：看 `/actuator/configprops` 里的实际值，或 `--debug` 看配置源。

3. **在错误的 profile**：你把配置写进 `application-prod.properties`，但启动时 `--spring.profiles.active=dev`，于是 prod 那份根本没加载。或者反过来。**profile 专属文件只在对应 profile 激活时才参与。**

4. **被 `@ConditionalOnMissingBean` 让位**：你想自定义一个 `DataSource`，但另一个 starter 的自动配置类**先**把默认 `DataSource` 装配了（顺序问题，15.9 题 2 展开），你的 `@Bean` 因为“容器里已有”没注册成功，于是生效的是默认配置不是你的。看 `/actuator/beans` 确认实际是哪个实现。

5. **`@PropertySource` 加载顺序问题**：你用 `@PropertySource("custom.properties")` 引入外部配置，但它在自动配置之后才加载，被 BOM/默认配置覆盖了；或者 `@PropertySource` 里的 key 和 `application.properties` 冲突，优先级没你想的高（看 15.4 表，`@PropertySource` 排在第 13，低于文件和环境变量）。

**排查 SOP（记住这个顺序）**：

```
第一步：--debug 看自动配置报告，确认你的配置类是不是 Positive matches（没匹配先解决条件）
第二步：/actuator/configprops 看实际绑定值，确认 key 对不对、值是多少
第三步：/actuator/beans 看容器里实际是哪个 Bean 实现（是不是被默认覆盖了）
第四步：确认 profile 激活的是哪个（启动日志第一行有 "The following profiles are active"）
第五步：确认有没有更高优先级来源（命令行 --server.port、环境变量）覆盖
```

**Go 对照**：Go 里“配置不生效”的原因简单得多——`os.Getenv` 返回空字符串、或 `viper` 没 `.SetConfigFile` 没 `.ReadInConfig`。因为 Go 的配置来源通常就一两层（环境变量 + 一个文件），没有十几层优先级链，排查用 `log.Printf("%+v", cfg)` 直接打印 struct 就完事。Spring Boot 的排查之所以复杂，就是因为 15.4 那十几层来源可能互相覆盖——工具（`--debug`、Actuator）就是为了在十几层里定位“到底哪层赢了”而存在的。

**更深一层**：这 5 个原因背后是一条主线——**“配置不生效”几乎从不意味着“框架坏了”，而是意味着“你的意图没有按你以为的优先级被框架采纳”**。框架永远按 15.4 的优先级链办事，出问题是因为你不知道你的配置处在链的第几层。所以排查的本质是：把“我以为的优先级”和“框架实际的优先级”对上。Actuator 和 `--debug` 就是帮你看到“框架实际怎么想的”的工具。

</details>

---

## 15.7 实战：两个 Spring Boot 工程化案例

### 案例一（自定义配置不生效）

**现象**：你写了 `order.timeout=5000`（意图：订单超时 5 秒），代码里读到的还是默认 3000。日志没报错，应用跑得好好的。

**排查过程**：
1. 先怀疑 key 拼错。打开代码，发现 `@Value("${order.timeout:3000}")`——key 是对的。
2. 看 `application.properties`，你写的是 `order.timeout=5000`。等等，再仔细看——你实际写的是 `order.time-out=5000`（kebab-case 带连字符）。而代码读的是 `order.timeout`（camelCase）。**Spring Boot 的配置绑定对 `@Value` 是字面匹配，`order.time-out` 和 `order.timeout` 是两个不同的 key**，`@Value` 找不到 `order.timeout`，静默用默认值 3000。
3. 为什么会写成 `time-out`？因为 YAML 里 kebab-case 常见，你混用了习惯。但 `@Value` 不做 kebab↔camel 的松绑（宽松绑定主要对 `@ConfigurationProperties` 生效，且规则有边界）。

**根因**：key 拼错（kebab-case 和 camelCase 的坑），被 `@Value` 的默认值静默吞掉。

**修复**：改成 `order.timeout=5000`，统一 camelCase；或者改用 `@ConfigurationProperties`（它对 `order.timeout` / `order.time-out` / `ORDER_TIMEOUT` 都能宽松绑定，且 IDE 会提示正确 key，从根上避免拼错）。

**教训**：用 `@ConfigurationProperties` 能让 IDE 提示正确 key、启动校验、宽松绑定。零散 `@Value` 拼错不报错，是线上“配置悄悄不生效”的头号来源。呼应 15.4 那个【思考】。

### 案例二（自动配置被意外排除）

**现象**：引入了一个 `my-redis-starter`，功能没启用——`RedisTemplate` 没被注入，代码里 `@Autowired RedisTemplate` 启动就 `NoSuchBeanDefinitionException`。

**排查过程**：
1. `--debug` 看 Negative matches：`RedisAutoConfiguration` 显示 `Did not match: @ConditionalOnClass did not find redis.clients.jedis.Jedis`。说明 classpath 上没有 Jedis 这个类。
2. 奇怪，starter 应该带 Jedis 啊。看 `mvn dependency:tree -Dincludes=redis.clients`——发现 Jedis 被 `omitted for conflict with`（呼应 05 章），原因是另一个依赖把它 `exclusions` 了。
3. 某同事为了排除一个冲突，在另一个 SDK 的 `<exclusions>` 里把 `redis.clients:jedis` 整个排除了。结果你的 starter 依赖的 Jedis 也被顺带排除了，classpath 上没 Jedis，`@ConditionalOnClass` 失败，Redis 自动配置整段不生效。

**根因**：传递依赖被别的 `<exclusions>` 误伤，导致自动配置的条件（`@ConditionalOnClass`）不满足。

**修复**：在业务模块显式声明 `redis.clients:jedis` 依赖（深度 1，nearest wins 保证它赢），或把误伤的 exclusion 改精确（只排除真正冲突的那个 classifier）。

**教训**：理解 starter 的传递依赖链。自动配置“没生效”未必是你的配置问题，可能是 classpath 上缺了触发条件的类——而缺类可能是被别人的 exclusion 误伤。排查自动配置不生效，`--debug` 的 Negative matches 是第一步，它直接告诉你“哪个条件没满足、为什么”。

### 第三个短案例：自己写一个 Starter 让团队复用

呼应 15.3，把团队的 `MyService` 封装成 `my-starter`（自动配置模块 + starter 空壳模块），全公司引入一个依赖就能用 `MyService`，且用户自定义 `MyService` Bean 时靠 `@ConditionalOnMissingBean` 自动覆盖默认。这一套下来，你就把 15.2、15.3 的原理变成了一个可交付的团队基建——这也正是 Spring Boot 生态的玩法：好用的能力都做成一个 Starter。

---

## 15.8 本章核心结论

如果这一章你只看这一段：

1. **`@SpringBootApplication` = `@SpringBootConfiguration` + `@EnableAutoConfiguration` + `@ComponentScan`**。`@EnableAutoConfiguration` 是“自动装配”的开关，它让框架类（Tomcat、Jackson、RedisTemplate）也进容器。
2. **自动装配 = 扫描候选清单 + 按 `@Conditional` 过滤 + 注册通过的 Bean**。候选清单在 `META-INF/spring/org.springframework.boot.autoconfigure.AutoConfiguration.imports`（2.7+，旧版 `spring.factories`）。
3. **`@Conditional` 家族是理解自动配置的总钥匙**：`@ConditionalOnClass`（classpath 有才配）、`@ConditionalOnMissingBean`（用户没配才配，自定义覆盖默认的开关）、`@ConditionalOnProperty`（配置满足才配）等。
4. **Starter = 依赖集合 + 自动配置**。它靠 BOM 管版本一致性、靠传递引入功能栈，是“约定优于配置”的打包单位；自己写 Starter 要分“自动配置模块”和“starter 空壳模块”两个模块。
5. **配置优先级链十几层，越靠运行环境的来源越高**：命令行 > 环境变量 > 包外 profile 文件 > 包内文件 > `@PropertySource` > 默认属性。环境变量能覆盖文件，是 12-factor 和云原生部署的基础。
6. **成组配置用 `@ConfigurationProperties` 而非散落 `@Value`**：类型安全、IDE 补全、启动校验、`@Value` 拼错 key 静默不报错。
7. **启动最重的一步是 `refresh`**：classpath 扫描、条件计算、反射建 Bean、AOP 代理生成、内嵌 Tomcat 启动都在这；慢的元凶和优化的方向（懒加载、排除自动配置、缩小扫描）都要对准它。
8. **排查“配置不生效”靠三件套**：`--debug` 看 Positive/Negative matches、`/actuator/conditions`、`/actuator/beans`、`/actuator/configprops`。本质是“你的意图没按你以为的优先级被框架采纳”。

---

## 15.9 深度思考题

### 题 1：为什么 Spring Boot 的自动配置可以用“条件注解”实现，而 Go 做不到？

<details>
<summary><b>参考答案</b></summary>

**直接答案：根因是 Java 有“运行时 classpath 扫描 + 反射 + 注解元数据”，能在启动时“探测环境、决定装配”；Go 没有运行时反射扫描 classpath 的能力（依赖在编译期确定），所以无法做“按环境自动装配”——除非用代码生成（wire）。这是两种语言编译模型决定的。**

**Java 这边为什么行**：
- classpath 在运行时是完整的、可枚举的（你能问“当前 classpath 上有没有 `Tomcat.class`”）。`@ConditionalOnClass` 就是问这个问题。
- 注解是运行时可读的元数据（`Class.getAnnotation(...)` 能拿到），`@Conditional` 本身是注解，条件类在运行期被求值。
- 反射能动态 `newInstance()` 创建 Bean，把“探测到环境满足就创建对象”变成现实。

三者叠加，Spring Boot 才能在启动时“看 classpath 上有什么 → 条件满足就注册 Bean → 反射实例化”。这套能力的代价（00 章反复讲）是运行时黑箱、启动慢、需要工具恢复可观测性。

**Go 这边为什么不行**：
- Go 的依赖在编译期链接确定。`import` 了什么就链接什么，二进制里没有“运行时枚举 classpath 上所有类型”的能力（没有反射扫描整个二进制的 API，且 Go 的反射拿不到“哪些类型实现了某接口”的全集，除非显式注册）。
- Go 的 struct tag 只是字符串，没有 Java 那样结构化、运行时可读的注解系统。
- 所以 Go 做不到“运行时探测环境、决定装配”——你要“按环境装配”，只能用 `go:generate` 在编译前生成注册表（wire 的路子），或者手写 `main()` 里的 `if env == "prod" { ... }`。那不是“运行时自动”，是“编译期/显式”的。

**更深一层**：这题是 00 章卡点二、14.7 题 4 的终极归纳。自动配置这整套“魔法”，底层依赖的是 Java 的运行时反射 + 注解 + classpath 扫描三件套；Go 在编译模型上就堵死了这条路。所以“Go 版 Spring Boot 的自动装配”不存在于运行时，只存在于代码生成阶段——这直接引出题 4。两种语言不是“谁更聪明”，是编译期确定 vs 运行期灵活的根本分叉。

</details>

### 题 2：如果你的自定义配置和 Starter 的默认重名了会怎样？怎么保证你的配置一定赢？

<details>
<summary><b>参考答案</b></summary>

**直接答案：`@ConditionalOnMissingBean` 保证“用户定义的 Bean 优先”，但前提是你的配置类先被扫描/注册到容器。如果 Starter 的自动配置类抢先装配了同类型 Bean，你的就进不来。所以要保证赢，得确保你自己的配置在自动配置之前生效——用 `@AutoConfigureBefore`，或干脆让自己的 `@Bean` 定义在业务模块（业务配置默认在自动配置之后处理，反而更稳）。给完整机制。**

**先澄清一个反直觉点**：很多人以为“自动配置一定先跑，所以默认总赢”。错。Spring Boot 的处理顺序是：**用户的 `@Configuration`（你自己写的）先处理，自动配置类（`@AutoConfigure` 标记的）后处理**。这正是 `@ConditionalOnMissingBean` 能让你赢的原因——你的 Bean 先注册，自动配置类后来看“容器里已有”，就跳过默认。

**但坑在“同类型、同名字、且你的配置也在自动配置能影响的范围”**：如果你写的自动配置类（`@AutoConfiguration`）和 Starter 的自动配置类都定义了 `DataSource`，那两者都是自动配置类，顺序由 `@AutoConfigureBefore/After` 决定，谁先谁后不确定，可能默认先装配、你的被让位。

**保证赢的几种做法（从稳到不稳）**：

```java
// 做法一（最稳）：写在业务模块的配置类里，不要写成 @AutoConfiguration
@Configuration
public class MyDataSourceConfig {
    @Bean
    public DataSource dataSource() { return new MyDataSource(); }
}
// 业务 @Configuration 先于自动配置处理，@ConditionalOnMissingBean 让默认让位

// 做法二：你非要写自动配置类，显式排顺序
@AutoConfiguration
@AutoConfigureBefore(DataSourceAutoConfiguration.class)  // 你比它先
public class MyDataSourceAutoConfiguration {
    @Bean
    @ConditionalOnMissingBean
    public DataSource dataSource() { return new MyDataSource(); }
}
```

**为什么重名不直接冲突**：Spring 默认不允许同 beanName 覆盖（会 `BeanDefinitionOverrideException`），除非你设 `spring.main.allow-bean-definition-overriding=true`。但正常路径不是“覆盖同名”，而是“条件让位”——你的先注册，默认的因 `@ConditionalOnMissingBean` 不注册。所以“重名”在健康用法下不会冲突，是条件机制把其中一个过滤掉了。

**更深一层**：这道题考的是“装配顺序的隐式性”。当你以为“我的配置一定赢”时，真正的保障是“我的配置在谁的之前被处理”。Spring Boot 用“用户配置先于自动配置”这个铁律 + `@ConditionalOnMissingBean` 给了你默认保障；只有当你自己也写自动配置类时，才需要手动管 `@AutoConfigureBefore`。老哥你从 Go 过来，会觉得“顺序居然是个隐含契约”——没错，又是运行时装配的隐性变量。Go 里谁先 `NewXxx` 谁先构造，编译期定死，没有这种“顺序靠框架约定”的事。

</details>

### 题 3：内嵌 Tomcat 和外部 Tomcat 部署，差别在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：内嵌是把 Tomcat 作为依赖打进 fat jar，JVM 直接 `main` 启动 Tomcat；外部是打 war 丢进独立 Tomcat 进程。内嵌优势：一个 jar 自包含、容器友好、启动快、版本锁定；外部优势：多个应用共享一个 Tomcat 进程、统一运维。云原生时代几乎都内嵌。**

**内嵌 Tomcat（Spring Boot 默认）**：
- 打包：`spring-boot-maven-plugin` 把依赖作为完整 jar 嵌套在 `BOOT-INF/lib/`，用自定义 `LaunchedURLClassLoader` 加载（05.7 讲过）。
- 启动：`main` 方法里 `SpringApplication.run` 触发 `ServletWebServerFactory` 创建 `Tomcat` 实例、绑定端口、开始监听。Tomcat 是应用进程内的一个对象，不是独立进程。
- 部署：`java -jar app.jar` 一个命令，jar 自包含一切（含容器），天然适配 Docker（`FROM eclipse-temurin && COPY app.jar && java -jar`）。

**外部 Tomcat**：
- 打包：打 `war`（`packaging=war`），且 `spring-boot-starter-tomcat` 设 `provided`（05.4 讲过，运行环境提供），Servlet 相关 API 也 provided。
- 启动：war 丢进独立 Tomcat 的 `webapps/`，由 Tomcat 进程加载，你的 `main` 类要实现 `SpringBootServletInitializer`。
- 部署：运维管理一个 Tomcat，多个 war 共享它；Tomcat 版本、JVM 参数由运维统一配。

**差别的本质**：

| 维度 | 内嵌 | 外部 |
|---|---|---|
| 进程模型 | 一个 jar = 一个 JVM = 一个 Tomcat | 一个 Tomcat 进程跑多个 war |
| 版本控制 | 每个应用自带 Tomcat 版本（BOM 锁） | 全局一个 Tomcat 版本 |
| 资源隔离 | 每个应用独立 JVM，隔离好 | 共享 JVM，一个应用 OOM 拖垮全部 |
| 扩容 | 起多个 jar 实例（K8s 友好） | 在一个 Tomcat 里加 war 或加 Tomcat 实例 |
| 启动速度 | 快（无外部容器初始化） | 稍慢（Tomcat 要扫 war、解压） |

**为什么云原生几乎都内嵌**：容器（Docker/K8s）的理念是“一个容器一个进程一个职责”，内嵌 Tomcat 的 fat jar 完美契合——镜像小、启动快、扩缩容就是一个进程的事。外部 Tomcat 那种“一个容器跑多个应用”的模型，和容器编排的“一个容器一个应用”相悖。所以除非你在维护一个老的企业应用服务器（WebLogic/WebSphere）环境，否则内嵌是默认且正确的选择。

**更深一层**：内嵌 vs 外部，是“应用自包含” vs “运行环境提供”的又一次显式/隐式（或者说“自包含/共享”）权衡。Go 的部署模型天然是“自包含单二进制”，和 Spring Boot 内嵌同构——你写 Go 服务时从没想过“把二进制丢进一个共享的运行环境”，因为一个二进制就是运行环境。Spring Boot 内嵌其实是让 Java 应用向 Go 的部署简单性靠拢。这是 Java 生态向云原生演进的自然结果。

</details>

### 题 4（开放题，无标准答案）：如果让你设计“Go 版 Spring Boot”，你会怎么做？

> 【思考】
>
> 这道题没有标准答案，但从本章你已经能推出来了：Go 没有运行时魔法，所以“Go 版 Spring Boot”本质是“约定优于配置的显式版”。给你几个方向想：
> - 自动装配在 Go 里做不到运行时版，那能不能用代码生成（`go:generate` / `wire`）在编译期生成“按环境选择的装配代码”？
> - 配置体系在 Go 里没有十几层优先级，那要不要引入 `viper` 的多来源合并（环境变量 > 文件 > 默认）来模拟外部化配置？
> - Starter 在 Go 里对应什么？是不是一个 `go.mod` require 了一组协同库 + 一个 `NewXxx` 初始化函数？
> - 内嵌“容器”这件事 Go 天然有（你 `r.Run()` 就是内嵌 HTTP server），反而是 Java 需要追平 Go 的地方。
>
> 想清楚这些，你会发现：Go 版 Spring Boot 能做出“约定优于配置”的**显式版**——配置在代码里生成、可追踪，但失去“运行时灵活性”（换实现要重新生成/重新编译）。这正好呼应 00 章题 2 和 14 章题 5 那条主线。

<details>
<summary><b>参考答案</b></summary>

**直接答案：Go 版 Spring Boot = 一套项目模板（wire 生成 DI）+ 约定（目录结构、配置文件位置）+ 常用中间件封装（gorm、gin、zap 的预装配）+ 代码生成器。结论：你能做到“约定优于配置”的显式版——配置在代码里生成、可追踪，但失去运行时灵活性。**

**分四块落地：**

1. **DI（对应 `@EnableAutoConfiguration` + 自动装配）**：用 `wire` 在编译期生成 `InitializeApp()`，把所有依赖显式接好。要“按环境选实现”（如 dev 用内存库、prod 用 MySQL），在 `wire` 的 `provider set` 里用 build tag 区分（`//go:build prod` 一套 provider，`//go:build dev` 另一套），编译期决定，没有运行时条件。代价：换实现要重新 `wire` 生成 + 重新编译；收益：`wire_gen.go` 一眼看到全部装配，无黑箱。

2. **Starter（对应起步依赖）**：Go 没有“自动配置模块”，所以等价于一个 `go.mod` 直接 require 一组协同库（如 `gin` + `gorm` + `zap`），外加一个团队内部的 `pkg/bootstrap` 提供 `NewServer(...)` 把这三个预装配好。谁引入这个 `pkg/bootstrap`，谁就“启动”了整套 Web 栈——和 Starter 的语义一致，只是没有运行时自动注册。

3. **配置体系（对应 15.4）**：用 `viper` 做多来源合并，顺序设成“环境变量 > 配置文件 > 代码默认值”，模拟外部化配置。但 Go 没有 `@ConditionalOnProperty` 那种“配置满足才装配”的运行时机制——要条件装配，还是 `if cfg.UseRedis { ... }` 显式写在 `main()` 里。显式，但啰嗦。

4. **内嵌容器**：Go 天然内嵌（`http.Server` 或 `gin.Engine.Run`），这点 Go 反而比 Java 早就是这么做的。Spring Boot 内嵌 Tomcat 是向 Go 的“单二进制自包含”靠拢。

**本质结论**：Go 版 Spring Boot 不是“在运行时替你做决定”，而是“把决定写在代码/生成代码里，让你 `go to definition` 能看全”。“约定优于配置”在 Go 里是显式的——约定体现在项目模板和生成代码，不体现在运行时反射。你得到的是可追踪性，付出的是灵活性（换实现要动代码、重新编译）。

**更深一层**：这道题其实是全书的收口问题。你学 Java 的 Spring Boot，最大的收获不是“会用注解”，而是认识到“声明式/隐式的代价”——它把装配、配置、条件都藏进运行时，换来灵活，代价是可观测性要靠工具补。而 Go 的价值观（显式、可追踪）在 Spring Boot 面前不是“低级”，是一种不同的、且在小到中型项目里更省心的取舍。学完这章你应该能反过来欣赏 Go 的 `r.Run()` 为什么让人安心——因为那一行背后没有几百个条件注解在运行时替你决定。约定优于配置可以有，但“显式的约定”和“隐式的约定”是两个物种。

</details>

---

## 下一章预告

第 16 章讲 **Web 层：一次请求的一生**。从 `Tomcat` 收到一个 HTTP 请求，到你的 `@GetMapping` 方法被调用，中间经过了什么：`DispatcherServlet` 怎么把请求路由到 Controller、拦截器（`HandlerInterceptor`）在哪一层、参数绑定（`@PathVariable` / `@RequestBody` / `@RequestParam`）怎么把字符串变成你的对象、以及 WebFlux 这套响应式栈和 Servlet 栈的本质区别。

它是第 15 章“内嵌 Tomcat + 自动配好的 `DispatcherServlet`”之上的请求处理细节——你这章知道 Tomcat 被自动装配了，第 16 章会告诉你请求进了 Tomcat 之后，怎么一路走到你的业务方法，以及在哪一层能被卡住、被拦截、被改写。读完第 15 章的自动装配，第 16 章会让你对“一个 HTTP 请求在 Spring 里到底走了哪几道门”彻底有底。
