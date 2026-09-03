# 第 15 章 `net` 家族参数分类——协议栈各层的守门人

> 第 10 章我们讲了 TCP 的微观旅程,顺带把 `tcp_*` 在事故里焊了一遍。但 `net` 这个 sysctl 家族比 `tcp` 大得多:`net.core`(通用收发)、`net.ipv4`(IP 层 + 一半 TCP)、`net.ipv6`、`net.unix`、`net.bridge`……
> 这一章把 `net` 家族**按协议栈分层**整理成一张"守门人地图":每一层有哪些关键调参旋钮、守哪道门、拿什么换什么。你已经认识 `tcp_*`,这里补全其余的,并且**把"为什么有这些参数"落到分层逻辑上**——而不是又一张参数表。

---

## 一、先画 `net` 的分层地图

墨:老哥,`sysctl -a | grep net` 一打出来几百行,晕不晕?别背。先按**协议栈分层**把它们归位,你才知道每个参数在管哪一段:

```
应用层 socket 选项  ←(不在 sysctl,SO_*,如 TCP_NODELAY)
   │
[net.core]      ← 通用:接收/发送缓冲上限、backlog、softirq 预算、邻居表
   │
[net.ipv4]      ← IP 层:路由/邻居(ARP)/ICMP/分片 + TCP 子项 + 源地址/转发
   │   ├─ tcp_*   (你已经熟悉,第10章)
   │   ├─ 非 tcp: 邻居/arp/icmp/conf/all/*/源路由/转发
   │
[net.ipv6]      ← 类似 ipv4 但 IPv6 特有(地址生成/ND/默认禁转发)
[net.unix]      ← 本地 socket 参数
[net.bridge]    ← 桥接(容器/KVM 常见)
```

墨:关键认知:**`net.core` 管的是"所有协议通用的收发管道",`net.ipv4` 管的是"IPv4 这一层的路由/邻居/分片/转发 + TCP"。你调 `net.core.somaxconn` 影响所有协议,调 `net.ipv4.tcp_*` 只影响 TCP。** 分层之后,哪个参数管哪段就清楚了。

---

## 二、`net.core`:通用收发管道(所有协议共享)

| 参数 | 类别 | 默认 | 守的门 / 拿什么换什么 |
|---|---|---|---|
| `net.core.somaxconn` | ① 日常旋钮 | 128 | accept 全连接队列全局上限(第 10 章事故一主角)。调大(如 65535)换高并发建连 ↔ 略多内存。**几乎必调。** |
| `net.core.netdev_max_backlog` | ② 安全阀 | 1000 | 软中断收包后,进协议栈前的**每 CPU 排队上限**。包速超处理速时,满了丢包。`/proc/net/softnet_stat` 第三列涨就调大(第 09 章)。换:多占一点 per-CPU 内存。 |
| `net.core.netdev_budget` | ① 日常旋钮 | 300(老)/变 | 软中断**每轮最多处理的包数**。调大(如 600)让软中断一次多干点,高 PPS 时减少轮次 ↔ 单次软中断占 CPU 久。第 09 章提过。 |
| `net.core.rmem_max` / `wmem_max` | ① 日常旋钮 | 视内核 | **socket 缓冲的硬上限**(应用 `SO_RCVBUF` 不能超过)。`tcp_rmem` 的 max 也不能超它。调大换长肥管道吞吐 ↔ 内存。 |
| `net.core.rmem_default` / `wmem_default` | ① 日常旋钮 | 视内核 | 未显式 setsockopt 时 socket 缓冲的默认值。 |
| `net.core.optmem_max` | ① 日常旋钮 | 20480 | 每个 socket 的"辅助数据/控制消息"缓冲上限(如 `recvmsg` 的 ancillary)。大消息控制场景调大。 |
| `net.core.netdev_budget_usecs` | ① 日常旋钮 | 2000(us) | 软中断每轮处理的时间预算(配合 budget)。 |

墨:`net.core` 这几个是**高并发网络服务必调基线**。somaxconn 在事故一已经焊死;`netdev_max_backlog` + `netdev_budget` 是第 09 章软中断丢包的逃生阀;`rmem_max/wmem_max` 是 `tcp_rmem`/`tcp_wmem` 的"天花板"——**你调大 tcp_rmem 的 max,如果 rmem_max 没跟着大,等于白调**(经典二层联动坑)。

---

## 三、`net.ipv4`:IP 层 + TCP(非 tcp 部分)

### 3.1 邻居/ARP 子系统(第 09 章链路层收尾)

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `net.ipv4.neigh.default.gc_thresh1/2/3` | ARP 表垃圾回收阈值(条目数) | 128/512/1024 | 调大换"大二层网络不丢 ARP 表" ↔ 多占内存。容器/K8s 节点邻居多,常需调大,否则 `neighbour: arp_cache: neighbor table overflow!` |
| `net.ipv4.neigh.default.base_reachable_time` / `gc_stale_time` | 邻居项有效期/过期扫描 | 30s/60s | 调大减 ARP 广播 ↔ 缓存 stale 风险 |
| `net.ipv4.conf.all.arp_ignore` / `arp_announce` | ARP 响应策略(多 IP/多网卡场景) | 0/0 | 设 `arp_announce=2 / arp_ignore=1` 是 LVS/负载均衡**防 ARP 混乱**的标准做法,换"正确通告" ↔ 略复杂 |

墨:邻居表溢出的报错你在 K8s/容器节点上一定见过。**一个 Pod 密集的节点,邻居(对端 MAC)成千上万,默认 1024 的 `gc_thresh3` 撑不住,新邻居加不进来,网络抽风。** 这是 `net.ipv4` 里最被忽视、却最常坑容器环境的参数。

### 3.2 ICMP 与分片(第 10 章事故二相关)

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `net.ipv4.icmp_echo_ignore_all` | 是否忽略 ping | 0 | 设 1 防 ping 探测 ↔ 也丢了诊断手段。**别为"安全"全禁 ICMP**,否则 PMTU 发现失效(第 10 章事故二)。 |
| `net.ipv4.icmp_ignore_bogus_error_responses` | 忽略伪造 ICMP 错误 | 1 | 安全项,防伪造 ICMP 干扰。 |
| `net.ipv4.ipfrag_high_thresh` / `ipfrag_low_thresh` | IP 分片重组缓冲上下限 | 视内存 | 调大换"大分片流不丢重组" ↔ 内存。分片攻击场景反而要调小防内存耗尽。 |
| `net.ipv4.tcp_mtu_probing` | ICMP 被墙时自探 MSS(第10章) | 0 | 设 1~2 换"抗 MTU 黑洞" ↔ 探测开销。 |

### 3.3 转发与源路由

