# 第 05 章（节选）　scopeBOM与多模块

> 本篇来自《Go 程序员的 Java 修炼之路》第 05 章「第 05 章　Maven 深水区：坐标、仓库与依赖仲裁（依赖到底从哪来）」。
> 返回：[第 05 章索引](./README.md)

## 05.4 scope：Java 特有的复杂概念

Go 里一个依赖就是依赖，没有作用域概念。Maven 有六种 scope，这不是闲得慌，是为解决一个真实问题：**classpath 是分层的，不同阶段需要的东西不一样。**

| scope | 编译期 | 测试期 | 运行时 | 是否传递 | 典型用途 |
|---|---|---|---|---|---|
| `compile` | 有 | 有 | 有 | 是 | 默认 |
| `provided` | 有 | 有 | 无 | 否 | Servlet API、Lombok |
| `runtime` | 无 | 有 | 有 | 是 | JDBC 驱动 |
| `test` | 无 | 有 | 无 | 否 | JUnit、Mockito |
| `system` | — | — | — | — | **已废弃**，别用 |
| `import` | — | — | — | — | 只在 `dependencyManagement` 里 |

`system` 简单说：它让你依赖一个**本地文件路径**的 jar（`<systemPath>`），破坏可移植性，官方标记废弃。见到它就说明有历史债。

### `provided`：运行环境会提供

```xml
<dependency>
    <groupId>javax.servlet</groupId>
    <artifactId>javax.servlet-api</artifactId>
    <version>4.0.1</version>
    <scope>provided</scope>
</dependency>
```

编译时你需要它（不然 `HttpServletRequest` 编译不过），但打包时**绝不能**打进去 —— Tomcat 自己有一份。打进去轻则包变大，重则两个版本打架。

> 【思考】为什么 Lombok 是 `provided`？编译完成后运行时还需要它吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不需要。Lombok 只在编译期工作，编译完使命就结束了。**

**它干了什么：** Lombok 不是普通"库"，它是挂到 javac **注解处理器（APT）** 上的插件，在**抽象语法树（AST）阶段**直接修改你的类。

```java
// 你写的
@Data
public class Order {
    private Long id;
    private String orderNo;
}
```

```java
// Lombok 在编译期把它变成（概念上，实际是改 AST 不是改源码）
public class Order {
    private Long id;
    private String orderNo;
    public Long getId() { return this.id; }
    public void setId(Long id) { this.id = id; }
    public String getOrderNo() { return this.orderNo; }
    // ... equals / hashCode / toString
}
```

**关键：那些 getter/setter 是真实生成在 `.class` 里的字节码，不是运行时调用的"Lombok 方法"。** 所以运行时不需要 Lombok —— 没有任何运行时代码会 `import lombok.*`。

**代码锚点 —— 验证：**

```bash
javap -p target/classes/com/example/Order.class
# 输出里你会看到 public java.lang.Long getId(); 等真实方法
```

**真实坑：`provided` 用错的后果**

```xml
<dependency>
    <groupId>com.mysql</groupId>
    <artifactId>mysql-connector-j</artifactId>
    <version>8.0.33</version>
    <scope>provided</scope>   <!-- 错误：打包时不会进去 -->
</dependency>
```

现象：本地 `mvn test` 全过（测试 classpath 里有），`mvn package` 成功，一部署就 `ClassNotFoundException: com.mysql.cj.jdbc.Driver`。**排查第一反应：看 tree 里这个依赖的 scope 对不对，再看产物里有没有这个 jar。**

**更深一层：Lombok 这类工具为什么 Java 有、Go 没有？** 因为 Go 没这个需求 —— public 字段直接 `order.OrderNo` 访问。Java 要 Lombok，根源是 **JavaBean 规范 + 封装教条**（字段必须 private、必须走 getter），于是每个 20 字段的 DTO 都有 200 行模板代码。Java 16 的 `record` 是官方答案（第 02 章讲过），但存量代码里 Lombok 还在，你躲不掉。

**记住：scope 是"意图声明"，不是性能优化。**
</details>

### `runtime`：面向接口编程的体现

