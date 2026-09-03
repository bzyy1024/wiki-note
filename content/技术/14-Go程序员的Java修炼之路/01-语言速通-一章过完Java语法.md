# 第 01 章　语言速通：一章过完 Java 语法（Go 视角）

> 这一章的目标很明确：**读完你能读懂任何 Java 代码的字面意思。**
> 但不是"Java 从入门到放弃"那种压缩版 —— `if`、`for`、`while`、`switch` 我一句话带过，你写了五年 Go，这些你看一眼就懂。
>
> 这一章真正的篇幅，全给**"看起来你懂了其实你会踩坑"**的地方。

---

## 1.1 先把那个最扎眼的问题解决了：为什么 Java 连 `main` 都要包在类里？

```java
package com.example.orderservice;

public class OrderApplication {
    public static void main(String[] args) {
        System.out.println("Hello, Java");
    }
}
```

Go 里你写：

```go
package main

func main() {
    fmt.Println("Hello, Go")
}
```

**第一个问题：**

> 为什么 Java 需要 `public static void main(String[] args)` 这么一长串？每一个关键字都是干嘛的？

拆开看：

| 部分 | 为什么必须 | Go 里对应 |
|---|---|---|
| `class OrderApplication` | Java 没有"游离的函数"，一切代码必须在类里 | 不需要 |
| `public` | JVM 要从外部调用这个方法 | Go 靠首字母大写 |
| `static` | **JVM 启动时还没有任何对象实例**，所以它只能调静态方法 | `main` 本身就是包级函数 |
| `void` | 返回值类型，显式声明 | Go 写在后面 |
| `String[] args` | 命令行参数，数组类型 | `os.Args` |

**关键在 `static`。** 这个概念 Go 里完全没有。

> 【思考】为什么 Java 需要 `static`？换句话说，`static` 方法跟普通方法的本质区别是什么？

<details>
<summary><b>参考答案</b></summary>

**普通（实例）方法有一个隐藏参数：`this`。**

```java
public class User {
    private String name;
    public String getName() {
        return this.name;   // this 是隐藏的第 0 号参数
    }
}
```

等价的 Go 写法（模拟）：

```go
type User struct{ name string }
func (u *User) GetName() string { return u.name }  // 接收者显式写出来
```

看到了吗？**Go 的"方法接收者"就是 Java 的 `this`，只不过 Go 把它显式写在了签名上。**

Java 把这个参数藏起来了。所以当你调用 `user.getName()`，JVM 实际上执行的是 `User.getName(user)` —— 把 `user` 作为第 0 号局部变量（aload_0）压进操作数栈。

那 `static` 方法就是：**没有 `this` 的方法**。它不属于任何实例，只属于类。

```java
public class MathUtils {
    public static int add(int a, int b) { return a + b; }
}
// 调用：MathUtils.add(1, 2)  不需要 new
```

**Go 里怎么表达"静态方法"？** —— 用包级函数。

```go
package mathutil
func Add(a, b int) int { return a + b }
```

所以 Go 的包级函数 ≈ Java 的 static 方法，Go 的带接收者的方法 ≈ Java 的实例方法。**Go 用两个语法结构表达了 Java 用 `static` 关键字区分的两种东西。**

**那为什么 `main` 必须是 static？**

因为 JVM 加载类之后，要调用 `main` 来启动程序。此时：
- 还没有 `new` 过任何对象
- 如果要调用实例方法，JVM 得先创建一个实例 —— 那要调哪个构造器？无参还是有参？参数从哪来？

所以 JVM 规范直接规定：`main` 必须是 `public static void main(String[])`。这是一个**约定**，不是语法要求 —— 你完全可以写一个叫 `main` 的非静态方法，只是 JVM 不认它作为入口。

**顺带一个坑**：`static` 方法里**不能**直接访问实例字段，因为没有 `this`。

```java
public class User {
    private String name;
    public static void printName() {
        System.out.println(name);   // 编译错误！non-static variable name cannot be referenced
    }
}
```

Go 里同样的问题不存在，因为你写包级函数时根本访问不到任何结构体的字段，编译器直接告诉你 `undefined: name`。

**更深一层**：`static` 是 Java"一切皆对象"这个设计的一个补丁。既然一切皆对象，那"不属于任何对象的函数"往哪放？答案是塞进类里，加个 `static` 标记。Go 从一开始就没打算"一切皆对象"，所以不需要这个补丁。
</details>

---

## 1.2 文件组织：Java 的包和 Go 的包，只是长得像

### 规则

```java
// 文件：src/main/java/com/example/order/OrderService.java
package com.example.order;    // 必须跟目录结构一致

import java.util.List;
import java.util.ArrayList;

public class OrderService { ... }
```

三条硬规则：

1. **一个文件只能有一个 `public` 类，且文件名必须跟类名完全一致**（包括大小写）
2. **`package` 声明必须跟磁盘目录结构一致**
3. 非 `public` 的类可以有多个（包级私有）

> 【思考】为什么 Java 要强制"文件名 = public 类名"？而在 Go 里，你一个包目录下可以放任意多个文件、任意多个类型，文件名随便叫。

<details>
<summary><b>参考答案</b></summary>

因为 **Java 编译器和 JVM 靠"类名 → 类文件"的确定性映射来找类**。

当你写：

```java
import com.example.order.OrderService;
```

或者代码里用全限定名 `com.example.order.OrderService` 时，javac 和 JVM 需要知道该去哪儿找这个类。它们的策略是：

```
classpath 根目录 + com/example/order/ + OrderService.class
```

这个映射是**硬编码在工具链里的**。如果允许一个文件里有多个 public 类、或者类名跟文件名不一致，那么"给我找 `com.example.OrderService`"这个请求就没法通过一次文件查找完成，必须遍历目录下所有 `.class` 文件去看里面有什么 —— 那会让类加载慢上几个数量级。

Go 为什么不需要这个规则？

因为 **Go 的编译单元是"包"，不是"文件"**。go build 时会把整个目录下所有 `.go` 文件一起编译成一个包，编译器在内存里建好了包级的符号表。所以文件名对 Go 毫无意义，只是给人看的组织方式。

**这个差异带来一个实际影响（你会经常遇到）：**

Java 里，一个"工具类"通常就是一个大类塞满 static 方法：

```java
// StringUtils.java
public class StringUtils {
    public static boolean isEmpty(String s) { ... }
    public static String join(String[] arr, String sep) { ... }
    // ... 200 个方法
}
```

而 Go 里，你会拆成若干个文件，按功能组织：`strings.go`、`strings_search.go`、`strings_replace.go`，都在 `strings` 包下。

**Java 的"一个 public 类一个文件"规则，客观上鼓励了"大类"。** 你想拆都拆不了 —— 除非拆成多个类（那就是不同的类型了）。

（顺带一提，这也是为什么 Lombok 这种"一个注解给你生成 50 个方法"的工具在 Java 里这么流行 —— 因为 Java 连 getter/setter 都要手写，一个 20 字段的 DTO 就是 200 行。Go 里 public 字段直接访问，没这个问题。第 02 章会讲 `record`，Java 16 之后这个问题被官方解决了。）
</details>

### import 的三种姿势

```java
import java.util.List;              // 精确导入
import java.util.*;                 // 通配导入（不推荐，且不影响性能）
import static java.util.Arrays.asList;  // 静态导入，之后可以直接写 asList(...)
```

**注意 `java.util.*` 和 Go 的差别**：Java 的通配导入**没有性能损失**，因为编译后 import 全部被替换成全限定名，字节码里根本没有 import 这个概念。它纯粹是一个"可读性"问题（看代码的人不知道 `List` 来自哪个包）。

**但有个真实的坑**：

```java
import java.util.Date;
import java.sql.Date;   // 编译错误：重复的类名
```

两个 `Date`，你必须用全限定名。Go 里靠 import 别名解决（`import sqlDate "database/sql"`），Java 里没有 import 别名，只能用全限定名。

---

## 1.3 类型系统：Java 有 8 种原始类型，Go 有……

这是第一个会让你觉得"Java 怎么这么麻烦"的地方。

### 原始类型（primitive types）

| Java | 位数 | Go 对应 |
|---|---|---|
| `byte` | 8 | `int8` / `byte` |
| `short` | 16 | `int16` |
| `int` | 32 | `int` / `int32` |
| `long` | 64 | `int64` |
| `float` | 32 | `float32` |
| `double` | 64 | `float64` |
| `char` | 16（UTF-16 码元） | `rune`(32) / `byte`(8) |
| `boolean` | JVM 规范未定义 | `bool` |

**关键点一：这 8 种不是对象，没有方法，不能 `new`。**

```java
int x = 5;
// x.toString();  // 编译错误
```

**关键点二（这是重灾区）：每个原始类型都有一个"包装类"。**

```java
Integer a = 5;      // 自动装箱 auto-boxing：Integer.valueOf(5)
int b = a;          // 自动拆箱 auto-unboxing：a.intValue()
```

> 【思考】下面这段代码输出什么？为什么？

```java
Integer a = 127;
Integer b = 127;
System.out.println(a == b);    // ?

Integer c = 128;
Integer d = 128;
System.out.println(c == d);    // ?

Integer e = 128;
int f = 128;
System.out.println(e == f);    // ?
```

<details>
<summary><b>参考答案</b></summary>

答案是：`true`、`false`、`true`。

**第一个 `true`：`Integer` 缓存。**

`Integer.valueOf(int)` 的实现是这样的：

```java
public static Integer valueOf(int i) {
    if (i >= IntegerCache.low && i <= IntegerCache.high)   // 默认 [-128, 127]
        return IntegerCache.cache[i + (-IntegerCache.low)];
    return new Integer(i);
}
```

JVM 启动时就预先创建了 -128 ~ 127 这 256 个 `Integer` 对象放在缓存数组里。所以 `Integer a = 127` 和 `Integer b = 127` 拿到的是**同一个对象**，`==` 比较引用，相等。

上限 127 可以通过 `-XX:AutoBoxCacheMax=<size>` 调整。

**第二个 `false`：超出缓存范围。**

