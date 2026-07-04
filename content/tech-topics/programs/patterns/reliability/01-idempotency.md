# 幂等性设计

---
前置知识: 无
难度: ⭐⭐⭐
预计时间: 45分钟
关键词: 幂等, idempotency, token, 去重, 重试安全, 唯一键
---

## 引入场景

用户点击"支付"按钮，网络卡了一下，用户又点了一次。你的支付接口被调用了两次。如果没有幂等设计，用户会被扣两次钱。

更隐蔽的场景：你的服务调用下游接口超时，重试机制自动重试——下游执行了两次。

**幂等性**就是为了解决这类问题：**无论操作执行一次还是多次，结果都是一样的。**

## 对话探索

**问题1：哪些操作天然幂等？哪些不是？**

💭 思考方向：
- `SELECT * FROM users WHERE id=1`
- `UPDATE users SET name='Alice' WHERE id=1`
- `UPDATE users SET balance = balance - 100 WHERE id=1`
- `INSERT INTO orders (id, amount) VALUES (123, 100)`

📖 参考答案：

| 操作 | 幂等？ | 原因 |
|------|--------|------|
| `GET /users/1` | ✅ 是 | 查询不改变状态 |
| `SET name='Alice'` | ✅ 是 | 设置固定值，执行多次结果一样 |
| `DELETE FROM users WHERE id=1` | ✅ 是 | 删一次和删一百次，最终都是没了 |
| `balance = balance - 100` | ❌ 否 | 每次执行都会扣100 |
| `INSERT INTO orders VALUES(...)` | ❌ 否 | 每次执行都会新增一条记录 |
| `counter++` | ❌ 否 | 每次执行计数器都增加 |

**判断标准**：`f(x) = f(f(x))`——执行一次和执行多次的最终状态相同。

---

**问题2：如何让"扣减余额"这种非幂等操作变成幂等的？**

💭 思考方向：
- 给每次操作一个唯一标识
- 记录已处理过的操作
- 重复的操作直接返回之前的结果

📖 参考答案：

**核心思路**：用唯一标识（幂等键）去重。

```
方案1：基于唯一请求ID

客户端 → 生成 requestID（如UUID）→ 发送请求
服务端：
  1. 检查 requestID 是否已处理
  2. 未处理 → 执行业务 → 记录 requestID + 结果
  3. 已处理 → 直接返回之前的结果
```

```go
func DeductBalance(ctx context.Context, db *sql.DB, requestID string, userID string, amount int) error {
    // 步骤1：检查是否已处理
    var exists bool
    err := db.QueryRowContext(ctx,
        "SELECT EXISTS(SELECT 1 FROM idempotency_keys WHERE request_id = ?)",
        requestID).Scan(&exists)
    if err != nil {
        return err
    }
    if exists {
        return nil // 已处理，直接返回
    }

    // 步骤2：在事务中执行业务 + 记录幂等键
    tx, _ := db.BeginTx(ctx, nil)
    defer tx.Rollback()

    // 扣减余额
    result, err := tx.ExecContext(ctx,
        "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
        amount, userID, amount)
    if err != nil {
        return err
    }
    affected, _ := result.RowsAffected()
    if affected == 0 {
        return errors.New("insufficient balance")
    }

    // 记录幂等键
    _, err = tx.ExecContext(ctx,
        "INSERT INTO idempotency_keys (request_id, created_at) VALUES (?, NOW())",
        requestID)
    if err != nil {
        return err // 唯一键冲突说明并发重复，事务回滚
    }

    return tx.Commit()
}
```

---

**问题3：幂等键应该存在哪里？有哪些方案？**

💭 思考方向：
- 数据库？Redis？内存？
- 幂等键需要保留多久？
- 和业务操作要在同一个事务里吗？

📖 参考答案：

| 方案 | 存储 | 优点 | 缺点 |
|------|------|------|------|
| **数据库唯一键** | MySQL | 和业务在同一事务，强一致 | 增加DB压力 |
| **Redis去重** | Redis | 性能高，天然支持TTL | 和DB不在同一事务 |
| **数据库唯一索引** | MySQL | 简单，INSERT自动去重 | 只适用于INSERT场景 |

**方案1：数据库幂等表**（推荐，最可靠）

```sql
CREATE TABLE idempotency_keys (
    request_id VARCHAR(64) PRIMARY KEY,
    response   TEXT,        -- 缓存响应结果
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_created (created_at)  -- 用于定期清理
);
```

**方案2：Redis去重**（高性能，适合非关键操作）

```go
func IsProcessed(ctx context.Context, rdb *redis.Client, requestID string) (bool, error) {
    // SET NX，设置成功说明是首次处理
    ok, err := rdb.SetNX(ctx, "idem:"+requestID, "1", 24*time.Hour).Result()
    return !ok, err // ok=false表示key已存在（已处理过）
}
```

**方案3：数据库唯一索引**（对INSERT天然幂等）

```sql
-- 订单表有唯一索引
CREATE UNIQUE INDEX uk_order_no ON orders(order_no);

-- INSERT时如果order_no重复，会报唯一键冲突
INSERT INTO orders (order_no, amount) VALUES ('ORD-001', 100);
-- 重复执行 → 报错 → 捕获错误，返回成功
```

