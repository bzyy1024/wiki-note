# 第 12 章 `/proc/sys/vm` 总地图——内存这颗炸弹的引信清单

> 第 06 章我们讲了内存的**机制**:buddy/slab、水位线、direct reclaim、swap、OOM。那章里参数是"随机制穿插"的。
> 这一章换个角度——你最早点名要的:"`/proc/sys/vm` 这下面很多参数,介绍在什么场景怎么用。" 我们**把它当一个家族来解剖**:先建一张分类地图(哪些参数是安全阀、哪些是日常旋钮、哪些是泄洪阀),再逐个钉死含义、默认值、调大调小各换来什么。
> 为什么单独开三章(vm 总地图 + 场景化 + 实战)?因为 **`vm` 下的参数,是整套 sysctl 里最容易"抄错"的**。内存是全局共享资源,你为一个进程调的 vm 参数,会悄悄影响整台机器上所有进程。调对了救命,调错了炸一片。

---

## 一、先建分类地图:别把"安全阀"当"日常旋钮"

墨:老哥,先别急着背参数表。我问你一个根本问题:`/proc/sys/vm` 下面几十个参数,它们**生效的时机**一样吗?

你:……应该不一样?有些是常驻生效的,有些是快溢出时才管用?

墨:**对,而且这个区别决定了你怎么对待它。** 我把 vm 参数分成三类,记死:

| 类别 | 什么时候生效 | 你该怎么对待 | 例子 |
|---|---|---|---|
| **① 日常旋钮** | **持续生效**,微调内存子系统的常态行为 | 按负载画像**长期固定**配,别天天动 | `swappiness`、`vfs_cache_pressure`、`watermark_scale_factor` |
| **② 安全阀** | **接近临界(水位线/阈值)时才发力的兜底逻辑** | 主角是"别让它误触发",必要时调高阈值留缓冲 | `min_free_kbytes`、`dirty_ratio` |
| **③ 泄洪阀** | **平时不动,出事了手动/自动放一下** | 应急用,**不是调优项** | `drop_caches`、`panic_on_oom`、`oom_kill_allocating_task` |

墨:这个分类是灵魂。**最经典的作死就是:把③泄洪阀当①日常旋钮天天拧。** 比如有人为了"清内存"写个 cron 每 5 分钟 `echo 3 > drop_caches`——这不是调优,这是**每隔 5 分钟主动把所有 page cache 清空,逼着所有读请求重新落盘**。等于为了"看起来内存干净"而自残 I/O。后面第 14 章我们会专讲这种事故。

你:那我怎么知道某个参数是哪类?

墨:看它"调大"之后是"更激进"还是"更保守"。**调大后更保守、更接近临界才动作 → 安全阀**;**调大后改变常态行为 → 日常旋钮**;**写个特殊值触发一次性动作 → 泄洪阀**。下面逐个过,每个我都标了类别。

---

## 二、overcommit 三兄弟:malloc 的"空头合同"由谁担保

> 第 06 章说过:malloc 是空头合同,真正给物理页是在你访问触缺页时。但"到底允不允许你开这张空头支票",由 overcommit 三兄弟决定。

| 参数 | 类别 | 默认 | 含义 |
|---|---|---|---|
| `vm.overcommit_memory` | ① 日常旋钮 | 0 | 0=启发式(允许略超)、1=永远允许(狂开空头支票)、2=严格按 commit 上限 |
| `vm.overcommit_ratio` | ① 日常旋钮 | 50 | 模式 2 下,允许 commit 的物理内存上限 = `物理内存 × ratio% + swap` |
| `vm.overcommit_kbytes` | ① 日常旋钮 | 0(覆盖 ratio) | 模式 2 下直接指定允许 commit 的**额外**千字节数(与 ratio 二选一) |

墨:`overcommit_memory` 三个值,是内存管理的"风险偏好开关":

- **=0(默认,启发式)**:内核估算"看似能commit的"略超物理+swap。正常情况下够用,但**突发大 malloc 可能直接失败(EAGAIN)**——这是第 14 章事故一的主角。
- **=1(总是允许)**:malloc 几乎永远成功(直到真触缺页发现没物理页才 OOM)。**好处**:大预分配的程序(如 JVM `-Xmx` 直接开 32G)不会因 commit 上限起不来;**代价**:一旦真的内存不够,OOM Killer 会更猛、更不可预测地杀进程。
- **=2(严格)**:commit 总量不能超过 `物理×ratio% + swap`。**好处**:malloc 提前失败,程序能优雅处理(EAGAIN),OOM 几乎不发生;**代价**:你得精确配 ratio/kbytes,否则明明还有 swap 却 malloc 失败(又见第 14 章)。

你:那数据库/缓存服务该用哪个?

墨:**没有银弹,看你能不能优雅处理 malloc 失败。** 能优雅处理的(有重试/降级)→ 用 2(严格,换"可预测");不能处理、一失败就崩的 → 用 1(宽松,换"不轻易失败、但赌 OOM")。绝大多数"裸跑的 Go/Java 服务"其实扛不住 malloc 失败,所以很多人默默用 1 或 0——**代价是把不确定性推到了 OOM 那一刻**。这就是权衡。

---

## 三、水位线三件套:内核什么时候开始"慌"

> 第 06 章讲了 min/low/high 三条水位线,direct reclaim 在低于 low 时触发。这里讲你能在 sysctl 里调的两个旋钮。

| 参数 | 类别 | 默认 | 含义 / 调大换来什么 |
|---|---|---|---|
| `vm.min_free_kbytes` | ② 安全阀 | 动态(视内存) | **保留的硬下限**。调大 → 更多内存永远不分配,减少 direct reclaim 概率、给原子分配(如网卡 DMA)留缓冲;**换来**:可用内存变少、可能浪费。调小 → 省内存,但水位太低时分配会卡甚至网络丢包(第 14 章事故三)。 |
| `vm.watermark_scale_factor` | ① 日常旋钮 | 10(=0.1%) | low~high 之间的"缓冲带"占内存比例 ×0.1%。调大 → 更早开始异步回收、更平滑;换来:略微多占内存做缓冲。大内存机器(几百 G)建议调大到 100~1000(即 1%~10%),否则默认 0.1% 的绝对缓冲太小,一有波动就 direct reclaim。 |
| `vm.extra_free_kbytes` | ② 安全阀 | 0(老内核) | 在 min 之上额外保留,给原子分配留余量。新版多并入 min_free_kbytes 逻辑。 |

墨:水位线的微妙在于:**它管的是"什么时候开始慌"**。默认 0.1% 的缓冲带,在 4G 内存上是 4MB(够),在 256G 内存上还是约 256MB——但 256G 机器上 256MB 缓冲相对业务突发太小,**一有分配尖峰就跌破 low,direct reclaim 卡住线程**(第 06 章的 `allocstall`)。所以大内存机器调 `watermark_scale_factor` 是常识,不是玄学。

---

## 四、脏页四件套:写的"谎言"什么时候被揭穿

> 第 06、07 章都碰过脏页:write 进 page cache 就返回"成功",后台异步刷盘。这四件套决定"后台多积极"和"前台被逼刷盘的阈值"。

