# 01 · 容器原理：namespace、cgroup 与手写运行时

> *"容器不是'轻量级虚拟机'。它根本没有第二层内核。"*

---

## 开场：一次误判

> **小林**：我把服务从虚拟机迁到容器，内存限制设成 2GB。结果容器频繁被 OOM Kill，但监控显示内存只用了 1.2GB。
>
> **老陈**：**你觉得矛盾在哪？**
>
> **小林**：……限制是 2GB，用了 1.2GB，不该 OOM 啊。
>
> **老陈**：**你监控的"1.2GB"是什么？**
>
> **小林**：Go 的 `runtime.MemStats.HeapAlloc`。
>
> **老陈**：**问题就在这。** 我问你：`HeapAlloc` 包含哪些内存？
>
> **小林**：……堆上的对象？
>
> **老陈**：**那这些呢？**
> - goroutine 的栈
> - 堆的元数据（span、bitmap）
> - GC 的工作缓冲区
> - mmap 分配的内存（比如 cgo）
> - 文件页缓存（page cache）
> - 二进制本身的代码段
>
> **小林**：……这些不算吗？
>
> **老陈**：**cgroup 算。Go 的 HeapAlloc 不算。**
>
> **小林**：所以实际用了 2GB+，但监控只显示 1.2GB？
>
> **老陈**：**对。这是容器环境下最常见的"监控盲区"。** 我们从头讲容器。

---

## 第一部分：容器 vs 虚拟机

### 架构对比

```
传统虚拟化（VM）:
┌─────────┬─────────┐
│  App A  │  App B  │
├─────────┼─────────┤
│ GuestOS │ GuestOS │   ← ★ 每个 VM 一个完整的操作系统内核
├─────────┼─────────┤
│  Hypervisor (KVM / Xen)                    │
├────────────────────────────────────────────┤
│  Host OS + 硬件                             │
└────────────────────────────────────────────┘

容器:
┌─────────┬─────────┐
│  App A  │  App B  │
├─────────┼─────────┤
│ 容器运行时 (containerd / runc)              │
├────────────────────────────────────────────┤
│  Host OS + 硬件                             │   ← ★ 共享同一个内核
└────────────────────────────────────────────┘
```

**关键差异：**

| | VM | 容器 |
|:---|:---|:---|
| **隔离层** | Hypervisor（硬件级） | **内核特性**（namespace/cgroup） |
| **内核** | 每个 VM 一个 | **共享宿主机内核** |
| **启动时间** | 几十秒到几分钟 | **毫秒到秒** |
| **内存开销** | 每个 VM 几百 MB（内核+系统进程） | **只有应用本身** |
| **隔离强度** | 强（硬件级） | **弱**（共享内核，攻击面大） |
| **可运行不同 OS** | ✅ 可以 | ❌ 只能跑同内核的 OS |

> **老陈**：**"容器比虚拟机轻"的真正原因：**
> - VM 要跑一个完整的 GuestOS 内核（几十 MB 内存 + 启动时的初始化）
> - 容器只是宿主机上的一个进程，**用内核特性做了隔离和限制**
>
> **代价是隔离不彻底。** 一个内核漏洞可能影响所有容器（这是容器安全的核心问题）。
>
> **所以 gVisor、Kata Containers 这类"安全容器"出现了——它们用不同的方式补强隔离：**
> - **gVisor**：在用户态实现一个"内核替身"（Sentry），拦截系统调用
> - **Kata**：每个容器跑在一个轻量级 VM 里（VM 的隔离 + 容器的体验）

---

## 第二部分：namespace —— 隔离"看到什么"

### 八种 namespace

| namespace | 隔离什么 | 效果 |
|:---|:---|:---|
| **Mount (mnt)** | 挂载点 | 容器里有自己的 `/`，看不到宿主机的文件系统 |
| **PID** | 进程号 | 容器内 PID 1 是自己的 init，看不到宿主机进程 |
| **Network (net)** | 网络栈 | 独立的网卡、IP、路由表、端口空间 |
| **UTS** | 主机名 | 容器可以有自己的 hostname |
| **IPC** | 进程间通信 | 独立的 System V IPC、消息队列 |
| **User** | 用户/组 ID | 容器内的 root 不等于宿主机的 root ★ |
| **Cgroup** | cgroup 视图 | 容器内看到的 cgroup 树是虚拟的 |
| **Time** | 系统时间 | 容器可以有独立的时间（较新，Linux 5.6+） |

### 关键 API：unshare 和 clone

