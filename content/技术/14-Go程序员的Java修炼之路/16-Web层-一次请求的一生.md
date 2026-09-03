# 第 16 章　Web 层：一次请求的一生（从 Tomcat 到你的 @GetMapping）

> 凌晨两点，报警群炸了：订单详情接口偶发返回 500，但日志里只有一行 `HttpMessageNotReadableException`，没有字段名。你 `git blame` 发现鉴权写在一个拦截器里，而那个拦截器抛的异常，`@ControllerAdvice` 死活兜不住——返回的居然是 Tomcat 的默认错误页。你盯着堆栈想：一个 HTTP 请求从网卡到我的 `@GetMapping`，中间到底过了几道门？哪道门能拦、哪道门能改、哪道门抛的异常根本没人接？
>
> 第 15 章你看到 `DispatcherServlet` 是被自动装配好的，第 14 章你看到 Controller 是被容器注入的。这章把这两件事之间的空白填上：请求进了 Tomcat 之后，到底走了哪几道门，才轮到你的业务方法说话。

---

## 16.1 先画一张门禁图：一次请求过了几道门

别急着记名词。先把全景画出来，后面每一个组件都是图上的一个节点，你知道它在哪，才知道它能在什么时候拦你、改你、坑你。

```text
HTTP 请求
  → Tomcat 连接器线程（Connector 线程池里的一条 worker 线程）
  → Filter 链（Servlet 容器层：字符编码 / CORS / 认证 / 链路追踪）
  → DispatcherServlet（前端控制器，Spring MVC 的总入口）
  → HandlerMapping（按 URL 找 HandlerExecutionChain：HandlerMethod + 拦截器列表）
  → HandlerAdapter（RequestMappingHandlerAdapter）
       → HandlerInterceptor.preHandle（逐层，任一返回 false 就截断）
       → HandlerMethodArgumentResolver（参数解析：@PathVariable / @RequestBody / ...）
       → 调用你的 @Controller / @RestController 方法
       → HandlerInterceptor.postHandle
       → HandlerMethodReturnValueHandler（返回值处理）
       → HttpMessageConverter（Jackson 把对象序列化成 JSON）
  → 响应写回客户端
  → HandlerInterceptor.afterCompletion（在 finally 里，成功失败都跑）
```

这串链路里，真正能"卡住请求"的有三道门：**Filter 门**（Servlet 容器层，能改 request/response、能直接截断）、**前端控制器门**（DispatcherServlet，所有请求的唯一总入口）、**拦截器门**（Spring MVC 层，能拿到"即将执行的是哪个 Controller 方法"）。再往后是**参数解析门**和**异常兜底门**，它们不拦请求，但决定"方法能不能被正确调用""出错长什么样"。

**问题 1：**为什么需要这么多层，而不是 `if (path.equals("/order")) { handle(req, resp); }` 一路写到底？

因为"认证、日志、跨域、参数绑定、异常格式化"这些横切逻辑，如果每层都手写一遍，十个接口复制十遍，和你在 14 章看到的 AOP 痛点一模一样。Spring 把这些抽成管道上的"门"，每道门只干一件事，可插拔、可排序。代价你也猜到了：请求路径变成了一条你看不到全貌的流水线，排错时得知道"我在第几道门"。

> 【思考】既然这么多层都是"为了不重复写横切逻辑"，那 Go 的 gin 中间件链不也是同一个目的吗？Java 这套和 Go 的本质区别到底在哪？

<details>
<summary><b>参考答案</b></summary>

**直接答案：目的完全一样——都是"把横切逻辑从每个 handler 里抽出来，做成管道节点"。本质区别在于"谁来编排这道管道、管道节点能拿到多少上下文、以及参数怎么到 handler"。** Go 的管道是你 `main()` 里显式 `r.Use(...)` 拼的，节点是普通函数，能拿到的只有 `*gin.Context`；Java 的管道由 DispatcherServlet 这个"框架总前台"在运行时编排，节点（Interceptor/Resolver）能拿到"即将执行的是哪个 HandlerMethod、方法参数上有啥注解"这种反射级上下文。

**展开看 Go 的写法：**

```go
// Go：管道是显式的，你能 go to definition 看到每一环
func main() {
    r := gin.New()
    r.Use(Logger())        // 中间件 1：日志
    r.Use(Auth())          // 中间件 2：鉴权
    r.Use(CORS())          // 中间件 3：跨域
    r.GET("/order/:id", GetOrder)
    r.Run(":8080")
}
```

**展开看 Java 的等价位置：**

```java
// Java：这些"门"不是你一行行拼的，是 DispatcherServlet 在运行时按顺序调的
// 你只注册组件（Interceptor / Filter / Resolver），编排交给框架
@Configuration
public class WebConfig implements WebMvcConfigurer {
    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new AuthInterceptor())   // 注册拦截器，排序交给框架
               .addPathPatterns("/**");
    }
}
```

Go 这边，`r.Use(Auth())` 之后下一个中间件/ handler 是你在代码里一眼看全的；Java 这边，请求从 Tomcat 进来到 DispatcherServlet，再到你的 `@GetMapping`，中间经过哪些 Resolver、哪些 Interceptor，是运行时由 Spring MVC 的策略对象（HandlerMapping、HandlerAdapter、一堆 Resolver）决定的，不在你的 `main()` 里。

**更深一层**：这又是一次"显式 vs 隐式"的复现。Go 的管道"代码即真相"，你写的顺序就是执行顺序；Java 的管道"配置即真相"，你注册组件、框架按自己的既定顺序串起来。Java 这套能拿走 Go 拿不到的上下文（比如 Interceptor 能拿到 `HandlerMethod`，知道"这次要调的是 `OrderController.findById`"），这是 AOP/反射体系给的红利；代价是管道不透明，排错得先搞清"我现在在第几道门"。带着这个视角看后面每一节，你会轻松很多。

</details>

---

## 16.2 DispatcherServlet 是什么：为什么 Java 有个"总前台"

`DispatcherServlet` 干的事，翻译成一句话就是：**所有进来的请求，先统一交给它，再由它分发给具体的 Controller 方法**。这是经典的"前端控制器模式"（Front Controller）。它自己不处理业务，它负责"接客、找人、派活、收尾"。

为什么需要这么一个总前台？你从 Go 过来会本能地反问：gin 里我 `r.GET("/order/:id", GetOrder)` 直接把路径和处理函数绑死了，请求来了 `http.ServeMux` 一查路由表就调到 `GetOrder`，要这个"总前台"干嘛？

区别在于**"路由之后的动作"复杂度不同**。

Go 的 `http.ServeMux` 只做一件事：URL → handler 函数。handler 函数签名固定 `func(w http.ResponseWriter, r *http.Request)`，参数你自己从 `r` 里解析。Java 这边要做的远不止"找到函数"：

