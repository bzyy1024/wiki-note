# 模式：Cache-Aside 与延迟双删

---
前置知识: [00-problem-space.md]
难度: ⭐⭐⭐
预计时间: 50分钟
关键词: Cache-Aside, 延迟双删, 缓存更新策略, Redis, 并发安全
---

## 引入场景

上一篇我们分析了缓存不一致问题的根源。现在来学习最常用的解决方案：**Cache-Aside模式**，以及它的增强版——**延迟双删**。

这是工作中最常遇到的缓存策略，理解它能帮你设计90%以上的缓存方案。

## 对话探索

**问题1：Cache-Aside模式的完整流程是什么？为什么叫"Cache-Aside"？**

💭 思考方向：
- Cache-Aside = "缓存在旁边"
- 应用程序负责管理缓存，缓存不是"自动"工作的
- 读和写分别怎么操作？

📖 参考答案：

**Cache-Aside = 旁路缓存**，意思是缓存"在数据库旁边"而非"在数据库前面"，由应用程序手动管理。

**读流程**：
```
客户端 → 应用程序 → 查Redis
                      │
                      ├─ 命中 → 返回缓存数据（快！）
                      │
                      └─ 未命中 → 查MySQL → 写入Redis → 返回数据
```

**写流程**：
```
客户端 → 应用程序 → 更新MySQL → 删除Redis缓存
                                 （下次读取时自动重建缓存）
```

**核心原则**：
1. **读**：缓存没有就从DB读，然后回填缓存
2. **写**：先写DB，然后删除缓存（不是更新缓存）
3. **懒加载**：缓存只在被读取时才创建

为什么**删除而不是更新**缓存？
- 删除是**幂等**的：删100次效果一样
- 更新可能因并发导致错乱（上一篇分析过）
- 如果这条数据接下来不被读取，更新缓存是浪费

---

**问题2：Cache-Aside的主要弱点是什么？在什么场景下会出问题？**

💭 思考方向：
- 并发读写时……
- 缓存刚好过期的瞬间……
- 大量请求同时缓存未命中……

📖 参考答案：

**弱点1：并发读写的不一致窗口**

```
请求A（读，缓存miss）              请求B（写）
──────────────────               ──────────────
1. 缓存未命中
2. 读DB → 旧值（price=100）
                                  3. DB更新 price=200
                                  4. 删除缓存
5. 将旧值写入缓存（price=100）     
                                  
结果：DB=200, 缓存=100 ← 不一致！直到缓存过期
```

出现条件：读DB 和 写入缓存 之间，恰好有写操作完成。窗口极短但确实存在。

**弱点2：缓存击穿**

```
热点key过期 → 大量请求同时缓存未命中 → 全部打到DB → DB压力暴增
```

**弱点3：缓存穿透**

```
查询不存在的数据 → 缓存永远miss → 每次都打到DB
```

---

**问题3：延迟双删（Double Delete）如何解决并发不一致问题？**

💭 思考方向：
- "双删"——删两次
- "延迟"——第二次删除有延迟
- 延迟多久？为什么要延迟？

📖 参考答案：

**延迟双删流程**：

```
写操作的步骤：
1. 删除缓存（第一次删除）
2. 更新数据库
3. 等待一小段时间（如500ms）
4. 再次删除缓存（第二次删除）
```

**为什么有效？**

```
请求A（写 price=200）              请求B（读，缓存miss）
──────────────────               ──────────────────
1. 删除缓存                        
                                  2. 缓存未命中
                                  3. 读DB → price=100（旧值）
4. 更新DB price=200
                                  5. 将旧值写入缓存 price=100
--- 延迟 500ms ---
6. 再次删除缓存                    
                                  （缓存被清除了！）
                                  下次读取 → 从DB读到200 → 正确值
```

第二次删除清掉了请求B可能写入的脏数据。**延迟时间须大于"一次读DB+写缓存"的耗时**。

**延迟时间怎么定？**

```
延迟 = 一次读DB的平均耗时 + 一次写缓存的平均耗时 + 安全余量
     ≈ 50ms + 5ms + 200ms
     ≈ 300-500ms（保守值）

太短：可能还没覆盖到脏数据写入
太长：不一致窗口更大，且阻塞写操作（如果同步等待）
```

---