| 参数 | 类别 | 默认 | 含义 / 调大换来什么 |
|---|---|---|---|
| `vm.dirty_background_ratio` | ① 日常旋钮 | 10(%) | 脏页占**可用内存**达此比例,**后台**线程开始异步刷盘。调小 → 更早后台刷,写延迟更稳但 I/O 更频繁;调大 → 攒更多再刷,突发写吞吐高但尖峰时主存脏页多。 |
| `vm.dirty_ratio` | ② 安全阀 | 20(%) | 脏页达此比例,**前台进程被阻塞**亲自刷盘(sync 式)。调小 → 前台更早被逼刷,写卡顿更平但频;调大 → 允许更多脏页,但若突然大量写,会触发"前台 sync 卡几百 ms~秒"(第 07 章 300ms 日志卡顿的近亲)。 |
| `vm.dirty_background_bytes` / `vm.dirty_bytes` | ①/② | 0(禁用) | 同上,但用**字节绝对值**而非比例。大内存机器更推荐用 bytes(比例在大内存下算出的绝对值大得离谱)。设 bytes 后对应 ratio 失效。 |
| `vm.dirty_writeback_centisecs` | ① 日常旋钮 | 500(=5s) | 后台刷盘线程**多久醒一次**。调小 → 脏页滞留短、更及时;换来:唤醒开销。 |
| `vm.dirty_expire_centisecs` | ① 日常旋钮 | 3000(=30s) | 脏页"年龄"到此时才被认为该刷(即使没到 ratio)。控制脏页最长滞留。 |

墨:两对"前台 vs 后台"的节奏旋钮,本质是**在"写吞吐"和"故障时的数据风险/卡顿"之间拉锯**。数据库/消息队列这类"写密集且不能丢"的负载,常把 `dirty_ratio`/`dirty_background_ratio` 调小,让脏页别攒太多(否则机器宕机丢的脏数据少);而批量导出/日志类"不怕丢、要吞吐"的,反而调大。

你:那 `dirty_bytes` 和 `dirty_ratio` 同时设会怎样?

墨:**设了 bytes 那一项,对应的 ratio 就失效**(内核以 bytes 为准)。这是常见坑:你以为在调 ratio,结果之前的 bytes 配置还生效着,改 ratio 没反应。调之前先看另一个是不是非零。

---

## 五、swap 与回收倾向:脏数据 vs 干净缓存谁先死

| 参数 | 类别 | 默认 | 含义 / 调大换来什么 |
|---|---|---|---|
| `vm.swappiness` | ① 日常旋钮 | 60 | 内核"把匿名页换到 swap 的积极性"。0=尽量不换(除非水位危险),100=积极换。调小(如 1~10)→ 保匿名页在内存,降延迟,但 page cache 易被挤、可能 direct reclaim 卡;调大 → 更积极腾 page cache,但匿名页进 swap 后访问变慢(第 14 章事故二)。**容器/DB 常设 1~10,桌面/通用可保持 60。** |
| `vm.vfs_cache_pressure` | ① 日常旋钮 | 100 | 回收 **inode/dentry 缓存**的积极性。>100 更积极回收目录缓存(省内存但 `ls`/路径解析变慢);<100 更保护目录缓存(适合大量小文件遍历的场景)。 |
| `vm.zone_reclaim_mode` | ① 日常旋钮 | 0 | NUMA 下,某 zone 内存紧时是否**优先在本 node 内回收**而非跨 node 取。0=允许跨 node(通常更快);设 1 会优先本地回收,在 NUMA 大内存机器上**反而引发局部 reclaim 卡顿**(第 23 章)。Redis 等曾因它设错而毛刺。 |

墨:`swappiness` 是被误解最深的参数之一。很多人以为"设 0 就关 swap"——**错,0 不是关 swap,是"除非水位危险绝不主动换"**。要真关 swap 得 `swapoff`。而且把 swappiness 设 0 的副作用常被忽略:内核不换匿名页,**page cache 一旦紧张就只能回收干净缓存,导致文件读命中率掉、direct reclaim 概率升**,延迟抖动反而更大。所以"数据库设 swappiness=0"未必最优,**设 1~10 让内核有一点点换出余地,往往比 0 更稳**。

---

## 六、OOM 与 compact:被杀的规矩、碎片的整理

| 参数 | 类别 | 默认 | 含义 / 调大换来什么 |
|---|---|---|---|
| `vm.panic_on_oom` | ③ 泄洪阀 | 0 | 0=OOM 时杀进程(不宕机);1=**OOM 直接 kernel panic 重启整台机器**。生产机几乎都该 0。设 1 等于把"一个进程吃内存"升级成"全机重启",除非你是单应用嵌入式且重启即恢复,否则别碰。 |
| `vm.oom_kill_allocating_task` | ③ 泄洪阀 | 0 | 0=OOM 按 `oom_score` 挑最胖的杀;1=**直接杀"正在申请内存惹毛 OOM 的那个"**。设 1 在某些"请求触发大分配"的服务上更"冤有头",但可能杀错无辜。 |
| `vm.oom_dump_tasks` | ③ 泄洪阀 | 1 | OOM 时是否把所有进程的内存占用 dump 到 dmesg。排障神器,保持 1。 |
| `vm.compact_memory` | ③ 泄洪阀 | (写 1 触发) | 写 `1` 触发**一次性内存压缩整理**(把零散空闲页合并成大块),缓解外部碎片。临时救急用,不是调优项(第 23 章大页场景会用到)。 |
| `vm.compact_unevictable_allowed` | ① 日常旋钮 | 1 | compact 时是否允许移动 unevictable(如 mlock)页。1 提高整理成功率,换来极少量开销。 |
| `vm.max_map_count` | ① 日常旋钮 | 65530 | 单进程**虚拟内存区(VMA)上限**。第 04 章提过:线程多/映射多(如 JVM、Elasticsearch)会触顶,报错 "max map count"。ES 官方建议设 262144。调大几乎无副作用(除非真有泄漏)。 |

墨:OOM 那几个都是**泄洪阀**——平时别动,死过一次才去定规矩。`oom_score_adj`(每进程,在 `/proc/<pid>/oom_score_adj`,范围 -1000~1000)才是你**日常能给关键进程"免死金牌"**的旋钮:给核心服务设 -500,它就几乎不会被 OOM 挑中(第 19 章实战)。注意它不在 `vm` 下,是 per-process,别找错地方。

---

## 七、drop_caches 与保留:正经用法 vs 作死

| 参数 | 类别 | 默认 | 含义 |
|---|---|---|---|
| `vm.drop_caches` | ③ 泄洪阀 | 0 | 写 1=清 page cache;2=清 slab(inode/dentry);3=全清。**写后自动回 0**。这是"手动泄洪",不是调优项。 |
| `vm.admin_reserve_kbytes` | ② 安全阀 | 8192 | 给 root 保留的内存,防止普通进程把内存吃光后 root 都登不进去救场。别乱调小。 |
| `vm.user_reserve_kbytes` | ② 安全阀 | 动态 | 给普通用户保留,防单个用户挤垮整机。 |
| `vm.page-cluster` | ① 日常旋钮 | 3 | 换入/预读时一次读几个页(2^3=8)。调大加速顺序换入,换来多读无用页。 |
| `vm.percpu_pagelist_fraction` | ① 日常旋钮 | 0 | 每 CPU 页缓存占内存比例。多核机器高分配压力下适当调大,减少 zone 锁竞争。 |
| `vm.stat_interval` | ① 日常旋钮 | 1(s) | `/proc/vmstat` 统计刷新间隔。调大降开销,换来统计变粗。 |
| `vm.mmap_min_addr` | ② 安全阀 | 4096 | 禁止 mmap 到地址 0 附近,防 NULL 指针解引用提权攻击。安全项,保持默认。 |

墨:`drop_caches` 的正经用法只有两种:**(a) 测性能时排除 page cache 干扰**(先 drop 再测,看"冷"表现);**(b) 内存被 page cache 占满、且你确认应用不需要那些缓存时手动释放**。除此之外的"定时清缓存脚本"都是自残(第 14 章事故四)。记住:**page cache 是好事,清它等于主动制造磁盘 I/O**。