- 参数不是固定签名，而是按注解从请求各处"装配"——`@PathVariable` 取路径段、`@RequestParam` 取 query、`@RequestBody` 把整个 body 反序列化成对象。
- 调用前后要过拦截器、要套 AOP（你的 Controller 方法可能也被事务代理包着）。
- 返回值不是固定 `ResponseWriter`，而是对象、要被 Jackson 序列化、要适配"返回 JSON 还是返回视图名"。
- 出错了要统一格式化。

这些动作如果每路由各写一遍，不可维护。所以 Java 把"路由之后的全部公共动作"收进 `DispatcherServlet` 这一个总入口，由它统一调度 HandlerMapping / HandlerAdapter / Resolver。**Go 是把"路由 + 调用"分散在每个 handler 里（靠显式代码）；Java 是把"路由之后的公共调度"集中到一个总前台里（靠框架）。**

```java
// DispatcherServlet 不是你 new 的——第 15 章讲过，它来自
// DispatcherServletAutoConfiguration（满足条件就自动注册成 Servlet Bean）
// 你看到的就是这个 Bean 在 Tomcat 里占着 "/" 这个映射
```

第 15 章你已经知道，`DispatcherServletAutoConfiguration` 在 classpath 有 `spring-webmvc` 且满足 Web 应用时，把这个 Servlet 注册进内嵌 Tomcat，映射路径默认是 `/`。所以"总前台"也是自动来的，不用你配。

**问题 2：**如果有两个 `DispatcherServlet` 会怎样？同一个请求会被派两次吗？

不会冲突，因为 Servlet 容器按 URL 映射分发：每个 `DispatcherServlet` 注册在不同的映射路径下（如一个管 `/api/*`，一个管 `/admin/*`），容器先按路径选 Servlet，选中的那个 Servlet 内部再走自己的 HandlerMapping。这是"Servlet 容器层路由"和"Spring MVC 层路由"的两级路由——第一级在 Tomcat，第二级在 DispatcherServlet 内部。

下面是本章第一张对照表，先把整体格局钉死：

| 概念 | Go | Java（Spring MVC） |
|---|---|---|
| 统一入口 | `http.ServeMux` / gin 的 `Engine`（每个 handler 自己 `r.GET` 注册） | `DispatcherServlet`（前端控制器，运行时统一调度） |
| 路由之后的公共动作 | 你自己写在 handler / 中间件里 | 框架在 DispatcherServlet 内统一做（参数解析、拦截、序列化） |
| 参数绑定 | 手动 `c.Param("id")` / `json.Unmarshal` | 注解驱动，ArgumentResolver 自动装配 |
| 拦截/横切 | 中间件链 `r.Use(...)`，显式 | HandlerInterceptor + Filter，注册后框架编排 |
| 异常兜底 | `recover` 中间件，显式 | `@ControllerAdvice` + `@ExceptionHandler`，声明式 |
| 路由表可见性 | 代码即真相，一眼看全 | 运行时由 HandlerMapping 算，靠 Actuator 恢复可观测性 |

**问题 3：**`net/http` 的 `Handler` 接口和 gin 的路由，跟 DispatcherServlet 是同一层东西吗？

不是。`net/http` 的 `Handler`（`func(w http.ResponseWriter, r *http.Request)`）和 gin 的 `Engine` 是"Servlet 容器 + 总路由"的合体——它们既负责接请求、又负责找 handler。而 `DispatcherServlet` 只相当于 gin 的 `Engine` 那部分（接收已进 Tomcat 的请求并分派）；Tomcat 自己充当了 `net/http` 的 `Server` + `ServeMux` 角色。一句话：Go 的 `http.Server` 涵盖 Tomcat + DispatcherServlet 两层，gin 的 `Engine` 约等于 DispatcherServlet。

---

## 16.3 过滤器链与拦截器：两道门，两个层次

这是全章最容易混的一对。名字像、都能"拦请求"，但**它们处在不同的层，能拿到的东西完全不同，抛异常时谁接得住也不同**。

### Filter：Servlet 容器层的门

`Filter`（`javax.servlet.Filter`）是 Servlet 规范的东西，在 **Tomcat 容器层**运行，**在 DispatcherServlet 之前**。它只能拿到 `HttpServletRequest` / `HttpServletResponse`，拿不到"这次要调哪个 Controller 方法"。它擅长干：字符编码、CORS 头、请求/响应包装（如把 request body 缓存下来以便重复读）、链路追踪埋点、最外层的认证。

```java
// Filter 在容器层，注册进 Tomcat，DispatcherServlet 之前执行
@WebFilter("/*")
public class TraceFilter implements Filter {
    @Override
    public void doFilter(ServletRequest req, ServletResponse res, FilterChain chain)
            throws IOException, ServletException {
        long start = System.nanoTime();
        try {
            chain.doFilter(req, res);   // 放行，才会进 DispatcherServlet
        } finally {
            log.info("cost={}", System.nanoTime() - start);
        }
    }
}
```

### HandlerInterceptor：Spring MVC 层的门

`HandlerInterceptor` 是 Spring MVC 自己的抽象，在 **DispatcherServlet 内部、HandlerAdapter 调用你的方法前后**执行。它最大的特权是：**能拿到 `HandlerMethod`，也就是"即将执行的是哪个 Controller 方法、参数是什么"**。这是 Filter 做不到的——Filter 那会儿 Spring 还没开始路由，根本不知道要调谁。

它有三个方法，顺序就是它们的名字：

```java
public class AuthInterceptor implements HandlerInterceptor {
    // 在 HandlerAdapter 真正调 Controller 之前；返回 false 就直接截断，后面的拦截器和 Controller 都不跑
    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse res, Object handler) {
        if (handler instanceof HandlerMethod m) {          // 能拿到目标方法
            log.info("即将调用 {}", m.getMethod().getName());
        }
        if (!authorized(req)) {
            res.setStatus(401);                            // 手动写响应
            return false;                                  // 截断，请求到此为止
        }
        return true;
    }

    // Controller 方法执行之后、视图渲染之前；注意此时响应还没写回客户端
    @Override
    public void postHandle(HttpServletRequest req, HttpServletResponse res, Object handler, ModelAndView mv) {
        // 通常用来往 Model 里塞公共数据，或改响应头
    }

    // 整个请求处理完（含渲染、含异常）之后，在 finally 里调用；常用于资源清理
    @Override
    public void afterCompletion(HttpServletRequest req, HttpServletResponse res, Object handler, Exception ex) {
        // 无论成功失败都跑；ex 非 null 代表链路中抛了异常
    }
}
```

关键记忆点：**`preHandle` 返回 `false` 能硬截断请求**；`postHandle` 改不了已经写出的响应；`afterCompletion` 是清理现场的最后机会，且总能跑（这点对"埋点上报、连接释放"很重要）。