```go
func CreateOrder(ctx context.Context, db *sql.DB, orderNo string, amount int) error {
    _, err := db.ExecContext(ctx,
        "INSERT INTO orders (order_no, amount) VALUES (?, ?)",
        orderNo, amount)
    if err != nil {
        if isDuplicateKeyError(err) {
            return nil // 重复订单，视为成功
        }
        return err
    }
    return nil
}
```

---

**问题4：HTTP接口如何设计幂等？不同HTTP方法有什么区别？**

💭 思考方向：
- GET、PUT、DELETE按规范本身应该是幂等的
- POST呢？
- 幂等键放在header还是body？

📖 参考答案：

**HTTP方法的幂等性规范**：

| 方法 | 幂等？ | 说明 |
|------|--------|------|
| GET | ✅ | 查询，不改变状态 |
| PUT | ✅ | 替换资源（同一个资源PUT多次结果一样） |
| DELETE | ✅ | 删除资源（删多次结果一样） |
| POST | ❌ | 创建资源/触发操作（每次可能创建新记录） |
| PATCH | ❌ | 部分更新（如 `balance += 100` 不幂等） |

**让POST接口幂等**：

```
方案：客户端生成幂等键，放在HTTP Header中

客户端：
  POST /api/payments
  Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
  Body: {"amount": 100, "user_id": "user-001"}

服务端：
  1. 检查 Idempotency-Key 是否已处理
  2. 已处理 → 返回缓存的响应（同样的状态码和body）
  3. 未处理 → 执行支付 → 缓存响应 → 返回
```

```go
// 中间件：通用幂等处理
func IdempotencyMiddleware(rdb *redis.Client) gin.HandlerFunc {
    return func(c *gin.Context) {
        key := c.GetHeader("Idempotency-Key")
        if key == "" {
            c.Next() // 没有幂等键，正常处理
            return
        }

        idempKey := "idem:" + key

        // 检查是否已处理
        cached, err := rdb.Get(c, idempKey).Result()
        if err == nil {
            // 已处理，返回缓存的响应
            c.Data(200, "application/json", []byte(cached))
            c.Abort()
            return
        }

        // 执行业务逻辑
        c.Next()

        // 缓存响应（24小时后自动清理）
        if c.Writer.Status() >= 200 && c.Writer.Status() < 300 {
            // 注意：这里需要interceptor来捕获响应body
            rdb.Set(c, idempKey, responseBody, 24*time.Hour)
        }
    }
}
```

---

**问题5：幂等和分布式锁有什么关系？需要一起用吗？**

💭 思考方向：
- 幂等解决的是"重复执行"问题
- 分布式锁解决的是"并发执行"问题
- 如果两个相同的请求同时到达？

📖 参考答案：

```
重复请求的两种场景：

1. 串行重复（幂等性解决）
   请求A到达 → 处理完成 → 请求A重试到达 → 检测到已处理 → 返回缓存结果

2. 并发重复（需要幂等+锁配合）
   请求A到达 ──→ 检查幂等键（不存在）──→ 执行业务
   请求A重试  ──→ 检查幂等键（不存在！还没记录）──→ 也执行业务 → 重复！
```

**解决并发重复的方案**：

```go
// 方案1：数据库唯一索引（最推荐）
// INSERT同一个幂等键时，数据库保证只有一个成功
_, err := tx.Exec("INSERT INTO idempotency_keys (request_id) VALUES (?)", requestID)
if isDuplicateKeyError(err) {
    return nil // 并发重复，另一个事务已经在处理
}

// 方案2：Redis + 分布式锁
func ProcessWithLock(ctx context.Context, rdb *redis.Client, requestID string) error {
    // 先用分布式锁防止并发
    lock := NewRedisLock(rdb, "lock:"+requestID, 10*time.Second)
    if err := lock.Lock(ctx); err != nil {
        return err
    }
    defer lock.Unlock(ctx)

    // 再检查幂等键
    if processed, _ := IsProcessed(ctx, rdb, requestID); processed {
        return nil
    }

    // 执行业务...
    return nil
}
```

**实际建议**：
- 数据库唯一索引/唯一键是最简单有效的方案
- 只有Redis去重方案才需要配合分布式锁
- 大部分场景用数据库事务+唯一索引就够了

## 小结

⭐ **核心要点**：
1. **幂等 = 执行一次和多次结果相同**，核心实现是"唯一标识 + 去重存储"
2. **三种主要方案**：数据库幂等表（最可靠）、Redis去重（高性能）、唯一索引（最简单）
3. **幂等和分布式锁互补**：幂等防重复执行，锁防并发执行，关键操作两者配合使用

## 关联阅读

- **相关**：[分布式锁](../concurrency-control/03-distributed-lock.md)（并发控制）
- **相关**：[缓存一致性](../consistency/01-cache-aside.md)（缓存更新也需要考虑幂等）
- **理论**：[一致性模型](../../theory/02-consistency-models.md)（幂等是实现最终一致性的关键手段）
