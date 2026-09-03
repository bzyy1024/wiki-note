# 第 17 章 其他家族与"长得像 sysctl 的近亲"对照

> 第 12~16 章把 `vm`/`net`/`fs`/`kernel` 四大主力家族讲完了。这一章两件事:① 扫尾**其他小家族**(`abi`/`dev`/`user`/`debug`/`crypto`),让你知道它们守什么门;② 重点讲**那些"长得像 sysctl 但其实不是"的东西**——`/sys/cgroup` 和 `ulimit`。这是所有新手(甚至老手)最容易**找错地方**的坑:你想调"进程内存上限",在 `/proc/sys` 里翻半天,其实它在 cgroup 里;你想调"文件句柄",`ulimit` 和 `fs.file-max` 是两回事。
> 本章给一张**"sysctl 与它的近亲对照表"**,从此不再找错门。

---

## 一、其他小家族扫尾(知道它们守什么门即可)

| 家族 | 守什么门 | 常见参数 | 拿什么换什么 |
|---|---|---|---|
| `abi` | 系统调用/ABI 兼容 | `abi.vsyscall32`(32位兼容) | 兼容老程序 ↔ 略安全面。一般不动。 |
| `dev` | 设备子系统 | `dev.tty.legacy_tiocstty`、`dev.cdrom.info` | 设备行为微调。极少动。 |
| `dev.raid` | RAID 加速 | `dev.raid.speed_limit_min/max` | 重建速度 ↔ 业务 I/O 争抢。存储运维动。 |
| `dev.parport` | 并口 | — | 古董设备。 |
| `user` | 用户命名空间/资源 | `user.max_user_namespaces`(容器关 namespace 数)、`user.max_ipc_namespaces` | 容器密度 ↔ 隔离。K8s 节点常调。 |
| `debug` | 内核调试接口 | `debug.exception-trace`(是否打印异常回溯)、`debug.kprobes-optimization` | 诊断信息 ↔ 性能/噪声。排障临时动。 |
| `crypto` | 内核加密算法默认 | `crypto.fips_enabled`(FIPS 合规模式) | 合规 ↔ 性能(某些算法禁用)。金融/政企动。 |
| `kernel` 补充 | 见第 16 章 | — | — |

墨:这些小家族**多数"知道存在即可"**,除非你做容器平台(`user.max_user_namespaces` 要调)、做合规(`crypto.fips_enabled`)、做存储(`dev.raid.speed_limit`)。它们的共同特点:**不是日常调优项,是特定领域的开关**。别为了"看起来调过了"去动它们。

---

## 二、最大的混淆源:`/proc/sys` vs `/sys` vs `ulimit`

墨:老哥,我问你一个能区分"懂不懂 Linux"的问题:**"限制一个进程能用多少内存"应该调哪里?**

你:……`vm.overcommit`?还是 `ulimit`?还是……

墨:**三个地方都有份,但层次完全不同。** 这正是新手最晕的。我给你画一张"三个世界的地图":

```
/proc/sys/*   ← sysctl 全局内核参数(整机生效,所有进程)
/sys/*        ← 内核向用户空间暴露的"对象树"(设备/总线/cgroup/块设备…)
   └─ /sys/fs/cgroup/*  ← cgroup 接口树(按"分组"限制资源,容器就是它)
ulimit        ← shell/进程级限制(只对"这个会话/这个进程"生效,PR_SET_RLIMIT 控制)
```

墨:三者的关系:**sysctl 是"整机规则",cgroup 是"分组规则",ulimit 是"单个进程/会话规则"**。你想限制"这台机器上所有进程的某行为"→ sysctl;想限制"这一组进程(容器)"→ cgroup;想限制"我这个 shell 起的程序"→ ulimit。

---

## 三、`ulimit`:进程级限制(不是 sysctl!)

| 资源 | ulimit 项 | 对应(sysctl/其他) | 区别 |
|---|---|---|---|
| 打开文件数 | `-n`(RLIMIT_NOFILE) | `fs.file-max`(全局)、`fs.nr_open`(单进程硬顶) | ulimit 是"本进程配额",file-max 是"全系统总闸",nr_open 是"单进程硬顶"。"全局够但 ulimit 小"照样 EMFILE(第04/16章)。 |
| 进程/线程数 | `-u`(RLIMIT_NPROC) | `kernel.pid_max`(全局 PID 上限) | ulimit -u 限制"本用户能建的进程数",pid_max 是系统 PID 编号上限。两层独立。 |
| 内存(地址空间) | `-v`(RLIMIT_AS) | cgroup memory.limit / `vm.overcommit` | ulimit -v 限"虚拟地址空间大小"(含未映射),cgroup 限"实际物理+swap";overcommit 管"是否能开空头支票"。三者层次不同。 |
| 栈大小 | `-s`(RLIMIT_STACK) | — | 单进程栈上限,递归过深爆栈与此相关。 |
| core 大小 | `-c`(RLIMIT_CORE) | `kernel.core_pattern`(落点) | ulimit -c 决定"是否/多大 core",core_pattern 决定"core 写哪"。 |
| CPU 时间 | `-t`(RLIMIT_CPU) | cgroup cpu / CFS | ulimit -t 是"进程累计 CPU 秒上限",到点发 SIGXCPU。 |

墨:`ulimit` 最常被误解的两点:**① 它是"进程级",改了只对"之后从这个 shell 起的进程"生效**,你改了 ulimit 但服务是 systemd 起的、没继承这个 shell,等于白改。**② `ulimit -n` 改到 100 万,但 `fs.nr_open` 是 100 万硬顶、且 `fs.file-max` 全局可能不够**——三层要一起看(第 04、16 章)。

你:那 systemd 起的服务,ulimit 在哪设?

墨:在 **service 文件的 `[Service]` 段**(`LimitNOFILE=`、`LimitNPROC=`、`LimitAS=` 等),或 `/etc/systemd/system.conf` 的 `DefaultLimit*`。`/etc/security/limits.conf` 只对 **PAM 登录会话**生效(SSH 登录的 shell),对 systemd 服务不生效——**这是"改了 limits.conf 服务还是 EMFILE"的头号原因**。

---

## 四、`/sys/fs/cgroup`:分组资源限制(容器就是它)

墨:cgroup 是**按"进程组"分配资源**的机制,容器(Docker/K8s)的 CPU/内存/IO 限制全靠它。它**不在 `/proc/sys`**,而在 `/sys/fs/cgroup/<controller>/<group>/`。和 sysctl 的对照:

| 资源 | cgroup 接口(以 v2 为例) | 对应的 sysctl 近亲 | 区别 |
|---|---|---|---|
| 内存 | `memory.max` / `memory.high` / `memory.stat` | `vm.*`(全局) | cgroup 限"这个组",vm.* 限"整机所有进程"。容器内看 `memory.stat` 而非 `free`。 |
| CPU | `cpu.max`(配额,第05章 cfs_quota_us)、`cpu.weight` | `kernel.sched_*`(全局) | cgroup 限"这个组的 CPU 份额/配额",sched_* 是全局调度器行为。CFS Throttling(`nr_throttled`)就来自这里(第05章)。 |
| IO | `io.max` / `io.weight` / `io.stat` | `vm.dirty_*`(全局脏页)、块层队列(第08章) | cgroup 限"这个组的磁盘 IO 带宽/权重",dirty_* 是整机脏页节奏。 |
| PID | `pids.max` | `kernel.pid_max`(全局) | cgroup 限"这个组能建多少进程",pid_max 是系统 PID 编号上限。防 fork bomb。 |
| 网络 | `net_cls`/`net_prio`(v1) | `net.*`(全局) | cgroup 给流量打标记/优先级,net.* 是协议栈全局行为。 |

墨:cgroup 是"**分组版的 sysctl**"。你前面学的所有"整机参数",在 cgroup 里都有"按组"的对应物。容器问题排查的铁律:**先看 cgroup 的 `*.max` 和 `*.stat`,再怀疑整机 sysctl**——因为容器里"内存满了"是 cgroup `memory.max` 到了,不是整机 `free` 没了(第 13 章讲过:容器内 `free` 看的是宿主,骗人)。

### 4.1 一个 cgroup vs sysctl 混淆的真实排障
- **现象**:容器里 `free` 显示还有 20G,但 Java 应用 OOM 被 kill。
- **推错**:以为整机内存够,疯狂调 `vm.swappiness`(白调)。
- **命中**:看 `/sys/fs/cgroup/memory/memory.stat`(或 v2 `memory.current`/`memory.max`),发现该容器 `memory.max=4G` 已到顶——**是 cgroup 限额到了,不是整机**。调 `vm.*` 不治本,得调容器的 `memory` limit(如 K8s 的 `resources.limits.memory`)。
- **改进**:正确认知"容器内 free 是宿主视角",排障看 cgroup 接口。

---

## 五、sysctl 与近亲对照总表(找对门)

| 你想干的事 | 该调哪 | 常见错误 |
|---|---|---|
| 限制整机某内核行为 | `/proc/sys/*`(sysctl) | — |
| 限制单个进程/本会话 | `ulimit`(或 systemd `Limit*`) | 改了 limits.conf 但服务是 systemd 起的(不生效) |
| 限制一组进程(容器) | `/sys/fs/cgroup/*` | 在 `/proc/sys` 里翻半天找不到 |
| 限制"本用户进程数" | `ulimit -u` | 和 `kernel.pid_max` 混淆 |
| 限制"全系统打开文件" | `fs.file-max` | 只改 `ulimit -n` 不治全局 |
| 限制"单进程文件数" | `ulimit -n`(受 nr_open 限) | 忘了 `fs.nr_open` 硬顶 |
| 限制"容器内存" | cgroup `memory.max` | 调 `vm.*` 白费 |
| 限制"进程地址空间" | `ulimit -v` | 和 cgroup memory / overcommit 混淆 |

---

## 六、🔧 思考题(都配参考答案)

**思考题 1(基础):** "限制一个进程能用多少内存"可能有 `ulimit -v`、`cgroup memory.max`、`vm.overcommit_memory` 三种。请说明三者层次区别,以及容器里该看哪个、为什么 `free` 会骗你。

<details>
<summary>【参考答案】</summary>

三者层次:`ulimit -v`(RLIMIT_AS)是**单进程/会话级**的虚拟地址空间上限(含未映射);`cgroup memory.max` 是**分组级**的对该组实际物理+swap 的限制(容器就是用这个);`vm.overcommit_memory` 是**整机级**的"是否允许开空头支票"开关。容器里该看 **cgroup 的 `memory.current`/`memory.max`/`memory.stat`**,因为容器内 `free` 命令显示的是**宿主机的视角**(容器没自己独立的内存统计,free 读的是 procfs 的整机值),会骗你"还有 20G"而实际 cgroup 限额已到顶。排障铁律:容器 OOM 先看 cgroup 接口,别调 vm.*。
</details>

**思考题 2(深入):** 你改了 `/etc/security/limits.conf` 把 `nofile` 设 1000000,但 systemd 起的 Nginx 仍报 `too many open files`。请解释为什么,以及正确做法。

<details>
<summary>【参考答案】</summary>

`limits.conf` 只通过 **PAM** 对**登录会话**(如 SSH 登录的 shell)生效。systemd 起的 service **不走 PAM 登录流程**,不会继承 limits.conf 的设置,所以 Nginx 仍用默认(常 1024)的 RLIMIT_NOFILE。正确做法:在 Nginx 的 **systemd service 文件 `[Service]` 段**设 `LimitNOFILE=1000000`,或改 `/etc/systemd/system.conf` 的 `DefaultLimitNOFILE=` 后 `systemctl daemon-reexec`。此外还要确认 `fs.nr_open` ≥ 该值、`fs.file-max` 全局够(第04/16章三层联动)。且服务需重启生效。
</details>

**思考题 3(对照):** 一个容器 "fork bomb" 把整台节点拖死,你觉得"不是有 `kernel.pid_max` 吗"。请指出为什么 pid_max 没挡住,以及正确防护(两层)。

<details>
<summary>【参考答案】</summary>

`kernel.pid_max` 是**全局 PID 编号上限**,它只决定"PID 编号能到多大",调大只是延后耗尽;它**不限制"某个进程组能建多少进程"**,所以单个容器的 fork bomb 会把全局 PID 吃光、拖垮整节点。正确防护用 **cgroup `pids` 控制器**:给每个容器设 `pids.max`(如 1024/4096),限制该组能同时存在的进程+线程总数,fork bomb 在到达 pids.max 时 `fork` 失败,**只炸自己容器、不波及节点**。这是"全局上限(pid_max) + 分组限额(cgroup pids.max)"两层配合:前者兜底编号空间,后者做实际隔离。
</details>

**思考题 4(进阶总账):** 综合第 04、12~17 章,画一张"内存相关限制"的层级总图:从整机(sysctl)到分组(cgroup)到进程(ulimit/per-process),每层举 1~2 个参数,说明它们如何叠加。

<details>
<summary>【参考答案】</summary>

