# 第 02 章（节选）　var与record

> 本篇来自《Go 程序员的 Java 修炼之路》第 02 章「第 02 章　Java 17 新特性与 Java 8 差异（现代 Java 长什么样）」。
> 返回：[第 02 章索引](./README.md)

## 02.1 `var`：局部变量类型推导（Java 10，JEP 286）

先看一段代码，这是 Java 8 和 Java 17 最容易被拿来做对比的例子：

```java
// Java 8
Map<String, List<Order>> ordersByUser = new HashMap<String, List<Order>>();

// Java 17
var ordersByUser = new HashMap<String, List<Order>>();
```

Go 程序员的第一反应一定是："哦，`var` 就是 Go 的 `:=` 嘛。"

**问题 1：** 真的吗？看这段代码，你觉得它在 Java 里能不能编译通过？

```go
// Go
x := 1
x = "hello"   // 编译错误：cannot use "hello" (untyped string constant) as int value
```

```java
// Java
var x = 1;
x = "hello";   // ?
```

答案是不行，报错信息是 `incompatible types: String cannot be converted to int`。

**这就是表面相似之下的第一个实质差别：Go 的 `:=` 是"声明 + 赋值"的组合记号，Java 的 `var` 只是"类型占位符"。**

Go 里 `x := 1` 这条语句做了三件事：声明变量、推导类型、赋值。Java 里 `var x = 1` 做的是：把 `var` 替换成右侧表达式的静态类型，然后走正常的声明流程。**推导发生在编译期，推导完就不存在了。** 你用 `javap` 看字节码，`var` 连个影子都没有。

所以类型仍然是**静态的**。这一点必须钉死，因为很多人（包括一些写 Java 多年的）会误以为 `var` 让 Java 变成了动态类型语言。

### 什么时候该用

判断标准只有一条：**右侧的类型信息，是否已经足够明显，明显到你写出来是冗余的。**

```java
// ✅ 好：右侧已经把类型写死了，左边再写一遍纯属废话
var list = new ArrayList<String>();
var br = new BufferedReader(new FileReader(path));
var entry = map.entrySet().iterator().next();

// ❌ 差：右侧看不出类型
var result = service.handle(req);        // handle 返回什么？看不出来
var data = load();                        // load 返回 Optional<User> 还是 User？
var x = getConfig().get("timeout");       // String? Integer? Object?
```

第二条判断标准（这是很多人忽略的）：**类型是核心信息时不要用 `var`。**

```java
// ❌ 糟糕：这里 long 是业务关键信息，读代码的人必须立刻看到
var amount = order.getAmount();

// ✅ 好
long amount = order.getAmount();
```

为什么？因为 `long` 和 `int` 的溢出边界完全不同，`double` 和 `BigDecimal` 的语义完全不同。你写 Go 的时候会给金额定义 `type Cent int64` 而不是裸 `int64`，道理是一样的 —— **让类型承担表达力**。`var` 会把这份表达力抹掉。

### `var` 用不了的地方

| 位置 | 能用 `var` 吗 | 说明 |
|---|---|---|
| 局部变量 | 能 | 必须有初始化器，不能 `var x;` |
| 增强 for 循环变量 | 能 | `for (var e : list)` |
| try-with-resources 资源变量 | 能 | `try (var conn = ds.getConnection())` |
| 字段 | 不能 | |
| 方法参数（普通方法） | 不能 | |
| 方法返回值 | 不能 | |
| 构造器参数 | 不能 | |
| lambda 参数 | **能**（Java 11，JEP 323） | 见下 |
| 数组初始化器 | 不能 | `var arr = {1, 2};` 非法 |

lambda 参数里那个"能"很反直觉，值得单独说：

```java
// Java 11 起合法，但你要用 var 就得所有参数都用
BiFunction<Integer, Integer, Integer> f = (var a, var b) -> a + b;

// 它的真正用途：给参数加注解
BiFunction<Integer, Integer, Integer> g = (@Nonnull var a, @Nonnull var b) -> a + b;
```

看到没？`var` 在这里不是用来省事的，是**用来给参数挂注解的** —— 因为 `(@Nonnull Integer a)` 这种写法在某些情况下有歧义（注解到底修饰类型还是参数）。Java 11 加这个东西纯粹是为了语法完整性，不是为了让你少打字。

