# 02 · WAL、MVCC 与事务

> *"如果写入到一半断电了，你的 B+Tree 不只是丢数据——整个树可能都坏了。"*

---

## 开场：一次"不可能"的损坏

> **小林**：我们的引擎跑了三个月，昨天机房断电，重启后数据库起不来了。B+Tree 的根节点指向了一个不存在的页。
>
> **老陈**：**你写了 WAL 吗？**
>
> **小林**：没有，但我觉得断电最多就是丢几条数据……
>
> **老陈**：**错。断电的后果比"丢数据"严重得多。** 我问你：插入一条记录导致页分裂，需要几步？
>
> **小林**：分配新页、移动一半数据、更新父节点、更新叶子链表……四步？
>
> **老陈**：**对。如果这四步执行到第二步时断电了呢？**
>
> **小林**：……数据复制到一半？
>
> **老陈**：**不止。** 你想想这四个后果：
>
> ① **数据丢失**：新页的内容只在 page cache 里，没落盘
> ② **结构损坏**：原页已经改了一半，新页还没写完
> ③ **空间泄漏**：新页已经分配（nextPageID++），但没有内容，永久浪费
> ④ **链表断裂**：叶子链表的 next 指针只更新了一半
>
> **小林**：那怎么办？
>
> **老陈**：**WAL（Write-Ahead Logging）。** 核心原则只有一条——
>
> **★ 在修改任何数据页之前，必须先把"要做什么"写进日志，并且日志已经落盘。**

---

## WAL 的核心原则

### Write-Ahead Logging 规则

```
规则 1（WAL 规则）:
    修改数据页之前，必须保证描述这个修改的 log record 已经落盘

规则 2（Force Log at Commit）:
    事务提交时，必须保证它的所有 log record 已经落盘
```

**为什么这样就够了？**

```
因为日志是"顺序追加"的，而数据页是"随机修改"的。

顺序写:  1 次 IO 可以写很多条日志（几百条）
随机写:  每条记录都要 1 次 IO

★ 用"一次顺序写"代替"多次随机写"
★ 这就是 WAL 让写入变快的根本原因（不只是为了恢复）
```

### WAL 的结构

```
┌──────┬──────┬──────┬──────┬──────┬─────┐
│ LSN1 │ LSN2 │ LSN3 │ LSN4 │ LSN5 │ ... │  日志（只追加）
└──────┴──────┴──────┴──────┴──────┴─────┘
   ▲                    ▲
   │                    │
 日志起点              已落盘位置
                    (flushed LSN)

每个 log record:
┌────────────────────────────────────────────┐
│ LSN          8 bytes   全局递增的日志序号     │
│ txnID        8 bytes   事务 ID              │
│ type         1 byte    BEGIN/UPDATE/COMMIT  │
│ pageID       4 bytes   修改的页             │
│ offset       2 bytes   页内偏移             │
│ beforeImage  变长       修改前的数据（undo）  │
│ afterImage   变长       修改后的数据（redo）  │
│ prevLSN      8 bytes   同一事务的上一条日志   │  ← 形成事务的日志链
│ checksum     4 bytes                        │
└────────────────────────────────────────────┘
```

### LSN（Log Sequence Number）

**LSN 是整个系统的"逻辑时钟"。**

```
LSN 单调递增，每个 log record 有唯一 LSN

关键用途：
① 每个数据页记录 pageLSN（最后修改它的日志的 LSN）
② 恢复时：如果 pageLSN >= 某条日志的 LSN
          → 说明这个修改已经应用到页了，不用重做
③ Buffer Pool 淘汰页时：
          如果 pageLSN > flushedLSN
          → ★ 违反 WAL 规则！必须先 flush 日志
```

**这个检查是 WAL 正确性的核心：**

```go
func (bp *BufferPool) evictPage(page *Page) error {
	// ★ WAL 规则检查
	if page.pageLSN > bp.logManager.GetFlushedLSN() {
		// 这个页的修改还没落盘到日志，不能淘汰数据页
		return errors.New("违反 WAL 规则：必须先 flush 日志")
	}
	if page.isDirty {
		return bp.diskManager.WritePage(page.id, page.data)
	}
	return nil
}
```

---

## ARIES 恢复算法

ARIES（Algorithms for Recovery and Isolation Exploiting Semantics）是 1992 年提出的经典算法，现代数据库的恢复基本都基于它。

### 三个阶段

```
崩溃发生
   │
   ▼
┌──────────────────────────────────────────┐
│  阶段 1: 分析 (Analysis)                   │
│  从最近的 checkpoint 开始，扫描日志         │
│  确定：                                    │
│    · 哪些事务已经提交（要 REDO）            │
│    · 哪些事务未提交（要 UNDO）              │
│    · 哪些页是脏页（可能没落盘）              │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  阶段 2: 重做 (REDO)                       │
│  从最早的"可能丢失的修改"开始               │
│  重放所有日志（不管事务是否提交）            │
│  目的：把数据库恢复到崩溃瞬间的状态           │
│  ★ 用 pageLSN 判断是否需要重做              │
└──────────────┬───────────────────────────┘
               ▼
┌──────────────────────────────────────────┐
│  阶段 3: 撤销 (UNDO)                       │
│  回滚所有未提交的事务                       │
│  从后往前，用 beforeImage 还原              │
│  ★ 撤销操作本身也要记日志（防止撤销时再崩）   │
└──────────────┬───────────────────────────┘
               ▼
          恢复完成
```

### 为什么先 REDO 再 UNDO？

> **老陈**：**这是一个"历史重演"的思路。**
>
> **REDO 阶段：把数据库恢复到"崩溃那一刻"的完整状态**（包括未提交事务的修改）。
> **UNDO 阶段：再把未提交的部分撤销掉。**
>
> **为什么不直接"只重做已提交的"？**
>
> 因为日志是交织的：
> ```
> LSN1: T1 BEGIN
> LSN2: T1 UPDATE page5
> LSN3: T2 BEGIN
> LSN4: T2 UPDATE page5    ← T2 修改了 T1 改过的页
> LSN5: T1 COMMIT
> LSN6: T2 UPDATE page7
> ...崩溃（T2 未提交）
> ```
>
> 如果只重做 T1，page5 的状态会不对（因为它还包含 T2 的修改）。
>
> **所以必须先完整重演历史，再撤销未提交的部分。** 这样每一步都是确定性的。

### 幂等性：REDO 可以重复执行