内存限制三层叠加(从粗到细):
- **整机(sysctl)**:`vm.overcommit_memory`/`overcommit_ratio`(能否开空头支票+commit 上限)、`vm.swappiness`(换出倾向)、`vm.min_free_kbytes`(原子分配底线)、`vm.watermark_scale_factor`(水位带)——影响**所有进程**。
- **分组(cgroup)**:`memory.max`(硬上限)/`memory.high`(软上限,超了 throttle)/`memory.stat`(监控)——限制**该组(容器)**实际物理+swap。容器内 OOM 看它。
- **进程(ulimit/per-process)**:`ulimit -v`(RLIMIT_AS 虚拟空间)、`/proc/<pid>/oom_score_adj`(免死金牌权重)——限制**单个进程**。
叠加关系:一个 malloc 能否成功 = 先过 overcommit 的 commit 账(整机)→ 再受 cgroup memory.max 硬顶(分组)→ 单进程还受 RLIMIT_AS(ulimit -v)。OOM 时按 oom_score(受 oom_score_adj 影响)在**整机**范围挑进程杀,但 cgroup 内的进程更易因 memory.max 先被自身 cgroup 的 OOM 杀。
</details>

---

## 七、sysctl / /sys / ulimit 三世界实战:一个限制该去哪改

墨:第 17 章的核心价值是"别找错门"。这一节用**具体诉求**演示三个世界的边界,你以后遇到"我想限制 X",先判断它属于哪一层:

| 你的诉求 | 该去哪改 | 不该去哪找(常见误区) |
|---|---|---|
| 限制**某个进程**能用的最大内存 | `ulimit -v`(RLIMIT_AS) 或 cgroup `memory.max` | ❌ 别去 `sysctl vm.*`(那是整机倾向,不针对单进程) |
| 改 **TCP 接收缓冲上限** | `sysctl net.core.rmem_max` | ❌ 别去 `/sys`(`/sys` 管设备/控制器,不管网参) |
| 调 **IO 调度器 / 队列深度** | `/sys/block/<dev>/queue/scheduler` | ❌ 别去 `sysctl`(没有 `sysctl` 的块层入口) |
| 限制**容器内进程数** | cgroup `pids.max` | ❌ 别只调 `kernel.pid_max`(那是全局编号,不隔离单容器) |
| 看**某进程打开了哪些文件** | `/proc/<pid>/fd` | ❌ 别去 `sysctl fs.*`(那是全局计数,不列具体进程) |
| 限制**单进程线程数** | `ulimit -u`(RLIMIT_NPROC) 或 cgroup `pids.max` | ❌ 别去 `kernel.threads-max` alone(那是系统总上限) |

墨:**sysctl = 整机内核行为旋钮; `/sys` = 设备/控制器具体接口(块层、cgroup 树、设备电源); `ulimit`/cgroup = 进程/分组边界。** 三者的颗粒度从"整机"到"分组"到"进程"递减。找错门 = 调了半天不生效,还以为系统坏了。

---

## 八、cgroup v1 vs v2 关键差异速查

墨:现在生产环境正在从 cgroup v1 迁到 v2(K8s 新版本默认 v2),但很多调优帖还停留在 v1 的接口名。**名字变了,语义也变了**,这里给你一张速查:

| 维度 | cgroup v1 | cgroup v2 |
|---|---|---|
| 结构 | 各控制器**独立挂载**(各自 hierarchy) | **单一统一树**,所有控制器挂同一 cgroup |
| 内存硬上限 | `memory.limit_in_bytes` | `memory.max` |
| 内存软上限 | `memory.soft_limit_in_bytes`(**基本无效,坑**) | `memory.high`(真正生效的节流线) |
| CPU 配额 | `cpu.cfs_quota_us` / `cpu.cfs_period_us` | `cpu.max`(`"配额 周期"` 同语义) |
| IO 限制 | `blkio.throttle.*` | `io.max` / `io.weight` |
| 进程数 | `pids.max`(同) | `pids.max`(同) |
| 压力监控 | 需外部工具 | **原生 PSI**:`/sys/fs/cgroup/<cgroup>/{cpu,memory,io}.pressure` |
| OOM 行为 | 组内挑分高杀 | `memory.oom.group` 可设"整组一起死/活",更可控 |

墨:v2 最值得关注的两个升级:**`memory.high` 替代了 v1 那个几乎无效的 `soft_limit_in_bytes`**(真正的软节流,超了就 throttle 而非等 OOM);以及**原生 PSI**——第 22 章讲的"内核喊救命"指标,在 v2 下每个 cgroup 自带,容器级压力一目了然。调 cgroup 前,**先 `stat -fc %T /sys/fs/cgroup` 确认是 v1 还是 v2**,再看对应名字,别拿 v1 的命令去敲 v2 的接口(会报"无此文件")。

---


---

## 九、真实事故:在 sysctl 里调了一周容器内存,其实该改 cgroup

`📦 案例:某 SRE 接手一个"容器内 Java 频繁 OOM"的工单,照着调优帖在 /proc/sys/vm 里调了一周——swappiness、overcommit、min_free_kbytes 全改了,Java 还是被 OOM kill。`

### 现象(第 0 层)
Java 容器(单容器)运行一段时间后被 OOM kill 重启,`dmesg` 前缀 `Memory cgroup out of memory`。SRE 在宿主机上 `free -h` 看"还有 20G",于是坚信"整机内存够,是 vm 参数不对",埋头调 `vm.*` 一周。

### 推断 1:vm 参数不对?(推错,且推错了一周)
你(作为那个 SRE):整机还有 20G,Java 还被 OOM,肯定是 swappiness/overcommit 这些 vm 旋钮没配对。
墨( retrospective):这是第 17 章反复警告的"**找错门**"。`dmesg` 前缀已经是 `Memory cgroup out of memory`——明确是**容器自己的 cgroup 内存上限到了**(第 19 章分水岭),和整机 `vm.*` 一毛钱关系没有。更坑的是:容器内跑 `free -h`,显示的是**宿主机的视角**(容器没独立内存统计,free 读的是 procfs 整机值),那"还有 20G"是**宿主的 20G,不是这个容器的 20G**——它从头到尾在用一个假数据指导调参。

### 命中:该看 cgroup,不是 sysctl
墨:正确动作——进容器看 `/sys/fs/cgroup/memory/memory.stat`(或 v2 的 `memory.current`/`memory.max`),发现该容器 `memory.max=2G`,而 JVM `-Xmx` 设了 3G(还不算 off-heap),**容器内真实内存撞到了 2G 的 cgroup 上限**,所以被 cgroup OOM 杀(第 17 章第四节那个排障的现场版)。调 `vm.*` 当然没用——你调的是"整机倾向",而限制它的是"分组上限"。

### 调整
墨:一剂药:把容器 `memory.max`(K8s 的 `resources.limits.memory`)从 2G 提到 4G,或把 JVM `-Xmx` 降到 1.5G 让常驻 < 上限(含 off-heap 余量)。**同时关闭"在 sysctl 里调容器内存"的错误思路**。

