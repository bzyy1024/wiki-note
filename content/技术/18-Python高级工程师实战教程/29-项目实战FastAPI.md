# 第 29 章 项目实战：FastAPI 分层服务骨架

> 这一章把前面二十八章的武器全装到一把枪上：用 FastAPI 搭一个能跑、能测、能上生产的待办服务，让你亲眼看到分层、依赖注入、pydantic、全局异常、pytest 在真实项目里怎么咬合。

墨叔：老哥，你前面二十八章的武器都摸过了——类型注解、异常设计、依赖注入、pytest、项目结构。可我打赌你心里还悬着一个问题：这些东西单拎出来都懂，真要写个服务，它们到底怎么长在一块儿？你写 Go 时 `handler → service → repo` 一套组合拳闭眼都能敲，换 Python 你是把 FastAPI 的 route 函数当成 controller，还是把所有逻辑糊进一个函数里？我见过太多人，FastAPI 的 `app.post` 里直接 `db.execute(sql)` 再拼 JSON，三个月后那函数比他的简历还长。咱今天不聊概念，直接搭一个能 `pip install` 起来、`pytest` 跑绿的待办服务，每贴一段代码我就点一句「这是第几章的哪个特性」。

## 一、分层骨架与依赖注入（怎么用）

先说骨架。FastAPI 本身不管你怎么分层，它只认 `APIRouter` 和 `Depends`。分层是你自己立的规矩，跟 Go 里没人逼你分 `handler/service/repo`、但你照做一样。我把目录先摆出来，再逐文件讲。

```text
todo_service/
├── pyproject.toml
├── src/
│   └── todo_app/
│       ├── __init__.py
│       ├── __main__.py        # uvicorn 启动入口
│       ├── main.py           # FastAPI app + 全局异常处理器
│       ├── api.py            # router 层：只管 HTTP 协议
│       ├── service.py        # service 层：业务规则
│       ├── repository.py     # repository 层：数据存取
│       ├── models.py         # pydantic 请求/响应模型
│       ├── errors.py         # 自定义业务异常
│       └── di.py             # 依赖注入装配
└── tests/
    ├── conftest.py
    ├── test_service.py
    └── test_api.py
```

这套布局和你说第 28 章学的 `src/` + 分层一模一样，这里不多废话。重点看 `di.py`——依赖注入。

```python
# src/todo_app/di.py
from fastapi import Depends
from todo_app.repository import TodoRepository
from todo_app.service import TodoService

_repo = TodoRepository()                       # 进程级单例，等价于 Go 的包级变量

def get_repository() -> TodoRepository:
    return _repo

def get_service(repo: TodoRepository = Depends(get_repository)) -> TodoService:
    return TodoService(repo)
```

老哥：等等，这 `Depends` 不就是 Go 里我手动 `svc := NewTodoService(repo)` 然后传进去？

墨叔：对，但更懒。Go 里依赖装配要么是 `wire` 这种代码生成、要么是你手写 `func NewServer() *Server { repo := NewRepo(); svc := NewSvc(repo); ... }`，编译期就把依赖图钉死。FastAPI 的 `Depends` 是**运行时按请求解析**的：框架看到 `svc: TodoService = Depends(get_service)`，就先调 `get_service`，而 `get_service` 又声明自己依赖 `get_repository`——框架递归把整条链拼好，再把成品塞进你的 route 函数。你看 `get_service(repo: ... = Depends(get_repository))` 这个参数，既是「声明依赖」又是「运行时实参」，Go 里这两件事是分开的（声明在类型、装配在 main）。代价是：依赖图的正确性你编译期看不到，要等测试或启动时才暴露——所以第 25 章的 pytest 在这里不是锦上添花，是兜底。

给你一个生活化类比：把这服务想成一家餐厅。`repository` 是后厨仓库，只管存货取货；`service` 是厨师，按菜谱把原料做成菜，不关心货从哪来；`api` 是前台服务员，只管把客人点的单翻译成后厨能懂的指令、再把做好的菜端出去。客人（HTTP 请求）永远只跟服务员说话，绝不会冲进仓库自己拿土豆。`Depends` 干的事，就是餐厅经理在开门前把「仓库→厨师→服务员」这条供应链悄悄接好——Go 里这条链是装修时（编译期）就焊死的，Python 里是每来一桌客人（每个请求）经理临时按图接的。好处是灵活，比如测试时经理换成「假仓库」，真仓库停电也不影响你验菜谱对不对；坏处就是你得靠试吃（测试）来确认链没接错，编译期不会替你喊停。

