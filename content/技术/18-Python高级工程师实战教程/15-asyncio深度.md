# 第 15 章 asyncio 深度：事件循环与任务

> 这一章带你钻进 asyncio 的引擎舱：事件循环怎么转、async/await 到底是什么、Task 怎么并发、超时和取消怎么玩。最后用「并发打多个 HTTP」对照 Go 的 goroutine + WaitGroup，你会明白为什么 asyncio 写起来比 goroutine「重」。

墨叔：老哥，Go 里你想并发干五件事，写个 `for` 甩五个 `go`，再 `wg.Wait()` 收个尾，干净利落。换成 Python，你听说有个 asyncio，兴冲冲写下 `async def`，结果一运行——要么忘了 `await`，要么在协程里调了个同步函数整个程序卡死，要么 `gather` 的异常不知道飞哪去了。你有没有觉得 asyncio 这座庙，门槛比 goroutine 高一大截？

老哥：太高了。而且我始终没搞懂 `async`/`await` 到底是个啥，编译器怎么就知道「这里该让出」？

墨叔：这问题问得专业。今天咱们把引擎舱拆开看：**事件循环本质、async/await 与可等待对象、Task 与 gather 并发、超时与取消**。最后落到「并发打多个 HTTP」的真实模式，并用 Go 的 WaitGroup 当镜子照差距。

## 一、事件循环本质（怎么用）

先破一个迷思：`async`/`await` 本身**不创造并发**，它只是「协作式多任务」的语法糖。真正让多个协程交替前进的，是**事件循环（event loop）**——一个死循环，不停地从队列里拿「就绪的协程」来跑，谁遇到 `await`（等 IO），就把控制权交还循环，循环去跑别的就绪协程。

拿生活类比：事件循环像**一个只有一名厨师的厨房**，厨师（单线程）同时照看十口锅。哪口锅在炖（等 IO），厨师就去切别的菜的料；炖好了（IO 完成，事件就绪）再回来翻那口锅。好处是这名厨师永远不闲着，十口锅「并发」往前走。代价？只要有一口锅需要厨师**一直站着搅拌不能离手**（CPU 密集活儿），其他九口锅全得干等——这就是 asyncio 干不了 CPU 密集的根因。

最小可运行骨架：

```python
import asyncio

async def hello() -> str:
    await asyncio.sleep(0.1)   # 模拟 IO 等待，这里把控制权交还事件循环
    return "hello"

async def main() -> None:
    result = await hello()      # await = 「等这个结果，期间让出 CPU 给别的协程」
    print(result)

asyncio.run(main())            # asyncio.run 帮你创建事件循环并跑 main
```

`asyncio.run(main())` 是 Python 3.7+ 的入口，它内部：创建一个事件循环 → 把 `main` 协程丢进去跑 → 跑完关循环。你日常 99% 情况只用 `asyncio.run` 这一个入口，不用手搓 `loop = asyncio.get_event_loop()`（那是老写法，容易踩坑）。

## 二、async/await 与可等待对象（什么场景 / 怎么用对）

老哥：`await` 后面能跟什么？我之前 `await` 一个普通 `int` 直接报错了。

墨叔：记住一句话——**`await` 后面只能跟「可等待对象（awaitable）」**。Python 里三类东西是 awaitable：

1. **协程（coroutine）**：`async def` 定义的函数，调用它返回的不是结果，而是一个协程对象（还没执行）。
2. **Task**：被事件循环「安排上日程」的协程，将来某刻会跑。
3. **Future**：底层「未来会有结果」的占位对象（一般你不直接造，是库返回给你的）。

关键区别在「协程」和「Task」：`await 协程` 是**串行**等它跑完；而把协程包成 `Task` 再 `gather`，才是**并发**。

```python
async def step(name: str, sec: float) -> str:
    await asyncio.sleep(sec)
    return f"{name} done"

async def main() -> None:
    # 下面这样是「串行」：先等 a 完，再等 b 完，共 0.3+0.2=0.5s
    r1 = await step("a", 0.3)
    r2 = await step("b", 0.2)
    print(r1, r2)

    # 下面这样包成 Task 才能并发
    ta = asyncio.create_task(step("a", 0.3))
    tb = asyncio.create_task(step("b", 0.2))
    # 此刻 a、b 都已在循环里「挂起等待」，谁先就绪谁先跑
    ra, rb = await ta, await tb   # 总耗时取最大者 0.3s，不是相加
```

老哥：哦！原来我之前 `await` 一个一个调，本质又把并发写成了串行。那「函数着色」就是从这来的？