### 改进:Java 稳定,收口
墨:改 cgroup limit 后 Java 不再被 OOM。复盘:**这是全书"找对门"的最高频反面教材**——`dmesg` 前缀(整机 vs cgroup)、容器内 `free` 的欺骗性、sysctl/cgroup/ulimit 三世界的边界,三条一起踩。三句话焊死:**① dmesg 带 "Memory cgroup" 前缀 → 去调容器 limit,别动 vm.*;② 容器内 free 是宿主视角,信它不如信 cgroup 的 memory.current;③ 限制"一组进程"的永远在 cgroup,限制"整机"的才在 sysctl。**

---

## 十、真实事故二:想限磁盘 IO,在 `sysctl` 里翻半天——其实该改 `/sys/block` 队列或 cgroup `io.max`

`📦 案例:某 SRE 想"限制某个容器的磁盘写入带宽,别让它把整块盘写爆影响邻居"。他在 /proc/sys 下翻了半小时(vm.dirty_*、fs.*),发现要么影响整机、要么根本不按容器生效,一筹莫展,最后在群里问"sysctl 里哪个参数限 IO 带宽?"`

### 现象(第 0 层)
单容器批量写把整盘吞吐打满,邻居容器 I/O 延迟飙升、P99 暴涨。SRE 想"给这个容器限个速",但翻遍 sysctl 找不到"按容器限 IO"的入口。

### 推断 1:调 vm.dirty_*?(推错)
你:想"限制写入",自然想到 `vm.dirty_ratio`/`dirty_background_ratio`(第 12、13 章)。但那是**整机脏页节奏**,一调影响所有容器,且只控"脏页占内存比例"不控"带宽 MB/s";更糟的是在容器里 `vm.*` 多不可写(第 12 章 12.3 / 第 17 章三世界)。方向错了。

### 命中:IO 限制不在 sysctl,在 `/sys/block/<dev>/queue/` 和 cgroup `io` 控制器
墨:第 17 章那张"三世界地图"在这里救场——**sysctl 里没有任何块层 / IO 带宽入口**。IO 相关的旋钮全在别处:
- **想调整块盘的队列深度 / 调度器**:`/sys/block/sda/queue/nr_requests`(队列深度)、`/sys/block/sda/queue/scheduler`(mq-deadline / bfq / none)、`/sys/block/sda/queue/read_ahead_kb`——这些在 `/sys`,**sysctl 完全没有块层入口**(第 17 章三世界表已点)。
- **想按容器 / 进程组限速(本题正解)**:cgroup v2 的 `io.max`(如 `echo "8:0 wbps=104857600" > /sys/fs/cgroup/<cgroup>/io.max` 限写 100MB/s)、`io.weight`(权重)。这才是"分组限速",目标容器被限、邻居不受累。

### 调整
墨:两剂药:
1. **按容器限速**:给那个容器设 cgroup v2 `io.max` 写带宽上限(如 100MB/s),邻居立刻恢复;
2. **若需调单盘队列深度**:改 `/sys/block/sda/queue/nr_requests`(注意这是整机单盘,影响所有用户);
3. **彻底放弃在 sysctl 里找**——那里根本没这东西。

### 改进:邻居 I/O 恢复,收口
墨:设 `io.max` 后邻居延迟回落,目标容器被限速。复盘:这是"找错门"的升级版——前面讲"容器内存该改 cgroup 不是 vm.*",这里是"容器 IO 该改 cgroup `io.max` 或 `/sys/block` 队列,不是 sysctl"。**sysctl 管的是内核协议栈 / 内存 / 文件句柄这类"通用内核行为";块设备队列在 `/sys/block`;分组 IO 在 cgroup。** 三者颗粒度递减,别串台。

### 同源坑:cgroup v1 的 `memory.soft_limit_in_bytes` 是废柴
墨:顺带把第 17 章 v1/v2 表那个坑焊成事故:有人想"软限制容器内存,超了就 throttle 别 OOM",在 cgroup v1 上依赖 `memory.soft_limit_in_bytes` 做超卖节流——**结果它基本不生效**,超了直接 OOM,和"软限制"的预期完全相反。真正能 throttle 的是 **cgroup v2 的 `memory.high`**(超了就节流、不 OOM,第 19 章讲过)。在 v1 上死磕 soft_limit,等于 trusting a no-op。排障铁律:**搞 cgroup 前先 `stat -fc %T /sys/fs/cgroup` 确认 v1 还是 v2,再查对应名字**——拿 v1 的 `soft_limit_in_bytes` 去指望节流,只会得到"说好软限制、实际硬 OOM"的惊吓。

---

## 实战补遗一：cgroup v2 `cpu.max` 硬配额——把 Redis/etcd 的"后台活"误伤下线

墨:你给容器设了 `cpu.max=200000 100000`(限 2 核),监控上 CPU 使用率从没超过 2 核,但 Redis 客户端延迟忽高忽低,etcd 还被踢出过 quorum。你查 CPU 使用率,一切正常——这时候你会往哪想?

你:CPU 没满,那肯定不是 CPU 问题,去查网络、查磁盘 IO 呗。

墨:又推错了。问题恰恰在 CPU,只是**不是"用满",是"被节流"**。cgroup v2 的 `cpu.max` 是硬配额,到了就掐;而 Redis 的 `bgsave`、etcd 的心跳,都是"短时想多用点"的活,被你一掐,就出大事了。

### 先分清 `cpu.max` 与 `cpu.weight`

- `cpu.max = "quota period"`(微秒)。`200000 100000` 意思是每 100000us 周期里最多跑 200000us = 限 2 核。到了就**硬节流**(throttle),进程被挂起直到下个周期。
- `cpu.weight`(默认 100):**相对权重**,只在"大家都要 CPU、且总量不够"时按权重分;空闲时你不限它,它能吃满。

二者语义完全不同:weight 是"抢不过别人时少分",max 是"到点必须停"。

### 现象:限了 2 核,Redis 却"抽风"

容器化 Redis,设 `cpu.max=200000 100000`。平时平稳;但每天一次 `bgsave`(RDB fork 子进程做快照)期间,客户端 P99 延迟从 1ms 飙到 300ms+,且 `BGREWRITEAOF` 时更糟。etcd 同节点设了 1 核 `cpu.max`,某次 compaction 期间 leader 心跳超时,被踢出 quorum,集群短暂不可用。

### 推断(可能推错):先去查磁盘/网络

第一推断:「`bgsave` 写盘慢,是磁盘 IO 瓶颈。」——`iostat` 一看磁盘 %util 才 20%,不是。

第二推断:「etcd 网络分区。」——`ping`/网络探针正常,不是。

都推错,因为没看 `cpu.stat` 里的节流计数。

### 真相:`cpu.stat` 在偷偷涨 `throttled_time`

`cat /sys/fs/cgroup/.../cpu.stat` 里有两个数:

```
throttled_periods  12345
throttled_time     678900000
```

前者是"被节流的周期数",后者是"累计被掐掉的微秒"。本例 Redis 容器 `throttled_periods` 在 `bgsave` 期间暴涨,`throttled_time` 累计几十万 ms——**它不是用满了 2 核,是被掐在 2 核上,想多用一点都不行**。

`bgsave` 的 fork 子进程要做大量页表复制(瞬时 CPU 密集),主线程还在做渐进 rehash/响应;2 核配额在 fork + rehash + 响应三者抢时不够分,子进程被 throttle,快照拖长,主线程也跟着卡。etcd 的 compaction/heartbeat 同理:被掐在 1 核,heartbeat 发晚了 → 超时 → 被踢。

### 调整:关键服务用 weight 而非 max,或给 headroom

- **首选:**对 Redis/etcd 这类"平时闲、突发要吃 CPU"的服务,用 `cpu.weight`(如设到 100 以上、邻组低些)做**相对保底**,而不是 `cpu.max` 硬配额——它空闲时能吃满邻居的空闲核,突发不被掐;
- **必须硬限时的正确姿势:**`cpu.max` 留 headroom,设成"略高于实测峰值"而非"以为够用的值",让 `bgsave` 这类短时突发能溢出;
- **隔离:**把 Redis/etcd 单独放 cgroup,别和批量任务混在一个 `cpu.max` 组里——批量任务会把它节流死;
- **监控:**把 `throttled_periods` / `throttled_time` 纳入告警,这比"CPU 使用率"早一步暴露问题。

### 再观察:换 weight 后

Redis 改用 `cpu.weight=200`、取消 `cpu.max` 硬限(或留很大 headroom),`bgsave` 期间 P99 回到 2ms 内,`throttled_time` 归零;etcd compaction 不再触发心跳超时。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `cpu.weight` 保底 | 无硬上限(邻组空闲时它能吃满) | 突发不被掐、延迟稳 |
| `cpu.max` 留 headroom | 可能略超"以为的容量" | 短时突发能溢出 |
| 关键服务单放 cgroup | 运维分组成本 | 不被批量任务拖累 |

🔧 思考题:既然 `cpu.weight` 没有上限,会不会让关键服务把整台机器吃光、饿死别人?

<details>
<summary>【参考答案】</summary>

`cpu.weight` 只在"CPU 总需求 > 可用核数"时才按权重分配,空闲时谁都能吃满——所以它**不会**在无竞争时饿死别人,反而在有竞争时按你设的权重(如 200 vs 默认 100)多分。真正会"吃光整机"的是不设任何限制、且业务真的能跑满多核的情况,那该用 `cpu.max` 硬限。一句话:关键、突发型服务用 weight 保公平,批处理、可预测型服务用 max 限上限,二者别用反。
</details>

---

## 实战补遗二：cgroup v2 `memory.low` vs `memory.min`——把"保命的"和"该保的"搞混

墨:你想给关键服务"锁一部分内存不被回收",设了 cgroup v2 的 `memory.min=4G`(硬保底)。结果同机别的容器开始 OOM。你说:我保的是关键服务,关别人什么事?

你:`memory.min` 不是"最少给 4G"吗?保关键服务有错?

墨:`memory.min` 是**硬保底**——内核在任何情况下都不回收这 4G,哪怕整机内存耗尽。你一台 16G 的机器,给一个服务硬保 4G,剩 12G 给所有其他服务 + 内核;当其他服务加起来要超 12G,它们被 OOM,而你的"保命服务"焊死 4G 纹丝不动。正确的软保底应该是 `memory.low`(有竞争才生效、没竞争不占)。

### 现象:硬保底焊死内存,邻居全 OOM

16G 机器,关键服务 cgroup 设 `memory.min=4G`,其余服务共享默认 cgroup。某天流量涨,总内存需求到 18G。内核保 `memory.min=4G` 不动,其余 12G 要装下 14G 需求 → 非关键服务被 OOM,连锁报警。`memory.min` 占了"保命额度",但把整机推到 OOM 边缘。

### 推断(可能推错):先查"是不是其他服务泄漏"

第一推断:「邻居服务内存泄漏。」——查邻居常驻都正常,是"被挤压"不是"自己涨"。推错,因为没看 `memory.min` 这道硬墙。

### 真相:low 是"软保底",min 是"硬保底"

cgroup v2 内存保护三档:
- `memory.min`:**硬保底**,任何情况不回收,哪怕整机 OOM 也先杀别人;
- `memory.low`:**软保底**,只在"有内存竞争"时优先保它,没竞争时不占(别人要用就让);
- `memory.high`:软上限,超了节流(第 19 章)。

设 `memory.min` 过大 = 把内存"焊死"给一个服务,整机可用内存被永久扣减,邻居被挤 OOM。设 `memory.low` = "该服务优先用,但整机闲时这块内存别人也能用",冲突时才保——这才是"保命不占坑"。

### 调整:用 low 保关键,min 只给真正不能死的内核级

- 关键业务用 `memory.low=4G`(软保底),而非 `memory.min`;
- `memory.min` 只留给真正不可回收的(如 `systemd`、关键的 kubelet),且值极小;
- 同时配 `memory.high` 做软上限防它自己膨胀;
- 监控 `memory.events` 的 `low`/`max` 计数,看保护是否生效、是否触顶;
- 验证:整机内存压力下,关键服务 `low` 保护生效(没被回收),邻居不被无谓 OOM。

### 再观察

`memory.min=512M`(仅系统级)+ 关键服务 `memory.low=4G` 后,流量涨时关键服务优先保、邻居不被硬挤 OOM,整机在 `memory.max` 触发时公平杀。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| 关键服务用 `low` | 无(软保底) | 优先保、不占坑 |
| `min` 只给系统级 | 关键服务无硬保 | 整机不被焊死 |

🔧 思考题:既然 `memory.low` 更好,为什么内核还要提供 `memory.min`?什么场景该用 `min`?

<details>
<summary>【参考答案】</summary>

`memory.min` 用于"哪怕整机 OOM 也绝不能被回收"的内核级关键进程(如 `systemd`、kubelet、sshd)——它们死了整机失联,所以值得"硬保底、宁可杀别人"。业务服务一般不该用 `min`,因为业务挂了能重启、且硬保底会挤压整机引发邻居 OOM(全局最差,第 24 章)。一句话:`min`=保命绳(极少、极关键),`low`=优先权的软保底(业务关键但可重启)。混淆二者,就是"把业务当系统级保",等于拿整机稳定性给单服务背书——第 17 章反复强调:cgroup 是整机资源的分配入口,参数要从整机视角评估外部性,单实例调参的"局部最优"常是集群的"全局最差"。
</details>

---