```xml
<dependency>
    <groupId>com.mysql</groupId>
    <artifactId>mysql-connector-j</artifactId>
    <version>8.0.33</version>
    <scope>runtime</scope>
</dependency>
```

编译期只需要 JDBC 接口（`java.sql.*`，在 JDK 里），**不需要 MySQL 驱动实现**。运行时才需要。这个设计背后的思想：**面向接口编程 + 运行时替换实现** —— 换数据库只换 runtime 依赖，一行 Java 代码都不用改。

Go 对照：`database/sql` 也是接口，但驱动注册靠 `import _ "github.com/go-sql-driver/mysql"`（空导入触发 `init()`）。**Go 用语法 hack 表达同一件事，Maven 用 scope。**

### scope 的传递规则表

Maven 官方文档的传递矩阵（行 = 直接依赖的 scope，列 = 传递依赖在它自己 pom 里的 scope）：

| 直接 ↓ / 传递 → | compile | provided | runtime | test |
|---|---|---|---|---|
| **compile** | compile | *(不传递)* | runtime | *(不传递)* |
| **provided** | provided | *(不传递)* | provided | *(不传递)* |
| **runtime** | runtime | *(不传递)* | runtime | *(不传递)* |
| **test** | test | *(不传递)* | test | *(不传递)* |

排查时最常用的是浓缩版：

| 在**你的 pom** 里声明的 scope | 传给**下游模块** |
|---|---|
| `compile` | 会，以 compile 传入 |
| `runtime` | 会，以 runtime 传入 |
| `provided` | **不会** |
| `test` | **不会** |

> 【思考】为什么 `provided` 和 `test` 不传递？

<details>
<summary><b>参考答案</b></summary>

**直接答案：传递它们会造成"运行环境被污染"和"职责越界"。**

**`provided` 不传递：** `provided` 的语义是"运行环境会提供这个东西"。如果传递，那么依赖 `order-core` 的所有模块（包括一个根本不是 Web 应用的批处理任务）都会拿到 servlet-api。

更糟的是：两个 Web 应用都通过传递拿到各自版本的 servlet-api 并打进 war，部署到同一个 Tomcat 时就有三份 `javax.servlet.Servlet` 类型（Tomcat 一份，两个 App 各一份）。于是：

```
java.lang.ClassCastException: com.example.MyFilter cannot be cast to javax.servlet.Filter
```

"我这个类明明实现了 Filter 啊！" —— 是的，但它实现的是**你 war 里那个**，Tomcat 要的是**它自己那份**。全限定名一样，但来自不同 ClassLoader，在 JVM 眼里就是两个类型。

**所以规则是：谁的运行环境提供，谁自己声明 provided。别替下游做这个决定。**

**`test` 不传递：** 更直白 —— **测试代码本身就不传递**。`order-core` 的 `src/test/java` 不会打进 jar，那么它的测试依赖自然也不该传给下游。如果传递，生产包里会出现 `mockito-core`、`byte-buddy`、`objenesis` 这一堆只跟测试有关的东西。**把 mock 框架带进生产环境是安全问题**（反射 + 字节码生成的库在生产包里就是攻击面）。

**代码锚点 —— 一个真实的 provided 误用排查：**

```bash
# 1. 看 tree 里这个依赖的 scope
mvn dependency:tree -Dincludes=com.example:common-utils
# 输出 common-utils:jar:1.2.0:provided  ← 找到了

# 2. 确认它不在打包产物里
mvn package && unzip -l target/order-web.war | grep common-utils
# 无输出 = 确实没打进去 = 根因确认
```

**更深一层：scope 是一套"classpath 分区"机制。** Go 没有 scope，是因为它靠**文件命名约定**（`_test.go`）实现分区 —— 编译器自己知道哪些符号进最终二进制。

Java 用显式 scope 声明做同一件事。区别是：**Go 的分区规则不能跨模块配置，Java 的 scope 是依赖声明的一部分，可以跨模块协商。** 这让 Java 更灵活，代价是你要记住上面那张 4×4 的表。
</details>

---


## 05.5 dependencyManagement 与 BOM：解决"版本满天飞"

回到开场的第二个结：

