# 第 14 章　Spring 核心：IoC、DI 与 AOP（把魔法翻译成 Map<String, Object>）

> 你第 N 次看到这段代码：
>
> ```java
> @RestController
> public class UserController {
>     @Autowired
>     private UserService userService;
>
>     @GetMapping("/user/{id}")
>     public User get(@PathVariable Long id) {
>         return userService.findById(id);   // userService 是谁 new 的？userService 里的 repository 谁塞的？
>     }
> }
> ```
>
> 你找不到 `new UserService()`，找不到 `userService.setRepository(...)`,但代码能跑。在 Go 里这不可能——你一定在某个 `main()` 里 new 了它、注入了它。Spring 把这件事吞了。
> 这一章把"吞掉的东西"全部吐出来：**谁创建了 Bean、谁注入了依赖、注解怎么变成动作、以及为什么你的 `@Transactional` 有时候不生效。**

---

## 14.1 IoC：控制反转到底反转了什么

先别急着背定义。我们看两段能跑的代码,然后你告诉我它们的区别到底在哪。

第一段,Go 味儿的"正转"写法(虽然这是 Java,但逻辑是 Go 的):

```java
// 控制正转：你自己控制对象的创建和装配
public class OrderApp {
    public static void main(String[] args) {
        OrderRepository repo = new OrderRepositoryImpl(new DataSource());
        OrderService service = new OrderServiceImpl(repo);  // 你 new 的
        service.createOrder(...);                            // 你调用的
    }
}
```

第二段,Spring 味儿的"反转"写法:

```java
@RestController
public class OrderController {
    private final OrderService orderService;

    public OrderController(OrderService orderService) {  // 你只"要"一个 OrderService
        this.orderService = orderService;                // 谁传进来的?你不知道,也不该关心
    }
}
```

区别不在语法,在**控制权在谁手里**。第一段里,`OrderServiceImpl` 的创建、`repo` 的装配,全在你 `main()` 的掌控下——**你控制对象的生死和关系**。第二段里,你只声明"我需要一个 `OrderService`",至于它怎么来、它的 `repo` 是谁、是 MySQL 实现还是内存实现,**控制权反转给了容器**。

这就引出本章最核心的一句定性:

**IoC(Inversion of Control,控制反转)是一种设计原则——好莱坞原则:"don't call us, we'll call you"(别打电话给我们,我们会打给你)。DI(Dependency Injection,依赖注入)是实现 IoC 的一种手段:容器把依赖"注入"给你的对象,而不是你自己去拿。**

注意措辞:IoC 是"原则",DI 是"手段"。这俩不是同义词。

**问题 1:** 既然 IoC 是更宽泛的概念,那还有别的手段吗?

有。最典型的另一个实现叫 **Service Locator(服务定位器)**。它长这样:

```java
// Service Locator:主动去容器里"取"
OrderService service = ServiceLocator.getBean(OrderService.class);
service.createOrder(...);
```

你看,Service Locator 也是 IoC——框架(容器)控制着对象的创建,你只是去取。但它和 DI 有个致命区别:**Service Locator 要求你的业务代码里到处带着容器引用**(`ctx.getBean(...)`),业务类被容器侵入了。DI 不侵入:你只写构造器参数,容器在背后帮你填,业务代码根本不知道容器的存在。

这就是为什么 Spring 选了 DI 而非 Service Locator。票根上写的是:DI 让业务代码保持纯净,可测试性更好(你可以直接 `new OrderService(mockRepo)`)。

> 【思考】为什么叫"控制反转"而不是"依赖注入"?IoC 和 DI 到底什么关系?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:IoC 是"框架调用你的代码"这个更宽泛的设计思想(最早泛指"控制权从应用代码转移到框架"),DI 只是 IoC 的一种具体实现方式。两者是"父类-子类"关系:IoC 是抽象,DI 是 Concrete 之一。

**为什么不直接叫 DI?**

"控制反转"这个词是 1988 年 Johnson 和 Foote 提出的,当时描述的是一种更普遍的现象:**传统程序里你主动调用库,反转之后变成框架主动调用你的代码**(模板方法、回调、事件监听都是 IoC)。依赖注入是 2004 年 Martin Fowler 才定名的,它是 IoC 在"对象装配"这个子问题上的具体落地。

除 DI 外,IoC 还有别的实现:

- **Service Locator**:主动 `ctx.getBean(Xxx.class)` 去取。它也把"创建对象"的控制权交给了框架,所以也是 IoC。但如正文所说,它侵入业务代码(到处传 container)。
- **事件/回调机制**:`ApplicationListener` 监听容器事件,也是"框架回调你"的 IoC。

**代码锚点——同一个功能,两种 IoC 风格的差异:**

```java
// DI 风格:容器帮你注入,业务代码无感知
@Service
public class OrderService {
    private final OrderRepository repo;
    public OrderService(OrderRepository repo) { this.repo = repo; }  // 干净
}

// Service Locator 风格:业务代码依赖容器
public class OrderService {
    private final OrderRepository repo =
        (OrderRepository) Container.current().getBean("orderRepo");  // 侵入
}
```

DI 风格下 `OrderService` 是个普通类,任何环境都能 `new`(测试时传 mock);Service Locator 风格下它绑定了某个全局容器,脱离了容器就废了。

**Go 对照**:你用的 `wire` 也是 DI——但它是**编译期 DI**。wire 在编译时生成 `wire_gen.go`,里面是显式的 `new OrderServiceImpl(new OrderRepositoryImpl(...))`,等价于把 DI 的结果"固化"成代码。Spring 是**运行时 DI**,靠反射 + 注解在启动时装配。这是 00 章卡点五那张对照表的本质:

| 维度 | Go (wire) | Java (Spring) |
|---|---|---|
| 依赖图解析时机 | 编译期,生成代码 | 运行时,反射扫描 |
| 看依赖图 | 打开 `wire_gen.go` | 看 `/actuator/beans` 或启动日志 |
| 出错时机 | 编译失败 | 启动失败,或更糟:注入错实现 |

**更深一层**:IoC 这个名字起得其实有点抽象,导致初学者以为它是某种"高级技术"。它本质是**一种责任转移**——把"对象怎么来、依赖怎么组装"这件事,从手写代码转移给一个统一的机制。你付出的代价是:代码里再也看不到 `new` 和装配,可追踪性下降(所以才需要 00 章讲的 Actuator 工具恢复可观测性)。你得到的收益是:实现可替换、可插拔、无需重编译。这笔交易划不划算,取决于你的项目规模——小项目亏,大项目赚。
</details>

Go 对照:你在 Go 里**手动** wired(在 `main()` 里 new + 注入,或 `wire` 生成)。Spring 把这件事**推迟到运行时 + 用注解声明**。代价与收益在 00 章讲过,这里给一个"手写 DI → Spring 注解 DI"的并排演进:

```go
// Go 手动 DI:一眼看到依赖从哪来
func main() {
    repo := NewOrderRepository(db)
    svc := NewOrderService(repo)   // 显式装配
    handler := NewOrderHandler(svc)
    r := gin.New()
    r.GET("/order/:id", handler.Get)
}
```

```java
// Spring 注解 DI:装配被容器接管
@Configuration
public class AppConfig {
    @Bean public OrderRepository orderRepository(DataSource ds) { return new OrderRepository(ds); }
    @Bean public OrderService orderService(OrderRepository r) { return new OrderService(r); }
}
// 或者直接 @Service / @Component 让容器扫
```

并排看你就明白了:Go 那一串 `NewXxx(...)` 是**你亲笔写的、可跳转的真相**;Spring 那一堆注解是**你给容器的指令**,容器在运行时替你执行装配。前者"代码即真相",后者"配置即真相"。

---

## 14.2 DI 的三种注入方式(以及为什么构造器注入是默认答案)

Spring 里往一个 Bean 里塞依赖,有三种主流写法。我们挨个看,然后我会告诉你为什么 Spring 官方只推荐其中一种。

### 方式一:字段注入(最简洁,也最危险)

```java
@Service
public class OrderService {
    @Autowired
    private OrderRepository orderRepository;   // 直接标在字段上
}
```

一个注解解决一切,看起来很爽。但它有四个坑,每一个都够你喝一壶:

1. **无法设为 `final`**——字段在构造后由反射填,所以你没法声明不可变性,依赖可能被改。
2. **单元测试必须启动容器**——你想测 `OrderService` 却传不进 mock,因为字段是私有的、由容器反射塞的。你得 `@SpringBootTest` 把整个容器拉起来才能测(慢,且测试变重)。
3. **循环依赖被掩盖**——A 和 B 互相字段注入,容器能"先造空壳再填字段"把环解开(14.6 讲),于是坏设计在启动期不报错,埋成运行时雷。
4. **依赖可能为 null**——如果容器里压根没有 `OrderRepository` 这个 Bean(比如你忘了加 `@Repository`),启动期不一定炸,直到运行时调到这个字段才 NPE。

