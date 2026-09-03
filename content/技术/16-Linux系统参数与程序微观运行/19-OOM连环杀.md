# 第 19 章 OOM 连环杀——"一个接一个被杀"的雪崩现场

> 第 18 章我们见识了"内核暂停类"的幽灵卡顿,靠 `vmstat` 和 `compact_stall` 锁定了 swap 颠簸和 THP compaction。
> 这一章换个更血腥的现场:**OOM Killer 像多米诺一样,把机器上的进程一个接一个干掉**,`dmesg` 里一整屏 `Out of memory: Killed process X (xxx)`。很多人对 OOM 的理解停留在"内存满了杀最胖的"——这半对半错,而且**恰恰是这半错的理解,让你在连环杀现场判断错凶手、下错药**。
> 我们照例走完整迭代环,并把 `overcommit`、`oom_score_adj`、`swappiness`、cgroup 内存上限这四个角色在"谁死"这件事上的分工彻底讲清。

---

## 一、OOM Killer 的杀人逻辑:它到底杀谁

墨:老哥,先考你一个最常被答错的问题。OOM 的时候,内核**具体按什么杀进程**?

你:杀最占内存的呗?哪个进程吃内存最多杀哪个。

墨:**只对了一半,而且这"一半"害死人。** 内核真正的判据是给每个进程算一个 **`oom_score`(OOM 评分)**,分越高越先死。它的核心构成是:

```
oom_score ≈ 该进程"当前占用物理内存(含子进程、共享页按比例)" 的相对大小
           + 一些惩罚项(如 fork 很多子进程、持有大量页)
```

注意两个关键细节,这俩就是"半错"的来源:

1. **它看的是"占的物理内存比例",不等同于你 `top` 里看到的 RES。** 共享库、子进程、cgroup 范围都会改变"谁占比高"的排序。
2. **`oom_score_adj`(每进程,范围 -1000~+1000)会**加算**到分数上**——这是你给进程发的"免死金牌"或"催死符"。`-1000` 直接免疫 OOM(永不杀),`+1000` 几乎必死。

你:`oom_score_adj` 在哪设?是不是在 `vm` 下?

墨:**不在 `vm` 下,是 per-process 文件 `/proc/<pid>/oom_score_adj`**(第 12、17 章强调过"找错门"的坑)。`systemd` 服务可以用 `OOMScoreAdjust=` 配置,cgroup v2 里则是 `memory.oom.group` 和 `oom_score` 的继承逻辑。这个位置差异,是很多人"想给核心服务免死却没生效"的根因。

墨:还有第三层——**OOM 触发的边界有两种**:
- **整机 OOM**:物理内存 + swap 真不够,触发全局 OOM Killer,在**所有进程**里挑 `oom_score` 最高的杀。
- **cgroup OOM**:某个 cgroup(容器/Slice)自己撞到了 `memory.max`(cgroup v2)/`memory.limit_in_bytes`(v1)上限,**只在这个 cgroup 内部**挑分高的杀,不影响别处。

你:这俩有啥区别,排障时重要吗?

墨:**太重要了,这是连环杀现场的第一个分水岭。** 整机 OOM 会杀得鸡飞狗跳、谁都可能死;cgroup OOM 是"哪个容器自己作死自己死"。看 `dmesg` 里的关键字:`"Out of memory: Killed process"` 是整机;`"Memory cgroup out of memory: Killed process"` 是 cgroup。分不清,你会跑去调整机参数,越调越乱。

---

## 二、事故全景:容器集群的"凌晨连环杀"

`📦 案例:某 SaaS 平台,K8s 集群,一批 4G 内存限制的 Java 订单 Pod。某日凌晨,告警"批量 Pod 重启",`dmesg` 一屏 OOM kill。`

### 现象(第 0 层)

值班拉 `dmesg`:

```
Out of memory: Killed process 8821 (java) ...
Out of memory: Killed process 9034 (java) ...
Out of memory: Killed process 9102 (java) ...
...
```

**短短几分钟内,同一节点上 6 个 Java Pod 被依次杀死并重启**。更诡异的是:被 kill 的**不全是内存最胖的**——有个只用 2.1G 的也被杀了,而另一个 3.8G 的反而活了下来。

墨:两个反常信号已经蹦出来:**(a) 连环**(不是偶发一个);**(b) 被杀的不都是最胖的**。这俩直接推翻"满了杀最胖"的朴素理解,提示现场有"非内存占比"的力在作用。

### 推断 1:是不是某个服务内存泄漏?(可能推错)

你:6 个 Java 接连被杀,肯定是有个 Pod 泄漏了,内存涨穿 4G 上限被 cgroup OOM 干掉,然后……

墨:先查被 kill Pod 的**被杀前内存**。发现:它们被杀时**没有一个真正"涨穿" 4G**——多数在 2~3G 就被杀了,离 4G 上限还有距离。如果是单纯泄漏穿上限,应该是"涨到 4G 才死",而且只死那一个。

**结论:推错。不是单点泄漏穿上限。**

### 推断 2:整机 OOM?(差点被骗)

你:那是不是节点物理内存(16G)被这批 Pod 吃满,触发整机 OOM,所以乱杀?

墨:查节点物理内存——**被杀时刻节点还有 3G+ 空闲**(加上 page cache 更多)。而且 `dmesg` 关键字是 `"Out of memory: Killed process"`(**没有 "Memory cgroup"** 前缀),但节点没满……等等,这矛盾了。

再细看:日志里其实**混着两种**——少数几行带 `Memory cgroup out of memory`,多数不带。说明**既有 cgroup 级 OOM,也有整机级 OOM**,是混合现场。

**结论:不完全错,但只看到一层。真正的连环机制还没摸到。**

### 再观察:抓到"连环"的传动链(关键转折)

你:既不是单点泄漏,节点也没满,那为什么**连环**?而且死的不是最胖的?

墨:把时间轴对齐 + 看每个 Pod 的 cgroup 内存曲线,传动链浮现了:

```
① 凌晨有个定时任务(batch 报表)在节点上启动,它本身不胖(1.2G),
   但把节点空闲内存从 5G 压到 2G,把"整机水位"顶高;
② 此时某订单 Pod 来一波请求峰值,堆内存从 2G 涨到 2.8G,
   它的 cgroup 没满(4G),但**节点整机 available 被压低**;
③ 节点触发"整机 OOM"(因为 available 跌破内核保留 + 某些原子分配需求),
   整机 OOM 按 oom_score 挑——而 java Pod 因为常驻 + 共享库,
   评分被"持有大量页"推高,**即使只占 2.8G 也被挑中**;
④ 杀掉一个 Pod → 它的流量瞬间转移到同节点其他订单 Pod →
   那些 Pod 请求量翻倍、堆内存上涨 → 更接近各自上限/整机水位 →
   又被挑中杀掉 → 流量再转移……
⑤ 形成"杀一个→流量转移→再杀一个"的雪崩(惊群),
   直到节点上订单 Pod 被杀光、或定时任务结束释放内存。
```

而你前面疑惑"为什么 2.1G 的死、3.8G 的活"——因为**整机 OOM 杀的是"oom_score 相对高"的,不是"绝对最胖"的**;而且 3.8G 那个恰好 `oom_score_adj` 被设过负值(前任给"重要服务"加过免死),评分被压下去了。这一下把"半错的理解"彻底纠正:**OOM 杀的是评分高者,评分 = 内存占比 + 惩罚项 + oom_score_adj,不是单纯的 RES。**

### 调整 1:给核心服务发"免死金牌"

墨:第一剂药——**用 `oom_score_adj` 把核心订单服务保护起来**,同时让"可牺牲"的批处理任务更容易被挑中:

```bash
# 订单 Pod 的 systemd / 容器运行时设置(举例)
echo -500 > /proc/<订单pid>/oom_score_adj     # 几乎免疫整机 OOM
# 批处理报表任务:
echo  500 > /proc/<报表pid>/oom_score_adj      # 内存紧张时优先被牺牲
```

注意:在 K8s 里更规范的做法是 `priorityClassName` + `PodDisruptionBudget`,让调度器层面就别把"互相挤兑"的 Pod 放同节点,而不是裸调 `oom_score_adj`。但我们这里是讲内核机制,先认准"免死金牌"这根针。

### 调整 2:堵住"整机 OOM"这个更大的窟窿

墨:第二剂药——**绝大多数业务根本不该触发整机 OOM**。根因是节点上"可挤占的缓冲"太少 + 批处理任务没设 cgroup 上限。`overcommit` 策略和 `swappiness` 也在这里插手:

- 这批节点 `vm.overcommit_memory=0`(默认启发式)。启发式下,**突发大 malloc 可能直接 EAGAIN 失败**(第 12/14 章),Java 的 `-Xmx` 预分配踩中时 JVM 直接起不来;而如果改成 `=1` 又把所有不确定性推到 OOM 那一刻(更猛地杀)。**没有银弹,但容器环境通常配合 cgroup 上限用 `=0` 或 `=2` + 精确 ratio**,让"该失败的(预分配)提前失败",而不是"该运行的被杀"。
- `swappiness=60` 默认,节点内存波动时把匿名页往 swap 推,**进一步压低 available,变相促成整机 OOM**。压到 10 能减少这种"被 swap 挤出来的 OOM"。

### 调整 3:切断"流量转移 → 再杀"的雪崩链

墨:第三剂药——**连环的传动链是"杀一个流量转移给剩的"**。光保护核心服务不够,还得让雪崩链断掉:
- 给订单 Pod 设 **`PodDisruptionBudget`**(最少可用副本数),杀之前先保证有替代;
- 入口层**限流/熔断**,被杀瞬间别把所有流量灌给剩余实例;
- 批处理报表任务**错峰 + 设 cgroup 内存上限**,不让它把节点水位顶高。

### 改进:连环杀归零,复盘收口

墨:三剂药下去(免死金牌 + 堵整机 OOM + 断雪崩链),连续一周再无连环杀。复盘最有价值的一句话:

> **OOM 连环杀,十次有九次不是"内存真不够",而是"某个边界被顶到 + 杀一个流量转移给剩的"形成的正反馈雪崩。** 你下药的层次,必须同时覆盖"谁死(oom_score_adj)"、"在哪死(cgroup vs 整机)"、"为什么连环(流量转移)",缺一不可。

你:所以 OOM 排查第一步,是看 `dmesg` 那行到底是"整机"还是"cgroup"前缀。

墨:**对,这是分水岭。前缀决定你该去调整机参数还是容器上限,调反了白忙。**

---

## 三、配套参数:四个角色在"谁死"上的分工

| 角色 | 参数 / 文件 | 它决定什么 | 怎么用 |
|---|---|---|---|
| 评分基数 | 进程占用物理内存比例 | 谁占比高、谁分高 | 监控 RES + 共享 |
| 免死/催死 | `/proc/<pid>/oom_score_adj`(-1000~1000) | 加算到评分 | 核心服务 `-500`,可牺牲 `+500` |
| 边界 ① | `vm.overcommit_memory`(0/1/2) | malloc 何时失败 vs 何时推到 OOM | 容器常 0/2+ratio,让该失败的提前失败 |
| 边界 ② | cgroup `memory.max`(v2)/`limit_in_bytes`(v1) | cgroup 级 OOM 边界 | 每个容器必设,别裸跑 |
| 促成者 | `vm.swappiness` | 高则更易压低 available → 促成整机 OOM | 容器/DB 设 10 左右 |
| 核按钮 | `vm.panic_on_oom`(0/1) | OOM 时杀进程(0)还是整机重启(1) | **生产必 0** |

墨:`oom_score_adj` 和 `overcommit` 经常被搞混——**`oom_score_adj` 决定"死了挑谁",`overcommit` 决定"你有没有机会在死之前就 malloc 失败"**。一个是临终选择器,一个是生前闸门。两件事,两套参数,别混。

---

## 四、参数总表(这一章动过的"拿什么换什么")

| 参数 / 文件 | 默认 | 本次动作 | 拿什么换什么 |
|---|---|---|---|
| `/proc/<pid>/oom_score_adj` | 0 | 核心 -500 / 可牺牲 +500 | 保核心不死 ↔ 可牺牲者更易死 |
| `vm.overcommit_memory` | 0 | 容器配 0/2+ratio | 该失败的提前失败 ↔ 可能误失败 |
| `vm.swappiness` | 60 | →10 | 减少 available 波动 ↔ page cache 略被挤 |
| cgroup `memory.max` | — | 每容器必设 | 隔离爆炸半径 ↔ 需预留 overhead |
| `PodDisruptionBudget` | — | 设最小可用副本 | 断雪崩链 ↔ 调度灵活性略降 |

