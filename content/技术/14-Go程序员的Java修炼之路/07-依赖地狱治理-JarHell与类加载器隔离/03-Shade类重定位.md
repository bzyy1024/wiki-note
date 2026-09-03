# 第 07 章（节选）　Shade类重定位

> 本篇来自《Go 程序员的 Java 修炼之路》第 07 章「第 07 章　依赖地狱治理：Jar Hell、ClassLoader 与 Shade（NoSuchMethodError 的三种死法）」。
> 返回：[第 07 章索引](./README.md)

## 07.4 Shade 与类重定位：把冲突"物理隔离"

### 问题场景

你的服务依赖 A（要 Guava 20）和 B（要 Guava 32）：

- Guava 20 里没有 `MoreObjects.firstNonNull` 之后的某个新方法 → A 调用它 → `NoSuchMethodError`
- Guava 32 删了某个老方法 → B 调用它 → `NoSuchMethodError`
- **两个版本你都得留着**

统一版本（BOM / dependencyManagement）在这里失效了 —— 没有任何单一版本能同时满足 A 和 B。剩下两条路：**ClassLoader 隔离**（07.3）和 **Shade 重定位**（本节）。

### Shade 的原理（呼应第 00 章那道思考题）

三步，缺一不可：

**第 1 步：把目标依赖的 class 文件改名。**

```
com/google/common/base/Preconditions.class
        ↓
com/example/shaded/guava/base/Preconditions.class
```

**第 2 步（最关键）：同时修改所有引用这些类的字节码。**

这里改的是 class 文件**常量池里的符号引用** —— `CONSTANT_Class`、`CONSTANT_Methodref`、`CONSTANT_Fieldref`。比如 A 的字节码里有一条 `invokevirtual #42 // Method com/google/common/base/Preconditions.checkArgument:(Z)V`，Shade 把 `#42` 指向的类名字符串改掉。

**第 3 步：打成一个 jar（uber-jar / fat jar）。**

**问题 3：** 为什么第 2 步不能省？只改文件名会怎样？

只改文件名，A 的字节码里还写着"我要 `com.google.common.base.Preconditions`" —— 加载时按老名字找，找到的是**你没改的那份**（或者找不到）。**重定位的难点从来不是改名，是改引用。**

