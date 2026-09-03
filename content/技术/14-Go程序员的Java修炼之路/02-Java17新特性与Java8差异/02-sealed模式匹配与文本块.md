# 第 02 章（节选）　sealed模式匹配与文本块

> 本篇来自《Go 程序员的 Java 修炼之路》第 02 章「第 02 章　Java 17 新特性与 Java 8 差异（现代 Java 长什么样）」。
> 返回：[第 02 章索引](./README.md)

## 02.3 `sealed`：我能限制谁能继承我（Java 17 正式，JEP 409）

先看一个你迟早会遇到的问题：

```java
public interface Shape {
    double area();
}
```

这个接口写在公共模块里。三个月后你接了个需求："统计所有图形的面积总和，按类型做不同处理。" 你去 IDE 里搜 `implements Shape`，搜出来 47 个实现，分布在 12 个模块里，其中 3 个是别的企业微信群里的人偷偷加的，还有 1 个是测试代码里的 mock。

**你做不到穷举。**

**问题 3：** 在 Go 里，你怎么解决"限制谁能实现这个接口"这个问题？

（先想三十秒。这个问题你大概率知道答案，但把它明确说出来，能帮你理解 Java 为什么要加 `sealed`。）

### 语法

```java
// sealed 接口：明确列出谁能实现我
public sealed interface Shape
        permits Circle, Square, Rectangle {
    double area();
}

// 每个被许可的实现，必须明确表态：final / sealed / non-sealed，三选一
public record Circle(double radius) implements Shape {
    public double area() { return Math.PI * radius * radius; }
}

public record Square(double side) implements Shape {
    public double area() { return side * side; }
}

public non-sealed class Rectangle implements Shape {
    private double w, h;
    public double area() { return w * h; }
}
```

三个修饰符的组合规则：

| 修饰符 | 含义 | 谁能继承我 |
|---|---|---|
| `final` | 到我这里为止 | 谁都不能 |
| `sealed` | 我也限制，我列名单 | 只有我 `permits` 的 |
| `non-sealed` | 我解除封闭 | 谁都行（回到普通类的状态） |

**规则：父类是 `sealed` 时，每个被 `permits` 的直接子类必须显式写 `final`、`sealed` 或 `non-sealed` 之一。** 不写就是编译错误。这条强制规则的用意是：**不许有人默默地把封闭性放开。**

另外两条细则：

1. 所有被 `permits` 的类必须**能被父类访问到**（同包，或者同模块）
2. 如果所有子类跟父类在**同一个编译单元**（同一个 `.java` 文件），`permits` 可以省略

第 2 条让你能写出这种很干净的代码：

```java
public sealed interface Result {
    record Ok(String data)  implements Result {}
    record Err(String msg)  implements Result {}
}
// permits 自动推导为 Result.Ok, Result.Err
```

### 为什么需要它：让编译器能穷举

这是重点。`sealed` 真正的价值不在"限制"，在**穷举性检查**。

看这段 Java 21 的代码（Java 17 里需要 `--enable-preview`，Java 21 正式）：

```java
double area(Shape s) {
    return switch (s) {
        case Circle c    -> Math.PI * c.radius() * c.radius();
        case Square sq   -> sq.side() * sq.side();
        case Rectangle r -> r.w() * r.h();
        // 没有 default！编译器知道这三种就是全部
    };
}
```

**没有 `default` 分支，而且编译通过。** 因为编译器看到 `Shape` 是 `sealed`，知道 `permits` 了三个，三个都覆盖了，穷尽了。

现在有人加了一个 `Triangle implements Shape`（并且更新了 `permits`），编译器会**在你这个 `switch` 这里报编译错误**："the switch statement does not cover all possible input values"。

**这就是"编译期强制你处理所有情况"，而且是在所有使用点同时报警。**

**问题 4：** 在 Go 里你要实现同样的效果（加一个新类型，所有没处理它的地方都编译失败），你怎么做？

答案是：做不了，至少语言层面做不到。Go 的 type switch 必须写 `default`，编译器不会帮你检查穷举性。Go 社区的做法是写 `default: panic("unreachable")` 然后靠代码评审和 grep。

