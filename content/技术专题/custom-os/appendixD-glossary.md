# 附录D：术语表

中英对照，按字母顺序排列。

---

## A

| 英文 | 中文 | 说明 |
|------|------|------|
| Address Space | 地址空间 | 进程可访问的内存范围 |
| ABI (Application Binary Interface) | 应用程序二进制接口 | 二进制级别的调用规范 |
| ACPI (Advanced Configuration and Power Interface) | 高级配置与电源接口 | 硬件信息和电源管理标准 |
| APIC (Advanced PIC) | 高级可编程中断控制器 | PIC的现代替代 |
| Assembly | 汇编语言 | 机器码的人类可读形式 |

## B

| 英文 | 中文 | 说明 |
|------|------|------|
| BIOS (Basic Input/Output System) | 基本输入输出系统 | 固件，启动时初始化硬件 |
| Bitmap | 位图 | 用位表示资源状态的数据结构 |
| Boot Sector | 引导扇区 | 磁盘第一个扇区（512字节） |
| Bootloader | 引导程序 | 加载操作系统内核的程序 |
| BSS (Block Started by Symbol) | 未初始化数据段 | 存放未初始化的全局/静态变量 |
| Bus | 总线 | 硬件组件间的通信通道 |
| Byte | 字节 | 8位数据单位 |

## C

| 英文 | 中文 | 说明 |
|------|------|------|
| Cache | 缓存 | 高速数据缓冲区 |
| Context Switch | 上下文切换 | CPU从一个进程/线程切换到另一个 |
| CPU (Central Processing Unit) | 中央处理器 | 执行指令的核心硬件 |
| Cross Compiler | 交叉编译器 | 在一个平台上编译另一个平台的代码 |

## D

| 英文 | 中文 | 说明 |
|------|------|------|
| Deadlock | 死锁 | 多个进程互相等待，无法继续 |
| Descriptor | 描述符 | GDT/IDT中的条目 |
| DMA (Direct Memory Access) | 直接内存访问 | 设备直接读写内存，不经CPU |
| Driver | 驱动程序 | 控制硬件设备的软件 |

## E

| 英文 | 中文 | 说明 |
|------|------|------|
| ELF (Executable and Linkable Format) | 可执行可链接格式 | Linux标准可执行文件格式 |
| EOI (End of Interrupt) | 中断结束信号 | 通知PIC当前中断处理完毕 |
| Exception | 异常 | CPU检测到的错误（如除零、缺页） |

## F

| 英文 | 中文 | 说明 |
|------|------|------|
| FAT (File Allocation Table) | 文件分配表 | 简单的文件系统格式 |
| FIFO (First In First Out) | 先进先出 | 队列数据结构的顺序 |
| Flag | 标志位 | 表示状态的单个位 |
| Frame | 帧/页框 | 物理内存的固定大小块（通常4KB） |
| Freestanding | 独立环境 | 没有标准库的编程环境 |

## G

| 英文 | 中文 | 说明 |
|------|------|------|
| GCC (GNU Compiler Collection) | GNU编译器集合 | 开源编译器套件 |
| GDB (GNU Debugger) | GNU调试器 | 开源调试工具 |
| GDT (Global Descriptor Table) | 全局描述符表 | 定义内存段的x86结构 |

## H

| 英文 | 中文 | 说明 |
|------|------|------|
| Heap | 堆 | 动态内存分配区域 |

## I

| 英文 | 中文 | 说明 |
|------|------|------|
| IDT (Interrupt Descriptor Table) | 中断描述符表 | 定义中断处理函数的表 |
| Inline Assembly | 内联汇编 | 在C代码中嵌入的汇编指令 |
| Interrupt | 中断 | 打断CPU正常执行的信号 |
| I/O Port | IO端口 | 与硬件设备通信的端口地址 |
| IPC (Inter-Process Communication) | 进程间通信 | 进程交换数据的机制 |
| IRQ (Interrupt Request) | 中断请求 | 硬件设备发出的中断信号 |
| IRET | 中断返回 | 从中断处理返回的指令 |
| ISR (Interrupt Service Routine) | 中断服务程序 | 处理中断的函数 |

## K

| 英文 | 中文 | 说明 |
|------|------|------|
| Kernel | 内核 | 操作系统的核心部分 |
| Kernel Mode (Ring 0) | 内核态 | CPU最高特权级别 |
| Kernel Panic | 内核恐慌 | 不可恢复的内核错误 |

## L

