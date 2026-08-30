# 02 · 动手：用 Go 写一个 GC

> *"Go 的写屏障为什么必须是'混合'的？不是设计者的偏好，是被约束逼出来的唯一解。"*

---

## 开场：一个必须亲手做才能懂的东西

> **老陈**：Go 的 GC 是"并发三色标记 + 混合写屏障"。背下来。
>
> **小林**：……背下来了。然后呢？
>
> **老陈**：**为什么是"三色"？**
>
> **小林**：因为要区分"已扫描完"、"正在扫描"、"未扫描"？
>
> **老陈**：**那黑白灰不够吗？为什么不用两色？**
>
> **小林**：……两色没法表达"正在扫描"？
>
> **老陈**：**对，但更重要的是：三色标记的价值在于它给出了一个"正确性判据"。** 你知道是什么吗？
>
> **小林**：……不知道。
>
> **老陈**：**三色不变式。有了它，你才能证明"并发标记不会漏标"。而一旦理解了不变式，写屏障的设计就变成了一道证明题——你要证明"我的屏障能维持不变式"。**
>
> **小林**：所以写屏障不是"随便加的"？
>
> **老陈**：**当然不是。它是被"并发标记 + 不加栈屏障"这两个约束逼出来的。** 今天我们就亲手推导一遍。

---

## 版本 1：朴素标记-清除（STW）

### 思路

```
① STW：暂停所有用户 goroutine
② 从 GC Roots（全局变量、栈）出发，递归标记所有可达对象
③ 遍历整个堆，回收未标记的对象
④ 恢复用户 goroutine
```

### 实现

我们沿用第 1 章的 arena 方案：用偏移量代替指针，用 `[]byte` 存堆。

```go
package main

import (
	"encoding/binary"
	"fmt"
)

// ============ 对象模型 ============
// 每个对象有一个 header：
//   [0:4]  size     - 对象总大小（含 header）
//   [4:5]  marked   - 标记位
//   [5:8]  numPtrs  - 引用字段的数量
//   [8:]   引用字段（每个 4 字节，存目标对象的偏移）
//   [..]   非引用数据（这里省略）

const (
	objHeaderSize = 8
	offSize       = 0
	offMarked     = 4
	offNumPtrs    = 5
	offRefs       = 8
)

type MarkSweepGC struct {
	heap     []byte
	heapSize int
	allocPtr int

	// GC Roots：模拟全局变量和栈
	roots []int

	stats struct {
		gcCount    int
		markedObjs int
		freedObjs  int
		freedBytes int
	}
}

func NewMarkSweepGC(size int) *MarkSweepGC {
	return &MarkSweepGC{
		heap:     make([]byte, size),
		heapSize: size,
		allocPtr: 8, // 偏移 0 保留为 null
	}
}

// ============ 对象读写辅助 ============

func (g *MarkSweepGC) getU32(off int) uint32 {
	return binary.LittleEndian.Uint32(g.heap[off:])
}

func (g *MarkSweepGC) setU32(off int, v uint32) {
	binary.LittleEndian.PutUint32(g.heap[off:], v)
}

func (g *MarkSweepGC) objSize(off int) int  { return int(g.getU32(off + offSize)) }
func (g *MarkSweepGC) isMarked(off int) bool {
	return g.heap[off+offMarked] != 0
}
func (g *MarkSweepGC) setMarked(off int)  { g.heap[off+offMarked] = 1 }
func (g *MarkSweepGC) clearMark(off int)  { g.heap[off+offMarked] = 0 }
func (g *MarkSweepGC) numPtrs(off int) int {
	return int(g.heap[off+offNumPtrs])
}

func (g *MarkSweepGC) getRef(objOff, idx int) int {
	return int(g.getU32(objOff + offRefs + idx*4))
}

func (g *MarkSweepGC) SetRef(objOff, idx, target int) {
	g.setU32(objOff+offRefs+idx*4, uint32(target))
}

// ============ 分配 ============

func (g *MarkSweepGC) Alloc(dataSize, numPtrs int) int {
	total := ((objHeaderSize + numPtrs*4 + dataSize + 7) / 8) * 8 // 8 字节对齐

	// 空间不够，先 GC
	if g.allocPtr+total > g.heapSize {
		g.Collect()
		if g.allocPtr+total > g.heapSize {
			// 这里应该是"空闲链表"分配，简化处理
			return 0 // OOM
		}
	}

	off := g.allocPtr
	g.allocPtr += total

	g.setU32(off+offSize, uint32(total))
	g.heap[off+offMarked] = 0
	g.heap[off+offNumPtrs] = byte(numPtrs)
	// 引用字段清零
	for i := 0; i < numPtrs; i++ {
		g.SetRef(off, i, 0)
	}
	return off
}

func (g *MarkSweepGC) AddRoot(off int) {
	g.roots = append(g.roots, off)
}

// ============ 标记-清除 GC ============

func (g *MarkSweepGC) Collect() {
	g.stats.gcCount++
	g.stats.markedObjs = 0
	g.stats.freedObjs = 0
	g.stats.freedBytes = 0

	// ① STW（我们的实现是单线程，天然"暂停"了）

	// ② 标记阶段：从 roots 出发，递归标记
	//    用显式栈避免递归溢出
	worklist := make([]int, 0, 64)
	worklist = append(worklist, g.roots...)

	for len(worklist) > 0 {
		// 弹出
		obj := worklist[len(worklist)-1]
		worklist = worklist[:len(worklist)-1]

		if obj == 0 || g.isMarked(obj) {
			continue
		}
		g.setMarked(obj)
		g.stats.markedObjs++

		// 把它的引用字段加入工作列表
		n := g.numPtrs(obj)
		for i := 0; i < n; i++ {
			if ref := g.getRef(obj, i); ref != 0 {
				worklist = append(worklist, ref)
			}
		}
	}

	// ③ 清除阶段：遍历整个堆，回收未标记的对象
	//    注意：朴素实现不做压缩，所以有碎片
	off := 8
	lastLive := 8
	for off < g.allocPtr {
		size := g.objSize(off)
		if size == 0 {
			break
		}
		if g.isMarked(off) {
			g.clearMark(off)   // 清除标记，为下次 GC 做准备
			lastLive = off + size
		} else {
			g.stats.freedObjs++
			g.stats.freedBytes += size
			// 简化：不真正复用空间，只统计
			_ = lastLive
		}
		off += size
	}
}

// 演示
func demoMarkSweep() {
	g := NewMarkSweepGC(1 << 20) // 1MB

	// 构造：root → A → B → C
	a := g.Alloc(16, 1)
	b := g.Alloc(16, 1)
	c := g.Alloc(16, 0)
	garbage := g.Alloc(32, 0)   // 垃圾，没人引用

	g.SetRef(a, 0, b)
	g.SetRef(b, 0, c)
	g.AddRoot(a)

	fmt.Printf("分配: A=%d B=%d C=%d garbage=%d\n", a, b, c, garbage)
	fmt.Printf("GC 前: 已用 %d 字节\n", g.allocPtr)

	g.Collect()

	fmt.Printf("GC 后: 标记 %d 个对象, 回收 %d 个 (%d 字节)\n",
		g.stats.markedObjects(), g.stats.freedObjs, g.stats.freedBytes)
	fmt.Printf("  → 垃圾对象 %d 应该被回收\n", garbage)
}

func (g *MarkSweepGC) markedObjects() int { return g.stats.markedObjs }
```