---

## 八、`/proc/sys/vm` 总表(拿什么换什么)

| 参数 | 类别 | 默认 | 拿什么换什么 |
|---|---|---|---|
| overcommit_memory | ① | 0 | 不轻易失败 ↔ 把不确定性推到 OOM |
| overcommit_ratio | ① | 50 | 可 commit 上限精确 ↔ 可能浪费/误失败 |
| min_free_kbytes | ② | 动态 | 防 direct reclaim/保原子分配 ↔ 可用内存减少 |
| watermark_scale_factor | ① | 10(0.1%) | 大内存机器更平滑 ↔ 略多占内存 |
| dirty_background_ratio | ① | 10% | 写延迟稳 ↔ I/O 更频繁 |
| dirty_ratio | ② | 20% | 限制脏页峰值 ↔ 前台 sync 卡顿风险 |
| dirty_writeback/expire | ① | 5s/30s | 脏页滞留短 ↔ 唤醒开销 |
| swappiness | ① | 60 | 保匿名页低延迟 ↔ page cache 被挤风险 |
| vfs_cache_pressure | ① | 100 | 回收目录缓存省内存 ↔ 路径解析变慢 |
| zone_reclaim_mode | ① | 0 | NUMA 本地性 ↔ 局部 reclaim 卡顿 |
| panic_on_oom | ③ | 0 | 不整机重启 ↔ 可能杀错进程 |
| oom_kill_allocating_task | ③ | 0 | 冤有头 ↔ 可能杀无辜 |
| compact_memory | ③ | 触发 | 解碎片 ↔ 一次性开销 |
| max_map_count | ① | 65530 | 多映射不死 ↔ 极少量内存 |
| drop_caches | ③ | 0 | 应急清缓存 ↔ 自残 I/O(若滥用) |

---

## 九、🔧 思考题(都配参考答案)

**思考题 1(基础):** 为什么说"把 `drop_caches` 写进 cron 每 5 分钟清一次"是自残?它清掉的到底是什么,清掉之后下一次读会发生什么?

<details>
<summary>【参考答案】</summary>

`drop_caches` 清的是 **page cache(文件数据缓存)和/或 slab(inode/dentry 缓存)**。page cache 的存在意义是"读过的文件下次命中内存,纳秒级,不碰盘"。每 5 分钟强制清空,等于**每 5 分钟主动销毁所有读缓存**,之后所有 `read`/文件访问都重新走块层落盘(第 07/08 章,机械盘随机读 8~15ms/次)。后果:磁盘 I/O 暴涨、读延迟陡增、`cache` 命中率掉到接近 0、业务感知"周期性卡顿"。正经用法只有两种:性能测试时排除缓存干扰、或确认不需要时手动释放。凡是"为了看起来 free 多"而定时清缓存,都是用 I/O 性能换一个心理安慰。
</details>

**思考题 2(深入):** 一台 256G 内存的机器,默认 `watermark_scale_factor=10`(0.1%),业务偶发几秒卡顿,`vmstat` 里 `allocstall`(direct reclaim)周期性飙升。请解释根因,并给出调参方向。

<details>
<summary>【参考答案】</summary>

根因:`watermark_scale_factor=10` 意味着 low~high 缓冲带只有内存的 0.1%,在 256G 上是约 256MB。业务突发分配时,free 内存很容易跌破 low,**触发 direct reclaim(同步回收,卡住分配线程)**,表现为 `allocstall` 飙升 + 卡顿。而异步 kswapd 的回收"缓冲带"太小,来不及在跌破前平滑回收。

调参方向:把 `vm.watermark_scale_factor` 调大到 100~1000(即 1%~10%),让 low~high 缓冲带变宽(256G 上变成 2.5G~25G),**更早触发异步 kswapd、给回收留出提前量**,避免跌到 low 触发 direct reclaim。同时可略增 `min_free_kbytes` 保原子分配。这是大内存机器常识性调优,不是玄学。注意:换来的是"常驻略多内存做缓冲",可接受。
</details>

**思考题 3(权衡):** `swappiness=0` 常被"数据库调优帖"推荐。请指出它的真实含义与可能反效果,并给出更稳妥的取值建议。

<details>
<summary>【参考答案】</summary>

`swappiness=0` **不是关 swap**,而是"除非水位线危险,绝不主动把匿名页换出"。反效果:内核不换匿名页,**page cache 一旦紧张就只能回收干净文件缓存**,导致文件读命中率下降、`allocstall`/direct reclaim 概率上升,延迟抖动反而更大。所以"设 0 保内存低延迟"在内存偏紧时可能适得其反。更稳妥:**设 1~10**(给内核一点点换出余地,让匿名页能适度进 swap 腾出 page cache),既能保低延迟又不至于让文件缓存被挤。真正要"几乎不 swap"靠的是**内存够 + `vm.min_free_kbytes` 留缓冲**,不是把 swappiness 压到 0。数据库/容器常用 1~10 而非 0。
</details>

**思考题 4(进阶总账):** 综合本章分类地图,假设你是一个 SRE,接手一台"内存参数被前任抄了一堆"的机器。请列出你会**第一优先检查**的 3 个"可能是泄洪阀被当日常旋钮滥用"的信号,以及对应参数。

<details>
<summary>【参考答案】</summary>

泄洪阀/安全阀被当日常旋钮滥用,是最常见且最伤的误操作。优先查 3 个:
1. **`vm.drop_caches` 被定时脚本写**:查 `crontab` / systemd timer 有无 `echo N > drop_caches`。信号:`free` 的 `cache` 周期性归零、磁盘 I/O 周期性暴涨。正经用法仅性能测试/手动。
2. **`vm.panic_on_oom=1`**:查 `/proc/sys/vm/panic_on_oom`。信号:任何 OOM 直接整机重启(比杀进程严重得多)。除非单应用嵌入式,生产必设 0。
3. **`vm.overcommit_memory=2` 但 `overcommit_ratio` 没适配**:查两者。信号:明明有 swap、内存也没满,大 malloc 却 EAGAIN 失败、服务起不来(第 14 章事故一)。需按"物理×ratio%+swap"重新适配或改回 0/1。
其他候补:`zone_reclaim_mode=1`(NUMA 局部 reclaim 毛刺)、`dirty_ratio` 被设得过小导致前台频繁 sync。
</details>

---

## 十、vm 参数的联动效应(别孤立调一个)

墨:前面把每个 vm 参数单独钉死了,但真实系统里它们**互相牵制**——你动一个,可能逼着另一个被迫补偿,单点调参因此翻车。我先给你三个"一动牵一片"的联动,免得你照抄时踩连环坑。

**联动 1:`swappiness` ↔ 水位线 ↔ direct reclaim。** 你把 `swappiness` 压到 0(想保匿名页低延迟),但如果 `min_free_kbytes` 和 `watermark_scale_factor` 没跟上、水位线太低,内存一波动,内核"不换匿名页"就只剩下"回收干净缓存"或"直接 direct reclaim"两条路——结果匿名页没保住,反而 direct reclaim 卡顿(第 18 章的幽灵卡顿同源)。**所以"压 swappiness"必须配"水位带加宽 + 原子分配留够"三件套一起动**,缺一个都可能更抖。

**联动 2:`dirty_ratio` ↔ 写回 ↔ 内存水位。** `dirty_ratio` 调大(想写吞吐),脏页攒多,前台被逼 sync 那一刻一次性写盘,写的过程本身可能吃内存、压低水位,又触发 swap 介入。`dirty_background_ratio` 是它的异步兄弟——若只调大 `dirty_ratio` 不调 `dirty_background_ratio`,后台不提前刷,所有压力都攒到前台 sync 那一哆嗦。两个要一起看。

