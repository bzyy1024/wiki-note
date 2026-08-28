# Go实现：Redis缓存方案

---
前置知识: [01-cache-aside.md, 02-write-strategies.md]
难度: ⭐⭐⭐
预计时间: 45分钟
关键词: Go, Redis, go-redis, singleflight, 缓存封装, 延迟双删实现
---

## 引入场景

前面三篇我们学了缓存一致性的理论和模式。现在把这些知识落地——用Go实现一个生产级的Redis缓存方案，包含Cache-Aside、延迟双删、击穿防护、穿透防护。

## 完整实现

### 1. 核心缓存层封装

```go
package cache

import (
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "math/rand"
    "sync"
    "time"

    "github.com/redis/go-redis/v9"
    "golang.org/x/sync/singleflight"
)

var (
    ErrNotFound  = errors.New("cache: not found")
    ErrNullValue = errors.New("cache: null value cached")
)

// nullValue 用于缓存空值，防止缓存穿透
const nullValue = "__NULL__"

// Cache 封装了Cache-Aside模式的完整实现
type Cache struct {
    rdb          *redis.Client
    sfGroup      singleflight.Group
    defaultTTL   time.Duration
    nullTTL      time.Duration       // 空值缓存TTL（防穿透）
    jitterRange  time.Duration       // TTL随机偏移范围（防雪崩）
    mu           sync.Mutex          // 用于需要互斥的场景
}

// NewCache 创建缓存实例
func NewCache(rdb *redis.Client, opts ...Option) *Cache {
    c := &Cache{
        rdb:         rdb,
        defaultTTL:  10 * time.Minute,
        nullTTL:     1 * time.Minute,
        jitterRange: 60 * time.Second,
    }
    for _, opt := range opts {
        opt(c)
    }
    return c
}

// Option 配置选项
type Option func(*Cache)

func WithDefaultTTL(ttl time.Duration) Option {
    return func(c *Cache) { c.defaultTTL = ttl }
}

func WithNullTTL(ttl time.Duration) Option {
    return func(c *Cache) { c.nullTTL = ttl }
}

func WithJitterRange(d time.Duration) Option {
    return func(c *Cache) { c.jitterRange = d }
}
```

### 2. Cache-Aside 读操作（含防击穿、防穿透）

```go
// LoadFunc 定义从数据源加载数据的函数
type LoadFunc func(ctx context.Context) (interface{}, error)

// Get 实现Cache-Aside读操作
// 1. 查缓存 → 命中则返回
// 2. singleflight防止缓存击穿
// 3. 从DB加载 → 写入缓存
// 4. 空值缓存防止穿透
func (c *Cache) Get(ctx context.Context, key string, dest interface{}, loader LoadFunc) error {
    // 第一步：查缓存
    val, err := c.rdb.Get(ctx, key).Result()
    if err == nil {
        // 检查是否是空值缓存
        if val == nullValue {
            return ErrNotFound
        }
        return json.Unmarshal([]byte(val), dest)
    }
    if !errors.Is(err, redis.Nil) {
        // Redis出错，降级直接查DB
        return c.loadAndCache(ctx, key, dest, loader)
    }

    // 第二步：缓存未命中，使用singleflight防止击穿
    result, err, _ := c.sfGroup.Do(key, func() (interface{}, error) {
        // 双重检查：可能在等待时已被其他goroutine加载
        val, err := c.rdb.Get(ctx, key).Result()
        if err == nil {
            if val == nullValue {
                return nil, ErrNotFound
            }
            return []byte(val), nil
        }

        return c.doLoadAndCache(ctx, key, loader)
    })

    if err != nil {
        return err
    }

    return json.Unmarshal(result.([]byte), dest)
}

func (c *Cache) doLoadAndCache(ctx context.Context, key string, loader LoadFunc) ([]byte, error) {
    // 从数据源加载
    data, err := loader(ctx)
    if errors.Is(err, ErrNotFound) {
        // 数据不存在 → 缓存空值防止穿透
        c.rdb.Set(ctx, key, nullValue, c.nullTTL)
        return nil, ErrNotFound
    }
    if err != nil {
        return nil, fmt.Errorf("cache: loader failed: %w", err)
    }

    // 序列化并写入缓存
    bytes, err := json.Marshal(data)
    if err != nil {
        return nil, fmt.Errorf("cache: marshal failed: %w", err)
    }

    // TTL加随机偏移，防止雪崩
    ttl := c.defaultTTL + time.Duration(rand.Int63n(int64(c.jitterRange)))
    c.rdb.Set(ctx, key, string(bytes), ttl)

    return bytes, nil
}

func (c *Cache) loadAndCache(ctx context.Context, key string, dest interface{}, loader LoadFunc) error {
    bytes, err := c.doLoadAndCache(ctx, key, loader)
    if err != nil {
        return err
    }
    return json.Unmarshal(bytes, dest)
}
```

### 3. Cache-Aside 写操作（延迟双删）

```go
// UpdateFunc 定义更新数据源的函数
type UpdateFunc func(ctx context.Context) error

// Update 实现Cache-Aside写操作（带延迟双删）
// 1. 删除缓存（第一次）
// 2. 更新数据库
// 3. 异步延迟后再次删除缓存（第二次）
func (c *Cache) Update(ctx context.Context, key string, updater UpdateFunc) error {
    // 第一次删除缓存
    c.rdb.Del(ctx, key)

    // 更新数据库
    if err := updater(ctx); err != nil {
        return err
    }

    // 异步延迟双删
    go c.delayedDelete(key, 500*time.Millisecond)

    return nil
}

// UpdateSync 同步版延迟双删（用于对一致性要求更高的场景）
func (c *Cache) UpdateSync(ctx context.Context, key string, updater UpdateFunc, delay time.Duration) error {
    c.rdb.Del(ctx, key)

    if err := updater(ctx); err != nil {
        return err
    }

    // 同步等待后删除（会增加接口延迟）
    time.Sleep(delay)
    c.rdb.Del(ctx, key)

    return nil
}

func (c *Cache) delayedDelete(key string, delay time.Duration) {
    time.Sleep(delay)
    // 使用新的context，因为原始请求可能已结束
    ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
    defer cancel()
    c.rdb.Del(ctx, key)
}

// Delete 直接删除缓存
func (c *Cache) Delete(ctx context.Context, keys ...string) error {
    if len(keys) == 0 {
        return nil
    }
    return c.rdb.Del(ctx, keys...).Err()
}
```

