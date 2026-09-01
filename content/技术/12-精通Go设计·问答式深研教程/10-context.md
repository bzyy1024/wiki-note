# 10 context：取消、超时、值传递的边界

## 开篇提问

先看一个非常常见的场景：

你写了一个 HTTP 接口，内部会起 goroutine 去查数据库、调下游服务、写缓存。现在客户端**超时断开了连接**——用户不等了。

问题：你接口里那一串正在跑的 goroutine，**会自动停下来吗？**

答案是不会。它们会继续跑，直到自己跑完。如果这种"没人要的结果还在继续算"的 goroutine 堆积起来，就是**资源泄漏 + 无谓的 CPU 和数据库压力**。

于是问题来了：**怎么把"客户端已经不等了"这个信号，从最外层一路传到最内层、让所有相关 goroutine 都停下来？**

答案就是 `context`。这一章，我们讲清楚 context 的三种用法、它的设计哲学、以及它最容易被误用的地方。

---

## 子主题一：context 是什么——一颗"信号树"

`context.Context` 本质是一个**贯穿整个调用链的信号载体**，它携带三种能力：

1. **取消（cancel）**：一个"停止工作"的信号。
2. **超时/截止时间（deadline）**：到点了自动触发取消。
3. **值传递（value）**：携带少量跨层传递的数据（如 traceID、用户身份）。

它最核心的设计是**树状结构**：一个父 context 可以派生出多个子 context，父 context 取消，所有子 context 连带取消。

```go
ctx, cancel := context.WithCancel(parentCtx)
defer cancel()                    // 取消时，所有从 ctx 派生的 goroutine 都会收到信号

go doWork(ctx)                    // 把 ctx 传给 goroutine
```

在 goroutine 里，通过 `<-ctx.Done()` 来监听取消：

```go
func doWork(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():        // 收到取消信号，退出
            return
        default:
            // 干活
        }
    }
}
```

这颗"信号树"解决的就是开篇那个问题：**把"上层已经不关心结果了"这个事实，沿着调用链广播下去，让所有在干活的 goroutine 都能及时收手。**

---

## 子主题二：context 的设计哲学——为什么它是"第一参数"

Go 有一条著名的约定：**context 应该作为函数的第一个参数，命名为 `ctx`，显式地传递。**

为什么不能做成全局变量？因为：

**第一，取消信号是有"作用域"的。** 一个请求的取消，只应该影响这个请求相关的 goroutine，不该影响别的请求。全局变量做不到这种隔离，只有显式传递，才能让每个请求带着"自己的 ctx"。

**第二，显式传递让"取消的边界"一目了然。** 你一眼就能看出"这个函数会不会响应取消、它的取消从哪来"。这是 Go"显式优于隐式"哲学在并发取消上的体现——宁可每个函数都多写一个 `ctx` 参数，也不要一个隐式的全局魔法。

**第三，context 的值是"请求级"的，天然该随调用链流动。** traceID、超时、用户身份这些，都是"属于某一次请求"的，跟着 ctx 走最自然。

这里要特别强调一个原则，它经常被违反：**context 应该贯穿整个请求的生命周期，一旦请求结束，它的 ctx 就失效。不要把 ctx 存进 struct、全局变量，或者跨请求复用。** 一个 struct 如果长期持有 ctx，就等于"这个 struct 绑定了一个已经死掉或随时会死的请求"，是典型的反模式。

---

## 子主题三：三种 context 的用法

**WithCancel：手动取消。**

```go
ctx, cancel := context.WithCancel(context.Background())
go func() { <-ctx.Done(); fmt.Println("cancelled") }()
cancel()   // 手动触发
```

用于"我知道什么时候该停"的场景，比如主协程退出时，取消所有子任务。

**WithTimeout / WithDeadline：定时取消。**

```go
ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
defer cancel()   // 重要：用完要 cancel，释放计时器资源
```

用于"最多等多久"的场景——超时自动取消，是服务端防雪崩、防资源泄漏的第一道防线。

**WithValue：值传递。**

```go
ctx = context.WithValue(ctx, key, value)
v := ctx.Value(key)
```

用于传递少量"请求级"的元数据。这里有个**必须记住的坑**：**value 的 key 必须是"不可比较时不会冲突"的类型，推荐用自定义的私有类型（`type ctxKey struct{}`），而不是 string。** 因为 string key 容易在不同包之间撞名，导致值被覆盖或误读。用私有类型，别的包根本构造不出相同的 key，天然隔离。

---

## 子主题四：context 的坑——别用 value 当"传参"、别忘 cancel

**坑一：把 context.Value 当成"隐藏的传参通道"。** 有些人会把大量业务数据塞进 ctx，当成免去显式传参的捷径。这是错的：ctx.Value 会破坏类型安全（拿到的是 interface{}，要断言）、让依赖关系隐晦、难以测试。**ctx.Value 只应该放"横切关注点"（traceID、鉴权信息、日志字段等请求级元数据），业务数据请老老实实显式传参。**

**坑二：忘记 cancel，导致计时器泄漏。** `WithTimeout`/`WithDeadline` 内部会创建计时器，如果不用 `defer cancel()`，这个计时器要等超时才释放；大量短请求累积，会泄漏计时器资源。所以铁律：**`ctx, cancel := ...; defer cancel()`。**

**坑三：在 goroutine 里闭包捕获 ctx，然后 ctx 取消后 goroutine 还在跑。** ctx 的取消只是"发信号"，不是"强制杀死"。goroutine 必须自己监听 `ctx.Done()` 并退出，ctx 才不会漏。**context 是协作式的，不是强制的**——它依赖每个 worker 自觉响应。

---

## 子主题五：context 与 goroutine 泄漏的关系

这一章的开篇问题，答案全在 context 的正确使用上。goroutine 泄漏的三大来源：

1. **阻塞在 channel 收发上**（第八章讲过）——用 `select + ctx.Done()` 兜底。
2. **阻塞在 I/O 上**——用 `ctx` 取消 I/O（比如 `http.NewRequestWithContext`、带 ctx 的数据库查询）。
3. **阻塞在 sleep/锁上**——用 `select + time.After` 或可取消的等待。

三者的共同解法都是：**给阻塞的 goroutine 一个"可取消的出口"，而 ctx 就是这个出口的标准载体。**

这里引出一个更深层的工程认知：**goroutine 不能从外部被"杀死"，只能被"请求"停止。** 这是 Go 并发模型的一个根本性质（不像线程有 `Thread.stop` 那种危险的强制终止）。所以**能不能优雅停止，取决于你写代码时有没有给它留"停止的出口"**——ctx 就是为这个出口设计的标准协议。理解了这一点，你就理解了为什么 Go 团队坚持"ctx 贯穿全链路、且要显式传递"。

---

## 子主题六：context 的树结构——取消信号到底是怎么传下去的

先抛一个反直觉的问题：**你说 context 是一棵树，但 `context` 包里根本没有一个 `AddChild` 或者 `Parent()` 的公开方法。那这棵树，到底是谁在维护？**

答案是：`WithCancel`/`WithTimeout`/`WithDeadline` 在创建子 context 的那一刻，偷偷帮你"上户口"了。

Go 在创建可取消的子 context 时，会走一个内部的"传播注册"流程，概念上是这样几步：

