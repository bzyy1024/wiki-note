# 分布式缓存一致性

---
前置知识: [01-cache-aside.md, 02-write-strategies.md]
难度: ⭐⭐⭐⭐
预计时间: 45分钟
关键词: Redis Cluster, 缓存分片, 一致性哈希, 数据同步, 多级缓存
---

## 引入场景

单机Redis能撑几万QPS，但当业务增长到百万QPS时，一台Redis不够了。你需要部署Redis集群——但集群引入了新的一致性问题：不同节点上的数据如何保持同步？key应该存在哪个节点？

## 对话探索

**问题1：为什么需要分布式缓存？单机Redis的瓶颈在哪里？**

💭 思考方向：
- 内存容量有限
- 单机QPS有上限
- 单机故障怎么办？

📖 参考答案：

| 瓶颈 | 单机Redis | 分布式方案 |
|------|----------|-----------|
| **内存** | 最大几百GB | 水平扩展，总容量=节点数×单节点 |
| **QPS** | 10-20万 | 总QPS=节点数×单节点QPS |
| **可用性** | 单点故障 | 主从复制+故障转移 |

**分布式缓存的基本架构**：

```
客户端
  │
  ├─→ Redis节点1 (key: a-g)
  ├─→ Redis节点2 (key: h-n)
  └─→ Redis节点3 (key: o-z)
```

核心问题：**如何决定key存在哪个节点？**

---

**问题2：怎么把key分配到不同节点？为什么不能简单地用 `hash(key) % N`？**

💭 思考方向：
- 如果某个节点挂了，N变成N-1？
- 如果需要扩容增加节点？
- 所有key的映射都会变？

📖 参考答案：

**简单取模的问题**：

```
3个节点时：hash("user:1") % 3 = 1 → 节点1
扩到4个后：hash("user:1") % 4 = 2 → 节点2 ← 变了！

几乎所有key的映射都会改变 → 大量缓存失效 → 缓存雪崩
```

**一致性哈希（Consistent Hashing）** 解决这个问题：

```
将哈希空间想象为一个环（0 ~ 2^32-1）：

              0
          /      \
        /          \
      节点A        节点B
        \          /
         \        /
          节点C
              
key的分配规则：沿环顺时针找到的第一个节点

增加节点D时：只有D和它逆时针方向前一个节点之间的key需要迁移
删除节点B时：只有B上的key要迁移到B顺时针的下一个节点
```

**Redis Cluster实际使用的是哈希槽（Hash Slot）**：

```
总共 16384 个槽

节点A: 槽 0-5460
节点B: 槽 5461-10922
节点C: 槽 10923-16383

key → CRC16(key) % 16384 → 得到槽号 → 找到对应节点

扩容时：从现有节点迁移一部分槽到新节点
```

---

**问题3：Redis Cluster的主从复制是异步的，这意味着什么？**

💭 思考方向：
- 主节点写入后，数据什么时候到从节点？
- 如果主节点在复制前崩溃？
- 客户端从从节点读，可能读到旧数据？

📖 参考答案：

**Redis复制是异步的**：

```
客户端写入 → 主节点确认 → 返回成功 → 异步复制到从节点
                                      │
                                      └─ 有延迟！通常几毫秒到几十毫秒
```

**可能的问题**：

1. **写后读不一致**：
   ```
   写请求 → 主节点（成功）
   读请求 → 从节点（还没收到复制数据）→ 返回旧值
   ```

2. **数据丢失**：
   ```
   写请求 → 主节点（成功，还没复制）
   主节点崩溃 → 从节点提升为主 → 那条数据丢了
   ```

3. **脑裂（Split Brain）**：
   ```
   网络分区 → 客户端继续写旧主节点
           → 集群选举了新主节点
           → 分区恢复后，旧主的数据被丢弃
   ```

**应对策略**：

```
1. 关键写操作使用 WAIT 命令
   WAIT <numreplicas> <timeout>
   等待至少N个从节点确认收到数据
   
2. 配置 min-replicas-to-write
   至少N个从节点在线才接受写入
   
3. 业务层面
   对于强一致性要求的数据，用数据库而不是Redis
```

---

**问题4：多级缓存（本地缓存 + Redis + DB）的一致性怎么保证？**

💭 思考方向：
- 本地缓存（进程内，如Go的map/sync.Map）
- Redis缓存（集中式）
- 更新时要清除哪些缓存？