### 方式二:构造器注入(Spring 官方推荐)

```java
@Service
public class OrderService {
    private final OrderRepository orderRepository;

    public OrderService(OrderRepository orderRepository) {  // 构造器要啥,容器给啥
        this.orderRepository = orderRepository;
    }
}
// 字段少时可用 Lombok: @RequiredArgsConstructor(onConstructor = @__(@Autowired))
```

优点恰好对应字段注入的缺点:

1. **依赖不可变**(`final`),构造完就定死,线程安全有保障。
2. **完全可测试**:`new OrderService(mockRepo)` 一行就够了,不用容器。
3. **启动即失败**:缺依赖,Spring 启动时就 `BeanCreationException`,而不是运行时 NPE——Bug 提前到启动期暴露。
4. **天然防循环依赖**(见下方【思考】)。

### 方式三:setter 注入(可选依赖时用)

```java
@Service
public class OrderService {
    private OrderRepository orderRepository;

    @Autowired
    public void setOrderRepository(OrderRepository repo) {  // 运行时可换实现
        this.orderRepository = repo;
    }
}
```

适合"可选依赖"(没它也能跑,比如一个监控钩子)或"想运行时替换实现"的场景。但凡是必须有的依赖,别用 setter。

> 【思考】为什么构造器注入能"天然防循环依赖"但字段注入不能?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:构造器注入要求"先有依赖才能构造出本对象",而循环依赖里 A 的构造要 B、B 的构造要 A,死锁在构造阶段就暴露;字段注入允许"先 new 出空壳对象、再回头填字段",把循环依赖的环悄悄解开了,于是坏设计不报错。

**展开看机制**:

构造器注入下,Spring 想创建 A,必须先拿到 A 的构造参数 B;去创建 B,又要 B 的构造参数 A。此时 A 还没被构造出来(构造和实例化是一步,没有"半成品"空隙),Spring 直接抛 `BeanCurrentlyInCreationException`。**循环在启动期就报错**,你立刻知道设计有问题。

字段注入下,Spring 的执行顺序是:① 反射 `new A()` 拿到一个空壳(字段还是 null)→ ② 把 A 放进"正在创建"集合 → ③ 反射填 A 的字段,发现要 B → ④ `new B()` 空壳 → ⑤ 填 B 的字段要 A → ⑥ 从"正在创建"集合里拿到 A 的**早期引用**(半成品)填进去 → ⑦ B 完成 → ⑧ 回到 A 把 B 填进去。环被"先有空壳再填字段"的机制化解了,启动不报错,**但 A 和 B 各自持有一个字段可能未完全初始化的对象**,直到运行时某次调用踩到 null 才炸。

**代码锚点——构造器循环依赖的报错**:

```java
@Service
public class A { public A(B b) {} }   // 构造要 B
@Service
public class B { public B(A a) {} }   // 构造要 A
// 启动直接:
// BeanCurrentlyInCreationException:
// Requested bean is currently in creation: Is there an unresolvable circular reference?
```

**更深一层**:Spring 之所以**推荐**构造器注入,正是因为构造器注入让循环依赖"报错而不是静默"。循环依赖本身是个设计坏味道(两个类紧耦合),字段注入把它藏起来,等上线后才爆;构造器注入把它顶到启动期,逼你改设计(拆类、用 `@Lazy`、或引第三方)。**这是"fail fast"哲学在 DI 上的体现**——和你 00 章看到的 `ArrayList` fail-fast 是同一个脾气。

Go 对照见下一个【思考】。
</details>

> 【思考】Go 里你怎么保证"依赖不为 nil"?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:Go 里你在 `main()` 里手动构造,如果某个依赖没传进去,要么**编译报错**(你没把依赖传给构造函数),要么你**显式 `if dep == nil { panic }`**。Go 没有"字段注入"这种运行时才填的东西,所以天然不会遇到"半成品对象"。

**代码锚点——Go 的两种防御**:

```go
func NewOrderService(repo OrderRepository) *OrderService {
    if repo == nil {                  // 防御式:启动即 panic,而不是运行时某次调用才 NPE
        panic("OrderRepository is nil")
    }
    return &OrderService{repo: repo}
}

func main() {
    repo := NewOrderRepository(db)
    // 如果忘了传 repo,下面这行编译都过不了(Go 的类型系统强制)
    svc := NewOrderService(repo)
}
```

对比 Spring 字段注入:你在业务代码里写 `@Autowired private OrderRepository repo`,**没有任何一处**强制 repo 非 nil。容器没扫到这个 Bean,代码照常编译,启动可能照常过(取决于是否有别的同类型 Bean 兜底),直到运行时 `repo.findById(...)` 才 NPE。

**更深一层**:这是**编译期 DI 的结构性优势**。wire 生成的代码就是一串 `NewXxx(...)`,每个构造函数参数都被类型系统强制,漏传一个就编译失败——错误被推到编译期。Spring 的运行时 DI 把错误推到启动期甚至运行期,换来了"换实现不用改代码"的灵活。两种选择,两种代价,没有谁绝对好。你作为 Go 老哥,初学 Spring 会觉得"这也能炸?",其实是范式差异:你习惯了"编译期兜底",Spring 习惯了"启动期兜底",而启动期兜底的前提是你**真的会去看启动日志**。
</details>

**问题 2:** 那如果我就想要可选依赖,又不想用 setter,怎么办?

用构造器 + `@Nullable` 标注可选参数,或者把可选依赖做成单独的 Bean、用 `@Autowired(required = false)`(字段/setter 场景)。通常更干净的做法是:必须依赖走构造器,真正可选的才走 setter。Spring 4.3 之后,**只要类只有一个构造器,`@Autowired` 都可以省**,容器自动用那个构造器注入——这是引导你走构造器注入的"暗手"。

**问题 3:** Lombok 的 `@RequiredArgsConstructor` 标在类上,它生成的构造器只含 `final` 字段。那非 final 的必填依赖它能处理吗?

不能。`@RequiredArgsConstructor` 只收集 `final` 和 `@NonNull` 字段。所以想用 Lombok 省构造器,就把所有必填依赖声明成 `final`——这反而逼你写出不可变的 Bean,正合 Spring 的意。

---

## 14.3 Bean:容器里的对象长什么样

"Bean" 这个词你到处都见,但它的精确定义值得花三十秒:

**Bean 就是被 Spring 容器管理的对象。你自己 `new` 出来的,不是 Bean——它没有生命周期、没被代理、没被纳入容器管理。**

这是 Go 老哥最容易混淆的点:在 Go 里你 `new` 出来的对象就是对象,无所谓"是否被框架管理"。Spring 里这道界线是硬的——只有进了容器(`Map<String, Object>`)的那个实例,才享有代理、作用域、生命周期回调等一切能力。你 `new UserService()` 手动造的,`@Transactional` 在它身上**绝不生效**,因为它绕过了容器。

**问题 4:** 那容器怎么知道要把哪些类变成 Bean?靠 `BeanDefinition`。

`BeanDefinition` 是容器里描述"一个 Bean 该怎么造"的元数据:类名、scope、构造器参数、要注入的属性、init/destroy 方法、是否懒加载……它是 Spring 把"类"翻译成"可管理对象"的**中间表示**。你可以把它理解为:容器先扫一遍 classpath,给每个候选类生成一份"建造说明书"(`BeanDefinition`),之后照着说明书实例化。

注册 Bean 的方式有三种,按使用频率排序:

1. **`@Component` 族**:`@Service` / `@Repository` / `@Controller` / `@Configuration` / `@Component`,容器启动时扫 classpath,带这些注解的类自动注册。
2. **`@Bean`**:写在 `@Configuration` 类的方法里,方法返回的对象注册成 Bean。适合"第三方库的类你改不了源码、加不了注解"的情况(比如 `RestTemplate`、`DataSource`)。
3. **XML `<bean>`**:老式写法,Spring Boot 项目基本见不到了,但你会遇到老项目。

**问题 5:** `@Component` 和 `@Bean` 选哪个?

经验法则:类是你自己写的、能加注解 → 用 `@Component` 族;类是别人的(框架/库提供的)→ 在 `@Configuration` 里用 `@Bean` 包一层。下面这张作用域表是本章必背:

| scope | 含义 | 典型用途 |
|---|---|---|
| `singleton`(默认) | 整个容器一个实例 | Service、Repository、Controller |
| `prototype` | 每次取都新建一个 | 有状态的对象、每次请求独立的内部助手 |
| `request` | 每个 HTTP 请求一个 | Web 层请求级状态 |
| `session` | 每个用户会话一个 | 用户会话状态(购物车) |
| `application` | 每个 ServletContext 一个 | ServletContext 级共享数据 |