### Go 里怎么做封闭

并排看：

```go
// Go：非导出方法 + 包内实现 + 工厂函数
package shape

type Shape interface {
    Area() float64
    sealed()        // 非导出方法：包外无法实现这个接口
}

type Circle struct{ Radius float64 }
func (c Circle) Area() float64 { return math.Pi * c.Radius * c.Radius }
func (c Circle) sealed()       {}

type Square struct{ Side float64 }
func (s Square) Area() float64 { return s.Side * s.Side }
func (s Square) sealed()       {}

// 包外：
// type Triangle struct{}
// func (t Triangle) Area() float64 { return 0 }
// ❌ 编译通过但无法满足 Shape（缺 sealed 方法），赋值给 Shape 时报错
```

```java
// Java 17
package com.example.shape;

public sealed interface Shape permits Circle, Square {
    double area();
}
public record Circle(double radius) implements Shape {
    public double area() { return Math.PI * radius * radius; }
}
public record Square(double side) implements Shape {
    public double area() { return side * side; }
}
```

> 【思考】既然 Go 用"非导出方法"就能实现封闭，**为什么 Java 非要在语言层面加一个 `sealed` 关键字？**
>
> 提示：想想 Java 的 `package` 和 Go 的 `package`，在"封装边界"这件事上是不是同一个东西。

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 Go 的包天然是封装边界，Java 的包不是 —— Java 的包只是一个命名分组，任何人都能写一行 `package com.example;` 把自己塞进去。**

这是两种语言对 `package` 这个词的根本性分歧，展开讲三层。

**第一层：Go 的包 = 编译单元 = 封装单元，三者是同一个东西。**

Go 里：

- 一个目录 = 一个包
- 包内的非导出标识符（小写开头）**在包外不可见**，这是编译器强制的
- 别的文件要用你的东西，必须通过 import 路径（通常是代码托管地址）

所以 Go 的"非导出方法"是一个**编译器强制的、不可绕过的访问屏障**。你在 `shape` 包里写一个 `sealed()` 方法，包外的任何代码都无法实现它 —— 不是"不该实现"，是"实现不了"，编译器不让。

**而且这个屏障的粒度刚好合适**：一个包通常是一个团队维护的一个功能模块，正好是"谁有权扩展我"的合理边界。

**第二层：Java 的包是"逻辑分组"，不是"封装边界"。**

Java 的包有这些特点：

1. **包名和物理位置只是约定上的对应**，编译后完全无关（决定类在哪的是 classpath，第 00 章讲过）
2. **包没有所有者** —— 任何人都可以写一个 `package com.example.shape;` 的文件，跟你的代码放在同一个包里
3. **`package-private`（默认访问权限）的边界就是这个"包"，而包是开放的**

第 2 点是致命的。看这段：

```java
// 你的代码：com/example/shape/Shape.java
package com.example.shape;
public interface Shape {
    double area();
}
```

```java
// 隔壁部门的人写：other/place/RogueShape.java
package com.example.shape;   // ← 就这么一行，他成了"包内"的人
public class RogueShape implements Shape {
    public double area() { return -1; }
}
```

**这在 Java 里完全合法。** 编译通过，运行通过，classpath 里两个 jar 一放，你的 `Shape` 就被人实现了。

**Java 有没有"包级私有方法"能模拟 Go 的 `sealed()`？** 有，就是不加修饰符：

```java
public interface Shape {
    double area();
    /* package-private */ void sealedMarker();
}
```

但如上所述，**包级私有拦不住任何人**，因为包本身是开放的。

Java 9 的模块系统（JPMS）本来想解决这个问题 —— `module-info.java` 里 `exports` 的包才是真正对外的。但 JPMS 的采纳率低得可怜（02.7 会讲为什么），而且它要求你把整个应用模块化，成本极高。

**所以 Java 需要一个不依赖模块系统的、类级别的封闭机制。这就是 `sealed`。**

**第三层：`sealed` 顺带拿到了 Go 拿不到的东西 —— 穷举性检查。**

