# 主线学习路径

> 按此路径学习，约8-10周建立完整的计算机科学思维体系。

---

## 阶段一：建立底层认知（2-3周）

**目标**：理解计算机如何执行代码、管理内存、处理并发

### 第1周：程序执行全流程

**学习内容**：
1. [概览：从源码到运行](../foundations/01-program-execution/00-overview.md)
2. [编译过程](../foundations/01-program-execution/01-compilation.md)
3. [链接过程](../foundations/01-program-execution/02-linking.md)
4. [装载过程](../foundations/01-program-execution/03-loading.md)
5. [运行时](../foundations/01-program-execution/04-execution.md)
6. [Go视角：go build背后](../foundations/01-program-execution/05-go-build.md)

**实践任务**：
- 用 `go build`、`readelf`、`objdump` 分析你的Go可执行文件
- 尝试画出从 `main.go` 到进程运行的完整流程图

**里程碑**：能不看教材画出"源码→编译→链接→装载→运行"的完整流程

---

### 第2周：内存与地址

**学习内容**：
1. [虚拟内存机制](../foundations/02-memory-addressing/01-virtual-memory.md)
2. [进程内存布局](../foundations/02-memory-addressing/02-memory-layout.md)
3. [指针的本质](../foundations/02-memory-addressing/03-pointer-essence.md)

**实践任务**：
- 写Go程序打印变量地址，观察栈和堆的分配
- 用 `go tool compile -S` 查看汇编输出中的地址引用

**里程碑**：能解释"指针就是一个存储地址的变量"背后的完整机制

---

### 阶段一检验

完成以下自测题，如果都能回答，恭喜通过：

- [ ] 从源码到运行经历了哪些步骤？每步做了什么？
- [ ] 符号解析和重定位分别解决什么问题？
- [ ] 虚拟内存的核心意义是什么？
- [ ] 进程内存中，代码段、数据段、堆、栈分别存什么？
- [ ] Go默认是静态链接还是动态链接？为什么？

---

## 阶段二：掌握工程模式（3-4周）

**目标**：学会解决实际工程问题，建立模式库

### 第3-4周：一致性问题

**学习内容**：
1. [场景：为什么会不一致？](../patterns/consistency/00-problem-space.md)
2. [Cache-Aside与延迟双删](../patterns/consistency/01-cache-aside.md)
3. [Write-Through/Write-Back](../patterns/consistency/02-write-strategies.md)
4. [分布式缓存一致性](../patterns/consistency/03-distributed-cache.md)
5. [Go实现：Redis缓存方案](../patterns/consistency/04-go-implementation.md)

**实践任务**：
- 实现一个带延迟双删的Redis缓存方案
- 用goroutine模拟并发场景，验证不一致问题
- 对比不同方案的延迟和一致性表现

**里程碑**：能独立设计一个缓存更新策略，并解释为什么选择该方案

---

### 第5周：并发控制与分布式锁

**学习内容**：
1. [分布式锁](../patterns/concurrency-control/03-distributed-lock.md)

**实践任务**：
- 实现Redis分布式锁（含续租、释放安全性）
- 对比Redis锁和Etcd锁的优缺点

**里程碑**：能说出3种分布式锁方案的适用场景

---

### 第6周：可靠性设计

**学习内容**：
1. [幂等性设计](../patterns/reliability/01-idempotency.md)

**实践任务**：
- 设计一个幂等的支付接口
- 实现token-based幂等控制

**里程碑**：遇到"重复请求"问题能立刻想到幂等性设计

---

### 阶段二检验

- [ ] Redis和DB不一致时有哪些解决方案？各自的权衡是什么？
- [ ] 延迟双删的延迟时间怎么确定？
- [ ] 分布式锁用Redis还是Etcd？取决于什么？
- [ ] 什么是幂等性？如何设计幂等接口？
- [ ] 能设计一个综合使用缓存、分布式锁、幂等性的系统吗？

---

## 阶段三：构建理论思维（2-3周）

**目标**：建立系统思维，理解设计背后的根本权衡

### 第7周：抽象与一致性

**学习内容**：
1. [抽象层次的艺术](../theory/01-abstraction-layers.md)
2. [一致性模型](../theory/02-consistency-models.md)

**思考任务**：
- 列出你在工作中接触到的3个抽象层次
- 画出一致性模型谱系图（从线性一致性到最终一致性）

**里程碑**：能从"抽象层次"视角解释复杂系统

---

### 第8-9周：系统思维

**学习内容**：
1. [系统思维：跨领域的通用原理](../theory/08-thinking-in-systems.md)

**思考任务**：
- 找出CPU缓存和分布式缓存的3个相似原理
- 写一篇短文：为什么计算机科学中到处都是权衡？

**里程碑**：能将计算机思维应用到技术方案评审中

---

### 阶段三检验

- [ ] 强一致性、顺序一致性、最终一致性有何区别？现实系统用哪种？
- [ ] CAP定理说的是什么？在实际中如何权衡？
- [ ] 从CPU缓存到分布式缓存，有什么共同的原理？
- [ ] 能从"权衡"视角分析一个你用过的系统的设计决策吗？

---

## 完成后，你将获得

1. **系统化知识**：从硬件到分布式系统的完整认知链条
2. **工程判断力**：面对问题能列出多种方案并分析权衡
3. **理论思维**：能从第一性原理分析问题本质
4. **跨领域能力**：能将计算机思维应用到其他领域