1. **向上找"最近的可取消祖先"。** 从 `parent` 开始一路往上问："你能被取消吗？"——遇到 `valueCtx` 就穿过去继续问（因为它自己没有取消能力，只是个挂着 kv 的壳子），直到找到一个真正可取消的节点（`cancelCtx`/`timerCtx`），或者走到根（`Background`/`TODO`，不可取消）。
2. **找到了，就把自己登记进那个祖先的 children 集合。** 注意是"最近的可取消祖先"，不是"直接 parent"。这条设计很妙：中间夹多少层 `WithValue` 都不影响取消链的连通性。
3. **没找到（祖先全不可取消），就起一个 goroutine 守着。** 这个 goroutine 做一件事：`select` 父的 `Done()` 和自己的 `Done()`，父一取消就取消自己。这是兜底方案，代价是多一个 goroutine。

取消发生时，一个可取消节点会按顺序做三件事：

1. **关闭自己的 done channel**——一次 `close`，所有阻塞在 `<-ctx.Done()` 上的 goroutine 同时被唤醒。**这是 Go 里最经典的"广播"手法：close 一个 channel，代价 O(1)，却能让 N 个接收者同时收到信号。** 你不需要给每个监听者发一份消息。
2. **遍历自己的 children，递归取消。** 这就是"父死子随"的实现——不是魔法，就是一次树的深度遍历。
3. **把自己从父节点的 children 集合里摘掉。**

第 3 步最容易被忽略，但它是一道**内存泄漏防线**：如果一个子 context 早就正常结束了（你调了 `cancel`），但父 context 还活着（比如一个长生命周期的 ctx），父的 children 集合里就会一直留着这个死节点的引用，整棵子树都跟着它一起不被 GC。**所以"取消"不只是发信号，也是一次"从树上摘果子"的动作。**

还有两个必须刻进肌肉记忆的性质：

**性质一：取消只向下传播，绝不向上传播。** 子 context 被取消，父 context 毫发无损。这不是缺陷，这是核心设计——正因为如此，你才敢给每个子任务套一个更短的超时：`ctx, cancel := context.WithTimeout(parent, 500*time.Millisecond)`，子任务超时自己烂掉，不会把整个请求拖死。**如果取消是双向的，"子任务超时"就等于"整个请求放弃"，那超时机制就没法分层设计了。**

**性质二：兄弟之间互不影响。** 取消大哥不会取消二哥。想让"一个子任务失败，其他兄弟一起收手"，`context` 包本身不管这事——那是 `errgroup` 的活（见子主题八）。

最后补一个硬核细节：**`Done()` 返回的 channel 是懒创建的**，你第一次调 `Done()` 时它才出现。而 `Background()`/`TODO()` 的 `Done()` 返回的是 **nil channel**。这有什么用？在 `select` 里"从 nil channel 接收"是永久阻塞的——所以"这个分支永远不会被选中"可以自然地用 nil channel 表达：

```go
select {
case <-ctx.Done():        // ctx 不可取消时这里返回 nil channel，分支永久阻塞
    return ctx.Err()
case v := <-ch:
    return v
}
```

看懂这段代码，你就看懂了为什么"永不取消"和"还没取消"在 Go 里可以用同一个 `select` 结构表达。

**一句话总结这棵树：context 的树不是数据结构课本上的树，而是一条"向上登记、向下广播"的取消责任链。** 节点只认识两样东西——我的取消源在哪、谁在等我取消。

---

## 子主题七：cancelCtx / timerCtx / valueCtx——三种能力，三种代价

前面一直在说"三种 context"，现在我们把它掰开到能做出工程决策的粒度。

先问个问题：**`WithTimeout` 和 `WithDeadline` 有什么区别？** 答：`WithTimeout(parent, d)` 内部就是 `WithDeadline(parent, time.Now().Add(d))`。**所以 deadline 才是本质，timeout 只是语法糖。** 这个区别在跨服务调用时非常重要：下游服务应该传递**绝对时间点**（deadline）而不是"还剩多久"（timeout），因为剩余时间每跳一次网络就少一点，传 timeout 等于每层都在骗自己。

### cancelCtx：手动取消，最便宜

```go
ctx, cancel := context.WithCancel(parent)
defer cancel()
```

能力：一个 `Done()` + 一个 `Err()`（固定为 `context.Canceled`）。
代价：一个 channel + 一次在父 children 集合里的登记。**没有计时器，没有 goroutine（如果父可取消）。**
何时用：你知道"什么时候该停"——比如主流程收敛子任务、扇出后的快速失败、优雅关闭、手动中断一个长轮询。

### timerCtx：定时取消，多一个计时器

`timerCtx` 在概念上是"cancelCtx + 一个 deadline + 一个运行时计时器"。

能力：`cancelCtx` 的全部 + `Deadline()`。到点了自动触发取消。
代价：cancelCtx 的代价 **+ 一个 runtime timer**。计时器到点前一直挂着，所以**必须 `cancel()`** 才能提前释放它（这就是子主题四说的"计时器泄漏"，现在你看到根子上了）。

关键的工程细节在这里：

**第一，err 不同，你能区分"为什么停"。**

```go
if errors.Is(ctx.Err(), context.DeadlineExceeded) {
    // 是我自己超时了 → 该告警、该降级
} else if errors.Is(ctx.Err(), context.Canceled) {
    // 是上游不要了 → 客户端跑了而已，别打 error 日志
}
```

`timerCtx` 自己到点取消时，`Err()` 是 `DeadlineExceeded`；被上游手动/提前取消时，是 `Canceled`。**这两个错误在服务端日志里的处理完全不同**：把"客户端断开"当成 error 打出来，是很多监控系统被自己的日志淹死的常见原因。

**第二，子 deadline 晚于父 deadline 时，会被"向下对齐"。** 如果你写 `context.WithDeadline(parent, 一年后)`，而父只剩 3 秒，那么得到的子 context **不会**真的设一个一年后的计时器，而是直接继承父的 3 秒。语义上完全正确：**父都死了，子再活也没意义。** 反过来说，`ctx.Deadline()` 是"真正生效的截止时间"，你可以用它算剩余预算：

```go
if dl, ok := ctx.Deadline(); ok {
    remain := time.Until(dl)
    // 用 remain 决定：还能不能重试？要不要降级？给下游留多少？
}
```

### valueCtx：只挂数据，不产生任何取消能力

`valueCtx` 极其简单：包住父 context，加一对 key/val。它**内嵌父 Context**，所以 `Done()`/`Err()`/`Deadline()` 全部直接委托给父——它自己完全没有取消能力。

三个必须知道的实现事实：

1. **`Value()` 是沿链向上逐级线性查找。** 每个 `valueCtx` 只知道自己这一层的 kv，找不到就问父。所以查找是 O(链长)。链上挂几十个值，每次 `Value()` 都要走几十步指针——**所以 `ctx.Value` 永远不要放在热点循环里，取一次存到局部变量再用。**
2. **不可变。** 每次 `WithValue` 返回一个新节点，绝不修改父节点。这意味着两个从同一个父派生的 `valueCtx` 互不可见对方的 kv。
3. **key 必须 comparable。** 因为它要做 `==` 比较。用 slice/map 当 key 会 panic。

配套的正确姿势（不是"能跑"，是"能维护"）：

```go
type traceIDKey struct{}                                    // 私有类型，别的包构造不出来

func WithTraceID(ctx context.Context, id string) context.Context {
    return context.WithValue(ctx, traceIDKey{}, id)
}

func TraceIDFrom(ctx context.Context) string {              // 导出访问器，收敛类型断言
    id, _ := ctx.Value(traceIDKey{}).(string)
    return id
}
```

注意这里的设计：**类型私有（防碰撞），但访问器导出（防各处散落断言）。** 只有 `TraceIDFrom` 一个地方做类型断言，全链路调用方都拿到强类型的 `string`。这一手把 `ctx.Value` 的类型安全问题压到了一个函数里。

### 三兄弟对照表