Go 的"非导出方法"方案只做到了**封闭**（不能新增实现），没有做到**可穷举**。Go 的编译器在做 type switch 的时候，并不知道"这个接口有哪些实现"，因为它压根没维护这个清单 —— 接口的满足是隐式的、结构化的，编译器无法枚举。

Java 的 `sealed` 在语法层面就写了一份**显式清单**（`permits`）。这份清单不只是给人看的，编译器会拿它做类型覆盖检查（type coverage）。

```java
// Java 21
int corners(Shape s) {
    return switch (s) {
        case Circle c    -> 0;
        case Square sq   -> 4;
        // Rectangle 漏了 → 编译错误
    };
}
```

**"封闭"和"可穷举"是两件事，Go 只拿到了前者，Java 两个都拿到了。** 这是 `sealed` 真正的价值。

**代码锚点 —— 自己验证穷举性检查：**

```bash
# Java 21 下直接编；Java 17 需要 --enable-preview
cat > Demo.java <<'EOF'
sealed interface Shape permits Circle, Square {}
record Circle(double r) implements Shape {}
record Square(double s) implements Shape {}

public class Demo {
    static String name(Shape sh) {
        return switch (sh) {
            case Circle c -> "circle";
            case Square s -> "square";
        };   // 无 default，穷举通过
    }
    public static void main(String[] a) {
        System.out.println(name(new Circle(1)));
    }
}
EOF

# Java 17（预览特性）
javac --enable-preview --release 17 Demo.java && java --enable-preview Demo
# Java 21（正式）
javac Demo.java && java Demo
```

然后加一个 `record Triangle(...) implements Shape {}` 并更新 `permits`，再编译 —— 你会看到 `name()` 那里报"不穷举"的错误。**这就是 sealed 的价值：新增一种情况，所有没处理它的地方同时编译失败。**

**更深一层 — 这背后是"名义类型"和"结构类型"的分野：**

Go 是结构类型（structural typing）：类型 A 满足接口 I，靠的是"方法集匹配"这个**可以事后验证的性质**，不需要事前登记。这套机制天然**支持开放扩展**，天然**不支持穷举**。

Java 是名义类型（nominal typing）：类型 A 实现接口 I，必须写 `implements I`，这是一次**事前登记**。既然有登记，就可以有清单；有清单，就能穷举。

**`sealed` 不是给 Java 加了一个新能力，是把名义类型系统本来就有的潜力兑现了出来。**

顺着这个逻辑往下推，你能自己得出一个结论：**Go 永远不可能在保持隐式接口的前提下支持穷举性检查。** 如果哪天 Go 想支持 switch 穷举，它必须先引入某种"显式登记"机制 —— 那就不再是今天的 Go 了。

**这就是我说的"推导出边界"**：你不需要记住"Go 不能穷举"，你需要知道的是"穷举依赖清单，清单依赖登记，Go 没有登记"—— 这条链你自己能推出来。
</details>

### `sealed` 的真实用途

- **AST 节点**：编译器/解析器里，`Expr` 只有 `BinaryExpr`/`LiteralExpr`/`VarExpr` 几种
- **状态机**：`OrderState permits Created, Paid, Shipped, Cancelled`
- **RPC 消息类型**：`Message permits Request, Response, Ping`
- **错误类型层次**：`AppError permits ValidationError, NotFoundError, RemoteError`
- **领域建模**：`PaymentMethod permits Alipay, WechatPay, Card`

判据：**当你写下"这个类型只有这几种情况"这句话的时候，就用 `sealed`。** 这不是风格偏好，是"把领域约束写进类型系统"，让它由编译器而不是 code review 来保证。

---


## 02.4 模式匹配：instanceof / switch / 记录模式

模式匹配是 Java 这几年最大的一笔投入，分四步走，跨了五个版本：

| 特性 | 版本 | JEP | 状态 |
|---|---|---|---|
| instanceof 模式匹配 | Java 16 | JEP 394 | 正式 |
| switch 表达式 | Java 14 | JEP 361 | 正式 |
| switch 模式匹配 | Java 17 | JEP 406 | **预览**（17/18/19/20 四次预览，JEP 420/427/433） |
| switch 模式匹配 | **Java 21** | **JEP 441** | 正式 |
| 记录模式 | Java 19 预览 / **Java 21 正式** | JEP 405 / **JEP 440** | 正式 |

