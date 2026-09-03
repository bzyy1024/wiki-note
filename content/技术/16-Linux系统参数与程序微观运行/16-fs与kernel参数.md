# 第 16 章 `fs` 与 `kernel` 家族——文件句柄、进程号、崩溃开关

> 前两章是内存和网络的守门人。这一章转去两个"资源配额"家族:**`fs`**(全系统的文件句柄、inode、配额——第 04 章见过的 `fs.file-max` 就在这)和 **`kernel`**(进程号上限、线程上限、System V 信号量、崩溃/看门狗开关——第 05 章的 softlockup 开关就在这)。
> 这两个家族的参数,**平时没人动,一动就是要出事或已经出事的边界**。继续我们的"守哪道门、拿什么换什么"主线。

---

## 一、`fs` 家族:全系统的"打开了多少文件"

墨:还记得第 04 章的事故吗?高并发下 `open()` 报 `EMFILE`(Too many open files),我们扒出 `RLIMIT_NOFILE`(进程级)和 `fs.file-max`(系统级)和 `fs.nr_open`(单进程硬上限)的树状继承。这一章把 `fs` 家族补全。

### 1.1 三层"打开文件数"上限(复习 + 补全第 04 章)

| 参数 | 层级 | 默认 | 守的门 |
|---|---|---|---|
| `fs.file-max` | ① 系统级上限 | 视内存(≈内存/10K) | 全系统同时打开的 file 描述符总数上限。`cat /proc/sys/fs/file-nr` 第三列逼近它 → 新 open 全失败。 |
| `fs.nr_open` | ① 单进程硬上限 | 1048576 | **单个进程** `RLIMIT_NOFILE` 不能超过它。比 `file-max` 更底层——你 `ulimit -n` 设再大也越不过 nr_open。 |
| `fs.file-nr`(只读) | — | — | 三元组 `[已分配, 已分配未用, file-max]`。看第三列知还剩多少额度。 |

墨:`fs.file-max` 是"全系统总共能开多少文件",`fs.nr_open` 是"单个进程最多多少"(比 ulimit 更硬),`RLIMIT_NOFILE`(ulimit -n)是"进程实际配额,取 min(ulimit, nr_open) 且总和受 file-max 约束"。**三层:file-max(全局总闸)→ nr_open(单进程硬顶)→ ulimit(单进程实际)**。三者任一触顶都报 EMFILE/ENFILE。

### 1.2 inode 与 dentry 缓存

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `fs.inode-nr`(只读) | 已分配 inode 数 | — | 看 inode 用尽没(小文件海量场景会撞)。 |
| `fs.inode-state`(只读) | inode 分配/空闲 | — | 监控用。 |
| `fs.aio-max-nr` | 异步 IO(io_submit)并发上限 | 65536 | 高并发 AIO(如某些数据库/存储)调大,换内存。 |
| `fs.aio-nr`(只读) | 当前 AIO 数 | — | 监控。 |
| `fs.leases-enable` | 文件租约(通知其他进程文件变更) | 1 | 特定场景(如 Samba)用,一般不动。 |
| `fs.pipe-max-size` | 匿名管道容量上限 | 1048576 | 大管道场景调,换内存。 |
| `fs.mqueue.*` | POSIX 消息队列 | — | 用 mq 的服务调。 |

墨:`fs.inode-nr` 撞顶是**海量小文件**场景(如百万级小图片/日志)的经典坑:磁盘没满,但 inode 用光,新文件建不了。这是"磁盘空间"和"inode 数"两个独立维度的坑——`df` 看空间,`df -i` 看 inode。

### 1.3 quota 与保护

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `fs.protected_hardlinks` | 防 hardlink 提权 | 1 | 安全项,保持 1。 |
| `fs.protected_symlinks` | 防 symlink 劫持 | 1 | 安全项,保持 1。 |
| `fs.quota.*` | 磁盘配额 | — | 多租户用。 |

---

## 二、`kernel` 家族:进程号、线程、信号量、崩溃开关

### 2.1 进程/线程号上限(容器密度高的隐形坑)

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `kernel.pid_max` | **全局进程/线程号上限** | 32768(或随内存更大) | 调大(如 4194304)换"高密度容器/线程不撞 PID 耗尽" ↔ PID 哈希表略增。容器节点必调。 |
| `kernel.threads-max` | 系统最大线程数 | 视内存 | 调大换高并发多线程 ↔ 内存。 |
| `kernel.max_threads`(派生) | — | — | 由内存算出的理论上限。 |

墨:`kernel.pid_max` 是**被容器时代重新激活的老参数**。一台物理机上跑几百个容器、每个几十线程,轻易突破 32768 的默认 PID 上限,然后 `fork` 失败、新进程/线程起不来、连 `ps` 都 fork 不出。**容器节点 `pid_max` 必须调大到百万级**,这是 2015 年后所有云厂商的标配。

### 2.2 System V IPC(老数据库的坑)

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `kernel.sem` | System V 信号量(4 元组:每信号量集最大信号量数 / 系统最大信号量总数 / 每个 semop 最大操作数 / 系统最大信号量集数) | `250 32000 32 128` | Oracle/PostgreSQL 等老数据库常因默认太小起不来,需调大(如 `250 32000 100 128` 或更大)。换内存。 |
| `kernel.msgmax` / `msgmnb` / `msgmni` | System V 消息队列单条/队列/总数上限 | 视内核 | 用 SysV MQ 的服务调。 |
| `kernel.shmmax` / `shmall` | 共享内存段最大/总量 | 视内存 | Oracle 等靠共享内存的数据库必调,否则 SGA 起不来。 |

墨:`kernel.sem`/`shmmax` 是**"DBA 入职第一天必调"**的经典。Oracle 在 Linux 上默认起不来,八成是这几个 SysV 参数太小。它们和"现代 Go/Java 服务"关系不大,但**你一旦碰遗留数据库系统,就是必踩点**。

### 2.3 崩溃与看门狗开关(第 05 章的开关在这)

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `kernel.panic` | panic 后多少秒自动重启(0=不重启) | 0 | 设非 0(如 10)换"panic 后自动恢复" ↔ 可能来不及 dump。生产常设 10~60。 |
| `kernel.panic_on_oops` | 内核 oops 是否直接 panic | 0 | 设 1 换"发现隐患立即重启避免脏数据" ↔ 轻微 oops 也重启。**关键系统可设 1。** |
| `kernel.softlockup_panic` | 软锁死(第05章 watchdog)是否 panic | 0 | 设 1 换"软锁死立即 panic 重启而非干等" ↔ 偶发长关中断也会重启。配合 `kernel.watchdog_thresh`(超时间隔)。 |
| `kernel.hung_task_panic` |  hung task(D 状态超阈值)是否 panic | 0 | 设 1 换"卡死即重启" ↔ 误判重启。 |
| `kernel.watchdog_thresh` | 看门狗超时(秒) | 10 | 调大换"容忍更长关中断/卡顿" ↔ 真锁死发现慢。第 05 章讲过。 |
| `kernel.panic_on_oom` | **注意:这是 `vm.panic_on_oom` 的镜像?** | — | 实际 OOM panic 在 `vm.panic_on_oom`(第12章),`kernel` 下无此项,别找错位置。 |

