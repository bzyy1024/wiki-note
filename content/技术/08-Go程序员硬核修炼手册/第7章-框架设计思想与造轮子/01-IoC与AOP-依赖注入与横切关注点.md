# 01 · IoC 与 AOP：依赖注入与横切关注点

> *"控制反转不是'把 new 换成注解'，它是一种关于'谁负责组装'的哲学。"*

---

## 开场：一个"简单"的重构

> **小林**：我看 Spring 的 IoC，感觉就是把 `new UserService()` 改成 `@Autowired`。这有什么意义？
>
> **老陈**：**你先回答我：下面这段 Go 代码有什么问题？**
>
> ```go
> type OrderService struct {
>     db      *sql.DB
>     cache   *redis.Client
>     mq      *kafka.Producer
>     logger  *zap.Logger
>     metrics *prometheus.Registry
> }
>
> func NewOrderService() (*OrderService, error) {
>     db, _ := sql.Open("mysql", "user:pass@/orders")
>     cache := redis.NewClient(&redis.Options{Addr: "localhost:6379"})
>     mq, _ := kafka.NewProducer(...)
>     logger, _ := zap.NewProduction()
>     return &OrderService{db, cache, mq, logger, prometheus.NewRegistry()}, nil
> }
> ```
>
> **小林**：……耦合太紧？
>
> **老陈**：**具体点。我要测试 `OrderService.CreateOrder()` 的业务逻辑，你要怎么做？**
>
> **小林**：……启动一个数据库？
>
> **老陈**：**还有 Redis、Kafka。你愿意为了跑一个单元测试起三个中间件吗？**
>
> **小林**：……不愿意。所以要用 mock。
>
> **老陈**：**那你改给我看。**
>
> **小林**：（改）
> ```go
> func NewOrderService(db *sql.DB, cache *redis.Client, mq *kafka.Producer, ...) *OrderService
> ```
> **这样就可测了。**
>
> **老陈**：**对。你已经理解了依赖注入的核心。** 现在我问你：**如果依赖有 20 个呢？如果依赖之间还有依赖关系呢？谁来负责组装这个依赖图？**
>
> **小林**：……所以这就是 IoC 容器要解决的问题？

---

## 第一部分：IoC 与 DI

### 概念澄清

| 概念 | 定义 | 一句话 |
|:---|:---|:---|
| **IoC (Inversion of Control)** | 控制反转 | **谁来调用谁**的反转 |
| **DI (Dependency Injection)** | 依赖注入 | IoC 的一种**实现方式** |
| **DIP (Dependency Inversion Principle)** | 依赖倒置原则 | 依赖抽象，不依赖具体 |

**关系：**
```
IoC 是思想（"框架调用你"）
  ↓ 实现方式之一
DI 是技术（"依赖从外部传入"）
  ↓ 遵循的原则
DIP 是设计原则（"依赖接口"）
```

**三种注入方式：**

```go
// ① 构造函数注入（★ Go 的标准做法，Spring 也推荐）
func NewOrderService(db DB, cache Cache) *OrderService {
	return &OrderService{db: db, cache: cache}
}

// ② Setter 注入
type OrderService struct {
	db DB
}
func (s *OrderService) SetDB(db DB) { s.db = db }

// ③ 字段注入（Spring 的 @Autowired，Go 里做不到，因为没有注解）
type OrderService struct {
	DB DB `inject:""`   // ★ 这个 tag 需要框架用反射处理
}
```

> **老陈**：**Go 几乎只用 ①。为什么？**
>
> **因为 Go 没有注解，字段注入要靠反射 + struct tag——这很"魔法"，而且失去了编译期检查。**
>
> **构造函数注入的好处：**
> - **编译期检查**：参数类型不对，编译不过
> - **不可变**：依赖在构造后不能再改（可以设为私有字段）
> - **明确**：看构造函数签名就知道依赖什么
> - **易测试**：直接传 mock

### ★ 手写 DI 容器（反射版）

现在实现一个类似 `dig` 的运行时 DI 容器。

