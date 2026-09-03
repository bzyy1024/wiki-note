# 第 19 章　Redis：缓存、客户端与一致性（从 Jedis 到缓存三大坑）

> 大促前一晚，你的订单详情接口 RT 突然从 5ms 飙到 800ms，DB 的 CPU 打到 99%，可 QPS 没涨多少。你 `kubectl logs` 翻了一通，发现打到 MySQL 的全是 `SELECT ... WHERE id = ?`,而那些 id 明明"应该"在 Redis 里。
> 你打开 Redis 监控，连接数只有 1,吞吐量也没满。问题不在 Redis 慢,而在"请求根本没走 Redis,全漏到 DB 了"。这一章就回答:Redis 为什么能挡在 DB 前面、你该用哪个 Java 客户端、Spring 帮你封装了什么又藏了什么坑,以及缓存一旦没管好会炸出哪三种事故。

---

## 19.1 为什么要把 Redis 挡在 DB 前面

先别急着记"加缓存"。你先想一个根本问题:一个请求打到 MySQL,和它的数据到底差了什么?

差的是**存储介质和访问路径**。MySQL 的数据落在磁盘(哪怕有 Buffer Pool,最终还是要过页、过索引 B+ 树、过事务和锁),一次点查要走索引定位、加行锁、走 MVCC 读视图,网络往返之外还有一堆 CPU 开销。而 Redis 的数据主要在内存,命令执行是**单线程串行**的:所有命令进一个队列,一个接一个跑,没有锁竞争、没有上下文切换。内存随机访问是纳秒级,磁盘是毫秒级——这就是差三四个数量级的来源。

所以"用 Redis 挡 DB"的本质,是把高频、读多写少、对一致性要求没那么苛刻的查询,从"慢路径"挪到"快路径"。单线程串行还有个附带好处:你不用像在 MySQL 那样担心并发读写的数据竞争,Redis 自己把命令原子化了。代价呢?单线程意味着**一个慢命令会阻塞后面所有命令**——这点在 19.5 讲大 key 时会咬你。

那缓存怎么和组织代码配合?业界最常用的是 **Cache-Aside(旁路缓存)**,因为它最简单也最贴合"缓存是 DB 的副本"这个事实:

```java
// 读路径:先查缓存,没命中再查 DB,并把结果回填缓存
public User getUser(Long id) {
    String key = "user:" + id;
    User u = (User) redisTemplate.opsForValue().get(key);
    if (u != null) return u;                 // 命中,直接返回,DB 完全不感知
    u = userMapper.selectById(id);           // 未命中,回源 DB(呼应 18 章 MyBatis)
    if (u != null) {
        redisTemplate.opsForValue().set(key, u, Duration.ofMinutes(30)); // 回填,带 TTL
    }
    return u;
}

// 写路径:先改 DB,再删缓存(为什么"删"不是"更",19.6 细说)
@Transactional
public void updateUser(User user) {
    userMapper.updateById(user);                 // 1. 先更 DB,保证 DB 是真相源
    redisTemplate.delete("user:" + user.getId()); // 2. 再删缓存,下次读自然回填新值
}
```

**问题 1:** 为什么写路径是"删缓存"而不是直接"把新值写进缓存"?

因为直接写缓存会引入一个时序地狱:两个并发写 A、B,A 先写 DB 后写缓存,B 后写 DB 后写缓存,但如果 B 的"写缓存"先执行、A 的后执行,缓存里就停在了 A 的旧值。删缓存让下一次读去回填,把"时序问题"推迟成一个"短暂的回源",简单且安全。后面 19.6 你会看到这也不是银弹。

> 【思考】Cache-Aside 的"读时回填"有个隐含前提:缓存里的数据和 DB 在某刻必须能对上。如果回填之前的窗口里 DB 又被改了,会发生什么?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:会发生一个短暂的不一致窗口——缓存里是旧值,DB 已是新值,直到 TTL 过期或下次写路径把它删掉。Cache-Aside 从来不保证强一致,它只保证"最终一致":只要 TTL 设得够短,或写路径正常删缓存,旧值最多存活一个窗口期。

**为什么这是必然的**:读路径是 `查缓存未命中 → 查 DB → 回填`,这三步之间没有任何锁把"并发写"挡在外面。设想线程 1 读未命中、去查 DB(拿到旧值 v1),此时线程 2 把 DB 改成 v2 并删了缓存,线程 1 才把 v1 回填进缓存——于是缓存里是 v1、DB 是 v2,不一致。这个窗口在"读多写少"时很短,但在"刚写完好被读"的热点数据上最常撞见。

**Go 对照**:这个窗口跟语言无关。你在 Go 里用 `go-redis` 写同样的 Cache-Aside,只要"读回填"和"写删缓存"是两个独立操作,窗口一模一样存在。Go 生态常用 `singleflight` 把"并发未命中"合并成一次 DB 查询来缩小窗口(19.7 讲),但合并不了"读回填 vs 写更新"的交叉。

**更深一层**:缓存系统在设计哲学上就把"性能"和"强一致"摆成了天平两端。你要纳秒级内存读取,就得接受"副本可能滞后"。强一致只能靠"读写都过同一把锁 / 同一存储"来换,而那等于放弃了缓存。所以看到"缓存和 DB 不一致"的工单,第一反应不该是"我的代码有 bug",而是"我的业务到底能不能容忍这个窗口"——能容忍,就靠 TTL 兜底;不能容忍(如余额),那条数据压根不该进缓存。

</details>

---

## 19.2 客户端选型:Jedis 与 Lettuce,以及 shareNativeConnection 那个坑

你用 Redis,得有个 TCP 客户端把命令发出去。Java 生态里真正活到今天的就两个:**Jedis** 和 **Lettuce**。Spring Boot 1.x 默认 Jedis,**Spring Boot 2.x 起默认切到了 Lettuce**。为什么?

先看清两者底子上的差异:

| 维度 | Jedis | Lettuce |
|---|---|---|
| 底层 IO 模型 | 阻塞 IO(BIO),一个连接一个线程占用 | 基于 Netty,事件驱动,异步非阻塞 |
| 线程安全 | **否**。一个 `Jedis` 实例不能多线程共用,必须池化 | **是**。`StatefulRedisConnection` 可多线程共享 |
| 连接管理 | 必须配 `JedisPool`,每次从池取、用完还 | 默认共享一条"原生连接",天然少连接 |
| 编程模型 | 同步阻塞 | 同步 / 异步(`RedisFuture`)/ 响应式(Reactive Redis) |
| 与 Spring 契合 | 靠社区维护的胶水 | Spring Data Redis 官方首选,自动装配开箱即用 |

Jedis 的"线程不安全"是你从 Go 转过来最别扭的点。在 Go 里你 `redis.NewClient` 拿到一个 client,全局 `*redis.Client` 到处传、goroutine 随便调,因为底层连接池和协程调度是 client 内部管的。Jedis 不是——你若把一个 `Jedis` 实例当单例给多线程用,命令会串台、响应会错位。所以 Jedis 必须这样用:

```java
// Jedis:每个线程从池里拿独立连接,用完必须归还
JedisPool pool = new JedisPool(new JedisPoolConfig(), "localhost", 6379);
try (Jedis jedis = pool.getResource()) {   // 从池取,AutoCloseable 自动还
    jedis.set("k", "v");                    // 这条连接在调用期间只属于当前线程
}
```

Lettuce 则松快得多:一个 `StatefulRedisConnection` 能在线程间共享,Netty 的 pipeline 把并发命令多路复用在同一物理连接上。

**问题 2:** 既然 Lettuce 线程安全、还能共享连接,那它默认"一条连接服务所有请求"岂不是又省连接又高效?为什么大促时反而会出事?

这就到了本章第一个真实事故。

**真实案例 ③:大促时 Lettuce 默认共享连接没配池,单连接成了瓶颈**

现象:某次大促,Redis 实例 CPU 和带宽都没满,但应用侧 RT 随流量线性恶化,从 3ms 涨到 200ms+。监控里 Redis 的连接数恒为 1(没错,就一条)。

排查过程:看 Spring Boot 自动装配,默认 `spring-boot-starter-data-redis` 用的是 Lettuce,且 `LettuceClientConfiguration` 里 `shareNativeConnection` 默认 **true**——所有同步命令复用同一条物理连接。Lettuce 虽基于 Netty 异步,但当你用**同步 API(`redisTemplate.opsForValue().get()`)**时,每个调用都要等这条连接的响应回来才能发下一个;高并发下这条连接变成串行化瓶颈,命令在客户端排队。

根因:`shareNativeConnection=true` 省连接,但同步阻塞调用下,单连接的吞吐上限卡死了整体 QPS。这跟 17 章你学的 HikariCP 一个道理——数据库连接要池化来突破单连接吞吐,Redis 连接同理,高并发下也得池化。

修复:关掉共享连接,并引入 `commons-pool2` 的连接池:

```java
// 方式一:代码里关掉共享连接(shareNativeConnection=false 是核心)
@Bean
public LettuceClientConfigurationBuilderCustomizer lettuceCustomizer() {
    return builder -> builder.shareNativeConnection(false); // 别复用单条物理连接
}
```

```properties
# 方式二(更常用):直接开 Lettuce 的连接池,让 Spring Boot 自动配
# Spring Boot 2.5+ 用 spring.data.redis 前缀;更早的 2.x 是 spring.redis.lettuce.pool
spring.data.redis.lettuce.pool.enabled=true
spring.data.redis.lettuce.pool.max-active=16   # 池里最多 16 条连接,突破单连接瓶颈
spring.data.redis.lettuce.pool.max-idle=16
spring.data.redis.lettuce.pool.min-idle=4
```

配完之后连接数随并发上去了,RT 回落。教训:** Lettuce 的"线程安全 + 共享连接"是默认省连接的好意,但在高并发同步调用下,你得显式池化,否则它替你做的"省连接"决定会反咬你一口**——这正是 15 章说的"约定优于配置的代价"。

> 【思考】Jedis 线程不安全所以要池化,Lettuce 线程安全却也要池化,这俩"池化"解决的问题是同一件事吗?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:不是同一件事。Jedis 池化解决的是"线程安全"(不池化就会数据串台、直接出错);Lettuce 池化解决的是"吞吐上限"(不池化不会错,但单连接在高并发同步调用下成为串行瓶颈,RT 飙升)。

**展开**:Jedis 的 `JedisPool` 是**正确性**要求——一个 `Jedis` 对象内部持有一条 socket 和读写缓冲,多线程同时写一个输出流必然乱码。所以 Jedis 不池化是 bug。Lettuce 的 `StatefulRedisConnection` 本身是线程安全的,多路复用没问题;它的池(`GenericObjectPool` 包着的连接)是为了在**同步阻塞**语义下,让多个线程不必排队等同一条连接的响应。如果你全程用 Lettuce 的**异步 API(`connection.async().get()`)**,Netty 把命令多路复用,单连接也能打很高吞吐,这时候池化收益就小了。

**Go 对照**:Go 的 `go-redis` client 内部自带连接池(`redis.Options.PoolSize`),你拿一个 `*redis.Client` 全局用,goroutine 并发调用时 client 自动从池里借连接——它把"池化"做成了 client 的内部默认,你几乎不用操心。Java 这边因为历史上有 Jedis(要你显式管池)和 Lettuce(默认不池化)两条路,所以"要不要池、怎么池"成了你要拍板的事。本质上 Go 帮你把 17 章 HikariCP 那套"连接池化"思维内建进了 client。

**更深一层**:池化的根本目的永远是"用连接数换并发度"。无论 Jedis 的"为了不出错"还是 Lettuce 的"为了不卡",底层都是同一个权衡:多开连接 → 多占文件描述符和 Redis 端资源 → 换更高并发。Redis 是单线程处理命令的,所以连接池突破的是"客户端到 Redis 的网络并发",不是"Redis 执行命令的并发"——命令在 Redis 端依旧串行。想真正水平扩展 Redis 的执行能力,得靠分片( cluster),那是另一个话题。

</details>

---

## 19.3 Spring Data Redis:RedisTemplate、StringRedisTemplate 与序列化之坑

Spring 把客户端封装成了 `RedisTemplate`,你不用直接碰 `Jedis`/`Lettuce` 的 API。但封装层有个最隐蔽的坑:**序列化器**。

