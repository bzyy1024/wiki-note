# 第 23 章 NUMA 与大页——大内存机器上最隐蔽的两类故障

> 第 18 章的 8 秒超长卡顿,根子之一是 THP 同步 compaction;第 22 章讲了缓存挤压。这一章专攻**大内存机器(128G/256G/多路 CPU)上最隐蔽、且参数最容易被"无脑抄"放大的两类故障**:
> **(a) NUMA 架构下"跨节点访问慢一倍",且某个曾被推荐的参数 `zone_reclaim_mode=1` 反而引发局部回收毛刺;**
> **(b) 大页(透明大页 THP)默认 `always`,在数据库/低延迟服务上可能引发 compaction 冻进程、或内存被大页"鲸吞"导致碎片。**
> 这两类,我们走完整迭代环,把"为什么多路 CPU 机器要特别小心 NUMA/大页""本地性 vs 公平性怎么权衡"讲透。

---

## 一、NUMA 的脸:内存也有"远近"

墨:老哥,先问个很多人没概念的问题。一台 2 路(两颗 CPU)的服务器,CPU 上插着各自的内存条。CPU0 访问"自己旁边那组内存"和访问"CPU1 旁边那组内存",速度一样吗?

你:……应该一样吧?都是内存啊。

墨:**不一样,而且能差一倍。** 这就是 **NUMA(Non-Uniform Memory Access,非一致内存访问)**。现代多路服务器,每颗 CPU 和它"本地"的内存组成一个 **node**,CPU 访问本地 node 内存快,跨 node 访问要过 CPU 间互联(QPI/UPI),**延迟高、带宽低**。

你:那内核不管这个吗?它分配内存时不应该优先给进程分配"离它跑的 CPU 近的内存"吗?

墨:**管,而且这正是坑的来源。** 内核默认尽量给进程分配**本地 node 内存**(保持本地性,快)。但一旦"本地 node 内存紧张",有两个策略:
- **默认(跨 node 取)**:本地不够,就去别的 node 取(慢一点,但**不卡**)。
- **`zone_reclaim_mode=1`(本地回收优先)**:本地不够,**先在本 node 内回收(把本 node 的 page cache/匿名页收一收),实在不行才跨 node**。这听起来"保持本地性更好",但**副作用是:本地回收会触发 direct reclaim,卡住进程**,在内存波动时形成**局部毛刺**。

墨:`zone_reclaim_mode=1` 曾是某些"调优帖"推荐的(为保 NUMA 本地性),但**在多数通用/数据库负载上,它引发的 direct reclaim 毛刺,比"偶尔跨 node 访问慢一点"更伤**。所以现在主流建议是 **保持 0(允许跨 node)**。Redis 等曾因它设错而毛刺,后来官方文档明确建议关掉。

---

## 二、事故 A:NUMA 机器上的周期性延迟毛刺

`📦 案例:某 2 路服务器(256G,每 node 128G),跑内存型 KV 缓存服务。P99 延迟周期性毛刺,但 CPU 利用率才 30%、网卡也没满。`

### 现象(第 0 层)

KV 服务 P99 每隔几分钟出现 30~80ms 毛刺。`top`/`htop` CPU 30%,`iostat` 正常,`网络`正常。看起来"什么都不忙,但就是卡"。

墨:又是"全机不忙却卡"的脸(和第 18 章同款第一印象),但这次不在 swap/compaction,而在**内存访问的 NUMA 本地性**。

### 推断 1:CPU 不够 / 调度问题?(可能推错)

你:是不是 CPU 不够,或者线程被调度到别的核上?

墨:看 `numastat`(NUMA 内存分布)和 `perf` 的 `cache-miss`/`remote-access`——发现**大量"远程内存访问"(cross-node access)**,且毛刺和"本地 node 内存紧张"时间点吻合。又查 `sysctl vm.zone_reclaim_mode` = **1**(前任按某帖设的)。

**结论:不是 CPU 不够,是 NUMA 本地性被破坏 + `zone_reclaim_mode=1` 引发本地回收卡顿。**

### 再观察:锁定"本地回收"的传动链

你:`zone_reclaim_mode=1` 怎么就卡了?

墨:传动链:
```
某 node 内存波动(比如一波请求让本地 node 分配增多)
  → 本地 node 内存跌破 low 水位
  → zone_reclaim_mode=1 → 内核**优先在本 node 内做 direct reclaim**(同步回收)
  → 回收卡住正在分配的线程(几 ms~几十 ms)
  → 表现为 P99 毛刺,而此时 CPU 并不忙(线程在等回收,不在算)
  → 毛刺过后,内存缓过来,又正常
```

注意:**CPU 不忙却卡**,正是因为线程卡在"同步回收内存"这个内核动作上,不是在算数。这和第 18 章"内核暂停类"是同一类机理,只是触发点从 swap/compaction 换成了 NUMA 本地回收。

### 调整 1:关掉 `zone_reclaim_mode`

```bash
sysctl -w vm.zone_reclaim_mode=0    # 允许跨 node 取内存,别本地硬回收
```

墨:改 0 后,本地不够就**去别的 node 取**(慢 30%~一倍,但不卡**),避免了 direct reclaim 卡顿。观察:**毛刺从 30~80ms 降到偶发 <5ms**。但还有**极少量**跨 node 访问的延迟 baseline 偏高。

### 调整 2:把进程"绑"到本地 node(治本,可选)

墨:要彻底消灭跨 node 访问,用 `numactl` 把进程和它的内存**绑在同一个 node**:
```bash
numactl --membind=0 --cpubind=0 ./kv_server     # 进程和内存都钉在 node 0
# 或 --interleave=all:内存轮询分布在所有 node,避免单 node 热点
numactl --interleave=all ./kv_server
```
- `--membind=0`:内存只从 node 0 分配(零跨 node,但若 node 0 不够会 OOM/失败,需保证够)。
- `--interleave=all`:内存**轮询**铺在所有 node,避免单 node 热点,且访问本地性靠"线程也绑对应核"维持。多数大内存服务用 `interleave` 更稳。

另外内核的 **`numa_balancing`**(自动迁移页到访问它的 CPU 所在 node)在 3.x+ 默认开,能帮助纠正"页面漂移",但也会有少量迁移开销,低延迟场景有时关掉 + 手动绑。

### 改进:毛刺归零,收口

墨:关 `zone_reclaim_mode` + `numactl` 绑定,毛刺消失。复盘:

> **NUMA 机器上,`zone_reclaim_mode=1` 是"为了本地性反而丢了延迟"的典型权衡失误。本地回收的卡顿代价 > 偶尔跨 node 访问的慢。保持 0 + 必要时 `numactl` 绑核绑内存,才是大内存机器的正解。**