| | 取消来源 | `Err()` | `Deadline()` | 额外资源 | 典型场景 |
|---|---|---|---|---|---|
| cancelCtx | 手动 `cancel()` | `Canceled` | 继承父 | 无 | 收敛子任务、优雅关闭、快速失败 |
| timerCtx | 到点 / 手动 | `DeadlineExceeded` / `Canceled` | 自己的（但会被父向下对齐） | 一个计时器 | 下游调用超时、接口总时限 |
| valueCtx | 无（继承父） | 继承父 | 继承父 | 一对 kv | traceID、鉴权信息、日志字段 |

### Go 1.20+ 新增的几把刀

- **`WithCancelCause` + `Cause(ctx)`（Go 1.20）**：取消时带一个原因，`Cause(ctx)` 把它取出来。终于不用靠日志猜"到底为什么取消"。
- **`WithTimeoutCause` / `WithDeadlineCause`（Go 1.21）**：超时也带原因。
- **`WithoutCancel`（Go 1.21）**：返回一个**不跟随父取消、但保留父的 value** 的 context。典型用途：请求已经返回了，但你要异步上报埋点——这时原 ctx 已经死了，直接拿来用会立刻失败。
- **`AfterFunc(ctx, f)`（Go 1.21）**：ctx 取消时回调 `f`，不用自己起 goroutine 守着。

`WithoutCancel` 有个陷阱要顺手记下：**它造出来的是一个"永不取消"的 context。** 如果你拿它去做 I/O，这个 I/O 就没有退路了。正确做法是立刻补上自己的超时：

```go
// 请求已返回，但要在后台上报
bg := context.WithoutCancel(r.Context())
go func() {
    ctx, cancel := context.WithTimeout(bg, 2*time.Second)  // 必须自己补超时
    defer cancel()
    report(ctx, payload)
}()
```

**脱离父的取消，不等于可以没有取消。** 这是 `WithoutCancel` 最常被用错的地方。

---

## 子主题八：context 与 goroutine 泄漏——跟着一个请求走完全程

现在把镜头拉到真实场景。你有个接口：并发查用户、查订单、查优惠券，然后聚合。

```go
func handle(ctx context.Context, uid int64) (Home, error) {
    var (
        user User
        orders []Order
        coupons []Coupon
    )
    g, gctx := errgroup.WithContext(ctx)   // golang.org/x/sync/errgroup
    g.Go(func() error { return fetchUser(gctx, uid, &user) })
    g.Go(func() error { return fetchOrders(gctx, uid, &orders) })
    g.Go(func() error { return fetchCoupons(gctx, uid, &coupons) })
    if err := g.Wait(); err != nil {
        return Home{}, err
    }
    return Home{user, orders, coupons}, nil
}
```

`errgroup.WithContext` 做了什么？它创建 `WithCancel(ctx)`，并在**任意一个子任务返回错误（包括 ctx 被取消）时自动调用 cancel**。这就是"一个失败，兄弟一起收手"——`context` 包本身不提供这个，它只提供树。

现在回答本节的核心问题：**ctx 取消了，goroutine 就一定退出了吗？**

**不一定。** 这是本章最重要的一句话。ctx 取消只是**把 done channel 关了**，能否退出取决于那个 goroutine 此刻正卡在什么上面。三种典型的"叫不醒"：

1. **纯 CPU 密集循环**：`for i := 0; i < 1e12; i++ { 算力 }`——它根本不看 ctx，取消信号发过去它听不见。解法是**分片检查**：

```go
for i := 0; i < n; i++ {
    if i%1024 == 0 {                 // 每 1024 次检查一次，摊薄开销
        select {
        case <-ctx.Done():
            return ctx.Err()
        default:
        }
    }
    step(i)
}
```

2. **卡在不支持 ctx 的第三方库/系统调用上**：ctx 取消后，那个阻塞调用可能还要等它自己的超时。**解法是给不可取消的操作套一层"可取消的等待"**：

```go
done := make(chan error, 1)
go func() { done <- legacyBlockingCall() }()   // 注意 channel 带缓冲，goroutine 不会卡在发送上
select {
case err := <-done:
    return err
case <-ctx.Done():
    return ctx.Err()   // 我不等了（但底层那个调用还在跑，这是代价，得认）
}
```

**注意那个 `make(chan error, 1)`。** 如果写成无缓冲，ctx 取消后里面那个 goroutine 会永久卡在 `done <- err` 上——你修好了一个泄漏，又造了一个。这类"救援 goroutine 自己泄漏"的 bug 我见过太多次。

3. **`time.Sleep` 不可取消。** 想要"可取消地等一会儿"：

```go
t := time.NewTimer(30 * time.Second)
defer t.Stop()
select {
case <-t.C:
case <-ctx.Done():
    return
}
```

顺带一个老坑：**在循环里用 `time.After` 会短暂泄漏计时器**——`time.After` 的计时器直到触发才会被回收，一秒几千次的循环里就是几千个悬挂计时器。循环里老老实实用 `time.NewTimer` + `Stop`。

### 泄漏的三种可见形态

- **goroutine 数持续上涨**：`runtime.NumGoroutine()` 打点，或者看 pprof 的 goroutine profile。**所有卡在 `chan receive` / `select` 上的 goroutine 都会带着它的完整堆栈**，pprof 一眼就能定位到哪行代码。
- **连接/事务泄漏**：goroutine 退了但连接没还池、`*sql.Rows` 没 `Close`、事务没提交/回滚。数据库侧的 `show processlist` 会越来越长。
- **内存缓慢上涨**：结果集、中间对象被已退出的逻辑间接持有。

### 想证明"我没泄漏"？用测试断言

```go
func TestHandlerNoLeak(t *testing.T) {
    defer goleak.VerifyNone(t)      // github.com/uber-go/goleak
    ctx, cancel := context.WithCancel(context.Background())
    _, _ = handle(ctx, 1)
    cancel()
    time.Sleep(50 * time.Millisecond)   // 给 goroutine 退出留出时间窗
}
```

**`goleak` 应该进每个涉及 goroutine 的包的 `TestMain`。** 这是把"我不泄漏"从口头承诺变成 CI 断言的唯一实用手段。

### detach：请求结束了，但我想留点后手

场景：请求已经返回给用户了，你还想异步写审计日志。此时 `r.Context()` 已经取消。三种做法，只有一种对：

```go
// 错：拿着死掉的 ctx 去做 I/O，第一次请求就永久失败
go audit(r.Context(), log)

// 错：脱离取消但没超时，这个 I/O 没有任何退路
go audit(context.WithoutCancel(r.Context()), log)

// 对：脱离父 + 自己的预算
go func() {
    ctx, cancel := context.WithTimeout(context.WithoutCancel(r.Context()), 3*time.Second)
    defer cancel()
    if err := audit(ctx, log); err != nil {
        slog.Warn("audit failed", "err", err)
    }
}()
```

**规则：任何脱离请求生命周期的 goroutine，必须自带超时。** 它不再有"上游会救我"这个假设了。

---

## 子主题九：context 在标准库里的落地——从 HTTP 到数据库

纸上谈兵结束。看标准库是怎么把 ctx 织进去的。

### 服务端：请求 ctx 是白送的

`net/http` 为每个请求构造一个 context（可用 `Server.BaseContext` 和 `Server.ConnContext` 两个钩子定制基础 ctx），通过 `r.Context()` 拿到。它的生命周期语义是：

- 客户端断开连接 → 请求 ctx **被取消**；
- handler 返回 → 请求 ctx **被取消**；
- 服务端写响应出错 → 请求 ctx **被取消**。

所以 handler 里的铁律是：**把 `r.Context()` 传下去，不要自己 `context.Background()`。** 你每写一次 `Background()`，就等于在这条链上剪一刀——下游所有超时、取消、traceID 全部断掉。

