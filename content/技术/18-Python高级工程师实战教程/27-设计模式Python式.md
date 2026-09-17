# 第 27 章 设计模式 Python 式写法

> 这一章专治一种病：从 Java 教程里背了一肚子「二十三种设计模式」，到 Python 里硬套，写出一堆只有类名没有灵魂的模板代码。咱们把经典模式翻译成 Python 该有的样子，顺手对照 Go。

墨叔：老哥，我问你个事儿。你以前看没看过那种「Python 设计模式」书，一上来先画 UML 类图，然后搞个 `AbstractFactory`、`ConcreteFactory`、`FactoryProducer` 三层接口，最后就为了 new 一个对象。你读完什么感觉？

老哥：……感觉在 Python 里写 Java。明明一行能解决，非要套五层。

墨叔：对，这就是「设计模式八股」的坑。设计模式本来是「在特定语言限制下，解决特定问题的套路」。Java 因为静态、啰嗦、缺一等公民函数，很多模式是被迫长那样。Python 有鸭子类型、有函数当值传递、有模块级单例，一大半 Java 模式的「壳」可以直接拆掉，只留「解决问题的内核」。今天咱们挑四个你项目里最可能用到的：单例、工厂、策略、依赖注入，看看 Python 怎么用最少的代码把事办了，再对照 Go 你会更通透。

## 一、单例：模块即单例，别写 `__new__`

先破一个最大误会。很多教程教你单例要重写 `__new__`，搞个私有类变量存实例，判断 `if cls._instance is None`。我直接说结论：**在 Python 里，你大概率根本不需要写单例类**，因为模块本身就是单例。

老哥：模块是单例？怎么说？

墨叔：Python 的模块在进程里只会被导入一次，导入后模块对象缓存在 `sys.modules` 里，后续 `import` 同一模块拿到的是同一个对象。你在模块顶层创建一个实例，全项目谁 `import` 它，拿到的都是同一个。这不就是单例吗？

```python
# app/config.py  —— 一个全局配置单例
from pydantic import BaseModel

class Settings(BaseModel):
    db_url: str = "sqlite:///app.db"
    debug: bool = False

settings = Settings()   # 模块加载时创建一次，全局唯一
```

```python
# 任何地方
from app.config import settings   # 拿到的永远是同一个对象
print(settings.db_url)
```

看，没有 `__new__`、没有锁、没有双重检查。因为模块导入的「只执行一次」语义，天然就是线程安全的单例。你要的「全局唯一一个配置 / 一个连接池 / 一个缓存」，直接模块级变量解决。对照 Go：Go 里你常写 `var cfg = loadConfig()` 包级变量，或者用 `sync.Once` 懒加载——思路和「模块级实例」异曲同工，都是「利用包初始化只跑一次」。

那什么时候**真**需要类级别单例（比如要延迟到第一次调用才创建）？用 `@functools.cache` 包住工厂函数，比手写 `__new__` 干净：

```python
import functools

@functools.cache
def get_redis():
    return RedisClient(host="localhost")   # 第一次调用才建，之后复用

# 全局任意处调用 get_redis() 都拿到同一个
```

`functools.cache` 本质是带键的 memoization，键是空元组（无参函数），所以只算一次。比 `__new__` + 锁那套，少写十行还不会写错线程安全。

## 二、工厂：函数就是工厂，要什么返回什么

Java 的工厂模式要 `Factory` 接口 + 多个 `Product` 实现 + `FactoryMethod`。Python 里，函数本身就能当工厂——它是一等公民，可以返回类、可以返回实例、可以返回闭包。

老哥：那如果产品种类多，怎么组织？

墨叔：最朴素的写法，一个函数 + 字典映射，比任何 `switch` 工厂都直白：

```python
class JsonSerializer:
    def dumps(self, data): return json.dumps(data)

class MsgPackSerializer:
    def dumps(self, data): return msgpack.packb(data)

def make_serializer(name: str) -> Serializer:
    registry = {
        "json": JsonSerializer,
        "msgpack": MsgPackSerializer,
    }
    try:
        return registry[name]()
    except KeyError:
        raise ValueError(f"未知序列化器: {name}") from None
```

这就是工厂：根据名字造不同的对象。注意我返回的是**类**（首字母大写，`registry[name]()` 才实例化），也完全可以直接返回实例，看你需不需要每次新的。对照 Go：Go 没有函数内嵌 map 当分发表那么顺手，你常写 `switch name { case "json": return JsonSerializer{} }`，或者用 `map[string]func() Serializer`。Python 这版少了一个 `switch`，因为字典天然适合「键到构造器」的映射。

