# 02 · 分布式共识：Raft 完整实现

> *"Raft 论文只有 18 页，但真正理解它需要你亲手实现一遍。"*

---

## 开场：为什么需要共识

> **老陈**：假设你有 3 台机器存同一份数据。客户端要写入 `x = 1`。你怎么保证 3 台机器的数据一致？
>
> **小林**：写三遍，都成功了就返回。
>
> **老陈**：**如果其中一台网络不通呢？**
>
> **小林**：……等它恢复？
>
> **老陈**：**等多久？客户端要一直等着吗？如果它永远不通呢？**
>
> **小林**：……那就先把能写的写了，等它恢复了再同步？
>
> **老陈**：**那如果客户端这时候来读，读到的是哪一份数据？** 而且如果那台机器恢复后，它上面的数据是 `x = 0`，其他两台是 `x = 1`，以谁为准？
>
> **小林**：…………以多数派为准？
>
> **老陈**：**对。你已经想到 Raft 的核心了。** 但这个"多数派"要怎么精确定义？为什么多数派就一定对？如果先后有两个 leader 呢？
>
> **这就是共识算法要解决的问题。我们开始。**

---

## 第一部分：一致性模型

在讲 Raft 之前，先明确"一致"到底是什么意思。

### 四种常见的一致性

| 模型 | 定义 | 直觉 |
|:---|:---|:---|
| **线性一致性** (Linearizable) | 所有操作看起来像在**单个瞬间**原子执行，且顺序符合实时顺序 | **最强**，等价于"只有一个副本" |
| **顺序一致性** (Sequential) | 所有操作按**某个**全局顺序执行，且**每个客户端自己的操作顺序**被保持 | 不保证实时性 |
| **因果一致性** (Causal) | 只保证**有因果关系**的操作顺序 | 并发操作可以任意顺序 |
| **最终一致性** (Eventual) | 如果没有新写入，最终所有副本会一致 | **最弱** |

### 用一个例子区分

```
初始 x = 0

客户端 A:  write(x, 1)    时刻 t=0 开始，t=10 完成
客户端 B:  read(x)        时刻 t=5
客户端 C:  read(x)        时刻 t=15
```

| 模型 | B 读到什么 | C 读到什么 | 允许吗 |
|:---|:---|:---|:---|
| **线性一致性** | 0 | 1 | B 的读在 write 完成前，只能读到 0 |
| **顺序一致性** | 0 或 1 | 0 或 1 | 但要保证 B、C 看到一致的顺序 |
| **最终一致性** | 0 或 1 | 0 或 1 | 无约束 |

**线性一致性的关键**：一旦写入完成（t=10），**之后的所有读都必须看到新值**。

### 为什么线性一致性重要但难

```
场景：分布式锁

客户端 A 获取锁 → 执行操作 → 释放锁
客户端 B 尝试获取锁

如果系统不是线性一致的:
  · A 释放锁后，B 可能还能"获取"到锁（因为某个副本还认为 A 持有）
  · → 两个客户端同时持有锁 → 数据损坏
```

**etcd/ZooKeeper 提供线性一致性，就是因为它们用 Raft/Zab 保证。**

**代价**：每次写都要等多数派确认（跨机器网络往返）。

---

## 第二部分：Raft 原理

### Raft 的三个子问题

Raft 把共识拆成三个相对独立的子问题：

```
① Leader 选举 (Leader Election)
   · 集群中必须恰好有一个 leader
   · leader 挂了要能选出新的

② 日志复制 (Log Replication)
   · leader 接收客户端请求，写入自己的日志
   · 复制给所有 follower
   · 多数派确认后提交

③ 安全性 (Safety)
   · ★ 保证"已提交的日志不会丢失"
   · 这是最难的部分
```

### 三种角色

```
┌──────────┐
│  Leader  │  处理所有客户端请求，发送心跳，复制日志
└──────────┘
     │ 选举超时
     ▼
┌──────────┐
│ Candidate│  发起选举，请求投票
└──────────┘
     │ 获得多数票 / 发现新 leader
     ▼
┌──────────┐
│ Follower │  被动响应，不主动发请求
└──────────┘
```

### Term（任期）

**Term 是 Raft 的"逻辑时钟"。**

```
term 1        term 2        term 3        term 4
├───────────┼─────────────┼────────┼──────────────
│ leader A  │  选举失败    │leader B│  选举中
│           │ (split vote)│        │
└───────────┴─────────────┴────────┴──────────────
                                          时间 ──►

规则：
 · 每个 term 最多一个 leader
 · term 单调递增
 · 每个节点持久化保存 currentTerm
 · ★ 节点收到更大 term 的请求 → 立即更新自己的 term，并变成 follower
```

**Term 的作用**：检测"过期的 leader"。

```
场景：旧的 leader A 被网络隔离
      集群选出了新 leader B（term 3）
      旧 leader A 恢复，还以为自己是 leader（term 2）
      
A 发送 AppendEntries(term=2) 给其他节点
其他节点: 你的 term 比我小，拒绝！
         顺便告诉 A: 现在 term 是 3
A: 收到更大 term → 立即变成 follower ★
```

### 选举的详细流程

```
① Follower 在 electionTimeout（150-300ms 随机）内没收到心跳
   → 变成 Candidate

② Candidate:
   · currentTerm++
   · 给自己投票
   · 重置 election timer
   · 向所有节点发送 RequestVote RPC

③ 等待结果：
   · 获得多数票 → 成为 Leader，立即发送心跳
   · 收到合法 Leader 的心跳 → 变回 Follower
   · 超时（split vote，没人获得多数）→ 开始新一轮选举（term++）

④ ★ 投票规则（关键！）：
   每个节点在每个 term 只能投一票
   且只有在"候选人的日志至少跟我一样新"时才投票
```

**为什么 electionTimeout 要随机？**

```
如果所有节点超时时间一样:
  所有 follower 同时变成 candidate
  所有 candidate 同时发起投票
  → 可能每个 candidate 都得一票（自己）
  → split vote，选举失败
  → 又同时超时，又 split vote...
  → ★ 活锁

随机化（150-300ms）:
  某个节点先超时，它有先发优势
  → 大概率能拿到多数票
```

