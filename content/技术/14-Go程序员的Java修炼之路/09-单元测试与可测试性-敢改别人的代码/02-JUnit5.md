# 第 09 章（节选）　JUnit5

> 本篇来自《Go 程序员的 Java 修炼之路》第 09 章「第 09 章　单元测试与可测试性：敢改别人的代码」。
> 返回：[第 09 章索引](./README.md)

## 09.2 JUnit 5：不只是"能跑测试"

### 从 JUnit 4 到 5 的迁移

老项目里你会看到大量 JUnit 4 的写法。迁移对照：

| JUnit 4 | JUnit 5 | 说明 |
|---|---|---|
| `@RunWith(MockitoJUnitRunner.class)` | `@ExtendWith(MockitoExtension.class)` | 扩展模型换了 |
| `@Before` / `@After` | `@BeforeEach` / `@AfterEach` | 每个测试方法前后 |
| `@BeforeClass` / `@AfterClass` | `@BeforeAll` / `@AfterAll` | 类级别，方法要 `static` |
| `@Ignore` | `@Disabled` | 跳过 |
| `@Rule` / `@ClassRule` | `Extension` 接口 | 规则变成扩展 |
| `@Test(expected = Xxx.class)` | `assertThrows(Xxx.class, () -> ...)` | 期望异常改成断言 |
| `@Test(timeout = 1000)` | `@Timeout(1)` 或 `assertTimeout` | 超时 |
| `@RunWith(SpringRunner.class)` | `@ExtendWith(SpringExtension.class)` / `@SpringBootTest` | Spring 侧 |

**注意 `@Test` 的包名变了**：JUnit 4 是 `org.junit.Test`，JUnit 5 是 `org.junit.jupiter.api.Test`。import 错了会得到一个"这个注解不允许加在方法上"的诡异报错。老项目迁移时最常见的翻车点就是这个，以及 `@RunWith` 和 `@ExtendWith` 混用。

想在同一个项目里同时跑 JUnit 4 和 5 的老测试，加 **Vintage 引擎**（见下面的架构说明）。

### JUnit 5 的架构：Platform + Jupiter + Vintage

JUnit 5 不是一个库，是三个：

| 层 | artifact | 职责 |
|---|---|---|
| **Platform** | `junit-platform-launcher` / `-engine` / `-commons` | 定义"测试引擎"的 SPI，负责发现和执行测试。IDE 和构建工具跟这一层打交道 |
| **Jupiter** | `junit-jupiter-api` / `-engine` / `-params` | 新的编程模型（就是 `@Test` 那套注解） |
| **Vintage** | `junit-vintage-engine` | 兼容层，让老 JUnit 3/4 的测试能跑在新平台上 |

**问题 5：** 为什么要拆成三层？一层不行吗？

因为 **JUnit 4 时代的一个致命设计缺陷：测试和框架绑死**。JUnit 4 里 `@RunWith(SpringRunner.class)` 这种写法，等于说"我的测试必须跑在 Spring 的 runner 里"，于是你没法同时用 Mockito 的 runner 和 Spring 的 runner（只能用 `@RunWith(MockitoJUnitRunner.class)` 加 `MockitoAnnotations.initMocks()` 这种 workaround）。

拆成 Platform + 引擎之后，**一个项目里可以同时挂多个引擎**：Jupiter 引擎跑新测试，Vintage 引擎跑老测试，Spock 引擎跑 Groovy 测试，Kotest 引擎跑 Kotlin 测试。IDE 只看 Platform，不管上面挂了什么。

**这也是为什么 Maven 里依赖叫 `junit-jupiter`（聚合包，含 api + params + engine）而不仅仅是一个 `junit`：**

```xml
<dependency>
    <groupId>org.junit.jupiter</groupId>
    <artifactId>junit-jupiter</artifactId>
    <scope>test</scope>          <!-- 05.4 讲过：test 不传递给下游 -->
</dependency>
```