还有 `websocket` scope(每次 WebSocket 会话一个),用得少,知道有就行。

> 【思考】为什么 Spring 的 Bean 默认是 singleton,而 Go 里你通常每次请求 new 一个 handler?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:因为 Spring 的 singleton Bean 里**不该有可变请求级状态**(呼应 01 章那个 `UserService` 缓存 bug)。Service/Repository 是无状态的,单例安全。Go 里你习惯把请求状态放结构体字段里所以每次 new handler——这是两种"状态放哪"的范式差异。

**展开**:

Spring 的 `singleton` 是说"这个 Bean 在容器里只存在一份,所有请求线程共享它"。这没问题**前提是 Bean 无状态**。一个典型的 `OrderService` 只持有 `OrderRepository`(也是无状态单例),自身没有任何随请求变的字段,所以多线程共享完全安全。

而 01 章题 3 那段"翻车代码"正好展示了反面教材:

```java
@Service
public class UserService {
    @Autowired private UserRepository userRepo;
    private List<User> cache = new ArrayList<>();   // ❌ 单例里放可变状态
    // 多线程 + 单例 => cache 被所有请求共享,并发错乱 + 内存泄漏
}
```

`cache` 是实例字段,但 `UserService` 是单例——于是 `cache` 变成全局可变状态,并发下直接炸。这就是"单例里放请求状态"的经典后果。

**Go 对照**:你在 Go 里 `r.GET("/user/:id", func(c *gin.Context){...})`,handler 通常是每次请求 new 的(或 handler 结构体里只放无状态的 `*Repo`,请求数据走 `c` 传)。Go 习惯"把状态放结构体字段",所以 new 一个 handler 是自然的。Spring 反过来:**状态要么放方法局部变量,要么放专门的缓存组件(Redis/Caffeine/`@Cacheable`)**,Bean 本身保持无状态才能安全地单例。

**更深一层**:这解释了为什么 00 章说"Spring 的魔法本质是拿编译期确定性换运行时灵活性"。单例 + 无状态是 Spring 性能好的根因(省内存、省 GC),但它对你的编码纪律提出了要求:**单例 Bean 必须是无状态的**。Go 没有这个约束(因为每个 handler 是新对象),所以 Go 老哥转到 Spring 第一坑就是"在单例里存了请求状态"。记住这条:

> Bean 里只能放"跨请求不变的依赖引用",不能放"随请求变的数据"。

这正好和 01 章题 3 的结论闭环——那道题说的"单例里别放可变状态",根因就在这。
</details>

> 【思考】`prototype` Bean 的循环依赖会怎样?为什么它和 singleton 的处理不一样?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:`prototype` Bean 的循环依赖会**直接报错**(`BeanCurrentlyInCreationException`),Spring 解不了。因为它无法套用 singleton 的"三级缓存提前暴露"机制——prototype 每次取都新建,本来就没有"可被共享的早期引用"可言。

**为什么 singleton 能解而 prototype 不能?**

singleton 解决循环依赖靠的是 14.6 要讲的"三级缓存":A 实例化出空壳后,把一个能返回 A 早期引用的工厂放进三级缓存;等 B 需要 A 时,从工厂拿到 A 的早期引用填进去,环就解了。这套机制成立的前提是:**A 的实例最终会进一级缓存被所有人共享**,所以"B 手里那份早期引用"和"容器手里那份成品"最终是同一个对象(或同一个代理),一致性有保证。

`prototype` 语义是"每次取都 new 一个",压根没有"共享的那个 A"。如果 A 要 B、B 要 A,且都是 prototype:Spring 给 A 造了个 B,B 又要一个全新的 A,这个新 A 又要 B……无限递归,而且即使造出来也没法回填给"上上个 A"(因为它们不是同一个实例)。所以 Spring 对 prototype 的循环依赖直接放弃,启动就报错。

**代码锚点**:

```java
@Scope("prototype")
@Service
public class A { public A(B b) {} }

@Scope("prototype")
@Service
public class B { public B(A a) {} }
// 启动时即抛: Requested bean is currently in creation: prototype scoped bean...
```

**更深一层**:这个区别揭示了一个事实——Spring 的"循环依赖能解"是**特例**(只针对 singleton + 字段/setter 注入),不是通用能力。凡是偏离 singleton 语义(scope 变了、或用了构造器注入),循环依赖一律报错。所以别把"字段注入能扛循环依赖"当成优点,它只是 singleton 机制的一个副作用;真正健康的做法是消灭循环依赖,而不是靠机制掩盖它。
</details>

---

## 14.4 Bean 的生命周期:从类到对象的 8 步

这是面试高频题,但实战里你迟早也会撞上(尤其是 `@PostConstruct` 没执行、`@Transactional` 在 init 里没生效这类诡异现象)。先给完整的生命周期顺序,脑子里要能背下来:

1. **实例化(Instantiation)**:反射调用构造器,拿到一个"空对象"(字段都还是默认值/null)。
2. **属性填充(Populate)**:DI 发生在这里——注入 `@Autowired` 字段、构造器参数、setter 参数。
3. **Aware 接口回调**:如果 Bean 实现了 `BeanNameAware` / `BeanFactoryAware` / `ApplicationContextAware`,容器把对应对象(`beanName`、`BeanFactory`、`ApplicationContext`)注入进来。
4. **`BeanPostProcessor.postProcessBeforeInitialization`**:所有 Bean 都会经过这个钩子,容器内任何 `BeanPostProcessor` 都有机会在初始化前改它。
5. **初始化(Initialization)**:执行 `@PostConstruct` 标注的方法,或 `InitializingBean.afterPropertiesSet()`。这是"依赖都齐了,做点启动准备"的地方。
6. **`BeanPostProcessor.postProcessAfterInitialization`**:**AOP 代理就在这里生成**(14.5 重点)。如果 Bean 需要被切面增强,容器在这里把原始对象换成代理对象。
7. **就绪**:Bean 进入容器,可以被其他 Bean 引用、可以被你 `getBean` 拿到。
8. **销毁(Destruction)**:容器关闭时,执行 `@PreDestroy` 或 `DisposableBean.destroy()`,做资源释放。

三个关键接口的作用:

- **`InitializingBean`**:`afterPropertiesSet()`——属性填完后调,等价于 `@PostConstruct`,但侵入接口(要 `implements`),所以一般推荐注解版。
- **`DisposableBean`**:`destroy()`——容器关闭时调,等价于 `@PreDestroy`。
- **`BeanPostProcessor`**:这是 Spring 的"总钩子"。**所有 Bean 创建时都会经过它**,AOP、事务(`@Transactional`)、异步(`@Async`)、校验,全靠它实现。理解它就理解了"魔法"的总开关:容器在步骤 4 和 6 各扫一遍所有 `BeanPostProcessor`,谁想改这个 Bean 谁就动手。

> 【思考】为什么 `@PostConstruct` 比 XML 的 `init-method` 属性好?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:注解写在业务代码里,自解释、跟方法绑定、不依赖外部 XML;但更本质的理由是——**生命周期回调越早做越好,避免用到一个还没初始化完的 Bean**。

**展开**:

XML 时代的写法是:

```xml
<bean id="orderService" class="com.x.OrderService" init-method="init"/>
```

问题在哪?`init-method="init"` 是个字符串,藏在 XML 里,你读 `OrderService.java` 时根本不知道它有个初始化方法,IDE 也不会提示;方法名拼错,编译期不报错,启动才炸。`@PostConstruct` 直接标在方法上:

```java
@Service
public class OrderService {
    private final OrderRepository repo;
    private SomeClient client;

    public OrderService(OrderRepository repo) { this.repo = repo; }

    @PostConstruct
    public void init() {                 // 依赖都注入完了才执行
        this.client = repo.loadClientConfig();
        client.healthCheck();            // 放在这里,保证 client 已就绪
    }
}
```

**为什么"早做"重要?** 因为 `@PostConstruct` 在第 5 步执行,此时所有依赖(步骤 2 已填完)都齐了。如果你把"依赖某个 Bean 已就绪"的逻辑写在别处(比如第一次请求时才懒加载),就可能遇到"半成品 Bean"。

**Go 对照**:Go 对象没有容器管理的生命周期。你通常是 `new -> 自己调 Init/Start -> 自己调 Stop`,顺序完全靠你手写:

```go
svc := NewOrderService(repo)
if err := svc.Init(); err != nil {   // 自己负责调,且容易忘了调
    log.Fatal(err)
}
defer svc.Stop()
```

