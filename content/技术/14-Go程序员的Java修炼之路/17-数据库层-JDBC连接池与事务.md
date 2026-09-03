# 第 17 章　数据库层：JDBC、连接池与事务（从 DriverManager 到 @Transactional）

> 上一章你顺着一次 HTTP 请求，看它从 Tomcat 走到 `@Controller`，`@Controller` 里注入的 `Service`，`Service` 里注入的 `Repository`。链路到 `Repository` 就断了——它背后那根连到 MySQL 的线，咱们一直没拉直。
>
> 这根线叫 JDBC。它上面套着连接池，再上面是 `JdbcTemplate` 和 `@Transactional`，最上面才是你写的 `Repository`。你天天 `@Autowired` 一个 `Repository` 就敢查库，但连接从哪来、事务在哪开、连接怎么还回池子，你心里其实没底。这一章把这条线从最底下的 `DriverManager` 一路捋到最上面的 `@Transactional`，让你以后看到 `Communications link failure` 不再只会重启。

---

## 17.1 从 Controller 到数据库：被藏起来的最后一公里

先别急着背名词。我们看一段你在第 16 章（Web 层）会写、但现在看不清全貌的代码：

```java
@RestController
public class OrderController {
    private final OrderService orderService;
    public OrderController(OrderService s) { this.orderService = s; }

    @PostMapping("/order")
    public Order create(@RequestBody OrderCmd cmd) {
        return orderService.createOrder(cmd);   // 这一跳之后，线就断了
    }
}

@Service
public class OrderService {
    private final OrderRepository orderRepository;
    public OrderService(OrderRepository r) { this.orderRepository = r; }

    @Transactional
    public Order createOrder(OrderCmd cmd) {
        Order o = orderRepository.save(cmd.toOrder());
        return o;
    }
}
```

`orderRepository.save(...)` 一行，背后发生了什么？我替你把调用栈摊开：

1. `JpaRepository.save` 内部拿到一个 `EntityManager`（JPA 的会话）。
2. `EntityManager` 向 `DataSource` 要一个 `Connection`。
3. `DataSource` 是连接池（Spring Boot 默认是 HikariCP），从池里借出一条物理连接。
4. 这条 `Connection` 被包成 JDBC 的 `PreparedStatement`，发给 MySQL。
5. MySQL 返回 `ResultSet`，JPA 映射成你的 `Order` 对象。

你看，`@Transactional` 在第三步之前悄悄把这条连接的 `autoCommit` 设成了 `false`，结束时再 `commit` 或 `rollback`。**这些动作你一个都没写，全藏在代理和框架里。** 这正是第 14 章说的——声明式能力 = AOP 代理；你只看到了 `save` 这一行，没看到它下面那条长链。

**问题 1：** 那如果我不套任何框架，用 Java 最原始的方式连数据库，长什么样？

这就要回到 JDBC 本身。先把它讲透，你才懂为什么后来要发明连接池、`JdbcTemplate`、`@Transactional`——每一层都是为了解决下一层的一个具体痛点。

---

## 17.2 JDBC 本质：Connection / Statement / ResultSet 三层抽象

JDBC（Java Database Connectivity）是 Java 访问关系型数据库的统一 API。它定义了一套接口（`java.sql.*`），各数据库厂商提供实现（驱动）。核心是三层抽象，你调数据库永远绕不开它们：

- **`Connection`**：一条到数据库的物理会话。相当于你手里那根电话线。
- **`Statement` / `PreparedStatement`**：在 `Connection` 上发出的 SQL 指令。相当于你对着电话说的那句话。
- **`ResultSet`**：SQL 执行后返回的结果集游标。相当于对方回的话，你得一行行听。

最原始的写法，裸 JDBC 长这样：

```java
// 裸 JDBC：每一步都要你亲手管
Connection conn = DriverManager.getConnection(url, user, pwd);  // 拿连接
PreparedStatement ps = conn.prepareStatement(
    "INSERT INTO orders(user_id, amount) VALUES(?, ?)");         // 预编译
ps.setLong(1, 1001L);
ps.setBigDecimal(2, new BigDecimal("99.00"));
ps.executeUpdate();                                              // 执行
ps.close();
conn.close();                                                   // 必须手动还
```

**问题 2：** `DriverManager.getConnection` 怎么知道该连 MySQL 还是 PostgreSQL？你明明没 `new MySQLDriver()`。

靠 SPI（Service Provider Interface）。从 JDBC 4.0（JDK 6）起，驱动 jar 里有一个固定文件 `META-INF/services/java.sql.Driver`，里面写着驱动实现类的全限定名，例如 MySQL 驱动里是：

```
com.mysql.cj.jdbc.Driver
```

`DriverManager` 启动时用 `ServiceLoader` 扫描 classpath 上所有 `META-INF/services/java.sql.Driver`，把每个实现类加载进来、调它的 `registerDriver`。你调用 `getConnection(url, ...)` 时，它遍历已注册的驱动，问"谁能处理这个 `jdbc:mysql://` 开头的 URL"，MySQL 驱动举手，于是用它建连。

```java
// 驱动 jar 里的 META-INF/services/java.sql.Driver 内容（示例）
com.mysql.cj.jdbc.Driver
```

这就是为什么你只加 `mysql-connector-j` 依赖、从没显式注册驱动，`getConnection("jdbc:mysql://...")` 就能工作——**驱动发现是 SPI 自动完成的，不是你 `Class.forName` 的功劳**（老教程里 `Class.forName("com.mysql.cj.jdbc.Driver")` 在 JDBC 4.0 之后已经多余）。

> 【思考】为什么裸 JDBC 没人直接在生产代码里写？它到底痛在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不是不能用，是样板代码太多、资源极易泄漏、每个方法都要重复同样的"拿连接—建语句—执行—关资源"四步，且任何一步漏关都会把连接池拖垮。**

**样板代码的重复**：一个查询，真正"业务"的只有那一行 SQL 和参数绑定；其余拿连接、建 `Statement`、关 `ResultSet`/`Statement`/`Connection` 全是固定的脚手架。十个方法复制十遍，且每一遍都可能写错。

**资源泄漏是致命的**：`Connection`、`Statement`、`ResultSet` 都持有底层资源（socket、游标）。裸 JDBC 里你必须手动 `close()`，而且要用 `try/finally` 保证异常路径也关：

```java
Connection conn = null;
PreparedStatement ps = null;
ResultSet rs = null;
try {
    conn = DriverManager.getConnection(url, user, pwd);
    ps = conn.prepareStatement("SELECT ...");
    rs = ps.executeQuery();
    while (rs.next()) { ... }
} finally {
    if (rs != null) try { rs.close(); } catch (Exception ignored) {}
    if (ps != null) try { ps.close(); } catch (Exception ignored) {}
    if (conn != null) try { conn.close(); } catch (Exception ignored) {}  // 三层 finally，丑且易错
}
```

