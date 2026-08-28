# 编译器和工具
CC = gcc
ASM = nasm
LD = ld

CFLAGS = -m32 -ffreestanding -fno-pie -fno-stack-protector -nostdlib -Wall -Wextra -g
ASMFLAGS = -f elf32
LDFLAGS = -m elf_i386 -T linker.ld --oformat binary

C_SOURCES = kernel.c screen.c string.c idt.c keyboard.c pmm.c
ASM_SOURCES = kernel_entry.asm interrupt.asm

C_OBJECTS = $(C_SOURCES:.c=.o)
ASM_OBJECTS = $(ASM_SOURCES:.asm=.o)

all: os-image.bin

boot.bin: boot.asm print.asm disk.asm gdt.asm switch_pm.asm
	$(ASM) -f bin boot.asm -o boot.bin

%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

%.o: %.asm
	$(ASM) $(ASMFLAGS) $< -o $@

kernel.bin: $(ASM_OBJECTS) $(C_OBJECTS)
	$(LD) $(LDFLAGS) -o kernel.bin $(ASM_OBJECTS) $(C_OBJECTS)

os-image.bin: boot.bin kernel.bin
	cat boot.bin kernel.bin > os-image.bin

run: os-image.bin
	qemu-system-x86_64 -fda os-image.bin

debug: os-image.bin
	qemu-system-x86_64 -fda os-image.bin -s -S &
	gdb -ex "target remote localhost:1234" -ex "set architecture i386"

clean:
	rm -f *.bin *.o

.PHONY: all run debug clean