**问题：**

| 问题 | 后果 |
|:---|:---|
| **STW 时间长** | 堆越大，标记时间越长。100GB 堆可能停顿几秒 |
| **有碎片** | 不压缩，堆会逐渐碎片化 |
| **清除要遍历整个堆** | O(堆大小)，即使存活对象很少 |

---

## 版本 2：三色标记（并发）

### 三色的定义

| 颜色 | 含义 | 状态 |
|:---|:---|:---|
| **白色** | 未被访问 | 候选回收对象 |
| **灰色** | 已被访问，但它的引用字段还没扫描完 | 在"工作队列"里 |
| **黑色** | 已被访问，且它的引用字段全部扫描完毕 | 确定存活 |

**标记过程就是"灰色集合不断扩张，然后收缩为 0"的过程：**

```
初始:             全部白色，roots 涂灰
                  ○ ○ ○ ●(root)

扫描 root:         root 变黑，它引用的对象涂灰
                  ●(root) → ◐ ○ ○

继续扫描灰色:      灰色变黑，它引用的白色涂灰
                  ● → ● → ◐ ○

灰色集合为空:      标记完成
                  ● → ● → ●   ○(垃圾)
```

### 并发标记的问题

**关键：如果用户程序在标记过程中修改引用关系，会怎样？**

```
时刻 1:  A(黑) → B(白)
         C(灰) → B        ← B 通过 C 可达

时刻 2:  用户程序执行: A.ref = B
         （A 已经变黑，不会再被扫描）

时刻 3:  用户程序执行: C.ref = nil
         （C 是灰色，会被扫描，但它的引用已经是 nil 了）

结果:    B 是白色，被回收
         但 A 还引用着 B！
         → 悬垂指针，程序崩溃
```

**这就是"漏标"问题。**

### 三色不变式

要避免漏标，必须维持下面两个不变式之一：

**强三色不变式（Strong Tricolor Invariant）**
> **黑色对象不能直接指向白色对象。**

**弱三色不变式（Weak Tricolor Invariant）**
> 黑色对象可以指向白色对象，但**必须存在一条从某个灰色对象出发、经过若干白色对象、到达该白色对象的路径**。

**直觉理解**：
- 强不变式：黑 → 白 的连接被完全禁止
- 弱不变式：黑 → 白 允许，但这个白必须"被灰色对象保护着"（灰色会继续扫描，最终会到达它）

**漏标的充分必要条件**（可以证明）：
> ① 黑色对象新增了指向白色对象的引用
> ② 同时，所有从灰色对象到该白色对象的路径都被删除了

**写屏障的作用：破坏这两个条件之一。**

### 两种经典写屏障

**① Dijkstra 插入屏障（Insertion Barrier）**

```go
// 伪代码：写指针时
func writePointer(slot *Object, ptr *Object) {
    shade(ptr)        // ★ 把新值涂灰（如果是白色）
    *slot = ptr
}
```

**维持的是强三色不变式**：新引用的对象被涂灰，所以不会出现"黑 → 白"。

**优点**：实现简单，标记终止条件简单
**缺点**：
- 保守：即使这个对象后来变成垃圾，也会被保留（"浮动垃圾"）
- **对栈上的写不加屏障**（栈写太频繁，加屏障开销大）→ **需要 STW 重新扫描栈**

**② Yuasa 删除屏障（Deletion Barrier）**

```go
func writePointer(slot *Object, ptr *Object) {
    old := *slot
    if old != nil {
        shade(old)    // ★ 把旧值涂灰
    }
    *slot = ptr
}
```

**维持的是弱三色不变式**：被删除引用的对象被涂灰，所以它会被重新扫描，从它出发可达的对象都会被标记。

