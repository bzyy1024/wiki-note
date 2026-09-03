# 第 4 章 API Server：唯一的真理之门

> 墨：老哥，上一章我们说 K8s 是"一堆控制器 + 一块共享状态板 + 一个状态入口"。这章拆"状态入口"——API Server。我先问你：既然状态都存在 etcd 里，**凭什么不让所有组件直接连 etcd 读写？** 加个 API Server 在中间，不脱裤子放屁吗？

---

## 4.1 第一问：为什么不能直接连 etcd？

etcd 是个 KV 存储，K8s 的状态确实躺在里面。那最朴素的设计：所有组件（调度器、控制器、kubelet）直接连 etcd，想读读想写写。简单吧？

**墨：你觉得直接连会出什么乱子？** 你先列三条，再往下看。

### 4.1.1 问题一：谁都能写，状态就烂了

etcd 不知道"Pod 该长啥样"。如果 kubelet 和调度器和控制器都能随意改 Pod 对象，没有任何规则，那"Pod 的 nodeName 被 kubelet 改了、调度器又改回去"这种冲突会满天飞。状态板会变成涂鸦墙。

### 4.1.2 问题二：没有"身份"和"权限"

etcd 的访问控制很粗。但 K8s 需要的是"这个 ServiceAccount 只能读这个 namespace 的 Pod"。直接在 etcd 上做这种细粒度授权，等于把业务语义（namespace、role、resource）塞进存储层——存储层根本不该懂这些。

### 4.1.3 问题三：没有"验证"和"副作用"

你 `apply` 一个 Pod，K8s 要干很多事：检查字段合法吗？该不该自动加默认字段？该不该因为策略拒绝？该不该写审计日志？该不该触发别的逻辑？这些"写之前的处理"如果散在各组件里，每个组件都重写一遍，立刻乱套。

### 4.1.4 问题四：etcd 扛不住"万人围观"

etcd 是强一致存储，**写吞吐有限**（第 5 章细讲）。如果上千个客户端都来 watch 它的 key 变化，etcd 自己会先跪。状态变更的通知（watch）必须有个"缓冲+分发"层。

**所以：etcd 只管"可靠地存"，API Server 管"谁、能不能、怎么改、通知谁"。** 这就是加这扇门的理由。API Server 是**所有读写的唯一入口（front door）**，是集群的"真理之门"——etcd 是后厨，API Server 是前台，谁点单都得经过前台。

> **设计原则：存储层只负责"存得可靠"，所有"业务规则、身份、权限、校验、通知"都收口在一个门面后面。** 这其实是所有大系统的通用套路：数据库之上必有应用层。K8s 把这个应用层叫 API Server，并且它是整个系统唯一允许碰 etcd 的进程。

---

## 4.2 API Server 到底干了几件事？

拆开看，一个请求打进 API Server，要经过一条流水线（你写 Web 框架的中间件也这个套路）：

```
请求 → 认证(Authentication) → 鉴权(Authorization) → 准入控制(Admission) → 校验/默认值 → 写 etcd → 返回
```

我们分别拆。先记住一句话区分前三个容易混的概念：

- **认证**：你是谁？（identity）
- **鉴权**：你被允许做这事吗？（permission）
- **准入**：就算你被允许，这请求的内容合规吗？要不要改？（policy / mutation）

**墨：你说"认证解决你是谁"，那如果连"你是谁"都不知道（匿名请求）呢？**

K8s 默认拒绝匿名写，但允许部分匿名读（如健康探针）。认证失败 = 401；鉴权失败 = 403。这两个状态码你排障时天天见，现在你知道它们对应流水线的哪一环了。

---

## 4.3 认证（Authentication）：你是谁

认证回答"调用者身份"。K8s 支持多种"凭证"，按场景分：

### 4.3.1 人类 / 外部系统：客户端证书、Token、OIDC

- **客户端证书（X.509）**：`kubectl` 用的 kubeconfig 里那串证书，就是证明"我是 admin"的。API Server 用 CA 校验证书真伪，并从证书里的 CN/O 字段提取用户名和组。这是最硬核的方式——证书丢了就完了，所以要好好管。
- **静态 Token / Bootstrap Token**：简单场景用，不推荐大规模。
- **OIDC（OpenID Connect）**：接企业的身份提供商（如 Azure AD、Google）。 humans 登录后拿 ID token，kubectl 带着它访问。**这是生产推荐**——因为身份归公司统一管，离职销号即可，不用挨个撤销集群证书。