三层 `try/finally` 才能安全关资源。只要有一处漏关，这条 `Connection` 就永远不归还——而裸 `DriverManager` 拿的是物理连接，不关就是真泄漏，很快把数据库 `max_connections` 占满，全库挂掉。

**`PreparedStatement` 的价值**：上面用 `PreparedStatement` 而非 `Statement`，不只是性能（SQL 预编译一次、可复用执行计划），更关键的是**防 SQL 注入**——参数用 `?` 占位、由驱动转义后拼入，而不是字符串拼接。你写 `Statement.execute("SELECT * FROM t WHERE name='" + name + "'")` 就是注入敞口。

**更深一层**：裸 JDBC 的痛，本质是"资源获取/释放的样板代码 + 异常安全"这两件事，和业务逻辑搅在一起。所有后续抽象（连接池、`JdbcTemplate`、ORM）都是在回答同一个问题：**怎么把"资源生命周期管理"从业务代码里剥离出去？** 你从 Go 过来，这和你用 `database/sql` 时 `defer rows.Close()` 是同一类诉求，只不过 Go 把"连接池"和"资源关闭"都内置进了标准库，省了一层框架。

</details>

**问题 3：** 既然裸 JDBC 这么痛，为什么第一章不干脆用 `DriverManager` 一直 `getConnection`？

因为 `DriverManager.getConnection` 每次都建一条**物理连接**：TCP 三次握手 + TLS 握手（如果用 SSL）+ 数据库身份认证 + 分配会话。这套开销在毫秒到几十毫秒级，高并发下根本扛不住。这就是连接池存在的理由。

---

## 17.3 为什么必须连接池：建连开销与 DataSource 抽象

每次 `getConnection` 都走一遍网络握手和数据库认证，代价有多大？

- TCP 建立连接：1 个 RTT。
- 如果开 TLS：再加 1~2 个 RTT 做握手。
- 数据库侧认证（`mysql_native_password` / `caching_sha2_password`）：一次用户校验。
- 数据库为这个连接分配会话内存、初始化会话变量。

单次建连轻松 5~30ms，且**数据库允许的并发连接数有硬上限**（`max_connections`，通常几百到几千）。如果每个请求都现建现断，两个后果：① 建连开销吃掉大半 RT；② 连接数打到上限后，新请求直接被数据库拒绝。

解法就是连接池：**预先建好一批连接放着，谁要用谁借，用完还回池子，而不是真关。** 借还的代价是微秒级，省掉了每次的网络握手。

抽象点就在 `javax.sql.DataSource`（Jakarta EE 9+ 为 `jakarta.sql.DataSource`）这个接口上。它的全部契约就一个方法：

```java
public interface DataSource extends CommonDataSource {
    Connection getConnection() throws SQLException;        // 语义是"借一条连接"
    Connection getConnection(String user, String pwd) throws SQLException;
}
```

**`DataSource` 是整个 JDBC 生态的抽象支点**：业务代码只依赖 `DataSource.getConnection()`，至于背后是直连、是 HikariCP、是 Druid、还是加了读写分离代理，业务代码一概不关心。Spring 的 `@Transactional`、`JdbcTemplate`、JPA 全部只认 `DataSource`——你换池子实现，上层一行不用改。这点和 Go 的 `database/sql` 用 `DB` 作为统一句柄是同一个设计哲学：先抽象一个"拿连接"的入口，再在下面自由换实现。

```java
// DataSource 是抽象点：上层不关心下面是谁
DataSource ds = new HikariDataSource(config);   // 今天用 HikariCP
// DataSource ds = new DruidDataSource();       // 明天换 Druid，上层代码不动
Connection conn = ds.getConnection();           // 永远是这个签名
```

> 【思考】既然 `DataSource` 只是个接口，那"连接池"到底是接口里的哪一部分？`getConnection()` 返回的 `Connection` 和物理连接是一回事吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：`DataSource` 接口本身不管池化——池化是具体实现类（如 `HikariDataSource`）在 `getConnection()` 内部做的。它返回的 `Connection` 是个"代理/包装"，`close()` 不是真关，是把连接还回池子。**

**展开**：`javax.sql.DataSource` 只有 `getConnection` 两个方法，协议里没有"池"的概念。池是 `HikariDataSource` 这类实现类在内部维护的——它预先持有 N 条物理连接，你的 `getConnection()` 是从这个池子里借一条空闲的。

关键在返回的 `Connection`：`HikariDataSource.getConnection()` 给你的，是池子对物理连接的一个封装。你调 `conn.close()`，包装类拦截了"关闭"，改成"把底层物理连接标记为空闲、放回池"（除非池决定淘汰它）。所以：

```java
Connection conn = ds.getConnection();   // 从池借
// ... 用 conn 查库 ...
conn.close();                           // 不是真关 TCP，是还回池
```

这点容器（连接池）和 Go 的 `database/sql` 高度一致：`sql.DB` 也是个"连接池外观"，你 `db.Query` 拿到的 `sql.Rows` 用 `rows.Close()` 还连接，语义完全一样。

**更深一层**：`DataSource` 这个接口只定义"借"，不定义"还"——"还"靠的是你调 `Connection.close()` 的**约定**（池子把 `close` 重写成还池）。这是个典型的设计取舍：接口保持极简（就一个方法），把"池化语义"藏在实现里、靠 `close` 约定表达。代价是：如果你忘了调 `close()`，池子永远收不回这条连接——所以连接池必须配"借了不还的兜底"（`maxLifetime` 强制回收、`leakDetectionThreshold` 报警）。这引出了下一节：池子自己的参数。

</details>

---

## 17.4 HikariCP：快在哪，以及四个要命的参数

Spring Boot 2.0 起，`DataSource` 的默认实现就是 **HikariCP**（之前是 Tomcat JDBC Pool）。它快到什么程度？同类基准测试里它通常比 Druid、Tomcat Pool 吞吐高一大截。快在哪？

1. **自定义无锁集合 `ConcurrentBag`**：连接池的核心操作是"借/还连接"，高并发下如果用 `synchronized` 或 `ReentrantLock` 全局锁，会成瓶颈。HikariCP 自己写了 `ConcurrentBag`，用 `ThreadLocal` + `CopyOnWriteArrayList` + 一个 `SynchronousQueue` 做"就近复用"——当前线程刚还的连接优先给当前线程再用，大部分借还走 `ThreadLocal` 无锁完成。
2. **字节码层面的调用点优化**：作者 Brett Wooldridge 把很多"多态方法调用"改成了"单态"（monomorphic），让 JIT 能内联，减少虚方法分派开销。这是真·抠到字节码的优化。
3. **极简的对象创建**：一个连接包装对象 `PoolEntry` 的字段布局、代理生成方式都针对 GC 友好设计，减少分配和停顿。
4. **默认配置就接近最优**：很多池子要你配一堆参数，HikariCP 的默认值（连接存活、超时）是经过推敲的，开箱即用。

但你得懂四个参数各自管什么、调错会怎样。这是线上翻车的高发区：

