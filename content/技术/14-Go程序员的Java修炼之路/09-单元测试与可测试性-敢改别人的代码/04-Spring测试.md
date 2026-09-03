# 第 09 章（节选）　Spring测试

> 本篇来自《Go 程序员的 Java 修炼之路》第 09 章「第 09 章　单元测试与可测试性：敢改别人的代码」。
> 返回：[第 09 章索引](./README.md)

## 09.4 Spring 测试：从"启动整个容器"到"只测一个类"

### 测试金字塔在 Spring 里的映射

| 层次 | 用什么 | 速度 | 测什么 | 占比建议 |
|---|---|---|---|---|
| 纯单元测试 | JUnit 5 + Mockito，**不启动 Spring** | 毫秒 | 业务逻辑 | 70% |
| 切片测试 | `@WebMvcTest` / `@DataJpaTest` / `@JsonTest` | 秒级 | 某一层（Controller / Repository / 序列化） | 20% |
| 集成测试 | `@SpringBootTest` | 十秒级 | 装配正确性 + 跨层流程 | 10% |
| 端到端 | Testcontainers / 真实环境 | 分钟级 | 全流程、真实中间件行为 | 少量 |

**关键认知：`@SpringBootTest` 是最后的选择，不是默认选择。**

这句话值得贴在工位上。它启动的是**一个完整的 ApplicationContext**：扫描 classpath、实例化所有 Bean、建所有代理、连数据源、起内嵌 Tomcat（如果配了 webEnvironment）。

> 【思考】为什么"所有测试都用 @SpringBootTest"是个坏习惯？
>
> 第一个理由很明显：慢。但真正致命的不是慢 —— 想一下，如果一个项目有 300 个 `@SpringBootTest`，而每个的配置组合都略有不同，会发生什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：三条 —— ①每个测试类平均几秒到几十秒，300 个就是几十分钟；②测试之间共享容器状态导致互相污染；③`@MockBean` 会导致 ApplicationContext 缓存失效并重建，这是 CI 变慢的头号原因。第三条大部分人不知道。**

**先说第一条：账很好算。**

一个中型 Spring Boot 项目启动容器 3-8 秒，加上 HikariCP 初始化、JPA 的 EntityManagerFactory 建（这个特别慢，要扫描所有 `@Entity`、建 metamodel）、内嵌 Tomcat 起端口 —— 一个 `@SpringBootTest` 平均 5 秒不算夸张。300 个就是 25 分钟。

**第二条：状态污染。**

Spring 会**缓存 ApplicationContext**（见下文），这意味着多个测试类可能共享同一个容器实例。于是：

- 测试 A 往数据库里插了一条订单，测试 B 查"订单总数"时看到了它
- 测试 A 改了一个单例 Bean 的字段（比如把某个缓存清空了），测试 B 依赖那个缓存
- 测试 A 修改了 `static` 的计数器

症状是**单独跑每个测试都过，一起跑就随机红**。这类 flaky test 的排查成本极高，因为它只在特定顺序下复现。

**第三条（最致命）：`@MockBean` 导致上下文重建。**

Spring TestContext 框架按"配置组合"缓存 ApplicationContext。缓存的 key 包含（但不限于）：

- 配置类 / `@ContextConfiguration` 的 locations
- 激活的 profile（`@ActiveProfiles`）
- `@TestPropertySource` 的属性
- **`@MockBean` 的定义（哪些 Bean 被替换成 mock）**
- `@Import` 的配置
- 各种 `ContextCustomizer`

**所以：不同的 `@MockBean` 组合 = 不同的缓存 key = 不同的 ApplicationContext。**

```java
@SpringBootTest
class OrderServiceTest {
    @MockBean InventoryClient inventory;      // key: {InventoryClient}
}

@SpringBootTest
class PaymentServiceTest {
    @MockBean InventoryClient inventory;      // 同样的组合 → 复用 ✅
    @MockBean PaymentClient payment;          // 组合变了 → 重新建容器 ❌
}

@SpringBootTest
class InventoryTest {
    @MockBean InventoryClient inventory;
    @MockBean OrderRepository repo;           // 又一个新组合 → 又重建 ❌
}
```