---

## 三、事故 B:大页(THP)在数据库上"鲸吞 + 冻进程"

墨:第二类大内存故障,是大页。先讲清楚**两种大页**:

| 类型 | 机制 | 特点 |
|---|---|---|
| **THP(透明大页)** | 内核**自动**把 4KB 页合并成 2MB 大页,对应用透明 | 普惠、零配置,但**碎片整理(defrag)可能冻进程** |
| **显式大页(HugeTLB)** | 启动预留 `nr_hugepages` 块 2MB/1GB 页,应用 `mmap(MAP_HUGETLB)` 或 `libhugetlbfs` 用 | **无碎片整理开销、稳定**,但需预留、不灵活 |

你:那 THP 不是好事吗?TLB 命中率更高。

墨:**对应用是好事,但默认 `defrag=always` 是坑**(第 18 章 8 秒卡顿同源)。数据库这种"内存访问极密、对延迟极度敏感"的负载,THP 有两个副作用:

### 事故 B 现象与迭代

`📦 案例:某 MySQL 主库,256G 内存,默认 THP `enabled=always`、`defrag=always`。夜间批量任务时,MySQL 偶发 1~3 秒卡顿。`

- **推断 1**:慢查询?查 slow log 对不上时间 → 推错。
- **再观察**:`/proc/vmstat` 里 `compact_stall` 暴涨,`cat /sys/kernel/mm/transparent_hugepage/defrag` = `always`。
- **推断 2**:THP 同步 compaction 冻进程(和第 18 章同机制)。
- **调整**:把 `defrag` 从 `always` 改 `madvise`(或 `defer` 交后台),甚至 `echo never` 关 THP:
  ```bash
  echo madvise > /sys/kernel/mm/transparent_hugepage/defrag
  # 或数据库官方常建议直接关: echo never > .../enabled
  ```
- **再观察**:卡顿消失,但 **`anon` 大页覆盖下降,TLB 命中略降,吞吐量掉了约 3%**。
- **改进权衡**:对数据库,那 3% 吞吐换"不冻进程"完全值得。或更优:**用显式 HugeTLB 给 buffer pool 预留大页**,既吃大页收益又无 compaction 开销:
  ```bash
  # 预留 64 个 2MB 大页(共 128G)给 MySQL buffer pool
  echo 65536 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
  # my.cnf: innodb_buffer_pool_use_hugetlb = ON (或启动时 mmap MAP_HUGETLB)
  ```

墨:THP vs 显式大页的权衡:**THP 零配置但有 compaction 冻进程风险;显式大页稳定无碎片整理,但需预留、可能浪费(预留了没用就空占)。** 数据库/低延迟服务:**要么 THP 关掉(`never`),要么 defrag 改 `madvise/defer`,要么上显式 HugeTLB**。别留 `defrag=always`。

---

## 四、参数总表(这一章动过的"拿什么换什么")

| 参数 / 文件 | 默认 | 本次取值 | 拿什么换什么 |
|---|---|---|---|
| `vm.zone_reclaim_mode` | 0 | 0(确认) | 允许跨 node ↔ 偶尔远程访问慢 |
| `numactl --membind/--interleave` | — | 绑定 | 零跨 node ↔ 单 node 不够会失败 |
| `transparent_hugepage/defrag` | always | madvise/never | 不冻进程 ↔ 大页覆盖略降 |
| `transparent_hugepage/enabled` | always | (DB 常 never) | 无 compaction 风险 ↔ 无 THP 收益 |
| `hugepages-*/nr_hugepages` | 0 | 预留 | 显式大页稳定 ↔ 预留内存可能空占 |
| `kernel.numa_balancing` | 1 | 1(或低延迟关) | 自动纠正页漂移 ↔ 少量迁移开销 |

---

## 五、🔧 思考题(都配参考答案)

**思考题 1(基础):** 什么是 NUMA?为什么 `zone_reclaim_mode=1` 这个"为了本地性"的参数,反而可能让服务毛刺更严重?

<details>
<summary>【参考答案】</summary>

NUMA:多路服务器每颗 CPU 配"本地"内存组成 node,**CPU 访问本地 node 内存快,跨 node 访问经互联慢约一倍**。内核默认优先分配本地 node 内存保本地性。
`zone_reclaim_mode=1` 的含义:本地 node 内存紧张时,**优先在本 node 内做 direct reclaim(同步回收)而非跨 node 取**。坑在于:本地回收是**同步的,会卡住正在分配的线程几 ms~几十 ms**,在内存波动时形成周期性毛刺;而"跨 node 取"虽然慢 30%~一倍,但**不卡**。所以为了"本地性"设 1,换来的是"回收卡顿",代价比"偶尔跨 node 慢"更大。主流建议保持 0(允许跨 node),必要时用 `numactl` 绑核绑内存治本。
</details>

**思考题 2(深入):** 案例 A 里 CPU 利用率才 30% 却卡。请解释"为什么 CPU 不忙却卡",并说明这和第 18 章哪类机理同源。

<details>
<summary>【参考答案】</summary>

"CPU 不忙却卡"是因为线程**卡在内核的同步内存回收动作上(direct reclaim / compaction),不是在算数**,所以 `top` 里 CPU 利用率不高,但线程实际上"停着等内核干完一件要命的事"。本案是 NUMA 本地回收(direct reclaim 发生在本 node 内)。
它和第 18 章**"内核暂停类"机理同源**——第 18 章是 swap thrashing + THP 同步 compaction 冻进程,本案是 NUMA 本地 direct reclaim 冻进程。三者本质都是"内核在某刻为了内存管理暂停/卡住进程",所以判法一致:看 `vmstat` 的 `b`(D 状态)、`/proc/vmstat` 的 `allocstall`/`compact_stall`、NUMA 下加 `numastat` 的 cross-node 访问。区别只在触发点是 swap / compaction / NUMA 回收。
</details>

**思考题 3(权衡):** 数据库服务,THP 的 `defrag=always` 为什么危险?给出你的参数建议并说明权衡。

<details>
<summary>【参考答案】</summary>

危险:`defrag=always` 表示进程**缺大页时内核同步做 compaction(把零散 4KB 页挪成 2MB 大块)**,碎片多时这个"挪"是同步的,**期间分配线程被冻住几 ms~秒**,对延迟极度敏感的数据库就是随机卡顿(本案夜间 1~3 秒)。
建议(三选一,按场景):
1. **`defrag=madvise` 或 `defer`**:缺页不再同步整理,交给后台 `khugepaged` 异步,不冻进程(代价大页覆盖率略降)。通用稳妥。
2. **`enabled=never`(关 THP)**:彻底无 compaction 风险;代价丢 THP 的 TLB 收益(数据库常可接受,官方常建议)。
3. **上显式 HugeTLB**:`nr_hugepages` 预留 + buffer pool 用 `MAP_HUGETLB`,既吃大页收益又**无 compaction 开销**(最稳但需预留、可能空占)。
权衡核心:数据库要的是"可预测的低延迟",`always` 把"冻进程风险"换"大页覆盖率",不划算;改 `madvise/never` 或显式大页,把风险去掉,那点 TLB 收益损失可接受。
</details>