handler 骨架长这样：

```go
func (s *Server) GetOrder(w http.ResponseWriter, r *http.Request) {
    ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)  // 在请求 ctx 之上加预算
    defer cancel()

    order, err := s.svc.Load(ctx, orderID(r))
    switch {
    case errors.Is(err, context.Canceled):
        return                                   // 客户端跑了，静默返回
    case errors.Is(err, context.DeadlineExceeded):
        http.Error(w, "upstream timeout", http.StatusGatewayTimeout)
        return
    case err != nil:
        slog.ErrorContext(ctx, "load order", "err", err)
        http.Error(w, "internal error", http.StatusInternalServerError)
        return
    }
    writeJSON(ctx, w, order)
}
```

注意 `slog.ErrorContext(ctx, ...)`——**日志也要吃 ctx**，这样日志处理器能从 ctx 里掏出 traceID 塞进每条日志。这就是"横切关注点走 ctx"的实战收益。

### 客户端：NewRequestWithContext

```go
req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
if err != nil { return err }
resp, err := http.DefaultClient.Do(req)
if err != nil { return err }          // ctx 取消时这里返回 *url.Error 包裹的 context.Canceled
defer resp.Body.Close()               // 不 Close，连接不回池，连接池很快耗尽
io.Copy(dst, resp.Body)
```

三个坑：

1. **`req.WithContext` 返回的是副本。** 它是浅拷贝，你必须用返回值，写 `r.WithContext(ctx)` 然后继续用旧的 `r` 是无效操作。
2. **`resp.Body` 必须读完或关闭**，否则这条 TCP 连接无法复用。取消场景下尤其容易漏——ctx 一取消你就 `return` 了，`defer` 得写在 `Do` 成功之后。
3. **`http.Client{Timeout}` 和 ctx 超时语义不同**：`Client.Timeout` 是"整个请求（含读 body）的总时限"，是一次性的自我保护；ctx 是"调用方不想要了"的信号，可以逐请求定制。**两者可以叠加，谁先到谁生效。**

### database/sql：带 ctx 的查询

```go
rows, err := db.QueryContext(ctx, "SELECT id, name FROM users WHERE dept = ?", dept)
if err != nil {
    if errors.Is(err, context.Canceled) { return ErrClientGone }
    return err
}
defer rows.Close()
for rows.Next() { /* ... */ }
if err := rows.Err(); err != nil { return err }   // 迭代中途取消，错误在这里才冒出来
```

要点：

- **永远用 `QueryContext`/`ExecContext`/`QueryRowContext`/`BeginTx`，不要用没有 ctx 的版本。** 后者只是前者的 `context.Background()` 包装。
- **取消能"真正中断"查询的前提是驱动实现了 `driver.QueryerContext`。** 主流驱动都实现了。没实现的话，database/sql 会退化成"等查询跑完再丢弃结果"——**所以取消数据库查询是"尽力而为"，不是保证。**
- **事务的 ctx 尤其重要**：`BeginTx(ctx, opts)` 里传的 ctx 一旦取消，这个事务会被**自动回滚并释放连接**。如果你传 `context.Background()`，一个因为客户端断开而卡住的事务会一直占着连接池里的一条连接——高并发下几分钟就能把池子抽干。
- **迭代中途取消的错误在 `rows.Err()` 里**，不在 `Next()` 的返回值里。忘了检查 `rows.Err()`，你会把"查询被取消"当成"查到 0 条"。

### 中间件：怎么把 ctx 贯穿全链路

```go
func TraceMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        ctx := context.WithValue(r.Context(), traceIDKey{}, newTraceID())
        ctx = context.WithValue(ctx, userKey{}, userFromToken(r))
        next.ServeHTTP(w, r.WithContext(ctx))   // 必须把新 req 传下去！
    })
}
```

**中间件最常见的错误就是：构造了新 ctx，却把旧的 `r` 传给了 `next`。** `r.WithContext` 返回副本，这是 `net/http` 的一条硬约束——因为 `*Request` 可能被并发读取，不能原地改。

读取侧：

```go
func handler(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()          // 注意：Request.Context() 永不为 nil，没设过就返回 Background
    traceID := TraceIDFrom(ctx)
    // ...
}
```

再补一条服务端防护：**光有 ctx 超时不够，还要设 `ReadHeaderTimeout`/`ReadTimeout`/`WriteTimeout`/`IdleTimeout`。** ctx 管的是"你的业务逻辑别跑太久"，这些 timeout 管的是"客户端别用慢速攻击占着连接不撒手"。两者防的不是同一种攻击。

---

## 子主题十：context 最佳实践与反模式清单

这一节全是能直接在 code review 里引用的条目。每条都配"症状"，方便你对号入座。

**反模式 1：把 ctx 存进 struct。**

```go
type Service struct {
    ctx context.Context   // 反模式：这个 struct 的生命周期可能远长于请求
}
```

症状：一个长生命周期对象持有一个会死/已死的请求；方法之间隐式共享取消状态，测试时无从下手。
正解：**ctx 作为方法的第一参数逐层传递。** 唯一被广泛容忍的例外是"短生命周期的迭代器/请求作用域对象"，但即便如此也不推荐。

**反模式 2：用 `ctx.Value` 当"隐藏的传参通道"。**

症状：函数签名看起来很干净 `func Charge(ctx, money)`，实际上它从 ctx 里掏出 userID、coupon、DB 句柄、配置……**调用方完全看不出它依赖什么，重构时一脚踩空。**
正解：业务参数显式传参。ctx 只放**横切、请求级、跨层且不想污染每一层签名的元数据**：traceID/spanID、鉴权身份、租户 ID、日志字段、deadline 相关的策略。

**反模式 3：用 string 当 key。** 症状：两个包都写 `ctx.Value("userID")`，一个存 int64 一个存 string，运行时随机踩雷。正解：`type userKey struct{}` + 导出的 `WithUser`/`UserFrom` 访问器。

**反模式 4：把 `cancel` 传给下游。** 症状：某个底层函数拿到 `cancel` 后随手一调，整条调用链全部猝死，而调用方完全不知情。
正解：**`cancel` 归创建者所有，绝不下传。** 谁 `WithCancel`，谁负责 `defer cancel()`。

**反模式 5：忘了 `cancel`。** 症状：计时器和 children 登记一直挂着，直到超时才释放。高并发短请求场景下表现为 timer 数量随 QPS 线性堆积。正解：`ctx, cancel := ...; defer cancel()`——**和 `resp.Body.Close()` 同一级别的肌肉记忆。**

**反模式 6：在库函数里擅自加超时。** 症状：一个通用库内部硬编码 3 秒超时，调用方想让它跑 10 秒都做不到。
正解：**库只接受 ctx，超时策略交给调用方（应用层）决定。** 这也呼应子主题七的 deadline 预算思想——预算的计算需要全局视角，库没有这个视角。

**反模式 7：传 nil ctx。** 症状：运行时 panic（`nil` 接口调 `Done()`）。正解：实在没想好就传 `context.TODO()`，它和 `Background()` 行为一致，但语义上表示"这里待办，以后要接真 ctx"——**是给 code review 留的信号。**

**反模式 8：不分青红皂白地把取消记成 error。**

```go
if err != nil {
    log.Error("failed", err)   // 其中一半是"客户端按了停止键"
}
```

正解：区分 `context.Canceled`（上游不要了，记 debug/info 或不记）和 `context.DeadlineExceeded`（我们自己慢了，记 error/warn 并告警）。**这两个错误的运维含义完全相反。**