> 【思考】为什么 Java 只给**局部变量**加 `var`，不给字段、方法参数、方法返回值加？
>
> 提示：想想 Java 的编译产物是什么，以及"方法签名"在 Java 里到底是什么东西。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为方法签名是二进制契约的一部分，而局部变量不是。**

展开讲三层。

**第一层：方法签名被写进了字节码，跨编译单元可见。**

你编译一个类：

```java
public class Foo {
    public String bar(String s) { return s; }
}
```

用 `javap -p Foo.class` 看：

```
public class Foo {
  public Foo();
  public java.lang.String bar(java.lang.String);
}
```

注意 `bar(java.lang.String)` —— 参数类型和返回类型**被完整地写进了 class 文件的方法描述符**（descriptor）里。这意味着：

- 别的模块编译的时候，可能压根没有你的源码，只有 `.class` 文件
- 别的模块要靠这个描述符生成 `invokevirtual` 指令
- JVM 在链接（resolution）阶段要靠这个描述符做校验

如果允许 `public var bar(var s)`，那编译器必须在编译 `Foo` 的时候就把 `var` 解析成具体类型 —— 而解析结果必须**稳定**。一旦你改了方法体里的一行代码导致返回类型变了，所有调用方即使重新编译也还好，但**不重新编译的调用方会拿到一个完全不同的二进制契约**，而且是静默的。

**这就是"二进制兼容性"的破坏，Java 对这件事的容忍度是零。**

Java 从 1.0 起就承诺：新版本 JDK 编译出来的代码，能跑在旧版本编译的库上；你升级一个 jar 的补丁版本，不应该需要重新编译整个系统。这个承诺是 Java 在企业市场立足的根本。方法签名是这个承诺的载体，所以它必须**显式、稳定、可从 class 文件读出**。

**第二层：字段也有类似的可见性问题。**

字段的类型同样写进 class 文件的字段描述符里，任何通过反射访问它的代码（`field.getType()`）都依赖这个类型。如果字段类型由初始化器推导，那加一个注解处理器、改一行代码，都可能让反射代码静默失效。

**第三层：那局部变量为什么就可以？**

因为局部变量**不出现在 class 文件的对外契约里**。方法内部的局部变量，只在 `Code` 属性内部使用，编译器推导完类型后，生成的字节码跟手写类型**完全一样**。局部变量表里存的是槽位（slot）和描述符，推导结果写死在那里，外部谁也看不见"这里原来写的是 `var`"。

也就是说：**局部变量的类型推导，是一个纯粹的编译期局部变换，不会泄漏到任何边界之外。** 这是一切的前提。

**代码锚点 —— 用 javap 自己验证：**

```bash
cat > Demo.java <<'EOF'
public class Demo {
    void f() {
        var a = "hello";       // 推导为 String
        var b = 42;            // 推导为 int
    }
    String g(String s) { return s; }
}
EOF
javac Demo.java
javap -p -c Demo.class
```

你会看到 `f()` 的字节码里，`a` 是 `java/lang/String` 类型、`b` 是 `int` 类型 —— 跟手写 `String a = "hello"; int b = 42;` 生成的东西一模一样。`var` 在字节码层面**不存在**。

**更深一层 — 这反映了两种语言对"边界"的定义：**

Go 的 `:=` 能做更激进的推导（比如 `a, b := f()`，类型由函数签名决定），是因为 Go 的编译单元是**包**，包与包之间的契约靠导出符号的接口表达，而这个契约在 Go 里同样是显式写在函数签名上的 —— 你也不能写 `func F(a := 1)`。**两种语言在同一个地方画了线：跨边界的契约必须显式，边界内部的可以推导。**

区别只在于 Java 的"边界"粒度更细（一个类文件就是一个可独立分发的契约单元），而 Go 的边界更粗（一个包）。所以 Java 连`private` 字段都不让你用 `var`，而 Go 的包级变量可以写 `var count = getCount()`（Go 里包级 `var` 的推导是允许的，因为它仍然不跨包泄漏）。

**一句话：能推导的范围，恰好等于"不被外部依赖的信息"的范围。** 这条规律你记下来，后面看到 Java 任何一个"为什么这个可以那个不行"的设计，都能用套。
</details>

### `var` 的真实坑