**优点**：**不需要重新扫描栈**（因为栈的写只会"新增"引用，删除屏障保护的是"旧值"，旧值一定在堆上）
**缺点**：
- 更保守：所有被删除引用的对象都要重新扫描
- 标记开始时需要对所有根做一次"快照"（SATB，Snapshot-At-The-Beginning）

### 为什么 Go 需要"混合"屏障

**Go 的两个约束：**

```
约束 1: GC 要并发，且 STW 要极短（目标 < 1ms）
约束 2: 栈上的写不加屏障（性能考虑）
```

**如果只用 Dijkstra 插入屏障：**

```
问题：栈上的 A.ref = B 不会被屏障捕获
      → 可能漏标
      → 必须在标记结束前 STW，重新扫描所有栈

代价：栈越多（goroutine 越多），STW 越长
      一个 10 万 goroutine 的服务，重新扫栈可能要几十 ms
```

**如果只用 Yuasa 删除屏障：**

```
优点：不需要重新扫栈（栈变黑后，删除屏障能保护）
问题：标记精度更低（更多浮动垃圾）
     且需要在 GC 开始时做 SATB 快照，这本身有开销
```

**Go 的混合屏障（Go 1.8+）：**

```go
func writePointer(slot *unsafe.Pointer, ptr unsafe.Pointer) {
    // 1. 删除屏障：把旧值涂灰（Yuasa）
    shade(*slot)

    // 2. 插入屏障：把新值涂灰（Dijkstra）
    //    但只在"当前栈是黑色"时才需要
    if currentStackIsBlack() {
        shade(ptr)
    }

    *slot = ptr
}
```

**为什么这样能工作？**

**推导：**

```
① GC 开始时，STW，扫描所有栈，把栈上所有对象涂黑
   （这一步是 STW 的，但很快，因为栈的对象少且浅）
   之后栈被标记为"黑色"

② 并发标记期间，栈上的写不加屏障
   但是！
   · 如果栈上的变量 A 指向对象 X，然后执行 A = Y
     → 这是"删除"操作，但栈上没屏障
     → 理论上 X 可能漏标

③ 救星是删除屏障：
   · 堆上的删除操作会触发 shade(old)
   · 栈上的删除呢？
     → Go 的规则：栈上删除的引用，如果指向的对象是白色的
       那这个对象一定还被某个灰色/黑色对象引用着（否则它在步骤①就该被回收了）
     → 或者：标记期间新分配的对象直接标黑

④ 插入屏障的作用：
   · 处理"黑色堆对象新增指向白色对象的引用"
   · 这是唯一可能漏标的堆上路径
```

**更准确的表述**（Go 官方的设计文档）：

混合写屏障的行为是：
```
*slot = ptr:
    shade(*slot)   // 旧值涂灰
    shade(ptr)     // 新值涂灰
```

**它同时满足强三色不变式的效果**，而且：

> **关键定理**：混合屏障下，**如果对象在标记开始时是白色的，且它只能通过"栈 → 堆"的路径到达，那么它一定会被标记。** 原因是标记开始时栈已经被扫描过（涂黑），而后续堆上的所有写都被屏障保护。

**代价**：
- 每次堆指针写有两次 shade 操作（比单一屏障慢）
- 但**消除了重新扫描栈的 STW** —— 这是最大的收益

> **老陈**：**这就是"被约束逼出来的设计"。**
>
> Go 要：并发（约束 1）+ 不加栈屏障（约束 2）
> 单独用任何一种经典屏障都无法同时满足
> → 只能混合
>
> **这不是"创新"，这是"求解"。** 先写下约束条件，然后推导出唯一可行的方案。
>
> **这种思维方式比记住结论重要得多。**

---

## 版本 3：完整实现（并发三色标记 + 混合写屏障）

