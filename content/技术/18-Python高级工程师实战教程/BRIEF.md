# BRIEF ·《Python 高级工程师实战教程》并行起草总纲

> 本文件是所有写作子代理的唯一事实来源。开始写任何章节前，先完整读一遍本文件。
> 输出目录：`C:\Users\admin\Desktop\Python高级工程师实战教程\`

---

## 0. 项目目标

为一位 **5 年经验的 Go 后端工程师** 写一部 Python 进阶教程，目标是让他能**在真实项目里像高级工程师一样用 Python**：
- 不只是「能跑 AI 生成的脚本」，而是**理解每个特性的设计意图、适用场景、收益与代价**；
- 覆盖「项目中常用」的语言特性、工程化、并发、测试、设计模式；
- 总中文字数 **≥ 100,000**（30 章 × 约 3500~4500 字，总量约 105,000~135,000）；
- 共 **30 篇技术章 + 1 篇导读**，每篇独立成文件，单篇中文字数 **3500 ~ 4500**（技术阅读带思考约 30 分钟）；
- 整体风格：**对话讨论式（导师「墨叔」vs 读者「老哥」）**，多反问、爱用生活化类比、频繁用 **Go 作为对照镜**。

---

## 1. 读者画像（务必时刻记着）

- 老哥：Go 主力，5 年，会写 CRUD 和中间件，协议层自认「会用不精通」。
- 对 Python：**能跑、会用 AI 生成**，但「没多深入」——知道语法，不知道「为什么这么设计」「什么时候该用哪个武器」。
- 痛点（写作时要戳中）：
  - Go 静态类型、编译期报错；Python 动态类型、运行时才炸 → 补「类型系统与 typing」。
  - Go 用 goroutine/channel + 显式 error；Python 有 GIL、threading/asyncio、异常 → 补「并发模型」。
  - Go 的 `defer`；Python 的 `with` → 对照讲上下文管理器。
  - Go 的 package/import 干净；Python 的 import 系统坑多 → 对照讲包与模块。
- **不要把他当小白**。略过：变量/循环/函数基础、print 用法、列表推导基础语法。默认他会这些。

---

## 2. 写作风格（硬性要求，违反即返工）

### 2.1 对话式骨架
- 用「墨叔」（导师，机房老兵，循循善诱、爱反问）和「老哥」（读者，Go 工程师）的**对谈**推进。
- 开头常用一个**反问**或**生活化场景**抛问题，再层层剥开。
- 例（领会精神，勿照抄）：
  > 墨叔：老哥，你说 Go 里一个函数返回 `error`，调用方必须显式 `if err != nil`。Python 没有这茬，那它的错误处理靠什么？
  > 老哥：……异常？
  > 墨叔：对，但不全对。异常在 Python 里是**控制流**，不是兜底。你先想：什么算「异常」，什么算「正常业务分支」？

### 2.2 三大锚点（每章至少用其中两项）
1. **「某特性怎么用」**：可运行最小代码（Python 3.11+ 语法，正确、简洁）。
2. **「什么场景用」**：适用/不适用边界，最好和 Go 类比。
3. **「用它的好处 / 代价」**：讲 trade-off，讲为什么这么设计。

### 2.3 生活化类比
- 难懂概念用生活场景类比（快递柜、餐厅点单、合同、停车场、流水线……），但**类比之后一定要落回代码和技术本质**。
- Go 对照是天然「理解锚」：能比就比（类型系统、defer、并发、包、错误、测试）。

### 2.4 思考题与参考答案（每章必须，且配对）
- 章末独立成行标记：
  ```
  【思考题】
  1. ...
  2. ...

  【参考答案】
  1. ...
  2. ...
  ```
- 思考题要**引发再思考**（含「延伸到项目里你会怎么做」）；参考答案要**当学习材料写**（详实、有代码或推导）。
- **禁止**在正文行内写「【思考题】」字样（校验脚本会误判），标记只在章末独立成行出现。

### 2.5 禁止事项
- 禁止 AI 味套话（「在当今快速发展的时代……」「Python 作为一门优秀的语言……」）。开头直接进问题。
- 禁止水字数：不堆 RFC 复述、不抄文档。每句话要么讲清机制，要么推动理解。
- 禁止代码示例无法运行或语法错误（3.11+）。禁止 `print` 式无聊 demo，示例要贴近真实项目。
- 禁止把「会」的内容当重点（基础 for 循环等）。聚焦「进阶 / 工程化 / 为什么」。
- 禁止 emoji。

---

## 3. 每章固定结构（子代理照此写）

```
# 第 N 章 <标题>