```c
#include <sched.h>

// 方式 1: 在当前进程上"脱离"某些 namespace
int unshare(int flags);

// 方式 2: 创建新进程时指定 namespace
int clone(int (*fn)(void*), void* stack, int flags, void* arg);

// flags:
//   CLONE_NEWNS    mount namespace
//   CLONE_NEWPID   PID namespace
//   CLONE_NEWNET   network namespace
//   CLONE_NEWUTS   UTS namespace
//   CLONE_NEWIPC   IPC namespace
//   CLONE_NEWUSER  user namespace
//   CLONE_NEWCGROUP cgroup namespace
```

### User namespace：容器安全的基石

**这是最重要的一个 namespace，但很多人不了解。**

```
传统容器（无 user namespace）:
  容器内的 root (uid=0)
      ↓
  宿主机上的 uid=0
  ★ 如果容器逃逸，攻击者直接拿到宿主机 root！

有 user namespace:
  容器内的 root (uid=0)
      ↓ 映射
  宿主机上的 uid=100000（普通用户）
  ★ 即使逃逸，攻击者也只是个普通用户
```

**映射文件：**

```bash
cat /proc/<pid>/uid_map
#          容器内      宿主机      长度
#          0           100000      65536
# 含义：容器内的 uid 0-65535 映射到宿主机的 uid 100000-165535
```

> **老陈**：**Docker 默认不开启 user namespace**（因为兼容性问题多）。但 **rootless 容器**（Podman、Docker rootless 模式）依赖它。
>
> **如果你的容器以 root 运行，且没有 user namespace，那么容器内的 root 就是宿主机的 root。** 这是容器安全最重要的一条。

---

## 第三部分：cgroup —— 限制"能用多少"

### cgroup v1 vs v2

| | v1 | v2 |
|:---|:---|:---|
| **结构** | 每个资源一个独立的层级树 | **统一的层级树** |
| **文件位置** | `/sys/fs/cgroup/<controller>/` | `/sys/fs/cgroup/` |
| **内存控制** | `memory.limit_in_bytes` | `memory.max` |
| **OOM 控制** | `memory.oom_control` | `memory.events` |
| **swap** | `memory.memsw.limit_in_bytes` | `memory.swap.max` |
| **IO 控制** | blkio 控制器 | **io 控制器**（更准确） |
| **状态** | 已废弃 | **推荐，K8s 1.25+ 默认** |

### cgroup v1 的内存相关文件

```bash
/sys/fs/cgroup/memory/docker/<container-id>/

memory.limit_in_bytes         # 内存上限
memory.usage_in_bytes         # 当前使用量 ★
memory.max_usage_in_bytes     # 历史峰值
memory.failcnt                # 达到限制的次数
memory.stat                   # 详细统计 ★
memory.oom_control            # OOM 控制
memory.kmem.usage_in_bytes    # 内核内存
memory.memsw.usage_in_bytes   # 内存 + swap
```

**★ `memory.stat` 是最重要的文件**（比 `usage_in_bytes` 详细得多）：

```bash
cat /sys/fs/cgroup/memory/memory.stat

cache 1234567              # page cache（文件缓存）★
rss 567890123              # 匿名内存（堆、栈）★
rss_huge 0
mapped_file 123456         # mmap 的文件
dirty 4096                 # 脏页
writeback 0
pgpgin 123456
pgpgout 100000
pgfault 234567
pgmajfault 123             # ★ major fault（要读磁盘）次数
inactive_anon 12345678
active_anon 45678901       # ★ 活跃的匿名页
inactive_file 12345678
active_file 4567890
unevictable 0
total_cache 1234567
total_rss 567890123
...
```

### 回答开场的问题：为什么 1.2GB 会 OOM

**cgroup 统计的内存 = RSS + Page Cache + 内核内存 + ...**

而 Go 的 `HeapAlloc` 只是其中的一部分：

```
cgroup 看到的内存（容器总占用）:
┌────────────────────────────────────────┐
│  Go heap (HeapAlloc)      1.2 GB       │ ← 你监控的
├────────────────────────────────────────┤
│  Go runtime 元数据:                     │
│    · span / bitmap                     │
│    · GC 工作缓冲                        │
│    · goroutine 栈                       │  ← 200-400 MB
├────────────────────────────────────────┤
│  未归还给 OS 的空闲 span               │  ← 可能几百 MB ★
├────────────────────────────────────────┤
│  mmap 分配（cgo、大块内存）              │
├────────────────────────────────────────┤
│  Page cache（文件读写缓存）              │  ← 可能几百 MB ★
├────────────────────────────────────────┤
│  二进制代码段 + 共享库                   │
└────────────────────────────────────────┘
  总计可能 2GB+，超过 limit → OOM Kill
```

**诊断方法：**