### 4. 使用示例

```go
package main

import (
    "context"
    "database/sql"
    "fmt"
    "log"

    "github.com/redis/go-redis/v9"
    // "yourproject/cache"
)

type User struct {
    ID    string `json:"id"`
    Name  string `json:"name"`
    Email string `json:"email"`
}

type UserService struct {
    db    *sql.DB
    cache *Cache // 上面定义的Cache
}

// GetUser 演示Cache-Aside读操作
func (s *UserService) GetUser(ctx context.Context, id string) (*User, error) {
    var user User
    key := fmt.Sprintf("user:%s", id)

    err := s.cache.Get(ctx, key, &user, func(ctx context.Context) (interface{}, error) {
        // 这个函数只在缓存未命中时调用
        row := s.db.QueryRowContext(ctx,
            "SELECT id, name, email FROM users WHERE id = ?", id)
        
        var u User
        if err := row.Scan(&u.ID, &u.Name, &u.Email); err != nil {
            if err == sql.ErrNoRows {
                return nil, ErrNotFound
            }
            return nil, err
        }
        return &u, nil
    })

    if err != nil {
        return nil, err
    }
    return &user, nil
}

// UpdateUser 演示Cache-Aside写操作（延迟双删）
func (s *UserService) UpdateUser(ctx context.Context, user User) error {
    key := fmt.Sprintf("user:%s", user.ID)

    return s.cache.Update(ctx, key, func(ctx context.Context) error {
        _, err := s.db.ExecContext(ctx,
            "UPDATE users SET name = ?, email = ? WHERE id = ?",
            user.Name, user.Email, user.ID)
        return err
    })
}

func main() {
    rdb := redis.NewClient(&redis.Options{
        Addr: "localhost:6379",
    })

    // 创建缓存实例
    c := NewCache(rdb,
        WithDefaultTTL(10*time.Minute),
        WithNullTTL(1*time.Minute),
        WithJitterRange(60*time.Second),
    )

    svc := &UserService{
        // db:    db,
        cache: c,
    }

    ctx := context.Background()

    // 读取用户（第一次从DB加载并缓存）
    user, err := svc.GetUser(ctx, "user-001")
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("User: %+v\n", user)

    // 更新用户（延迟双删）
    err = svc.UpdateUser(ctx, User{
        ID:    "user-001",
        Name:  "New Name",
        Email: "new@example.com",
    })
    if err != nil {
        log.Fatal(err)
    }
    fmt.Println("User updated with delayed double delete")
}
```

## 对话探索

**问题1：为什么用 `singleflight` 而不是分布式锁来防击穿？**

💭 思考方向：
- singleflight是进程内的
- 如果有100个Pod呢？
- 权衡复杂度和效果

📖 参考答案：

| | singleflight | 分布式锁 |
|---|-------------|---------|
| **范围** | 进程内去重 | 全局去重 |
| **效果** | 100 Pod = 最多100个并发查DB | 全局只有1个查DB |
| **复杂度** | 低（一行代码） | 高（锁续期、超时、重试） |
| **失败影响** | 无（最多多查几次DB） | 锁没释放→阻塞所有请求 |

**实际选择**：大多数场景singleflight够用。100个Pod同时查一条数据的概率低，且DB通常能承受。只有极端热点key（如秒杀商品）才需要分布式锁。

---

**问题2：延迟双删的500ms怎么定？不同场景不同吗？**

📖 参考答案：

```
延迟 = 一次读DB耗时（P99）+ 一次写Redis耗时 + 安全余量

场景举例：
  一般业务：DB P99 = 50ms, Redis = 5ms → 延迟 300-500ms
  复杂查询：DB P99 = 200ms → 延迟 500ms-1s
  读写分离：还要加上主从复制延迟 → 可能需要 1-2s
```

---

**问题3：这个方案的局限性是什么？**

📖 参考答案：

1. **异步双删不可靠**：进程崩溃就丢了 → 需要TTL兜底
2. **不能保证强一致性**：仍有短暂不一致窗口
3. **序列化开销**：JSON序列化有CPU开销 → 热点数据可考虑protobuf
4. **Redis不可用时**：需要降级策略（直连DB、本地缓存）

## 小结

⭐ **核心要点**：
1. **封装Cache-Aside**：统一的Get/Update接口，内置singleflight/空值缓存/TTL随机化
2. **延迟双删实现**：异步goroutine + 新context，注意延迟时间要大于读DB+写缓存耗时
3. **生产级需要**：降级策略、监控metrics、合理的TTL设置

## 关联阅读

- **前置**：[Cache-Aside理论](01-cache-aside.md)、[写策略](02-write-strategies.md)
- **相关**：[分布式缓存](03-distributed-cache.md)（集群场景下的一致性）
- **相关**：[分布式锁](../concurrency-control/03-distributed-lock.md)（极端热点场景）
- **理论**：[一致性模型](../../theory/02-consistency-models.md)（最终一致性的理论基础）