## 实战补遗三：ulimit -n、fs.file-max、cgroup 三套"文件描述符账本"

墨:一个进程报 `Too many open files`,你第一反应改什么?

你:`ulimit -n` 调到 65535?

墨:对了一半。但你可能不知道,`ulimit -n` 只是三道关卡里**最里面、最弱**的一道。它外面还有两道,任何一道没放开,你改 `ulimit` 也是白改。这三道是:

1. **进程级**:`ulimit -n`(即 `RLIMIT_NOFILE`),单进程能开的 fd 上限。用户态,`ulimit` 或 systemd 的 `LimitNOFILE=` 改。
2. **系统级**:`fs.file-max`,全内核"已分配 fd 数"的上限。内核态,`sysctl` 改。
3. **容器级**:cgroup v1 的 `pids.max`/`files.max`(v2 的 `pids.max`),容器能用的进程/文件数硬墙。

**真实事故**:一个微服务在容器里跑,高峰期报 `Too many open files`。SRE 进容器 `ulimit -n` 一看是 65535,觉得够了;宿主机 `sysctl fs.file-max` 是 800 万,也够。改不动,卡住。

推断推错:前三道都够,那为什么还报?答案是**第四道藏在第三道里**——容器的 cgroup v1 `files` 子系统。当年这个容器平台给每个容器默认 `files.limit = 1048576`(约 100 万),但更老的版本默认只有 **8192**!而 `ulimit -n` 在容器里看到的"65535"是**继承宿主的 soft limit 显示值**,实际受 cgroup `files.max` 这堵硬墙卡着——内核分配 fd 时先查 cgroup 配额,超了直接拒,错误码还是 `EMFILE`,但和 `ulimit` 无关。

验证:`cat /sys/fs/cgroup/.../files.max`(或在 v2 看 `pids.max`/对应文件子系统)发现是 8192;容器内进程实际打开的 fd 数 `ls /proc/<pid>/fd | wc -l` 逼近 8192 就报错。

调整:让平台把容器的 `files.max` 提到 1048576 或 `max`,同时确认应用 `ulimit -n` 和宿主 `fs.file-max` 都留足余量。三道一起放开后才稳定。

你:那 `fs.file-max` 是不是越大越好,直接设个天文数字?

墨:不是。`fs.file-max` 控制的是内核**已分配**的 fd 结构体内存。每个 fd 对应一个 `struct file`(约几百字节)+ `fdtable`。设得过大不会立刻吃内存(它是上限不是预留),但有两个隐患:① 某个失控进程真疯狂开 fd 时,会把全系统内核内存拖垮,连 ssh 都连不上(这时 cgroup `files.max` 的价值就来了——它能把爆炸范围锁在单个容器);② `fs.file-nr` 的第三个值就是 `file-max`,监控告警要基于它而不是凭感觉。

所以正确的"三件套"策略是:
- `fs.file-max`:给全系统一个合理大值(如内存的 10% 折算,常见 200 万~800 万),防单点;
- `ulimit -n`:按单进程真实并发连接数给(长连接服务常需 10 万+);
- cgroup `files.max`/`pids.max`:**这是容器时代的真正保险丝**,把爆炸锁在容器内,别让一个 pod 拖垮节点。

🔧 思考题:为什么我说"容器时代,`ulimit` 和 `fs.file-max` 都成了次要的,真正要盯的是 cgroup 配额"?传统物理机时代这套认知为什么不够用?

<details>
<summary>【参考答案】</summary>

物理机时代:一台机器一个团队管,`ulimit` 和 `fs.file-max` 调好就全局生效,没有"邻居"概念。容器时代:一台宿主机上混部几十个 pod,彼此是**共享内核但资源隔离**的关系。这时:
- `ulimit -n` 在容器里看到的值可能只是继承显示,真正的硬墙在 cgroup;
- `fs.file-max` 是**节点级**共享的,一个 pod 把 fd 开爆会吃光全节点内核内存,连 `kubelet` 自己都可能是受害者;
- 只有 cgroup 的 `files.max`/`pids.max` 能实现"单容器限额",把故障爆炸半径锁死在 pod 内。

所以排障顺序要反过来:容器里报 fd 类错误 → 先查 cgroup 配额(`/sys/fs/cgroup/.../files.max`)→ 再查容器内 `ulimit -n` → 最后才怀疑宿主 `fs.file-max`。传统"改 ulimit + sysctl"两套拳在容器里经常打在空气上。这也是为什么 k8s 后来推 `LimitNOFile` 在 pod 注解里直接声明——把这道关从运维手动改变成声明式配置,少踩一层坑。
</details>

---

## 实战补遗四：cpu.weight 与 cpu.max——"相对让"与"绝对砍"的两条节流线

墨:前面讲了 cgroup v2 的 `memory` 四档。CPU 侧也有两兄弟:`cpu.weight`(相对权重)和 `cpu.max`(绝对硬限)。你知道什么时候用哪个吗?

你:`cpu.weight` 是"大家抢的时候按比例分",`cpu.max` 是"不管怎样最多用这么多"?

墨:对,而且这是**两种完全不同的节流哲学**。举个生活化比喻:`cpu.weight` 像"几个同事共用一台打印机,活多时按权重排队,谁权重高谁先打,但没人用的时候闲着的那台你可以随便用";`cpu.max` 像"行政规定你每天最多用打印机 2 小时,到点强制断,哪怕打印机闲着也不行"。

**真实事故**:一个节点上混部 A(核心交易,要稳)、B(离线训练,能吃空闲 CPU)。最初用 `cpu.weight`:A 设 100、B 设 50,意思是"抢的时候 A 拿 2/3、B 拿 1/3"。结果问题来了:白天交易高峰,A 自己就把 8 核吃满,B 几乎拿不到;半夜 A 闲了,B 想全速跑完训练,但 `cpu.weight` 只在"抢"的时候生效——不抢的时候 B 能用到全部空闲,这倒是好。可**当 A 突发流量、B 正在全速跑,B 会瞬间被挤到 1/3,训练任务抖动**、checkpoint 超时。

推断:核心交易要的是"B 绝不能影响 A",但 `cpu.weight` 给的是"相对让",突发时 B 仍会占着 CPU 直到调度器重排,有毫秒级抖动。要的是**硬隔离**——B 无论何时最多用 X 核,A 永远有保底。

调整:给 B 加 `cpu.max` 硬墙,比如 `cpu.max="400000 100000"`(限 4 核,即 400000 微秒配额 / 100000 微秒周期),同时保留 `cpu.weight` 让 B 在 A 闲时能抢到更多。A 不设 `cpu.max`(要能吃满)、靠"B 被焊死在 4 核"自然保底。再观察:白天 A 高峰,B 稳定只占 4 核、绝不挤 A;半夜 A 闲,B 在 `cpu.max` 4 核内全速,配合 `weight` 若 A 完全空闲 B 仍受 4 核硬限(这是代价,但换来了 A 的绝对稳)。