```bash
# 在容器里看
cat /sys/fs/cgroup/memory/memory.stat
cat /sys/fs/cgroup/memory/memory.usage_in_bytes

# 对比 Go 的视角
curl http://localhost:6060/debug/pprof/heap > heap.prof
go tool pprof -http=:8080 heap.prof
# 看 HeapAlloc / HeapSys / Sys 的差异
```

**关键指标：**

```go
var m runtime.MemStats
runtime.ReadMemStats(&m)

fmt.Printf("HeapAlloc  = %d MB\n", m.HeapAlloc>>20)   // Go 堆上的对象
fmt.Printf("HeapSys    = %d MB\n", m.HeapSys>>20)     // 从 OS 申请的堆内存
fmt.Printf("HeapIdle   = %d MB\n", m.HeapIdle>>20)    // 空闲（未归还）
fmt.Printf("HeapReleased=%d MB\n", m.HeapReleased>>20) // 已归还给 OS
fmt.Printf("Sys        = %d MB\n", m.Sys>>20)         // ★ Go 从 OS 申请的总量
fmt.Printf("StackSys   = %d MB\n", m.StackSys>>20)    // goroutine 栈
fmt.Printf("MSpanSys   = %d MB\n", m.MSpanSys>>20)    // span 元数据
fmt.Printf("OtherSys   = %d MB\n", m.OtherSys>>20)
```

**★ 最重要的：设置 Go 的内存软限制（Go 1.19+）**

```go
import "runtime/debug"

func main() {
	// 容器 limit 是 2GB，我们给 Go 设 1.6GB 软限制
	debug.SetMemoryLimit(1600 << 20)   // 1.6GB

	// ...
}
```

**原理**：
- `MemoryLimit` 是"软限制"，Go 会尽量不超过它
- 接近限制时：GC 更频繁 + scavenger 更积极地把内存还给 OS
- **效果**：Go 的实际占用会尽量贴近 `MemoryLimit`，而不是无脑涨到 limit

**这是容器环境下 Go 服务最重要的一行配置。**

### CPU 限制：CFS Bandwidth Control

```bash
/sys/fs/cgroup/cpu/docker/<id>/
cpu.cfs_period_us   # 周期，默认 100000 (100ms)
cpu.cfs_quota_us    # 每个周期内可用的 CPU 时间（微秒）

# 限制 2 核:
#   period = 100000 (100ms)
#   quota  = 200000 (200ms = 2 核 × 100ms)
```

**★ 这个机制会导致"CPU 限流"——第 1 章第 07 节讲过的延迟尖刺。**

```bash
# 看限流情况（cgroup v1）
cat /sys/fs/cgroup/cpu/cpu.stat
# nr_periods      12345      周期总数
# nr_throttled    892        ★ 被限流的周期数
# throttled_time  12345678901  被限流的总时间（纳秒）

# cgroup v2
cat /sys/fs/cgroup/cpu.stat
# nr_periods 12345
# nr_throttled 892
# throttled_usec 12345678
```

---

## 第四部分：手写容器运行时

现在我们用 Go 实现一个 mini-docker。