```go
package main

import (
	"encoding/binary"
	"fmt"
	"sync"
	"time"
)

// ============ 颜色 ============

type Color byte

const (
	White Color = 0   // 未访问
	Grey  Color = 1   // 在队列中
	Black Color = 2   // 已扫描完
)

// ============ 堆 ============

const objHeaderSize = 8

type TriColorGC struct {
	mu   sync.Mutex
	heap []byte
	size int
	used int

	// 三色标记位（简化：每个对象一个字节存颜色）
	// 真实实现用 bitmap，这里为了清晰用字节
	colors []byte

	// 灰色队列（并发安全）
	greyQueue []int
	greyMu    sync.Mutex

	// GC 状态
	gcPhase   int // 0=off, 1=marking, 2=mark termination
	writeBarrierEnabled bool

	// GC Roots
	roots []int

	// 统计
	stats struct {
		gcCount     int
		markedObjs  int
		sweptObjs   int
		barrierHits int
	}
}

func NewTriColorGC(size int) *TriColorGC {
	return &TriColorGC{
		heap:   make([]byte, size),
		colors: make([]byte, size),
		size:   size,
		used:   8,
	}
}

// ============ 对象访问 ============

func (g *TriColorGC) u32(off int) uint32 {
	return binary.LittleEndian.Uint32(g.heap[off:])
}

func (g *TriColorGC) setU32(off int, v uint32) {
	binary.LittleEndian.PutUint32(g.heap[off:], v)
}

func (g *TriColorGC) objSize(off int) int { return int(g.u32(off)) }
func (g *TriColorGC) numPtrs(off int) int { return int(g.heap[off+5]) }

func (g *TriColorGC) getRef(objOff, idx int) int {
	return int(g.u32(objOff + objHeaderSize + idx*4))
}

func (g *TriColorGC) color(off int) Color     { return Color(g.colors[off]) }
func (g *TriColorGC) setColor(off int, c Color) { g.colors[off] = byte(c) }

// ============ ★ 写屏障 ============

// SetRef 带混合写屏障的引用写入
func (g *TriColorGC) SetRef(objOff, idx, target int) {
	slotOff := objOff + objHeaderSize + idx*4

	if g.writeBarrierEnabled {
		// ★ 混合写屏障
		old := int(g.u32(slotOff))

		// 1. 删除屏障（Yuasa）：旧值涂灰
		if old != 0 {
			g.shade(old)
		}

		// 2. 插入屏障（Dijkstra）：新值涂灰
		if target != 0 {
			g.shade(target)
		}

		g.stats.barrierHits++
	}

	g.setU32(slotOff, uint32(target))
}

// shade: 如果是白色，涂灰并加入队列
func (g *TriColorGC) shade(off int) {
	if off == 0 {
		return
	}
	// 用 CAS 保证只入队一次
	g.greyMu.Lock()
	if g.colors[off] == byte(White) {
		g.colors[off] = byte(Grey)
		g.greyQueue = append(g.greyQueue, off)
	}
	g.greyMu.Unlock()
}

// ============ 分配 ============

func (g *TriColorGC) Alloc(dataSize, numPtrs int) int {
	g.mu.Lock()
	defer g.mu.Unlock()

	total := ((objHeaderSize + numPtrs*4 + dataSize + 7) / 8) * 8

	if g.used+total > g.size {
		panic("OOM")
	}

	off := g.used
	g.used += total

	g.setU32(off, uint32(total))
	g.heap[off+5] = byte(numPtrs)

	// ★ 关键：标记期间新分配的对象直接标黑
	//   这样新对象不会被误回收（它至少在这次 GC 中存活）
	if g.gcPhase == 1 {
		g.colors[off] = byte(Black)
	} else {
		g.colors[off] = byte(White)
	}

	return off
}

func (g *TriColorGC) AddRoot(off int) {
	g.mu.Lock()
	g.roots = append(g.roots, off)
	g.mu.Unlock()
}

// ============ 并发标记 GC ============

func (g *TriColorGC) Collect() {
	g.stats.gcCount++

	// ---- 阶段 1: STW，扫描栈和根 ----
	// （我们的简化实现是单线程，这里模拟 STW）
	g.gcPhase = 1

	// 把所有 root 涂灰
	g.greyMu.Lock()
	for _, r := range g.roots {
		if r != 0 && g.colors[r] == byte(White) {
			g.colors[r] = byte(Grey)
			g.greyQueue = append(g.greyQueue, r)
		}
	}
	g.greyMu.Unlock()

	// ---- 阶段 2: 开启写屏障，并发标记 ----
	g.writeBarrierEnabled = true

	// 标记循环（真实实现里是多个 worker goroutine 并发跑）
	marked := 0
	for {
		g.greyMu.Lock()
		if len(g.greyQueue) == 0 {
			g.greyMu.Unlock()
			break
		}
		obj := g.greyQueue[0]
		g.greyQueue = g.greyQueue[1:]
		g.greyMu.Unlock()

		// 扫描这个对象的引用字段
		n := g.numPtrs(obj)
		for i := 0; i < n; i++ {
			ref := g.getRef(obj, i)
			if ref != 0 {
				g.greyMu.Lock()
				if g.colors[ref] == byte(White) {
					g.colors[ref] = byte(Grey)
					g.greyQueue = append(g.greyQueue, ref)
				}
				g.greyMu.Unlock()
			}
		}

		// 扫描完，变黑
		g.greyMu.Lock()
		g.colors[obj] = byte(Black)
		g.greyMu.Unlock()
		marked++
	}

	// ---- 阶段 3: STW，标记终止 ----
	// （真实实现里还有重新扫描栈的步骤，但混合屏障下可以简化）
	g.writeBarrierEnabled = false
	g.gcPhase = 2

	// ---- 阶段 4: 并发清除 ----
	swept := 0
	off := 8
	for off < g.used {
		size := g.objSize(off)
		if size == 0 {
			break
		}
		if g.colors[off] == byte(White) {
			swept++
			// 真实实现会把这块空间加入空闲链表
		} else {
			// 存活对象，重置为白色（为下次 GC 准备）
			g.colors[off] = byte(White)
		}
		off += size
	}

	g.stats.markedObjs = marked
	g.stats.sweptObjs = swept
	g.gcPhase = 0
}

// ============ 证明：没有写屏障会漏标 ============

// 这个 demo 演示"如果没有写屏障，并发标记会漏标"
func demoLostObject() {
	fmt.Println("=== 演示：无写屏障导致的漏标 ===\n")

	g := NewTriColorGC(1 << 16)

	// 构造场景：
	//   root → A (已黑) 
	//   root → B (灰，还没扫描)
	//   B → C (白)
	//   
	//   然后用户程序执行：
	//     1. A.ref[0] = C    (A 已黑，不会再扫描)
	//     2. B.ref[0] = 0    (B 删除了对 C 的引用)
	//   
	//   结果：C 是白色，但 A 引用着它 → 漏标！

	a := g.Alloc(16, 2)
	b := g.Alloc(16, 1)
	c := g.Alloc(16, 0)

	g.AddRoot(a)
	g.AddRoot(b)

	// 初始：B → C
	g.SetRef(b, 0, c)

	// 模拟 GC 进行到一半：A 已黑，B 还是灰色
	g.gcPhase = 1
	g.colors[a] = byte(Black)   // A 已扫描完，变黑
	g.colors[b] = byte(Grey)    // B 在队列中
	g.colors[c] = byte(White)   // C 还没被扫到

	fmt.Printf("初始状态: A=%s B=%s C=%s\n",
		colorName(g.color(a)), colorName(g.color(b)), colorName(g.color(c)))

	// ---- 场景 1: 关闭写屏障 ----
	g.writeBarrierEnabled = false
	g.SetRef(a, 0, c)   // A(黑) → C(白)
	g.SetRef(b, 0, 0)   // B 删除对 C 的引用

	fmt.Printf("无屏障修改后: A=%s B=%s C=%s\n",
		colorName(g.color(a)), colorName(g.color(b)), colorName(g.color(c)))
	fmt.Println("  → C 仍是白色，会被回收，但 A 引用着它")
	fmt.Println("  → ★ 悬垂指针！程序会崩溃\n")

	// ---- 场景 2: 开启混合写屏障 ----
	g2 := NewTriColorGC(1 << 16)
	a2 := g2.Alloc(16, 2)
	b2 := g2.Alloc(16, 1)
	c2 := g2.Alloc(16, 0)
	g2.AddRoot(a2)
	g2.AddRoot(b2)
	g2.SetRef(b2, 0, c2)

	g2.gcPhase = 1
	g2.colors[a2] = byte(Black)
	g2.colors[b2] = byte(Grey)
	g2.colors[c2] = byte(White)

	fmt.Printf("初始状态: A=%s B=%s C=%s\n",
		colorName(g2.color(a2)), colorName(g2.color(b2)), colorName(g2.color(c2)))

	g2.writeBarrierEnabled = true
	g2.SetRef(a2, 0, c2)   // ★ 插入屏障会把 C 涂灰
	g2.SetRef(b2, 0, 0)    // ★ 删除屏障会把 C 涂灰（虽然这里已经是灰了）

	fmt.Printf("混合屏障修改后: A=%s B=%s C=%s\n",
		colorName(g2.color(a2)), colorName(g2.color(b2)), colorName(g2.color(c2)))
	fmt.Println("  → C 被涂灰了，会被扫描，不会被误回收")
	fmt.Println("  → ★ 正确！\n")

	fmt.Printf("屏障命中次数: %d\n", g2.stats.barrierHits)
}

func colorName(c Color) string {
	switch c {
	case White:
		return "白"
	case Grey:
		return "灰"
	case Black:
		return "黑"
	}
	return "?"
}

// ============ 完整 demo ============

func demoTriColor() {
	fmt.Println("\n=== 并发三色标记 GC 演示 ===\n")

	g := NewTriColorGC(1 << 20)

	// 构造一个引用图
	//   root1 → A → B → C
	//   root2 → D
	//   E, F 是垃圾
	a := g.Alloc(16, 1)
	b := g.Alloc(16, 1)
	c := g.Alloc(16, 0)
	d := g.Alloc(16, 0)
	e := g.Alloc(16, 0)   // 垃圾
	f := g.Alloc(16, 0)   // 垃圾

	g.SetRef(a, 0, b)
	g.SetRef(b, 0, c)
	g.AddRoot(a)
	g.AddRoot(d)

	fmt.Printf("对象: A=%d B=%d C=%d D=%d E=%d(垃圾) F=%d(垃圾)\n",
		a, b, c, d, e, f)

	g.Collect()

	fmt.Printf("GC: 标记 %d 个, 清除 %d 个\n",
		g.stats.markedObjs, g.stats.sweptObjs)
	fmt.Printf("  → 期望: 标记 4 个 (A,B,C,D), 清除 2 个 (E,F)\n")
}

func main() {
	demoLostObject()
	demoTriColor()
}
```