### ★ 投票限制：日志新旧比较

这是 Raft 安全性的第一条保证。

```go
// 判断候选人的日志是否至少跟我一样新
func (rf *Raft) isLogUpToDate(candidateLastLogIndex, candidateLastLogTerm int) bool {
	myLastIndex := rf.getLastLogIndex()
	myLastTerm := rf.getLastLogTerm()

	// 比较最后一条日志的 term
	if candidateLastLogTerm != myLastTerm {
		return candidateLastLogTerm > myLastTerm
	}
	// term 相同，比较长度
	return candidateLastLogIndex >= myLastIndex
}
```

**为什么这样能保证安全？**

```
引理：如果一个候选人的日志"至少跟多数派一样新"，
      那么它一定包含了所有已提交的日志。

证明思路：
  ① 已提交的日志 = 被多数派复制的日志
  ② 候选人要当选，必须获得多数派的票
  ③ 这两个"多数派"必然有交集（抽屉原理）
  ④ 交集里的节点，日志至少跟候选人一样新（否则不会投票）
  → 所以候选人包含了所有已提交的日志  ∎
```

### 日志复制

```
客户端 → Leader: SET x=1

Leader:
  ① 追加到本地日志（未提交）
  ② 并行发送 AppendEntries 给所有 Follower
  ③ 等待多数派响应
  ④ 提交（应用到状态机）
  ⑤ 返回成功给客户端
  ⑥ 下次 AppendEntries 时通知 Follower 提交
```

**AppendEntries RPC 的内容：**

```go
type AppendEntriesArgs struct {
	Term         int        // leader 的 term
	LeaderID     int

	PrevLogIndex int        // ★ 新日志条目的前一条的索引
	PrevLogTerm  int        // ★ 新日志条目的前一条的 term
	Entries      []LogEntry // 要复制的日志（心跳时为空）
	LeaderCommit int        // leader 已提交的索引
}

type AppendEntriesReply struct {
	Term          int   // 当前 term，用于 leader 更新自己
	Success       bool

	// ★ 优化：冲突时快速回退
	ConflictIndex int
	ConflictTerm  int
}
```

### ★ 一致性检查（Consistency Check）

**这是日志复制的核心机制。**

```
Leader 发送 AppendEntries 时带上 prevLogIndex 和 prevLogTerm

Follower 检查：
  "我的日志在 prevLogIndex 位置的 term，是不是等于 prevLogTerm？"
  
  · 相等 → 我的日志跟 leader 的前缀一致，接受
  · 不相等 → 拒绝！

Leader 收到拒绝：
  · 递减 nextIndex，重试
  · 直到找到匹配的位置
```

**为什么这样能保证日志一致？**

**归纳证明**：

```
初始状态：所有日志为空，满足"日志匹配特性"

归纳假设：AppendEntries 成功返回时，
         follower 在 prevLogIndex 及之前的所有日志与 leader 相同

归纳步骤：
  · Leader 只在 follower 的日志匹配 prevLogIndex/prevLogTerm 时才追加
  · 追加是"覆盖"式的（删除冲突的，追加新的）
  · 所以新加入的日志也与 leader 相同

结论（日志匹配特性 Log Matching Property）：
  如果两个日志在相同索引处的 term 相同，那么：
  ① 这条日志的内容相同
  ② 这条日志之前的所有日志也相同
```

---

## ★ 最关键的问题：为什么只能提交当前 term 的日志

这是 Raft 论文里 Figure 8 描述的场景，也是**实现 Raft 最容易写错的地方**。

> **老陈**：**现在我们来亲手构造这个 bug。** 假设我们不做这个限制——leader 可以提交任何"被多数派复制"的日志，包括旧 term 的。

### 反例构造

```
5 个节点：S1, S2, S3, S4, S5

───── 阶段 1: term 2 ─────
S1 是 leader (term 2)
S1 复制日志 index=2 (term=2) 给 S2
  S1: [1(t1), 2(t2)]
  S2: [1(t1), 2(t2)]
  S3: [1(t1)]          ← 没收到
  S4: [1(t1)]
  S5: [1(t1)]

S1 崩溃
★ 注意：index=2 只被 2 个节点复制，未达到多数派（3 个），所以未提交

───── 阶段 2: term 3 ─────
S5 成为 leader (term 3)
  （S5 的日志 [1(t1)]，但 S3、S4 的日志也一样新，它们会投票给 S5）
S5 收到客户端请求，写入 index=3 (term=3)
S5 只复制到自己，然后崩溃
  S5: [1(t1), 3(t3)]    ← index=2 空着！因为 S5 不知道 S1 的 index=2
  
───── 阶段 3: term 4 ─────
S1 重启，成为 leader (term 4)
  （S1 的日志 [1(t1), 2(t2)] 比多数派新，能当选）
S1 继续复制 index=2 (term=2) 给 S3
  S1: [1(t1), 2(t2)]
  S2: [1(t1), 2(t2)]
  S3: [1(t1), 2(t2)]    ← ★ 现在 index=2 达到多数派了！
  S4: [1(t1)]
  S5: [1(t1), 3(t3)]

★ 关键问题：S1 现在能不能提交 index=2？

如果不加限制（错误做法）：
  S1 看到 index=2 被多数派复制 → 提交 → 应用 → 返回客户端

───── 阶段 4: term 5 ─────
S1 崩溃
S5 成为 leader (term 5)
  （S5 的最后日志是 index=3, term=3
    S2/S3/S4 的最后日志是 index=2, term=2
    ★ 3 < 2？不，term 3 > term 2，所以 S5 的日志更新！
    S5 能获得 S2/S3/S4 中某些节点的票）

S5 复制自己的 index=3 给所有节点
  → ★ 所有节点在 index=2 的位置被覆盖成 S5 的内容

结果：
  index=2 的日志（term=2）被覆盖了
  但它已经被提交并应用了！
  
  ★★ 已提交的日志丢失了！这是严重的安全违规！
```

### 正确的做法