**联动 3:`overcommit` ↔ OOM ↔ `oom_score_adj`。** 你把 `overcommit_memory=2`(严格),malloc 提前失败,但 JVM 类"一失败就崩"的程序扛不住(第 14 章事故一)——你要么改程序优雅处理 EAGAIN,要么用 `oom_score_adj` 保它,要么退回 0/1。**overcommit 的选择和"你的程序能不能优雅失败"强耦合**,不能脱离程序特性孤立定。

你:所以调 vm 参数像调音频 EQ,不是拉一个推一个。

墨:**对,而且比 EQ 更狠——EQ 拉错只是难听,vm 拉错能冻全机。** 给你一句铁律:**动任何 vm 参数前,先问"它会让哪个相邻参数被迫补偿?补偿不了的代价我扛不扛得住?"** 下一章(13)的场景化,就是把这套联动按负载画像固化成组合。

---

## 十一、vm 调参决策树:拿到一台新机器先问什么

墨:给你一张"接手新机器/新容器,vm 该怎么定"的决策树,按顺序问,当 checklist 用:

- **Q1 内存多大?** < 32G 小机器:`watermark_scale_factor` 可保持默认 0.1%(缓冲带够);≥ 128G 大内存:**必须调 `watermark_scale_factor=100~1000`**(第 12 章思考题 2),否则默认 0.1% 的绝对缓冲带在几百 G 上太小,一波动就 direct reclaim。
- **Q2 跑什么负载?** 数据库/缓存(内存敏感低延迟)→ `swappiness=1~10`、THP `defrag=madvise/never`、`zone_reclaim_mode=0`;通用/桌面 → `swappiness=60` 可保持、`overcommit=0`;容器 → 每容器 cgroup 内存上限必设,宿主 `swappiness` 偏低、`overcommit=0/2+ratio`。
- **Q3 有没有 swap?** 有 swap 且想防颠簸 → `swappiness` 压 10;无 swap → `min_free_kbytes` 必须留够保原子分配(第 14 章事故三:太小连网卡 DMA 都丢包)。
- **Q4 NUMA?** 多路机器 → `zone_reclaim_mode=0` + `numactl` 绑/交错,否则本地回收毛刺(第 23 章)。
- **Q5 大页需求?** 数据库要大页 → 上**显式 HugeTLB** 给 buffer pool,别留 THP `defrag=always`(冻进程)。

你:这张树能直接当上线 checklist?

墨:**能,而且比抄任何调优帖都稳。** 它就是把前面所有"拿什么换什么"压缩成提问。每次上新机器,按 Q1~Q5 走一遍,80% 的 vm 隐患在出事之前就被你定掉了。

---


---

## 十二、`sysctl` 的"假生效":你以为改了,其实被 tuned / 启动顺序 / 容器权限覆盖了

墨:老哥,前面我把几十个 vm 参数钉死了,你肯定手痒去改过几个。但你有没有遇到过这种事:`sysctl -w vm.swappiness=10` 写下去,`sysctl vm.swappiness` 一看还是 60?或者写在 `/etc/sysctl.conf` 里,重启后 `cat /proc/sys/vm/swappiness` 还是默认值?这种"改了没生效"的坑,比参数本身还常见。这一节把三类"假生效"根因讲透,否则你前面学的全白搭。

### 12.1 第一类:被 `tuned` 守护进程覆盖(最阴)

`📦 案例:某 SRE 在 /etc/sysctl.conf 里写了 vm.swappiness=10、vm.dirty_ratio=10,重启后一查,swappiness 还是 60、dirty_ratio 还是 20。他怀疑文件没加载,手动 sysctl -p 加载后值变对了;但过几分钟自己又变回默认——像有只手在偷偷改回去。`

**推断 1:配置文件没加载?(推错)**
你:`sysctl -p` 手动加载能生效,说明文件本身没问题,是"加载时机"问题。先怀疑 `/etc/sysctl.conf` 没被开机加载——但大多数发行版 `systemd-sysctl.service` 会开机读它,且手动加载已生效,排除"没加载"。

**命中:tuned 在"加载之后"又覆盖了一遍**
墨:根因是 **`tuned` 服务**(多数服务器发行版默认装并自启)。`tuned` 是"动态调优守护进程",它会根据激活的 profile(如 `throughput-performance`、`latency-performance`)在启动时**主动写一批 sysctl**。`throughput-performance` 这个 profile 里就显式把 `vm.swappiness` 设回 60、把 `vm.dirty_*` 设回激进值。于是启动顺序变成:`systemd-sysctl` 读了你的 conf(生效)→ 稍后 `tuned` 启动,用自己的 profile 又写一遍(覆盖)。你看到的就是"手动加载对、过会儿变回去"。

排查与治本:
- `tuned-adm active` 看当前激活哪个 profile;
- `tuned-adm list` 看有哪些;
- 要么 `tuned-adm off`(关闭 tuned,简单粗暴),要么把你的参数**写进 tuned 自己的配置**:在 `/etc/tuned/<profile>/tuned.conf` 的 `[sysctl]` 段里写,或新建一个自定义 profile;
- 最稳的做法是直接管住 tuned:把你的参数放在 tuned profile 之内,而不是和它打架。

墨:教训:**生产机若跑了 tuned,你的 /etc/sysctl.conf 改动可能被它覆盖**。调参前先 `tuned-adm active` 确认有没有这只"看不见的手"。这是"改了没生效"里最阴的一类——因为它不是不生效,是"生效后又被改回去",你手动查的瞬间可能正好在两次覆盖之间,极具迷惑性。和第 14 章"调了一周没用"同源,只是这只手在内核之外。

### 12.2 第二类:写了文件但没加载 / 被后序文件覆盖

墨:还有两种更朴素的"假生效":
- **(a) 写了 conf 但没 `sysctl -p`**:`/etc/sysctl.conf` 只在开机(`systemd-sysctl`)和手动 `sysctl -p` 时加载。`sysctl -w` 是运行时直接写 `/proc/sys`,**立刻生效但不持久**;你若只 `sysctl -w` 没写文件,重启即丢。反过来,只写文件不 `-p`,当前运行值不变。
- **(b) `/etc/sysctl.d/` 里的文件字母序靠后覆盖靠前的**:`sysctl.d` 按文件名**字典序**加载,后加载的覆盖先加载的。你写了 `/etc/sysctl.d/10-my.conf`,结果发行版自带 `/etc/sysctl.d/50-default.conf` 在它之后加载、把你的值覆盖。排查:`sysctl --system` 会按序打印每次加载,能看到谁覆盖了谁;或 `journalctl -u systemd-sysctl` 看开机加载日志。

### 12.3 第三类:容器里多数 vm 参数根本不可写

墨:第 13 章讲过"容器里别拧 vm"。这里补机制:容器内执行 `sysctl -w vm.swappiness=1`,**大概率报 `sysctl: setting key "vm.swappiness": Read-only file system` 或静默无效**。因为容器默认挂载 `/proc/sys` 为只读,且 `vm.*` 多不属于"可被 namespace 隔离的安全参数"(只有 `net.*` 部分、少数 `kernel.*` 在特权容器内可写)。即便 `docker run --privileged` 或 `--sysctl`,也只允许白名单里的少数参数。**在容器里折腾 vm.* 基本是徒劳**,要调的是宿主(影响所有容器)或 cgroup(第 17 章)。

### 12.4 验证一个 vm 参数"真的"在生效的标准动作