**墨：你公司用 SSO 登录各种系统吧？OIDC 接入 K8s 和你登录内部平台，是不是一回事？**

一模一样。都是"身份在中心管，应用只验证 token"。K8s 不自己存密码，它只信任 OIDC 颁的 token——这叫**把认证外包给专业系统**，自己不做重复造轮子。又是关注点分离。

### 4.3.2 Pod 内部：ServiceAccount（SA）

Pod 里的进程（比如你写的要调用 K8s API 的 Go 程序）怎么证明自己？用 **ServiceAccount**。每个 namespace 有默认的 SA，Pod 被挂载一个 **token 文件**（在 `/var/run/secrets/kubernetes.io/serviceaccount/token`）。这个 token 是 API Server 签的、限期的（旧版是永久的，后面演化我们讲）。

**演化重点（请你记）：** 早期 SA token 是**永久、不过期**的，写死在 Secret 里。丢了就永久有效，极危险。后来引入 **TokenRequest API（Projected ServiceAccount Token）**：token 由 API Server 动态签发、可设有效期（默认 1 小时）、可绑定 Pod（Pod 删了 token 失效）。这是 K8s 安全上的一次重要修正——**从"永久凭证"走向"短期、绑定身份的凭证"**，跟云厂商的临时 STS token 一个思路。

### 4.3.3 节点：kubelet 的凭证

kubelet 也是 API Server 的客户端，用客户端证书证明"我是节点 node-7"。它只被授权操作自己节点相关的对象（通过 NodeRestriction 准入）。

---

## 4.4 鉴权（Authorization）：RBAC

认证知道"你是张三（属于 dev 组）"，鉴权决定"张三能不能删生产 namespace 的 Pod"。K8s 有多种鉴权模式，主流是 **RBAC（基于角色的访问控制）**。

### 4.4.1 RBAC 的三个核心对象

- **Role / ClusterRole**：定义"一组权限规则"。比如"能 get/list/watch/create Pod"。ClusterRole 是集群级（跨 namespace），Role 是 namespace 级。
- **RoleBinding / ClusterRoleBinding**：把"角色"绑给"用户/组/SA"。Binding 是"谁拥有这些权限"的声明。

**墨：为什么是"角色"和"绑定"分开，而不是直接写"张三能删 Pod"？**

这是 RBAC 的经典设计：**权限（role）和身份（who）解耦**。你改权限只改 Role，不用动每个用户；人离职只删 Binding，不用改 Role。就像公司职级（role）和"谁在这个职级"（binding）分开——升职是改 binding，改职级定义是改 role。扩展性天差地别。

### 4.4.2 RBAC 规则长啥样（你扫一眼语义）

```
rule:
  apiGroups: [""]          # core 组
  resources: ["pods"]      # 资源
  verbs: ["get","list","watch","create","delete"]
```
一条规则 = "在哪些 apiGroup 的哪些资源上，能做哪些动作"。精细化到这种程度，你就能写出"只读 Pod 但不能删""只能管自己 namespace 的 ConfigMap"这种策略。

**⚠️ 坑：** `verbs: ["*"]` 和 `resources: ["*"]` 是"给超能力"，生产里给人乱绑 cluster-admin 是常见事故源。最小权限原则（least privilege）在 K8s 里不是口号，是排障和安全的分界线。

### 4.4.3 演化：ABAC → RBAC

最早 K8s 用 **ABAC（基于属性的访问控制）**，规则写在一个静态 JSON 文件里，改规则得重启 API Server、而且不区分 namespace。太僵了。RBAC 把规则变成**集群里的 API 对象**（Role/Binding 本身就是 K8s 资源），于是"授权"也能用声明式管理、也能 GitOps——你改权限也是 `kubectl apply` 一个 YAML。这又是"用 K8s 自己管理 K8s"的自举（bootstrap）思想。

---

## 4.5 准入控制（Admission）：最被低估的一环

**墨：你认证过了、鉴权也过了，API Server 就直接写 etcd 了吗？** 不一定。

准入控制是"鉴权之后、写库之前"的一段**可编程关卡**。它的特殊之处在于：它看的是**请求内容本身**，而且**能改内容（mutating）也能拒（validating）**。

两类 webhook：