| 参数 | 守的门 | 默认(服务器) | 拿什么换什么 |
|---|---|---|---|
| `net.ipv4.ip_forward` | 是否开启 IP 转发(路由器/网关需 1) | 0 | 做网关/NAT/容器需 1 ↔ 风险面变大。 |
| `net.ipv4.conf.all.accept_redirects` / `send_redirects` | ICMP 重定向 | 1/1(或按 distro) | 设 0 防重定向劫持(安全),换"失去自动路由优化"。 |
| `net.ipv4.conf.all.rp_filter` | 反向路径过滤(防 IP 欺骗) | 1 | 严格 RPF 防 spoofing ↔ 非对称路由场景可能误丢合法包(需设 2/loose)。 |
| `net.ipv4.conf.all.accept_source_route` | 接受源路由包 | 0 | 0 防源路由攻击,几乎都设 0。 |

墨:`rp_filter` 是个经典"安全默认却坑业务"的参数:严格模式(=1)下,如果流量走**非对称路由**(去和回不是同一条链路,如多线 BGP),回包会被当" spoofing"丢掉。这种网络环境下要么设 `rp_filter=2`(loose),要么按接口单独设。**又是"字面安全"踩坑。**

---

## 四、`net.ipv6`:IPv6 特有守门人

墨:IPv6 和 IPv4 是**两套独立参数树**(`net.ipv6.*`)。常见运维只调了 ipv4,结果 IPv6 路径出问题(双栈环境下某些流量走 v6)。

| 参数 | 守的门 | 默认 | 拿什么换什么 |
|---|---|---|---|
| `net.ipv6.conf.all.forwarding` | IPv6 转发(对应 ipv4 的 ip_forward) | 0 | 容器/网关需 1。 |
| `net.ipv6.conf.all.accept_ra` | 接受路由器通告(RA) | 1 | 服务器静态 IP 常设 0(防被 RA 改默认路由)。 |
| `net.ipv6.neigh.*` | IPv6 邻居(ND)表,同 ipv4 邻居 | — | 容器节点同样要调大 gc_thresh。 |
| `net.ipv6.bindv6only` | 是否只绑 v6(影响 v4-mapped) | 0 | 0 允许 v4-mapped,1 严格分离。 |

你:那我双栈服务器,是不是 ipv4 和 ipv6 都得调一遍?

墨:对,而且**很多"玄学网络问题"就是 v6 路径用了默认参数、v4 路径调过了**——比如 `somaxconn` 对两者都生效(`net.core` 通用),但 `neigh` 的 gc_thresh、forwarding 必须各调各的。排障时先 `ss -tunlp` 看连接是 v4 还是 v6 建立的,再决定调哪棵树。

---

## 五、`net.unix` 与 `net.bridge`:常被忽略的两支

| 家族 | 关键参数 | 守的门 |
|---|---|---|
| `net.unix` | `net.unix.max_dgram_qlen` | 本地(unix domain socket)数据报队列上限。高并发本机 IPC(如通过 unix socket 的 sidecar)满时丢包。 |
| `net.bridge` | `net.bridge.bridge-nf-call-iptables` / `bridge-nf-call-ip6tables` | 桥接流量是否过 iptables/nftables。容器/KVM 网桥场景**必须理解**:设 1 则桥上流量也被 iptables 规则处理(常导致性能/规则意外命中),设 0 则桥直接转发不过滤。K8s/ Docker 环境常因此翻车。 |

墨:`net.bridge.bridge-nf-call-iptables` 是容器网络**第一玄学来源**:你写了条 iptables 规则想挡某 IP,结果桥上的 Pod 流量也莫名其妙被挡/或不过滤,根因就在这。它把"二层桥接"和"三层 iptables"焊在一起,**理解它才懂容器网络为什么要把它设 0 或 1**。

---

## 六、`net` 家族总表(守门人速查)

| 层 | 参数 | 守的门 | 拿什么换什么 |
|---|---|---|---|
| core | somaxconn | accept 队列上限 | 高并发建连 ↔ 内存 |
| core | netdev_max_backlog/budget | 软中断→协议栈排队 | 高 PPS ↔ per-CPU 内存/CPU 占 |
| core | rmem_max/wmem_max | socket 缓冲天花板 | 长肥管道吞吐 ↔ 内存 |
| ipv4 | neigh.gc_thresh* | ARP 表容量 | 大二层不溢出 ↔ 内存 |
| ipv4 | tcp_mtu_probing | MTU 黑洞(第10章) | 抗黑洞 ↔ 探测开销 |
| ipv4 | rp_filter | IP 欺骗防护 | 安全 ↔ 非对称路由误丢 |
| ipv4 | ip_forward/accept_redirects | 转发/重定向 | 网关功能 ↔ 风险面 |
| ipv6 | forwarding/accept_ra/neigh | v6 转发/邻居 | 双栈可用 ↔ 安全/内存 |
| bridge | bridge-nf-call-iptables | 桥接是否过 iptables | 容器网络可控 ↔ 性能/规则命中 |

---

## 七、🔧 思考题(都配参考答案)

**思考题 1(基础):** 你调大了 `net.ipv4.tcp_rmem` 的 max 想提升长肥管道吞吐,但 `ss -tin` 看窗口还是撑不开。请指出一个最可能的"二层联动"遗漏,并解释为什么。

<details>
<summary>【参考答案】</summary>

遗漏:`net.core.rmem_max`(socket 接收缓冲的**硬上限**)没跟着调大。`tcp_rmem` 的 max 是 TCP 层面的软上限,但**应用缓冲区 + TCP 缓冲都不能超过 `net.core.rmem_max`**——它是天花板。你调大 tcp_rmem 的 max,若 rmem_max 仍是默认较小值,TCP 实际能撑的窗口被 rmem_max 卡住,窗口撑不开。正确:`net.core.rmem_max` ≥ `tcp_rmem` 的 max,且应用 `setsockopt(SO_RCVBUF)` 也不超 rmem_max。这是"调了 A 却不知 B 是天花板"的经典联动坑。
</details>

**思考题 2(深入):** 一个 K8s 节点,Pod 网络偶发"新连接建立慢/部分不通",`dmesg` 里有 `neighbour: arp_cache: neighbor table overflow!`。请解释根因,并给出调参与根因两层解法。

<details>
<summary>【参考答案】</summary>

根因:Pod 密集节点,邻居(对端 MAC)条目成千上万,超过 `net.ipv4.neigh.default.gc_thresh3`(默认 1024)上限,新邻居加不进 ARP 表,导致对应目的 IP 无法解析 MAC,连接建不起来/慢。调参(治标):调大 `gc_thresh1/2/3`(如 1024/4096/8192)给 ARP 表扩容。根因(治本):节点上 Pod 密度/网段规划是否合理,或是否该用 `ipv6`/大二层优化;长期应控制单节点邻居规模。注意这是 `net.ipv4` 里最被忽视却最常坑容器环境的参数,且 IPv6 的 `net.ipv6.neigh.*` 同样要调。
</details>

