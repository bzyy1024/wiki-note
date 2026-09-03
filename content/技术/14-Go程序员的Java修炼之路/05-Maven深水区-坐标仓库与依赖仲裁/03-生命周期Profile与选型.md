# 第 05 章（节选）　生命周期Profile与选型

> 本篇来自《Go 程序员的 Java 修炼之路》第 05 章「第 05 章　Maven 深水区：坐标、仓库与依赖仲裁（依赖到底从哪来）」。
> 返回：[第 05 章索引](./README.md)

## 05.7 生命周期与插件：Maven 的执行引擎

### lifecycle → phase → goal

| 概念 | 是什么 | 例子 |
|---|---|---|
| **lifecycle** | 一套完整构建流程（三套） | `clean`、`default`、`site` |
| **phase** | lifecycle 里的阶段，有序 | `compile`、`test`、`package` |
| **goal** | 插件提供的具体任务 | `maven-compiler-plugin:compile` |

```
validate → compile → test → package → verify → install → deploy
```

> 【思考】执行 `mvn package` 时，`test` 阶段会执行吗？你只说了 package 啊。

<details>
<summary><b>参考答案</b></summary>

**直接答案：会。执行后面任何一个 phase，都会先把前面所有 phase 依次执行完。**

**这是 Maven 和 Make / Gradle 最重要的差别之一。** Make 和 Gradle 的模型都是**任务 DAG**（只构建目标真正需要的东西、可跳过 up-to-date 的任务、可并行）；**Maven 的模型是线性序列** —— 没有"依赖关系"，只有"先后顺序"。

所以 `mvn package` 实际执行 `validate, compile, test, package`；`mvn compile` 不跑测试（compile 在 test 前面）；想跳过测试必须显式 `-DskipTests`。

**验证方法：** 跑 `mvn package`，看输出里的 `[INFO] --- maven-...-plugin:x.y:goal ---` 段落，你会看到 `maven-surefire-plugin:test` 出现在 `maven-jar-plugin:jar` 之前。

**goal 绑定到 phase 用 `<executions>`：**

```xml
<plugin>
    <artifactId>maven-shade-plugin</artifactId>
    <version>3.5.1</version>
    <executions>
        <execution>
            <id>build-fat-jar</id>
            <phase>package</phase>          <!-- 绑到 package 阶段 -->
            <goals><goal>shade</goal></goals>
            <configuration>
                <transformers>
                    <!-- 多个 jar 的 MANIFEST 合并，指定 mainClass -->
                    <transformer implementation="org.apache.maven.plugins.shade.resource.ManifestResourceTransformer">
                        <mainClass>com.example.order.OrderApplication</mainClass>
                    </transformer>
                </transformers>
            </configuration>
        </execution>
    </executions>
</plugin>
```

**更深一层：线性序列为什么能活二十年？** 因为它**牺牲效率换来可预测性**。你拿到任何陌生 Maven 项目，不用看构建脚本就知道 `mvn install` 会发生什么 —— 一定是那几个 phase、那个顺序。插件可换、绑定可改，骨架固定。

**对照 Go：** `go build` 没有 phase 概念，测试是 `go test`、vet 是 `go vet`、格式化是 `gofmt`，各干各的。更正交、更好组合，代价是**跨项目没有统一构建约定** —— 所以每个 Go 项目都要写个 `Makefile`。而 Maven 项目的 `mvn install` 在哪都长一个样。
</details>

### 常用插件清单

**`maven-compiler-plugin`**

```xml
<plugin>
    <artifactId>maven-compiler-plugin</artifactId>
    <version>3.11.0</version>
    <configuration>
        <!-- Java 9 之后用 release，不要用 source/target -->
        <release>17</release>
    </configuration>
</plugin>
```

**为什么用 `<release>` 而不是 `<source>`+`<target>`？** 后者只保证字节码版本兼容，但**编译时仍用当前 JDK 的 API**。你在 JDK 17 上设 `<source>11</source><target>11</target>`，代码里调了 JDK 14 才有的 API，编译照样过，跑到 JDK 11 上就 `NoSuchMethodError`。`<release>11</release>` 通过 `--release` 同时限制**字节码版本 + API 可用性**。

**`maven-surefire-plugin`**：跑单测，默认匹配 `*Test` / `Test*` / `*Tests` / `*TestCase`。3.x（以及 2.22+）原生支持 JUnit 5，前提是引入 `junit-jupiter-engine`。