```xml
<dependency>
    <groupId>org.mybatis</groupId>
    <artifactId>mybatis</artifactId>
    <!-- 没有 version！ -->
</dependency>
```

版本来自父 pom 或 BOM 里的 `dependencyManagement`。

### 最容易误解的一点

> **`dependencyManagement` 只声明版本，不引入依赖。**

```xml
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.mybatis</groupId>
            <artifactId>mybatis</artifactId>
            <version>3.5.13</version>
        </dependency>
    </dependencies>
</dependencyManagement>
```

**这段代码执行完，你的项目里没有 mybatis。** 它只是登记了一条规则："如果将来有人要用 mybatis 且没写版本，用 3.5.13。"

**问题 4：** 子模块自己写了版本号呢？**子模块覆盖 dependencyManagement** —— 这是有意的（允许局部逃生），但也是混乱来源，成熟团队会用 enforcer 禁止。

### BOM：一个只有 dependencyManagement 的 pom

`spring-boot-dependencies` 管理了上千个第三方库的版本，每一个都经过 Spring 团队的兼容性测试。这就是 Spring Boot "开箱即用"的技术基础之一。

```xml
<dependencyManagement>
    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-dependencies</artifactId>
            <version>2.7.18</version>
            <type>pom</type>        <!-- 必须是 pom -->
            <scope>import</scope>   <!-- 必须是 import -->
        </dependency>
    </dependencies>
</dependencyManagement>
```

> 【思考】`import` scope 是怎么工作的？为什么它能"导入"另一个 pom 的 `dependencyManagement`？
>
> 更进一步：Maven 的 `<parent>` 只能有一个（单继承），`import` 解决的是什么问题？

<details>
<summary><b>参考答案</b></summary>

**直接答案：Maven 解析 pom 时，把目标 BOM 的 `dependencyManagement` 内容原地展开（inline expansion）到当前 pom。这是 Maven 2.0.9 引入的特性，目的是解决"单继承不够用"。**

**单继承的问题：** `<parent>` 只能指定一个。你的项目既要继承**公司统一的 parent**（编译器配置、发布配置、规范插件），又想用 **Spring Boot 的 BOM**。如果 BOM 只能通过 parent 引入，你就得让公司的 parent 去继承 Spring 的 parent —— 于是全公司所有项目都被绑死在 Spring Boot 上，一个纯工具库项目也被迫继承 Spring 配置。这不可接受。

**`import` 的解法：** 告诉 Maven "去把这个 pom 的 `dependencyManagement` 段读出来，把里面每一条当作在我自己的 `dependencyManagement` 里声明的来处理"。这是 **pom 解析期的文本展开**，不是运行时机制。`mvn help:effective-pom` 能直接看到展开结果 —— 这是理解它最好的方式。

**关键特性：可以 import 多个，先声明的赢。**

```xml
<dependencyManagement>
    <dependencies>
        <dependency><!-- Spring Boot --><type>pom</type><scope>import</scope></dependency>
        <dependency><!-- AWS SDK   --><type>pom</type><scope>import</scope></dependency>
        <dependency><!-- Jackson   --><type>pom</type><scope>import</scope></dependency>
    </dependencies>
</dependencyManagement>
```

**代码锚点 —— 公司级 BOM：**

```xml
<!-- company-bom/pom.xml：独立模块，packaging 必须是 pom -->
<project>
    <groupId>com.example</groupId>
    <artifactId>company-bom</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>

    <dependencyManagement>
        <dependencies>
            <!-- 1. 先 import 上游 BOM，让它们管大部分 -->
            <dependency>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-dependencies</artifactId>
                <version>2.7.18</version>
                <type>pom</type><scope>import</scope>
            </dependency>
            <!-- 2. 再覆盖/补充（放在后面 = 优先级更高） -->
            <dependency>
                <groupId>com.fasterxml.jackson</groupId>
                <artifactId>jackson-bom</artifactId>
                <version>2.15.3</version>
                <type>pom</type><scope>import</scope>
            </dependency>
            <dependency>
                <groupId>org.mybatis</groupId>
                <artifactId>mybatis</artifactId>
                <version>3.5.13</version>
            </dependency>
            <!-- 3. 内部构件版本也在这里统一 -->
            <dependency>
                <groupId>com.example</groupId>
                <artifactId>order-api</artifactId>
                <version>${project.version}</version>
            </dependency>
        </dependencies>
    </dependencyManagement>
</project>
```