墨:看门狗相关的三个 panic 开关,是**"要稳定性还是要可诊断性"的取舍**。云厂商常设 `softlockup_panic=1` + `panic=10`:一旦软锁死立刻 panic 自动重启,用"快速失败"换"不僵死"。代价:你失去现场,要靠 kdump 抓panic 前的 dump。这是"让机器自己救自己"的哲学。

### 2.4 其他常用 `kernel` 项

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `kernel.core_pattern` | core dump 写哪 | `core` | 设管道(如 `|/usr/lib/systemd/systemd-coredump`)换"自动收集 core" ↔ 配错丢 core。排障关键。 |
| `kernel.core_uses_pid` | core 名加 PID | 1 | 便利项。 |
| `kernel.sysrq` | Magic SysRq 开关 | 视 distro | 设允许某些 SysRq(如 `echo m > /proc/sysrq-trigger` 抓内存)换"应急诊断" ↔ 安全风险。 |
| `kernel.dmesg_restrict` | 非特权能否读 dmesg | 1(较新) | 设 0 方便排障 ↔ 信息泄露。 |
| `kernel.printk` | 内核日志级别 | — | 控制 printk 输出。 |
| `kernel.sched_*` | 调度器(第05章详) | — | 此处不重复,见第05章。 |

---

## 三、`fs` 与 `kernel` 总表(守门人速查)

| 家族 | 参数 | 守的门 | 拿什么换什么 |
|---|---|---|---|
| fs | file-max | 系统打开文件总数 | 高并发 ↔ 内存 |
| fs | nr_open | 单进程文件硬顶 | 大 ulimit ↔ 内存 |
| fs | inode-nr | inode 用尽(海量小文件) | `df -i` 监控 |
| fs | aio-max-nr | AIO 并发 | 高并发 AIO ↔ 内存 |
| kernel | pid_max | 全局 PID/线程号 | 高密度容器 ↔ PID 表 |
| kernel | threads-max | 系统线程上限 | 高并发 ↔ 内存 |
| kernel | sem/shmmax | SysV 信号量/共享内存 | 遗留数据库起得来 ↔ 内存 |
| kernel | panic / softlockup_panic | panic 即重启 | 快速恢复 ↔ 失去现场 |
| kernel | watchdog_thresh | 看门狗超时 | 容忍长卡顿 ↔ 真锁死发现慢 |
| kernel | core_pattern | core 落点 | 自动收集 ↔ 配错丢 core |

---

## 四、两个真实事故的迭代环(简版)

### 4.1 事故:`fork: Resource temporarily unavailable` 但内存充足
- **现象**:容器平台某节点批量 `fork` 失败,`free`/`top` 正常。
- **推断(推错)**:内存不够 → 查内存充足。
- **命中**:`kernel.pid_max=32768` 撞顶(节点跑了几百容器)。`ps -eLf | wc -l` 接近 32768。
- **改进**:`kernel.pid_max=4194304` + cgroup pids 限制防单容器耗尽。**观察**:fork 恢复正常。

### 4.2 事故:Oracle 启动报 `ORA-27123` / 共享内存不足
- **现象**:Oracle 实例起不来,日志 `shmget` 失败。
- **推断(推错)**:Oracle 配置错 → 查 SGA 大小合理。
- **命中**:`kernel.shmmax` 默认太小,SGA 超过单段上限;`kernel.sem` 也偏小。
- **改进**:按 SGA 调 `kernel.shmmax`/`shmall`、调大 `kernel.sem`。**观察**:实例起得来。

---

## 五、🔧 思考题(都配参考答案)

**思考题 1(基础):** 高并发 Go 服务报 `too many open files`,你 `ulimit -n` 已经设 1000000,但仍失败。请指出还可能在哪两层触顶,以及该查什么。

<details>
<summary>【参考答案】</summary>

`ulimit -n`(RLIMIT_NOFILE)只是中间一层。还可能在:① **`fs.nr_open`**:单进程硬上限默认 1048576,且 `RLIMIT_NOFILE` 不能超过它——但如果 nr_open 被显式调小过,ulimit 设再大也越不过;查 `cat /proc/sys/fs/nr_open`。② **`fs.file-max`**:全系统打开文件总数上限,所有进程共享;若全局已分配逼近它(`cat /proc/sys/fs/file-nr` 第三列),新 open 全失败;查 file-nr。三层:`file-max`(全局总闸)→`nr_open`(单进程硬顶)→`ulimit`(单进程实际),任一触顶都报 EMFILE/ENFILE。另:改 ulimit 需进程重启生效,运行中改不救已起的进程。
</details>

**思考题 2(深入):** 一台容器节点 "fork 失败" 但内存充足,你怀疑 `kernel.pid_max`。请说明为什么容器时代这个老参数被重新激活,以及正确调法与配套防护。

<details>
<summary>【参考答案】</summary>

原因:默认 `pid_max=32768` 是单台物理机跑少量进程时代的遗产。容器时代一台物理机跑几百个容器、每个几十线程,轻易突破 32768,于是 `fork`/`clone` 失败、新进程起不来、甚至 `ps` 都 fork 不出。调法:`kernel.pid_max=4194304`(百万级)。配套防护:用 **cgroup pids 子系统**给每个容器设 `pids.max`,防止单容器 fork bomb / 泄漏耗尽整节点 PID(否则光调大 pid_max 只是延后爆发,且 PID 表本身占内存)。监控:`ps -eLf | wc -l` 看线程总数。
</details>

**思考题 3(取舍):** `kernel.softlockup_panic=1` + `kernel.panic=10` 被云厂商广泛采用。请解释这套组合的哲学(换什么、丢什么),以及什么场景你反而**不该**这么设。

<details>
<summary>【参考答案】</summary>

