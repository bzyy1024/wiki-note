# 第 8 章 描述符与 @property

> 这一章帮你揭开 @property 的底层，看懂 SQLAlchemy、attrs、pydantic 这些框架到底在「属性访问」上玩了什么把戏——看完你再读它们源码，不会再一脸懵。

墨叔：老哥，你在 Go 里给结构体加字段，外部直接 `u.Age = 18` 就完事了。要是想加个校验——比如年龄不能是负数——你得自己写个 `SetAge(int) error`，然后祈祷所有人都调它，而不是手贱直接 `.Age = -1`。Python 呢？你想让一个「看起来像字段、用起来像字段」的东西背后藏着逻辑，靠的就是 @property，更深一层，靠的是描述符。

老哥：property 我见过，就是 `@property` 加 `@age.setter`，把方法伪装成属性。但你说它底层是描述符，这俩啥关系？

墨叔：问到点子上了。这章我就把这层窗户纸捅破：**@property 不过是描述符协议的一个语法糖**，而描述符是 Python 属性访问机制的「地基」。你搞懂地基，不仅能写出自己的 property 类，还能一眼看穿那些框架的魔法。咱们从「属性访问到底发生了什么」讲起。

## 一、描述符协议到底是什么（怎么用）

你每次写 `obj.attr`，Python 背后不是简单查字典，而是走一套查找规则。这套规则里最关键的角色，就是**描述符（descriptor）**——一个实现了特定方法的对象。

一个对象只要实现了下面三个方法里的任意一个，就被当作描述符：

```python
class Descriptor:
    def __get__(self, instance, owner=None):
        ...
    def __set__(self, instance, value):
        ...
    def __delete__(self, instance):
        ...
```

- `__get__(self, instance, owner)`：当你**读取** `obj.attr` 时调用。`instance` 是持有它的实例，`owner` 是它的类。
- `__set__(self, instance, value)`：当你**写入** `obj.attr = value` 时调用。
- `__delete__(self, instance)`：当你 `del obj.attr` 时调用。

注意区分两个概念，这是新手最容易混的：

- **数据描述符（data descriptor）**：实现了 `__set__` 或 `__delete__`。
- **非数据描述符（non-data descriptor）**：只实现了 `__get__`（比如函数、classmethod、staticmethod 都是这个）。

这个区分后面讲优先级时会救命，先记着。

来个最小例子，自己写一个描述符，让它每次读取属性时都打日志：

```python
class Logged:
    def __init__(self, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        value = instance.__dict__.get(self.name)
        print(f"[读] {self.name} = {value!r}")
        return value

    def __set__(self, instance, value):
        print(f"[写] {self.name} = {value!r}")
        instance.__dict__[self.name] = value


class User:
    age = Logged("age")


u = User()
u.age = 30          # 触发 __set__，打印 [写] age = 30
print(u.age)        # 触发 __get__，打印 [读] age = 30，再输出 30
```

关键点在这里：`age` 不是 `User` 类的普通字段，而是**类属性上的一个描述符对象**。`u.age = 30` 时，Python 看到 `User.age` 是个数据描述符，于是把赋值请求转交给 `Logged.__set__`，由它决定怎么存——这里它存进了实例自己的 `instance.__dict__`。`u.age` 读取同理，转交给 `__get__`。

墨叔：你品一下这个结构。描述符把自己挂在「类」上，但它操作的是「实例」的数据。这就像小区门口的快递柜（描述符）属于物业（类）管理，但每个柜子存的都是某户人家（实例）的包裹。快递柜统一管「怎么存取」，住户只管「我的柜子在几号」。

## 二、@property 本质就是描述符语法糖

老哥：那 @property 怎么就跟描述符挂钩了？

墨叔：猜一下，`property` 本身是什么？它其实是个**内置类**，而且是个完整实现了描述符协议的数据描述符。你写的 `@property` + `@x.setter` 语法，等价于手动 `x = property(getter, setter, deleter, doc)`。看等价写法：

```python
class User:
    def __init__(self, age):
        self._age = age

    def get_age(self):
        return self._age

    def set_age(self, value):
        if value < 0:
            raise ValueError("年龄不能为负")
        self._age = value

    age = property(get_age, set_age)   # 和 @property + @age.setter 完全等价


u = User(18)
print(u.age)        # 18，调用 get_age
u.age = -5          # 抛 ValueError，因为 set_age 校验失败
```

装饰器写法只是把 `property(get_age, set_age)` 这块语法糖做得更甜：

```python
class User:
    def __init__(self, age):
        self._age = age

    @property
    def age(self):
        """读取时返回实际值。"""
        return self._age

    @age.setter
    def age(self, value):
        if value < 0:
            raise ValueError("年龄不能为负")
        self._age = value
```