### 两者区别一张表

| 维度 | Filter（容器层） | HandlerInterceptor（MVC 层） |
|---|---|---|
| 所处位置 | Tomcat 内、DispatcherServlet 之前 | DispatcherServlet 内、HandlerAdapter 前后 |
| 能拿到的上下文 | `HttpServletRequest` / `Response` | 上面那些 + `HandlerMethod`（目标方法） |
| 能否截断请求 | `chain.doFilter` 不放行即截断 | `preHandle` 返回 `false` 截断 |
| 能否改响应体 | 需包装 response 才能改 | `postHandle` 可改 Model/头，但响应多已定型 |
| 异常被谁兜 | 容器自己（Tomcat 错误页） | DispatcherServlet 的异常处理流程 |

> 【思考】Filter 里抛异常和 Interceptor 的 preHandle 里抛异常，哪个会被 `@ControllerAdvice` 兜住？

<details>
<summary><b>参考答案</b></summary>

**直接答案：都不保证能被 `@ControllerAdvice` 兜住，但原因不同。Filter 在 DispatcherServlet 之外，容器层抛的异常根本进不了 Spring 的异常处理通道，Tomcat 直接上默认错误页；Interceptor 的 preHandle 在 DispatcherServlet 之内，Spring 5 起 DispatcherServlet 把它的异常也纳入了同一套 dispatcher 异常处理流程（交给 HandlerExceptionResolver），理论上 @ControllerAdvice 能兜——但这依赖版本、且要求你真写了匹配那个异常的 @ExceptionHandler，否则照样 500。所以不能把 @ControllerAdvice 当成"兜一切"的保险。**

**为什么 Filter 兜不住：** `@ControllerAdvice` 的 `@ExceptionHandler` 是通过 `HandlerExceptionResolver` 在 `DispatcherServlet` 内部生效的。Filter 跑在 DispatcherServlet 之前，异常冒出去就到了 Tomcat 容器，容器按 `web.xml` 的 `<error-page>` 或 Spring Boot 的 `error` 端点渲染。**Spring MVC 的异常处理通道根本没被走到。**

**为什么 Interceptor 不能全信：** Spring 5.0 重构了 `DispatcherServlet.doDispatch`，把 `applyPreHandle` 抛出的异常也收进 `dispatchException`，再交给 `processDispatchResult` → `HandlerExceptionResolver`。所以"preHandle 异常被 @ControllerAdvice 兜"是从 Spring 5 开始的；旧版直接冒出去变 500。更要命的是：即便版本对，如果你没为那个异常写专门的 `@ExceptionHandler`，Spring 的默认行为仍是把它当未处理异常，返回 500。

**代码锚点——最稳的写法，别依赖兜底：**

```java
// 在 preHandle 里直接写响应，不抛异常，行为百分之百确定
@Override
public boolean preHandle(HttpServletRequest req, HttpServletResponse res, Object handler) {
    if (!authorized(req)) {
        res.setStatus(401);                              // 直接定状态
        res.setContentType("application/json;charset=UTF-8");
        try (var w = res.getWriter()) {
            w.write("{\"code\":401,\"msg\":\"unauthorized\"}");  // 直接写体
        } catch (IOException ignored) {}
        return false;                                    // 截断
    }
    return true;
}
```

**更深一层**：`@ControllerAdvice` 兜的是"MVC 层的 handler 异常"（Controller 方法执行、参数解析、返回值处理阶段抛的），不是"容器层 / 拦截器入口"的万能兜底。你作为 Go 老哥，会把 `@ControllerAdvice` 类比成 gin 的 `recover` 中间件——但 gin 的 `recover` 中间件也是你显式挂在链首的，包住了后面所有 handler；而 Spring 这套分层后，"包住的范围"有边界。结论是：**认证这类该硬截断的逻辑，在 preHandle 里直接写响应最稳，别把希望寄托在异常被兜成 401。**

</details>

---

## 16.4 参数绑定：字符串怎么变成你的对象

到了 `HandlerAdapter` 真正调你的方法这一步，最大的魔法发生了：你方法签名上写的不是 `HttpServletRequest`，而是 `Long id`、`OrderReq dto` 这种业务类型。字符串是怎么变成对象的？靠的是 `HandlerMethodArgumentResolver`（参数解析器）。

Spring 内置了一打解析器，按注解分工：

| 注解 | 数据来源 | 背后用的解析器 |
|---|---|---|
| `@PathVariable("id")` | URL 路径段 `/order/{id}` | `PathVariableMethodArgumentResolver` |
| `@RequestParam("page")` | query string `?page=1` | `RequestParamMethodArgumentResolver` |
| `@RequestBody` | 整个请求 body（JSON） | `RequestResponseBodyMethodProcessor`（它同时是返回值处理器） |
| `@ModelAttribute` | query / form 字段，按名绑到对象属性 | `ModelAttributeMethodArgumentResolver` |
| `@RequestHeader` / `@CookieValue` | 请求头 / Cookie | 各自专属解析器 |

`HandlerAdapter` 在调用你的方法前，会遍历方法参数，对每个参数问一圈"谁认领这个注解"，认领的解析器负责把 `HttpServletRequest` 里的原始数据变成方法参数对象。

```java
@GetMapping("/order/{id}")
public OrderDTO get(@PathVariable Long id) {            // 路径段字符串 "42" → Long 42
    return service.findById(id);
}

@PostMapping("/order")
public void create(@RequestBody OrderReq req) {         // body JSON → OrderReq 对象
    service.create(req);
}
```

### @RequestBody 是特殊的：它靠 HttpMessageConverter + Jackson

`@RequestBody` 不像前几个只是"取个字符串再类型转换"，它是把**整个 body 当消息**读出来，交给 `HttpMessageConverter` 做"消息→对象"的转换。默认的消息转换器是 `MappingJackson2HttpMessageConverter`，底层就是 Jackson 的 `ObjectMapper` 把 JSON 反序列化。所以"JSON 怎么变成对象"的规矩，全是 Jackson 的规矩（字段名匹配、类型匹配、`@JsonFormat` 等）。

> 【思考】为什么 `@RequestBody` 解析失败报的是 400，而且日志里常常看不到"到底是哪个字段错了"？

<details>
<summary><b>参考答案</b></summary>

**直接答案：因为 `@RequestBody` 的反序列化发生在参数解析阶段，Jackson 抛的是 `JsonMappingException`（被 Spring 包成 `HttpMessageNotReadableException`），Spring 默认把它映射成 HTTP 400（客户端请求格式错）。至于"看不到哪个字段"——Jackson 其实在异常里带了 JSON path（如 `order.items[2].price`），但 Spring Boot 默认的 `/error` 响应只回了状态码和简短 message，没把 Jackson 的字段路径展开；而很多人排错只看"有没有 400"，没去读那条 `HttpMessageNotReadableException` 的完整堆栈，于是只看到异常类名、看不到字段。**