组合哲学:"软锁死(第05章 watchdog 发现关中断超 watchdog_thresh)即 panic,panic 后 10 秒自动重启"= **用"快速失败 + 自动恢复"换"不僵死"**。代价:失去故障现场,要靠 kdump 在 panic 前抓内核 dump 才能事后分析;且**偶发的长关中断/长卡顿也会触发重启**,可能误杀健康节点。不该设的场景:① 无法部署 kdump 抓 dump 的环境(重启即丢现场,等于白重启);② 单实例不可重启的关键系统(如某些主备里"重启=业务中断"的核心库,宁可卡住等人工介入也不自动重启);③ 关中断本就偏长且无法优化的实时负载。
</details>

**思考题 4(进阶总账):** 综合第 04、16 章,给"文件句柄 + 进程号"两张速查卡:(a) EMFILE 的排查顺序;(b) fork 失败的排查顺序。

<details>
<summary>【参考答案】</summary>

(a) EMFILE(打开文件失败)排查顺序:
1. 进程级:`cat /proc/<pid>/limits` 看 `Max open files`(=ulimit -n,RLIMIT_NOFILE);
2. 硬顶:`cat /proc/sys/fs/nr_open` 是否比 ulimit 小(ulimit 越不过它);
3. 全局:`cat /proc/sys/fs/file-nr` 第三列(file-max)是否逼近,`cat /proc/sys/fs/file-max`;
4. 还可能有容器 cgroup `pids/max` 外的 fd 限制。
(b) fork 失败排查顺序:
1. `cat /proc/sys/kernel/pid_max` 是否撞顶(`ps -eLf|wc -l` 接近它);
2. 内存是否真够(`fork` 失败也可能是 OOM/Cgroup 内存上限,非 pid);
3. cgroup `pids.max` 是否限制;
4. `kernel.threads-max` 是否触顶。
心法:两类失败都遵循"先定位是哪一层上限",再动对应旋钮。
</details>

---

## 六、fs 与 kernel 的真实事故三则(补完本家族)

`📦 这一节用三个小事故,把本章参数焊进真实场景(每个走"现象→推断→调整"环,呼应前面思考题)。`

### 事故 A:`too many open files`,`ulimit -n` 已很大仍失败
- **现象**:高并发 Go 服务偶发 `EMFILE`,运维 `ulimit -n` 已设百万,仍失败。
- **推断(锁定)**:不是 ulimit。查 `cat /proc/sys/fs/nr_open`——发现前任把它显式调小过(默认 1048576),`RLIMIT_NOFILE` 越不过它;再 `cat /proc/sys/fs/file-nr` 第三列逼近 `fs.file-max`。
- **调整**:`fs.nr_open` 调回 ≥ ulimit;`fs.file-max` 按内存 `≈ 内存/10KB` 上调。
- **教训**:fd 限制三层(全局 `file-max` → 单进程硬顶 `nr_open` → 实际 `ulimit`),任一层触顶都报 EMFILE(第 04、16 章联动)。

### 事故 B:容器 `fork` 失败,内存却充足
- **现象**:容器节点批量 `fork: resource temporarily unavailable`,`free` 显示内存充裕。
- **推断(锁定)**:`cat /proc/sys/kernel/pid_max` = 32768(老默认),`ps -eLf|wc -l` 接近它——容器时代几百容器×几十线程轻松撞顶(第 16 章思考题 2)。
- **调整**:`kernel.pid_max=4194304`;并给每容器设 cgroup `pids.max` 防 fork bomb 拖垮节点。
- **教训**:`pid_max` 是全局编号上限,**不隔离单容器**;真正隔离用 cgroup `pids.max`。

### 事故 C:机器"假死"几十秒后自愈
- **现象**:节点每隔几天"假死"几十秒(SSH 都卡),随后恢复,`dmesg` 有 `softlockup: CPU#N stuck for 23s`。
- **推断(锁定)**:某内核路径长关中断(或某驱动 bug),看门狗 `watchdog` 报软锁。
- **调整**:临时 `kernel.softlockup_panic=1` + `kernel.panic=10`(快速重启恢复);**根因**是找那个长关中断的路径/驱动打补丁(第 05 章 watchdog 机制)。
- **教训**:`softlockup_panic` 组合是"快速失败+自动恢复"哲学,但失现场,需 kdump 配合(第 16 章思考题 3)。

---


---

## 七、第四则事故:磁盘没满却建不了文件——inode 耗尽

`📦 案例:某日志服务,磁盘 df -h 显示还有 60% 空闲,但写新日志报 No space left on device,新文件(包括临时文件)一个都建不了。`

### 现象(第 0 层)
`df -h` 显示磁盘空间充裕(用掉 40%),但任何 `touch`/新建文件都失败 `ENOSPC`。业务日志写不进去,监控"磁盘满"告警却没触发(因为看的是字节空间)。

### 推断 1:磁盘真满了?(推错)
你:`No space left` 嘛,肯定是磁盘满。
墨:`df -h` 明明还有 60%。懵。再想:报错是"No space left on device",**它说的是"设备上没有空间",但不一定是'字节空间'"**——还可能指"inode 号用光了"。查 `df -i`(看 inode 而非字节)——**`IUse%` 100%**。

### 命中:海量小文件耗尽 inode
墨:这台机器存了**几千万个 tiny 日志碎片**(每个几百字节)。磁盘"字节"只用了 40%,但每个文件都占一个 inode,几千万文件把 `fs.inode-nr`(第 16 章 1.2 节)的 inode 总数吃光了。**inode 和字节空间是两个独立维度**:字节够,inode 不够,照样建不了文件。这是"海量小文件"场景的经典坑(相比"大文件把字节吃光",它更隐蔽,因为 `df -h` 看起来很空)。

### 调整
墨:两剂药:
1. **治标**:清理无用的小文件碎片(合并/归档旧日志),释放 inode。
2. **治本**:重新格式化时调大 inode 密度(`mkfs -i <更小 bytes-per-inode>`),或改用更适合海量小文件的文件系统/对象存储;应用层把碎日志合并成大文件再写。
配套:监控不只看 `df -h`,要加 `df -i` 的 inode 使用率告警(第 16 章 `fs.inode-nr` 的实战版)。

### 改进:日志恢复,收口
墨:清理 + 归档后 inode 回落,日志正常。**复盘**:`df -h` 看的是"字节",`df -i` 看的是"inode 数",**两者任一耗尽都报 `ENOSPC`**。海量小文件场景必须双监控。这条把第 16 章 1.2 节那句"`df` 看空间,`df -i` 看 inode"从一个提示,变成了你亲手抓到的真凶。

---

## 八、第五则事故:`kernel.threads-max` 触顶,高并发网关新连接线程起不来