**思考题 3(安全 vs 业务):** `net.ipv4.conf.all.rp_filter=1`(严格反向路径过滤)是安全默认,但什么网络拓扑下会导致合法流量被丢?该怎么正确配置?

<details>
<summary>【参考答案】</summary>

`rp_filter=1` 严格校验"回包必须从到达接口的同一链路出去",**在非对称路由拓扑下(去和回不是同一条链路,如多线 BGP、双上联不同 ISP)会误判合法回包为 IP 欺骗而丢弃**。正确配置:非对称路由环境设 `rp_filter=2`(loose,只校验源地址在路由表中可达,不限接口);或按接口单独设(对外接口 strict、内网接口 loose)。原则:安全默认(1)是为防 spoofing,但**拓扑不匹配时它比攻击者更先干掉你的合法流量**——这是"字面安全"踩坑的又一例。
</details>

**思考题 4(进阶总账):** 综合第 09、10、15 章,给"高并发网关"列一张 `net` 家族调优基线(至少 6 项:参数 + 取值方向 + 守的门),作为速查卡。

<details>
<summary>【参考答案】</summary>

高并发网关 `net` 基线:
1. `net.core.somaxconn=65535`(accept 队列,第10章事故一)+ 应用 listen backlog 跟上。
2. `net.core.netdev_max_backlog=65535` + `net.core.netdev_budget=600`(软中断排队/处理,第09章)。
3. `net.core.rmem_max`/`wmem_max` 调大(如 16MB),并 `tcp_rmem`/`tcp_wmem` max ≤ 它(长肥管道,第10/15章联动)。
4. `net.ipv4.tcp_max_syn_backlog=8192` + `tcp_syncookies=1`(syn 队列/抗洪峰,第10章)。
5. `net.ipv4.tcp_tw_reuse=1`(客户端角色复用 TIME_WAIT,第10章)。
6. `net.ipv4.neigh.default.gc_thresh3` 调大(容器/大二层防 ARP 溢出,本章)。
7. (可选)`net.ipv4.tcp_congestion_control=bbr`(bufferbloat 场景,第10章)。
心法:core 通用 + ipv4/tcp 分层,且**注意 rmem_max 是 tcp_rmem 天花板**这类联动。
</details>

---

## 八、net 参数的"天花板"联动陷阱

墨:第 13 章讲 vm 参数联动,net 也一样——**很多 net 参数调了不生效,是因为有个"天花板"或"兄弟参数"你没一起动**。这一节把最坑的联动钉死。

**陷阱 1:`net.core.rmem_max` 是 `tcp_rmem` 的天花板(思考题 1 已点,展开)。** `tcp_rmem` 的 max 是 TCP 层软上限,但**应用缓冲区 + TCP 缓冲都不能超过 `net.core.rmem_max`**(它是硬顶)。你调大 `tcp_rmem` 的 max,若 `rmem_max` 仍默认较小,TCP 窗口被它卡死、撑不开。同理 `wmem_max` 是 `tcp_wmem` 的天花板。两对必须**配对调**,且应用 `setsockopt(SO_RCVBUF)` 也不超 `rmem_max`。

**陷阱 2:`net.core.somaxconn` vs 应用 `listen()` 的 backlog。** `somaxconn` 是内核 accept 队列上限,但应用 `listen(fd, backlog)` 的 `backlog` 参数**同样限制**队列长度,实际取两者较小值。光调 `somaxconn` 不调应用 `listen` 的 backlog(如 Nginx `backlog`、Go `net.ListenConfig` 默认),队列照样小(第 10 章事故一)。

**陷阱 3:`net.core.netdev_budget` vs 核数/多队列。** `netdev_budget` 限制单核每轮 NAPI 处理的包数,**多核靠多队列把包分摊到各核**。单队列机器调大 `netdev_budget` 也救不了(一个核处理到死);必须先 `ethtool -L` 开多队列,`netdev_budget` 才有意义(第 09 章)。

**陷阱 4:`tcp_rmem` max vs BDP(带宽×延迟)。** 长肥管道要窗口 ≥ BDP 才喂得饱,但窗口受 `rmem_max` 与 `tcp_rmem` max **双重限制**,且 `tcp_window_scaling` 必须开(否则窗口上限 64KB)。三者都要对。

墨:net 调参的铁律和 vm 一样——**动 A 之前,先找"卡 A 的天花板 B"和"必须配对的兄弟 C"**。

---

## 九、net 故障速查:症状 → 参数

墨:把第 10、15 章的 net 参数收成一张"症状→该查的参数"速查卡,排障时直接跳:

| 症状 | 第一怀疑参数 | 配套检查 |
|---|---|---|
| 建连慢 / 拒绝新连接 | `somaxconn` + `tcp_max_syn_backlog` + `tcp_syncookies` + 应用 listen backlog | 第 10 章事故一 |
| `EADDRNOTAVAIL`(端口不够) | `ip_local_port_range` + `tcp_tw_reuse` + `tcp_max_tw_buckets` | 第 21 章案 A |
| 高 PPS 丢包 | `netdev_max_backlog` + `netdev_budget` + RPS/XPS + 多队列(`ethtool -L`) | 第 09 章 |
| 重传率高 / RT 高(小包通大包丢) | `tcp_mtu_probing` + MTU + `tcp_retries2` + `tcp_sack` | 第 21 章案 B |
| 邻居表溢出(ARP) | `neigh.default.gc_thresh1/2/3` | 本章 |
| 带宽起不来(长肥管道) | `rmem_max`/`wmem_max` + `tcp_rmem`/`tcp_wmem` + `tcp_window_scaling` + 拥塞控制 `bbr` | 第 10 章 |
| 合法流量被误丢(连接飘) | `rp_filter`(非对称路由设 2) | 本章 |

---


---

## 十、net 实战事故:`rp_filter=1` 把跨国专线的回包全丢了

`📦 案例:某出海业务,国内机房到海外节点走"双线 BGP + 专线"混合链路。上线后海外用户投诉"一半请求超时",但国内访问正常,且服务器 CPU/内存/磁盘都闲。`

### 现象(第 0 层)
海外方向超时率高(约 50%),国内正常。服务器资源全闲,`tcpdump` 在服务器上能看到海外请求**进来**,但**回包没出去**(或出去了没被对端收)。

### 推断 1:海外链路 / 防火墙?(推错)
你:超时嘛,先看链路质量、看海外防火墙。
墨:查海外链路——延迟正常、没丢包;防火墙规则没拦。且诡异的是:**服务器收到了请求,却"选择性"地不回某些源**。方向转向"服务器自己把回包丢了"。

