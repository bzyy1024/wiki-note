# 第 8 章 Pod 与容器运行时：为什么是 Pod，不是容器

> 墨：老哥，这一章先抛一个你大概率从没认真想过的问题——**K8s 调度的最小单位是 Pod，不是容器。为什么？** 容器不是已经够"小"了吗？为什么还要在外面套一层 Pod？这层套得值不值？今天扒开。

---

## 8.1 如果只调度容器，会卡在哪

设想你要部署一个 Web 服务，它旁边必须有个"日志收集进程"和"配置热加载进程"——这三个进程**必须同一台机器、共享同一个网络端口空间、共享同一块磁盘**。如果 K8s 调度的是"单个容器"：

**墨：你说，我把这三个容器各调度一次，能不能保证它们永远在同一台机器、共享网络？**

很难，而且很脆：

- 三个容器分别调度，可能落三台机器，它们要通信就得走网络，延迟和复杂度上来；
- 它们想"共享同一个 localhost 端口"（比如日志进程监听 127.0.0.1:9000 给主进程发），跨机器做不到；
- 它们想"共享同一块内存/IPC"做进程间通信，跨机器更不行；
- 你想"这三个一起扩、一起缩、一起死"，但调度器眼里它们是三个独立的东西，没法当整体管。

**所以 K8s 引入了 Pod：一组"必须同生共死、亲密无间"的容器的包裹。** 调度的最小单位变成这个包裹，保证里头的容器永远在同一节点、共享网络命名空间、可共享存储卷。

> **核心洞察：调度的"单位"必须等于"部署的原子单位"。** 如果你的应用天然是"一组协作进程"，那原子单位就得是"一组"，不能是"一个"。Pod 就是"一组协作进程"的建模。这跟操作系统里"进程组 / 线程组"的思想同源——调度线程组而不是单线程，因为有共享上下文。

---

## 8.2 Pod 是怎么让容器"共享"的：pause 容器

**墨：Pod 里多个容器，怎么做到"共享同一个网络栈"？Linux 的 network namespace 是 per 进程的，谁先建、谁持有？**

妙处在 **pause 容器（也叫 infra 容器 / 沙箱容器）**。当你创建一个 Pod，kubelet 第一步起的不是你的业务容器，而是一个**极简的 pause 容器**（它几乎啥也不干，就 `pause()` 系统调用睡在那）。这个 pause 容器**率先创建 Pod 的 network namespace、IPC namespace 等**。

然后你的业务容器（容器 A、B、C）启动时被指定**加入 pause 容器已经建好的那些 namespace**（用 `--network=container:<pause>`、`--ipc=container:<pause>`）。于是：

- A、B、C 看到的是**同一个网络栈**——它们 `localhost` 互通，能绑同一个端口（当然得错开端口）；
- 它们共享 IPC，能做进程间通信；
- 它们通过挂载**同一个 Volume**，看到同一份文件。

**pause 容器是"锚点"**：它生命周期最长（Pod 不删它不退出），所有业务容器都挂在它的 namespace 上。哪怕业务容器全崩了、重启，namespace 还在（pause 在），重建的容器仍加入同一个网络。等到 Pod 要删，pause 先退出，整个 namespace 才销毁。

**墨：为什么非得有个 pause，不能直接让容器 A 建 namespace、B/C 加入 A？**

因为 A 可能崩。如果 A 是 namespace 持有者，A 一挂 namespace 可能随之清理（取决于怎么建），B、C 就失联。pause 专门用来"只持有资源、绝不干业务、几乎不会崩"，把"基础设施生命周期"和"业务逻辑生命周期"解耦。**设计上"用最稳定的那个当锚"是常见套路**——就像船靠码头，码头（pause）不动，船（业务容器）来了走了。

**生活化类比：** Pod 像一套**合租房**。pause 容器是这套房的"门牌号和电表水龙头总闸"（基础设施），你的业务容器是房客。房客来来去去（重启），门牌号和水电表（网络/IPC）一直都在。合租户之间能用同一套水电、能互相串门（localhost 互通），但不能随便搬到别的楼（别的 Pod 的 namespace）。

---

## 8.3 Pod 内共享什么、不共享什么

明确边界，排障有用：

**共享的（因为同一 namespace / 挂载）：**
- 网络（IP、端口、localhost、DNS 设置）；
- 某些存储卷（你显式 `volumeMounts` 挂同一个 volume 的部分）；
- IPC（同一 IPC namespace，可 System V IPC / POSIX 信号量通信）。