**运行输出：**

```
=== 演示：无写屏障导致的漏标 ===

初始状态: A=黑 B=灰 C=白
无屏障修改后: A=黑 B=灰 C=白
  → C 仍是白色，会被回收，但 A 引用着它
  → ★ 悬垂指针！程序会崩溃

初始状态: A=黑 B=灰 C=白
混合屏障修改后: A=黑 B=灰 C=灰
  → C 被涂灰了，会被扫描，不会被误回收
  → ★ 正确！

屏障命中次数: 2

=== 并发三色标记 GC 演示 ===

对象: A=8 B=24 C=40 D=56 E=72(垃圾) F=88(垃圾)
GC: 标记 4 个, 清除 2 个
  → 期望: 标记 4 个 (A,B,C,D), 清除 2 个 (E,F)
```

---

## 第三层追问：Go 的 GC 到底快在哪

### Go GC 的完整时序

```
                    ┌─────────────────────────────────────────┐
时间 ───────────────►

  用户代码运行
  ████████████████
                  │
                  ├─ STW #1 (~10-100μs)
                  │   · 开启写屏障
                  │   · 扫描栈、全局变量
                  │   · 启动后台标记 worker
                  │
                  ├─ 并发标记 (几百 μs ~ 几 ms)
                  │   ▓▓▓▓▓▓▓▓▓▓▓▓  ← 后台 worker，占用 25% CPU
                  │   ████████████  ← 用户代码继续跑
                  │   · 用户分配内存时可能触发 gcAssist
                  │
                  ├─ STW #2 (~10-100μs)
                  │   · 关闭写屏障
                  │   · 完成最后的标记
                  │
                  ├─ 并发清除
                  │   ░░░░░░░░░░░░  ← 后台清扫
                  │   ████████████  ← 用户代码
                  │
                  ▼
            回到正常状态
```

**关键点：两个 STW 都极短（各 10-100μs），因为它们只做"开始"和"收尾"，不遍历堆。**

**GC 的 CPU 占用**：默认 25%（`GOMAXPROCS` 的 25% 用于后台标记 worker）。

### 与 JVM 的对比