这里用到了第 27 章讲的「依赖注入」模式、第 2 章的 `Protocol` 思路（真实项目里 `TodoRepository` 应是个 `Protocol` 抽象，测试时换内存实现），还有第 28 章的 `src/` 布局纪律。

## 二、pydantic 做请求/响应模型与校验（什么场景用）

Go 里你收请求，要么用 `json.Unmarshal` 再手写 `if body.Title == ""` 校验，要么上 `validator` 标签。pydantic 把「反序列化 + 校验」合二为一，而且校验失败 FastAPI 自动回 422，你不用写一行 if。

```python
# src/todo_app/models.py
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

class TodoStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"

class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)   # 空标题直接 422
    owner: str = Field(min_length=1, max_length=50)

class TodoOut(BaseModel):
    id: int
    title: str
    owner: str
    status: TodoStatus
    created_at: datetime
```

老哥：这 `TodoOut` 当响应模型，FastAPI 真会按字段过滤？

墨叔：会，而且这是 pydantic 最香的地方之一。你 service 层返回的领域对象可能带一堆内部字段（密码哈希、内部标记），只要 `response_model=TodoOut`，FastAPI 会用 `TodoOut.model_validate` 只挑声明的字段序列化出去，多出来的自动剥掉。对照 Go：你要么手写一个 `TodoDTO` 再 `copier.Copy`，要么用 `json:"-"` 标签屏蔽字段——pydantic 用「响应模型即契约」一句话搞定。这里底层其实是第 8 章讲的「描述符」：`Field(...)` 声明的每个字段都是一个描述符，负责校验和序列化，你不用关心它怎么拦下非法值。

注意 `TodoStatus(str, Enum)`——这正是第 9 章讲的枚举，把「pending/done」这种魔法字符串变成类型安全的成员，路由里拿到的就是枚举而不是裸字符串。什么场景用 pydantic？所有「边界」：HTTP 入参、配置（第 12 章）、跨服务消息体。什么场景不用？纯内存的领域计算、热点循环里反复 `model_validate` 会有开销，那种地方用第 20 章的 `dataclass` 更轻。

老哥：pydantic 校验失败自动回 422，这个行为我能改吗？比如我想对空标题回 400 而不是 422。

墨叔：能改，但先想清楚语义。422（Unprocessable Entity）是 FastAPI 故意选的——它区分「请求格式错（400 Bad Request，比如不是合法 JSON）」和「格式对但业务校验不过（422）」。你用 `Field(min_length=1)` 拦的是后者，所以默认 422 其实是准确的，别为了「习惯 400」就改。真要统一状态码，在全局异常处理器里接 `RequestValidationError`（`from fastapi.exceptions import RequestValidationError`）自定义回 400 即可，但那等于抹掉了格式错和校验错的区分，调用方排错反而更费劲。这又回到第 13 章那句话：异常/状态码的语义是给调用方看的契约，改之前想清楚对方靠它怎么排错，别凭肌肉记忆动刀。

## 三、全局异常处理：把业务异常翻译成 HTTP 状态码（对照 Go 错误中间件）

你写 Go，习惯在 `main` 或 `middleware` 里 `if err != nil { writeStatus(w, code) }`，把领域错误映射成 HTTP 状态。FastAPI 用「全局异常处理器」干同一件事，而且比中间件更精准——它能按异常类型分派。

```python
# src/todo_app/errors.py
class TodoError(Exception):
    code: str = "todo_error"

class NotFoundError(TodoError):
    code = "not_found"

class ConflictError(TodoError):
    code = "conflict"
```

```python
# src/todo_app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from todo_app.api import router
from todo_app.errors import TodoError, NotFoundError

app = FastAPI(title="todo-service")

@app.exception_handler(TodoError)
async def handle_todo_error(request: Request, exc: TodoError) -> JSONResponse:
    status = 404 if isinstance(exc, NotFoundError) else 409
    return JSONResponse(status_code=status,
                        content={"error": exc.code, "detail": str(exc)})

app.include_router(router)
```

老哥：那我 route 里直接 `raise NotFoundError(...)` 就行，不用自己拼 404？

墨叔：正是。service 层只管抛领域异常（第 13 章的「异常是控制流」），不碰 `HTTPException`——这样 service 是可复用的，既能给 HTTP 用，也能给 CLI 或定时任务用。`NotFoundError` 继承自 `TodoError`，这里用 `isinstance` 把「找不到」映射成 404、其他业务冲突映射成 409。对照 Go 的 `errors.As(err, &NotFoundErr)` 再决定状态码，思路完全一致，只是 Python 用异常分派、Go 用错误变量判断。好处是 route 函数干干净净，坏处是：忘了注册 handler 时，未捕获的业务异常会落到 FastAPI 默认的 500，所以上线前务必给每个自定义异常配 handler，别裸奔。