**为什么是 400 不是 500：** `HttpMessageNotReadableException` 继承自 Spring 的"客户端错误"异常体系（`ResponseStatusException` 子类），Spring Boot 的 `DefaultHandlerExceptionResolver` 专门把它映射成 400。语义是"你的请求体我读不了，是你客户端的问题"。这点和 Go 不同：Go 里 `json.Unmarshal` 失败你通常自己决定返回 400 还是 500。

**为什么字段名藏起来了：** Jackson 的 `JsonMappingException` 带有 `getPath()`（一串 `Reference`，记录走到 `order -> items -> [2] -> price`），但 Spring Boot 默认错误响应体（`/error`）只序列化了 `status/message`，没把 `path` 暴露出来。于是你线上看到的是 `HttpMessageNotReadableException: JSON parse error`，没有字段坐标。

**代码锚点——把字段路径挖出来：**

```java
@ControllerAdvice
public class BodyErrorAdvice {
    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<Map<String,Object>> onBody(HttpMessageNotReadableException ex) {
        // 真正的根因在 cause 里，是 Jackson 的 JsonMappingException
        var cause = ex.getCause();
        String field = "unknown";
        if (cause instanceof JsonMappingException jme) {
            // 把 Jackson 的 path 拼成 order.items[2].price 这种可读路径
            field = jme.getPath().stream()
                    .map(JsonMappingException.Reference::getFieldName)
                    .collect(Collectors.joining("."));
        }
        return ResponseEntity.badRequest().body(Map.of("error", "bad_field", "field", field));
    }
}
```

**更深一层**：这个坑暴露的是"序列化错误发生在框架替你做的那一层"。Go 里你手写 `json.Unmarshal(b, &req)`，失败的那一刻你就在现场，`err` 里带字段信息，你想怎么打怎么打；Java 里 Jackson 在 `ArgumentResolver` 内部替你反序列化，你不在现场，只能接住它抛出的异常再去挖。所以排 `@RequestBody` 400 的 SOP 是：**去读 `HttpMessageNotReadableException` 的完整 cause 堆栈，而不是只看异常类名**——字段坐标一直都在 Jackson 的 path 里，只是默认响应没把它端给你。

</details>

**问题 4：**`@ModelAttribute` 和 `@RequestParam` 有什么区别？什么时候用哪个？

`@RequestParam` 绑定单个 query/form 参数到单个方法参数（`?page=1` → `int page`）；`@ModelAttribute` 把多个 query/form 字段按"属性名"拼成一个对象（`?name=a&age=1` → `User user`，属性名对上就填）。简单查询参数用 `@RequestParam`；一个表单/一組相关字段用 `@ModelAttribute`。注意 `@RequestBody` 读的是 body，和这俩读 query/form 的来源完全不同——别把一个 POST 既想 `@ModelAttribute` 又想 `@RequestBody`，它们抢的不是同一份数据。

---

## 16.5 统一异常处理：@ControllerAdvice 在哪一层兜底

你写 CRUD 一定想要"所有异常都变成统一格式的 JSON，而不是 Tomcat 的白页"。Spring 给的工具是 `@ControllerAdvice` + `@ExceptionHandler`。

机制上，`@ControllerAdvice` 是个全局增强的 `@Component`，它里面的 `@ExceptionHandler` 方法会被 `ExceptionHandlerExceptionResolver` 收集起来。当 Controller 方法（或参数解析、返回值处理）抛异常时，DispatcherServlet 的异常处理流程会问这个 resolver："你有没有能处理这个异常类型的方法？"有就调它，把返回值当响应写回。

```java
@ControllerAdvice                 // 全局生效，拦截所有 Controller 抛出的异常
public class GlobalExceptionAdvice {

    @ExceptionHandler(BizException.class)        // 只兜 BizException
    public ResponseEntity<ErrorBody> handleBiz(BizException e) {
        return ResponseEntity.status(e.getCode())
                .body(new ErrorBody(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(Exception.class)          // 兜底所有其他异常 → 500 统一样式
    public ResponseEntity<ErrorBody> handleOther(Exception e) {
        log.error("unexpected", e);
        return ResponseEntity.status(500)
                .body(new ErrorBody(500, "internal error"));
    }
}
```

它的生效范围是**MVC 层**：Controller 方法执行、参数解析（含 `@RequestBody` 失败）、返回值处理阶段抛的异常。回到 16.3 那个【思考】的结论——它**兜不住 Filter 层抛的异常**，对 Interceptor 的 preHandle 异常则"看版本、看有没有匹配 handler"。

> 【思考】`@ControllerAdvice` 和 Go 的 `recover` 中间件，本质是一回事吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：目的一样（全局兜异常、统一错误格式），但机制相反。Go 的 `recover` 中间件是你显式挂在链首的普通函数，用 `defer recover()` 包住后面所有 handler，范围由你把中间件放哪决定，肉眼可见；Spring 的 `@ControllerAdvice` 是声明式注解，框架在 DispatcherServlet 的异常处理流程里自动"织入"，你不知道它具体在调用栈哪一层被触发，且它的覆盖范围有边界（MVC 层，不含 Filter 层）。一个是"显式包一层"，一个是"声明一个、框架去找"。**

**Go 的写法（显式、范围清楚）：**

```go
// gin 的 recover 中间件，挂在最前面，包住后面所有 handler
func Recover() gin.HandlerFunc {
    return func(c *gin.Context) {
        defer func() {
            if err := recover(); err != nil {        // 显式兜住 panic
                c.JSON(500, gin.H{"msg": "internal"})
            }
        }()
        c.Next()
    }
}

func main() {
    r := gin.New()
    r.Use(Recover())        // 你看得到它包住了一切
    r.GET("/order/:id", GetOrder)
}
```

**Java 的写法（声明式、范围靠框架）：**

```java
// 你只声明"这是个全局异常处理器"，框架在 DispatcherServlet 内部自动接住 MVC 层异常
@ControllerAdvice
public class GlobalExceptionAdvice {
    @ExceptionHandler(BizException.class)
    public ResponseEntity<ErrorBody> handle(BizException e) { ... }
}
```

**范围差异是核心**：Go 的 `Recover()` 在 `r.Use` 链首，`c.Next()` 之后的所有 handler 都被它包住，包括你手写的认证逻辑——只要认证逻辑写在 handler 里（而不是 `r.Use` 之前的更外层）。Spring 的 `@ControllerAdvice` 只作用于"进入 DispatcherServlet 之后、MVC 调度过程中"的异常；你写在 Filter 里的认证逻辑抛的异常，它够不着（那是容器层）。所以同样叫"全局异常处理"，Go 的全局性是"链范围"，Spring 的全局性是"MVC 层范围"。

