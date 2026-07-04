; boot.asm - 完整的Bootloader
; 功能: 打印启动信息，从磁盘加载内核到内存
;
; 编译: make
; 运行: make run

[BITS 16]
[ORG 0x7C00]

KERNEL_OFFSET equ 0x1000    ; 内核将被加载到这个地址

start:
    ; 初始化段寄存器
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00          ; 栈指针设在引导扇区之前（向下增长）

    ; 保存BIOS传递的驱动器号
    mov [BOOT_DRIVE], dl

    ; 打印启动信息
    mov si, msg_boot
    call print_string

    ; 从磁盘加载内核
    mov dh, 15              ; 读取15个扇区
    mov dl, [BOOT_DRIVE]    ; 驱动器号
    mov bx, KERNEL_OFFSET   ; 目标内存地址
    call disk_read

    ; 打印加载成功信息
    mov si, msg_loaded
    call print_string

    ; 暂时停在这里（下一章将跳转到内核）
    jmp $

; ============================================================
; 数据区
; ============================================================

msg_boot    db 'Booting MyOS...', 0x0D, 0x0A, 0
msg_loaded  db 'Kernel loaded!', 0x0D, 0x0A, 0
BOOT_DRIVE  db 0

; ============================================================
; 包含的子模块
; ============================================================

%include "print.asm"
%include "disk.asm"

; ============================================================
; 填充和引导签名
; ============================================================

times 510-($-$$) db 0
dw 0xAA55
