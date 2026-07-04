# C语言要点

操作系统开发中的C语言用法与应用开发有很大不同。这里聚焦OS开发中最关键的几个知识点。

## 1. 指针和直接内存操作

在OS开发中，你会经常直接操作物理内存地址：

```c
// 直接操作VGA显存（物理地址 0xB8000）
char *video_memory = (char*)0xB8000;

// 在屏幕左上角显示字符'A'（白色）
video_memory[0] = 'A';      // 字符
video_memory[1] = 0x0F;     // 属性（白色前景，黑色背景）

// 等价写法
*(video_memory) = 'A';
*(video_memory + 1) = 0x0F;

// 使用uint16_t一次写入字符+属性
uint16_t *vga = (uint16_t*)0xB8000;
vga[0] = 0x0F41;  // 0x0F=属性, 0x41='A'
```

### 指针类型转换

```c
// 把一个整数当作地址使用
uint32_t addr = 0xB8000;
char *ptr = (char*)addr;

// 把指针转回整数
uint32_t addr2 = (uint32_t)ptr;

// 在OS开发中这是正常操作，不是bug
```

## 2. 内联汇编

C语言中嵌入汇编指令，用于执行特权操作：

### 基本语法

```c
// 简单的内联汇编
__asm__ volatile("cli");     // 关闭中断
__asm__ volatile("sti");     // 开启中断
__asm__ volatile("hlt");     // 暂停CPU

// volatile 告诉编译器不要优化掉这条指令
```

### 带输入输出的内联汇编

```c
// 读取端口
static inline uint8_t inb(uint16_t port) {
    uint8_t result;
    __asm__ volatile("inb %1, %0"
                     : "=a"(result)      // 输出：result = AL
                     : "Nd"(port));      // 输入：port → DX
    return result;
}

// 写入端口
static inline void outb(uint16_t port, uint8_t data) {
    __asm__ volatile("outb %0, %1"
                     : /* 无输出 */
                     : "a"(data),        // 输入：data → AL
                       "Nd"(port));      // 输入：port → DX
}
```

**内联汇编模板：**
```c
__asm__ volatile(
    "汇编指令"
    : 输出操作数          // "=约束"(C变量)
    : 输入操作数          // "约束"(C变量)
    : 被修改的寄存器      // 告诉编译器哪些寄存器会被改变
);
```

常用约束：
- `"a"` — EAX寄存器
- `"b"` — EBX寄存器
- `"c"` — ECX寄存器
- `"d"` — EDX寄存器
- `"m"` — 内存操作数
- `"r"` — 任意通用寄存器

## 3. 结构体和 packed 属性

OS开发中的结构体需要精确控制内存布局：

```c
// 普通结构体（编译器可能插入填充字节）
struct normal {
    uint8_t  a;    // 1字节
    // 3字节填充  ← 编译器自动加的
    uint32_t b;    // 4字节
};
// sizeof(struct normal) = 8（不是5！）

// packed结构体（禁止填充，按实际大小排列）
struct __attribute__((packed)) packed {
    uint8_t  a;    // 1字节
    uint32_t b;    // 4字节
};
// sizeof(struct packed) = 5（精确控制）
```

**GDT表项的例子：**
```c
struct gdt_entry {
    uint16_t limit_low;     // 段界限（低16位）
    uint16_t base_low;      // 基地址（低16位）
    uint8_t  base_middle;   // 基地址（中8位）
    uint8_t  access;        // 访问权限
    uint8_t  granularity;   // 粒度和段界限高4位
    uint8_t  base_high;     // 基地址（高8位）
} __attribute__((packed));  // 必须packed！硬件要求精确的8字节
```

## 4. 位运算

OS开发大量使用位运算来操作硬件寄存器和标志位：

```c
// 设置某一位
flags |= (1 << 3);        // 设置第3位

// 清除某一位
flags &= ~(1 << 3);       // 清除第3位

// 检查某一位
if (flags & (1 << 3)) {   // 第3位是否为1？
    // ...
}

// 提取字段
uint8_t low  = value & 0xFF;           // 低8位
uint8_t high = (value >> 8) & 0xFF;    // 高8位

// 合并字段
uint16_t combined = (high << 8) | low;
```

## 5. 固定宽度整数类型

OS开发中必须使用精确大小的类型：

```c
#include <stdint.h>

uint8_t   a;    // 无符号8位  (0~255)
uint16_t  b;    // 无符号16位 (0~65535)
uint32_t  c;    // 无符号32位 (0~4294967295)
uint64_t  d;    // 无符号64位

int8_t    e;    // 有符号8位  (-128~127)
int16_t   f;    // 有符号16位
int32_t   g;    // 有符号32位

// 不要使用 int、long 等，因为大小在不同平台上可能不同
```

## 6. 编译和链接过程

```
源代码 (.c)
    │
    ▼ 预处理 (gcc -E)
头文件展开、宏替换 (.i)
    │
    ▼ 编译 (gcc -S)
汇编代码 (.s)
    │
    ▼ 汇编 (gcc -c 或 as)
目标文件 (.o)
    │
    ▼ 链接 (ld)
可执行文件 / 二进制映像 (.bin)
```

**OS开发的特殊编译选项：**
```bash
gcc -m32 \               # 32位模式
    -ffreestanding \      # 独立环境（不依赖标准库）
    -fno-pie \           # 禁用位置无关代码
    -nostdlib \          # 不链接标准库
    -nostdinc \          # 不搜索标准头文件路径
    -fno-builtin \       # 不使用内建函数
    -c kernel.c \        # 只编译不链接
    -o kernel.o          # 输出目标文件
```

### 链接脚本

OS开发需要自定义链接脚本来控制代码在内存中的位置：

```ld
/* linker.ld */
ENTRY(kernel_entry)        /* 入口点 */

SECTIONS {
    . = 0x1000;            /* 从地址0x1000开始放置代码 */

    .text : { *(.text) }   /* 代码段 */
    .rodata : { *(.rodata) }  /* 只读数据 */
    .data : { *(.data) }   /* 已初始化数据 */
    .bss : { *(.bss) }     /* 未初始化数据 */
}
```

## 7. freestanding 环境

OS开发中没有标准库（没有 printf、malloc、string.h 等），需要自己实现：

```c
// 自己实现 memset
void *memset(void *ptr, int value, uint32_t size) {
    uint8_t *p = (uint8_t*)ptr;
    for (uint32_t i = 0; i < size; i++) {
        p[i] = (uint8_t)value;
    }
    return ptr;
}

// 自己实现 memcpy
void *memcpy(void *dest, const void *src, uint32_t size) {
    uint8_t *d = (uint8_t*)dest;
    const uint8_t *s = (const uint8_t*)src;
    for (uint32_t i = 0; i < size; i++) {
        d[i] = s[i];
    }
    return dest;
}

// 自己实现 strlen
uint32_t strlen(const char *str) {
    uint32_t len = 0;
    while (str[len] != '\0') {
        len++;
    }
    return len;
}
```

**可以使用的标准头文件（freestanding环境自带）：**
- `<stdint.h>` — 固定宽度整数
- `<stddef.h>` — NULL、size_t
- `<stdbool.h>` — bool、true、false
- `<stdarg.h>` — 可变参数