**Raft 的规则：**
> **Leader 只能提交当前 term 的日志。旧 term 的日志只能通过"提交当前 term 的日志"来间接提交。**

```go
// 正确的提交判断
func (rf *Raft) updateCommitIndex() {
	// 只对当前 term 的日志计数
	for n := rf.commitIndex + 1; n <= rf.getLastLogIndex(); n++ {
		if rf.log[n].Term != rf.currentTerm {
			continue   // ★ 跳过旧 term 的日志
		}
		// 统计有多少节点复制了这条日志
		count := 1   // 自己
		for i := range rf.peers {
			if i != rf.me && rf.matchIndex[i] >= n {
				count++
			}
		}
		if count > len(rf.peers)/2 {
			rf.commitIndex = n   // ★ 提交这一条，同时也提交了它之前的所有日志
		}
	}
}
```

**为什么这样就安全了？**

```
关键：一旦提交了一条当前 term 的日志 N，
      根据日志匹配特性，所有前于 N 的日志也都被"间接提交"了。

为什么不会重演上面的反例？

回到阶段 3：
  S1 (term 4) 复制 index=2 (term=2) 给 S3，达到多数派
  ★ 但 S1 不能提交 index=2，因为它不是当前 term（term 4）的日志
  
  S1 必须写入一条新日志（term 4），等它被多数派复制后提交
  这时才能间接提交 index=2

如果 S1 在写完 term=4 的日志之前就崩溃了：
  → index=2 从未提交
  → 后续的 leader 覆盖它是安全的（因为它没提交过）
  ★ 安全！
```

> **老陈**：**这个反例的精髓在于：**
>
> **"多数派复制过" ≠ "已提交"。**
>
> 一条日志可能被多数派复制，但在它被"确认提交"之前，它可能又被覆盖。
> **只有当你提交了一条当前 term 的日志，之前的所有日志才"锁定"了。**
>
> **这是一个非常微妙的点，也是我见过最多的 Raft 实现 bug。**
>
> **如果你想验证自己写对了，就跑这个测试：**
> ```
> 测试用例：Figure 8 Unavailability
> 1. 5 个节点
> 2. 让 leader 复制一些日志但故意让部分节点收不到
> 3. 让 leader 崩溃
> 4. 让一个日志较短的节点成为 leader
> 5. 让它写入日志
> 6. 再让原来的 leader 恢复并成为 leader
> 7. 检查之前"看起来已复制"的日志是否被覆盖
> 8. ★ 关键：如果被覆盖的日志从未被提交，这是正确的
> ```

---

## 完整实现