两者底层一模一样：`age` 这个 `property` 对象挂在 `User` 类上，是个数据描述符。读 `u.age` → `property.__get__` → 调 `get_age`；写 `u.age = v` → `property.__set__` → 调 `set_age`。

对照 Go：Go 没有属性概念，要么直接暴露字段 `Age int`，要么写 `GetAge()/SetAge()` 两个方法。直接暴露字段就丢了校验能力；写方法就得多打一堆括号 `u.SetAge(18)`，调用方还得记住「这个字段有 setter，那个没有」。Python 用 property 把「字段的简洁」和「方法的灵活」捏一块了——外部永远写 `u.age = 18`，至于背后是裸字段还是校验逻辑，调用方根本不关心。这叫「接口稳定，实现可换」。

老哥：那是不是说，我一开始写 `self.age = 18` 当普通字段，后来想加校验了，直接改成 property，外面调用代码一行都不用动？

墨叔：一针见血！这就是 property 最大的工程价值——**它是不破坏 API 的前提下，给字段悄悄加上逻辑的通道**。Go 里你要从 `u.Age = 18`（字段）改成 `u.SetAge(18)`（方法），所有调用点都得改。Python 几乎零成本升级。这也是为什么很多库能长期保持接口兼容。

## 三、用它的收益与代价（为什么这么设计）

墨叔：光会用不够，你得想清楚「什么时候值得上描述符，代价是什么」。

**收益有三层：**

1. **复用逻辑，消灭样板**。如果 `User`、`Order`、`Product` 都要做「非负年龄」「非负价格」校验，每次写 `@property`/`@setter` 还是重复。把校验逻辑抽成一个描述符类，挂到任意字段上即可，像装饰字段一样复用。
2. **惰性属性（lazy）**。有些属性计算很贵（比如从数据库拉关联数据、算一份大报表），你不想在 `__init__` 里就付这个代价，而是「第一次访问时才算，算完缓存」。描述符是做这个的天然容器。
3. **统一拦截访问**。框架想在所有属性读写上插一脚（ORM 跟踪「哪些字段被改了」以便生成 UPDATE 语句），靠的就是描述符——你 `.attr` 一下，框架就知道了。

**代价也要说清：**

- 描述符对象挂在**类**上，对所有实例**共享**。所以它内部**绝对不能**保存「属于某个实例的状态」——上面例子里状态存在了 `instance.__dict__`，而不是描述符自己身上。新手最爱写成 `self._value = value`，结果所有实例共享同一个值，炸得莫名其妙。
- 调试变难。属性访问不再是「查字典」，而是「调函数」，出错时 traceback 多一层，性能也比裸字段略慢（每次访问多一次函数调用）。
- 过度使用会让代码「魔幻」。一个字段背后藏了远程调用，调用方不知情，容易写出性能坑。

所以规则是：**公开 API、可能加校验/缓存的字段，用 property；纯内部状态、高频访问的字段，直接裸字段**。

## 四、一个贴近项目的例子

光讲协议太虚，给你个真实项目里能直接用的——一个 `Lazy` 描述符做惰性加载，加一个 `Validated` 做通用校验。

```python
import re
from typing import Callable


class Lazy:
    """第一次访问才计算并缓存，之后直接返回缓存。"""

    def __init__(self, func: Callable):
        self.func = func
        self.name = func.__name__

    def __get__(self, instance, owner):
        if instance is None:
            return self
        if self.name not in instance.__dict__:
            instance.__dict__[self.name] = self.func(instance)
        return instance.__dict__[self.name]


class Validated:
    """通用校验描述符：传入校验函数，失败抛 ValueError。"""

    def __init__(self, validate: Callable[[object, object], None]):
        self.validate = validate
        self.name = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.get(self.name)

    def __set__(self, instance, value):
        self.validate(instance, value)
        instance.__dict__[self.name] = value


def non_empty(value):
    if not str(value).strip():
        raise ValueError("不能为空")


class Article:
    title = Validated(lambda i, v: non_empty(v))

    def __init__(self, title, source_text):
        self.title = title
        self._source = source_text

    @Lazy
    def word_count(self):
        # 假设这是一次昂贵的统计
        return len(self._source.split())

    @Lazy
    def summary(self):
        return self._source[:120]


a = Article("Python 描述符入门", "这是一篇很长很长很长很长的文章 " * 50)
print(a.title)           # 触发校验通过的赋值
print(a.word_count)      # 第一次访问才计算
print(a.word_count)      # 第二次直接读缓存，不再算
a.title = "   "          # 抛 ValueError: 不能为空
```