三个测试类 = 三个容器 = 三次完整启动。**你以为在复用，其实每次都在重来。**

**真实优化案例（现象 → 排查 → 根因 → 修复 → 教训）：**

- **现象**：某项目 300 个测试，CI 跑 25 分钟，本地没人愿意跑全量
- **排查**：`mvn test` 时观察日志，发现 `Starting OrderApplicationTests using Java 17` 出现了 **40 多次**（正常应该是 2-3 次）
- **根因**：47 个 `@SpringBootTest` 类里，`@MockBean` 的组合有 38 种，其中一半的组合只差一个 mock。另外还有几个类带了 `@DirtiesContext`（强制丢弃容器）
- **修复**：
  1. 业务逻辑测试改成纯单元测试（`new OrderServiceImpl(mockRepo, fixedClock)`），47 个 `@SpringBootTest` 砍到 12 个
  2. 剩下的按"共享同一套 `@MockBean` 组合"重组成 4 个测试类（用 `@Nested` 组织用例）
  3. Repository 测试改用 `@DataJpaTest`（H2，秒级）
  4. 删掉不必要的 `@DirtiesContext`
- **结果**：25 分钟 → 3 分 20 秒
- **教训**：**大部分"需要 Spring 容器"的测试，其实只是需要"一个被人构造好的对象"。** 手动 `new` 一个 service，把 mock 传进去，比启动容器快三个数量级。

**代码锚点 —— 不需要 Spring 的 service 测试：**

```java
// 不用 @SpringBootTest，不启动容器，毫秒级
class OrderServiceImplTest {
    @Mock InventoryClient inventory;
    @Mock OrderEventProducer producer;
    InMemoryOrderRepository repo = new InMemoryOrderRepository();
    Clock clock = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), UTC);

    OrderServiceImpl service;

    @BeforeEach
    void setUp() {
        service = new OrderServiceImpl(repo, inventory, producer, clock);
    }

    @Test
    void 库存扣减失败时不落库() {
        when(inventory.deduct(anyLong(), anyInt())).thenReturn(false);
        assertThatThrownBy(() -> service.createOrder(cmd())).isInstanceOf(BusinessException.class);
        assertThat(repo.findAll()).isEmpty();       // Fake 验证：没落库
    }
}
```

**这个测试跑起来 5 毫秒。而它替代的那个 `@SpringBootTest` 版本跑 6 秒。业务覆盖完全一样。**

**更深一层：`@SpringBootTest` 测的到底是什么？**

它测的是**装配** —— Bean 有没有被正确创建、依赖有没有注入、配置有没有生效、AOP 有没有织上。这是有价值的，但它是**一次性的验证**（只要装配不变，验证一次就够了），不是需要三百次重复的业务验证。

**判断标准：这个测试会因为"业务逻辑改了"而红吗？还是会因为"配置改了"而红？** 前者应该用纯单元测试，后者才需要容器。

</details>

### Spring Test 的上下文缓存机制

Spring 按配置组合缓存 `ApplicationContext`，默认最多缓存 **32 个**（超出后按 LRU 淘汰，被淘汰的容器会被 close 掉）。

**导致缓存失效（重建容器）的东西：**

| 因素 | 说明 |
|---|---|
| `@MockBean` / `@SpyBean` | 不同的 mock 组合 = 不同的 key |
| `@DirtiesContext` | 强制标记容器脏了，下次重建。**除非你在测试里改了 Bean 定义，否则不要用** |
| `@ActiveProfiles` | 不同 profile = 不同容器 |
| `@TestPropertySource` / `@DynamicPropertySource` | 属性不同 = 不同容器（Testcontainers 常用后者） |
| `@ContextConfiguration` | 配置类不同 |
| `@Import` | 导入的配置不同 |
| 不同的 `@SpringBootTest` 属性 | 如 `webEnvironment`、`classes` |

