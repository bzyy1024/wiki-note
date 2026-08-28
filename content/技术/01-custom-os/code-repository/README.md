# OS Tutorial - 代码仓库

本目录包含《从零开始写操作系统》教程各章节的完整源代码。

## 目录结构

| 目录 | 章节 | 内容 |
|------|------|------|
| `chapter03/` | BIOS与启动 | 最小引导扇区 |
| `chapter04/` | 编写Bootloader | 打印、磁盘读取 |
| `chapter05/` | 进入保护模式 | GDT、模式切换 |
| `chapter06/` | 加载内核 | C内核、链接脚本 |
| `chapter07/` | 内核初始化 | 类型定义、端口IO、字符串库 |
| `chapter08/` | 屏幕输出 | VGA文本模式驱动 |
| `chapter09/` | 中断处理 | IDT、PIC、ISR/IRQ |
| `chapter10/` | 键盘输入 | PS/2键盘驱动 |
| `chapter11/` | 物理内存管理 | 位图分配器、kmalloc |
| `chapter12/` | 虚拟内存 | 分页、页表、缺页处理 |
| `chapter13/` | 进程管理 | PCB、进程创建/销毁 |
| `chapter14/` | 任务调度 | PIT定时器、轮转调度、上下文切换 |
| `chapter15/` | 用户程序 | TSS、系统调用、Ring 3 |

## 编译与运行

每个章节目录都包含独立的 `Makefile`：

```bash
cd chapter08
make        # 编译
make run    # 在QEMU中运行
make clean  # 清理
```

## 依赖

- GCC（支持 `-m32`）
- NASM
- LD
- QEMU
- Make

Ubuntu/Debian 安装：
```bash
sudo apt install build-essential nasm qemu-system-x86 make
```

## 分支与标签

每章代码对应一个 Git tag：
```
git tag chapter03
git tag chapter04
...
git tag chapter15
```