**坑一：`var` + 菱形语法 = `Object`**

```java
var list = new ArrayList<>();   // 推导为 ArrayList<Object>，不是 ArrayList<String>！
list.add("a");
list.add(1);                    // 合法，因为它是 Object
```

菱形语法 `<>` 的语义是"从上下文推导类型参数"。而 `var` 说"我从右边推导"。两边互相瞪眼，最后编译器按规则选了 `Object`。

**坑二：`var` + 匿名类 = 推导出一个你写不出名字的类型**

```java
var obj = new Object() {
    void hello() { System.out.println("hi"); }
};
obj.hello();   // ✅ 能编译！因为 obj 的类型是这个匿名类本身
```

这在 Java 8 里是**编译错误**（`Object` 没有 `hello()` 方法）。用 `var` 之后它反而能过了。这个"能过"很危险 —— 你把一个本该被接口约束的东西，变成了一个只有这一处能用的匿名类型。方法返回值写不出来了。

**坑三：数字字面量的类型悄悄变了**

```java
var price = 100;      // int
var total = 100L;     // long
var rate  = 0.1;      // double
var big   = 1_000_000_000_000L;  // long，还好
```

在 Go 里 `price := 100` 之后 `price` 是 `int`，你做 `price * rate` 编译器会直接报错。Java 里也一样会报错（int 和 double 混合运算会提升，但赋值给 var 后类型是推导时定死的）。真正的问题在于**隐式数值提升**：`var x = 1_000_000 * 1_000_000;` 会静默溢出成 int，而如果你写的是 `long x = ...`，结果就完全不同。

**判据：涉及金额、数量、ID 的变量，一律不写 `var`。**

---


## 02.2 `record`：一行搞定不可变数据类（Java 16 正式，JEP 395）

先看这个 Java 8 项目里真实存在的东西（第 01 章提过，这里看完整版）：

```java
public class Order {
    private Long id;
    private String name;
    private long amount;

    public Order() {}                    // MyBatis / Jackson 要的无参构造器

    public Order(Long id, String name, long amount) { ... }

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getName() { return name; }
    public void setName(String name) { this.name = name; }
    public long getAmount() { return amount; }
    public void setAmount(long amount) { this.amount = amount; }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        Order order = (Order) o;
        return amount == order.amount
            && Objects.equals(id, order.id)
            && Objects.equals(name, order.name);
    }

    @Override
    public int hashCode() { return Objects.hash(id, name, amount); }

    @Override
    public String toString() {
        return "Order{id=" + id + ", name='" + name + '\'' + ", amount=" + amount + '}';
    }
}
```

一个 3 字段的类，60 行。20 字段的 DTO 就是 400 行。**而且这 400 行里没有任何一行业务逻辑。**

Java 16 之后：

```java
public record Order(Long id, String name, long amount) {}
```

一行。

**问题 2：** 这一行背后，编译器到底给你生成了什么？猜一下 —— 是"生成一堆 getter 的字节码"，还是别的什么？

答案是后者，而且做法比你想的聪明。用 `javap -p` 看：

```bash
javac Order.java
javap -p Order.class
```

```
final class Order extends java.lang.Record {
  private final java.lang.Long id;
  private final java.lang.String name;
  private final long amount;

  public Order(java.lang.Long, java.lang.String, long);   // canonical constructor
  public java.lang.String toString();
  public final int hashCode();
  public final boolean equals(java.lang.Object);
  public java.lang.Long id();
  public java.lang.String name();
  public long amount();
}
```

五个要点，逐个看：

1. **`final class`，且隐式 `extends java.lang.Record`** —— 所以 record 不能继承任何类（Java 单继承，名额被 `Record` 占了），也不能被继承。
2. **字段是 `private final`** —— 不可变，语言级保证，不是靠你自觉。
3. **accessor 是 `id()` / `name()`，不是 `getId()`**（下面专门讲为什么）。
4. **`equals` 和 `hashCode` 是 `final`** —— 你不能重写它们。`toString()` 可以重写。
5. **`toString()`/`equals()`/`hashCode()` 不是"生成的字节码"，而是 `invokedynamic`**。

第 5 点值得展开。你用 `javap -c -v` 看 `toString()` 的实现，会看到：