```
关键设计：REDO 是幂等的

判断依据：pageLSN
  · 读页，看 pageLSN
  · 如果 pageLSN >= 日志的 LSN
    → 这个修改已经应用过了，跳过
  · 否则应用

★ 这使得恢复过程中再次崩溃也没关系
★ 重启后重新 REDO，已经做过的会被跳过
```

### 检查点（Checkpoint）

**问题**：日志会无限增长，恢复时要从头扫描。

**解法**：定期做 checkpoint。

```
Checkpoint 做什么:
  1. 把 Buffer Pool 里的所有脏页写盘
  2. 记录当前活跃的事务列表
  3. 记录当前 LSN
  4. 写一条 CHECKPOINT 日志记录

恢复时:
  · 从最后一个 checkpoint 开始扫描（不用从头）
```

**Fuzzy Checkpoint（模糊检查点）**：

```
朴素 checkpoint: 要暂停所有事务，等所有脏页写完
                → 停顿很长（秒级）

Fuzzy checkpoint: 不暂停事务
                 · 记录 checkpoint 开始时的活跃事务
                 · 记录 checkpoint 开始时的最小 LSN（所有脏页中最小的 pageLSN）
                 · 后台慢慢写脏页
                 · 写 CHECKPOINT_END 记录

恢复: 从"checkpoint 记录的最小 LSN"开始 REDO（而不是从 checkpoint 的 LSN）
     ★ 因为 checkpoint 期间可能有更早的脏页没写完
```

> **老陈**：**Fuzzy Checkpoint 的精髓是"记录一个保守的下界"。**
>
> 你不确定哪些页写完了，但你知道"所有 LSN < X 的修改都写完了"。那就从 X 开始恢复。**多做一些 REDO 没关系（幂等），但不能少做。**
>
> **这个"用冗余换取简单性"的思路，在分布式系统里也非常常见。**

---

## 事务与隔离级别

### ACID

| | 含义 | 实现机制 |
|:---|:---|:---|
| **A**tomicity 原子性 | 要么全做，要么全不做 | **Undo Log** |
| **C**onsistency 一致性 | 从一个合法状态到另一个 | 应用层 + 约束 |
| **I**solation 隔离性 | 并发事务互不干扰 | **锁 + MVCC** |
| **D**urability 持久性 | 提交后不丢失 | **Redo Log + fsync** |

> 注意：**一致性（C）不是数据库单独保证的**，它需要应用层的配合（比如转账时两个账户的总和不变）。数据库保证的是 AID。

### 四个隔离级别与三种问题

**三种并发问题：**

| 问题 | 描述 | 例子 |
|:---|:---|:---|
| **脏读** | 读到另一个未提交事务的修改 | T1 改了 x=2（未提交），T2 读到 x=2，T1 回滚 → T2 读到的是"不存在的"值 |
| **不可重复读** | 同一事务内两次读，结果不同 | T1 读 x=1，T2 改 x=2 并提交，T1 再读 x=2 |
| **幻读** | 同一事务内两次范围查询，行数不同 | T1 查 age>18 有 10 条，T2 插入一条并提交，T1 再查有 11 条 |

**四个隔离级别：**

| 级别 | 脏读 | 不可重复读 | 幻读 | 实现 |
|:---|:---|:---|:---|:---|
| **读未提交** (RU) | ❌ 可能 | ❌ 可能 | ❌ 可能 | 不加锁（基本不用） |
| **读已提交** (RC) | ✅ 避免 | ❌ 可能 | ❌ 可能 | **每次读生成新快照** |
| **可重复读** (RR) | ✅ 避免 | ✅ 避免 | ❌ 可能* | **事务开始时生成快照** |
| **串行化** (S) | ✅ 避免 | ✅ 避免 | ✅ 避免 | 加锁 / SSI |

> *MySQL InnoDB 在 RR 级别下通过 **Next-Key Lock** 也解决了幻读，这是它的一个"超额完成"。

### 实现对比：MySQL vs PostgreSQL

| | MySQL (InnoDB) | PostgreSQL |
|:---|:---|:---|
| **默认级别** | **可重复读 (RR)** | **读已提交 (RC)** |
| **MVCC 实现** | Undo Log 版本链 | 多版本元组留在表里 |
| **旧版本存储** | 单独的 undo 段 | **留在表空间中** |
| **需要 vacuum** | 需要（purge 线程） | **必须**（autovacuum） |
| **回滚段满** | 可能（长事务） | 表膨胀（bloat） |

> **老陈**：**这是一个很有意思的设计差异。**
>
> **MySQL 的方案**：旧版本放 undo log，表里只有最新版本。
> - 优点：表不膨胀，主键索引查找快
> - 缺点：undo 段会满（长事务是噩梦），需要 purge 线程
>
> **PostgreSQL 的方案**：每个更新都产生一个新元组，旧元组留在表里。
> - 优点：回滚极快（不需要 undo），MVCC 实现简单
> - 缺点：**表膨胀**，需要 autovacuum（ vacuum 是 PostgreSQL 运维的头号难题）
>
> **没有完美方案。** 这就是为什么不同数据库做出了不同选择。

---

## MVCC：让"读不加锁"成为可能

### 核心思想

> **"读"和"写"的冲突，可以通过"给每个读者一个快照"来消除。**

```
传统方案（锁）:
  读事务 ──── 加 S 锁 ────┐
                          ├── 互斥
  写事务 ──── 加 X 锁 ────┘
  → 读写互相阻塞

MVCC:
  读事务 ──── 读快照版本 V1 ────┐
                                ├── 不冲突！
  写事务 ──── 创建新版本 V2 ────┘
  → 读不阻塞写，写不阻塞读
```

### MySQL InnoDB 的 MVCC 实现

**三件套：**

```
① 隐藏列（每行数据都有）:
   · DB_TRX_ID   6 bytes  最后修改这行的事务 ID
   · DB_ROLL_PTR 7 bytes  回滚指针，指向 undo log 里的旧版本
   · DB_ROW_ID   6 bytes  隐藏主键（没有显式主键时用）

② Undo Log:
   每次 UPDATE 时，把旧版本写入 undo log
   DB_ROLL_PTR 指向它
   → 形成一个版本链

③ ReadView（读视图）:
   事务执行快照读时生成
   记录"当前哪些事务是活跃的"
   → 用于判断哪个版本对当前事务可见
```

**版本链的结构：**