`📦 案例:某接入网关(每连接一个 worker 线程模型),晚高峰连接数涨到约 12 万时,新连接开始大量失败、已连接的处理也变慢,但内存还有大把、kernel.pid_max 也早调到了百万级。运维第一反应是"又撞 pid_max 了",改了 pid_max 没用。`

### 现象(第 0 层)
晚高峰连接数到 ~12 万,新连接 `accept` 后起 worker 线程失败,错误形如 `pthread_create: Resource temporarily unavailable`;内存充足,`pid_max` 百万级未触顶。

### 推断 1:fd 不够 / pid_max?(推错)
你:"线程起不来"嘛,先查经典两层:① `cat /proc/sys/fs/file-nr`——未到 `file-max`,排除 fd;② `cat /proc/sys/kernel/pid_max` = 百万级,`ps -eLf | wc -l` 才 ~12 万,远未触顶。两道经典闸都没问题,懵了。

### 命中:`kernel.threads-max` 是第三道闸
墨:根因在 **`kernel.threads-max`**——它是"**系统级最大线程(轻量进程/task 结构)总数**",和 `pid_max` 是**两个独立上限**:`pid_max` 管 PID 编号空间(能编到多大号),`threads-max` 管内核 `task_struct` + 内核栈的**总数量**(受内存约束)。每连接一线程的模型下,12 万线程逼近这台 64G 机器默认的 `threads-max`(约 10 万级别),新线程 `clone()` 失败,报 `EAGAIN`(被 `pthread_create` 转述成 "Resource temporarily unavailable")。

墨:这是个经典的"**只知两道闸、不知第三道**"——大家背得出 `pid_max` 和内存,却忘了 `threads-max` 这条隐藏上限。它和内存强相关(每个内核线程约占 16KB 内核栈 + task 结构),机器内存决定了它的默认上限。

### 调整
墨:两剂药:
1. **(治标)`kernel.threads-max` 调大**:按内存允许值调(如 `3145728`),它本质受"内核能容纳多少 task"限制,大内存机器设大没问题;
2. **(根因)改连接模型**:每连接一线程在 10 万+ 并发下本就吃紧,更稳的是 **事件驱动 + 固定 worker 线程池**(epoll + 线程池),而非无限开线程——否则调再大 threads-max 也只是延后爆发,且每个线程都吃内存和调度;
3. **(容器配套)** 用 cgroup `pids.max` 防单容器吞光整节点线程。

### 改进:threads-max 调大后新连接恢复,收口
墨:调大后晚高峰新连接恢复正常。复盘:**"`pthread_create` / `clone` 失败" 不只是 pid_max 和内存,还有 `threads-max` 这第三道闸**。三者排查顺序焊死:① 内存真不够?(OOM/Cgroup 内存上限);② `kernel.pid_max` 撞顶?(`ps -eLf|wc -l` 接近它);③ `kernel.threads-max` 撞顶?(线程模型服务的高并发必查)。这条把第 16 章 2.1 节那句"`pid_max` 是全局编号上限"补全成"编号上限 + 线程总数上限"两道独立闸——新手常把"线程起不来"笼统归为"进程数限制",其实 `pid_max` 和 `threads-max` 是各管一摊。

---

## 实战补遗一：`fs.inotify.max_user_watches`——监控 agent 把整台机器"看"崩了

墨:`lsof` 看 fd 没满,磁盘也没满,但日志采集 agent 疯狂报 `Too many open files`,更离谱的是**同机其他容器也开始丢事件、报 ENOSPC**。你第一反应去调 `ulimit -n`,对吧?

你:不然呢?`Too many open files` 不就是 fd 不够吗?

墨:这就是 `fs` 家族最阴的一处——**inotify 的 watch 不算普通文件描述符**,它走的是一套完全独立的计数 `max_user_watches`。你拿 `ulimit -n` 去救,等于拿灭火器去浇漏电,越救越乱。

### 先分清:inotify 的三道门槛

- `fs.inotify.max_user_watches`:**单个用户**能创建的 watch 总数(默认 8192,很多发行版已提到 65536/524288)。这是最容易踩的。
- `fs.inotify.max_user_instances`:单个用户能创建的 inotify 实例数(默认 128)。
- `fs.inotify.max_queued_events`:单个实例事件队列长度(默认 16384),满了丢事件但不报错。

注意:这些 limit 是**按用户(uid)**计的,而且容器里默认共享宿主的这套计数(除非 user namespace 隔离)。一个 pod 把 `max_user_watches` 吃光,**同 uid 的其他 pod 直接受累**——这就是"我啥也没干,凭什么我也崩"的来源。

### 现象:一个 agent 拖垮一整台节点

某_node 上跑着 filebeat + 一个自研文件监听服务,它们 `inotify_add_watch` 了一棵巨大的目录树(含上百万小文件)。某天目录里文件数涨过 524288,agent 开始刷:

```
Failed to watch /data/logs: too many open files
inotify_add_watch ... ENOSPC
```

`dmesg` 里:`inotify watch limit reached`。

紧接着诡异事发生:同机的**另一个**完全无关的容器也开始报 `ENOSPC`、监听静默、事件丢失——因为它和 agent 是**同一个 uid**。

### 推断(可能推错):先去调 ulimit

第一推断:「`ulimit -n` 太小,fd 不够。」——于是在 agent 的启动脚本里狂加 `ulimit -n 1048576`。结果:agent 照样报 `ENOSPC`,因为 inotify watch **根本不走 fd 表**,`lsof` 看 fd 用了还不到 1%。

第二推断:「磁盘 inode 满了?」——`df -i` 一看还有 90% 余量,也不是。

两个推错,因为没看 `/proc/sys/fs/inotify/max_user_watches` 实际用量,也没意识到 inotify 是独立计数。

### 真相:watch 是独立配额,且按 uid 共享

`inotify_add_watch` 的配额由 `max_user_watches` 管,和 `RLIMIT_NOFILE` 是两回事。而且容器场景里,除非做了 user namespace 隔离,pod 的 uid 在宿主视角是同一个数字,**limit 被整台机器共享**。一个 agent watch 整棵树,等于在全体同 uid 进程头上悬了把刀。

### 调整:抬配额 + 改设计,两手抓

- **治标:**`fs.inotify.max_user_watches=524288`(或更大,按文件数定),让 agent 暂时不崩;
- **治本(更重要):**agent **不要 watch 整棵大目录树**。正确的设计是 watch 已知的子目录、或只 watch 一层、或改用轮询+增量,而不是 `inotify` 整棵百万文件树——那是反面模式,每个 watch 占内核几百字节到 1KB,百万 watch 就是几百 MiB 内核内存;
- **隔离:**容器场景给关键 agent 单独 user namespace,或把 `max_user_watches` 的共享粒度控制住,避免一颗雷炸一节点;
- **监控:**把 `fs.inotify` 的用量也纳入告警,别只盯 fd。

