# 第 18 章　MyBatis：把 SQL 写回你手里（XML/注解映射与动态 SQL）

> 你接手了一个订单服务，DAO 层是 Spring Data JPA。某天运营说"月度对账报表"跑一次要八秒。你点开那个 `ReportRepository`，看到一个 `@Query` 写了一坨 JPQL，EXPLAIN 一跑发现它先 SELECT 出三千个订单，再对每一个订单发一条 SQL 去查退款记录——经典的 N+1，而你翻遍代码找不到一条能改的 SQL，它藏在 `SimpleJpaRepository` 的反射生成逻辑里。
> 你想直接写一条带 `LEFT JOIN` 的聚合 SQL，却发现自己被"对象关系映射"架空了：你想控制 SQL，SQL 不在你手里。这时候，有人给你递了 MyBatis。

---

## 18.1 为什么 JPA / Spring Data 用得好好的，还要 MyBatis

先把话说清楚：JPA 和 Spring Data 不是"落后产能"。它的核心卖点是**对象关系映射（ORM）**——你写 `User` 这个实体类，框架替你管建表、管 CRUD、管 `findByStatus` 这种按命名规则自动生成的方法。第 17 章你会看到，`JpaRepository` 一个接口继承下来，增删改查连实现都不用写。对标准 CRUD 场景，这是真省事。

但 ORM 的代价，恰恰出在它最得意的地方：**SQL 是框架替你生成的，不在你手里**。

你作为 Go 老哥，对"SQL 不可控"这件事的厌恶程度应该比 Java 新人高。你写过 `db.Raw("SELECT ... ").Scan(&res)`，SQL 是你亲手敲的，慢了你能直接拿去 `EXPLAIN`。JPA 把这道门焊死了，于是出现三个具体问题：

1. **复杂查询难控**：多表聚合、窗口函数、`EXISTS` 子查询，用 JPQL（JPA 的面向对象查询语言）写别扭，用 `@Query` 写原生 SQL 又退化成"在注解里写裸 SQL"，那还 ORM 什么？
2. **N+1 隐患**：关联对象懒加载，一不小心就在循环里多发 SQL。根因是框架替你决定"查几次"，而你以为只查了一次。
3. **生成的 SQL 你不一定信**：`findAll()` 背后是 `SELECT *` 全字段，`Page` 分页背后到底是 `LIMIT` 还是游标，你不去翻 Hibernate 源码根本不知道它吐了什么给数据库。

MyBatis 的哲学正相反——**它不跟你玩 ORM 的自动生成，它把 SQL 明文交还给你**，写在 XML 或注解里，你写什么它发什么。它不是 ORM，是"SQL 映射框架"：你给 SQL，它负责把参数填进去、把结果集扫进对象。控制权回到你手上。

> 【思考】既然 MyBatis 也要手写 SQL，那它和"直接用 `JdbcTemplate` 手敲 SQL + 自己 `ResultSet` 扫描"有什么区别？多这一层代理图什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：区别在"样板代码"。`JdbcTemplate` 你得自己写 `RowMapper` 把每一行 `ResultSet` 手动 `rs.getString("x")` 映射到对象；MyBatis 用 Mapper 接口 + 映射文件把这层样板全自动了，还白送你动态 SQL 标签、一级/二级缓存、参数类型转换。

**展开**：用 `JdbcTemplate` 查一个 `User`，长这样：

```java
// JdbcTemplate：SQL 是你写的，但映射也得你手写
List<User> users = jdbcTemplate.query(
    "SELECT id, name, email FROM user WHERE status = ?",
    (rs, rowNum) -> {                       // 手写 RowMapper，逐字段搬
        User u = new User();
        u.setId(rs.getLong("id"));
        u.setName(rs.getString("name"));
        u.setEmail(rs.getString("email"));
        return u;
    }, status);
```

每加一个字段，这里就多三行。字段多了，这个类一半代码都在干"搬运工"。

MyBatis 等价的写法：

```java
// MyBatis：SQL 还是你写的，但映射交给框架
@Select("SELECT id, name, email FROM user WHERE status = #{status}")
List<User> findByStatus(@Param("status") int status);   // 返回类型一标，自动扫进 List<User>
```

你看，SQL 仍然在你手里（这正是你要的），但"参数填占位符"和"结果扫进对象"这两件重复到死的苦力活被框架接管了。你得到的是"手写 SQL 的掌控感 + 接近 JPA 的便捷度"，这就是 MyBatis 存在的理由——**它不抢你的 SQL，只替你搬砖**。

**更深一层**：这个取舍暴露了 Java 持久层的两极——JPA 是"对象优先，SQL 由我生成"，MyBatis 是"SQL 优先，映射由我代劳"，`JdbcTemplate` 是"全手动，连映射都自己来"。Go 老哥你的直觉是对的：要掌控 SQL 就该选 MyBatis 这一极；但别走到 `JdbcTemplate` 全手动那一级，那是在用 2026 年的框架干 2005 年的活。

</details>

**问题 1**：那是不是"简单 CRUD 用 JPA，复杂报表用 MyBatis"就完美了？很多项目确实是这么干的——一个工程里 JPA 和 MyBatis 混用。这算不算精神分裂？

不算。这是国内互联网项目的常态，叫"双引擎"。`UserRepository extends JpaRepository` 管单表增删改查，`ReportMapper` 管复杂聚合。代价是团队要懂两套心智模型，但收益是各取所长。你作为接盘侠，看到工程里既有 `Repository` 又有 `Mapper` 别慌，先判断这个 DAO 是单表操作还是报表操作，再决定去翻 `JpaRepository` 还是去翻 `XxxMapper.xml`。

---

## 18.2 MyBatis 的核心抽象：SqlSessionFactory → SqlSession → Mapper

要懂 MyBatis，先把它那条"生产线"摸清楚。它和你在第 17 章看到的 `DataSource`（通常是 HikariCP 连接池）是直接咬合的：

```
DataSource(HikariCP)  →  SqlSessionFactory  →  SqlSession  →  Mapper 接口(代理)
   (连接从哪来)           (工厂,全局一个)      (一次会话=一个连接)   (你调用的接口)
```

- **`SqlSessionFactory`**：全局一个，持有着 `DataSource`。你说"给我一个会话"，它就从连接池拿一条连接，包成 `SqlSession`。
- **`SqlSession`**：代表一次数据库会话，里面揣着一条 JDBC 连接。它既能直接 `selectOne/insert`（老式用法），也能 `getMapper(XxxMapper.class)` 拿到 Mapper。
- **Mapper**：就是你定义的那个接口。你从不 `new` 它——`sqlSession.getMapper(UserMapper.class)` 返回的是一个**代理对象**。