你:那为什么不直接给 A 也设 `cpu.max` 焊死?

墨:因为 A 是核心交易,峰值要能吃满所有核,焊死 `cpu.max` 会限死它的突发能力——交易量大时 A 自己不够用反而坏事。`cpu.max` 适合"可牺牲的、要限制上限的"负载(B 类),不适合"必须能吃满的"核心负载(A 类)。所以组合是:**核心负载不设 `cpu.max`(或设很大)、靠限制干扰负载的 `cpu.max` 来保底;非核心负载 `cpu.max` 焊死 + `cpu.weight` 调相对优先级**。这和第 17 章 `memory` 的"核心用 `memory.min` 焊死保底、边缘用 `memory.max` 硬墙"是同一套思路,只是换到 CPU 维度。

🔧 思考题:`cpu.max` 设 `max 100000`(即 "max" 配额)是什么意思?和 `cpu.weight` 一起用会怎样?

<details>
<summary>【参考答案】</summary>

`cpu.max="max 100000"` = 不设上限(`max` 表示配额无限),等于"这个 cgroup 想用多少 CPU 用多少"。它和 `cpu.weight` 共存时:`cpu.weight` 只在**CPU 争用**时按比例分,不争用时各自随便用;`cpu.max=max` 则完全不限制。所以这是"只用相对权重、不要硬墙"的配置,适合你**信任调度器、只想要优先级**的场景。

但注意一个细节:`cpu.max` 的第二值是周期(默认 100000 微秒=100ms),第一值 `max` 表示不封顶。如果你写 `cpu.max="100000 100000"` 那才是限 1 核。常见坑:把 `max` 误写成一个大数(如 `800000 100000`=限 8 核)以为是"不限制",其实焊死了 8 核。真正不限制就用字面 `max`。生产口诀:**核心负载 `cpu.max=max`(或干脆不设)+ 高 `cpu.weight`;干扰负载 `cpu.max` 焊死具体核数 + 低 `weight`**。这套和 memory 的 min/max 对偶,理解了 memory 那套,CPU 这套秒懂。
</details>

---

## 实战补遗五：memory.events 监控实战——把 cgroup OOM 接进告警

墨:第 17 章讲了 cgroup v2 的 `memory.max`/`high`/`low`/`min` 四档和 `oom_group`。但"设了限额"不等于"看得见它快撞墙"。cgroup 给了个**金矿文件**:`memory.events`,很多人没监控它。

你:`memory.events` 记录啥?和 `dmesg` 的 OOM 日志有啥不同?

墨:`memory.events` 是**该 cgroup 自己的内存事件计数器**,独立于全局 `dmesg`,而且**能早早在"撞墙前"预警**。关键计数:
- `max` / `high`:达到 `memory.max`(被 OOM 杀) / 达到 `memory.high`(被节流)的**次数**;
- `oom`:本 cgroup 触发 OOM 的次数;
- `oom_kill`:本 cgroup 内被 OOM 杀的进程数;
- `oom_group_kill`(若开 `oom.group`):连坐杀整组的次数。

**真实事故**:一个 K8s 集群,某 pod 频繁 `OOMKilled` 重启,但 SRE 只在 `kubectl describe` 看到 `OOMKilled`(exit 137)才知情——也就是**重启发生了才知道**,业务已断了几十秒。没有"快撞墙"的提前预警。

推断:只有"死后验尸"(OOMKilled),没有"生前预警"。`memory.events` 里其实有**前兆**:`high` 计数会在撞 `max` 之前先涨(因为 `memory.high` 是软上限,先触发节流),`max`/`oom` 计数在真正的 OOM 之前也会有零星增长。如果监控了这些,能在"偶尔 throttle"阶段就报警,而不是等"被杀重启"。

调整:① 给 pod 同时设 `memory.high`(略低于 `memory.max`,如 max=1G、high=900M),让快撞墙时先节流(慢一点)而非直接杀;② 监控 `memory.events` 的 `high` 计数增长率——它涨说明"这个 pod 内存快不够、正在被节流",提前告警;③ 监控 `oom`/`oom_kill` 计数——一旦 >0 说明已经 OOM 过,立刻查;④ 把 `memory.events` 接进 Prometheus(用 `cgroup_exporter` 或 `kube-state-metrics` 的 cgroup 指标),配告警规则。再观察:pod 内存接近上限时,`high` 计数先涨 → 告警亮 → SRE 在"被杀前"就扩 limit 或查泄漏,`OOMKilled` 不再发生。

你:`memory.events` 在容器里怎么读?路径长啥样?

墨:在 cgroup v2 挂载点下,按 cgroup 层级。容器里(若挂了 cgroup v2 的只读视图)路径如:
```
/sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/.../<pod-hash>/memory.events
```
K8s 环境更方便的是用 **`kube-state-metrics`** 或 **cAdvisor**,它们已经把 cgroup 的 `memory.events`、`memory.current`、`memory.max` 等暴露成 Prometheus 指标(`container_memory_*` 系列,部分含 `oom` 事件)。所以生产不用自己 `cat` 文件,直接:
- `container_memory_working_set_bytes`(≈ `memory.current`,看当前用量);
- cAdvisor 的 `container_vmstat_*` 或 kube-state 的 OOM 事件指标(看 `oom_kill` 次数);
- 配告警:`oom_kill > 0` → 紧急;`working_set / limit > 0.9` 且 `high` 事件涨 → 预警。

这把第 17 章的"cgroup 四档"和**可观测性**(第 24 章)接起来了:设限额是"防",监控 `memory.events` 是"看见防的过程",两者缺一都是瞎调。口诀:**`memory.max` 是保险丝,`memory.events` 是保险丝的"服役记录"——不监控它,你永远不知道保险丝快烧断**。

🔧 思考题:`memory.current`(当前用量)和 `memory.stat`(细分统计)有什么不同?排查"内存去哪了"该看哪个?

<details>
<summary>【参考答案】</summary>

- `memory.current`:**一个总数**,本 cgroup 当前占用的内存字节数(含匿名页 + 缓存 + 内核内存),对应监控里的 `container_memory_working_set_bytes`(近似)。看"用了多少",不告诉"哪类"。
- `memory.stat`:**细分账本**,把 `memory.current` 拆成:`anon`(匿名页,堆/mmap)、`file`(page cache,含 `file_cache`/`slab` 可回收部分)、`kernel_stack`/`sock`/`shmem`/`inactive_file`/`active_file` 等。看"哪类占了多少"。