**注意版本基线**：本书以 Java 17 为主，所以下面凡是 switch 模式匹配和记录模式的代码，都标注了"Java 21"。**在 Java 17 上你要用这些，得加 `--enable-preview`，而且编译产物不能上生产**（预览特性的 class 文件带特殊标记，且不保证跨版本兼容）。

### 第一步：instanceof 模式匹配（Java 16，JEP 394）

Java 8：

```java
if (obj instanceof String) {
    String s = (String) obj;    // 你得再写一遍 String，再强转一次
    System.out.println(s.length());
}
```

Java 16：

```java
if (obj instanceof String s) {   // 匹配成功就把 s 绑定好，作用域覆盖整个 if 块
    System.out.println(s.length());
}
```

**省掉的不只是强转，还有一次人为的犯错机会** —— Java 8 那种写法里，`instanceof` 和强转的类型是两处独立的代码，理论上可以写不一致（虽然编译器通常能发现）。

作用域规则很聪明，值得注意：

```java
if (!(obj instanceof String s)) {
    return;      // 不匹配就走了
}
// 这里 s 仍然可用！因为编译器知道走到这里说明匹配成功了
System.out.println(s.length());

if (obj instanceof String s && s.length() > 5) {   // ✅ s 在 && 右边可用
}
if (obj instanceof String s || s.length() > 5) {   // ❌ 编译错误：|| 右边 s 不一定存在
}
```

### 第二步：switch 表达式（Java 14 正式，JEP 361）

Java 8 的 switch 有三个众所周知的问题：贯穿（fall-through）、不能返回值、case 里声明变量作用域混乱。

Java 14 给了新写法：

```java
// 箭头语法：不会贯穿
DayType type = switch (day) {
    case MON, TUE, WED, THU, FRI -> DayType.WEEKDAY;
    case SAT, SUN                -> DayType.WEEKEND;
};   // 注意末尾的分号 —— switch 是一个表达式，它有值
```

要点三条：

1. **`->` 后面可以是值、表达式，或者一个块**（块里用 `yield` 返回值）
2. **不写贯穿**，一个 case 匹配完就结束，不需要 `break`
3. **穷尽性**：如果 switch 用作表达式（有返回值），必须覆盖所有情况

```java
int len = switch (s) {
    case null      -> 0;                     // Java 21 起支持 case null
    case ""        -> 0;
    default        -> {
        System.out.println("计算中: " + s);
        yield s.length();                    // 块里用 yield 产出值
    }
};
```

**问题 5：** `yield` 和 `return` 有什么区别？

`return` 从**方法**返回；`yield` 从**switch 分支**产出值。设计上不能用 `return`，因为 `return` 会让代码读起来像"方法结束了"，而实际上 switch 后面还有代码要执行。这是个纯可读性考量。

### 第三步：switch 模式匹配（Java 21 正式，JEP 441）

```java
// Java 21
static String format(Object o) {
    return switch (o) {
        case Integer i -> String.format("int %d", i);
        case Long l    -> String.format("long %d", l);
        case Double d  -> String.format("double %f", d);
        case String s  -> String.format("String %s", s);
        case null      -> "null";              // 显式处理 null
        default        -> o.toString();
    };
}
```

守卫条件（`when`）：

```java
static String classify(Object o) {
    return switch (o) {
        case String s when s.isEmpty()  -> "空字符串";
        case String s when s.length() > 100 -> "长字符串";
        case String s                   -> "普通字符串 (" + s.length() + ")";
        case Integer i when i < 0       -> "负整数";
        case Integer i                  -> "非负整数";
        default                         -> "其他";
    };
}
```

### 第四步：记录模式（Java 21 正式，JEP 440）—— 解构

这是模式匹配真正好用的地方：