墨:给你一套**确认参数生效的 SOP**,别再"改完就当成了":
1. **写文件**:把值写进 `/etc/sysctl.d/99-<name>.conf`(而非只 `sysctl -w`);
2. **加载**:`sysctl -p /etc/sysctl.d/99-<name>.conf`(或 `sysctl --system`);
3. **核对当前运行值**:`sysctl vm.swappiness`(读 `/proc/sys/vm/swappiness`)——这是唯一真相,`sysctl -a` 也是从这里读;
4. **排除覆盖**:`tuned-adm active` 看是否被 tuned 管;查启动日志确认加载顺序;
5. **长期验证**:过一天再 `sysctl vm.xxx` 看是否还在——防止"被 tuned 深夜改回"。

墨:这套 SOP 把"我以为改了"变成"我证明它改了"。vm 调参的最后一步永远是**回去读 `/proc/sys` 确认**,而不是"我写了 conf 就算完"。再好的参数,不验证生效,等于没调。

---

## 实战补遗一：给你的服务画一张 `vm` 画像——四类负载对应四组参数

墨:你打开 `/proc/sys/vm` 一看几十个参数,第一反应是不是"我该调哪几个"?

你:对啊,总不能全背吧。

墨:不必背。按"负载画像"分四类,每类只动 4~5 个关键参数,其余保持默认。这一节给你一张"画像→参数集"的速查,把第 12 章的总地图从"字典"变成"处方"。

### 四类负载画像

1. **计算密集(CPU bound,少 IO/少分配):**如计算服务、算法。
   - 关键:`vm.swappiness=1`(别让它把匿名页换出去偷延迟)、`transparent_hugepage` 按需、其余默认。基本不用动 `vm`。
2. **内存密集(大堆/大缓存,如 Redis、ES、JVM):**
   - 关键:`vm.overcommit_memory=1`(避免 commit 上限误杀大分配,前提你真有内存)、`vm.swappiness=1`、`vm.min_free_kbytes` 留原子分配余量、`admin_reserve_kbytes` 保命、`transparent_hugepage` 延迟敏感服务关。
   - 真实坑:某 Redis 设了 `swappiness=1` 但仍偶发延迟——查是 `bgsave` 时 page cache 被回收挤压,调到 `swappiness=0` + `memory.low` 护 cgroup 才稳(呼应第 19/23 章)。
3. **IO 密集(日志/消息队列/数据库,大量写盘):**
   - 关键:`vm.dirty_ratio=10` / `dirty_background_ratio=5`(防脏页触顶前台 sync 卡写,第 18 章)、`vm.dirty_expire_centisecs`/`dirty_writeback_centisecs`(回写节奏)、`vm.vfs_cache_pressure`(海量小文件时调高,第 22 章)。
   - 真实坑:某 Kafka 集群 `dirty_background_ratio` 默认 10%,后台 writeback 过早启动打散批量刷盘,吞吐腰斩;调到 `dirty_background_ratio=5` + 增大 `dirty_ratio=20` 让批量更聚合,吞吐回正。
4. **网络密集(网关/代理,高并发连接):**
   - 关键:`vm.min_free_kbytes` 留够(网卡 DMA 要原子分配,少了丢包,第 14 章)、`vm.swappiness=1`、其余默认。网络密集服务卡顿常是内存余量不够导致分配失败,不是网络本身。

### 一张处方表(拿什么换什么)

| 画像 | 必守参数 | 拿什么 | 换什么 |
|---|---|---|---|
| 计算密集 | swappiness, THP | 少 | 不被 swap 偷延迟 |
| 内存密集 | overcommit, swappiness, min_free, THP | 常驻少量保留内存 | OOM 不误杀、保命通道 |
| IO 密集 | dirty_*, vfs_cache_pressure | 更多脏页缓冲 | 写不卡、批量聚合 |
| 网络密集 | min_free_kbytes | 常驻保留 | 网卡不丢包 |

### 墨叔一句:画像先于参数

**先回答"我的服务是哪类负载",再动参数。** 反过来"看哪个参数顺眼调哪个",就是第 0 章说的"负优化"——你调的恰好是这类负载不该动的。

🔧 思考题:一个"既计算密集又网络密集"的网关,该按哪类画像调?冲突时怎么取舍?

<details>
<summary>【参考答案】</summary>

网关的核心是"高并发连接 + 低延迟转发",归网络密集(内存余量 > 计算)。优先守 `min_free_kbytes`(防网卡丢包)和 `swappiness=1`(防转发缓冲区被换),THP 关(延迟敏感)。计算密集那侧通常不是瓶颈(转发逻辑轻),不必为它牺牲网络侧的内存余量。取舍原则:**延迟敏感的路径优先保**——网关的"不丢包、不卡转发"比"计算快点"重要得多,所以网络密集画像压计算密集画像。这也体现第 12 章"总地图"的精髓:参数有主次,按你的关键路径排,别平均用力。
</details>

---

## 实战补遗二：`vm` 默认值陷阱速查——哪些默认值是给桌面/通用设的,生产该改

墨:你拿着第 12 章的画像去调参,但有没有想过:那些"默认 60"、"默认 10%"的值,本就不是给你的生产服务器设的?

你:默认值不就是"官方推荐"吗?

墨:默认值是**通用/桌面**场景的妥协,不是服务器最优。这一节给你一张"`vm` 默认值陷阱"速查:哪些默认在你的生产上该改、为什么。

### 五个最常踩的 `vm` 默认值陷阱

1. **`vm.swappiness=60`(默认):**桌面让桌面"流畅换出",但服务器(尤其 DB/缓存)该 `=1`。60 意味着内存稍紧就积极换出匿名页 → 延迟抖。改 `1`。
2. **`vm.dirty_ratio=20` / `dirty_background_ratio=10`(默认):**桌面容忍大脏页缓冲。服务器高 IO 时,20% 脏页触顶 = 前台 `fsync` 同步刷几十 GB,写卡几秒(第 18 章)。改 `dirty_ratio=10` / `dirty_background_ratio=5`。
3. **`vm.min_free_kbytes`(默认极小,按内存比例算):**小内存机器上默认几十 MB,不够网卡原子分配 → 丢包(第 14 章)。按"网卡缓冲 + 并发"调到数百 MB~1G。
4. **`vm.vfs_cache_pressure=100`(默认):**平衡回收 inode/dentry 与 page cache。海量小文件元数据场景,100 让 inode cache 被过快回收 → `stat` 暴增(第 22 章)。调 `200`。
5. **`vm.overcommit_memory=0`(默认启发式):**通用安全,但 Redis/大分配服务 `fork` 时可能被拒(第 13 章)。这类服务改 `=1` + cgroup 兜底。

### 一张"默认→生产"改值表

| 参数 | 默认 | 服务器建议 | 为什么 |
|---|---|---|---|
| swappiness | 60 | 1 | 别积极换匿名页 |
| dirty_ratio | 20 | 10 | 防脏页触顶前台卡 |
| dirty_background_ratio | 10 | 5 | 后台回写更早、更平 |
| min_free_kbytes | 极小 | 数百 MB~1G | 网卡不丢包 |
| vfs_cache_pressure | 100 | 100~200(看场景) | 元数据多则调高 |
| transparent_hugepage | always/madvise | never(延迟敏感) | 防 khugepaged 毛刺 |

### 墨叔一句

**默认值是"不会错",不是"最好"。** 它保证你开机能用,但不保证你生产最优。第 12 章画像 + 本节陷阱,合起来就是"你的生产 `vm` 该长什么样"。

🔧 思考题:既然默认值不是最优,为什么我不该"无脑全按建议值改"?

<details>
<summary>【参考答案】</summary>

