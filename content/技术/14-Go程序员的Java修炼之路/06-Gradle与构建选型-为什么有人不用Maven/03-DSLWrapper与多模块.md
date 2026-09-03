# 第 06 章（节选）　DSLWrapper与多模块

> 本篇来自《Go 程序员的 Java 修炼之路》第 06 章「第 06 章　Gradle 与构建选型：为什么有人不用 Maven」。
> 返回：[第 06 章索引](./README.md)

## 06.4 Kotlin DSL vs Groovy DSL

Gradle 有两种脚本语言。老项目是 Groovy（`build.gradle`），新项目应该是 Kotlin（`build.gradle.kts`）。

**Groovy DSL：**

```groovy
plugins {
    id 'java-library'
    id 'org.springframework.boot' version '3.2.0'
}

dependencies {
    implementation 'org.springframework:spring-context:6.1.1'
    testImplementation 'org.junit.jupiter:junit-jupiter:5.10.1'
}

test {
    useJUnitPlatform()
    testLogging {
        events 'passed', 'skipped', 'failed'
    }
}
```

**Kotlin DSL（同一段）：**

```kotlin
plugins {
    `java-library`
    id("org.springframework.boot") version "3.2.0"
}

dependencies {
    implementation("org.springframework:spring-context:6.1.1")
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.1")
}

tasks.withType<Test>().configureEach {
    useJUnitPlatform()
    testLogging { events("passed", "skipped", "failed") }
}
```

看起来差不多？差别不在语法，在**工具链能不能帮你**。

| 维度 | Groovy DSL | Kotlin DSL |
|---|---|---|
| 类型检查 | 运行时（动态派发） | **编译期** |
| IDE 自动补全 | 弱，经常只能补全到 `{}` | **完整**，依赖坐标也能补全 |
| 跳转到定义 | 经常跳不过去 | 能跳（包括 Version Catalog 里的坐标） |
| 重构（重命名） | 不可靠 | 可靠 |
| 错误发现时机 | **跑一遍才知道** | **写的时候 IDE 就画红线** |
| 首次编译脚本 | 快 | 慢一点（要编译 Kotlin 脚本） |
| 语法噪音 | 少 | 多一点（引号、括号、`tasks.withType<Test>()`） |
| 生态文档 | 存量文档多 | Gradle 官方文档默认给 Kotlin 版 |

> 【思考】为什么新项目应该用 Kotlin DSL？"语法更现代"这个理由够吗？
>
> 想一下：一个 200 行的构建脚本，你多久改一次？改的时候最大的成本是什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：语法现代是最不重要的理由。真正理由是——构建脚本的可维护性几乎完全取决于 IDE 能不能帮你，而 IDE 支持依赖静态类型。**

**构建脚本的真实使用模式，决定了什么最重要：**

一个 200 行的 `build.gradle.kts`，你多久改一次？**大概一两个月一次**（加个依赖、调个 Task 配置、升个插件版本）。这意味着：

1. **你对这段语法是陌生的** —— 上次写的时候查的文档，早忘了
2. **你不想为它跑一遍构建来验证** —— 跑一遍要几十秒到几分钟
3. **你只能靠 IDE 提示** —— 这是唯一的低成本验证手段

所以关键问题变成：**改构建脚本时，IDE 能给你多少帮助？**

**Groovy 的动态性在这里是致命的：**

```groovy
dependencies {
    implementaion 'org.springframework:spring-context:6.1.1'    // 拼错了
}
```

这行代码**语法完全合法**。Groovy 的动态派发会在运行时去找 `implementaion` 这个方法，找不到就报 `Could not find method implementaion()`。你要**跑一遍构建**才知道自己拼错了。

```groovy
tasks.named('compilJava') { ... }    // Task 名拼错
tasks.withType(Test) { usJUnitPlatform() }   // 方法名拼错
```

一样的后果。**在 Groovy DSL 里，你所有的 typo 都是运行时错误，而"运行时"= 跑一次构建 = 几十秒到几分钟。**

**Kotlin DSL 里，这些全是编译期错误：**

```kotlin
dependencies {
    implementaion("org.springframework:spring-context:6.1.1")
    // ^^^^^^^^^^^^ IDE 立刻画红线：Unresolved reference: implementaion
}
```