```go
package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"syscall"
)

// ============ 主程序 ============

func main() {
	switch os.Args[1] {
	case "run":
		run()
	case "child":
		child()
	default:
		panic("用法: ./mini-docker run <cmd>")
	}
}

func run() {
	fmt.Printf("[父进程] PID=%d, 启动容器...\n", os.Getpid())

	// ★ 关键：用 /proc/self/exe 重新执行自己
	//    并传入 namespace flags
	//    这样子进程就在新的 namespace 里了
	cmd := exec.Command("/proc/self/exe", append([]string{"child"}, os.Args[2:]...)...)

	// 设置标准输入输出
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	// ★ 创建新的 namespace
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Cloneflags: syscall.CLONE_NEWUTS |    // 主机名
			syscall.CLONE_NEWPID |             // PID
			syscall.CLONE_NEWNS |              // 挂载点
			syscall.CLONE_NEWNET |             // 网络
			syscall.CLONE_NEWIPC,              // IPC
		// 注意：CLONE_NEWUSER 需要额外处理，这里先不加
	}

	if err := cmd.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "运行失败: %v\n", err)
		os.Exit(1)
	}
}

func child() {
	fmt.Printf("[子进程] PID=%d, 在容器里\n", os.Getpid())

	cmd := os.Args[2]

	// ① 设置主机名
	must(syscall.Sethostname([]byte("mini-container")))

	// ② 切换根文件系统
	must(setupRootFS())

	// ③ 挂载 /proc（这样 ps、top 才能用）
	must(syscall.Mount("proc", "/proc", "proc", 0, ""))

	// ④ 设置 cgroup 限制
	setupCgroups()

	// ⑤ 执行命令
	must(syscall.Exec(cmd, os.Args[2:], os.Environ()))
}

// ============ 根文件系统 ============

func setupRootFS() error {
	rootfs := "/tmp/mini-container-rootfs"

	// 1. 准备一个最小的根文件系统
	//    真实容器用镜像（overlayfs），这里简化
	if err := prepareRootFS(rootfs); err != nil {
		return err
	}

	// 2. pivot_root（比 chroot 更安全）
	//    chroot 可以被突破（因为进程可能还持有旧 root 的文件描述符）
	//    pivot_root 把整个挂载命名空间切换过去

	// 先 bind mount 自己（pivot_root 的要求）
	must(syscall.Mount(rootfs, rootfs, "", syscall.MS_BIND|syscall.MS_REC, ""))

	// 创建 put_old 目录，用于存放旧的 root
	putOld := filepath.Join(rootfs, ".old_root")
	os.MkdirAll(putOld, 0700)

	// ★ pivot_root
	if err := syscall.PivotRoot(rootfs, putOld); err != nil {
		// 在某些环境下可能失败，fallback 到 chroot
		fmt.Printf("pivot_root 失败(%v)，使用 chroot\n", err)
		return syscall.Chroot(rootfs)
	}

	// 切换工作目录
	must(os.Chdir("/"))

	// 卸载旧的 root
	syscall.Unmount("/.old_root", syscall.MNT_DETACH)
	os.Remove("/.old_root")

	return nil
}

func prepareRootFS(rootfs string) error {
	// 创建目录结构
	dirs := []string{"/bin", "/proc", "/sys", "/dev", "/tmp", "/etc"}
	for _, d := range dirs {
		if err := os.MkdirAll(filepath.Join(rootfs, d), 0755); err != nil {
			return err
		}
	}

	// 复制 busybox 作为 shell
	// （真实容器会解压一个完整的镜像）
	if _, err := os.Stat("/bin/busybox"); err == nil {
		return copyFile("/bin/busybox", filepath.Join(rootfs, "/bin/busybox"))
	}
	if _, err := os.Stat("/bin/sh"); err == nil {
		return copyFile("/bin/sh", filepath.Join(rootfs, "/bin/sh"))
	}

	// 如果都没有，就创建一个 busybox 的软链接说明
	// 实际使用时需要准备 rootfs
	return fmt.Errorf("需要准备 rootfs: %s", rootfs)
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0755)
}

// ============ cgroup 限制 ============

func setupCgroups() {
	cgroupPath := "/sys/fs/cgroup/mini-container"

	// cgroup v2 的方式
	if _, err := os.Stat("/sys/fs/cgroup/cgroup.controllers"); err == nil {
		setupCgroupV2(cgroupPath)
		return
	}

	// cgroup v1 的方式
	setupCgroupV1()
}

func setupCgroupV2(path string) {
	// 1. 创建 cgroup
	if err := os.MkdirAll(path, 0755); err != nil {
		fmt.Printf("创建 cgroup 失败: %v\n", err)
		return
	}

	// 2. 启用控制器（v2 需要显式启用）
	os.WriteFile(filepath.Join(path, "cgroup.subtree_control"),
		[]byte("+cpu +memory +pids"), 0644)

	// 3. 设置内存限制：512MB
	os.WriteFile(filepath.Join(path, "memory.max"),
		[]byte(strconv.Itoa(512*1024*1024)), 0644)

	// 4. 设置 CPU 限制：0.5 核
	//    格式: "quota period"，比如 "50000 100000" = 0.5 核
	os.WriteFile(filepath.Join(path, "cpu.max"),
		[]byte("50000 100000"), 0644)

	// 5. 限制进程数
	os.WriteFile(filepath.Join(path, "pids.max"), []byte("100"), 0644)

	// 6. 把自己加入这个 cgroup
	pid := os.Getpid()
	os.WriteFile(filepath.Join(path, "cgroup.procs"),
		[]byte(strconv.Itoa(pid)), 0644)

	fmt.Printf("[cgroup v2] 已设置: 内存 512MB, CPU 0.5 核, 最多 100 个进程\n")
}

func setupCgroupV1() {
	// cgroup v1: 每个控制器一个目录
	memoryPath := "/sys/fs/cgroup/memory/mini-container"
	cpuPath := "/sys/fs/cgroup/cpu/mini-container"
	pidsPath := "/sys/fs/cgroup/pids/mini-container"

	os.MkdirAll(memoryPath, 0755)
	os.MkdirAll(cpuPath, 0755)
	os.MkdirAll(pidsPath, 0755)

	// 内存限制 512MB
	os.WriteFile(filepath.Join(memoryPath, "memory.limit_in_bytes"),
		[]byte(strconv.Itoa(512*1024*1024)), 0644)
	// 禁用 swap（避免性能抖动）
	os.WriteFile(filepath.Join(memoryPath, "memory.swappiness"),
		[]byte("0"), 0644)

	// CPU 限制 0.5 核
	os.WriteFile(filepath.Join(cpuPath, "cpu.cfs_period_us"), []byte("100000"), 0644)
	os.WriteFile(filepath.Join(cpuPath, "cpu.cfs_quota_us"), []byte("50000"), 0644)

	// 进程数限制
	os.WriteFile(filepath.Join(pidsPath, "pids.max"), []byte("100"), 0644)

	// 加入 cgroup
	pid := os.Getpid()
	os.WriteFile(filepath.Join(memoryPath, "cgroup.procs"), []byte(strconv.Itoa(pid)), 0644)
	os.WriteFile(filepath.Join(cpuPath, "cgroup.procs"), []byte(strconv.Itoa(pid)), 0644)
	os.WriteFile(filepath.Join(pidsPath, "cgroup.procs"), []byte(strconv.Itoa(pid)), 0644)

	fmt.Printf("[cgroup v1] 已设置: 内存 512MB, CPU 0.5 核\n")
}

func must(err error) {
	if err != nil {
		panic(err)
	}
}
```