### 命中:rp_filter 严格模式误杀非对称路由回包
墨:`net.ipv4.conf.all.rp_filter=1`(严格反向路径过滤):内核校验"回包是否从到达接口的同一条链路出去",不一致就当 spoofing 丢。本案海外流量**去走专线、回走 BGP**(非对称路由,去回不同链路),于是**合法的回包被 `rp_filter=1` 判为 IP 欺骗直接丢弃**——一半请求"有来无回",表现为 50% 超时。
验证:`nstat -az | grep -i rpfilter`(或 `netstat -s` 的 filter 计数)在超时期间暴涨;临时 `sysctl -w net.ipv4.conf.all.rp_filter=2`(loose,只校验源在路由表可达,不限接口)后超时消失。

### 调整
墨:两剂药:
1. **`rp_filter=2`(loose)**:非对称路由环境的正确值(只查源可达性,不查接口一致)。
2. **按接口细配**:对外多线接口设 2,纯内网单线接口可保持 1(严格防 spoofing)。别"all=1"一刀切。

### 改进:超时归零,收口
墨:`rp_filter=2` 后海外超时归零。复盘:**`rp_filter=1` 是"为安全默认开"的参数,但在非对称路由(多线 BGP、双上联、专线+公网混合)下,它比攻击者更先干掉你的合法流量**(第 15 章表 3.3 已点)。这又是一例"字面安全、实则坑业务"。排障口诀:多线/跨境/混合链路 + 一半超时 + 资源全闲 → 先查 `rp_filter`,别在链路和防火墙里打转。

---

## 十一、net 实战事故二:`net.core.rmem_max` 天花板把 BBR 长肥管道吞吐卡死

`📦 案例:某跨境传输服务,客户端到海外节点跑 BBR,链路是 1Gbps、RTT 80ms 的长肥管道(BDP ≈ 10MB)。理论上 BBR 能把带宽吃满,实测只跑到 120Mbps,且怎么调 net.ipv4.tcp_rmem 都没用——运维一度怀疑是跨境专线被限速。`

### 现象(第 0 层)
跨境大文件传输吞吐上不去(目标 ~950Mbps,实际 ~120Mbps)。`ss -tin` 看 `rcv_wnd`(接收窗口)卡在某个很小的值上不去;`bbr` 显示没拥塞、无重传,但窗口就是撑不开。

### 推断 1:链路质量 / BBR 没生效?(推错)
你:跨境嘛,先怀疑专线限速或丢包。查 `ss -i` —— `bbr` 确实在跑、RTT 稳定、无重传、`retrans` 率低;换 `cubic` 试也一样慢。排除链路和拥塞算法本身。

### 命中:`rmem_max` 是 `tcp_rmem` 的天花板(第 15 章"陷阱 1"的实体版)
墨:回忆第 15 章:**`tcp_rmem` 的 max 是 TCP 层软上限,但应用缓冲 + TCP 缓冲都不能超过 `net.core.rmem_max`(硬顶)**。该机 `rmem_max` 是默认 `212992`(≈ 208KB),而长肥管道要窗口 ≥ BDP ≈ 10MB 才喂得饱。于是 `tcp_rmem` 即便被设到 16MB,实际窗口被 `rmem_max=208KB` 卡死,`rcv_wnd` 撑不开,发送端受流控限制只能慢慢发,吞吐被锁在 120Mbps。验证:`sysctl net.core.rmem_max` = 208KB;且 `ss -tin` 的 `rcv_wnd` 上限正好卡在 ≈ rmem_max 附近。

### 调整
```bash
net.core.rmem_max = 16777216          # 16MB,窗口天花板先抬高
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216   # max ≤ rmem_max
net.ipv4.tcp_wmem = 4096 65536 16777216
# 应用 setsockopt(SO_RCVBUF) 也不超 rmem_max;BBR 保持
```
配套确认:`net.ipv4.tcp_window_scaling = 1`(否则窗口硬上限 64KB,再多 rmem 也白搭,第 15 章"陷阱 4")。

### 改进:吞吐从 120Mbps 涨到 ~950Mbps,收口
墨:三把锁(`rmem_max` / `tcp_rmem max` / `window_scaling`)对齐 BDP 后,窗口撑开,BBR 吃满带宽。复盘:**这是"调了 A 却不知 B 是天花板"的 net 版典范**,和第 15 章思考题 1 / 陷阱 1 同一坑,只是从一个"思考题"变成了你亲手抓到的 8 倍吞吐差距。排障口诀:**长肥管道窗口撑不开 → 先查 `rmem_max`/`wmem_max`(硬顶)→ 再查 `tcp_rmem`/`tcp_wmem` 的 max(软顶)→ 再查 `tcp_window_scaling` 是否开**。三者必须同时对齐 BDP(带宽×延迟),少一个都喂不饱链路。这条把第 15 章那张"天花板联动"表从知识变成了肌肉记忆。

---

## 实战补遗一：`net.core.somaxconn` + `tcp_max_syn_backlog`——突发流量下,新连接被"静默丢弃"

墨:秒杀、抢票、开服那一刻,你的监控图上 QPS 没到上限,CPU 也闲,但客户端就是一大片 `connection timed out` / `connection reset by peer`,偶发、难复现。你第一反应去查什么?

你:八成先查客户端网络、查 Nginx、查 DNS,或者把客户端超时调大——因为服务端"看起来好好的"。

墨:这就是坑。服务端"看起来好"是因为**问题不在处理能力,在"排队队列"满了之后内核直接把新连接扔了**,而你监控的根本没看那个队列。这两个参数就是队列的天花板:`net.core.somaxconn` 和 `net.ipv4.tcp_max_syn_backlog`。

### 先搞清两条队

- **accept 队列(全连接队列):**三次握手完成、等应用 `accept()` 取走的连接。长度上限 = `min(应用 listen 的 backlog 参数, net.core.somaxconn)`。默认值在很多发行版是 **128**——对现代高并发服务来说等于纸糊。
- **SYN 队列(半连接队列):**收到 SYN、还没完成三次握手的。长度上限 = `net.ipv4.tcp_max_syn_backlog`(默认 1024/2048)。

Go 的 `net/http` 默认 `listen` 时如果系统支持 `SOMAXCONN` 就用它,但**你的 `somaxconn` 本身才 128**,所以应用怎么写都白搭——天花板在 sysctl。

### 现象:开服 30 秒的"玄学超时"

某游戏开服,瞬间涌入 5 万连接。客户端侧:约 8% 的 `connect` 报 `connection timed out`(等了 1s 重试才成),少量 `reset by peer`。服务端侧:CPU 30%、带宽 20%、`ss -lnt` 看监听端口 `Recv-Q` 一直顶在 128。

### 推断(可能推错):先去调客户端

第一推断:「客户端超时太短 / 重试策略烂。」——于是让客户端把 `connect timeout` 从 1s 调到 3s,重试 3 次。结果超时率只降了一点点,因为**真正被丢的连接重试也未必中**。