**优化清单（按收益排序）：**

1. **把业务测试改成纯单元测试** —— 收益最大，零容器
2. **统一 `@MockBean` 的组合** —— 定义一个抽象基类，把常用 mock 放进去，让所有需要容器的测试继承它。这样所有子类共享同一个缓存 key
3. **删掉不必要的 `@DirtiesContext`** —— 它是性能杀手，也是"我懒得清理状态"的遮羞布
4. **减少 profile 的使用** —— 每多一个 profile 组合，就多一份容器
5. **Profile/properties 尽量走 `@TestPropertySource` 的继承**，避免每个测试类都写不一样的
6. **并行执行** —— 见 09.2 的 `junit-platform.properties`

```java
// 共享 mock 组合的基类（让所有子类命中同一个上下文缓存）
@SpringBootTest
public abstract class AbstractIntegrationTest {
    @MockBean protected InventoryClient inventory;
    @MockBean protected OrderEventProducer producer;
    @MockBean protected PaymentClient payment;
}

// 子类继承 → 配置组合一致 → 复用同一个 ApplicationContext
class OrderFlowTest extends AbstractIntegrationTest {
    @Autowired OrderService orderService;
    // ...
}
```

### 切片测试：提速的主力

切片测试（Test Slices）的思路是：**只启动应用的某一层，其余的用 mock 顶掉**。Spring Boot 为此提供了一批注解。

**`@WebMvcTest` —— 只测 Controller**

```java
@WebMvcTest(OrderController.class)      // 只加载 Web 层，不加载 Service/Repository
class OrderControllerTest {
    @Autowired MockMvc mockMvc;                    // 不发真实 HTTP，直接调 DispatcherServlet
    @Autowired ObjectMapper objectMapper;
    @MockBean OrderService orderService;           // Service 被 mock 掉

    @Test
    void 创建订单返回201() throws Exception {
        when(orderService.createOrder(any())).thenReturn(new Order(1L, new BigDecimal("199")));

        mockMvc.perform(post("/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(new CreateOrderCmd(1001L, 2))))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.id").value(1))
            .andExpect(jsonPath("$.amount").value(199));
    }

    @Test
    void 参数缺失返回400() throws Exception {
        mockMvc.perform(post("/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
            .andExpect(status().isBadRequest());
    }
}
```

`MockMvc` 的关键点：它**不起 HTTP 服务器**，直接在内存里构造 `MockHttpServletRequest` 交给 `DispatcherServlet`。所以它是毫秒级的，但**它不测网络层、不测序列化之外的过滤器链以外的东西**（比如 Tomcat 的连接超时、SSL 配置）。

**Go 对照**：`MockMvc` 大致等于 Go 里的 `httptest.NewRecorder()` + 直接调 handler。

```go
w := httptest.NewRecorder()
r := httptest.NewRequest("POST", "/orders", bytes.NewReader(body))
router.ServeHTTP(w, r)
if w.Code != 201 { t.Errorf(...) }
```

两者语义几乎一样。**差别是 Java 的 MockMvc 走完整的 Spring MVC 栈（参数绑定、校验、拦截器、异常处理器），所以能测到 `@Valid`、`@ExceptionHandler` 这些 —— 这是它的价值所在。**

**`@DataJpaTest` —— 只测 Repository**

```java
@DataJpaTest        // 只加载 JPA 相关配置，默认用嵌入式数据库替换真实数据源
class OrderRepositoryTest {
    @Autowired OrderRepository repository;
    @Autowired TestEntityManager entityManager;    // 测试专用的 EntityManager

    @Test
    void 按订单号能查到() {
        entityManager.persistAndFlush(new Order("NO-001", new BigDecimal("199")));
        assertThat(repository.findByOrderNo("NO-001")).isPresent();
    }
}
```

`@DataJpaTest` 的三个默认行为：