```go
package main

import (
	"fmt"
	"math/rand"
	"sync"
	"time"
)

// ============ 日志条目 ============

type LogEntry struct {
	Term    int
	Index   int
	Command interface{}
}

// ============ 角色 ============

type Role int

const (
	Follower  Role = 0
	Candidate Role = 1
	Leader    Role = 2
)

func (r Role) String() string {
	switch r {
	case Follower:
		return "Follower"
	case Candidate:
		return "Candidate"
	case Leader:
		return "Leader"
	}
	return "?"
}

// ============ Raft 节点 ============

type Raft struct {
	mu sync.Mutex

	// 节点 ID 和集群信息
	me     int
	peers  []*Raft   // 简化：直接引用其他节点

	// 持久化状态（★ 真实实现要落盘）
	currentTerm int
	votedFor    int
	log         []LogEntry

	// 易失状态
	commitIndex int
	lastApplied int

	// Leader 专用（选举后重置）
	nextIndex  []int
	matchIndex []int

	// 角色和计时器
	role            Role
	lastHeartbeat   time.Time
	electionTimeout time.Duration

	// 状态机（应用层）
	stateMachine map[string]string

	// 用于测试
	applyCh chan ApplyMsg
	stopCh  chan struct{}
}

type ApplyMsg struct {
	Index   int
	Command interface{}
}

func NewRaft(me int, peers []*Raft) *Raft {
	rf := &Raft{
		me:              me,
		peers:           peers,
		currentTerm:     0,
		votedFor:        -1,
		log:             []LogEntry{{Term: 0, Index: 0}},   // 哨兵，索引从 1 开始
		commitIndex:     0,
		lastApplied:     0,
		nextIndex:       make([]int, len(peers)),
		matchIndex:      make([]int, len(peers)),
		role:            Follower,
		lastHeartbeat:   time.Now(),
		electionTimeout: time.Duration(0),
		stateMachine:    make(map[string]string),
		applyCh:         make(chan ApplyMsg, 100),
		stopCh:          make(chan struct{}),
	}
	rf.resetElectionTimeout()
	return rf
}

func (rf *Raft) resetElectionTimeout() {
	// 150-300ms 随机
	rf.electionTimeout = time.Duration(150+rand.Intn(150)) * time.Millisecond
}

// ============ 日志访问辅助 ============

func (rf *Raft) getLastLogIndex() int {
	return rf.log[len(rf.log)-1].Index
}

func (rf *Raft) getLastLogTerm() int {
	return rf.log[len(rf.log)-1].Term
}

func (rf *Raft) getLogTerm(index int) int {
	if index < 0 || index >= len(rf.log) {
		return -1
	}
	return rf.log[index].Term
}

// ============ 主循环 ============

func (rf *Raft) Start() {
	go rf.electionLoop()
	go rf.applyLoop()
}

func (rf *Raft) electionLoop() {
	for {
		select {
		case <-rf.stopCh:
			return
		default:
		}

		rf.mu.Lock()
		role := rf.role
		elapsed := time.Since(rf.lastHeartbeat)
		timeout := rf.electionTimeout
		rf.mu.Unlock()

		if role != Leader && elapsed > timeout {
			rf.startElection()
		}

		if role == Leader {
			// Leader 发送心跳
			rf.sendHeartbeats()
			time.Sleep(50 * time.Millisecond)
		} else {
			time.Sleep(10 * time.Millisecond)
		}
	}
}

// ============ 选举 ============

type RequestVoteArgs struct {
	Term         int
	CandidateID  int
	LastLogIndex int
	LastLogTerm  int
}

type RequestVoteReply struct {
	Term        int
	VoteGranted bool
}

func (rf *Raft) startElection() {
	rf.mu.Lock()

	rf.role = Candidate
	rf.currentTerm++
	rf.votedFor = rf.me
	rf.resetElectionTimeout()
	rf.lastHeartbeat = time.Now()

	args := RequestVoteArgs{
		Term:         rf.currentTerm,
		CandidateID:  rf.me,
		LastLogIndex: rf.getLastLogIndex(),
		LastLogTerm:  rf.getLastLogTerm(),
	}

	votes := 1   // 自己的票
	voteCh := make(chan bool, len(rf.peers)-1)

	rf.mu.Unlock()

	// 并行向所有节点请求投票
	for i := range rf.peers {
		if i == rf.me {
			continue
		}
		go func(peerIdx int) {
			reply := RequestVoteReply{}
			if rf.peers[peerIdx] != nil {
				rf.peers[peerIdx].RequestVote(&args, &reply)
			}
			voteCh <- reply.VoteGranted
		}(i)
	}

	// 收集投票
	go func() {
		needed := len(rf.peers)/2 + 1
		got := 1
		for i := 0; i < len(rf.peers)-1; i++ {
			granted := <-voteCh
			if granted {
				got++
			}
			if got >= needed {
				rf.becomeLeader()
				return
			}
		}
	}()
}

func (rf *Raft) RequestVote(args *RequestVoteArgs, reply *RequestVoteReply) {
	rf.mu.Lock()
	defer rf.mu.Unlock()

	reply.Term = rf.currentTerm
	reply.VoteGranted = false

	// 规则 1: 请求的 term 比我小，拒绝
	if args.Term < rf.currentTerm {
		return
	}

	// 规则 2: 请求的 term 更大，更新自己的 term 并变回 follower
	if args.Term > rf.currentTerm {
		rf.currentTerm = args.Term
		rf.role = Follower
		rf.votedFor = -1
	}

	// 规则 3: 已经投过票了（且不是投给这个候选人），拒绝
	if rf.votedFor != -1 && rf.votedFor != args.CandidateID {
		return
	}

	// ★ 规则 4: 日志新旧检查（这是安全性的关键！）
	myLastTerm := rf.getLastLogTerm()
	myLastIndex := rf.getLastLogIndex()

	logUpToDate := false
	if args.LastLogTerm > myLastTerm {
		logUpToDate = true
	} else if args.LastLogTerm == myLastTerm && args.LastLogIndex >= myLastIndex {
		logUpToDate = true
	}

	if !logUpToDate {
		return
	}

	// 投票
	rf.votedFor = args.CandidateID
	reply.VoteGranted = true
	rf.lastHeartbeat = time.Now()   // 重置选举计时器
	rf.resetElectionTimeout()
}

func (rf *Raft) becomeLeader() {
	rf.mu.Lock()
	defer rf.mu.Unlock()

	if rf.role != Candidate {
		return   // 已经变成 follower 了
	}

	rf.role = Leader
	fmt.Printf("[节点 %d] 成为 Leader (term %d)\n", rf.me, rf.currentTerm)

	// 初始化 nextIndex 和 matchIndex
	lastIdx := rf.getLastLogIndex()
	for i := range rf.peers {
		rf.nextIndex[i] = lastIdx + 1
		rf.matchIndex[i] = 0
	}

	// 立即发送心跳
	go rf.sendHeartbeats()
}

// ============ 日志复制 ============

type AppendEntriesArgs struct {
	Term         int
	LeaderID     int
	PrevLogIndex int
	PrevLogTerm  int
	Entries      []LogEntry
	LeaderCommit int
}

type AppendEntriesReply struct {
	Term    int
	Success bool

	// 快速回退优化
	ConflictIndex int
	ConflictTerm  int
}

func (rf *Raft) sendHeartbeats() {
	rf.mu.Lock()
	if rf.role != Leader {
		rf.mu.Unlock()
		return
	}
	term := rf.currentTerm
	rf.mu.Unlock()

	for i := range rf.peers {
		if i == rf.me {
			continue
		}
		go rf.replicateTo(i, term)
	}
}

func (rf *Raft) replicateTo(peerIdx int, term int) {
	rf.mu.Lock()
	if rf.role != Leader || rf.currentTerm != term {
		rf.mu.Unlock()
		return
	}

	nextIdx := rf.nextIndex[peerIdx]
	prevLogIndex := nextIdx - 1
	prevLogTerm := rf.getLogTerm(prevLogIndex)

	var entries []LogEntry
	if nextIdx <= rf.getLastLogIndex() {
		entries = make([]LogEntry, rf.getLastLogIndex()-nextIdx+1)
		copy(entries, rf.log[nextIdx:])
	}

	args := AppendEntriesArgs{
		Term:         rf.currentTerm,
		LeaderID:     rf.me,
		PrevLogIndex: prevLogIndex,
		PrevLogTerm:  prevLogTerm,
		Entries:      entries,
		LeaderCommit: rf.commitIndex,
	}
	rf.mu.Unlock()

	reply := AppendEntriesReply{}
	if rf.peers[peerIdx] != nil {
		rf.peers[peerIdx].AppendEntries(&args, &reply)
	}

	rf.mu.Lock()
	defer rf.mu.Unlock()

	if rf.role != Leader || rf.currentTerm != term {
		return
	}

	// 收到更大的 term，变成 follower
	if reply.Term > rf.currentTerm {
		rf.currentTerm = reply.Term
		rf.role = Follower
		rf.votedFor = -1
		return
	}

	if reply.Success {
		// 更新 nextIndex 和 matchIndex
		if len(entries) > 0 {
			rf.nextIndex[peerIdx] = nextIdx + len(entries)
			rf.matchIndex[peerIdx] = rf.nextIndex[peerIdx] - 1
		}
		// 更新 commitIndex
		rf.updateCommitIndex()
	} else {
		// 冲突，回退 nextIndex
		if reply.ConflictTerm != 0 {
			// 优化：跳到冲突 term 的最后一条日志
			found := false
			for i := rf.getLastLogIndex(); i >= 1; i-- {
				if rf.log[i].Term == reply.ConflictTerm {
					rf.nextIndex[peerIdx] = i + 1
					found = true
					break
				}
			}
			if !found {
				rf.nextIndex[peerIdx] = reply.ConflictIndex
			}
		} else {
			rf.nextIndex[peerIdx] = reply.ConflictIndex
		}
		if rf.nextIndex[peerIdx] < 1 {
			rf.nextIndex[peerIdx] = 1
		}
	}
}

// ★ 关键：只在当前 term 的日志达到多数派时才提交
func (rf *Raft) updateCommitIndex() {
	// 从后往前找第一个满足条件的
	for n := rf.getLastLogIndex(); n > rf.commitIndex; n-- {
		// ★ 只统计当前 term 的日志
		if rf.log[n].Term != rf.currentTerm {
			continue
		}

		count := 1   // leader 自己
		for i := range rf.peers {
			if i != rf.me && rf.matchIndex[i] >= n {
				count++
			}
		}

		if count > len(rf.peers)/2 {
			rf.commitIndex = n
			break   // ★ 提交 n 的同时，n 之前的所有日志都被间接提交了
		}
	}
}

func (rf *Raft) AppendEntries(args *AppendEntriesArgs, reply *AppendEntriesReply) {
	rf.mu.Lock()
	defer rf.mu.Unlock()

	reply.Term = rf.currentTerm
	reply.Success = false

	// 规则 1: term 太小，拒绝
	if args.Term < rf.currentTerm {
		return
	}

	// 规则 2: 收到合法 leader 的消息，更新 term 并变回 follower
	if args.Term >= rf.currentTerm {
		rf.currentTerm = args.Term
		rf.role = Follower
		rf.votedFor = -1
	}
	rf.lastHeartbeat = time.Now()
	rf.resetElectionTimeout()

	// ★ 规则 3: 一致性检查
	if args.PrevLogIndex > 0 {
		if args.PrevLogIndex >= len(rf.log) {
			// 我的日志太短
			reply.ConflictIndex = len(rf.log)
			reply.ConflictTerm = 0
			return
		}
		if rf.log[args.PrevLogIndex].Term != args.PrevLogTerm {
			// term 不匹配
			reply.ConflictTerm = rf.log[args.PrevLogIndex].Term
			// 找到这个 term 的第一条日志
			conflictIdx := args.PrevLogIndex
			for conflictIdx > 1 && rf.log[conflictIdx-1].Term == reply.ConflictTerm {
				conflictIdx--
			}
			reply.ConflictIndex = conflictIdx
			return
		}
	}

	// 规则 4: 追加日志（覆盖冲突的）
	for _, entry := range args.Entries {
		if entry.Index < len(rf.log) {
			if rf.log[entry.Index].Term != entry.Term {
				// 冲突，删除这条及之后的所有日志
				rf.log = rf.log[:entry.Index]
			} else {
				// 已存在且相同，跳过
				continue
			}
		}
		rf.log = append(rf.log, entry)
	}

	// 规则 5: 更新 commitIndex
	if args.LeaderCommit > rf.commitIndex {
		lastNewEntry := args.PrevLogIndex + len(args.Entries)
		if args.LeaderCommit < lastNewEntry {
			rf.commitIndex = args.LeaderCommit
		} else {
			rf.commitIndex = lastNewEntry
		}
	}

	reply.Success = true
}

// ============ 应用到状态机 ============

func (rf *Raft) applyLoop() {
	for {
		select {
		case <-rf.stopCh:
			return
		default:
		}

		rf.mu.Lock()
		if rf.commitIndex > rf.lastApplied {
			rf.lastApplied++
			entry := rf.log[rf.lastApplied]
			cmd := entry.Command
			rf.mu.Unlock()

			// 应用到状态机
			rf.applyCommand(cmd)

			rf.applyCh <- ApplyMsg{Index: rf.lastApplied, Command: cmd}
		} else {
			rf.mu.Unlock()
			time.Sleep(10 * time.Millisecond)
		}
	}
}

func (rf *Raft) applyCommand(cmd interface{}) {
	rf.mu.Lock()
	defer rf.mu.Unlock()

	if kv, ok := cmd.(KVCommand); ok {
		if kv.Op == "SET" {
			rf.stateMachine[kv.Key] = kv.Value
		} else if kv.Op == "DEL" {
			delete(rf.stateMachine, kv.Key)
		}
	}
}

type KVCommand struct {
	Op    string
	Key   string
	Value string
}

// ============ 客户端接口 ============

func (rf *Raft) Submit(cmd interface{}) (bool, error) {
	rf.mu.Lock()
	if rf.role != Leader {
		rf.mu.Unlock()
		return false, fmt.Errorf("not leader")
	}

	entry := LogEntry{
		Term:    rf.currentTerm,
		Index:   len(rf.log),
		Command: cmd,
	}
	rf.log = append(rf.log, entry)
	index := entry.Index
	term := rf.currentTerm
	rf.mu.Unlock()

	// 立即复制
	rf.sendHeartbeats()

	// 等待提交
	for i := 0; i < 100; i++ {   // 最多等 1 秒
		rf.mu.Lock()
		committed := rf.commitIndex >= index
		stillLeader := rf.role == Leader && rf.currentTerm == term
		rf.mu.Unlock()

		if committed {
			return true, nil
		}
		if !stillLeader {
			return false, fmt.Errorf("lost leadership")
		}
		time.Sleep(10 * time.Millisecond)
	}

	return false, fmt.Errorf("timeout")
}

// ============ 演示 ============

func demoRaft() {
	fmt.Println("=== Raft 集群演示 ===\n")

	const numNodes = 5
	nodes := make([]*Raft, numNodes)
	peers := make([]*Raft, numNodes)

	// 创建节点
	for i := 0; i < numNodes; i++ {
		nodes[i] = NewRaft(i, peers)
		peers[i] = nodes[i]
	}

	// 启动
	for _, n := range nodes {
		n.Start()
	}

	time.Sleep(1 * time.Second)

	// 找到 leader
	var leader *Raft
	for _, n := range nodes {
		n.mu.Lock()
		if n.role == Leader {
			leader = n
		}
		n.mu.Unlock()
	}

	if leader == nil {
		fmt.Println("没有选出 leader")
		return
	}

	fmt.Printf("Leader 是节点 %d\n\n", leader.me)

	// 提交几个命令
	cmds := []KVCommand{
		{Op: "SET", Key: "name", Value: "alice"},
		{Op: "SET", Key: "age", Value: "30"},
		{Op: "SET", Key: "city", Value: "Beijing"},
	}

	for _, cmd := range cmds {
		ok, err := leader.Submit(cmd)
		status := "成功"
		if !ok {
			status = "失败: " + err.Error()
		}
		fmt.Printf("提交 %s %s=%s: %s\n", cmd.Op, cmd.Key, cmd.Value, status)
	}

	time.Sleep(500 * time.Millisecond)

	// 检查所有节点的状态机是否一致
	fmt.Println("\n各节点状态机:")
	consistent := true
	expected := ""
	for i, n := range nodes {
		n.mu.Lock()
		sm := fmt.Sprintf("name=%s age=%s city=%s",
			n.stateMachine["name"], n.stateMachine["age"], n.stateMachine["city"])
		if i == leader.me {
			expected = sm
		}
		fmt.Printf("  节点 %d: %s\n", i, sm)
		n.mu.Unlock()
	}

	for i, n := range nodes {
		n.mu.Lock()
		sm := fmt.Sprintf("name=%s age=%s city=%s",
			n.stateMachine["name"], n.stateMachine["age"], n.stateMachine["city"])
		n.mu.Unlock()
		if sm != expected {
			consistent = false
			fmt.Printf("  ⚠️ 节点 %d 不一致！\n", i)
		}
	}

	if consistent {
		fmt.Println("\n✓ 所有节点状态一致")
	}

	// 停止
	for _, n := range nodes {
		close(n.stopCh)
	}
}

func main() {
	rand.Seed(time.Now().UnixNano())
	demoRaft()
}
```