Spring 把 `Init/Start/Stop` 交给容器统一编排:你只标注解,容器保证"所有依赖注入完才调 init、容器关闭才调 destroy"。**代价**:你看不到编排顺序(黑箱);**收益**:生命周期统一、优雅停机自动触发(收到 SIGTERM 时容器挨个调 `@PreDestroy`)。

**更深一层**:`BeanPostProcessor` 存在于步骤 4/6,意味着**任何初始化逻辑(包括 `@PostConstruct`)都在 AOP 代理生成之前**。这解释了为什么"在 `@PostConstruct` 里调用本 Bean 的一个 `@Transactional` 方法"事务会生效(此时还是原始对象,但方法直接被本对象调,不经过代理也还行——注意这里有别于自调用的细节,14.5 会讲清代理边界)。一句话:生命周期步骤的顺序不是随便排的,它决定了哪些能力在哪一刻才可用。
</details>

**问题 6:** 如果 `@PostConstruct` 里抛了异常,会怎样?

整个 Bean 创建失败,容器启动中止(除非这个 Bean 是 `@Lazy` 且没被用到)。所以 `@PostConstruct` 里只放"启动必须成功"的轻量检查(连数据库探活、加载配置),别放可能失败的重逻辑。

**问题 7:** `BeanPostProcessor` 会不会处理它自己?

不会——`BeanPostProcessor` 本身是在更早的阶段由容器特殊处理的,它不参与对自己的后处理,否则就鸡生蛋了。

---

## 14.5 AOP:面向切面编程(Spring 最"魔法"的部分)

AOP(Aspect-Oriented Programming,面向切面编程)要解决的问题很实在:日志、事务、鉴权、监控这些"横切关注点"(cross-cutting concern),散落在每个业务方法里,导致**代码重复 + 侵入业务**。

没有 AOP 时你每个方法都这么写:

```java
public Order createOrder(...) {
    long start = System.nanoTime();
    log.info("enter createOrder");          // 横切逻辑
    try {
        Order o = doCreate(...);
        log.info("exit createOrder cost={}", System.nanoTime() - start);
        return o;
    } catch (Exception e) {
        log.error("createOrder failed", e);  // 横切逻辑
        throw e;
    }
}
```

十个方法复制十遍。AOP 的做法:把这些横切逻辑抽成一个"切面",声明"在哪些方法的前后织入",业务方法恢复原样。

### 核心概念(四件套)

- **Join Point(连接点)**:程序里可以被增强的点,Spring AOP 里基本就是"方法执行"。
- **Pointcut(切点)**:你要增强的是**哪些**连接点。用表达式描述,如 `execution(* com.x..*Service.*(..))` 表示"com.x 下所有 `*Service` 类的所有方法"。
- **Advice(通知)**:在连接点做什么。`@Around`(环绕,最灵活)、`@Before`、`@After`、`@AfterReturning`、`@AfterThrowing`。
- **Aspect(切面)**:切点 + 通知的组合,即"在哪儿、做什么"。

一个完整示例,做方法耗时统计:

```java
@Aspect                 // 这是个切面
@Component
public class TimingAspect {
    @Around("execution(* com.example..*Service.*(..))")   // 切点:所有 Service 方法
    public Object time(ProceedingJoinPoint pjp) throws Throwable {
        long start = System.nanoTime();
        try {
            return pjp.proceed();                         // 继续调原方法
        } finally {
            log.info("{}.{} cost {} ns",
                pjp.getTarget().getClass().getSimpleName(),
                pjp.getSignature().getName(),
                System.nanoTime() - start);
        }
    }
}
```

### AOP 的实现原理(重点,决定你理解 @Transactional 为什么失效)

**Spring AOP 默认用动态代理。** 回到 14.4 生命周期第 6 步:容器在 `postProcessAfterInitialization` 检查这个 Bean 是否需要被切面增强;如果需要,**返回一个代理对象放进容器,原始对象被代理包装**。此后你通过 `@Autowired` 拿到的、通过 `getBean` 拿到的,都是这个代理。

调用链变成:你调 `service.createOrder(...)` → 实际调代理的方法 → 代理先执行切面的 `@Around`(计时/开事务)→ 再转发给原始对象的真实方法 → 切面的 `@After` 收尾。原始对象对你是透明的。

代理的两种方式:

1. **JDK 动态代理(基于接口)**:要求目标类实现了接口。`Proxy.newProxyInstance(classLoader, interfaces, invocationHandler)` 生成一个**实现了这些接口的代理类**,方法调用全部转发给 `InvocationHandler.invoke(...)`。注意:它生成的是"接口的实现",不是目标类的子类,所以**只能代理接口里声明的方法**。
2. **CGLIB(基于类)**:要求目标类**非 final、方法非 final**。它通过 ASM 字节码生成目标类的一个**子类**,重写方法,在子类方法里插入增强逻辑再 `super.xxx()` 调父类(原始)方法。

> 【思考】为什么有接口用 JDK 代理、没接口用 CGLIB?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:因为 **JDK 动态代理的 API 限制——`Proxy.newProxyInstance` 只能为一组接口生成实现类**,它压根不碰目标类的字节码;而 CGLIB 通过生成目标类的**子类**来代理任何非 final 类。两者能力边界不同,Spring 按"有没有接口"选。

**代码锚点——JDK 代理的签名限制**:

```java
// Proxy 的 API:第二个参数是接口数组,不是类
Object proxy = Proxy.newProxyInstance(
    target.getClass().getClassLoader(),
    new Class[]{ OrderService.class },   // 必须传接口
    (Object p, Method m, Object[] args) -> {
        System.out.println("before");
        return m.invoke(target, args);   // 转发
    });
// 如果 OrderServiceImpl 没实现任何接口,这里就传不了"类",只能报 IllegalArgumentException
```

所以:目标类实现了接口 → JDK 代理能上(生成接口实现);没实现接口 → JDK 代理无能为力 → 退而用 CGLIB 生成子类。

**为什么 Spring Boot 2.0 之后默认优先 CGLIB?** 因为 CGLIB 能代理**类**(不只是接口),于是 `@Transactional` 标在类上、或标在"没接口的方法"上也能生效,行为更一致;而 JDK 代理只能代理接口方法,类上特有的 public 方法(非接口声明)不会被增强。代价:CGLIB 要求类和方法非 final(否则没法生成子类重写)。

**Go 对照**:Go 没有代理机制。要做横切逻辑,要么**显式**写中间件链(gin 的 `r.Use(logger(), auth())`,每个 handler 都过一遍),要么用代码生成(如 ent 的 hook、`go:generate` 生成包装)。关键区别:**Go 的 middleware 是显式的、你能 `go to definition` 跳到的**;Spring 的 AOP 藏在注解后,你调 `service.method()` 时完全感知不到中间有个代理。这是"声明式简洁"换来的"调用链不透明"。

**更深一层**:JDK 代理 vs CGLIB 不是"技术进步"的关系,是"两条互补的技术路线"。JDK 代理基于接口(干净、无侵入字节码),CGLIB 基于子类(强、但要求类可继承)。Spring 早期默认 JDK 代理(有接口就走接口),Spring Boot 2.0 把 `spring.aop.proxy-target-class` 默认设为 `true`(即优先 CGLIB),让行为统一。你只要记住一条铁律:**final 类 / final 方法无法被 CGLIB 代理,事务、缓存、异步在它身上全部失效**——这是后面 @Transactional 失效场景二的根。
</details>

### @Transactional 失效的经典场景(本章炸药,呼应 01 章 1.8)

`@Transactional` 就是靠 AOP 代理实现的。理解了"代理才有增强逻辑",下面四个失效场景的根因就一句话:**只有通过代理对象进入的方法才走增强;凡是绕过代理直接调原始对象,增强全无。**

**场景一:类内部方法自调用(最高频)**

```java
@Service
public class OrderService {
    public void batchPay(List<Long> ids) {
        for (Long id : ids) {
            this.pay(id);     // ❌ this 是原始对象,不是代理,@Transactional 失效
        }
    }
    @Transactional
    public void pay(Long id) { ... }
}
```

`this` 指向原始对象(容器注入的是代理,但 `this` 是 Java 关键字指向自身),`this.pay()` 直接调原始方法,**绕过代理**,事务逻辑不执行。根因:`@Transactional` 的增强在代理对象的 `pay` 里,你用 `this` 调等于跳过了代理。

**场景二:方法是 `private` 或 `final`**

`@Transactional` 标在 `private` 方法上,Spring 根本不会为它建代理增强(private 方法不会被代理暴露);标在 `final` 方法上,CGLIB 无法重写,增强也失效。

**场景三:异常被 catch 吞掉,或抛了 checked 异常**

Spring 的 `@Transactional` **默认只在抛出 `RuntimeException` 和 `Error` 时回滚**。如果你:

