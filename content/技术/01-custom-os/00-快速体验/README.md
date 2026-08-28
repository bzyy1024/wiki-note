# 第0章：快速体验

> 5分钟看到你最终能做出什么

## 本章目标

在开始学习之前，先看看最终成果——用15章课程构建出的操作系统。这将帮助你：

1. 了解最终能做到什么
2. 建立学习信心
3. 确认开发环境可用

## 预计时间

⏱️ 5分钟

## 快速运行

### 方式一：使用运行脚本

```bash
cd 00-快速体验/
chmod +x run.sh
./run.sh
```

### 方式二：手动运行

```bash
qemu-system-x86_64 -drive format=raw,file=预编译镜像/os.img
```

## 你将看到

```
QEMU启动...

Booting MyOS...
Loading kernel...
Kernel initialized!

Welcome to MyOS v0.1
======================
[Physical Memory] Initialized - 128MB available
[Virtual Memory]  Paging enabled
[Interrupts]      IDT loaded, 256 vectors
[Keyboard]        Driver ready
[Scheduler]       Round-robin, 10ms quantum

System ready.

MyOS> _
```

**功能演示：**
- 屏幕显示彩色启动信息
- 内核初始化各子系统
- 键盘输入响应
- 多任务调度运行

## 这是如何实现的？

这个操作系统包含了你将在15章中逐步实现的所有组件：

| 章节 | 组件 | 作用 |
|------|------|------|
| 03-04 | Bootloader | 从磁盘加载内核到内存 |
| 05 | 保护模式 | 从16位切换到32位/64位 |
| 06-07 | C内核 | 内核主体框架 |
| 08 | 屏幕输出 | VGA文本模式彩色输出 |
| 09 | 中断处理 | 异常捕获和硬件中断 |
| 10 | 键盘驱动 | 接收键盘输入 |
| 11-12 | 内存管理 | 物理和虚拟内存分配 |
| 13-14 | 进程调度 | 多任务并发执行 |
| 15 | 用户程序 | 运行用户态程序 |

## 下一步

确认体验成功后，前往 [01-环境准备](../01-环境准备/README.md) 开始搭建你自己的开发环境。

> 💡 如果QEMU无法运行，说明你还没有安装必要的工具。没关系，下一章会详细指导你完成环境配置。
