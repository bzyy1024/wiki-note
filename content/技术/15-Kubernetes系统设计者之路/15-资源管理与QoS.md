# 第 15 章 资源管理与 QoS：cgroups / requests / limits / OOM / 驱逐

> 墨：老哥，前面第 6、7、8 章我反复埋了个坑——"不写 requests 的 Pod 会被调度器当空气，堆一起然后全 OOM"。这章总清算。我先问：**你说 limits 是硬限还是软限？CPU 超了和内存超了，下场一样吗？** 这俩问题的答案，决定了你线上多少事故。

---

## 15.1 为什么要有资源管理：节点是有限的花盆

一台节点（机器）的 CPU、内存、磁盘 IO 是**物理上限**。上面跑了 20 个 Pod，如果都不设限，一个 Pod 内存泄漏就能把整台机器吃满，其他 19 个被拖死（第 2.2.1 配置漂移同源问题——隔离缺失）。

**墨：Docker 本身有 cgroup 限制，K8s 再加一层 requests/limits 干啥？** 因为 cgroup 是"单容器单机"的限制，K8s 要解决的是"**集群层面的资源分配与优先级**"：哪个 Pod 该被优先保证？节点满了先杀谁？调度时怎么知道这台机器还装不装得下？这些是集群调度/驱逐的决策，单机 cgroup 管不了。所以 K8s 在"单机 cgroup"之上，加了"集群级的 requests/limits 语义 + QoS 优先级 + 驱逐策略"。两层配合：K8s 决定"谁重要、谁该被调度"，cgroup 决定"跑起来后硬限多少"。

---

## 15.2 requests vs limits：两个被混淆的概念

这是全章地基，必须钉死。

- **requests（请求）**：Pod 容器**至少要**多少资源。用于**调度决策**——调度器算"节点已分配给其他 Pod 的 requests 之和 + 本 Pod requests ≤ 节点 Allocatable"才放行（第 6.3）。它表达的是"保底"。
- **limits（限制）**：Pod 容器**最多**能用多少。用于**运行时硬限**——cgroup 把它翻译成内核限制，超了就 throttle（CPU）或 OOM kill（内存）。

**墨：如果只设 limits 不设 requests 会怎样？** 调度器把 requests 当 0——等于"这台机器随便塞"，可能把节点塞爆，然后运行时靠 limits 限流/OOM。结果：调度阶段盲目（节点过载），运行阶段频繁 throttle/OOM。所以**requests 是给调度器的"诚实申报"，limits 是给内核的"硬天花板"**。两者都得设，且 requests ≤ limits（CPU 可相等，内存必须 requests≤limits）。

### 15.2.1 一个反例洞见

**墨：requests 设得比 limits 小很多（如 requests CPU 100m, limits 2）有啥用？** 这叫"**突发（burst）**"模式：调度时按 100m 占坑（节点以为你只吃 100m，能塞更多 Pod），运行时你真能突到 2 核。好处：提高节点利用率（大家平时都少吃，偶尔突发）。风险：若所有 Pod 同时突发，节点 CPU 被争抢（throttle），内存若都突发可能 OOM。这是"超卖（overcommit）"——K8s 默认允许 requests 总和 > 节点资源（因为大家不会同时跑满），用"平均 + 突发"换利用率。**超卖是云厂商赚钱的核心逻辑**，但超卖过度 = 频繁争抢/OOM。又是"利用率 vs 稳定性"的权衡。

---

## 15.3 requests/limits 怎么落到 cgroups

**墨：你写在 YAML 的 `resources.limits.memory: 512Mi`，最终怎么变成"这个容器最多用 512M"的？** 经过两层翻译：

1. **K8s 层**：kubelet 看到 Pod 的 resources，把它换算成 cgroup 参数；
2. **内核层**：kubelet（经容器运行时 CRI）写 cgroup 文件：
   - 内存：`memory.limit_in_bytes = 512Mi`（硬限，超了 OOM）；
   - CPU：`cpu.cfs_quota_us / cpu.cfs_period_us`——如 limits 2 核 = quota 200000us / period 100000us，表示每 100ms 最多跑 200ms（即 2 核）；
   - 还设 `cpu.shares`（来自 requests）决定争抢时的权重。