```java
@Transactional
public void pay(Long id) {
    try {
        doPay(id);
    } catch (Exception e) {
        log.error("fail", e);   // ❌ 吞了异常,事务认为成功,提交
    }
}
```

catch 住没往外抛 → 代理的 `@AfterThrowing` 收不到异常 → 提交。或者你抛的是 checked 异常(如 `IOException`)且没配 `rollbackFor`,Spring 也提交。

**场景四:想用自调用触发事务**

就是场景一的变体——你想在一个非事务方法里调本类的事务方法,结果事务不生效。

**修复对照**:

| 场景 | 根因 | 修复 |
|---|---|---|
| 自调用 | `this` 绕过代理 | 把被调方法拆到另一个 Bean;或注入自己 `self` 再 `self.pay(id)`;或用 `ApplicationContext.getBean(Self.class)`;或上 AspectJ 编译期织入 |
| private/final | 代理无法覆盖 | 改成 `public` 且非 final |
| 吞异常/checked | 代理收不到回滚信号 | 抛出 `RuntimeException`,或 `@Transactional(rollbackFor = Exception.class)` |
| 自调用事务 | 同自调用 | 同自调用修复 |

最干净的修复通常是**拆 Bean**:把 `pay` 抽到 `PaymentService`,`OrderService` 注入 `PaymentService` 后调用,走的就是代理了。

> 【思考】为什么 Go 没有"@Transactional 失效"这种问题?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:因为 Go 的事务是你**显式**写的,调用关系完全显式,没有代理、没有"被绕过的增强"。Spring 用代理换来了"声明式简洁",代价是"代理边界"这个心智负担。

**代码锚点——Go 的显式事务**:

```go
func (s *OrderService) Pay(ctx context.Context, id int64) error {
    tx, err := s.db.BeginTx(ctx, nil)   // 显式开事务
    if err != nil {
        return err
    }
    defer tx.Rollback()                 // 显式默认回滚
    if err := s.doPay(tx, id); err != nil {
        return err                      // 返回错误 => defer 的 Rollback 执行
    }
    return tx.Commit()                  // 显式提交
}
```

你看,事务的"开/提交/回滚"全是你手写的、看得见的。不存在"某个注解偷偷生效",也不存在"`this.doPay` 绕过代理导致事务没开"。调用关系就是字面意思:你调 `s.doPay(tx, id)`,传的就是带事务的 `tx`。

**对比 Spring**:`@Transactional` 的"开事务"藏在代理里,只有"通过代理进入的方法"才触发。于是 `this.method()`、`private` 方法、`final` 方法、吞异常——全都绕过了代理,事务静默失效。这在 Go 里不可能发生,因为 Go 根本没有这层"隐式增强"。

**更深一层**:这是本章最值得记的一句话——**声明式能力的代价,是你要理解它的边界**。Spring 用 AOP + 注解把"事务/缓存/异步/鉴权"变成了"加个注解就好",极大降低了样板代码;但每省下的一行样板,都转移成了"你必须知道代理在哪、什么时候被绕过"的认知成本。Go 把成本摊在明面(每次手写事务),Spring 把成本藏进黑箱(理解代理机制)。没有谁更"对",但作为从 Go 过来的人,你第一次遇到 `@Transactional` 不回滚时,第一反应应该是:"是不是又绕过代理了?"——而不是去查数据库配置。这恰恰是 01 章 1.8 埋的雷,这里正式引爆。
</details>

**问题 8:** `@Async`(异步)失效是不是也是同一个原因?

是。 `@Async` 也靠代理,所以自调用、private、final 同样会让它失效,排查思路和 `@Transactional` 一模一样。记一个规律:**凡是带 `@` 且"自动生效"的 Spring 能力(事务、缓存、异步、重试),本质都是 AOP 代理,失效场景高度雷同。**

---

## 14.6 循环依赖:Spring 怎么做到的(以及为什么构造器注入不行)

循环依赖:A 依赖 B,B 依赖 A。 naive 地想,这俩谁都造不出来。但 14.3 说过,singleton + 字段注入时它能跑。秘密在"三级缓存"。

### 三级缓存机制

- **一级缓存 `singletonObjects`**:成品 Bean(完全初始化好的)。
- **二级缓存 `earlySingletonObjects`**:早期暴露对象(半成品,已实例化但还没填完属性,可能已被代理)。
- **三级缓存 `singletonFactories`**:`ObjectFactory`(能生成早期引用的工厂,**关键在它能决定返回原始对象还是 AOP 代理**)。

**流程(以 A↔B 为例)**:

1. 创建 A → 反射 `new A()` 空壳 → 把"能返回 A 早期引用的工厂"放进**三级缓存**。
2. 填 A 的属性,发现要 B → 去拿 B。
3. 创建 B → `new B()` 空壳 → B 的工厂进三级缓存。
4. 填 B 的属性,发现要 A → 从三级缓存拿 A 的工厂,调 `getObject()` 得到 A 的**早期引用**(若 A 需要被代理,这一步就生成 A 的代理,并放进二级缓存)。
5. B 拿到 A 的早期引用,属性填完 → B 初始化完 → B 进一级缓存。
6. 回到 A,把 B 填进去 → A 初始化完 → A 进一级缓存,清掉二三级缓存里的 A。

注意第 4 步:如果 A 上有 `@Transactional`,容器在"取 A 早期引用"时就生成了**A 的代理**,B 手里拿到的也是这个代理。这样 B 持有的 A 和最终容器里的 A(代理)是同一个,一致性有保证。

> 【思考】为什么需要三级缓存,两级不行吗?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:两级(只保留"原始早期对象")不够,因为解决不了"早期引用到底要不要是 AOP 代理"这个问题。三级缓存存的是**工厂**,把"返回原始对象还是代理对象"的决定推迟到**真正需要早期引用那一刻**才做,且只做一次,保证全程一致。

**为什么两级会翻车?**

假设只有二级缓存,里面直接放 A 的**原始空壳**(没有代理)。流程走到"B 要 A"时,从二级缓存拿到**原始 A**(不是代理)。于是 B 的字段 `a` 指向原始 A。但 A 本身有 `@Transactional`,容器在第 6 步最终要放进一级缓存的是**A 的代理**。结果:**容器里是代理 A,而 B 手里是原始 A**——同一个 Bean 在系统里出现了"两个不一样的对象",B 调用 `a.method()` 走的是原始对象,**事务不生效**。这就是不一致。

三级缓存怎么解?三级缓存放的不是对象,是工厂 `() -> getEarlyBeanReference(A)`。当 B 需要 A 时,调工厂:工厂内部会跑 `SmartInstantiationAwareBeanPostProcessor`(包括 AOP 的 `AbstractAutoProxyCreator`),**此时才决定**——A 需要代理就生成代理,不需要就返回原始。生成后把结果(代理)移入二级缓存,后续任何人再来取都拿到同一个(同一个代理)。这样 B 手里的 A 和最终一级缓存里的 A 是**同一个代理**,一致性保住。

**代码锚点——工厂延迟决定代理(简化自 AbstractAutowireCapableBeanFactory)**:

```java
// 三级缓存里存的是这样的 lambda
singletonFactories.put(beanName, () -> {
    // 只有在"别人要早期引用"时才调用,决定是否包代理
    return getEarlyBeanReference(beanName, mbd, bean);
});
// getEarlyBeanReference 会遍历 SmartInstantiationAwareBeanPostProcessor,
// 其中 AbstractAutoProxyCreator 若有切面匹配,则返回代理
```

**更深一层**:三级缓存不是"多一级更牛",而是"用工厂把代理决策延迟并去重"。它的存在暴露了一个事实:Spring 的循环依赖解决**是在"保证 AOP 一致性"这个硬约束下设计的**。如果 Spring 不支持 AOP,两级缓存就够。但 AOP 要求代理和原始对象一一对应,所以必须有一层"按需生成且只生成一次"的工厂。理解这点,你就理解了为什么 Spring 宁可多维护一个缓存也不简化——因为它要同时兑现"能解循环依赖"和"AOP 代理一致"两个承诺。

顺带:这也解释了为什么构造器注入的循环依赖解不了——构造器注入没有"先 new 空壳再填属性"的空隙,工厂根本没机会被注册,见下一个【思考】。
</details>

> 【思考】为什么构造器注入的循环依赖 Spring 解决不了?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:构造器注入要求"构造 A 前必须先把 A 的所有构造参数(含 B)备齐",但构造 B 又要求先把 A 备齐——构造阶段就死锁(`BeanCurrentlyInCreationException`)。三级缓存依赖"**先实例化空壳、再填充属性**"之间的空隙来暴露早期引用,而构造器注入把"构造"和"实例化"合为一步,没有这个空隙。