| 参数 | 默认 | 管什么 | 调错会怎样 |
|---|---|---|---|
| `maximumPoolSize` | 10 | 池里最多多少条连接 | 太小：并发上来借不到，线程阻塞；太大：打爆 DB `max_connections` |
| `connectionTimeout` | 30000ms | 借连接最多等多久 | 太小：高峰偶发拿不到就抛 `SQLException`；太大：线程干等、接口拖死 |
| `idleTimeout` | 600000ms | 空闲连接保留多久后回收 | 太小：连接频繁重建；太大：闲时占着 DB 连接 |
| `maxLifetime` | 1800000ms | 连接最长存活时间，到期强制回收 | **大于 DB 的 `wait_timeout` 会拿到死连接**（下面案例详讲） |

`maxLifetime` 这条是重灾区。它说"一条连接不管闲不闲，活到这个时间就强制从池里剔除重建"。**它的取值必须小于 MySQL 的 `wait_timeout`**（MySQL 默认的 `wait_timeout` 是 28800 秒 = 8 小时）。如果 `maxLifetime` 比 `wait_timeout` 还大，会发生什么？

MySQL 会在连接空闲超过 `wait_timeout` 后**单方面断开**这条物理连接；但 HikariCP 不知道，它还认为这条连接活着。应用借到这条已经被 MySQL 掐断的连接，执行 SQL 时直接报：

```
com.mysql.cj.jdbc.exceptions.CommunicationsException:
Communications link failure.
The last packet successfully received from the server was X milliseconds ago.
```

**问题 4：** 那 HikariCP 不是有 `keepaliveTime` 和借出前校验吗？为什么还会借到死连接？

有，但都不是免费的。`keepaliveTime`（HikariCP 3.2+）会让池子在连接空闲时主动发个轻量探活（`ping`），提前发现死连接并剔除；但探活也有开销，且默认是关闭的。借出前校验（`connectionTestQuery` / `validationTimeout`）每次借连接都查一下，代价是直接吃掉借连接的性能——HiikariCP 作者明确建议别开，靠 `maxLifetime < wait_timeout` + `keepaliveTime` 就够了。**所以根因是：把 `maxLifetime` 调得比 `wait_timeout` 大，等于让池子主动去借那些 DB 已经丢弃的连接。** 这条坑我们下一节用真实事故讲透。

---

## 17.5 案例一：连接池耗尽，全站接口超时

**现象**：某个工作日下午三点，订单服务突然全线超时，RT 从 50ms 飙到 30s，健康检查 `/actuator/health` 直接挂，但 DB 本身（单独连上去查）健健康康，其他服务也正常。重启应用后恢复，半小时后又来一次。

**排查过程**：
1. 先怀疑 DB。DBA 说连接数、CPU、慢查询都正常，MySQL 那边连接数才 20 多，远没到 `max_connections`。
2. 拿应用线程 dump（jstack）。发现大量 `http-nio-8080-exec-N` 线程处在 `BLOCKED` / `WAITING`，栈顶全卡在同一个地方：

```
at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:686)
   - waiting on <lock> (a java.util.concurrent.Semaphore)
at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:... )
```

意思是：这些线程都在等连接池发一条连接，但池子空了，它们在信号量上排队。
3. 再看 `HikariPool` 的状态：活跃连接数等于 `maximumPoolSize`（10），且长时间不归还。说明**连接被借出去了，但没人还**。根因从"DB 慢"转向"连接泄漏 + 池太小"。
4. 翻代码，找到一个老接口：手写了 `DataSource ds = ...; Connection conn = ds.getConnection(); PreparedStatement ps = conn.prepareStatement(sql);` 然后中途抛异常，后面的 `conn.close()` 在 `try/catch` 之外没执行——连接泄漏。高峰期这个接口被并发打，10 条连接很快全借光且永不归还，新请求在 `getConnection` 处等到 `connectionTimeout`（30s）才抛 `SQLException`，于是全站看起来"超时"。
5. 同时发现另一个诱因：`maxLifetime` 被人手贱设成了 1 小时，而 MySQL `wait_timeout` 是 60 秒（这个环境 DBA 特意调小过）。于是大量连接其实早已被 MySQL 掐断，池子还当宝贝，借出去执行就报 `Communications link failure`，触发重建风暴，进一步加剧拿不到健康连接。

**根因**：连接泄漏（没关连接）+ `maxLifetime > wait_timeout`（借到死连接）+ `maximumPoolSize` 只有 10。三者叠加，高峰期池子被借空且填不满。

**修复**：
- 把所有裸 `getConnection` 改成 `JdbcTemplate` 或 `try-with-resources`，从根上消除泄漏：
```java
// 修复前：泄漏
Connection conn = ds.getConnection();
PreparedStatement ps = conn.prepareStatement(sql);
ps.executeUpdate();                       // 抛异常 => conn 永不关

// 修复后：try-with-resources 自动关
try (Connection conn = ds.getConnection();
     PreparedStatement ps = conn.prepareStatement(sql)) {
    ps.executeUpdate();                   // 无论成败，conn/ps 自动还池
}
```
- 把 `maxLifetime` 改成 1800000ms（30 分钟，仍小于 8h 的 `wait_timeout`，留足余量）；这个环境 `wait_timeout` 只有 60s 是特例，所以 `maxLifetime` 设成 550000ms（约 9 分钟）更安全。
- `maximumPoolSize` 按"DB `max_connections` / 实例数"算，从 10 提到 20，并开 `leakDetectionThreshold=60000`（借出 60s 没还就打日志报警）。

**教训**：
1. 连接池耗尽的第一信号不是 DB 慢，是**应用线程 dump 里一堆线程卡在 `HikariPool.getConnection`**。学会 jstack 看这个栈。
2. 连接泄漏比连接慢更阴险——它不报错，只是池子慢慢被借空，直到某次高峰引爆。用 `try-with-resources` 或 `JdbcTemplate` 让"还连接"变得不可能遗漏。
3. **池参数必须和 DB 侧超时对齐**：`maxLifetime` 永远小于 `wait_timeout`，留 10%~20% 余量。

---

## 17.6 JdbcTemplate：模板方法替你管资源

HikariCP 解决"连接从哪来、怎么复用"。但裸 JDBC 还有一层痛——"拿连接、建语句、关 `ResultSet`/`Statement`/`Connection`"的样板。Spring 用 `JdbcTemplate` 把这层包了：你只写 SQL 和怎么把行映射成对象，资源关闭它全管。

它是**模板方法模式**的典型：父类（`JdbcTemplate`）固化"获取连接 → 建语句 → 执行 → 关资源 → 异常处理"这个不变骨架，把"SQL 是什么、行怎么转对象"这个会变的点，留成回调（`RowMapper`、`PreparedStatementSetter`）交给你填。