再戳一个你容易忽略的点：全局异常处理器是「按类型就近匹配」的。`@app.exception_handler(TodoError)` 只接 `TodoError` 及其子类，如果一个你没预料的异常（比如 repo 里真连库时抛的 `OperationalError`）冒上来，它不在 `TodoError` 体系里，于是走 FastAPI 默认的 500 兜底。真实项目里我会再补一个「兜底 handler」接 `Exception`，统一回 500 并打日志（第 14 章结构化日志），既不让调用方看到 Python 的内部堆栈，也不让异常静默消失。这对照 Go 的中间件里 `if err != nil { log; write 500 }` 收尾那段——无论哪层漏的错，最后都有一个统一出口，绝不让它穿透到客户端。

## 四、service 与 repository 层：业务与存储解耦（贴近项目的例子）

骨架搭好，往里填肉。repository 只管存取，用内存字典假装数据库，真实项目里换成 SQLAlchemy/asyncpg 即可，接口形状不变。

```python
# src/todo_app/repository.py
from todo_app.models import TodoCreate, TodoOut, TodoStatus
from todo_app.errors import NotFoundError
from datetime import datetime

class TodoRepository:
    def __init__(self) -> None:
        self._rows: dict[int, dict] = {}
        self._seq = 0

    def create(self, data: TodoCreate) -> TodoOut:
        self._seq += 1
        row = {"id": self._seq, "title": data.title, "owner": data.owner,
               "status": TodoStatus.PENDING, "created_at": datetime.now()}
        self._rows[self._seq] = row
        return TodoOut(**row)

    def get(self, todo_id: int) -> TodoOut:
        row = self._rows.get(todo_id)
        if row is None:
            raise NotFoundError(f"todo {todo_id} not found")
        return TodoOut(**row)

    def list_by_owner(self, owner: str) -> list[TodoOut]:
        return [TodoOut(**r) for r in self._rows.values() if r["owner"] == owner]
```

```python
# src/todo_app/service.py
from todo_app.models import TodoCreate, TodoOut
from todo_app.repository import TodoRepository
from todo_app.errors import ConflictError

class TodoService:
    def __init__(self, repo: TodoRepository) -> None:
        self.repo = repo

    def create(self, data: TodoCreate) -> TodoOut:
        if not data.title.strip():
            raise ConflictError("title 不能为空白")   # 业务规则在 service，不在 repo
        return self.repo.create(data)

    def get(self, todo_id: int) -> TodoOut:
        return self.repo.get(todo_id)

    def list_by_owner(self, owner: str) -> list[TodoOut]:
        return self.repo.list_by_owner(owner)
```

老哥：校验放 service 还是 pydantic？刚才 `min_length=1` 不是已经拦了空标题吗？

墨叔：好问题，这正是边界意识。pydantic 拦的是「格式」——长度、类型、是否为空串。service 拦的是「业务」——比如「标题全是空格算不算空」「这个 owner 是否已被封禁」「同 title 是否重复」。空格标题 `Field(min_length=1)` 放不过，因为 `"  "` 长度大于 1；但业务上它该被拒，所以 service 再 `strip()` 一刀。这分工和 Go 一模一样：`validator` 标签管格式，service 管规则。别把业务校验塞进 pydantic，也别在 route 里查库——第 28 章讲的「分层不串味」在这里就是铁律。

## 五、router 层：把一切接上 HTTP

最后把上面的零件拧到 HTTP 上。

```python
# src/todo_app/api.py
from fastapi import APIRouter, Depends
from todo_app.models import TodoCreate, TodoOut
from todo_app.service import TodoService
from todo_app.di import get_service

router = APIRouter(prefix="/todos", tags=["todos"])

@router.post("", response_model=TodoOut, status_code=201)
def create_todo(data: TodoCreate, svc: TodoService = Depends(get_service)) -> TodoOut:
    return svc.create(data)

@router.get("/{todo_id}", response_model=TodoOut)
def get_todo(todo_id: int, svc: TodoService = Depends(get_service)) -> TodoOut:
    return svc.get(todo_id)

@router.get("", response_model=list[TodoOut])
def list_todos(owner: str | None = None, svc: TodoService = Depends(get_service)) -> list[TodoOut]:
    return svc.list_by_owner(owner) if owner else []
```