**运行输出：**

```
=== Raft 集群演示 ===

[节点 3] 成为 Leader (term 1)
Leader 是节点 3

提交 SET name=alice: 成功
提交 SET age=30: 成功
提交 SET city=Beijing: 成功

各节点状态机:
  节点 0: name=alice age=30 city=Beijing
  节点 1: name=alice age=30 city=Beijing
  节点 2: name=alice age=30 city=Beijing
  节点 3: name=alice age=30 city=Beijing
  节点 4: name=alice age=30 city=Beijing

✓ 所有节点状态一致
```

---

## 第三部分：Raft 的工程实践

### etcd 的 Raft 实现

etcd 用的 Raft 库（`go.etcd.io/raft`）已经是很多分布式系统的基础。它相对论文做了这些优化：

| 优化 | 说明 |
|:---|:---|
| **Prevote** | 选举前先"预投票"，避免网络隔离的节点频繁发起选举（term 暴涨） |
| **Leader Lease** | leader 在租约期内可以本地读，不需要走 Raft 日志 |
| **ReadIndex** | 线性一致性读的优化：记录 commitIndex，等状态机追上 |
| **批量复制** | 累积多个日志条目一起发送 |
| **流水线复制** | 不等上一个响应就发下一个（需要窗口控制） |
| **快照** | 日志太长时做快照，压缩日志 |
| **Learner** | 新加入的节点先作为 learner（不投票），追上后再变成 voter |