---

## 五、🔧 思考题(都配参考答案)

**思考题 1(基础):** `dmesg` 里两行 OOM:`"Out of memory: Killed process"` 和 `"Memory cgroup out of memory: Killed process"`,排障含义有何不同?你该分别去调什么?

<details>
<summary>【参考答案】</summary>

- **不带 "Memory cgroup" 前缀**:**整机 OOM**,物理内存+swap 真不够,在内核全局范围内挑 `oom_score` 最高的杀,可能影响任意进程。该去查节点总体内存水位、整机 `overcommit`/`swappiness`、是否有进程把节点吃满;下药点是整机参数和节点调度。
- **带 "Memory cgroup" 前缀**:**cgroup(容器/Slice)级 OOM**,只在该 cgroup 撞到 `memory.max`(v2)/`limit_in_bytes`(v1)时触发,只杀该 cgroup 内部进程,不影响别处。该去查这个容器的内存上限设得是否合理、里面是否有泄漏。
分不清这俩,你会去调整机参数却其实该调容器上限(或反之),越调越乱。这是连环杀现场的第一个分水岭。
</details>

**思考题 2(深入):** 案例里"2.1G 的 Pod 被杀了,3.8G 的反而活了"。用 OOM 评分机制解释这个反直觉现象。

<details>
<summary>【参考答案】</summary>

OOM 杀的是 **`oom_score` 相对高**的,不是 RES 绝对最大的。`oom_score` ≈ 进程占用物理内存比例 + 惩罚项(子进程数、持有页量等) + `oom_score_adj`。本案:
- 2.1G 那个是 java 常驻进程,共享库多、持有大量页,惩罚项推高评分,且 `oom_score_adj=0`,于是即便只占 2.1G 也被整机 OOM 挑中;
- 3.8G 那个**恰好前任给设过 `oom_score_adj=-xxx`(免死金牌)**,评分被压下去,反而在那一轮没被挑中。
这纠正了"满了杀最胖"的朴素误解:评分=内存占比+惩罚+oom_score_adj 三者合力,`oom_score_adj` 这一项能完全改写生死排序。
</details>

**思考题 3(权衡):** 给核心服务设 `oom_score_adj=-500` 是"免死金牌",但为什么它**不能**解决所有 OOM 问题,甚至可能掩盖真问题?

<details>
<summary>【参考答案】</summary>

`oom_score_adj=-500` 只是降低该进程"被整机 OOM 挑中"的概率,**并不减少它真实的内存占用,也不阻止 cgroup 级 OOM**(cgroup OOM 在组内挑,组上限撞了照样死,且 `-500` 只是相对降分)。副作用:
- 若核心服务真有泄漏,免死金牌会让它**一直涨、一直苟活、最后把别的都挤死**,把"一个服务慢"升级成"全节点雪崩",反而更难查;
- 它掩盖了"为什么整机会 OOM"的真问题(节点水位被谁顶高、为什么 available 跌破)。
所以免死金牌是"止血针",必须配合:查真凶(谁顶高水位)、设 cgroup 上限隔离爆炸半径、用 PDB/限流断雪崩链。单靠它,是把 determinable 的问题变成 delayed 的灾难。
</details>

**思考题 4(进阶总账):** 你接手一个"凌晨周期性 OOM 连环杀"的节点。请设计一套**分层止血方案**,覆盖"谁死 / 在哪死 / 为什么连环"三个层次,并说明每层对应的参数或机制。

<details>
<summary>【参考答案】</summary>

三层覆盖:
1. **谁死(临终选择器)**:用 `/proc/<pid>/oom_score_adj` 给核心服务设负值(免死)、给可牺牲的批处理/报表任务设正值(优先牺牲);K8s 下用 `priorityClassName` 表达同意图。
2. **在哪死(爆炸半径)**:每个容器设 cgroup `memory.max`/`limit_in_bytes`,让单容器作死只死自己,不波及节点;节点层面把 `vm.panic_on_oom` 保持 0(别升级成整机重启),`overcommit` 配 0/2+ratio 让"该 malloc 失败的提前失败"而非推到 OOM。
3. **为什么连环(雪崩链)**:入口限流/熔断 + `PodDisruptionBudget`(最小可用副本),断掉"杀一个→流量转移→再杀"的正反馈;批处理任务错峰 + 设 cgroup 上限,别把节点水位顶高促成整机 OOM;`swappiness` 压到 10 减少 available 波动。
三层同时下药,才是"连环杀"的正解;只做一层往往复发。
</details>

---

## 六、第二个现场:cgroup 内存上限误设,触发"组内连环 OOM"

墨:第 19 章第一个现场讲的是"整机 OOM 连环杀"。这第二个现场,把镜头拉到**容器内部**——cgroup 级 OOM,它更隐蔽,因为 `dmesg` 前缀带 "Memory cgroup",很多人看都没看就当成整机问题去调。

`📦 案例:某 K8s 节点,一个 Java 订单 Pod 被反复 OOM kill 重启,但节点物理内存还剩一半。`

### 现象(第 0 层)
Pod 重启告警,`dmesg`:

```
Memory cgroup out of memory: Killed process 7742 (java) ...
```

但 `free -h` 显示节点还有 50% 空闲。**只有这一个 Pod 死,同节点其他 Pod 好好的**。

### 推断 1:整机 OOM?(推错)
你:节点内存满了吗?
墨:查节点 `free`——**一半空闲**,且 `dmesg` 关键字是 **"Memory cgroup out of memory"**(带前缀)。立刻判定:**不是整机 OOM,是这个 Pod 自己的 cgroup 撞到了内存上限**(第 19 章分水岭)。去调节点参数是南辕北辙。

### 再观察:上限设错了
墨:看这个 Pod 的 cgroup 配置——`kubectl describe pod` 显示 `memory limit = 2Gi`,但**这个 JVM 的 `-Xmx` 设了 3G**,加上 JVM 自身 off-heap(线程栈、metaspace、direct buffer),实际常驻远超 2G。于是**容器 cgroup 在 2G 处不断 OOM kill**,JVM 重启,重启后重新吃满 2G 又被杀——单 Pod 内的"连环杀"。