第二推断:「Nginx `worker_connections` 不够。」——调大 Nginx,但流量根本没到 Nginx 层就被内核丢了,改它没用。

两个都推错,因为没看 `Recv-Q` 和 `netstat -s`。

### 真相:队列满了,内核二选一

当 accept 队列满:

- 若 `net.ipv4.tcp_abort_on_overflow=0`(默认):内核**静默丢弃**第三次握手的 ACK,客户端以为握手还在进行、继续等重传,表现为 `connection timed out`——最阴险,因为服务端日志干干净净;
- 若 `=1`:内核直接回 `RST`,客户端立刻 `reset by peer`——虽然难看,但至少失败得快。

`netstat -s` 里这两个计数器会涨:`listen queue errors`(accept 队列溢出) 和 `TCPBacklogDrop`(SYN 队列丢)。**这才是真证据**,比看 CPU 有用一百倍。

### 调整:抬天花板 + 看队列

- `net.core.somaxconn=65535`(全连接队列上限);
- `net.ipv4.tcp_max_syn_backlog=65535`(半连接队列上限);
- `net.core.netdev_max_backlog=65535`(软中断收包队列,防高速网卡丢包);
- 应用侧:确认 `listen` 的 backlog 用了大值(Go 服务可显式用 `net.ListenConfig` + 调大,或干脆依赖 `somaxconn` 足够大);**更根本的**是让 `accept()` 消费速度跟得上——队列只是缓冲,不是解决方案;
- `tcp_abort_on_overflow` 保持 0(对客户端更友好,失败慢但能重试),除非你明确要快速失败。

### 再观察:复现对比

同样开服压测:`Recv-Q` 不再顶满,`netstat -s` 的 `listen queue errors` 不再增长,客户端超时率从 8% 降到 0.1% 以内,且那 0.1% 是真实后端慢而非队列丢。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `somaxconn` 65535 | 每监听 socket 多占内核内存 | 突发连接不被静默丢 |
| `tcp_max_syn_backlog` 65535 | 半连接态多占内存 | SYN 洪峰不丢新客 |
| 队列只是缓冲 | 不治本 | 应用 `accept` 慢仍会满 |

🔧 思考题:把 `somaxconn` 设成 100 万,是不是就再也不丢连接了?

<details>
<summary>【参考答案】</summary>

不是,而且有两大副作用。第一,**队列只是缓冲,不是处理能力**:`accept` 消费慢,队列再大也只是把"客户端等得更久"推迟,不会减少真正建不成的连接,反而掩盖了应用瓶颈。第二,**每个排队连接都占内核内存**,100 万队列在连接洪峰时能把内核内存吃爆,引发新一轮 OOM。正确做法是:抬到"能扛住正常突发"的量级(几万足够),同时让应用 `accept` 并发跟上、`listen` 多实例分摊,而不是无脑堆队列。
</details>

---

## 实战补遗二：`nf_conntrack_max` 耗尽,新连接被静默 DROP——你调的 `sysctl` 不在这个家族

墨:你网关并发一高,新连接偶发建不上,`dmesg` 刷 `nf_conntrack: table full, dropping packet`。你去 `net.ipv4.tcp_*` 里翻 `tcp_max_*` 想调大,翻半天没用。我说:你找错门了。

你:连接表不就是网络参数吗?怎么不在 `net.ipv4.tcp`?

墨:连接跟踪(conntrack)是 **`net.netfilter.nf_conntrack_*`** 家族,不是 `tcp` 家族。`tcp_max_*` 管的是 TCP 协议本身的队列,conntrack 是 Netfilter(防火墙/NAT)维护的"连接状态表"——两者都管"连接",但是**两扇不同的门**。这正好呼应第 17 章"sysctl 也要找对门"。

### 现象:高并发下新连接被静默丢

某 NAT/网关并发连接 30 万,`nf_conntrack_max` 默认 65536。并发一高,`dmesg` 刷 `nf_conntrack: table full, dropping packet`,新连接建不上(客户端 `timeout`/`reset`),但 `ss -lnt` 队列没满、`tcp_max_syn_backlog` 也没满——现象和第 15 章 somaxconn 满很像,根因却不同门。

### 推断(可能推错):先去调 tcp 队列

第一推断:「`tcp_max_syn_backlog` 不够。」——调大,无效(因为丢在 conntrack 表,不是 SYN 队列)。推错,因为没看 `dmesg` 那行 `nf_conntrack`。

### 真相:conntrack 表是独立上限

`nf_conntrack_max` 限制 Netfilter 同时跟踪的连接数(所有状态:ESTABLISHED/TIME_WAIT 等)。表满后,**新数据包被 DROP**(静默,客户端只看到超时)。它和 `tcp_max_syn_backlog`(半连接队列)是两套独立计数:
- `tcp_max_syn_backlog` 满 → SYN 队列丢(第 15 章 somaxconn 相关);
- `nf_conntrack_max` 满 → 跟踪表丢(防火墙层)。

很多服务没意识到自己走了 conntrack(只要过 `iptables`/`nftables` 的 NAT 或状态规则就走)。

### 调整:调对门 + 减小跟踪负担

- `net.netfilter.nf_conntrack_max=1000000`(或按并发定)——调对家族;
- `net.netfilter.nf_conntrack_tcp_timeout_established` 调小(默认 5 天,太长让 TIME_WAIT/ESTAB 占表),让空闲连接早释放;
- 若不需要连接跟踪(纯转发/无 NAT):用 `NOTRACK` 或 `ct` 豁免,彻底不占表;
- 监控 `cat /proc/sys/net/netfilter/nf_conntrack_count` 接近 `nf_conntrack_max` 即告警;
- 验证:`dmesg | grep conntrack` 不刷、新连接建得上。

### 再观察

`nf_conntrack_max` 调到 100 万 + established 超时调 1 天后,`dmesg` 不再刷,新连接建得上。

### 改进(权衡:拿什么换什么)

| 动作 | 拿什么 | 换什么 |
|---|---|---|
| `nf_conntrack_max` 调大 | 内核内存(每连接状态约 300B) | 高并发不丢新连 |
| established 超时调小 | 长闲连接早释 | 表不堆积 |
| NOTRACK 豁免 | 改防火墙规则 | 不占表 |

🔧 思考题:为什么"纯转发网关"也可能走 conntrack,明明它不关心连接状态?

<details>
<summary>【参考答案】</summary>