**思考题 4(进阶总账):** 你接手一台 2 路 512G 的数据库服务器,被反馈"偶发秒级卡顿"。请设计一套**从 NUMA 到 大页 的分层排查**,每层看什么、调什么,并指出哪些参数"宁可不动"。

<details>
<summary>【参考答案】</summary>

分层:
1. **NUMA 层**:`numastat` 看 cross-node 访问量;`sysctl vm.zone_reclaim_mode` 是否 =1(是则改 0);`/proc/vmstat` 的 `numa_*` 和 `allocstall`。调:`zone_reclaim_mode=0` + `numactl --interleave=all` 或 `--membind`。
2. **大页/compaction 层**:`cat .../transparent_hugepage/defrag`(若 always→改 madvise/never);`/proc/vmstat` 的 `compact_stall`(暴涨=同步 compaction 冻进程)。调:defrag 改 madvise,或上显式 HugeTLB 给 buffer pool。
3. **通用暂停类**(和第 18 章合查):`vmstat` 的 `si/so`(swap thrashing)、`dmesg` 的 lockup。
"宁可不动"的参数:`zone_reclaim_mode` 不要为了"本地性"去设 1(保持 0);`transparent_hugepage/defrag` 别留 `always`(但也不要盲目改到影响别的负载,DB 专用机可 `never`);`nr_hugepages` 预留别贪多导致别的进程内存不够。**大内存机器调参第一原则:先确认"哪些是被无脑抄错的",再动,且每次只动一个变量观察。**
</details>

---

## 六、第二个现场:NUMA 绑核不当,一半 CPU 饿死

墨:第 23 章第一个现场讲了"NUMA 本地回收(`zone_reclaim_mode=1`)引发毛刺"。这第二个现场,讲 NUMA 的**另一面坑**——绑核/绑内存不当,导致"资源明明有,却用不上",表现为延迟高但你看哪儿都"没满"。

`📦 案例:某双路(2 socket)机器跑一个 CPU 密集服务,`top` 看 node0 的核全 100%,node1 的核全闲,但服务延迟反而高、吞吐上不去。`

### 现象(第 0 层)
服务吞吐卡在预期的一半,延迟高。`htop` 按 node 分组看:**node0 的核 100%,node1 的核 0%**。机器有 64 个逻辑核,实际只用上了 32 个。

### 推断 1:CPU 不够?(推错)
你:是不是该加机器/加核?
墨:看 `numastat` + `lscpu`——**node1 的 32 核全闲着**。不是"不够",是"没用上"。方向立刻从"扩容"转向"为什么进程全挤在 node0"。

### 再观察:进程全绑在 node0(命中)
墨:查发现:启动时用了 `numactl --membind=0 --cpubind=0`(第一现场案 A 的"绑 node"做法),但**这个服务实际需要的 CPU 远超 node0 的 32 核**,于是所有线程挤在 node0 的 32 核上互相抢,node1 的 32 核空转。第一现场"绑 node"是治"跨 node 访问慢",但**前提是负载真能塞进单 node**;本案负载超过单 node,绑 node 反而把并行度砍半。

### 调整
墨:
1. **`numactl --interleave=all`**:内存轮询铺在所有 node,线程也允许跨 node 调度——虽引入一点跨 node 访问,但**并行度回来了**(总比一半核饿死强)。
2. 或**改架构**:把服务拆成两个实例,各绑一个 node(`--membind=0`/`--membind=1`),让两个 node 都吃饱。
3. 内核 `numa_balancing=1`:让内核自动把页迁移到访问它的 CPU 所在 node,纠正页漂移。

### 改进:吞吐翻倍,收口
墨:改 `interleave=all` 后,node1 的核被用上,吞吐翻倍、延迟降。复盘:**NUMA 的"绑 node"是把双刃剑——负载能塞进单 node 时是优化(零跨 node),负载超单 node 时是自残(并行度砍半)**。判断法是先看"负载的 CPU/内存需求 vs 单 node 容量",再决定绑还是交错。

---

## 七、大内存机器调参总账(把第 23 章收成武器)

墨:把大内存(≥128G、多路)机器的调参收成一张"该动 / 宁可不动"表:

| 层 | 参数 / 机制 | 该动 | 宁可不动(或反向) |
|---|---|---|---|
| NUMA | `zone_reclaim_mode` | 保持 **0**(允许跨 node) | 别设 1(本地回收毛刺) |
| NUMA | `numactl` 绑核绑内存 | 负载≤单 node 时绑;否则 `interleave=all` | 别"不绑 + reclaim=1" |
| NUMA | `kernel.numa_balancing` | 低延迟可关(手动绑);通用开 | — |
| 大页 | `transparent_hugepage/defrag` | DB 设 `madvise`/`never` | 别留 `always`(冻进程) |
| 大页 | 显式 `nr_hugepages` | DB buffer pool 用 HugeTLB | 别贪多预留(空占) |
| 通用 | `vm.watermark_scale_factor` | 大内存调 100~1000 | 别留默认 0.1%(缓冲带太小) |
| 通用 | `vm.min_free_kbytes` | 大内存适当调大 | 别设极小(原子分配丢包) |

墨:大内存机器调参第一原则(第 23 章思考题 4 也强调):**先确认"哪些是被无脑抄错的"(zone_reclaim=1、defrag=always 是头号嫌疑),再动,且每次只动一个变量观察。** 大内存的坑,十次有九次是"把小内存/单路的配置无脑搬过来"——而规模变了,原来的优化就变负担(第 24 章母题五)。

---


---

## 八、第三个现场:显式 HugeTLB 预留吞掉普通内存,反而引发 OOM

墨:前两个现场讲"NUMA 本地回收"和"绑核不当"。这第三个现场,讲大页的**另一面坑**——你为了"吃满大页收益"显式预留了一堆 `HugeTLB`(2MB/1GB 大页),结果**这些大页从普通内存池里被"永久挖走",普通分配反而不够用,非大页的进程/内核结构开始 direct reclaim 甚至 OOM**。这是"优化变负担"的又一个活例(第 24 章母题五:规模/配置变了,原来的优化变负担)。