### 线性一致性读的三种方案

```
方案 1: 走 Raft 日志（最慢但最简单）
  读请求 → 写日志 → 复制 → 提交 → 应用 → 返回
  ★ 每次读都要一次 Raft 往返

方案 2: ReadIndex（etcd 默认）
  ① leader 记录当前 commitIndex
  ② 发送一轮心跳确认自己还是 leader（防止脑裂）
  ③ 等状态机应用到 commitIndex
  ④ 返回本地读的结果
  ★ 只需要一轮心跳（比日志复制轻量），仍然是线性一致的

方案 3: Lease Read（最快但有风险）
  leader 在租约期内（比如 electionTimeout 的 90%）直接本地读
  ★ 依赖时钟！如果时钟漂移，可能破坏线性一致性
```

> **老陈**：**方案 3 的风险是个经典问题。**
>
> **Google 的 Spanner 用 TrueTime（GPS + 原子钟）把时钟误差限制在 7ms 以内，才敢用类似方案。**
>
> **普通机器用 NTP，时钟误差可能到几百毫秒，绝对不能依赖。**
>
> **这是"硬件保证决定软件设计"的又一个例子。**

### 分布式锁的正确实现

用 Raft（etcd）实现分布式锁：

```go
type DistributedLock struct {
	client *etcd.Client
	key    string
	myID   string   // 唯一标识（比如 UUID）
	lease  etcd.LeaseID
}

func (l *DistributedLock) Lock(ctx context.Context, ttl int) error {
	// 1. 创建租约（自动过期，防止死锁）
	lease, err := l.client.Grant(ctx, int64(ttl))
	if err != nil {
		return err
	}
	l.lease = lease.ID

	// 2. 用事务尝试获取锁
	//    ★ 关键：用 CAS（Compare-And-Swap）
	txn := l.client.Txn(ctx).
		If(clientv3.Compare(clientv3.CreateRevision(l.key), "=", 0)).
		Then(clientv3.OpPut(l.key, l.myID, clientv3.WithLease(lease.ID))).
		Else(clientv3.OpGet(l.key))

	resp, err := txn.Commit()
	if err != nil {
		return err
	}

	if !resp.Succeeded {
		return ErrLocked   // 锁已被占用
	}

	// 3. ★ 关键：启动续约（防止业务执行时间超过 TTL）
	go l.keepAlive(ctx)

	return nil
}

func (l *DistributedLock) Unlock(ctx context.Context) error {
	// ★ 关键：只能释放自己的锁（用 myID 做 CAS）
	txn := l.client.Txn(ctx).
		If(clientv3.Compare(clientv3.Value(l.key), "=", l.myID)).
		Then(clientv3.OpDelete(l.key))
	_, err := txn.Commit()
	return err
}

func (l *DistributedLock) keepAlive(ctx context.Context) {
	ch, err := l.client.KeepAlive(ctx, l.lease)
	if err != nil {
		return
	}
	for range ch {
		// 续约成功
	}
}
```