因为 conntrack 不是"你关心才走",是**数据包过了 Netfilter 的状态规则就自动跟踪**。只要你的 `iptables`/`nftables` 里有 `-m state`/`ct state` 或 NAT(`-t nat`)规则,哪怕只是默认的 `INPUT` 链 `RELATED,ESTABLISHED` 放行,内核就会为经过的包建 conntrack 表项。纯 L3 转发若规则里不含状态匹配,可 `NOTRACK` 豁免;但只要有一条状态规则,所有相关流都进表。所以"网关不关心状态"不等于"不走 conntrack"——这也是为什么高并发网关常在 conntrack 满而 `tcp_*` 都没满:两扇门,你只看了一扇。呼应第 17 章:sysctl 调参第一步永远是"确认参数在哪个家族、守哪扇门",找错门调一周也是白调(第 17 章实战事故二正是这个教训)。
</details>

---

## 实战补遗三：两个队列都满了,连接却"静默消失"

墨:前面讲了 `somaxconn` 是 accept 队列。那 SYN 队列呢?它归谁管?

你:是不是 `net.ipv4.tcp_max_syn_backlog`?

墨:对,但它俩不是平行的两道门,而是**串联的两道门**。三次握手的链路是:客户端发 SYN → 进 SYN 队列(`tcp_max_syn_backlog` 控长)→ 内核回 SYN+ACK → 客户端回 ACK → 连接从 SYN 队列移到 accept 队列(`somaxconn` 控长)→ 应用 `accept()` 取走。这两道门任何一道满了,连接都会出问题,但**表现完全不同**。

**真实事故**:一个 Go 写的 API 网关,流量一上峰值,客户端大量报 `connection timeout`,但服务端 `ss -lnt` 看监听端口 `Recv-Q` 不算满,应用也没报错,`dmesg` 干干净净。最诡异的是:两侧都"看不出问题",可连接就是建不起来。

推断可能推错的方向:第一反应以为是应用 `accept()` 太慢——但 `Recv-Q` 没满,排除。第二反应是防火墙丢包——但同机 `telnet 127.0.0.1` 也偶发超时,排除网络层。第三反应才想到:SYN 队列满。

怎么验证?`netstat -s | grep -i listen` 看 `times the listen queue of a socket overflowed` 和 `SYNs to listened sockets ignored` 两个计数。结果发现 `SYNs ... ignored` 在涨——说明 SYN 队列溢出,内核**直接丢弃 SYN**,客户端收不到 SYN+ACK,只能重传,表现出来就是 `connection timeout`,而服务端日志毫无痕迹(因为连接根本没进到应用层)。

根因:这个网关开了 `tcp_tw_recycle`(老内核的坑,新内核已删)且客户端在 NAT 后,导致部分 SYN 被 Timestamps 判断为"旧连接"直接丢弃;叠加 `tcp_max_syn_backlog` 默认才 1024,峰值瞬间被打满。

调整:删掉 `tcp_tw_recycle`(它和 NAT 客户端的 PAWS 判断冲突,是著名巨坑)、把 `tcp_max_syn_backlog` 提到 8192、`somaxconn` 提到 65535,并确认应用 `listen()` 的 backlog 参数也给了大值(否则内核 `somaxconn` 再大,应用自己的 backlog 小也是白搭)。再观察:`SYNs ... ignored` 计数不再增长,超时告警消失。

你:那为什么不用 `tcp_abort_on_overflow=1` 让满了直接回 RST?

墨:那是个"把问题变明显"的开关,不是"解决问题"的开关。开了之后队列溢出时内核回 `RST`,客户端立刻拿到 `connection reset`,你能在应用层日志看到——这方便你**发现**问题,但连接一样建不成。它适合用在"我想让故障暴露出来"的排查期,不适合当长期方案。长期方案永远是把队列容量调到匹配真实并发,而不是靠 RST 把溢出显性化。

🔧 思考题:`tcp_max_syn_backlog` 和 `somaxconn` 哪个更容易被忽略?为什么很多人只调了一个、另一个还是默认值就上线了?

<details>
<summary>【参考答案】</summary>

`somaxconn` 更容易被忽略,因为它有两层:内核 `net.core.somaxconn` 是上限,但应用 `listen(fd, backlog)` 里传的 `backlog` 是"请求值",内核取 `min(应用backlog, somaxconn)`。很多人改了 sysctl 却忘了把应用代码里的 `backlog` 调大(Go 的 `net.Listen` 默认 backlog 受 `somaxconn` 限制但部分框架写死 128),等于白改。

而 `tcp_max_syn_backlog` 是纯内核参数,`sysctl -w` 即生效、应用无感知,反而容易被当成"万能药"单独调。真实生产两个都要查:先 `ss -lnt` 看 `Recv-Q`(accept 队列占用)和 `netstat -s` 的 overflow/ignored 计数分别涨不涨,哪个涨调哪个,别盲目两个一起拍大——队列太大也会拖慢 SYN 洪泛攻击下的防御。
</details>

---

## 实战补遗四：rp_filter 反向路径过滤——"能 ping 通却建不了连接"的幽灵

墨:`net.ipv4.conf.all.rp_filter` 默认是 1(严格反向路径过滤)。它干嘛的?为什么有时候它会**悄悄丢包**,让你查到怀疑人生?

你:防 IP 欺骗吧?检查"从哪进来的包,回程路由是不是也从这出",不一致就丢?

墨:对。RFC 3704 的 uRPF:`rp_filter=1`(strict)时,内核对每个进来的包做一件事——"这个包的源 IP,从我收到它的网卡出去,路由能不能通?能通才收,不通就丢"。本意是防伪造源 IP 的 DDoS。但它在**非对称路由 / 多网卡 / 策略路由**环境里会变成"合法包也被丢"的幽灵。

**真实事故**:一台双网卡服务器(eth0 内网、eth1 外网),从外网某客户发起 TCP 连接,`ping` 通(ICMP 正常回),但 TCP 三次握手偶尔失败,业务表现"连接时好时坏"。服务端 `tcpdump` 看:SYN 收到了、也回了 SYN+ACK,但客户端说"没收到你的 SYN+ACK"。

推断:ICMP 能通但 TCP 不行,说明不是链路断,是**特定包的回程路径被判非法**。查 `rp_filter`:`cat /proc/sys/net/ipv4/conf/eth1/rp_filter` = 1。再看路由:`ip route get <客户端IP>` 回程走的是 eth0(因为默认路由/策略路由把回程指到内网),而包是从 eth1 进来的——strict 模式一看"源 IP 的回程不走 eth1",`DROP`。ICMP 为什么没事?因为当时 `ping` 测试走的是对称路径(恰好回程也 eth1),而真实业务 TCP 的源 IP 段走了非对称路由。

调整:① 临时:`sysctl -w net.ipv4.conf.all.rp_filter=2`(`rp_filter=2` 是 loose 模式——只要求"源 IP 全局可达",不要求"从收包网卡回程",非对称路由下不丢合法包);或针对该网卡 `net.ipv4.conf.eth1.rp_filter=0`(关,适合确定无 spoofing 风险的内网网卡);② 根本:理清路由,让回程路径对称,或上策略路由让 uRPF 判据成立。再观察:TCP 握手不再失败,连接稳定。