因为"建议值"是另一类通用妥协,未必贴合你的负载画像(第 12 章)。比如 `swappiness=1` 对 DB 好,但对**计算密集、几乎不碰内存**的服务毫无意义(它本就不 swap);`dirty_ratio=10` 对写多服务好,但对纯读服务没影响。无脑全改 = 又回到"看参数顺眼就调"的负优化(第 0 章)。正确姿势:先看画像(计算/内存/IO/网络密集),再只动该类该动的几个,改完量化对比(第 24 章)。默认值是起点不是终点,但"偏离默认"必须有你的负载理由,不能为了"显得专业"而调——每个改动都要回答"我的负载是哪类、为什么这个值对它最优",否则和瞎调没区别。
</details>

---

## 实战补遗三：把一行 vmstat 读"活"——用真实数字走一遍

墨:前一节给了 vm 参数地图,这一节给你个"读仪表盘"的练习。光知道参数没用,得会把 `/proc/vmstat` 的数字翻译成"机器在干嘛"。我们拿一行真实采样走一遍。

采样(某 Web 机器,峰值期,每 5 秒取一次 `vmstat 5`):

```
procs --------memory-------- ---swap-- ---io---- -system-- ----cpu----
 r  b  swpd   free   buff  cache  si  so   bi   bo   in   cs  us sy id wa
 8  2  1024  21000  3000  98000   0   0   40  800  4500 9200  35 18 40  7
```

你:这一行你先挑哪个数看?

墨:我的顺序——**先看 `b`(不可中断睡眠的进程数),再看 `wa`(CPU 等 IO 的百分比),再看 `so`/`si`(swap 进出),最后看 `cs`(上下文切换)和 `r`**。为什么这个顺序?因为 `b` 和 `wa` 直接告诉你"机器卡在不在 IO",这是最要命的。

逐列翻译:
- `r=8`:运行队列里 8 个任务等着 CPU(假设这机器 8 核,说明 CPU 刚好打满、无冗余)——`us=35 sy=18`,用户态+内核态共 53%,还有 `id=40`,说明 CPU 没跑满,`r=8` 是因为有其他资源卡着,不是真 CPU 不够。
- `b=2`:2 个进程在 D 状态(等 IO 不可中断)。结合 `wa=7`(CPU 7% 耗时在等 IO)——有轻微 IO 等待,但不严重。
- `si=0 so=0`:没 swap,好。哪怕 `swpd=1024`(有 1G 在 swap 里)但 `si/so` 都是 0,说明那 1G 是"睡着的冷数据",没在换来换去,无害。
- `bi=40 bo=800`:块设备入 40KB/s、出 800KB/s,写略多于读,正常(Web 写日志/落库)。
- `cs=9200`:每秒 9200 次上下文切换。配合 `in=4500` 中断,量级合理,没异常暴涨(几万以上才要警惕)。
- `cache=98000`:page cache 占 98G,`free=21000` 才 21G——但记住第 1 章:`available` 才是真余量,这 98G cache 大部分可回收,机器内存健康。

推断结论:这台机器"峰值有点 IO 等待(`b=2, wa=7`),但 swap 干净、CPU 有余、cache 充足",属于**健康偏忙**,不用调 vm。如果哪天看到 `so` 持续 >0、`wa` 飙升到 30+、`b` 两位数,那才该动手(第 14 章的 dirty_*、第 6 章的回收策略)。

你:那 `vmstat` 和 `sar -B`(页换出统计)、`/proc/vmstat` 有啥区别?

墨:口径不同:
- `vmstat` 是**聚合速率视图**(每秒变化量),适合"现在机器在干嘛"的实时把脉;
- `sar -B` 是**历史采样**(pgpgin/pgpgout/pfaults 等),适合"昨天这个点是不是也这样"的回溯;
- `/proc/vmstat` 是**累计绝对值**(自开机起累加),适合算"某段时间增量"或查 `nr_dirty`、`pgfault` 等细粒度计数器(第 14、22 章都用它)。

三者互补:实时用 `vmstat`,回溯用 `sar`,深挖用 `/proc/vmstat`。别只盯一个。

🔧 思考题:`vmstat` 里 `free` 只剩 2G、但 `cache` 有 98G,有人说"内存快满了要加",你怎么一句话回他?

<details>
<summary>【参考答案】</summary>

一句话:"看 `free` 是外行,Linux 故意把空闲内存拿去当 page cache,`free` 低不等于内存紧;看 `procs/b` 和 `si/so` 才是真指标——`b` 不高、`si/so` 都是 0,说明没人在等 IO、没在换页,机器健康。" 

补一刀:真要判断余量,`free -h` 的 `available` 列或 `cat /proc/meminfo | grep MemAvailable`,它已经把可回收的 cache 折进去算过。这台机器 `available` 大概 110G+(98G cache 大部分可回收 + 21G free),离 OOM 十万八千里。催着加内存的人,通常是被 `free` 这个"越低越好看"的假象骗了——Linux 的设计哲学恰恰是"空闲内存就是浪费,拿去缓存文件 IO 能白嫖性能",所以 `free` 低是**正常且健康**的表现。
</details>

---

## 实战补遗四：改了 sysctl 没生效——字母序加载与"后写的覆盖先写的"

墨:第 12 章给了 vm 参数地图。但"改了 sysctl 为啥没生效"是高频坑。你知道 `sysctl.d/` 目录下的文件是怎么加载的吗?

你:不是 `sysctl -p` 加载吗?或者开机读 `sysctl.conf`?

墨:这正是坑点。讲清楚加载顺序:
- `sysctl -p`(不带参数):**只加载 `/etc/sysctl.conf` 一个文件**,不碰 `sysctl.d/` 目录;
- `sysctl --system`(或开机时 systemd 的 `systemd-sysctl`):**加载 `sysctl.d/` 目录下所有 `.conf` 文件**,按**文件名 ASCII 字母序**依次应用,**后加载的覆盖先加载的**。

**真实事故**:一台机器,`/etc/sysctl.d/` 下有两个文件:
- `10-defaults.conf`:`vm.swappiness = 10`
- `99-tuning.conf`:`vm.swappiness = 1`(运维后来加的,想压低)

运维改完 `99-tuning.conf` 后跑了 `sysctl -p`——结果 `sysctl vm.swappiness` 显示还是 **10**!他以为没生效,又改一遍,还是 10,懵。

推断:问题在 `sysctl -p` 只读了 `/etc/sysctl.conf`,而 `sysctl.conf` 里(或别处)还写着 `swappiness=10`,`99-tuning.conf` 根本没被 `sysctl -p` 加载。验证:`sysctl --system` 重跑,注意输出顺序,最后 `sysctl vm.swappiness` 显示 1——证明 `99-tuning.conf` 其实是对的,只是 `sysctl -p` 没加载它。

更深一层坑:就算用 `sysctl --system`,**字母序后加载覆盖先加载**。如果还有个 `aa-emergency.conf` 写 `swappiness=60`,它会排在 `99-tuning.conf` 之前、被覆盖,没事;但如果有 `zz-late.conf` 写 `swappiness=30`,它排在 `99-tuning.conf` 之后,会把 1 覆盖成 30——运维以为是 1,实际是 30,**静默错误**。

调整:① 改完一律用 `sysctl --system`(不是 `sysctl -p`)重新加载,且加载后**立即 `sysctl <参数>` 验证**;② 把自定义调优放**单一文件**(如 `99-my-tuning.conf`),避免多个文件互相覆盖;③ 用 `systemd-analyze` 或 `sysctl --system` 的输出确认"最后生效的来自哪个文件";④ 别在 `sysctl.conf` 和 `sysctl.d/` 重复写同一参数,重复必有一方被覆盖且难查。再观察:统一成 `99-my-tuning.conf` + `sysctl --system` + 验证,`swappiness` 稳定为 1。