```go
package main

import (
	"fmt"
	"reflect"
	"sync"
)

// ============ 容器 ============

type Container struct {
	mu sync.RWMutex

	// 类型 → 构造函数
	providers map[reflect.Type]*provider

	// 类型 → 已构造的实例（单例缓存）
	instances map[reflect.Type]reflect.Value

	// 正在构造中的类型（用于循环依赖检测）
	constructing map[reflect.Type]bool
}

type provider struct {
	ctor      reflect.Value   // 构造函数
	params    []reflect.Type  // 依赖的参数类型
	returns   []reflect.Type  // 返回的类型
	hasError  bool            // 是否返回 error
	isSingleton bool
}

func NewContainer() *Container {
	return &Container{
		providers:    make(map[reflect.Type]*provider),
		instances:    make(map[reflect.Type]reflect.Value),
		constructing: make(map[reflect.Type]bool),
	}
}

// Provide 注册一个构造函数
// ctor 的形式: func(dep1 T1, dep2 T2, ...) (T, error) 或者 func(...) T
func (c *Container) Provide(ctor interface{}, opts ...Option) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	ctorType := reflect.TypeOf(ctor)
	if ctorType.Kind() != reflect.Func {
		return fmt.Errorf("构造函数必须是一个函数，实际是 %v", ctorType.Kind())
	}

	p := &provider{
		ctor:        reflect.ValueOf(ctor),
		isSingleton: true,   // 默认单例
	}

	// 解析参数
	for i := 0; i < ctorType.NumIn(); i++ {
		p.params = append(p.params, ctorType.In(i))
	}

	// 解析返回值
	switch ctorType.NumOut() {
	case 1:
		p.returns = append(p.returns, ctorType.Out(0))
	case 2:
		p.returns = append(p.returns, ctorType.Out(0))
		// 第二个返回值必须是 error
		if ctorType.Out(1) != reflect.TypeOf((*error)(nil)).Elem() {
			return fmt.Errorf("第二个返回值必须是 error")
		}
		p.hasError = true
	default:
		return fmt.Errorf("构造函数只能返回 1 或 2 个值")
	}

	for _, opt := range opts {
		opt(p)
	}

	// 注册到每个返回类型
	for _, retType := range p.returns {
		if _, exists := c.providers[retType]; exists {
			return fmt.Errorf("类型 %v 已经被注册了", retType)
		}
		c.providers[retType] = p
	}

	return nil
}

type Option func(*provider)

func Transient() Option {
	return func(p *provider) {
		p.isSingleton = false
	}
}

// Resolve 解析一个类型的实例
func (c *Container) Resolve(target interface{}) error {
	targetValue := reflect.ValueOf(target)
	if targetValue.Kind() != reflect.Ptr {
		return fmt.Errorf("target 必须是指针")
	}

	targetType := targetValue.Type().Elem()

	instance, err := c.resolve(targetType)
	if err != nil {
		return err
	}

	targetValue.Elem().Set(instance)
	return nil
}

func (c *Container) resolve(t reflect.Type) (reflect.Value, error) {
	c.mu.Lock()

	// 1. 已有单例？
	if instance, ok := c.instances[t]; ok {
		c.mu.Unlock()
		return instance, nil
	}

	// 2. 循环依赖检测
	if c.constructing[t] {
		c.mu.Unlock()
		return reflect.Value{}, fmt.Errorf("检测到循环依赖: %v", t)
	}

	// 3. 找 provider
	p, ok := c.providers[t]
	if !ok {
		c.mu.Unlock()
		return reflect.Value{}, fmt.Errorf("没有注册类型 %v 的构造函数", t)
	}

	c.constructing[t] = true
	c.mu.Unlock()

	// 4. 递归解析所有依赖
	args := make([]reflect.Value, len(p.params))
	for i, paramType := range p.params {
		arg, err := c.resolve(paramType)
		if err != nil {
			c.mu.Lock()
			delete(c.constructing, t)
			c.mu.Unlock()
			return reflect.Value{}, fmt.Errorf("解析 %v 的依赖 %v 失败: %w",
				t, paramType, err)
		}
		args[i] = arg
	}

	// 5. 调用构造函数
	results := p.ctor.Call(args)

	// 6. 处理 error
	if p.hasError {
		if errVal := results[1]; !errVal.IsNil() {
			c.mu.Lock()
			delete(c.constructing, t)
			c.mu.Unlock()
			return reflect.Value{}, fmt.Errorf("构造 %v 失败: %w",
				t, errVal.Interface().(error))
		}
	}

	instance := results[0]

	// 7. 缓存单例
	if p.isSingleton {
		c.mu.Lock()
		c.instances[t] = instance
		delete(c.constructing, t)
		c.mu.Unlock()
	} else {
		c.mu.Lock()
		delete(c.constructing, t)
		c.mu.Unlock()
	}

	return instance, nil
}

// Invoke 调用一个函数，自动注入它的参数
func (c *Container) Invoke(fn interface{}) error {
	fnType := reflect.TypeOf(fn)
	if fnType.Kind() != reflect.Func {
		return fmt.Errorf("必须是一个函数")
	}

	args := make([]reflect.Value, fnType.NumIn())
	for i := 0; i < fnType.NumIn(); i++ {
		arg, err := c.resolve(fnType.In(i))
		if err != nil {
			return err
		}
		args[i] = arg
	}

	results := reflect.ValueOf(fn).Call(args)
	// 处理返回的 error
	if len(results) == 1 {
		if err, ok := results[0].Interface().(error); ok && err != nil {
			return err
		}
	}
	return nil
}

// ============ 演示 ============

// 依赖链: Config → Database → UserRepository → UserService

type Config struct {
	DSN      string
	RedisAddr string
}

func NewConfig() (*Config, error) {
	return &Config{
		DSN:       "user:pass@/db",
		RedisAddr: "localhost:6379",
	}, nil
}

type Database struct {
	dsn string
}

func NewDatabase(cfg *Config) (*Database, error) {
	if cfg.DSN == "" {
		return nil, fmt.Errorf("DSN 不能为空")
	}
	return &Database{dsn: cfg.DSN}, nil
}

type Cache struct {
	addr string
}

func NewCache(cfg *Config) *Cache {
	return &Cache{addr: cfg.RedisAddr}
}

type UserRepository struct {
	db    *Database
	cache *Cache
}

func NewUserRepository(db *Database, cache *Cache) *UserRepository {
	return &UserRepository{db: db, cache: cache}
}

type UserService struct {
	repo   *UserRepository
	cache  *Cache
	dbInfo string
}

func NewUserService(repo *UserRepository, cache *Cache, db *Database) *UserService {
	return &UserService{
		repo:   repo,
		cache:  cache,
		dbInfo: db.dsn,
	}
}

func (s *UserService) GetUser(id int) string {
	return fmt.Sprintf("user-%d (db: %s)", id, s.dbInfo)
}

func demoDI() {
	fmt.Println("=== 手写 DI 容器演示 ===\n")

	c := NewContainer()

	// 注册依赖
	must(c.Provide(NewConfig))
	must(c.Provide(NewDatabase))
	must(c.Provide(NewCache))
	must(c.Provide(NewUserRepository))
	must(c.Provide(NewUserService))

	// 解析
	var svc *UserService
	if err := c.Resolve(&svc); err != nil {
		fmt.Println("解析失败:", err)
		return
	}

	fmt.Println(svc.GetUser(123))

	// Invoke: 自动注入参数
	err := c.Invoke(func(svc *UserService, cfg *Config) error {
		fmt.Printf("Invoke 成功: %s, redis=%s\n", svc.GetUser(456), cfg.RedisAddr)
		return nil
	})
	if err != nil {
		fmt.Println("Invoke 失败:", err)
	}

	// 演示循环依赖检测
	fmt.Println("\n=== 循环依赖检测 ===")
	c2 := NewContainer()
	c2.Provide(func(b *B) (*A, error) { return &A{}, nil })
	c2.Provide(func(a *A) (*B, error) { return &B{}, nil })

	var a *A
	if err := c2.Resolve(&a); err != nil {
		fmt.Println("预期中的错误:", err)
	}
}

type A struct{}
type B struct{}

func must(err error) {
	if err != nil {
		panic(err)
	}
}

func main() {
	demoDI()
}
```