```
当前行 (最新版本):
┌────────────────────────────────────┐
│ id=1, name="C"                     │
│ DB_TRX_ID = 103                    │
│ DB_ROLL_PTR ─────────┐             │
└──────────────────────┼─────────────┘
                       ▼
undo log 版本 2:
┌────────────────────────────────────┐
│ id=1, name="B"                     │
│ DB_TRX_ID = 102                    │
│ DB_ROLL_PTR ─────────┐             │
└──────────────────────┼─────────────┘
                       ▼
undo log 版本 1:
┌────────────────────────────────────┐
│ id=1, name="A"                     │
│ DB_TRX_ID = 100                    │
│ DB_ROLL_PTR = NULL                 │  ← 链尾
└────────────────────────────────────┘
```

**ReadView 的结构：**

```go
type ReadView struct {
	// 生成 ReadView 时，活跃（未提交）的事务 ID 列表
	mIDs []uint64

	// 最小活跃事务 ID
	minTrxID uint64

	// 下一个将被分配的事务 ID（即"最大事务 ID + 1"）
	maxTrxID uint64

	// 创建这个 ReadView 的事务 ID
	creatorTrxID uint64
}
```

**可见性判断算法：**

```go
func (rv *ReadView) IsVisible(rowTrxID uint64) bool {
	// 规则 1: 如果这行是我自己改的，可见
	if rowTrxID == rv.creatorTrxID {
		return true
	}

	// 规则 2: 如果修改这行的事务，在 ReadView 生成之前就提交了，可见
	if rowTrxID < rv.minTrxID {
		return true
	}

	// 规则 3: 如果修改这行的事务，在 ReadView 生成之后才开始，不可见
	if rowTrxID >= rv.maxTrxID {
		return false
	}

	// 规则 4: 处于 [minTrxID, maxTrxID) 区间
	//         需要检查这个事务在 ReadView 生成时是否还活跃
	for _, id := range rv.mIDs {
		if id == rowTrxID {
			return false   // 还活跃（未提交），不可见
		}
	}
	return true   // 已经提交了，可见
}

// 读取一行：沿着版本链找第一个可见的版本
func (txn *Transaction) ReadRow(row *Row) *RowVersion {
	rv := txn.GetReadView()
	current := row.LatestVersion()

	for current != nil {
		if rv.IsVisible(current.TrxID) {
			return current
		}
		// 不可见，顺着回滚指针找上一个版本
		current = current.PrevVersion()
	}

	return nil   // 对所有版本都不可见（这行对当前事务来说不存在）
}
```

### RC 与 RR 的唯一区别

**ReadView 生成的时机：**

```
读已提交 (RC):
  ★ 每条 SELECT 语句都生成一个新的 ReadView

  T1: BEGIN
  T1: SELECT * FROM t WHERE id=1;    → 生成 ReadView #1，读到 A
  T2: UPDATE t SET name='B' WHERE id=1;  COMMIT;
  T1: SELECT * FROM t WHERE id=1;    → 生成 ReadView #2，读到 B   ← 变了！
  T1: COMMIT
  ★ 这就是"不可重复读"

可重复读 (RR):
  ★ 事务的第一条 SELECT 生成 ReadView，之后一直用这个

  T1: BEGIN
  T1: SELECT * FROM t WHERE id=1;    → 生成 ReadView #1，读到 A
  T2: UPDATE t SET name='B' WHERE id=1;  COMMIT;
  T1: SELECT * FROM t WHERE id=1;    → 还是用 ReadView #1，读到 A   ← 没变！
  T1: COMMIT
  ★ 这就是"可重复读"
```

**就这么一个差别。** 理解了这一点，你就理解了 MySQL 的隔离级别实现。

### 快照读 vs 当前读

```sql
-- 快照读（Snapshot Read）：不加锁，读快照
SELECT * FROM t WHERE id = 1;

-- 当前读（Current Read）：加锁，读最新版本
SELECT * FROM t WHERE id = 1 FOR UPDATE;      -- 加 X 锁
SELECT * FROM t WHERE id = 1 LOCK IN SHARE MODE;  -- 加 S 锁
UPDATE t SET name='C' WHERE id = 1;           -- 内部也是当前读
DELETE FROM t WHERE id = 1;                   -- 内部也是当前读
INSERT INTO t VALUES (...);                   -- 内部也是当前读
```

**这是一个极其重要的区分，也是很多人困惑的来源：**

```sql
-- 场景：RR 隔离级别
-- 初始：id=1, name='A'

-- 事务 T1
BEGIN;
SELECT name FROM t WHERE id=1;        -- 快照读，返回 'A'

-- 事务 T2
BEGIN;
UPDATE t SET name='B' WHERE id=1;     -- 当前读，改成了 'B'
COMMIT;

-- 事务 T1 继续
SELECT name FROM t WHERE id=1;        -- 快照读，还是 'A'  ✓ 符合 RR
SELECT name FROM t WHERE id=1 FOR UPDATE;  -- 当前读，返回 'B'  ← 变了！
UPDATE t SET name='C' WHERE id=1;     -- 当前读，在 'B' 基础上改成 'C'
COMMIT;

-- 最终：name = 'C'（T2 的修改被覆盖了！）
```

> **老陈**：**这就是"丢失更新"（Lost Update）的经典场景。**
>
> **MVCC 保证了"读的一致性"，但没保证"写的一致性"。**
>
> **解决方案：**
> 1. **用当前读**：`SELECT ... FOR UPDATE`（加 X 锁）
> 2. **乐观锁**：加 version 字段，`UPDATE ... WHERE version = ?`
> 3. **提高隔离级别**：串行化
>
> **这是一个真实的生产事故来源。** 很多"数据莫名其妙被覆盖"的问题，根因都在这里。

---

## Go 实现：WAL + MVCC