`Depends(get_service)` 把第二、三章的依赖链接到这里收口。注意返回类型注解 `-> TodoOut`：FastAPI 既用它生成 OpenAPI 文档，也给第 2 章的 mypy 检查留了依据。`status_code=201` 是创建成功的标准码，比裸 200 更诚实。

`__main__.py` 用 uvicorn 拉起，等效于 `go run ./cmd/server`：

```python
# src/todo_app/__main__.py
import uvicorn
if __name__ == "__main__":
    uvicorn.run("todo_app.main:app", host="127.0.0.1", port=8000, reload=False)
```

## 六、pytest 测试分层：每一层都能单独打（对照 Go testing）

分层的最大回报就是测试。service 测试用假 repo，不碰 HTTP、不连库；api 测试用 `TestClient` 打真实路由，但把底层 repo 换成内存版。

```python
# tests/test_service.py
import pytest
from todo_app.service import TodoService
from todo_app.repository import TodoRepository
from todo_app.errors import NotFoundError

@pytest.fixture
def svc() -> TodoService:
    return TodoService(TodoRepository())

def test_create_then_get(svc: TodoService) -> None:
    created = svc.create(TodoCreate(title="买菜", owner="老哥"))
    assert created.id == 1
    assert svc.get(created.id).title == "买菜"

def test_get_missing_raises(svc: TodoService) -> None:
    with pytest.raises(NotFoundError):
        svc.get(999)
```

```python
# tests/test_api.py
from fastapi.testclient import TestClient
from todo_app.main import app
from todo_app.repository import TodoRepository
from todo_app.di import get_repository

def _client() -> TestClient:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_repository] = lambda: TodoRepository()  # 注入内存 repo
    return TestClient(app)

def test_create_e2e() -> None:
    client = _client()
    resp = client.post("/todos", json={"title": "写教程", "owner": "墨叔"})
    assert resp.status_code == 201
    tid = resp.json()["id"]
    got = client.get(f"/todos/{tid}")
    assert got.status_code == 200
    assert got.json()["status"] == "pending"
```

老哥：`dependency_overrides` 这个招，不就是 Go 里给接口换个 `FakeImpl` 然后注入？

墨叔：一语道破。`app.dependency_overrides[get_repository] = lambda: ...` 等于运行时把「真数据库」换成了「内存假库」，route 到 service 到 repo 全链路跑通，但零外部依赖、毫秒级。这对应第 25 章的 fixture + 替身思路，也呼应第 27 章的注入可替换性。对照 Go 的表驱动测试（`testing.T` + 假实现），习惯平移过来毫无障碍，只是 Python 用 `pytest.raises` 断言异常、用 fixture 造环境，比你 `if err != nil { t.Fatal() }` 省几行。

## 七、收益与代价：为什么值得这么分

老哥：这套比「一个函数写到底」啰嗦十倍，小接口值得吗？

墨叔：又回到那个老问题——看寿命和出错代价。我给你算笔账。

**收益：**
1. **变更隔离。** 哪天把内存 repo 换成 PostgreSQL，只动 `repository.py` 一个文件，api/service 一行不用改。Go 里你换 `sqlc` 生成层也是同样逻辑——分层把「变的东西」圈在最小范围。
2. **测试便宜。** service 单测不连库、api 测试不连库，整套 `pytest` 跑下来亚秒级，能塞进 pre-commit 和 CI（第 26 章）。「一个函数写到底」的代码，要测就得真起服务、真连库，测试慢且脆。
3. **异常语义清晰。** 业务异常在 service 抛、HTTP 状态在 handler 映射，读代码时一眼分清「这是业务规则错了」还是「这是协议层错了」，排错（第 24 章 traceback）时直接定位。
4. **类型贯穿全链。** `Depends` 拿到的是 `TodoService` 实例、`response_model` 是 `TodoOut`，mypy 能从 route 一路查到 repo，动态语言的「运行时才炸」被消掉一大半。

**代价：**
1. **文件多、样板多。** 一个简单接口要开 models/errors/service/repo/api/di 六个文件，新人会觉得「杀鸡用牛刀」。
2. **Depends 的隐式装配**，编译期查不出依赖图错误，要靠测试兜。Go 的 `wire`/`NewXxx` 在编译期就钉死，这是 Python 这边实打实让出的一块安全感。
3. **过度分层对玩具接口是负担。** 一个「返回服务器时间」的接口，硬分三层纯属表演。判断标准就一句：它会不会变大、会不会多人改、要不要测？会，就分；不会，route 里直接 return 也行。这点和 Go 完全一致——你写 `hello.go` 也不会搞 `cmd/internal`。