**问题 2**：为什么 Mapper 是接口、却能被"调用"？接口没有实现类，谁在跑那段 SQL？

这时候第 14 章的知识派上用场了。MyBatis 的 Mapper 默认就是用 **JDK 动态代理**实现的——和 Spring AOP 的 JDK 代理是同一套机制（`InvocationHandler`）。MyBatis 写了个 `MapperProxy` 类实现 `InvocationHandler`，你调 `userMapper.findById(1L)` 时，实际进的是 `MapperProxy.invoke(...)`，它根据"接口全限定名 + 方法名"去映射文件里找到对应的 SQL，填参、执行、扫结果，再把结果还给你。

```java
// MyBatis 怎么把接口变成能跑的东西(简化)
UserMapper mapper = sqlSession.getMapper(UserMapper.class);
// 上面返回的其实是 Proxy.newProxyInstance(...) 生成的代理
// 调 mapper.findById(1L) → MapperProxy.invoke() → 按 namespace+id 找 SQL → 执行
```

所以 Mapper 接口本身一个方法体都没有，它只是个"钥匙"——钥匙的形状（方法签名、返回类型）告诉 MyBatis 要什么，MyBatis 拿这把钥匙去开映射文件里对应的那把锁。

> 【思考】既然靠 JDK 动态代理，那 Mapper 能不能写成一个普通类（不是接口）？比如 `class UserMapperImpl`？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：不能。MyBatis 默认用 JDK 动态代理，而 `Proxy.newProxyInstance` 的第二个参数必须是**接口数组**——它只能生成"接口的实现类"，没法代理普通类。所以 Mapper 必须是 `interface`。这也正是第 14 章讲的那条铁律：JDK 代理只能代理接口，CGLIB 才能代理类；MyBatis 选了 JDK 代理这条路，所以 Mapper 必须是接口。

**展开**：如果你非要写类，MyBatis 也有基于 CGLIB 的 `MapperFactoryBean`（早期整合 Spring 时的老写法），但现代 MyBatis（MyBatis-Spring Boot Starter）统一走接口 + JDK 代理。原因很实在：Mapper 本就该是"纯签名、无状态、无逻辑"的，接口天然契合——你不能在 Mapper 接口里写业务逻辑（写了也没用，代理根本不调用你的实现），这就从语法层面逼你"接口只声明 SQL 契约，逻辑放 Service 层"。

**Go 对照**：Go 这边根本没这层代理戏法。你要"接口即 SQL"，要么用 `sqlx` 直接 `db.Named(query, params)` 然后 `StructScan`，要么用 `gorm` 的 `db.Raw(...).Scan(&res)`：

```go
// Go：没有 Mapper 接口，SQL 和扫描都在调用点附近
type User struct {
    ID    int64  `db:"id"`
    Name  string `db:"name"`
    Email string `db:"email"`
}
var users []User
// Named 把结构体字段按名字填进 :name 占位符,StructScan 按 db tag 扫回
db.Named("SELECT id,name,email FROM user WHERE status=:status", map[string]any{"status": 1})
db.Select(&users, "SELECT id,name,email FROM user WHERE status=?", 1)
```

Go 的哲学是"SQL 在哪调，就写哪"，没有"接口 ↔ XML 绑定"这套中间层。MyBatis 的"接口即 SQL"是 Java 的"注解 + 动态代理 + XML"三件套独有的形态，你初学会觉得绕，但习惯后会发现它把"SQL 散落各处"收编到了统一命名空间。

**更深一层**：Mapper 必须是接口这件事，本质上是 MyBatis 借用了 JVM 的"接口=契约"语义来省去一堆模板。接口没有字段、没有实现，它唯一承载的信息就是"方法签名"——而这恰恰是定位一条 SQL 所需的全部信息（方法名 = SQL 的 id，参数类型 = 入参，返回类型 = 结果映射）。MyBatis 用代理把"接口签名"翻译成"SQL 调用"，是 Java 动态代理最经典的运用场景之一，和 Spring 用代理做 AOP 异曲同工。

</details>

**问题 3**：在 Spring Boot 里我从来没写过 `sqlSession.getMapper(...)`，为什么直接 `@Autowired UserMapper` 就能用？

因为 `mybatis-spring-boot-starter` 帮你把每个 Mapper 接口都注册成了 Spring Bean（靠 `@MapperScan` 扫包，或接口上标 `@Mapper`）。它内部做的事就是：启动时用 `SqlSessionFactory` 给每个 Mapper 接口生成代理，塞进 Spring 容器。你 `@Autowired` 拿到的就是那个代理。注意——它既然是 Spring Bean，就受第 14 章那套约束：单例、可被 AOP 代理包裹。MyBatis 自己那层 JDK 代理，外面可能还套着 Spring 的代理。

---

## 18.3 XML 映射 vs 注解映射：怎么选

MyBatis 给你两条路写 SQL，别纠结，各有地盘。

**注解映射**：SQL 直接写在接口方法上，适合简单单表 SQL。

```java
@Mapper
public interface UserMapper {
    @Select("SELECT id, name, email FROM user WHERE id = #{id}")
    User selectById(@Param("id") Long id);           // 简单查询,注解最清爽

    @Insert("INSERT INTO user(name,email) VALUES(#{name},#{email})")
    @Options(useGeneratedKeys = true, keyProperty = "id")   // 回填自增主键到对象
    int insert(User user);
}
```

**XML 映射**：SQL 写在独立的 `XxxMapper.xml` 里，靠 `namespace` + `id` 和接口绑定。适合复杂、尤其是带动态 SQL 的语句。

```xml
<!-- UserMapper.xml：namespace 必须 = Mapper 接口全限定名 -->
<mapper namespace="com.example.mapper.UserMapper">
    <!-- id 必须 = 接口方法名; resultType 告诉 MyBatis 把行扫进哪个类 -->
    <select id="selectById" resultType="com.example.entity.User">
        SELECT id, name, email FROM user WHERE id = #{id}
    </select>
</mapper>
```

绑定的关键就两条：**`namespace` 必须等于 Mapper 接口的全限定名**，`<select id="...">` 必须等于方法名。MyBatis 启动时把 XML 里的每条语句登记成 `namespace + "." + id`，你调接口方法时，代理拿"接口全限定名.方法名"去这个登记表查 SQL。

**问题 4**：既然注解也能写 SQL，为什么大家都说"复杂 SQL 必须放 XML"？注解里不能写动态 SQL 吗？