- **Mutating Admission**：改请求。比如自动给所有 Pod 注入 sidecar（Istio 就是这么干的）、自动加默认资源请求、自动打标签。
- **Validating Admission**：只校验不修改。比如"生产 namespace 禁止 latest 镜像""必须有 resource requests"。不合规直接拒绝（返回 403 类错误）。

还有一堆**内置准入控制器**（编译进 API Server）：
- `LimitRanger`：给没设资源限制的 Pod 补默认值/上限；
- `ResourceQuota`：限制 namespace 总资源，超了拒绝；
- `PodSecurity`（取代老 PSP）：强制 Pod 安全标准；
- `NamespaceLifecycle`：不能往正在删除的 namespace 创建对象；
- `ServiceAccount`：自动挂载 SA token。

**墨：准入和鉴权有啥不同？一个说"你不允许"，一个说"这事不合规"——听着像一回事？**

区别在于**视角**：鉴权看"**主体**有没有权限做这类动作"（张三能不能 create pod）；准入看"**请求对象**本身合不合规"（这个 pod 用了 latest 镜像，违反策略）。而且**准入能改对象**——鉴权只能放/拒。再说个要害：**准入能基于对象内容做决策，而对象内容鉴权看不到**（鉴权只看 resource+verb）。所以准入是"内容级策略"，鉴权是"动作级权限"，两道不同的门。

**演化看点（极重要）：** 早期没有可编程准入，想加策略只能改 API Server 源码或等官方加内置控制器。后来有了 **Admission Webhook**：你起一个 HTTPS 服务，API Server 把请求转发给你，你返回"改/拒/过"。这一下把"集群策略"的扩展权交给了用户——就像 CRD 把"数据模型"扩展权交出去。第 14 章我们会看到，Istio、Kyverno、Gatekeeper 这些全靠 admission webhook 活着。**API Server 用"把决策外包成 webhook"的方式，再次把核心做成可扩展的。**

---

## 4.6 版本化与兼容性：为什么 K8s 升级不崩

**墨：你写过要"向前兼容"的 API 吧？K8s 这种跑在全球无数集群上的系统，怎么保证"老客户端"在新版本上还能用？**

这是 API Server 设计里最见工程功力的一块。K8s 用 **Group/Version/Kind（GVK）** 给每个资源定身份：

- **Group**：资源分组，比如 `apps`、`networking.k8s.io`；
- **Version**：版本，`v1`（稳定）、`v1beta1`（测试）、`v2alpha1`（预览）；
- **Kind**：类型，`Deployment`、`Pod`。

### 4.6.1 为什么要有版本？

因为对象结构会变。比如 Deployment 的字段可能从 `v1beta1` 加到 `v1`。K8s 的做法是：**同一类资源可以同时存在多个版本（如 `apps/v1beta1` 和 `apps/v1` 并存），API Server 负责在内部存储格式和外部版本之间做转换（conversion）。** 老客户端继续用 `v1beta1` 读写，新客户端用 `v1`，API Server 在中间翻译。

### 4.6.2 废弃（Deprecation）策略：给用户缓冲

K8s 的铁的纪律：**一个 API 版本要废弃，必须先保留至少两个小版本（N 和 N+1 都支持，N+2 才移除）**，且移除前大喊大叫（告警、文档）。这样你升级集群时，不会因为"某个字段没了"而全崩——你有充足时间把 YAML 从 `v1beta1` 迁到 `v1`。

**演化实例：** `extensions/v1beta1` 的 Ingress 被废弃，迁到 `networking.k8s.io/v1`。很多人拖着不迁，升级到某个版本后 Ingress 突然 404——这就是没听废弃警告的代价。**这背后是"兼容性 vs 演进"的永恒权衡**：K8s 选择"慢废弃、长过渡"，宁可背着历史包袱，也要保护全球集群不崩。**

### 4.6.3 转换 webhook 与 CRD 版本

你自己定义的 CR（第 14 章）也能有多个版本，API Server 支持你挂一个 **conversion webhook** 来做版本间翻译。这是把"官方资源的版本机制"原样开放给用户。一以贯之：核心能力对用户平等开放。

---

## 4.7 List-Watch：控制器怎么"实时"看到变化

第 3 章说控制器靠"观测实际状态"工作。它怎么观测才不拖垮系统？答案是 **List-Watch** 机制，这是 API Server 给客户端的高效订阅方式：