**更深一层**：又是显式 vs 隐式。Go 的 recover 中间件你 `go to definition` 能看到它包住了谁；Spring 的 `@ControllerAdvice` 让你少写一个中间件，但"它到底兜不兜得住 Filter 的异常"这种边界问题，得理解 DispatcherServlet 的分层才答得上来。你从 Go 过来最容易犯的错，就是以为 `@ControllerAdvice` 像 `recover` 一样"包住一切"，结果发现 Filter/Interceptor 入口的异常漏了——这正好是第 16.7 案例一的真凶。

</details>

---

## 16.6 WebFlux：另一种线程模型，以及它的饿死陷阱

前面整章讲的都是 **Servlet 栈**（Spring MVC）：一请求一线程（或线程池里的一条 worker 线程），从 Filter 到 Controller 到写响应，全程占着那条线程。Tomcat 的 Connector 线程池（默认 `TomcatRequestThreadPool`，约 200 条上限）就是并发天花板——请求多到线程用完，新请求排队。

**WebFlux 是另一条路：响应式栈。** 它底下是 Netty（不是 Tomcat），线程模型是**少量 event loop 线程（event loop / selector 线程，通常等于 CPU 核数）承载海量连接**。一条 event loop 线程不专属于某个请求，它在"事件就绪"时处理一点，然后就去处理别的请求。请求在等待 IO（查库、调下游、读文件）时，**不占用任何线程**——线程被释放去服务其他请求。

这不是"更先进的线程池"，是**编程模型的根本切换**：从"一个请求占一条线程直到做完"变成"少量线程在多路复用事件上切换"。

**问题 5：**这不就是第 12 章的虚拟线程想解决的同一件事吗？

思路同源（都为了减少"每请求一线程"的线程开销），但机制相反。虚拟线程是"你照旧写阻塞式代码，JVM 在阻塞时自动把虚拟线程从载体线程上卸载，腾出载体线程跑别的虚拟线程"——**对你透明，代码还是同步写法**。WebFlux 是"你必须在代码里处处返回 `Mono`/`Flux`、处处非阻塞，线程才不会被你占住"——**对你不透明，代码要改成响应式写法**。虚拟线程保住了你的写法；WebFlux 要你改写法换吞吐。

### 背压（back-pressure）是什么

Servlet 栈里，下游处理慢，上游（如数据库批量吐数据）照样猛推，结果内存爆。WebFlux 的 `Flux<T>` 是**带背压的流**：消费者通过 `request(n)` 告诉生产者"我这次最多能吃 n 个"，生产者按量发。于是"生产快、消费慢"时不会被活活压垮，而是反向节流。这是响应式流（Reactive Streams）规范的核心，Servlet 栈没有内建这东西。

> 【思考】WebFlux 里能不能放心调阻塞 API（比如一个老旧的 JDBC 查询）？事件循环线程被阻塞了会怎样？

<details>
<summary><b>参考答案</b></summary>

**直接答案：不能，这是 WebFlux 最臭名昭著的坑。event loop 线程总数极少（约等于 CPU 核数），它一旦在某个请求的处理里被阻塞（同步 JDBC 查询、阻塞锁、`Thread.sleep`、甚至 `block()` 调用），这条线程就被占住、服务不了任何其他请求。你只阻塞了几条核数级的线程，整个应用的吞吐就直接趴窝——因为没有任何多余线程可切换了。这和第 12 章虚拟线程形成尖锐对照：虚拟线程阻塞时自动卸载，event loop 阻塞时不卸载。**

**为什么 WebFlux 扛不住阻塞：** Servlet 栈线程池有几百条，堵一两条还有几百条顶着，最多"部分变慢"；WebFlux 的 event loop 就几条，堵一条少一条，堵满几条，所有连接都卡住，吞吐骤降、延迟飙红。

**代码锚点——一个压测必炸的写法：**

```java
// WebFlux Handler：在 event loop 线程上同步查 JDBC，灾难
@Bean
public RouterFunction<ServerResponse> routes(OrderRepo repo) {
    return RouterFunctions.route(GET("/order/{id}"), req -> {
        // ❌ 同步 JDBC 阻塞了 event loop 线程
        Order o = repo.blockingFindById(req.pathVariable("id"));
        return ServerResponse.ok().bodyValue(o);
    });
}
```

```java
// ✅ 正确：把阻塞调用丢到专门的调度器（绑定一个独立线程池），别占 event loop
@Bean
public RouterFunction<ServerResponse> routes(OrderRepo repo) {
    return RouterFunctions.route(GET("/order/{id}"), req ->
        Mono.fromCallable(() -> repo.blockingFindById(req.pathVariable("id")))
            .subscribeOn(Schedulers.boundedElastic())   // 丢给弹性线程池，event loop 不被占
            .flatMap(o -> ServerResponse.ok().bodyValue(o))
    );
}
```

**真实场景**：某服务把订单查询从 MVC 迁到 WebFlux 想提吞吐，但 Handler 里直接调了团队的 `JdbcOrderDao.findXxx`（同步 JDBC）。压测一上来，QPS 不升反降，CPU 不高、线程数卡在核数级、延迟全红。排查发现 event loop 线程全 `BLOCKED` 在 JDBC socket read 上——`jstack` 一看，几条 `reactor-http-nio` 线程栈顶都是 `SocketInputStream.read`。修复就是上面那样：把阻塞调用 `subscribeOn(Schedulers.boundedElastic())` 挪出 event loop。

**更深一层**：WebFlux 的吞吐优势，前提是你**全程非阻塞**。只要链路上有任意一个同步阻塞点忘了隔离，event loop 就被钉死，优势瞬间变劣势，而且比 Servlet 栈更脆（因为线程余量少）。所以"什么时候该用 WebFlux"的答案是：**只有当你能保证整条调用链非阻塞（响应式 DB 驱动、响应式 HTTP 客户端、下游也快），且瓶颈真是"连接多、IO 等待长、客户端慢"时，才划算**。如果你只是"换个时髦框架但里面还是 JDBC/hibernate 同步查"，那不仅没收益，还凭空多了一个 event loop 饿死的雷。Servlet 栈 + 虚拟线程（第 12 章）往往是更省心的替代：写法不变、阻塞自动卸载、吞吐也上得来。

</details>

### 什么时候用 WebFlux，什么时候不该用

| 场景 | 用 WebFlux？ | 理由 |
|---|---|---|
| 高并发长连接、客户端慢、IO 等待长（如 SSE 推送、网关） | 适合 | event loop 不占线程，连接多也不爆线程 |
| 瓶颈是 CPU 计算 | 不适合 | 响应式不加速计算，反而因异步编排增加开销 |
| 链路里有同步 JDBC / 阻塞 API 且改不动 | 不适合 | event loop 被钉死（见上） |
| 团队不熟悉响应式、代码要大量改 `Mono`/`Flux` | 谨慎 | 心智负担高，收益未必覆盖成本 |
| 想提吞吐但保留同步写法 | 用 Servlet 栈 + 虚拟线程 | 写法不变、阻塞自动卸载 |