能，注解里可以用 `<script>` 包动态 SQL（如 `@Select("<script>SELECT ... <where>...</where></script>")`），但那玩意儿挤在 Java 字符串里，换行、缩进、XML 标签全糊成一团，可读性灾难。所以约定俗成：**带 `<if>`/`<foreach>` 的、超过三五行的 SQL，一律 XML；单表 CRUD、字段少的，用注解**。你接手老项目如果看到注解里塞 `<script>`，那是前任在偷懒，你可以心安理得地把它挪去 XML。

> 【思考】`namespace` 为什么要和接口全限定名一致？如果我故意写成不一样的，会怎样？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：因为 MyBatis 用 `namespace + id` 当 SQL 的全局唯一地址。Mapper 代理调用方法时，拼出的查找键就是"接口全限定名.方法名"，它必须能在 XML 的 `namespace.id` 表里命中。你把 `namespace` 写错，代理拼出的键对不上，调方法就抛 `BindingException: Invalid bound statement (not found)`。

**展开**：这是 MyBatis 最高频的启动/调用期报错之一。现象通常是：

```
org.apache.ibatis.binding.BindingException:
Invalid bound statement (not found): com.example.mapper.UserMapper.selectById
```

排查四件套（按出现频率）：
1. XML 的 `namespace` 拼错（包名、类名多一个字母）。
2. `<select id="...">` 和方法名不一致（大小写、下划线）。
3. XML 文件没被编译进 `target/classes`（Maven 默认不打包 `src/main/java` 下的 xml，要在 `pom.xml` 的 `<resources>` 里配，或把 XML 放 `src/main/resources` 下同包路径下）。
4. 方法返回类型和 `resultType`/`resultMap` 对不上。

**Go 对照**：Go 没有这层"字符串键查找"，所以永远不会遇到 `Invalid bound statement`。你的 SQL 写在哪、调在哪，是静态可跳转的。MyBatis 这种"namespace + id 字符串绑定"是运行时才校验的，属于 Spring/MyBatis 那套"运行时魔法"的典型代价——和第 14 章 `@Transactional` 失效同源：**绑定关系藏在字符串里，编译期查不出来**。

**更深一层**：`namespace` 这个设计其实是 MyBatis 从 iBATIS（它祖宗，XML 驱动的）继承来的。它把"SQL 的寻址"和"Java 的包结构"对齐，好处是 IDE 可以按 `namespace` 反查接口、做跳转和重命名（现代 IDE 都支持）；坏处是这套对齐是**约定**，不是语言保证。你从 Go 过来要记住：凡是 MyBatis 报 `not found`，第一反应是"命名空间/方法名/编译路径"三连查，而不是怀疑 SQL 写错。

</details>

---

## 18.4 #{} 与 ${} 的本质区别：这是安全红线

这是全章最重要的一条，没有之一。两种占位符，天壤之别。

- **`#{}`**：MyBatis 把它翻译成 JDBC 的 **`PreparedStatement` 占位符 `?`**，参数走预编译、类型安全、天然防 SQL 注入。
- **`${}`**：MyBatis 把它当成**字符串拼接**，把变量的值原样替换进 SQL 文本里，再发给数据库。

```java
// #{} 安全：生成 SELECT ... WHERE name = ? , 参数 "ro" 作为字符串传入,不会破坏 SQL 结构
@Select("SELECT * FROM user WHERE name = #{name}")
User findByName(@Param("name") String name);

// ${} 危险：生成 SELECT ... WHERE name = ro , 若 name="x' OR '1'='1" 直接被注入
@Select("SELECT * FROM user WHERE name = ${name}")   // ❌ 拼接,注入温床
User findByNameBad(@Param("name") String name);
```

`#{}` 走的是 `PreparedStatement.setString(idx, value)`，数据库先编译带 `?` 的语句模板，`ro` 只是参数值，不可能被解释成 SQL 片段。`${}` 是纯文本替换，用户输入什么就拼什么进 SQL——这就等于把数据库的大门钥匙挂在输入框上。

那 `${}` 是不是一无是处？不是。它唯一合理的用武之地是**那些 SQL 语法里不能用占位符的地方**：表名（`FROM ${tableName}`）、排序字段（`ORDER BY ${column}`）、排序方向（`ASC/DESC`）。因为 `ORDER BY ?` 这种占位符在大多数数据库里是不合法的——列名不能被参数化。所以 `${}` 是"给框架用的动态结构"，不是"给用户输入用的"。

### 真实案例 ①：排序参数用 ${} 且前端可控，被注入拖库

一个列表接口，前端传 `orderBy` 决定按哪列排序，后端偷懒直接拼：

```java
// 后端(错误)：前端传什么就拼什么
@Select("SELECT id, name, phone FROM user ORDER BY ${orderBy}")
List<User> list(@Param("orderBy") String orderBy);
```

前端本该传 `create_time DESC`，但攻击者把 `orderBy` 改成：

```
id; DROP TABLE user; --
```

拼接后的 SQL 变成 `... ORDER BY id; DROP TABLE user; --`，数据库直接执行两条语句，用户表没了。或者更阴的，传 `1=1 UNION SELECT username,password,null FROM admin`，把管理员表数据通过你这个接口的返回字段拖出来。

**触发条件**：`${}` 接了外部输入（URL 参数、请求体、Header）。**现象**：数据被删/被泄露，WAF 可能拦不住（看起来是正常查询参数）。**根因**：`${}` 是文本替换，输入即 SQL。**修复**：排序字段/方向绝不用用户输入原值，走白名单枚举：

```java
// 正确：方向用白名单,列名从允许集合取,都不走 ${} 直接吞用户输入
String dir = "DESC".equalsIgnoreCase(orderDir) ? "DESC" : "ASC";   // 只有两个合法值
if (!Set.of("create_time","id","name").contains(orderBy)) {
    orderBy = "create_time";                                        // 非法列名回退默认
}
// 此时 ${orderBy}/${dir} 拼进去的已是你信任的常量,不是用户输入
```

> 【思考】那如果排序必须动态、又想绝对安全，有没有比"白名单 + ${}"更省心的写法？比如能不能用 `#{}` 拼排序？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：`#{}` 拼不了排序列名——`ORDER BY ?` 在大多数数据库会报语法错，因为列名不能被参数化（占位符只能替"值"，不能替"标识符"）。所以动态排序的标准解就是"白名单枚举 + `${}`"：你控制 `${}` 里只能是白名单内的常量，用户永远碰不到拼接点。要更省心，可以上 MyBatis 的 `<bind>` 或在 Java 侧用枚举 `Map<前端值, 真实列>`，彻底斩断"用户输入直达拼接"的路径。