### 核心注解清单

| 注解 | 作用 | 备注 |
|---|---|---|
| `@Test` | 标记测试方法 | 最基础，无参数 |
| `@ParameterizedTest` | 参数化测试，跑多组输入 | 必须配一个参数源 |
| `@RepeatedTest(n)` | 重复执行 n 次 | 测幂等性/并发用 |
| `@DisplayName("...")` | 给测试起人类可读的名字 | 支持中文，IDE 里显示 |
| `@Nested` | 内部类作为一组嵌套测试 | 天然的组织手段 |
| `@Tag("integration")` | 打标签，用于分组执行 | CI 里按标签筛 |
| `@Disabled("原因")` | 跳过，必须写原因 | |
| `@Timeout(5)` | 超时（默认**不**抢占式） | 见下文 |
| `@BeforeEach` / `@AfterEach` | 每个测试方法前后 | |
| `@BeforeAll` / `@AfterAll` | 整个测试类前后 | 方法必须 `static`（除非 `@TestInstance(PER_CLASS)`） |
| `@ExtendWith` | 注册扩展 | Mockito、Spring 都靠它 |
| `@TestInstance` | 控制测试实例的生命周期 | 默认每个方法一个新实例 |

**`@Nested` 值得单独说一句**，它是组织测试的神器：

```java
@DisplayName("订单金额计算")
class CalcAmountTest {
    @Nested @DisplayName("有优惠券时")
    class WithCoupon {
        @Test @DisplayName("满减券应该扣减")
        void 满减() { /* ... */ }
        @Test @DisplayName("折扣券不应超过订单金额")
        void 折扣上限() { /* ... */ }
    }
    @Nested @DisplayName("无优惠券时")
    class WithoutCoupon {
        @Test @DisplayName("按原价")
        void 原价() { /* ... */ }
    }
}
```

在 Go 里你靠 `t.Run("有优惠券时", func(t *testing.T){...})` 做同样的事。**两者的差别：Go 的子测试是运行时的一等对象（有返回值、可以 `t.Parallel()`），Java 的 `@Nested` 是编译期的类结构。** 各有好处：Go 更灵活，Java 在 IDE 里可以折叠、可以单独运行一个类。

### 参数化测试：JUnit 5 对表驱动测试的回应

这是 Go 程序员最关心的部分。先看 Go 的写法：

```go
func TestCalcAmount(t *testing.T) {
    tests := []struct {
        name   string
        items  []Item
        coupon *Coupon
        want   decimal.Decimal
    }{
        {"无优惠券", []Item{{Price: dec(100), Qty: 2}}, nil, dec(200)},
        {"满100减20", []Item{{Price: dec(100), Qty: 2}}, &Coupon{Full: 100, Cut: 20}, dec(180)},
        {"不满减门槛", []Item{{Price: dec(30), Qty: 2}},  &Coupon{Full: 100, Cut: 20}, dec(60)},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            got := calcAmount(tt.items, tt.coupon)
            if !got.Equal(tt.want) {
                t.Errorf("calcAmount() = %v, want %v", got, tt.want)
            }
        })
    }
}
```

再看 JUnit 5 的等价物，三种写法按复杂度递增：

**写法一：`@ValueSource` —— 只有单参数时用**

```java
@ParameterizedTest
@ValueSource(ints = {1, 2, 5, 10})
void 数量为正时金额随之增长(int qty) {
    assertThat(calcAmount(List.of(item(100, qty)), null))
        .isEqualByComparingTo(new BigDecimal("100").multiply(BigDecimal.valueOf(qty)));
}
```

**写法二：`@CsvSource` —— 多参数、简单类型，最像 Go 的表**