1. **自动配置嵌入式数据库**（H2/HSQLDB/Derby，谁在 classpath 里用谁），通过 `@AutoConfigureTestDatabase`
2. **带 `@Transactional`，测试结束自动回滚**
3. **只扫描 `@Entity` 和 Spring Data Repository**，不加载 `@Service` / `@Controller`

想用真实数据库（比如 Testcontainers 起的 MySQL）测 Repository，加 `@AutoConfigureTestDatabase(replace = NONE)`。

**`@JsonTest` —— 只测序列化**

```java
@JsonTest
class OrderJsonTest {
    @Autowired JacksonTester<Order> json;      // AssertJ 风格的 JSON 断言

    @Test
    void 序列化包含金额字段() throws Exception {
        assertThat(json.write(new Order(1L, new BigDecimal("199"))))
            .hasJsonPathNumberValue("$.id")
            .extractingJsonPathNumberValue("$.amount")
            .isEqualTo(199);
    }

    @Test
    void 反序列化() throws Exception {
        assertThat(json.readObject("{\"id\":1,\"amount\":199}").getAmount())
            .isEqualByComparingTo("199");
    }
}
```

这个测试的价值在于：**它能抓到 DTO 改字段名导致的 API 破坏**，而这种问题是编译期发现不了的（JSON 是字符串）。

**`@RestClientTest` —— 测 RestTemplate / WebClient**

```java
@RestClientTest(InventoryClient.class)
class InventoryClientTest {
    @Autowired InventoryClient client;
    @Autowired MockRestServiceServer server;      // 假的 HTTP 服务器，不发真实请求

    @Test
    void 扣库存成功() {
        server.expect(requestTo("/inventory/deduct"))
              .andRespond(withSuccess("{\"ok\":true}", MediaType.APPLICATION_JSON));
        assertThat(client.deduct(1001L, 2)).isTrue();
    }
}
```

`MockRestServiceServer` 不发真实网络请求，在客户端层拦截。相当于 Go 里的 `httptest.NewServer` 的轻量版。

> 【思考】`@Transactional` 在测试里自动回滚，是好事还是坏事？
>
> `@DataJpaTest` 默认带事务并回滚，很多教程把它当成优点讲。但你想想：一个从来不提交的事务，测出来的东西跟生产一样吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：对 Repository 测试是好事（隔离、快）；对 Service 层的集成测试是坏事 —— 回滚会掩盖真实的事务问题，让你测出一个生产上会炸的版本。**

**回滚的好处（真实且重要）：**

1. **测试之间不污染。** 每个测试跑完数据自动消失，不用写 `@AfterEach` 清理
2. **快。** 不提交意味着不用真的写 redo log、不用刷盘
3. **可以并行**（如果配了并行执行，各自的测试事务互不干扰）

对 `@DataJpaTest` 来说，这个默认是对的 —— 你测的是"这条 SQL 能不能查出我要的数据"，事务只是手段。

**回滚的坏处（这才是重点）：**

**一、掩盖事务不生效的问题。**

Spring 的 `@Transactional` 有一堆失效场景（第 14 章会细讲）：同类内部方法调用、`private` 方法、`final` 类、异常被 catch 掉了、异常类型不对、用了错误的传播行为。

如果测试本身跑在一个事务里（`@Transactional` 测试），**被测代码的方法即使没有自己的事务，也会"搭车"外层测试的事务**。于是：

```java
@SpringBootTest
@Transactional                    // 测试自带事务
class OrderServiceTest {
    @Test
    void 扣库存失败应该回滚订单() {
        // 被测方法上的 @Transactional 就算没生效，也会搭测试事务的车
        assertThatThrownBy(() -> service.createOrder(badCmd)).isInstanceOf(...);
        // 断言"订单没被保存" → 绿了 ✅
    }
}
```

**生产上没有那个外层事务，你的 `@Transactional` 又没生效 —— 订单就真的被保存了。** 测试绿着，线上炸了。