```java
record Point(int x, int y) {}
record Line(Point start, Point end) {}

// 解构：一层一层把 record 拆开
static void print(Object o) {
    if (o instanceof Point(int x, int y)) {
        System.out.println("点: " + x + ", " + y);
    }
}

// 嵌套解构
static double length(Line l) {
    if (l instanceof Line(Point(int x1, int y1), Point(int x2, int y2))) {
        return Math.hypot(x2 - x1, y2 - y1);
    }
    throw new IllegalArgumentException();
}

// 在 switch 里解构 + sealed 穷举（这就是 02.3 说的那个组合拳）
sealed interface Shape permits Circle, Rect {}
record Circle(Point center, double r) implements Shape {}
record Rect(Point topLeft, Point bottomRight) implements Shape {}

static double area(Shape s) {
    return switch (s) {
        case Circle(Point(var cx, var cy), double r) -> Math.PI * r * r;
        case Rect(Point(int x1, int y1), Point(int x2, int y2))
            -> Math.abs((x2 - x1) * (y2 - y1));
        // 无 default，因为 Shape 是 sealed 且全部覆盖
    };
}
```

**`sealed` + `record` + 记录模式 + switch，这四个特性是一套的。** 分开看每个都只是"省了几行代码"，合起来是一种新的编程范式 —— Java 官方管它叫**面向数据编程**（Data-Oriented Programming），跟传统的面向对象编程并列。

### Go 的 type switch 对照

```go
// Go：type switch
func format(v any) string {
    switch x := v.(type) {
    case int:
        return fmt.Sprintf("int %d", x)
    case string:
        return fmt.Sprintf("string %s", x)
    case nil:
        return "null"
    default:
        return fmt.Sprintf("%v", x)
    }
}
```

```java
// Java 21
static String format(Object v) {
    return switch (v) {
        case Integer i -> "int " + i;
        case String s  -> "string " + s;
        case null      -> "null";
        default        -> v.toString();
    };
}
```

长得几乎一样。但能力边界差很多。

> 【思考】Go 的 type switch 和 Java 的 switch 模式匹配，**能力边界差在哪？** 列出至少三个 Java 能做、Go 做不到的点。
>
> 提示：想想 type switch 的"被匹配对象"有什么限制。

<details>
<summary><b>参考答案</b></summary>

**直接答案：三个核心差异 —— 匹配范围、解构能力、守卫条件。**

**差异一：Go 只能对接口做 type switch，Java 可以对任意对象。**

这是最根本的一条。Go 的 `switch x := v.(type)` 要求 `v` 的静态类型是**接口**（通常是 `any`/`interface{}`）。如果你传一个具体类型，编译器直接报错：

```go
func f(p Point) {
    switch p.(type) {   // ❌ 编译错误：cannot type switch on non-interface value
    case Point:
    }
}
```

原因很直白：type switch 的语义是"在运行时的动态类型里选一个"。**如果静态类型已经是 `Point`，那动态类型必然是 `Point`，这个 switch 毫无意义**，Go 就直接禁止了。

Java 的模式匹配没有这个限制：

```java
Point p = getPoint();
if (p instanceof Point(int x, int y)) { }   // ✅ 合法，而且有用（因为解构了）
```

Java 的 switch 支持 `Object`、`String`、`int`、枚举、以及任何引用类型的选择器。它的语义不是"从动态类型里选"，而是"用模式去测试这个值"。**模式测试比类型测试宽泛得多。**

**差异二：Java 能解构（destructuring），Go 不能。**

```java
// Java 21：一层拆到底
if (shape instanceof Circle(Point(int x, int y), double r)) {
    // x, y, r 直接可用
}
```

Go 里等价的代码：

```go
switch v := shape.(type) {
case Circle:
    x, y := v.Center.X, v.Center.Y   // 手动一层一层取
    r := v.Radius
    _ = x; _ = y; _ = r
}
```

Go 没有解构语法。结构体字段只能手动取，或者用多返回值辅助（`x, y := p.XY()`）。这一条在深层嵌套结构里差距会被放大：Java 一行解构三层，Go 要写三个临时变量。

**反过来，Go 有一个 Java 没有的能力** —— 对多返回值的天然支持，让"拆包"这件事在很多时候根本不需要解构语法：

```go
v, ok := m[key]        // Go 的 map 查询天然返回两个值
n, err := strconv.Atoi(s)
```