`RedisTemplate` 默认的 key 和 value 序列化器是 `JdkSerializationRedisSerializer`。它干的事是 `ObjectOutputStream` 把对象打成二进制,前面还带 JVM 的类名信息。你存个 `User`,Redis 里看到的是 `\xac\xed\x00\x05t\x00...user.User` 这种鬼东西——人看不懂,别的语言(包括你未来的 Go 服务、Python 脚本)更读不了。

`StringRedisTemplate` 是 `RedisTemplate` 的特例:它把 key 和 value 都用 `StringRedisSerializer`,也就是 UTF-8 字符串。可读、可调试,但只能存 `String`,对象得你自己转 JSON。

**问题 3:** 生产上到底该用哪个?既然 `StringRedisTemplate` 可读,那我全用 `String` 不就完了?

不够。业务对象那么多,你每次手写 `objectMapper.writeValueAsString` 太啰嗦,而且 value 反序列化时还得记得转回具体类型。更稳的做法是:用 `RedisTemplate`,但把序列化器换成 JSON。

```java
@Bean
public RedisTemplate<String, Object> redisTemplate(RedisConnectionFactory factory) {
    RedisTemplate<String, Object> t = new RedisTemplate<>();
    t.setConnectionFactory(factory);
    t.setKeySerializer(new StringRedisSerializer());                      // key 用 String,可读好排查
    t.setValueSerializer(new GenericJackson2JsonRedisSerializer());       // value 用 JSON,带类型信息
    t.setHashKeySerializer(new StringRedisSerializer());
    t.setHashValueSerializer(new GenericJackson2JsonRedisSerializer());
    return t;
}
```

`GenericJackson2JsonRedisSerializer` 会在 JSON 里多写一个 `@class` 字段记录类型,反序列化时不用你显式传 `Class`,直接 `get()` 回来就是对象。代价是 JSON 体积稍大,且**要求类有默认构造器、字段可被 Jackson 访问**。

**真实案例(序列化器的隐藏雷):JDK 序列化"改个类名就反序列化失败"**

有人图省事用了默认 `RedisTemplate`(JDK 序列化),存了一批 `com.shop.order.dto.OrderDTO`。半年后做包重构,把类挪到 `com.shop.dto.OrderDTO`,类名路径变了。旧缓存还在 Redis 里,新代码 `get()` 回来,JVM 找不到 `com.shop.order.dto.OrderDTO`,直接抛 `ClassNotFoundException`——而 JDK 序列化把类名焊死在了字节流里,你没法改、没法兼容,只能手动清缓存或写迁移脚本。

**Go 对照**:Go 这边没有 Spring 那套 `RedisTemplate` 抽象,序列化完全你自己定。社区惯例是直接 `json.Marshal` / `json.Unmarshal`,类型信息靠你反序列化时传入 `&OrderDTO{}` 决定。好处是没有任何"框架偷偷塞类名"的魔法,坏处是每次都得记着传对类型。Go 的 `json` 标签(`json:"id"`)对应 Java Jackson 的 `@JsonProperty`;Go 没有"改 struct 名就反序列化失败"的问题,因为 JSON 里只存字段名不存类型路径——这也反过来说明:**把类型路径写进序列化字节流,是个双刃剑的设计**(Java 方便、Go 灵活)。

> 【思考】既然 JDK 序列化会把类名焊死在字节流里、还不可读,为什么 Spring 还要把它设成 RedisTemplate 的默认值?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:因为 `RedisTemplate` 在 Spring Data Redis 早期是为"把任意 Java 对象原样存取"设计的,默认就要能存任何 `Serializable` 对象,JDK 原生序列化是当时"零配置就能跑"的唯一选择。可读性和跨语言是后来微服务化才变成刚需的,默认值却因为兼容性被保留了下来。

**展开**:`JdkSerializationRedisSerializer` 不依赖任何第三方库(纯 JDK),所以 `RedisTemplate` 开箱即用、不需要你配 ObjectMapper。这在"缓存只给 Java 自己看、对象结构稳定"的年代没问题。但微服务时代,缓存常被多语言服务共享、类还在不停重构,默认值就露馅了:字节流不可读、类名耦合、版本升级即崩。Spring 没改默认值是怕破坏老项目,但**新项目你第一件事就该覆盖它**——换成 `StringRedisSerializer` + `GenericJackson2JsonRedisSerializer`(或自定义 `Jackson2JsonRedisSerializer` 指定具体类型,避免 `@class` 字段带来的反序列化安全隐患)。

**一个安全提醒**:`GenericJackson2JsonRedisSerializer` 因为写了 `@class`,反序列化时会按类名加载类,如果缓存内容来自不可信来源(如公网可写的 key),存在远程代码执行风险。对不可信数据,用不写 `@class` 的 `Jackson2JsonRedisSerializer` 并显式指定目标类型更稳。

**更深一层**:默认值反映的是框架设计时的"主流假设",而假设会过时。你在 15 章学到的"约定优于配置"在这里显形:Spring 替你选了"能跑"的默认,但当你的场景偏离它的假设(跨语言、常重构),默认值就从便利变成了债。所以接手任何 Spring 项目,第一件事应该是翻它的 `RedisTemplate`/`RestTemplate`/`ObjectMapper` 配置——这些"默认即坑"的地方,十有八九被前人留了雷。

</details>

---

## 19.4 缓存三大坑(一):穿透与击穿

缓存没管好,会炸出三种经典事故:**穿透、击穿、雪崩**。名字像,触发条件完全不同。先讲前两个,每个都配真实案例。

### 19.4.1 缓存穿透:查一个根本不存在的 key

触发条件:请求的参数在 DB 里也不存在(比如 `id = -1`、超大随机数、被遍历的用户 ID)。

现象:每次请求都"缓存未命中 → 查 DB 未命中",缓存层完全没挡住,全部流量穿透到 DB。攻击者拿这个刷接口,DB CPU 直接打满——因为缓存永远不会命中,也就永远不会回填任何能拦住后续请求的东西。

根因:缓存的语义是"DB 里有才存"。对"DB 里没有"的请求,缓存无从拦截,每次都放给 DB。

修复两条路,通常叠加用:

```java
// 修复一:缓存空值(短 TTL),让"不存在"也能被缓存拦住
public User getUserSafe(Long id) {
    String key = "user:" + id;
    Object cached = redisTemplate.opsForValue().get(key);
    if (cached != null) {
        return cached.equals("") ? null : (User) cached; // 命中空值,直接返回,不打 DB
    }
    User u = userMapper.selectById(id);
    if (u != null) {
        redisTemplate.opsForValue().set(key, u, Duration.ofMinutes(30));
    } else {
        redisTemplate.opsForValue().set(key, "", Duration.ofMinutes(2)); // 空值也存,但 TTL 短,防脏数据滞留
    }
    return u;
}
```

```bash
# 修复二:布隆过滤器,在进缓存/DB 之前先判断"这 id 可能存在吗"
# RedisBloom 模块提供 BF.* 命令
BF.RESERVE user_bf 0.01 1000000    # 误判率 1%,预计容纳 100 万个元素
BF.ADD user_bf 12345               # 把真实存在的 id 预加载进去
BF.EXISTS user_bf 99999            # 返回 0 => 一定不存在,直接拒绝,连缓存都不用查
                                  # 返回 1 => 可能存在(有误判),再走正常缓存+DB 流程
```

布隆过滤器的精髓:**它说"不存在"就绝对不存在(无假阴性),说"存在"可能误判**。所以它能 100% 拦掉穿透攻击里的非法 id,代价是误判时会多走一次 DB(可接受),以及过滤器本身要预加载真实 id 集合、要处理新增。

**真实案例 ①:攻击者刷不存在的用户 ID,DB CPU 打满**

现象:某开放接口 `GET /user/{id}` 半夜被脚本狂刷,id 是一堆 `-1`、`0`、超大随机数。DB CPU 99%,正常用户登录不了。

排查:看慢查询日志,全是 `SELECT ... WHERE id = ?` 且 `rows_examined` 很低(因为根本没这行),说明不是慢 SQL,是**请求量把连接打光了**。缓存命中率监控显示接近 0%——因为这些 id 永远不在缓存里。

修复:接口层加布隆过滤器(真实用户 id 预加载进 `user_bf`),过滤器说不存在的直接返回 400;同时对所有未命中的查询缓存空值(TTL 2 分钟)兜底。两道加起来,攻击流量在 Redis 层就被空值缓存吸收,DB 恢复平静。

### 19.4.2 缓存击穿:一个热点 key 过期瞬间,流量全涌向 DB

触发条件:**某个被高频访问的热点 key 在同一刻过期**(比如首页推荐列表 key 设了零点过期)。

现象:在过期前,这个 key 扛住了绝大部分流量;过期的那一瞬间,所有并发请求同时未命中,同时去查 DB 重建——DB 被一记重拳打挂。

根因:和穿透不同,击穿查的 key 是"真实存在且很热"的,只是恰好过期。问题出在**"未命中 → 重建"这一步被成千上万个并发同时触发**。

**真实案例 ②:首页推荐列表 key 零点过期,瞬时流量把 MySQL 打挂**

现象:零点流量高峰,首页推荐位 key `home:rec` 的 TTL 正好设在零点到期。到期刹那,几万 QPS 同时未命中,同时 `SELECT ... FROM recommend WHERE ...`,MySQL 连接池瞬间耗尽,首页 5xx。

修复:让"重建缓存"这件事**同一时刻只让一个人干**,其他人等结果。Java 里用 `SET NX` 抢一把互斥锁:

```java
public List<RecItem> getHomeRec() {
    String key = "home:rec";
    List<RecItem> list = (List<RecItem>) redisTemplate.opsForValue().get(key);
    if (list != null) return list;                 // 命中,直接返回
    String lock = "lock:" + key;
    // SET NX PX:只有抢到锁的线程去重建,其他人等着,避免几万请求同时打 DB
    Boolean locked = stringRedisTemplate.opsForValue()
            .setIfAbsent(lock, "1", Duration.ofSeconds(10)); // 10s 自动过期,防死锁
    if (Boolean.TRUE.equals(locked)) {
        try {
            list = recMapper.selectHotList();       // 只有一个线程真正查 DB
            redisTemplate.opsForValue().set(key, list, Duration.ofHours(1));
        } finally {
            stringRedisTemplate.delete(lock);        // 重建完释放锁
        }
    } else {
        try { Thread.sleep(50); } catch (InterruptedException ignored) {} // 没抢到,稍等
        return getHomeRec();                         // 重试,此时大概率已回填
    }
    return list;
}
```

另一种修复叫"逻辑过期":value 里带一个 `expire` 字段,过期后不删 key,只是让抢到锁的线程异步重建、其他线程先返回旧值。它比"互斥锁"体验好(不阻塞用户),但实现更复杂、且短期内会读旧值。选型看你能不能接受短暂旧数据。

> 【思考】互斥锁修复击穿,靠 `SET NX` 保证"只有一人重建"。那 Go 侧有没有等价的原语?是不是也得自己写 `SET NX`?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:Go 侧有两个层次的做法——你可以照 Java 一样用 `SET NX`(go-redis 的 `SetNX`),但 Go 生态更地道的是用标准库扩展 `golang.org/x/sync/singleflight`,它把"合并并发、只执行一次"做成了语言级原语,比手写锁更不容易出错。

**并排对比:Go 的 singleflight vs Java 的 SET NX 互斥锁**

Go 写法(推荐):

```go
var g singleflight.Group // 全局一个 Group,按 key 合并并发调用

func GetHomeRec() ([]RecItem, error) {
    key := "home:rec"
    if v, ok := cache.Get(key); ok {
        return v, nil
    }
    // 同一 key 的并发调用,只有第一个真正执行 fn,其余阻塞等待并共享它的结果
    v, _, _ := g.Do(key, func() (interface{}, error) {
        list, err := db.QueryHotList() // 只有一个 goroutine 打 DB
        cache.Set(key, list, time.Hour)
        return list, err
    })
    return v.([]RecItem), nil
}
```

Java 写法(SET NX 互斥锁,见上一段代码):

```java
Boolean locked = stringRedisTemplate.opsForValue()
        .setIfAbsent(lock, "1", Duration.ofSeconds(10)); // 抢锁
if (Boolean.TRUE.equals(locked)) { /* 重建 */ } else { Thread.sleep(50); return getHomeRec(); }
```