**问题4：延迟双删的"延迟"怎么实现？直接 `time.Sleep` 吗？**

💭 思考方向：
- Sleep会阻塞当前goroutine
- 接口响应延迟增加500ms用户能接受吗？
- 有没有异步方案？

📖 参考答案：

**方案对比**：

| 方案 | 实现 | 优点 | 缺点 |
|------|------|------|------|
| **同步Sleep** | `time.Sleep(500ms)` | 简单 | 阻塞接口，响应变慢 |
| **异步goroutine** | `go delayedDelete()` | 不阻塞 | 进程重启则丢失 |
| **延迟队列** | Redis延迟队列/MQ | 可靠 | 系统复杂度高 |
| **定时任务** | 定时扫描删除 | 简单可靠 | 不一致窗口更大 |

**推荐：异步goroutine（大部分场景够用）**

```go
func UpdateUser(db *sql.DB, rdb *redis.Client, user User) error {
    key := fmt.Sprintf("user:%s", user.ID)
    
    // 1. 第一次删除缓存
    rdb.Del(ctx, key)
    
    // 2. 更新数据库
    if err := updateDB(db, user); err != nil {
        return err
    }
    
    // 3. 异步延迟双删（不阻塞当前请求）
    go func() {
        time.Sleep(500 * time.Millisecond)
        rdb.Del(ctx, key)
    }()
    
    return nil
}
```

**高可靠场景：用消息队列**

```go
func UpdateUser(db *sql.DB, rdb *redis.Client, mq *MessageQueue, user User) error {
    key := fmt.Sprintf("user:%s", user.ID)
    
    rdb.Del(ctx, key)
    
    if err := updateDB(db, user); err != nil {
        return err
    }
    
    // 发送延迟消息到MQ，即使进程重启也能保证执行
    mq.SendDelayMessage(DeleteCacheMessage{Key: key}, 500*time.Millisecond)
    
    return nil
}
```

---

**问题5：实际工程中，Cache-Aside + 延迟双删 够用吗？还需要什么补充？**

💭 思考方向：
- TTL（缓存过期时间）的作用
- 如果应用重启，延迟删除丢了怎么办？
- 缓存击穿怎么防？

📖 参考答案：

**完整的缓存一致性策略（生产级）**：

```
基础方案：Cache-Aside + TTL
    │
    ├─ +延迟双删 → 缩小并发不一致窗口
    │
    ├─ +TTL兜底 → 即使双删失败，TTL过期后也会修正
    │   （TTL设置：热点数据5-10分钟，一般数据30-60分钟）
    │
    ├─ +缓存击穿防护 → singleflight/互斥锁防止大量穿透
    │
    ├─ +缓存穿透防护 → 空值缓存/布隆过滤器防止不存在的key
    │
    └─ +监控告警 → 缓存命中率、DB QPS、不一致次数
```

```go
// singleflight防止缓存击穿
var group singleflight.Group

func GetUser(id string) (*User, error) {
    key := "user:" + id
    
    // 查缓存
    if val, err := rdb.Get(ctx, key).Result(); err == nil {
        return decodeUser(val)
    }
    
    // singleflight：相同key只有一个goroutine去查DB
    result, err, _ := group.Do(key, func() (interface{}, error) {
        user, err := queryDB(id)
        if err != nil {
            return nil, err
        }
        // 写入缓存，设置TTL
        rdb.Set(ctx, key, encodeUser(user), 10*time.Minute)
        return user, nil
    })
    
    if err != nil {
        return nil, err
    }
    return result.(*User), nil
}
```

## 小结

⭐ **核心要点**：
1. **Cache-Aside**：读时回填、写时删除，是最通用的缓存模式
2. **延迟双删**：两次删除+延迟，缩小并发不一致窗口，延迟时间 > 一次读DB+写缓存的耗时
3. **生产级方案**：Cache-Aside + 延迟双删 + TTL兜底 + singleflight防击穿

## 关联阅读

- **前置**：[问题空间](00-problem-space.md)（为什么会不一致）
- **深入**：[写策略](02-write-strategies.md)（Write-Through/Write-Back对比）
- **深入**：[Go实现](04-go-implementation.md)（完整的Go代码实现）
- **理论**：[一致性模型](../../theory/02-consistency-models.md)（最终一致性的理论基础）