### 调整
墨:两剂药:
1. **对齐 `-Xmx` 和 cgroup limit**:要么把 limit 提到 4G(留 off-heap 余量),要么把 `-Xmx` 降到 1.5G。规则:**容器的内存 limit 必须 > JVM 常驻峰值(含 off-heap),否则 limit 就是个定时炸弹**(第 13 章画像 A 也强调 buffer pool 别占太满)。
2. **别设 `panic_on_oom=1`**:确认是 0(否则容器内 OOM 会升级成节点 panic)。

### 改进:Pod 不再被杀,收口
墨:把 limit 调到 4G 后,Pod 稳定。复盘这个现场和第一个现场的对照,你得到 **OOM 的"两层边界"模型**:
- **整机 OOM**:节点物理+swap 不够,全局挑 `oom_score` 高的杀(第一个现场)。
- **cgroup OOM**:某容器撞自己 `memory.max`,只杀组内进程(本现场)。

两者根因完全不同:整机多是"水位被顶高 + 流量转移雪崩",cgroup 多是"limit 与进程真实常驻没对齐"。**排障第一动作永远是看 `dmesg` 前缀**,这一步错,后面全错。

---

## 七、OOM 排查的"十条肌肉记忆"

墨:把第 19 章两个现场 + 第 12/13 章的 OOM 相关机制,压缩成十条你该刻进肌肉的记忆:

1. **先看 `dmesg` 前缀**:`Memory cgroup` 在前 = 容器内问题;`Out of memory`(无前缀)= 整机问题。这是分水岭。
2. **`oom_score` = 内存占比 + 惩罚项 + `oom_score_adj`**,不是单纯 RES 最胖。
3. **`oom_score_adj`(/proc/<pid>/oom_score_adj)是免死金牌**,范围 -1000~1000,不在 `vm` 下。
4. **`overcommit_memory`**:0 启发式 / 1 狂开空头支票 / 2 严格按 ratio。**容器常 0 或 2+ratio**,让"该失败的提前失败"。
5. **`swappiness` 高会压低 available,间接促成整机 OOM**;容器/DB 设 1~10。
6. **cgroup `memory.max`(v2)/`limit_in_bytes`(v1)是容器级 OOM 边界**,必须 > 进程真实常驻(含 off-heap)。
7. **连环杀的传动链是"杀一个→流量转移→再杀"**,断链靠 PDB + 限流 + 错峰,不是单改 OOM 参数。
8. **`panic_on_oom` 生产必 0**;设 1 等于把单进程问题升级成整机重启。
9. **`vm.panic_on_oom` 与 `kernel.softlockup_panic` 是两回事**:前者 OOM 时重启,后者锁死时重启。
10. **OOM 不是调参问题,常是"规划问题"**:limit 设错、buffer pool 占太满、泄漏——参数只能止血,规划才治本。

---


---

## 八、第三个现场:memory.high 软上限被当硬上限,引来"节流风暴"而非 OOM

墨:前两个现场讲"谁死"(整机 OOM)和"在哪死"(cgroup 硬上限)。这第三个现场,讲 cgroup v2 里一个**最容易被误解**的边界——`memory.high`(软上限)和 `memory.max`(硬上限)长得像,行为却天差地别。把它俩搞混,你会"以为设了上限就不会 OOM",结果要么没拦住、要么拦得太狠把服务拖死。

`📦 案例:某 K8s 节点,一个 Java Pod 没被 OOM kill,却每隔几秒"变慢一截",监控看到这个 cgroup 的 PSI 内存 some 长期高企,但 memory.current 始终卡在一个固定值附近,从没撞 memory.max。`

### 现象(第 0 层)
Pod 没重启、没 OOM kill(排除第二个现场的硬上限),但 RT 周期性变慢、`/sys/fs/cgroup/.../memory.pressure` 的 `some.avg10` 长期 > 5%。`memory.current` 稳定在比如 3.9G,而 `memory.max=4G` 从没被撞到。

### 推断 1:又是 cgroup 硬上限撞了?(推错)
你:是不是 memory.max 太小,撞了就 OOM?
墨:查 `dmesg`——**没有任何 OOM 记录**;且 `memory.current` 离 `memory.max` 还差一截(3.9G vs 4G)。说明没撞硬上限,不是第二个现场的机理。方向转向:"谁在 3.9G 这个位置反复把内存压住?"

### 再观察:memory.high 在起作用(命中)
墨:查 cgroup 配置——发现前任**除了 `memory.max=4G`,还设了 `memory.high=3.9G`**。这正是关键:`memory.high` 是 **v2 的"软上限"**,当 cgroup 内存**试图超过 `high` 时,内核不会杀进程,而是主动、持续地**对这个 cgroup 做**节流(throttle)——压低它的分配速率、更激进地回收它的页**,直到它回到 `high` 以下。于是这个 Pod 一涨到 3.9G 就被内核"掐着脖子"往回压,分配变慢、回收变猛,表现为**周期性变慢但绝不 OOM**。
对比(第 17 章也强调):cgroup v1 的 `memory.soft_limit_in_bytes` **基本是个废柴**——内核并不严格尊重它;v2 的 `memory.high` 才是真生效的软上限。很多人从 v1 迁 v2 时,把"曾经没用的 soft_limit"当成"曾经有用的软上限"搬过来,结果在 v2 上它突然"活了",反而成了性能陷阱。

### 调整
墨:两剂药:
1. **想要"软约束、超了就 throttle 别 OOM"**:保留 `memory.high`,但设得离 `memory.max` 有充裕余量(如 `high=3.2G`、`max=4G`),别让高压节流区间太窄,否则一涨就进"掐脖子"区。
2. **想要"硬边界、撞了就杀、平时不拖慢"**:干脆**不设 `memory.high`**(或设得很大),只留 `memory.max` 做硬 OOM 边界。这是多数"延迟敏感"服务的选择——宁可撞了被杀、由编排层拉起,也不要平时被悄悄节流。

### 改进:变慢消失,收口
墨:把 `memory.high` 调到 3.2G(留 0.8G 缓冲)后,throttle 频率骤降,RT 平稳。复盘:**v1 的 `soft_limit_in_bytes` 是装饰品,v2 的 `memory.high` 是真凶**——迁移时别把"曾经没用的"当"曾经有用的"搬。一句话:`max` 决定"死不死",`high` 决定"平时被不被掐脖子",两件事,两套语义,别混。这也回扣第 12 章那句铁律:**动任何参数前,先问它会让哪个相邻机制被迫补偿**——这里 `high` 的补偿就是"偷偷 throttle 你的服务"。