`📦 案例:某数据库机,DBA 按官方建议 echo 10000 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages(预留 10000 个 2MB 大页 = 20G 给 buffer pool)。预留后,同机上的 agent、监控、sidecar 开始莫名被 OOM kill,且内核日志出现 direct reclaim 抖动。`

### 现象(第 0 层)
DB 的 buffer pool 用上大页了(性能略升),但**同节点其他小进程开始被 OOM kill**,`dmesg` 有 `allocstall`(direct reclaim)抖动。节点总内存 128G,DB buffer pool 才用 20G 大页,理论上还有上百 G 空闲,为什么小进程会 OOM?

### 推断 1:别的进程泄漏?(推错)
你:是不是那些 agent 自己泄漏吃光了内存?
墨:查那些被 OOM 的 agent——RES 才几十 MB,根本不可能吃光。且它们**在 `nr_hugepages` 调大之后才开始死**。方向从"agent 泄漏"转向"大页预留动了全局内存格局"。

### 再观察:大页预留是"预分配黑洞"(命中)
墨:关键机制——`nr_hugepages=N` 是**从普通 buddy 系统里"预挖" N 个大页并锁死**,这些内存**从此从普通内存池消失**,任何普通分配(包括那些 agent 的小匿名页、内核 slab、网络 buffer)都**再也用不到这 20G**。更坑的是:**大页预留只在"系统还有连续 2MB 块"时成功**;若预留时内存已碎片化,内核会反复尝试、迁移、甚至**触发大量直接回收来凑连续块**,这段过程本身就会让普通分配卡顿/被 OOM。于是:`nr_hugepages` 一调大,普通池瞬间少 20G,小进程分配撞墙,agent 被 OOM。

### 调整
墨:两剂药:
1. **预留前先算账**:`nr_hugepages` 的 20G 必须**在"节点总内存 − DB 常驻(含 off-heap) − 其他进程常驻 − 内核/原子分配余量"之后还有富余**时才预留。本案把预留从 20G 降到 8G,且确认其余进程常驻总和远低于剩余,agent 不再死。
2. **预留时机放启动早期**:在内存还没碎片化、连续块充足时(机器刚起、DB 未起)就预留大页,避免"运行时强凑连续块"引发的回收风暴;或用 `hugepagesz` 内核启动参数 + `default_hugepagesz` 在 boot 阶段锁定。

### 改进:agent 不再死,收口
墨:把 `nr_hugepages` 降到 8G 并在启动早期预留后,agent OOM 消失。复盘:**显式大页是"预分配黑洞"——它从普通池永久挖走内存,不是"额外 bonus"**。优化大页收益时,必须同时考虑"普通池被挖走后,其他进程/内核还够不够"。这和第 13 章"画像 A 里 buffer pool 别占太满"是同一句警告的两种说法:**预留/占用必须给全局留余量,否则你的优化就是别人的 OOM。** 大页这把剑,DB 该用,但剑柄在你手里——`nr_hugepages` 写多大,得先问"剩下的普通内存够不够所有人活"。

---

## 实战补遗一：`zone_reclaim_mode=1` 与 `numactl --interleave`——NUMA 上的两个"好心办坏事"

墨:NUMA 双路机器,内存总量够,但某一刻 P99 延迟周期性抖几十毫秒,`numastat` 看两个 node 都有空闲。你第一反应会觉得是"内存不够"吗?

你:多半会,因为延迟抖通常先怀疑内存压力。

墨:内存总量够、两个 node 都闲,就不是"容量"问题,是"分配策略"问题。NUMA 上有两个经典好心办坏事:`zone_reclaim_mode=1`(宁可本地回收也不要跨 node)和 `numactl --interleave=all`(无脑交错)。这俩坑都长着"为性能好"的脸,实际都埋雷。

### 先复习:NUMA 的"远近"代价

CPU 访问"本地 node 内存"快、跨 node 访问慢(多走一次 QPI/UPI 总线,延迟翻倍级)。所以内核默认策略:`zone_reclaim_mode=0`,本地 node 不够时**直接跨 node 分配**——拿一点跨节点延迟,换"不阻塞、不回收"。这对绝大多数服务是最稳的。

### 坑一:`zone_reclaim_mode=1` 把"本地优先"变"本地回收风暴"

设为 1 时,本地 node 内存不足,内核**先在本地 node 做直接回收**(扫 LRU、可能写回脏页、甚至换出),努力把内存"留"在本地,实在不行才跨 node。后果:

- 分配路径被拉长成"回收→再分配",一次分配可能卡几毫秒到几十毫秒;
- 回收失败(`zone_reclaim_failed` 计数涨)还得回退跨 node,等于**白忙一场还更慢**;
- 表现就是周期性 P99 毛刺,且 `numastat` 看不出内存不够(两个 node 都闲,只是分配策略在本地死磕)。

现象:某 NUMA 机器上 `vm.zone_reclaim_mode=1`,跑内存局部性强的服务,`/proc/vmstat` 里 `zone_reclaim_failed` 持续涨,P99 每隔几秒抖一次。`numastat -p <pid>` 显示本地分配比例高但伴随回收。

### 坑二:`numactl --interleave=all` 无脑交错

有人为了"均衡",给进程 `numactl --interleave=all`,让每次分配轮流落到各 node。初衷是避免单 node 满,但副作用:

- 每个分配都可能在"远 node",**本地性归零**,TLB / L1-L3 缓存命中率下降,整体吞吐反而降;
- 对内存局部性强(反复访问同一批页)的服务,交错 = 每次访问都可能在远 node,延迟稳定地差;
- 它解决的是"单 node 容量不够"问题,而大多数服务的瓶颈是"延迟",不是"单 node 容量"。

### 推断(可能推错):先去调水位线

第一推断:「`min_free_kbytes` / `watermark_scale_factor` 太小,触发 direct reclaim。」——调大水位线,毛刺照旧,因为根因不是水位线,是 **zone_reclaim 在本地死磕回收**。

第二推断:「绑核没绑对。」——`numactl --interleave=all` 反而让情况更糟(见坑二),越调越偏。

### 调整:默认 0 + 精准 bind,而非无脑策略

- **首选:**`vm.zone_reclaim_mode=0`(默认),让分配跨 node,用一点跨节点延迟换"无回收毛刺",对绝大多数服务最稳;
- 确有强本地性需求时,用 `numactl --membind=<空闲node>` 把进程**绑到真正空闲的那个 node**,而不是 `interleave=all` 无脑交错;
- 多实例服务,把不同实例 `membind` 到不同 node,天然均衡且保留本地性;
- 监控 `numastat`(各 node 分配/命中)和 `zone_reclaim_failed`,比看总量更早暴露策略问题。

### 再观察:改回 0 + membind