- **List**：首次连上，全量拉一次某个资源（带 `resourceVersion`）；
- **Watch**：之后长连接挂着，API Server 把**增量事件**（ADDED/MODIFIED/DELETED）推给你。

客户端（用 client-go 的 **Informer**）把事件维护成本地缓存（store）。于是控制器读状态**根本不打 API Server**——它读自己内存里的缓存，又快又省。只有缓存没命中才回源。

**墨：这像不像你写过的"全量同步 + 增量订阅"？比如消息推送、配置中心？**

完全一样。etcd 自己有 watch，但 API Server 在前面做了一层**多路复用 + 缓存**：几千个客户端 watch 同一个资源，API Server 自己只在 etcd 上开少量 watch，再把事件分发给所有人。否则几千个客户端直连 etcd watch，etcd 早跪了（回到 4.1.4）。**这就是加 API Server 当"门"的另一个硬理由：它是 watch 的扇出层（fan-out）。**

> **架构套路提炼：** 当 N 个消费者都想订阅一份状态变更，别让存储层直接面对 N 个 watch。在前面放一个"缓存 + 扇出"层，它自己只跟存储保持少量连接，再把事件分发给 N 个消费者。这是消息系统、配置中心、K8s 通用的解法。

---

## 4.8 审计（Audit）：谁动了什么

生产排障和安全回溯需要"谁在几点对哪个对象做了什么"。API Server 有 **审计日志**，按阶段（RequestReceived / ResponseStarted / ResponseComplete / Panic）记录每个请求的主体、动作、资源、响应码。可以打到文件或外部 SIEM。

**墨：你说审计和"准入/鉴权"日志有啥关系？**

它们是不同层：鉴权失败记一条"拒绝"，审计记"这次请求的完整事实"。审计是用来**事后回溯**的（"昨晚谁删了生产库？"），鉴权是用来**事前拦截**的。一个防守，一个取证。

---

## 4.9 Aggregated API Server：把"门"也变成可扩展的

API Server 还有一手：它支持 **Aggregation Layer**——你可以挂一个**自己写的 API Server**（比如_metrics 的扩展 API、或者自家 CRD 的某些高级接口），作为"扩展 API 组"挂在核心 API Server 后面。客户端访问 `apis/mycompany.example.com/v1`，请求被核心 API Server 转发到你的扩展 API Server。

**意义：** 核心 API Server 不必包含所有功能。它提供"统一入口 + 认证鉴权复用 + 发现机制"，具体逻辑可以外包给别人。这正是"门面模式（Facade）"+"插件化"的组合——**入口统一，实现可插**。第 14 章 CRD 是更轻量的扩展，Aggregated API 是重量级的（你自己起服务）。

---

## 4.10 本章演化线小结

- 认证：永久 SA token → 短期 Projected Token（绑定 Pod、可过期），走向"临时凭证"；
- 鉴权：ABAC（静态文件、无 namespace）→ RBAC（规则成对象、可声明式管理）；
- 准入：内置写死 → Admission Webhook（策略可编程、外包给用户）；
- 版本：单版本 → GVK 多版本并存 + 转换，配合"慢废弃长过渡"的兼容纪律；
- 入口：单一 API Server → 支持 Aggregated API（门面可扩展）；
- watch：直连 etcd → API Server 缓存扇出（List-Watch + Informer）。

你会发现一条贯穿主线：**API Server 把"身份、权限、策略、版本、订阅"全部收口，然后又把"策略"和"扩展"依次外包成 webhook / 聚合层——它在"集中管控"和"开放扩展"之间反复找平衡。**

---

## 4.11 本章思考题

### 🔧 思考题 1
如果去掉 API Server，让所有组件直连 etcd，且你用乐观锁（resourceVersion）解决写冲突，你觉得还有哪 3 个问题乐观锁解决不了？

**【参考答案】**
乐观锁只解决"同时写同一对象"的冲突，解决不了：(1) **语义校验缺失**：etcd 不懂 Pod 长啥样，谁都能写个字段非法的对象，状态板被污染；(2) **权限缺失**：etcd 做不了"dev 组只能读 dev namespace"这种细粒度 RBAC，等于集群裸奔；(3) **watch 扇出瓶颈**：上千客户端直连 etcd watch，etcd 写吞吐本就有限，会被 watch 压垮；(4) **无审计/无准入副作用**：写之前没法注入 sidecar、没法拒 latest 镜像、没法留痕。乐观锁只是"不写串"，但这些"业务规则"它一概不管——所以必须有 API Server 这层应用逻辑。