### 再观察:收窄后验证

agent 改为只 watch 业务子目录(从 120 万 watch 降到 3 万),`max_user_watches` 用量稳定在 6% 以内,同机其他容器 `ENOSPC` 消失,`dmesg` 不再刷 watch limit。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `max_user_watches` 调大 | 内核内存(每个 watch 几百 B) | agent 不崩 |
| agent 只 watch 必要子目录 | 改动监听逻辑 | 内核内存可控、不炸邻居 |
| 容器 user namespace 隔离 | 配置复杂度 | 单 pod 不拖垮整节点 |

🔧 思考题:既然 `max_user_watches` 调大能"解决",为什么我们说"watch 整棵大目录树"是反面模式?

<details>
<summary>【参考答案】</summary>

因为 watch 是占**内核内存**的,且按 uid 在整机/整节点共享。watch 整棵百万文件树,等于把几百 MiB 内核内存焊死在一个"文件变化监控"上,而且一旦目录膨胀就无限涨——你调大的 limit 永远追不上业务增长,且共享配额下会连累同 uid 的其他进程。正确的解法是**缩小监控范围**(已知子目录、单层、或轮询增量),让 watch 数收敛,而不是用 limit 去 cover 一个无界的设计。
</details>

---

## 实战补遗二：`kernel.sem` 四个值配错——System V 信号量把批量导入卡死

墨:你 PostgreSQL/Oracle 批量导入,报错 `No space left on device`(或 `Resource temporarily unavailable`),但 `df` 磁盘满、`ulimit` 够。你一脸懵:这错误不是"磁盘满"吗?

你:`No space left on device` 不是磁盘满吗?怎么和信号量有关?

墨:这是 Linux 最骗人的错误信息之一。`semget`/`semop` 失败时有时返回 `ENOSPC`("设备上没空间")——但这个"设备"指的是**System V 信号量集**,不是磁盘。它来自 `kernel.sem` 这条内核参数,和 `fs`/`kernel` 家族都沾边(第 16 章范畴),但绝大多数人只在磁盘满时见过 `ENOSPC`,于是被误导。

### 现象:批量导入报"磁盘满",磁盘明明空

某 PostgreSQL 大批量并发导入,worker 报错 `No space left on device` 或 `could not create semaphores`,导入卡死。`df -h` 磁盘 70% 空,`ulimit -n`/`ulimit -u` 都够。`ipcs -s` 一看,信号量集堆了几千个没释放。

### 推断(可能推错):先查磁盘和 fd

第一推断:「磁盘真满 / inode 满。」——`df -h`、`df -i` 都正常,推错(被 `ENOSPC` 字面误导)。
第二推断:「`ulimit -n` 满。」——fd 没满,推错。

### 真相:`kernel.sem` 的四个数,一个都不该忽略

`kernel.sem = SEMMSL SEMMNS SEMOPM SEMMNI`(四个空格分隔):
- `SEMMSL`:每个信号量集最多信号量数;
- `SEMMNS`:系统级信号量总数上限;
- `SEMOPM`:每次 `semop` 最多操作数;
- `SEMMNI`:系统级信号量集数上限。

PG 每连接建一个信号量集,并发导入时集数冲到 `SEMMNI` 上限 → `semget` 失败 → 报 `ENOSPC`(误导人的"设备上没空间")。默认 `SEMMNI` 常只有 32000 或更小,高并发 DB 轻松触顶。

### 调整:按 DB 并发放大,并查泄漏

- `kernel.sem="250 32000 100 1024"` 这类(按并发放大 `SEMMNI`/`SEMMNS`,具体看 DB 文档);
- 同时查**信号量泄漏**:`ipcs -s` 看大量 owned by 已退出的进程 → 应用没 `semctl` 释放(如崩溃没清理),需重启或 `ipcrm` 清理;
- 监控 `ipcs -s` 的集数 / `semmni` 用量;
- 持久化到 `sysctl.d`(第 0 章顺序坑)。

### 再观察

放大 `kernel.sem` + 修复应用释放信号量后,批量导入不再 `ENOSPC`,`ipcs -s` 集数稳定在合理值。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `kernel.sem` 放大 | 内核内存(每信号量集占结构) | 高并发不卡 |
| 修信号量泄漏 | 改代码 | 不堆积占满 |

🔧 思考题:为什么 `ENOSPC` 既可能指磁盘满、又可能指信号量满?遇到这个错怎么快速定位是哪个?

<details>
<summary>【参考答案】</summary>

`ENOSPC` 的字面是"设备上没有剩余空间",但"设备"在 Unix 里是泛称——磁盘、共享内存、信号量集都可能是"device"。定位:① `df -h`/`df -i` 看磁盘/inode,满就是磁盘;② `ipcs -s`/`ipcs -m` 看信号量/共享内存集数,接近 `kernel.sem`/`kernel.shmmni` 上限就是 IPC;③ 看报错进程在干什么——DB/中间件报、且磁盘空,九成是 IPC 满。关键:**别被错误字面带节奏**,看"谁在上限"。这也呼应全书的排障心法:现象(错误码)是线索不是结论,先确认"哪个资源到了上限"再动手——和 `EAGAIN`(第 2 章)、`SIGBUS`(第 3 章)一样,错误码只告诉你"哪类资源可能满",不告诉你"一定是哪个",要配计数确认。
</details>

---

## 实战补遗三：pid_max 被僵尸占满,新进程起不来

墨:`kernel.pid_max` 默认是多少?你猜过大还是小?

你:我记得 x86_64 上默认是 32768 还是 4194304?

墨:关键点就在这——32 位内核默认 32768,64 位内核默认 4194304(约 419 万)。所以**现代机器一般不会撞到 pid_max 上限**。但"一般不会"不等于"不会",而且撞上的方式特别阴。

**真实事故**:一台跑了三年没重启的渲染农场节点,某天早上批量任务全部起不来,报 `fork: resource temporarily unavailable`(`EAGAIN`),但 `free` 看内存还一大把、`uptime` 负载也不高。运维第一反应是"内存不够 fork 不出",加 swap、加内存,没用。

推断:既然不是内存,那就是"进程数/线程数"相关的资源。先看 `ps -eLf | wc -l`(线程总数)和 `ps -e | wc -l`(进程总数)。进程数才 1.2 万,远没到 419 万。那为什么 `fork` 失败?