128 不在缓存范围内，所以 `valueOf(128)` 每次 `new` 一个新对象。`c` 和 `d` 是两个不同的对象，`==` 比较引用地址，不相等。

**这就是为什么 Java 里比较包装类型必须用 `.equals()`：**

```java
Integer c = 128;
Integer d = 128;
System.out.println(c.equals(d));   // true
```

**第三个 `true`：一边是包装类，一边是原始类型时，会自动拆箱。**

`e == f` 中，`f` 是 `int`，所以 `e` 被拆箱成 `int` 再比较值 → `128 == 128` → `true`。

**Java 的 `==` 规则总结（这是面试重灾区，也是真实 bug 来源）：**

| 左边 | 右边 | `==` 比较的是 |
|---|---|---|
| 原始类型 | 原始类型 | **值** |
| 原始类型 | 包装类型 | **值**（包装类型自动拆箱） |
| 包装类型 | 包装类型 | **引用地址** |

**NPE 陷阱（这个坑死了很多人）：**

```java
Integer count = null;   // 比如从数据库查出来是 NULL
if (count == 0) {       // NullPointerException！
    System.out.println("没有数据");
}
```

`count` 是 `Integer`，`0` 是 `int`，按规则要拆箱 → `count.intValue()` → NPE。

**正确写法**：

```java
if (count != null && count == 0) { }
// 或者
if (Integer.valueOf(0).equals(count)) { }
// 或者用 Optional（第 02 章）
if (Optional.ofNullable(count).orElse(0) == 0) { }
```

**Go 对照：**

Go 里没有装箱的概念，因为 Go 的值类型就是值类型，指针就是指针，不存在"自动转换"。

```go
var a int = 127
var b *int = &a   // 显式取地址，没有任何隐式行为
```

Go 的哲学是"显式优于隐式"。Java 的自动装箱是为了解决"泛型不支持原始类型"这个历史遗留问题（`List<int>` 非法，必须 `List<Integer>`），付出了语义模糊的代价。

顺带说一句，**这正是 Valhalla 项目（Java 的泛型特化）要解决的问题** —— 让 `List<int>` 合法，避免装箱开销。这个项目从 2014 年立项，到现在（Java 21）还在孵化器里。可见历史包袱有多重。

**真实事故案例**：

某电商系统的优惠券逻辑：

```java
// 从 Redis 拿到的可能是 null
Integer discount = redisTemplate.opsForValue().get(key);
if (discount > 0) {   // NPE，整个下单流程挂掉
    applyDiscount(discount);
}
```

`>` 运算符也要拆箱。这类 bug 的特点是：**测试环境数据完整，永远走不到 null 分支，一上线就炸。**
</details>

### 字符串：Java 和 Go 都不可变，但 Java 有个"池"

```java
String s = "hello";
s = s + " world";   // 创建了新对象，原来的 "hello" 没变
```

跟 Go 一样，`String` 不可变。但 Java 多了一个概念：**字符串常量池（String Pool）**。

```java
String a = "hello";           // 从常量池取
String b = "hello";           // 同一个对象
String c = new String("hello");  // 强制在堆上 new 一个

System.out.println(a == b);       // true
System.out.println(a == c);       // false
System.out.println(a.equals(c));  // true
```

> 【思考】为什么 Java 要搞一个字符串常量池？Go 为什么不需要？

<details>
<summary><b>参考答案</b></summary>

**因为 Java 程序里字符串字面量的数量极其庞大，而且大量重复。**

想想一个典型的 Spring Boot 项目：Bean 名字、配置项 key、日志消息、SQL 片段、JSON 字段名、注解里的字符串值…… 一个中型项目里可能有几十万个字符串字面量，其中大量是重复的（比如 `"id"` 出现几千次）。

如果每个字面量都创建一个新的 `String` 对象，堆内存会被这些短命的、重复的对象塞满。

**常量池的做法**：类加载时，把所有字符串字面量放进一个全局的哈希表（StringTable），内容相同的字面量共享同一个对象。

这个机制在 Java 7 之前放在永久代（PermGen），Java 7 之后移到了堆里。可以用 `-XX:StringTableSize` 调整桶数量（默认 60013，JDK 8+）。

**Go 为什么不需要？**

1. **Go 的字符串字面量在编译期就被放进了只读数据段（.rodata）**，多个相同的字面量编译器会自动合并（这个优化叫 string interning，Go 编译器做了一部分）。运行时字符串是 `{指针, 长度}` 的二元组，指向 `.rodata`，天然共享。

2. **Go 的字符串是值类型**（一个 16 字节的结构体），赋值就是拷贝指针和长度，不涉及"对象"的概念，也就不需要"对象复用"。

3. **Go 没有"运行时创建类、加载类"这种动态性**（除了 plugin，用得极少），所以字符串字面量的集合在编译期就确定了，编译器可以做全局优化。

**Java 需要常量池，本质上还是因为它有"运行时动态性"** —— 类可以在运行时被加载（ClassLoader 从网络、从数据库、从任意地方读字节码），字符串可以在运行时被 `intern()`：

```java
String s = new String("hello").intern();   // 主动放进常量池，返回池中引用
```

这个 `intern()` 曾经是性能优化的常用手段（尤其在处理大量重复字符串时，比如从 CSV 读取百万行数据），但现代 JVM 里要小心 —— StringTable 是全局的，且有 GC 开销，滥用会适得其反。

**实用建议**：
- 业务代码里**永远不要用 `==` 比较字符串**，用 `.equals()`。这是 Java 第一条铁律。
- 更安全的写法：`Objects.equals(a, b)` 或者 `"literal".equals(variable)`（把字面量放前面，避免 NPE）
- 大量字符串拼接用 `StringBuilder`，不要 `+`（编译器对单行 `+` 会优化，但循环里不会）
</details>

---

## 1.4 数组、集合：Go 的 slice 在 Java 里叫什么？

这是 Go 程序员最容易懵的地方之一。

### Java 的数组是"定长"的

```java
int[] arr = new int[5];        // 长度 5，不能改
arr[0] = 1;
// arr[5] = 2;                 // ArrayIndexOutOfBoundsException
```

**Java 的数组 ≠ Go 的 slice。** Java 的数组更像 Go 的**数组**（`[5]int`）—— 长度是类型的一部分（虽然不写在类型声明里）。

那 Go 的 slice（`[]int`，可以 append）在 Java 里对应什么？

**`ArrayList`。**

```java
List<Integer> list = new ArrayList<>();
list.add(1);
list.add(2);
int size = list.size();
Integer first = list.get(0);
list.remove(0);
```

> 【思考】`ArrayList` 的底层是什么？它跟 Go 的 slice 扩容策略有什么不同？为什么 Java 里要写 `new ArrayList<>()` 而不是像 Go 那样 `make([]int, 0, 10)`？

<details>
<summary><b>参考答案</b></summary>

**底层就是一个 `Object[]` 数组 + `size` 字段。**

```java
// 简化版 ArrayList 核心
public class ArrayList<E> {
    transient Object[] elementData;   // 真正存数据的数组
    private int size;                  // 实际元素个数（<= elementData.length）

    public boolean add(E e) {
        ensureCapacityInternal(size + 1);   // 可能需要扩容
        elementData[size++] = e;
        return true;
    }
}
```

**扩容策略对比：**

| | Go slice | Java ArrayList |
|---|---|---|
| 初始容量 | `make([]T, 0, n)` 可指定 | 默认 10（懒初始化，第一次 add 才分配） |
| 扩容倍数 | < 256 时 2 倍，>= 256 时 1.25 倍 | **固定 1.5 倍**（`old + (old >> 1)`） |
| 扩容动作 | 分配新数组 + `copy` | `Arrays.copyOf`（底层 `System.arraycopy`，native 方法） |
| 缩容 | 从不自动缩容 | 从不自动缩容（`trimToSize()` 可手动） |

**为什么是 1.5 倍而不是 2 倍？**

这是一个内存利用率的权衡：

- 2 倍扩容：扩容次数少（O(log n) 次拷贝），但**浪费空间多**。最坏情况下，刚扩容后只用了 50% 的容量。
- 1.5 倍扩容：扩容次数稍多，但**内存碎片更少**，且旧的空闲块更容易被后续扩容复用。

理论上 1.5 倍有个额外的好处（虽然 JVM 的实现可能没利用）：按 1.5 倍增长时，前面释放掉的旧数组加起来，有可能容纳下一次扩容需要的空间，从而提高本地缓存命中率。

**跟 Go 的 `[]T` 最重要的语义差别：**

Go 的 slice 是 `{ptr, len, cap}` 的三元组，**值传递**。所以：

```go
func add(s []int) {
    s = append(s, 4)   // 如果触发扩容，调用方的 s 完全不知情
}
```

这个坑 Go 程序员都知道。

Java 的 `ArrayList` 是**引用类型**，传递的是引用副本：

```java
void add(List<Integer> list) {
    list.add(4);   // 调用方的 list 确实变了
}
```

因为 Java 里所有非原始类型都是"引用"（本质是指针，但没有指针运算），方法参数传递的是引用的拷贝。**修改对象的内容会影响到调用方，但重新赋值不会**：

```java
void replace(List<Integer> list) {
    list = new ArrayList<>();   // 只改了局部的引用副本，调用方不受影响
}
```

**Go 里的等价物**：传 `*[]T` 或者返回新 slice。Java 里就是传引用值（自动的）。

**实用建议（Go 程序员容易写错的）：**

```java
// 错误：在遍历中删除元素
for (Integer item : list) {
    if (item < 0) {
        list.remove(item);   // ConcurrentModificationException !
    }
}
```

这是 Java 的 **fail-fast** 机制：`ArrayList` 内部有个 `modCount` 计数器，每次结构性修改（add/remove）都会 +1。迭代器创建时会记录 `expectedModCount`，遍历时检查两者是否一致，不一致就抛异常。

目的是**尽早暴露并发修改的 bug**，而不是让迭代器产生未定义行为。

**正确写法有三种：**

