# 编译和链接工具
ASM = nasm

# 目标文件
TARGET = boot.bin

# 默认目标
all: $(TARGET)

# 编译汇编为原始二进制
$(TARGET): boot.asm
	$(ASM) -f bin boot.asm -o $(TARGET)

# 在QEMU中运行
run: $(TARGET)
	qemu-system-x86_64 -drive format=raw,file=$(TARGET)

# 在QEMU中运行（带调试支持）
debug: $(TARGET)
	qemu-system-x86_64 -drive format=raw,file=$(TARGET) -s -S &
	@echo "GDB连接: target remote localhost:1234"

# 查看二进制内容
hexdump: $(TARGET)
	xxd $(TARGET) | head -40

# 清理
clean:
	rm -f $(TARGET)

.PHONY: all run debug hexdump clean