更高级一点，如果你想让用户**注册**自己的产品（插件式工厂），用装饰器收集：

```python
_SERIALIZERS: dict[str, type] = {}

def register(name: str):
    def deco(cls):
        _SERIALIZERS[name] = cls
        return cls
    return deco

@register("json")
class JsonSerializer:
    ...

def make_serializer(name: str):
    return _SERIALIZERS[name]()
```

这比 Java 的 `ServiceLoader` 轻了不是一个量级。装饰器即注册，闭包存名字——又是「Python 用语言特性替代样板代码」的典型。

## 三、策略：把函数当一等公民传进去

策略模式在 Java 里是「定义一个策略接口，多个实现类，上下文持有一个策略对象」。Python 里，策略就是一个**函数**，直接当参数传，连接口都不用定义。

```python
def discount_regular(price: float) -> float:
    return price

def discount_vip(price: float) -> float:
    return price * 0.9

def checkout(price: float, strategy: Callable[[float], float]) -> float:
    return strategy(price)   # 策略就是个函数，传谁用谁

# 调用
final = checkout(100.0, discount_vip)   # 90.0
```

`strategy` 参数类型标注成 `Callable[[float], float]`，mypy 能查「你传的确实是接收 float 返回 float 的函数」。这比 Java 的 `interface DiscountStrategy { float apply(float p); }` + 两个实现类，少一大半代码，且语义完全一样：把「可变的行为」从「固定流程」里抽出来。

老哥：那如果策略要带状态呢？比如要记「这个策略用过了几次」。

墨叔：好问题，这正是 Java 非要上类的地方。Python 里两种解法：一是用带属性的闭包（nonlocal 计数），二是直接上类——但即便用类，也别硬套接口，直接用：

```python
class RateLimitStrategy:
    def __init__(self, limit: int):
        self.limit = limit
        self.calls = 0
    def allow(self) -> bool:
        self.calls += 1
        return self.calls <= self.limit

# 当成策略传入，callable 对象一样能被持有和调用
limiter = RateLimitStrategy(3)
process(req, limiter.allow)   # 把 bound method 当函数传
```

你看，哪怕用类，也是「需要状态才上类」，而不是「为了模式而上模式」。对照 Go：Go 里策略就是一个 `type Strategy func(price float64) float64`，函数类型直接当参数——和 Python 这版几乎一字不差。Go 因为没有类方法当一流 callable 那么灵活，反而更早就接受了「函数是值」，这点俩语言出奇地合拍。

## 四、依赖注入：FastAPI 的 Depends 是真香

依赖注入（DI）在 Java/Spring 里是一套庞大的容器和注解体系。Python 生态里最优雅的实现，是 FastAPI 的 `Depends`——它把「我要用某个依赖，但你别让我手动 new」这件事，用函数参数声明表达出来。

```python
from fastapi import Depends, FastAPI

def get_db():
    db = Database(config.db_url)
    try:
        yield db        # yield 出来，用完自动回收（上下文管理器式）
    finally:
        db.close()

app = FastAPI()

@app.get("/users/{uid}")
def get_user(uid: int, db: Database = Depends(get_db)):
    return db.fetch_user(uid)
```

`db: Database = Depends(get_db)` 这句话的意思是：「这个接口的 `db` 参数，别调用方传，框架按 `get_db` 这个函数给我造好、注入进来」。好处一堆：

1. **测试时随便换实现。** 测试里你 override `get_db` 返回一个假数据库，业务代码一行不改。这就是 DI 的核心价值——依赖可替换。
2. **资源生命周期自动管。** `yield` 写法让 FastAPI 在请求结束自动跑 `finally` 关连接，你不用手写清理。
3. **依赖能嵌套。** `get_db` 自己也能 `Depends(get_config)`，框架递归解析整棵依赖树。

对照 Go：Go 没有内建 DI 容器，你通常手写——把依赖作为结构体字段注入：`type UserHandler struct { db Database }`，在 `main` 里 `NewUserHandler(db)` 手动装配。FastAPI 的 `Depends` 只是把「手动装配」变成了「声明式、框架自动解析」，少写装配代码，但本质一样：**依赖从外部传入，不内部硬编码 new**。理解了这个本质，你会发现 Spring 那套、FastAPI 这套、Go 手写这套，内核是同一个——只是 Python 用装饰器和类型注解把这事写得更短。

## 五、用它的收益与代价（为什么这么设计）

老哥：听下来，Python 把这些模式都「减肥」了。那减肥会不会减掉什么东西？什么时候该老老实实写全模式？