```java
// 1. 用迭代器的 remove 方法
Iterator<Integer> it = list.iterator();
while (it.hasNext()) {
    if (it.next() < 0) it.remove();
}

// 2. Java 8+ ：removeIf
list.removeIf(item -> item < 0);

// 3. Stream 过滤，生成新 list
List<Integer> filtered = list.stream()
                             .filter(item -> item >= 0)
                             .collect(Collectors.toList());
```

**Go 里为什么没这个问题？** 因为 Go 的 `for range` 遍历的是 slice 的**副本**（那个三元组的副本），你一边遍历一边 append，遍历的还是原来的长度。Go 选择了"静默地做最不容易崩的事"，Java 选择了"大声报错"。这又是两种哲学的体现。
</details>

### 集合框架全家桶（速查）

这是 Java 里你每天都要用的东西，一张表看明白：

| 接口 | 实现类 | 特点 | Go 对应 |
|---|---|---|---|
| `List` | `ArrayList` | 数组，随机访问快 | `[]T`（切片） |
| | `LinkedList` | 双向链表，几乎不用 | `container/list` |
| | `CopyOnWriteArrayList` | 读多写少，写时复制 | 无（需自己加锁） |
| `Set` | `HashSet` | 哈希表，无序 | `map[T]struct{}` |
| | `LinkedHashSet` | 保持插入顺序 | 无 |
| | `TreeSet` | 红黑树，有序 | 无（需自己实现） |
| `Map` | `HashMap` | 哈希表，无序 | `map[K]V` |
| | `LinkedHashMap` | 保持插入顺序（**LRU 缓存的基础**） | 无 |
| | `TreeMap` | 红黑树，按 key 排序 | 无 |
| | `ConcurrentHashMap` | 线程安全，分段锁/CAS | `sync.Map` |
| `Queue` | `ArrayBlockingQueue` | 有界阻塞队列 | `chan`（有缓冲） |
| | `LinkedBlockingQueue` | 可选有界 | `chan` |
| | `SynchronousQueue` | 零容量，直接交接 | `chan`（无缓冲） |
| | `PriorityQueue` | 堆 | `container/heap` |

**几个要点：**

1. **`HashMap` 的 key 必须正确实现 `hashCode()` 和 `equals()`**。如果你用自定义对象做 key 而没重写这两个方法，会导致"存进去了取不出来"。Go 里 map 的 key 必须是 comparable 类型，编译器强制；Java 里是运行时约定，忘了就出 bug。

2. **`HashMap` 非线程安全，多线程 put 可能死循环**（JDK 7 的经典问题，因为扩容时链表头插法会成环）。JDK 8 改成了尾插法，解决了死循环，但仍有数据丢失问题。并发场景用 `ConcurrentHashMap`。

3. **`LinkedHashMap` 有个隐藏技能**：构造时传 `accessOrder=true`，就变成 LRU 缓存：

```java
Map<String, Object> lruCache = new LinkedHashMap<>(16, 0.75f, true) {
    @Override
    protected boolean removeEldestEntry(Map.Entry<String, Object> eldest) {
        return size() > 1000;   // 超过 1000 个就淘汰最久未访问的
    }
};
```

这是 Java 里实现 LRU 最简洁的方式，很多框架内部就这么干。

---

## 1.5 面向对象：Java 的"继承"是 Go 没有的东西

### 类、继承、多态

```java
public class Animal {
    protected String name;

    public Animal(String name) { this.name = name; }

    public void speak() {
        System.out.println("...");
    }
}

public class Dog extends Animal {
    public Dog(String name) {
        super(name);            // 必须第一行调用父类构造器
    }

    @Override                    // 注解，不是关键字，但强烈建议加
    public void speak() {
        System.out.println(name + " says woof");
    }
}
```

Go 的等价物是**组合 + 嵌入**：

```go
type Animal struct{ Name string }
func (a *Animal) Speak() { fmt.Println("...") }

type Dog struct {
    *Animal                      // 嵌入，方法提升
}
func (d *Dog) Speak() { fmt.Println(d.Name + " says woof") }  // 覆盖
```

> 【思考】Java 的 `extends` 和 Go 的嵌入（embedding），最本质的区别是什么？提示：想想"方法调用的分派时机"和"父类能不能调用子类的方法"。

<details>
<summary><b>参考答案</b></summary>

**最本质的区别：Java 的继承是"is-a"的语义关系 + 动态分派，Go 的嵌入只是"语法糖 + 静态转发"。**

**区别一：分派时机和方向**

Java 的继承会发生**向下调用**：

```java
public abstract class HttpServlet {
    public void service(Request req, Response resp) {
        if (req.getMethod().equals("GET")) {
            doGet(req, resp);      // 调用的是子类的 doGet！
        }
    }
    protected void doGet(Request req, Response resp) { /* 默认实现 */ }
}

public class MyServlet extends HttpServlet {
    @Override
    protected void doGet(Request req, Response resp) {
        // 被父类的 service() 调用了
    }
}
```

`service()` 是父类的方法，但它调用的 `doGet()` 会分派到子类的实现。这叫**虚方法分派（virtual dispatch）**，是"模板方法模式"的基础。

**Go 里做不到这一点。** 嵌入的方法提升是**编译期的静态转发**：

```go
type Base struct{}
func (b *Base) Service() {
    b.DoGet()      // 永远调用 *Base 的 DoGet，不会分派到"子类"
}
func (b *Base) DoGet() { ... }

type Derived struct{ *Base }
func (d *Derived) DoGet() { ... }   // Base.Service() 永远调不到这里
```

`Base.Service()` 里的 `b.DoGet()` 中 `b` 是 `*Base`，编译期就绑定了，运行时不会变。

**这是 Go 没有继承的真正含义** —— 不是"不能复用代码"（嵌入可以复用），而是**不能做"父类定义流程骨架，子类填充具体步骤"这种设计**。

（Go 里要模拟，得用函数字段或接口：
```go
type Handler struct {
    DoGet func(req *Request, resp *Response)
}
```
这就是"组合优于继承"的实践 —— 但代价是你得自己设计这套结构。）

**区别二：类型转换和类型断言**

Java 里，子类引用可以**自动向上转型**（upcasting），父类引用要向下转型（downcasting）必须显式且会运行时检查：

```java
Animal a = new Dog("旺财");      // upcast，自动，永远安全
Dog d = (Dog) a;                  // downcast，运行时检查，失败抛 ClassCastException
if (a instanceof Dog) {           // 安全写法
    Dog d2 = (Dog) a;
}
// Java 16+ 的模式匹配：
if (a instanceof Dog d3) {        // 直接绑定变量
    d3.fetch();
}
```

Go 里没有自动向上转型。`*Dog` 和 `*Animal` 是两个完全无关的类型，你要用接口来抽象：

```go
var a Speaker = &Dog{...}          // 接口赋值
if d, ok := a.(*Dog); ok { ... }   // 类型断言
```

**区别三：字段阴影 vs 方法重写**

Java 里字段**没有多态**：

```java
Animal a = new Dog("旺财");
System.out.println(a.name);   // 访问的是 Animal.name，不是 Dog.name！
```

如果 Dog 也定义了 `name` 字段，通过 `Animal` 引用访问到的是父类的字段。这叫**字段隐藏（field hiding）**，是 Java 的一个著名陷阱。

Go 的嵌入里，如果外层和内层有同名字段，外层优先（就近原则），语义更直观：

```go
d.Name        // Derived.Name（如果 Derived 有 Name 字段）
d.Animal.Name // 显式访问内层的
```

**一句话总结对读代码的影响：**

读 Java 项目时，看到 `service.doSomething()`，你必须意识到：**这个 `doSomething` 可能不是 `service` 这个对象所属类里定义的，而是某个子类的实现**。你得顺着继承链往下找。

这就是为什么 Java 项目里 IDE 的 "Go to Implementation" 比 "Go to Definition" 用得多 —— **定义可能不是你实际执行的代码**。

而 Go 里，`d.Speak()` 要么是 `Dog` 自己的方法，要么是被提升的嵌入方法，编译期就确定了。看代码时能确定的东西更多。
</details>

### 抽象类和接口

```java
// 抽象类：可以有状态、有构造方法、有已实现的方法
public abstract class AbstractOrderService implements OrderService {
    protected final OrderRepository repository;

    protected AbstractOrderService(OrderRepository repository) {
        this.repository = repository;
    }

    public Order findById(Long id) {   // 已实现
        return repository.findById(id).orElseThrow(...);
    }

    public abstract void pay(Order order);   // 留给子类
}

// 接口：Java 8 之后可以有 default 和 static 方法
public interface OrderService {
    Order findById(Long id);

    default void cancel(Long id) {     // 默认实现，实现类可以不重写
        Order o = findById(id);
        o.setStatus(CANCELLED);
    }

    static OrderService noop() {       // 静态工厂方法
        return id -> null;
    }
}
```

**Java 的接口在 Java 8 之后有了三个新能力：**

| 能力 | 语法 | 为什么加 |
|---|---|---|
| default 方法 | `default void foo() {...}` | 接口演进：加方法不破坏已有实现类（为了 Stream API 能加进 `Collection`） |
| static 方法 | `static X of() {...}` | 工厂方法、工具方法 |
| 私有方法（Java 9） | `private void helper() {...}` | default 方法之间复用代码 |

**函数式接口（Functional Interface）**：只有一个抽象方法的接口，可以用 lambda 实现。

```java
@FunctionalInterface    // 编译器会检查，多于一个抽象方法就报错
public interface OrderProcessor {
    void process(Order order);
}

// lambda
OrderProcessor p = order -> System.out.println(order.getId());
// 方法引用
OrderProcessor p2 = System.out::println;
```

Java 内置了一堆函数式接口，基本覆盖所有场景：

| 接口 | 签名 | 用途 |
|---|---|---|
| `Function<T,R>` | `R apply(T t)` | 转换 |
| `Consumer<T>` | `void accept(T t)` | 消费（有副作用） |
| `Supplier<T>` | `T get()` | 提供（无参产生值） |
| `Predicate<T>` | `boolean test(T t)` | 判断 |
| `UnaryOperator<T>` | `T apply(T t)` | 一元运算 |
| `BiFunction<T,U,R>` | `R apply(T t, U u)` | 二元函数 |
| `Runnable` | `void run()` | 无参无返回 |