这里有两个新角色：`__set_name__` 是 Python 3.6+ 给描述符的「出生时回调」——描述符被赋值到类上时，解释器自动调用它，告诉我们「你叫什么名字」，省得手动传名字。这个细节在框架里大量使用，一定要记。

老哥：等等，你 `__get__` 里用 `instance.__dict__.get(self.name)`，那如果有人恰好也有个同名 key 不就冲突了？

墨叔：好眼力。真实框架会加前缀避开冲突，比如存成 `_lazy_word_count`。我这里简化的写法在单描述符场景下没问题，但你提的隐患在复杂的类里确实存在，正经写库时都会加命名空间前缀。

## 五、看懂框架：ORM / attrs / pydantic 的把戏

这才是这章的「爽点」——你读完上面，再看 SQLAlchemy 这类代码，就该笑了。

**SQLAlchemy 的 `Column` 是描述符。** 你写：

```python
class User(Base):
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
```

`Column` 对象挂在 `User` 类上，是个描述符。当你 `user.name = "Tom"`，触发 `Column.__set__`，它不直接存，而是先记到实例的「待提交变更」里（`instance._sa_instance_state`），这样 ORM 知道「这个字段被改了，之后 UPDATE 要带上」。当你 `user.name`，`Column.__get__` 去状态里取当前值，可能还会做类型转换（把数据库里的字符串转成 Python 的 str）。**整个 ORM 的「对象-表」映射魔法，地基就是描述符拦截属性读写。** 你现在回头看源码里 `Column.__get__`/`__set__`，不会觉得是黑魔法了。

**attrs / pydantic 同理。** pydantic 的 `BaseModel` 在类创建时（`__init_subclass__` / metaclass），把你声明的 `name: str` 字段收集起来，生成一个描述符或 `__pydantic_fields__` 元数据。当你 `User(name="Tom")` 或 `user.name`，校验和类型转换都在描述符（或重写的 `__setattr__`）里完成。很多同学以为 pydantic 是「在 `__init__` 里一个个 if 校验」，其实底层是描述符 + 类构造期元编程的组合拳，所以才又快又干净。

墨叔：你现在理解为什么我说「描述符是地基」了吧？`@property`、`classmethod`、`staticmethod`、ORM 字段、pydantic 字段，甚至函数本身（函数在类里是非数据描述符，所以能绑定成方法），全都是描述符协议的产物。你掌握了协议，等于拿到了「Python 一切属性访问」的万能钥匙。

老哥：那描述符优先级那个坑呢？你说数据和非数据描述符不一样。

墨叔：问得好，补一刀。属性查找顺序（简化版）是：**数据描述符 > 实例 `__dict__` > 非数据描述符 > 类 `__dict__`**。所以：

- 数据描述符（有 `__set__`）优先级最高，哪怕你在 `instance.__dict__` 里塞了同名 key，访问时还是走描述符。
- 非数据描述符（只有 `__get__`，比如方法）会被实例 `self.x = 1` 覆盖——这就是为啥你能临时给实例挂个属性「遮蔽」掉方法，但不推荐这么干。

记住这条线，你遇到「我明明赋值了为什么读出来不对」「我覆盖了属性为什么方法没了」这类诡异 bug，直接拿这条顺序去对，十拿九稳。

## 六、实战演示：数据描述符如何「压制」实例属性

光说优先级太抽象，给个能跑的例子，把它刻进你的直觉。假设我们故意在实例字典里塞一个和描述符同名的 key，看谁赢：

```python
class Guard:
    def __get__(self, instance, owner):
        if instance is None:
            return self
        return instance.__dict__.get("_secret")

    def __set__(self, instance, value):
        instance.__dict__["_secret"] = value


class Demo:
    secret = Guard()          # 数据描述符（实现了 __set__）


d = Demo()
d.secret = "abc"              # 走 Guard.__set__，存进 _secret
print(d.secret)              # abc

# 现在直接往实例字典塞一个同名 key
d.__dict__["secret"] = "hacked"
print(d.secret)              # 还是 abc！因为数据描述符优先级高于实例字典
```

注意最后一行：`d.__dict__` 里明明有了 `"secret": "hacked"`，但 `d.secret` 读出来的还是 `"abc"`。原因就是查找顺序：**数据描述符 > 实例 `__dict__`**。描述符把实例字典里那个同名 key 「盖」住了。

反过来，如果把 `Guard` 的 `__set__` 删掉，它变成「非数据描述符」（只剩 `__get__`，跟普通方法一样），那么 `d.__dict__["secret"] = "hacked"` 就会生效——`d.secret` 返回 `"hacked"`，因为此时实例字典排在描述符前面。这个区别，就是你偶尔看到「我给实例动态挂了个属性，居然把方法/property 盖掉了」这类怪事的根源。理解这条线，你对「属性访问」就有底了。