```java
@ParameterizedTest(name = "{0}")
@CsvSource({
    "无优惠券,    100, 2,   0, 200",
    "满100减20,   100, 2,  20, 180",
    "不满门槛,     30, 2,  20,  60"
})
void 计算订单金额(String name, int price, int qty, int cut, String expected) {
    Coupon coupon = cut == 0 ? null : new Coupon(new BigDecimal("100"), new BigDecimal(cut));
    BigDecimal got = calcAmount(List.of(item(price, qty)), coupon);
    assertThat(got).isEqualByComparingTo(new BigDecimal(expected));
}
```

`@CsvSource` 是最接近 Go 表驱动的写法，也是我最推荐的默认选项。注意 `name = "{0}"` —— 它让每个用例在 IDE 里显示成"满100减20"而不是"1, 2, 3"。**不写这个，测试失败时你看到的是 `[3] 100, 2, 20, 180`，完全不知道哪个用例挂了。**

**写法三：`@MethodSource` —— 参数类型复杂、需要构造对象时**

```java
static Stream<Arguments> 金额用例() {
    return Stream.of(
        Arguments.of("无优惠券", List.of(item(100, 2)), null,  new BigDecimal("200")),
        Arguments.of("满减",     List.of(item(100, 2)), cut20, new BigDecimal("180")),
        Arguments.of("超门槛",   List.of(item(30,  2)), cut20, new BigDecimal("60"))
    );
}

@ParameterizedTest(name = "{0}")
@MethodSource("金额用例")
void 计算订单金额(String name, List<OrderItem> items, Coupon coupon, BigDecimal expected) {
    assertThat(calcAmount(items, coupon)).isEqualByComparingTo(expected);
}
```

`@MethodSource` 引用的方法必须是 `static`，返回 `Stream<Arguments>`。类型安全，可以传任意对象，代价是最啰嗦。

**还有 `@EnumSource`（枚举全覆盖）和 `@ArgumentsSource`（自定义 Provider）**，用到再查。

> 【思考】Go 的表驱动测试写起来比 JUnit 5 简洁得多，为什么？
>
> 这是客观事实，不用护短。真正的问题是：这个"简洁"是从哪来的？Java 有没有办法更简洁？

<details>
<summary><b>参考答案</b></summary>

**直接答案：Go 的表驱动测试写法是"普通代码"，JUnit 5 的参数化测试是"注解驱动的元数据"。前者用语言本身的能力，后者用框架提供的 DSL。DSL 天然比普通代码受限。**

**Go 简洁的原因，靠的是三样语言级能力：**

1. **匿名结构体切片** —— `[]struct{ name string; want int }{...}`，不用先定义类型
2. **复合字面量** —— `{100, 2, 0, 200}` 按位置填值，不用写字段名
3. **`t.Run()` 是普通函数调用** —— 子测试就是闭包，可嵌套、可传参、可 `t.Parallel()`

关键在第 3 点：**Go 的测试就是普通 Go 代码**，`testing` 只是一个库，没有框架在背后驱动。

**Java 为什么做不到：**

- **没有匿名结构体。** 多组异构数据要么定义 `record`（Java 16+），要么用 `Arguments.of(...)` 这种 `Object...` 包装 —— 后者**丢掉类型安全**，参数顺序写错编译期不报错，运行时才 `ClassCastException`
- **注解只能是常量。** `@CsvSource` 每行必须是编译期字符串常量，不能写 `@CsvSource({calcCase()})`，所以复杂对象只能走 `@MethodSource` 那条静态方法的路
- **方法不是一等公民。** `t.Run(name, func)` 没有对应物，最接近的 `@Nested` 是**编译期的类结构**，不能运行时生成

**三条合起来就是必然的啰嗦。这是静态类型 + 注解元数据模型的代价，不是 JUnit 设计得差。**

**Java 有没有办法更简洁？有，三条路：**

**路一：用好 `record` + `@MethodSource`。** Java 16 之后这已经相当不错了：