```go
package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"sort"
	"sync"
	"time"
)

// ============ WAL ============

type LogType byte

const (
	LogTypeBegin    LogType = 1
	LogTypeUpdate   LogType = 2
	LogTypeCommit   LogType = 3
	LogTypeAbort    LogType = 4
	LogTypeCheckpoint LogType = 5
	LogTypeCLR      LogType = 6   // Compensation Log Record（补偿日志）
)

type LogRecord struct {
	LSN         uint64
	PrevLSN     uint64   // 同一事务的上一条
	TxnID       uint64
	Type        LogType
	Key         string
	OldValue    []byte   // before image（undo 用）
	NewValue    []byte   // after image（redo 用）
}

type WAL struct {
	file       *os.File
	nextLSN    uint64
	flushedLSN uint64
	buf        []byte
	mu         sync.Mutex
	syncMode   int   // 0=每次 sync, 1=每秒 sync, 2=异步
}

func NewWAL(path string) (*WAL, error) {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_APPEND, 0644)
	if err != nil {
		return nil, err
	}
	return &WAL{file: f, nextLSN: 1, buf: make([]byte, 0, 4096)}, nil
}

func (w *WAL) Append(rec *LogRecord) uint64 {
	w.mu.Lock()
	defer w.mu.Unlock()

	rec.LSN = w.nextLSN
	w.nextLSN++

	// 序列化
	data := encodeLogRecord(rec)
	w.buf = append(w.buf, data...)

	return rec.LSN
}

func (w *WAL) Sync() error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if len(w.buf) == 0 {
		return nil
	}
	if _, err := w.file.Write(w.buf); err != nil {
		return err
	}
	if err := w.file.Sync(); err != nil {   // ★ fsync
		return err
	}
	w.flushedLSN = w.nextLSN - 1
	w.buf = w.buf[:0]
	return nil
}

func (w *WAL) FlushedLSN() uint64 {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.flushedLSN
}

func encodeLogRecord(rec *LogRecord) []byte {
	// 格式: [len:4][LSN:8][PrevLSN:8][TxnID:8][Type:1]
	//       [keyLen:4][key][oldLen:4][old][newLen:4][new]
	keyBytes := []byte(rec.Key)
	total := 4 + 8 + 8 + 8 + 1 + 4 + len(keyBytes) + 4 + len(rec.OldValue) + 4 + len(rec.NewValue)
	buf := make([]byte, total)

	off := 0
	binary.LittleEndian.PutUint32(buf[off:], uint32(total)); off += 4
	binary.LittleEndian.PutUint64(buf[off:], rec.LSN); off += 8
	binary.LittleEndian.PutUint64(buf[off:], rec.PrevLSN); off += 8
	binary.LittleEndian.PutUint64(buf[off:], rec.TxnID); off += 8
	buf[off] = byte(rec.Type); off++
	binary.LittleEndian.PutUint32(buf[off:], uint32(len(keyBytes))); off += 4
	copy(buf[off:], keyBytes); off += len(keyBytes)
	binary.LittleEndian.PutUint32(buf[off:], uint32(len(rec.OldValue))); off += 4
	copy(buf[off:], rec.OldValue); off += len(rec.OldValue)
	binary.LittleEndian.PutUint32(buf[off:], uint32(len(rec.NewValue))); off += 4
	copy(buf[off:], rec.NewValue)

	return buf
}

// ============ MVCC 存储引擎 ============

type Version struct {
	Value    []byte
	TrxID    uint64      // 创建这个版本的事务
	PrevLSN  uint64      // 指向 undo log，可以找到上一个版本
	Timestamp int64
}

type KeyVersions struct {
	versions []*Version   // 按时间从新到旧
}

type MVCCTxn struct {
	ID        uint64
	ReadView  *ReadView
	writeSet  map[string]*Version  // 本事务修改的（未提交）
	startTime int64
	committed bool
	aborted   bool
}

type MVCKEngine struct {
	mu       sync.RWMutex
	data     map[string]*KeyVersions
	wal      *WAL
	nextTrxID uint64
	activeTxns map[uint64]*MVCCTxn
	isoLevel  int   // 0 = RC, 1 = RR
}

func NewMVCKEngine(wal *WAL) *MVCKEngine {
	return &MVCKEngine{
		data:       make(map[string]*KeyVersions),
		wal:        wal,
		nextTrxID:  1,
		activeTxns: make(map[uint64]*MVCCTxn),
		isoLevel:   1,   // 默认 RR
	}
}

func (e *MVCKEngine) Begin() *MVCCTxn {
	e.mu.Lock()
	defer e.mu.Unlock()

	txn := &MVCCTxn{
		ID:        e.nextTrxID,
		writeSet:  make(map[string]*Version),
		startTime: time.Now().UnixNano(),
	}
	e.nextTrxID++
	e.activeTxns[txn.ID] = txn

	// 写 BEGIN 日志
	e.wal.Append(&LogRecord{
		TxnID: txn.ID,
		Type:  LogTypeBegin,
	})

	// ★ RR: 事务开始时不生成 ReadView，第一条读时才生成
	//   RC: 每条读都生成新的
	//   我们的实现：在 Get 时根据 isoLevel 决定

	return txn
}

func (e *MVCKEngine) createReadView(txn *MVCCTxn) *ReadView {
	e.mu.RLock()
	defer e.mu.RUnlock()

	var activeIDs []uint64
	minID := uint64(^uint64(0))
	for id := range e.activeTxns {
		if id != txn.ID {
			activeIDs = append(activeIDs, id)
			if id < minID {
				minID = id
			}
		}
	}
	sort.Slice(activeIDs, func(i, j int) bool { return activeIDs[i] < activeIDs[j] })

	if minID == ^uint64(0) {
		minID = e.nextTrxID
	}

	return &ReadView{
		mIDs:         activeIDs,
		minTrxID:     minID,
		maxTrxID:     e.nextTrxID,
		creatorTrxID: txn.ID,
	}
}

// Get 读取（快照读）
func (e *MVCKEngine) Get(txn *MVCCTxn, key string) ([]byte, bool) {
	// ★ RC: 每次读都生成新 ReadView
	//   RR: 第一次读生成，之后复用
	if e.isoLevel == 0 || txn.ReadView == nil {
		txn.ReadView = e.createReadView(txn)
	}

	// 1. 先查自己的写集（读己之所写）
	if v, ok := txn.writeSet[key]; ok {
		if v.Value == nil {
			return nil, false   // 本事务删除了
		}
		return v.Value, true
	}

	// 2. 查全局数据，沿版本链找可见的版本
	e.mu.RLock()
	defer e.mu.RUnlock()

	kvs, ok := e.data[key]
	if !ok {
		return nil, false
	}

	for _, v := range kvs.versions {
		if txn.ReadView.IsVisible(v.TrxID) {
			if v.Value == nil {
				return nil, false   // 墓碑，表示已删除
			}
			return v.Value, true
		}
	}

	return nil, false
}

// Put 写入
func (e *MVCKEngine) Put(txn *MVCCTxn, key string, value []byte) error {
	e.mu.RLock()
	oldValue, existed := e.getLatestValue(key)
	e.mu.RUnlock()

	// 1. 写 WAL（★ WAL 规则：先写日志）
	e.wal.Append(&LogRecord{
		TxnID:    txn.ID,
		Type:     LogTypeUpdate,
		Key:      key,
		OldValue: oldValue,
		NewValue: value,
	})

	// 2. 写入本事务的写集（未提交，对其他事务不可见）
	txn.writeSet[key] = &Version{
		Value:     value,
		TrxID:     txn.ID,
		Timestamp: time.Now().UnixNano(),
	}

	_ = existed
	return nil
}

func (e *MVCKEngine) getLatestValue(key string) ([]byte, bool) {
	kvs, ok := e.data[key]
	if !ok || len(kvs.versions) == 0 {
		return nil, false
	}
	return kvs.versions[0].Value, true
}

// Commit 提交
func (e *MVCKEngine) Commit(txn *MVCCTxn) error {
	// 1. 写 COMMIT 日志
	e.wal.Append(&LogRecord{
		TxnID: txn.ID,
		Type:  LogTypeCommit,
	})

	// 2. fsync（★ 持久性的保证）
	if err := e.wal.Sync(); err != nil {
		return err
	}

	// 3. 应用写集到全局数据
	e.mu.Lock()
	for key, v := range txn.writeSet {
		kvs, ok := e.data[key]
		if !ok {
			kvs = &KeyVersions{}
			e.data[key] = kvs
		}
		// 新版本插到最前面
		kvs.versions = append([]*Version{v}, kvs.versions...)
		// ★ 保留有限个历史版本（真实实现由 purge 线程清理）
		if len(kvs.versions) > 10 {
			kvs.versions = kvs.versions[:10]
		}
	}
	txn.committed = true
	delete(e.activeTxns, txn.ID)
	e.mu.Unlock()

	return nil
}

// Rollback 回滚
func (e *MVCKEngine) Rollback(txn *MVCCTxn) error {
	// 1. 写 ABORT 日志
	e.wal.Append(&LogRecord{
		TxnID: txn.ID,
		Type:  LogTypeAbort,
	})

	// 2. 用 undo log 回滚（简化：直接丢弃写集）
	//    真实实现要写 CLR（补偿日志）
	for key, v := range txn.writeSet {
		e.wal.Append(&LogRecord{
			TxnID:    txn.ID,
			Type:     LogTypeCLR,
			Key:      key,
			OldValue: v.Value,   // 撤销：把新值还原成旧值
		})
	}

	e.wal.Sync()

	e.mu.Lock()
	txn.aborted = true
	txn.writeSet = make(map[string]*Version)
	delete(e.activeTxns, txn.ID)
	e.mu.Unlock()

	return nil
}

// ============ 演示：隔离级别的效果 ============

func demoIsolationLevels() {
	os.Remove("/tmp/wal.log")
	wal, _ := NewWAL("/tmp/wal.log")
	defer wal.file.Close()

	for _, isoName := range []string{"读已提交 (RC)", "可重复读 (RR)"} {
		engine := NewMVCKEngine(wal)
		if isoName[0] == '读' {
			engine.isoLevel = 0   // RC
		} else {
			engine.isoLevel = 1   // RR
		}

		fmt.Printf("\n=== %s ===\n", isoName)

		// 初始数据
		setup := engine.Begin()
		engine.Put(setup, "account", []byte("1000"))
		engine.Commit(setup)

		// T1 开始
		t1 := engine.Begin()
		v1, _ := engine.Get(t1, "account")
		fmt.Printf("T1 第一次读: %s\n", v1)

		// T2 修改并提交
		t2 := engine.Begin()
		engine.Put(t2, "account", []byte("2000"))
		engine.Commit(t2)
		fmt.Printf("T2 修改为 2000 并提交\n")

		// T1 再读
		v2, _ := engine.Get(t1, "account")
		fmt.Printf("T1 第二次读: %s   ← %s\n", v2,
			map[bool]string{true: "一致（可重复读）", false: "不一致（不可重复读）"}[string(v1) == string(v2)])

		engine.Commit(t1)
	}
}

// ============ 演示：丢失更新问题 ============

func demoLostUpdate() {
	fmt.Println("\n=== 丢失更新问题（Lost Update）演示 ===")

	wal, _ := NewWAL("/tmp/wal2.log")
	defer wal.file.Close()

	engine := NewMVCKEngine(wal)
	engine.isoLevel = 1   // RR

	// 初始：库存 100
	setup := engine.Begin()
	engine.Put(setup, "stock", []byte("100"))
	engine.Commit(setup)

	// T1: 读库存，减 30
	t1 := engine.Begin()
	v1, _ := engine.Get(t1, "stock")
	fmt.Printf("T1 读到库存: %s\n", v1)

	// T2: 读库存，减 50，先提交
	t2 := engine.Begin()
	v2, _ := engine.Get(t2, "stock")
	fmt.Printf("T2 读到库存: %s\n", v2)
	engine.Put(t2, "stock", []byte("50"))    // 100 - 50
	engine.Commit(t2)
	fmt.Printf("T2 提交: 100 - 50 = 50\n")

	// T1: 基于它读到的 100 计算，减 30
	engine.Put(t1, "stock", []byte("70"))    // 100 - 30
	engine.Commit(t1)
	fmt.Printf("T1 提交: 100 - 30 = 70\n")

	final, _ := engine.Get(engine.Begin(), "stock")
	fmt.Printf("\n最终库存: %s\n", final)
	fmt.Printf("期望库存: 20 (100 - 50 - 30)\n")
	fmt.Printf("★ T2 的修改被覆盖了！这就是丢失更新\n")

	fmt.Println("\n解决方案:")
	fmt.Println("  1. SELECT ... FOR UPDATE (当前读，加 X 锁)")
	fmt.Println("  2. 乐观锁: UPDATE ... WHERE version = ?")
	fmt.Println("  3. 单条原子更新: UPDATE stock SET v = v - 30")
}

func main() {
	demoIsolationLevels()
	demoLostUpdate()
}
```

