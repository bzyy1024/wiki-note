# 第14章：任务调度

## 本章概述

有了进程管理后，我们需要一个调度器让多个进程"同时"运行。本章将实现定时器驱动的上下文切换和轮转调度算法。

## 学习目标

- 理解抢占式调度的原理
- 配置可编程间隔定时器（PIT）
- 实现上下文切换（context switch）
- 实现轮转（Round-Robin）调度算法
- 看到多个任务交替运行！

## 前置知识

- 中断处理（第9章）
- 进程管理（第13章）

## 知识要点

### 调度器工作原理

```
时钟中断(IRQ0) → 定时器处理器 → 调度决策 → 上下文切换
                                    │
                      ┌─────────────┼─────────────┐
                      ↓             ↓             ↓
                 继续当前进程   切换到下一个   抢占当前进程
```

### 上下文切换流程

```
保存当前进程:               恢复下一进程:
  push edi                   mov esp, next->esp
  push esi                   pop edi
  push ebx                   pop esi
  push ebp                   pop ebx
  mov [prev->esp], esp       pop ebp
                              ret (→ 新进程的EIP)
```

## 文件结构

```
14-任务调度/
├── README.md           ← 本文件
├── 理论讲解.md
├── code/
│   ├── timer.h         ← 定时器接口
│   ├── timer.c         ← PIT配置和定时器中断
│   ├── scheduler.h     ← 调度器接口
│   ├── scheduler.c     ← 轮转调度实现
│   ├── switch.asm      ← 上下文切换汇编
│   ├── kernel.c
│   ├── Makefile
│   └── [共享文件]
├── 常见错误.md
└── 练习题.md
```

## 构建与测试

```bash
cd code
make
make run
# 应该能看到多个任务交替打印输出！
```

## 本章收获

- ✅ PIT定时器配置
- ✅ 上下文切换实现
- ✅ Round-Robin调度器
- ✅ 多任务并发运行