**展开对比**:

- **字段/setter 注入**:`new A()`(空壳)→ 注册工厂进三级缓存 → 填属性时才去要 B。空壳存在期间,工厂已经就位,别人可以取 A 的早期引用。**空隙 = 实例化之后、属性填充之前。**
- **构造器注入**:`new A(B b)`——构造 A 的同一刻就必须有 B。要 B 就得先 `new B(A a)`,要 A 又得先构造 A。两者互相等待,Spring 在尝试创建 A 时发现"A 正在创建中"又来要 A,立刻抛 `BeanCurrentlyInCreationException`。根本没有"先造空壳"的机会,三级缓存无从介入。

**代码锚点**:

```java
@Service
public class A { public A(B b) {} }   // 构造即需 B
@Service
public class B { public B(A a) {} }   // 构造即需 A
// 启动即失败:
// BeanCurrentlyInCreationException:
// Requested bean is currently in creation: Is there an unresolvable circular reference?
```

**更深一层**:Spring 选择"让构造器注入的循环依赖报错",是一种**有意的取舍**——循环依赖是设计坏味道,字段注入用"空壳+回填"把它掩盖成运行时隐患,而构造器注入在启动期就把它顶出来。Spring 推荐构造器注入,正是因为它"fail fast":**报错比静默强**。所以结论反直觉但重要:**字段/setter 能扛循环依赖不是优点,是掩盖;构造器不能扛才是健康信号**。遇到构造器循环依赖,正确动作是改设计(拆类、抽接口、把一方改成 `@Lazy` 延迟注入),而不是换回字段注入。
</details>

> 【思考】Go 有循环依赖吗?为什么?它和 Java 的循环依赖是一回事吗?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:Go 也有"循环",但分两层,且都和 Java 的 Bean 循环依赖不是一回事。Go 的**包级循环导入(import cycle)在编译期直接报错**(Go 禁止包循环依赖);而 Go 的**对象**可以互相持有对方指针(运行期完全合法)。Java 的循环依赖是"Bean 创建顺序"问题(构造期),Go 的循环依赖是"包初始化顺序"问题(编译期)——两者机制不同,但都靠"编译/启动期报错"避免运行期惊喜。

**展开**:

Go 的包循环依赖:

```go
// package a 导入 b,package b 又导入 a —— 编译直接报错:
// import cycle not allowed
```

Go 编译器禁止 import cycle,根本原因是 Go 的包初始化顺序必须确定(按依赖拓扑排序),循环就排不出来,会引发初始化死锁隐患。所以 Go 在编译期就掐死。

但 Go 的对象可以互相引用,运行期完全没问题:

```go
type A struct{ b *B }
type B struct{ a *A }
func main() {
    a := &A{}; b := &B{}
    a.b = b; b.a = a   // 互相持有指针,合法,因为没有"构造时递归 new"
}
```

为什么合法?因为 Go 里 `&A{}` 只是分配一个结构体(字段默认零值,`b` 是 `nil` 指针),不触发"B 的构造"。之后你手动 `a.b = b` 把指针填上,不存在"构造 A 必须先构造 B"的递归。指针本身不触发任何构造。

**对比 Java**:Java 的循环依赖是"Bean 创建顺序"——Spring 想 `new A(repo)` 但 repo 又要 A,是构造/装配期的递归。它和 Go 的包循环导入完全不是一类问题:

| | Java 循环依赖 | Go 循环依赖 |
|---|---|---|
| 本质 | Bean 创建顺序(构造期) | 包初始化顺序(编译期) / 对象指针互引(运行期合法) |
| 何时暴露 | 启动期(或构造器注入启动即报错) | 编译期(import cycle 直接报错) |
| 对象互相引用 | 受限于"构造递归" | 完全合法(指针不触发构造) |

**更深一层**:两者都用"尽早报错"来避免运行期惊喜,但报错的层面不同——Go 在编译期(包级),Java 在启动期(Bean 级)。这也呼应了全书的基调:Go 把越多东西推到编译期,Spring 把越多东西推到运行期。你作为 Go 老哥,初见 Java 循环依赖会觉得"这还能启动?",是因为你习惯了"编译期就枪毙";Spring 的世界里,很多错要等容器启动才显形,所以**看启动日志**是基本功。
</details>

---

## 14.7 ApplicationContext:容器本身

前面一直在说"容器",它就是 `ApplicationContext`(应用上下文)。它的父亲是 `BeanFactory`(基础容器),区别值得记:

| | `BeanFactory` | `ApplicationContext` |
|---|---|---|
| 实例化策略 | 懒加载(用时才造 Bean) | 启动即预实例化 singleton(非懒加载) |
| 国际化(MessageSource) | 无 | 有 |
| 事件发布(ApplicationEvent) | 无 | 有 |
| AOP 集成 | 需手动 | 自动 |
| 环境/配置(Environment) | 弱 | 强 |

日常你用的 `SpringApplication.run(Xxx.class)` 返回的,就是个 `ApplicationContext`(具体是 `AnnotationConfigServletWebServerApplicationContext` 之类)。**99% 的场景你只跟 `ApplicationContext` 打交道。**

**问题 9:** 懒加载和预实例化的取舍是什么?

`BeanFactory` 懒加载省启动时间,但第一个请求访问某个 Bean 时才造,可能把创建开销(和创建失败)推到请求期。`ApplicationContext` 启动就把所有 singleton 造好,启动慢一点,但**启动失败 = 问题早发现**,且请求期零创建开销。Web 服务基本都选后者——你绝不想用户第一次请求时才发现某个 Bean 装配错了。

容器的启动流程(简述):加载配置(注解扫描 / XML)→ 实例化 `BeanFactory` → 注册 `BeanDefinition` → 通过 `BeanPostProcessor` 处理每个 Bean → 预实例化非懒加载 singleton。

**怎么查看容器里有哪些 Bean(排错利器,呼应 00 章卡点五)**:

```java
@Autowired
private ApplicationContext ctx;

public void printBeans() {
    for (String name : ctx.getBeanDefinitionNames()) {   // 列出所有 Bean 名
        System.out.println(name);
    }
}
```

更实用的是 Actuator(00 章讲过,这里正式对接):

- `/actuator/beans`:列出容器里所有 Bean 及其类型、来源(哪个 @Configuration 注册的)。
- `/actuator/conditions`:告诉你哪些自动配置类匹配了、哪些没匹配、为什么没匹配——排查"我那个 @Configuration 怎么没生效"的核武器。
- `--debug` 启动:打印完整自动配置决策报告。

> 【思考】Spring 容器和 Go 的 `wire` 生成的 `Initialize` 函数,本质区别是什么?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:`wire` 生成的是**一段编译期确定、显式的构造代码**(如 `ctx := NewApp()`);Spring 容器是**运行时扫描 classpath、反射创建、动态装配**的对象池。前者"代码即真相",后者灵活但需要工具恢复可观测性。这正是 00 章卡点五那张对照表的浓缩。

**代码锚点——wire 的产物是一段普通代码**:

```go
// wire_gen.go(编译期生成,你可直接读)
func InitializeApp() *App {
    db := NewDB()
    repo := NewOrderRepository(db)   // 显式
    svc := NewOrderService(repo)     // 显式
    return NewApp(svc)               // 所有依赖一眼可见
}
```

对比 Spring:你写的 `@Component` + `@Autowired`,运行时才被容器解析成等价的装配。`InitializeApp()` 是确定性的、可单步调试的;`ApplicationContext` 的装配是动态的、依赖 classpath 上有什么 jar。

**差异的具体后果**:

1. **看依赖图**:Go 打开 `wire_gen.go`;Spring 要看 `/actuator/beans` 或启动日志。
2. **出错时机**:Go 漏依赖 → 编译失败;Spring 漏 Bean → 启动失败,或更糟(如 00 章的 `@Profile("test")` 误激活,启动成功却注入了内存实现)。
3. **灵活性**:Spring 换实现只换 jar / 改注解;Go 要重新 `wire` 生成。

**更深一层**:这不是"谁更好",是两种工程哲学。wire 把装配成本付在编译期,换来"代码即真相、无黑箱、启动快";Spring 把装配付在运行期,换来"插件化、实现可替换、无需重编译"。你接手 Java 项目时,最大的不适应就是"看不到 `new` 在哪儿"——但一旦你熟练用 `/actuator/beans` 和 `--debug`,Spring 的可观测性其实比 wire 还强(因为运行时能告诉你"实际注入了哪个实现、为什么")。关键是:别再找 `new` 了,去容器里看。
</details>

**问题 10:** 能不能拿到原始对象(绕过代理)来调试?

