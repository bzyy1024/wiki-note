# 第 09 章（节选）　Mockito

> 本篇来自《Go 程序员的 Java 修炼之路》第 09 章「第 09 章　单元测试与可测试性：敢改别人的代码」。
> 返回：[第 09 章索引](./README.md)

## 09.3 Mockito：把依赖换成"假的"

### 核心 API

```java
@ExtendWith(MockitoExtension.class)       // 必须加，否则 @Mock 不生效
class OrderServiceTest {
    @Mock OrderRepository repo;           // 全假对象
    @Mock InventoryClient client;
    @InjectMocks OrderServiceImpl service; // 自动把上面的 mock 注入进去

    @Test
    void 库存不足时抛异常() {
        // stub：指定"当调用这个方法、传这个参数时，返回什么"
        when(client.deduct(anyLong(), anyInt())).thenReturn(false);

        // 执行
        assertThatThrownBy(() -> service.createOrder(cmd))
            .isInstanceOf(BusinessException.class)
            .hasMessageContaining("库存不足");

        // verify：验证"这个方法确实被调用过，参数是这个"
        verify(client).deduct(1001L, 2);
        verify(repo, never()).save(any());     // 断言"没被调用"
    }
}
```

几个容易忘的点：

- `@ExtendWith(MockitoExtension.class)` 不加，`@Mock` 字段就是 `null`。这是新手第一大坑。
- `@InjectMocks` 会尝试**构造器注入 → setter 注入 → 字段注入**。优先走构造器，所以**有构造器注入的类最好 mock**（又一个该用构造器注入的理由）。
- `when(...)` 里如果被调用的方法返回 `void`，不能用 `thenReturn`，要用 `doThrow(...).when(mock).method()`。
- **Mockito 默认严格 stubbing（strictness）**：你 stub 了一个方法但测试里没用到，会报 `UnnecessaryStubbingException`。这是好事 —— 它在告诉你"你的测试准备了一些用不上的东西"。想放宽用 `@MockitoSettings(strictness = Strictness.LENIENT)`。

### Mock 的三个层次

**这是本节最重要的认知。大部分人只知道第一层。**

| 层次 | 是什么 | 用 `mock()` / `@Mock` 造 | 适用场景 |
|---|---|---|---|
| **Mock** | 全假。所有方法返回默认值（`null`/`0`/`false`），你显式 stub 才返回指定值 | ✅ | 验证"调用发生了"（副作用） |
| **Spy** | 半真。包一个真实对象，调用默认走真实实现，可以单独 stub 某些方法 | `@Spy` | 救急，慎用 |
| **Fake** | 真实现，但简化。自己写的一个能跑的简化版本 | 手写类 | 数据访问层的首选 |

```java
// Fake：一个真的能用的内存版 Repository，不是 mock
public class InMemoryOrderRepository implements OrderRepository {
    private final Map<Long, Order> store = new ConcurrentHashMap<>();
    private final AtomicLong seq = new AtomicLong(1);

    @Override
    public Order save(Order order) {
        if (order.getId() == null) {
            Order withId = order.withId(seq.getAndIncrement());   // record 风格
            store.put(withId.getId(), withId);
            return withId;
        }
        store.put(order.getId(), order);
        return order;
    }

    @Override
    public Optional<Order> findById(Long id) {
        return Optional.ofNullable(store.get(id));
    }
}
```

```java
// Spy：真实对象，但 stub 掉其中一个方法
@Spy OrderServiceImpl realService = new OrderServiceImpl(repo, client);
when(realService.calcAmount(any(), any())).thenReturn(new BigDecimal("1"));
```

**问题 6：** `@Spy` 看起来很方便 —— 为什么要"慎用"？

因为**你需要 spy 这件事本身就是设计有问题的信号**。你为什么需要让一个对象的一部分是真、一部分是假？因为这个类同时干了两件事。正常做法是把那部分逻辑拆成另一个类，然后正常注入。

> 【思考】什么时候该用 Fake 而不是 Mock？
>
> 换个问法：Mock 验证的是"调用发生了"，Fake 验证的是"结果是对的"。这两件事哪件更重要？

<details>
<summary><b>参考答案</b></summary>

**直接答案：优先 Fake（尤其对 Repository、HTTP client 这类"数据访问"），对"副作用"（发消息、发邮件、调第三方）用 Mock 验证调用。核心原因是 Mock 会把测试跟实现细节绑死。**

**看一个对照例子 —— 同一个业务行为，两种测法。**

业务规则：`createOrder` 成功后要保存订单。

**Mock 测法（跟实现绑死）：**

```java
@Test
void 创建订单后应该保存() {
    service.createOrder(cmd);
    // 断言"调用了 save 方法，参数是个 Order"
    verify(repo).save(any(Order.class));
}
```