Java 要模拟这个就得靠 record（还是个对象，有分配开销）。**这是 Go 的"多返回值"设计换来的红利。**

**差异三：Java 有守卫条件 `when`，Go 只能靠嵌套 if。**

```java
// Java 21
case String s when s.length() > 100 -> "长字符串";
case String s                       -> "短字符串";
```

```go
// Go
case string:
    if len(v) > 100 {
        return "长字符串"
    }
    return "短字符串"
```

Go 的写法在 case 少的时候也还行，但当你要"同一类型的多种条件分支"时，就得写嵌套 if 或者提前 return，代码开始往右边斜。

**差异四（补充）：Java 有编译期穷举检查，Go 没有。**

这条来自 `sealed`（02.3 讲过）。Go 的 type switch 必须写 `default` 分支（其实可以不写，但那就意味着不匹配时什么都不做 —— 一个静默的 bug 源头），而且编译器不会告诉你"你漏了一种类型"。

**代码锚点 —— 直接用 JDK 跑：**

```bash
# Java 21+
jshell --enable-preview   # 21 不需要 preview，直接 jshell 即可
```

```java
record Point(int x, int y) {}
Object o = new Point(3, 4);
if (o instanceof Point(int x, int y)) System.out.println(x + "," + y);   // 3,4
```

**更深一层 — 这个差异的根源是"类型的性质不同"：**

Go 的 `switch x := v.(type)` 本质上是**运行时类型标签的分支跳转**。它匹配的是 `v` 的接口值里存的那个类型描述符（type descriptor）。所以它必须作用在接口上，只能按类型分派，不能做结构判断。

Java 的模式匹配是**"匹配 + 绑定"的通用机制**。`instanceof` 只是众多模式中的一种（类型模式），此外还有记录模式、数组模式（预览中）。**匹配这个动作本身比"查类型标签"宽泛** —— 它可以包含解构、可以包含守卫谓词、可以递归嵌套。

**所以我的判断是**：Go 的 type switch 会长期停留在今天这个能力水平，因为它解决的问题就是"接口值的类型分派"，这个问题已经被解决了。Java 的模式匹配还在扩张（原始类型模式、数组模式都在 JEP 里），因为它定义的是一套通用机制。**一个已完成的特性和一个正在生长的机制，看起来像，其实不在一个层面。**

**对你的实际意义**：从 Go 过来，你不需要重新学"类型分派"这件事（你已经会了），你需要补的是**"解构 + 穷举"这两个新维度** —— 而这恰好是 Go 里没有的思维习惯。写 Java 21 代码时，遇到"按类型分情况处理"，先问一句：这个类型是不是该声明成 `sealed` + `record`，让编译器帮我检查穷举？
</details>

---


## 02.5 Text Block（Java 15 正式，JEP 378）

Java 8 里拼一段 SQL 是这样的：

```java
String sql = "SELECT o.id, o.name, u.nickname\n" +
             "FROM t_order o\n" +
             "LEFT JOIN t_user u ON o.user_id = u.id\n" +
             "WHERE o.status = ?\n" +
             "ORDER BY o.created_at DESC";
```

Java 15：

```java
String sql = """
        SELECT o.id, o.name, u.nickname
        FROM t_order o
        LEFT JOIN t_user u ON o.user_id = u.id
        WHERE o.status = ?
        ORDER BY o.created_at DESC
        """;
```

### 规则（只有几条，但要记准）

1. **开始分隔符 `"""` 后面必须换行**，内容从下一行开始
2. ** incidental indentation（附带缩进）会被自动去掉** —— 按所有非空行的**最小缩进**，以及结束分隔符的缩进，取更小者
3. **每行行尾的空格会被去掉**（这是意外行为的高发区）
4. `\` 放在行尾 = **抑制换行**（续行）
5. `\s` = **一个不会被去掉的空格**（专门用来保留行尾空格）

第 3、4、5 条是不写会踩的，各看一个例子：

```java
// 第 4 条：续行
String json = """
        {
            "name": "Alice", \
            "age": 30
        }
        """;
// 结果：{ "name": "Alice",             "age": 30 }  —— 注意 \ 后面那行的缩进被保留了

