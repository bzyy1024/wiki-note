ASM = nasm
CC = gcc
LD = ld

CFLAGS = -m32 -ffreestanding -fno-pie -fno-builtin -nostdlib -nostdinc -c
LDFLAGS = -m elf_i386 -T linker.ld --oformat binary

C_SOURCES = kernel.c string.c
C_OBJECTS = $(C_SOURCES:.c=.o)

BOOT = boot.bin
KERNEL = kernel.bin
IMAGE = os-image.bin

all: $(IMAGE)

$(BOOT): boot.asm print.asm disk.asm gdt.asm switch_pm.asm
	$(ASM) -f bin boot.asm -o $(BOOT)

kernel_entry.o: kernel_entry.asm
	$(ASM) -f elf32 kernel_entry.asm -o kernel_entry.o

%.o: %.c
	$(CC) $(CFLAGS) $< -o $@

$(KERNEL): kernel_entry.o $(C_OBJECTS)
	$(LD) $(LDFLAGS) -o $(KERNEL) kernel_entry.o $(C_OBJECTS)

$(IMAGE): $(BOOT) $(KERNEL)
	cat $(BOOT) $(KERNEL) > $(IMAGE)
	truncate -s 16384 $(IMAGE)

run: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE)

clean:
	rm -f *.o *.bin

.PHONY: all run clean