**最佳实践：parent pom 和 BOM 分离。** parent 管构建行为（插件、编译器、发布地址），BOM 只管版本号。因为**变更频率不同** —— BOM 一周改三次（升依赖），parent 一年改一次（改构建流程）。分开后升 Jackson 不需要动 parent，也就不会影响暂时不想升级的模块。

**更深一层：这才是 Java 生态对"依赖地狱"给出的真正答案。** 问题链是：nearest wins 会选到低版本 → 冲突 → `NoSuchMethodError` → 所以需要"所有人用同一个版本"。**BOM 就是最后一步的机制：把版本决策从每个模块收拢到一个地方，由最了解兼容性的人统一做。**

**对照 Go：Go 没有 BOM，也不需要。** 因为 `go.mod` 本身就是解析结果的快照，每个模块都把版本写清楚了，没有需要协商的余地。

| | Go 的 `go.mod` | Maven 的 `pom.xml` |
|---|---|---|
| 本质 | 解析结果的**快照** | 解析**规则**的描述 |
| 谁算版本 | `go mod tidy` 算完写进去 | 每次构建时现场算 |
| 冲突在哪暴露 | 写 go.mod / 编译期 | 运行时（`NoSuchMethodError`） |
| 代价 | go.mod 很长 | 需要 BOM + 治理工具 |

**Go 用"把结果写死"消灭了协商环节，代价是每个 go.mod 几百行且升级靠工具；Maven 用"保留协商 + 提供 BOM"维持了灵活性，代价是你需要 enforcer、需要定期 review 依赖树。**
</details>

---


## 05.6 多模块项目：聚合 vs 继承

### 两个独立的机制

**聚合（aggregation）**：`<modules>`，目的是"一起构建"。

```xml
<packaging>pom</packaging>
<modules>
    <module>order-api</module>
    <module>order-core</module>
    <module>order-dal</module>
    <module>order-web</module>
</modules>
```

**继承（inheritance）**：`<parent>`，目的是"共享配置"。

| 组合 | 是否存在 | 场景 |
|---|---|---|
| 只聚合不继承 | 存在 | 把几个不相关的项目凑一起一键构建（少见） |
| 只继承不聚合 | 存在 | 子模块单独发布，父 pom 在仓库里 |
| 既聚合又继承 | 最常见 | 标准多模块项目 |

第三种最常见，但**你要知道前两种存在**，否则看到别人的项目结构会懵。

### Reactor

根目录跑 `mvn install` 时，Maven 收集所有模块、**按依赖关系拓扑排序**、依次构建。所以 `<modules>` 不必按依赖顺序写。但出现**循环依赖**会直接报错 —— 排不出拓扑序，也就没有安全的构建顺序。

### 常用命令

```bash
mvn install -pl order-core -am     # 只构建 order-core 及它依赖的模块
mvn install -pl order-core -amd    # 构建 order-core 及依赖它的所有下游
mvn install -rf order-dal          # 从 order-dal 开始构建
mvn install -T 1C                  # 并行构建（每核一线程）
mvn package -DskipTests            # 跳过测试执行，但仍编译测试代码
mvn package -Dmaven.test.skip=true # 连测试代码都不编译
```

`-pl` 支持 `:order-core`（按 artifactId）、`order-core,order-dal`（多个）。`-T 1C` 能省一半时间，但**并行会放大部分插件的线程不安全 bug**，第一次用先跑两遍看结果是否稳定。

> 【思考】多模块该怎么切分？按层切（api/core/dal/web）还是按业务切（order/user/payment）？
>
> 先想：加一个"订单支持优惠券"的功能，两种切法分别要动几个模块？

<details>
<summary><b>参考答案</b></summary>

**直接答案：现代实践倾向"按业务垂直切分 + 少量公共模块"。**