### `maven-shade-plugin` 完整配置

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-shade-plugin</artifactId>
    <version>3.5.1</version>
    <executions>
        <execution>
            <id>shade-guava</id>
            <phase>package</phase>
            <goals><goal>shade</goal></goals>
            <configuration>
                <!-- 是否生成 dependency-reduced-pom.xml 并替换项目 pom -->
                <createDependencyReducedPom>true</createDependencyReducedPom>

                <relocations>
                    <relocation>
                        <pattern>com.google.common</pattern>
                        <shadedPattern>com.example.order.shaded.guava</shadedPattern>
                        <!-- 可选：只重定位匹配的类，其余放过 -->
                        <!-- <includes><include>com.google.common.base.*</include></includes> -->
                    </relocation>
                </relocations>

                <filters>
                    <!-- 坑一：签名文件。重定位后类内容变了，签名失效 → SecurityException -->
                    <filter>
                        <artifact>*:*</artifact>
                        <excludes>
                            <exclude>META-INF/*.SF</exclude>
                            <exclude>META-INF/*.DSA</exclude>
                            <exclude>META-INF/*.RSA</exclude>
                        </excludes>
                    </filter>
                </filters>

                <transformers>
                    <!-- 坑二：SPI 文件里的类名不会被自动重定位，需要这个 transformer -->
                    <transformer implementation=
                        "org.apache.maven.plugins.shade.resource.ServicesResourceTransformer"/>
                    <!-- 坑三：多个 jar 的同名资源会互相覆盖，用 AppendingTransformer 合并 -->
                    <transformer implementation=
                        "org.apache.maven.plugins.shade.resource.AppendingTransformer">
                        <resource>META-INF/spring.handlers</resource>
                    </transformer>
                    <transformer implementation=
                        "org.apache.maven.plugins.shade.resource.AppendingTransformer">
                        <resource>META-INF/spring.schemas</resource>
                    </transformer>
                    <!-- 指定 main class -->
                    <transformer implementation=
                        "org.apache.maven.plugins.shade.resource.ManifestResourceTransformer">
                        <mainClass>com.example.order.OrderApplication</mainClass>
                    </transformer>
                </transformers>
            </configuration>
        </execution>
    </executions>
</plugin>
```

**三个配置项要理解清楚：**

| 配置 | 作用 | 什么时候改 |
|---|---|---|
| `<createDependencyReducedPom>` | 默认 `true`。生成一个 `dependency-reduced-pom.xml`，**把被 shade 进去的依赖从依赖列表里删掉**，并安装进本地仓库 | **发布的是库** → 保持 `true`（否则使用者的依赖树被污染）；**发布的是应用** → 通常改 `false`，避免莫名其妙的问题 |
| `<filters>` | 排除签名文件 | 依赖里有签名 jar（如 `javax.servlet-api`、bouncycastle）时**必须配**，否则运行时 `SecurityException: invalid signature file digest for Manifest main attributes` |
| `<transformers>` | 合并/改写资源文件 | 见下面"Shade 的其他坑" |

> 【思考】Shade 之后，A 库里的 `Preconditions.class.getName()` 返回什么？如果 A 库里有一行 `Class.forName("com.google.common.base.Preconditions")`，会怎样？
>
> 提示：想想 Shade 改的是字节码里的什么结构，而 `Class.forName` 的参数又是什么。

<details>
<summary><b>参考答案</b></summary>

**第一问：`getName()` 返回重定位后的名字。**

```java
// shade 前
System.out.println(Preconditions.class.getName());
// com.google.common.base.Preconditions

// shade 后（relocation: com.google.common → com.example.order.shaded.guava）
System.out.println(Preconditions.class.getName());
// com.example.order.shaded.guava.base.Preconditions
```

为什么？因为 `getName()` 读的是运行时 `Class` 对象里存的**真实类名**，而这个类**就是**被改过名的那一个 —— 它的 class 文件里 `this_class` 字段已经是新名字了。所以 **`getName()`、`getSimpleName()`、异常栈里打印的类名、日志里 `%C`/`%logger` 输出的，全都是新名字**。

这带来一个实际问题：**你的日志和监控会变得难认。** 一搜 `com.google.common` 搜不到，得搜 shaded 前缀。这也是为什么成熟的 shade 配置会把 shadedPattern 定得很显眼（`com.mycompany.shaded.xxx`），而不是塞进某个不相关的包下。

**第二问：`Class.forName("com.google.common.base.Preconditions")` 会抛 `ClassNotFoundException`。**

**这是 Shade 最经典的坑，也是"有些库 shade 之后会挂"的头号原因。**

原因很简单，但要看清楚才印象深刻：

```java
// A 库的源码里
Class<?> c = Class.forName("com.google.common.base.Preconditions");
```

编译后的字节码里，这个字符串躺在**常量池的 `CONSTANT_String` 项**里，被 `ldc` 指令加载。对它来说，这就是**一段普通字符串** —— 跟 `String s = "hello"` 没有任何区别。

Shade 能做的是改写**结构化**的符号引用：

| 常量池项 | 是什么 | Shade 会改吗 |
|---|---|---|
| `CONSTANT_Class` | 类/接口的符号引用 | **会改**（这是重定位的核心） |
| `CONSTANT_Methodref` / `Fieldref` | 方法/字段引用，内含类名 | **会改** |
| `CONSTANT_NameAndType` | 方法名 + 描述符 | 会按类型改 |
| `CONSTANT_String` | **任意字符串字面量** | **不保证改** —— 它无法判断这个字符串"是不是类名" |

所以 Shade 会在**语义层面**改写"我引用了这个类"，但改不了"我的业务逻辑里恰好有一段字符串长得像类名"。

**哪些代码会踩这个坑：**

```java
Class.forName("com.google.common.base.Preconditions");        // 反射加载
Class.forName(Config.getString("guava.adapter"));             // 配置里的类名 —— 双杀，连字符串都在 jar 外面
obj.getClass().getMethod("doIt").invoke(obj);                 // 这个没问题（不用字符串）
serviceLoader.load(Driver.class);                             // SPI，靠资源文件 —— 见下个坑
Serializer.deserialize(bytes);                                // 序列化，类名写死在字节流里
```

**代码锚点 —— 验证方法：**

```bash
# shade 之后，用 javap 看常量池里的字符串有没有被改
javap -c -p -constants target/app.jar \
  | grep -n "com.google.common"       # 如果还能搜到，说明有漏网的反射引用

# 更直接：看 jar 里还有没有老包路径
jar tf target/app.jar | grep "com/google/common"    # 应该一行都没有
```

**规避方案（按推荐度排序）：**

1. **优先选不用反射的库。** 这是选型阶段就该问的问题
2. **用 `<relocation>` 的 `<includes>` 缩小范围** —— 只重定位必要的类，减少踩雷面积
3. **配合 `maven-replacer-plugin`** 手动改配置文件里的类名字符串（笨但有效）
4. **换成 ClassLoader 隔离**（07.3）—— 不改字节码，反射天然可用

**更深一层：这暴露了 Shade 的本质 —— 它是一种"语法层"的重命名，不是"语义层"的隔离。**

语法层的意思是：它处理的是**编译器能静态确定的符号**（类名、方法签名、字段描述符）。运行时才确定的东西 —— 字符串类名、反射、`MethodHandle`、序列化字节流、JNI 的 `FindClass`、注解里的 `Class<?>` 值 —— 都在它的能力之外。

**对照 Go**：Go 的静态链接是**语义层**的隔离。链接器看到的是完整的符号表，不存在"一段字符串恰好是符号名"这种歧义 —— 因为反射在 Go 里拿到的也是编译期就确定好的类型信息。

**所以判断一个库能不能 shade，本质上是在问：它有多少行为是在运行时才决定"用哪个类"的？** 反射密集的框架（Spring、Hibernate、Jackson 的某些模块）shade 风险高；纯计算型库（Guava、commons-lang3、Netty 的 buffer 部分）shade 风险低。

</details>

### Shade 的其他坑（清单收好）

| 坑 | 现象 | 解法 |
|---|---|---|
| **签名失效** | `SecurityException: invalid signature file digest` | `<filters>` 排除 `META-INF/*.SF`、`.DSA`、`.RSA` |
| **SPI 文件类名不重定位** | 服务加载失败，`No implementations found` | `ServicesResourceTransformer` |
| **同名资源互相覆盖** | Spring 自动配置失效、`spring.handlers` 只剩一份 | `AppendingTransformer`（注意：Spring Boot 2.x 的 `META-INF/spring.factories` 也要合并） |
| **jar 体积膨胀** | 一个 5MB 的应用变成 80MB | `<minimizeJar>`（**危险** —— 靠静态分析删类，会删掉反射用到的类）；更好的做法是只 shade 真正冲突的那几个依赖 |
| **构建变慢** | 每次 package 要重写所有 class 的常量池 | 只在需要 shade 的模块上开，不要全项目开 |
| **栈信息难读** | 异常栈里全是 `com.mycompany.shaded.xxx` | 无解，只能靠命名规范缓解 |
| **minimizeJar 删了反射用到的类** | 运行时 `ClassNotFoundException`，且只在某条分支 | **别开 minimizeJar**，或者开了就全量回归测试 |

### 什么时候该用 Shade，什么时候不该用

**该用：**

1. **你发布的是一个库，给外部用，且不希望污染使用者的依赖树。** 使用者可能是另一个大型应用，你塞一个 Guava 20 进去会破坏他整个依赖树 —— 这时候 shade 是**礼貌**
2. **你需要一个"自包含"的可执行包**，且目标环境不可控（比如要交给客户本地部署）
3. **确实存在无法用统一版本解决的冲突**（A 要 v1 的删除方法、B 要 v2 的新方法）

**不该用：**

1. **应用内部的依赖冲突** → 用 `dependencyManagement` 统一版本（第 05 章方案 C）
2. **仅仅为了"打个 fat jar"** → 用 Spring Boot 的 `spring-boot-maven-plugin`（07.5），它没这些坑
3. **反射密集的库**（Spring、Hibernate、Jackson 的 databind）→ shade 风险远大于收益

> 【思考】为什么 Kafka、Elasticsearch、Flink 这些大数据组件历史上都重度使用 Shade？
>
> 提示：从"它们的代码运行在谁的 JVM 里"这个角度想。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为它们的代码要跑在**用户**的 JVM 里，而用户的 classpath 完全不受它们控制。**

**先看清这个处境跟普通应用开发者的区别：**

| | 应用开发者 | 大数据组件作者 |
|---|---|---|
| 代码跑在哪 | 自己的服务里，classpath 自己说了算 | 用户的集群里，classpath 由用户决定 |
| 能不能要求用户配 dependencyManagement | 能（就是自己的项目） | **不能** —— 用户根本不会为你的库改依赖树 |
| 依赖冲突了谁改 | 自己改，改完发版 | 用户改不了，只能换组件版本或者弃用 |
| 冲突的后果 | 自己线上炸 | 用户线上炸，**但用户会认为是你的组件的锅** |

Kafka client 要进用户的 JVM，而用户的 JVM 里可能已经有：Flink 的 Kafka connector、Spark 的某个包、用户自己的业务代码引入的 Jackson/Guava/Netty……**你在跟全世界的所有版本组合做兼容测试，而你无法拒绝其中任何一个。**

**Shade 是唯一能"无视对方 classpath"的方案** —— 因为重定位后，你的类在自己的命名空间里，跟用户 classpath 上的同名类根本不是同一个类。

**具体例子（这些都是真实的）：**

```xml
<!-- Flink 的 pom 里（简化） -->
<relocation>
    <pattern>com.google.common</pattern>
    <shadedPattern>org.apache.flink.shaded.guava30</shadedPattern>
    <!-- 注意 shadedPattern 里连版本号都带上了 -->
</relocation>
<relocation>
    <pattern>org.apache.commons</pattern>
    <shadedPattern>org.apache.flink.shaded.commons</shadedPattern>
</relocation>
```

**注意 `guava30` 里的那个 `30`** —— 这是一条很有价值的工程经验：**把版本号编码进 shaded pattern**。这样当 Flink 内部有模块之间要区分"我用的是 shade 的 guava 30 还是 guava 18"时，从包名就能看出来。这是从 Go 的 `/v2` 后缀借的思路（07.3 那道思考题）。

Elasticsearch 更极端：它 shade 了 Lucene（它的核心依赖），因为 Lucene 版本迭代快、API 破坏性变更多，而用户集群里几乎必然有别的组件依赖了不同版本的 Lucene。

**代码锚点 —— 库作者的典型 shade 策略（跟应用开发者完全不同）：**

```xml
<configuration>
    <createDependencyReducedPom>true</createDependencyReducedPom>  <!-- 关键！ -->
    <promoteTransitiveDependencies>true</promoteTransitiveDependencies>
    <relocations>
        <relocation>
            <pattern>com.fasterxml.jackson</pattern>
            <shadedPattern>com.mycorp.sdk.shaded.jackson</shadedPattern>
        </relocation>
    </relocations>
</configuration>
```

`createDependencyReducedPom=true` 在这里是**必须**的：它把被 shade 进去的依赖从 pom 的依赖列表里删掉。否则使用者 `mvn dependency:tree` 时会看到你引了 jackson 2.9，而 Maven 可能据此把他的 jackson 仲裁成 2.9 —— **你不但没隔离，反而污染了他的依赖树**。

**更深一层：这是"库作者"和"应用开发者"两种视角的根本差异。**

- **应用开发者**看到依赖冲突，第一反应是"统一版本" —— 因为你控制整个 classpath，统一是最省事的解法
- **库作者**没法统一，因为他只有 classpath 的一部分。他只能**把自己隔离出去**，代价是包变大、栈变丑、反射风险

**这个差异也解释了一个你迟早会遇到的现象：为什么有些 SDK 文档里明确写着"请不要在你的项目里显式依赖 Guava/Jackson，我们用 shade 的版本"。** 因为一旦你显式声明，nearest wins（深度 1）会覆盖它自己的传递依赖 —— 它的 shade 隔离就白做了，还可能引发"SDK 内部用的是 shaded 版本、你的代码用的是原生版本"这种割裂状态。

**给 Go 程序员的对照**：Go 里没有这个区分，因为**静态链接让"库作者"和"应用开发者"面对同一个模型** —— 所有符号在编译期解析，不存在"我的类会污染别人的 classpath"这种事。Go 的库作者只需要在意 API 兼容性，不需要在意"依赖隔离"。

**Java 的库作者要多操心一整层 —— 这也是为什么 Java 生态里"写一个高质量的库"比 Go 难得多。**

</details>

---


