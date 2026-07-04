# 模式：Write-Through 与 Write-Back

---
前置知识: [01-cache-aside.md]
难度: ⭐⭐⭐
预计时间: 40分钟
关键词: Write-Through, Write-Back, Write-Behind, Read-Through, 缓存策略
---

## 引入场景

Cache-Aside需要应用程序自己管理缓存更新逻辑——读的时候手动回填，写的时候手动删除。有没有更"自动"的方案？让缓存层透明地处理数据同步？

事实上，CPU缓存（L1/L2/L3）就面临同样的问题，而它使用了Write-Through和Write-Back策略。这些策略在应用层缓存中也有对应。

## 对话探索

**问题1：什么是Write-Through？它和Cache-Aside有什么区别？**

💭 思考方向：
- "Through"是"穿过"的意思——写入穿过缓存直达DB
- 应用程序只和缓存交互，还是和两者都交互？
- 这样做数据一致性如何？

📖 参考答案：

**Write-Through = 写穿透**：每次写操作同时更新缓存和DB。

```
Cache-Aside（旁路）：               Write-Through（写穿透）：

应用程序 ─→ 更新DB                应用程序 ─→ 缓存层
         ─→ 删缓存                          │
    （应用管理两者）                缓存层 ─→ 同步写入DB
                                            │
                                  两者同时更新完才返回
```

**Write-Through流程**：

```
写操作：
  应用 → 缓存层 → 同时更新缓存 + 同步写入DB → 成功后返回
  
读操作（通常配合Read-Through）：
  应用 → 缓存层 → 命中返回 / 未命中从DB加载并缓存
```

| 特性 | Cache-Aside | Write-Through |
|------|-------------|---------------|
| **谁管理缓存** | 应用程序 | 缓存层（中间件/代理） |
| **写操作** | 写DB+删缓存 | 写缓存层→缓存层同步写DB |
| **一致性** | 可能有短暂不一致 | 强一致（同步写两者） |
| **写延迟** | 一次DB写入 | 一次缓存写入+一次DB写入 |
| **实现复杂度** | 应用层逻辑 | 需要缓存中间件支持 |

**优点**：数据始终一致（同步写入两者）
**缺点**：写延迟高（每次写都要等DB确认），对于写多读少的场景性能差

---

**问题2：什么是Write-Back（Write-Behind）？它如何提升写性能？**

💭 思考方向：
- "Back"是"回"的意思——先写缓存，稍后"回写"DB
- 写操作只需等缓存写入完成
- 如果缓存在回写前崩溃了？

📖 参考答案：

**Write-Back = 写回**：写操作只更新缓存，稍后异步批量写入DB。

```
Write-Through（同步）：            Write-Back（异步）：

写请求 → 更新缓存                 写请求 → 更新缓存 → 立即返回
       → 同步写DB                         │
       → 返回（等两步都完成）              后台异步回写DB
                                          （批量、定时）
```

**Write-Back流程**：

```
写操作：
  应用 → 写入缓存 → 标记为"脏数据" → 立即返回（不等DB）

后台回写线程：
  定时/定量 → 收集脏数据 → 批量写入DB → 清除脏标记
```

**性能对比**：

```
场景：1秒内对同一条数据修改10次

Write-Through: 10次缓存写入 + 10次DB写入 = 20次IO
Write-Back:    10次缓存写入 + 1次DB写入  = 11次IO（只回写最终值）
```

**风险**：缓存崩溃时，未回写的数据会丢失！

| 特性 | Write-Through | Write-Back |
|------|---------------|------------|
| **写延迟** | 高（等DB） | 低（只写缓存） |
| **数据安全** | 高（同步写DB） | 低（缓存崩溃可能丢数据） |
| **DB压力** | 高（每次写都到DB） | 低（批量回写） |
| **适用场景** | 数据不能丢的场景 | 写多的场景，允许少量丢失 |

---

**问题3：Read-Through是什么？它和Cache-Aside的读流程有什么区别？**

💭 思考方向：
- Cache-Aside的读：应用自己查缓存、查DB、回填缓存
- Read-Through：缓存层自动处理miss
- 对应用程序来说有什么变化？

📖 参考答案：