**代码锚点——用枚举做映射,用户输入只当 key**：

```java
// 前端传 "time"/"name",后端翻译成真实列名,翻译失败就回退
private static final Map<String,String> COLUMNS =
    Map.of("time", "create_time", "name", "user_name", "id", "id");

public List<User> list(String orderKey, String orderDir) {
    String col = COLUMNS.getOrDefault(orderKey, "create_time");   // 用户输入只是 map 的 key
    String dir = "DESC".equals(orderDir) ? "DESC" : "ASC";        // 方向也只有两值
    return mapper.listOrder(col, dir);                            // XML 里 ORDER BY ${col} ${dir}
}
```

这里 `${col}` 拼进去的是 `"create_time"` 这种你代码里的常量，攻击者在 `orderKey` 里写 `DROP TABLE` 只会让 `getOrDefault` 返回默认列，根本进不了 SQL。

**更深一层**：`#{}` 与 `${}` 的区别，本质是"参数化查询 vs 字符串拼接"这条 SQL 安全的祖宗级纪律。你写 Go 用 `db.Query("... WHERE name = ?", name)` 从来都是占位符，因为 Go 的 `database/sql` 只有占位符一种玩法，根本没有"`${}` 拼接"这个坑——所以 Go 老哥转到 MyBatis 最大的一课就是：**永远默认 `#{}`，见到 `${}` 先问自己"这东西能不能被用户摸到"**。MyBatis 把注入的扳机做成了语法糖，这是它反直觉、也最危险的地方。

</details>

---

## 18.5 动态 SQL：<if> / <choose> / <foreach> / <trim><where><set>

真实业务的查询条件从来不是固定的：用户可能只填了姓名，可能只填了时间区间，可能姓名时间都填。你不想为每种组合写一条 SQL，于是 MyBatis 给了你动态 SQL 标签——在 XML 里按条件拼 SQL。

```xml
<select id="search" resultType="com.example.entity.Order">
    SELECT id, user_id, amount, status, create_time FROM orders
    <where>                                            <!-- where 自动去头 AND/OR,且内容空则不输出 WHERE -->
        <if test="userId != null">
            AND user_id = #{userId}                    <!-- 条件成立才拼这一句 -->
        </if>
        <if test="status != null">
            AND status = #{status}
        </if>
        <if test="start != null">
            AND create_time &gt;= #{start}             <!-- 注意 XML 里 > 要写 &gt; -->
        </if>
    </where>
    ORDER BY create_time DESC
</select>
```

- **`<if test="...">`**：`test` 是 OGNL 表达式，条件为真才拼标签体内容。
- **`<choose><when><otherwise>`**：等价于 Java 的 `switch`——多个 `when` 命中第一个，都不中走 `otherwise`。
- **`<foreach>`**：拼 `IN` 列表，比如 `id IN (1,2,3)`。
- **`<trim><where><set>`**：`where`/`set` 自动处理拼接时的"多余 AND/逗号"。

### 真实案例 ②：<if> 拼 WHERE 多出 AND/逗号，SQL 语法错

新手手写动态 SQL 常这么写（不用 `<where>` 标签）：

```xml
<!-- 错误：用户没传 userId 时,SQL 变成 WHERE  AND status = ? , 多出一个 AND,语法错 -->
<select id="search" resultType="Order">
    SELECT * FROM orders
    WHERE
        <if test="userId != null">user_id = #{userId}</if>
        <if test="status != null">AND status = #{status}</if>
</select>
```

当用户只传 `status` 时，拼出来是 `WHERE AND status = ?`——`WHERE` 后面直接跟 `AND`，数据库报 `You have an error in your SQL syntax`。同理 `<set>` 里多个 `<if>` 更新字段，容易在末尾多一个逗号：`SET name=?, email=,`，逗号导致语法错。

**修复**：用 `<where>` 标签，它有两招——内容以 `AND`/`OR` 开头时自动去掉；内容整体为空时不输出 `WHERE` 关键字。同理 `<set>` 自动去掉末尾多余的逗号。也可以用 `<trim prefix="WHERE" prefixOverrides="AND |OR ">` 手动控制。

```xml
<select id="search" resultType="Order">
    SELECT * FROM orders
    <where>                                           <!-- ✅ 自动去头 AND,空则无 WHERE -->
        <if test="userId != null">AND user_id = #{userId}</if>
        <if test="status != null">AND status = #{status}</if>
    </where>
</select>
```

`<foreach>` 拼 `IN` 是另一个高频点，参数别拼错：

```xml
<select id="byIds" resultType="Order">
    SELECT * FROM orders
    WHERE id IN
    <foreach collection="ids" item="id" open="(" close=")" separator=",">
        #{id}                                          <!-- 每个元素用 #{} 占位,安全 -->
    </foreach>
    <!-- 展开: id IN (?, ?, ?) -->
</select>
```

> 【思考】`<where>` 标签到底是怎么做到"智能去头 AND"的？它是字符串正则替换吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：不是简单的正则。MyBatis 的 `WhereSqlNode` 在拼接完内部内容后，会检查生成的 SQL 片段是不是以 `AND ` 或 `OR `（大小写不敏感，后跟空白）开头，如果是就截掉这段前缀；并且如果内部所有 `<if>` 都不成立、整段为空，它连 `WHERE` 关键字本身都不输出。它是在"SQL 片段树"层面做后处理，不是对最终字符串暴力替换。

**展开**：`<where>` 本质是 `<trim prefix="WHERE" prefixOverrides="AND |OR |AND\n|OR\n|...">` 的语法糖。它的逻辑是：
1. 先递归拼出内部所有子节点（`<if>` 等）的内容。
2. 如果拼出来是空串 → 整个 `<where>` 不输出任何东西（没有 `WHERE`）。
3. 如果拼出来以 `AND `/`OR ` 开头 → 去掉这个前缀，再补上 `WHERE`。

所以你写 `<if>AND user_id=#{...}</if>` 时，把 `AND` 写在里面是故意的——`<where>` 负责兜底去掉它。这就是为什么"每个 `<if>` 里的条件都带 `AND` 前缀"才是正确写法，而不是在 `<if>` 外统一写一个 `AND`。

**Go 对照**：Go 里你要动态拼 `WHERE`，要么用 `strings.Builder` 自己拼（然后自己处理前缀 AND、自己收集参数到 `[]any`），要么用 `sqlx` 的 `sq` 构造器（`sq.Select(...).Where(...)`）或 `gorm` 的链式 `db.Where(...).Where(...)`。Go 没有"标签"概念，全靠代码拼，所以你天然要为"第一个条件不加 AND"专门写逻辑——而 MyBatis 把这条逻辑收进了 `<where>` 标签。代价是 MyBatis 这套是"声明式、运行时拼接"，你看不到拼接过程；收益是少写大量 `if first { "WHERE " } else { " AND " }` 的脏代码。