而且不只是画红线——**补全能直接告诉你有哪些配置可选**。你敲 `imple` 然后按补全，IDE 弹出 `implementation`、`implementation` 的重载……这对"两个月才写一次构建脚本"的人来说是救命的。

**更值钱的是跳转到定义：** 有了 Version Catalog（06.8 节），你在脚本里看到 `implementation(libs.jackson.databind)`，Cmd+B 一下直接跳到 `gradle/libs.versions.toml` 里那一行。**在 Groovy 里这个跳转通常做不到**，因为 `libs.jackson.databind` 是运行时动态解析出来的。

**代价，也得说清楚：**

1. **首次编译慢一点。** Kotlin 脚本要编译，第一次会明显感觉。开了 Configuration Cache 之后这个成本被摊薄，但冷启动仍然存在。
2. **语法稍啰嗦。** 引号（Kotlin 要求字符串用双引号）、`tasks.withType<Test>()` 这种泛型写法、`register` 的 lambda 写法，都比 Groovy 长。
3. **存量 Groovy 代码不好抄。** 你在网上搜到的 Gradle 配置，一大部分还是 Groovy 的，要自己翻译。这是最实际的摩擦。
4. **某些 Groovy 的灵活写法在 Kotlin 里做不到或很难看**（比如 `withGroovyBuilder {}`）。真需要时可以用，但很丑。

**代码锚点 —— 一个迁移时会遇到的真实差异：**

```kotlin
// Groovy：直接访问 project 的任意属性（动态）
version = '1.0.0'
sourceCompatibility = JavaVersion.VERSION_17

// Kotlin：部分属性需要显式指定类型或用 setter
version = "1.0.0"
// sourceCompatibility = JavaVersion.VERSION_17   // ❌ Kotlin DSL 里不直接可用
java {
    sourceCompatibility = JavaVersion.VERSION_17   // ✅ 通过 java extension 配置
}
```

另一个高频差异：

```kotlin
// Groovy
test {
    systemProperty 'key', 'value'
}

// Kotlin
tasks.test {
    systemProperty("key", "value")
}
// 或者（更推荐的懒配置写法）
tasks.withType<Test>().configureEach {
    systemProperty("key", "value")
}
```

**决策建议：**

| 场景 | 建议 |
|---|---|
| 新项目 | **Kotlin DSL**，没有例外 |
| 老项目用 Groovy 且能跑 | 别为了迁而迁，但**新增的脚本片段写 Kotlin 风格**（少用动态特性） |
| 老项目要重构构建逻辑 | 趁机一起迁。Gradle 官方有 Groovy→Kotlin 的迁移指南，机械翻译部分可以靠工具 |
| 团队里没人写过 Kotlin | 仍然建议 Kotlin DSL。构建脚本用到的 Kotlin 语法非常有限，两小时能上手 |

**更深一层：这是一次"用类型系统换取可维护性"的交易，跟本书主线完全一致。**

回看第 00 章那条主线：**Go 倾向编译期确定性，Java 倾向运行时灵活性**。有意思的是，在构建脚本这件事上，Gradle 社区主动选择了编译期——Kotlin DSL 取代 Groovy DSL、Version Catalog 取代字符串坐标、`strictly` 取代静默仲裁，**每一条都是"把运行时的意外提前成编译期的错误"**。

**为什么？** 因为构建脚本的特殊性：它是**低频修改、高破坏性**的代码。低频修改意味着你永远记不住语法（需要工具帮助），高破坏性意味着错了代价很大（需要编译器拦截）。这两条加一起，指向唯一答案：**静态类型 + 好 IDE。**

Go 在这一点上的对应物是 `go.mod`：纯数据格式，没有逻辑，所以工具能 100% 可靠地解析和改写它。**Go 的答案是"取消编程能力换工具可靠性"，Gradle 的答案是"保留编程能力但加类型"。** 两个答案都有效，取决于你认为构建脚本需要多少表达力。

</details>

---


## 06.5 Gradle Wrapper：为什么每个项目都带一个

每个 Gradle 项目的根目录下都有这四个东西：

