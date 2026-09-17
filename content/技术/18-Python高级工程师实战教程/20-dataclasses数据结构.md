# 第 20 章 dataclasses 与数据结构

> 这一章帮你把「一堆散装字段」收拢成有类型、能校验、好维护的数据结构，少写几十行样板代码——顺便搞清楚它和 Go 的 struct 到底差在哪。

老哥，你写 Go 的时候，一个 `User` 结构长这样：`type User struct { ID int; Name string; CreatedAt time.Time }`。字段、类型、对齐，编译器门儿清。到了 Python，你是不是经常偷懒写成 `user = {"id": 1, "name": "墨叔"}`？数据在代码里到处飘，取个字段靠敲字符串键，IDE 不会提示，拼错了运行时才炸。你先想一个问题：Python 里有没有一种写法，能让你既像 Go 的 struct 那样「字段是显式的、类型是可知的」，又不用自己手写 `__init__`、`__repr__`、`__eq__` 这一堆样板？

墨叔：对，答案之一就是 `dataclasses`。今天咱不堆概念，直接从一个你项目里天天会遇到的场景聊起。

## 一、dataclass 到底是什么（怎么用）

`dataclass` 是 Python 3.7 引入的装饰器，本质是一个「帮你自动生成样板方法」的语法糖。你只声明字段和类型，它替你把 `__init__`、`__repr__`、`__eq__`、`__hash__` 按需生成出来。

```python
from dataclasses import dataclass

@dataclass
class OrderLine:
    sku: str
    quantity: int
    unit_price: float

line = OrderLine(sku="A-100", quantity=3, unit_price=9.9)
# 自动有了好用的 repr
print(line)                       # OrderLine(sku='A-100', quantity=3, unit_price=9.9)
# 自动有了值相等比较
print(line == OrderLine("A-100", 3, 9.9))   # True
# 字段是属性访问，不是字典键
print(line.quantity)
```

你注意到了吗？我没写一行 `__init__`，但 `OrderLine("A-100", 3, 9.9)` 能直接构造。这就是 dataclass 的「少写样板」核心：**类型注解即字段声明**。在 Go 里你写 `Name string`，在 dataclass 里你写 `name: str`——形式上几乎一一对应，只是 Python 的注解默认不参与运行时强制。

那类型注解会不会被「强制检查」？不会。`dataclass` 生成的 `__init__` 只按位置/关键字接收参数，不验证你传的 `quantity` 是不是真 `int`。除非你装了 `mypy` 这类静态检查器，否则 `OrderLine(sku=123, quantity="三", unit_price="贵")` 也能构造出来。这点跟 Go 编译期就把类型门死完全不同——代价是灵活，收益是快，坑是运行时才暴露。所以墨叔一直强调：**类型注解是给人和工具看的契约，不是运行时的铁栅栏**。

字段还能带默认值，但有个大坑马上讲。先看正常版：

```python
from dataclasses import dataclass, field

@dataclass
class Task:
    title: str
    done: bool = False
    tags: list[str] = field(default_factory=list)
```

`done=False` 没问题。但 `tags: list[str] = []` 这种写法会直接报 `ValueError: mutable default ... is not allowed`。为什么？这就是下面要扒的「可变默认参数」老坑。

## 二、什么场景该用它（对照 Go / 边界）

先说那个经典坑：`tags: list[str] = []`。

你在写普通函数时可能听过「Python 的默认参数是在函数定义时求值的」。dataclass 继承了这个语义。如果在定义时把 `[]` 绑死，所有实例会**共享同一个列表对象**——你给 A 任务加标签，B 任务的标签也跟着变了。这跟 Go 完全不同，Go 里 `Tags []string` 每个实例各自一份零值切片，互不串门。

所以 dataclass 干脆在语法层禁止了你写 `= []`，逼你用 `field(default_factory=list)`。`default_factory` 接收一个**无参可调用对象**，每次构造新实例时才调用一次，从而给每个实例一份独立的可变对象。记住这条铁律：**任何可变默认值（list、dict、set、甚至自定义对象），一律用 `default_factory`**。

```python
@dataclass
class Cart:
    items: dict[str, int] = field(default_factory=dict)
    coupon_codes: list[str] = field(default_factory=list)
```

那 dataclass 跟几个「近亲」怎么选？你脑子里大概有四个候选：`namedtuple`、手写类、`attrs`、`dataclass`。咱一个个比：