```
public java.lang.String toString();
  Code:
     0: aload_0
     1: invokedynamic #x,  0   // InvokeDynamic #0:toString:(LOrder;)Ljava/lang/String;
     6: areturn
```

它调用的是 `java.lang.runtime.ObjectMethods.bootstrap`。**编译器没有为这三个方法生成任何实现代码，只有一个启动引导。** 真正的逻辑在 JDK 的 `ObjectMethods` 类里，按 record 的分量（component）反射式地生成。

这意味着什么？意味着**如果你以后给 record 加一个字段，以前编译的调用方不需要重新编译**（`toString` 的行为会自动跟着变，因为逻辑在运行时解析）。这是 JVM 层面为 record 专门做的设计。

### 紧凑构造器（compact constructor）：加校验

```java
public record Order(Long id, String name, long amount) {
    // 紧凑构造器：没有参数列表，没有赋值语句（赋值是自动的）
    public Order {
        Objects.requireNonNull(id, "id 不能为空");
        if (amount < 0) {
            throw new IllegalArgumentException("金额不能为负: " + amount);
        }
        // 注意：这里可以改参数值，改完的值会用于自动赋值
        name = name == null ? "" : name.trim();
    }
}
```

关键区别：

```java
// 紧凑构造器（推荐）：参数隐式存在，末尾自动赋值
public Order { /* 校验/规范化 */ }

// 完整写法（需要显式赋值）
public Order(Long id, String name, long amount) {
    this.id = id;
    this.name = name;
    this.amount = amount;
}
```

紧凑构造器的语义是：**方法体在"参数已经可用、字段尚未赋值"的时刻执行，方法体结束后自动 `this.xxx = xxx`。** 这个时刻你改参数的值，就是改最终字段的值。

### record 的限制（这些是硬约束，不是风格建议）

| 限制 | 具体内容 | 后果 |
|---|---|---|
| 不能继承 | 隐式 `extends java.lang.Record` | 不能 `extends` 任何类 |
| 不能被继承 | 类是 `final` | 不能做父类 |
| 字段不可变 | `private final` | 没有 setter，改数据只能 new 一个新的 |
| 不能加实例字段 | 只能加 `static` 字段 | 想加缓存字段？不行 |
| 可以实现接口 | `record X(...) implements Foo` | ✅ 这是它的主要扩展方式 |
| 可以加方法 | 可以加普通实例方法 | ✅ 常用于派生计算 |

```java
public record Money(long cents, String currency) implements Comparable<Money> {
    public Money {
        if (cents < 0) throw new IllegalArgumentException();
    }
    // 可以加方法
    public Money plus(Money other) {
        checkCurrency(other);
        return new Money(this.cents + other.cents, currency);
    }
    @Override
    public int compareTo(Money o) {
        checkCurrency(o);
        return Long.compare(cents, o.cents);
    }
    // 可以加 static 字段
    private static final Set<String> SUPPORTED = Set.of("CNY", "USD");
    // ❌ 不能加实例字段：private long cachedValue;
}
```

### Go struct 对照

```go
type Order struct {
    ID     int64
    Name   string
    Amount int64  `json:"amount"`
}

o := Order{ID: 1, Name: "x", Amount: 100}
o.Amount = 200                       // 可变
fmt.Println(o)                       // {1 x 200}，格式固定，不是自动生成的
```

| 维度 | Go struct | Java record |
|---|---|---|
| 可变性 | 可变（除非你只导出方法不导出字段） | **不可变，语言级** |
| 自动生成方法 | 无（只有内置的可比较性：可比较字段才能 `==`） | `equals`/`hashCode`/`toString` 自动生成 |
| 构造器 | 字面量 `T{...}`，字段可选 | canonical constructor，必须全参 |
| 元数据 | struct tag（字符串，反射可读） | 注解（结构化，运行时可读） |
| 零值 | 有零值（`Order{}` 合法且字段为零值） | **无零值**，必须显式构造 |
| 内存布局 | 连续（值语义，可避免间接寻址） | 对象（引用语义，除非未来的 value type） |

**"无零值"这条在 Java 里是优点。** Go 的零值设计让 `var o Order` 是一个合法但通常无意义的对象，你必须靠约定避免它。record 直接不给你这个选项。

### 跟 Lombok `@Data` 对比