再看 `ps -eo pid,stat,comm | grep -c Z`——僵尸进程数 3.1 万。几乎到 32768 了。等等,`pid_max` 不是 419 万吗?原来这台机器当年为了兼容一个老监控脚本,被人手贱写进了 `kernel.pid_max=32768`。僵尸进程不占内存、不占 CPU,但**占着 pid 号**。pid 是全局线性分配的,环回复用;当僵尸把可用 pid 区间塞满,新 `fork` 找不到空闲 pid,就 `EAGAIN`。

为什么有 3 万僵尸?渲染任务的父进程是个常驻调度器,它 `fork` 子进程渲染,子进程退出后调度器**没调 `wait()` 回收**,子进程变僵尸。日积月累三年,僵尸堆到上限。

调整:两步走。① 临时:`echo 4194304 > /proc/sys/kernel/pid_max` 立刻放开;② 根本:修调度器,渲染子进程退出后必须 `wait()` 或设 `SIGCHLD` 信号处理回收僵尸。同时把 `kernel.threads-max`(系统级线程上限,默认 ≈ `pid_max` 的 1/2 到 2 倍,按内存算)和容器的 `pids.max`(cgroup 的进程数硬墙)对齐,防止单容器 fork 炸弹拖垮整机。

再观察:放开 `pid_max` 后新任务立刻能起;修完回收逻辑,僵尸数逐日回落到个位数。

你:`threads-max` 和 `pid_max` 是两套账吗?

墨:是两套,但挂钩。`kernel.threads-max` 是"全系统线程总数上限",`pid_max` 是"pid 编号空间上限"。因为 Linux 里线程也是用 `clone` 出来的轻量进程、也占 pid,所以理论上 `threads-max` 不该超过 `pid_max`。内核会按内存自动给 `threads-max` 一个合理默认(每 4KB 内存一条线程的粗略估算),多数情况不用动;只有当你故意压低了 `pid_max`,或跑超密集线程程序(如某些 Java 应用开上万线程)时,才需要同步调大 `threads-max`。

🔧 思考题:僵尸进程"占着 pid 不占内存",那它到底占什么资源?为什么放任不管三年才会爆?

<details>
<summary>【参考答案】</summary>

僵尸进程在内核里只剩一个 `task_struct`(进程描述符)壳子:它已经释放了地址空间、文件描述符表会被父进程继承逻辑关掉,但 `task_struct` 本身要等父进程 `wait()` 才真正回收。所以僵尸占的是:
- **pid 编号**(全局有限资源,这是本次事故的直接原因);
- **一点点内核内存**(每个 `task_struct` 约 1–2KB,3 万僵尸也就 30–60MB,所以 `free` 看不出);
- **父进程的进程表项关联**(父进程不回收,僵尸永远挂着)。

为什么三年才爆?因为僵尸是**线性累积、不可逆**的——每漏回收一个就永久 +1,直到撞 pid 上限。短时间看不出,长期运行的服务(尤其 7×24 常驻调度器、老版本语言运行时的 GC 漏 wait)会在数月到数年间悄悄堆满。排查口诀:`fork` 报 `EAGAIN` 但内存充足 → 立刻查僵尸数 `ps -eo stat | grep -c Z` 和 pid 占用率,别先加内存。
</details>

---

## 实战补遗四：kernel.sem 四值——被 ENOSPC 误导的信号量配额

墨:`kernel.sem` 管 System V 信号量。没人用 SysV 信号量了吧?你以为这参数用不上,直到你跑了个老数据库或中间件。

你:四值是 `SEMMSL SEMMNS SEMOPM SEMMNI` 吧?分别对应单集合最大信号量数、系统总数、单次 op 数、集合数。

墨:对,但它坑在**报错会误导你**。讲个真实故事。

一个老版的 Oracle/某中间件集群,启动时报:`ORA-27154: ... error 28 (ENOSPC)` 或应用层 `semget: No space left on device`。运维一看 `ENOSPC`——"磁盘满了?" `df` 一看盘还有 80% 空;"inode 满了?" `df -i` 也够。完全懵。

你:ENOSPC 不是"设备上没空间"吗?怎么跟信号量扯上?

墨:这就是 System V 信号量的著名坑:`semget()` 失败返回 `ENOSPC`,**字面上"设备上无空间",实际意思是"信号量配额用完了"**——和磁盘一毛钱关系没有。内核用 `ENOSPC` 表达"系统级信号量资源耗尽",但错误信息措辞继承自"设备空间"的旧语义,害得无数人去查磁盘。

推断:既然不是磁盘,查信号量配额。四值默认(老内核):`SEMMSL=250 SEMMNS=32000 SEMMOPM=32 SEMMNI=128`。意思是:全系统最多 128 个信号量集合(`SEMMNI`),所有集合的信号量总数上限 32000(`SEMMNS`)。这个中间件每起一个实例就建一批信号量集合,实例多了,`SEMMNI=128` 先撞顶——第 129 个实例 `semget` 就 `ENOSPC`。

调整:把 `kernel.sem` 调大,如 `250 32000 100 1024`(最后一值 `SEMMNI` 从 128 提到 1024,允许 1024 个集合)。`sysctl -w kernel.sem="250 32000 100 1024"` 后实例全起得来。再观察:不再报 `ENOSPC`,集群满员。

你:四值里到底先撞哪个?怎么预判?

墨:看你的使用模式:
- 实例多、每个实例信号量集合少 → 先撞 `SEMMNI`(集合数上限),本事故就是;
- 单实例要超大信号量数组 → 先撞 `SEMMSL`(单集合上限);
- 全系统信号量总数多(很多小集合) → 先撞 `SEMMNS`(总数上限);
- 单次 `semop` 操作批量大 → 先撞 `SEMOPM`(单批 op 数)。

预判方法:`ipcs -s` 看现有信号量集合数和总数,对比四值上限,哪个先到顶调哪个。别像事故里那样被 `ENOSPC` 骗去查磁盘——记住:**任何 `semget`/`shmget`/`msgget` 报 `ENOSPC`,第一反应查 IPC 配额(`kernel.sem`/`kernel.shmmax`/`kernel.msgmni`),不是磁盘**。

🔧 思考题:System V IPC 还有共享内存(shm)和消息队列(msg),它们的"配额耗尽"也用 ENOSPC 吗?分别归哪个参数管?

<details>
<summary>【参考答案】</summary>