> 一句话点题（这章解决你项目里的什么痛点）。

（开场：墨叔抛问题 / 生活化场景，引出主题，1~2 段）

## 一、<特性名> 到底是什么（怎么用）
（概念 + 最小可运行代码 + 逐步解释）

## 二、什么场景该用它（对照 Go / 边界）
（适用 / 不适用场景、和 Go 对比、踩坑提醒）

## 三、用它的收益与代价（为什么这么设计）
（trade-off、性能/可维护性/可读性维度）

## 四、一个贴近项目的例子
（稍完整小例子，能直接用到项目里）

【思考题】
1. ...
2. ...

【参考答案】
1. ...
2. ...
```

- 标题层级：章用 `#`，节用 `##`，代码块用 ```python 围栏。
- 每章中文字数 **3500~4500**（用第 5 节脚本自证，下限 3500）。

---

## 4. 章节清单（30 章技术章 + 00 导读，文件名即 序号-标题.md）

| 文件 | 标题 | 核心要点 |
|---|---|---|
| 00-导读.md | 导读：从 Go 老兵到 Python 高级工程师 | 墨叔开场；为什么写；和 Go 关系；怎么用；阅读建议。**无思考题（豁免）**。 |
| 01-思维对撞.md | Python 与 Go 的思维方式对撞 | 动态vs静态；鸭子类型；EAFP vs LBYL；运行时哲学；对照表。 **（已写，样本）** |
| 02-类型系统进阶.md | 类型系统进阶：type hints 是工程契约 | 注解本质（不强制）；typing；TypeVar/Generic 泛型；Protocol 结构子类型（对照 Go interface）；mypy 收益。 |
| 03-装饰器.md | 装饰器：给函数穿衣服的艺术 | 一等公民；闭包；装饰器本质；functools.wraps；类装饰器；叠加；场景（缓存/计时/鉴权/重试）——对照 Go 中间件。 |
| 04-生成器迭代器.md | 生成器与迭代器：惰性计算救内存 | 可迭代/迭代器协议；yield；生成器表达式；send/yield from；惰性求值收益；大文件/流式。 |
| 05-上下文管理器.md | 上下文管理器：Python 的 defer | with 协议（__enter__/__exit__）；@contextmanager；contextvars；异常安全清理——对照 Go defer。 |
| 06-函数式工具箱.md | 函数式工具箱：functools 与 itertools | map/filter/lambda 取舍；lru_cache/partial/reduce；itertools（chain/groupby/islice）；和 Go 差别。 |
| 07-数据模型魔术方法.md | 数据模型与魔术方法 | dunder 总览；__str__/__repr__ 区别；__call__；__getitem__/__iter__；让对象像内置类型；运算符重载。 |
| 08-描述符与property.md | 描述符与 @property | 描述符协议；@property 本质；校验/惰性属性；ORM/attrs/pydantic 底层原理。 |
| 09-枚举与模式匹配.md | 枚举与模式匹配：告别魔法字符串 | enum.Enum（状态/类型安全，对照 Go const+iota）；match/case（对照 Go switch，带模式解构）。 |
| 10-包与模块.md | 包与模块：import 机制深坑 | import 系统；__init__；绝对vs相对导入；循环导入；命名空间包；sys.path——对照 Go package。 |
| 11-虚拟环境与依赖.md | 虚拟环境与依赖管理 | venv；pip；requirements vs pyproject.toml；poetry/uv；lockfile；可复现构建。 |
| 12-配置与环境.md | 配置与环境：pydantic 实战 | 12-factor；环境变量；.env；pydantic Settings 校验；配置即类型；多环境。 |
| 13-异常设计.md | 异常设计：Python 的错误处理哲学 | 异常层级；自定义异常；EAFP；何时异常vs返回值；异常链——对照 Go error。 |
| 14-日志.md | 日志：logging 模块与结构化 | logging 基础；level/handler/formatter；结构化日志；避免 print 调试。 |
| 15-并发全景.md | 并发全景：GIL 卡了什么 | GIL 本质；CPU密集vs IO密集；threading/asyncio/multiprocessing 决策树；对照 Go 并发。 |
| 16-asyncio深度.md | asyncio 深度：事件循环与任务 | 事件循环；async/await；Task/gather；取消与超时；真实项目模式（并发请求）。 |
| 17-异步生态实战.md | 异步生态实战：httpx 与异步数据库 | aiohttp/httpx；异步 DB 驱动；同步代码混用陷阱；何时值得上异步。 |
| 18-多线程多进程.md | 多线程与多进程实战 | threading；multiprocessing；concurrent.futures；进程间通信；GIL 挡路时。 |
| 19-性能剖析优化.md | 性能剖析与优化 | cProfile；时间/内存剖析；缓存；__slots__；dataclass vs dict；常见瓶颈。 |
| 20-dataclasses数据结构.md | dataclasses 与数据结构 | dataclass/attrs/namedtuple；少写样板；默认值坑（mutable default）；何时用。 |
| 21-序列化与数据交换.md | 序列化与数据交换 | json/pickle 取舍；dataclass↔dict/json；pydantic 深入；版本兼容。 |
| 22-标准库精读.md | 标准库精读：collections/pathlib/datetime | Counter/defaultdict/deque/OrderedDict；pathlib 取代 os.path；datetime 坑；argparse。 |
| 23-文件与IO.md | 文件与 IO：编码坑与流式 | 编码（utf-8 默认但到处坑）；文本/二进制；流式读大文件；with 配合；临时文件。 |
| 24-调试与排错.md | 调试与排错：pdb 与 traceback 阅读 | pdb 基础；断点；远程/事后调试；读懂 traceback；logging 辅助；常见诡异 bug 套路。 |
| 25-测试工程.md | 测试工程：pytest 全家桶 | pytest 基础；fixture；parametrize；mock；覆盖率——对照 Go testing。 |
| 26-代码质量流水线.md | 代码质量流水线 | ruff/flake8；black；isort；mypy；pre-commit；CI 集成。 |
| 27-设计模式Python式.md | 设计模式 Python 式写法 | 单例（模块即单例）；工厂；策略；依赖注入；Pythonic 实现，不硬套 Java 八股。 |
| 28-项目结构最佳实践.md | 项目结构最佳实践 | 可安装包布局；__main__.py；cookiecutter 式目录；分层（router/service/repo）；CLI 入口。 |
| 29-项目实战FastAPI.md | 项目实战：FastAPI 分层服务骨架 | 串起全篇：分层、依赖注入、pydantic、异常、测试；一个可跑的小服务。 |
| 30-进阶路线与收尾.md | 进阶路线与收尾：从「会用」到「精通」 | 学习地图；下一步读什么；参与开源；把 Python 当第二母语。**无思考题（豁免）**。 |

> 00-导读.md 与 01-思维对撞.md 已由主代理（墨叔）亲自写定，不分配给子代理，作为风格与长度样本。
> 其余 02~29 由子代理并行撰写；30 收尾章可由主代理或某子代理写。

---

## 5. 字数自证脚本（每章写完后运行）

子代理写完自己的章节后，用受管 Python 校验**自己负责的每个文件**中文字数是否 ≥ 3500：

```python
import re, glob, os
base = r'C:\Users\admin\Desktop\Python高级工程师实战教程'
files = [r'C:\Users\admin\Desktop\Python高级工程师实战教程\03-装饰器.md',  # 改成你负责的文件列表
        ]
for f in files:
    t = open(f, encoding='utf-8').read()
    n = len(re.findall(r'[一-鿿]', t))
    print(os.path.basename(f), n, 'OK' if n >= 3500 else 'TOO SHORT')
```

不足则**扩展对应章节**（追加「五、进阶细节」「六、更多场景」等小节），不要删改已合格内容。

---

## 6. 交付要求（子代理返回内容）

每个子代理任务完成后，返回一句话：`已写 <文件列表>，中文字数 <各文件字数>`。
不要回灌整章正文到主对话（避免污染上下文），只回路径与字数。