你:那容器里 `sysctl -w vm.xxx=1` 能生效吗?和宿主的 `sysctl.d` 啥关系?

墨:关键区分:
- **特权容器**(`--privileged` 或 `CAP_SYS_ADMIN`)里 `sysctl -w` 改的是**宿主内核的同一份 sysctl**(因为容器共享宿主内核)——它真的改了全机参数,影响所有容器!这是危险操作,生产禁止容器里手改 `vm.*`/`net.*` 这些**宿主级**参数。
- **非特权容器**:大多数 `vm.*`/`net.*` 改不了(权限不够),且 K8s 用 `securityContext.sysctls` 白名单机制只允许声明**安全的可容器化 sysctl**(如 `net.ipv4.ip_local_port_range`),`vm.swappiness` 这类**不在白名单**(因为它影响宿主全局),容器根本改不了。

所以"容器里想调 vm 参数"又是找错门——`vm.*` 是宿主级,K8s 节点初始化时统一设好,容器侧别碰。正确做法:节点级 `sysctl.d/99-my-tuning.conf` 设好 + `sysctl --system` 验证;容器只在白名单内用 `securityContext.sysctls` 声明允许的那些。口诀:`sysctl -p` 只加载 `sysctl.conf`、`sysctl --system` 才走 `sysctl.d/` 字母序;容器改 `vm.*` 改的是宿主、且通常不被允许——三层(加载命令 / 字母序 / 容器作用域)任何一个搞错,都是"改了没生效"的来源。

🔧 思考题:`/etc/sysctl.conf` 和 `/etc/sysctl.d/*.conf` 同时存在同名参数,谁赢?开机和 `sysctl --system` 行为一致吗?

<details>
<summary>【参考答案】</summary>

行为一致,都按"后加载覆盖先加载",但**加载顺序有讲究**:
- `systemd-sysctl`(开机 和 `sysctl --system`)的加载顺序:先 `/etc/sysctl.d/*.conf`(按文件名排序)、`/run/sysctl.d/*.conf`、`/usr/lib/sysctl.d/*.conf`,**最后才 `/etc/sysctl.conf`**。
- 所以 `/etc/sysctl.conf` 里写的参数,会**覆盖** `sysctl.d/` 里同名的(因为它排在最后加载)!这反直觉——很多人以为 `sysctl.d/` 优先级高,其实 `sysctl.conf` 是"最后加载、最大"。

后果:如果你在 `sysctl.d/99-tuning.conf` 写 `swappiness=1`,又在老旧的 `/etc/sysctl.conf` 留着 `swappiness=60`,开机后实际是 **60**(conf 后加载赢了)。这正是"改了没生效"的经典陷阱。

最佳实践:① **别在 `sysctl.conf` 写任何非默认参数**(它属于历史遗留,优先级还最高,最易坑人),全部搬进 `sysctl.d/` 下的有序文件;② 自定义统一放 `99-my-tuning.conf`(数字大、在同目录里最后加载、赢过其他 `sysctl.d` 文件);③ 改完 `sysctl --system` + 立即 `sysctl <param>` 验证真实值。口诀:`sysctl.conf` 是"后妈生的老大却最有权",要么清空它只留默认,要么把所有调优迁到 `sysctl.d/` 且别和 conf 重复——重复即埋雷。
</details>

---

---

## 实战补遗五：THP 与 Go GC 的恩怨——madvise 还是 never；dirty 回写怎么监控才不踩

墨：老哥，你 Go 服务上线前，会去摸 `cat /sys/kernel/mm/transparent_hugepage/enabled` 吗？

你：一般不动，用系统默认 `always` 或 `madvise`。

墨：默认 `always` 在 Go 上可能是坑。这节把"大页 vs Go GC"的账算清，再顺手讲怎么看 dirty 回写别被它偷袭——都是 `vm` 家族里最容易"好心办坏事"的。

现象：一个 Go 服务（堆 4G，常驻 5G），开着默认 THP `always`，平时正常，但每隔几分钟 P99 出现一次 30~50ms 的尖峰，跟流量无关。perf 抓到 `khugepaged` 和 `compact_zone` 在忙。

推断：以为是 GC 的 STW 尖峰。

可能推错：GC STW 在 Go 里通常亚毫秒（Go 1.14+ 几乎全并发）。尖峰来自**内存规整（compaction）**——`always` 模式下内核为了凑出 2M 连续大页，会后台搬移匿名页，搬移时短暂锁页、触发缺页，应用访问被卡。这是 `khugepaged` + `defrag` 的合并/规整停顿，不是 GC。

调整：看 `cat /proc/<pid>/smaps | grep AnonHugePages` 确认大页用量；看 `/sys/kernel/mm/transparent_hugepage/defrag` 是不是 `always`（最激进，同步规整会卡应用）。Go 的堆是大量匿名 mmap，正好是大页的"目标客户"，所以 `always` 下合并频繁。

再观察：把 `defrag` 改成 `defer` 或 `madvise`，并对 Go 堆段用 `madvise(MADV_HUGEPAGE)` 精准开大页（Go 1.21+ 支持 `GODEBUG=arenas`/runtime 已对 heap arena 尝试 THP），尖峰消失。但更省心的做法：对延迟敏感的 Go 服务直接设 THP `madvise`，**只让明确标注的段用大页**，其余 4K，避免全局规整风暴。有些团队干脆 `never`，靠堆够大本身 TLB 压力可接受。

顺带讲 dirty 回写监控：THP 之外，`vm.dirty_*` 也会偷袭。看 `/proc/vmstat` 的 `nr_dirty`、`dirty_threshold`、以及 `sar -r 1` 的 `kbdirty`——当 `kbdirty` 长期顶到 `dirty_ratio` 阈值，前台写会被**同步阻塞**等回写，表现就是"写个小文件突然卡 100ms"。监控 `nr_dirty` + `dirty_expire_centisecs` 才能提前发现，而不是等卡了再查。

改进：
- Go 服务：THP 用 `madvise`（精准），别全局 `always` 引规整停顿；或按实测定 `never`。
- 监控 `AnonHugePages` 确认大页真用上；监控 `nr_dirty`/`kbdirty` 防 dirty 回写阻塞。
- 延迟敏感的全局关 `defrag=always`。

🔧 思考题：为什么"全局 always 大页"在 Go 上反而可能比 "never" 更慢？而数据库（fork 多）又是另一套逻辑——你该怎么给一台"又跑 Go 又跑 Redis"的混合机器定 THP 策略？

<details>
<summary>【参考答案】</summary>

`always` 让内核对**所有**匿名映射都尝试凑 2M 大页，Go 堆是巨大匿名映射，于是 `khugepaged` 频繁合并、且 `defrag=always` 时内存规整是**同步**的——搬页期间持页表锁、触发缺页，应用线程访问被卡几十毫秒。这就是"全局 always 反而更慢"的来源。关成 `never` 虽然没了大页的 TLB 收益，但也绝无规整停顿，延迟平稳。

混合机器（Go + Redis 同机）的尴尬：Redis 要 `never`（fork 时 COW 粒度别变大，见第 3 章 TLB 实战补遗），Go 想要 `madvise`。二者全局 THP 策略互斥。解法：
1. 用 cgroup v2 的 `thp` 接口按组设（内核 5.x+ 支持 per-cgroup `thp.enabled`），给 Go 组设 `madvise`、Redis 组设 `never`——这是正解。
2. 退而求其次：全局 `madvise`，然后对 Go 进程的堆 arena 用 `madvise(MADV_HUGEPAGE)` 主动开，Redis 不动（默认随 madvise 不主动合并，fork 时仍是 4K COW）。
3. 实在不行就分机部署，别让 fork 模型和无 fork 模型抢同一个 THP 策略。

