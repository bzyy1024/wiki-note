# 第13章：进程管理

## 本章概述

进程是操作系统中最核心的抽象——它是程序的运行实例。本章将实现进程控制块（PCB）、进程创建与销毁、以及进程状态管理。

## 学习目标

- 理解进程的概念和生命周期
- 设计并实现进程控制块（PCB）
- 实现进程创建和销毁
- 管理进程状态转换
- 为下一章的调度器做准备

## 前置知识

- 虚拟内存（第12章）
- 中断处理（第9章）

## 知识要点

### 进程状态机

```
              创建
               │
               ↓
  ┌──── [就绪 READY] ←──────┐
  │            │              │
  │   被调度 ↓   时间片到/让出 │
  │      [运行 RUNNING] ──────┘
  │            │
  │    等待I/O ↓
  │    [阻塞 BLOCKED]
  │            │
  │    I/O完成 │
  └────────────┘
               │
          退出 ↓
       [终止 TERMINATED]
```

### 进程控制块（PCB）

```c
typedef struct process {
    uint32_t pid;              // 进程ID
    char name[32];             // 进程名
    process_state_t state;     // 状态
    registers_t regs;          // 保存的寄存器
    page_directory_t *page_dir; // 页目录
    uint32_t kernel_stack;     // 内核栈顶
    struct process *next;      // 链表指针
} process_t;
```

## 文件结构

```
13-进程管理/
├── README.md           ← 本文件
├── 理论讲解.md
├── code/
│   ├── process.h       ← 进程数据结构
│   ├── process.c       ← 进程管理实现
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
```

## 本章收获

- ✅ PCB数据结构设计
- ✅ 进程创建与销毁
- ✅ 进程状态管理
- ✅ 进程链表维护