**二、掩盖 flush 时机和延迟写入的问题。**

JPA 的一级缓存意味着 `save()` 之后不一定立刻发 `INSERT`。事务提交时才 flush。回滚的测试里，你看到的行为和生产上"真正提交"的行为可能不同 —— 特别是涉及到**数据库约束**（唯一索引冲突、外键约束）时。

```java
@Test
void 订单号唯一() {
    repo.save(new Order("NO-001"));
    // 没 flush，唯一索引冲突还没触发
    assertThatCode(() -> repo.save(new Order("NO-001")))
        .doesNotThrowAnyException();     // 绿了？！生产上第二条会炸
}
```

想测真实的约束行为，得手动 `entityManager.flush()` 或者提交事务。

**三、掩盖乐观锁的问题。**

`@Version` 乐观锁的冲突在 `commit` 时才检测（抛出 `OptimisticLockingFailureException`）。回滚的测试里你永远看不到它。

**四、用真实数据库时不回滚会留脏数据。** 这条是反过来的坑：如果你用 Testcontainers 起真实 MySQL 又没加事务，测试跑完数据留下了，下次跑测试就冲突。**所以要么回滚，要么每个测试清理。**

**实践建议：**

| 测试类型 | 用不用 `@Transactional` 回滚 | 理由 |
|---|---|---|
| `@DataJpaTest`（Repository） | **用**（默认） | 测的是 SQL 和映射，不涉及事务语义 |
| Service 层纯单元测试 | **不涉及**（没有数据库） | 用 Fake Repository |
| Service 层集成测试（跨层、真实 DB） | **不用**，跑完手动清理 | 要测真实的事务边界、flush、乐观锁 |
| 端到端测试 | **不用** | 要模拟真实流程 |

**代码锚点 —— 不用回滚时怎么清理：**

```java
@SpringBootTest
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class OrderIntegrationTest {
    @Autowired OrderRepository repo;
    @Autowired OrderService service;

    @BeforeEach
    @AfterEach                            // 前后都清，防止别处留下的数据干扰
    void clean() {
        repo.deleteAll();
    }

    @Test
    void 扣库存失败时订单不应落库() {          // 真实提交，能测出事务是否真的生效
        assertThatThrownBy(() -> service.createOrder(badCmd)).isInstanceOf(BusinessException.class);
        assertThat(repo.findAll()).isEmpty();     // 这句现在是有意义的断言了
    }
}
```

另一个做法是加 `@Transactional` 但**在断言前手动 flush**：

```java
@Autowired EntityManager em;

@Test
void 唯一约束() {
    repo.save(new Order("NO-001"));
    em.flush();          // 强制刷到数据库，触发唯一索引检查
    assertThatThrownBy(() -> { repo.save(new Order("NO-001")); em.flush(); })
        .isInstanceOf(DataIntegrityViolationException.class);
}
```

**更深一层：测试里的"简化"和"保真"是一对永恒的矛盾。**

回滚让测试简单、快、隔离，代价是**丧失了保真度**。Testcontainers 让测试保真，代价是慢。这两个极端之间，你要根据"这段测试想抓什么 bug"来选位置。

**判断标准：这个 bug 只能在真实事务下复现吗？** 如果是（事务边界、隔离级别、乐观锁、约束冲突、死锁），就必须用真实提交 + 真实数据库。如果不是（SQL 语法、字段映射、查询条件），H2 + 回滚完全够用。

**对照 Go**：Go 里没有框架帮你自动回滚，所以 Go 程序员对这个问题的直觉是"每个测试自己清理数据"：

```go
func TestCreateOrder(t *testing.T) {
    db := setupTestDB(t)
    t.Cleanup(func() { db.Exec("TRUNCATE orders") })   // 显式清理
    // ...
}
```

更啰嗦，但**它逼你想清楚"这个测试的数据边界在哪"**，不会因为框架帮你兜底而忽略了事务语义。**这是"框架便利性"的又一个隐藏成本。**

</details>

---