```
gradlew                                  # Unix 启动脚本
gradlew.bat                              # Windows 启动脚本
gradle/wrapper/gradle-wrapper.jar        # 一个很小的 bootstrap jar
gradle/wrapper/gradle-wrapper.properties # 只有这个是需要你关心的
```

`gradle-wrapper.properties`：

```properties
distributionUrl=https\://services.gradle.org/distributions/gradle-8.7-bin.zip
distributionSha256Sum=...                # 可选，但强烈建议有，防篡改
networkTimeout=10000
validateDistributionUrl=true
```

跑 `./gradlew build` 时，wrapper 做一件事：**检查这个版本的 Gradle 在不在 `~/.gradle/wrapper/dists/` 里，不在就下载，然后用它跑构建。**

> 【思考】为什么不能直接装一个全局 gradle，每个人自己管版本？
>
> 对比一下 Go：`go.mod` 里有 `go 1.21` 这一行，但 Go 项目里没有任何"wrapper"文件。为什么 Go 不需要？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 Gradle 不向后兼容，而"构建工具版本不一致"的失败方式极其难查。Wrapper 是 Java 生态用来解决"工具链版本漂移"的外部机制——而 Go 把这件事内建进了语言工具。**

**先说 Gradle 为什么必须锁版本。**

Gradle 的主版本之间破坏性变更是常态：DSL 语法变、API 废弃、插件要求最低 Gradle 版本、默认行为变。一个真实的排查噩梦：

```
小王的机器：Gradle 8.7   → 构建成功
小李的机器：Gradle 7.6   → 构建失败：Could not find method versionCatalogs()
CI 机器：   Gradle 8.5   → 构建成功，但某个 Task 行为不同
```

**最可怕的不是"失败"，是"成功但行为不同"。** 比如不同 Gradle 版本的依赖仲裁细节、Task 的 up-to-date 判断、资源处理行为，都可能有细微差别。结果就是"在我机器上是好的"——这句话在 Java 团队里的出现频率，跟构建工具版本管理的严格程度成反比。

**Wrapper 把版本变成了项目的一部分：** 版本写在 `gradle-wrapper.properties` 里，跟着 git 走，所有人、所有 CI 用同一个。升级是**一次提交**（`./gradlew wrapper --gradle-version 8.11`），有 review、有回滚、有历史。

**升级 wrapper 的正确姿势：**

```bash
./gradlew wrapper --gradle-version 8.11      # 改 properties + 重新下载 wrapper jar
./gradlew wrapper --gradle-version 8.11 --distribution-type all   # 带源码版，IDE 跳转更好用
git diff gradle/wrapper/gradle-wrapper.properties                 # 确认改了什么
./gradlew --version                          # 验证
```

**顺带一条安全建议：** 在 `gradle-wrapper.properties` 里保留 `distributionSha256Sum`。Wrapper 下载发行版时会校验哈希，防止中间人替换。CI 上尤其重要。

---

**现在看 Go —— 为什么它不需要 wrapper？**

```go
// go.mod
module github.com/example/order-service

go 1.21        // ← 这一行声明了语言版本

require (
    github.com/gin-gonic/gin v1.9.1
)
```

Go 的处理方式：

1. **`go 1.21` 这一行是"最低语言版本"声明**，由 `go` 命令自己解释。你用 Go 1.22 的工具链去构建声明了 `go 1.21` 的项目，完全没问题。
2. **工具链版本漂移由 Go 自己处理。** Go 1.21 起加入了**工具链切换（toolchain switching）**：如果 `go.mod` 里写了 `go 1.22.0` 而你本地装的是 1.21，`go` 命令会**自动下载并使用 1.22.0** 来构建。这个行为内置在 `go` 命令里。
3. **没有插件生态需要匹配版本。** Go 的构建没有"插件"概念——没有 Maven 插件、没有 Gradle 插件，所以不存在"插件要求构建工具 >= X 版本"这类约束矩阵。

```bash
# Go 1.21+ 的工具链管理（内建，不需要任何 wrapper 文件）
GOTOOLCHAIN=go1.22.0 go build     # 临时指定
go mod edit -toolchain go1.22.0   # 写进 go.mod，团队共享
```

**所以对比是这样的：**