---

## 实战补遗一：oom_score_adj 配反,把数据库杀了、留着泄漏进程

墨:你想保护数据库不被 OOM 杀,给它的进程设了 `oom_score_adj=-500`。结果某天 OOM,死的偏偏是数据库,泄漏的野进程活得好好的。你懵不懵?

你:我设了 -500 让它最安全啊,怎么会反?

墨:因为 OOM 杀谁,看的是**最终分 `oom_score + oom_score_adj`**(`adj` 为负则减分)。你只给 DB 减了分,却没给野进程加分——而野进程内存占了 80%,它的 `oom_score` 基数本身就高,减 500 也还是比 DB 高。更阴的是:有人手滑把野进程也设了 `-1000`……

### 现象:保护错对象,关键进程先死

一台机器跑着 MySQL(占 20% 内存)和一个有内存泄漏的采集 agent(占 70%,且持续增长)。为"保护 MySQL",运维给 MySQL 设 `oom_score_adj=-500`,但没动 agent(默认 0)。某天 agent 吃满内存触发 OOM,`dmesg` 显示 `Killed process <MySQL pid>`——数据库被杀了,agent 活着。

### 推断(可能推错):先查 MySQL 为什么占那么多

第一推断:「MySQL 自己内存涨了。」——看 MySQL 内存稳稳 20%,不是它涨,是 agent 涨。推错,因为只看了"被杀的"没看"真凶"。

### 真相:adj 是"加减分",不是"免死金牌"

`oom_score` 默认正比于进程内存占用(占得越多分越高,越先死)。`oom_score_adj` 是在这个分数上**加减**(范围 -1000~1000)。MySQL 设 -500:若它占 20%、基数分低,减 500 后可能变负,确实安全;但 agent 占 70%、基数分极高,默认 0,最终分远超 MySQL——**OOM 照样先杀 MySQL**。想保 MySQL,得让 agent 的 adj **更高**(更容易死),或给 agent 设正 adj、给 MySQL 设负 adj 且确保 MySQL 总分最低。

更坑的误操作:有人把 agent 的启动脚本也写了 `oom_score_adj=-1000`(想"它重要别杀"),结果 agent 成了最不可杀的,泄漏时 MySQL 必死。

### 调整:让"该死的"分最高

- 给关键服务(MySQL/Redis)`oom_score_adj=-500~-1000`(接近免死);
- 给**已知会涨、可重启**的进程(采集 agent、批处理)`oom_score_adj=+300~+500`(更容易死);或用 systemd 的 `OOMScoreAdjust=` 在服务文件里固化;
- 验证走 `cat /proc/<pid>/oom_score` 看**最终分**,不是只看 adj;
- 配合 cgroup v2 `memory.max` + `memory.low` 给关键服务留保命内存(第 17/19 章),从源头减少 OOM。

### 再观察

给 agent 设 `+500`、MySQL 设 `-800` 后,复现泄漏:OOM 杀的是 agent,MySQL 稳如老狗,`oom_score` 最终分 agent 最高。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| 关键服务 adj 大负 | 它们"占着不被杀" | 关键进程保命 |
| 野进程 adj 正 | 它们更易被杀 | OOM 杀对的进程 |
| 看 `oom_score` 最终分 | 多一步验证 | 不靠 adj 猜 |

🔧 思考题:`oom_score_adj=-1000` 是不是"绝对不会被杀"?

<details>
<summary>【参考答案】</summary>

几乎不会被杀,但有两个例外:第一,`-1000` 只是让最终分降到最低,若**所有**进程都设了 -1000(或内存彻底耗尽到连内核结构体都分配不出),仍在极端情况下可能被挑;第二,`-1000` 只对**该进程的整机 OOM** 生效,若它属于某个 cgroup 且 cgroup 触发 `memory.max` OOM,杀谁由 cgroup 内的权重/`memory.events` 决定,`oom_score_adj` 在 cgroup OOM 下权重不同(且 cgroup v2 有 `oom_group` 等机制,可能整组一起杀)。所以 -1000 是"用户态整机 OOM 几乎免死",不是跨所有 OOM 场景的免死金牌——关键服务更要靠 cgroup `memory.low` 从源头避免 OOM,而不是只赌 adj。
</details>

---

## 实战补遗二：cgroup v2 `memory.max` 设太紧,流量高峰就 OOM 且连环杀

墨:你给容器设了 `memory.max=2G`(硬上限),想着"限死它别吃别人"。结果正常流量高峰,容器被 OOM 杀,而且同 cgroup 下别的容器也跟着遭殃。你说:2G 不是够了吗?

你:设上限防它膨胀,有错?而且 OOM 不是只杀超的的那个吗?

墨:`memory.max` 触发 OOM 时,**默认杀的是 cgroup 内 `oom_score` 最高的进程**——但如果你的"流量高峰"让整个 cgroup 的多个容器都逼近 2G, OOM 会**连环杀**这个 cgroup 里的进程(尤其开了 `oom_group` 时整组一起杀)。你设的"2G"低于"峰值真实需求",等于把正常高峰判成 OOM。

### 现象:流量高峰必 OOM,平时没事

某 cgroup 跑 3 个容器,设 `memory.max=2G`。平时总占用 1.2G 稳;大促流量来,瞬时到 2.1G → `memory.max` 触发 OOM,杀了一个容器;剩余两个因请求转移压力更大,又逼到 2G → 再杀 → 连环,整组雪崩。`dmesg` `Memory cgroup out of memory`,但你看 `free` 整机还有 10G。

### 推断(可能推错):先查"是不是内存泄漏"

第一推断:「容器内存泄漏,正常该 1.2G 怎么到 2G?」——看平峰 1.2G 稳定、仅高峰到 2.1G,是**流量驱动的正常增长**,不是泄漏。推错,因为把"峰值"当"泄漏"。

### 真相:memory.max 是硬墙,峰值撞墙即 OOM