`zone_reclaim_mode=0`、实例按 node `membind` 后,`zone_reclaim_failed` 归零,P99 毛刺消失,吞吐因本地性保留反而略升。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `zone_reclaim_mode=0` | 偶尔跨 node 延迟 | 无本地回收毛刺 |
| `membind` 到空闲 node | 需规划实例布局 | 本地性 + 容量都保 |
| `interleave=all`(不推荐) | 本地性/缓存命中 | 仅解决单 node 容量 |

🔧 思考题:`zone_reclaim_mode=0` 会让跨 node 访问变多,那对"内存局部性极强、且单 node 容量够"的服务,是不是反而该用 1?

<details>
<summary>【参考答案】</summary>

通常不该。原因:即使局部性强,`=1` 的代价是"本地不够时先回收再分配",回收路径的延迟(可能写回脏页)远大于一次跨 node 访问;而 `=0` 跨 node 只是偶尔多走总线,且现代总带宽足够,单次跨 node 访问的代价远小于一次 direct reclaim 卡顿。真正该做的是用 `numactl --membind` 把进程绑到它本地、且容量足够的 node,让"本地分配"成为事实而非靠回收强求。`=1` 只在极特殊"绝对不能跨 node、且能接受回收停顿"的场景才考虑,生产默认远离。
</details>

---

## 实战补遗二：`numactl --membind` 绑错 node——核与内存不同 node 的"远内存"陷阱

墨:你 NUMA 机器上把服务绑到 node0 的核,又 `numactl --membind=1` 把内存绑到 node1(因为 node1 内存空)。你以为"核绑了、内存也绑了,双保险",结果延迟比不绑还差。你哪反了?

你:核在 node0、内存在 node1,不是各得其所吗?

墨:反了。你让 CPU(在 node0)去访问**永远在 node1 的内存**——每一次访存都走跨 node 总线,等于把"本地内存"全变成了"远内存"。正确做法是**核和内存绑在同一个 node**,哪怕那个 node 内存没那么空(或留 headroom 让分配跨 node 但访问本地)。

### 现象:绑了反而更慢

双路 NUMA 机器,node0 CPU 忙、node1 闲;node1 内存空、node0 内存紧。运维 `numactl --cpunodebind=0 --membind=1 ./service`,想"CPU 用 node0、内存用空的 node1"。结果服务延迟比不绑(默认跨 node 分配)还高 30%,`numastat` 显示该进程几乎 100% 是 `numa_miss`(分配落在非本地 node)和 `numa_foreign`(本 node 分配被别人用)。

### 推断(可能推错):先以为绑核没生效

第一推断:「`cpunodebind` 没生效,线程跑错核。」——`taskset`/`numastat` 看 CPU 确实在 node0,生效了。推错。
第二推断:「node1 内存慢(不同型号)?」——同型号,不是。

### 真相:访存距离是按"CPU 所在 node × 内存所在 node"算的

NUMA 延迟 = f(CPU node, 内存 node)。你把 CPU 钉 node0、内存钉 node1,**每次访存都是 node0→node1 的远访问**(延迟翻倍级),且 `membind=1` 强制所有分配在 node1,CPU 永远吃远内存。不绑时默认策略:分配尽量本地(node0 内存紧时跨 node,但至少热数据可能在本地)——综合反而更优。

正确绑定:**核和内存同 node**。`numactl --cpunodebind=N --membind=N`(N 同一个),让本地性成立;或反过来全绑 node1(含 CPU 也放 node1)。若 node0 内存紧,应当**把 CPU 也迁到 node1**,让"核+内存"都在空的 node1,而不是拆开。

### 调整:核内存同 node,或干脆不绑

- 首选:`numactl --cpunodebind=N --membind=N`(N 同一个),让本地性成立;
- 多实例:实例 A 绑 node0、实例 B 绑 node1,各自核内存同 node,整机均衡;
- 若单 node 容量不够:`zone_reclaim_mode=0`(默认)+ 不绑,让分配跨 node 但**访问**靠首次缺页落在发起 CPU 的本地 node(多数分配天然本地),比强制 `membind` 错 node 强;
- 验证:`numastat -p <pid>` 看 `numa_hit`(本地分配)占比应高、`numa_miss` 应低;`perf stat` 看 `remote_access` 远程访存次数。

### 再观察

改成 `--cpunodebind=1 --membind=1`(CPU 也迁 node1,内存同 node)后,`numa_hit` 98%,延迟比"错绑"降 30%、比不绑也略优。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| 核内存同 node 绑 | 需规划实例布局 | 本地性、延迟稳 |
| 不绑(默认跨 node) | 偶发远访问 | 容量灵活、免绑错 |

🔧 思考题:既然"核内存同 node"最好,为什么云上容器常常**不绑** NUMA 也更稳?

<details>
<summary>【参考答案】</summary>

因为容器被调度到哪个 node、和谁共享,是调度器的事,应用层硬 `membind` 反而容易绑错(如本例)。云调度器(如 Kubernetes 的 `topologyManager`)会在"分配 CPU 和内存"时**一起**保证同 node,应用无需自己绑;且容器常是多核共享、NUMA 局部性由调度器保证更准。手动 `numactl --membind` 在"你清楚整机布局、且能控制 CPU 也同 node"时才安全,否则不如交给调度器。一句话:**核内存同 node 的原则不变,但"谁来做这个绑定"该是调度器而非你手敲 membind**——手绑错 node 比不绑更糟,这呼应第 17 章 cgroup/调度器才是资源归属的正确入口。
</details>

---

## 实战补遗三：容器里调 `zone_reclaim_mode` 想优化 NUMA,其实是找错门

墨:你容器里 NUMA 机器上延迟抖,想"优化 NUMA 分配",在容器里 `sysctl vm.zone_reclaim_mode=1`。结果没改善,甚至更抖。我说:你又在容器里找错门了。

你:NUMA 是内核行为,容器里不能调吗?

墨:`zone_reclaim_mode` 是**整机内核**参数(影响所有进程的内存分配策略),容器里 `sysctl -w` 要么 `read-only` 失败、要么改了影响整机所有容器——而且 K8s 的 `topologyManager` 已经在调度层把"CPU 和内存同 node"做好了(第 23 章实战补遗七),你再手调 `zone_reclaim_mode` 是**和调度器打架**。这和第 17 章"容器内存该改 cgroup 不是 sysctl"是同一类坑。

### 现象:容器里调 zone_reclaim,抖动更甚

某容器在 NUMA 双路机上延迟周期抖。运维在容器里 `sysctl -w vm.zone_reclaim_mode=1` 想"让本地 node 优先",结果抖动更频。`dmesg`/`sysctl` 看,值"看似改了"但因为容器是独立 netns/不独立 kernel,实际整机所有容器分配策略都变了,邻居也抖。