能,但一般用不上。如果你怀疑某个 Bean 被代理了,看它的类名:`getBean` 拿到的对象 `getClass().getName()` 如果带 `$Proxy`(JDK 代理)或 `$$EnhancerBySpringCGLIB`(CGLIB 代理),说明它是代理。这招在排查 `@Transactional` 失效时极有用——14.8 会用到。

---

## 14.8 实战:一个完整的"魔法"排查案例

光讲原理不过瘾,来一个你绝对会遇到的真实场景。

**现象**:加了 `@Transactional` 的方法,异常后数据**没回滚**——订单状态被改成了 PAID,但下游扣库存失败了,数据库里订单已经是 PAID,库存没减,**数据不一致**。

**排查过程**:

第一步,先看是不是自调用。打开 `OrderService`:

```java
@Service
public class OrderService {
    public void placeOrder(OrderCmd cmd) {        // 非事务
        this.doPlace(cmd);                        // 自调用!
    }
    @Transactional
    public void doPlace(OrderCmd cmd) {           // 事务在这
        orderRepo.save(cmd.toOrder());            // 写订单
        inventoryClient.deduct(cmd.items());      // 抛异常
    }
}
```

`placeOrder` 调 `this.doPlace(cmd)`,`this` 是原始对象,绕过代理,`@Transactional` 从未开启。异常发生时压根没有事务,`orderRepo.save` 直接提交了。

第二步,确认异常类型与是否被吞。即使不是自调用,也要看:异常是 `RuntimeException` 吗?有没有被 `try/catch` 吞掉?本例是 `RuntimeException` 且没吞,所以排除场景三。

第三步,看方法是不是 `private`/`final`。`doPlace` 是 `public` 非 final,排除场景二。

第四步,用 Actuator 确认 Bean 是不是代理(呼应 14.7):

```java
System.out.println(orderService.getClass().getName());
// 如果打印 OrderService 而不是 OrderService$$EnhancerBySpringCGLIB$$...
// 说明它根本没被代理 => @Transactional 一定不生效
```

本例如果是自调用,`getBean(OrderService.class)` 拿到的其实是代理,但**调用发生在 `this`(原始对象)上**,所以代理没被用到——类名检查只能证明"代理存在",不能证明"调用走了代理",所以自调用要靠读代码发现。

**根因**:自调用绕过代理,事务增强未触发,`save` 在自动提交的连接上直接落库。

**修复(选最干净的)**:把 `doPlace` 拆到独立的 `PaymentService`,`OrderService` 注入 `PaymentService` 后调用,走代理:

```java
@Service
public class OrderService {
    private final PaymentService paymentService;
    public OrderService(PaymentService p) { this.paymentService = p; }

    public void placeOrder(OrderCmd cmd) {
        paymentService.doPlace(cmd);   // ✅ 走代理,事务生效
    }
}

@Service
public class PaymentService {
    @Transactional
    public void doPlace(OrderCmd cmd) { ... }
}
```

**教训(三条,记牢)**:

1. `@Transactional` 的自调用失效是头号坑,凡是"一个非事务方法调本类事务方法",先怀疑它。
2. 排错顺序:看自调用 → 看异常类型/是否被吞 → 看 `private`/`final` → 用 `getClass().getName()` 确认代理。
3. **这整章的浓缩**:Spring 的声明式能力 = AOP 代理。代理在,能力在;绕过代理(自调用 / final / private),能力消失。你从 Go 过来,第一反应该是"是不是又绕过代理了",而不是去查数据库。

**问题 11:** 如果打死不想拆 Bean,怎么让自调用也能用事务?

三种绕过法(都不如拆 Bean 干净,但应急可用):① 注入自己 `self` 然后 `self.doPlace(cmd)`(自己也是代理);② `ApplicationContext.getBean(OrderService.class).doPlace(cmd)`;③ 换 AspectJ 编译期织入(`spring-boot-starter-aop` + `@EnableLoadTimeWeaving` 或编译期织入),它直接改字节码,不依赖代理,自调用也生效。生产环境首选拆 Bean,AspectJ 留给实在拆不动的老代码。

---

## 14.9 本章核心结论

如果这一章你只看这一段,看完应能复述 Spring 的"魔法"全貌:

1. **Spring 容器本质就是 `Map<String, Object>` + 一套基于注解的填充规则**——Bean 是普通 `new` 不出来的、被容器管理的对象。
2. **IoC 是原则,DI 是实现手段**;Spring 选 DI 而非 Service Locator,因为 DI 不侵入业务代码。
3. **构造器注入是默认答案**:不可变、可测试、启动即失败、天然防循环依赖;字段注入最危险。
4. **Bean 默认 singleton 且必须无状态**——在单例里放请求级可变状态(如那个 `cache`)会并发错乱,这是 01 章缓存 bug 的根。
5. **Bean 生命周期 8 步的核心**:第 2 步 DI、第 5 步 `@PostConstruct`、第 6 步 AOP 代理生成,顺序决定了能力何时可用。
6. **AOP 默认动态代理**:有接口用 JDK 代理、没接口用 CGLIB;`@Transactional`/`@Cacheable`/`@Async` 全是代理,失效根因都是"绕过代理"。
7. **三级缓存解决 singleton 循环依赖**:靠"先实例化空壳、再填属性"的空隙暴露早期引用;构造器注入没这空隙,所以循环依赖直接报错(这反而是好事)。
8. **Spring 的运行时魔法 = 拿编译期确定性换运行时灵活性**,代价是你要用 Actuator / `--debug` 恢复可观测性;Go 的 wire 把真相留在编译期。

---

## 14.10 深度思考题

### 题 1:你说"Spring 容器就是 Map<String, Object>"。那这个 Map 的 key 是什么?同名 Bean 会怎样?两个不同包的同名类呢?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:key 默认是 **beanName**(类名首字母小写,如 `OrderService` → `orderService`)。同名 Bean 默认冲突,抛 `BeanDefinitionOverrideException`(除非显式允许覆盖);不同包的同名类,只要 beanName 不同就相安无事,用 `@Qualifier` 区分。

**展开**:

Spring 给每个 Bean 一个名字,默认规则是"类名首字母小写"。于是:

```java
@Service
public class OrderService {}     // beanName = "orderService"

@Service
public class OrderService {}     // 另一个同名类(不同包) → 也想要 "orderService"
// 默认: BeanDefinitionOverrideException: Conflicting bean definition
```

冲突时你有两个解法:

```java
@Service("mysqlOrderService")        // 显式改名
public class OrderService {}

@Autowired
@Qualifier("mysqlOrderService")      // 注入时指定要哪个
private OrderService svc;
```

如果用 `@Bean` 方法,方法名就是 beanName:

```java
@Bean
public OrderRepository orderRepository() { ... }   // beanName = "orderRepository"
@Bean("pgOrderRepository")                         // 显式
public OrderRepository pgRepo() { ... }
```

**不同包同名类**:只要 beanName 不同(一个默认 `orderService`,另一个你显式 `@Service("legacyOrderService")`),完全 OK,`@Qualifier` 区分即可。注意:如果你依赖的是接口 `OrderService` 且有两个实现,Spring 会按 beanName 匹配注入点上的 `@Qualifier`,没有 `@Qualifier` 且有多个实现就 `NoUniqueBeanDefinitionException`。

**更深一层**:这个 Map 的 key 是"名字"而非"类型",这点很关键——Spring 允许同类型多个 Bean(靠名字区分),也允许一个名字对应一个 Bean 但被多个类型引用(接口 + 实现)。这比 wire 的"类型即真相"灵活,但也意味着"注入哪个"取决于名字匹配规则,出错时你得去查 beanName 而非类名。这正是可观测性工具(看 beanName 列表)存在的理由。
</details>

### 题 2:一个 `@Service` Bean 的构造器里调用了另一个 `@Service`(字段注入)的方法,会怎样?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:构造器执行时,另一个 Bean 可能还没走完属性填充(它的 `@Autowired` 字段还是 null)——于是你调用的方法内部一旦访问自己的字段,就 NPE 或拿到半成品。这是"**构造器里不要依赖其他 Bean 的业务方法**"的原因;要调别的 Bean,等 `@PostConstruct`(那时所有依赖已注入)。

**代码锚点**:

```java
@Service
public class A {
    @Autowired private B b;                 // 字段注入
    public A() {
        // ❌ 构造器里调 b 的方法:此时 b 还是 null(字段还没填)
        b.initSomething();                  // NullPointerException!
    }
}

@Service
public class B {
    @Autowired private C c;                 // c 也还没填
    public void initSomething() { c.work(); }  // 即使 b 非 null,c 也还是 null
}
```

**为什么?** 回到 14.4 生命周期:A 的构造器在第 1 步(实例化),此时 `b` 字段尚未填充(第 2 步)。即使 Spring 先造了 B,B 的字段 `c` 也还没填。所以你在 A 构造器里碰 B,触发的连锁访问里全是 null。