**注意**：这些接口的原始类型特化版本（`IntFunction`、`ToLongFunction` 等）是为了避免装箱开销。所以你会在源码里看到 `IntStream` 而不是 `Stream<Integer>`。

---

## 1.6 泛型：先知道怎么用，第 03 章讲为什么

```java
List<String> list = new ArrayList<>();   // <> 是菱形语法，Java 7+
Map<String, List<Order>> index = new HashMap<>();

// 泛型方法
public static <T> List<T> filter(List<T> list, Predicate<T> p) {
    return list.stream().filter(p).collect(Collectors.toList());
}

// 泛型类
public class Result<T> {
    private T data;
    private String error;
}

// 边界
public class Repository<T extends BaseEntity> { ... }   // 上界
public <T super Order> void add(T order) { ... }        // 下界（用于写入）
```

**Java 泛型 vs Go 泛型（1.18+）的关键差异：**

| | Java | Go |
|---|---|---|
| 实现机制 | **类型擦除**（编译后变 `Object` + 强制转换） | **单态化 + 字典**（GCC 生成多份代码，或运行时传字典） |
| 运行时类型信息 | 丢失（`list instanceof List<String>` 非法） | 保留（可通过反射获取） |
| 原始类型支持 | **不支持**（`List<int>` 非法，必须 `Integer`） | 支持（`[]int`） |
| 方法可以有自己的类型参数 | 支持（`<T> T foo(T t)`） | 不支持（只能定义在类型上） |
| 性能 | 有装箱开销 + 强制转换开销 | 特化版本无开销 |

> 【思考】为什么 Java 选了"类型擦除"，而 Go/C++/Rust 都选了"代码生成"？是 Java 设计失误吗？

（这题的完整答案在第 03 章，这里先给你一个引子：Java 引入泛型是 2004 年（Java 5），当时有几十亿行 Java 代码在跑，JVM 规范不可能为了泛型改字节码格式 —— 否则所有老代码都跑不了了。**擦除是为了向后兼容做的妥协，不是设计失误。** 代价就是 `List<String>` 和 `List<Integer>` 在运行时是同一个类。）

---

## 1.7 异常：Go 程序员最不适应的部分

```java
// 定义
public class OrderNotFoundException extends RuntimeException {
    public OrderNotFoundException(Long id) {
        super("Order not found: " + id);
    }
}

// 抛出
public Order findById(Long id) {
    return repository.findById(id)
        .orElseThrow(() -> new OrderNotFoundException(id));
}

// 捕获
try {
    order = findById(id);
} catch (OrderNotFoundException e) {
    log.warn("订单不存在: {}", id);
    return null;
} catch (Exception e) {
    log.error("未知错误", e);   // 注意：e 放最后一个参数，会打印完整栈
    throw e;
} finally {
    // 一定会执行（除非 System.exit 或 JVM 崩溃）
}
```

### Checked vs Unchecked

```
Throwable
├── Error                  ← JVM 层面的严重问题，不要 catch
│   ├── OutOfMemoryError
│   ├── StackOverflowError
│   └── NoClassDefFoundError
└── Exception
    ├── RuntimeException   ← Unchecked，编译器不强制处理
    │   ├── NullPointerException
    │   ├── IllegalArgumentException
    │   ├── IllegalStateException
    │   └── IndexOutOfBoundsException
    └── 其他 Exception      ← Checked，编译器强制处理
        ├── IOException
        ├── SQLException
        └── InterruptedException
```

**规则（争议很大，但这是事实）：**

- **Checked exception 必须被 catch 或声明 throws**，否则编译不过
- **Unchecked exception（RuntimeException 及其子类）不强制**
- **Error 不应该被 catch**（OOM 之后程序状态已经不可信了）

> 【思考】现代 Java 项目（尤其是 Spring 生态）里，几乎所有人都在用 Unchecked exception，Checked exception 被大量抛弃。为什么？

<details>
<summary><b>参考答案</b></summary>

核心原因有三个，一个比一个致命。

**原因一：Checked exception 会"污染"整个调用链。**

假设你有一个数据访问方法抛 `SQLException`（Checked）：

```java
public Order findById(Long id) throws SQLException { ... }
```

调用它的 Service 要么 catch（但 Service 层不知道该怎么处理一个 SQL 错误），要么继续 throws：

```java
public OrderDTO getOrder(Long id) throws SQLException { ... }
```

Controller 也一样：

```java
@GetMapping("/order/{id}")
public OrderDTO getOrder(@PathVariable Long id) throws SQLException { ... }
```

**结果：一个底层实现细节（用了 JDBC）泄漏到了最上层。** 哪天你把 JDBC 换成 MyBatis 或者 JPA，抛的异常类型变了，所有方法签名都要改。

这就是为什么 Java 社区发明了"异常转译"：

```java
public Order findById(Long id) {
    try {
        return jdbcTemplate.query(...);
    } catch (SQLException e) {
        throw new DataAccessException("查询订单失败", e);   // 转成自己的 Unchecked 异常
    }
}
```

Spring 的整个异常体系就是这么干的 —— Spring 把 JDBC、Hibernate、JMS 等所有框架的 Checked 异常，统一转成了 `DataAccessException`（继承自 `RuntimeException`）。

**你发现问题了吗？** 如果最终都要转成 Unchecked，那中间那些 Checked 声明就纯属噪音。

**原因二：Checked exception 跟 lambda 和函数式接口冲突。**

这是技术上的硬伤。`Function<T, R>` 的签名是：

```java
R apply(T t);   // 没有 throws
```

所以你没法写一个抛 Checked exception 的 lambda：

```java
list.stream().map(item -> {
    return parseJson(item);   // 如果 parseJson 抛 IOException，编译错误！
});
```

你被迫包一层：

```java
list.stream().map(item -> {
    try {
        return parseJson(item);
    } catch (IOException e) {
        throw new RuntimeException(e);   // 丑
    }
});
```

Go 里完全没这个问题，因为 Go 的 error 就是返回值的一部分，函数类型签名里天然包含 `error`。

**Java 的异常是"类型系统之外的第二套错误处理机制"，而 lambda 的类型签名只描述了"正常返回"的类型，描述不了异常。** 这是设计上的结构性缺陷。

（有意思的是，这也是为什么 Kotlin 直接取消了 Checked exception —— Kotlin 的设计者明确说这是 Java 的一个错误。）

**原因三：Checked exception 鼓励坏的编码习惯。**

因为编译器强制你处理，而很多开发者其实不知道怎么处理，于是：

```java
try {
    doSomething();
} catch (Exception e) {
    // TODO: 以后处理        ← 最常见的
}

// 或者更糟
try {
    doSomething();
} catch (Exception e) {
    e.printStackTrace();    // 打印到 stderr，不进日志系统，没人看得到
}
```

**一个"强制你处理错误"的机制，最终导致大量错误被静默忽略。** 这不是有点讽刺吗？

Go 的 `if err != nil` 虽然啰嗦，但至少你**看见**了它，写 `_ = f()` 是你主动的选择。

**那 Java 现在的实践是什么？**

1. **业务异常用 Unchecked**（继承 `RuntimeException`），比如 `OrderNotFoundException`、`InsufficientBalanceException`
2. **在框架边界统一处理**（Spring 的 `@ControllerAdvice` + `@ExceptionHandler`）
3. **系统级异常也转译**，带上上下文（`throw new ServiceException("下单失败, orderId=" + id, e)`）
4. **永远保留 cause 链**：`new MyException(msg, e)` 而不是 `new MyException(msg)`
5. **不要用异常做流程控制**（性能问题，见第 00 章）

**Go 对照**：Go 的答案是"让 error 成为一等公民"，Java 的答案是"放弃 Checked，靠规范约束"。前者更严格，后者更灵活。

**一个真实的判断标准**：如果你写一个库，用 Checked 还是 Unchecked？

答案是：**如果调用方"有能力恢复"，用 Checked（比如 `IOException`，调用方可以重试）；如果调用方"无能为力"，用 Unchecked（比如 `IllegalArgumentException`，这是调用方的 bug）。**

Spring 选了全 Unchecked，因为在一个 Web 请求里，大部分异常都是"这个请求失败了，返回 500"，统一处理比逐层处理更合理。
</details>

---

## 1.8 注解：Java 的"元数据"，Go 里的 struct tag 的加强版

```java
@Override
public String toString() { ... }

@Deprecated
public void oldMethod() { ... }

@SuppressWarnings("unchecked")
public void legacy() { ... }

@Service
@Transactional(readOnly = true)
public class OrderServiceImpl implements OrderService { ... }
```

**注解是什么？** 本质是一个**继承了 `java.lang.annotation.Annotation` 的接口**，加上一些"元注解"描述它的行为。

```java
@Target(ElementType.METHOD)              // 能加在哪儿
@Retention(RetentionPolicy.RUNTIME)      // 保留到什么时候
@Documented
@Inherited
public @interface AuditLog {
    String value() default "";           // 属性，有默认值
    String[] tags() default {};
    boolean async() default false;
}
```

**三个关键元注解：**

| 元注解 | 作用 |
|---|---|
| `@Target` | 限制能标注的位置（TYPE/METHOD/FIELD/PARAMETER/CONSTRUCTOR/...） |
| `@Retention` | **SOURCE**（编译后丢弃，如 `@Override`）/ **CLASS**（保留到 class 文件，但运行时不可读）/ **RUNTIME**（运行时可通过反射读取，**框架全靠这个**） |
| `@Inherited` | 子类是否继承父类的注解 |

> 【思考】`@Override` 的 Retention 是什么？为什么？而 `@Transactional` 的 Retention 是什么？为什么？

<details>
<summary><b>参考答案</b></summary>

**`@Override` 是 `SOURCE`** —— 它只在编译期有意义。

编译器看到 `@Override` 会检查：这个方法真的重写了父类的方法吗？如果不是（比如你拼错了方法名，或者参数类型不对），编译报错。