| | Go | Java（Gradle/Maven） |
|---|---|---|
| 工具版本声明 | `go.mod` 里的 `go` / `toolchain` 指令 | Gradle：wrapper properties；Maven：`mvnw` |
| 谁来下载正确版本 | **`go` 命令自己**（内建 toolchain switching） | **一个外部脚本**（gradlew / mvnw） |
| 仓库里多几个文件 | 0 个 | 4 个（gradlew, gradlew.bat, wrapper jar, properties） |
| 版本不一致时 | go 命令自动切换，**用户无感** | 构建失败或行为不同，**用户要自己发现** |
| 为什么能这样 | Go 没有插件生态，构建行为由 go 命令定义 | Java 的构建行为由插件定义，插件和工具版本强耦合 |

**核心差别在最后一行：Go 把构建行为的规范写进了 `go` 命令，Java 把它外包给了插件。**

一旦构建行为由插件定义，你就必然面对一个二维兼容矩阵：`(构建工具版本) × (插件版本)`。这个矩阵必须有东西来钉住——Gradle 的答案是 wrapper 钉工具版本 + Version Catalog 钉插件版本。**Maven 也有 wrapper（`mvnw`），但用得少得多，因为 Maven 的向后兼容性做得比 Gradle 好，且 pom.xml 的 schema 二十年基本没变。**

**更深一层：这是"内建 vs 外部机制"的又一个实例，跟 06.1 节那个增量构建的对照是同一个模式。**

Go 的做法是**把必需的机制做进语言工具**：构建缓存内建、工具链版本管理内建、依赖锁定内建（`go.sum`）、格式化内建（`gofmt`）、测试内建（`go test`）。用户没有选择权，也就没有配错的机会。

Java 生态的做法是**把机制留给外部工具**：缓存要配 Build Cache、版本要 wrapper、锁要 `gradle.lockfile`（得主动开）、格式化要 Spotless、测试要 JUnit + surefire。每个都有多个竞争方案，每个都要选型、配置、维护。

**代价是配置负担和"选择疲劳"；收益是你能为每个环节选最合适的方案。** 这不是"Go 更先进"，是"Go 服务的场景更窄，所以敢做减法"。Go 只需服务"编译 Go 代码成一个二进制"，Java 要服务 jar/war/ear/fat jar/native image、Java/Kotlin/Scala/Groovy、Android、代码生成、字节码增强、多产物发布——**问题域本身的复杂度决定了工具链必须可组合。**

</details>

### distributionUrl 下载慢怎么办

`services.gradle.org` 在国内经常很慢或超时。三个方案，从简到繁：

**方案一：换成国内镜像（个人最快）**

```properties
# 腾讯云
distributionUrl=https\://mirrors.cloud.tencent.com/gradle/gradle-8.7-bin.zip
# 或者阿里云
distributionUrl=https\://mirrors.aliyun.com/macports/distfiles/gradle/gradle-8.7-bin.zip
```

**方案二：用 `-all` 分发包换取 IDE 体验**

```properties
distributionUrl=https\://services.gradle.org/distributions/gradle-8.7-all.zip
```

`-all` 版（约 200MB）带 Gradle 源码和文档，IDE 里 Ctrl+点击能跳进 Gradle 自身的 API 源码。**写复杂构建逻辑或自定义插件时，这个体验差别很大。** 日常 `-bin`（约 130MB）够了。

**方案三：企业内网放一份（团队正解）**

```properties
distributionUrl=https\://nexus.internal.example.com/gradle/gradle-8.7-bin.zip
```

把分发包传一份到自己的 Nexus/Artifactory 或者内网静态服务器上，wrapper 的 URL 指过去。**这样 CI 不依赖外网，且下载是内网速度。** 注意保留 `distributionSha256Sum`，保证内网那份跟官方一致。

**排查技巧：** wrapper 下载卡住时，去看 `~/.gradle/wrapper/dists/gradle-8.7-bin/<hash>/` 目录，里面会有 `.part` 文件和 `.lck` 锁文件。删掉整个目录重来即可——这跟第 05 章讲的 Maven `.lastUpdated` 是同一类问题。

---


## 06.6 多模块与复合构建

### settings.gradle.kts 的 include

```kotlin
rootProject.name = "order-service"

include("order-api")
include("order-core")
include("order-dal")
include("order-web")
```