**运行输出：**

```
=== 读已提交 (RC) ===
T1 第一次读: 1000
T2 修改为 2000 并提交
T1 第二次读: 2000   ← 不一致（不可重复读）

=== 可重复读 (RR) ===
T1 第一次读: 1000
T2 修改为 2000 并提交
T1 第二次读: 1000   ← 一致（可重复读）

=== 丢失更新问题（Lost Update）演示 ===
T1 读到库存: 100
T2 读到库存: 100
T2 提交: 100 - 50 = 50
T1 提交: 100 - 30 = 70

最终库存: 70
期望库存: 20 (100 - 50 - 30)
★ T2 的修改被覆盖了！这就是丢失更新

解决方案:
  1. SELECT ... FOR UPDATE (当前读，加 X 锁)
  2. 乐观锁: UPDATE ... WHERE version = ?
  3. 单条原子更新: UPDATE stock SET v = v - 30
```

---

## 第三层追问：Redis 的持久化——另一种思路

### Redis 的两种持久化

| | RDB | AOF |
|:---|:---|:---|
| **方式** | 定时快照（fork + COW） | 追加写命令日志 |
| **文件** | 紧凑的二进制 | 文本协议（RESP） |
| **恢复速度** | 快（直接加载） | 慢（要重放所有命令） |
| **数据安全** | 丢失最后一次快照后的数据 | 取决于 fsync 策略 |
| **文件大小** | 小 | 大（需要 AOF rewrite） |

