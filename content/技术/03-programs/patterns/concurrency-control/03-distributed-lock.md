# 分布式锁：Redis、Etcd、ZooKeeper

---
前置知识: [../consistency/00-problem-space.md]
难度: ⭐⭐⭐⭐
预计时间: 55分钟
关键词: 分布式锁, Redis锁, Etcd锁, Redlock, 锁续租, fencing token
---

## 引入场景

你的服务部署了多个实例。用户下单时要扣减库存，如果两个实例同时处理同一个商品的订单，都读到库存=1，都执行扣减，库存变成了-1。

单机Go程序中你会用 `sync.Mutex`，但多个进程间呢？这就需要**分布式锁**。

## 对话探索

**问题1：分布式锁需要满足哪些基本条件？**

💭 思考方向：
- 同一时刻只有一个客户端持有锁
- 持有锁的客户端崩溃了，锁怎么办？
- 网络延迟导致客户端以为锁还在，其实已过期？

📖 参考答案：

分布式锁的三个核心要求：

| 要求 | 说明 | 如果违反 |
|------|------|---------|
| **互斥性** | 同一时刻只有一个客户端持有锁 | 数据竞争、重复扣减 |
| **无死锁** | 持有者崩溃后，锁最终会被释放 | 锁永远不释放，服务卡死 |
| **安全释放** | 只有锁的持有者能释放锁 | 误释放别人的锁 |

可选但重要：
- **可重入**：同一客户端可以重复加锁
- **续租**：长时间操作时可以延长锁的有效期
- **公平性**：等待队列按序获取锁

---

**问题2：用Redis实现最基本的分布式锁怎么做？有什么陷阱？**

💭 思考方向：
- `SETNX` 命令（SET if Not eXists）
- 锁需要设过期时间
- 释放锁时要检查是否是自己加的

📖 参考答案：

**基本实现**：

```go
// ❌ 错误示例1：没有过期时间
rdb.SetNX(ctx, "lock:order:123", "1", 0)
// 如果客户端崩溃，锁永远不会释放 → 死锁

// ❌ 错误示例2：SETNX和EXPIRE不是原子的
rdb.SetNX(ctx, "lock:order:123", "1", 0)
rdb.Expire(ctx, "lock:order:123", 10*time.Second)
// 如果在两条命令之间崩溃 → 死锁

// ✅ 正确：使用SET的NX+EX选项（原子操作）
locked, err := rdb.SetNX(ctx, "lock:order:123", clientID, 10*time.Second).Result()
```

**安全释放**——必须用Lua脚本保证原子性：

```go
// ❌ 错误示例：先GET再DEL不是原子的
val, _ := rdb.Get(ctx, "lock:order:123").Result()
if val == clientID {
    rdb.Del(ctx, "lock:order:123")  // 在GET和DEL之间锁可能已过期并被其他客户端获取！
}

// ✅ 正确：Lua脚本保证原子性
const unlockScript = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
`

func Unlock(ctx context.Context, rdb *redis.Client, key, clientID string) (bool, error) {
    result, err := rdb.Eval(ctx, unlockScript, []string{key}, clientID).Int64()
    return result == 1, err
}
```

**陷阱：锁过期但业务未完成**

```
时间线：
  0s    客户端A获取锁（TTL=10s）
  ...   客户端A执行业务（GC暂停、网络延迟...）
  10s   锁自动过期！
  10.1s 客户端B获取了同一个锁
  10.2s 客户端A恢复，继续执行业务 → 此时A和B同时在临界区！
  10.5s 客户端A释放锁 → 释放的是B的锁！（如果不检查clientID）
```

---

**问题3：锁续租（Watch Dog）如何解决过期问题？**

💭 思考方向：
- 如果TTL能自动延长呢？
- 后台线程定期续期
- 客户端真的崩了，续期自然停止→锁自动过期

📖 参考答案：

**锁续租机制**：

```
客户端A获取锁（TTL=30s）
  │
  ├─ 主goroutine：执行业务逻辑
  │
  └─ 续租goroutine：每10s检查一次
       ├─ 锁还在？→ 续期到30s
       ├─ 锁还在？→ 续期到30s
       └─ 业务完成/客户端崩溃 → 停止续期 → 锁30s后自动过期
```

```go
type RedisLock struct {
    rdb      *redis.Client
    key      string
    value    string
    ttl      time.Duration
    cancelFn context.CancelFunc
}

func NewRedisLock(rdb *redis.Client, key string, ttl time.Duration) *RedisLock {
    return &RedisLock{
        rdb:   rdb,
        key:   key,
        value: generateUniqueID(), // UUID或随机字符串
        ttl:   ttl,
    }
}

func (l *RedisLock) Lock(ctx context.Context) error {
    // 尝试获取锁
    ok, err := l.rdb.SetNX(ctx, l.key, l.value, l.ttl).Result()
    if err != nil {
        return err
    }
    if !ok {
        return errors.New("lock: failed to acquire")
    }

    // 启动续租
    renewCtx, cancel := context.WithCancel(context.Background())
    l.cancelFn = cancel
    go l.renewLoop(renewCtx)

    return nil
}