排查"内存去哪了"的姿势:
1. 先 `memory.current`(或 `working_set`)确认"总量在涨"——这是告警触发信号;
2. 再 `memory.stat` 看构成:
   - `anon` 涨 → 真泄漏(堆没释放)或业务数据涨,去查 `smaps`/`pprof`(第 1、22 章);
   - `file`/`inactive_file` 涨 → page cache 多(正常,可回收),**不是泄漏**(第 22 章的告警乌龙就在这);
   - `sock`/`slab` 涨 → 网络/slab 不可回收(第 22 章的 SUnreclaim 类)。

所以:`memory.current` 管"是否涨"(预警),`memory.stat` 管"涨在哪类"(定位根因),`memory.events` 管"是否撞墙/OOM"(事故)。三个 cgroup 文件各管一段:`current` 看量、`stat` 看构成、`events` 看撞墙。配合 `smaps`(进程级,第 1/22 章)和 `slabtop`(内核 slab,第 22 章),从"cgroup 总量"到"进程明细"到"内核对象"全链路打通。口诀:current 定预警、stat 定根因、events 定事故。
</details>

---

---

## 实战补遗六：oom_group 连坐与 memory.stat——cgroup v2 里"杀一个还是杀一组"

墨：老哥，你在 cgroup v2 里设过 `memory.oom_group` 吗？知道它干嘛的吗？

你：没碰过，只知道 `memory.max` 撞墙会杀进程。

墨：默认是"杀最胖的那个进程"，但有时候你得"整个组一起死"才干净。这节讲 cgroup OOM 的连坐机制，外加怎么用 `memory.stat` 看"内存到底花哪了"——这比 `memory.current` 有用十倍。

现象：一个 cgroup 里跑着主进程 + 它的 sidecar（日志采集、agent）。主进程内存暴涨撞 `memory.max`，OOM 时内核杀了**最胖的主进程**，但 sidecar 还活着，抱着一堆已死主进程的资源（pipe、socket），变成僵尸宿主，cgroup 没被回收，节点监控看到这个 cgroup 内存一直不归零。

推断：杀了主进程就该没事了。

可能推错：主进程死了，但 sidecar 仍在这个 cgroup 内，cgroup 的 `memory.current` 因为 sidecar 持有的缓冲没释放，迟迟不降。更糟的是 sidecar 可能因为主进程没了而疯狂重试/重连，反而吃更多内存，二次 OOM。单杀主进程在"主从一组"的场景下不干净。

调整：开 `memory.oom_group=1`（在 cgroup 目录 `echo 1 > memory.oom_group`）。效果：撞 `memory.max` 触发 OOM 时，**整个 cgroup 的所有进程一起收到 SIGKILL**（连坐），由上层编排（systemd/K8s）统一重启整组，避免"半死不活"的残留。这对"主进程 + 辅助进程必须共存亡"的服务（如带 sidecar 的 Pod）正是所需。

再观察：怎么提前知道"快 OOM 了"而不是等杀？看 `memory.events`：
- `oom`：发生 OOM 的次数（撞 max）。
- `oom_kill`：被 OOM 杀的进程数。
- `high`：内存超过 `memory.high` 的次数（**早于 OOM 的预警**，软上限节流触发）。
配合 `memory.stat` 看内存构成：`file`（page cache）、`anon`（匿名页=堆/栈）、`kernel_stack`、`slab`（含 `slab_reclaimable`/`slab_unreclaim`）、`sock`（网络内存，含 skbuff）。真排查泄漏时，`memory.stat` 里 `anon` 只涨不跌 = 堆泄露；`sock` 涨 = 连接没关；`slab_unreclaim` 涨 = 内核对象泄露。这比只看 `memory.current` 一个总数精准。

改进：
- 主从一组的服务设 `memory.oom_group=1`，连坐干净重启。
- 监控 `memory.events` 的 `high` 做**早期预警**（超 `memory.high` 就告警），别等 `oom` 才知。
- 排查用 `memory.stat` 拆 `anon`/`file`/`sock`/`slab`，定位是哪类内存涨。
- `memory.max`（硬墙，撞了杀）和 `memory.high`（软上限，超了节流不杀）配合用：high 设成 max 的 90%，给节流+告警留缓冲。

🔧 思考题：为什么 `memory.high`（软上限）比 `memory.max`（硬墙）更适合"第一节省内存、第二节省被杀"？如果只设 max 不设 high，会丢掉什么观察窗口？

<details>
<summary>【参考答案】</summary>

`memory.max` 是硬墙：内存触顶就**立刻**在该 cgroup 内选进程 SIGKILL。问题是它是"事后"的——你只有被杀那一刻才知道，没有缓冲、没有优雅降级，且杀谁由内核按 OOM score 选（默认最胖，未必是你想要的那个）。

`memory.high` 是软上限：内存超过它，内核**不杀**，而是对这个 cgroup 做**回收节流**——更激进地回收它的 page cache、限制它分配速度、触发直接回收，等于"踩刹车"让内存增速慢下来甚至回落。这给你两个宝贵东西：
1. **观察窗口**：超过 high 时 `memory.events` 的 `high` 计数+1，你的监控能**提前告警**"这个 Pod 内存快顶了"，在真 OOM 前介入（扩 limit、查泄露、重启）。
2. **优雅降级**：很多情况下高水位是暂时的（流量尖峰），节流让它自己回落，不用杀进程，业务不中断。

只设 max 不设 high 的代价：要么内存平稳到撞墙被秒杀（无预警），要么你为了"不杀"把 max 设得很大（失去限制意义、可能挤占节点其他 Pod）。正确组合是 high=max×0.9：平时 high 节流+告警，真失控才 max 兜底杀。`oom_group` 则是"杀了也要杀干净"的收尾，三者配合才是完整的内存护栏。systemd 对应 `MemoryHigh=`/`MemoryMax=`/`MemoryOOMGroup=`；K8s 里 `memory.max` 由 limit 决定，`memory.high` 需通过 cgroup v2 直接写或设 `memory.oom_group`。
</details>

下一章预告

墨:到这一章,`/proc/sys` 下你最早点名的 `vm` 全解了,`net`/`fs`/`kernel`/其他家族分类完了,连"和 sysctl 长得像但不是"的 cgroup/ulimit 也对照清了。**系统参数这部分,算是彻底收口。**

接下来进入你最初要的"丰富真实案例"——第 18~23 章,六个独立诊断案例,每个走完整迭代环,把前面所有机制(02~17 章)串起来实战:神秘卡顿、OOM 连环杀、磁盘 IO 毛刺、网络重传与 TCP 调优、内存泄漏 vs 缓存挤压、NUMA 与大页。这些案例不是"再讲一遍原理",是"给你一个现象,看你能否用前面学的显微镜定位到门、再拧对阀"。

---

*本章完。真实诊断案例集见第 18~23 章。*