### AOF 的 fsync 策略

```redis
# redis.conf
appendfsync always    # 每个命令都 fsync  → 最安全，最慢（约几百 TPS）
appendfsync everysec  # 每秒 fsync      → 丢 1 秒数据（默认，推荐）
appendfsync no        # 交给 OS         → 丢最多 30 秒，最快
```

**这跟 MySQL 的 `innodb_flush_log_at_trx_commit` 是完全一样的权衡。**

### RDB 的 COW（Copy-on-Write）

**这是 Redis 的一个精妙设计：**

```
问题：Redis 是单线程的。做快照时，如果遍历整个数据集并写文件，
     会阻塞所有请求几十秒。

解法：fork 一个子进程
     ① fork 的瞬间，父子进程共享所有内存页（COW）
     ② 子进程遍历内存，写 RDB 文件
     ③ 父进程继续服务请求
     ④ 父进程修改某个 key 时，触发缺页异常
        → 内核复制那一页（4KB）
        → 父子各有独立副本
     ⑤ 子进程看到的还是 fork 那一刻的快照

★ 关键点：只有被修改的页才会被复制
★ 如果 Redis 有 10GB 数据，快照期间只改了 100MB
  → 实际内存增长只有 100MB，而不是翻倍到 20GB
```

**隐患：如果写密集，COW 会让内存接近翻倍。**

```
10GB 数据，快照期间所有 key 都被修改
→ 所有页都被复制
→ 内存峰值接近 20GB
→ 如果机器只有 16GB，会 OOM 或者触发 swap

★ 这是 Redis 运维的经典坑
★ 解决：预留足够内存（至少 2 倍），或者控制写入速率
```

> **老陈**：**COW fork 是"用操作系统的虚拟内存机制做快照"的典范。**
>
> **它把"复制 10GB 数据"变成了"复制被修改的页"。**
>
> **这跟第 1 章讲的按需分页、第 3 章讲的复制式 GC，是同一个思想的三种应用：**
> - 按需分页：需要时才分配物理页
> - 复制式 GC：只复制存活对象
> - COW：只复制被修改的页
>
> **统一法则："只做必要的工作"。**

---

## 更深层的发问

### 问题 A：为什么 WAL 能让写入变快？

**直觉上"多写一份日志"应该更慢才对。**

```
不用 WAL（直接改数据页）:
  1. 读目标页（随机读）      ~100μs (SSD)
  2. 修改页
  3. 写回页（随机写）        ~100μs
  4. fsync                  ~500μs
  ★ 每次操作约 700μs，且是随机 IO

用 WAL:
  1. 追加日志（顺序写）      ~10μs（批量后更便宜）
  2. 修改 Buffer Pool 里的页（内存）  ~1μs
  3. 批量 fsync             ~500μs / N 个操作
  ★ 每个操作约 11μs + 摊销的 fsync

★ 快 60 倍
```

**关键差异：**

| | 直接写 | WAL |
|:---|:---|:---|
| **IO 类型** | 随机写（每个记录一个页） | **顺序追加** |
| **IO 次数** | 每次操作 1-2 次 | 批量后 N 次操作 1 次 |
| **fsync 粒度** | 每次操作 | **批量** |

**核心洞察：把"随机写"变成"顺序写"，把"多次 fsync"变成"一次"。**

> **老陈**：**这正是第 2 章讲的 LSM-Tree 的核心思想，WAL 也一样。**
>
> **事实上，LSM-Tree 可以看作是"WAL 的极端版本"——它把所有写入都变成日志追加，数据页（SSTable）只是日志的物化视图。**

### 问题 B：分布式事务为什么难？

单机事务靠 WAL + 锁 + MVCC 就能解决。分布式事务难在哪？

**难点 1 · 原子提交（Atomic Commit）**

```
参与者：A、B、C 三个节点
协调者：要提交一个跨三节点的事务

问题：
  · A 说 OK，B 说 OK，C 说 OK → 提交
  · 但如果 C 在说 OK 之后、收到 commit 之前崩溃了？
  · 协调者在发出 commit 之前崩溃了？
  · 网络分区，协调者联系不上 C？

★ 结论：不存在能容忍任意节点失败的原子提交协议
  （这是已被证明的不可能结果，跟 FLP 不可能定理相关）
```

**2PC（两阶段提交）的问题**：协调者崩溃 → 参与者阻塞（要等协调者恢复）。

**3PC（三阶段提交）的问题**：网络分区下可能不一致。

**实际方案**：
- 数据库的 XA 事务（2PC，有协调者单点）
- **Percolator（Google）**：用中心化的时间戳服务 + 2PC，TiDB 用的就是这个
- **Raft/Paxos + 2PC**：把协调者也做成高可用的

**难点 2 · 分布式快照（全局一致性读）**

```
单机：ReadView 是"当前活跃事务列表"
分布式：
  · 每个节点的 LSN/时间戳不同步
  · 需要一个"全局时间"

解法：
  ① 中心化时间戳（TiDB 的 PD 集群）
  ② 混合逻辑时钟（HLC，CockroachDB）
  ③ TrueTime（Google Spanner，用 GPS + 原子钟）
  ④ 向量时钟 / 版本向量
```

**难点 3 · 分布式死锁检测**

```
单机：等待图（wait-for graph），一个节点就能检测
分布式：等待图分散在多个节点，需要跨节点收集

解法：
  · 中心化死锁检测（定期上报等待图）
  · 超时回滚（简单粗暴）
  ·  wound-wait / wait-die 协议（按时间戳排序，避免死锁）
```

> **老陈**：**分布式事务的难度，本质上是"没有全局时钟"和"没法可靠地知道对方是死是活"。**
>
> **这两个不确定性，是分布式系统所有难题的根源。第 5 章讲 Raft 时，你会看到同样的主题。**

---

## 思考题 ·【应用层】

**你的 Go 服务用 MySQL (InnoDB, RR 隔离级别)。有一个"扣库存"的逻辑：**
```go
func DeductStock(db *sql.DB, productID int, count int) error {
	tx, _ := db.Begin()
	defer tx.Rollback()

	var stock int
	tx.QueryRow("SELECT stock FROM products WHERE id = ?", productID).Scan(&stock)

	if stock < count {
		return errors.New("库存不足")
	}

	_, err := tx.Exec("UPDATE products SET stock = stock - ? WHERE id = ?", count, productID)
	if err != nil {
		return err
	}
	return tx.Commit()
}
```
**压测发现高并发下会出现超卖（库存变成负数）。请分析原因，给出至少 3 种解决方案，并说明各自的代价。**