**Read-Through = 读穿透**：缓存未命中时，缓存层自动从DB加载。

```
Cache-Aside读：                    Read-Through读：

应用 → 查缓存                     应用 → 查缓存层
miss → 应用查DB                   miss → 缓存层自动查DB
     → 应用写缓存                      → 缓存层自动缓存
     → 返回                            → 返回
   （应用管理miss逻辑）              （缓存层管理miss逻辑）
```

**本质区别**：加载数据的职责在哪里。

- **Cache-Aside**：应用负责（灵活但重复）
- **Read-Through**：缓存层负责（封装好但需要中间件支持）

```go
// Cache-Aside（应用层管理）
func GetUser(id string) (*User, error) {
    // 应用自己管理缓存逻辑
    val, err := rdb.Get(ctx, "user:"+id).Result()
    if err == redis.Nil {
        user, _ := db.QueryUser(id)
        rdb.Set(ctx, "user:"+id, encode(user), 10*time.Minute)
        return user, nil
    }
    return decode(val), nil
}

// Read-Through（缓存层管理）
func GetUser(id string) (*User, error) {
    // 缓存层自动处理miss（如LocalCache、Guava Cache）
    return cache.Get("user:"+id)
    // 内部：miss时自动调用loader函数查DB并缓存
}
```

---

**问题4：CPU缓存用的是哪种策略？和应用层缓存有什么联系？**

💭 思考方向：
- CPU的L1/L2/L3缓存
- 写一个变量时，是Write-Through还是Write-Back？
- MESI协议

📖 参考答案：

**CPU缓存通常使用Write-Back**：

```
CPU写入变量 x = 42：
1. 只更新L1缓存中的x → 标记这个缓存行为"Modified"
2. 不立即写回内存
3. 当缓存行被替换（evict）时，才将修改写回内存
```

原因：CPU需要极致性能，不能每次写都等内存（内存延迟~100ns vs 缓存~1ns）。

**从CPU到应用的类比**：

| | CPU缓存 | 应用缓存（Redis） |
|---|---------|------------------|
| **缓存** | L1/L2/L3 | Redis |
| **后端存储** | 主内存 | MySQL |
| **通常策略** | Write-Back | Cache-Aside |
| **一致性协议** | MESI | 延迟双删/TTL |
| **不一致原因** | 多核各有自己的缓存 | 多实例各自操作 |

**相似的本质**：无论是CPU缓存还是Redis缓存，核心挑战都是**在性能和一致性之间权衡**。

---

**问题5：实际项目中应该选哪种策略？**

💭 思考方向：
- 读多写少？写多读少？
- 能否容忍数据丢失？
- 系统复杂度预算？

📖 参考答案：

**决策树**：

```
你的场景是？
│
├─ 读多写少（绝大多数Web应用）
│   └─ ✅ Cache-Aside + TTL + 延迟双删
│       简单、灵活、够用
│
├─ 写多，且不能丢数据
│   └─ ✅ Write-Through
│       一致性好，但写性能受限
│
├─ 写非常多，且允许少量丢失
│   └─ ✅ Write-Back
│       写性能最好，但有数据丢失风险
│
└─ 想要封装缓存逻辑
    └─ ✅ Read-Through（配合上面的写策略）
        应用代码更简洁
```

**实际上**：绝大多数Go后端项目使用 **Cache-Aside**，因为：
1. 实现简单，不需要特殊中间件
2. Go标准库+Redis客户端就能实现
3. 大多数场景是读多写少
4. 配合TTL和延迟双删，不一致窗口可控

## 小结

⭐ **核心要点**：
1. **Write-Through（写穿透）**：同步写缓存+DB，一致性好但写延迟高
2. **Write-Back（写回）**：只写缓存异步回写DB，性能好但可能丢数据
3. **实战选择**：大多数Web场景用Cache-Aside就够了，复杂策略按需引入

## 关联阅读

- **前置**：[Cache-Aside与延迟双删](01-cache-aside.md)
- **深入**：[分布式缓存一致性](03-distributed-cache.md)（多节点Redis的一致性）
- **深入**：[Go实现](04-go-implementation.md)（完整代码）
- **基础**：虚拟内存中的CPU缓存也使用Write-Back策略