```java
@Repository
public class OrderRepository {
    private final JdbcTemplate jdbcTemplate;
    public OrderRepository(DataSource ds) {
        this.jdbcTemplate = new JdbcTemplate(ds);     // 注入 DataSource
    }

    public Order findById(Long id) {
        return jdbcTemplate.queryForObject(
            "SELECT id, user_id, amount FROM orders WHERE id = ?",
            (rs, rowNum) -> new Order(                // RowMapper：行 -> 对象
                rs.getLong("id"),
                rs.getLong("user_id"),
                rs.getBigDecimal("amount")),
            id);                                      // 参数绑定，PreparedStatement 防注入
    }

    public int updateAmount(Long id, BigDecimal amount) {
        return jdbcTemplate.update(                  // 返回受影响行数
            "UPDATE orders SET amount = ? WHERE id = ?", amount, id);
    }
}
```

你看：没有 `Connection`、没有 `close()`、`ResultSet` 的遍历和关闭也消失了——`JdbcTemplate` 在 `execute` 内部 `try/finally` 把三层资源全关了。你只关心"SQL + 映射"。

把它和 Go 对照一下，你会发现两边的"替你关资源"思路很像，只是表达方式不同：

```go
// Go：database/sql，靠 defer 显式关
func (r *OrderRepo) FindByID(id int64) (*Order, error) {
    row := r.db.QueryRow(ctx, "SELECT id, user_id, amount FROM orders WHERE id = $1", id)
    var o Order
    if err := row.Scan(&o.ID, &o.UserID, &o.Amount); err != nil {
        return nil, err
    }
    return &o, nil   // 连接自动随 QueryRow 结束归还，无需手动 close
}
```

```java
// Java：JdbcTemplate，靠框架在模板里关
Order o = jdbcTemplate.queryForObject(
    "SELECT id, user_id, amount FROM orders WHERE id = ?",
    (rs, n) -> new Order(rs.getLong("id"), rs.getLong("user_id"), rs.getBigDecimal("amount")),
    id);
```

并排看：Go 用 `defer`/`QueryRow` 的语义保证连接归还（标准库内部管池），Java 用 `JdbcTemplate` 的回调框架管。两者都让你"不用手写 `close`"，但 Go 是语言级（defer） + 标准库（`sql.DB` 内置池），Java 是框架级（`JdbcTemplate` + 外接 HikariCP）。**一个关键差异**：Go 的 `sql.DB` **本身就是连接池**；Java 的 `JdbcTemplate` **不池化**，它只管资源关闭，池化是 `DataSource`（HikariCP）单独负责的——所以 Java 这边是"两个抽象叠起来干 Go 一个 `sql.DB` 的活"。

> 【思考】既然 `JdbcTemplate` 这么省事，为什么还有人用 `JpaRepository`、甚至手写 MyBatis？`JdbcTemplate` 的边界在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：`JdbcTemplate` 帮你关资源、防注入，但它不替你"写 SQL 之外的事"——对象到表的映射还是你手写的 `RowMapper`，多表关联、分页、动态条件照样要拼 SQL。当 CRUD 很规整时，重复写 `JdbcTemplate` 也是样板；JPA 把"对象↔表"的映射和 CRUD 也自动了；MyBatis 则相反，把 SQL 完全交回你手写。三者是"自动化程度"的梯度选择。**

**展开**：`JdbcTemplate` 消除了"资源关闭"样板，但没消除"SQL + 映射"样板。一个 `Order` 有 20 个字段，你 `findById`、`findAll`、`update`、`insert` 要写四遍 `RowMapper`/`INSERT` 列名——这又是另一种重复。于是：

- **JPA / `JpaRepository`**：连 `RowMapper` 和 SQL 都不用写，方法名派生成 SQL，对象↔表靠 `@Entity` 注解映射。自动化最高，代价是"生成的 SQL 你控制不了"（N+1、低效 JOIN 是常事）。
- **MyBatis**：SQL 完全你写（XML 或注解），框架只做"参数代入 + 结果映射"。自动化最低，但你 100% 掌控 SQL——适合复杂查询、报表、多表 JOIN。
- **`JdbcTemplate`**：卡在中间，适合"SQL 不复杂但想自己掌控、又不想写关资源样板"的场景。

**更深一层**：这其实是 ORM 光谱上的定位问题。`JdbcTemplate` 是"半自动"——它管资源不管映射；JPA 是"全自动"——它连映射和 CRUD 都管；MyBatis 是"手动挡但变速箱好"——SQL 你写，映射它管。你从 Go 过来，`JdbcTemplate` 最接近 `database/sql` + `sqlx` 的手感（手写 SQL + 结构体扫描）；`JpaRepository` 接近 gorm 的 `AutoMigrate` + 链式 CRUD；MyBatis 在 Go 里没有特别对的等价值（Go 习惯直接写 SQL 字符串）。第 18 章专讲 MyBatis，这里先记住：**当你不想把 SQL 交给框架自动生成、要把 SQL 写回自己手里时，就是 MyBatis 的出场时刻。**

</details>

### Go 对照表：数据库层全维度对照

把这一节的东西和你的 Go 经验对齐，记这张表就够了——它是本章所有 Go 对照的浓缩：

| 概念 | Go | Java |
|---|---|---|
| 连接池 | `sql.DB` 内置（`SetMaxOpenConns` / `SetMaxIdleConns` / `SetConnMaxLifetime`） | 需外接 `DataSource` 实现（HikariCP / Druid），`JdbcTemplate` 不池化 |
| 驱动发现 | `database/sql` 的 `sql.Register` + 驱动包 `init()` 自注册 | `DriverManager` 经 SPI 扫 `META-INF/services/java.sql.Driver` |
| 资源释放 | `defer rows.Close()` / `QueryRow` 结束自动还 | `JdbcTemplate` 或 `try-with-resources` 自动还 |
| 事务写法 | 显式 `db.Begin()` + `defer tx.Rollback()` + `tx.Commit()` | 声明式 `@Transactional`（AOP 代理，隐式） |
| 事务边界 | 代码显式可见，事务对象当参数传 | 代理隐式，自调用（`this`）会绕过代理 |
| ORM | gorm（链式 / `AutoMigrate`，近似 JPA 自动挡） | JPA（方法名派生 SQL）+ MyBatis（手写 SQL，第 18 章） |

---

## 17.7 @Transactional 原理：AOP 代理在事务上的落地

现在到本章最重的一块，也是你从 Go 过来最容易踩坑的一块。第 14 章讲了 AOP 代理是 `@Transactional` 的地基，这里把"事务"具体怎么落在代理上捋清楚。

`@EnableTransactionManagement`（Spring Boot 通过自动配置默认开了）会在容器里注册一个 advisor：`BeanFactoryTransactionAttributeSourceAdvisor`。它由三部分组成：

- **切点（Pointcut）**：匹配所有带 `@Transactional` 的方法。
- **通知（Advice）**：`TransactionInterceptor`——真正干"开事务、提交、回滚"的活。
- **属性源**：`TransactionAttributeSource` 读取 `@Transactional` 上的 `propagation`、`isolation`、`rollbackFor` 等配置。