**差异**:`singleflight` 是**进程内**的合并,不依赖 Redis,延迟更低、也更简单(不用管锁过期、死锁);但它只合并"同一进程内的并发",多实例部署时每个实例各自合并一次,DB 仍可能被 N 个实例各打一次(N 不大时完全可接受)。`SET NX` 是**分布式**锁,跨实例只放一个请求进 DB,但你要自己处理锁超时、误删别人的锁(用 UUID 值校验)、容错。Go 也有人用 `go-redis` 的 `SetNX` 做分布式锁(`github.com/redis/go-redis/v9` 的 `redis.NewScript` 写 Lua 保证原子释放),但单纯防击穿,`singleflight` 是更轻的锤子。

**更深一层**:击穿的本质是"热点数据失效瞬间,重建成本被并发放大"。无论 Java 的锁还是 Go 的 singleflight,都是在"重建"这个动作上加互斥,把 N 次 DB 查询压成 1 次。真正根治的办法往往更简单——**热点 key 不设 TTL、改为后台定时刷新**(逻辑过期思路),让 key 永不过期、由任务线程主动更新。这跟"能不能接受短暂旧值"强相关。

</details>

---

## 19.5 缓存三大坑(二):雪崩,以及大 key / 热 key

### 19.5.1 缓存雪崩:大量 key 同时失效,或 Redis 自己挂了

触发条件有两种:
- **大量 key 同一时刻过期**:比如你批量预热缓存时,给成百上千个 key 设了相同的 TTL(常见写法 `set(k, v, 3600)`,结果零点一起到期)。
- **Redis 实例宕机**:主节点挂了、没切从,或 Redis 被打满 OOM,全量请求瞬间倾泻到 DB。

现象:DB 在短时间被巨量请求淹没,轻则 RT 飙升,重则连接池打光、级联雪崩把整个服务拖死。名字"雪崩"就是形容这种"一片一片塌下来"的连锁。

根因:缓存层在某一刻整体失守,DB 被迫承接远超设计容量的流量。

修复:
- **过期时间加随机抖动**:`TTL = 基准 + random(0, 300s)`,让 key 错峰过期,绝不同步失效。
- **多级缓存**:本地缓存(Caffeine/Guava) + Redis + DB,Redis 挂了还有本地兜一层(Go 侧对应 BigCache/freecache,19.7 讲)。
- **高可用**:Redis 用主从 + 哨兵,或 Redis Cluster,单节点挂了能切、能分片扛量。
- **限流降级**:DB 前加熔断(Resilience4j / Sentinel),缓存全失时拒绝部分请求保核心。

```java
// 错峰过期:在基准 TTL 上叠加随机抖动,避免集体到期
int base = 3600;
int jitter = new Random().nextInt(300); // 0~300 秒随机
redisTemplate.opsForValue().set(key, value, Duration.ofSeconds(base + jitter));
```

### 19.5.2 大 key 与热 key:单线程的阿喀琉斯之踵

Redis 是**单线程处理命令**的。这俩问题都直接利用(或者说攻击)了这个事实:

- **大 key**:一个 key 的 value 特别大(比如一个 `List` 塞了 50 万元素,或一个 `String` 几 MB)。读它、删它、过期它,都会占用 Redis 主线程很久,期间**所有其他命令都被卡住**(因为串行)。现象是 Redis 偶发卡顿、延迟毛刺,监控上 `latest_fork_usec` 或慢日志里出现这个 key。
- **热 key**:某个 key 被超高并发访问(比如顶流直播间商品详情),流量集中打在单个分片上,该分片 CPU 打满、其他分片闲着。单分片成为瓶颈。

修复第一步是**识别**。Redis 自带命令:

```bash
redis-cli --bigkeys            # 扫描全库,按类型统计每种最大的 key 及其元素数/字节数
redis-cli --bigkeys -i 0.1     # -i 控制扫描节流(每秒扫描库的比例),生产上务必加,别打满
redis-cli --hotkeys            # Redis 4.0+ 且开 maxmemory-policy 相关采样时,可查热 key
```

第二步是**拆分 / 打散**:
- 大 key 拆分:一个 50 万元素的 `List`,拆成 100 个 `List`,按 `hash(id) % 100` 分桶;或改用 Hash 结构逐 field 操作,避免一次 `LRANGE 0 -1` 拉全量。
- 热 key 打散:在 key 后拼随机后缀(如 `hot:123:0`~`hot:123:9`),读时随机选一个,把单 key 流量均摊到 10 份;或用本地多级缓存兜掉大部分读,让 Redis 只承接未命中。

**问题 4:** 大 key 卡住单线程,和 19.1 说的"单线程串行带来高性能"是不是矛盾?

不矛盾,是同一特性的两面:单线程让你免去了锁和竞争,所以常规小命令极快;但也意味着**任何一个慢命令都会阻塞整条命令流**。单线程是把"快"和"脆弱"焊在了一起——你享受了无锁的高吞吐,就得为"别让任何一条命令变慢"负责。这也是为什么大 key、慢 Lua、跨 slot 的多 key 事务在 Redis 里都是禁忌。

---

## 19.6 缓存与 DB 一致性:先删还是先更,以及 MQ 兜底

这一节是缓存的终极难题:缓存是 DB 的副本,副本就会滞后。你要"缓存和 DB 绝对一致"吗?

先说 Cache-Aside 的推荐顺序,也就是 19.1 写路径用的:**先更新 DB,再删缓存**。为什么不反过来(先删缓存再更新 DB)?

**问题 5:** 为什么"先删缓存、再更新 DB"更糟?

设想:线程 A 先删缓存,正要去更新 DB;此时线程 B 来读,缓存未命中,去 DB 读到**旧值**并回填缓存;然后 A 才把 DB 更新成新值。结果:缓存里是旧值、DB 是新值,且这个旧值在 TTL 内一直脏着。而"先更 DB 再删缓存",最坏情况是"删缓存之前的极短窗口里读到了旧缓存值",窗口远短于前者,且删缓存那一下能纠正。所以业界默认选后者。

但"先更 DB 再删缓存"仍有不一致窗口(19.1 的【思考】已分析)。增强版叫**延迟双删**:

```java
@Transactional
public void updateUserDoubleDelete(User user) throws InterruptedException {
    userMapper.updateById(user);                  // 1. 先更 DB
    redisTemplate.delete("user:" + user.getId()); // 2. 立刻删一次缓存
    Thread.sleep(500);                            // 3. 等并发读把"旧值"回填完
    redisTemplate.delete("user:" + user.getId()); // 4. 再删一次,清掉可能回填的旧值
}
```

延迟双删用"多删一次"把"读回填旧值"的脏数据再擦掉。但它靠 `sleep` 猜窗口,丑且不精确;且第 4 步删失败就又脏了。

那怎么根治?**强一致在"缓存 + 独立 DB"架构下基本不可能**——因为两者是两个存储,没有任何分布式事务能零成本地把"更新 DB"和"删缓存"绑成原子(二阶段提交成本极高且 Redis 不支持)。你能追求的只有**最终一致**。而最终一致的工程化兜底是:**把"删缓存"变成异步、可重试的事件**。

这就引出了下一章的主角——消息队列:

```java
@Transactional
public void updateUserWithMq(User user) {
    userMapper.updateById(user);                  // 1. 本地事务先落库(强一致在 DB 内保证)
    kafkaTemplate.send("cache-invalidate",        // 2. 发一条"请删缓存"的消息
            "user:" + user.getId());              //    解耦:缓存删除失败可重试、可削峰
}
```

用 MQ 的好处有三:① 删缓存失败能靠消费重试兜底,而不是"删一次就认命";② 把删除动作从写请求的关键路径里摘出来,写接口 RT 不受缓存影响;③ 大促时 DB 写猛、缓存删除可以靠 MQ 削峰,不会反向冲垮 Redis。代价是引入了一层最终一致窗口(消息没消费完前缓存是旧的)——但如前所述,缓存本就不该承诺强一致。

还有更彻底的路线:监听 DB 的 binlog(Canal / Debezium),由下游消费者统一删缓存。这样"写 DB"和"删缓存"彻底解耦,业务代码零侵入,且顺序由 binlog 保证。这条路线同样离不开 MQ。

> 【思考】既然"缓存 + DB"做不到强一致,那什么场景下的数据压根不该进缓存?判断标准是什么?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:判断标准是"这份数据能否容忍一个最终一致窗口、以及不一致时的业务代价多大"。能容忍且代价小(用户资料、商品详情、首页推荐)的进缓存;不能容忍(账户余额、库存扣减、支付状态)的要么不进缓存,要么只在读路径用缓存做"加速展示"、写路径和关键决策一律走 DB。

**展开**:余额这类数据,你敢在缓存里扣、DB 里没扣,或者反过来,就会出现"显示有钱实际没钱"的资损。所以这类数据缓存只用于"我查给你看",真正的扣减、校验必须落在 DB 事务里,且常常用 DB 的行锁 / 乐观锁保证。库存则是另一个经典坑:用缓存 `DECR` 扣库存若不同步落 DB,超卖就来了;正确做法是 DB 持真相、缓存只挡"查库存"的读,扣减走 DB 并删缓存。

**MQ 的角色**:当数据必须最终一致时,MQ 是"异步、可重试、保序"的纽带。第 20 章你会看到,Producer 发消息、Consumer 按 offset 顺序消费删缓存,正好补上这一章"延迟双删靠 sleep 猜窗口"的粗糙。把"写 DB"和"删缓存"用 MQ 串成"事务消息 + 可靠消费",才是生产级做法。

**更深一层**:一致性的强弱不是技术问题,是**业务 SLA**问题。架构师的工作不是"让缓存和 DB 强一致"(那等于不用缓存),而是"为每类数据选对的一致性级别并让代价可见"。你在 17 章学了事务隔离级别——同理,缓存一致性也是一张"性能 vs 正确"的谱,你得知道你的业务站在哪个点。

</details>

---

## 19.7 Go 程序员的 Redis 对照表

你写 Go 时大概率用过 `go-redis`,这一节把两边摆平,让你少踩"以为 Java 也这样"的坑。

**概念对照表(这一章的 Go ↔ Java 总览)**

| 概念 | Go | Java |
|---|---|---|
| 主流客户端 | `github.com/redis/go-redis/v9`(go-redis);老的 `github.com/gomodule/redigo/redis`(redigo) | `Lettuce`(Spring Boot 2.x 默认)、`Jedis`(老项目多见) |
| 连接池 | client 内建(`redis.Options.PoolSize`),全局 `*Client` 随便用 | Lettuce 默认共享单连接,高并发需配 commons-pool2;Jedis 必配 `JedisPool` |
| 序列化 | 自己 `json.Marshal` / `json.Unmarshal`,只存字段不存类型路径 | `RedisTemplate` 默认 JDK 序列化(带类名,坑);生产换 JSON 序列化器 |
| 防击穿 | `golang.org/x/sync/singleflight` 进程内合并;或 `SetNX` 分布式锁 | `SET NX` 互斥锁 / 逻辑过期;Redisson 提供 `RLock` |
| 本地多级缓存 | `BigCache`(bigcache)、`freecache`(freecache),应对热 key 和 Redis 宕机 | Caffeine / Guava Cache,作 Redis 前的本地层 |
| 缓存模式 | Cache-Aside 同样适用,三大坑同样存在,与语言无关 | 同左 |

**Go 侧的两个成熟实践,值得你直接移植到 Java 思路里**:

第一,**防击穿用 singleflight**。上面 19.4.2 已并排对比过。Go 把"合并并发只执行一次"做成了标准库扩展,比手写 Redis 锁省心。Java 侧没有标准库等价物,你要么用 `SET NX` 手写(注意锁过期和误删),要么引入 Redisson 的 `RLock`(分布式、可重入、带看门狗自动续期),要么用 Caffeine 的 `get(key, k -> load())` 在本地层合并——本地合并 + Redis 回源,效果和 singleflight 接近。

第二,**热 key 用本地多级缓存**。Go 的 `BigCache` / `freecache` 是纯内存、无 GC 压力的本地缓存(它们用堆外或分片绕开 Go GC 大对象问题),常叠在 Redis 前:读顺序 `本地 → Redis → DB`。Java 侧对应 Caffeine,同样叠在 `RedisTemplate` 前:

```java
// Java 多级缓存:本地 Caffeine 挡热点,Redis 挡次热,DB 兜底
Cache<String, Object> local = Caffeine.newBuilder()
        .maximumSize(10_000).expireAfterWrite(Duration.ofMinutes(5)).build();

public User getUserMulti(Long id) {
    String key = "user:" + id;
    Object v = local.getIfPresent(key);          // 1. 本地命中,最快
    if (v != null) return (User) v;
    v = redisTemplate.opsForValue().get(key);    // 2. Redis 命中
    if (v != null) { local.put(key, v); return (User) v; }
    User u = userMapper.selectById(id);          // 3. 回源 DB
    redisTemplate.opsForValue().set(key, u, Duration.ofMinutes(30));
    local.put(key, u);
    return u;
}
```

**问题 6:** Go 的 go-redis 和 Java 的 Lettuce,都是"一个 client 全局复用、内部池化",那 redigo 为什么被说"较老"?

redigo 是 Go 早期最流行的客户端,但它的 API 偏底层(返回 `redis.Conn`,要手动管连接、手动 `Flush`/`Receive`),且官方已声明进入维护模式、不再激进更新。go-redis(现 `redis/go-redis`)API 更现代:支持 context、Pipeline、Cluster、哨兵、Sentinel,类型安全更好,基本是今天 Go 项目的新默认。这跟 Java 侧"Jedis 老、Lettuce 新"的演进方向一致——社区都在往"基于事件循环 / 连接池内建 / 异步友好"走。你从 Go 转 Java,直接默认用 Lettuce + 配池,不会对齐错对象。

**Go 程序员最容易踩的 Java 专属坑**:① 以为 `RedisTemplate` 开箱即用就万事大吉,结果 JDK 序列化把数据写成不可读二进制、还跨语言不通(覆盖序列化器!);② 以为 Lettuce 线程安全就不用管连接,结果高并发下共享单连接成瓶颈(配池!);③ 在 Go 里习惯了 client 内建池,到 Java 忘了 Jedis 不池化会串台、Lettuce 不配池会卡吞吐。

---

## 19.8 本章核心结论

1. Redis 挡 DB 的本质是"内存纳秒级读取 + 单线程串行免锁",它把高频读从磁盘慢路径挪到内存快路径,代价是单线程下任何慢命令都会阻塞全局。
2. Cache-Aside 是生产主流:读时回填、写时删缓存;它只保证最终一致,绝不保证强一致,不一致窗口是设计使然而非 bug。
3. Spring Boot 2.x 默认 Lettuce(Netty 异步、线程安全);但高并发同步调用下必须关掉 `shareNativeConnection` 并配 commons-pool2 连接池,否则单连接成瓶颈——思路同 17 章 HikariCP 池化。
4. `RedisTemplate` 默认 JDK 序列化会写出带类名的二进制丑数据、且改类名即反序列化失败;生产应换 JSON 序列化器(`GenericJackson2JsonRedisSerializer` 或自定义)。
5. 缓存三大坑要分清:穿透=查不存在的 key(布隆过滤器 / 空值缓存),击穿=热点 key 过期瞬间并发打 DB(互斥锁 / singleflight / 逻辑过期),雪崩=大量 key 同过期或 Redis 宕机(随机 TTL / 多级缓存 / 高可用)。
6. 缓存与 DB 一致性:默认"先更 DB 再删缓存",增强用延迟双删;强一致几乎不可能,最终一致靠 MQ 异步删缓存兜底,引出第 20 章。
7. 大 key 阻塞单线程、热 key 打满单分片;用 `redis-cli --bigkeys` 识别,靠拆分 / 本地多级缓存打散。
8. Go 侧 go-redis + singleflight + BigCache 是成熟组合,三大坑与 Cache-Aside 和 Java 完全一致,只是序列化、池化、防击穿的原语不同——你的 Go 经验直接可迁移。

---

## 19.9 深度思考题

**题目 1(穿透 vs 击穿的区分):** 你监控到 DB 突然流量翻倍但缓存命中率没明显变化,这更像穿透还是击穿?如果是击穿,缓存命中率会怎么变?

> 【思考】缓存命中率这个指标,能不能单独用来区分穿透和击穿?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:DB 流量翻倍但缓存命中率没明显变化,更像**击穿**(热点 key 过期瞬间,命中率会在那一小段骤降然后恢复,你可能正好没采到低谷);如果是典型的穿透,缓存命中率会**持续偏低甚至接近 0%**,因为请求的参数根本不在缓存里、永远不命中。

**展开**:穿透的特征是"命中率长期低 + DB 查的都是不存在的数据";击穿的特征是"命中率瞬间跳水又回弹 + DB 那一瞬被打的是真实热点 key"。所以单看命中率不够,要结合"DB 查询的内容是否存在"和"时间分布(持续 vs 尖峰)"。监控上建议同时看三个量:缓存命中率、DB 的 `rows_examined` 分布(穿透的行数常为 0/1)、以及热点 key 的过期时间线。

**更深一层**:指标要"成对看"才有意义。命中率单独是个比率,掩盖了"查的是不存在的"还是"查的是过期热点"的本质区别。你在 08 章学的排错方法论在这里用得上——先问"现象对应哪种触发条件",再反推指标该怎么组合。

</details>

**题目 2(Lettuce 池化的副作用):** 你把 Lettuce 的 `shareNativeConnection` 关掉并配了 `max-active=16` 的池。现在连接数上去了,RT 降了,但 Redis 服务端 `connected_clients` 从 1 涨到几十。这会带来什么新成本?连接数不是越多越好,边界在哪?

> 【思考】连接池是不是越大越能扛?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:不是越大越好。每条连接占用 Redis 端的文件描述符、内核 socket 缓冲和一定的内存;连接数暴涨会带来 Redis 端内存和上下文切换开销,且在 Redis 单线程处理下,连接多不等于命令执行快——命令在 Redis 端依旧串行。池过大还可能压垮 Redis 的 `maxclients`,或在客户端机器上耗尽 fd。