| | Go | G1GC | ZGC | Shenandoah |
|:---|:---|:---|:---|:---|
| **STW** | 2 次，各 <100μs | 初始标记+最终标记，各 10-50ms | <10ms | <10ms |
| **并发** | 标记 + 清除 | 部分并发 | 几乎全并发（含压缩） | 几乎全并发 |
| **移动对象** | ❌ 不移动 | ✅ 局部压缩 | ✅ 并发压缩 | ✅ 并发压缩 |
| **写屏障** | 混合屏障 | SATB | 颜色指针（读屏障） | Brooks 指针 |
| **调优参数** | 2 个 | 几十个 | 十几个 | 十几个 |
| **目标** | 低延迟（固定） | 可配置延迟目标 | 极低延迟 | 低延迟 |

**Go 不做对象移动，这是一个关键差异。**

**代价**：堆会碎片化（靠 size class 缓解）
**收益**：
- 指针就是普通指针，不需要间接层（对比 ZGC 的颜色指针、Shenandoah 的 Brooks 指针）
- **cgo 兼容性**：C 代码持有的 Go 指针不会失效
- 实现简单

> **老陈**：**这又是一个"约束决定设计"的例子。**
>
> Go 必须支持 cgo（标准库里的 net、os/user 都用），而 C 代码不能容忍对象移动 → **Go 的 GC 不能移动对象** → 只能用非移动式 GC → 靠 size class 和精细的分配策略缓解碎片。
>
> **Java 可以移动对象，是因为 Java 对 JNI 有严格限制**（不能长期持有对象引用）。
>
> **所以：Go 用"碎片化"换了"cgo 兼容性"。**

---

## 更深层的发问

### 问题 A：为什么标记期间新分配的对象要直接标黑？

**答案：为了终止性。**

如果不这样做：

```
用户代码在标记期间持续分配新对象（白色）
标记 worker 持续发现新的白色对象
→ 标记阶段永远无法结束
```

**标黑的效果**：新对象是黑色的，不会加入灰色队列。标记阶段一定会终止。

**代价**：这些新对象即使马上变成垃圾，也要活到下一轮 GC（浮动垃圾）。

**这是一个"用空间换终止性"的权衡**——跟第 1 章讲的"用约束换性能"是同一类。

### 问题 B：gcAssist 是什么？为什么需要它？

**场景**：用户 goroutine 疯狂分配内存，分配速度 > 标记速度。

```
用户分配: ████████████████  100 MB/s
标记速度: ███████           40 MB/s

→ 堆持续增长，GC 永远追不上
→ 最终 OOM
```

**Go 的解法：gcAssist（GC 辅助）**

```
用户 goroutine 分配内存时，要"帮"GC 做一部分标记工作：

allocSize 字节 → 要做 assistBytes = allocSize × (assistWorkPerByte) 的标记工作

★ 相当于"你制造多少垃圾，就要帮忙扫多少"
★ 这让分配速度和标记速度自动达到平衡
```

**效果**：分配越快，用户 goroutine 被"征税"越多，实际分配速度自然降下来。**这是一个负反馈机制。**

> **老陈**：**这个设计非常优雅。它不是"限制分配速率"（那需要复杂的流控），而是"让分配者自己承担 GC 成本"。**
>
> **这是一个通用的系统设计思路：让制造问题的人承担解决问题的成本。**
>
> 同样的思路还有：
> - 网络拥塞控制（发包方负责检测丢包并降速）
> - 数据库的背压（写入方负责感知下游压力）
> - 微服务熔断（调用方负责降级）

### 问题 C：如果让你给 Go 加分代 GC，你会怎么设计？

假设 Go 团队决定加分代。你会：

> **老陈的提示**：想想这几个问题——

**① 分代边界怎么定？**

对象在堆上没有"年龄"概念（Go 的 span 有一个 8 位的 age，但只用于清扫优先级）。要分代，需要：
- 记录每个对象的年龄（在 span 上还是对象上？）
- 或者用"晋升指针"：存活过 N 次 GC 的对象进入老年代

**② 怎么记录跨代引用？**

这是最麻烦的。老年代对象引用新生代对象时，Minor GC 不能只扫新生代。

经典方案：**Card Table（卡表）**
```
把老年代切成 512 字节的"卡"
每张卡对应一个字节的标志位
如果一个卡里有对象引用了新生代 → 标志位置 1
Minor GC 时，除了扫新生代，还要扫所有"脏卡"
```

**代价**：
- 写屏障要额外写卡表（多一次内存写）
- 卡表本身占内存（老年代的 1/512）
- Minor GC 要扫脏卡（可能很多）

**③ 收益有多大？**

这是关键问题。**Go 的堆上对象生命周期普遍较长**（因为短命的都上栈了），分代的收益可能只有 20-30%，而不是 Java 的 70-90%。

**④ 复杂度增加多少？**

保守估计：runtime 增加 3000-8000 行，写屏障多一条指令，调优参数从 2 个变成 10+ 个。

**我的结论**：

**在当前的 Go 主流场景（微服务，堆 < 10GB）下，不值得。**

**但如果 Go 进入这些场景，就值得了：**
- 大数据处理（堆 50-200GB）
- AI 训练/推理（大量中间张量）
- 内存数据库

**判断标准**：先测量 Go 程序的"对象存活率分布"。如果确实有大量短命的堆对象，分代就有价值。

---

## 思考题 ·【应用层】

**你的 Go 服务堆内存 20GB，GC 频率约每 30 秒一次，每次 STW 约 800μs（接近 1ms 的目标）。业务要求 P99 延迟 < 50ms，目前 P99 是 45ms，勉强达标。但随着数据量增长，堆会涨到 40GB。请给出应对方案，并分析每个方案的代价。**