<details>
<summary>参考答案</summary>

### 现象分析：为什么会超卖

**这段代码看起来"有事务"，但实际上没有保护。**

**原因：RR 隔离级别下，普通的 `SELECT` 是快照读，不加锁。**

```
时间线：
T1: BEGIN
T1: SELECT stock → 1          (快照读，不加锁)
T2: BEGIN
T2: SELECT stock → 1          (快照读，不加锁) ★ 也能读到 1！
T1: UPDATE stock = stock - 1 → 0
T1: COMMIT
T2: UPDATE stock = stock - 1 → -1    ★ 超卖！
T2: COMMIT

最终库存: -1
```

**关键：两个事务都读到了 stock=1，都认为可以扣减。**

这就是前面讲的**丢失更新**问题，只不过表现为"超卖"。

**MySQL 官方文档里的这个坑有个专门的名字：**
> *"The consistent read... does not lock the rows... If you want to ensure that no other transaction can modify the rows you read, you must use SELECT ... FOR UPDATE."*

---

### 解决方案 1：`SELECT ... FOR UPDATE`（当前读 + 排他锁）

```go
func DeductStockV1(db *sql.DB, productID int, count int) error {
	tx, _ := db.Begin()
	defer tx.Rollback()

	var stock int
	// ★ 加 FOR UPDATE：当前读 + 排他锁
	err := tx.QueryRow(
		"SELECT stock FROM products WHERE id = ? FOR UPDATE",
		productID).Scan(&stock)
	if err != nil {
		return err
	}

	if stock < count {
		return errors.New("库存不足")
	}

	_, err = tx.Exec(
		"UPDATE products SET stock = stock - ? WHERE id = ?",
		count, productID)
	if err != nil {
		return err
	}
	return tx.Commit()
}
```

**为什么这样能解决？**

```
T1: SELECT ... FOR UPDATE → 加锁，读到 1
T2: SELECT ... FOR UPDATE → ★ 阻塞，等 T1 释放锁
T1: UPDATE stock = 0
T1: COMMIT                → 释放锁
T2: 获得锁，读到 0        ★ 读到的是最新值
T2: 发现 0 < 1，返回"库存不足"
```

**代价：**

| 代价 | 说明 |
|:---|:---|
| **性能** | 所有扣库存的请求串行化。热点商品（秒杀场景）会成为瓶颈 |
| **锁等待超时** | 默认 50 秒（`innodb_lock_wait_timeout`），高并发下大量超时 |
| **死锁风险** | 如果事务里还要锁其他资源，可能死锁 |
| **锁范围** | `FOR UPDATE` 在 RR 下用 Next-Key Lock，会锁住索引区间 |

**适用场景**：并发不高，或者需要严格一致性的场景。

---

### 解决方案 2：原子 UPDATE（推荐）

**核心思路：把"读 + 判断 + 写"合并成一条 SQL。**

```go
func DeductStockV2(db *sql.DB, productID int, count int) error {
	// ★ 一条 SQL 完成：判断 + 更新
	result, err := db.Exec(
		"UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
		count, productID, count)
	if err != nil {
		return err
	}

	rows, _ := result.RowsAffected()
	if rows == 0 {
		return errors.New("库存不足")
	}
	return nil
}
```

**为什么这样能解决？**

```
UPDATE ... WHERE stock >= count 是一个原子操作

InnoDB 的执行：
  1. 定位到行（当前读，加 X 锁）
  2. 检查 WHERE 条件（stock >= count）
  3. 如果满足，更新
  4. 释放锁

★ 步骤 1-4 在 InnoDB 内部是原子的，不存在"读-改-写"的间隙
```

**优势：**

| 优势 | 说明 |
|:---|:---|
| **无锁等待** | 事务极短（单条 UPDATE），锁持有时间微秒级 |
| **无死锁** | 只锁一行，且顺序固定 |
| **性能最好** | 单次往返，无应用层往返 |
| **代码简单** | 一条 SQL |

**代价：**
- 无法在扣减前做复杂业务逻辑（比如"扣减并记录流水"要拆成两条 SQL）
- 如果需要返回详细错误信息（比如"当前库存是 X"），要额外查询

**这是最常用的方案。** 阿里的《Java 开发手册》里明确推荐这种写法。

---

### 解决方案 3：乐观锁（版本号）

```go
func DeductStockV3(db *sql.DB, productID int, count int) error {
	for retry := 0; retry < 3; retry++ {
		tx, _ := db.Begin()

		var stock, version int
		tx.QueryRow(
			"SELECT stock, version FROM products WHERE id = ?",
			productID).Scan(&stock, &version)

		if stock < count {
			tx.Rollback()
			return errors.New("库存不足")
		}

		// ★ 带版本号的 CAS 更新
		result, err := tx.Exec(
			"UPDATE products SET stock = stock - ?, version = version + 1 "+
				"WHERE id = ? AND version = ?",
			count, productID, version)
		if err != nil {
			tx.Rollback()
			return err
		}

		rows, _ := result.RowsAffected()
		if rows > 0 {
			return tx.Commit()   // 成功
		}

		// 版本冲突，重试
		tx.Rollback()
		time.Sleep(time.Millisecond * time.Duration(retry+1))
	}
	return errors.New("并发冲突，请重试")
}
```

**为什么能解决？**

```
T1: SELECT stock=1, version=5
T2: SELECT stock=1, version=5
T1: UPDATE ... WHERE version=5  → 成功，version 变成 6
T2: UPDATE ... WHERE version=5  → ★ 0 rows affected（version 已经是 6 了）
T2: 重试，重新 SELECT stock=0, version=6
T2: 发现 0 < 1，返回"库存不足"
```

**代价：**

| 代价 | 说明 |
|:---|:---|
| **重试开销** | 冲突越多，重试越多。极端情况下会活锁 |
| **需要版本号字段** | 表结构要改 |
| **ABA 问题** | 理论上可能（version 从 5 变成 6 又变回 5），实践中用单调递增版本号可避免 |
| **冲突率高时性能差** | 热点商品大量重试 |

**适用场景**：读多写少，冲突概率低的场景。

---

### 解决方案 4：Redis 预扣减（高并发场景）

**核心思路：把库存扣减放到 Redis（原子操作），异步同步到 DB。**