**反模式 9：不加超时预算的层层调用。** 症状：接口总时限 5 秒，但里面有 6 跳下游调用，每跳自己 5 秒，最坏情况 30 秒。正解：用 `ctx.Deadline()` 算剩余时间，每跳只拿一部分预算，并预留重试/降级空间。

**反模式 10：只写 happy path，从不测取消分支。** 症状：代码里到处是 `<-ctx.Done()`，但从没有测试真的触发过它，那些分支可能根本不可达或有 bug。正解：测试里主动 `cancel()`，断言函数返回 `context.Canceled`；配合 `goleak` 断言无泄漏。

要不要记住十条？不用。记一句就够：**ctx 是"请求的作用域"，不是"参数的垃圾桶"，也不是"全局变量的替代品"。**

---

## 子主题十一：实战——带 ctx 的 HTTP 服务优雅关闭

需求很朴素：收到 `SIGTERM` 后，**不再接新请求，正在处理的请求最多再跑 10 秒，后台 worker 收到信号退出，数据库连接最后关闭**。K8s 滚动更新时，这就是"零 502"和"每次发布都掉一批请求"的区别。

先看整体骨架，再逐段解释：

```go
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

const (
	shutdownTimeout = 10 * time.Second   // 优雅关闭的最长等待
	requestBudget   = 2 * time.Second    // 单个请求的超时预算
)

type traceIDKey struct{}

func main() {
	// 1. 把 OS 信号变成 ctx：第一次 SIGINT/SIGTERM 取消 ctx
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	mux := http.NewServeMux()
	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		rctx, cancel := context.WithTimeout(r.Context(), requestBudget)
		defer cancel()
		_ = rctx
		_, _ = w.Write([]byte("pong"))
	})

	srv := &http.Server{
		Addr:              ":8080",
		Handler:           traceMiddleware(mux),
		ReadHeaderTimeout: 5 * time.Second,   // 防慢速攻击
		IdleTimeout:       60 * time.Second,
	}
	srv.RegisterOnShutdown(func() {          // 2. 关停钩子：关连接池
		slog.Info("closing db")
		closeDB()
	})

	// 3. 后台 worker 吃同一个 ctx，信号一到自动收摊
	go worker(ctx)

	go func() {
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			slog.Error("server died", "err", err)
			stop()   // 起不来就别卡在等信号上
		}
	}()

	<-ctx.Done()          // 4. 等信号
	slog.Info("shutting down")

	// 5. 给"正在处理的请求"一个独立预算，不再跟随信号 ctx（它已经取消了）
	sdCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), shutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(sdCtx); err != nil {
		slog.Warn("graceful shutdown timed out, force close", "err", err)
		_ = srv.Close()
	}
	slog.Info("bye")
}

func worker(ctx context.Context) {
	t := time.NewTicker(5 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			slog.Info("worker exit", "reason", context.Cause(ctx))
			return
		case <-t.C:
			slog.Info("tick")
		}
	}
}

func traceMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := context.WithValue(r.Context(), traceIDKey{}, newTraceID())
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}
```

逐条拆解其中的设计判断：

**① `signal.NotifyContext`（Go 1.16+）** 是整段代码的支点：它把"操作系统信号"这个事件源，直接翻译成了"一个被取消的 context"。从此**信号处理和请求取消用的是同一套协议**——worker、数据库、HTTP server 全都监听同一个 ctx，不需要任何额外的退出机制。这就是 context 最爽的地方：**一个信号源，全链路收摊。**

**② `Shutdown` 而不是 `Close`。** 两者语义完全不同：

- `Close()`：立刻关闭 listener 和**所有**活跃连接，正在写的响应被截断，客户端收到 connection reset。
- `Shutdown(ctx)`：先关 listener（**不再接新请求**），然后**等**活跃请求自己跑完，空闲连接立刻关。只有 `ctx` 到期还没跑完，才强制断开。

**`Shutdown` 语义里最重要的一条：它不强制中断你的 handler。** 所以 handler 自己必须响应取消——如果你的 handler 里有个 30 秒的死循环不看 ctx，那 10 秒的 shutdown 预算到了，连接照样被强行掐断。**优雅关闭是双向的：框架给你等待的诚意，你得给出退出的能力。** 这又回到了子主题八：可取消性必须由业务代码自己保证。

**③ 第 5 步里为什么是 `context.WithoutCancel(ctx)`？** 这是个精妙但容易写错的点。信号到达后 `ctx` 已经取消了，如果你直接 `context.WithTimeout(ctx, 10*time.Second)`，得到的是一个**立刻就取消**的 context——`Shutdown` 会瞬间返回"超时"，全部请求被强行掐断，优雅关闭形同虚设。**所以给关闭流程的预算，必须脱离那个已经死掉的信号 ctx，另起炉灶。** 这个坑极其隐蔽：代码看起来完全正确，只有在真的发版时才会暴露。

**④ `ListenAndServe` 一定返回错误**（被 Shutdown 时返回 `http.ErrServerClosed`），所以必须用 `errors.Is` 过滤掉。**忘了这一行，每次正常关停都会打一条刺眼的 error 日志。**

**⑤ 第二次信号要立刻走。** 运维同学 Ctrl-C 之后发现没反应，会再按一次。加一段：

```go
force := make(chan os.Signal, 1)
signal.Notify(force, os.Interrupt, syscall.SIGTERM)
select {
case <-ctx.Done():        // 第一次：优雅关闭
case <-force:             // 第二次：不等了，直接走
}
```

**⑥ 生产环境还有一步：先摘流量，再关进程。** `Shutdown` 只保证"这个进程不再接新连接"，但**负载均衡器可能还在往你这里转发**。K8s 场景下正确的顺序是：收到 SIGTERM → 健康检查立刻开始返回失败 → 等 `terminationGracePeriodSeconds` 里留的一小段（或用 `preStop` hook sleep 几秒）让 kubelet 把 endpoint 摘掉 → 再 `Shutdown`。**这中间的几秒，就是"滚动更新零 502"的全部秘密。** 另外记得让 `shutdownTimeout` 小于 `terminationGracePeriodSeconds`，否则你会被 SIGKILL 掉，优雅关闭的钱白花了。

**⑦ 一个 `Shutdown` 管不到的东西：hijacked 连接**（WebSocket、HTTP/2 长流）。`Shutdown` 不跟踪它们。所以有 WebSocket 的服务必须自己做广播关闭：在信号 ctx 上 `AfterFunc` 一个"向所有连接发 close frame"的动作，或者在 worker 里监听 ctx 后主动 `conn.Close()`。

**一句话收束：优雅关闭 = 信号转 ctx + 不再接新 + 给在途请求预算 + 预算独立于信号 ctx + 先摘流量。** 五步缺一不可。

---

## 子主题十二：业界对照补强——Java 结构化并发、C# CancellationToken、Kotlin 协程

同一个问题——"上层不要了，怎么让下面全都停手"——四门语言给了四份答卷。看懂它们，你才真正理解 Go 这份答卷为什么长这样。

### Java：StructuredTaskScope——用"词法作用域"保证生命周期

Java 的传统答案（`ExecutorService` + `Future`）有个致命缺陷：`Future.cancel()` 只能取消"还没开始跑"的任务，**已经在跑的任务根本停不下来**；而且父线程被中断时，中断不会传播给子任务——`fetchOrder()` 会继续在自己的线程里跑完，这是教科书级的线程泄漏。

结构化并发（Structured Concurrency）就是来治这个的。它的发展轨迹值得记一下：JDK 19/20 孵化（JEP 428/437），JDK 21 起转预览（JEP 453，`fork` 返回值从 `Future` 改成 `Subtask`），JDK 22/23/24 连续预览（JEP 462/480/499），**JDK 25（JEP 505，第五次预览）把构造函数改成了 `StructuredTaskScope.open()` 静态工厂并引入 `Joiner` 策略接口，JDK 26（JEP 525，第六次预览）继续打磨（新增 `onTimeout()` 等超时能力）。到 JDK 26 为止它仍是预览 API，需要 `--enable-preview`**——但方向已经确定。