```java
record AmountCase(String name, List<OrderItem> items, Coupon coupon, BigDecimal want) {}

static Stream<AmountCase> cases() {
    return Stream.of(
        new AmountCase("无优惠券", List.of(item(100, 2)), null,  new BigDecimal("200")),
        new AmountCase("满减",     List.of(item(100, 2)), cut20, new BigDecimal("180"))
    );
}

@ParameterizedTest
@MethodSource("cases")          // 方法名省略时默认找同名方法
void 计算金额(AmountCase c) {
    assertThat(calcAmount(c.items(), c.coupon())).isEqualByComparingTo(c.want());
}
```

**这一个 `record` 把类型安全拿回来了**，写起来也就比 Go 多几行。这是我推荐的默认写法。

**路二：换 JVM 语言写测试 —— Kotlin 的 Kotest。**

```kotlin
class CalcAmountTest : StringSpec({
    "无优惠券按原价" {
        calcAmount(listOf(item(100, 2)), null) shouldBe BigDecimal("200")
    }
}) 
```

或者用 Kotest 的 `withData` 做表驱动，语法比 Go 还紧凑。**这是 JVM 生态给你的一个真实选项：生产代码用 Java，测试用 Kotlin**（Maven 里配 kotlin-maven-plugin 就行，很多团队已经在这么干）。

**路三：接受它。** 参数化测试写起来多花那几分钟，在测试的生命周期里不算什么。**真正贵的不是"写"，是"读"和"改"** —— 而 JUnit 5 在"读"上不吃亏，`@CsvSource` 那张表一眼能看全。

**更深一层：这背后是"测试是代码还是配置"的哲学分歧。** Go 的回答斩钉截铁：**测试是代码**，所以 `testing` 只提供最小原语（`t.Errorf`/`t.Run`/`t.Parallel`），剩下全靠你写。表达力无上限，代价是**没有跨项目约定**。JUnit 的回答是**测试是声明**：有注解、有扩展模型、有 IDE 深度集成（点一个类就跑、失败用例可单独重跑）。工具链强、跨项目一致，代价是**表达力被框架 DSL 框住**。

**Java 选后者不是偶然 —— 它的重心是"大规模团队协作下的可维护性"，牺牲一点表达力换一致性，在这个语境下划算。**

</details>

### 断言：为什么你应该用 AssertJ

JUnit 5 自带 `org.junit.jupiter.api.Assertions`：

```java
assertEquals(expected, actual);
assertTrue(order.getAmount().compareTo(BigDecimal.ZERO) > 0);
assertThrows(BusinessException.class, () -> service.createOrder(badCmd));

// 分组断言：所有断言都跑一遍，一次性报出全部失败
assertAll("订单校验",
    () -> assertEquals(OrderStatus.CREATED, order.getStatus()),
    () -> assertEquals(0, order.getAmount().compareTo(new BigDecimal("199"))),
    () -> assertNotNull(order.getCreatedAt())
);

// 超时断言
assertTimeout(Duration.ofSeconds(1), () -> service.createOrder(cmd));
assertTimeoutPreemptively(Duration.ofSeconds(1), () -> service.createOrder(cmd));
```

**`assertTimeout` 和 `assertTimeoutPreemptively` 的差别是个真实的坑：**

- `assertTimeout` 在**当前线程**执行你的代码，超时了只是把测试标记为失败，**代码还在跑**。如果那段代码是个死循环，你的测试永远结束不了。
- `assertTimeoutPreemptively` 在**另一个线程**执行，超时就中断。但它有个反作用：**被中断的代码里如果持有锁或者改了共享状态，你的测试会变得诡异。**

默认用 `assertTimeout`。只有在测异步代码或者明确怀疑会 hang 住时才用 `assertTimeoutPreemptively`。

`@Timeout` 注解同理，默认不是抢占式的。

**但日常我建议你用 AssertJ：**