## 七、什么时候该自己写描述符

落到工程决策。三种情况我建议你手写描述符，其余用 `@property` 足矣：

1. **同样的逻辑要挂在多个类的多个字段上**（校验、单位转换、日志、懒加载）——抽描述符类复用。
2. **需要 `__set_name__` 自动拿到字段名**（比如 ORM 列名、序列化字段名）。
3. **想做框架级能力**（统一拦截、状态跟踪），那是库的活儿。

如果只是「这一个字段加个校验」，别上描述符，直接 `@property` 最清楚。过早抽象成描述符类，反而是过度设计——你 Go 写多了也知道，`interface` 不是越多越好。

最后给你一句判断口诀：**「一个字段用 property，一类字段用描述符」**。当你发现自己在三个类里复制粘贴差不多的 `@property`/`@setter` 校验，那就是信号——把它抽成一个描述符类（像前面 `Validated` 那样），一挂了事。反过来，如果一个描述符类只被一个字段用、且逻辑很特化，那它大概率是过度抽象，退回 `@property` 更直白。这份「该抽还是该摊开」的直觉，就是高级工程师和普通开发的分水岭：不是写得越通用越好，而是**刚好覆盖复用需求、又不制造理解负担**。你回过头把这一章的链路串一遍——描述符协议是地基，`@property` 是它派生的语法糖，`Lazy`/`Validated` 是手写描述符的实战形态，而 SQLAlchemy、pydantic 这些框架只是在这套地基上盖了更高的楼——下次读它们的源码，你应该能认出每一块砖是哪来的。

【思考题】
1. 你在 Go 里给 `User` 加 `Age int`，现在需求变成「年龄赋值必须非负」。Go 和 Python 各自要改什么？谁的调用方改动更小？这背后体现了两种语言的什么设计取向？
2. 描述符对象挂在「类」上、被所有实例共享。如果我在描述符的 `__init__` 里写了 `self._cache = {}`，想用它缓存每个实例的值，会发生什么 bug？正确的状态该存在哪里？
3. 阅读你项目里任意一个用 pydantic 或 SQLAlchemy 的模型，指出其中哪一行对应「描述符」或「类构造期收集字段」。试着解释它赋值时到底走了什么代码路径。

【参考答案】
1. Go 方案：把 `Age int` 改为私有 `age int` 并新增 `SetAge(int) error` + `GetAge() int`，所有 `u.Age = x` 的调用点都得改成 `u.SetAge(x)`（且要处理 error），改动面大。Python 方案：把 `self.age = age` 改成带 `@property`/`@age.setter` 的属性，外部 `u.age = x` 一行不用动，校验逻辑藏在 setter 里。这体现了 Go「显式、编译期契约，改接口要全改」与 Python「接口稳定、实现可换、运行时拦截」的分歧。Python 在「字段逐步变聪明」的演进中成本极低，这也是它适合快速迭代、库长期兼容的原因之一；代价是调用方无法从语法上区分「裸字段」和「带逻辑的属性」，容易踩隐蔽的性能/副作用坑。
2. 灾难性 bug：`self._cache = {}` 在描述符对象自身上，而描述符只被创建一次、被所有实例共享。于是 `u1.age = 1`、`u2.age = 2` 会把值存进**同一个** `_cache` 字典，导致不同实例的值互相覆盖、串台。正确做法：**状态绝不存描述符自己身上**，而是存到 `instance.__dict__`，比如 `instance.__dict__[self.name] = value`，或以实例 id 为 key 存（`instance.__dict__` 天然按实例隔离，最干净）。这正是「描述符管逻辑、实例管数据」的铁律。
3. 以 pydantic 为例：`class User(BaseModel): name: str = Field(max_length=10)` 这一行，在 `User` 类被创建（metaclass / `__init_subclass__`）时，pydantic 扫描注解收集出 `name` 字段的元信息到 `__pydantic_fields__`（相当于 `__set_name__` 的进阶版，自动拿到字段名和注解）。赋值时 `User(name="Tom")` → `__init__` → 内部走描述符式或重写的 `__setattr__`，对每个字段做「类型校验 + 约束校验（max_length）+ 类型转换」，失败抛 `ValidationError`；读取 `user.name` 走 `__getattribute__`/描述符取值。SQLAlchemy 的 `Column(...)` 行同理，列对象在类构造期登记进 `Mapper`，赋值时被描述符拦截进实例状态，供后续 flush 生成 SQL。看懂这两处「类构造期收集」+「属性访问拦截」，就算真正进了框架源码的门。