墨叔：一点就通。`async def` 标记这个函数「我内部可能有 await，得在循环里跑」；一旦某个函数被标成 async，调用它的函数**也必须**是 async（因为它得 `await` 人家）。于是整条调用链从上到下全染成 async 色——这就是「函数着色」。Go 没这堵墙，因为 goroutine 能直接跑同步函数，runtime 调度器在底下把阻塞调用挂起，对你透明。Python 把这层透明撕开了，好处是「哪段是异步的一眼可见」，代价是「想用异步得全员改造」。

还有一个新手必踩：`await` 一个**普通同步函数**不会报错，但那个函数会**阻塞整个循环**。比如你在 async 函数里写 `time.sleep(1)`（不是 `await asyncio.sleep(1)`），事件循环这一秒完全卡死，所有其他协程都动不了。这叫「在协程里混入阻塞调用」，第 16 章专治。

## 三、Task 并发、超时与取消（收益与代价）

真正并发靠 `asyncio.gather`，它把一堆协程/Task 一起排进循环，等全部完成（或第一个出错）返回结果列表：

```python
async def fetch_all(urls: list[str]) -> list[str]:
    tasks = [asyncio.create_task(fetch(u)) for u in urls]
    # gather 并发跑所有 task，返回顺序与入参一致
    return await asyncio.gather(*tasks)
```

`gather` 有个坑：**默认一个任务抛异常，其他任务不会被取消**，异常会在 `gather` 这一层重新抛出（且 `return_exceptions=True` 时可改成把异常当结果返回，方便你逐个处理）。线上打多个下游接口时，我常写 `asyncio.gather(*tasks, return_exceptions=True)`，然后在结果里区分 `str` 和 `Exception`，不让一个挂了的接口拖垮整批。

**超时**怎么玩？`asyncio.wait_for` 给单个可等待对象套个闹钟：

```python
async def slow() -> str:
    await asyncio.sleep(5)
    return "done"

async def main() -> None:
    try:
        result = await asyncio.wait_for(slow(), timeout=1.0)
    except asyncio.TimeoutError:
        print("1 秒还没好，算了")
```

`wait_for` 超时后会**自动 cancel 掉里面的协程**——这点比「自己记时」优雅太多，也是 Go 里 `context.WithTimeout` 的对应物。

**取消**是 asyncio 的一等公民，靠 `Task.cancel()`：

```python
async def job() -> None:
    try:
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        print("被取消了，做清理")
        raise   # 重要：重新抛出，让 cancel 状态正确传播

async def main() -> None:
    task = asyncio.create_task(job())
    await asyncio.sleep(0.5)
    task.cancel()          # 请求取消
    try:
        await task
    except asyncio.CancelledError:
        print("已确认取消")
```

墨叔提醒一个要命细节：`task.cancel()` **不会立刻杀死协程**，它只是往协程里「塞一个 `CancelledError`」。协程必须在某个 `await` 点上才能收到这个异常并退出——如果你的协程是纯 CPU 死循环、从不 `await`，那它**永远收不到取消信号**，会一直跑。所以写长时间协程，记得在循环里插 `await asyncio.sleep(0)` 这类「让出点」，让取消和调度有机会生效。对照 Go，`ctx.Done()` 也是协作式的，但 Go 的调度器会在系统调用处自动挂起 goroutine，Python 得你手动 `await` 让点——又是那堵「透明墙」的差异。

## 四、真实项目模式：并发打多个 HTTP（对照 Go WaitGroup）

异步最实用的场景就是「并发调 N 个下游」。用 `httpx` 的异步客户端（第 16 章细讲生态，这里先把模式立住，先 `pip install httpx`）：

```python
import asyncio
import httpx

async def fetch(client: httpx.AsyncClient, url: str) -> tuple[str, int]:
    resp = await client.get(url, timeout=5.0)
    return url, resp.status_code

async def fetch_many(urls: list[str]) -> list[tuple[str, int]]:
    # 用连接池复用 TCP，比每次 new 客户端快得多
    async with httpx.AsyncClient() as client:
        tasks = [asyncio.create_task(fetch(client, u)) for u in urls]
        # 超时兜底：整批最多等 8 秒，超时就取消未完成的
        try:
            return await asyncio.wait_for(asyncio.gather(*tasks), timeout=8.0)
        except asyncio.TimeoutError:
            # gather 被取消，未完成的 task 自动 cancel
            return []

async def main() -> None:
    urls = [
        "https://api.github.com/repos/python/cpython",
        "https://api.github.com/repos/golang/go",
        "https://api.github.com/repos/rust-lang/rust",
    ]
    results = await fetch_many(urls)
    for url, code in results:
        print(url, code)

if __name__ == "__main__":
    asyncio.run(main())
```

对照你 Go 里怎么写同样的事：

```go
func fetchMany(urls []string) []Result {
    var wg sync.WaitGroup
    ch := make(chan Result, len(urls)) // 用 channel 收结果，天然并发安全
    for _, u := range urls {
        wg.Add(1)
        go func(u string) {
            defer wg.Done()
            ch <- fetch(u) // goroutine 真并行，IO 等待时让出 M
        }(u)
    }
    wg.Wait()
    close(ch)
    var out []Result
    for r := range ch {
        out = append(out, r)
    }
    return out
}
```

