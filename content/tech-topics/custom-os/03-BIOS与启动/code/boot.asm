; 最简单的引导扇区 - 打印一个字符
; 这是你的第一个操作系统代码！
;
; 编译: nasm -f bin boot.asm -o boot.bin
; 运行: qemu-system-x86_64 -drive format=raw,file=boot.bin

[BITS 16]           ; 16位实模式
[ORG 0x7C00]        ; BIOS加载到这个地址

start:
    ; 初始化段寄存器（好习惯）
    xor ax, ax      ; AX = 0
    mov ds, ax      ; 数据段 = 0
    mov es, ax      ; 附加段 = 0

    ; 使用BIOS中断打印字符
    mov ah, 0x0E    ; 功能号：teletype输出
    mov al, 'A'     ; 要打印的字符
    int 0x10        ; 调用BIOS视频中断

    ; 无限循环
    jmp $           ; $ = 当前地址，即原地跳转

; 填充到510字节
times 510-($-$$) db 0

; 引导签名（BIOS检查这两个字节来判断是否是有效引导扇区）
; 注意：小端序存储，所以 dw 0xAA55 实际存储为 55 AA
dw 0xAA55