**不共享的（默认隔离）：**
- **文件系统**：每个容器有自己的 rootfs（镜像层），除非挂同一个 volume；
- **进程空间**：容器 A 看不到容器 B 的进程列表（除非共享 PID namespace，少见）；
- **资源限制**：每个容器独立设 requests/limits（第 15 章），不是整个 Pod 一个总限——**注意这点坑**：Pod 没有"总 CPU 限额"，是容器各自限，调度看的是容器 requests 之和。

**墨：你说"Pod 没有总资源限额"，调度器怎么算这个 Pod 要多少资源？** 调度器把 Pod 里所有容器的 **requests 求和**，作为整个 Pod 的资源需求去过滤节点（第 6.3）。所以你不给某个容器设 requests，它按 0 算，可能把 Pod 塞进其实装不下的节点——又是"不写 requests 的坑"（第 15 章炸）。

---

## 8.4 CRI：把"运行时"从 K8s 里摘出去

**墨：你用 Docker 跑容器，K8s 直接调 Docker 不就完了？为什么中间插个 CRI？**

历史真相最有教益。早期 K8s 确实内置了对 Docker 的直连代码（叫 **Dockershim**）。但问题来了：

- Docker 的接口（dockerd）**不是为 K8s 设计的**，功能冗余（build、swarm 等 K8s 都用不上）；
- K8s 真正要的只是"创建/启动/停止/删除容器 + 管理镜像"这一小撮；
- 而且 K8s 想支持**多种运行时**（containerd、CRI-O、甚至安全沙箱如 gVisor/Kata），不想绑死 Docker。

于是 K8s 定义了 **CRI（Container Runtime Interface）**：一组 gRPC 接口（ `RuntimeService` 管容器生命周期，`ImageService` 管镜像）。任何运行时只要实现 CRI，就能给 K8s 用。**kubelet 只调 CRI，不认得 Docker 还是 containerd。**

### 8.4.1 Dockershim 的移除（重大演化事件）

**墨：那 Dockershim 后来怎么了？**

K8s 1.24（2022）**正式移除 Dockershim**。从此 kubelet 不再内置对接 Docker 的代码。原因是：Docker 本身不直接实现 CRI，K8s 得在中间垫一层 Dockershim 去翻译——这层是"技术债"，维护成本高、易出 bug。而 containerd 和 CRI-O **原生实现 CRI**，直接对接更干净。

**影响与误解澄清：** 很多人吓一跳"K8s 不用 Docker 了？我的镜像怎么办？"——**镜像照用**。OCI 镜像格式是标准，containerd 一样跑你的 Docker 构建的镜像。变的只是"kubelet 调用的运行时从 Docker 换成 containerd/CRI-O"。你本地 `docker build` 照常，集群跑的是 containerd。

**演化启示（极深）：** 这是一个"**为解耦而移除一层适配**"的经典案例。Dockershim 是"为了兼容老朋友临时加的翻译层"，长期看它拖慢演进、藏 bug。K8s 选择**砍掉特例、逼生态标准化到 CRI**——短期有迁移阵痛（用 Docker 的集群要换 containerd），长期整个生态更干净、运行时可替换。**这教你的系统设计课：接口（CRI）比具体实现（Docker）重要；临时适配层最终要么转正要么切除，别让它永久躺核心里。**

---

## 8.5 Pod 生命周期：从 Pending 到 Succeeded

Pod 有总状态（Pod phase）：

- **Pending**：API Server 已收、但还没调度成功，或镜像还在拉；
- **Running**：至少一容器 Running，且 Pod 已绑节点、沙箱起好；
- **Succeeded**：所有容器正常退出（且不再重启）——Job 的终点；
- **Failed**：至少一个容器失败退出，且重启策略不允许再起；
- **Unknown**：kubelet 失联，API Server 读不到状态（节点可能挂了）。

**墨：Unknown 是怎么来的？** 因为 Pod 状态是 kubelet **周期上报**给 API Server 的（通过 status 子资源，第 5.10 提过）。节点宕机，kubelet 不上报，API Server 那边的 Pod 状态就卡在最后已知值，最终被标记为 Unknown（靠节点租约/心跳超时判定）。这又是"期望 vs 实际"——实际状态靠节点持续上报，节点没了上报就停，系统标记为未知。**分布式系统里"未知"往往 = "该上报的没了"，不是"真的怎样"。**