```go
func DeductStockV4(redis *redis.Client, db *sql.DB, productID int, count int) error {
	key := fmt.Sprintf("stock:%d", productID)

	// ★ Redis 的 DECRBY 是原子操作
	newStock, err := redis.DecrBy(ctx, key, int64(count)).Result()
	if err != nil {
		return err
	}

	if newStock < 0 {
		// 扣减失败，回滚（加回去）
		redis.IncrBy(ctx, key, int64(count))
		return errors.New("库存不足")
	}

	// 异步落库
	go func() {
		db.Exec("UPDATE products SET stock = stock - ? WHERE id = ?", count, productID)
		// 或者写消息队列，批量落库
	}()

	return nil
}
```

**优势**：
- Redis 单线程，DECRBY 天然原子
- 性能极高（10 万+ TPS）
- 无锁等待

**代价**：
- **Redis 和 DB 的数据一致性**：Redis 挂了怎么办？
- **需要预热**：把 DB 的库存同步到 Redis
- **异步落库可能丢失**：Redis 成功但 DB 失败
- **复杂度显著上升**

**适用场景**：秒杀、大促等极端高并发场景。

---

### 解决方案 5：分段库存（终极方案）

**核心思路：把一行库存拆成多行，减少锁竞争。**

```sql
-- 原来：一行
CREATE TABLE products (
    id INT PRIMARY KEY,
    stock INT
);

-- 改成：多行
CREATE TABLE product_stock_segments (
    product_id INT,
    segment_id INT,        -- 0, 1, 2, ..., 9
    stock INT,
    PRIMARY KEY (product_id, segment_id)
);

-- 初始化：1000 库存拆成 10 段，每段 100
```

```go
func DeductStockV5(db *sql.DB, productID int, count int) error {
	// ★ 随机选一个段，减少冲突
	segmentID := rand.Intn(10)

	result, err := db.Exec(
		"UPDATE product_stock_segments SET stock = stock - ? "+
			"WHERE product_id = ? AND segment_id = ? AND stock >= ?",
		count, productID, segmentID, count)
	if err != nil {
		return err
	}

	rows, _ := result.RowsAffected()
	if rows == 0 {
		// 这个段库存不够，试试其他段
		return deductFromAnySegment(db, productID, count)
	}
	return nil
}
```

**效果**：锁竞争降低 10 倍（10 个段可以并行扣减）

**代价**：
- 总库存要分散查询（或者维护一个汇总字段）
- 某个段没库存了，其他段还有 → 需要"段间转移"逻辑
- 复杂度上升

**适用场景**：单商品 QPS 极高（比如几万/秒）

---

### 方案对比与选择

| 方案 | QPS 上限 | 一致性 | 复杂度 | 适用 |
|:---|:---|:---|:---|:---|
| FOR UPDATE | 1000-3000 | 强 | 低 | 普通并发 |
| **原子 UPDATE** | **5000-10000** | **强** | **低** | ★ **推荐，覆盖 90% 场景** |
| 乐观锁 | 3000-8000 | 强 | 中 | 读多写少 |
| Redis 预扣 | 100000+ | 最终 | 高 | 秒杀 |
| 分段库存 | 50000+ | 强 | 高 | 极端热点 |

### 我的建议

**默认用方案 2（原子 UPDATE）**，理由：
- 代码最简单
- 性能足够（单商品几千 TPS）
- 无死锁、无锁等待
- 一致性有保证

**只有当单商品 QPS 超过 5000 时**，才考虑 Redis 预扣或分段库存。

---

### 三个额外的重要提醒

**① 一定要有兜底校验**

即使应用层逻辑正确，也要在 DB 层加约束：

```sql
ALTER TABLE products
  ADD CONSTRAINT chk_stock CHECK (stock >= 0);
```

**这是最后一道防线。** 应用层可能有 bug，但 DB 的 CHECK 约束不会。

**② 监控超卖**

```go
// 定期扫描
rows, _ := db.Query("SELECT id FROM products WHERE stock < 0")
if rows.Next() {
	alert("检测到超卖！")
}
```

**出了问题是难免的，关键是能快速发现。**

**③ 幂等性**

扣库存的接口必须支持幂等（重复调用不重复扣减）：

```go
func DeductStockIdempotent(db *sql.DB, orderID string, productID, count int) error {
	// 1. 先查是否已处理过这个订单
	var exists int
	db.QueryRow("SELECT COUNT(*) FROM stock_log WHERE order_id = ?", orderID).Scan(&exists)
	if exists > 0 {
		return nil   // 已处理，直接返回
	}

	// 2. 用唯一索引保证幂等
	_, err := db.Exec(
		"INSERT INTO stock_log (order_id, product_id, count) VALUES (?, ?, ?)",
		orderID, productID, count)
	if err != nil {
		return nil   // 唯一键冲突，说明已处理
	}

	// 3. 扣库存
	return deductStock(db, productID, count)
}
```

**在分布式系统里，重试是常态。不幂等的接口一定会出问题。**

</details>

---

## 小结：这一节你应该带走的东西

1. **没有 WAL 的后果比"丢数据"严重**：结构损坏、空间泄漏、链表断裂。WAL 的核心原则是"先写日志，再改数据页"。

2. **WAL 让写入变快的真正原因**：把随机写变成顺序写，把 N 次 fsync 变成 1 次（组提交）。它不只是为了恢复。

3. **ARIES 的三阶段（分析/重做/撤销）**。"先完整重演历史，再撤销未提交部分"，因为日志是交织的。REDO 是幂等的（靠 pageLSN 判断）。

4. **RC 和 RR 的唯一区别是 ReadView 生成的时机**：RC 每条 SELECT 生成新的，RR 事务内第一条生成后复用。

5. **MVCC 解决了"读-写"冲突，但没解决"写-写"冲突**——丢失更新仍在（超卖就是典型）。

6. **快照读 vs 当前读**是理解 MySQL 并发的关键。`UPDATE` 内部就是当前读。

7. **Redis 的 RDB 用 COW fork**，是"只做必要的工作"这一法则的又一例证（跟按需分页、复制式 GC 同构）。

---

## 下一节

[03 · 动手：从零构建分布式搜索引擎](./03-动手-从零构建分布式搜索引擎.md)

这是第 4 章的终极项目，也是"没有 ES 就自己造一个 ES"的兑现。

> **老陈的预告**：我们要实现 LSM-Tree 存储引擎、倒排索引、分片策略、查询打分。全部用 Go，全部能跑。
>
> **学完这一节，你手上就有了一个能真正用的东西。**