**墨：CPU 的 requests 和 limits 在内核里是两种不同机制，你注意到了吗？** 对。CPU requests → `cpu.shares`（**权重**，争抢时按比例分，不硬限）；CPU limits → `cfs_quota`（**硬限**，超了就 throttle 不让跑）。内存则只有硬限（limit_in_bytes），没有"权重"概念——因为内存不能"节流"，要么给要么不给（OOM）。这引出下节关键区分。

---

## 15.4 CPU 可压缩 vs 内存不可压缩（极其重要）

**墨：CPU 用超了和内存用超了，下场一样吗？** 完全不一样，这是很多事故的根：

- **CPU 是可压缩资源（compressible）**：你超了 limits，内核** throttle（限流）**你——让你跑慢点，但进程不死。表现：请求延迟升高、CPU 使用率卡在限额、但服务还在。所以"CPU 超了"是"变慢"，不是"死"；
- **内存是不可压缩资源（incompressible）**：你超了 limits，内核 **OOM kill** 你——直接杀进程（选最耗内存的）。表现：Pod 重启（restartPolicy Always 的话），日志里 `OOMKilled`，退出码 137。

**为什么不同？** CPU 是"时间片"，少给点只是慢；内存是"空间"，没了就是没了，没法"少给点凑合"，只能杀。所以**内存超 limit 是致命的（进程死），CPU 超 limit 是温和的（变慢）**。排障时看到 `OOMKilled` 就是内存超了；看到 CPU 使用率被卡在限额、延迟高，是 CPU throttle。

**⚠️ 坑：** 有人不设内存 limits（怕 OOM），结果 Pod 内存泄漏吃光节点，触发**节点级驱逐**（见 15.7），把节点上**所有 Pod** 都杀了——比单单 OOM 一个 Pod 更惨。所以内存 limits 要设（哪怕宽松点），别因噎废食。

---

## 15.5 QoS：节点满了先杀谁

**墨：节点内存快爆了，kubelet 必须杀一些 Pod 腾空间。杀谁？随机吗？** 不是。K8s 给每个 Pod 定一个 **QoS 等级（服务质量）**，决定"被杀优先级"。三档：

### 15.5.1 Guaranteed（最高保障）

条件：**每个容器都设了 requests == limits（且 CPU、内存都设）**。比如 `requests.cpu=limits.cpu=1, requests.memory=limits.memory=512Mi`。

含义：这个 Pod "要多少就是多少，绝不超"，最可预测。kubelet **最后才杀**它（除非它自己超了 limits 被 OOM）。

### 15.5.2 Burstable（中等）

条件：至少**一个容器设了 requests 但不等于 limits**（或只设了 limits 没设 requests 的部分）。即"有保底、可突发"。

含义：平时保证 requests，突发可到 limits。节点压力大时**中间批次被杀**（先杀那些"当前用得远超 requests"的）。

### 15.5.3 BestEffort（最低）

条件：**所有容器啥都没设**（无 requests 无 limits）。正是"不写 resources"的 Pod。

含义：kubelet 对它"零承诺"，节点一有压力**第一个被杀**。而且因为它没 limits，它可能偷偷吃光资源拖垮别人——所以 BestEffort 是"最危险也最易被牺牲"的档。

**墨：所以"不写 requests/limits"= BestEffort = 节点一紧先被杀 + 可能拖累全场。这就是前面几章埋的坑的总账。** 对。设了 requests/limits 不只是一行配置，是**给 Pod 买了"不被随意牺牲"的保险**。生产核心服务至少 Burstable，关键（如数据库、支付）要 Guaranteed。

### 15.5.4 同档内谁先死

同 QoS 内（如都是 Burstable），kubelet 按 **(1) 谁最超 requests（实际用 - requests 越大越该杀）(2) 谁用得最多内存** 排序。也就是"最超标、最贪吃"的先杀。这很合理：你申报 100M 却吃了 500M，你比"申报 100M 吃了 120M"的更该让位。

---

## 15.6 OOM 的发生链（排障用）

```
Pod 内存涨 → 超过 limits → cgroup memory.limit_in_bytes 触发 →
内核 OOM killer 在该 cgroup 内选最耗内存的进程 → 杀之 →
容器退出码 137（SIGKILL）→ kubelet 看到 → 按 restartPolicy 重启（Always）→
若反复 OOM → 可能触发 Pod 级退避 / 或节点压力驱逐
```