**更深一层**：`<where>`/`<set>` 这种标签揭示了一个事实——MyBatis 的动态 SQL 不是"模板字符串"，而是一棵**SQL 节点树**，每个标签是一个节点，运行时按条件遍历生成 SQL 字符串。这和 JPA 的 Criteria API（用 Java 代码拼查询）是同一种"拼查询"需求的两套解法：MyBatis 用 XML 标签树，JPA 用 Java 方法链。两者都比手写字符串拼接安全，但 MyBatis 的好处是 SQL 长什么样你能在 XML 里一眼扫完。

</details>

---

## 18.6 ResultMap：字段名到属性名的映射

SQL 查出来的是 `ResultSet`，Java 要的是对象。这中间有一道"列名 → 属性名"的映射关。

**自动映射**：MyBatis 默认按"同名"映射。`user_id` 列想映射到 `userId` 属性，需要开 `mapUnderscoreToCamelCase=true`（下划线转驼峰）。这是最常见的配置，你第 17 章配 MyBatis 时一定会在 `application.yml` 里看到它。

**显式映射**：当列名和属性名对不上、或要映射关联对象（一对一、一对多），就得写 `resultMap`：

```xml
<resultMap id="orderMap" type="com.example.entity.Order">
    <id column="id" property="id"/>              <!-- 主键 -->
    <result column="user_id" property="userId"/> <!-- 列名→属性名 显式指定 -->
    <result column="amount" property="amount"/>
    <result column="create_time" property="createTime"/>
</resultMap>

<select id="selectById" resultMap="orderMap">    <!-- 用 resultMap 而非 resultType -->
    SELECT id, user_id, amount, create_time FROM orders WHERE id = #{id}
</select>
```

这和第 17 章 JPA 的 `@Column(name = "user_id")` 是一回事——都是"数据库列名"和"Java 字段名"之间的桥。区别在位置：JPA 把映射标在**实体类**上（`@Column`/`@JoinColumn`），MyBatis 把映射放在**XML 的 resultMap** 里，和 SQL 待在一起。

**问题 5**：自动映射和显式 `resultMap` 怎么选？

经验法则：单表、列名和属性名能靠驼峰规则对齐 → 用 `resultType` + 自动映射，零配置最爽。多表关联（`JOIN` 出对方表的字段）、列名故意起别名、要嵌套对象 → 必须 `resultMap`，否则 MyBatis 不知道 `u_name` 该塞进 `user.name` 还是 `userName`。

> 【思考】为什么 Go 的 `sqlx` 用 struct tag（`db:"user_id"`）做映射，而 MyBatis 偏要弄一个独立的 `resultMap` 写在 XML 里？是啰嗦还是高明？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：两者解决同一个问题（列名→字段名），但取舍不同。`sqlx` 把映射信息**绑死在结构体 tag 上**，读 Go 代码即知映射，改映射要改 Go 代码重编译；MyBatis 把映射**抽到 XML**，和 SQL 同处一地，改映射不用动 Java 类，甚至 DBA 能直接改 XML 调 SQL——这是"SQL 与代码分离"哲学的延伸。啰嗦是啰嗦，但换来了"Java 实体类保持纯净、SQL/映射集中治理"。

**代码锚点——并排看两种映射声明**：

```go
// Go sqlx:映射在 struct tag,编译器可见,改映射=改代码
type Order struct {
    ID         int64  `db:"id"`
    UserID     int64  `db:"user_id"`
    Amount     int64  `db:"amount"`
    CreateTime int64  `db:"create_time"`
}
// db.Select(&orders, "SELECT id,user_id,amount,create_time FROM orders")
```

```xml
<!-- MyBatis:映射在 resultMap,和 SQL 同文件,改映射不用碰 Java 类 -->
<resultMap id="orderMap" type="com.example.entity.Order">
    <result column="user_id" property="userId"/>
    <result column="create_time" property="createTime"/>
</resultMap>
```

Go 的优势：映射就在结构体上，IDE 跳转、编译期校验，没有"XML 里写错列名查不出来"的风险。MyBatis 的优势：实体类就是普通 POJO，没有 `db` tag 入侵；DBA 或后端能在 XML 里统一调 SQL 和映射，不动 Java 代码——这对"SQL 由专人优化"的团队很友好。

**更深一层**：这是两种工程文化的缩影。Go 信"代码即真相、编译期兜底"；MyBatis/Java 信"配置与代码分离、运行时灵活"。你作为 Go 老哥会本能觉得 `resultMap` 啰嗦且易错（XML 里的 `property` 拼错只有运行时才知道），这直觉对——但也要理解它背后的"SQL 集中治理"诉求。折中方案：能用 `resultType`+驼峰自动映射就别写 `resultMap`，把显式 `resultMap` 留给真正需要关联映射的少数场景，既享受自动映射的简洁，又保留 `resultMap` 的掌控力。

</details>

---

## 18.7 一级缓存与二级缓存：省了查询，也埋了雷

MyBatis 自带两级缓存，但和"用 Redis 挡数据库"不是一回事——它是** JVM 进程内的本地缓存**。

**一级缓存**：作用在 `SqlSession` 级别。同一个 `SqlSession` 内，相同查询（同 SQL、同参数）第二次会直接返回第一次的结果，不发 SQL。默认开启，关不掉（严格说是 `localCacheScope`，默认 `SESSION`）。但 `SqlSession` 一般极短命——Spring 整合下，一次 Mapper 调用往往就是一个 `SqlSession`，方法结束就关。所以一级缓存的实际命中率很低，你基本感知不到它，但它确实是"同 Session 内重复查不命中数据库"的来源（排查"我改了库，同方法里却读不到新值"时要想到它）。

**二级缓存**：作用在 `namespace`（也就是 Mapper 接口）级别，跨 `SqlSession`——同一个 Mapper 的查询，不同会话、不同请求都能命中。默认**关闭**，要在 XML 里显式 `<cache/>` 开启。

```xml
<mapper namespace="com.example.mapper.OrderMapper">
    <cache/>                    <!-- 开启本 Mapper 的二级缓存 -->
    <select id="selectById" resultType="Order" useCache="true">
        SELECT ... FROM orders WHERE id = #{id}
    </select>
</mapper>
```

### 真实案例 ③：二级缓存导致关联表更新后读到旧值（脏读）

`OrderMapper` 和 `UserMapper` 都开了二级缓存。流程：