一旦编译通过，这个注解的使命就完成了，**没必要留在 class 文件里** —— 留着只会浪费空间，且运行时没人会去读它。

类似的还有 `@SuppressWarnings`（告诉编译器别警告某个问题）、Lombok 的 `@Data`（编译期生成 getter/setter，编译完就没了）。

**`@Transactional` 是 `RUNTIME`** —— 它必须在运行时可读。

因为 Spring 是这么工作的：

1. 容器启动时，扫描所有 Bean
2. 用反射检查这个类/方法上有没有 `@Transactional`
3. 如果有，就为这个 Bean 创建一个**代理对象**（JDK 动态代理或 CGLIB）
4. 把代理对象放进容器，替换掉原始对象
5. 你调用 `service.pay(order)` 时，实际调用的是代理对象的方法，代理在调用前后开启/提交事务

**如果 `@Transactional` 是 SOURCE 或 CLASS，Spring 在运行时就看不见它，事务就不会生效。**

**这解释了一个著名的坑**：

```java
@Service
public class OrderService {

    public void batchPay(List<Long> ids) {
        for (Long id : ids) {
            this.pay(id);      // ← 事务不生效！
        }
    }

    @Transactional
    public void pay(Long id) { ... }
}
```

`batchPay` 调用 `this.pay()`，`this` 是**原始对象**而不是代理对象（代理对象的引用在容器里，通过 `@Autowired` 注入进来的那个才是代理）。所以 `@Transactional` 的逻辑被完全绕过。

（第 14 章会详细讲这个，包括几种解决方案。这里先埋个雷。）

**对比 Go：**

Go 的 struct tag 也是元数据，但有三个根本限制：

1. **只能是字符串**，没有结构化（Java 注解有类型：`String[] tags()`、`boolean async()`）
2. **只能加在结构体字段上**（Java 注解可以加在类、方法、参数、局部变量、包、类型参数上）
3. **只能在编译期确定**（Java 注解可以有默认值，可以被继承，可以在运行时组合查询）

所以 Go 里做 ORM、做序列化，都得靠解析 tag 字符串：

```go
type Order struct {
    ID     int64  `json:"id" db:"id" validate:"required"`
    Amount int64  `json:"amount" db:"amount"`
}
```

Java 里是：

```java
public class Order {
    @JsonProperty("id")
    @Column(name = "id")
    @NotNull
    private Long id;
}
```

Java 的写法更啰嗦，但**类型安全**（写错属性名编译不过）、**可被 IDE 检查**、**可以带复杂结构**（注解里可以嵌套注解数组）。

**这就是 Java "运行时元数据"的价值** —— 它让框架可以在不改你代码的前提下，给你的类加上序列化、校验、事务、缓存、监控等能力。Go 要达到同样效果，只能靠代码生成（在编译前生成额外代码）。

**代价**：这些"魔法"让代码变得难以追踪。第 15 章会教你如何把这些魔法还原成显式的调用链。
</details>

---

## 1.9 反射：Java 的"运行时自省"，以及它的代价

```java
Class<?> clazz = Order.class;              // 方式一：类字面量
Class<?> clazz2 = order.getClass();        // 方式二：实例
Class<?> clazz3 = Class.forName("com.example.Order");  // 方式三：字符串（框架最爱）

// 拿到所有字段
Field[] fields = clazz.getDeclaredFields();
Field nameField = clazz.getDeclaredField("name");
nameField.setAccessible(true);             // 突破 private（Java 9+ 模块系统可能阻止）
nameField.set(order, "new value");

// 拿到方法并调用
Method m = clazz.getMethod("setAmount", long.class);
m.invoke(order, 100L);

// 注解
Transactional tx = clazz.getMethod("pay").getAnnotation(Transactional.class);
boolean readOnly = tx.readOnly();
```

**Go 的 reflect 对照：**

| 能力 | Java 反射 | Go reflect |
|---|---|---|
| 获取类型信息 | ✅ | ✅ |
| 获取字段/方法 | ✅ | ✅ |
| 修改私有字段 | ✅（`setAccessible`） | ❌（unsafe 才行） |
| 动态调用方法 | ✅ | ✅ |
| 读取注解 | ✅ | 只能读 struct tag 字符串 |
| 运行时创建类 | ✅（动态代理、字节码生成） | ❌ |
| 获取方法参数**名** | ⚠️（需 `-parameters` 编译参数） | ❌ |
| 性能 | 慢（JIT 后约慢 2-5 倍） | 慢（约慢 10-100 倍） |

> 【思考】Spring 大量使用反射，那 Spring 应用的启动慢、运行慢，是不是反射的锅？

<details>
<summary><b>参考答案</b></summary>

**一半是，一半不是。要分开看。**

**启动慢：确实是反射的锅（部分）。**

Spring 启动时要做：
1. **classpath 扫描**：遍历 jar 包找候选类。这个是 IO + 解压，不全是反射
2. **读取类的元数据**：用 ASM 直接读字节码（**注意：Spring 用的是 ASM 字节码分析，不是反射**）。为什么不用反射？因为反射会触发类的加载和验证（`Class.forName` 会执行静态初始化），而 ASM 只读字节码不加载类，快得多
3. **创建 Bean 实例**：用反射调构造器。这一步确实慢
4. **依赖注入**：反射设置字段 / 调用 setter
5. **创建代理**：生成代理类的字节码（JDK Proxy 或 CGLIB/ByteBuddy）

所以，**反射是启动慢的一个因素，但不是最大的**。更大的因素是：
- classpath 里有几百个 jar、几万个类要扫
- 大量 Bean 要创建（有的项目上千个 Bean）
- 自动配置类要做大量条件判断（`@ConditionalOnClass` 等，每次都要尝试加载类看在不在）

**运行慢：基本不是反射的锅。**

这是很多人误解的地方。关键点在于：

**Spring 只在启动时用反射，运行时的调用路径上是普通方法调用。**

```java
@Service
public class OrderService {
    @Autowired
    private OrderRepository repo;   // 启动时反射注入一次

    public Order findById(Long id) {
        return repo.findById(id);   // 运行时：普通方法调用，零反射开销
    }
}
```

`repo` 在启动时被反射赋值一次，之后所有调用都是虚方法分派，**跟手写代码性能完全一样**。

**真正运行时有反射开销的是：**
- JSON 序列化/反序列化（Jackson 用反射读写字段，虽然它做了大量缓存优化）
- Bean 拷贝（`BeanUtils.copyProperties`）
- 动态代理的方法调用（`@Transactional`、`@Cacheable`、`@Async` 走代理，多一层方法调用）
- MyBatis 的结果集映射

**但 JVM 会优化反射！**

从 JDK 1.4 开始，`Method.invoke()` 有一个"膨胀"（inflation）机制：

```
前 15 次调用：走 native 版本（慢）
第 16 次开始：JVM 生成一个字节码版本的访问器（Accessor），之后调用接近直接调用的速度
```

阈值由 `-Dsun.reflect.inflationThreshold=15` 控制，可以用 `-Dsun.reflect.noInflation=true` 关闭膨胀（直接从第一次就生成访问器，但生成本身有成本）。

**所以"反射很慢"这句话的真实含义是：**

| 场景 | 是否慢 |
|---|---|
| 反射调用一次 | 慢（要查方法、检查权限、可能要生成访问器） |
| 反射调用一百万次（同一个 Method 对象） | **不慢**（膨胀后 JIT 会内联，接近直接调用） |
| 每次都重新 `getMethod()` 再 `invoke` | **很慢**（方法查找是 O(n) 遍历） |

**优化建议（写框架代码时必知）：**

```java
// 错误：每次都查
for (int i = 0; i < 1000000; i++) {
    Method m = obj.getClass().getMethod("foo");
    m.invoke(obj);
}

// 正确：缓存 Method 对象
Method m = obj.getClass().getMethod("foo");
for (int i = 0; i < 1000000; i++) {
    m.invoke(obj);
}

// 更好：用 MethodHandle（Java 7+）或 LambdaMetafactory（Java 8+）
MethodHandle mh = MethodHandles.lookup().findVirtual(Obj.class, "foo", methodType(void.class));
for (int i = 0; i < 1000000; i++) {
    mh.invokeExact(obj);   // JIT 可以完全内联，性能 = 直接调用
}
```

**这就是高性能框架的做法**：Jackson、Fastjson2、MyBatis 这些对性能敏感的库，要么缓存 Method，要么用 `LambdaMetafactory` 生成一个函数式接口的实例（等价于把反射调用变成直接调用）。

**Go 对照**：Go 的反射没有膨胀机制，所以 Go 的反射是真的慢。Go 生态的做法是**代码生成**（easyjson 为每种类型生成专用的序列化代码，比 `encoding/json` 快 3-5 倍）。Java 因为 JVM 会 JIT 优化，所以对反射的容忍度更高。

**一句话结论**：Spring 启动慢主要是"扫描 + 装配"的 IO 和对象创建成本，不是反射；Spring 运行慢通常是你的代码问题（N+1 查询、大对象、锁竞争），不是反射。
</details>

---

## 1.10 Lambda、方法引用、Stream：Java 的函数式子集

```java
// Lambda
Comparator<Order> byAmount = (a, b) -> Long.compare(a.getAmount(), b.getAmount());
Runnable r = () -> System.out.println("done");

// 方法引用（四种）
Function<Order, Long> f1 = Order::getAmount;       // 实例方法
Supplier<Order> f2 = Order::new;                    // 构造器
Function<String, Integer> f3 = Integer::parseInt;  // 静态方法
BiFunction<Order, Order, Integer> f4 = Order::compareTo;  // 特定对象的实例方法

// Stream
List<Long> ids = orders.stream()
    .filter(o -> o.getStatus() == PAID)
    .sorted(comparing(Order::getCreateTime).reversed())
    .map(Order::getId)
    .limit(100)
    .collect(Collectors.toList());
```

> 【思考】Java 的 lambda 和 Go 的闭包，实现上有什么不同？Java 的 lambda 里能修改外部局部变量吗？