📖 参考答案：

**多级缓存架构**：

```
请求 → 本地缓存（L1, 进程内, ~1μs）
       │ miss
       → Redis缓存（L2, 网络, ~1ms）
         │ miss
         → MySQL（~10ms）
```

**一致性挑战加倍**：

```
更新DB后，需要清除：
1. Redis缓存 → 延迟双删 / 直接删除
2. 所有应用实例的本地缓存 → 怎么通知？
```

**清除本地缓存的方案**：

```
方案1：Redis Pub/Sub
  更新DB → 发布消息到Redis频道 → 所有实例订阅并清除本地缓存

方案2：广播通知（如Kafka）
  更新DB → 发消息到Kafka → 所有实例消费并清除

方案3：短TTL
  本地缓存TTL设很短（如5-10秒）→ 接受短暂不一致

方案4：版本号/时间戳
  每条数据带版本号，读取时比对版本
```

```go
// Redis Pub/Sub通知本地缓存失效
func setupCacheInvalidation(rdb *redis.Client, localCache *sync.Map) {
    pubsub := rdb.Subscribe(ctx, "cache:invalidate")
    
    go func() {
        for msg := range pubsub.Channel() {
            key := msg.Payload
            localCache.Delete(key)  // 清除本地缓存
        }
    }()
}

func UpdateUserAndInvalidate(db *sql.DB, rdb *redis.Client, user User) error {
    key := "user:" + user.ID
    
    // 更新DB
    if err := updateDB(db, user); err != nil {
        return err
    }
    
    // 删除Redis缓存
    rdb.Del(ctx, key)
    
    // 通知所有实例清除本地缓存
    rdb.Publish(ctx, "cache:invalidate", key)
    
    return nil
}
```

---

**问题5：缓存雪崩、击穿、穿透在分布式环境下如何防护？**

💭 思考方向：
- 雪崩：大量key同时过期
- 击穿：热点key过期
- 穿透：查不存在的key
- 分布式环境下这些问题会放大

📖 参考答案：

| 问题 | 描述 | 解决方案 |
|------|------|---------|
| **雪崩** | 大量key同时过期 | TTL加随机偏移：`TTL = 基础TTL + random(0, 60s)` |
| **击穿** | 热点key过期 | singleflight / 分布式互斥锁 |
| **穿透** | 查不存在的key | 空值缓存(短TTL) / 布隆过滤器 |

```go
// 防雪崩：TTL随机化
func setWithJitter(rdb *redis.Client, key string, val interface{}, baseTTL time.Duration) {
    jitter := time.Duration(rand.Intn(60)) * time.Second
    rdb.Set(ctx, key, val, baseTTL+jitter)
}

// 防击穿：singleflight（单机有效）
var sfGroup singleflight.Group

func getWithSingleflight(key string) (interface{}, error) {
    return sfGroup.Do(key, func() (interface{}, error) {
        // 只有一个goroutine执行，其他等待结果
        return queryDB(key)
    })
}

// 防穿透：缓存空值
func getWithNullCache(rdb *redis.Client, key string) (*User, error) {
    val, err := rdb.Get(ctx, key).Result()
    if err == nil {
        if val == "NULL" {
            return nil, ErrNotFound  // 空值缓存命中
        }
        return decode(val), nil
    }
    
    user, err := queryDB(key)
    if err == ErrNotFound {
        rdb.Set(ctx, key, "NULL", 1*time.Minute)  // 缓存空值，短TTL
        return nil, ErrNotFound
    }
    
    rdb.Set(ctx, key, encode(user), 10*time.Minute)
    return user, nil
}
```

## 小结

⭐ **核心要点**：
1. **分布式缓存用哈希槽/一致性哈希分配key**，扩缩容时只迁移部分数据
2. **Redis复制是异步的**：可能丢数据、可能读到旧值——强一致性数据不应只依赖Redis
3. **多级缓存**：本地缓存+Redis+DB，通过Pub/Sub或消息队列通知清除本地缓存

## 关联阅读

- **前置**：[Cache-Aside](01-cache-aside.md)、[写策略](02-write-strategies.md)
- **深入**：[Go实现](04-go-implementation.md)（完整代码）
- **理论**：[一致性模型](../../theory/02-consistency-models.md)（异步复制→最终一致性）
- **相关**：[分布式锁](../concurrency-control/03-distributed-lock.md)（Redis Cluster中的锁）