所以这一章你真正带走的不是 FastAPI 的 API，而是「把前面学的特性组装成工程」的那只手。类型注解给契约，异常给业务信号，DI 给可替换性，pytest 给安全感，项目结构给秩序——它们单独都不难，难的是你第一次主动把它们摆成这样。

【思考题】
1. 上面 `di.py` 里 `_repo = TodoRepository()` 是进程级单例。如果真实项目换成 PostgreSQL，且 repository 需要持有连接池（有生命周期、要优雅关闭），这种「模块加载即创建」的单例会有什么问题？结合第 5 章上下文管理器和第 28 章的结构，你会怎么改才能让连接在应用退出时正确释放？
2. 现在 `TodoService` 直接 `raise NotFoundError`，由全局 handler 翻译成 404。如果某个需求需要「查不到就返回空列表而不是报错」（比如 `list_by_owner` 对一个不存在的 owner），你会在哪一层做这个分支？为什么不能在每个 route 里都写 `try/except`？延伸到你在 Go 里怎么处理「Not Found 到底是错误还是正常空结果」的边界。
3. 本章测试用了 `dependency_overrides` 换内存 repo。如果将来 `TodoRepository` 是个 `Protocol`，而 `TodoService` 依赖这个 `Protocol` 而非具体类，pytest 里你能不能写一个比 `TodoRepository` 更轻的 fake（比如只实现 `get` 一个方法）来测 service？这和第 2 章讲的 `Protocol` 结构子类型有什么关系？

【参考答案】
1. 模块加载即 `new` 单例的问题：连接池在 `import` 那一刻就建立，一是 import 顺序敏感（测试、CLI、文档生成都会触发建连，可能连到不存在的库而崩）；二是没有关闭钩子，进程退出时连接池泄漏。正确做法是用「应用生命周期工厂」替代模块级单例：在 `main.py` 用 FastAPI 的 `lifespan` 上下文管理器创建连接池、注入、退出时关闭。这正好是第 5 章 `with`/上下文管理器的生产用法——把「建连/用连/关连」三段用 `__enter__`/`__exit__` 绑死，等价于 Go 的 `defer db.Close()`。`@contextlib.asynccontextmanager` 包一个 `def lifespan(app): async with create_pool() as pool: app.state.repo = TodoRepository(pool); yield`，再 `get_repository` 从 `request.app.state.repo` 取。这样连接随 app 生灭，import 不再副作用建连，优雅退出也有了着落。
2. 分支应落在 service 层而非 route。「查不到返回空」本身就是业务语义——比如「列出某 owner 的待办，owner 不存在等价于空列表」是规则，不是协议细节。`TodoService.list_by_owner` 直接 `return []` 即可，不抛异常；而 `get(todo_id)` 找不到才是真异常（调用方明确要一个、却没拿到），继续抛 `NotFoundError`。绝不能在 route 里写 `try/except NotFoundError: return []`——那会把「业务该不该报错」的判断散落到每个接口，同一语义在不同 route 可能写出不同行为，腐化和第 28 章讲的「route 里顺手查库」同源。对照 Go：`ListByOwner` 返回 `([]Todo, nil)` 即使为空也不算 error，而 `GetByID` 返回 `(*Todo, ErrNotFound)`——错误与否由「这个操作的前提是否满足」决定，不是由调用方心情决定，这正是第 13 章「异常 vs 返回值」的 Go 侧镜像。
3. 能，而且这正是 `Protocol` 的用武之地。把 `TodoRepository` 改成 `class TodoRepository(Protocol)` 只声明方法签名，service 依赖 `Protocol` 而非具体类。pytest 里就能写一个超轻 fake：`class StubRepo: def get(self, tid): return TodoOut(id=tid, ...)`——只要它有 service 实际调用的方法，鸭子类型就满足（第 1 章），mypy 用 `Protocol` 在静态期确认「StubRepo 确实长得像个 repo」（第 2 章结构子类型），运行期照样能注入。比继承真 `TodoRepository` 轻得多：不用实现 `create/list_by_owner`，也不用管内存字典状态。这和第 2 章的关系在于——`Protocol` 让你「用最小接口描述依赖」，测试替身只需实现被用到的方法，依赖契约越窄、替身越轻、测试越快，这正是 Go 里「依赖小接口」哲学在 Python 的可检查版本。