### 8.5.1 容器状态与重启策略

每个容器有自己状态：Waiting（等启动/拉镜像）、Running、Terminated（退出，带原因和退出码）。

Pod 的 `restartPolicy`：
- **Always**（默认，Deployment 用）：退了就重启，永远维持（对应"服务"）；
- **OnFailure**（Job 用）：非 0 退才重启，成功就停；
- **Never**（裸 Pod/调试）：退了不重启。

**墨：restartPolicy 和控制器期望是怎么配合的？** Deployment 要"永远在"，所以 Always；Job 要"成功一次就停"，所以 OnFailure/Never。控制器的期望语义和 Pod 的 restartPolicy 必须**对齐**，否则矛盾（比如 Job 配 Always 会无限重启成功的 Pod）。又是"期望状态的自洽"问题。

---

## 8.6 探针（Probe）：Pod 怎么告诉 K8s "我活没活、能不能接客"

**墨：kubelet 怎么知道容器"真的好了"还是"进程起了但还在初始化"？** 光看进程在不在不够——进程在，可能服务还没 listen。于是有探针：

- **livenessProbe（存活探针）**：探失败 → kubelet **杀掉容器并按 restartPolicy 重启**。用于"死锁了但进程没退"的场景（比如 Go 服务 goroutine 全卡死，进程还在，但得重启救活）；
- **readinessProbe（就绪探针）**：探失败 → 从 Service 的**后端列表移除**，不接流量，但**不重启**。用于"启动中要预热/等依赖"时，别让流量打进来；好了再加回；
- **startupProbe（启动探针，较新）**：给慢启动应用一段"宽限期"，这段时间内不触发 liveness，避免慢启动被误杀。

三种探测方式：`exec`（执行命令看退出码）、`tcpSocket`（连端口）、`httpGet`（请求 HTTP 路径看状态码）。

**📦 案例：** 一个 Java 服务启动要 60 秒（加载 Spring 上下文）。你不设 startupProbe，livenessProbe 默认 10 秒探一次，连续失败几次（如 3 次）就杀容器重启——结果永远在"启动→被杀→重启"的死循环（liveness 风暴）。加上 `startupProbe` 给 120 秒宽限，启动期内 liveness 不生效，等真正起来了再交给 liveness 守着。这题是**生产真事故**，探针配错 = Pod 反复重启。

**⚠️ 坑：** readinessProbe 失败**只摘流量不重启**，所以"服务 500 但进程在"时它不会自愈——自愈靠 liveness（重启）或控制器（重建）。两者分工：readiness 管"接不接客"，liveness 管"是不是得换个新的"。

---

## 8.7 init 容器：主容器启动前的"序章"

Pod 可定义 **initContainers**：在**所有普通容器之前、按顺序**、**必须全部成功**才启动主容器。用途：

- 等依赖就绪（如等数据库端口通）；
- 做初始化（拉配置、建目录、跑 migration）；
- 做权限降级前的准备（init 可用更高权限做一次性设置）。

**墨：为什么不用"主容器里写个启动脚本"代替 init 容器？**

因为 init 容器**隔离且有序且失败可重试**：它跑在独立镜像/文件系统，不影响主容器；顺序保证（init1 完才 init2）；失败则 Pod 不进入主容器，排障清晰。脚本塞主容器里，初始化逻辑和业务耦合、顺序靠你自己写、失败了主容器可能已起一半。init 容器把"启动前契约"变成一等公民。

---

## 8.8 sidecar 模式与"原生 sidecar"的演化

**墨：你听过 sidecar（边车）吧？日志收集、服务网格代理（Envoy）常作为 sidecar 和业务容器放一个 Pod。它和 init 容器有啥不同？**

sidecar 是**和业务容器并行运行、长期共存**的辅助容器（如 Envoy 代理所有进出流量）。区别 init 是"一次性前戏"，sidecar 是"全程副驾"。

但老版本 K8s 有个尴尬：sidecar 是个普通容器，`restartPolicy: Always`，它**和业务容器同时启动**，没有"等主容器"的语义，且 Pod 退出顺序难控（sidecar 可能比主容器晚退，主容器已退但 sidecar 还在写日志导致丢尾）。社区长期用 hack（如 sidecar 监听主容器退出再退）。