| 英文 | 中文 | 说明 |
|------|------|------|
| LBA (Logical Block Addressing) | 逻辑块寻址 | 用连续编号访问磁盘扇区 |
| LDT (Local Descriptor Table) | 局部描述符表 | 每个进程的段描述符表 |
| Linker | 链接器 | 将目标文件合并为可执行文件 |
| Linker Script | 链接脚本 | 控制链接器输出布局的脚本 |

## M

| 英文 | 中文 | 说明 |
|------|------|------|
| MBR (Master Boot Record) | 主引导记录 | 磁盘的第一个扇区 |
| MMU (Memory Management Unit) | 内存管理单元 | 硬件地址转换单元 |
| Mutex | 互斥锁 | 保护共享资源的同步原语 |

## N

| 英文 | 中文 | 说明 |
|------|------|------|
| NASM (Netwide Assembler) | NASM汇编器 | x86汇编器 |

## O

| 英文 | 中文 | 说明 |
|------|------|------|
| Object File | 目标文件 | 编译后的中间文件（.o） |
| Offset | 偏移量 | 相对于基地址的距离 |
| OS (Operating System) | 操作系统 | 管理硬件和软件资源的系统软件 |

## P

| 英文 | 中文 | 说明 |
|------|------|------|
| Page | 页 | 虚拟内存的固定大小块（通常4KB） |
| Page Directory | 页目录 | 一级页表（指向页表） |
| Page Fault | 缺页异常 | 访问未映射虚拟地址时的异常 |
| Page Table | 页表 | 虚拟到物理地址的映射表 |
| Paging | 分页 | 虚拟内存管理机制 |
| PCB (Process Control Block) | 进程控制块 | 存储进程状态的数据结构 |
| PIC (Programmable Interrupt Controller) | 可编程中断控制器 | 管理硬件中断的芯片（8259A） |
| PIT (Programmable Interval Timer) | 可编程间隔计时器 | 产生定时中断的芯片（8253/8254） |
| PMM (Physical Memory Manager) | 物理内存管理器 | 管理物理内存分配的模块 |
| Protected Mode | 保护模式 | x86 32位模式，具有内存保护 |
| Privilege Level (Ring) | 特权级 | CPU权限级别（0最高，3最低） |
| Process | 进程 | 正在运行的程序实例 |

## Q

| 英文 | 中文 | 说明 |
|------|------|------|
| QEMU | QEMU模拟器 | 开源机器模拟器和虚拟化工具 |
| Queue | 队列 | FIFO数据结构 |

## R

| 英文 | 中文 | 说明 |
|------|------|------|
| Real Mode | 实模式 | x86 16位模式，无内存保护 |
| Register | 寄存器 | CPU内部的高速存储单元 |
| Round Robin | 轮转调度 | 每个进程获得相等的CPU时间片 |

## S

| 英文 | 中文 | 说明 |
|------|------|------|
| Scan Code | 扫描码 | 键盘按键的硬件编码 |
| Scheduler | 调度器 | 决定哪个进程运行的模块 |
| Sector | 扇区 | 磁盘的最小读写单位（通常512字节） |
| Segment | 段 | 内存的逻辑区域 |
| Semaphore | 信号量 | 计数型同步原语 |
| Shell | 命令行解释器 | 接收用户命令并执行的程序 |
| SMP (Symmetric Multiprocessing) | 对称多处理 | 多CPU核心共享内存 |
| Spinlock | 自旋锁 | 忙等待的同步原语 |
| Stack | 栈 | LIFO数据结构，函数调用使用 |
| Syscall (System Call) | 系统调用 | 用户程序请求内核服务的接口 |

## T

| 英文 | 中文 | 说明 |
|------|------|------|
| Thread | 线程 | 进程内的执行单元 |
| Time Slice | 时间片 | 调度器分配给进程的CPU时间 |
| TLB (Translation Lookaside Buffer) | 转译后备缓冲区 | 页表缓存，加速地址转换 |
| Triple Fault | 三重故障 | CPU无法处理异常导致的重启 |
| TSS (Task State Segment) | 任务状态段 | 保存任务硬件上下文的x86结构 |

## U

| 英文 | 中文 | 说明 |
|------|------|------|
| User Mode (Ring 3) | 用户态 | CPU最低特权级别 |

## V

| 英文 | 中文 | 说明 |
|------|------|------|
| VGA (Video Graphics Array) | 视频图形阵列 | 显示标准，文本模式地址0xB8000 |
| Virtual Address | 虚拟地址 | 进程看到的地址，由MMU转换 |
| Virtual Memory | 虚拟内存 | 每个进程拥有独立地址空间的抽象 |
| VMM (Virtual Memory Manager) | 虚拟内存管理器 | 管理页表和地址映射的模块 |
