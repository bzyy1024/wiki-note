# 附录B：工具链详解

## 1. GCC编译过程

### 编译阶段

```
源文件 → 预处理 → 编译 → 汇编 → 链接 → 可执行文件
 .c      .i       .s     .o     a.out
```

```bash
# 分步执行
gcc -E kernel.c -o kernel.i      # 预处理
gcc -S kernel.i -o kernel.s      # 编译为汇编
gcc -c kernel.s -o kernel.o      # 汇编为目标文件
ld kernel.o -o kernel             # 链接
```

### OS开发常用GCC选项

| 选项 | 说明 |
|------|------|
| `-m32` | 生成32位代码 |
| `-ffreestanding` | 独立环境（无标准库假设） |
| `-fno-pie` | 不生成位置无关代码 |
| `-fno-stack-protector` | 禁用栈保护（我们没有__stack_chk_fail） |
| `-nostdlib` | 不链接标准库 |
| `-nostdinc` | 不使用标准头文件路径 |
| `-Wall -Wextra` | 启用更多警告 |
| `-g` | 生成调试信息 |
| `-O0` / `-O2` | 优化级别（调试用O0） |
| `-c` | 只编译不链接 |

### 交叉编译器

推荐使用 `i686-elf-gcc` 交叉编译器：

```bash
# 下载源码构建（简要步骤）
export PREFIX="$HOME/opt/cross"
export TARGET=i686-elf
export PATH="$PREFIX/bin:$PATH"

# 构建binutils
cd build-binutils
../binutils-x.y/configure --target=$TARGET --prefix=$PREFIX --disable-nls --disable-werror
make && make install

# 构建gcc
cd build-gcc
../gcc-x.y/configure --target=$TARGET --prefix=$PREFIX --disable-nls --enable-languages=c --without-headers
make all-gcc all-target-libgcc
make install-gcc install-target-libgcc
```

## 2. 链接脚本详解

### 基本结构

```ld
/* linker.ld */
ENTRY(_start)              /* 入口点 */

SECTIONS {
    . = 0x1000;            /* 起始地址 */

    .text : {              /* 代码段 */
        *(.text)
    }

    .rodata : {            /* 只读数据段 */
        *(.rodata)
    }

    .data : {              /* 已初始化数据段 */
        *(.data)
    }

    .bss : {               /* 未初始化数据段 */
        *(COMMON)
        *(.bss)
    }
}
```

### 关键概念

- `.` 是位置计数器（Location Counter），表示当前地址
- `ENTRY` 指定程序入口符号
- `SECTIONS` 定义输出段的布局
- `*(.text)` 表示所有输入文件的 `.text` 段

### 常用技巧

```ld
SECTIONS {
    . = 0x1000;

    /* 记录内核起始和结束地址 */
    kernel_start = .;

    .text : ALIGN(4096) {
        *(.text)
    }

    .data : ALIGN(4096) {
        *(.data)
    }

    .bss : ALIGN(4096) {
        bss_start = .;
        *(.bss)
        *(COMMON)
        bss_end = .;
    }

    kernel_end = .;
}
```

在C代码中使用链接脚本符号：
```c
extern uint32_t kernel_start;
extern uint32_t kernel_end;
extern uint32_t bss_start;
extern uint32_t bss_end;

// 清零BSS段
memset(&bss_start, 0, (uint32_t)&bss_end - (uint32_t)&bss_start);
```

## 3. Makefile教程

### 基本语法

```makefile
# 变量
CC = gcc
CFLAGS = -m32 -ffreestanding

# 规则：目标: 依赖
#     命令（必须用Tab缩进）
kernel.o: kernel.c
	$(CC) $(CFLAGS) -c $< -o $@
```

### 自动变量

| 变量 | 说明 |
|------|------|
| `$@` | 目标文件名 |
| `$<` | 第一个依赖文件 |
| `$^` | 所有依赖文件 |
| `$*` | 目标的stem（模式匹配部分） |

### OS项目Makefile模板