- **namedtuple**：不可变、轻量，适合「只读坐标点」这种场景。但它不能方便地加方法、不能有可变默认值、Python 3.7 后基本被 dataclass 在可变需求上取代了。它更像 Go 的「值类型小结构体」，只是不可变。
- **手写类**：完全可控，但 `__init__`/`__repr__`/`__eq__` 几十行样板，纯属体力活。墨叔只在需要高度自定义逻辑时才手写。
- **attrs**：第三方库，dataclass 的设计蓝本。功能更猛（自动类型转换、槽位优化、校验钩子），但多一个依赖。新项目用标准库 dataclass 通常够；要进阶能力再上 attrs。
- **dataclass**：标准库、零依赖、`@dataclass` 一行搞定 80% 场景。它是咱今天的主角。

对照 Go，dataclass 大致等于「自动生成构造器+打印+相等比较的 struct」。但 Go 的 struct 是值语义（赋值/传参默认拷贝），Python 的 dataclass 实例是引用语义（默认浅拷贝）这点要刻进脑子——你把一个 dataclass 实例塞进另一个，改内部可变字段会互相影响，跟 Go 的 `append` 切片偶尔的「扩容后不共享」还不一样，Python 这边是铁定共享。

`__post_init__` 是你做「构造后校验」的钩子，对应 Go 里你常常手写 `func NewUser(...) (*User, error)` 做的事：

```python
from dataclasses import dataclass, field

@dataclass
class Money:
    currency: str
    amount: float

    def __post_init__(self):
        if self.amount < 0:
            raise ValueError("金额不能为负")
        if self.currency not in ("CNY", "USD", "EUR"):
            raise ValueError(f"不支持的币种: {self.currency}")
```

`__post_init__` 在自动生成的 `__init__` 末尾被调用，所以字段都已经就位，你可以做跨字段校验、类型归一化，甚至从原始字段派生新字段。这比在 `__init__` 里手写一整套清爽太多——你不用再写 `self.a = a; self.b = b`，只管写校验逻辑。

什么时候**不该**用 dataclass、改用普通 `dict`？墨叔给你一个判断尺：

- 字段结构**不稳定、动态拼装**（比如外部 API 返回的半结构化 JSON，你只想 `data["x"]["y"]` 一路取），用 dict 更省事，强套 dataclass 反而累。
- 数据只是**临时中转、用完即弃**的一次性管道，dict 更快更轻。
- 反之：字段**语义明确、要在多处作为「值」传递和比较**（领域模型、配置项、消息体），就值得上 dataclass。它给你的是「可读性 + IDE 补全 + 相等比较 + 集中校验点」，这些在大型项目里比那点性能差异值钱得多。

## 三、用它的收益与代价（为什么这么设计）

收益你都看见了：样板代码从几十行压到几行；`__repr__` 自动生成，调试时一眼看清状态；`__eq__` 默认按字段值比较，测试里 `assert result == expected` 直接能用；配合 `asdict`/`astuple` 还能一键转字典。

代价也得算清楚：

1. **运行时零校验**：类型注解不强制，传错类型不报错。要真正「类型即契约」，得叠加 `mypy` + 必要时 `pydantic`（下一章讲）。
2. **可变默认陷阱**：忘了 `default_factory` 就直接翻车。这是 dataclass 最常踩的坑，没有之一。
3. **`__hash__` 的微妙之处**：默认 `unsafe_hash=False`，当类里有可变字段时，`__hash__` 会被设为 `None`（实例不可哈希，不能进 set/dict 的 key）。如果你的 dataclass 要当字典键用，得显式 `@dataclass(frozen=True)` 或 `eq=True, frozen=True` 让它可哈希。`frozen=True` 让实例不可变，类似 `namedtuple`，配 `slots=True`(3.10+) 还能省内存。
4. **性能**：dataclass 实例本质还是普通对象，存少量字段时比 dict 略省内存（因为不用维护哈希表），但差异在微观级，别为这点性能强上 dataclass——可读性和可维护性才是主因。

```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float

p = Point(1.0, 2.0)
# p.x = 3.0  # 会抛 FrozenInstanceError，和 Go 里你想改 const 一样的感觉
```

`slots=True` 在 Python 3.10+ 可用，它让实例不再有 `__dict__`，内存占用更友好，也杜绝了「随手给实例加野字段」的坏习惯。墨叔在定义明确的领域模型时几乎必开。

## 四、一个贴近项目的例子

假设你有个订单服务的内部消息模型，要在服务间用队列传递。用 dataclass 建模，集中校验，出参能直接转 dict 进 JSON：