现在你做一次**不改变行为**的重构：把 `save` 改成 `saveAll(List<Order>)`（因为要支持批量）。

```java
// 重构后：行为没变（订单还是被保存了），但 mock 测试红了
orderRepository.saveAll(List.of(order));
```

`verify(repo).save(...)` 失败。**代码行为完全正确，测试却红了。** 你得改测试。这不是"测试保护了重构"，这是"测试阻碍了重构"。

**Fake 测法（跟实现解耦）：**

```java
@Test
void 创建订单后应该保存() {
    var repo = new InMemoryOrderRepository();     // Fake
    var service = new OrderServiceImpl(repo, client, clock);

    Order order = service.createOrder(cmd);

    // 断言"结果是对的"：从 repository 里能查回来
    assertThat(repo.findById(order.getId())).isPresent();
    assertThat(repo.findById(order.getId()).get().getStatus()).isEqualTo(CREATED);
}
```

这个测试在 `save` → `saveAll` 重构后**依然是绿的**。因为它断言的是可观测的行为结果，不是内部调用方式。

**那 Mock 什么时候该用？**

三种情况：

**1. 副作用 —— 你没法通过"查结果"验证它。** 发了一封邮件、推了一条 Kafka 消息、调了一次第三方支付接口。这些动作的"结果"不落在你能查询的地方，唯一能验证的就是"它被调用了，参数对"。

```java
@Test
void 订单创建后应该发消息() {
    service.createOrder(cmd);
    verify(producer, timeout(2000))      // 异步场景可以加 timeout
        .send(argThat(e -> e.getOrderId().equals(1L) && e.getType() == CREATED));
}
```

**2. 外部依赖不可控，且没有简化实现的价值。** 时间（`Clock`）、随机数、第三方 SDK。

**3. 依赖很重，Fake 写起来成本太高。** 比如你要 mock 一个有三四十个方法的 AWS SDK 客户端，但你只用其中两个 —— 手写 Fake 要实现全部方法，不值当。

**不该用 Mock 的情况：**

- **不要 mock 你自己写的简单值对象和 DTO。** `mock(Order.class)` 然后 `when(order.getAmount()).thenReturn(...)` —— 直接 `new Order(...)` 不就完了？
- **不要 mock 你为了 mock 而 mock。** 每个 mock 都是有成本的（见下）。
- **不要 mock 数据访问层之外的东西，只为了"隔离"。** 有些人会把 service 的每个依赖都 mock 掉，包括纯计算的类。这把测试变成了"实现复述"。

**代码锚点 —— 一个折中的真实例子：**

```java
class CreateOrderTest {
    // 数据访问用 Fake：验证结果
    final InMemoryOrderRepository repo = new InMemoryOrderRepository();
    // 副作用用 Mock：验证调用
    @Mock OrderEventProducer producer;
    @Mock InventoryClient inventory;
    // 时间用固定 Clock
    final Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), UTC);

    OrderServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new OrderServiceImpl(repo, inventory, producer, clock);
    }

    @Test
    void 创建订单_扣库存成功_落库并发消息() {
        when(inventory.deduct(anyLong(), anyInt())).thenReturn(true);   // 外部依赖用 stub

        Order order = service.createOrder(cmd(1001L, 2));

        assertThat(repo.findById(order.getId()).get().getStatus()).isEqualTo(CREATED);  // Fake 验证结果
        verify(producer).send(any(OrderCreatedEvent.class));                             // Mock 验证副作用
    }
}
```

**这就是我推荐的默认组合：Fake 管数据，Mock 管副作用，Clock 管时间。**

**更深一层：Mock 的成本到底是什么？**

一句话：**Mock 的成本是"测试与实现耦合"，收益是"隔离和速度"。**

每一次 `verify(mock).someMethod(...)`，你都在测试里写下了"我期望实现会调用这个方法"这个假设。这个假设在**实现重构时就会失效**，哪怕行为没变。所以 mock 越多，你的测试套件就越"脆" —— 每次重构都要改一堆测试，最后团队开始说"测试拖慢了开发"，然后开始删测试。

Fake 的成本是"要写代码"（维护成本），收益是"测试只依赖可观测行为"。Fake 写得好的话，一份 Fake 能被几十个测试复用，摊薄后成本很低。**而且 Fake 逼你定义清晰的接口契约 —— 写不出来 Fake，往往说明你的接口设计有问题。**