**墨：你 Pod 反复重启，日志 `OOMKilled`，你怎么判断是"limits 设小了"还是"真泄漏"？** 看内存**增长曲线**：若稳定在高位后 OOM、重启后又涨到同样高位 → 是 limits 不够（调大 limits 或优化内存）；若**持续单调上涨不回头** → 是真泄漏（limits 调再大也只是延迟 OOM，得修代码）。区别"配置问题"和"代码问题"是排障第一步。

---

## 15.7 节点压力驱逐（kubelet eviction）：比 OOM 更上游

**墨：除了 cgroup OOM，节点还有别的"压力"会杀 Pod 吗？** 有，而且更上游。**kubelet 自己**会监控节点压力（内存、磁盘、inode、PID），超过阈值就**主动驱逐（evict）Pod** 腾空间，避免真到内核 OOM 那一步（内核 OOM 会乱杀，不如 kubelet 按 QoS 有序杀）。

- **驱逐信号**：`memory.available`（可用内存）、`nodefs.available`（节点磁盘）、`imagefs.available`（镜像盘）、`inode` 等；
- **软阈值（soft eviction）**：超过后给宽限期（如 90s），期望压力自己降（如别的 Pod 被删释放）；
- **硬阈值（hard eviction）**：超过立即驱逐，不协商；
- **驱逐顺序**：同 QoS 逻辑——先 BestEffort、再 Burstable（超 requests 多的）、Guaranteed 最后。被驱逐的 Pod 被**删掉**，由控制器在其他节点重建（如果集群有资源）。

**墨：驱逐和 OOM 谁先发生？** kubelet 的硬阈值通常设在"比 cgroup OOM 早触发"的位置（如可用内存剩 100Mi 就驱逐，而 Pod OOM 是单个 Pod 超 limits）。设计意图：让**有序的、按 QoS 的驱逐**先于**无序的、内核随机 OOM**。又是"用可控机制替代不可控故障"的思路——节点压力是必然的，关键是谁来管"杀谁"：kubelet（懂 QoS、有序）优于内核 OOM killer（懂 cgroup、但跨 Pod 无序）。

**⚠️ 坑：** 磁盘满（nodefs）也会驱逐——常见于日志不清理、镜像堆积。所以节点要配日志轮转（如集群级 logrotate / 用 Loki 收集后清）、镜像 GC。否则"磁盘满→驱逐一堆 Pod→服务抖"。

---

## 15.8 cgroups v1 vs v2：演化中的资源管理底座

**墨：cgroups 是内核功能，它自己有版本吗？对 K8s 有影响？** 有，且影响不小。Linux 有 **cgroups v1**（各子系统独立、歷史久）和 **cgroups v2**（统一层级、更准）。

**K8s 演化（1.25+ 默认偏向 v2，且部分功能只 v2 支持）：**
- **资源监控更准**：v1 的 `cpu` 统计在某些场景不准（如 `cpuacct` vs `cpu` 子系统分裂），v2 统一；
- **OOM 优先级（oom_score_adj）**：v2 有更精细的 cgroup 级 OOM 控制，K8s 用它更准地实现 QoS 驱逐（v1 下 K8s 靠写 `oom_score_adj` 文件近似）；
- **PSI（Pressure Stall Information）**：v2 提供"资源压力"精细指标，K8s 的驱逐判断更及时；
- **默认推行**：新版 K8s + 新内核默认 cgroups v2，老集群可能还在 v1（需内核支持 v2 且未显式禁用）。

**演化启示：** 资源管理这种"贴近内核"的能力，受底层（cgroup 版本）演进驱动。K8s 适配新内核能力来让 QoS/驱逐更准——又是"上层机制靠底层演化变强"的例子（和 eBPF 强化网络、CSI 强化存储同构）。你做系统也要注意：你的能力天花板常被你依赖的底层（内核/库）决定，底层升级要跟。

---

## 15.9 一道总清算：把前面所有"requests 坑"连起来

前面章节埋的"不写 requests"的坑，现在你能串成完整因果链了：

1. **调度（第 6.3）**：不写 requests → 调度器当 0 → 多 Pod 堆一台节点（看似能装）；
2. **运行时（本章）**：这些 Pod 是 BestEffort，无 limits → 一个泄漏吃光节点内存；
3. **QoS（15.5）**：节点压力，BestEffort 先被驱逐 → 你的 Pod 莫名消失、重建、再被杀；
4. **网络/服务（第 9 章）**：Pod 反复被杀重建 → Service 后端抖动 → 调用方 502；
5. **控制器（第 3 章）**：Deployment 不断调和"补回 3 个"，但节点资源不够 → 一直 Pending/被杀循环。

