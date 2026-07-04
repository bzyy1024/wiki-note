; boot.asm - Bootloader: 加载内核 + 切换到保护模式
;
; 编译: make
; 运行: make run

[BITS 16]
[ORG 0x7C00]

KERNEL_OFFSET equ 0x1000

start:
    ; 初始化段寄存器
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00

    ; 保存驱动器号
    mov [BOOT_DRIVE], dl

    ; 打印启动信息（16位模式下使用BIOS）
    mov si, msg_real_mode
    call print_string

    ; 从磁盘加载内核
    mov dh, 15
    mov dl, [BOOT_DRIVE]
    mov bx, KERNEL_OFFSET
    call disk_read

    mov si, msg_loaded
    call print_string

    ; 切换到保护模式
    call switch_to_pm

    jmp $           ; 不应到达这里

; ============================================================
; 数据
; ============================================================

msg_real_mode db 'Started in 16-bit Real Mode', 0x0D, 0x0A, 0
msg_loaded    db 'Kernel loaded into memory', 0x0D, 0x0A, 0
BOOT_DRIVE    db 0

; ============================================================
; 包含子模块
; ============================================================

%include "print.asm"
%include "disk.asm"
%include "gdt.asm"
%include "switch_pm.asm"

; ============================================================
; 32位代码
; ============================================================

[BITS 32]
BEGIN_PM:
    ; 已经在32位保护模式！
    ; 不能使用BIOS中断，直接操作VGA显存
    mov ebx, 0xB8000        ; VGA显存起始地址

    ; 在屏幕第3行显示消息（跳过前2行BIOS输出）
    ; 每行80字符，每字符2字节 → 第3行偏移 = 80 * 2 * 2 = 320
    add ebx, 320

    mov esi, msg_pm
    call print_string_pm

    jmp $

; 32位打印函数（直接写VGA显存）
; ESI = 字符串地址, EBX = VGA显存位置
print_string_pm:
    pusha
    mov ah, 0x0F            ; 白色前景，黑色背景
.loop:
    lodsb                   ; AL = [ESI], ESI++
    cmp al, 0
    je .done
    mov [ebx], ax           ; 写入字符+属性
    add ebx, 2
    jmp .loop
.done:
    popa
    ret

msg_pm db 'Landed in 32-bit Protected Mode!', 0

; ============================================================
; 填充和引导签名
; ============================================================

times 510-($-$$) db 0
dw 0xAA55