### 🔧 思考题 2
Mutating Admission 能"改请求内容"。如果集群里挂了 3 个 mutating webhook，都给 Pod 加环境变量，且第二个挂了（超时），会发生什么？API Server 怎么处理失败的 webhook？

**【参考答案】**
这是生产真坑。每个 mutating webhook 可配 `failurePolicy`：`Fail`（默认对多数关键 webhook）= webhook 出错则**整个请求失败**（拒绝创建）；`Ignore` = 出错就跳过这个 webhook 继续。所以如果第二个 webhook 超时且 failurePolicy=Fail，那个 Pod 创建直接被拒，用户看到的是"创建失败，因为准入 webhook 无响应"。如果设 Ignore，则跳过它，Pod 照样创建但少了它该注入的东西（可能悄悄出问题）。启示：(1) webhook 必须高可用，否则它挂=集群写入口被卡；(2) failurePolicy 选 Fail 还是 Ignore 是"严格"vs"可用"的权衡；(3) mutating webhook 串行执行、顺序敏感（前面改的后面能看到），出问题时排障要按配置顺序逐个看。这又是"扩展能力带来可用性风险"的典型。

### 🔧 思考题 3
RBAC 里，为什么"给用户绑定 ClusterRole"要用 ClusterRoleBinding，而不能用 RoleBinding 跨 namespace？这设计想防什么？

**【参考答案】**
RoleBinding 把角色绑到**某个具体 namespace**，作用域锁死在那个 namespace；ClusterRoleBinding 才是集群级绑定。如果允许 RoleBinding "跨 namespace 引用 ClusterRole"，语义就乱了：ClusterRole 是集群级权限，但 RoleBinding 是 namespace 级——到底权限范围多大？K8s 用"绑定对象的种类决定作用域"来保持清晰：想给全局权限就用 ClusterRoleBinding，想给某 ns 权限就在该 ns 建 RoleBinding（可引用 ClusterRole 限定到本 ns）。这设计防的是"权限作用域歧义"——安全系统里，权限边界必须一眼能看清，不能出现"我以为只在 A ns，其实全局生效"的错觉。这也是最小权限原则在工程结构上的体现。

### 🔧 思考题 4（进阶）
K8s 的"慢废弃、长过渡"策略（保留 2 个版本才移除）保证了兼容，但代价是代码里长期背着历史包袱。如果你是 K8s 维护者，会在什么信号下决定"这次真要删掉老版本了"？你怎么衡量"该弃坑"？

**【参考答案】**
信号组合：(1) **使用率 telemetry**：官方看匿名统计/社区反馈，老版本 API 调用占比已极低（如 <1%）；(2) **文档与告警已喊够久**： deprecated 告警持续若干个版本，用户有充足迁移窗口；(3) **维护成本 > 收益**：老版本和新版本并存要写 conversion、要测兼容、要修老 bug，成本超过照顾少数用户的收益；(4) **有清晰的迁移路径**：新版功能等价且工具自动迁移（如 `kubectl convert`）。衡量"弃坑"本质是算 **(继续兼容的成本) vs (破坏少数用户的风险)**。K8s 的取向明显偏"保护用户、慢弃坑"，所以即便背着 `apps/v1beta1` 这类包袱也宁可多留。反过来启示：做你自己的系统时，API 兼容性承诺是"负债"，承诺越硬，演化越慢——所以公开 API 要尽量稳定，内部 API 可以大胆重构。

---

## 4.12 小结

- etcd 只管存，API Server 是统一读写入口，承担身份/权限/校验/通知；
- 认证（你是谁）→ 鉴权 RBAC（你能不能）→ 准入（请求合不合规、能不能改）；
- SA token 从永久走向短期绑定，是安全上的重要修正；
- 准入 webhook 把"策略"外包给用户，是平台化的关键一跃；
- GVK 多版本 + 慢废弃，让全球集群升级不崩，体现"兼容 vs 演进"的权衡；
- List-Watch + Informer 让控制器读状态不打 API Server，API Server 是 watch 扇出层；
- Aggregated API 把"门"本身也做成可插。

下一章，我们进后厨——**etcd**。API Server 背后那块"必须一致、必须持久、还必须快"的状态板，到底是怎么既可靠又不崩的。