`memory.max` 是硬上限:当前 cgroup 内存使用 ≥ max,立刻在该 cgroup 内挑 `oom_score` 最高进程杀;若 `memory.oom.group=1`,整组一起杀。你设 2G < 真实峰值 2.1G,等于**把正常高峰判死刑**。而且 cgroup OOM 和整机 OOM 是两套:`free` 看整机有 10G 没用,因为墙在 cgroup 这层(第 17 章)。

### 调整:max 留 headroom + low 保底 + oom_group 慎开

- `memory.max` 设成"峰值 × 1.3~1.5"headroom(如峰值 2.1G → max 3G),别贴着峰值设;
- 用 `memory.low=2G` 软保底(第 17 章实战补遗五),而不是直接硬墙;
- `memory.oom.group=0`(默认),避免一杀杀一组;
- 真正防膨胀:`memory.high` 软上限(超了节流,不直接杀)+ 应用层限流;
- 监控 `memory.events` 的 `max` 计数(`oom`/`oom_kill`),涨就告警。

### 再观察

`memory.max=3G` + `memory.low=2G` 后,高峰 2.1G 不再触顶,OOM 消失,流量回落平稳。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `memory.max` 留 headroom | 多占预留 | 高峰不 OOM |
| `memory.low` 保底 | 无(软) | 优先保、不占坑 |
| `oom.group=0` | 可能单杀 | 不连坐整组 |

🔧 思考题:既然 `memory.max` 会连环杀,为什么不用 `memory.high` 代替?它俩到底怎么选?

<details>
<summary>【参考答案】</summary>

`memory.high` 是**软上限**:cgroup 内存超 high 后,内核**节流**(限制该 cgroup 分配速度、加速回收),让它慢慢降到 high 以下,**不直接 OOM 杀**。适合"想限膨胀、但不想杀进程"的场景。`memory.max` 是**硬墙**:超了必 OOM 杀。选型:绝大多数服务用 `high` 做软限(超了减速而非死),`max` 只设一个"兜底硬墙"且留足 headroom(防真失控才杀);把 `max` 当日常上限贴着峰值设 = 把正常高峰变 OOM,是本节的坑。一句话:`high`=主防线(节流),`max`=最后保险(留余量),别让保险丝当日常开关用——呼应第 19 章 OOM 连环杀那句"杀是最后手段,先靠 `memory.high` 节流,把 OOM 留给真失控",以及第 17 章"cgroup 是资源入口,参数要从整机视角评估外部性"。
</details>

---

## 实战补遗三：oom_score_adj 战略——保核心、杀边缘,而不是杀最胖的

墨:上一节讲了 `oom_kill_allocating_task` 决定"杀撞枪口的"。但更聪明的做法是**提前给每个进程打"该不该死"的分",让 OOM killer 按你的意愿挑**。这把分叫 `oom_score_adj`。

你:这个 adj 怎么算?范围多少?

墨:`/proc/<pid>/oom_score_adj` 是个 **-1000 到 +1000** 的整数,直接加在 OOM 算出的"基础分"(`oom_score`,按内存占用比例 0~1000)上。规则极其简单:
- `adj = -1000`:这进程**永不被 OOM 杀**(焊死,等价于 `oom_score` 强制 0);
- `adj` 为负数:降低被杀优先级(越负越安全);
- `adj` 为正数:提高被杀优先级(越正越先死);
- `adj = 0`:按内存占用公平竞争。

**真实事故**:一个推理服务平台,一台 8 卡 GPU 机器上跑:① 常驻 `scheduler`(调度器,占 200M,但它是"大脑",死了全平台停摆);② 8 个 `worker`(每个占 1 张卡 + 18G 显存对应的大匿名内存,约 20G);③ 偶发的 `preempt` 抢占任务(临时起,占 10G)。某次 `preempt` 和 8 个 worker 同时跑,匿名内存吃满,触发 OOM。默认策略下,OOM 挑了**内存最大的——一个 worker**。结果:一张卡的 worker 死了,调度器把它标记失联,触发整卡重调度,雪崩。

推断:问题不是"杀错了谁",是"没有提前声明谁重要"。OOM 默认只认内存大小,不认业务优先级。

调整:在 `scheduler` 启动脚本里写 `echo -500 > /proc/$!/oom_score_adj`(重要但内存小,给强保护但不焊死,万一它真泄漏还能被杀);在 `worker` 启动脚本写 `echo -300`(业务主力,次保护);在 `preempt` 启动脚本写 `echo +500`(可抛弃的边缘任务,先死)。同时把 `oom_kill_allocating_task` 设 0(让 OOM 按分数挑,而不是杀撞枪口的)。再观察:下次内存吃紧,OOM 精准杀掉 `preempt` 那个可抛弃任务,worker 和 scheduler 安然无恙,平台只丢了一次临时抢占,无雪崩。

你:`-1000` 焊死不是最安全吗?为什么 scheduler 只给 `-500`?

墨:这正是新手最爱踩的坑——**给太多关键进程设 `-1000`,等于把 OOM 的逃生门全焊死**。如果 scheduler 自己内存泄漏涨到吃光整机,而它被 `-1000` 保护,OOM 杀不动它,就会去杀别的,直到把所有能杀的都杀光仍不够,最后**整机无进程可杀 → kernel panic**。所以 `-1000` 只给"绝对不能死且你确信它不会泄漏"的极少数进程(如 `init`/`systemd` 默认就是 `-1000`)。业务进程一律用负数区间(如 -300~-500)留一线"它真泄漏还能被杀"的余地。

🔧 思考题:容器里你能直接 `echo -500 > /proc/<pid>/oom_score_adj` 吗?cgroup v2 的 `memory.oom.group` 和 `oom_score_adj` 是互补还是冲突?

<details>
<summary>【参考答案】</summary>

容器里:你能写,但写的是**容器内 PID namespace 里的 pid 对应的 `/proc/<pid>/oom_score_adj`**,而 cgroup v2 的 OOM 是按 **cgroup 内存超限**触发的(对应 `memory.max`)。两者作用域不同:
- `oom_score_adj` 是**进程级**,决定"同一次 OOM 事件里,这个进程相对其他进程多容易被挑中";
- `memory.oom.group=1` 是**cgroup 级**,决定"一旦该 cgroup 触发 OOM,是只杀一个进程,还是把整个 cgroup 的所有进程一起杀(连坐)"。