如果你在老项目里见过这个，那它是 Lombok：

```java
@Data
@NoArgsConstructor
@AllArgsConstructor
public class Order {
    private Long id;
    private String name;
    private long amount;
}
```

看起来也挺简洁。为什么不继续用？

| 维度 | record（语言级） | Lombok `@Data`（编译期魔法） |
|---|---|---|
| 实现机制 | 编译器原生支持 | 注解处理器 + **修改 javac 内部 AST** |
| 依赖 | 无（JDK 自带） | 要加依赖，要装 IDE 插件 |
| 升级 JDK | 无感 | **每次升级大版本都可能炸**（Lombok 用了 javac 内部 API） |
| 不可变性 | 强制 | 默认可变（生成了 setter） |
| IDE 支持 | 原生 | 需要插件，插件跟不上就报错 |
| 调试 | 正常 | 你要看的代码不存在，是生成的 |

Lombok 的实现原理是：它注册了一个 javac 的注解处理器，而这个处理器**通过反射/unsafe 往 javac 的内部 AST 结构里塞节点**。这不是 JDK 的公开 API，是 hack。所以每次 javac 内部重构，Lombok 就要跟着改 —— 这也是为什么社区里"升级 JDK 17 之后 Lombok 报错"的帖子特别多。

**判据：新项目用 record，老项目别急着把 Lombok 全换了（收益不大，风险不小），但新写的类一律用 record。**

> 【思考】为什么 record 的 accessor 叫 `name()` 而不是 `getName()`？
>
> 补充信息：Java Bean 规范（1996 年）规定 getter 必须叫 `getXxx()`，二十多年来整个 Java 生态都建立在这个约定上。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 record 不承认自己是 Java Bean，它想表达的是"分量"（component），不是"属性"（property）。**

这个命名不是偷懒，是**主动切割**。展开说。

**第一层：Java Bean 的 `get` 前缀本来就是个历史包袱。**

Java Bean 规范诞生于 1996 年，目标场景是**可视化 IDE 里的组件拖放**：你把一个 Button 拖到窗体上，IDE 在属性面板里列出它的属性让你改。IDE 怎么知道哪些方法算"属性"？靠命名约定：`getXxx()`/`setXxx()`。

这个约定后来被无数框架沿用了：

- **Spring**：`${user.name}` 这种属性访问，底层是 `getName()`
- **Jackson**：默认按 `getXxx()` 找字段来序列化
- **MyBatis**：结果集映射靠 setter，或者按字段名找 getter
- **JSP EL / Thymeleaf**：`${order.amount}` → `getAmount()`

于是 `get` 前缀从"IDE 的约定"变成了"整个生态的 ABI"。

**第二层：这个包袱给 record 带来了麻烦。**

如果 record 生成 `getName()`，那它就是"一个不可变的 Bean"—— 生态里所有按 Bean 处理它的代码都会假设：

1. 有对应的 `setName()`（没有 → 某些框架在反射时直接失败）
2. 有一个无参构造器（没有 → MyBatis、很多 JSON 库反序列化失败）
3. 类不是 `final`（是 → 任何想生成子类的代理机制失败）

**这三点恰好是 record 做不到的。** 你叫它 Bean，然后它满足不了 Bean 的契约，那所有框架都会以各种奇怪的方式炸。

所以 JDK 团队选了 `name()`，含义是：**"我不是 Bean，别拿 Bean 那套规则套我。你想支持我，得显式支持。"**

这是一个**强制生态表态**的设计决策，代价是短期内兼容性阵痛。

**第三层：实际影响（这一段是你日常会撞上的）**

**Jackson**：从 2.12 起原生支持 record。意思是它看到 `record` 会走一条专门路径 —— 读 `getRecordComponents()`，用 canonical constructor 反序列化，序列化时用 accessor。

```java
record User(String name, int age) {}

var mapper = new ObjectMapper();
String json = mapper.writeValueAsString(new User("Alice", 30));
// {"name":"Alice","age":30}   ✅ 注意：是 name/age，不是 getName

User u = mapper.readValue(json, User.class);   // ✅ 走 canonical constructor
```

**但如果你用的 Jackson < 2.12，序列化出来是 `{}`。** 因为它按 Bean 规则找 `getName()`，一个都没找到，就认为这个对象没有属性。这是个真实的坑，而且报错信息极其不友好 —— 不报错，就是静默给你一个空对象。