<details>
<summary><b>参考答案</b></summary>

**先回答第二个问题：不能。Java 的 lambda 捕获的局部变量必须是 `final` 或"事实上 final"（effectively final）。**

```java
int count = 0;
orders.forEach(o -> {
    count++;   // 编译错误！Variable used in lambda expression should be final or effectively final
});
```

**为什么？** 因为 Java 的 lambda 捕获的是**值的副本**，不是变量的引用。

Java 的 lambda 在编译后会被转换成一个**静态方法**（invokedynamic 调用），捕获的变量作为方法参数传进去：

```java
// 源码
int base = 100;
Function<Integer, Integer> f = x -> x + base;

// 编译后大致等价于
private static Integer lambda$0(int base, Integer x) { return x + base; }
```

因为是按值传递，所以 lambda 内部改 `base` 不会影响外部，反之亦然。**Java 强制你声明 final，是为了避免"看起来能改其实改不了"的困惑。**

**Go 的闭包捕获的是变量本身（引用）：**

```go
count := 0
for _, o := range orders {
    go func() { count++ }()   // 真的会改外部的 count，且有数据竞争
}
```

Go 里这个著名的"循环变量捕获"坑（Go 1.22 之前）就是这么来的 —— 所有 goroutine 共享同一个 `i` 变量。

**所以这是两种截然不同的设计：**

| | Java lambda | Go 闭包 |
|---|---|---|
| 捕获方式 | **值捕获**（副本） | **引用捕获** |
| 能否修改外部变量 | 不能（编译错误） | 能（需自己加锁） |
| 数据竞争风险 | 低（捕获的是不可变副本） | 高 |
| 实现 | 编译成静态方法 + invokedynamic | 编译成闭包结构体（堆分配逃逸分析） |

**有意思的是**：Java 允许你修改捕获对象的**字段**，因为捕获的是"对象引用的副本"，引用指向的还是同一个对象：

```java
List<Long> result = new ArrayList<>();
orders.forEach(o -> result.add(o.getId()));   // 合法！改的是 result 指向的对象
```

这不是矛盾，因为 `result` 这个**引用**没变（还是指向同一个 ArrayList），变的是引用指向的**对象内容**。

**Stream 的三个重要特性（Go 程序员容易误用）：**

**1. 惰性求值（lazy evaluation）**

```java
orders.stream()
    .filter(o -> { System.out.println("filter"); return o.getStatus() == PAID; })
    .map(o -> { System.out.println("map"); return o.getId(); })
    .count();     // ← 没有这行，上面什么都不会打印
```

中间操作（`filter`/`map`/`sorted`）都是惰性的，只有终止操作（`collect`/`count`/`forEach`）才会触发执行。

而且 Java 会做**流水线融合**：`filter` 和 `map` 会在同一次遍历中完成，不是"先 filter 出一个中间集合再 map"。

**2. Stream 不能重复使用**

```java
Stream<Order> s = orders.stream();
s.count();      // OK
s.count();      // IllegalStateException: stream has already been operated upon or closed
```

Go 里没有对应概念（Go 就是普通的 for 循环）。

**3. parallelStream 是个陷阱**

```java
orders.parallelStream()   // 看起来很美
    .forEach(o -> process(o));
```

**别用。** 除非你非常清楚三件事：

- `parallelStream` 内部用的是**公共的 ForkJoinPool**（`ForkJoinPool.commonPool()`），默认线程数 = `CPU核心数 - 1`。整个 JVM 共享这个池子。
- 如果 `process(o)` 里有**任何阻塞 IO**，所有 commonPool 线程都会被占满，**影响到 JVM 里所有用 parallelStream 的地方**（包括其他库里的）
- 如果 `process(o)` 里操作了共享的可变状态，有数据竞争

**Java 官方的 Effective Java 作者 Joshua Bloch 说过**：不要随便用 parallelStream，除非你测过确实更快。

**什么时候适合用？** 纯 CPU 密集型、数据量足够大（万级以上）、每个元素处理时间较长、无共享状态、无阻塞 IO。

**Go 对照**：Go 里你会用 goroutine + channel 或者 errgroup 来做并行，显式控制并发度和资源。Java 的 parallelStream 把并发度隐藏起来了（用的是全局池），这是它危险的根本原因。

**一个真实的坑**：某服务用了 `parallelStream` 做批量数据处理，同时在另一个地方用 `CompletableFuture.supplyAsync()`（默认也用 commonPool）。结果批量任务占满了 commonPool，导致所有异步任务排队，接口超时。排查了两天才定位到。

**教训**：`parallelStream` 和 `CompletableFuture` 默认共用同一个线程池。要用，就自己传 `Executor`。
</details>

---

## 1.11 `enum`：Java 的枚举是个完整的类

Go 没有枚举，一般用 `const` + `iota` 模拟：

```go
type OrderStatus int
const (
    Created OrderStatus = iota
    Paid
    Shipped
)
func (s OrderStatus) String() string { ... }
```

Java 的 `enum` 是一个**完整的类**，可以有字段、构造器、方法：

```java
public enum OrderStatus {
    CREATED(0, "已创建"),
    PAID(1, "已支付"),
    SHIPPED(2, "已发货"),
    CANCELLED(-1, "已取消");

    private final int code;
    private final String desc;

    OrderStatus(int code, String desc) {   // 构造器默认 private
        this.code = code;
        this.desc = desc;
    }

    public int getCode() { return code; }
    public String getDesc() { return desc; }

    public static OrderStatus of(int code) {
        for (OrderStatus s : values()) {
            if (s.code == code) return s;
        }
        throw new IllegalArgumentException("未知状态码: " + code);
    }
}
```

**Java enum 的几个杀手级特性：**

1. **天生单例**（JVM 保证），是实现单例模式的最佳方式（Effective Java 推荐）
2. **`switch` 完美支持**（编译时还会检查是否覆盖了所有值）
3. **可以用在 `EnumSet` / `EnumMap`**，这两个是位向量和数组实现，性能远超 `HashSet`/`HashMap`
4. **可以实现接口**，甚至可以每个枚举常量有不同的行为：

```java
public enum Operation {
    PLUS { public double apply(double x, double y) { return x + y; } },
    MINUS { public double apply(double x, double y) { return x - y; } };

    public abstract double apply(double x, double y);
}
```

---

## 1.12 那些"看起来一样其实不一样"的东西

### `final` 关键字（Java 有多个含义，很容易混）

```java
final int x = 5;              // 常量，不能重新赋值（类似 Go 的 const，但可以是运行时值）
final List<String> l = new ArrayList<>();
l.add("a");                   // 合法！final 只锁引用，不锁内容（类似 Go 里指针常量）

final class Foo { }           // 不能被继承
final void bar() { }          // 不能被子类重写
```

**Go 里没有 `final` 对应物**（`const` 只能用于编译期常量）。Go 里你无法禁止一个结构体被嵌入，也无法禁止方法被覆盖（Go 根本没有覆盖）。

**`final` 的三个实际价值：**

1. **线程安全**：`final` 字段的初始化有特殊的内存语义（JMM 保证构造器结束时 final 字段对所有线程可见）—— 这是实现不可变对象的关键
2. **JIT 优化**：`final` 方法可以被内联（虽然现代 JIT 自己也能推断）
3. **防止继承破坏**：设计不可变类时必须 `final`（比如 `String`、`Integer`）

### 访问控制

| Java | 可见范围 | Go 对应 |
|---|---|---|
| `public` | 所有地方 | 首字母大写 |
| `protected` | 同包 + 子类（**注意：包括不同包的子类**） | 无 |
| 包私有（默认，不写） | 同包 | 首字母小写（但 Go 是包级，Java 是包级+） |
| `private` | 同类 | 无（Go 只能靠包隔离） |

**Java 的 `protected` 比 Go 的任何机制都复杂** —— 它同时是"包级可见"和"子类可见"。

### `null`

```java
String s = null;
s.length();   // NullPointerException（NPE）
```

Java 的 `null` 是 Tony Hoare 发明的，他自称这是"十亿美元的错误"。

Go 的 `nil` 更温和一些：
- `nil` slice 可以 `append`、`len()`、`range`（都是安全的）
- `nil` map 可以 `len()`、`range`（读安全，写 panic）
- `nil` interface 调用方法会 panic

Java 里 `null` 做任何事都是 NPE。

**Java 的应对方案**：`Optional`（第 02 章详讲）、`@Nullable`/`@NonNull` 注解（配合 IDE 或编译期检查）、`Objects.requireNonNull()`。

---

## 1.13 一章速查表：Go ↔ Java 对照

| 概念 | Go | Java |
|---|---|---|
| 包声明 | `package order` | `package com.example.order;`（必须匹配目录） |
| 导入 | `import "fmt"` | `import java.util.List;` |
| 入口 | `func main()` | `public static void main(String[] args)` |
| 变量 | `x := 5` / `var x int = 5` | `int x = 5;` / `var x = 5;`（Java 10+） |
| 常量 | `const X = 5` | `static final int X = 5;` |
| 类型定义 | `type Order struct{...}` | `public class Order {...}` |
| 方法 | `func (o *Order) Pay()` | `public void pay()`（this 隐含） |
| 包级函数 | `func Pay()` | `public static void pay()` |
| 接口 | 隐式实现 | `implements`（显式）+ default 方法 |
| 组合 | 嵌入（struct embedding） | 继承（`extends`）+ 组合（字段） |
| 泛型 | `func F[T any](t T)` | `<T> void f(T t)`（擦除） |
| 错误处理 | `if err != nil` | `try/catch/finally` + throws |
| 并发 | `go func()` + channel | `Thread` / 线程池 / `CompletableFuture` / 虚拟线程 |
| 同步 | `sync.Mutex` / `sync.WaitGroup` | `synchronized` / `ReentrantLock` / `CountDownLatch` |
| 切片 | `[]T`（len + cap） | `List<T>`（ArrayList） |
| map | `map[K]V` | `Map<K,V>`（HashMap） |
| 字符串拼接 | `strings.Builder` | `StringBuilder` |
| 格式化 | `fmt.Sprintf("%d", x)` | `String.format("%d", x)` |
| 时间 | `time.Now()` / `time.Duration` | `LocalDateTime.now()` / `Duration` |
| JSON | `json.Marshal` / tag | Jackson / `@JsonProperty` |
| 测试 | `xxx_test.go` + `testing` | `XxxTest.java` + JUnit 5 |
| 构建 | `go build` / `go.mod` | `mvn` / `gradle` + `pom.xml` |
| 依赖版本 | MVS（最小版本选择） | 依赖仲裁（nearest wins） |
| 可见性 | 首字母大小写 | `public`/`protected`/`private` |
| 不可变 | 靠约定 | `final` 关键字 |