### 推断(可能推错):先以为"1 还不够,调到 3"

第一推断:「`zone_reclaim_mode=1` 不够激进,设 3(含写回/换出)。」——越调越糟,因为根因不是"本地回收不够",是"在容器里动了整机参数 + 和调度器冲突"。推错。

### 真相:NUMA 在容器里由调度器管,不在 sysctl 管

- 容器**共享宿主内核**:`sysctl -w vm.zone_reclaim_mode=1` 在容器里要么被 `read-only` 拒绝(很多参数是宿主级),要么改了影响整机——你以为"只调我的容器",实际动了所有容器;
- K8s `topologyManager`(若开)已按 `cpuset` + `memory` **保证同 NUMA node** 分配(第 23 章实战补遗七的"核内存同 node"),你的手调是**重复且冲突**的;
- NUMA 抖动真因若在容器:该看**调度器有没有把 Pod 跨 node 拆**(topologyManager 没开时可能),或 cgroup 内存没隔离,而非手调 `zone_reclaim_mode`。

### 调整:交给调度器 + 查 cgroup,不手调整机参数

- 确认 K8s `topologyManager` 开启(`single-numa-node` 策略),让 Pod 的 CPU/内存同 node;
- 查 Pod 是否真跨 node:`numactl --hardware` + `kubectl describe` 看调度;
- 若需 NUMA 控制,用 `numactl --membind` 在**Pod 启动命令**里(第 23 章实战补遗七),而非 `sysctl` 整机级;
- 容器里别碰 `zone_reclaim_mode`(它是整机开关,且默认 0 已是最稳);
- 验证:调度同 node 后,`numastat -p <pid>` 看 `numa_hit` 高、抖动消失。

### 再观察

关掉容器里的 `zone_reclaim_mode` 手调 + 开启 `topologyManager=single-numa-node` 后,Pod 落单 node、核内存同 node,抖动消失,邻居也不受影响。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| 交调度器管 NUMA | 少一个手动开关 | 核内存同 node、不冲突 |
| 不手调整机参数 | 失去"局部控制感" | 不连坐邻居 |

🔧 思考题:既然 `zone_reclaim_mode` 默认 0 最稳,为什么内核还要提供 `=1`?容器场景到底该不该碰它?

<details>
<summary>【参考答案】</summary>

`=1` 给"单 node 内存满、但希望优先本地回收而非跨 node"的特定 NUMA 优化场景(如某数据库明确要本地内存局部性)。但默认 `=0`(跨 node 分配、无本地回收毛刺)对绝大多数负载最稳(第 23 章实战补遗六讲过 `=1` 的回收毛刺)。容器场景:**不该碰**——因为容器共享宿主内核,`=1` 是整机级开关,会连坐所有邻居;且 K8s `topologyManager` 已在调度层解决"核内存同 node",手调是重复+冲突。一句话:NUMA 优化在容器里属于"调度器/cgroup 的职责",不是 `sysctl` 的职责(呼应第 17 章"容器资源该改 cgroup 不是 sysctl")——找错门调一周,不如让调度器做一次对。这也再次印证第 0 章那句:调参第一步是"确认这参数守哪扇门、在哪个层",容器里大部分"整机级 sysctl"都是你不该伸手的地方。
</details>

---

## 实战补遗四：NUMA 绑核 + 网卡中断亲和——"内存近、中断也近"才真快

墨:前面讲了 `numactl --membind` 把内存绑到本地 node(实战补遗七讲过错绑 node 反而慢)。但 NUMA 调优还有另一半常被忘:**网卡中断亲和(IRQ affinity)**。你知道网卡收包的中断默认跑在哪个 CPU 上吗?

你:默认是不是所有中断都堆在 CPU0,或者内核自动均衡?

墨:默认是内核 `irqbalance` 做均衡,但它**不保证"收包的 CPU"和"处理这个包的进程所在 node"一致**。于是一条跨 node 的路径就出现了:网卡 DMA 把数据放到的内存,可能在 node1;处理进程绑在 node0 的核;进程读数据时跨 node 访存,慢一截。单看 `numactl` 你以为绑对了,其实**中断这一半没绑**,性能差 10~20% 找不出原因。

**真实事故**:一个低延迟交易网关,绑了 `numactl --cpunodebind=0 --membind=0`(进程和内存都在 node0),本地压测延迟 20µs。上生产接真实网卡流量,延迟变成 35µs。查 `numactl` 没绑错,查 `zone_reclaim_mode` 也没问题(实战补遗七讲过),卡在"哪慢了"。

推断:用 `cat /proc/interrupts` 看网卡中断(`eth0-TxRx-*`)分布——发现 `irqbalance` 把大部分网卡队列中断分到 **node1 的 CPU**!于是:网卡在 node1 的 CPU 上收包、DMA 到 node1 内存,但处理进程在 node0,它读包要去 node1 取数据(跨 node),且进程在 node0 发的回复包又可能 DMA 到 node0——双向跨 node。

调整:手动绑网卡中断亲和到 node0 的 CPU(和处理进程同 node):
```bash
# 把 eth0 的每个队列中断绑到 node0 的对应核
for irq in $(grep eth0 /proc/interrupts | awk -F: '{print $1}'); do
  echo 0-7 > /proc/irq/$irq/smp_affinity_list   # node0 的核 0-7
done
```
同时确认 `irqbalance` 关掉或设白名单(否则它又给你搬走)。再观察:中断、内存、进程三者在 node0 内闭环,延迟回到 21µs,跨 node 访存归零。

你:那容器里怎么绑网卡中断?pod 能碰 `/proc/irq` 吗?

墨:又回到"找错门"的老问题——`/proc/irq/<n>/smp_affinity` 是**宿主节点级**,容器里(无特权)碰不了,且它影响整块网卡所有流量,不该由某个 pod 改。正确做法:
- 宿主/init 阶段按"哪类流量归哪个 node"统一绑好 IRQ 亲和,或交给支持 NUMA 的 CNI/网络插件;
- 容器侧靠 K8s `topologyManager`(第 23 章讲过)+ 节点已绑好的 IRQ,保证 pod 被调度到"网卡中断所在的 node",自然闭环;
- 单 pod 想"独占某 node 的核 + 对应网卡队列",用 `static` CPU 管理器 + `topologyManager=single-numa-node` 策略,让调度器把 pod 塞进 IRQ 同 node。

所以 NUMA 调优的**完整闭环**是三件事都对齐:① 进程 `cpunodebind`(算在哪)② 内存 `membind`(存在哪)③ 网卡中断 `smp_affinity`(DMA 到哪)+ 三者同 node。只做前两个、漏了第三个,就是本事故"本地快、生产慢"的根源。