**对照 Go**：Go 社区其实早就偏向 Fake 了。`sqlmock` 是 mock 派，`sqlite` 内存库是 fake 派，`httptest.NewServer(handler)` 是 fake 派（起一个真的 HTTP server）。你会发现 Go 里"起一个真的东西"的倾向更强 —— 因为 Go 起一个真东西的成本太低了（一个 goroutine + 一个端口，几毫秒）。Java 起一个真东西贵，所以历史上更依赖 mock。**但 Testcontainers（09.5）正在把 Java 也推向 fake 派。**

</details>

### Mockito 的实现原理：为什么早期不能 mock final 类

Mockito 造 mock 对象的机制是 **ByteBuddy 在运行时生成一个目标类的子类**，覆盖掉所有方法，把方法调用拦截下来路由到 Mockito 的拦截器。

```java
// 概念上，Mockito 生成了这么个东西（实际是字节码，不是源码）
class OrderRepository$MockitoMock$123 extends OrderRepository {
    public Order save(Order o) {
        return (Order) MockInterceptor.handle(this, "save", new Object[]{o});
    }
}
```

**问题 7：** 这个机制决定了哪些东西不能 mock？

`final` 类（不能继承）、`final` 方法（不能覆盖）、`private` 方法（子类看不到）、`static` 方法（不属于实例）、以及 JDK 的一些核心类（`String`、`Class`，因为它们在 bootstrap classloader 里）。

> 【思考】为什么 Mockito 早期不能 mock final 类？Go 的 gomock 又是怎么做的？
>
> 这个问题值得想透，因为它直接解释了两个社区"面向接口"文化的差异。

<details>
<summary><b>参考答案</b></summary>

**直接答案：Mockito 靠生成子类覆盖方法，final 类不能被继承、final 方法不能被覆盖，所以没法 mock。Go 的 gomock 靠代码生成（生成接口的实现类），所以只能 mock 接口 —— 这也是 Go 社区强调"面向接口"的技术根源。**

**三方对照：**

| | Java Mockito | Go gomock | Go monkey |
|---|---|---|---|
| 实现手段 | **运行时字节码生成子类**（ByteBuddy） | **编译前代码生成**（mockgen 生成 `_mock.go`） | **运行时改写函数指令**（改机器码） |
| 能 mock 什么 | 非 final 类和接口 | **只有接口** | 任意函数、方法，包括标准库 |
| 生成时机 | 运行时（测试跑起来时） | 编译前（`go generate`） | 运行时 |
| 类型安全 | 是（编译期检查返回值类型） | 是（生成的是 Go 代码） | **否**（靠字符串/反射，编译期不检查） |
| 速度 | 慢（每次 mock 都要生成并加载类） | 快（就是普通 Go 代码） | 快 |
| 危险程度 | 低 | 低 | **高**：改机器码，会让内联失效、不能并行跑、Go 版本变了可能崩 |

**Go 的 gomock 为什么只能 mock 接口？**

`mockgen` 读取你的接口定义，生成一个实现了该接口的结构体：

```go
//go:generate mockgen -source=repository.go -destination=mock_repository.go

type MockOrderRepository struct {
    ctrl     *gomock.Controller
    recorder *MockOrderRepositoryMockRecorder
}

func (m *MockOrderRepository) Save(o *Order) (*Order, error) {
    ret := m.ctrl.Call(m, "Save", o)
    // ... 类型断言后返回
}
```

它生成的是**普通 Go 代码**，所以编译期类型检查、IDE 跳转、go vet 全部有效。但**它只能为接口生成实现** —— 因为 Go 没有子类化，你没法"生成一个继承了某个结构体的类型"。

**这就是 Go 社区 "accept interfaces, return structs" 和"必须面向接口才能测"的技术根源。** 不是审美，是 mockgen 的能力边界。

**那 Java 的 final 问题怎么解决的？**

Mockito 从 **3.4.0** 起提供了一个替代的 mock maker —— **`mockito-inline`**，它基于 **JVM 的 Instrumentation API**（`java.lang.instrument`），在类加载时（retransform）直接修改目标类的字节码，而**不是生成子类**。于是 final 类、final 方法、static 方法都能 mock 了。

```xml
<dependency>
    <groupId>org.mockito</groupId>
    <artifactId>mockito-inline</artifactId>
    <scope>test</scope>
</dependency>
```

**关键节点：Mockito 5.0（2023）把 inline mock maker 设成了默认**，所以你现在用 `mockito-core` 5.x 就自带这个能力，`mockito-inline` 这个 artifact 已停止更新（最后一个版本是 5.2.0）。

**static 方法用 `MockedStatic`（需要 inline mock maker）：**