当一个 Bean 的方法带 `@Transactional`，容器在生命周期第 6 步（呼应 14.4）给它生成代理。你调 `orderService.createOrder(...)` 实际调的是代理，代理先把活交给 `TransactionInterceptor`：

```java
// TransactionInterceptor 的核心逻辑（简化）
public Object invoke(MethodInvocation invocation) {
    PlatformTransactionManager tm = ...;          // 通常是 DataSourceTransactionManager
    TransactionStatus status = tm.getTransaction(txAttr);   // 开事务：拿到连接，autoCommit=false
    try {
        Object result = invocation.proceed();     // 调你的真实业务方法
        tm.commit(status);                         // 正常 => 提交
        return result;
    } catch (RuntimeException ex) {
        tm.rollback(status);                       // 异常 => 回滚
        throw ex;
    }
}
```

`tm.getTransaction` 内部（`DataSourceTransactionManager`）做了什么？向 `DataSource` 借一条 `Connection`，把它的 `autoCommit` 设成 `false`，再**把这条连接绑到当前线程的 `ThreadLocal` 上**（`TransactionSynchronizationManager.bindResource`）。之后同一个事务里所有的 `JdbcTemplate` / JPA 拿连接，都从线程上取这条已被绑定的连接——而不是新借一条。这就是"一个 `@Transactional` 方法里多次查库共用一个事务"的底层机制。

**问题 5：** 那如果方法里抛的是受检异常（checked exception），代理会回滚吗？

**不会**——这正是下一个大坑，也是本章案例三的主题。先记住一条铁律：**`@Transactional` 默认只在抛出 `RuntimeException` 和 `Error` 时才回滚；抛受检异常（如你自定义的 `extends Exception` 的业务异常）它会提交。**

为什么这么设计？因为受检异常在 Java 语义里"你本就该处理的"，Spring 认为"你 Catch 了或声明抛出了，说明你有预案"，所以不替你回滚。但现实中你的业务异常往往是 `extends Exception` 的受检异常——于是脏数据就入库了。

---

## 17.8 传播行为与隔离级别

`@Transactional` 上两个最常被乱用的配置：`propagation` 和 `isolation`。

**传播行为（propagation）** 回答的是："一个已经开着事务的方法，调用另一个 `@Transactional` 方法时，后者是加入前者、还是自己新开一个？" 最常用三个：

| 传播行为 | 行为 | 典型场景 |
|---|---|---|
| `REQUIRED`（默认） | 有事务就加入，没有就新建 | 绝大多数业务方法，套在同一个事务里 |
| `REQUIRES_NEW` | 挂起当前事务，自己新开一个独立事务 | 写审计日志、发消息——即使主事务回滚，这条也要落库 |
| `NESTED` | 在当前事务里开一个保存点（savepoint），内层回滚不影响外层 | 批量处理，单条失败只回滚那条，其余继续 |

`REQUIRED` 和 `REQUIRES_NEW` 的差异是最常考也最易错：

```java
@Service
public class OrderService {
    @Transactional                                 // REQUIRED
    public void placeOrder(OrderCmd cmd) {
        orderRepository.save(cmd.toOrder());
        auditLog.asyncLog(cmd);                    // 调下面那个方法
        paymentClient.charge(cmd);                 // 这里抛异常
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void asyncLog(OrderCmd cmd) {
        logRepository.save(new AuditLog(cmd));     // 独立事务，即使 placeOrder 回滚，这条也在
    }
}
```

`placeOrder` 抛异常整体回滚，`order` 不会落库；但 `asyncLog` 是 `REQUIRES_NEW`，它 own 一个独立物理事务，已在 `placeOrder` 异常前提交——所以审计日志留下来了。这正好是"审计日志不能因为业务失败而丢失"的场景。

> 【思考】`REQUIRES_NEW` 真的"挂起"了外层事务吗？它底层怎么做到的？代价是什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：是的，它把外层事务的连接从线程 `ThreadLocal` 上解绑暂存，开一条新连接绑上去跑内层，内层结束提交/回滚后，再把外层连接绑回来。代价是：它需要两条物理连接，且内层提交后外层再回滚，两者已经不可逆——你失去了"统一回滚"的能力。**

**展开**：`TransactionSynchronizationManager` 用 `ThreadLocal` 存"当前线程绑定的连接"。`REQUIRES_NEW` 的 `TransactionInterceptor` 处理时：

1. 把外层事务的 `Connection` 从 `ThreadLocal` 取出、暂存（挂起）。
2. 从池里借一条**新** `Connection`，设 `autoCommit=false`，绑到 `ThreadLocal`，开新事务。
3. 执行内层方法，结束 `commit`（此时内层已落库，不可逆）。
4. 把内层连接解绑、归还/保留，把外层连接重新绑回 `ThreadLocal`，外层事务恢复。

所以内层一旦提交就独立生效，外层后来回滚影响不到它——这是 `REQUIRES_NEW` 的语义，也是它的危险：你以为"都在一个 `@Transactional` 里会一起回滚"，其实 `REQUIRES_NEW` 的那段早就单方面提交了。

**代码锚点——误用导致"部分提交"**：

```java
@Transactional
public void batch() {
    step1();                 // REQUIRED，和外层同事务
    audit();                 // REQUIRES_NEW，自己先提交
    step2();                 // 抛异常 => 外层回滚，但 audit 已落库
}
// 结果：audit 在、step1 不在 => 数据不一致，且很难查
```

**更深一层**：传播行为不是装饰品，是在定义"事务边界怎么切"。`REQUIRED` 把多个方法并成一个原子单元；`REQUIRES_NEW` 主动把一段切出去独立提交——你用它前要想清楚"这段是不是真的可以和外层不一致地提交"。审计、通知、计费等"副作用型"写操作才适合 `REQUIRES_NEW`；业务主链路千万别乱用，否则你会收获一堆"外层回滚了但某段还在"的幽灵数据。

</details>

**隔离级别（isolation）** 直接对齐数据库的隔离级别：`READ_UNCOMMITTED`、`READ_COMMITTED`、`REPEATABLE_READ`、`SERIALIZABLE`。`@Transactional(isolation = Isolation.READ_COMMITTED)` 会把这个级别传给数据库连接的会话设置。**Spring 默认是 `Isolation.DEFAULT`，即"用数据库自己的默认级别"**——MySQL 默认 `REPEATABLE_READ`，PostgreSQL 默认 `READ_COMMITTED`。所以你写 `@Transactional` 不配 isolation，落到哪一级完全看底层库。想统一行为，显式配。

**问题 6：** 那隔离级别是 Spring 实现的还是数据库实现的？

是**数据库**实现的。Spring 只是在开事务时给连接 `SET TRANSACTION ISOLATION LEVEL ...`，真正的锁、MVCC、快照读都是数据库干的。Spring 不重新发明隔离语义，只是把"连接级别的隔离设置"自动化了。这点要清楚，否则你会去 Spring 文档里找"隔离级别怎么实现的"，找不着——它在 MySQL/PG 的文档里。

---