```java
import static org.assertj.core.api.Assertions.*;

// 流式断言：一个断言链写完所有条件，失败信息自动带上实际值
assertThat(order.getAmount())
    .isGreaterThan(BigDecimal.ZERO)
    .isLessThan(new BigDecimal("10000"));

// 集合断言
assertThat(orders)
    .hasSize(3)
    .extracting(Order::getStatus)
    .containsExactly(CREATED, CREATED, CANCELLED);

// 异常断言，还能接着断言异常内容
assertThatThrownBy(() -> service.createOrder(badCmd))
    .isInstanceOf(BusinessException.class)
    .hasMessageContaining("库存不足");
```

AssertJ 最大的价值不是"链式调用好看"，是**失败信息**。看对照：

```
# JUnit 原生
expected: <200> but was: <180>

# AssertJ
Expecting:
 <180>
to be equal to:
 <200>
but was not.
```

差别不大？看集合断言的差别就大了 —— JUnit 的 `assertEquals(list1, list2)` 失败时给你两个几百元素的 `toString()` 让你自己 diff；AssertJ 会告诉你"第 3 个元素不同，期望 X 实际 Y"。

> 【思考】断言失败信息该怎么写？
>
> 先想：凌晨三点，CI 红了，你看到一条 `expected: <200> but was: <180>`。你要花多久定位？
>
> 再想一个更具体的问题：`assertEquals(expected, actual)` 和 `assertEquals(actual, expected)`，参数顺序写反了会怎样？

<details>
<summary><b>参考答案</b></summary>

**直接答案：JUnit 的 `assertEquals(expected, actual)` 参数顺序写反了不会报错，但会把错误信息说反 —— 这是 Java 测试里最经典的低级错误之一，而且它藏得很深。**

**坏例子一：参数顺序**

```java
// 约定是 assertEquals(expected, actual)
assertEquals(200, order.getAmount());          // 对
assertEquals(order.getAmount(), 200);          // 反了，编译照样过
```

第二条报错时会说 `expected: <180> but was: <200>` —— **把期望值和实际值说反了**。你拿这个去看代码，会往完全相反的方向查。

编译器为什么拦不住？JUnit 有大量 `assertEquals(Object, Object)`、`assertEquals(int, int)` 这样的重载，两个参数类型一样，顺序反了类型检查也过。**这是 API 设计上的真 bug，JUnit 5 也没修（因为兼容性）。**

**坏例子二：没有上下文**

```java
assertTrue(order.getAmount().compareTo(BigDecimal.ZERO) > 0);
```

失败信息：`expected: <true> but was: <false>`。完了。**你不知道 amount 是多少、是哪个订单、这是第几个用例。**

**好例子一：AssertJ 的流式 API（推荐）**

```java
assertThat(order.getAmount())
    .as("订单 %s 的金额应该为正", order.getOrderNo())
    .isGreaterThan(BigDecimal.ZERO);
```

`.as()` 是 AssertJ 的描述，失败时打在最前面。用 `%s` 占位符而不是字符串拼接 —— **拼接在断言执行前就算好了，哪怕测试通过也要付字符串构造的成本**（微小，但几万个断言时可测量）。

**好例子二：JUnit 的 message 参数**

```java
assertEquals(200, order.getAmount(),
    () -> "订单 " + order.getOrderNo() + " 金额计算错误，用例=" + caseName);
```

**注意传的是 `Supplier<String>` 不是 `String`。** JUnit 5 提供了 `assertEquals(expected, actual, Supplier<String>)` 重载，Supplier 只在失败时求值 —— 跟 AssertJ 的 `%s` 是同一个优化：**别为成功路径付代价**。

**好例子三：BigDecimal 专用。** 金额比较永远用 `isEqualByComparingTo`，不要用 `isEqualTo` —— `new BigDecimal("200").equals(new BigDecimal("200.00"))` 返回 `false`，因为 `scale` 不同（0 vs 2），而 `compareTo` 忽略 scale。**这个坑在金额计算里一踩一个准。**

**代码锚点 —— 一个"好失败信息"长什么样：**