**演化（K8s 1.28+ 原生 sidecar）：** 引入 `initContainers` 里设 `restartPolicy: Always` 的写法——这种"常驻型 init 容器"被当作**原生 sidecar**：它在主容器前启动、主容器运行期间一直活着、主容器全退后它才退。终于把"边车"做成官方语义，解决了退出顺序和生命周期耦合的老问题。这又是一个"用户用 hack 解决的问题，官方后来收编成一等公民"的演化故事（和 StatefulSet、CRI 同理）。

---

## 8.9 静态 Pod：kubelet 的"私生子"

**墨：你说 Pod 都是 API Server 管的，那控制面组件（如 API Server 自己、etcd）在 K8s 起来之前怎么跑？**

鸡生蛋问题：API Server 还没起来，谁来调度 API Server？答案是 **静态 Pod（Static Pod）**。kubelet 可以读**本地目录/文件**里的 Pod 清单（不在 etcd 里），直接管好这些 Pod。它们**不受任何控制器管、不通过 API Server 调度**，是 kubelet 单方面维护的。

特点：API Server 能看到它们（kubelet 上报成镜像对象），但**删不了它们**（API Server 删了 kubelet 又建，因为是本地清单驱动）。常用于**引导控制面组件本身**（kubeadm 部署时，etcd、api-server、controller-manager、scheduler 都是静态 Pod，由 kubelet 在节点上拉起，API Server 起好后接管其他）。这是"自举（bootstrap）"的经典手法——用最低依赖（kubelet + 本地清单）先把核心拉起来，再让核心接管全局。

**演化看点：** 静态 Pod 是"引导期特例"，正常运行时你几乎不用它（除了控制面）。它体现了"系统启动必须有不依赖系统的那一层"——任何自举系统都要有"先有鸡还是先有蛋"的解法，静态 Pod 就是 K8s 的答案。

---

## 8.10 本章演化线小结

- Pod 作为"一组亲密进程"的包裹，是调度原子单位 = 部署原子单位；
- pause 容器作 namespace 锚点，解耦"基础设施生命周期"与"业务生命周期"；
- CRI 解耦 K8s 与具体运行时；Dockershim 移除（1.24）是"砍临时适配层、逼标准化"的典范；
- 生命周期 phase + 容器状态 + restartPolicy 对齐控制器语义；
- 探针 trio（liveness/readiness/startup）分工：活没活 / 接不接客 / 启动宽限；
- init 容器做有序前戏；原生 sidecar（1.28）收编长期 hack；
- 静态 Pod 解决自举：控制面组件不依赖 API Server 自己先起。

---

## 8.11 本章思考题

### 🔧 思考题 1
一个 Pod 里有容器 A（web，监听 8080）和容器 B（日志收集，连 127.0.0.1:8080 拉日志）。pause 容器崩溃退出会怎样？A、B 还在跑吗？网络还通吗？

**【参考答案】**
pause 容器是 Pod 的 network/IPC namespace 持有者。它崩溃退出，Linux 上该 network namespace 会被销毁（除非有别的进程仍持有，但 A、B 都 join 的是 pause 的 ns，pause 退出后 ns 引用归零则销毁）。后果：(1) A、B 进程可能仍在，但它们依附的 network namespace 没了，等于"悬浮"，127.0.0.1:8080 的互通断裂，A 的 8080 对外也失联；(2) kubelet 检测到 pause（沙箱）没了，会认为 Pod 沙箱失效，按 restartPolicy 重建整个 Pod（A、B 连同新 pause 一起重启）。所以现实中"pause 崩"表现为"整个 Pod 重启"而非"只 pause 没了"。关键：**pause 是锚，锚没了整艘船重来**——正因如此 pause 极简极稳，几乎不会自己崩。这题考你对"namespace 生命周期绑定持有者"的理解。

### 🔧 思考题 2
Dockershim 移除后，你 `docker build` 打的镜像还能在 K8s 跑吗？请区分"构建"和"运行"两个阶段，说清各自由谁负责、CI 和集群分别用什么。