```python
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timezone
from typing import Optional

class OrderStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    DONE = "done"

@dataclass(frozen=True, slots=True)
class OrderItem:
    sku: str
    qty: int
    price_cents: int

    def __post_init__(self):
        if self.qty <= 0:
            raise ValueError("购买数量必须为正")
        if self.price_cents < 0:
            raise ValueError("单价不能为负")

@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    user_id: str
    items: list[OrderItem] = field(default_factory=list)
    status: OrderStatus = OrderStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    remark: Optional[str] = None

    def __post_init__(self):
        if not self.order_id:
            raise ValueError("order_id 不能为空")
        if not self.items:
            raise ValueError("订单至少要有一件商品")

    @property
    def total_cents(self) -> int:
        return sum(i.qty * i.price_cents for i in self.items)

    def to_payload(self) -> dict:
        # asdict 会递归把内部 dataclass 也转成 dict，方便序列化
        return asdict(self)

# 构造一笔订单，校验在构造时就完成
order = Order(
    order_id="O-20260917-001",
    user_id="U-42",
    items=[OrderItem("A-1", 2, 9900), OrderItem("B-2", 1, 1500)],
)
assert order.total_cents == 2 * 9900 + 1500
payload = order.to_payload()
# payload 现在是纯 dict，可直接 json.dumps 发出去
```

你看，这个 `Order` 一旦构造出来，你就**确定**它是合法的——所有不变量在 `__post_init__` 里被锁死。这跟 Go 里 `NewOrder` 返回 `error` 是同一个工程意图：把非法状态挡在系统门外。区别只是 Go 在编译期让你必须处理 error，Python 这里你得**自觉地、约定俗成地**在构造处接住异常。

对照 Go，你大概会写：

```go
type Order struct {
    OrderID   string      `json:"order_id"`
    UserID    string      `json:"user_id"`
    Items     []OrderItem `json:"items"`
    Status    OrderStatus `json:"status"`
    CreatedAt time.Time   `json:"created_at"`
}
func NewOrder(id, uid string, items []OrderItem) (*Order, error) { ... }
```

Go 用 `json` tag 控制序列化字段名，Python 这边字段名本身就得和 JSON 对齐（或靠 `alias`/下一章的 pydantic 处理）。这是两种哲学：Go 把序列化规则写进 struct tag，Python 用 dataclass 时有更少的隐式约定，但遇到「下划线 vs 驼峰」的对接时，往往要额外一层转换。

老哥，你品一品：dataclass 解决的从来不是「能不能存数据」——dict 也能存。它解决的是「**成百上千个数据载体在你的项目里漂着时，你怎么保证它们长得规矩、改得安全、看得明白**」。这恰恰是 Go 的 struct 在编译期白送你的东西，Python 得靠 dataclass + 约定来补。

## 五、field 参数与继承的两个深坑

`field()` 除了 `default_factory`，还有几个值得记住的参数，它们决定字段在「构造、打印、比较」里怎么表现：

- `init=False`：该字段不参与构造器，常用于「由其他字段派生、在 `__post_init__` 里算出来」的属性。
- `repr=False`：在自动生成的 `__repr__` 里隐藏它——比如密码、长 token、大列表，避免日志里刷屏。
- `compare=False`：相等比较时忽略它。比如「两个订单内容相同就视为相等，不看创建时间戳」。
- `kw_only=True`（3.10+）：该字段只能用关键字传入，避免位置参数的顺序烦恼。

```python
from dataclasses import dataclass, field

@dataclass
class Token:
    value: str
    created_at: str = field(init=False, repr=False)

    def __post_init__(self):
        self.created_at = "now"   # init=False 所以构造器不接收，这里自己填
```

**继承的坑**是 dataclass 最常让人摔跟头的地方。dataclass 的字段顺序是「基类字段在前、子类字段在后」，但 Python 不允许「无默认值的参数排在带默认值的参数之后」——这条函数参数铁律在跨类拼接字段时照样生效：

```python
@dataclass
class Base:
    id: int                 # 无默认值
@dataclass
class Child(Base):
    name: str = ""          # 有默认值 -> TypeError：非默认参数跟在默认参数后
```

解法有二：要么给子类字段 `kw_only=True`，让它变成只有关键字参数、不参与位置排序；要么把带默认值的字段统一放后面。墨叔在写「可能被继承的数据模型」时，习惯给所有可选字段加 `kw_only=True`，一劳永逸避开这坑。

**不可变实例怎么「改」？** `frozen=True` 后不能赋值，但标准库给了 `dataclasses.replace` 做「拷贝 + 局部修改」：

```python
from dataclasses import replace
p = Point(1.0, 2.0)
p2 = replace(p, x=10.0)     # 返回新 Point(10.0, 2.0)，原 p 不变
```

这对应 Go 里你重新构造一个 struct、只改一个字段的写法——值语义下的「改」其实是「建个新的」。函数式更新，线程安全、好推理、易测试，墨叔在并发/不可变建模时很喜欢它。

## 六、dataclass 在 Python 生态里的位置（对照 Go struct）

老哥，咱把这一章收个尾，给你一张「选武器」的对照表，免得你在项目里犯选择困难：