**`maven-shade-plugin`**：fat jar + 类重定位。relocation 把目标包下所有类的全限定名改掉，**同时修改所有引用这些类的字节码** —— 解决 Jar Hell 最暴力的手段（第 07 章详讲）。

```xml
<configuration>
    <relocations>
        <relocation>
            <pattern>com.fasterxml.jackson</pattern>
            <shadedPattern>com.example.order.shaded.jackson</shadedPattern>
        </relocation>
    </relocations>
</configuration>
```

**`spring-boot-maven-plugin`**

```xml
<plugin>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-maven-plugin</artifactId>
    <executions><execution><goals><goal>repackage</goal></goals></execution></executions>
</plugin>
```

| | shade | spring-boot-maven-plugin |
|---|---|---|
| 打包方式 | 依赖 class **解压后平铺**进一个 jar | 依赖以**完整 jar 嵌套**在 `BOOT-INF/lib/` |
| 类加载 | 普通 AppClassLoader | 自定义 `LaunchedURLClassLoader`，能加载 jar 里的 jar |
| 冲突处理 | relocation 改名 | 靠 BOM 统一版本 |

Spring Boot 的方式更干净（不改字节码），但**需要自定义 ClassLoader** —— 标准 JVM ClassLoader 不认识 `jar:file:...!/BOOT-INF/lib/xxx.jar!/` 这种嵌套路径。

**`maven-enforcer-plugin`**（依赖治理神器）

```xml
<plugin>
    <artifactId>maven-enforcer-plugin</artifactId>
    <version>3.4.1</version>
    <dependencies>
        <!-- banDuplicateClasses 规则在这个扩展包里 -->
        <dependency>
            <groupId>org.codehaus.mojo</groupId>
            <artifactId>extra-enforcer-rules</artifactId>
            <version>1.7.0</version>
        </dependency>
    </dependencies>
    <executions>
        <execution>
            <id>enforce-rules</id>
            <goals><goal>enforce</goal></goals>
            <configuration>
                <rules>
                    <dependencyConvergence/>        <!-- 同依赖多版本 → 构建失败 -->
                    <banDuplicateClasses>
                        <findAllDuplicates>true</findAllDuplicates>
                    </banDuplicateClasses>
                    <requireMavenVersion><version>[3.8,)</version></requireMavenVersion>
                    <requireJavaVersion><version>[17,)</version></requireJavaVersion>
                </rules>
            </configuration>
        </execution>
    </executions>
</plugin>
```

**`dependencyConvergence` 是本章最该记住的配置** —— 它把依赖冲突从运行时事故提前成构建期失败。

**`versions-maven-plugin`**

```bash
mvn versions:display-dependency-updates   # 只看不改，最安全
mvn versions:use-latest-releases          # 批量升级
mvn versions:revert                       # 不满意就回滚
```

**`maven-dependency-plugin`**

```bash
mvn dependency:analyze
```

```
[WARNING] Used undeclared dependencies found:
[WARNING]    org.apache.commons:commons-lang3:jar:3.12.0:compile
[WARNING] Unused declared dependencies found:
[WARNING]    com.google.guava:guava:jar:31.1-jre:compile
```

- **Used undeclared**：用了但没声明（靠传递进来的）。**必须修** —— 上游哪天去掉那个传递依赖，你的代码就编译不过。
- **Unused declared**：可以删，但要小心 —— 反射、SPI、注解处理器用到的依赖它检测不出来。

> 【思考】为什么 `mvn spring-boot:run` 能直接把应用跑起来，而 `mvn package` 只是打个包？注意冒号。

<details>
<summary><b>参考答案</b></summary>

**直接答案：冒号是关键。`plugin:goal` 是直接调用 goal，不带冒号的是执行 phase。**

```bash
mvn spring-boot:run                    # 直接调用 goal，不经过 lifecycle
mvn package                            # 执行 default lifecycle 的 package phase
mvn compiler:compile                   # 只编译，不跑测试不打包
mvn dependency:tree                    # 只画依赖树，不构建
mvn clean install                      # 两个 lifecycle 串起来跑
```

**为什么 `spring-boot:run` 能跑起来？** 因为它绕过了 lifecycle，`run` goal 内部会组装 classpath，然后 **fork 一个 JVM 进程**，以你的主类启动。你在输出里看到的 `Started OrderApplication in 4.2 seconds` 是**子进程**打的。