**运行输出：**

```
=== 手写 DI 容器演示 ===

user-123 (db: user:pass@/db)
Invoke 成功: user-456 (db: user:pass@/db), redis=localhost:6379

=== 循环依赖检测 ===
预期中的错误: 解析 *main.A 的依赖 *main.B 失败: 检测到循环依赖: *main.A
```

---

## ★ wire vs dig：编译期 vs 运行期

### 两种 DI 方案对比

| | `google/wire`（编译期） | `uber-go/dig`（运行期） |
|:---|:---|:---|
| **机制** | 代码生成 | 反射 |
| **错误发现** | **编译期** | 运行时 |
| **启动速度** | 快（就是普通函数调用） | 慢（要反射解析依赖图） |
| **运行时开销** | **零** | 每次 Resolve 有反射开销 |
| **灵活性** | 低（依赖图要编译期确定） | 高（可以动态注册） |
| **调试** | 简单（生成的代码可读） | 难（堆栈里全是反射） |
| **二进制大小** | 小 | 大（要保留类型信息） |

### wire 的用法

```go
// wire.go
//go:build wireinject

package main

import "github.com/google/wire"

func InitializeUserService() (*UserService, error) {
	wire.Build(
		NewConfig,
		NewDatabase,
		NewCache,
		NewUserRepository,
		NewUserService,
	)
	return &UserService{}, nil   // ★ 这个返回值是给 wire 看的占位符
}
```

```bash
# 生成代码
wire

# 生成的 wire_gen.go:
func InitializeUserService() (*UserService, error) {
	config, err := NewConfig()
	if err != nil {
		return nil, err
	}
	database, err := NewDatabase(config)
	if err != nil {
		return nil, err
	}
	cache := NewCache(config)
	userRepository := NewUserRepository(database, cache)
	userService := NewUserService(userRepository, cache, database)
	return userService, nil
}
```

**看清楚了吗？生成的代码就是"手写的样子"。**

> **老陈**：**wire 的精髓：用代码生成把"运行时反射"变成"编译期代码"。**
>
> **这正是第 1 章讲的"把信息提前到编译期"的又一个例子。**
>
> **代价**：依赖图修改后要重新运行 `wire`；多了一个构建步骤。
> **收益**：零运行时开销、编译期错误、可读的代码。
>
> **这也是 Go 社区的普遍偏好：宁可多一个构建步骤，也不要运行时魔法。**

### 什么时候用 DI 容器？

```
小型项目（< 20 个组件）:
  ★ 不要 DI 容器
  手写构造函数注入就够了
  func main() {
      cfg := NewConfig()
      db := NewDatabase(cfg)
      svc := NewUserService(NewUserRepo(db))
      // 就这么简单
  }

中型项目（20-100 个组件）:
  考虑 wire（编译期，无运行时开销）

大型项目（100+ 组件，插件化）:
  考虑 dig（运行时的灵活性更重要）
```