🔧 思考题:`irqbalance` 到底该开还是关?它不就是自动做中断均衡的吗,为什么生产常关?

<details>
<summary>【参考答案】</summary>

`irqbalance`(默认开)适合"通用负载、不想管 NUMA"的场景——它自动把中断铺到各 CPU,避免单核过热。但**延迟敏感 / NUMA 敏感服务要关或限制**,原因:
1. 它不感知你的"进程绑在哪个 node",可能把网卡中断分到别的 node,造成跨 node 访存(本事故);
2. 它的均衡是"周期性重算",会**把正在跑的中断搬来搬去**,搬运瞬间引入抖动(对低延迟是致命的);
3. 多队列网卡本就可以"每个队列绑一个核",手动绑比自动均衡更可控。

生产做法:延迟敏感节点 `systemctl stop irqbalance`(或设 `IRQBALANCE_BANNED_CPUS` 把关键核排除),然后**手动**把网卡队列中断绑到"服务进程所在的 node/核"。通用节点可留 `irqbalance` 省心。口诀:要稳定低延迟 → 中断手动绑、和进程同 node;要省心通用 → 留自动均衡。别让"自动"在你最在乎延迟的地方偷偷搬中断。
</details>

---

## 实战补遗五：THP defrag 的"分配阻塞"——开 THP 后 malloc 偶发卡

墨:第 23 章讲了手动大页和 THP 的取舍。但即使你**开了 THP**(某些负载真需要大页 TLB 收益),还有个隐藏开关会坑你:`transparent_hugepage/defrag`。它干嘛的?

你:`defrag` 不是"整理碎片让大页更容易分配"吗?这还有坑?

墨:对,但"整理"的方式有讲究。`/sys/kernel/mm/transparent_hugepage/defrag` 有三个模式:`always`(同步整理)、`defer`(延迟)、`madvise`(只对标了 `MADV_HUGEPAGE` 的区域)。坑在 `always`:**分配 2M 大页时,若没有现成的空闲大页,内核会同步做内存碎片整理(搬页、合并),这个动作会阻塞当前 `malloc` 线程几十毫秒甚至更久**——而且是**同步阻塞**,不是后台。

**真实事故**:一个开了 THP 的分析服务(它需要大页的 TLB 收益),偶发 `malloc` 卡 50~200ms(用 `perf` 抓到卡在 `compact_zone` / `__alloc_pages_direct_compact` 调用栈里)。业务没改代码、流量没变,就是间歇性"分配卡"。`pprof` 看业务 CPU 正常,卡在内核分配路径。

推断:卡在 `compact_zone` = THP 的 **defrag 在同步整理碎片**。验证:`cat /sys/kernel/mm/transparent_hugepage/defrag` 是 `always`,且 `cat /proc/vmstat | grep compact` 看 `compact_stall`(同步整理导致分配停顿的次数)在卡顿时刻暴涨。根因:内存碎片多时,分配 2M 连续页需要整理,`defrag=always` 让它**就地整理、阻塞分配线程**——这比"合并大页"更阴,因为它直接卡你的 `malloc`/`mmap`。

调整:① 把 `defrag` 从 `always` 改成 `defer` 或 `madvise`:`defer` 模式下,分配大页失败时**不阻塞、先给 4K 页**(后台 khugepaged 之后慢慢整理补大页),业务不卡;`madvise` 更精细,只对显式 `madvise(MADV_HUGEPAGE)` 的区域做整理,其余走 4K。② 配合预留 `nr_hugepages` 减少运行时分配需求(第 3 章)。再观察:`compact_stall` 归零,`malloc` 卡顿消失,大页 TLB 收益仍在(后台 khugepaged 持续补)。

你:`defrag=always` 和 `khugepaged`(后台合并)的区别?一个阻塞一个不阻塞?

墨:对,这是 THP 两个**独立**的整理机制,常被混:
- **`khugepaged`**(第 13、18 章讲过):**后台线程**,扫描、把连续 4K 页合并成 2M 大页,**不阻塞**业务(但它搬页时短暂持锁,造成第 18 章那种几十 ms 卡顿,那是另一码事);
- **`defrag=always`**:**分配路径上的同步整理**,你 `malloc` 要 2M 页、没有现成的,内核当场搬内存整理出连续 2M,**阻塞你的线程**直到整理完。

所以 THP 的卡顿有两来源:khugepaged 后台搬页(轻微、偶发) + defrag=always 同步整理(直接卡 malloc,重)。生产建议:**`enabled=always`(或按需) + `defrag=defer/madvise`**——保留大页收益,但把"整理"从同步阻塞改成异步/按需,彻底消除 `malloc` 卡顿。这也是为什么第 13 章我说"Go 服务关 THP"——Go 既不需要大页 TLB 收益(堆访问分散),又最怕这种同步卡顿;而真正需要大页的数据库,正确姿势是"开 THP 但 defrag 设 defer",不是一刀切关。

🔧 思考题:你预留了 `nr_hugepages`(手动大页),还需要 THP 的 `defrag` 吗?两者冲突吗?

<details>
<summary>【参考答案】</summary>

不冲突,且是互补的两套:
- `nr_hugepages`(手动大页,HugePages):启动时从物理内存**预留**一块连续 2M 页池,应用 `mmap(MAP_HUGETLB)` 或 `shmget` 用,**分配时直接从预留池取,不触发运行时整理**——所以手动大页路径根本不经过 THP 的 defrag,没有 `malloc` 卡顿。
- THP 的 `defrag`:针对**没预留大页、靠内核自动合并**的路径(匿名内存的 THP)。如果你已经用 `nr_hugepages` 手动大页,且应用显式 `MAP_HUGETLB`,那 THP 的自动合并对你意义不大,可关 THP 或设 `defrag=defer` 当兜底。

所以:
- 数据库/DPDK 类"显式用 HugePages 的热数据" → 预留 `nr_hugepages` + 关 THP(或 defrag=defer),零整理卡顿、TLB 收益稳;
- 通用负载"想偷懒自动用大页" → 开 THP 但 `defrag=defer`,避免同步卡顿,接受后台整理。

两者不冲突:手动大页是"预分配池",THP defrag 是"自动合并的整理策略"。用了手动大页就基本不需要 THP 自动合并;留 THP 自动合并就务必把 defrag 调成非阻塞模式。口诀:要稳延迟 → 手动大页 + 关 THP 自动整理;图省事 → 开 THP 但 defrag 绝不设 always。
</details>

---

---

## 实战补遗六：K8s topologyManager 与跨 node 内存带宽——绑核绑内存别只绑一半

墨：老哥，你在 K8s 里跑对延迟极敏感的服务，会把 Pod 绑到固定 NUMA node 吗？