它们**互补不冲突**:`oom_score_adj` 负责"组内谁先死",`oom.group` 负责"死了是不是拉全组陪葬"。典型组合:给容器内 `sidecar`(日志/监控)设 `oom_score_adj = +800`(先死),业务主容器设 `memory.oom.group=1`(主容器 OOM 就连坐清掉整个 pod,让 k8s 干净重启,避免半死不活)。注意 `oom_score_adj` 对容器 PID namespace 外的宿主进程不可见,所以想"保护宿主关键进程不被容器 OOM 误伤",得在宿主侧对容器 runtime 进程整体设 adj,而不是进容器里调。
</details>

---

## 实战补遗四：cgroup OOM 与节点 OOM——两套杀手,规则不同

墨:前面讲了 `oom_score_adj`(进程级优先级)和 `memory.max`(cgroup 级硬墙)。但 OOM 实际发生时,**cgroup 内的 OOM 和整机节点 OOM 是两套不同的杀手**,你知道吗?

你:不是都是内存不够就杀吗?cgroup 超限杀 cgroup 内的,节点不够杀全机,区别在范围?

墨:范围只是表面,**触发逻辑和选杀目标都不同**,这才是坑。讲清楚:

**节点级 OOM(传统)**:整机物理内存 + swap 真不够了,内核 `oom_killer` 在所有进程里按 `oom_score`(内存占比 + `oom_score_adj`)挑一个杀。它能杀**任何进程**,包括重要系统进程(除非 `oom_score_adj=-1000` 焊死)。

**cgroup v2 级 OOM**:某个 cgroup 的内存超过 `memory.max`(硬墙),**只在该 cgroup 内部**触发 OOM,内核只从该 cgroup 的进程里挑被杀者。它**杀不到 cgroup 外的进程**,范围被锁死——这是容器的"保险丝"。

**真实事故(混淆两套导致误判)**:一个 K8s 节点,某 pod 内存涨到 `memory.max`,触发**cgroup OOM**,pod 被 `OOMKilled`(K8s 重启它)。但 SRE 看 `dmesg` 找"Out of memory"全局日志,**没找到**——因为 cgroup OOM 的日志在 `memory.events`(`oom` 计数 +1)和该 cgroup 的 `dmesg` 片段里,不一定写进全局 `dmesg` 的明显位置;SRE 误以为是"节点没 OOM、是 pod 自己崩了",去查应用 crash,白查。

推断:区分看**证据在哪**:
- 节点 OOM:`dmesg` 有 `Out of memory: Killed process X`、`oom_kill` 计数(`grep oom /proc/vmstat` 的 `oom_kill` 涨);
- cgroup OOM:`cat /sys/fs/cgroup/.../memory.events` 里 `oom` 和 `oom_kill` 计数涨,且 `kubectl describe pod` 显示 `OOMKilled`、`reason: OOMKilled`、exit code 137。

根因:这个 pod 的 `memory.max`(即 K8s `memory limit`)设得太小,正常流量波动就撞墙,每次撞墙 cgroup OOM 把它杀了重启,形成"频繁 OOMKilled 重启"的死循环,但节点物理内存其实还很充足(其他 pod 都健康)。SRE 之前盯节点 OOM 是找错地方。

调整:① 看 `memory.events` 确认是 cgroup OOM,不是节点 OOM;② 把该 pod 的 `memory limit`(= `memory.max`)调大(或把 `memory.high` 设软上限先节流、不硬杀,第 17 章);③ 若真想让它"超限就杀但别频繁",用 `memory.high` 做软节流 + `memory.max` 留余量当最后兜底,而不是 `memory.max` 卡太紧。再观察:pod 不再频繁 OOMKilled,流量波动时被 `memory.high` 节流(慢一点)但不被杀,稳定。

你:那 cgroup OOM 时,`oom.group=1`(连坐)和节点 OOM 的"杀最胖的"叠加,会怎样?

墨:分两层看:
- **cgroup 内**:若 `memory.oom.group=1`,则该 cgroup OOM 时**整个 cgroup 所有进程一起杀**(连坐),而不是只杀"最胖的一个"。适合"进程组必须同生死"的服务(如主从绑定的网关)。
- **节点级**:若 cgroup OOM 没解决、且**连节点都快没内存了**(cgroup 没限制住、或宿主机本身超卖),节点 OOM 才会启动,按全局 `oom_score` 挑——这时可能杀 cgroup 外的进程(如 `kubelet`、别的 pod),范围更大、后果更惨。

所以正确防御是**两层都设好**:cgroup 内 `memory.max` 当保险丝(锁死爆炸半径在 pod 内)+ `oom.group` 按业务决定连坐与否;节点级靠**不超卖**(节点总 limit 之和 < 物理内存)避免节点 OOM 启动。最怕的是"节点超卖 + cgroup 不设 max"——那节点 OOM 随时可能杀核心系统进程,整机雪崩。K8s 的 `kubelet` 的 `eviction` 机制(节点内存紧张时先驱逐低优先级 pod)就是在这两层之间加的缓冲阀。

🔧 思考题:为什么 K8s 里"设了 memory limit 还是被节点 OOM 杀了"?limit 不是该保护 pod 吗?

<details>
<summary>【参考答案】</summary>

因为 `memory limit` 保护的是"pod 不超自己配额",不是"pod 不被节点 OOM 杀"。两种情况会突破:
1. **limit 设得比实际需要的低**:pod 正常波动就撞 `memory.max` → cgroup OOM 杀它(这是 limit 正常工作,不是节点 OOM,exit 137 / `OOMKilled`)。
2. **节点超卖 / 总 limit 之和 > 物理内存**:所有 pod 都"在各自 limit 内",但**加起来超过节点物理内存**→ 节点物理内存耗尽 → **节点级 OOM** 启动,它不care 你的 cgroup limit,按全局 `oom_score` 杀,可能正好杀了这个"在 limit 内"的 pod(若它 `oom_score` 高)。这时 `dmesg` 有全局 `Out of memory`,`kubectl` 看 `OOMKilled` 但 `memory.events` 里 cgroup 的 `oom` 没涨——这是**节点 OOM 杀的,不是 cgroup 墙杀的**。

所以:设了 limit 仍被节点 OOM 杀 = **节点超卖**的信号。解法:节点不超卖(预留 `system-reserved`/`kube-reserved`)、或降总负载。`limit` 是"pod 内硬墙",节点 OOM 是"物理内存真没了"的终极杀手,两层独立。口诀:limit 防 pod 自己胀爆,节点不超卖防整机 OOM——只设 limit 不控节点超卖,等于只装了户内保险丝却忘了整栋楼的电闸。
</details>

