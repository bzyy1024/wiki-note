# 附录A：调试大全

## 1. GDB调试

### 基本用法

```bash
# 启动QEMU调试模式（冻结CPU等待GDB连接）
qemu-system-x86_64 -fda os-image.bin -s -S

# 另一个终端连接GDB
gdb -ex "target remote localhost:1234" -ex "set architecture i386"
```

### 常用GDB命令

| 命令 | 说明 |
|------|------|
| `b *0x7c00` | 在bootloader入口设断点 |
| `b *0x1000` | 在内核入口设断点 |
| `c` | 继续执行 |
| `si` | 单步执行一条指令 |
| `ni` | 步过（不进入函数） |
| `info registers` | 查看所有寄存器 |
| `p/x $eax` | 打印EAX（十六进制） |
| `x/16x 0x7c00` | 查看内存（16个32位值） |
| `x/10i $eip` | 反汇编EIP处10条指令 |
| `watch *0x1234` | 数据断点（内存写入时停下） |
| `bt` | 查看调用栈 |

### 实用脚本

创建 `.gdbinit` 文件：
```
target remote localhost:1234
set architecture i386
b *0x7c00
b *0x1000
layout asm
```

### 调试内核C代码

编译时加 `-g` 标志，使用ELF格式辅助文件：
```bash
# 生成带调试信息的ELF
gcc -m32 -g -ffreestanding -c kernel.c -o kernel.o
ld -m elf_i386 -T linker.ld -o kernel.elf kernel.o  # ELF格式（调试用）

# 在GDB中加载符号
(gdb) symbol-file kernel.elf
(gdb) b kernel_main
```

## 2. QEMU调试功能

### 常用QEMU选项

```bash
# 输出中断日志
qemu-system-x86_64 -fda os-image.bin -d int

# 输出CPU重置事件
qemu-system-x86_64 -fda os-image.bin -d int,cpu_reset -no-reboot

# 输出到文件
qemu-system-x86_64 -fda os-image.bin -d int -D qemu.log

# 显示页表信息
qemu-system-x86_64 -fda os-image.bin -d mmu

# 所有调试信息
qemu-system-x86_64 -fda os-image.bin -d all -D qemu.log
```

### QEMU Monitor

在QEMU运行时按 `Ctrl+Alt+2` 进入Monitor：

```
(qemu) info registers    # 查看CPU寄存器
(qemu) info mem          # 查看内存映射
(qemu) info tlb          # 查看TLB
(qemu) info pic          # 查看PIC状态
(qemu) info irq          # 查看IRQ统计
(qemu) xp /16x 0x7c00   # 查看物理内存
(qemu) gpa2hva 0x1000    # 物理到虚拟地址转换
```

## 3. 串口调试

### 配置QEMU串口输出

```bash
qemu-system-x86_64 -fda os-image.bin -serial stdio
```

### 内核串口输出

```c
#define SERIAL_PORT 0x3F8

void serial_init(void) {
    outb(SERIAL_PORT + 1, 0x00);  // 关闭中断
    outb(SERIAL_PORT + 3, 0x80);  // DLAB
    outb(SERIAL_PORT + 0, 0x03);  // 38400 baud
    outb(SERIAL_PORT + 1, 0x00);
    outb(SERIAL_PORT + 3, 0x03);  // 8位, 无校验, 1停止位
    outb(SERIAL_PORT + 2, 0xC7);  // FIFO
    outb(SERIAL_PORT + 4, 0x0B);  // 启用
}

void serial_write(char c) {
    while (!(inb(SERIAL_PORT + 5) & 0x20));
    outb(SERIAL_PORT, c);
}

void serial_puts(const char *str) {
    while (*str) serial_write(*str++);
}
```

## 4. 常用调试技巧

### 幻数标记

在关键结构中使用幻数验证完整性：
```c
#define PCB_MAGIC 0xDEAD1234

typedef struct process {
    uint32_t magic;  // = PCB_MAGIC
    // ... 其他字段
} process_t;

// 检查
assert(proc->magic == PCB_MAGIC);
```

### 内核panic

```c
void kernel_panic(const char *msg, const char *file, int line) {
    __asm__ volatile("cli");  // 关中断
    screen_set_color(VGA_COLOR_WHITE, VGA_COLOR_RED);
    screen_printf("\n*** KERNEL PANIC ***\n%s\nat %s:%d\n", msg, file, line);
    while (1) __asm__ volatile("hlt");
}

#define PANIC(msg) kernel_panic(msg, __FILE__, __LINE__)
```

### 栈溢出检测

在栈底部放置金丝雀值：
```c
#define STACK_CANARY 0xCAFEBABE

uint32_t *canary = (uint32_t *)stack_bottom;
*canary = STACK_CANARY;

// 定期检查
if (*canary != STACK_CANARY) {
    PANIC("Stack overflow detected!");
}
```

## 5. 常见调试命令速查

```bash
# 十六进制查看二进制文件
xxd os-image.bin | head -20

# 反汇编二进制
ndisasm -b 16 boot.bin | head -30       # 16位
ndisasm -b 32 kernel.bin | head -30     # 32位

# objdump（ELF格式）
objdump -d kernel.elf | less

# 查看ELF节信息
readelf -S kernel.elf

# 查看符号表
nm kernel.elf
```