1. 请求 A 查 `orderMapper.selectById(1)` → 缓存 `Order(1)`。
2. 请求 B 更新了 `user` 表（通过 `UserMapper.update`），`UserMapper` 的二级缓存按**自己的 namespace** 失效了 `User` 相关数据。
3. 请求 C 再查 `orderMapper.selectById(1)`，它查的 `Order` 里嵌了 `userName` 字段（来自 `JOIN user`）。`OrderMapper` 的二级缓存里 `Order(1)` 还在，直接返回旧 `userName`——而 `user` 表早改了。

**触发条件**：多个 Mapper 的查询涉及同一批底层表，且各自维护独立二级缓存。**现象**：A 表更新后，通过 B Mapper 查出来还是旧值，时隐时现（取决于谁先过期）。**根因**：二级缓存的失效**只清自己 namespace**，不感知"别的 namespace 也用了同一张表"。**修复**：

- 最干脆：**关掉二级缓存**（删 `<cache/>`，或 `useCache="false"`）。MyBatis 二级缓存默认关不是没原因的。
- 用 `<cache-ref namespace="...">` 把多个 Mapper 的缓存绑成一个 namespace，让它们一起失效——但耦合变重。
- 正经方案：需要跨表一致的热点数据，交给**集中式 Redis**（第 19 章），别用 JVM 本地二级缓存。

> 【思考】二级缓存和 Redis 都是"挡在数据库前面的缓存"，为什么分布式部署下 MyBatis 二级缓存几乎不可用，而 Redis 可以？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：因为 MyBatis 二级缓存是**每个 JVM 实例各自内存里的一份 Map**——你部署了 3 个服务节点，就有 3 份互不感知的缓存。节点 1 更新了数据、清了节点 1 的二级缓存，节点 2、3 的缓存纹丝不动，照样返回旧值。Redis 是独立的集中式服务，所有节点共享同一份缓存，谁更新谁删除，大家看到一致。所以"本地二级缓存"只适合单机/只读字典表，分布式下它是脏数据制造机。

**展开**：二级缓存的失效粒度是 `namespace`，且只在"当前 JVM"内有效。它设计于单机时代（一个 Tomcat 进程），那时候一份 JVM 内存 = 全应用视角，失效没问题。微服务 + 多实例部署后，这个前提崩了。更要命的是案例 ③ 那种"跨 namespace 不联动"——即使单机，只要两个 Mapper 碰同一张表，脏读就可能在单进程内发生。

**Go 对照**：`gorm` **没有内置二级缓存**——你查就是查库，要缓存自己接 Redis（`redis-go`/`go-redis`）。这反而是"少一个坑"：Go 老哥从一开始就知道"缓存是 Redis 的事，ORM 不掺和"，不会掉进"ORM 自带缓存但集群下不一致"的陷阱。MyBatis 给了你二级缓存这个选项，很多人初学图省事开了，上线多实例后才被脏数据教做人。

**更深一层**：二级缓存的教训和本书一以贯之的提醒同源——**凡是"自动替你省事"的能力，都要想清楚它在什么边界下失效**。JPA 的 N+1、Spring 的 `@Transactional` 自调用失效、MyBatis 的二级缓存脏读，全是"框架默认行为在分布式/复杂场景下不成立的"实例。框架给你的"免费午餐"，在规模上来后会变成"隐性账单"。所以二级缓存的实用建议就一句：**除非你确认是单机 + 只读 + 不跨表，否则别开；要缓存，上 Redis**。

</details>

**问题 6**：那 Hibernate（JPA 的底层实现）也有二级缓存，它和 MyBatis 二级缓存是一回事吗？

机制类似——都是 namespace/Region 级的进程内缓存，都有"更新只清自己 Region"的脏读隐患，也都只在单机有效。区别是 Hibernate 二级缓存生态更成熟（有 Ehcache、Infinispan 等集中式后端可插），MyBatis 的 `<cache>` 默认就是个 `PerpetualCache`（HashMap）。所以两者在分布式下的结论一致：**本地二级缓存不可信，热点缓存交给 Redis**。

---

## 18.8 Go ↔ Java 持久层对照表

把这一章的骨架和你的 Go 经验对齐，这张表建议截图贴显示器上。

| 维度 | Go | Java (MyBatis) |
|---|---|---|
| SQL 写在哪 | 代码里（`db.Raw`/`sqlx`）或 `go:generate` 生成 | Mapper 接口（注解）或 `XxxMapper.xml`（namespace+id 绑定） |
| 参数绑定 | `?` 占位符 / `:name` 命名参数（`sqlx.Named`） | `#{}` 占位符（预编译）/`${}` 字符串拼接（危险） |
| 结果映射 | struct `db` tag + `StructScan` | `resultType` 自动映射 / `resultMap` 显式映射（对照 `@Column`） |
| 动态 SQL | 代码拼 `strings.Builder` / `sq` 构造器 / `gorm` 链式 | `<if>`/`<choose>`/`<foreach>`/`<where>`/`<set>` 标签树 |
| "接口即 SQL" | 无此形态，SQL 在调用点 | Mapper 接口 + JDK 动态代理（`MapperProxy`） |
| 缓存 | 无内置二级缓存，`gorm` 直查库 | 一级（SqlSession，默认开）/ 二级（namespace，默认关，本地内存） |
| 典型组合 | `sqlx` 或 `gorm` + Redis | MyBatis + Redis；或 JPA 管 CRUD、MyBatis 管复杂 SQL |

并排看一段"按条件查 + 扫对象"，体会两者的 DNA 差异：

```go
// Go (sqlx)：SQL 在代码里,命名参数 :status,StructScan 按 db tag 扫
rows, _ := db.Named(
    "SELECT id, user_id, amount FROM orders WHERE status = :status AND amount > :min",
    map[string]any{"status": "PAID", "min": 100})
var orders []Order
sqlx.StructScan(rows, &orders)   // db tag 决定列→字段
```

```java
// Java (MyBatis)：SQL 在 XML, #{} 占位符,返回类型标注即自动扫
// OrderMapper.xml:
// <select id="search" resultType="Order">
//   SELECT id, user_id, amount FROM orders
//   <where>
//     <if test="status != null">AND status = #{status}</if>
//     <if test="min != null">AND amount &gt; #{min}</if>
//   </where>
// </select>
List<Order> orders = orderMapper.search(status, min);   // 调用即拿 List<Order>
```

Go 那侧 SQL 和扫描都在你眼前、可单步；MyBatis 那侧 SQL 藏在 XML、调用点干干净净。这是"显式可追踪"和"声明式整洁"的老分歧，你从 Go 过来要两只手都要——享受 MyBatis 的整洁，但永远记得去 XML 里看它到底发了什么 SQL。