> **老陈的判断**：**大部分 Go 项目不需要 DI 容器。**
>
> **手写构造函数注入 + 一个 `main()` 里的组装函数，就够了。**
>
> **引入 DI 容器的信号：**
> - 依赖图确实复杂（几十上百个组件）
> - 有插件系统（运行时动态注册）
> - 多个入口（CLI、HTTP、Worker 各自需要不同的依赖子集）
>
> **否则，"显式"比"魔法"好。这是 Go 的核心价值观。**

---

## 第二部分：AOP

### 什么是 AOP

**AOP (Aspect-Oriented Programming)** 解决的是**横切关注点（Cross-cutting Concerns）**：

```
业务逻辑:
  创建订单 → 扣库存 → 支付 → 发通知

横切关注点（每个业务都要做，但跟业务无关）:
  · 日志记录
  · 事务管理
  · 权限校验
  · 性能监控
  · 错误处理
```

**不用 AOP：**

```go
func (s *OrderService) CreateOrder(req *CreateOrderReq) error {
	// 1. 权限校验
	if !checkPermission(req.UserID) {
		return ErrNoPermission
	}

	// 2. 开始事务
	tx, _ := s.db.Begin()
	defer tx.Rollback()

	// 3. 日志
	log.Infof("创建订单: %+v", req)

	// 4. 性能监控
	start := time.Now()
	defer func() {
		metrics.Observe("create_order", time.Since(start))
	}()

	// 5. ★ 真正的业务逻辑（只有这几行）
	if err := s.deductStock(tx, req.Items); err != nil {
		return err
	}
	if err := s.pay(tx, req.Payment); err != nil {
		return err
	}

	// 6. 提交事务
	return tx.Commit()
}
```

**问题：业务逻辑被淹没在样板代码里。**

### Go 的做法 1：中间件（Middleware）

```go
type HandlerFunc func(*Context) error

type Middleware func(HandlerFunc) HandlerFunc

// 链式组合
func Chain(h HandlerFunc, mws ...Middleware) HandlerFunc {
	// ★ 从后往前包，这样第一个中间件在最外层
	for i := len(mws) - 1; i >= 0; i-- {
		h = mws[i](h)
	}
	return h
}

// 日志中间件
func Logging() Middleware {
	return func(next HandlerFunc) HandlerFunc {
		return func(c *Context) error {
			start := time.Now()
			err := next(c)
			log.Infof("%s %s cost=%v err=%v",
				c.Method, c.Path, time.Since(start), err)
			return err
		}
	}
}

// 权限中间件
func Auth() Middleware {
	return func(next HandlerFunc) HandlerFunc {
		return func(c *Context) error {
			token := c.Header("Authorization")
			user, err := validateToken(token)
			if err != nil {
				return ErrUnauthorized
			}
			c.Set("user", user)
			return next(c)
		}
	}
}

// 恢复中间件
func Recovery() Middleware {
	return func(next HandlerFunc) HandlerFunc {
		return func(c *Context) (err error) {
			defer func() {
				if r := recover(); r != nil {
					log.Errorf("panic: %v\n%s", r, debug.Stack())
					err = fmt.Errorf("internal error")
				}
			}()
			return next(c)
		}
	}
}

// 使用
handler := Chain(
	createOrderHandler,
	Recovery(),
	Logging(),
	Auth(),
)
```

**洋葱模型：**

```
请求 ──► ┌─────────────────────────────────┐
         │  Recovery                        │
         │  ┌───────────────────────────┐  │
         │  │  Logging                  │  │
         │  │  ┌─────────────────────┐  │  │
         │  │  │  Auth               │  │  │
         │  │  │  ┌───────────────┐  │  │  │
         │  │  │  │   业务逻辑     │  │  │  │
         │  │  │  └───────────────┘  │  │  │
         │  │  └─────────────────────┘  │  │
         │  └───────────────────────────┘  │
         └─────────────────────────────────┘
                                          ──► 响应
```

### Go 的做法 2：装饰器（Decorator）

```go
// 用接口 + 装饰器实现 AOP

type UserRepository interface {
	Get(id int) (*User, error)
	Save(u *User) error
}

// 基础实现
type userRepoImpl struct {
	db *sql.DB
}

func (r *userRepoImpl) Get(id int) (*User, error) {
	// 实际查询
}

// 缓存装饰器
type cachedUserRepo struct {
	inner UserRepository
	cache Cache
}

func (r *cachedUserRepo) Get(id int) (*User, error) {
	// 1. 查缓存
	if u, ok := r.cache.Get(fmt.Sprintf("user:%d", id)); ok {
		return u.(*User), nil
	}
	// 2. 查数据库
	u, err := r.inner.Get(id)
	if err != nil {
		return nil, err
	}
	// 3. 写缓存
	r.cache.Set(fmt.Sprintf("user:%d", id), u, time.Minute)
	return u, nil
}

// 监控装饰器
type metricsUserRepo struct {
	inner   UserRepository
	metrics Metrics
}

func (r *metricsUserRepo) Get(id int) (*User, error) {
	start := time.Now()
	defer func() {
		r.metrics.ObserveDuration("user_repo_get", time.Since(start))
	}()
	return r.inner.Get(id)
}

// 组装
repo := UserRepository(&userRepoImpl{db})
repo = &cachedUserRepo{inner: repo, cache: cache}
repo = &metricsUserRepo{inner: repo, metrics: metrics}
```