你：会用 `resources.limits` + 节点亲和性，但没专门管 NUMA。

墨：K8s 里 NUMA 对齐是 TopologyManager 管的，不是你手动 `numactl`。我拆过一次——只绑了 CPU 没对齐内存，反而更慢，因为跨 node 取内存带宽塌了。

现象：一个低延迟交易 Pod，节点 2 个 NUMA node（各 16 核 + 本地内存 64G）。Pod limit 设 8 核，被调度到核 0-7（都在 node0），但容器里的分配偶尔落到 node1 的内存（因为节点整体内存压力，内核把匿名页分到 node1），结果访存要走 node 间总线（QPI/UPI），延迟翻倍、带宽受限，P99 抖动。

推断：绑了 CPU 到 node0 就 NUMA 对齐了。

可能推错：CPU 绑 node0 ≠ 内存也在 node0。内存分配看的是**当时哪个 node 有空闲页**，不由你的 CPU 亲和性自动保证。只绑 CPU 不约束内存，就会出现"核在 node0、内存在 node1"的跨 node 访问——延迟从 ~80ns（本地）涨到 ~140ns（跨 node），且 node 间总线带宽有限，多核并发访存时更挤。这就是"绑了一半"的坑。

调整：K8s 里用 **TopologyManager**（kubelet 特性，需开启且策略设 `single-numa-node` 或 `restricted`）：它让 CPU Manager（绑核）、设备 Manager、内存 Manager **联合决策**，保证"分配的 CPU 和内存落在同一个 NUMA node"。配合：
- `CPUManager` 策略 `static`：Pod 设 `guaranteed` QoS（limits==requests），且 `cpu` 为整数核，kubelet 把它绑到独占核。
- `memoryManager`：保证内存从同一 node 分配（单 node 放不下才跨 node，策略 `single-numa-node` 下直接拒绝调度，避免跨 node）。
这样 Pod 的核和内存同 node，零跨 node 访存。

再观察：手动 `numactl --membind=0` 在容器里**多数不生效**——因为容器共享宿主的 NUMA 策略命名空间（除非开启 `--cpuset-mems` 的 cpuset cgroup v2），且 K8s 调度器不知道你手动绑了啥，可能把 Pod 调度到 node1 的核但你 membind 到 node0，变成"核 node1、内存 node0"反向跨 node。所以容器里的 NUMA 对齐必须交给 **TopologyManager**，手动 numactl 是找错门（与第 23 章"容器里调 zone_reclaim 找错门"同理——层级错了）。

改进：
- 延迟敏感 Pod：开 kubelet 的 TopologyManager（`single-numa-node`）+ CPUManager（`static`），并设 `guaranteed` QoS 让绑核生效。
- 别在容器里手动 `numactl`/`zone_reclaim_mode`，交给编排层统一管。
- 验证对齐：`numactl --hardware` 看节点拓扑 + `cat /sys/fs/cgroup/.../cpuset.cpus` + `cpuset.mems` 确认同 node。
- 跨 node 带宽塌方的信号：`numastat` 看 `interleave`/`foreign` 页数（跨 node 访问多 = 没对齐）；`perf` 看 `remote_dram` 访问占比。

🔧 思考题：为什么"核在 node0、内存在 node1"比"核内存都在 node1"更糟？TopologyManager 的 `single-numa-node` 和 `best-effort` 策略，对延迟敏感服务该选哪个，为什么？

<details>
<summary>【参考答案】</summary>

NUMA 的代价在于**内存访问的不对称延迟**：每个 CPU 有"本地内存"（直连的 node），访问延迟低、带宽高；访问"远端 node 内存"要过 node 间互连（Intel 的 UPI / AMD 的 Infinity Fabric），延迟高（约 1.5~2 倍）且带宽受互连限制。

"核在 node0、内存在 node1"最糟，是因为它把**最热的路径（CPU 取指令+数据）全变成跨 node 访问**：每条 load/store 都走远端，延迟翻倍、且所有核的远端访问挤在同一条互连总线上，带宽争抢让多核并发时更慢。而"核内存都在 node1"至少本地快。所以对齐的核心是"**核和内存在同一 node**"，只绑 CPU 不绑内存等于把最关键的访存变成远端。

TopologyManager 策略选择：
- `none`（默认）：各 Manager 独立决策，不保证对齐——会出"绑了一半"的坑。
- `best-effort`：尽量对齐，对齐不了也不拒绝调度（可能跨 node 跑，但 Pod 能起来）。适合"尽量快、但不能因对齐失败而 Pending"的服务。
- `restricted`：必须对齐，对齐不了则**拒绝**该 Pod 的部分资源（更严格，可能 Pod 起不来）。
- `single-numa-node`：最严——要求**所有**资源（CPU/内存/设备）都在同一个 NUMA node，否则**整个 Pod 不调度（Pending）**。

延迟敏感服务选 `single-numa-node`（或至少 `restricted`）：宁可靠拢到同 node 牺牲一点"调度成功率"（Pending 了再调度别的节点），也不要跨 node 跑导致延迟翻倍。代价是节点碎片化时 Pod 可能 Pending——这正是 TopologyManager 和调度器要解决的"碎片化 vs 对齐"权衡，靠节点资源规划缓解。

验证：`numactl -H` 看拓扑；Pod 内 `cat /sys/fs/cgroup/.../cpuset.mems` 应等于 `cpuset.cpus` 所在 node；`numastat -p <pid>` 看 `numa_foreign`（跨 node 访问页数）应接近 0。`perf stat -e numa_misses,remote_dram` 能量化跨 node 访存代价——这是判断 NUMA 对齐有没有真正生效的硬指标，比"看着绑了核"可靠。
</details>

下一章预告

墨:第 23 章我们把大内存机器上最隐蔽的两类故障——NUMA 本地回收毛刺、THP 同步 compaction 冻进程——讲透了,你学会了 `zone_reclaim_mode` 保持 0、`numactl` 绑核绑内存、`defrag` 别留 always。

到这里,**真实诊断案例集(第 18-23 章)全部收口**。下一阶段进入**哲学与工具箱**:
- 第 24 章 **优化哲学**:把全书反复出现的母题(懂微观才配谈优化、平均值掩盖分布、缓冲区治突发不治过载、通用机制+专家逃生口……)提炼成可复用的思维模型;
- 第 25 章 **工具箱**:`perf`/`ftrace`/`bpftrace`/`vmstat`/`iostat`/`sar`/`ss`/`nstat` 各自怎么用、看什么、什么时候上哪个;
- 第 26 章 **结语**:把全书串成一张"程序从源码到硬件"的认知地图,给你一张"遇事查哪章"的检索表。

---

*本章完。优化哲学见第 24 章。*