你:`rp_filter=2`(loose)不是形同虚设吗?防 spoofing 还防个啥?

墨:loose 防的是"源 IP 根本不可达"的明显伪造(比如一个公网包源 IP 是 127.0.0.1 或私有段),但不防"源 IP 可达但路径不对称"的复杂 spoofing。所以:
- 边界/公网入口:`rp_filter=1`(strict)仍推荐,防 spoofing 价值大,且公网路径通常对称;
- 内网/双网卡/多宿主/任何非对称路由环境:`rp_filter=2`(loose)或按网卡单独设 `0`,否则必踩幽灵丢包。

这条和第 15 章另一节(`tcp_max_syn_backlog` 静默丢 SYN)是**一对"静默丢包"案例**:都是"服务端没日志、客户端超时、ping 却通"的诡异表现,根因一个是队列满、一个是 rp_filter。排查口诀一致:**凡是"能 ping 通却建不了连接",先查两个静默丢包源——SYN 队列(`netstat -s` 的 ignored)和 rp_filter(`cat` 一下各网卡值)**,别上来就怀疑应用。

🔧 思考题:容器里 `rp_filter` 怎么生效?pod 里 `ping` 通宿主但访问不通,会不会是 rp_filter 在作怪?

<details>
<summary>【参考答案】</summary>

容器网络通常走 `veth`+网桥或 `ipvlan`/`macvlan`,包的进出路径和宿主物理网卡不同。`rp_filter` 在**宿主的每个物理/虚拟网卡接口上独立判断**(注意是 `conf/<dev>/rp_filter`,不是只有 `conf/all/`),而容器流量往往经过 `veth`、`cni0` 网桥等多层虚拟设备,回程路由极易"非对称"——于是宿主某虚拟网卡的 strict `rp_filter` 可能把合法的容器回包判非法丢弃。

所以 K8s 节点上常见做法:把 `net.ipv4.conf.all.rp_filter=2`(loose)或把 `cni0`/`veth` 相关网卡的 `rp_filter` 设 0/2,避免虚拟网络路径被判非法。pod 内自己改 `rp_filter` 没用(作用域是宿主接口,且多数 pod 无 `CAP_NET_ADMIN`)。排查"pod 能 ping 宿主但连不上":先看宿主 `ip route get <pod源IP>` 回程走哪、再 `cat` 对应宿主网卡的 `rp_filter`,很可能就是 strict 模式在虚拟网络里误杀。云厂商的 CNI 通常已帮你设好 loose,自己手搭网络才容易踩。
</details>

---

## 实战补遗五：tcp_abort_on_overflow 的"告警价值"——把静默丢变成显性报错

墨:第 15 章讲了两道队列(SYN 队列 `tcp_max_syn_backlog`、accept 队列 `somaxconn`),溢出时内核**静默丢包**,客户端超时但服务端无日志。那时提了一句 `tcp_abort_on_overflow` 是"把问题变明显"的开关。展开讲。

你:开了它,队列溢出时内核回 RST,客户端立刻 `connection reset`,应用层能看见——所以排查期该开?

墨:对,它本质是**可观测性开关,不是解决方案**。讲个真实用法。

一个网关,客户端偶发 `connection timeout`,服务端 `netstat -s` 的 `overflowed` 在涨(accept 队列溢出),但 SRE 一开始没盯这个计数,在应用层日志里找了半天"为什么没收到连接",当然找不到(连接根本没进应用层)。后来开了 `tcp_abort_on_overflow=1` 做排查:

- 队列溢出时,内核不再静默丢 SYN/ACK,而是对超出的连接回 **RST**;
- 客户端立刻拿到 `connection reset by peer`(而非磨蹭 30 秒 timeout),**应用层日志瞬间出现大量 reset 报错**;
- SRE 一眼定位:"reset 集中在 accept 队列溢出时段" → 确认是 `somaxconn`(应用 `listen` backlog)太小 + 应用 `accept()` 消费慢。

推断:静默丢包时,故障"看不见"(客户端超时、服务端无痕);开 `tcp_abort_on_overflow` 后,故障"显性化"(服务端虽不直接报错,但客户端 reset 让全链路日志串联起来)。这开关的价值是**把隐形故障变成可追踪的显性信号**,加速定位。

调整(关键:这是临时排查手段,不是长期方案):① 排查期开 `tcp_abort_on_overflow=1`,快速定位 accept 队列溢出;② 定位后**根本解决**:调大应用 `listen` 的 backlog(配合 `somaxconn`)、优化 `accept()` 消费速度(别在 `accept` 后做重活);③ 查清根因、队列不再溢出后,**把 `tcp_abort_on_overflow` 改回 0**(长期开着会让正常流量高峰时也 RST,白白丢连接)。

你:那 RST 和"静默丢"对客户端体验,哪个更糟?

墨:看你是"想定位"还是"想服务":
- **长期生产**:静默丢(overflow=0)对客户体验**略好**——客户端会按 TCP 重传/超时重试,可能最终连上(若队列很快腾出);RST 则直接断,客户端必失败一次。所以稳定后关掉它,让 TCP 自己重试,连接成功率更高;
- **排查期**:RST(overflow=1)对**运维体验**好——故障显性、可追踪、定位快。代价是排查期间少量连接被 RST(可接受,因为本来就在溢出丢)。

所以这是"**运维可观测性 vs 客户端连接成功率**"的权衡:平时 0(保连接成功率),排查时 1(保故障可见)。别长期开 1——很多人"为了能看到错误"一直开着,结果正常流量高峰也 RST,反而制造新故障。

🔧 思考题:`tcp_abort_on_overflow` 和 `tcp_tw_reuse`(TIME_WAIT 复用)都是"连接相关的开关",它们各自解决什么?为什么 `tcp_tw_recycle` 被删而 `tcp_tw_reuse` 还在?

<details>
<summary>【参考答案】</summary>

两个完全不同:
- `tcp_abort_on_overflow`:解决"accept 队列溢出时故障不可见",是**可观测性开关**(上题详述);
- `tcp_tw_reuse`:解决"主动关闭方大量 `TIME_WAIT` 占满端口",让新连接**安全复用**处于 TIME_WAIT 的本地端口(只对**出站**连接、且基于时间戳 PAWS 判断安全才复用)。它缓解"端口耗尽"类问题(如高并发短连接客户端)。

`tcp_tw_recycle` 被删(4.12+ 内核):它和 `tcp_tw_reuse` 类似但**更激进**——对**入站**连接也试图快速回收 TIME_WAIT,且依赖**对端时间戳**判断。问题:客户端在 **NAT 后**(多个客户端共享一个公网 IP、但各自时间戳不同)时,服务端收到"同一 IP 不同时间戳"的包,PAWS 判定"旧包"直接丢——**导致 NAT 后客户端大量连接失败**(第 15 章 B8 的 SYN 队列事故里提过这坑)。所以 `recycle` 因 NAT 不友好被彻底删除,只留 `tw_reuse`(它只对出站、且更保守,不踩 NAT 坑)。