老哥你看出差距没？Go 版：goroutine + channel，**零函数着色**，fetch 是同步函数也能直接 `go`；超时得自己套 `context.WithTimeout`。Python 版：全程 async（`fetch`、`fetch_many`、`main` 全是 `async def`），结果靠 `gather` 收集保序，超时一个 `wait_for` 搞定。功能等价，但 Python 版要求你的 `fetch` 和整条链都 async——这就是「函数着色」带来的额外约束。收益是：单线程扛万级连接，内存比开万级线程小几个数量级，且超时/取消的语义比 goroutine 显式（你在代码里看得见 `cancel` 和 `wait_for`）。

墨叔再补一个工程要点：**别在循环里反复 `httpx.AsyncClient()`**。客户端内部有连接池和 DNS 缓存，应整个请求批次共用一个，像上面 `async with httpx.AsyncClient()` 那样。每请求 new 一个客户端，连接不复用，性能掉一大截——这是 asyncio HTTP 客户端最常见的性能坑。

## 五、把 asyncio 用稳的三条纪律

1. **入口只有一个 `asyncio.run`**。别在已经跑着的循环里再 `run_until_complete`，会报「已有运行中的循环」。需要嵌套时（比如同步框架里调异步），用 `asyncio.run` 包最外层，内部全用 `await`/`gather`/`create_task`。
2. **协程里绝不写阻塞调用**。`requests.get`、`time.sleep`、`pandas.read_csv` 这些同步重活，要么挪到线程池（`await loop.run_in_executor(None, blocking_fn)`），要么确认它真的快。否则一个阻塞调用卡死整个事件循环，其它协程全饿死。
3. **长任务要留「让出点」**。CPU 重的协程，循环里周期性 `await asyncio.sleep(0)`，既让出 CPU 给其他协程，也让你发出的 `task.cancel()` 能被收到。

回到开头：asyncio 不是比 goroutine「难」，是它把「调度透明」这层皮剥给你看。你看得见循环、看得见 Task、看得见取消信号——代价是写起来重，收益是单线程高并发 IO 既省内存又语义清晰。认清它「只对 IO 密集有用、要求整条链 async」，你就知道什么时候该上、什么时候该退回多线程。

## 六、再往深一层：可等待对象的本质与调试陷阱

老哥：墨叔，你前面说「可等待对象」有三类和「Task 是排进循环的协程」。我还有个底层困惑：协程对象我 `print` 出来是个 `coroutine`，它到底是个什么东西？为什么我忘了 `await` 程序就不报错但啥也不干？

墨叔：这个问题问到 asyncio 的骨头上了，答清楚你能少踩一半坑。一个 `async def` 函数，**调用它时不执行函数体**，而是返回一个「协程对象」——它像一个「被暂停在开头的、将来才会跑的计算说明书」。只有当你 `await` 它，或者把它包成 `Task` 交给事件循环，这份说明书才被真正「执行」。所以你写 `result = fetch(url)` 却忘了 `await`，`result` 拿到的不是数据，是一张没被执行的说明书，函数体一行都没跑——程序不报错，因为语法完全合法，但你要的 IO 根本没发生。这种「静默无操作」是 asyncio 最阴的坑，因为它不像 Go 缺 `<-ch` 至少有类型不吻合提醒，Python 全靠你眼睛盯。所以我的习惯是：任何返回协程的函数调用，落地的那行一定带 `await` 或包进 `create_task`，宁可多写一次也要让「执行」这件事在代码里显形，绝不能把协程对象赋值给变量就丢一边。

更深一层：`Future` 是 asyncio 最底层的「占位结果」，Task 其实是 Future 的子类，专门包协程。库作者（比如 httpx、asyncpg 内部）返回给你的 awaitable，本质就是往事件循环里注册一个 Future，IO 完成时由循环把结果填进 Future、再唤醒等待它的协程。你日常不用手搓 Future，但理解这层，就能看懂报错里「Task was destroyed but it is pending」是什么意思——通常是协程还没 `await` 完、循环就关了，里面的 Future 悬空。预防办法：所有 `create_task` 出来的 Task，最后都要 `await` 一次收尾，或用 `asyncio.gather` 统一等，别让 Task 变成「没人等的孤儿」。

还有个调试开关值得记：开发期设 `PYTHONASYNCIODEBUG=1` 或 `asyncio.get_event_loop().set_debug(True)`，循环会帮你抓「在协程里调了耗时同步函数」「Task 长时间没 await」「没等待的 Task 被销毁」这类问题，压测前开着能提前揪出隐性阻塞。asyncio 的难，一半在「逻辑看不见」，把调试开关打开，透明度就回来了。