| 你的需求 | 推荐 | 对照 Go |
|---|---|---|
| 字段固定、要校验、多处当值传递 | `dataclass` | `struct` + `NewXxx() (*X, error)` |
| 字段不可变、轻量、按位置取 | `namedtuple` | 值类型小 struct |
| 外部输入、要强校验强转换 | `pydantic.BaseModel` | `json.Unmarshal` + 手写校验 |
| 结构动态、用完即弃 | 普通 `dict` | `map[string]any` |
| 需要 attrs 的高级能力 | 第三方 `attrs` | —— |

关键认知：Go 的 struct 把「类型强约束 + 零值 + 值/引用语义」焊进编译期，是语言级的契约；Python 的 dataclass 是运行时的便利封装，契约要靠「类型注解 + mypy + `__post_init__` 校验」三层自己补。代价是你要多操心，收益是灵活、迭代快。墨叔的经验：领域模型（订单、用户、配置）用 dataclass/pydantic 收口；临时管道数据用 dict 放行——别把 dataclass 当万能药，也别长期让核心数据裸奔在 dict 里。

再补一句内存视角：当你有几十万个小对象时，`@dataclass(slots=True)` 比普通类省下可观内存（没有 `__dict__` 开销），比 dict 也略省（dict 要维护哈希表）。但说实话，绝大多数业务项目里这点差异不值得作为选型主因——可读性、可维护性才是 dataclass 的主场。只有当你真的在做「百万级对象常驻内存」的环节（缓存、图谱、批处理），才需要专门用 `slots=True` 去抠这块内存。别本末倒置，为了微优化把代码写复杂。

【思考题】
1. 为什么 dataclass 禁止你用 `tags: list[str] = []` 这种可变默认值，而要求 `field(default_factory=list)`？如果硬要用一个共享列表当默认值，项目里会出现什么具体 bug？延伸到：你在写 Go 时有没有遇到过类似的「共享状态」陷阱，又是怎么避开的？
2. 假设你要做一个配置对象，字段很多、构造后绝不应被修改，你会在 `@dataclass` 上加哪些参数？为什么 `frozen=True` 还不够，有时还要 `slots=True`？
3. dataclass 的类型注解（比如 `quantity: int`）在运行时并不强制类型，那它到底「有啥用」？如果你是团队 lead，怎么在保证灵活的同时不丢掉类型安全？

【参考答案】
1. dataclass 默认生成的 `__init__` 在类定义阶段就对默认参数求值一次，如果写成 `= []`，这个列表对象会被所有实例共享（类属性级别的一个对象）。后果：你往 `order_a.items.append(x)`，会发现 `order_b.items` 也多了 `x`，因为两者指向同一块内存。这种 bug 极难排查，因为它不报错、只在特定调用顺序下暴露。Go 没有这个坑，因为每个 struct 实例的切片字段是各自独立的零值。但 Go 里有「切片底层数组共享」的类似陷阱：对切片重新切片（`sub := big[2:5]`）后，`sub` 和 `big` 共享底层数组，改 `sub` 会污染 `big`。Go 里用 `append` 触发扩容、或用 `copy` 显式拷贝来隔离；Python dataclass 这边用 `default_factory` 让每个实例各自新建对象来隔离。本质是同一个工程命题：可变共享状态是万恶之源，语言在「默认值求值时机」上的差异决定了坑的形态。

2. 我会写成 `@dataclass(frozen=True, slots=True, eq=True)`。`frozen=True` 让实例不可变，任何属性赋值都会抛 `FrozenInstanceError`，从语义上锁死「配置一经构造不得更改」，类似 Go 里把配置当作不可变值传递。`slots=True` 的额外价值有两点：一是内存更省（不再为每个实例维护 `__dict__`），配置对象如果很多实例或字段多时收益明显；二是**杜绝野字段**——你不能再 `cfg.new_field = 1` 随手加属性，这能把「拼写错字段名本该报错却静默创建新字段」的隐患直接变成 `AttributeError`。注意 `frozen=True` 的 dataclass 内部若含可变字段（如 list），该 list 本身仍可改；若要彻底不可变，需配合不可变容器（如 `tuple`）作为默认值。

3. 类型注解的「用」有三层：(1) 给人看——读代码时立刻知道 `quantity` 应该是 int，不必翻调用方；(2) 给 IDE 看——补全、重构、跳转都靠它；(3) 给静态检查器（mypy/pyright）看——在 CI 里跑一遍，能把「传错类型」这种 bug 在合并前抓出来，逼近 Go 编译期检查的效果。运行时确实不强制，所以纯粹靠注解并不能挡住错误数据。作为 team lead，墨叔的做法是：dataclass 负责「结构 + 构造期校验（__post_init__）」，mypy 负责「静态类型门禁」，边界输入（外部 JSON、环境变量）交给 pydantic 做运行时强制转换与校验。三层组合，才既保留 Python 的灵活，又不丢类型安全。