墨叔：问得专业。减肥减掉的是「样板代码」，保住的是「解耦内核」，通常稳赚。但代价你要清楚：

- **可读性对「懂 Python 的人」更友好，对新手更隐蔽。** `make_serializer` 返回类、策略直接传函数、单例藏在模块里——这些「隐式约定」要求读者也懂 Python 哲学。一个从 Java 过来的新人，看到 `db = Depends(get_db)` 可能不知道框架偷偷注入了什么。所以团队要做的是统一约定、写好文档，别各写各的魔法。
- **过度设计照样存在。** 「别硬套 Java 八股」不等于「啥模式都不用」。如果一个行为确实有多种实现、且要在运行时切换（折扣策略、序列化器），那策略/工厂就是该用的；如果只是 `if kind == "a": do_a()` 写两行，硬抽成策略类反而过度。判断标准：这个变化点会不会真的变多？会，才值得抽象。
- **DI 框架带来隐式控制流。** `Depends` 很香，但你得记住「参数不是我传的，是框架塞的」，调试时堆栈会多一层框架。代价是心智模型要更新，收益是装配代码趋近于零。

一句话收益与代价总结：Python 式写法的收益是「用语言特性替代样板，代码短、改起来快」；代价是「更依赖约定和读者水平，隐式行为多一点」。和 Go 比，Go 靠接口和显式装配更「看得穿」，Python 靠动态和约定更「写得爽」——又是那个老主题：没有谁更好，看你的团队和场景。

## 六、一个贴近项目的例子

把上面四个点串成一个真实的小服务骨架，你看看「Python 式」长什么样：

```python
# app/serializers.py —— 工厂（字典映射）+ 注册装饰器
_SERIALIZERS: dict[str, type] = {}

def register(name: str):
    def deco(cls):
        _SERIALIZERS[name] = cls
        return cls
    return deco

@register("json")
class JsonSerializer:
    def encode(self, data: dict) -> bytes:
        return json.dumps(data).encode()

def make_serializer(name: str):
    return _SERIALIZERS[name]()   # 工厂：按名字造

# app/strategies.py —— 策略（函数即策略）
def no_discount(price: float) -> float:
    return price

def vip_discount(price: float) -> float:
    return price * 0.9

DISCOUNTS = {"none": no_discount, "vip": vip_discount}

# app/main.py —— DI（FastAPI Depends）
from fastapi import FastAPI, Depends

def get_cache():
    c = Cache(host="localhost")
    yield c
    c.close()

app = FastAPI()

@app.post("/order")
def create_order(
    payload: OrderIn,
    cache: Cache = Depends(get_cache),         # 注入缓存
    serializer=Depends(lambda: make_serializer("json")),
):
    price = DISCOUNTS[payload.level](payload.amount)  # 策略直接调
    cache.set(payload.id, serializer.encode(payload.model_dump()))
    return {"price": price}
```

这里面：配置单例（模块级 `settings`）、序列化器工厂（注册 + 字典）、折扣策略（函数当值传）、缓存依赖注入（`Depends` + `yield` 管生命周期）。没有一个 `AbstractXxx`、`XxxImpl`、`XxxFactoryProducer`。该有的解耦全有，该短的样板全短了。你拿去和任何一份 Java Spring 的等价实现比行数，差距一目了然。

## 七、什么时候「反倒该写全模式」

老哥：听你一路讲「减肥」，我有点担心走极端——是不是所有模式都该砍成最简？

墨叔：警惕这个反弹。我说的是「别为了模式而模式」，不是「模式有害」。有几类场景，该老老实实把结构的壳写上，反而更稳：

第一，当「变化点真的会频繁扩展」时，全模式提供的「显式接口」价值就出来了。比如你做一个插件系统，第三方要来实现你的接口，这时候用 `typing.Protocol` 明确定义「插件必须有哪些方法」，比「大家心照不宣传个有 `handle` 的对象」更保护生态——因为外部贡献者看得到契约，mypy 也替他们查。Python 式不是「不要接口」，是「用 Protocol 这种轻量接口替代 Java 的 abstract class 重接口」。

第二，当代码要被不熟悉 Python 的人长期维护时，太「隐式」的写法会成为协作成本。比如单例藏在模块里、策略直接传匿名 lambda，新人读代码时得脑补「这参数哪来的、这对象是全局唯一的吗」。这时候适度加类型注解、加一行 docstring 说明「这是单例、这是注入点」，比追求极简更重要。工程可读性 > 个人炫技。