```java
@Test
void mock静态方法() {
    // try-with-resources 是必须的：不 close 会在别的测试里继续生效，污染整个套件
    try (MockedStatic<IdGenerator> mocked = mockStatic(IdGenerator.class)) {
        mocked.when(IdGenerator::nextId).thenReturn("FIXED-ID-001");
        assertThat(IdGenerator.nextId()).isEqualTo("FIXED-ID-001");
    }   // 出了这个块，静态方法恢复原样
}
```

**但要说清楚：能 mock static 不等于应该 mock static。** 如果你在正常业务测试里大量 mock 静态方法，那说明这些静态方法承载了不该承载的逻辑 —— 正确做法是注入 `Clock`、抽接口、或者包一层实例方法。

**Go 的 monkey 该怎么看？**

`bouk/monkey` 做的事比 Mockito inline 更狠：它拿到函数指针，用 `mprotect` 把那段内存改成可写，然后**直接写入一条跳转到你的替身函数的机器指令**。这让它能 patch 任何东西，包括 `time.Now`。

代价是：

1. **必须关掉内联**（`go test -gcflags=-l`），否则编译器可能已经把调用内联掉了，你的 patch 不生效
2. **不能并行跑**（`-parallel` 会出事），因为改的是全局的机器码
3. **不能开 race detector**
4. **Go 版本升级可能直接崩**（指令编码变了）

**所以 monkey 在 Go 社区是"最后的手段"，Mockito inline 在 Java 社区是"默认能力"。** 这个差别的根源是：JVM 有官方的、稳定的 Instrumentation API，而 Go 没有官方的运行时 patch 机制。

**更深一层：三种手段对应三种"替换行为"的时机。**

```
编译前代码生成（gomock）    → 确定性强、类型安全、能力最弱
运行时生成子类（Mockito 经典）→ 灵活、对代码有要求（不能 final）
运行时改写字节码/机器码（inline / monkey）→ 能力最强、最危险
```

**这是一个普遍规律：能力越强的技术，牺牲的确定性越多。** Java 因为有 JVM 这个"运行时平台"，天然更容易做运行时改写；Go 的哲学是编译期搞定一切，所以选择了代码生成。**两种选择都不需要道歉，但你得知道自己在用哪一种、代价是什么。**

</details>

### Mockito 的四个坑

**坑一：过度 verify。** 每调一个方法就 verify 一次，等于把实现在测试里复述一遍。判断标准：**这个 verify 断言的是"业务规则"还是"内部调用方式"？** 如果是后者，删掉它。

```java
// 过度：这三个 verify 里有两个是纯实现复述
verify(repo).findById(1L);
verify(calc).calc(any(), any());
verify(repo).save(any());

// 合理：只验证"业务上有意义的副作用"
verify(eventProducer).send(any());
```

**坑二：mock 深层对象链。**

```java
// 危险信号：违反迪米特法则
when(order.getUser().getAccount().getBalance().getCurrency()).thenReturn("CNY");
```

`a.getB().getC().getD()` 在测试里出现，说明**你 mock 的对象对你来说太"深"了**。这不是 mock 的问题，是设计的问题 —— 正确做法是让 `order` 直接暴露一个 `getCurrency()`，或者把这段逻辑移到 `User` 上。

**顺带的技术点**：Mockito 有一个 `RETURNS_DEEP_STUBS` 模式能自动处理这种链式调用，**但别用它**，它会让你继续容忍糟糕的设计。

**坑三：`any()` 和 null。**

这里有个流传很广的说法是"`any()` 不匹配 null"，**严格说要分清楚**：

```java
when(repo.save(any())).thenReturn(order);            // any()：匹配任何东西，包括 null
when(repo.findByName(any(String.class))).thenReturn(o); // any(Class)：从 Mockito 2 起不匹配 null

// 想匹配 null，显式写
when(repo.findByName(isNull())).thenReturn(o);
// 想匹配"null 或某个类型"
when(repo.findByName(nullable(String.class))).thenReturn(o);
```

所以准确表述是：**`any(Class)` 不匹配 null，`any()` 匹配包括 null 在内的一切。要显式表达 null 语义用 `isNull()` / `isNotNull()` / `nullable(Class)`。**

**坑四：参数匹配器不能混用。**

```java
// 错误：混用匹配器和原始值
when(client.deduct(anyLong(), 5)).thenReturn(true);
//       ↑ 匹配器      ↑ 原始值  → InvalidUseOfMatchersException

// 正确：要么全用匹配器
when(client.deduct(anyLong(), eq(5))).thenReturn(true);
// 要么全用原始值
when(client.deduct(1001L, 5)).thenReturn(true);
```

原因是匹配器靠**线程局部的栈**记录，混用会让 Mockito 数不清参数个数。这个报错信息（`InvalidUseOfMatchersException`）在新版本里已经友好了很多，会直接告诉你"expected N matchers, recorded M"。

---