dirty 回写那块补充：`vm.dirty_background_ratio`（后台开始回写的脏页百分比）和 `vm.dirty_ratio`（前台同步等待的硬上限）是两个阀门；`dirty_expire_centisecs` 是脏页最长存活。生产常把 `dirty_ratio` 调小（如 10→5）让写更平滑，但太小会频繁回写掉吞吐——又是一个权衡。
</details>

---

## 实战补遗六：脏页观测 nr_dirty 与早期预警——在被前台写阻塞前就看见

墨：老哥，你服务器"写个小文件突然卡 100ms"，你第一反应是查什么？

你：查磁盘 IO？还是看写入队列？

墨：可能是脏页回写在后台没跟上、前台写被同步阻塞了。这节讲怎么**提前**用 `/proc/vmstat` 的 `nr_dirty` 看到"脏页快堆满"，而不是等卡了再查——补第 12/13 章脏页那节没写完的"观测"部分。

现象：一个日志服务，平时写延迟 <1ms，但每隔几分钟出现一次 100~300ms 的写卡顿，且卡顿时 `iostat` 看磁盘 `util` 100%、`await` 高。运维以为是"磁盘偶尔忙"，加了盘还是卡。

推断：磁盘性能不够，IO 打满。

可能推错：磁盘 `util` 100% 是**结果不是原因**。根因是脏页（page cache 里改了还没落盘的数据）堆积到 `vm.dirty_ratio` 阈值，内核**强制前台写进程同步等待回写**——你的 `write()` 本来该"写进 cache 就返回"，这下变成"等磁盘真写完才返回"，于是卡 100ms+。磁盘 `util` 100% 是回写线程在刷积压的脏页，前台被它堵。

调整：看脏页指标，提前预警（不用等卡）：
- `cat /proc/vmstat | grep nr_dirty`：`nr_dirty` = 当前脏页数（×4K = 脏页字节）。
- `sar -r 1` 的 `kbdirty`：同上，更易看趋势。
- 阈值：`vm.dirty_ratio`（前台同步等待的硬上限，默认 20% 内存）和 `vm.dirty_background_ratio`（后台开始回写的软上限，默认 10%）。当 `kbdirty` 接近 `dirty_ratio × 内存` 的比例，前台写就会被阻塞。

再观察：那次"周期卡顿"是因为日志服务**突发批量写**（每分钟一批），把脏页瞬间堆过 `dirty_background_ratio`，内核后台回写线程（`kworker` 的 `wb_workfn`，见第 8 章 kworker 实战补遗）开始刷，但刷速（磁盘带宽）跟不上写入速度，脏页继续堆到 `dirty_ratio`，于是**后续前台写被同步阻塞**等回写——卡顿发生。加盘没用是因为根因是"脏页阈值 + 回写速率 vs 写入速率不匹配"，不是盘绝对速度（盘闲时回写早该完）。

改进：
- 监控 `nr_dirty`/`kbdirty` 趋势，超过 `dirty_background_ratio` 就预警（早于前台阻塞）。
- 调 `vm.dirty_background_ratio` 调小（如 10→5），让后台回写**更早、更平滑**开始，避免堆到 `dirty_ratio` 触发前台阻塞。但太小会频繁回写、掉吞吐。
- `vm.dirty_ratio` 也可调小（如 20→10）限制前台阻塞的最坏延迟（卡顿上限降低），代价是更容易触发前台等待。
- 写密集服务（日志/消息队列）：配合 `dirty_expire_centisecs`（脏页最长存活）和 `dirty_writeback_centisecs`（回写周期），让回写节奏匹配写入。
- 临时消尖峰：`sync` 或 `sysctl` 调小比例，但治本是"写入速率≈回写速率"匹配。

🔧 思考题：为什么 `dirty_background_ratio`（后台回写阈值）调小能降卡顿，但调太小又会掉吞吐？这两个参数（background vs ratio）分别管"什么"？

<details>
<summary>【参考答案】</summary>

两个参数管**两个不同的阀门**，对应脏页生命周期的两道关：

- **`vm.dirty_background_ratio`**：脏页占到物理内存这个比例，**后台回写线程（writeback）开始异步刷盘**。注意是"后台"——此时前台 `write()` 仍只写 cache 就返回，不阻塞，系统继续跑。它控制"回写启动的早晚"。调小（如 10→5）意味着脏页刚到 5% 内存后台就开始刷，回写启动早、攒的脏页少，不容易堆到硬上限，于是**前台被阻塞的概率低、卡顿少**。

- **`vm.dirty_ratio`**：脏页占到这个比例，**前台写被强制同步等待回写**（write() 不返回直到脏页降下来）。这是"硬墙"，控制"前台阻塞的最坏延迟上限"。调小（20→10）意味着即便触发阻塞，要刷的脏页量也少，单次阻塞时间短（卡顿上限降低）。

为什么 background 调小能降卡顿但太小掉吞吐：
- 降卡顿的逻辑：background 小→回写早启动→脏页始终少→几乎到不了 dirty_ratio 的硬墙→前台不阻塞→无卡顿。
- 掉吞吐的逻辑：回写是"把脏页写盘"的 IO 操作，它要占磁盘带宽。background 太小，回写**过于频繁启动**，且每次刷的量少但次数多，回写 IO 与你的"正常业务读写"抢同一块磁盘带宽——业务读可能被回写写冲（尤其 HDD，回写排序/寻道干扰业务 IO），吞吐降。极端小（如 1%）会让回写几乎持续运行，磁盘一直半忙，业务 IO 被拖。

所以二者是"平滑 vs 开销"的权衡：
- 想要低延迟（少卡顿）：background 小 + ratio 小，让脏页少、回写早，代价是回写 IO 占比高、吞吐略降（适合延迟敏感、写不太猛的服务）。
- 想要高吞吐：background 大 + ratio 大，让脏页多攒、批量回写高效，代价是偶尔前台阻塞卡顿（适合吞吐优先、能接受尖峰延迟的批处理/日志归档）。

日志服务那次：写入是"周期突发"，background=10% 时突发把脏页瞬间推过 10%、后台回写启动但追不上，堆到 20% 硬墙卡前台。调 background=5% + ratio=10%，回写更早更平稳，且硬墙更低，尖峰卡顿从 300ms 降到 30ms，吞吐基本不降（因为突发总量没变，只是回写节奏更顺）。监控 `kbdirty` 看趋势是验证调参是否生效的硬指标——调完看尖峰 `kbdirty` 是否明显变低、且不再触硬墙。这跟第 12 章"脏页节奏与 swappiness 联动"是同一组旋钮，Kafka 类顺序写可大胆调大（批量回写高效），MySQL/日志类随机写要小（防前台阻塞）。
</details>

下一章预告

墨:第 12 章我们把 `/proc/sys/vm` 这张"引信清单"逐个钉死了,还给了你"安全阀/日常旋钮/泄洪阀"这副眼镜——戴上它,你再看任何 vm 调优帖都能先判断"这参数到底是哪类、该不该长期动"。

但参数不是孤立背的。第 13 章我们**反过来:从负载画像出发**。你是跑数据库的?文件服务器的?低延迟交易的?容器里的?NUMA 大内存的?每一种,vm 参数该"组合"成什么样子、各自赌的是什么、哪些是铁律别碰。这一章你会拿到几套"可以直接抄、但知道为什么"的参数组合。

---

*本章完。场景化用法见第 13 章。*