**一句话：一行 `resources` 没写，能引发从调度到服务可用的整条链路故障。** 这就是为什么我反复念叨它。设 resources 不是"规范"，是"给系统提供决策依据"——没依据，系统只能瞎猜，瞎猜就出事。

---

## 15.10 本章演化线小结

- requests(调度保底/权重) vs limits(运行时硬限)：两层语义，都得设且 requests≤limits；
- requests/limits 经 kubelet→CRI 落到 cgroup：内存 limit_in_bytes、CPU quota(硬限)+shares(权重)；
- CPU 可压缩（throttle 变慢）vs 内存不可压缩（OOM 杀进程）——超 limit 下场不同；
- QoS 三档 Guaranteed/Burstable/BestEffort，决定节点压力下被杀顺序；不写 resources=BestEffort=最危险；
- 同档内按"超 requests 程度、内存占用"排序杀；
- 节点压力驱逐（kubelet 主动、按 QoS 有序）先于内核 OOM（无序）；磁盘满也驱逐；
- cgroups v1→v2：监控更准、OOM 控制更精、PSI 压力指标，K8s 跟进变强。

---

## 15.11 本章思考题

### 🔧 思考题 1
节点 4核8G，已分配：Pod A(requests 1c/1G, limits 1c/2G)、Pod B(无 resources)。再来 Pod C(requests 1c/1G, limits 1c/2G)。调度器会放行 C 吗？若放行，节点实际"申报资源"vs"硬上限"各是多少？若 A、B、C 同时内存涨到接近 limits，谁先 OOM/被驱逐？

**【参考答案】**
调度：调度器算节点已分配 requests。A 申报 1c/1G，B 申报 0/0（无 resources），C 申报 1c/1G。已分配 requests 合计 2c/2G（B 算 0），节点 4c/8G 装得下，放行 C。节点"申报资源"= 2c/2G（B 不占申报），但"硬上限（limits 之和）"= A2G+B无限+C2G。B 无 limits 可吃光剩余 6G。若三者同时涨内存：B 是 BestEffort（无 resources），A、C 是 Burstable（有 requests≠limits 或相等？假设他们 requests=limits 则 Guaranteed，题设 requests1c/1G limits1c/2G 是 Burstable）。节点压力时：(1) B(BestEffort) 先被驱逐/OOM；(2) 然后 A、C 按"超 requests 程度"——谁实际用远超 1G 谁先死。但若 B 无 limits 吃光内存导致节点整体 OOM，内核 OOM killer 会在全节点选最耗内存进程——可能杀 B（最贪）也可能误伤 A/C。结论：B 不写 resources 既自己最危险、又可能拖垮节点致 A/C 被误杀。这题把"调度盲目 + QoS 排序 + 节点压力"串成一次。

### 🔧 思考题 2
你设了内存 limits=512Mi 但程序需要 1G 才不 OOM，于是你**不设 limits**（想避免 OOMKilled）。结果节点上另一个 BestEffort Pod 内存泄漏。描述接下来可能发生的连锁，并说明"不设 limits"是不是好主意。

**【参考答案】**
不设 limits 的后果：(1) 你的 Pod 无内存硬限，本可安稳用 1G；(2) 但同节点另一 BestEffort Pod 泄漏，吃光节点内存（它也无限），触发**节点级内存压力**；(3) kubelet 看可用内存低于硬阈值，按 QoS 驱逐——BestEffort 先杀，于是**那个泄漏 Pod 被驱逐**，但你也可能因为节点资源被它占满、且你是 Burstable/也可能 BestEffort 而被波及；(4) 更糟：若压力到内核 OOM，内核 OOM killer 选"当前最耗内存进程"——可能选那个泄漏 Pod（它最占），也可能因你的 Pod 也占 1G 而被选，于是**你本想躲 OOM 的 Pod 仍被 OOM**（因为节点整体没内存了，谁占多杀谁）。所以"不设 limits 躲 OOM"是错觉：你躲过了"自己超 limits 的 OOM"，但躲不过"节点整体内存耗尽的无差别 OOM/驱逐"。正确做法：设合理 limits（覆盖真实需求，如 1G 或略大）、设 requests 保证调度份额、用 QoS(Burstable/Guaranteed) 提升不被驱逐优先级。limits 是"自保+不害人"的契约，不该为躲 OOM 而弃。

