# 问题索引

> 遇到具体问题？在这里快速找到相关内容。

---

## 程序运行相关

| 遇到的问题 | 查看文档 |
|-----------|---------|
| 不理解程序如何运行 | [程序执行全流程](../foundations/01-program-execution/00-overview.md) |
| 编译报错看不懂 | [编译过程](../foundations/01-program-execution/01-compilation.md) |
| 不理解链接错误 | [链接过程](../foundations/01-program-execution/02-linking.md) |
| 想了解go build背后发生了什么 | [Go编译](../foundations/01-program-execution/05-go-build.md) |

## 内存相关

| 遇到的问题 | 查看文档 |
|-----------|---------|
| 指针和地址搞不清 | [指针的本质](../foundations/02-memory-addressing/03-pointer-essence.md) |
| 想了解虚拟内存 | [虚拟内存机制](../foundations/02-memory-addressing/01-virtual-memory.md) |
| 程序内存是怎么布局的 | [进程内存布局](../foundations/02-memory-addressing/02-memory-layout.md) |
| OOM了，不知道为什么 | [进程内存布局](../foundations/02-memory-addressing/02-memory-layout.md) |

## 缓存一致性

| 遇到的问题 | 查看文档 |
|-----------|---------|
| Redis缓存和DB不一致 | [Cache-Aside与延迟双删](../patterns/consistency/01-cache-aside.md) |
| 缓存更新策略怎么选 | [Write-Through/Write-Back](../patterns/consistency/02-write-strategies.md) |
| 分布式缓存一致性问题 | [分布式缓存一致性](../patterns/consistency/03-distributed-cache.md) |
| 想看Go实现的缓存方案 | [Go实现：Redis缓存方案](../patterns/consistency/04-go-implementation.md) |
| 为什么会有一致性问题 | [问题空间](../patterns/consistency/00-problem-space.md) |

## 并发与锁

| 遇到的问题 | 查看文档 |
|-----------|---------|
| 分布式锁怎么选 | [分布式锁](../patterns/concurrency-control/03-distributed-lock.md) |
| Redis锁还是Etcd锁 | [分布式锁](../patterns/concurrency-control/03-distributed-lock.md) |

## 可靠性

| 遇到的问题 | 查看文档 |
|-----------|---------|
| 如何设计幂等接口 | [幂等性设计](../patterns/reliability/01-idempotency.md) |
| 重复请求怎么处理 | [幂等性设计](../patterns/reliability/01-idempotency.md) |

## 理论与思维

| 遇到的问题 | 查看文档 |
|-----------|---------|
| 什么是最终一致性 | [一致性模型](../theory/02-consistency-models.md) |
| 不理解CAP定理 | [一致性模型](../theory/02-consistency-models.md) |
| 想建立系统性思维 | [系统思维](../theory/08-thinking-in-systems.md) |
| 分层抽象是什么意思 | [抽象层次的艺术](../theory/01-abstraction-layers.md) |

---

## 按关键词查找

| 关键词 | 相关文件 |
|--------|---------|
| 编译、AST、词法分析 | [编译过程](../foundations/01-program-execution/01-compilation.md) |
| 符号表、重定位、.o文件 | [链接过程](../foundations/01-program-execution/02-linking.md) |
| 装载器、ELF、内存映射 | [装载过程](../foundations/01-program-execution/03-loading.md) |
| 调用栈、函数调用、返回地址 | [运行时](../foundations/01-program-execution/04-execution.md) |
| 虚拟内存、页表、MMU | [虚拟内存](../foundations/02-memory-addressing/01-virtual-memory.md) |
| 堆、栈、代码段、数据段 | [内存布局](../foundations/02-memory-addressing/02-memory-layout.md) |
| Cache-Aside、延迟双删 | [缓存一致性](../patterns/consistency/01-cache-aside.md) |
| Write-Through、Write-Back | [写策略](../patterns/consistency/02-write-strategies.md) |
| Redis锁、Etcd锁、ZooKeeper | [分布式锁](../patterns/concurrency-control/03-distributed-lock.md) |
| 幂等、token、去重 | [幂等性](../patterns/reliability/01-idempotency.md) |
| 强一致性、顺序一致性 | [一致性模型](../theory/02-consistency-models.md) |
| 抽象、分层、封装 | [抽象层次](../theory/01-abstraction-layers.md) |
| 权衡、tradeoff、系统思维 | [系统思维](../theory/08-thinking-in-systems.md) |