**运行：**

```bash
# 需要 root 权限
sudo go run mini-docker.go run /bin/sh

# 在容器里验证
$ hostname
mini-container          ← ★ UTS namespace 生效

$ ps aux
PID   USER     COMMAND
    1 root     /bin/sh   ← ★ PID namespace 生效（PID 从 1 开始）

$ ip addr
1: lo: <LOOPBACK> ...    ← ★ Network namespace 生效（只有 lo）
```

### 关键实现点解读

**① 为什么用 `/proc/self/exe`？**

```
问题：Go 程序不能在自己内部调用 unshare 然后继续跑
     （因为 Go runtime 假设线程和进程的关系是固定的）

解法：用 /proc/self/exe 重新执行自己
     在 exec 时传入 CLONE_NEW* flags
     → 新进程从一开始就在一个"干净"的新 namespace 里
     → Go runtime 在这个环境里正常初始化

★ 这是 Docker/runc 的标准做法（runc 的 init 阶段）
```

**② 为什么用 pivot_root 而不是 chroot？**

```
chroot 的问题：
  · 只改变进程的根目录，但进程可能还持有旧 root 的文件描述符
  · 有已知的逃逸方法（比如 fchdir + chroot 组合攻击）
  · 挂载点还是共享的

pivot_root：
  · 把整个 mount namespace 的根切换过去
  · 旧的 root 被"卸载"到一个目录
  · ★ 彻底的隔离
```

**③ 为什么 Go 程序要注意 namespace？**

> **老陈**：这是 Go 特有的坑。
>
> **Go 的 runtime 会创建多个线程（M）**。如果你在 Go 程序里直接调用 `unshare(CLONE_NEWUSER)` 或 `setns`，**只有调用的那个线程会进入新 namespace**，其他线程还在旧的。
>
> **这会导致各种诡异问题**（比如权限不一致）。
>
> **正确做法**：
> 1. 用 `exec` 重新执行（像我们做的）
> 2. 或者用 cgo 在程序的"最早阶段"（runtime 起来之前）调用
>
> **这就是为什么容器运行时的 init 阶段通常用 C 写，或者用 Go 的特殊技巧。**

---

## 第五部分：容器的文件系统 —— OverlayFS

### 镜像的分层结构

```
Docker 镜像是分层的:

┌──────────────────────────────────────┐
│  Container Layer (可写)  ★ 容器自己的修改 │
├──────────────────────────────────────┤
│  Layer 3: apt install nginx           │  只读
├──────────────────────────────────────┤
│  Layer 2: COPY app /app               │  只读
├──────────────────────────────────────┤
│  Layer 1: ubuntu:22.04 base           │  只读
└──────────────────────────────────────┘
```

**OverlayFS 的合并：**

```
lowerdir (只读，多层):  /var/lib/docker/overlay2/l/XXX:layer3:layer2:layer1
upperdir (可写):        /var/lib/docker/overlay2/XXX/diff
merged (合并视图):      /var/lib/docker/overlay2/XXX/merged  ← 容器看到这个
workdir (工作目录):     /var/lib/docker/overlay2/XXX/work

挂载:
mount -t overlay overlay \
  -o lowerdir=layer3:layer2:layer1,upperdir=diff,workdir=work \
  merged
```

**写时复制（Copy-on-Write）：**

