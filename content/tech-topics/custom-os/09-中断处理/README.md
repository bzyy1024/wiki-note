# 第9章：中断处理

> 建立中断描述符表（IDT）和异常处理机制

## 学习目标

1. 理解中断的三种类型（硬件中断、软件中断、异常）
2. 掌握IDT（中断描述符表）的结构和配置
3. 实现CPU异常处理程序
4. 配置PIC（可编程中断控制器）

## 预计时间

⏱️ 4-5小时

## 前置要求

- 完成 [08-屏幕输出](../08-屏幕输出/README.md)

## 本章成果预览

```
[IDT] Interrupt Descriptor Table initialized
[IDT] 256 vectors configured
[PIC] Programmable Interrupt Controller remapped

Testing exception: Division by zero...
!!! EXCEPTION: Division By Zero !!!
```

## 核心概念

### 中断类型

| 类型 | 触发方式 | 示例 |
|------|---------|------|
| 异常 (Exception) | CPU内部检测 | 除零、页错误、一般保护错误 |
| 硬件中断 (IRQ) | 外部设备 | 键盘、定时器、磁盘 |
| 软件中断 | INT指令 | 系统调用 |

### 中断向量表

```
向量 0-31:   CPU异常（Intel保留）
  0  - 除零异常
  6  - 无效操作码
  8  - 双重错误
  13 - 一般保护错误
  14 - 页错误

向量 32-47:  硬件中断（通过PIC映射）
  32 - 定时器 (IRQ0)
  33 - 键盘 (IRQ1)

向量 48-255: 可用于软件中断
  128 (0x80) - 系统调用（惯例）
```

### IDT门描述符（8字节）

```c
struct idt_entry {
    uint16_t base_low;      /* 处理程序地址低16位 */
    uint16_t selector;      /* 代码段选择子 */
    uint8_t  always0;       /* 保留 */
    uint8_t  flags;         /* 类型和属性 */
    uint16_t base_high;     /* 处理程序地址高16位 */
} __attribute__((packed));
```

### PIC重映射

8259A PIC默认将IRQ 0-7映射到中断向量8-15，与CPU异常冲突。需要重映射：

```
重映射前: IRQ 0-7  → 向量 8-15  (与CPU异常冲突！)
重映射后: IRQ 0-7  → 向量 32-39
         IRQ 8-15 → 向量 40-47
```

## 关键文件

```
code/
├── idt.h / idt.c           IDT定义和初始化
├── isr.h / isr.c           中断服务程序（C部分）
├── interrupt.asm            中断服务程序（汇编入口）
├── pic.h / pic.c           PIC配置
├── screen.h / screen.c     屏幕输出（上一章）
└── kernel.c                 更新的内核主程序
```

## 成果检查

- ✅ IDT正确配置并加载（256个向量）
- ✅ PIC重映射到向量32-47
- ✅ 能捕获CPU异常并显示错误信息
- ✅ 能正确处理硬件中断

## 下一步

前往 [10-键盘输入](../10-键盘输入/README.md) 实现键盘驱动。
