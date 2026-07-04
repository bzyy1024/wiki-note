# 工具
ASM = nasm
CC = gcc
LD = ld

# 编译选项
CFLAGS = -m32 -ffreestanding -fno-pie -fno-builtin -nostdlib -nostdinc -c
LDFLAGS = -m elf_i386 -T linker.ld --oformat binary

# 文件
BOOT = boot.bin
KERNEL = kernel.bin
IMAGE = os-image.bin

all: $(IMAGE)

# 引导扇区
$(BOOT): boot.asm print.asm disk.asm gdt.asm switch_pm.asm
	$(ASM) -f bin boot.asm -o $(BOOT)

# 内核入口（汇编）
kernel_entry.o: kernel_entry.asm
	$(ASM) -f elf32 kernel_entry.asm -o kernel_entry.o

# 内核（C语言）
kernel.o: kernel.c
	$(CC) $(CFLAGS) kernel.c -o kernel.o

# 链接内核
$(KERNEL): kernel_entry.o kernel.o
	$(LD) $(LDFLAGS) -o $(KERNEL) kernel_entry.o kernel.o

# 创建OS映像
$(IMAGE): $(BOOT) $(KERNEL)
	cat $(BOOT) $(KERNEL) > $(IMAGE)
	# 填充到合适大小（至少16个扇区）
	truncate -s 16384 $(IMAGE)

run: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE)

debug: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE) -s -S &
	@echo "GDB: target remote localhost:1234"

clean:
	rm -f *.o *.bin

.PHONY: all run debug clean