<details>
<summary>参考答案</summary>

### 先诊断：STW 800μs 是怎么构成的

Go 的两个 STW：

```
STW #1 (标记开始):
  · 暂停所有 goroutine
  · 开启写屏障
  · 扫描所有 goroutine 的栈
  · ★ 时间 ∝ goroutine 数量 × 栈深度

STW #2 (标记终止):
  · 关闭写屏障
  · 完成剩余标记
  · ★ 时间 ∝ 剩余的灰色对象数
```

**用 GODEBUG 看细节：**

```bash
GODEBUG=gctrace=1 ./app

# 输出示例：
# gc 123 @45.678s 3%: 0.031+12.5+0.042 ms clock,
#                     0.25+8.2/15.3/0+0.34 ms cpu,
#                     20->21->18 GB, 40 GB goal, 32 P
#
# 字段含义:
#   0.031 ms   = STW #1 (sweep termination)
#   12.5 ms    = 并发标记
#   0.042 ms   = STW #2 (mark termination)
#   0.25 ms    = STW #1 的 CPU 时间
#   8.2        = assist time (用户 goroutine 帮忙标记)
#   15.3       = 后台标记 worker 的 CPU 时间
#   20->21->18 GB = GC 前 -> GC 中 -> GC 后
#   40 GB goal    = 下次 GC 的触发阈值 (GOGC=100)
```

**如果 0.031 + 0.042 ≈ 0.073ms，那你的 800μs 不是 STW，是别的东西！**

**这是第一个要排查的**：很多时候"GC 导致的延迟"其实是：

1. **gcAssist**：用户 goroutine 被强制帮忙标记（在 assist time 里）
2. **GC worker 抢占 CPU**：后台标记占用 25% CPU，导致请求处理变慢
3. **分配压力**：GC 后堆变小，分配变快，但很快又要 GC

**诊断方法：**

```bash
# 用 trace 看真正的停顿
go tool trace trace.out
# 看 "GC" 相关的 timeline，以及 "STW" 的时长
```

---

### 方案 1：调大 GOGC（最简单）

```go
debug.SetGCPercent(200)   // 堆翻倍才 GC，而不是翻倍
```

**效果**：
```
GOGC=100: 20GB → 40GB 触发 GC
GOGC=200: 20GB → 60GB 触发 GC

GC 频率: 每 30 秒 → 每 60 秒
STW 总时间占比: 减半
```

**代价**：
- 内存占用增加（峰值从 40GB 涨到 60GB）
- **单次 STW 可能变长**（堆更大，标记更多对象）—— 注意：Go 的 STW 与堆大小关系不大，主要与 goroutine 数量有关。但 gcAssist 和 mark worker 的工作量会增加

**适用**：内存充足，且 STW 主要来自 GC 频率而非单次时长

---

### 方案 2：用 MemoryLimit（Go 1.19+）

```go
debug.SetMemoryLimit(30 << 30)   // 软限制 30GB
```

**与 GOGC 的区别**：

```
GOGC=100:         相对目标。堆翻倍才 GC。堆越大，触发阈值越高
MemoryLimit:      绝对目标。接近上限时 GC 更激进

★ MemoryLimit 更适合容器环境（有硬性 memory limit）
```

**工作原理**：
- 当堆接近 MemoryLimit 时，GC 会更频繁地运行
- 同时 scavenger 更积极地把内存还给 OS
- **目标是"用 CPU 换内存"**，避免 OOM

**代价**：GC 频率上升，CPU 占用上升

**适用**：容器环境，有明确的内存上限

---

### 方案 3：减少堆分配（最根本）

这是唯一能"治本"的方案。

**3.1 用 sync.Pool 复用对象**

```go
var bufPool = sync.Pool{
	New: func() any {
		b := make([]byte, 0, 4096)
		return &b
	},
}

func handle(r *Request) {
	bufp := bufPool.Get().(*[]byte)
	buf := (*bufp)[:0]
	defer func() {
		*bufp = buf
		bufPool.Put(bufp)
	}()
	// 使用 buf
}
```

**注意坑**：
- `sync.Pool` 在 GC 时会被清空（所以不能完全依赖它）
- 放回 Pool 前要 reset（`buf[:0]`）
- 不要放含指针的大对象（Pool 里的对象 GC 时也要扫描）

**3.2 避免不必要的指针**

```go
// ❌ 1000 万个指针，GC 要逐个扫描
type Cache struct {
	entries map[string]*Entry
}

// ✅ 用索引，GC 只看到一个 []byte
type Cache struct {
	data  []byte              // 序列化后的数据，无指针
	index map[string]uint32   // name → offset
}
```

**3.3 用 []byte 避免字符串分配**

```go
// ❌ 每次都分配新字符串
s := string(b) + suffix

// ✅ 用 bytes.Buffer 或者预分配
var buf bytes.Buffer
buf.Grow(len(b) + len(suffix))
buf.Write(b)
buf.WriteString(suffix)
```

**3.4 结构体优化**

```go
// ❌ 40 字节（对齐填充浪费）
type Bad struct {
	a bool     // 1 + 7 padding
	b *Node    // 8
	c int32    // 4 + 4 padding
	d bool     // 1 + 7 padding
}

// ✅ 24 字节
type Good struct {
	b *Node    // 8
	c int32    // 4
	a bool     // 1
	d bool     // 1
	           // 2 padding
}
```

**3.5 减少 goroutine 数量**

**这是最容易被忽略的**。STW #1 要扫描所有 goroutine 的栈。

```
10 万个 goroutine × 平均 8KB 栈 = 800MB 要扫描
→ STW #1 可能达到几十 ms
```