共享内存:`shmget` 失败常见 `EINVAL`(size 超 `kernel.shmmax` 单段上限)或 `ENOSPC`(总共享内存超 `kernel.shmall` 页数上限,或 `shmmni` 集合数上限)。归 `kernel.shmmax`(单段最大字节)、`kernel.shmall`(全系统共享内存总页数)、`kernel.shmmni`(段数上限)三兄弟管。
消息队列:`msgget` 失败 `ENOSPC` 通常是总字节数超 `kernel.msgmnb`(单队列最大字节)或队列数超 `kernel.msgmni`。归 `kernel.msgmni`(队列数)、`kernel.msgmnb`(单队列字节上限)管。

所以"IPC 三兄弟"(sem/shm/msg)的配额耗尽**全用 ENOSPC 误导你**,分别归 `kernel.sem`/`kernel.shmmax`+`shmall`/`kernel.msgmni`+`msgmnb`。口诀:**凡 `semget/shmget/msgget` 报 `ENOSPC`,别碰 `df`,直接 `ipcs -l` 看配额上限、`ipcs -s/-m/-q` 看已用量,哪个到顶调哪个**。现代程序多用 POSIX 信号量/共享内存(`/dev/shm` 走 `tmpfs`,归 `fs.*` 和 cgroup 管),但跑老版 Oracle/PostgreSQL(某些编译选项)/中间件时,SysV 这套仍绕不开,运维必知。
</details>

---

## 实战补遗五：fs.inotify.max_user_watches 耗尽——"too many open files"的表亲陷阱

墨:第 16 章讲了 fd 三件套(ulimit/fs.file-max/cgroup)。但还有个**独立配额**,它耗尽时报的错和 fd 很像,却完全不归那三件套管——`fs.inotify.max_user_watches`。你知道谁最容易踩吗?

你:inotify 是监听文件变更的吧?`max_user_watches` 是"一个用户能 watch 多少文件"?

墨:对,而且关键在于"**按 uid 共享,不是按进程**"。讲个真实事故。

一个开发机(也是 CI 节点)跑着:① VS Code(监听工作区所有文件做语法高亮)② `webpack --watch`(监听源码变更热重载)③ 一个 Go 服务的 `fsnotify` 监听配置目录。某天新启一个 `webpack` 项目,直接报错:`Error: ENOSPC: System limit for number of file watchers reached`。

你:又是 ENOSPC!这报错跟 kernel.sem 那个一样误导吧?

墨:对,还是那个臭名昭著的 `ENOSPC`(设备上无空间),实际意思是"**inotify watch 配额用完了**",跟磁盘一毛钱关系没有。而且坑在"按 uid 共享":这台机器上 VS Code、`webpack`、CI 全用**同一个用户**跑,它们的 watch 数**累加到同一个 uid 的配额**(`max_user_watches` 默认才 8192)。VS Code 一个就 watch 几千个文件,加上多个 `webpack` 项目,8192 轻松打满,新项目再想 watch 就 `ENOSPC`。

推断:不是 fd 不够(ulimit/fs.file-max 都够),是 **inotify watch 这个独立配额**满。验证:`cat /proc/sys/fs/inotify/max_user_watches`(上限,默认 8192)、`cat /proc/sys/fs/inotify/max_user_instances`(每用户实例数);再用 `find /proc/*/fd -lname anon_inode:inotify 2>/dev/null | wc -l` 或 `inotifywait -m` 统计当前 watch 数,发现逼近 8192。根因就是"同 uid 多 watcher 累加超默认配额"。

调整:① 临时:`sysctl -w fs.inotify.max_user_watches=524288`(提到几十万,现代机器内存够);② 根本:如果是容器,**这个配额是宿主级的**(inotify watch 按宿主 uid 算,容器里看到的默认 8192 是宿主值,且容器通常改不了——又是找错门),得在**宿主节点 init 阶段**统一调大;③ 应用层:减少不必要的 watch(如 `webpack` 用 `ignored` 排除 `node_modules`,VS Code 关掉不需要的文件夹监听)。再观察:配额提到 50 万后,所有 watcher 并存无压力,`ENOSPC` 消失。

你:inotify 配额和 fd 配额是两套,那它消耗内存吗?为什么默认才 8192 这么小?

墨:inotify watch **每个消耗内核内存**(约几百字节到 1KB 的 `inotify` 结构体 + 被 watch 的 inode 引用)。默认 8192 是老内核时代的保守值(那时机器内存小、没人 watch 几万个文件)。现在:
- 开发机/CI 节点:一个 IDE + 几个 watch 项目轻松几万 watch,8192 必爆,必须调大(内存代价也就几十 MB,值得);
- **容器场景要注意**:`max_user_watches` 是**宿主按 uid 算的全局配额**,一个节点上几十个 pod 若都用同一宿主 uid(或特权容器),它们的 inotify watch 会**累加吃宿主配额**——所以节点级要调大,且容器不该依赖"自己改这个值"(改不了、且影响别人)。

和 fd 三件套的区分口诀:**`Too many open files` → 查 ulimit/fs.file-max/cgroup files; `ENOSPC: file watchers reached` → 查 fs.inotify.max_user_watches(且是独立配额、按 uid 共享、宿主级)**。两者报错都可能含 "ENOSPC" 或 "too many",但作用域和参数完全不同,别混。这也是全书"分清作用域"主题在 fs 家族的又一例:inotify 有自己独立的、按 uid 的、宿主级的账本。

🔧 思考题:容器里 `cat /proc/sys/fs/inotify/max_user_watches` 看到 8192,我 `sysctl -w` 改成 524288 报错 permission denied——为什么?正确怎么改?

<details>
<summary>【参考答案】</summary>

报错 `permission denied` 是因为:① 容器(非特权)没有 `CAP_SYS_ADMIN`,改不了这个内核参数;② 就算特权容器能改,它改的是**宿主内核的那一份**(`max_user_watches` 是全局、按宿主 uid),会**影响同 uid 的所有容器/进程**,且重启容器后丢失(因为改的是运行中的内核值,不是持久化)。所以"在 pod 里改"既非法又无效、还可能误伤别人。

正确做法(节点级):
1. 在**宿主** `sysctl -w fs.inotify.max_user_watches=524288`(临时),或写宿主 `sysctl.d/99-node-tuning.conf` 持久化(`fs.inotify.max_user_watches = 524288`);
2. 容器侧别碰,重启后宿主配置仍在,所有 pod 共享放大后的配额;
3. 应用层兜底:`webpack` 配 `watchOptions.ignored = /node_modules/`、`vite` 配 `server.watch.ignored`、Go `fsnotify` 只 watch 必要目录——减少 watch 数,比无脑调大配额更干净。