---

## 1.14 本章核心结论

1. **`static` 是 Java "一切皆对象" 的补丁** —— Go 用"包级函数 vs 方法接收者"两个语法结构表达了 Java 用 `static` 区分的东西。

2. **`==` 在包装类型上比较引用，在原始类型上比较值** —— 这是 Java 最高频的 bug 来源之一。永远用 `.equals()` 比较对象。

3. **Java 的继承能做"父类调子类方法"（虚分派），Go 的嵌入不能** —— 这意味着读 Java 代码时，`service.doSomething()` 的实际实现可能在子类里，要用 IDE 的 "Go to Implementation"。

4. **Java 的泛型是擦除的，Go 的是单态化的** —— 这是向后兼容的妥协，第 03 章详讲。

5. **Checked exception 在实践中被大量抛弃**，因为泄漏实现细节、跟 lambda 冲突、鼓励坏的 catch 习惯。

6. **注解（RUNTIME 保留）+ 反射 = Java 框架魔法的全部基础** —— `@Transactional` 不生效的经典原因就是代理被绕过。

7. **Java 的 lambda 是值捕获，Go 的闭包是引用捕获** —— 所以 Java lambda 里改不了外部变量，但也因此天然少了一类数据竞争。

8. **`parallelStream` 和 `CompletableFuture` 共用 `ForkJoinPool.commonPool()`** —— 这是生产事故的高发区，生产代码要用自己传 Executor。

---

## 1.15 深度思考题

### 题 1：为什么 Java 的 `String` 要设计成不可变（`final`）？

<details>
<summary><b>参考答案</b></summary>

至少有五个理由，从实用到安全层层递进：

**1. 字符串常量池的前提**

如果 String 可变，那常量池就毫无意义 —— 你改了 `a`，`b` 也跟着变了：

```java
String a = "hello";
String b = "hello";
a.modify("world");   // 如果可变，b 也变成 "world"，灾难
```

**2. 哈希缓存**

`String` 内部缓存了 `hash` 字段：

```java
private int hash;   // 默认为 0
public int hashCode() {
    int h = hash;
    if (h == 0 && value.length > 0) {
        hash = h = ...;   // 算一次，之后复用
    }
    return h;
}
```

只有不可变对象才能缓存 hash。这是 `HashMap` 用 String 做 key 性能极好的原因之一。

**3. 安全性（这条最硬）**

想象一下，如果 String 可变：

```java
// 类加载器用字符串指定类名
Class.forName(className);
// 如果 className 在你检查完之后、加载之前被改了……
```

数据库 URL、文件路径、类名、网络地址 —— 这些全是 String。安全检查（权限校验）通常发生在"检查字符串内容"，而使用发生在之后。如果中间字符串能变，所有安全检查都形同虚设。

Java 的安全模型里有一条原则：**安全敏感的参数在传递过程中不能被修改**，不可变是实现这一原则最直接的手段。

**4. 线程安全**

不可变对象天然线程安全，无需同步。`String` 可以被任意多线程共享，不需要任何锁。

**5. 类加载机制的依赖**

JVM 的方法区/元空间里，类的元数据大量使用字符串（类名、方法签名、字段名）。这些字符串在类加载时就确定了，如果可变，JVM 的内部一致性无法保证。

**代价是什么？**

拼接性能。所以 Java 提供了：
- `StringBuilder`（单线程拼接）
- `StringBuffer`（线程安全，方法都 `synchronized`，已过时，几乎不用）
- Java 9 的 **String 紧凑字符串（Compact Strings）**：内部从 `char[]`（UTF-16，每个字符 2 字节）改成 `byte[]` + 编码标志（Latin-1 用 1 字节，UTF-16 用 2 字节）。对于纯 ASCII 字符串，内存占用直接减半。这个优化对绝大多数应用都是纯收益。

**顺便说一个面试常问但很实用的点**：

```java
String s = "";
for (int i = 0; i < 10000; i++) {
    s += i;      // 每次循环 new 一个 StringBuilder，再 toString()，O(n²)
}
```

编译器会把 `s += i` 优化成：

```java
s = new StringBuilder().append(s).append(i).toString();
```

**注意：`new StringBuilder()` 在循环体内！** 所以是 O(n²)。一万次循环要创建一万个 StringBuilder 和一万个临时 String。

正确写法：

```java
StringBuilder sb = new StringBuilder();
for (int i = 0; i < 10000; i++) {
    sb.append(i);
}
String s = sb.toString();
```

**Go 里为什么没这个问题？** 因为 Go 的 `strings.Builder` 是显式的，`+` 拼接字符串在 Go 里也不会被优化成 builder —— Go 程序员从一开始就知道要用 `strings.Builder`。Java 的 `+` 看起来能用（单行确实会被优化），所以容易在循环里误用。
</details>

---

### 题 2：Java 里"一切皆对象"，但 `int` 不是对象。这种不一致带来了哪些具体问题？

<details>
<summary><b>参考答案</b></summary>

这是 Java 最被人诟病的设计之一，带来的问题是系统性的：

**问题 1：容器不能装原始类型**

```java
List<int> list;        // 非法！
List<Integer> list;    // 必须装箱
```

后果：
- **内存膨胀**：一个 `Integer` 对象 = 对象头（12 字节，开启压缩指针）+ int 字段（4 字节）+ 对齐填充 = 16 字节。而 `int` 只要 4 字节。**4 倍膨胀**。
- **GC 压力**：一百万个整数 → 一百万个对象，GC 要标记、要移动。Go 的 `[]int` 是一块连续内存，GC 扫描快得多，甚至可能完全不参与 GC。
- **缓存不友好**：`List<Integer>` 是"指针数组 + 一百万个散落的对象"，遍历时缓存命中率极低。`int[]` 是连续内存，遍历飞快。

**这就是为什么 Java 有 IntStream、IntArrayList（fastutil 库）、Trove、HPPC 这些"原始类型特化容器"**，也是为什么性能敏感的代码（比如 Kafka、Flink、Spark）里你会看到大量 `long[]`、`int[]` 而不是 `List<Long>`。

**问题 2：自动装箱的隐式性导致语义模糊**

就像前面那个 `Integer == int` 的例子。装箱是自动的，所以你不知道什么时候发生了装箱：

```java
Long sum = 0L;
for (int i = 0; i < 1000000; i++) {
    sum += i;      // 每次循环：拆箱 → 加法 → 装箱 → 新对象！一百万个 Long 对象
}
```

把 `Long sum` 改成 `long sum`，性能差几十倍。

**问题 3：方法重载时的歧义**

```java
void f(int x) { }
void f(Integer x) { }

f(5);      // 调哪个？→ f(int)，因为不需要装箱的优先
f(Integer.valueOf(5));  // → f(Integer)
```

Java 的方法重载解析有三阶段：
1. 不装箱/拆箱、不变长参数，能匹配就匹配
2. 允许装箱/拆箱，再试
3. 允许变长参数，再试

这个规则很复杂，实际项目中要避免这种重载。

**问题 4：null 的二义性**

```java
boolean flag = getFlag();   // getFlag 返回 Boolean，可能是 null → NPE
```

`Boolean` 有三个值：`TRUE`、`FALSE`、`null`。`boolean` 只有两个。这个"第三种状态"经常导致 NPE。

**问题 5：泛型方法无法特化**

```java
<T> T max(List<T> list)    // T 只能是引用类型
```

你不能写一个对 `int[]` 和 `long[]` 都高效的泛型算法，只能为每种原始类型写一遍 —— 这就是为什么 `Arrays` 类里有 `sort(int[])`、`sort(long[])`、`sort(double[])`、`sort(char[])`、`sort(short[])`、`sort(byte[])`、`sort(float[])` 七个几乎一模一样的重载。

**Java 正在怎么解决？**

**Project Valhalla**（2014 年立项，至今仍在开发中）引入三个特性：

1. **Value Types（值类型）**：用户可定义不可变、无对象头、无身份（identity）的类，可以像 `int` 一样按值传递
2. **Generic Specialization（泛型特化）**：让 `List<int>` 合法，JIT 会为原始类型生成特化代码（避免装箱）
3. **Primitive Classes**：允许原始类型有自己的方法（`int.compareTo()`）

Java 21 里 Valhalla 的预览特性还没正式落地（JEP 401/402 还在草案阶段）。

**Go 对照**：Go 从来没这个问题，因为 Go 的值类型就是值类型，`[]int` 天然合法，泛型（1.18+）也支持原始类型。Go 用 GC 形状字典（GC shape stencil）实现泛型，对指针类型和非指针类型分别生成代码，int 和 int64 可能共享一份代码。

**这就是为什么**：Go 写一个通用的容器/算法库很自然，Java 写同样的东西要付出 3-5 倍的冗余代码或者接受装箱开销。这是 Java 的历史包袱，短期内不会消失。
</details>

---

### 题 3：下面这段代码有什么问题？（真实代码改编）

```java
@Service
public class UserService {

    @Autowired
    private UserRepository userRepo;

    private List<User> cache = new ArrayList<>();

    public List<User> getAllUsers() {
        if (cache.isEmpty()) {
            cache = userRepo.findAll();
        }
        return cache;
    }

    public void addUser(User user) {
        userRepo.save(user);
        cache.add(user);
    }
}
```

<details>
<summary><b>参考答案</b></summary>

这段代码至少有 **5 个问题**，每一个都是生产级的：