**展开**:池大小要匹配"你的并发量 / 单连接往返耗时"。同步阻塞调用下,一条连接同一时刻只能跑一个命令,吞吐 ≈ 1 / 平均RT;要扛 N 的 QPS,池至少要 N × 平均RT 量级。`max-active=16` 对多数服务够用,但如果你 RT 是 1ms、QPS 要 5000,16 条连接理论吞吐才 16000 但排队会堆积——这时该加池,或改用 Lettuce 异步 API 让单连接多路复用。关键是压测定边界,不是拍脑袋设大数。

**更深一层**:池化是用"资源(连接)"换"并发",资源有上限、有成本。这和 17 章 HikariCP 完全一致——`maximumPoolSize` 设太大反而因线程竞争和连接保活拖垮 DB。任何池的参数都是"在实测拐点附近取值",不是越大越安全。

</details>

**题目 3(序列化选型的安全性):** `GenericJackson2JsonRedisSerializer` 因为往 JSON 里写了 `@class`,方便反序列化,但有人指出这有反序列化漏洞风险。什么场景下这真的是风险?你怎么既保留方便又去掉风险?

> 【思考】"自动按类名加载类"在什么输入下会变成攻击面?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:风险出现在"缓存内容可能来自不可信来源"时——比如 key 可被外部写入、或 Redis 本身被多租户/公网接触。攻击者可构造带恶意 `@class` 的 JSON,Jackson 反序列化时按类名实例化对象,触发 gadget chain 造成 RCE。自己服务内部、Redis 仅内网且 key 写入受控时,风险低。

**展开**:要既方便又安全,用 `Jackson2JsonRedisSerializer`(不带 `@class`)并**在反序列化时显式指定目标类型**(`new Jackson2JsonRedisSerializer<>(User.class)`),或读出来后手动 `objectMapper.readValue(json, User.class)`。这样 JSON 里没有类型指令,无法被诱导加载任意类,类型由你的代码决定。也可配合 Redis 的 ACL 把写入权限收口、用 `redis.conf` 的 `rename-command` 关掉危险命令。

**更深一层**:任何"数据里携带类型/代码指令、由接收方执行"的机制,本质都是反序列化攻击面(Java 原生序列化、PHP 的 `unserialize`、Python 的 `pickle` 同理)。安全原则只有一条:**不要反序列化你不信任的来源里的类型信息**。Go 的 `json.Unmarshal` 强制你传目标类型,反而天然避开了这坑——这是 Go 设计里"显式优于隐式"在安全上的红利。

</details>

**题目 4(延迟双删的粗糙):** 延迟双删用 `Thread.sleep(500)` 猜"并发读回填"的窗口。如果业务读很慢、500ms 不够,会怎样?如果读很快、500ms 太长,又浪费了什么?有没有不靠 sleep 的更稳方案?

> 【思考】用固定 sleep 猜窗口,在分布式多实例部署下还成立吗?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:sleep 不够 → 第二次删发生在旧值回填之前,脏数据继续存活;sleep 太长 → 无谓延迟、且期间若有新写又产生新窗口。更稳的方案是直接用 MQ:写 DB 后发"删缓存"消息,由消费者可靠重试删除,不靠猜窗口;或监听 binlog(Canal)由下游统一删,顺序由 binlog 保证,且多实例下每个实例都消费同一事件、各自删本地/Redis 缓存。

**展开**:`Thread.sleep` 在单实例、读快时能凑合,但多实例部署时,实例 A 的 sleep 管不了实例 B 的读回填——B 可能刚回填旧值,A 的第二次删早执行完了,脏数据又回来了。所以 sleep 方案根本不具备跨实例正确性,只是单机的权宜。MQ / binlog 方案把"删缓存"变成跨实例的、有序的、可重试的事件,才真正兜住。

**更深一层**:凡是用"时间"去掩盖"并发时序"问题的,都是在赌一个会变的常量。sleep 的毫秒数是业务读耗时的函数,而读耗时随数据量、DB 负载波动。把不变的时间去对齐变化的时序,迟早漏。工程上正确的姿势是**用事件(消息/binlog)显式表达"该删了",而不是用延时隐式等待**——这正好是第 20 章消息队列要解决的问题。

</details>

**题目 5(开放题,无标准答案):** 如果让你从零设计一个"秒杀库存"的缓存方案,你会在缓存里放什么、DB 里放什么、扣减走谁、一致性靠什么保证?要不要把库存这种强一致数据放进 Redis?

> 【思考】秒杀场景下,"超卖"和"少卖"哪个更不可接受?这个业务判断会不会反过来决定你的架构?

<details>
<summary><b>参考答案</b></summary>

**方向提示(非唯一解)**:库存这种数据,纯放 Redis 用 `DECR` 扣,若 Redis 与 DB 不同步就会超卖;纯放 DB 用行锁扣,高并发下 DB 顶不住。生产常见折中:DB 持真相(行锁 / 乐观锁保证不超卖),Redis 预扣减做"前置闸门"挡掉绝大多数无效请求,真正成交才落 DB 并删 Redis 预扣;少卖(预扣了没成交)靠异步回补,比超卖(资损)可接受。一致性靠"DB 为最终裁决 + MQ 异步对账回补"。是否进 Redis,取决于你能不能接受"少卖"——秒杀里少卖通常比超卖温和,所以 Redis 可作加速层,但绝不能当真相源。

**更深一层**:这道题没有标准答案,因为它考的是"业务 SLA 决定架构"——你先得回答超卖和少卖哪个致命,才能定缓存放什么。技术选型永远在被业务代价牵引,而非反过来。

</details>

---

## 下一章预告

第 20 章讲 **Kafka 与消息队列**:缓存一致性里"写 DB 后异步删缓存"靠什么兜底?大促写请求怎么削峰?服务间怎么解耦?这一章你会学到 MQ 的三板斧——异步、解耦、削峰,以及 Producer/Consumer、offset、消费组这些核心概念。我们还会把 Go 的 `sarama` / `kafka-go` 客户端和 Java 的 Spring Kafka 并排对照,让你看到"消息队列"在两种语言里如何殊途同归。承接关系很清楚:本章的延迟双删、MQ 兜底删缓存、binlog 同步,全都要落到第 20 章的 MQ 上——缓存一致性、异步写、削峰填谷,离不开消息队列。