// 更常见的续行用法：超长行折行但不想引入换行符
String longSql = """
        SELECT * FROM t_order \
        WHERE status = ? \
        ORDER BY id
        """;   // 结果是一整行
```

```java
// 第 5 条：保留行尾空格
String s = """
        abc\s
        def
        """;
// "abc \ndef\n"  —— \s 让这个空格活下来了

// 对比：不写 \s
String t = """
        abc
        def
        """;
// "abc\ndef\n"  —— 行尾空格被 strip 掉了
```

### 三个新方法（Java 15 一起加的）

```java
String text = """
        Hello %s, you have %d messages
        """.formatted("Alice", 3);     // formatted() = String.format 的实例方法版本

text.stripIndent();       // 手动去掉附带缩进
text.translateEscapes();  // 手动处理转义序列
```

`formatted()` 是日常最常用的 —— 它让 Text Block 能当模板用。

### 跟 Go 反引号原始字符串的对比

```go
// Go：反引号 = 原始字符串
sql := `
    SELECT id, name
    FROM t_order
    WHERE status = ?
`
// 注意：Go 不做缩进处理！那 4 个空格会原样留在字符串里
// 而且 Go 保留换行符，所以首行会有一个空行
```

```java
// Java：Text Block
String sql = """
        SELECT id, name
        FROM t_order
        WHERE status = ?
        """;
```

| 维度 | Go 反引号 | Java Text Block |
|---|---|---|
| 转义处理 | **完全不处理**，`\n` 就是两个字符 | **处理转义序列**，`\n` 仍是换行符 |
| 缩进处理 | 不处理，原样保留 | **自动 strip 附带缩进** |
| 首行换行 | 保留（所以字符串以 `\n` 开头） | 去掉 |
| 行尾空格 | 保留 | **去掉**（要用 `\s` 保留） |
| 插值 | **不支持**（只有 `fmt.Sprintf`） | **不支持**（只有 `formatted()` / `String.format`） |
| 能否包含反引号/三引号 | Go 里不能包含反引号 | Java 里 `"""` 要转义成 `\"\"\"` |

**关键差异是第一条：Go 是真正"原始"的，Java 不是。**

```go
path := `C:\Users\admin`      // 反斜杠原样，正是你想要的
re := `\d{3}-\d{4}`           // 正则不用双重转义，这是 Go 反引号最大的价值
```

```java
String path = """
        C:\\Users\\admin
        """;   // ❌ 还是要写两个反斜杠！Text Block 依然处理转义
```

**所以 Java 的 Text Block 对正则没有任何帮助**，这是 Go 程序员最容易踩的一个预期落差。想要 Go 那种效果，Java 只能靠字符串拼接或者外部文件。

**问题 6：** 为什么 Java 不像 Go 一样做一个"完全不处理转义"的原始字符串？

因为 Java 已经有 25 年的字符串字面量语义，`\n`、`\u4e2d`（Unicode 转义）这些行为被写进了语言规范和无数代码里。做一个"什么都不处理"的新字面量，会让 `"\n"` 和 ```` `\n` `` 这两种写法的边界极其容易搞混，而且 `\u` 转义在 Java 里是**词法分析阶段**就处理的（在 `javac` 看到字符流时就替换了），想绕开这个阶段成本极高。Java 选择了"处理转义，但提供 `\s` 和 `\"` 让你精确控制"这条保守路线。（Java 21 的 String Templates 预览特性，JEP 430，本来想解决插值问题，后来被撤回重设计了。）

### 真实用途

```java
// 1. SQL（最常见）
// 2. JSON 测试夹具
String fixture = """
        {
          "userId": 1001,
          "items": [{"sku": "A-01", "qty": 2}]
        }
        """;

// 3. HTML 模板片段
// 4. 多行错误信息 / help 文本
// 5. 单元测试里的 expected 值
```

**注意一个实践细节**：SQL 放 Text Block 里，很多人会担心缩进影响 SQL 解析 —— 不会，SQL 不关心空白。但如果你把 **YAML 或 Python 代码**放进 Text Block，缩进处理就可能改变语义，这时候要格外小心，或者用 `stripIndent()` 明确控制。

---