**对比：**

| | Middleware | Decorator |
|:---|:---|:---|
| **粒度** | 函数级（Handler） | 方法级（任意接口方法） |
| **类型安全** | ✅ | ✅ |
| **能否改变返回值** | ✅ | ✅ |
| **能否跳过调用** | ✅（比如 auth 失败） | ✅ |
| **适用** | HTTP 处理链 | 任意接口 |

### Go 的做法 3：代码生成（最"Spring"的方式）

如果真的想要 Spring 那种"加个注解就生效"的效果，可以用代码生成：

```go
// 定义接口
//go:generate go run ./gen -type=UserRepository

type UserRepository interface {
	//log:info
	//metric:user_repo
	//cache:ttl=1m
	Get(id int) (*User, error)

	//tx
	Save(u *User) error
}
```

生成器读取注释，生成装饰器代码。

**这就是"编译期 AOP"** —— 用代码生成代替运行时代理。

**优点**：零运行时开销、类型安全
**缺点**：需要构建步骤、调试稍复杂

**真实案例**：`go-mock`（gomock）、`protoc-gen-go` 都是这个思路。

---

## 第三部分：Spring 的核心模式在 Go 里的对应

| Spring 模式 | Go 的对应 | 说明 |
|:---|:---|:---|
| **IoC Container** | wire / dig | 依赖组装 |
| **@Autowired** | 构造函数参数 | Go 的惯例 |
| **@Component + 扫描** | 显式注册 | Go 没有包扫描 |
| **AOP + 动态代理** | Middleware / Decorator | 装饰器模式 |
| **@Transactional** | 手动 Tx 或 中间件 | Go 倾向于显式 |
| **BeanPostProcessor** | 没有直接对应 | 用 Option 模式 |
| **@Configuration** | 包级函数 | `config.New()` |
| **ApplicationListener** | Channel | Go 用 channel 传事件 |
| **@Value（配置注入）** | 结构体 + viper | 显式传参 |

### 为什么 Go 不需要"BeanPostProcessor"

Spring 的 `BeanPostProcessor` 允许你在 Bean 初始化前后插入逻辑：

```java
public interface BeanPostProcessor {
    Object postProcessBeforeInitialization(Object bean, String beanName);
    Object postProcessAfterInitialization(Object bean, String beanName);
}
```

这是**运行时扩展点**。

**Go 用 Option 模式代替：**

```go
type ServerOption func(*Server)

func WithTimeout(d time.Duration) ServerOption {
	return func(s *Server) {
		s.timeout = d
	}
}

func WithLogger(l *zap.Logger) ServerOption {
	return func(s *Server) {
		s.logger = l
	}
}

func NewServer(addr string, opts ...ServerOption) *Server {
	s := &Server{addr: addr, timeout: 30 * time.Second}
	for _, opt := range opts {
		opt(s)
	}
	return s
}

// 使用
srv := NewServer(":8080",
	WithTimeout(10*time.Second),
	WithLogger(logger),
)
```

**Option 模式的好处**：
- **编译期检查**（类型安全）
- **可读性**（看调用就知道配了什么）
- **灵活**（可选参数，不需要 10 个构造函数）
- **可扩展**（加新选项不用改签名）

> **老陈**：**Go 的这些"替代方案"体现了一个共同的价值取向：**
>
> **宁可多写几行显式的代码，也不要运行时的隐式魔法。**
>
> **代价是样板代码多，收益是：**
> - 代码的行为是"可预测的"
> - 错误在编译期暴露
> - 新人能看懂（不需要先学框架的"魔法规则"）
>
> **这不是"Go 不如 Java 强大"，而是"Go 选择了另一种复杂度分布"。**

---

## 思考题 ·【应用层】

**你要设计一个"插件化的 API 网关"。需求：**
- **核心功能固定（路由、转发、负载均衡）**
- **插件可以动态加载（认证、限流、日志、监控、熔断、灰度）**
- **插件之间可能有依赖（比如"灰度"依赖"认证"的结果）**
- **插件可以配置（不同的路由启用不同的插件组合）**

**请设计架构，说明你如何组织插件、如何处理依赖、如何保证性能。**

<details>
<summary>参考答案</summary>

### 需求分析

```
三个核心挑战：
① 插件的动态性：插件可以加载/卸载
② 插件的依赖：A 依赖 B 的结果
③ 插件的性能：每个请求都要过一遍插件链，不能有明显开销
```

---

## 架构设计

### 整体结构

```
┌──────────────────────────────────────────────────┐
│                  控制面 (Control Plane)            │
│  · 插件注册表                                       │
│  · 路由配置                                         │
│  · 依赖解析（拓扑排序）                              │
│  · ★ 生成插件链（编译期/启动时确定，不在运行时解析）   │
└──────────────────────┬───────────────────────────┘
                       │ 生成好的插件链
┌──────────────────────▼───────────────────────────┐
│                  数据面 (Data Plane)               │
│                                                   │
│  请求 → [插件1] → [插件2] → ... → [转发] → 响应     │
│         ★ 插件链在启动时就组合好了，运行时只是调用    │
└──────────────────────────────────────────────────┘
```