**【参考答案】**
能跑。镜像格式是 OCI 标准，与运行时无关。分两阶段：(1) **构建**：`docker build`（或 buildah、kaniko）产出 OCI 镜像，推到镜像仓库（Harbor/ECR 等）。构建用谁都行，跟集群运行时无关。(2) **运行**：集群节点上 kubelet 通过 CRI 调 containerd（或 CRI-O），containerd 拉 OCI 镜像、解层、起容器。Dockershim 移除只影响"运行阶段 kubelet 如何调运行时"——从"经 Dockershim 转 Docker"变成"直接调 CRI 原生运行时"。CI 仍可用 docker build（你习惯不变），集群跑的是 containerd。所以"K8s 不用 Docker"是误读，准确说"kubelet 不再经 Docker 守护进程，改直连 containerd"，镜像完全兼容。这题考你区分"镜像标准"和"运行时接口"两层。

### 🔧 思考题 3
一个 Go 服务偶尔死锁（goroutine 全卡，但进程不退出，HTTP 端口仍 listen 但请求永远不返回）。你该配哪种探针救它？如果只配 readiness 不配 liveness 会怎样？如果只配 liveness（10 秒探一次）但启动要 40 秒会怎样？

**【参考答案】**
死锁但进程在 = 需用 **livenessProbe**（探失败→杀容器重启救活）。死锁时进程在、端口 listen，readiness 若探的是"端口通"也会误判为就绪（实际请求卡死），所以 liveness 必须用"业务能响应"的探测（如 httpGet 一个会真正处理的 health 路径，超时即失败）。只配 readiness 不配 liveness：死锁时 readiness 失败→摘流量，但**不重启**，服务永久不可用且不自愈——流量是不打了，但 Pod 废了没人救。只配 liveness 且启动 40 秒但 liveness 周期 10 秒（failureThreshold 3）：启动期 30 秒时 liveness 已连续失败 3 次→杀容器→重启→又卡启动→又杀，死循环（liveness 风暴）。正确解法：加 **startupProbe** 给 60 秒宽限（期内 liveness 不生效），启动完交给 liveness 守；liveness 探测要真正反映"能处理业务"而非"端口在"。这题是探针配置的生产级陷阱。

### 🔧 思考题 4（进阶）
sidecar 演化为"原生 sidecar"（1.28 常驻 init 容器）解决了什么老问题？从"生命周期顺序"角度，对比老 hack（普通容器 sidecar）和新原生 sidecar 在"Pod 启动"和"Pod 终止"时的差异。

**【参考答案】**
老 hack：sidecar 是普通容器（restartPolicy: Always），与主容器**同时启动、无序**，且 Pod 终止时容器退出顺序不确定。问题：(1) 启动期 sidecar（如 Envoy）可能还没就绪，主容器就已发流量出去，流量绕过代理/丢失；(2) 终止期主容器先退，sidecar 后退，主容器最后一点日志/请求可能因 sidecar 已退而丢失（如日志 sidecar 没收到尾日志）。原生 sidecar（initContainers 里 restartPolicy: Always）：(1) **启动**：它在所有普通容器**之前**启动且需 Ready 才放行主容器，保证"副驾先就位"；(2) **终止**：主容器全部退出后，sidecar 才被终止，保证"主退了副驾还在收尾"。这把"sidecar 生命周期应包裹主容器"的语义做成官方保证，消除退出顺序竞态。启示：分布式系统里"启动/关闭的顺序"是正确性的一部分，不能靠运气（同时启动的竞态），要把顺序变成显式契约。K8s 把用户长期用 hack 维持的顺序，收编成 API 语义——又见"社区实践→官方一等公民"的演化规律。

---

## 8.12 小结

- Pod 是"一组亲密进程"的包裹，因为调度原子 = 部署原子；没有 Pod 就无法保证同机、共享网络、整体扩缩；
- pause 容器作 namespace 锚点，解耦基础设施与业务生命周期；
- CRI 解耦运行时，Dockershim 移除是"砍临时适配、逼标准化"的典范，镜像仍兼容；
- phase + 容器状态 + restartPolicy 必须和控制器语义对齐；
- 探针 trio 分工明确：liveness 救活、readiness 摘流量、startup 给宽限；
- init 做有序前戏，原生 sidecar 收编 hack 解决生命周期顺序；
- 静态 Pod 是自举解：控制面先靠 kubelet 本地清单起来，再接管全局。

下一章进网络——K8s 里最让人头秃、也最见设计深度的一块。**Pod 各有 IP、随时生灭，网络怎么不乱套？Service 那个"虚拟 IP"到底是什么鬼？** 咱们下一章把网络模型拆穿。