**对照 Maven：** 这是 `<modules>`（聚合）的等价物。但**注意 Gradle 没有 `<parent>` 继承这个机制**——Gradle 里没有"父 pom 继承配置"这回事，共享配置靠**插件**和**约定**（下面讲）。

这个差别很重要：Maven 里子模块"天然继承"父 pom 的一切（属性、依赖管理、插件管理），代价是你必须理解 effective pom 才知道最终配置。Gradle 里子模块**默认什么都不继承**——根项目的配置要显式用 `allprojects {}` / `subprojects {}` 注入，或者更好，**抽成插件再 apply**。

### 跨项目共享构建逻辑：三种粒度

**粒度一：`buildSrc` 目录**

```
order-service/
├── buildSrc/
│   ├── build.gradle.kts        # buildSrc 自己是个独立构建
│   └── src/main/kotlin/
│       ├── java-conventions.gradle.kts    # 约定插件
│       └── Version.kt                      # 共享的 Kotlin 代码
├── settings.gradle.kts
└── order-core/build.gradle.kts
```

```kotlin
// buildSrc/build.gradle.kts
plugins {
    `kotlin-dsl`     // 让 buildSrc 里的 .gradle.kts 能被当作插件用
}

repositories {
    mavenCentral()
}
```

```kotlin
// buildSrc/src/main/kotlin/java-conventions.gradle.kts
plugins {
    `java-library`
}

java {
    toolchain { languageVersion.set(JavaLanguageVersion.of(17)) }
}

dependencies {
    testImplementation("org.junit.jupiter:junit-jupiter:5.10.1")
}

tasks.withType<Test>().configureEach {
    useJUnitPlatform()
}
```

```kotlin
// order-core/build.gradle.kts
plugins {
    id("java-conventions")    // ← 应用约定插件，拿到上面所有配置
}
```

**这就是 Gradle 版的"parent pom"**，但粒度是**插件级**的：一个模块可以 apply 多个约定插件（`java-conventions`、`spring-boot-conventions`、`publish-conventions`），自由组合。Maven 只能单继承一个 parent。

**粒度二：约定插件（convention plugins）—— 就是上面那个东西**

命名习惯是 `xxx-conventions.gradle.kts`。好处：

- **真正的代码**，有编译期检查，能跳转
- **可组合**，比单继承灵活
- **可测试**，能用 TestKit 写构建逻辑的测试

**粒度三：`includeBuild` 复合构建**

```kotlin
// settings.gradle.kts
plugins {
    id("gradle-enterprise") version "3.16"
}

includeBuild("../company-build-logic")    // 引入另一个独立的 Gradle 构建
includeBuild("../order-sdk")
```

复合构建解决的是"**跨仓库**共享构建逻辑"和"**本地联调依赖**"：

```kotlin
// 把对某个外部模块的依赖替换成本地源码
includeBuild("../order-sdk") {
    dependencySubstitution {
        substitute(module("com.example:order-sdk")).using(project(":order-sdk"))
    }
}
```

**这是 Gradle 相对 Maven 的一个杀手级能力**：你改 SDK 的代码，主项目立刻用上，不需要 `mvn install` 到本地仓库。Go 里的等价物是 `go.mod` 的 `replace` 指令——**思想一样，但 Gradle 的实现更复杂（因为它要处理插件、Task 图、产物类型），而 Go 的 `replace` 就是改个路径。**

| 需求 | Maven | Gradle | Go |
|---|---|---|---|
| 同仓库多模块 | `<modules>` + `<parent>` | `include` + 约定插件 | 多个 `go.mod`，无继承 |
| 同仓库共享配置 | parent pom 继承 | `buildSrc` / 约定插件 | 无（宁可重复） |
| 跨仓库共享构建逻辑 | 发布一个 parent pom 到私服 | `includeBuild` 复合构建 | 无（配置不共享） |
| 本地联调依赖 | `mvn install` 装到本地仓库 | `includeBuild` + 依赖替换 | `replace` 指令 |
| 复用粒度 | 整体继承 | **插件级，可组合** | 无 |

> 【思考】`buildSrc` 里写的代码，改了之后会发生什么？
>
> 提示：buildSrc 是一个"独立的构建"，它会被编译，产物被加入主构建的 classpath。