**MyBatis**：record 没有 setter，也没有无参构造器，所以字段映射必须走**构造器映射**：

```java
public interface UserMapper {
    @Select("select name, age from user where id = #{id}")
    @ConstructorArgs({
        @Arg(column = "name", javaType = String.class),
        @Arg(column = "age",  javaType = int.class)
    })
    User findById(long id);
}
```

或者用 XML 的 `<constructor>` 元素。**注意构造器参数的名字默认拿不到**（Java 编译后方法参数名默认不保留，需要 `-parameters` 编译选项），所以要么加 `-parameters`，要么显式用 `@Arg` 或 `@Param` 标注。这一步很多人漏掉，然后拿到一个全 null 的 record，一脸懵。

**Spring 的配置绑定**：`@ConfigurationProperties` 对 record 的支持（Spring Boot 2.6+ 有构造器绑定），也需要 `-parameters` 或者显式标注。

**代码锚点 —— 验证 Jackson 的行为差异：**

```bash
# 在自己的项目里跑一下，看你的 Jackson 版本对 record 的支持情况
mvn dependency:tree | grep jackson

# 确认 -parameters 是否开启（Maven 的 spring-boot-starter-parent 默认开了）
javap -p -v target/classes/com/example/User.class | grep MethodParameters
```

**更深一层 — 这揭示了一个语言演进的普遍规律：**

**新特性要摆脱旧约定的时候，必须在命名上做切割，否则旧约定会顺着名字爬回来。** 这跟 Go 里"不接受接口就别起 `Xxxer` 的名字"是同一种洁癖的反面：Go 靠社区约定保持一致性，Java 靠"切断命名"来强制生态重新表态。

**代价是什么？** 短期兼容性地狱（你今天用 record + 老框架，就要踩这些坑）。**收益是什么？** 十年后 Java 不必再背 `get` 前缀这个 1996 年的包袱。

**这是 Java 演进"慢"的一个具体体现 —— 它每次做切割，都要付一次全生态的迁移成本。** 第 02.11 的思考题 1 会回到这个话题。
</details>

### record 的真实坑：不能做 JPA 的 `@Entity`

```java
@Entity                                    // ❌ 编译能过，运行时炸
@Table(name = "t_order")
public record Order(Long id, String name) {}
```

JPA（Hibernate）的实体要求：

1. **类不能是 `final`** —— Hibernate 要靠生成代理子类（CGLIB）实现懒加载；record 是 `final`
2. **必须有无参构造器** —— Hibernate 从数据库读出一行后，先 `new` 一个空对象再填字段；record 没有
3. **字段不能是 `final`** —— 同上，要靠反射/setter 填值；record 的字段是 `final`

**这三条 record 全中。** 所以 record 不能做实体类。

**那 record 能做什么？** 这才是它真正的主场：

- **DTO**（Controller 的请求/响应对象）—— 最常用的场景
- **配置绑定对象**（`@ConfigurationProperties`）
- **多返回值** —— Java 没有 Go 的 `(T, error)`，record 是最接近的替代品
- **Map 的 key** —— 自动的 `equals`/`hashCode` 让它天然适合
- **模式匹配的载体** —— 见 02.4 的记录模式
- **投影查询的结果**（Spring Data JPA 的 interface projection 之外的新选择）

多返回值那个场景值得看一眼，因为它是 Go 程序员最怀念的东西：

```go
// Go
func Parse(s string) (int, error) { ... }
n, err := Parse("42")
```

```java
// Java：用 record 模拟
record Parsed(int value, String error) {}

static Parsed parse(String s) {
    try { return new Parsed(Integer.parseInt(s), null); }
    catch (NumberFormatException e) { return new Parsed(0, e.getMessage()); }
}
// 或者更 Java 的写法：直接抛异常，或者返回 Optional<Integer>
```

**但要诚实：这个模拟很别扭。** Java 社区的主流意见是"多返回值就用异常或者抛自定义异常"，`Optional` 只用于"值可能不存在"这一种语义。硬套 Go 的 `(T, error)` 模式，会让你的代码在 Java 里显得很怪 —— 团队里其他人看不懂你为什么要这么写。**02.6 会详细对比。**

---