---

## 16.7 实战：三个真实事故

前面是原理，这节把它变成你能直接套用的排错 SOP。三个事故对应三道门：拦截器门、参数解析门、线程模型门。

### 案例一：拦截器抛异常，@ControllerAdvice 没兜住，返回 500 不是 401

**现象**：订单服务上线后，未登录访问接口返回的是 Tomcat 默认错误页（500），而不是产品预期的 401 JSON。监控里 5xx 告警狂飙，但业务日志没打任何业务异常。

**排查过程**：
1. 看代码，鉴权逻辑在 `AuthInterceptor.preHandle` 里，没登录就 `throw new AuthException("no token")`。
2. 看全局异常处理，确实有 `@ControllerAdvice` + `@ExceptionHandler(AuthException.class)`，本应兜成 401。
3. 关键问题：这个异常是在 `preHandle` 里抛的。`preHandle` 在 DispatcherServlet 内部、HandlerAdapter 调 Controller **之前**。按 16.3 的结论，它能不能被 `@ControllerAdvice` 兜，取决于 Spring 版本和有没有匹配的 handler；而当时项目用的是较老的 Spring（5 之前的行为），`preHandle` 异常直接冒出 DispatcherServlet，Tomcat 兜底成了 500。
4. 即便在 Spring 5 上，如果忘了为 `AuthException` 写 `@ExceptionHandler`，默认行为仍是 500。

**根因**：把"该硬截断的认证失败"当成了"该被统一异常处理兜的业务异常"，搞错了异常该在哪道门被接住。Filter/Interceptor 入口的异常，`@ControllerAdvice` 兜不住或不可靠。

**修复**：鉴权失败不在 `preHandle` 抛异常，而是直接写响应并 `return false` 截断（见 16.3 代码锚点）。需要统一错误体时，让 `preHandle` 里写出的 JSON 和 `@ControllerAdvice` 的格式一致即可。

**教训**：认证这类"入口级、该立刻拒绝"的逻辑，在拦截器/Filter 里直接定响应状态 + 写体最稳，别依赖 `@ControllerAdvice` 把异常兜成 401。把 `@ControllerAdvice` 留给真正的业务异常（Controller 方法执行阶段抛的）。

### 案例二：@RequestBody 嵌套字段类型不匹配，400 但找不到字段

**现象**：前端传了一批订单创建请求，少量返回 400，但告警里只有 `HttpMessageNotReadableException`，没有字段名。前端同学问"到底哪个字段错了"，你答不上来。

**排查过程**：
1. 确认 400 来自 `@RequestBody` 反序列化失败（16.4 讲过，Spring 把 `HttpMessageNotReadableException` 映射成 400）。
2. 看 Spring Boot 默认 `/error` 响应体，只有 `status:400` 和一句 `JSON parse error`，没有字段坐标。
3. 去读 `HttpMessageNotReadableException` 的 **完整 cause 堆栈**：根因是 Jackson 的 `JsonMappingException`，它有 `getPath()`，记录走到 `order.items[2].price` 这个嵌套字段时，字符串 `"abc"` 无法转成 `BigDecimal`。
4. 但默认日志只打了异常类名，没展开 cause 的 path——因为业务代码里 `catch` 时只 `log.error("bad request", e)` 打了顶层，或压根没 catch（交给框架）。

**根因**：Jackson 在 `ArgumentResolver` 内部反序列化，字段路径信息在 `JsonMappingException.getPath()` 里，但默认错误响应和粗略日志都没把它端出来。

**修复**：加一个 `@ExceptionHandler(HttpMessageNotReadableException.class)`，从 `ex.getCause()` 取 `JsonMappingException` 并 `getPath()` 拼出字段路径，返回 `{"error":"bad_field","field":"order.items[2].price"}`（见 16.4 代码锚点）。前端立刻能定位字段。

**教训**：排 `@RequestBody` 400，别只看异常类名，去读 `HttpMessageNotReadableException` 的完整 cause——字段坐标一直在 Jackson 的 path 里。要做"对前端友好"的校验，就自己写这个异常处理器把 path 挖出来；光靠默认 `/error` 永远看不到字段。

### 案例三：WebFlux Handler 里同步查 JDBC，压测时 event loop 线程打满

**现象**：订单查询从 MVC 迁到 WebFlux 想提吞吐，压测时 QPS 不升反降，延迟全红，CPU 不高，线程数卡在核数级（几条 `reactor-http-nio` 线程）。

**排查过程**：
1. `jstack` 抓栈，几条 `reactor-http-nio-*` 线程栈顶全是 `java.net.SocketInputStream.read` / `Socket.read`——阻塞在 JDBC 的 socket 读上。
2. 看代码，Handler 里直接调了团队的同步 `JdbcOrderDao.findById`（一个普通阻塞 JDBC 查询），没有 `subscribeOn` 隔离。
3. 对照 16.6：WebFlux 的 event loop 线程极少，被同步 JDBC 阻塞后无法服务其他连接，吞吐瞬间趴窝。

**根因**：在响应式栈里混入了同步阻塞调用，且没把它挪出 event loop 线程。这是"以为换了响应式框架就快了，但链路里还有阻塞点"的典型翻车。

**修复**：把阻塞 JDBC 调用包进 `Mono.fromCallable(...).subscribeOn(Schedulers.boundedElastic())`，让 event loop 线程只做调度、阻塞发生在独立弹性线程池里（见 16.6 代码锚点）。或者，如果整条链路改不动、还是 JDBC 主导，直接退回 Servlet 栈 + 虚拟线程（第 12 章），写法不变、阻塞自动卸载，吞吐同样上得来，还省了响应式改造的心智成本。

**教训**：WebFlux 的红利前提是"全程非阻塞"。只要链路上有任意同步阻塞点忘了隔离，event loop 就被钉死，比 Servlet 栈更脆。迁 WebFlux 前先问自己：我的 DB 驱动、HTTP 客户端、下游调用，全是响应式的吗？不是，就别硬上，或把阻塞点严格 `subscribeOn` 隔离。

---

## 16.8 本章核心结论

如果这一章你只看这一段：