口诀:高并发客户端(主动关闭多)端口不够 → 开 `tcp_tw_reuse`(安全);**永远别碰 `tcp_tw_recycle`(已删,且当年是 NAT 连接失败的著名元凶)**;accept 队列溢出排查 → 临时 `tcp_abort_on_overflow=1`(定位后关)。三者作用域和年代不同,NAT 环境尤其躲 `recycle`。
</details>

---

---

## 实战补遗六：tcp_tw_reuse 与 TIME_WAIT 洪水——高并发短连接怎么不被端口耗尽卡死

墨：老哥，你有没有过"客户端报无法建立连接，ss 一看全是 TIME_WAIT，几万条"？

你：有，网上说开 `tcp_tw_reuse` 就好了。

墨："开 tw_reuse 就好"是半句真理，开错地方、理解错机制，反而埋新雷。这节把 TIME_WAIT 和那两个参数讲透。

现象：一个用短连接（每次请求新建 TCP）的压测客户端，单机 1 分钟打出 5 万连接，之后新连接大量失败，`ss -tan | grep TIME_WAIT | wc -l` 显示 4 万条 TIME_WAIT 占着本地端口，可用端口（`ip_local_port_range` 默认 3 万）被吃光。

推断：TIME_WAIT 太多，端口不够用。

可能推错：第一，TIME_WAIT 是**主动关闭方**才有的状态（谁先 `close` 谁进 TIME_WAIT）。客户端是主动关闭方，所以客户端的端口被自己的 TIME_WAIT 占住——这不是服务端问题，是**客户端**要处理。第二，直接 `tcp_tw_reuse` 只对**客户端（出站）**生效，且依赖时间戳（`tcp_timestamps=1`），对服务端入站的 TIME_WAIT 无效。第三，千万别开 `tcp_tw_recycle`——它在新内核已删除，且会在 NAT 下因为对端时间戳乱序直接丢包（经典"一过 NAT 就抽风"）。

调整：先确认角色。客户端端口耗尽，正确解法优先级：
1. **用长连接/连接池**：根本不该每条请求新建 TCP。Go 的 `http.Transport` 默认复用连接（`MaxIdleConnsPerHost`），压测客户端没配好才会短连接。这是治本。
2. 扩 `ip_local_port_range`：`sysctl -w net.ipv4.ip_local_port_range="1024 65535"`，可用端口从 3 万扩到 6 万。
3. 开 `tcp_tw_reuse=1`（仅客户端、需 `tcp_timestamps=1`）：允许**复用**处于 TIME_WAIT 的本地 socket 发起新连接，安全（靠时间戳区分新旧报文，不会串包）。
4. 调 `tcp_max_tw_buckets`：限制全局 TIME_WAIT 数量上限，超额直接回收最老的，避免耗尽内存（但设太小会误杀正常连接）。

再观察：服务端侧的 TIME_WAIT 是"服务被动关闭"才产生（客户端先 close，服务端进 TIME_WAIT）——服务端通常不缺端口（监听端口固定，四元组里客户端 IP:端口多变），所以服务端一般**不需要** tw_reuse。乱开反而可能在某些中间件场景出问题。

改进：
- 短连接压测/客户端：连接池优先；不行再 `tw_reuse=1` + 扩 `ip_local_port_range`。
- **绝不开 `tcp_tw_recycle`**（已废弃且 NAT 致命）。
- `tcp_fin_timeout` 调小（如 30s）让 FIN_WAIT_2 快点回收，但 TIME_WAIT 的 2*MSL 不由它管（`tcp_tw_reuse` 才是 TIME_WAIT 的解法）。
- 监控 `ss -tan | wc -l` 按状态分桶，定位到底是 TIME_WAIT 还是 SYN_RECV 洪水。

🔧 思考题：为什么 TIME_WAIT 必须等 2*MSL（最长报文寿命）才能关？如果强行"快速回收"TIME_WAIT，最坏会出什么网络层的乱子？

<details>
<summary>【参考答案】</summary>

TIME_WAIT 等 2*MSL 有两个目的：
1. **保证最后那个 ACK 可靠到达**：被动关闭方若没收到主动方的 ACK，会重发 FIN；主动方必须在 TIME_WAIT 里待着才能回这个 ACK。如果主动方发完 ACK 立马关，被动方重发的 FIN 就没人理，被动方永远卡在 LAST_ACK。
2. **让网络中滞留的旧报文过期**：同一四元组（源IP:端口-目的IP:端口）的旧报文可能在网络里游荡 MSL 才消失。如果主动方立刻用同一四元组建新连接，滞留的旧报文可能被新连接误收，造成数据错乱。等 2*MSL（两端各 MSL）确保旧报文彻底清场。

所以"强行快速回收 TIME_WAIT"的代价：旧连接滞留报文串进新连接（数据污染），或被动方 FIN 重传无人响应导致对端资源泄漏。`tcp_tw_reuse` 之所以安全，是它**不跳过等待**，而是利用 `tcp_timestamps` 的时间戳：新连接带着更大的 TS 值，内核能区分"这是新连接的报文还是旧连接的滞留报文"，从而放心复用该四元组——本质是"用时间戳解决了 2*MSL 要防的第二个问题"，所以可提前复用而不串包。`tcp_tw_recycle` 更激进（直接按对端 IP 的时间戳回收），但在 NAT 后多个客户端共享同一出口 IP、各自时间戳不同步，服务端会认为"时间戳倒退"而丢弃它们的包——这就是 NAT 下 `tw_recycle` 致病的根因，已在新内核移除。结论：客户端用 `tw_reuse`，服务端靠连接池，别碰 `tw_recycle`。
</details>

下一章预告

墨:`net` 家族这一章,把第 10 章的 `tcp_*` 嵌回了"core→ipv4→ipv6→bridge"的分层地图,你终于知道每个参数在管协议栈的哪一段。`net` 是 `sysctl` 里最大、最常被"抄错"的家族——因为条目多、分层乱。

下一章(第 16 章)我们转去 **`fs` 与 `kernel` 家族**:`fs.file-max`(第 04 章见过的"全系统打开文件数上限")、`fs.inode-*`(inode 缓存)、`kernel.pid_max`(进程号上限,容器密度高了会撞)、`kernel.threads-max`、`kernel.sem`(System V 信号量,老数据库爱踩)、`kernel.panic`/`kernel.softlockup_panic`(第 05 章 watchdog 的开关)、`kernel.msgmnb` 等。同样:每个讲清守哪道门、拿什么换什么。

---

*本章完。fs 与 kernel 家族见第 16 章。*