```
读取文件:  从上往下找，找到第一个就返回
          upper → layer3 → layer2 → layer1

修改文件:  ① 从 lower 层复制到 upper 层
          ② 在 upper 层修改
          ★ 原文件不变（所以多个容器可以共享基础层）

删除文件:  在 upper 层创建一个 whiteout 文件（字符设备 0,0）
          ★ 不是真的删除，而是"遮住"下层的同名文件
```

> **老陈**：**这就是 Docker 镜像"分层共享"的原理。**
>
> **10 个容器基于同一个 ubuntu 镜像，磁盘上只有一份 ubuntu。** 因为只读层是共享的。
>
> **代价：写性能下降**（第一次修改要复制整个文件，即使只改 1 字节）。
>
> **这也是为什么容器里不适合放频繁写入的大文件**（数据库数据应该用 volume，而不是容器层）。

---

## 思考题 ·【应用层】

**你的 Go 服务部署在 K8s 上，容器 limit 设的是 memory=2Gi, cpu=2。现象：**
- **Pod 每隔几小时被 OOMKilled 一次**
- **`kubectl top pod` 显示内存使用稳定在 1.3Gi**
- **但 `memory.usage_in_bytes` 在 OOM 前会突然飙升到 2Gi**

**请分析：为什么监控和实际不一致？飙升的那 0.7Gi 是什么？给出完整的诊断和解决方案。**

<details>
<summary>参考答案</summary>

### 现象的矛盾点

```
监控（kubectl top / cAdvisor）:  1.3 Gi
cgroup 实际（OOM 前）:          2.0 Gi
差值:                           0.7 Gi  ★ 这是什么？
```

**首先要知道 `kubectl top` 的数据来源：**

```
kubectl top pod
    ↓
metrics-server
    ↓
kubelet 的 cAdvisor
    ↓
读 cgroup 的 memory.usage_in_bytes 或 memory.stat

★ 理论上应该是一致的
```

**那为什么不一致？两个可能：**

**可能 1 · 采样频率问题**

```
metrics-server 默认 15-60 秒采样一次
OOM 前的内存飙升可能只持续几秒
→ 采样没抓到

★ 这是最常见的原因之一
```

**可能 2 · 统计口径不同**

```
cAdvisor 的默认计算（老版本）:
  工作集 (working_set) = usage_in_bytes - inactive_file
  
  ★ 它减去了"非活跃的文件缓存"！

而 cgroup 的 OOM 判定用的是:
  usage_in_bytes（不减去任何东西）

★ 所以：如果容器有大量 inactive_file（文件缓存），
       监控显示的数字会显著小于 OOM 判定用的数字
```

**验证：**

```bash
# 在容器里看
cat /sys/fs/cgroup/memory/memory.stat | grep -E "^(cache|rss|inactive_file|active_file)"
cat /sys/fs/cgroup/memory/memory.usage_in_bytes

# 计算：
#   usage = rss + cache
#   working_set = usage - inactive_file
```

---

### 那 0.7Gi 可能是什么

#### 可能 1：文件缓存（Page Cache）—— 最可能

```
场景：
  · 服务读取大量文件（日志、配置、数据文件）
  · 或者用了 mmap
  · 或者容器日志写到文件（stdout 重定向到文件！）

Page cache 的特点：
  · 读文件时，内核会缓存到内存
  · 这部分内存计入 cgroup 的 usage
  · ★ 但在内存压力下可以被回收（inactive 的部分）

关键：
  · inactive_file: 可以被立即回收
  · active_file:   还在被频繁访问，回收代价高

★ 如果 0.7Gi 全是 active_file（比如 mmap 的热数据），
  cgroup 不会回收它，会直接触发 OOM
```

**诊断：**

```bash
cat /sys/fs/cgroup/memory/memory.stat
# 如果 cache 很大（接近 1GB）→ 就是它

# 看进程打开了哪些文件
lsof -p <pid>

# 看 mmap
cat /proc/<pid>/maps | grep -v "\[" | head -30
```

**Go 特有的场景：日志**

```go
// ❌ 如果 stdout 重定向到文件，Go 的日志写入会产生 page cache
//    而且 K8s 的容器运行时会把 stdout 写到
//    /var/log/pods/<pod>/<container>/0.log
//    ★ 这个文件的 page cache 计入容器的 cgroup！

// 如果日志量大（比如 100MB/min），几分钟就能攒出几百 MB 的 page cache
```

**解决方案：**

1. **限制日志量**（最根本）
   ```go
   // 用 lumberjack 之类的库做日志轮转
   logger := &lumberjack.Logger{
       Filename:   "/var/log/app.log",
       MaxSize:    100,   // 每个文件最大 100MB
       MaxBackups: 3,
       MaxAge:     7,
   }
   ```

2. **降低日志级别**（生产环境不要 DEBUG）