**按层切的致命缺点：改一个业务功能要动 4 个模块。** "订单支持优惠券"要改 `order-api`（DTO）、`order-dal`（Mapper）、`order-core`（逻辑）、`order-web`（参数）—— 四次 review、四次发布协调，且**在 git 历史里是四个 commit**，三个月后想知道"优惠券功能改了什么"得自己拼。

更糟的是：这种结构会诱导所有人把代码往 `order-core` 里塞。两年后 `order-core` 两千个类，其余三个剩骨架。**分层切分最终都会退化成一个巨石模块 + 三个空壳。**

**按业务切：** 改订单逻辑只动 `order/`；模块边界 = 业务边界，天然适合未来拆微服务。缺点是需要纪律，否则 `common/` 会变成垃圾桶。

**DDD 分层和多模块切分的关系，很多人搞混了：** DDD 讲的 interface / application / domain / infrastructure 是**模块内部**的分层，不是**模块之间**的切分维度。正确做法是：

```
order/                          # 一个 Maven 模块 = 一个限界上下文
└── src/main/java/com/example/order/
    ├── web/                    # interface 层
    ├── application/            # 用例编排
    ├── domain/                 # 实体、领域服务、仓储接口
    └── infrastructure/         # 仓储实现、外部调用
```

**用 Java 包做分层，用 Maven 模块做限界上下文切分。** 粒度不一样，混在一起两头不讨好。

**代码锚点 —— 用 enforcer 强制模块边界：**

```xml
<plugin>
    <artifactId>maven-enforcer-plugin</artifactId>
    <version>3.4.1</version>
    <executions>
        <execution>
            <id>ban-bad-deps</id>
            <goals><goal>enforce</goal></goals>
            <configuration>
                <rules>
                    <bannedDependencies>
                        <!-- 订单域只能依赖 user-api，不能直接依赖 user-core -->
                        <excludes><exclude>com.example:user-core</exclude></excludes>
                        <message>订单域不得直接依赖用户域实现，请依赖 user-api</message>
                    </bannedDependencies>
                </rules>
            </configuration>
        </execution>
    </executions>
</plugin>
```

**决策清单：**

| 情况 | 建议切法 |
|---|---|
| 5 人以下小团队、单体 | 按层切，别折腾。层切的问题在团队大了才致命 |
| 10 人以上、多业务线并行 | 按业务切 + `common` 模块 |
| 明确要拆微服务 | 按业务切，每个业务再拆 `xxx-api` + `xxx-impl` |
| 遗留系统改造 | 先按层切稳住，再把"高频变更的业务"逐步抽成独立模块 |

**更深一层：切分的本质是"划定变更的边界"。** 模块的价值不是"代码放得整齐"，是**让一次变更的影响范围可控**。所以切分依据应该是"哪些代码会一起变"，不是"哪些代码长得像"。

**对照 Go：** Go 一个 repo 可以有多个 `go.mod`，但没有父子继承机制 —— 每个模块自包含，配置不继承，宁可重复也不引入隐式继承。好处是打开任何 `go.mod` 看到的就是全部真相；代价是跨模块统一配置很痛苦。Maven 的继承让你少写重复，代价是**必须理解 effective pom 才知道最终配置** —— 这也是 `mvn help:effective-pom` 那么重要的原因。
</details>

### 目录结构最佳实践

```
order-service/
├── pom.xml          # parent：packaging=pom，聚合 + 共享配置
├── company-bom/pom.xml
├── order-api/  ├── pom.xml └── src/main/java/...
├── order-core/ ├── pom.xml └── src/main/java/...
└── order-web/  ├── pom.xml └── src/main/java/...
```

父 pom 放根目录、子模块在同级子目录，这是最标准的扁平布局。另一种把父 pom 也放进 `order-parent/` 子目录，那样 `<relativePath>` 得写成 `../order-parent/pom.xml`，徒增复杂度。

`<relativePath>` 默认值是 `../pom.xml`。**如果 Maven 在这个路径找不到、或 groupId/artifactId 对不上，它会去仓库里找 parent** —— 这就是为什么有时候你改了父 pom，子模块构建却没生效（拿到的是仓库里的旧 parent）。遇到就先 `mvn install -N`（`-N` 非递归，只装父 pom）。

---