---

## 18.9 本章核心结论

如果这一章你只看这一段：

1. **MyBatis 不是 ORM，是 SQL 映射框架**——它把 SQL 交还给你，只替你干"填参数"和"扫结果"的苦力活，这是它相对 JPA 的核心价值。
2. **Mapper 接口靠 JDK 动态代理生效**（`MapperProxy` 实现 `InvocationHandler`），所以 Mapper 必须是接口，且 `namespace + id` 必须和"接口全限定名 + 方法名"对齐——绑错就 `Invalid bound statement`。
3. **`#{}` 是占位符（预编译、防注入），`${}` 是字符串拼接（危险）**；见到 `${}` 先问"这玩意儿用户摸得到吗"，摸得到就是 SQL 注入漏洞。
4. **动态 SQL 用 `<where>`/`<set>` 兜掉多余的 AND/逗号**，别手写在 `<if>` 外统一拼 `AND`，那会在条件缺失时炸语法。
5. **字段映射有自动（驼峰）和显式（`resultMap`）两条路**，单表用自动，关联/别名用 `resultMap`；它等价于 JPA 的 `@Column`，只是位置在 XML。
6. **一级缓存（SqlSession 级）默认开但短命，二级缓存（namespace 级）默认关且是 JVM 本地内存**——分布式下二级缓存是脏数据制造机，热点缓存请交给 Redis。
7. **MyBatis 的"接口即 SQL"是 Java 独有形态**，Go 没有这套，SQL 要么在代码里要么靠 `sqlx`/`gorm`；理解映射层差异，你才不会用 Go 的直觉误判 Java 项目。

---

## 18.10 深度思考题

### 题 1：你说 Mapper 是 JDK 动态代理。那如果我在 Mapper 接口里写了一个 `default` 方法（Java 8+），MyBatis 会怎么处理？

> 【思考】`default` 方法没有对应 SQL，MyBatis 的 `MapperProxy` 遇到它会走哪条路？能用来干什么、不能用来干什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：`default` 方法会被代理直接调用接口里的默认实现，MyBatis 不会、也没法为它找 SQL——因为它没有对应的 `MappedStatement`。所以 `default` 方法里你要么调本接口其他 Mapper 方法（会正常走代理查 SQL），要么写纯 Java 逻辑；它适合做"调多个 Mapper 方法做结果组合"的便捷封装，不适合写 SQL。

**展开**：`MapperProxy.invoke` 的逻辑是：如果方法是 `default` 方法（且 MyBatis 版本支持，需要 JDK 8+ 且 MyBatis 3.4+ 用 `MethodHandle` 调默认实现），就直接执行接口的 `default` 实现体，不走 SQL 查找。否则才按 `namespace + id` 去查 `MappedStatement`。

```java
@Mapper
public interface UserMapper {
    @Select("SELECT name FROM user WHERE id = #{id}")
    String nameById(Long id);

    default String greet(Long id) {            // default 方法:不走 SQL,直接跑这段 Java
        return "hello, " + nameById(id);        // 内部再调 Mapper 方法 → 正常走代理查 SQL
    }
}
```

**更深一层**：`default` 方法在 Mapper 里是把双刃剑。它让你能在"接口层"做轻量组合（比如拼两个查询的结果），不用上升到 Service 层；但滥用会让 SQL 调用链分散在接口里，可追踪性下降。本书一贯立场：Mapper 保持"纯 SQL 契约"，组合逻辑放 Service。偶尔用 `default` 做无害的便捷封装可以，但别把业务塞进去——那又回到"JPA 的 `@Entity` 里塞业务逻辑"的老坑了。

</details>

### 题 2：一个方法同时标了 `@Transactional`（第 17 章的声明式事务）和 `@Select`，事务和 SQL 执行是怎么协作的？会不会事务没开？

> 【思考】Mapper 自己的 JDK 代理和 Spring 的 `@Transactional` AOP 代理是两层，它们叠加时谁在外、SQL 跑在哪条连接上、事务凭什么生效？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：不会冲突，但要想清两层代理的嵌套。MyBatis 的 Mapper 是 JDK 代理（负责找 SQL），Spring 的 `@Transactional` 是另一层 AOP 代理（负责开事务），两层可以叠加。关键在：事务代理在外、Mapper 代理在内（或反之取决于注册顺序），调用 Mapper 方法时，事务拦截器先开连接并绑定到当前线程（`DataSourceUtils` 把连接放进 `ThreadLocal`），MyBatis 执行 SQL 时从同一个 `ThreadLocal` 取到这条连接——于是 SQL 跑在事务连接上。所以事务正常生效。

**展开**：协作的核心是 Spring 的 `DataSourceUtils` 和 `SqlSession` 的"绑定到线程"。`@Transactional` 开启时，Spring 从 `DataSource` 拿连接、关自动提交、存进 `TransactionSynchronizationManager` 的 `ThreadLocal`。MyBatis-Spring 的 `SqlSession` 执行时，通过 `DataSourceUtils.getConnection(dataSource)` 取连接——它发现线程里已有事务连接，就复用，而不是从池里另拿一条。于是"开事务"和"跑 SQL"用的是同一条连接，提交/回滚对这条 SQL 有效。

```java
@Service
public class OrderService {
    private final OrderMapper orderMapper;
    public OrderService(OrderMapper m) { this.orderMapper = m; }

    @Transactional                                    // 外层 AOP 代理:开事务连接绑线程
    public void createAndLog(Order o) {
        orderMapper.insert(o);                        // 内层 Mapper 代理:从线程取到同一连接
        orderMapper.insertLog(...);                   // 同连接,同事务,任一异常整体回滚
    }
}
```

**更深一层**：这题把第 14 章（AOP 代理）、第 17 章（事务/DataSource）和第 18 章（Mapper 代理）拧到了一起。你看到的"加个 `@Transactional` 就好"背后，是 Spring 用 `ThreadLocal` 把连接在代理之间透传的精密协作。作为 Go 老哥，你习惯显式传 `tx`（`doPay(tx, id)`），Spring 用 `ThreadLocal` 隐式传——代价是"连接从哪来"不透明，收益是业务代码零 `tx` 参数。两层代理叠加时只要记得：事务代理负责"绑连接"，Mapper 代理负责"用连接"，各司其职，不会互相踩。

</details>

### 题 3：MyBatis 的 `#{}` 真的百分百防注入吗？有没有它防不住、必须用别的手段的场景？