---

---

## 实战补遗五：PSI 早期预警与 systemd OOMPolicy——在被杀之前先知道、被杀之后怎么收

墨：老哥，你等服务 OOM 被杀了才告警，是不是太晚？能不能"内存快顶了"就先知？

你：看监控啊，内存超 80% 就告警。

墨：监控百分比是粗筛，真正精细的是 **PSI（Pressure Stall Information）**——它能量"资源被抢、任务在等"的**时间占比**，比"用了多少内存"早一步预警。这节把 PSI 讲透，再顺手说 systemd 的 OOM 善后。

现象：一个服务内存从 70% 平稳爬到 95% 被 OOMKill，监控在 80% 告警了，但你赶到时已经杀了、业务抖了 1 分钟。你想"更早一步、在还没杀之前就干预"。

推断：提高告警阈值到 85% 更早知。

可能推错：百分比只看"占用"，不看"抢不抢"。内存 95% 但都是 page cache（可瞬间回收），其实**没压力**；反之内存 60% 但匿名页涨得快、分配开始触发**直接内存回收（direct reclaim）**让任务卡住，这时已经有压力了——PSI 能抓到后者，百分比抓不到。

调整：看 `/proc/pressure/memory`：
```
some avg10=1.25 avg60=0.80 total=123456
full avg10=0.40 avg60=0.20 total=45678
```
- `some`：某些任务因等内存而停滞的时间占比（部分卡）。
- `full`：所有任务都因等内存停滞（全员卡，等于"卡死"）。
`some avg10` 持续 >1~2% 就该警惕（有人在等内存）；`full` 出现更危险（没人能推进）。比"内存 80%"早得多——直接回收刚开始时 PSI 就涨，percentage 还早着呢。

再观察：PSI 还能接 `systemd-oomd`（systemd 的户级 OOM 守护进程）：它监视 cgroup 的 PSI `full`，超过阈值就**主动**按策略杀/压某个 cgroup，避免内核硬 OOM 乱杀。这是"软 OOM 治理"。配合 systemd 服务单元的 `OOMPolicy=`：
- `OOMPolicy=stop`：本服务 OOM 时，systemd 停掉它（不杀依赖它的）。
- `OOMPolicy=kill`：杀掉整个 service 及依赖（连坐）。
- `OOMPolicy=continue`：忽略（默认对普通服务）。
对"主从一组"用 `kill`（连坐干净重启），对"被依赖的核心"用 `stop`。

改进：
- 用 PSI 的 `some`/`full` 做**早期压力预警**，比内存百分比早一步、且更准（区分"占得多但可回收"vs"真在抢"）。
- `systemd-oomd` + cgroup `memory.high` 做软治理，把"硬 OOM 乱杀"变成"按策略软杀/压"。
- 服务单元配 `OOMPolicy` 决定被杀后的善后姿态（连同依赖一起 kill，还是只停自己）。

🔧 思考题：PSI 的 `some` 和 `full` 分别回答什么问题？为什么运维常说"full 比 some 可怕十倍"，但它出现得更少？

<details>
<summary>【参考答案】</summary>

PSI 表达的是"任务因等资源（CPU/mem/io）而停滞的时间占比"，是**时间维度**的压力，不是**占用维度**的用量。

- `some`：统计窗口内，**至少有一个**任务因等该资源而停滞的时间比例。它回答"有没有任务在等资源、等资源占了多大比例时间"。比如 `some avg10=5%` 表示过去 10 秒里，平均有 5% 的时间至少有一个任务在等内存——系统在"间歇性卡"。
- `full`：统计窗口内，**所有**非空闲任务都因等该资源而停滞的时间比例（全员阻塞，没人能推进任何工作）。它回答"系统是不是整体卡死了"。`full>0` 意味着这段时间机器"看起来在跑但啥正经活都没干"，是最严重的stall。

为什么 full 可怕十倍但更少：some 是常态——高峰期总有个别任务在等内存/IO，比例不高时系统整体仍能推进（别的任务在跑），所以 some 常见、影响可控。full 是"全员卡死"，此时吞吐归零、延迟无限大，业务完全不可用，破坏性远甚 some。但 full 触发条件苛刻（所有任务同时等同一资源），所以出现频率低——正因低频，一旦出现就更要命，必须立刻干预。运维实践：`some` 用于早预警（趋势），`full` 用于紧急（已卡死）。PSI 还有 CPU 和 IO 的 `/proc/pressure/{cpu,io}`，io 的 `some` 能抓"磁盘成瓶颈"比 iowait 百分比更准（iowait 只看空闲时间，PSI 看"任务真的在等"）。

systemd-oomd 用 PSI 做决策，比内核盲杀聪明：它根据 PSI `full` 阈值 + cgroup 的 `memory.min/low`（保护关键 cgroup）选"该压谁"，把 OOM 从"内核在撞墙瞬间乱杀最胖进程"升级成"用户态按策略软治理"。`OOMPolicy` 则定义被杀后 systemd 的善后：核心依赖服务用 `stop`（别连坐误伤别的），独立无依赖用 `kill`（连坐干净重启，见第 17 章 oom_group 实战补遗）。
</details>

下一章预告

墨:第 19 章我们把 OOM 连环杀拆成了"谁死 / 在哪死 / 为什么连环"三层,你学会了看 `dmesg` 前缀分整机还是 cgroup、用 `oom_score_adj` 发免死金牌、用 cgroup 上限隔离爆炸半径、用 PDB+限流断雪崩链。

下一章(第 20 章)我们下到**磁盘 I/O 毛刺**的现场——服务 RT 曲线上那些"突然多 50ms"的尖峰,`iostat` 一看 `%util` 才 30%,`await` 却飙到几百毫秒。这又是"平均值掩盖分布"的典型:你被 `%util` 骗了。我们要讲清 IO 调度器(none/mq-deadline/bfq)、`nr_requests`、写回拥堵、以及"换 NVMe 没变快"那个老梗背后的真相——很多时候瓶颈根本不在盘,在 buffer pool 命中率和排队。

---

*本章完。磁盘 I/O 毛刺见第 20 章。*