1. **一次请求过了三道可拦的门**：Filter 门（Servlet 容器层，能改 request/response、能截断）、DispatcherServlet 门（前端控制器，总入口）、Interceptor 门（Spring MVC 层，能拿到 `HandlerMethod`）；之后是参数解析门和异常兜底门。
2. **DispatcherServlet 是前端控制器**：它统一接请求、再调度 HandlerMapping/HandlerAdapter/Resolver，把"路由之后的公共动作"收进框架；Go 是把这些动作分散在每个 handler/中间件里显式写。
3. **Filter 和 Interceptor 不是一回事**：Filter 在容器层、拿不到目标方法；Interceptor 在 MVC 层、能拿 `HandlerMethod`，`preHandle` 返回 `false` 截断、`postHandle` 在渲染前、`afterCompletion` 在 finally 必跑。
4. **参数绑定靠 ArgumentResolver**：`@PathVariable`/`@RequestParam` 取字符串转换，`@RequestBody` 走 `HttpMessageConverter`+Jackson 反序列化；`@RequestBody` 失败报 400，字段路径藏在 Jackson 异常里。
5. **`@ControllerAdvice` 兜的是 MVC 层异常**：Controller 方法、参数解析、返回值处理阶段抛的；兜不住 Filter 层异常，对 Interceptor 入口异常不可全信——认证失败应直接写响应而非抛异常等兜。
6. **WebFlux 是少量 event loop 线程多路复用**：连接多、IO 等待长时吞吐高；但有背压、且**全程必须非阻塞**——混入同步阻塞调用会钉死 event loop，比 Servlet 栈更脆。
7. **WebFlux 不等于虚拟线程**：虚拟线程保你同步写法、阻塞自动卸载；WebFlux 要你改 `Mono`/`Flux` 写法换吞吐。阻塞点改不动时，Servlet 栈 + 虚拟线程往往更省心。

---

## 16.9 深度思考题

### 题 1：如果让你在 Go 里实现"DispatcherServlet 这种总前台 + 参数自动绑定"，你会怎么做？能做到和 Spring 一样吗？

<details>
<summary><b>参考答案</b></summary>

**直接答案：Go 里"总前台"本来就有（gin 的 `Engine` / `http.ServeMux`），但"参数按注解自动绑定成对象"这套需要你自己写绑定逻辑或用框架（gin 的 `c.ShouldBind` 已做了大部分）。完全做到 Spring 那种"按 `@RequestBody`/`@PathVariable` 注解自动选解析器"的程度，gin 的 `ShouldBind`/`ShouldBindJSON` 基本等价，但 Spring 的"运行时按注解动态选 Resolver"是反射+注解体系给的，Go 没有结构化运行时注解，得靠 struct tag + 反射（gin 正是这么干的，tag 如 `uri:"id"` `json:"name"`）。**

**Go 的等价写法：**

```go
type OrderReq struct {
    ID   int64  `uri:"id"`           // 路径参数
    Name string `json:"name"`        // body 字段
}

func GetOrder(c *gin.Context) {
    var req OrderReq
    c.ShouldBindUri(&req)            // 等价于 @PathVariable 绑定
    c.ShouldBindJSON(&req)           // 等价于 @RequestBody 绑定
    // ...
}
```

**和 Spring 的本质差异**：Spring 的绑定是"方法参数上贴注解、框架在调用前自动解析并填参"，你方法签名直接是业务类型；Go 的 `ShouldBind` 是你显式调、把数据填进你传的 struct 指针。前者"声明式、你不在现场"，后者"命令式、你在现场"。能力上 gin 覆盖了 90% 场景，但 Spring 那种"HandlerMethodArgumentResolver 可插拔、可自定义解析器"的扩展性是 Go 框架少有的——你要在 Go 里加"自定义参数来源"，得自己写中间件往 `c.Set` 塞、 handler 里取，没有 Spring 那种"写个 Resolver 注册进容器就全局生效"的机制。

**更深一层**：Go 能用 struct tag + 反射做到"参数自动绑定"的八成，但"运行时按注解动态编排一整套解析器链"是 Java 反射/注解体系的特产。你从 Go 过来会觉得 gin 的 `ShouldBind` 已经够爽，只是少了 Spring 那种"框架替你在调用栈里悄悄把参数填好"的隐式；而这隐式的代价，就是 16.4 那个"@RequestBody 400 看不到字段"的排错黑箱。

</details>

### 题 2：HandlerInterceptor 的 afterCompletion 为什么放在 finally 里、且总能跑？它和 postHandle 的最大区别是什么？

<details>
<summary><b>参考答案</b></summary>

**直接答案：afterCompletion 在 DispatcherServlet 的 finally 块里调用，无论 Controller 成功、抛异常、还是 preHandle 返回 false 截断，只要 preHandle 已经对某个拦截器返回过 true，它的 afterCompletion 就会跑——它是清理现场（释放资源、上报埋点、清 ThreadLocal）的最后一环。postHandle 不一样：它在 Controller 方法执行之后、视图渲染之前调用，一旦 Controller 抛了异常走异常通道，postHandle 根本不会被调到（异常处理不走"正常返回"分支）。**

**代码锚点（DispatcherServlet 的语义）：**

```java
// 伪代码表达 DispatcherServlet.doDispatch 的拦截器调用顺序
try {
    if (!mappedHandler.applyPreHandle(req, res)) return;   // preHandle 全 true 才继续
    mv = ha.handle(req, res, handler);                     // 调 Controller
    mappedHandler.applyPostHandle(req, res, mv);           // 成功才到这
} catch (Exception ex) {
    dispatchException = ex;                                // 异常被记下，走异常通道
} finally {
    mappedHandler.triggerAfterCompletion(req, res, dispatchException);  // 总能跑
}
```

**区别的本质**：postHandle 是"正常流程的尾巴"，前提是没有异常；afterCompletion 是"无论如何都收尾"，前提是该拦截器的 preHandle 曾返回 true（因为只对已通过的拦截器负责清理）。所以你要"无论成败都做"的事（如链路追踪结束、MDC 清理）放 afterCompletion；要"基于 Controller 返回值改点什么"（如统一往 Model 塞数据）才放 postHandle。

**更深一层**：这个设计把"清理"和"加工"分开了。Go 的中间件里你用 `defer` 做清理、用 `c.Next()` 之后做加工，其实是一个意思——`defer` 对应 afterCompletion（总能跑），`c.Next()` 之后对应 postHandle（正常才到）。只是 Go 的 `defer` 是语言级保证、你写的时候就在现场；Spring 的 afterCompletion 是框架在 finally 里调、你只声明"我有这个拦截器"。又一次显式 vs 隐式。

</details>

### 题 3：WebFlux 的背压真的能防止内存溢出吗？如果消费者一直不 request，生产者会怎样？

<details>
<summary><b>参考答案</b></summary>

**直接答案：背压能把"生产快、消费慢"从"无脑猛推撑爆内存"变成"反向节流"——生产者按消费者的 `request(n)` 节奏发，消费者迟迟不 request，生产者就停在原地等（不积压、不 OOM）。但背压只约束"遵守 Reactive Streams 协议的响应式生产者"；如果你的数据源本身是阻塞的、非响应式的（比如一次性 `List` 查出来、或阻塞 JDBC 全量吐），背压根本管不到它，内存照样爆。背压不是银弹，它管得了"流"，管不了"你已经全量加载进内存的那坨"。**

