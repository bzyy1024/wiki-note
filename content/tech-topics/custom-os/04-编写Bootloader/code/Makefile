# 编译工具
ASM = nasm

# 目标文件
BOOT = boot.bin
IMAGE = os-image.bin

all: $(IMAGE)

# 编译引导扇区
$(BOOT): boot.asm print.asm disk.asm
	$(ASM) -f bin boot.asm -o $(BOOT)

# 创建磁盘映像（引导扇区 + 模拟内核空间）
$(IMAGE): $(BOOT)
	cat $(BOOT) > $(IMAGE)
	dd if=/dev/zero bs=512 count=15 >> $(IMAGE) 2>/dev/null

# 在QEMU中运行
run: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE)

# 调试模式
debug: $(IMAGE)
	qemu-system-x86_64 -drive format=raw,file=$(IMAGE) -s -S &
	@echo "GDB连接: target remote localhost:1234"

# 查看二进制
hexdump: $(BOOT)
	xxd $(BOOT) | head -40

clean:
	rm -f $(BOOT) $(IMAGE)

.PHONY: all run debug hexdump clean