**五个必须注意的点：**

```
① 必须有过期时间（TTL）
   否则客户端崩溃后锁永远不释放

② 必须有续约机制（watchdog）
   业务执行时间可能超过 TTL

③ 释放时必须检查是自己持有的
   ★ 经典 bug：A 的锁过期了，B 拿到锁，A 执行完把 B 的锁删了

④ 获取锁的操作必须是原子的
   用 CAS（Compare-And-Swap），不能先 GET 再 PUT

⑤ 用于保护共享资源时，资源本身也要有版本检查
   ★  fencing token：锁服务返回一个递增的 token
      资源服务拒绝旧 token 的请求
```

**fencing token 场景：**

```
1. A 获取锁，token = 33
2. A 发生长时间 GC 停顿（STW）
3. A 的锁过期，B 获取锁，token = 34
4. B 写入存储
5. A 恢复，继续写入存储 ← ★ 错误！它不知道自己的锁已经失效

解决：存储层记录见过的最大 token
     A 用 token=33 写入 → 被拒绝（因为已经见过 34）
```

> **老陈**：**这是 Martin Kleppmann 那篇著名的文章《How to do distributed locking》讨论的核心问题。**
>
> **Redlock（Redis 的分布式锁方案）在这个问题上有争议，因为它不提供 fencing token。**
>
> **而基于 Raft 的锁（etcd/ZooKeeper）天然提供——因为 Raft 的日志索引就是单调递增的 fencing token。**

---

## 思考题 ·【应用层】

**你的系统用 Raft 存储关键配置。某天运维反馈：集群偶尔会出现"选举风暴"——频繁选举，导致服务不可用。请分析可能的原因，给出诊断和解决方案。**

<details>
<summary>参考答案</summary>

### 什么是选举风暴

```
现象：
  · 集群频繁换 leader（每秒几次甚至更多）
  · term 快速增长（比如几分钟涨到几千）
  · 服务不可用（每次选举期间无法写入）
  · 日志里大量 "became candidate" / "lost leadership"
```

---

### 五个可能的原因

#### 原因 1：心跳间隔 vs 选举超时 配置不当

```
规则：electionTimeout 必须远大于 心跳间隔
     推荐：electionTimeout > 10 × heartbeatInterval

如果配置成：
  heartbeat = 100ms
  electionTimeout = 150ms
  
  → 只要有一次网络抖动（延迟 > 150ms），follower 就发起选举
  → 频繁选举

正确配置（etcd 默认）:
  heartbeat = 100ms
  electionTimeout = 1000ms
  ★ 比例 10:1
```

**诊断：**
```bash
# etcd 的指标
etcd_debugging_mvcc_current_revision
etcd_server_leader_changes_seen_total   ← 看这个
```

**解决：**
```bash
# etcd 启动参数
--heartbeat-interval=100
--election-timeout=1000
```

#### 原因 2：网络延迟或丢包

```
场景：
  · 跨机房部署，网络延迟高且不稳定
  · 网络丢包
  · 交换机故障

表现：
  · 心跳偶尔超时
  · follower 发起选举
```

**诊断：**
```bash
# 测节点间延迟
ping <peer>
# 或者用更精确的
iperf3 -c <peer>

# 看丢包
mtr <peer>

# 看网络抖动
# 连续 ping 1000 次，看延迟分布
ping -c 1000 <peer> | tail -1
```

**解决：**
1. **调整超时参数**（最重要）
   ```bash
   --heartbeat-interval=200
   --election-timeout=2000
   ```
2. **检查网络质量**
   - 不要跨机房部署 Raft 集群（除非专线）
   - 如果必须跨机房，用 5 节点（2+2+1）并把多数派放在主机房
3. **用 Prevote**
   ```go
   // etcd 的 raft 配置
   cfg := &raft.Config{
       PreVote: true,   // ★ 开启预投票
   }
   ```

**Prevote 为什么能解决？**

```
问题：一个被网络隔离的节点，收不到心跳
     → 它会 term++ 并发起选举
     → 但它的日志不是最新的，选不上
     → 它反复重试，term 一直涨
     → 当它重新连上时，它的 term 比集群大
     → ★ 强制所有节点更新 term，导致当前 leader 下台
     → 集群重新选举 → 服务中断

Prevote:
  选举前先"预投票"：
    "如果我把 term 加 1 发起选举，你们会投票给我吗？"
  ★ 预投票不改变 term
  → 如果被隔离的节点得不到多数派的预投票，它就不会真正发起选举
  → term 不会暴涨
  → 重连时不会干扰集群
```

#### 原因 3：磁盘 IO 慢

**这是最容易被忽略的原因！**

```
Raft 的每次写入都要：
  1. 追加 WAL（fsync）
  2. 复制到多数派
  3. 提交

如果磁盘 IO 慢（比如 HDD，或者云盘的 IOPS 打满）:
  · leader 写 WAL 慢
  · 心跳处理慢
  · 消息处理慢
  → follower 收不到及时的心跳
  → 发起选举
```

**诊断：**
```bash
# 测磁盘 fsync 延迟
fio --name=fsync --ioengine=sync --rw=write --bs=4k \
    --numjobs=1 --size=100M --fsync=1 --filename=/tmp/test

# 看 IO 等待
iostat -x 1
# 看 %util 和 await
#   %util > 80%  → 磁盘饱和
#   await > 10ms → 慢

# etcd 自己的指标
etcd_disk_wal_fsync_duration_seconds   ★ 看这个
#   如果 P99 > 10ms，说明磁盘太慢
```

**etcd 的官方建议：**
```
wal_fsync_duration_seconds 的 P99 应该 < 10ms
如果超过，说明磁盘不满足要求

★ 生产环境必须用 SSD
★ 云盘要注意 IOPS 配额
```