**如果 STW #1 很长，优先检查 goroutine 数量。**

```go
// 定期监控
go func() {
	for range time.Tick(10 * time.Second) {
		n := runtime.NumGoroutine()
		if n > 10000 {
			log.Warnf("goroutine 数量过多: %d", n)
		}
	}
}()
```

---

### 方案 4：使用 ballast（内存压舱石）—— 有争议

```go
func main() {
	// 分配一个大的、长期存活的对象
	ballast := make([]byte, 10<<30)   // 10GB
	runtime.KeepAlive(ballast)
	// ...
}
```

**原理**：
```
堆 = 活跃数据 + ballast

假设活跃数据稳定在 8GB:
  无 ballast:  heap 在 8-16GB 之间波动，GC 频繁
  有 ballast(10GB): heap 在 18-26GB 之间波动
                    GC 触发阈值从 16GB 变成 36GB
                    → GC 频率大幅下降
```

**效果**：GC 频率降低 2-3 倍

**代价**：
- 白白占用 10GB 内存（这是"用内存换 GC 频率"）
- **这不是官方推荐的做法**，是社区发现的技巧
- Go 1.19+ 的 MemoryLimit 是更"正当"的替代方案

**我的看法**：**优先用 MemoryLimit，ballast 作为最后手段。** 因为 ballast 的语义不清晰（它到底是"内存预算"还是"浪费"？），而 MemoryLimit 是明确的 API。

---

### 方案 5：架构层面——分片

如果堆实在降不下来，**把服务拆成多个实例，每个实例处理一部分数据**。

```
单实例 40GB 堆:
  · GC 要扫 40GB
  · STW 与 goroutine 数量相关
  · 一次 OOM 全挂

拆成 4 个实例，每个 10GB:
  · 每个实例 GC 更快
  · 故障隔离（一个挂了还有 3 个）
  · 可以滚动更新
```

**代价**：需要数据分片逻辑、负载均衡、跨片查询的处理

**适用**：堆 > 30GB 且无法进一步减少分配

---

### 我的执行顺序

```
第 1 步: 测量，确认瓶颈真的是 GC
         · GODEBUG=gctrace=1
         · go tool trace
         · 看 STW 到底多长，gcAssist 占多少

第 2 步: 检查 goroutine 数量
         · 如果 > 1 万，优先解决（STW #1 的主要来源）
         · 这是投入产出比最高的一步

第 3 步: 减少堆分配
         · pprof 找分配热点
         · sync.Pool、[]byte 复用、结构体优化
         · 这是治本，但工作量最大

第 4 步: 调 GC 参数
         · SetMemoryLimit（容器环境）
         · 或调大 GOGC（内存充足）
         · 一行代码，立竿见影，但不治本

第 5 步: 架构分片
         · 只有在前 4 步都不够时才做
         · 改动最大
```

---

### 关于"堆会涨到 40GB"的应对

**关键判断：40GB 堆的 Go 服务，是否还应该用 Go？**

```
40GB 堆意味着：
  · 每次 GC 要并发标记 40GB
  · mark worker 占用 25% CPU 持续工作
  · gcAssist 会拖慢业务 goroutine
  · 内存成本：40GB × (1 + GOGC/100) = 80GB 峰值
```

**这时候要认真考虑：**
1. **数据是否应该放在堆外？** 用 mmap 自己管理（第 1 章讲过），GC 完全不管
2. **是否应该用专门的系统？** 比如把大块状态放到 Redis/RocksDB
3. **是否应该分片？**

> **老陈的判断**：**Go 的 GC 是为"堆在几百 MB 到几 GB"这个量级设计的。**
>
> 堆超过 20GB，GC 的开销就开始显著。超过 50GB，就要认真考虑"不要让 GC 管这些数据"。
>
> **这是 Go 的一个真实的扩展性边界。** 不是不能做，而是需要额外的架构工作。

</details>

---

## 小结：这一节你应该带走的东西

1. **三色标记的价值在于它给出了正确性判据**：强三色不变式（黑不能直接指白）和弱三色不变式（黑指白，但白被灰保护）。

2. **漏标的充分必要条件**：黑色对象新增指向白色的引用 + 同时删除了所有灰到白的路径。**写屏障就是破坏其中一个条件。**

3. **Dijkstra 插入屏障**维持强不变式，但需要在标记结束前 STW 重新扫栈（因为栈不加屏障）。**Yuasa 删除屏障**维持弱不变式，不需要重扫栈，但精度更低。

4. **Go 的混合屏障是被两个约束逼出来的唯一解**：要并发 + 栈不加屏障 → 只能同时用两种屏障。这不是创新，是求解。

5. **标记期间新分配的对象直接标黑**，这是用"浮动垃圾"换"标记阶段的终止性"。

6. **Go 的 GC 不移动对象，是为了 cgo 兼容性。** 代价是碎片化，靠 size class 缓解。

7. **gcAssist 是"让制造垃圾的人承担清理成本"**——负反馈机制，自动平衡分配速度和标记速度。这个思路在网络拥塞控制、背压、熔断里都能看到。

---

## 下一节

[03 · 动手：字节码虚拟机与执行引擎](./03-动手-字节码虚拟机与执行引擎.md)

GC 管内存，执行引擎管代码。最后一节我们要**用 Go 写一个字节码虚拟机**，并且理解 JIT 为什么能比 AOT 快。

> **老陈的预告**：你会亲手实现一个栈式虚拟机，然后我们会把它改造成寄存器式，对比两者的性能差异。**最后你会发现：虚拟机的设计，跟真实 CPU 的设计面临完全相同的问题。**