<details>
<summary><b>参考答案</b></summary>

**直接答案：改 buildSrc 里的任何一行代码，都会触发 buildSrc 的重新编译，然后导致整个项目的构建脚本全部重新编译和重新执行（Configuration 阶段全量重来）。这是 Gradle 构建"莫名其妙变慢"的一个极常见原因。**

**完整链条：**

```
你改了 buildSrc/src/main/kotlin/java-conventions.gradle.kts
    ↓
Gradle 检测到 buildSrc 的输出变了
    ↓
重新编译 buildSrc（这是个独立的 Gradle 构建，有自己的 configuration + execution）
    ↓
buildSrc 产出的 class 加入主构建脚本的 classpath
    ↓
classpath 变了 → 所有 build.gradle.kts 的编译缓存失效
    ↓
所有构建脚本重新编译（Kotlin 脚本编译不便宜）
    ↓
Configuration 阶段全量重来（Configuration Cache 也失效了，因为输入变了）
    ↓
你只是想跑个测试，结果等了一分钟
```

**这解释了一个很多人困惑的现象：为什么我在业务代码里改一行跑一次只要 2 秒，但改了 buildSrc 一行就要 60 秒？** 因为前者只影响 Execution 阶段的一个 Task，后者让整个"配置"层全部作废。

**实践建议（按优先级）：**

1. **buildSrc 里只放构建逻辑，不放业务逻辑，也不要在里面做 IO。** 一条通用的编译配置、一个自定义 Task 类、一个版本常量——这些合适。读文件、发 HTTP、跑 git 命令——不合适。
2. **buildSrc 的依赖要精简。** 你在 `buildSrc/build.gradle.kts` 里加的每个依赖，都会进入构建脚本的 classpath，增加编译时间。
3. **约定插件按"变更频率"拆分。** 把"一年改一次"的（Java 版本、编码）和"一周改三次"的（依赖版本）分开，后者改用 Version Catalog（`gradle/libs.versions.toml`）而不是写死在 buildSrc 里。这是 Gradle 官方的建议，理由就是**改 TOML 不会触发 buildSrc 重编译**。
4. **稳定后考虑把 buildSrc 独立成复合构建（`includeBuild`）。** 这样它有自己的构建缓存，跨仓库也能用。代价是配置复杂一点。

**代码锚点 —— 怎么确认时间花在 buildSrc 上了：**

```bash
./gradlew build --dry-run     # 只走配置阶段，看耗时
# 然后 touch 一下 buildSrc 里的文件，再跑一次
touch buildSrc/src/main/kotlin/java-conventions.gradle.kts
./gradlew build --dry-run     # 对比两次耗时

./gradlew build --scan        # Build Scan 里能看到 buildSrc 的编译单独计时
```

如果你发现第二次明显更慢，那就是它了。

**更深一层：这是"构建脚本即代码"的另一个隐藏账单。**

Maven 的 parent pom 是纯数据，改了之后子模块只是重新解析 XML，成本极低。Gradle 的构建逻辑是**要编译的代码**，所以有一整套"代码"才会有的开销：编译、classpath 失效传播、缓存失效传播。

**Gradle 一直在补这个洞：** Kotlin DSL 的脚本编译避免（script compilation avoidance）、Configuration Cache、以及最新几个版本里对 Kotlin 脚本编译的专门优化（Gradle 9 明确提到"better Kotlin DSL script compilation avoidance"）。这些优化的边际收益都很高，但它们是在补一个**由核心设计决定**的成本。

**对照 Go，为什么没有这个问题？** 因为 Go 根本没有"可编程的构建配置"这一层。`go.mod` 是数据，改了就是重新解析，没有编译步骤，没有 classpath 失效传播。**Go 用"不能编程"换来了"配置层零开销"。**

**这个对照值得反复咀嚼：** Gradle 的每一次慢，几乎都能追溯到"构建脚本是代码"这个决定的某个后果——配置阶段要执行、脚本要编译、classpath 变化要传播、缓存要能序列化整个 Task 图。而 Maven 的每一次别扭，也都能追溯到"构建脚本不是代码"——想加个条件逻辑都要绕道 profile。

</details>

---