## 17.9 案例二：自调用导致库存超卖

这是 `@Transactional` 失效场景里最高频、也最能让你背锅的一个。你从 Go 过来，因为在 Go 里根本不存在这个问题（第 14 章讲过），所以第一次遇到会非常懵。

**现象**：大促期间，库存偶发超卖——明明库存只有 100，却被卖出了 103 件，数据库里库存变成负数。日志没有任何报错，接口都返回"成功"。

**排查过程**：
1. 看扣库存的代码：

```java
@Service
public class OrderService {
    @Transactional
    public void createOrder(OrderCmd cmd) {
        for (OrderItem item : cmd.items()) {
            this.deductStock(item.sku(), item.qty());   // 自调用！
        }
        orderRepository.save(cmd.toOrder());
    }

    @Transactional                                     // 期望：每次扣减在一个事务里
    public void deductStock(String sku, int qty) {
        Stock s = stockRepository.findBySku(sku);      // SELECT 当前库存
        if (s.getQty() < qty) throw new BizException("库存不足");
        s.setQty(s.getQty() - qty);
        stockRepository.save(s);                       // UPDATE
    }
}
```

2. `createOrder` 调 `this.deductStock(...)`——`this` 是原始对象（Spring 注入的是代理，但 `this` 这个 Java 关键字永远指向自身），**绕过代理**，`deductStock` 上的 `@Transactional` 根本没生效。于是 `findBySku` 和 `save` 各跑在自动提交的连接上，不是同一个事务。
3. 更糟的是：即使加了事务，这里是 `SELECT` 再 `UPDATE`（读-改-写），并发下两个请求同时 `SELECT` 到库存 100，都 `UPDATE` 成 100-qty，第二个覆盖第一个——**丢失更新（lost update）**。自调用没开事务让这个问题彻底暴露。
4. 用 14.8 的招：`orderService.getClass().getName()` 打印是代理名，但调用发生在 `this` 上，代理没被用上——所以光看类名证明不了"调用走了代理"，得读代码发现 `this.`。

**根因**：`this.deductStock` 自调用绕过 AOP 代理，`@Transactional` 未触发；且扣减逻辑用"先查后改"而非 DB 原子更新，并发下丢失更新。

**修复（两处，缺一不可）**：
- 把 `deductStock` 拆到独立的 `StockService`，`OrderService` 注入它后调用，走代理：

```java
@Service
public class StockService {
    @Transactional
    public void deduct(String sku, int qty) {
        // 用 DB 原子更新，而非先查后改：UPDATE stock SET qty = qty - ? WHERE sku = ? AND qty >= ?
        int rows = jdbcTemplate.update(
            "UPDATE stock SET qty = qty - ? WHERE sku = ? AND qty >= ?", qty, sku, qty);
        if (rows == 0) throw new BizException("库存不足");   // 受影响行数 0 = 扣减失败
    }
}
```

- 库存扣减改用单条 `UPDATE ... WHERE qty >= ?`，把"判断+扣减"交给数据库原子完成，并发安全。

**教训**：
1. `@Transactional` 自调用失效是头号坑，**凡是"一个方法调本类另一个 `@Transactional` 方法"，先怀疑它**。
2. 库存/余额这类"读-改-写"操作，绝不能用"先 SELECT 再 UPDATE"在应用层算——必须用 DB 原子 `UPDATE ... WHERE 条件`，否则并发下必然丢更新。事务能保一致性，但保不了"非原子的读改写"。
3. Go 老哥的直觉是对的：在 Go 里 `tx := db.Begin(); s.deduct(tx, ...)` 传的是显式事务，没有"代理被绕过"这回事。Java 这边，把依赖关系想清楚——谁调谁、是不是走代理——是写 `@Transactional` 前的必修课。

---

## 17.10 案例三：漏写 rollbackFor，脏数据入库

**现象**：一个"下单 + 风控校验"的方法，风控接口偶尔超时抛 `RiskCheckException`（自定义业务异常）。按理整个下单该回滚，但事实是：订单落库了，风控也"记了一笔失败"，但**订单状态是已支付、库存没扣**——脏数据。更诡异的是，只有风控抛这个异常时才脏，其他 `NullPointerException` 时却正常回滚。

**排查过程**：
1. 看风控异常的定义：

```java
public class RiskCheckException extends Exception {   // 注意：extends Exception，是受检异常
    public RiskCheckException(String m) { super(m); }
}
```

2. 看 `@Transactional`：

```java
@Transactional                                          // 没配 rollbackFor
public void createOrder(OrderCmd cmd) throws RiskCheckException {
    orderRepository.save(cmd.toOrder());                // 写订单（已提交）
    riskClient.check(cmd);                              // 抛 RiskCheckException（受检）
    stockService.deduct(cmd);                           // 没执行到
}
```

3. `RiskCheckException` 是 `extends Exception` 的**受检异常**。`@Transactional` 的默认回滚规则只认 `RuntimeException` 和 `Error`——受检异常默认**提交**。所以 `orderRepository.save` 在自动提交（代理没收到回滚信号）下落库了，风控失败但订单已成。
4. 为什么 `NullPointerException` 时正常回滚？因为 `NPE` 是 `RuntimeException`，命中默认回滚规则。这也解释了"只有风控异常才脏"——异常类型不同，命运不同。

**根因**：自定义业务异常是受检异常（继承 `Exception`），而 `@Transactional` 默认不回滚受检异常，导致事务提交了脏数据。

**修复**：

```java
@Transactional(rollbackFor = Exception.class)            // ✅ 显式：所有异常都回滚
public void createOrder(OrderCmd cmd) throws RiskCheckException {
    ...
}
```

或者更干净：让业务异常继承 `RuntimeException`（`public class RiskCheckException extends RuntimeException`），符合"业务异常就是未受检"的 Java 惯例，默认就会回滚。

**教训**：
1. **业务异常一律继承 `RuntimeException`**，或 `@Transactional` 显式写 `rollbackFor = Exception.class`。这是 Java 项目里"脏数据"的头号来源之一。
2. 排 `@Transactional` 不回滚的顺序：先看是不是自调用（17.9）→ 再看异常是不是受检且没配 `rollbackFor` → 再看是不是 `private`/`final`（代理覆盖不了，见 14.5）。
3. Go 没有这个坑：gorm 里 `tx, err := db.Begin(); ... if err != nil { tx.Rollback() }` 回滚不回滚全看你是否 `Rollback`，和异常类型无关——因为 Go 根本没有 checked exception 这套分类。你转到 Java，得把"异常类型决定回滚"刻进肌肉记忆。

---

## 17.11 Spring Data JPA：自动生成 SQL 的便利与失控

讲完底层，往上走一层。你第 16 章看到的 `OrderRepository` 多半不是手写的 `JdbcTemplate`，而是这样的：