老哥：那「事件循环」在什么时候会自己切到别的协程？我总怕它切得不是时候，把我的共享变量改乱。

墨叔：这个问题触及并发正确性的命门，答准了你能少写一堆锁。事件循环只在协程**主动 `await` 的那一刻**才切换——也就是「让出点」。只要你的代码在一段没有 `await` 的连续语句里改共享变量，这段代码就是「原子」的，不可能被别的协程插进来打断，因为循环没机会切走。危险只发生在 `await` 之间：你读了一个共享变量、然后 `await` 了一下、再写回，这个「读改写」跨了让出点，别的协程就可能在你等待期间插进来改同一个变量，于是出现竞态。对照 Go，goroutine 同样有这问题，Go 靠 `sync.Mutex` 或 `channel` 串行化访问；Python asyncio 里因为切换点可预期（只有 `await`），你甚至比 Go 更容易看出「哪段是临界区」。轻量共享状态可以用 `asyncio.Lock`（协程版互斥锁，`async with lock` 保护临界区），但更 Pythonic 的做法是「尽量不在协程间共享可变状态」——用 `asyncio.Queue` 传消息、用各自独立的 Task 持有各自的数据，像 Go 推崇「通过通信共享内存，而非通过共享内存通信」一样，把可变状态收敛到单一 owner，并发正确性就自然来了。

【思考题】
1. 下面这段 asyncio 代码，三个 `step` 各睡 0.3/0.2/0.1 秒，总耗时约多少？为什么？如果想让它们并发、总耗时取最大值 0.3 秒，该改哪几行？
   ```python
   async def main():
       a = await step("a", 0.3)
       b = await step("b", 0.2)
       c = await step("c", 0.1)
   ```
2. 你的协程里写了 `while True: 做重型计算()`，从不 `await`。你在外面 `task.cancel()` 后，为什么这个任务停不下来？怎么改才能让取消生效？对照 Go 的 `ctx.Done()` 说明两者取消机制的异同。
3. `asyncio.gather(*tasks)` 默认（不带 `return_exceptions`）时，若其中一个 task 抛异常，其它 task 会怎样？线上「并发打 5 个下游接口、允许部分失败」的场景，你应该用 `gather` 的哪个参数？拿到的结果怎么区分成功和失败？

【参考答案】
1. 总耗时约 **0.3 + 0.2 + 0.1 = 0.6 秒**。因为三行是**串行** `await`：先等 a 跑完才发起 b，再等 b 完才发起 c，没有重叠。改成并发：把每个 `step` 用 `asyncio.create_task` 包成 Task 再 `gather`，即 `ta, tb, tc = (asyncio.create_task(step(n, s)) for n, s in ...); ra, rb, rc = await asyncio.gather(ta, tb, tc)`。这样三个协程在 `create_task` 那一刻就都挂进事件循环「等待 IO」，它们 sleep 期间互相让出，总耗时取最大 0.3 秒。核心区别：`await 协程`=串行等待；`create_task`+`gather`=并发调度。
2. 停不下来原因：Python 的取消是**协作式**的——`task.cancel()` 只是往协程内部「注入一个 `CancelledError` 待抛」，协程**必须在一个 `await` 点上**才能接收并处理这个异常。纯 `while True` 做重计算、从不 `await`，协程永远不把控制权交还事件循环，也就永远碰不到那个 `await` 让出点，异常塞不进去，任务一直跑。改法：在循环里插入 `await asyncio.sleep(0)`（让出点），或在重计算每轮后 `await asyncio.sleep(0)`，让取消信号能被接收。对照 Go：`select { case <-ctx.Done(): return }` 也是协作式——goroutine 必须主动检查 `ctx.Done()` 才能退出；不同在于 Go 调度器会在 goroutine 做系统调用/通道操作时自动挂起它，Python 则要求你**手动**写 `await` 让点。两者都不是「强杀」，都靠协程配合退出，这点理念一致。
3. 默认不带 `return_exceptions=True` 时：某个 task 抛异常，`gather` 会**立刻把那个异常向外抛**，但**其它 task 不会被自动取消**——它们继续在后台跑（可能浪费资源或产生游离任务）。线上「允许部分失败」场景应写 `asyncio.gather(*tasks, return_exceptions=True)`：这样异常不会向外抛，而是作为**结果列表里的一个元素**返回（与入参顺序一一对应）。拿到结果后遍历：`if isinstance(r, Exception): 记日志/降级 else: 正常用 r`。这样既不让一个接口挂掉拖垮整批，又能逐个区分成功/失败做降级。若你还想「一旦有一个成功就够了」，可改用 `asyncio.wait` 配 `FIRST_COMPLETED`，或 `asyncio.as_completed` 边完成边处理。