```java
try (var scope = StructuredTaskScope.open()) {     // 词法作用域 = 并发边界
    Subtask<User>   u = scope.fork(() -> findUser(id));
    Subtask<Order>  o = scope.fork(() -> fetchOrder(id));
    scope.join();                                   // 等全部完成
    return new Home(u.get(), o.get());
}   // close：保证所有 subtask 都已结束，否则不让你走出这个块
```

对比 Go，差异非常清晰：

| | Go context | Java StructuredTaskScope |
|---|---|---|
| 生命周期保证 | **约定**：你把 ctx 传下去，并且自觉检查 | **强制**：`close()` 必须等所有 subtask 结束才能走出块 |
| 传播方式 | 显式第一参数 | 词法作用域 + `fork` 自动建立父子 |
| 取消实现 | 关闭 done channel | 中断 subtask 线程（仍是协作式，不响应 interrupt 的阻塞会拖住 `close`） |
| 错误传播 | 靠 `errgroup` 等三方库 | `Joiner` 内建策略（任一失败即短路取消） |

**关键洞察：Java 用"结构"换掉了"纪律"。** Go 的 ctx 可以传、也可以不传，传了也可以不看；Java 的 scope 你没法"忘记等"——`try-with-resources` 会在块结束时强制收敛。

代价是什么？**Java 拿不到 Go 那种"跨任意深度调用链的自由传递"**——`StructuredTaskScope` 的 owner 线程限制很严（`fork`/`join`/`close` 只能由打开 scope 的线程调用），而 Go 的 ctx 可以穿过任何函数、任何 goroutine。**Java 给你更强的保证，Go 给你更轻的工具。** 有意思的是，JEP 里明说"不打算取代线程中断机制"——**所以 Java 的取消和 Go 一样是协作式的**；那个被诟病了二十多年的 `Thread.stop()` 在 JDK 26 的清理动作中被彻底移除，Java 用行动承认了"强制杀死线程"这条路走不通。

顺带一提，**虚拟线程（JEP 444）是这套东西的燃料**：线程便宜到"一个请求一个线程"，才谈得上给每个 subtask 开一条。这和 goroutine 便宜才谈得上"每个子任务一个 ctx"是同一个经济学。而 `ThreadLocal` 的结构化替代（ScopedValue，同样在预览推进）要解决的，正是 Go 里 `ctx.Value` 承担的那个"跨层传递请求级数据"的角色——**你看，需求是同一个，只是落点不同。**

### C#：`CancellationToken`——和 Go context 最像的一份答卷

C# 把这件事拆成两个类型，分工极干净：

- **`CancellationTokenSource`（CTS）**：取消的**所有者**。它 `Cancel()`、`CancelAfter(d)`、`Dispose()`。
- **`CancellationToken`（CT）**：取消的**观察者**，是个 struct，随便按值传递。它只能 `ThrowIfCancellationRequested()`、查 `IsCancellationRequested`、`Register(回调)`。

**这个"所有者 / 观察者"的分离，正是 Go 里 `cancel` 函数和 `ctx` 的关系。** Go 的 `ctx, cancel := WithCancel(p)` 返回两样东西，本质上就是"一个只读信号 + 一个只写开关"，只是 C# 用两个类型把它表达得更形式化。

对应关系一览：

| Go | C# |
|---|---|
| `context.WithCancel(parent)` | `CancellationTokenSource.CreateLinkedTokenSource(parentToken)` |
| `WithTimeout(parent, d)` | `new CancellationTokenSource(d)` + `CreateLinkedTokenSource` 合并外部 token |
| `defer cancel()` | `using var cts = ...`（**必须 Dispose，否则计时器和回调注册不释放**） |
| `<-ctx.Done()` | `await Task.Delay(..., token)` / `token.ThrowIfCancellationRequested()` |
| `context.AfterFunc(ctx, f)` | `token.Register(f)` |
| `ctx.Err()` | `OperationCanceledException`（异常传播） |
| 约定放**第一个**参数 | 约定放**最后一个**参数（且通常带默认值 `default`） |

三种取消响应方式，和 Go 一一对应：

```csharp
// 1. 抛出（最常见，等价于 Go 里 return ctx.Err()）
ct.ThrowIfCancellationRequested();

// 2. 优雅退出（等价于 Go 里 select 到 Done 后做清理再 return）
if (ct.IsCancellationRequested) { Cleanup(); return; }

// 3. 注册回调（等价于 context.AfterFunc）
using var reg = ct.Register(() => Console.WriteLine("cancelled"));
```

几个值得 Go 程序员抄走的细节：

- **`CreateLinkedTokenSource` = Go 的派生。** 合并"外部 token + 内部超时"得到的 linked token，**任意一个源取消它就取消**（OR 语义）。注意：**每个 linked CTS 都会向父 token 注册一个回调**，所以"每秒创建几千个 linked token 挂在长生命周期父 token 上"会成为性能瓶颈——这与 Go 里"每个 `WithCancel` 都要在父的 children 集合里登记一次"是同构的成本，谁也别笑谁。
- **超时和取消都抛 `OperationCanceledException`，怎么区分？** 检查你自己的 `timeoutCts.IsCancellationRequested`：为真就是超时，否则是调用方取消。这比 Go 的 `DeadlineExceeded` vs `Canceled` 两个哨兵值笨拙一些——**Go 在这一点上设计得更干净。**
- **千万别吞掉 `OperationCanceledException`。** 微软文档直接把它列为"应用关不掉"的第一号原因。对应到 Go 就是：**别 `if err != nil { log.Error(...) }` 一把梭，把 `context.Canceled` 也一起吞了。**
- ASP.NET Core 里 `HttpContext.RequestAborted` 就是 Go 的 `r.Context()`——**客户端断开，它就取消。** 同一个痛点，同一个答案。

最大的哲学差异只有一条：**C# 用异常传播取消，Go 用返回值传播取消。** 异常的好处是不会忘记处理（漏了就往上冒），坏处是你要在每个 `catch` 里小心别误吞；Go 的好处是"取消"只是个普通 error、能被 `errors.Is` 组合判断，坏处是你可能压根忘了检查。**C# 靠编译器和运行时兜底，Go 靠 code review 和 goleak 兜底。**

### Kotlin 协程：结构化并发的"完全体"

Kotlin 的协程把这件事做成了**语言级默认行为**，三条规则：

1. **父协程取消，所有子协程自动取消**（递归向下）。
2. **父协程必须等所有子协程结束才算结束**（`coroutineScope {}` 在退出前会 join 所有子协程）。
3. **子协程失败（未捕获异常），默认会取消父协程，进而取消所有兄弟**（除非用 `SupervisorJob`/`supervisorScope`）。

```kotlin
suspend fun loadHome(uid: Long) = coroutineScope {      // 作用域 = 生命周期边界
    val user   = async { fetchUser(uid) }
    val orders = async { fetchOrders(uid) }
    Home(user.await(), orders.await())
}   // 走出这个块时：所有子协程必定已结束；任一失败则其余全部取消
```

**和 Go 的对比要害在这里：Kotlin 的父子关系是隐式建立的。** 你只要在 `CoroutineScope` 里 `launch`/`async`，父子关系自动成立，不需要传任何参数。Go 需要你手动 `WithCancel` + 手动传 ctx。**这确实是"更少的心智负担"——Kotlin 程序员不会写出"忘了传 ctx"这种 bug。**