**★ 关键设计：控制面和数据面分离。**

- **控制面**：处理"配置、依赖解析、链生成"——慢没关系，只在配置变更时运行
- **数据面**：处理实际的请求——必须极快，**不做任何动态解析**

> 这是第 1 章讲的"把信息提前到编译期"在架构层面的应用：**配置期做复杂的事，运行期只做简单的调用。**

### 插件接口

```go
// ============ 插件定义 ============

type Phase string

const (
	PhaseAuth      Phase = "auth"       // 认证
	PhaseRateLimit Phase = "ratelimit"  // 限流
	PhasePreRoute  Phase = "preroute"   // 路由前
	PhaseRoute     Phase = "route"      // 路由
	PhasePostRoute Phase = "postroute"  // 路由后
	PhaseLog       Phase = "log"        // 日志
)

type Plugin interface {
	// 元信息
	Name() string
	Phase() Phase
	// ★ 声明依赖：我依赖哪些插件（按名字）
	Dependencies() []string
	// 初始化（配置变更时调用）
	Init(config json.RawMessage) error
	// 处理请求
	Handle(ctx *Context, next Handler) error
	// 清理
	Close() error
}

type Handler func(ctx *Context) error

type Context struct {
	Request  *http.Request
	Response http.ResponseWriter

	// ★ 插件间通信：共享的键值存储
	values map[string]interface{}

	// 短路控制
	aborted bool
	abortErr error
}

func (c *Context) Set(key string, val interface{}) {
	c.values[key] = val
}

func (c *Context) Get(key string) (interface{}, bool) {
	v, ok := c.values[key]
	return v, ok
}

// ★ 短路：跳过后续插件
func (c *Context) Abort(err error) {
	c.aborted = true
	c.abortErr = err
}
```

### 依赖解析（拓扑排序）

```go
// ============ 插件注册表 ============

type Registry struct {
	mu      sync.RWMutex
	factory map[string]PluginFactory
	plugins map[string]Plugin
}

type PluginFactory func() Plugin

func (r *Registry) Register(name string, f PluginFactory) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.factory[name] = f
}

// BuildChain 根据配置构建插件链
// ★ 这个方法只在配置变更时调用，不在请求路径上
func (r *Registry) BuildChain(config []PluginConfig) (Handler, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	// 1. 实例化插件
	plugins := make(map[string]Plugin)
	for _, cfg := range config {
		factory, ok := r.factory[cfg.Name]
		if !ok {
			return nil, fmt.Errorf("未注册的插件: %s", cfg.Name)
		}
		p := factory()
		if err := p.Init(cfg.Config); err != nil {
			return nil, fmt.Errorf("插件 %s 初始化失败: %w", cfg.Name, err)
		}
		plugins[cfg.Name] = p
	}

	// 2. ★ 拓扑排序（处理依赖）
	ordered, err := r.topologicalSort(plugins, config)
	if err != nil {
		return nil, err
	}

	// 3. 构建处理链（洋葱模型）
	//    从后往前包
	var handler Handler = r.finalHandler   // 最后的转发逻辑
	for i := len(ordered) - 1; i >= 0; i-- {
		p := ordered[i]
		next := handler
		handler = func(ctx *Context) error {
			if ctx.aborted {
				return ctx.abortErr
			}
			return p.Handle(ctx, next)
		}
	}

	return handler, nil
}

// 拓扑排序（Kahn 算法）
func (r *Registry) topologicalSort(
	plugins map[string]Plugin,
	config []PluginConfig,
) ([]Plugin, error) {

	// 建图 + 计算入度
	inDegree := make(map[string]int)
	graph := make(map[string][]string)

	for _, cfg := range config {
		name := cfg.Name
		if _, ok := inDegree[name]; !ok {
			inDegree[name] = 0
		}
		for _, dep := range plugins[name].Dependencies() {
			graph[dep] = append(graph[dep], name)
			inDegree[name]++
		}
	}

	// 入度为 0 的进队列
	var queue []string
	for name, deg := range inDegree {
		if deg == 0 {
			queue = append(queue, name)
		}
	}

	// BFS
	var result []Plugin
	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]
		result = append(result, plugins[cur])

		for _, next := range graph[cur] {
			inDegree[next]--
			if inDegree[next] == 0 {
				queue = append(queue, next)
			}
		}
	}

	// 检查是否有环
	if len(result) != len(plugins) {
		return nil, fmt.Errorf("插件依赖存在环")
	}

	return result, nil
}
```

### 具体插件示例