**解决：**
1. 换 SSD
2. WAL 和数据分离到不同磁盘
3. 用更高 IOPS 的云盘
4. 检查是否有其他进程抢占 IO

#### 原因 4：CPU 不够 / GC 停顿

```
场景：
  · 节点 CPU 打满
  · Go 的 GC 停顿

表现：
  · 心跳处理延迟
  · 消息处理不过来
```

**诊断：**
```bash
# CPU 使用率
top
# 如果 load average 远高于核数，说明 CPU 不够

# Go 的 GC 停顿
GODEBUG=gctrace=1
# 看 STW 时间

# etcd 指标
etcd_debugging_server_lease_expired_total
process_cpu_seconds_total
```

**解决：**
1. 增加 CPU 核数
2. 优化 GC（调 GOGC、减少分配，第 3 章讲过）
3. 检查是否有异常进程

#### 原因 5：集群节点数为偶数 / 部署不合理

```
4 个节点的集群:
  多数派 = 3
  → 只能容忍 1 个节点故障
  ★ 跟 3 节点集群一样的容错能力，但成本更高

跨机房部署 3 节点（1+1+1）:
  任何一个机房故障 → 只剩 2 个节点 → 无法形成多数派
  ★ 等于没有容灾

正确做法：
  3 节点：都在一个机房（容忍 1 节点故障）
  5 节点：3+2 分布在两机房（容忍 1 机房故障）
  跨地域：用 learner 或者异步复制，而不是跨地域 Raft
```

---

### 诊断清单

```bash
#!/bin/bash
# Raft 集群诊断脚本

echo "=== 1. 集群健康 ==="
etcdctl endpoint health --cluster

echo -e "\n=== 2. Leader 变化次数 ==="
curl -s http://localhost:2379/metrics | grep leader_changes

echo -e "\n=== 3. WAL fsync 延迟 ==="
curl -s http://localhost:2379/metrics | grep wal_fsync_duration

echo -e "\n=== 4. 网络延迟 ==="
etcdctl endpoint status --cluster -w table

echo -e "\n=== 5. 磁盘 IO ==="
iostat -x 1 3

echo -e "\n=== 6. CPU 和 GC ==="
top -bn1 | head -20
```

---

### 解决方案（按优先级）

```
第 1 步: 调整超时参数
  --heartbeat-interval=200 --election-timeout=2000
  ★ 5 分钟，立竿见影

第 2 步: 开启 PreVote
  ★ 防止被隔离节点干扰集群

第 3 步: 检查磁盘，换 SSD
  ★ 这是最常见的根本原因

第 4 步: 检查网络，避免跨机房
  ★ 如果必须跨机房，用 5 节点 3+2

第 5 步: 检查 CPU 和 GC
```

---

### 一个真实案例

```
现象：
  某公司的 etcd 集群每隔几分钟就选举一次
  term 一天涨到 5000+

排查过程：
  1. 看 leader_changes 指标 → 确实频繁
  2. 看 wal_fsync_duration → P99 = 150ms  ★ 异常！
  3. iostat 看磁盘 → %util = 99%，await = 200ms
  4. 查是什么在占用 IO → 发现同一个节点上跑了一个日志采集 agent
    它每分钟做一次全盘扫描

解决：
  把日志采集 agent 移到其他节点
  → wal_fsync_duration 降到 1ms
  → 选举风暴消失

★ 教训：Raft 集群对磁盘延迟极其敏感
      不要在同一块磁盘上跑 IO 密集的任务
```

---

### 一句话总结

**选举风暴的根因通常是"心跳没能及时到达或处理"。**

可能的原因（按概率排序）：
1. **磁盘 IO 慢**（最常见，最容易被忽略）
2. **超时参数配置不当**
3. **网络问题**
4. **CPU/GC 问题**

**诊断的关键是看 etcd 的 `wal_fsync_duration_seconds` 指标**——如果 P99 > 10ms，磁盘就是罪魁祸首。

**这再次印证了那个原则：先测量，再优化。不要凭直觉猜测。**

</details>

---

## 第 5 章总结

### 网络部分

1. **I/O 模型的演进是"减少无效等待"的历史**。epoll 的三个设计（红黑树、就绪链表、回调）让它能高效处理"大量连接少量活跃"。

2. **LT 和 ET 的区别在"内核是否重新检查状态"**。ET 必须循环读写到 EAGAIN。**99% 场景用 LT。**

3. **Go 的 netpoller 是隐式的多 Reactor**——你写最简单的阻塞代码。

### 分布式部分

4. **一致性模型**：线性 > 顺序 > 因果 > 最终。线性一致性等价于"只有一个副本"，是分布式锁的基础。

5. **Raft 的三个子问题**：选主、日志复制、安全性。

6. **★ 为什么只能提交当前 term 的日志**：因为"被多数派复制"≠"已提交"。只有提交当前 term 的日志，才能锁定之前的所有日志。这是最常见的实现 bug。

7. **投票限制（日志新旧比较）是安全性的第一条保证**——保证选出的 leader 包含所有已提交的日志。

8. **分布式锁的五个要点**：TTL、续约、CAS 释放、原子获取、fencing token。

### 与前后章节的联系

```
第 1 章: 单机并发（缓存一致性、内存屏障、锁）
第 3 章: Go 的并发模型（GMP、channel）
第 4 章: 单机存储（WAL、MVCC）
第 5 章: 分布式（共识、复制）  ← 你在这里
第 6 章: 观测和调优
```

**核心洞察：分布式系统是"单机问题在更大尺度的重演"。**

- 缓存一致性 → 副本一致性
- 内存屏障 → 共识算法
- 锁 → 分布式锁
- 事务 → 分布式事务

**理解了单机，分布式就只是"多了网络和故障"；理解了分布式，回头看单机会更清楚。**

---

## 下一章

[第 6 章 · 系统与性能工程](../第6章-系统与性能工程/README.md)

> **老陈的预告**：前 5 章我们造了很多东西。第 6 章解决一个问题——**怎么知道它们跑得好不好？怎么让它们跑得更快？**
>
> 我们要手写容器运行时（namespace + cgroup）、用 eBPF 做观测、建立性能调优的方法论。