func (l *RedisLock) renewLoop(ctx context.Context) {
    ticker := time.NewTicker(l.ttl / 3) // 每1/3 TTL续期一次
    defer ticker.Stop()

    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            // Lua脚本：只有持有者才能续期
            const renewScript = `
            if redis.call("GET", KEYS[1]) == ARGV[1] then
                return redis.call("PEXPIRE", KEYS[1], ARGV[2])
            else
                return 0
            end
            `
            l.rdb.Eval(context.Background(), renewScript,
                []string{l.key}, l.value, l.ttl.Milliseconds())
        }
    }
}

func (l *RedisLock) Unlock(ctx context.Context) error {
    // 停止续租
    if l.cancelFn != nil {
        l.cancelFn()
    }
    // 安全释放锁
    _, err := Unlock(ctx, l.rdb, l.key, l.value)
    return err
}
```

---

**问题4：Redis单节点锁和Etcd锁相比，各有什么优缺点？**

💭 思考方向：
- Redis单节点可能宕机丢数据
- Etcd基于Raft协议，强一致性
- 性能差异、运维差异

📖 参考答案：

| 特性 | Redis单节点锁 | Etcd锁 |
|------|-------------|--------|
| **一致性** | 弱（异步复制可能丢锁） | 强（Raft共识） |
| **性能** | 高（~10万QPS） | 较低（~1万QPS） |
| **可靠性** | 单点故障风险 | 集群多数节点存活即可 |
| **锁续租** | 需自己实现 | 内置Lease机制 |
| **等待队列** | 需自己实现（轮询） | 内置Watch + 有序前缀 |
| **运维** | 简单 | 较复杂（需理解Raft） |

**Etcd锁示例**（使用官方concurrency包）：

```go
import (
    clientv3 "go.etcd.io/etcd/client/v3"
    "go.etcd.io/etcd/client/v3/concurrency"
)

func etcdLockExample() error {
    cli, _ := clientv3.New(clientv3.Config{
        Endpoints: []string{"localhost:2379"},
    })
    defer cli.Close()

    // 创建session（自带Lease续租）
    session, _ := concurrency.NewSession(cli, concurrency.WithTTL(10))
    defer session.Close()

    // 创建互斥锁
    mutex := concurrency.NewMutex(session, "/locks/order/123")

    // 加锁（阻塞等待）
    if err := mutex.Lock(context.Background()); err != nil {
        return err
    }
    defer mutex.Unlock(context.Background())

    // 执行临界区代码
    fmt.Println("acquired lock, doing work...")

    return nil
}
```

**选型建议**：

```
你的场景是？
│
├─ 数据丢失可以容忍（如缓存更新、限流）
│   └─ ✅ Redis锁：简单、高性能
│
├─ 数据绝对不能重复处理（如支付、库存）
│   └─ ✅ Etcd锁：强一致、可靠
│
├─ 已有Redis集群，且要求极高可靠性
│   └─ ⚠️ Redlock（Redis多节点，有争议）
│
└─ 已有ZooKeeper
    └─ ✅ ZK锁：类似Etcd，基于ZAB协议
```

---

**问题5：Redlock是什么？Martin Kleppmann为什么批评它？**

💭 思考方向：
- 单Redis节点不可靠，多节点呢？
- 多数节点加锁成功就算成功？
- 时钟漂移的问题

📖 参考答案：

**Redlock算法**（Redis作者Antirez提出）：

```
N个独立Redis节点（如5个），执行：
1. 记录当前时间t1
2. 逐个尝试在N个节点上加锁（每个节点设超时）
3. 记录当前时间t2
4. 如果在多数节点（N/2+1）加锁成功，且t2-t1 < 锁TTL → 加锁成功
5. 否则 → 在所有节点释放锁
```

**Martin Kleppmann的批评**（"How to do distributed locking"）：

核心论点：**Redlock依赖时钟假设，但分布式系统不应该依赖时钟**。

```
问题场景：
1. 客户端A在3/5节点获取锁
2. 节点1的时钟跳跃（NTP调整）→ 锁提前过期
3. 客户端B在3/5节点获取锁（包括时钟跳跃的节点1）
4. 此时A和B都认为自己持有锁 → 互斥性被打破

更安全的替代：Fencing Token
  - 锁服务每次发锁都附带一个递增的token
  - 资源操作时带上token
  - 资源服务端拒绝旧的token
  → 即使锁失效，旧token的操作也会被拒绝
```

**实际建议**：
- 大多数场景用单Redis节点+TTL+续租就够了
- 对安全性要求高的场景用Etcd
- Redlock的复杂度高但安全性仍有争议，不推荐

## 小结

⭐ **核心要点**：
1. **Redis锁**：SET NX EX + Lua脚本释放 + 续租，适合大多数场景
2. **Etcd锁**：基于Raft强一致性 + 内置Lease + Watch，适合安全性要求高的场景
3. **没有完美方案**：Redis锁快但可能不安全，Etcd锁安全但较慢——根据业务选择

## 关联阅读

- **前置**：[缓存一致性问题空间](../consistency/00-problem-space.md)
- **相关**：[幂等性设计](../reliability/01-idempotency.md)（分布式锁+幂等=可靠的并发控制）
- **理论**：[一致性模型](../../theory/02-consistency-models.md)（理解Redis和Etcd一致性差异）
- **理论**：[系统思维](../../theory/08-thinking-in-systems.md)（分布式锁的权衡）