```java
@Entity                                      // 标记这是一张表
public class Order {
    @Id                                       // 主键
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private Long userId;
    private BigDecimal amount;
    // getter / setter
}

public interface OrderRepository extends JpaRepository<Order, Long> {
    // 方法名派生 SQL：findBy + 字段名 + And/Or => 自动生成 SELECT
    List<Order> findByUserIdAndAmountGreaterThan(Long userId, BigDecimal amount);

    // 不用写任何 SQL，框架按命名规则生成
}
```

你只写了一个接口继承 `JpaRepository<Order, Long>`，连实现类都没有，`findAll`、`save`、`findById`、`delete` 全有了；方法名 `findByUserIdAndAmountGreaterThan` 被 JPA 解析成 `SELECT ... WHERE user_id = ? AND amount > ?`。这就是 **Spring Data JPA**：用"接口 + 方法命名规范"替你生成 SQL 和实现。

`CrudRepository` 提供最基础的 `save` / `findById` / `existsById` / `delete`；`JpaRepository` 继承它，再加分页（`Pageable`）、批量、`flush` 等。你日常用 `JpaRepository` 就够了。

它的定位，和 MyBatis 是光谱两端：

| 维度 | Spring Data JPA | MyBatis（第 18 章） |
|---|---|---|
| SQL 谁写 | 框架按方法名/注解自动生成 | 你手写（XML 或注解） |
| 对象↔表映射 | `@Entity` 注解，全自动 | `resultMap` / 注解，半自动 |
| SQL 可控性 | 低，复杂查询难调 | 高，完全掌控 |
| 上手成本 | 低，CRUD 几乎零代码 | 中，要写 SQL 和映射 |
| 失控风险 | 生成的 SQL 低效（N+1、笛卡尔积）你未必察觉 | SQL 在你手里，慢能直接看见 |

JPA 的便利是真便利：规整的 CRUD 你一行 SQL 不写。但它的**失控风险也是真的**——`@OneToMany` 懒加载触发 N+1 查询、复杂 `JOIN` 生成的 SQL 难以预期、分页在大表上拖垮 DB。等你发现"一个简单的 `findByXxx` 居然打了 200 条 SQL"时，已经踩进去了。

> 【思考】既然 JPA 这么容易"生成失控的 SQL"，为什么还有人用？它到底解决了什么你真正在意的问题？

<details>
<summary><b>参考答案</b></summary>

**直接答案：它解决的是"对象模型和关系模型的阻抗失配（impedance mismatch）"——你用 Java 对象思考，数据库用表和行存储，JPA 把这道翻译自动化了。对于 CRUD 规整、模型稳定、不追求极致 SQL 控制的业务，它把"建表、映射、基础查询"三件事一次干完，开发速度碾压手写。**

**展开**：没有 JPA 时，你要手写：DDL 建表、实体类、`RowMapper` 把行转对象、每个查询的 SQL。JPA 用 `@Entity` 一处声明，建表（`hbm2ddl` 或配合 Flyway）+ 映射 + CRUD 全自动。对"用户、订单、地址"这种朴素领域模型，这是巨大的省力。

但它解决的"翻译"问题，在复杂查询场景会变成"失控"：ORM 要同时讨好对象模型和 SQL，于是它生成的 SQL 常常不是人写的最优形态。`@OneToMany` 默认懒加载，你遍历集合时每条触发一条查询（N+1）；你以为一次 `JOIN` 搞定，实际几十次 round-trip。

**更深一层**：JPA vs MyBatis 不是"谁更好"，是"SQL 控制权归谁"的取舍。JPA 把控制权交给框架换速度，代价是 SQL 黑箱（你要学怎么引导它生成好 SQL：`@EntityGraph`、警惕懒加载、用 DTO 投影）；MyBatis 把控制权留给你换"要自己写"，代价是样板。你从 Go 过来，gorm 其实更接近 JPA 的"自动挡"哲学（AutoMigrate + 链式查询），而 Go 社区也常说"复杂查询还是手写 SQL 吧"——这心态和 Java 圈"简单用 JPA、复杂上 MyBatis"完全一致。**下一章 MyBatis 就是给你"把 SQL 写回自己手里"的那个选项。**

</details>

---

## 17.12 本章核心结论

如果这一章你只看这一段：

1. **JDBC 三层抽象是 Connection / Statement(PreparedStatement) / ResultSet**；驱动发现靠 SPI（`META-INF/services/java.sql.Driver`），`DriverManager` 用 `ServiceLoader` 自动加载，不用 `Class.forName`。
2. **裸 JDBC 没人直接写，因为样板多、资源（`Connection`/`Statement`/`ResultSet`）极易泄漏**；三层 `try/finally` 关资源既丑又易错，漏关一条就拖垮连接池。
3. **连接池是必须的**：建物理连要 TCP+握手+认证，开销大且有 `max_connections` 上限；`DataSource` 是抽象支点，上层只认 `getConnection()`，换池子实现不改业务。
4. **HikariCP 快在 `ConcurrentBag` 无锁复用 + 字节码单态优化 + 默认配置就优**；四个要命参数里，`maxLifetime` 必须小于 MySQL `wait_timeout`，否则借到死连接报 `Communications link failure`。
5. **`JdbcTemplate` 用模板方法替你关资源、防注入，但不替你管对象映射**；它不池化（池在 `DataSource`），和 Go 的 `sql.DB`（既池化又关资源）职责划分不同。
6. **`@Transactional` 是 AOP 代理落地**：`TransactionInterceptor` 开事务（借连接、`autoCommit=false`、绑线程 `ThreadLocal`）、提交/回滚；`@EnableTransactionManagement` 默认开启。
7. **两个高频失效：自调用（`this` 绕过代理，事务没开）+ 漏 `rollbackFor`（受检异常默认提交，脏数据入库）**；默认只回滚 `RuntimeException`/`Error`。传播行为 `REQUIRED` 合并、`REQUIRES_NEW` 独立提交、`NESTED` 用保存点。
8. **JPA 自动生成 SQL 省事但 SQL 易失控（N+1 等）**，MyBatis 把 SQL 交回你手写——下一章专门讲。

---

## 17.13 深度思考题

> 【思考】Go 的 `sql.DB` 和 Java 的 `DataSource` + `JdbcTemplate`，到底谁干了更多活？

<details>
<summary><b>参考答案</b></summary>

**直接答案：Go 的 `sql.DB` 一个对象干了 Java 两个对象（`DataSource` 管池 + `JdbcTemplate` 管资源关闭）的活——`sql.DB` 既内置连接池，又在你 `Query`/`QueryRow` 结束时自动归还连接；Java 这边池化和资源关闭是分开的两层抽象。**

**代码锚点——职责对比**：

```go
// Go：sql.DB 一身兼两职
db, _ := sql.Open("mysql", dsn)
db.SetMaxOpenConns(20)                 // 池化配置在 sql.DB 上
rows, _ := db.Query(ctx, "SELECT ...") // 查完 rows.Close() 还连接，池内置
```