> 【思考】`#{}` 走预编译占位符，那是不是只要用 `#{}` 就永远安全？哪些场景它无能为力、逼你只能用 `${}`，又该怎么防？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：`#{}` 对"值"百分百防注入（它走预编译占位符，值不可能被解释成 SQL 结构）。但它防不住"标识符/结构"——表名、列名、排序方向这类不能用占位符的地方本就只能用 `${}`，而 `${}` 是拼接。所以"防不住"的从来不是 `#{}`，是"你不得不用 `${}` 的场景"。应对手段只有一条：对这些动态结构做**白名单枚举**，绝不让用户输入直接进 `${}`。

**展开**：`#{}` 的防护边界是"只能替值"。下面这些都**不能**用 `#{}`，必须用 `${}` 且必须白名单：

- 表名分片：`FROM ${tableName}`（按 userId 取模分 256 张表）。攻击点：用户若能影响 `tableName`，就能注入。
- 动态排序：`ORDER BY ${column} ${dir}`。攻击点同上。
- `IN` 的列表元素**可以**用 `#{}`（`<foreach>` 里每个 `#{id}` 都是占位符，安全），但 `IN` 本身的结构不用拼。

所以"防注入"的真正纪律是：**凡值，一律 `#{}`；凡结构，白名单 + `${{}`**。常见误用是"为了省事把整个 `WHERE` 子句用 `${}` 拼"——那是自杀。

```java
// ❌ 自杀式:整段条件用 ${} 拼用户输入
@Select("SELECT * FROM orders ${whereClause}")      // 攻击者传 "1=1; DROP TABLE orders"
List<Order> bad(@Param("whereClause") String whereClause);

// ✅ 正确:条件是固定 SQL + #{} 占位符,动态部分用 <if> 决定拼不拼
@Select("<script>SELECT * FROM orders <where>
    <if test='userId!=null'>AND user_id=#{userId}</if></where></script>")
List<Order> good(@Param("userId") Long userId);
```

**更深一层**：`#{}` 防注入的本质是"预编译语句（PreparedStatement）把代码和数据分离"这一数据库层纪律，MyBatis 只是把它做成了语法糖。你写 Go 用 `db.Query("... ?", val)` 时早就信这条纪律了——MyBatis 只是多了个 `${}` 后门，诱你犯错。所以结论不变：**值用占位符是铁律，任何语言任何框架都一样**；MyBatis 增加的风险只是"它给了你 `${}` 这个诱人的快捷键"。

</details>

### 题 4：如果让你用 Go 复刻一个"迷你 MyBatis"（接口即 SQL + 结果自动映射），你怎么设计？难点在哪？

> 【思考】Go 没有 JDK 动态代理这种"给空接口生成实现"的能力，那 Go 世界的"接口即 SQL"靠什么实现？难点卡在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案**：Go 没有 JDK 动态代理那种"给接口生成实现"的机制，所以你没法像 MyBatis 那样"只写接口"。Go 的等价物通常是**代码生成**（`go:generate` + `text/template`）或**反射 + 方法名约定**：启动时扫描结构体/接口，按命名规则生成 SQL，用 `reflect.StructTag` 做列映射。难点有三：① Go 没有"接口方法 → SQL 字符串"的注册机制（接口方法体为空，运行时拿不到"想查什么"的意图，除非另写元数据）；② 动态 SQL 在 Go 里只能是代码拼或模板，没有 XML 标签树；③ 结果映射靠 `reflect` 逐字段赋值，性能与可追踪性都要权衡。

**代码锚点——Go 里最现实的"迷你 MyBatis"是 sqlx + 命名查询**：

```go
// 不是"接口即 SQL",而是"函数即 SQL",但达到了同款体验:写 SQL + 自动扫对象
func FindOrders(db *sqlx.DB, status string, min int64) ([]Order, error) {
    // Named 把结构体/map 的字段按 :name 填进占位符
    q := `SELECT id, user_id, amount FROM orders
          WHERE status = :status AND amount > :min`
    rows, err := db.NamedQuery(q, map[string]any{"status": status, "min": min})
    if err != nil {
        return nil, err
    }
    var orders []Order
    for rows.Next() {
        var o Order
        rows.StructScan(&o)        // 按 db tag 自动映射,等价于 resultMap
        orders = append(orders, o)
    }
    return orders, nil
}
```

你得到的是"手写 SQL + 自动扫对象"，但**没有** Mapper 接口那层抽象——因为 Go 没法让一个空接口方法"凭空去查库"。要更近一步（接口即 SQL），只能 `go:generate` 在编译前扫描你的"带 tag 的接口/结构体"，生成上面这种 `FindOrders` 函数。这正是 `sqlc`、`ent` 这类 Go 工具在做的：`sqlc` 读 SQL 文件生成类型安全的 Go 函数，`ent` 用代码生成做图式化查询。所以 Go 世界的"MyBatis"是**代码生成**，不是运行时代理——这又回到了全书基调：**Go 把魔法推到编译期（生成代码），Java 把魔法留在运行期（代理）**。

**更深一层**：这题其实是让你反向理解 MyBatis 为什么"必须是 Java 形态"。JDK 动态代理是 JVM 的运行时能力，Go 没有，所以 Go 选了代码生成路线。两条路殊途同归——都想要"手写 SQL 的掌控 + 自动映射的省事"，只是"接口到 SQL 的绑定"一个在运行时（代理）、一个在编译期（生成）。你从 Go 过来若想造类似工具，别想着复刻 Mapper 代理，直接上 `go:generate`，那才是 Go 的地盘。

</details>

---

## 下一章预告

第 19 章讲 **Redis：缓存、Java 客户端与三大坑**。这一章你反复被提醒"热点数据交给 Redis"——MyBatis 查出来的、JPA 查出来的，最终都要考虑用 Redis 挡在数据库前面。第 19 章会把这件事讲透：`Jedis` 与 `Lettuce` 两个 Java 客户端怎么选（Lettuce 基于 Netty、天然支持异步与连接共享，对应你 Go 里 `go-redis` 的非阻塞模型）、Java 对象怎么序列化进 Redis（JDK 原生序列化、`Jackson` JSON、`Kryo` 的取舍）、以及缓存三大经典坑——**穿透**（查不存在的 key）、**击穿**（热点 key 过期瞬间大量请求打库）、**雪崩**（大量 key 同时失效）。每一坑都会和你在第 18 章埋下的"二级缓存脏读"对照：本地缓存和集中式缓存在一致性与可用性上的根本分歧。

读完第 18 章的"SQL 在你手里"，第 19 章会告诉你：手握 SQL 之后，怎么让这些 SQL 少打几次数据库。