**正确写法**:

```java
@Service
public class A {
    private final B b;
    public A(B b) { this.b = b; }            // 构造器只接依赖,不调业务
    @PostConstruct
    public void init() {                     // ✅ 此刻 b 已注入,b.c 也已注入
        b.initSomething();
    }
}
```

**更深一层**:这条规则的本质是"**依赖注入完成前,Bean 不完整**"。构造器注入比字段注入安全,正是因为构造器拿到的依赖已经齐了(构造器参数由容器填好才调构造器),所以构造器里用 `this.repo` 是安全的;但构造器里调**别的 Bean 的方法**仍然危险,因为那个 Bean 可能还在初始化中。所以铁律:**构造器只存依赖,`@PostConstruct` 才做跨 Bean 的初始化协作。**
</details>

### 题 3:为什么 Spring Boot 2.0 之后默认用 CGLIB 代理而不是 JDK 动态代理?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:因为 CGLIB 能代理**类**(不只是接口),于是 `@Transactional` 标在类上、或标在"没接口声明的方法"上也能生效,行为更一致;代价是 `final` 类 / `final` 方法无法被代理(增强失效)。

**展开**:

Spring 早期(及纯 Spring、非 Boot)默认优先 JDK 动态代理——目标类实现了接口就走 JDK 代理。问题:JDK 代理只为接口生成实现,**目标类自己特有的 public 方法(不在接口里声明的)不会被代理**。如果你的 `@Transactional` 标在一个没接口的类的方法上,或标在类本身(JDK 代理只看接口方法),增强可能不生效,行为诡异难查。

Spring Boot 2.0 起把 `spring.aop.proxy-target-class` 默认设为 `true`,即**优先 CGLIB**。CGLIB 生成目标类的子类,重写所有非 final 方法,所以无论有没有接口、方法是不是接口声明的,都能被增强。`@Transactional` 一致性大幅提升。

**代码锚点——final 方法的代价**:

```java
@Service
public class OrderService {
    @Transactional
    public final void pay() { ... }   // ❌ final,CGLIB 无法重写 => 事务失效
}
// 去掉 final 才生效;这是 Spring Boot 默认 CGLIB 后的新坑:
// "加了注解怎么不生效?" 先检查是不是 final
```

**更深一层**:默认 CGLIB 是"用更强的代理能力换一致性",但它把"final 类/方法无法代理"这个限制推到了台前。Go 老哥不会遇到这个(Go 没有代理),但转到 Spring 后,**看到 `@Transactional` 失效,新 checklist 第一条应是:方法是不是 `final`?类是不是 `final`?** 这也是为什么本书反复强调:Spring 的声明式能力全是代理,而代理有边界。
</details>

### 题 4:如果你要自己写一个 Mini-Spring(只支持 `@Component` + `@Autowired` + 单例),你会怎么做?

<details>
<summary><b>参考答案</b></summary>

**直接答案**:极简实现四步——扫类路径找 `@Component` → 反射实例化存 Map → 反射注入 `@Autowired` 字段 → 处理循环依赖(三级缓存思路)。这是一道"把知识变能力"的好题,呼应你"能自己造工具"的目标。

**代码骨架(伪实现,展示思路)**:

```java
public class MiniContext {
    private final Map<String, Object> beans = new HashMap<>();   // 那就是这个 Map

    public void scan(String basePackage) {
        // 1. 扫类路径,找带 @Component 的类(真实要用 ASM/类路径扫描库)
        for (Class<?> clazz : findComponentClasses(basePackage)) {
            String name = lowerFirst(clazz.getSimpleName());
            Object instance = clazz.getDeclaredConstructor().newInstance();  // 2. 反射 new
            beans.put(name, instance);
        }
        // 3. 注入 @Autowired 字段
        for (Object bean : beans.values()) {
            for (Field f : bean.getClass().getDeclaredFields()) {
                if (f.isAnnotationPresent(Autowired.class)) {
                    f.setAccessible(true);
                    f.set(bean, beans.get(lowerFirst(f.getType().getSimpleName())));  // 从 Map 取
                }
            }
        }
    }
}
```

**这一步的坑(对应本章知识点)**:

- 上面这段是**字段注入版**,没有处理循环依赖(A↔B 时,B 的字段填 A,但 A 还没注入完 B,会拿到半成品)。要支持循环依赖,得加三级缓存:实例化后先放"早期引用工厂",填属性时从工厂取。
- 真实 Spring 用 **ASM 读字节码**找注解(而不是 `Class.forName`,因为后者会触发类加载和静态初始化,慢且有副作用)。Mini 版用反射扫是图省事。
- 真实 Spring 区分 BeanDefinition、lazy、scope、生命周期回调——Mini 版全省了,但"核心魔法"(Map + 反射实例化 + 反射注入)就这三行。

**更深一层**:写一遍 Mini-Spring,你会彻底理解"容器 = Map + 填充规则"不是比喻,是字面事实。你也会明白 Spring 为什么重——它要处理 scope、AOP、生命周期、条件装配、环境配置……这些全是"在 Map + 注入"之上的增量。等你第 15 章看自动装配,回头想这个 Mini 版,会发现自动装配不过是"更高级的扫描 + 条件注册 BeanDefinition"。自己造一遍,比读十篇博客都管用。
</details>

### 题 5(开放题,无标准答案):Spring 的"运行时魔法"值不值?如果让你在 Go 里实现同样的能力(声明式事务、统一切面),你会怎么做?

<details>
<summary><b>参考答案</b></summary>

这道题没有标准答案,给你几个 Go 视角的思路作锚点。

**Spring 值不值?**

值,但有前提。在"几十人协作、要插件化、要换实现不重编译"的大型项目里,运行时 DI + AOP 省下的样板代码和耦合成本,远大于"黑箱"的代价(而且有 Actuator 兜底)。在"小服务、要快、要可追踪"的场景里,wire 的编译期显式更香。所以值不值,取决于项目规模和你对"可追踪性"的估值。

**Go 里怎么做等价能力?**

- **声明式事务**:Go 没有代理,通常两种路。① **middleware/装饰器**:写一个 `Tx(h func(tx *sql.Tx) error) error` 包装函数,业务方法都收 `tx` 参数——显式但侵入签名。② **代码生成**:用 `go:generate` 给方法生成事务包装(类似 ent 的 hook)。③ **约定**:事务对象通过 `context.Context` 传递(`tx := txFromCtx(ctx)`),业务不显式传 `tx`,由框架在 middleware 里 `ctx = withTx(ctx)` 注入。这条路最接近 Spring 的"隐式",但依赖约定,且仍然显式可追。
- **统一切面(日志/鉴权/监控)**:Go 用 **middleware 链**(gin 的 `r.Use(...)`、gRPC 的 interceptor),这是显式的、你能跳到的。或者用 `go:generate` 在编译前给每个 handler 生成包装代码(把横切逻辑织进去)。

**结论**:Go 倾向于"显式但啰嗦",Spring 倾向于"声明但隐式"。Go 的等价物要么侵入 handler 签名(middleware/context),要么靠代码生成(hook/generate)。没有谁更"对",但作为从 Go 过来的人,你会更珍惜 Spring 的"加注解就好",也会更警惕它的"代理边界"——这正是本章反复锤的那条:声明式能力的代价,是你要懂它的边界。

**更深一层**:这道题其实是全书的元问题——Java 和 Go 在"显式 vs 隐式"上的取舍。你学 Java 不是抛弃 Go 的价值观,而是把"显式可追踪"当成尺子,去量 Spring 的"隐式简洁"到底付出了什么。等你第 22 章回看,会发现学 Java 最大的收获,是反过来把 Go 那些"理所当然的显式"理解得更深。
</details>

---

## 下一章预告

第 15 章讲 **Spring Boot 工程化**:自动装配原理(`@EnableAutoConfiguration` 怎么把一堆 starter 变成 Bean)、Starter 机制(为什么加个依赖就有 RedisTemplate/DataSource)、配置体系(`application.yml` + `@ConfigurationProperties` + Environment)、启动流程(`SpringApplication.run` 内部到底发生了什么)。

它是"Spring 核心"之上那层"约定优于配置"——你 00 章卡点五看到的 `@Profile("test")` 误注入、`/actuator/conditions` 排查,在第 15 章会从原理上彻底讲透:自动配置类为什么匹配 / 为什么没匹配,`@ConditionalOnMissingBean` 怎么被你的配置覆盖,以及"我的 `@Configuration` 为什么没生效"。

读完第 14 章的"容器 = Map + 填充规则",第 15 章会告诉你:这个 Map 是怎么被一堆 starter **自动填满**的。