```java
assertThat(order.getAmount())
    .as("用户 %s 下单 SKU=%s 数量=%s，优惠券=%s",
        cmd.getUserId(), cmd.getSkuId(), cmd.getQty(), coupon)
    .isEqualByComparingTo(expected);
```

失败时你看到：

```
[用户 10086 下单 SKU=SKU-1 数量=3，优惠券=Coupon{id=99}]
Expecting:
 <180.00>
to be equal to:
 <200>
but was not.
```

**一行定位到具体数据。这就是"好"与"坏"的差距。**

**更深一层：断言失败信息不是"日志"，是给未来的自己（或者接盘的人）写的一份 bug 报告。**

写测试时你是全知全能的 —— 你知道每个分支、这个用例在测什么。但**读失败信息的人是瞎的**：他只有一行输出、一个栈，还可能是凌晨三点的脑子。

判断标准：**这条失败信息能不能让一个不了解这段代码的人直接开始查数据，而不是先花二十分钟搞清"这个断言在测啥"。**

**对照 Go**：Go 的 `t.Errorf("calcAmount() = %v, want %v", got, want)` 手写 message，本质跟 JUnit 的 Supplier 版一样。Testify 的 `assert.Equal(t, expected, actual)` 有同样的问题 —— **它也是 expected 在前，反了不报错**。这个坑是跨语言的，属于"参数顺序无法被类型系统约束"这个根本问题的表现。

</details>

### surefire：并行跑测试和分组执行

`maven-surefire-plugin` 是 Maven 跑测试的插件（05.7 提过）。三个常用配置：

```xml
<plugin>
    <artifactId>maven-surefire-plugin</artifactId>
    <version>3.2.5</version>
    <configuration>
        <!-- 只跑打了 integration 标签的（配合 excludes 用） -->
        <groups>unit</groups>
        <excludedGroups>integration</excludedGroups>
        <systemPropertyVariables>
            <!-- JUnit 5 的并行配置走系统属性 -->
            <junit.jupiter.execution.parallel.enabled>true</junit.jupiter.execution.parallel.enabled>
            <junit.jupiter.execution.parallel.mode.default>concurrent</junit.jupiter.execution.parallel.mode.default>
            <junit.jupiter.execution.parallel.config.strategy>fixed</junit.jupiter.execution.parallel.config.strategy>
            <junit.jupiter.execution.parallel.config.fixed.parallelism>4</junit.jupiter.execution.parallel.config.fixed.parallelism>
        </systemPropertyVariables>
    </configuration>
</plugin>
```

**更干净的做法是把并行配置放进 `src/test/resources/junit-platform.properties`**，不用改 pom：

```properties
junit.jupiter.execution.parallel.enabled=true
junit.jupiter.execution.parallel.mode.default=same_thread
junit.jupiter.execution.parallel.mode.classes.default=concurrent
junit.jupiter.execution.parallel.config.strategy=dynamic
junit.jupiter.execution.parallel.config.dynamic.factor=0.5
```

注意 `mode.default=same_thread` + `mode.classes.default=concurrent` 这个组合：**同一个类里的方法串行（避免共享状态打架），不同类之间并行（拿到大部分收益）**。这是我推荐的配置，因为它不需要你检查每个测试类是不是线程安全。

命令行筛选：

```bash
mvn test -Dgroups=unit              # 只跑 unit 标签
mvn test -Dtest=CalcAmountTest      # 只跑一个类
mvn test -Dtest='Order*Test'        # 通配
mvn test -Dtest='CalcAmountTest#满减'   # 只跑一个方法
mvn test -Dsurefire.failIfNoSpecifiedTests=false
```

**一个必须知道的坑：并行执行 + 共享可变状态 = 随机失败（flaky test）。** 最常见的元凶是测试里改了 `static` 变量、改了系统属性、或者共享了同一个数据库表。**并行化之前先确认你的测试是独立的**；第一次开并行建议先连跑三遍看结果是否稳定。

---