这解释了几个常见现象：Ctrl+C 后应用停了但 Maven 还在收尾（两个进程）；**`spring-boot:run` 的 JVM 参数要用 `<jvmArguments>` 配**，不是 `MAVEN_OPTS`（后者是给 Maven 自己的 JVM 的）。

```xml
<plugin>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-maven-plugin</artifactId>
    <configuration>
        <!-- 给 fork 出来的应用 JVM，不是给 Maven 的 -->
        <jvmArguments>-Xmx2g -Dspring.profiles.active=dev</jvmArguments>
    </configuration>
</plugin>
```

**判断方法很简单：看有没有冒号。**

| 写法 | 含义 | 触发 lifecycle？ |
|---|---|---|
| `mvn <phase>` | 执行某 phase | 是，从头执行到该 phase |
| `mvn <plugin>:<goal>` | 直接调用 goal | 否 |
| `mvn <plugin>:<version>:<goal>` | 指定版本的直接调用 | 否，且版本确定 |

第三种在 CI 里很有用 —— **显式锁版本，避免不同环境拉到不同插件版本**：

```bash
mvn org.apache.maven.plugins:maven-dependency-plugin:3.6.1:tree -Dverbose
```

**更深一层：这是 Maven"约定优于配置"哲学的体现。** 90% 的场景只需记住 `clean`/`install`/`package`/`test` 这几个标准化语义（phase）；剩下 10% 的非常规需求，开放 `plugin:goal` 作为逃生口。

**一句话记住：phase 是"我要达到什么状态"，goal 是"我要执行哪个动作"。**
</details>

---


## 05.8 属性、Profile 与环境隔离

```xml
<properties>
    <jackson.version>2.15.3</jackson.version>
    <java.version>17</java.version>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
</properties>
```

常用内置属性：`${project.version}`、`${project.groupId}`、`${project.basedir}`（`${basedir}` 是旧写法）、`${settings.localRepository}`、`${env.JAVA_HOME}`。

多模块里引用兄弟模块的正确姿势是 `${project.version}` —— 写死版本号会导致发版时要改 N 个地方。

### Profile 激活方式

```xml
<profile>
    <id>prod</id>
    <activation>
        <jdk>17</jdk>
        <os><family>linux</family></os>
        <property><name>deploy.env</name><value>prod</value></property>
        <file><exists>src/main/resources/flag.prod</exists></file>
    </activation>
</profile>
```

```bash
mvn package -P prod
mvn package -P '!dev'
mvn help:active-profiles    # 看当前激活了哪些
```

**一个必须知道的坑**：`<activeByDefault>true</activeByDefault>` 的语义是"**当没有其他 profile 被激活时**才生效"。一旦你 `-P prod`，那个 default 的 `dev` 就自动失效了。

### 资源过滤

```xml
<build>
    <resources>
        <resource>
            <directory>src/main/resources</directory>
            <filtering>true</filtering>     <!-- 开启 ${...} 占位符替换 -->
        </resource>
    </resources>
</build>
```

**坑**：开启 filtering 后，目录下**所有**文件里的 `${...}` 都会被尝试替换，二进制文件（证书、字体）会被破坏。分目录，只对需要的开启。

> 【思考】Maven profile 和 Spring profile，该用哪个？

<details>
<summary><b>参考答案</b></summary>

**直接答案：优先 Spring profile。Maven profile 只在"不同环境需要不同的依赖/构建产物"时用。**

**核心理由：一次构建，到处部署（Build Once, Deploy Anywhere）。** 从测试环境流转到生产的应该是**同一个二进制产物**，只是启动参数不同。如果你给每个环境打不同的包，那你在测试环境测的那个包**根本不是要上生产的那个包** —— 中间隔着一个未经测试的构建过程。

```bash
# Maven profile：两个不同的 jar，测试通过不能证明生产包能跑
mvn package -P test   →  order-service-test.jar
mvn package -P prod   →  order-service-prod.jar

# Spring profile：同一个 jar，靠启动参数区分
java -jar order-service.jar --spring.profiles.active=prod
```

**Maven profile 该用的三条标准：**

1. **不同环境需要不同依赖**（如 native 库按 OS 用不同 classifier）
2. **构建产物本身不同**（如同时发布 JDK 8 / JDK 17 两个版本）
3. **构建流程需要跳过某些步骤**（本地跳过代码签名、跳过集成测试）