```makefile
CC = gcc
LD = ld
NASM = nasm

CFLAGS = -m32 -ffreestanding -fno-pie -fno-stack-protector -Wall -Wextra
LDFLAGS = -m elf_i386 -T linker.ld --oformat binary
NASMFLAGS = -f elf32

# 源文件
C_SOURCES = $(wildcard *.c)
ASM_SOURCES = $(wildcard *.asm)
HEADERS = $(wildcard *.h)

# 目标文件
C_OBJECTS = $(C_SOURCES:.c=.o)
ASM_OBJECTS = $(filter-out boot.o, $(ASM_SOURCES:.asm=.o))

# 默认目标
all: os-image.bin

os-image.bin: boot.bin kernel.bin
	cat $^ > $@

boot.bin: boot.asm
	$(NASM) -f bin $< -o $@

kernel.bin: kernel_entry.o $(C_OBJECTS) $(ASM_OBJECTS)
	$(LD) $(LDFLAGS) $^ -o $@

# 模式规则
%.o: %.c $(HEADERS)
	$(CC) $(CFLAGS) -c $< -o $@

%.o: %.asm
	$(NASM) $(NASMFLAGS) $< -o $@

clean:
	rm -f *.bin *.o

run: os-image.bin
	qemu-system-x86_64 -fda $<

debug: os-image.bin
	qemu-system-x86_64 -fda $< -s -S &
	gdb -ex "target remote localhost:1234" -ex "set architecture i386"

.PHONY: all clean run debug
```

### Makefile常见错误

1. **用空格而非Tab缩进** → `*** missing separator. Stop.`
2. **循环依赖** → 目标A依赖B，B依赖A
3. **$(wildcard) 路径错误** → 不会自动递归搜索

## 4. NASM详解

### 基本语法

```nasm
; 注释用分号
section .text      ; 代码段
section .data      ; 数据段
section .bss       ; 未初始化数据段

global _start      ; 导出符号
extern func        ; 导入外部符号
```

### 常用指令

| 指令 | 说明 | 示例 |
|------|------|------|
| `mov` | 数据传送 | `mov eax, 42` |
| `push/pop` | 栈操作 | `push eax` |
| `call/ret` | 函数调用 | `call my_func` |
| `int` | 软中断 | `int 0x80` |
| `cli/sti` | 关/开中断 | `cli` |
| `in/out` | 端口IO | `in al, 0x60` |
| `lgdt/lidt` | 加载描述符表 | `lgdt [gdt_ptr]` |
| `iret` | 中断返回 | `iret` |
| `hlt` | 停机等待中断 | `hlt` |

### 伪指令

```nasm
db 0x55, 0xAA      ; 定义字节
dw 0x1234           ; 定义字（16位）
dd 0x12345678       ; 定义双字（32位）
dq 0                ; 定义四字（64位）

times 510-($-$$) db 0   ; 填充到510字节
resb 4096               ; 在BSS段保留4096字节

%define CONST 42         ; 宏常量
%macro name 1            ; 宏定义（1个参数）
    push %1
%endmacro

[bits 16]   ; 16位代码
[bits 32]   ; 32位代码
[org 0x7c00] ; 设置起始地址
```

### NASM输出格式

| 格式 | 说明 | 命令 |
|------|------|------|
| `bin` | 纯二进制（bootloader） | `nasm -f bin` |
| `elf32` | ELF 32位目标文件 | `nasm -f elf32` |
| `elf64` | ELF 64位目标文件 | `nasm -f elf64` |

## 5. Docker开发环境

### Dockerfile

```dockerfile
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    build-essential \
    nasm \
    qemu-system-x86 \
    gdb \
    xxd \
    make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /os
```

### 使用方法

```bash
# 构建镜像
docker build -t os-dev .

# 运行（挂载源码目录）
docker run -it --rm -v $(pwd):/os os-dev

# 在容器内编译
make clean && make

# GUI模式（需要X11转发）
docker run -it --rm \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $(pwd):/os \
    os-dev make run
```