但——**Kotlin 的取消依然是协作式的。** 这一点必须说清楚，因为很多人误以为"自动传播 = 强制杀死"。真相是：

```kotlin
// 这样写，取消不会生效：CPU 密集循环里没有挂起点，协程根本不检查取消
while (true) { heavyCompute() }

// 必须主动让出检查点
while (isActive) { heavyCompute() }        // isActive ≈ ctx.Err() == nil
// 或
ensureActive()                              // ≈ select 到 Done 就抛 CancellationException
// 或
yield()                                     // 主动让出调度，顺带检查取消
```

**`while (isActive)` 就是 Kotlin 版的 `select { case <-ctx.Done(): return }`。** 发现没？**两门语言的"协作式取消"是同一个灵魂，只是 Kotlin 给它起了个 `isActive` 的名字，Go 给了个 channel。** 而且 Kotlin 同样有"清理阶段不能被取消"的需求，对应 `withContext(NonCancellable) { ... }`——Go 这边你得自己用 `WithoutCancel` 或者一个已经保存好的 background ctx 来实现。

`supervisorScope` 是另一个值得对照的精妙设计：**它只打破"失败向上传播"，不打破"取消向下传播"。** 也就是说，一个子协程崩了不会连坐兄弟，但父协程被取消时，子协程照样全部收摊。**这两件事是正交的**——很多 Go 程序员会把它们混为一谈，以为"某个任务失败不该影响别人"就得整条链脱离取消，其实不需要：`errgroup` 已经帮你处理了失败传播，取消传播始终应该保留。

最后是共通的反模式：**`GlobalScope.launch {}` 之于 Kotlin，等价于 `go func() { ... }()` 里用 `context.Background()` 之于 Go。** 两者都表示"这个任务的生命周期和任何作用域都无关"——也就是"我制造了一个不受控的东西"。**这就是为什么 Go 社区强调 `go` 出来的 goroutine 必须有退出路径，Kotlin 社区强调不要用 GlobalScope。同一条戒律，两种说法。**

### 收束：为什么 Go 不学 Kotlin？

一个很自然的问题：**既然隐式作用域传播这么省事，Go 为什么坚持显式传 ctx？**

因为"隐式"需要一个前提：**运行时知道"当前 goroutine 是谁的孩子"**，也就是要维护一张动态的 goroutine 亲缘表（类似于 ThreadLocal 那种动态作用域）。这会带来两个 Go 不愿付的代价：一是**每次 goroutine 创建/退出都要维护这张表，这是调度器热路径上的成本**；二是**函数签名上看不出它受谁管，违背 Go"显式优于隐式"的核心审美**。

Go 的选择是：**把"建立父子关系"的成本，从运行时挪到代码里——`WithCancel` 那一行、那个 `ctx` 参数，就是你付出的一次性成本，换来的是"取消的边界在代码里肉眼可见"。**

所以别再抱怨 ctx 满屏飞了。**那不是啰嗦，那是 Go 在强迫你把"这个调用会不会被取消、被谁取消"这件事，在写下这行代码的时候就想清楚。**

---

## 业界对照

**Java：** 没有语言级的 context。取消机制散落在各处：`Thread.interrupt()`（协作式中断标志）、`Future.cancel()`（有取消语义但往往只是标记）、响应式流（Reactor/RxJava）里的 `Subscription.cancel()` 和背压。Java 的取消是"碎片化"的，没有统一的"信号树"协议。Java 21 的虚拟线程 + Structured Concurrency 在尝试引入类似 context 的结构化取消。

**C#：** `CancellationToken` + `CancellationTokenSource` 是 .NET 的"取消协议"，和 Go 的 context 高度同源（都是"可传播的取消信号"）。区别是 C# 用 `async/await` + 异常来传播取消，Go 用显式的 `ctx` 参数 + `select`。两者殊途同归。

**Kotlin（协程）：** `CoroutineScope` + `Job` 提供了**结构化并发（structured concurrency）**——子协程的生命周期绑定在父协程上，父协程取消，子协程自动取消。这比 Go 的 context 更进一步（Go 需要手动传递 ctx，Kotlin 靠作用域自动传播）。Go 社区也有类似的诉求，但官方至今坚持显式传递 ctx。

**Rust（tokio）：** 取消靠 `tokio::select!` + `CancellationToken`（三方库），或 drop future 来取消。Rust 的"取消"是"drop 即取消"，非常彻底（future 被丢弃就真的不跑了），但这也要求代码对"随时可能被 drop"保持警惕。

---

## 版本演进小结

- context 从 golang.org/x/net/context 演进而来，Go 1.7 正式进入标准库。
- 它出现的背景：Google 内部大量服务需要一个统一的"请求级取消和元数据传递"协议，社区方案（x/net/context）证明了价值，于是转正。
- 之后 context 逐渐渗透进标准库的 I/O、HTTP、数据库驱动，成为 Go 服务端编程的"基础设施协议"。

主线：**context 是 Go 对"请求级取消"这个真实痛点给出的标准答案——它用一颗显式的信号树，统一了"超时、取消、元数据传递"三件事，代价是要求你处处显式传递。这是 Go"显式优于隐式"哲学在并发取消上的集中体现。**

---

## 本章思考题

【思考题】

1. context 为什么要"显式传递"而不是做成全局变量？它的取消是"强制"还是"协作"的？

2. `WithTimeout` 为什么必须 `defer cancel()`？忘了会怎样？

3. context.Value 的 key 为什么推荐用私有自定义类型而不是 string？value 应该放什么、不该放什么？

4. 一个 goroutine 阻塞在 `ch <- v` 上，怎么写才能让它响应 ctx 取消？

5. context 的取消是"单向"还是"双向"的？子 context 被取消，父 context 会受影响吗？这个性质为什么重要？

6. 用 `WithCancel` 创建子 context 时，"把自己登记进父的 children 集合"这一步为什么是必须的？取消时又为什么要把自己从父的 children 里摘掉（不摘会怎样）？

7. 父 context 的 deadline 是 3 秒后，你却写 `context.WithDeadline(parent, time.Now().Add(一年))`，实际会得到什么？为什么这样设计？

8. 服务端日志里怎么区分"我们自己超时了"和"客户端跑了"？为什么把这两者混为一谈会毁掉你的告警？

9. 一个 HTTP handler 里写了 `context.Background()` 而不是用 `r.Context()`，会造成什么后果？中间件里 `r.WithContext(ctx)` 之后忘了用返回值会怎样？

10. 在 `errgroup.WithContext` 的并发场景里，其中一个子任务的 goroutine 卡在一个不支持 ctx 的老式阻塞调用上。你起了一个"救援 goroutine"去包它，写出这个包装函数，并指出其中最容易泄漏的一行。

11. 优雅关闭时，下面这行代码有什么致命问题？`sdCtx, cancel := context.WithTimeout(signalCtx, 10*time.Second)`（signalCtx 是 `signal.NotifyContext` 返回的、已被信号取消的 context）。

12. 一个纯 CPU 密集的长循环（没有任何 channel 或 I/O 操作），怎么让它响应 ctx 取消？这个方案的性能开销怎么控制？

13. 对比 Go 的 context 与 Kotlin 协程的结构化并发：两者在"父子关系如何建立"和"取消是否强制"这两点上分别是怎样的？

【参考答案】

1. 因为取消信号有作用域——一个请求的取消只应影响该请求相关的 goroutine，全局变量无法隔离；显式传递让"取消的边界"一目了然，符合 Go"显式优于隐式"哲学。取消是**协作式**的：ctx 只是发信号，goroutine 必须自己监听 `ctx.Done()` 并退出，否则 ctx 漏不掉它。Go 无法从外部强制杀死 goroutine，这是并发模型的根本性质。

