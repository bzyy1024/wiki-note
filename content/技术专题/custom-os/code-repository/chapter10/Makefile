# 编译器和工具
CC = gcc
ASM = nasm
LD = ld

# 编译标志
CFLAGS = -m32 -ffreestanding -fno-pie -fno-stack-protector -nostdlib -Wall -Wextra -g
ASMFLAGS = -f elf32
LDFLAGS = -m elf_i386 -T linker.ld --oformat binary

# 源文件
C_SOURCES = kernel.c screen.c string.c idt.c keyboard.c
ASM_SOURCES = kernel_entry.asm interrupt.asm
BOOT_SOURCES = boot.asm

# 目标文件
C_OBJECTS = $(C_SOURCES:.c=.o)
ASM_OBJECTS = $(ASM_SOURCES:.asm=.o)

# 最终目标
all: os-image.bin

# 启动扇区
boot.bin: boot.asm print.asm disk.asm gdt.asm switch_pm.asm
	$(ASM) -f bin boot.asm -o boot.bin

# C源文件编译
%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

# ASM源文件编译
%.o: %.asm
	$(ASM) $(ASMFLAGS) $< -o $@

# 链接内核
kernel.bin: $(ASM_OBJECTS) $(C_OBJECTS)
	$(LD) $(LDFLAGS) -o kernel.bin $(ASM_OBJECTS) $(C_OBJECTS)

# 生成OS镜像
os-image.bin: boot.bin kernel.bin
	cat boot.bin kernel.bin > os-image.bin

# 运行
run: os-image.bin
	qemu-system-x86_64 -fda os-image.bin

# 调试
debug: os-image.bin
	qemu-system-x86_64 -fda os-image.bin -s -S &
	gdb -ex "target remote localhost:1234" \
	    -ex "set architecture i386"

# 清理
clean:
	rm -f *.bin *.o

.PHONY: all run debug clean