**代码锚点 —— 推荐的组合方式：**

```java
@Configuration
@Profile("prod")     // 只有 prod 激活时才注册
public class ProdDataSourceConfig {
    @Bean
    public DataSource dataSource() {
        HikariConfig cfg = new HikariConfig();
        cfg.setMaximumPoolSize(100);   // 生产环境连接池大一些
        return new HikariDataSource(cfg);
    }
}
```

**折中方案（很多公司在用）**：Maven profile 只做资源过滤，不做依赖差异。所有环境配置都放在 `application-{profile}.properties` 里**全部打进同一个 jar**，运行时由 Spring 选择。这样只有一个产物、配置各异、切换环境不用重新构建。**唯一注意：别把生产密码明文放进去，用环境变量 `${DB_PASSWORD}` 或配置中心。**

**更深一层：这又是一次"编译期 vs 运行时"的抉择。** Maven profile 是构建期定型（改配置要重新构建），Spring profile 是运行时选择（改配置只需重启）。回看第 00 章那条主线 —— Go 倾向编译期，Java 倾向运行时 —— 但**这次 Java 自己的最佳实践也选了运行时**。

所以判断标准不是"哪种语言喜欢哪种"，而是"**这个决定需要在不重新构建的情况下改变吗**"：数据库地址、超时、特性开关 → 运行时；native 库、目标 JDK、构建优化级别 → 构建期。

**对照 Go：** Go 没有构建期 profile（`build tag` 管的是代码不是配置）。标准做法是**十二要素：配置全走环境变量**，一个二进制到处跑。**Go 从设计上把"构建期环境差异"这条路堵死了 —— 因为构建产物必须自包含、可复制。这是 Go 部署模型简单的重要原因。**
</details>

---


## 05.9 Maven vs Gradle

### 仲裁策略差异（最重要的差别）

| | Maven | Gradle |
|---|---|---|
| 冲突仲裁 | **nearest wins**（路径最短） | **最高版本优先** |
| 顺序敏感 | 是 | 否 |

**同一个依赖图，两个工具可能解析出不同结果。** 所以从 Maven 迁移到 Gradle（或反向），**必须重新验证整个依赖树** —— 构建通过只说明编译能过，运行时的版本可能对不上。

```kotlin
configurations.all {
    resolutionStrategy {
        failOnVersionConflict()   // 冲突即失败（Gradle 7 起标记废弃）
    }
}
```

### 构建速度

| 机制 | Maven | Gradle |
|---|---|---|
| 增量编译 | 有限（模块级） | 任务级 + 文件级 |
| 构建缓存 | 无内置 | 有，本地 + 远程共享 |
| 常驻进程 | 无 | **Daemon** |
| 并行 | `-T 1C`（模块级） | 默认任务级并行 |

Daemon 是最直观的差别：之后每次省掉 JVM 启动 + 配置解析，通常快 2-5 秒。对 CI 单次构建没意义，对本地"改一行跑一次"的循环差别很大。

### DSL 表达力

```kotlin
// Gradle Kotlin DSL：就是代码
tasks.register("printDeps") {
    doLast {
        configurations["runtimeClasspath"]
            .resolvedConfiguration.resolvedArtifacts
            .forEach { println("${it.moduleVersion.id} -> ${it.file.name}") }
    }
}
```

XML 的优势是**可预测、易工具化、不会写得太离谱**；Kotlin DSL 的优势是**能表达任意逻辑**。代价也明显：**一个写得很烂的 `build.gradle.kts` 比任何 `pom.xml` 都难读。**

### 选型建议

| 场景 | 建议 |
|---|---|
| Android | **必须 Gradle** |
| Spring Boot 应用 | 都行。官方两种都支持，**Spring 源码本身用 Gradle** |
| 传统企业项目、需要严格治理 | Maven（XML 的约束反而成了优势） |
| 构建逻辑复杂、需要自定义流程 | Gradle |
| 多模块大型项目、追求构建速度 | Gradle |
| 发布流程已固化 | Maven（迁移成本可能大于收益） |

**我的实际建议：项目已经在用 Maven 且没痛点，别迁。** 迁移的隐性成本（依赖树变化、插件差异、CI 改造、团队学习）远超收益。第 06 章展开讲 Gradle。

---