```java
// Java：DataSource 管池，JdbcTemplate 管关
HikariDataSource ds = new HikariDataSource();   // 池化在 DataSource
ds.setMaximumPoolSize(20);
JdbcTemplate jt = new JdbcTemplate(ds);          // 关资源在 JdbcTemplate
jt.query("SELECT ...", (rs, n) -> ...);          // 内部自动关 rs/ps/conn
```

**更深一层**：这是 Go 标准库"小而全"和 Java"接口细分、各司其职"的哲学差异。`sql.DB` 是 Go 团队替你定好的"数据库句柄 = 池 + 查询"，你不用选池实现；Java 把"抽象（DataSource）"和"便利（JdbcTemplate）"拆开，换来"池可以随便换（HikariCP/Druid）、便利层也可以换（JdbcTemplate/Spring Data）"的灵活。两种都合理，你从 Go 过来会觉得 Java 这层分得碎，但碎片化换来的是每个点都能独立替换。

</details>

> 【思考】如果 `@Transactional` 方法里新开了一个线程去跑任务，这个任务里查库，会和主事务在同一事务里吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不会。事务绑定在当前线程的 `ThreadLocal` 上（17.7 讲的 `TransactionSynchronizationManager`）。新线程没有这个 `ThreadLocal`，它去 `DataSource` 拿连接时取不到绑定连接，会自己借一条新连接——于是新线程里的数据库操作是**独立的新事务（或自动提交），不属于外层 `@Transactional`。**

**代码锚点——典型翻车**：

```java
@Transactional
public void createOrder(OrderCmd cmd) {
    orderRepository.save(cmd.toOrder());          // 主线程，外层事务
    new Thread(() -> {
        stockService.deduct(cmd);                 // 新线程，拿不到绑定连接 => 独立连接/事务
    }).start();
    // 主事务提交了，但新线程可能还没跑完 => 时序错乱 + 不在同一事务
}
```

**更深一层**：这条坑揭示了"事务上下文不能跨线程传递"这个事实。Spring 的事务上下文是 `ThreadLocal`，天然线程封闭。你要"事务内异步"，得用 `@Async` + 事务传播的特殊处理（或把连接/事务显式传进线程），而不是随手 `new Thread`。这点和 Go 不同：Go 的 `tx *gorm.DB` 是值/指针，你 `go func(tx *gorm.DB){...}(tx)` 把事务对象传进 goroutine 就能共用——Go 的"显式传参"反而在这儿更安全，因为你清楚地把事务交了出去；Java 的 `ThreadLocal` 隐式绑定，新线程悄悄拿不到，静默地开了新事务。

</details>

> 【思考】既然 `maxLifetime` 必须小于 `wait_timeout`，那我直接把 `maxLifetime` 设成 1 秒，连接永远新鲜，行不行？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不行。`maxLifetime` 太小，每条连接只用 1 秒就被强制回收重建，等于把连接池退化成"每次借都新建物理连接"——你又回到了 17.3 说的"建连开销吃掉 RT"的老路，连接池的意义没了。`maxLifetime` 要"小于 `wait_timeout` 但远大于典型请求耗时"，通常设成 `wait_timeout` 的 1/3 到 1/2，留足余量。**

**展开**：`maxLifetime` 的用意是"淘汰那些可能被 DB 悄悄断开的长寿连接"，不是"频繁换连接"。它设得太小，池子永远在销毁旧连接、建新连接，建连的网络握手 + 认证开销被放大到每一次借连接。经验值：MySQL `wait_timeout` 默认 8 小时，`maxLifetime` 设 30 分钟（1800000ms，HikariCP 默认值）就很稳；若 `wait_timeout` 被 DBA 调小（如 60s），则 `maxLifetime` 设成 `wait_timeout` 的约 80%（如 50s），既避免借到死连接，又不至于频繁重建。

**更深一层**：所有"生命周期/超时"类参数，本质都是在两个成本之间取平衡——`maxLifetime` 太大会借到死连接（正确性成本），太小会频繁重建（性能成本）。你调任何超时参数，都先问自己"它在避免哪种失败、又在引入哪种开销"，而不是无脑取极值。

</details>

> 【思考】为什么 Spring Data JPA 的 `findByXxx` 方法名能变成 SQL，而 Go 的 gorm 也要你写链式调用，两者"自动"的层级差在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：JPA 的"自动"是**编译期/启动期的方法名解析**——Spring Data 在启动时扫描你的 Repository 接口，把 `findByUserIdAndAmountGreaterThan` 按命名规则解析成 JPQL/SQL 并生成代理实现，你连实现类都不写。gorm 的"自动"是**运行期的链式 API 拼接**——你写 `db.Where("user_id = ?", uid).Where("amount > ?", amt).Find(&orders)`，SQL 在调用时由方法链拼出来。JPA 是"声明式自动生成实现"，gorm 是"流畅 API 拼 SQL"。

**展开**：这是两种"少写代码"的路子：
- JPA：`interface OrderRepository extends JpaRepository<...>`，方法签名即查询契约，框架启动时用反射 + 命名解析生成字节码实现。你零实现、零 SQL 字符串。代价：复杂查询命名写不下（要用 `@Query` 写 JPQL），且生成的 SQL 不透明。
- gorm：`db.Model(&Order{}).Where(...).Find(...)`，你显式写链式条件，SQL 由链拼成。代价：每次调用都要写这串链（样板），但 SQL 完全在你眼前、可控、可调试。

**更深一层**：JPA 的"方法名即查询"是把"查询意图"声明在方法签名上，靠框架翻译成 SQL——更接近"声明式"；gorm 的链式是把"查询构建"变成一个可组合的函数调用序列——更接近"可编程"。你从 Go 过来会觉得 gorm 的链式更"看得见"，JPA 的方法名更"省事但黑箱"。这两条路，恰好对应 JPA 和 MyBatis 那张对照表里的"SQL 控制权归谁"：JPA 把构建也交给框架，gorm 把构建留给你（只是不用写原始 SQL 字符串），MyBatis 连 SQL 文本都留给你。自动化程度递减，控制力递增。

</details>

---

## 下一章预告

第 18 章讲 **MyBatis：为什么有了 JPA 还要它、XML/注解映射、`#{}` vs `${}`、动态 SQL、一级二级缓存**。

这一章你看到 JPA 自动生成 SQL 的便利，也看到它的失控风险（N+1、生成的 SQL 难以预期）。当你不想把 SQL 交给框架、要把 SQL 一行行写回自己手里、要精确控制 `JOIN` 和分页性能时，MyBatis 就是那个选项。第 18 章会讲清：`#{}` 和 `${}` 的注入天壤之别（呼应 17.2 的 `PreparedStatement` 防注入）、`<if>`/`<foreach>` 动态 SQL 怎么拼、`resultMap` 怎么把行映射成对象，以及 MyBatis 那两级缓存为什么又是一个"默认开着但容易踩"的隐式能力——和第 14 章的"声明式能力 = 代理边界"是同一个脾气，只是换到了 SQL 层。读完第 18 章，你对"Java 项目里 SQL 到底从哪来"就彻底有底了。