**问题 1（最严重）：线程安全 —— `ArrayList` 不是线程安全的**

`getAllUsers()` 和 `addUser()` 可能被多个线程同时调用（Spring 的 Controller 是多线程的，一个请求一个线程，而 Service 是单例）。

两个线程同时执行 `cache.add(user)`：
- `ArrayList.add()` 内部是 `elementData[size++] = e`
- 两个线程可能读到同一个 `size`，写到同一个位置 → 数据丢失
- `size++` 不是原子操作（读-改-写三步）→ size 可能出错
- 极端情况下扩容时并发 → 数组越界或数据错乱

**修复**：用 `CopyOnWriteArrayList`（读多写少场景）或者 `Collections.synchronizedList()` 或者显式加锁。但更根本的问题见问题 2。

**问题 2：`cache` 是实例字段，但 `UserService` 是单例 Bean —— 这是"状态泄漏"**

Spring 的 Bean 默认是**单例（singleton）**，整个 JVM 里只有一个 `UserService` 实例，被所有请求共享。

所以这个 `cache` 是**全局共享的可变状态**。这意味着：
- 所有用户线程共享同一份缓存
- 一个请求对 cache 的修改，会影响所有其他请求
- 内存泄漏风险：cache 只增不减，应用跑一周，所有用户都在内存里

**这是 Go 程序员最容易犯的错** —— 在 Go 里你可能习惯这样写：

```go
type UserService struct {
    userRepo *UserRepo
    cache    []*User      // 如果 handler 每次 new 一个 UserService，这没问题
}
```

但 Java Spring 里，**Service/Controller 是单例的**，里面不能放请求级的状态。

**正确的做法**：
- 用真正的缓存组件（`Caffeine` / `Redis` / Spring `@Cacheable`）
- 或者把状态放到方法局部变量里
- 或者把 Bean 声明为 `@Scope("prototype")`（不推荐，会失去 Spring 的管理优势）

**问题 3：`if (cache.isEmpty())` 的逻辑漏洞**

如果数据库里确实没有用户，`findAll()` 返回空 list，`cache` 一直是空的。**每次请求都会查一次数据库** —— 缓存完全失效，还多了一次判断开销。

**修复**：用一个标志位或者 `null` 判断。

**问题 4：缓存永远不会失效**

`addUser` 往 cache 里加，但删除、更新操作不会被同步到 cache。跑一天之后，cache 里全是脏数据。

而且：**如果应用部署了多个实例，每个实例的 cache 都不一样**。用户在实例 A 注册，请求打到实例 B 时看不到。

**这就是"本地缓存"在分布式环境下的经典问题** —— 要么用 Redis 这种集中式缓存，要么接受不一致。

**问题 5：`userRepo.findAll()` 的结果直接作为 cache —— 可能是不可修改的 List**

如果 `findAll()` 返回的是一个不可变 List（比如 JPA 返回的实现，或者 `List.of()`），后续 `cache.add(user)` 会抛 `UnsupportedOperationException`。

而且 MyBatis/JPA 返回的实现类型不确定，依赖它的可变性是脆弱的。

**修复**：`cache = new ArrayList<>(userRepo.findAll());`

---

**正确的写法（示意）：**

```java
@Service
public class UserService {

    private final UserRepository userRepo;

    // 构造器注入（推荐，见第 14 章）
    public UserService(UserRepository userRepo) {
        this.userRepo = userRepo;
    }

    public List<User> getAllUsers() {
        return userRepo.findAll();     // 让数据库/MyBatis 二级缓存/Redis 去操心
    }

    @Transactional
    public void addUser(User user) {
        userRepo.save(user);
    }
}
```

需要缓存的话：

```java
@Cacheable(value = "users", unless = "#result.isEmpty()")
public List<User> getAllUsers() {
    return userRepo.findAll();
}

@CacheEvict(value = "users", allEntries = true)
@Transactional
public void addUser(User user) {
    userRepo.save(user);
}
```

**（第 14 章会讲为什么 `@Cacheable` 在同一个类内部调用也会失效 —— 跟前面讲的 `@Transactional` 是同一个原因：代理。）**

**这道题浓缩了两个最关键的 Java 认知**：
1. **Spring 的 Bean 默认是单例，不要在里面放可变状态**
2. **`ArrayList` / `HashMap` 不是线程安全的**

这两条加起来，是 Java 新手（包括转语言的老手）最高频的生产事故来源。
</details>

---

### 题 4：Java 的方法参数传递是"值传递"还是"引用传递"？

<details>
<summary><b>参考答案</b></summary>

**Java 100% 是值传递（pass by value）。没有任何例外。**

这是经典的争论点，但答案是确定的。关键在于理解"传递的值是什么"。

**对于原始类型**：传递的是值的副本。

```java
void f(int x) {
    x = 100;
}
int a = 1;
f(a);
System.out.println(a);   // 1，没变
```

**对于引用类型**：传递的是**引用的副本**（也就是"指针的值"的副本）。

```java
class User { String name; }

void f(User u) {
    u.name = "Bob";        // ✅ 改的是引用指向的对象 → 外部可见
    u = new User("Carol"); // ❌ 只改了局部的引用副本 → 外部不可见
}

User a = new User("Alice");
f(a);
System.out.println(a.name);   // "Bob"
```

**为什么？** 调用 `f(a)` 时：
1. `a` 里存的是一个地址（比如 `0x1234`）
2. Java 把这个地址**复制一份**传给 `f` 的参数 `u`
3. 现在 `a` 和 `u` 都存着 `0x1234`，指向同一个对象
4. `u.name = "Bob"`：通过 `u` 里的地址找到对象，改它的字段 → 对象变了，`a` 看到也变了
5. `u = new User(...)`：把 `u` 里存的地址改成 `0x5678`。但 `a` 里还是 `0x1234` → 没影响

**所以：Java 是"引用的值传递"（pass reference by value）。**

**Go 完全一样：**

```go
func f(u *User) {
    u.Name = "Bob"      // ✅ 外部可见
    u = &User{"Carol"}  // ❌ 外部不可见
}
```

Go 里如果传的是结构体值（不是指针），那连字段修改都不可见：

```go
func f(u User) {
    u.Name = "Bob"   // ❌ 完全不可见，因为整个结构体被复制了
}
```

**Java 里没有对应的"整个对象被复制"的传递方式**，因为 Java 的变量永远存的是引用（除了 8 种原始类型）。要复制必须显式 `clone()` 或者 `new`。

**那为什么有人说是"引用传递"？** 因为混淆了术语。"引用传递"（pass by reference）在编程语言理论里的严格定义是：**形参是实参的别名，对形参的赋值会改变实参**。C++ 的 `&`、C# 的 `ref` 才是引用传递。

```cpp
void f(int& x) {
    x = 100;   // 真的改了外面的变量
}
int a = 1;
f(a);   // a 变成 100
```

**Java 做不到这一点。** Java 没有 C++ 的引用（别名）概念，也没有 Go 的指针运算。你不能在 Java 里写一个 `swap(int a, int b)` 函数。

**这个认知对实际编码的影响：**

1. **方法可以修改传入对象的字段**（这是最常见的副作用来源）。所以 Java 里"防御性拷贝"很重要：

```java
public class Order {
    private List<Item> items;

    public List<Item> getItems() {
        return new ArrayList<>(items);   // 防御性拷贝，防止外部修改内部状态
        // 或者 return Collections.unmodifiableList(items);
    }
}
```

2. **返回可变对象也有同样的风险**（见题 3 的 `getAllUsers`）

3. **这就是为什么"不可变对象"在 Java 里这么受推崇** —— `String`、`Integer`、`LocalDateTime`、`record`（Java 16）都是不可变的。不可变对象可以随便传来传去，不用担心里面的状态被改。

4. **Go 里的对应实践**：Go 程序员习惯用指针传递大结构体（避免复制），用值传递小结构体。Java 里不用纠结 —— 传引用永远是 8 字节（压缩指针下 4 字节），代价一样。

**一句话总结**：Java 传的是"引用的副本"。改内容会影响外面，改引用不会。
</details>

---

### 题 5（动手）：把你写过的某个 Go 项目的一个模块，用 Java 17 重写一遍

> 不用很复杂，选一个 200-500 行的模块。建议选一个包含"数据结构 + 业务逻辑 + 错误处理"的部分。
>
> 重写的时候，注意记录这几件事：
>
> 1. 你的 `error` 返回值变成了什么？（提示：你需要定义自己的异常类，或者返回 `Optional`）
> 2. 你的 struct + 方法，变成了 class + 方法。方法接收者（`func (o *Order) xxx`）消失了，变成隐式的 `this`。你怀念显式接收者吗？
> 3. 你的 `[]T` 变成了 `List<T>`。`append` 变成 `add`。有没有哪个地方你发现 `List` 的接口跟 slice 语义不匹配？
> 4. 你的 `map[K]V` 变成了 `Map<K,V>`。遍历方式从 `for k, v := range m` 变成 `m.forEach((k, v) -> ...)` 或 `for (var e : m.entrySet())`。
> 5. 你的 `sync.Mutex` 变成了什么？（先自己查一下 `synchronized` 和 `ReentrantLock` 的区别）
>
> **做完这个练习，你就会发现：Java 语法你真的已经会了。** 剩下的 21 章，讲的是"为什么 Java 世界的这些东西长这样"。

---

## 下一章预告

第 02 章讲 **Java 17 的新特性和 Java 8 的差异**。

这一章对 Go 程序员特别重要，因为：
- `record` 解决了"DTO 要写 200 行 getter/setter"的荒谬问题
- `sealed` 让你能限制"谁能实现这个接口"（Go 里用非导出接口 + 工厂函数模拟）
- switch 模式匹配让 Java 代码第一次有了点 Go/Rust 的味道
- `Optional` 是 Java 对 NPE 的官方答案（虽然争议很大）

同时我会讲 Java 8 的那些"坑"：`Date`/`Calendar` 的灾难、`Stream` 的误用、`parallelStream` 的陷阱、以及为什么国内还有大量项目卡在 Java 8 上。
