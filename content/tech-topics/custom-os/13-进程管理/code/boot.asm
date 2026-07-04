; boot.asm - Bootloader: 加载内核并跳转执行

[BITS 16]
[ORG 0x7C00]

KERNEL_OFFSET equ 0x1000

start:
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00

    mov [BOOT_DRIVE], dl

    mov si, msg_real_mode
    call print_string

    ; 加载内核到 KERNEL_OFFSET
    mov dh, 15
    mov dl, [BOOT_DRIVE]
    mov bx, KERNEL_OFFSET
    call disk_read

    mov si, msg_loaded
    call print_string

    call switch_to_pm
    jmp $

; ============================================================

msg_real_mode db 'Started in 16-bit Real Mode', 0x0D, 0x0A, 0
msg_loaded    db 'Kernel loaded into memory', 0x0D, 0x0A, 0
BOOT_DRIVE    db 0

%include "print.asm"
%include "disk.asm"
%include "gdt.asm"
%include "switch_pm.asm"

[BITS 32]
BEGIN_PM:
    ; 在保护模式下，跳转到内核入口
    call KERNEL_OFFSET
    jmp $

; ============================================================

times 510-($-$$) db 0
dw 0xAA55