第三，当你需要框架或工具链配合时，有些结构必须保留。比如你要做依赖注入但不用 FastAPI，自己手写一个轻量 DI 容器，那「容器 + 注册表 + 解析器」这套壳是躲不掉的，因为你要解决的是「自动装配」本身，不是「少写几行」。模式服务于问题，不是服务于少写代码。

总结一句：判断该不该写全模式，问自己三个问题——「这个边界会不会被外部实现」「这段代码会不会被不熟悉 Python 的人维护」「这个结构本身是不是我要解决的核心问题」。三个里中一个，就值得把壳留着；三个都不中，就用 Python 式写法砍掉它。这和 Go 的判断逻辑其实一致：Go 里你也只在「确实需要多态」时才抽 interface，不会给每个 struct 都配接口。语言不同，工程直觉相通。

【思考题】
1. 你现在项目里有没有「为了显得专业而写出来的」工厂类或策略接口，其实用「一个函数 + 字典」就能替换？挑一个真实例子，用 Python 式重写，看能砍掉多少行，又会不会损失什么（比如类型安全、可扩展性）。
2. 模块即单例很方便，但它的「全局可变状态」本质和 Go 包级变量一样，会带来测试时的状态污染问题（一个测试改了 settings，影响另一个测试）。你打算怎么在 Python 项目里既享受单例便利、又隔离测试状态？能想到哪几种方案？
3. FastAPI 的 `Depends` 是声明式 DI。你觉得它和 Go 里「手动在 main 里 new 依赖、塞进结构体」相比，除了少写代码，还有什么深层差异（比如可测试性、循环依赖、生命周期管理）？反过来，Go 的写法有什么 Python 式 DI 反而做不来的好处？

【参考答案】
1. 典型候选是「支付方式 / 通知渠道 / 存储后端」这类「多种实现、按名选择」的场景。Java 式常写成 `interface Payment { pay() }` + `AlipayImpl` + `WechatImpl` + `PaymentFactory.get(name)`。Python 式：
   ```python
   _PAYMENTS = {"alipay": Alipay, "wechat": Wechat}
   def make_payment(name): return _PAYMENTS[name]()
   ```
   砍掉的是接口声明、工厂类、实现类样板，通常能从 60+ 行降到 10 行。会不会损失？类型安全上，Java 接口强制 `pay()` 签名一致；Python 这边用 `typing.Protocol` 补：`class Payment(Protocol): def pay(self, amount: int) -> str: ...`，再上 mypy 一样能查。可扩展性上，字典映射加一项就支持新渠道，和工厂子类一样开放，甚至更直白（不用改工厂类的 switch）。唯一真正损失的是「编译期强制所有实现都实现接口」——但 Python 用 `Protocol` + mypy 基本补回。结论：这种「分发式多实现」，Python 式几乎全面占优。
2. 模块级单例的测试污染，本质是「全局可变状态跨测试共享」。三种解法：（一）测试用 fixture 重置——pytest 里在 conftest 用 fixture 在测试前后 `monkeypatch.setattr(settings, "debug", False)` 或重建，保证每个测试前回到干净态。（二）别把「真会变的东西」放模块级单例——把配置做成「可注入」的，测试传一份覆盖配置，生产用默认，单例只装「不会变的环境信息」。（三）用 `pydantic-settings` 的 `model_copy(update=...)` 在测试里造覆盖实例，避免改原对象。核心原则：单例装「只读的全局真相」（如 db_url），可变的运行态走依赖注入，别混。这和 Go 里「包级配置变量 + 测试时覆盖」的痛点完全一样，解法也一致。
3. 深层差异：（一）可测试性——`Depends` 让依赖在「声明处」就标清，测试时 `app.dependency_overrides` 一行换掉，业务零改；Go 手动注入也得在测试 new 假依赖，但更显式、谁依赖什么一眼在结构体字段上看得见。（二）生命周期——`Depends` 的 `yield` 自动管「请求级」资源开关，Go 得自己在 handler 里 `defer db.Close()`，各有优劣。（三）循环依赖——`Depends` 延迟解析，循环依赖可能运行时才爆；Go 编译期就能发现「A 依赖 B、B 依赖 A」的结构问题，更早暴露。反过来 Go 的好处：依赖图完全静态、可读、编译器保证不漏装配；Python 式 DI 太灵活，新手容易写出「运行时才知道依赖谁」的隐式图，重构时不如 Go 看得穿。所以大型、多人、长生命周期服务，Go 的显式装配更稳；快速迭代的 Web 服务，FastAPI 式 DI 开发爽度更高。