2. 因为 `WithTimeout`/`WithDeadline` 内部创建了计时器，不用 `defer cancel()` 的话，计时器要等超时时间到了才释放；大量短请求累积，会泄漏计时器资源。所以铁律是 `ctx, cancel := ...; defer cancel()`，让请求一结束就释放。

3. 因为 string key 容易在不同包之间撞名，导致值被覆盖或误读；用私有类型 `type ctxKey struct{}`，别的包构造不出相同 key，天然隔离。value 只应放"横切关注点"（traceID、鉴权信息、日志字段等请求级元数据），不放业务数据——业务数据塞 value 会破坏类型安全、让依赖隐晦、难测试，应显式传参。

4. 用 select 兜底：`select { case ch <- v: ...; case <-ctx.Done(): return }`。这样当 ctx 取消时，即使 channel 无人接收，goroutine 也能从 `ctx.Done()` 分支退出，不再永久阻塞在发送上。这是给阻塞 goroutine 留"可取消出口"的标准写法。

5. **单向：只向下（父→子），绝不向上。** 子 context 取消，父 context 及兄弟 context 毫发无损。这个性质之所以重要，是因为它让"分层超时"成为可能：你可以给每个子任务套一个比父更短的超时（父 5 秒、子任务各 800ms），子任务超时自己烂掉，不会连累整个请求。如果取消是双向的，任何一个子任务超时都等于整个请求放弃，超时预算就没法分层设计了。兄弟之间互不影响同理——想让"一个失败、兄弟一起停"，那是 `errgroup` 的职责，不是 `context` 包的。

6. 登记是必须的，因为**取消的传播靠的就是这张 children 表**：父取消时，它只能遍历自己 children 集合里登记过的节点，逐个递归取消；没登记过就等于没挂在这棵树上，父取消时它收不到信号（此时创建流程会退化成"起一个 goroutine 守着父的 Done()"来兜底）。取消时把自己摘掉同样关键，这是一道**内存泄漏防线**：子 context 结束了但父还活着（比如长生命周期的父），如果父的 children 集合里一直留着这个死节点，整棵子树都会因为这一个引用而无法被 GC。**所以 cancel 不只是"发信号"，也是一次"从树上摘果子"。**

7. 会得到**继承父的 3 秒 deadline 的 context，而不会真的设一个一年后的计时器**。因为创建时若发现父的 deadline 早于你给的 deadline，就直接沿用父的（返回的是仅带取消能力的节点，不再新建计时器）。这样设计在语义上完全正确：**父都死了，子活再久也没意义。** 推论是：`ctx.Deadline()` 返回的永远是"真正生效的截止时间"，可以安全地用它算剩余预算（`time.Until(dl)`），来决定还能不能重试、给下游留多少、要不要直接降级。

8. 用两个哨兵错误区分：`errors.Is(err, context.DeadlineExceeded)` 是**我们自己慢了/下游慢了**，属于真实故障，该记 warn/error 并计入告警和 SLO；`errors.Is(err, context.Canceled)` 是**上游不要了**（客户端关页面、网关先超时、调用方放弃），属于正常现象，记 debug/info 甚至不记。**混为一谈的后果**：把海量的"客户端断开"当成 error 打出来并告警，运维很快就会对告警免疫（告警疲劳），等真正的超时故障混进这批噪声里时，没人会再看。这两者的运维含义完全相反，必须在错误处理的分岔口就分开。

9. 后果是**在这条调用链上剪了一刀**：下游所有函数拿到的都是一个永不取消的 ctx——客户端断开不会传导下去（goroutine 和数据库连接继续耗着）、你设的接口级超时对下游失效、traceID 和用户身份等 ctx.Value 全部丢失（日志再也串不起来）。这等于把一个有生命周期的请求变成了一个"孤儿任务"。中间件里 `r.WithContext(ctx)` 忘了用返回值（继续把旧 `r` 传给 `next`）同样无效：因为 `WithContext` 返回的是**浅拷贝的副本**，`*Request` 不允许原地修改 ctx（它可能被并发读取）。正确写法是 `next.ServeHTTP(w, r.WithContext(ctx))`，把副本一路传下去。

10. 包装函数：

```go
func callLegacy(ctx context.Context) error {
    done := make(chan error, 1)                 // 必须是带缓冲的！
    go func() { done <- legacyBlockingCall() }()
    select {
    case err := <-done:
        return err
    case <-ctx.Done():
        return ctx.Err()
    }
}
```

最容易泄漏的一行是 `make(chan error, 1)` 的**缓冲大小**。如果写成无缓冲的 `make(chan error)`，那么当 ctx 先取消、`select` 走 `ctx.Done()` 分支返回后，里面那个 goroutine 会永久卡在 `done <- err` 上——**你修好了一个泄漏，又造了一个**。带缓冲 1 就是为了让救援 goroutine 无论谁先到都能无阻塞地写下结果并退出。还要注意：`legacyBlockingCall()` 本身仍会跑完，这是"包装不可取消操作"必须接受的代价（ctx 取消的是"等待"，不是"底层操作"）。

11. `signalCtx` 已经被信号取消了，基于它派生出来的 context **会立刻处于已取消状态**，等于 `Shutdown` 拿到一个一开始就过期的 deadline——它会瞬间返回 `context.Canceled`（或 DeadlineExceeded），把所有在途请求强行掐断，优雅关闭完全失效。正确做法是脱离这个已死的信号 ctx，另起炉灶给关闭流程一个独立预算：`context.WithTimeout(context.WithoutCancel(signalCtx), 10*time.Second)`。这个坑极其隐蔽：代码读起来毫无问题，只有在真的发版（收到 SIGTERM）时才会暴露一次掉一片请求。

12. 在循环里**分片检查** ctx，把检查开销摊薄到可忽略：

```go
for i := 0; i < n; i++ {
    if i%1024 == 0 {                     // 每 1024 次迭代检查一次
        select {
        case <-ctx.Done():
            return ctx.Err()
        default:                          // 关键：default 让 select 变成非阻塞探测
        }
    }
    step(i)
}
```

要点：① **必须有 `default` 分支**，否则 select 会阻塞住整个循环，反而把计算卡死；② 检查频率可按单次迭代耗时调（1024 只是常用起点，目标是让检查开销占比 < 1%）；③ 如果循环体内部是可拆分的块，更好的位置是在**每个数据块边界**检查，而不是固定次数。同理，`time.Sleep` 也不可取消，要用 `time.NewTimer` + `select`（并且循环里别用 `time.After`，它的计时器直到触发才回收，高频循环会堆积悬挂计时器）。

13. **父子关系如何建立**：Kotlin 是**隐式**的——只要在 `CoroutineScope` 内 `launch`/`async`，父子关系由作用域自动建立，无需传参；Go 是**显式**的——必须 `context.WithCancel(parent)` 并把 ctx 作为第一参数一路传下去，漏传就等于脱离取消链。**是否强制**：两者都**不是强制的，都是协作式**。Kotlin 的自动传播只是"自动把取消信号发给子协程"，子协程仍需在挂起点或 `isActive`/`ensureActive()`/`yield()` 处检查才能真正停下；Go 同理，goroutine 必须自己 `select` 到 `ctx.Done()` 才退出。**所以"自动传播"≠"强制杀死"**——`while(true) { heavyCompute() }` 在 Kotlin 里叫不醒，等价于 Go 里不看 ctx 的死循环叫不醒。另外 `supervisorScope` 只打破"失败向上传播"，**不打破"取消向下传播"**，这两件事是正交的，别混为一谈。