```go
// ============ 认证插件 ============

type AuthPlugin struct {
	secret []byte
}

func (p *AuthPlugin) Name() string { return "auth" }
func (p *AuthPlugin) Phase() Phase { return PhaseAuth }
func (p *AuthPlugin) Dependencies() []string { return nil }

func (p *AuthPlugin) Init(cfg json.RawMessage) error {
	var c struct {
		Secret string `json:"secret"`
	}
	if err := json.Unmarshal(cfg, &c); err != nil {
		return err
	}
	p.secret = []byte(c.Secret)
	return nil
}

func (p *AuthPlugin) Handle(ctx *Context, next Handler) error {
	token := ctx.Request.Header.Get("Authorization")
	if token == "" {
		ctx.Abort(ErrUnauthorized)
		return ErrUnauthorized
	}

	claims, err := validateJWT(token, p.secret)
	if err != nil {
		ctx.Abort(ErrUnauthorized)
		return ErrUnauthorized
	}

	// ★ 把结果放到 Context 里，供后续插件使用
	ctx.Set("user_id", claims.UserID)
	ctx.Set("user_tier", claims.Tier)

	return next(ctx)
}

// ============ 灰度插件（依赖认证）============

type CanaryPlugin struct {
	rules []CanaryRule
}

func (p *CanaryPlugin) Name() string { return "canary" }
func (p *CanaryPlugin) Phase() Phase { return PhasePreRoute }
func (p *CanaryPlugin) Dependencies() []string {
	return []string{"auth"}   // ★ 声明依赖
}

func (p *CanaryPlugin) Handle(ctx *Context, next Handler) error {
	// ★ 使用认证插件的结果
	userID, ok := ctx.Get("user_id")
	if !ok {
		// 理论上不会发生，因为拓扑排序保证了 auth 先执行
		return errors.New("canary 依赖 auth，但 auth 未执行")
	}

	// 根据灰度规则决定后端
	for _, rule := range p.rules {
		if rule.Match(userID.(string), ctx.Request) {
			ctx.Set("upstream", rule.Upstream)
			break
		}
	}

	return next(ctx)
}

// ============ 限流插件 ============

type RateLimitPlugin struct {
	limiter *Limiter
}

func (p *RateLimitPlugin) Name() string { return "ratelimit" }
func (p *RateLimitPlugin) Phase() Phase { return PhaseRateLimit }
func (p *RateLimitPlugin) Dependencies() []string { return []string{"auth"} }

func (p *RateLimitPlugin) Handle(ctx *Context, next Handler) error {
	tier, _ := ctx.Get("user_tier")
	quota := p.quotaForTier(tier.(string))

	if !p.limiter.Allow(ctx.Request.RemoteAddr, quota) {
		ctx.Abort(ErrTooManyRequests)
		return ErrTooManyRequests
	}
	return next(ctx)
}
```

### 性能优化

#### 优化 1：插件链预编译（最重要）

```go
// ❌ 每次请求都解析插件链
func handleRequest(w http.ResponseWriter, r *http.Request) {
	chain := buildChainFromConfig(config)   // ★ 每次都构建！
	chain(&Context{...})
}

// ✅ 配置变更时才构建，请求路径上直接调用
type Gateway struct {
	// 路由 → 预构建好的插件链
	chains map[string]Handler
	mu     sync.RWMutex
}

func (g *Gateway) handleRequest(w http.ResponseWriter, r *http.Request) {
	g.mu.RLock()
	chain := g.chains[matchRoute(r)]
	g.mu.RUnlock()

	ctx := &Context{Request: r, Response: w, values: make(map[string]interface{})}
	chain(ctx)   // ★ 只是函数调用，零解析开销
}
```

#### 优化 2：Context 对象池

```go
var ctxPool = sync.Pool{
	New: func() interface{} {
		return &Context{
			values: make(map[string]interface{}, 8),
		}
	},
}

func (g *Gateway) handleRequest(w http.ResponseWriter, r *http.Request) {
	ctx := ctxPool.Get().(*Context)
	defer func() {
		// 重置
		for k := range ctx.values {
			delete(ctx.values, k)
		}
		ctx.aborted = false
		ctx.abortErr = nil
		ctxPool.Put(ctx)
	}()

	ctx.Request = r
	ctx.Response = w

	chain(ctx)
}
```

#### 优化 3：避免 map 查找（插件间通信）

```go
// ❌ map 查找有哈希开销，且逃逸到堆
ctx.Set("user_id", uid)
uid, _ := ctx.Get("user_id")

// ✅ 用类型化的字段（热路径优化）
type Context struct {
	// 常用字段直接放在结构体里
	userID   string
	userTier string
	upstream string

	// 不常用的才放 map
	values map[string]interface{}
}

func (c *Context) UserID() string { return c.userID }
func (c *Context) SetUserID(id string) { c.userID = id }
```

#### 优化 4：插件链扁平化

```go
// 洋葱模型每层都是一次函数调用
// 10 个插件 = 10 层嵌套调用

// ✅ 扁平化：把所有插件放在一个循环里
type FlatChain struct {
	plugins []Plugin
}

func (c *FlatChain) Handle(ctx *Context) error {
	for _, p := range c.plugins {
		if ctx.aborted {
			return ctx.abortErr
		}
		if err := p.Handle(ctx, nil); err != nil {  // next 传 nil
			return err
		}
	}
	return nil
}

// ★ 但这样插件就不能"在 next 之后做事情"了（比如日志要记录响应时间）
//   折中：区分 Before/After 两类插件
type Plugin interface {
	Before(ctx *Context) error   // 请求前
	After(ctx *Context)          // 请求后（不能中断）
}
```