3. **用 `O_DIRECT` 或者定期 `fadvise`**
   ```go
   // 通知内核"这个文件的缓存我不用了"
   syscall.Fadvise(int(f.Fd()), 0, 0, syscall.FADV_DONTNEED)
   ```

4. **调大容器 limit**（治标）

#### 可能 2：Go 未归还给 OS 的内存

```
Go 的堆:
  HeapSys:   从 OS 申请的总量
  HeapAlloc: 存活对象
  HeapIdle:  空闲但未归还
  HeapReleased: 已归还

★ HeapIdle - HeapReleased 这部分仍然占用 RSS！
```

**为什么会这样？**

```
Go 的 scavenger（内存回收器）策略：
  · 默认保留最近用到的内存，避免反复 mmap/munmap
  · 归还 5 分钟以上没碰过的页（Go 1.16+）
  · ★ 如果内存使用是"一次性大突发"，之后闲置，
       scavenger 需要 5 分钟才开始归还

场景：
  · 服务处理了一个大请求（比如导出 500MB 数据）
  · 处理完，对象变成垃圾
  · GC 回收了，但物理页还没还给 OS
  · ★ 此时 RSS 仍然很高
  · 如果这时候又来一个大请求 → 总内存超过 limit → OOM
```

**诊断：**

```go
var m runtime.MemStats
runtime.ReadMemStats(&m)

fmt.Printf("HeapSys      = %.2f Gi\n", float64(m.HeapSys)>>30)
fmt.Printf("HeapAlloc    = %.2f Gi\n", float64(m.HeapAlloc)>>30)
fmt.Printf("HeapIdle     = %.2f Gi\n", float64(m.HeapIdle)>>30)
fmt.Printf("HeapReleased = %.2f Gi\n", float64(m.HeapReleased)>>30)
fmt.Printf("★ 未归还     = %.2f Gi\n", float64(m.HeapIdle-m.HeapReleased)>>30)
```

**解决方案：**

**方案 A：设置 MemoryLimit（Go 1.19+，推荐）**

```go
debug.SetMemoryLimit(1600 << 20)   // 1.6 Gi，留出 400Mi 给非堆内存
```

**原理**：Go 会主动把内存占用压在这个限制以下，包括：
- 更激进的 GC
- 更积极的 scavenger（提前归还内存）

**方案 B：调 GOGC**

```go
debug.SetGCPercent(50)   // 堆增长 50% 就 GC（默认 100）
```

**方案 C：手动触发**

```go
// 处理完大请求后
runtime.GC()
debug.FreeOSMemory()   // ★ 强制归还，但代价是 STW + 后面的分配要重新 mmap
```

**⚠️ 不推荐频繁调用 `FreeOSMemory`**——它会导致性能抖动。只在明确的批处理场景用。

#### 可能 3：goroutine 泄漏

```
每个 goroutine 至少 2KB 栈
100 万个 goroutine = 2GB！

★ 但更常见的是"缓慢泄漏"：
  每天泄漏 1 万个，一个月就是 30 万个 = 600MB
```

**诊断：**

```bash
# 看 goroutine 数量
curl http://localhost:6060/debug/pprof/goroutine?debug=1

# 或者用 go tool pprof
go tool pprof http://localhost:6060/debug/pprof/goroutine
(pprof) top
(pprof) traces    ★ 看 goroutine 的调用栈
```

**常见泄漏模式：**

```go
// ❌ 1. channel 没关闭，接收者永久阻塞
func worker(ch chan Task) {
	for task := range ch {   // ch 永远不关闭 → goroutine 泄漏
		process(task)
	}
}

// ❌ 2. 没有 context 控制
func fetch(url string) {
	resp, _ := http.Get(url)   // 没有超时 → 可能永久挂起
	defer resp.Body.Close()
}

// ✅ 用 context
func fetch(ctx context.Context, url string) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
	resp, err := http.DefaultClient.Do(req)
	// ...
}

// ❌ 3. ticker 没停止
ticker := time.NewTicker(time.Second)
go func() {
	for range ticker.C {   // 如果函数返回，ticker 不会停
		doSomething()
	}
}()

// ✅
defer ticker.Stop()
```

#### 可能 4：cgo 分配的内存

```
★ cgo 分配的内存不受 Go GC 管理！

场景：
  · 用了 C 库（比如 RocksDB、OpenSSL、图像处理）
  · C 代码 malloc 了内存
  · Go 的 GC 看不到，也不会回收
```

**诊断：**

```bash
# 看进程的 VmSize 和 Go 的 Sys 的差值
cat /proc/<pid>/status | grep VmSize
# 如果 VmSize 远大于 Go 的 Sys → 可能是 cgo

# 用 pprof 看（需要开启 cgo 的 profile）
```