**机制锚点——Reactive Streams 的 request 协议：**

```java
// 消费者通过 Subscription.request(n) 向上游要 n 个，上游最多发 n 个
// 上游（Publisher）必须实现：收到 request(n) 才发，且发的数量 <= n
Flux.range(1, 1_000_000)          // 一百万个元素
    .subscribe(new BaseSubscriber<Integer>() {
        @Override
        protected void hookOnSubscribe(Subscription s) {
            request(1);           // 一次只要 1 个，处理完再要下一个
        }
        @Override
        protected void hookOnNext(Integer value) {
            slowProcess(value);   // 消费慢
            request(1);           // 处理完才再要 1 个 => 上游被节流
        }
    });
```

**如果消费者一直不 request**：上游收到 0 个 request，按规范不能发任何元素，于是上游停住、背压生效、无积压。这正是背压防止 OOM 的方式——它不是"丢了数据"，是"按消费能力节流"。

**坑：背压管不到非响应式源**：`Flux.fromIterable(blockingRepo.findAll())` 这种，数据是 `findAll()` 一次性查进内存的，`Flux` 只是包了一层壳，背压对"已经全量在内存里的 List"无能为力。要真享受背压，数据源得是响应式的（如 R2DBC 驱动、响应式消息队列），能在"被 request 时才去拉下一批"。

**更深一层**：背压是"响应式流"这套协议给的能力，前提是整条链都遵守协议。WebFlux 的卖点之一是"数据从源头到响应全程背压可控"，但只要你链上有一个非响应式阻塞点（案例三的 JDBC 就是），背压的保证从那一点就断了。这和第 12 章虚拟线程的对照再次出现：虚拟线程不要求你改数据源、不要求全链响应式，阻塞自动卸载；WebFlux 的整套红利（含背压）都要求你"全链响应式"。代价与收益，一目了然。

</details>

### 题 4（开放题，无标准答案）：你的下一个服务，该用 Servlet 栈还是 WebFlux？

> 【思考】
>
> 这道题没有标准答案，但从本章你能推出来了。给你几个判断锚点：
> - 你的瓶颈是"连接多、客户端慢、长轮询/SSE"吗？是 → WebFlux 有戏。
> - 你的 DB 是 JDBC/hibernate 同步查、下游是普通 `RestTemplate` 吗？是 → WebFlux 要么全改响应式，要么把阻塞点 `subscribeOn` 隔离，否则 event loop 饿死。
> - 团队熟响应式吗？不熟 → 改 `Mono`/`Flux` 的心智成本可能高于收益。
> - 你只是想提吞吐、代码不想大改 → Servlet 栈 + 虚拟线程（第 12 章）往往是最优解：写法不变、阻塞自动卸载。
>
> 想清楚这些，你会发现：WebFlux 不是"新版 Servlet"，是"另一种编程模型"。它解决的是特定问题（海量连接 + 全链非阻塞），不是"让所有服务都更快"。你从 Go 过来，Go 的 `net/http` 本身就是"每请求一 goroutine"的轻量模型，和 Servlet 栈 + 虚拟线程同构；Go 没有 WebFlux 这种"显式响应式"的主流需求，正是因为 goroutine 已经把"每请求一线程"的开销压到极低。这反而是 Go 比 Java 早解决好的一个问题。

<details>
<summary><b>参考答案</b></summary>

**直接答案：默认选 Servlet 栈（Spring MVC）+ 虚拟线程；只有当你确认"瓶颈是海量长连接/慢客户端、且整条调用链能全响应式"时，才上 WebFlux。绝大多数业务 CRUD 服务，Servlet 栈 + 虚拟线程在"写法不变"的前提下就能拿到够用的吞吐，且避开了 event loop 饿死的雷。**

**分场景给结论**：

- CRUD / 内部 API / 瓶颈在 DB：Servlet 栈 + 虚拟线程。DB 还是 JDBC 阻塞查，但虚拟线程阻塞时自动卸载载体线程，线程数不再是天花板，吞吐够用，代码零改动。
- 网关 / SSE 推送 / 海量长连接：WebFlux 更合适，event loop 不占线程，几万连接也不爆线程。但要保证下游（转发、鉴权调用）也是响应式的。
- 迁 WebFlux 但里面还是 JDBC：别，要么把阻塞点严格 `subscribeOn(Schedulers.boundedElastic())` 隔离，要么退回 Servlet 栈 + 虚拟线程。

**和 Go 的同构**：Go 的 `http.Server` 每条连接一个 goroutine，goroutine 轻量到你可以"无视线程数"，所以 Go 几乎从不需要 WebFlux 这种显式响应式。Java 因为平台线程贵，才演化出"每请求一线程（Servlet，靠线程池顶）"和"少量 event loop 多路复用（WebFlux）"两条路；虚拟线程的出现让 Java 也接近了 Go 的"轻量每请求一线程"模型。所以 2023 年后的新项目，Servlet 栈 + 虚拟线程往往是比 WebFlux 更省心的默认。

**更深一层**：选型不是"追新"，是"匹配瓶颈"。WebFlux 解决的是 Servlet 栈在"海量连接 + 长 IO 等待"下的线程数天花板，但它用"改写法换吞吐"作代价；虚拟线程用"改 JVM 调度、不改写法"消掉了同一个天花板。当虚拟线程可用时，WebFlux 的适用面被大幅压缩——除非你还要响应式流的背压（那是 WebFlux 独有、虚拟线程给不了的能力）。所以真正让 WebFlux 值得上的理由，往往不是"更快"，而是"背压 + 海量连接"这两个具体需求同时成立。

</details>

---

## 下一章预告

第 17 章讲 **数据库层：JDBC 的本质、连接池 HikariCP、声明式事务 @Transactional、Spring Data JPA**。它接在第 16 章之后——你这章看到 `OrderController` 里 `@Autowired` 进来的 `OrderService` / `OrderRepository`，它们背后到底怎么连上数据库、SQL 从哪来、事务怎么开。

第 14 章你学过 `@Transactional` 是 AOP 代理实现的，第 16 章案例三你看到同步 JDBC 在 WebFlux 里会钉死 event loop——第 17 章会把这些点收口：`DataSource` 是谁（HikariCP）创建的、`Connection` 在事务里怎么被同一个线程复用、`@Transactional` 的代理在数据库层到底干了什么、以及为什么"事务方法里又开了一个新连接"会莫名其妙不生效。读完第 16 章的"请求走到 Controller"，第 17 章会带你往下钻一层：Controller 之后，请求是怎么落到磁盘上的。