**性能对比：**

```
洋葱模型（10 层嵌套）:  10 次函数调用 + 10 次闭包调用 = 20 次
扁平化（Before/After）: 10 次直接调用 + 10 次直接调用 = 20 次

看起来一样？不一样：
  · 洋葱模型：每次调用都有一个闭包捕获（堆分配）
  · 扁平化：直接方法调用，可以内联

★ 实测：扁平化快 30-50%（因为内联和更少的逃逸）
```

#### 优化 5：热重载

```go
// 配置变更时，原子替换插件链
func (g *Gateway) Reload(newConfig Config) error {
	// 1. 在"旁边"构建新的插件链（不影响正在服务的请求）
	newChains := make(map[string]Handler)
	for _, route := range newConfig.Routes {
		chain, err := g.registry.BuildChain(route.Plugins)
		if err != nil {
			return err   // ★ 构建失败，不影响旧的配置
		}
		newChains[route.Pattern] = chain
	}

	// 2. 原子替换
	g.mu.Lock()
	oldChains := g.chains
	g.chains = newChains
	g.mu.Unlock()

	// 3. 延迟关闭旧的插件（等正在处理的请求完成）
	go func() {
		time.Sleep(30 * time.Second)   // 等待旧请求
		for _, chain := range oldChains {
			closeChain(chain)
		}
	}()

	return nil
}
```

**★ 这是"无锁读 + 原子切换"的模式**，跟第 4 章讲的"增量索引原子切换"是同一个思路。

---

## 完整架构图

```
┌────────────────────────────────────────────────────────┐
│                     控制面                               │
│  ┌──────────────┐   ┌──────────────┐  ┌─────────────┐ │
│  │ 插件注册表    │   │ 配置管理      │  │ 链构建器     │ │
│  │ (Registry)   │   │ (etcd/文件)   │  │(拓扑排序)    │ │
│  └──────────────┘   └──────────────┘  └─────────────┘ │
│                            │                           │
│                    配置变更触发                          │
└────────────────────────────┼───────────────────────────┘
                             │ 原子替换
┌────────────────────────────▼───────────────────────────┐
│                     数据面                               │
│                                                         │
│  请求 ──► 路由匹配 ──► 预构建的插件链 ──► 转发 ──► 响应    │
│            (radix)      [auth][ratelimit][canary]        │
│                              │                          │
│                         Context（对象池复用）             │
└─────────────────────────────────────────────────────────┘
```

---

## 五个设计权衡

| 决策 | 选择 | 理由 |
|:---|:---|:---|
| **依赖解析时机** | 配置期（拓扑排序） | ★ 运行期零开销 |
| **插件通信** | Context 传值 | 简单；热字段用结构体成员优化 |
| **插件链结构** | 扁平化 Before/After | 比洋葱模型快 30-50% |
| **配置更新** | 原子替换 + 延迟关闭 | 无锁读，无请求中断 |
| **Context 管理** | 对象池 | 减少 GC 压力 |

---

## 一句话总结

**插件化架构的核心矛盾是"灵活性"和"性能"。**

解法是**控制面/数据面分离**：
- 控制面做所有复杂的事（依赖解析、拓扑排序、链构建）
- 数据面只做简单的函数调用

**这跟第 1 章讲的"把信息提前到编译期"、第 4 章讲的"倒排索引定期重建 + 增量索引"是完全相同的思路：**

> **把复杂的工作挪到"不常发生的时刻"（编译期、配置期、离线），让"频繁发生的时刻"（运行期、请求处理）尽可能简单。**

</details>

---

## 小结：这一节你应该带走的东西

1. **IoC 是思想（框架调用你），DI 是技术（依赖外部传入）**。依赖注入的核心价值是**可测试性**。

2. **Go 几乎只用构造函数注入**——编译期检查、不可变、明确、易测试。

3. **wire vs dig = 编译期 vs 运行期**。wire 用代码生成把反射变成普通函数调用，是"把信息提前到编译期"的典范。

4. **大部分 Go 项目不需要 DI 容器**——手写构造函数 + `main()` 里的组装函数就够了。

5. **AOP 解决横切关注点**。Go 的三种实现：Middleware（函数级）、Decorator（接口级）、代码生成（编译期）。

6. **Go 用 Option 模式代替 BeanPostProcessor**——编译期检查、可读、可扩展。

7. **插件化架构的核心是控制面/数据面分离**——把复杂的工作挪到配置期，让请求路径尽可能简单。

---

## 下一节

[02 · 手写 Web 容器：从 Socket 到 MVC](./02-手写Web容器-从Socket到MVC.md)

> **老陈的预告**：`net/http` 帮你做了太多事。这一次我们把 HTTP 服务器从零实现一遍——解析 HTTP 报文、实现路由树、处理连接。
>
> **写完你会明白：所谓的 Web 框架，核心就是"URL 到函数的映射"加"一串中间件"。**