**解决**：
- 确保 C 代码正确释放内存
- 用 `runtime.SetFinalizer` 做兜底
- 或者用纯 Go 的库替代

---

### 完整的诊断流程

```bash
#!/bin/bash
# 容器 OOM 诊断脚本

PID=$(pidof your-app)

echo "=== 1. cgroup 内存详情 ==="
cat /sys/fs/cgroup/memory/memory.stat

echo -e "\n=== 2. cgroup 使用量 ==="
echo "usage: $(cat /sys/fs/cgroup/memory/memory.usage_in_bytes)"
echo "limit: $(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)"

echo -e "\n=== 3. 进程内存映射 ==="
cat /proc/$PID/status | grep -E "VmSize|VmRSS|VmSwap"

echo -e "\n=== 4. OOM 次数 ==="
cat /sys/fs/cgroup/memory/memory.failcnt

echo -e "\n=== 5. Go 视角 ==="
curl -s http://localhost:6060/debug/pprof/heap > /tmp/heap.prof
go tool pprof -top /tmp/heap.prof | head -20

echo -e "\n=== 6. goroutine 数量 ==="
curl -s http://localhost:6060/debug/pprof/goroutine?debug=1 | head -5

echo -e "\n=== 7. 文件缓存占用 ==="
cat /sys/fs/cgroup/memory/memory.stat | grep -E "cache|mapped_file"
```

---

### 解决方案总结

| 问题 | 方案 | 优先级 |
|:---|:---|:---|
| **Page cache 占用** | 限制日志量、日志轮转 | ★★★★★ |
| **Go 未归还内存** | `debug.SetMemoryLimit` | ★★★★★ |
| **goroutine 泄漏** | context 控制、修复泄漏点 | ★★★★ |
| **cgo 内存** | 检查 C 代码释放 | ★★★ |
| **limit 太小** | 根据实际占用调大 | ★★ |

**我的执行顺序：**

```
第 1 步: 加 debug.SetMemoryLimit（一行代码，立刻见效）
第 2 步: 检查 goroutine 数量（快速排除泄漏）
第 3 步: 看 memory.stat 的 cache 字段（确认是否文件缓存）
第 4 步: 限制日志量
第 5 步: 如果还不行，调大 limit
```

---

### 一个重要建议：给非堆内存留余量

```
容器 limit = 2Gi 时，Go 的内存预算应该是：

  堆内存上限:        1.4 Gi  (70%)
  非堆内存（栈、元数据、page cache）: 0.6 Gi (30%)

设置:
  debug.SetMemoryLimit(1400 << 20)   // 1.4 Gi

★ 这 30% 的余量不是"浪费"，而是必须的：
  · goroutine 栈
  · Go runtime 的元数据
  · page cache
  · 内存碎片的临时峰值
```

### 一句话总结

**容器 OOM 的核心问题是"你看到的内存"和"cgroup 算的内存"不是一回事。**

- **Go 的 HeapAlloc** < **Go 的 Sys** < **进程 RSS** < **cgroup 的 usage**

**每一层都有"看不见"的部分。理解这些差值，才能在容器环境里正确地管理内存。**

</details>

---

## 小结：这一节你应该带走的东西

1. **容器 = namespace（隔离视图）+ cgroup（限制资源）+ 其他内核特性**。它不是"轻量 VM"，根本没有第二层内核。

2. **User namespace 是容器安全的基石**：容器内的 root 映射到宿主机的普通用户。Docker 默认不开启，这是安全风险。

3. **cgroup v2 是统一层级**（v1 是每资源一棵树）。K8s 1.25+ 默认 v2。

4. **Go 在容器里最重要的一行配置**：`debug.SetMemoryLimit`。它让 Go 主动把内存压在限制以下。

5. **cgroup 的 OOM 判定用 `usage_in_bytes`**（RSS + page cache），而监控常用 `working_set`（减去 inactive_file）。**这个差异是"监控显示没超但被 OOM"的常见原因。**

6. **写容器的正确姿势**：用 `/proc/self/exe` 重新执行（因为 Go runtime 与 namespace 有冲突）、用 pivot_root 而不是 chroot。

7. **OverlayFS 的写时复制**是镜像分层共享的基础。代价是写性能，所以数据库数据要用 volume。

---

## 下一节

[02 · 性能工程：从观测到调优](./02-性能工程-从观测到调优.md)

> **老陈的预告**：你知道 `perf` 能看 CPU 热点，pprof 能看 Go 的调用栈。**但如果瓶颈在内核里呢？如果在系统调用里？如果偶发但你抓不到？**
>
> 下一节我们建立一套完整的性能方法论，并用 eBPF 做无侵入观测。
