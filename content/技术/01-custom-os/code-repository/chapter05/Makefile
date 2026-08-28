ASM = nasm

BOOT = boot.bin
IMAGE = os-image.bin

all: $(IMAGE)

$(BOOT): boot.asm print.asm disk.asm gdt.asm switch_pm.asm
	$(ASM) -f bin boot.asm -o $(BOOT)

$(IMAGE): $(BOOT)
	cat $(BOOT) > $(IMAGE)
	dd if=/dev/zero bs=512 count=15 >> $(IMAGE) 2>/dev/null

run: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE)

debug: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE) -s -S &
	@echo "GDB: target remote localhost:1234"

clean:
	rm -f $(BOOT) $(IMAGE)

.PHONY: all run debug clean