### 🔧 思考题 3
cgroups v2 比 v1 让 K8s 的 QoS 驱逐"更准"。从"OOM 优先级怎么落地"的角度，解释 v1 下 K8s 怎么近似、v2 怎么做得更好，以及这为何影响"Guaranteed Pod 是否真的最不被杀"。

**【参考答案】**
v1 下：cgroup 层级各子系统独立，K8s 只能通过写每个容器的 `oom_score_adj`（一个 -1000~1000 的微调值）来近似 QoS——Guaranteed 设很低（如 -998，难被杀）、BestEffort 设很高（如 1000，极易被杀）。但这是"近似"：oom_score_adj 是相对权重，内核最终选"score 最高"的进程，多个 BestEffort 同时高分时谁先死不完全可控，且跨 cgroup 的全局 OOM 时这个近似会失真。v2 下：cgroup v2 有**统一的、层级化的内存防护**（如 `memory.oom.group`、更准的 cgroup 级 OOM 决策），K8s 能更精确地表达"这个 cgroup（Guaranteed Pod）整体受保护、那个（BestEffort）可被牺牲"，且 PSI 提供实时压力信号让 kubelet 更早有序驱逐、不必等内核 OOM。影响：v2 下 Guaranteed Pod 的"最不被杀"从"近似权重"变成"结构性保护"，更可信——你设了 Guaranteed，节点压力下它确实最后才倒，而非靠 score 概率。这题考你"上层 QoS 语义的可靠性，取决于底层 cgroup 能力的精度"，底层升级让上层契约更硬。

### 🔧 思考题 4（进阶）
超卖（overcommit，requests 总和 > 节点资源）是 K8s 默认允许的，也是云厂商盈利核心。但超卖过度会导致频繁 throttle/OOM。从"调度器决策 + 节点压力"两端，设计一个"既高利用率又不太容易炸"的资源策略（requests/limits 怎么设、QoS 怎么分、配额怎么控）。

**【参考答案】**
策略框架：(1) **requests 诚实、limits 给突发但有界**：每个 Pod 设真实 requests（调度器据此准确分配，避免盲目堆叠），limits 设"requests 的 1.5~2 倍"允许突发但封顶，避免单 Pod 吃光节点（防 15.2.1 的过度超卖）。(2) **QoS 分层**：核心服务（DB/支付）设 requests=limits → Guaranteed，节点压力最后牺牲；普通无状态设 Burstable；批处理/可弃任务设 BestEffort（显式，而非"忘了写"变成隐性 BestEffort）。(3) **命名空间配额（ResourceQuota）**：给每个团队/环境设总 requests/limits 上限，防止单一团队超卖炸全集群（第 4.5 准入层防线）。(4) **LimitRange 默认值**：给忘了设 resources 的 Pod 自动补"最小 requests + 合理 limits"，把"隐性 BestEffort"消灭在准入时（第 12.5 同思路）。(5) **HPA + 节点池分级**：突发型用 HPA 按指标扩，关键型放专用节点池（taint+toleration，第 6.3）避免混部被挤。核心：超卖靠"requests 总和 > 节点"提升利用率，但用"limits 封顶 + QoS 分层 + 配额 + LimitRange"四道闸防止"过度超卖炸集群"。利用率与稳定性不是二选一，是用约束把超卖控制在"安全区间"。这是生产资源治理的标准答案。

---

## 15.12 小结

- requests(调度保底/权重) vs limits(运行时硬限)，两层语义都得设且 requests≤limits；
- 落到 cgroup：内存 limit_in_bytes 硬限、CPU quota 硬限 + shares 权重；
- CPU 可压缩（throttle 变慢）vs 内存不可压缩（OOM 杀）——超 limit 下场不同，排障看退出码 137；
- QoS 三档决定被杀顺序，不写 resources = BestEffort = 最危险且拖累全场；
- 节点压力驱逐（kubelet 有序、按 QoS）先于内核 OOM（无序），磁盘满也驱逐；
- cgroups v2 让 QoS 保护更结构化、更可信；
- 一行 resources 缺失能引发"调度→运行时→网络→控制器"整链路故障，务必设。

下一章进**高可用与控制面演化**——前文各章的组件（API Server/etcd/调度器/控制器）自己挂了怎么办？一个"管高可用的系统"怎么保证自己高可用？这章还顺带讲云托管趋势（把最不能错的部件交给云厂商）。