口诀:inotify 配额是"宿主按 uid 全局"的,和 zone_reclaim_mode、read_ahead_kb、vm.* 一样——**容器里改是找错门 + 越权 + 不持久**,统一在节点 init 设。K8s 节点初始化脚本(如 kubeadm 的 `sysctl` 阶段、或 Node 的 cloud-init)里把这行写进去,所有 pod 受益且重启不丢。
</details>

---

---

## 实战补遗六：fs.file-max、aio-max-nr 与 Docker 默认 ulimit——"Too many open files" 到底卡在哪一层

墨：老哥，你线上报过 `too many open files` 吗？第一反应是不是 `ulimit -n` 调大？

你：对，调 `nofile` 的 soft/hard。

墨：调 `ulimit -n` 对症，但很多人不知道这报错背后**有三层限制**，只调一层可能没用。我拆一次"调了 ulimit 还是报"的事故。

现象：一个 Go 网关（Caddy 类），长连接 + 每连接一个 goroutine，连接数到 1 万就报 `accept tcp: too many open files`。运维把 `ulimit -n` 调到 10 万，重启，**还是 1 万就报**。

推断：ulimit 没生效（systemd 服务没继承）。

可能推错：第一，`ulimit -n` 在 shell 里调，但**服务由 systemd 拉起，不读你的 shell ulimit**——得在 unit 文件里写 `LimitNOFILE=100000`。第二，即使进程层 `ulimit -n` 够了，还有**内核全局**的 `fs.file-max`——它是全系统打开文件句柄（file descriptor）的总上限，所有进程共享。第三，容器里 Docker 默认 `ulimit -n` 是 **65536 但 soft 可能 1048576 之类**，具体看成镜像，且容器里看到的 `fs.file-max` 是**宿主的**（不隔离）。

调整：三层从下往上看：
1. **进程级 `ulimit -n`（nofile）**：单进程能开的 fd 上限。看 `cat /proc/<pid>/limits | grep "open files"`。systemd 服务在 `[Service]` 加 `LimitNOFILE=`。
2. **cgroup 级（容器）**：Docker 用 `--ulimit nofile=...` 或 k8s `resources.limits` 不设则继承宿主默认（通常足够大）。这是容器的"进程级"上限。
3. **内核全局 `fs.file-max`**：`cat /proc/sys/fs/file-max`，系统总 fd 数。看 `cat /proc/sys/fs/file-nr`：第三列是 `file-max`，第一列是当前已分配 fd 数。若 `file-nr` 第一列逼近第三列，就是全局满了，得 `sysctl -w fs.file-max=...` 调大（同时要 `fs.nr_open` 够大）。

再观察：那次"调了 ulimit 还报"，根因是 **systemd unit 没设 `LimitNOFILE`**，进程实际继承的是默认 1024（或 Docker 默认），所以 1 万连接就撞。改 unit 文件后解决。另外还发现 `fs.file-max` 默认 80 万，在 1 万连接远没到，所以全局没瓶颈——确认是进程层。

顺带：`fs.aio-max-nr` 是**异步 IO 事件**上限（不是 fd），只有用 `io_uring`/`libaio` 的服务关心；Go 一般不直接用 aio，除非用了某些存储库。`kernel.sem` 四值（`SEMMSL/SEMMNS/SEMOPM/SEMMNI`）控制 System V 信号量，老应用（Oracle 等）才碰，报 `ENOSPC` 时容易被误导去查磁盘空间（详见第 16 章 kernel.sem 实战补遗）。

改进：
- 先 `cat /proc/<pid>/limits` 看进程实际 nofile，别信 shell 里的 `ulimit`。
- systemd 服务必须在 unit 写 `LimitNOFILE`；容器用 `--ulimit nofile=` 或 k8s 配。
- 全局 `fs.file-nr` 第一列逼近第三列才调 `fs.file-max`。
- 监控 fd 泄漏：连接数稳定但 fd 一直涨 = 泄漏（没 `close`），调大只是拖延，根因是代码没关连接。

🔧 思考题：为什么"连接数稳定但 fd 数一直涨"几乎一定是泄漏，而不是"业务量真的大了"？怎么用 `ls /proc/<pid>/fd | wc -l` 和 `ss` 区分"正常高并发"和"泄漏"？

<details>
<summary>【参考答案】</summary>

"连接数稳定但 fd 涨"：fd 是"当前打开的句柄数"，它等于"活跃连接 + 没被关掉的死连接"。如果业务连接数已经平稳（比如 `ss -tan | grep ESTAB | wc -l` 恒定在 1 万），但 `ls /proc/<pid>/fd | wc -l` 还在涨到 5 万、10 万，说明有大量 fd 对应的连接**已经不在 `ss` 的 ESTAB 里了**（已关闭或卡在别的状态），却没被进程 `close`——这就是典型的 fd 泄漏：goroutine 退出但没关连接、或 `defer` 没写、或 HTTP 客户端没 `resp.Body.Close()`。正常高并发是"连接数和 fd 数一起涨一起落、比例稳定"；泄漏是"连接数平、fd 一直涨、比例越来越离谱"。

定位步骤：
1. `ls /proc/<pid>/fd | wc -l` 看进程总 fd。
2. `ss -tanp | grep <pid> | wc -l` 看该进程真正的 socket 连接数。
3. 二者差距巨大 → 泄漏。再看 fd 里大多是 socket 还是 pipe/regular file：`ls -l /proc/<pid>/fd | awk '{print $NF}' | sort | uniq -c` 归类。
4. socket 泄漏查"哪个包建立的连接没 close"；pipe 泄漏查 `io.Pipe`/`exec.Cmd` 没读完 stdout。

根因修复是代码里补 `close`（Go 里 `defer resp.Body.Close()` 是铁律，哪怕 `io.Copy` 掉也别忘了）。`ulimit -n` 调大只是把"爆炸点"往后挪，不治本，且会拖慢 OOM 时的故障暴露。所以：**fd 泄漏靠 code review + close，不靠调 ulimit**。
</details>

下一章预告

墨:`fs` 和 `kernel` 两章把"资源配额 + 崩溃开关"讲完了。下一章(第 17 章)我们扫尾**其他家族**:`abi`(系统调用兼容)、`dev`(设备相关)、`user`(用户命名空间/进程计数)、`debug`(内核调试接口)、`crypto`(加密算法默认),以及——**最容易混的**——那些**长得像 sysctl 但不是**的东西:`/sys/cgroup`(cgroup v1/v2 接口树)和 `ulimit`(shell/进程级限制,不是 sysctl)。我会专门画一张"sysctl 与它的近亲对照表",让你从此不再找错地方。

---

*本章完。其他家族与 cgroup/ulimit 对照见第 17 章。*
