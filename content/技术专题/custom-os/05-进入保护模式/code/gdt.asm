; gdt.asm - 全局描述符表定义
;
; 定义3个描述符：空描述符、代码段、数据段
; 使用平坦内存模型（基址=0，界限=4GB）

gdt_start:
    ; 空描述符（第0项，CPU要求必须为空）
    dq 0x0

gdt_code:
    ; 代码段描述符
    ; 基址=0x0, 界限=0xFFFFF, 粒度=4K → 覆盖4GB
    ; 访问字节: 10011010b = Present, DPL=0, Code, Execute/Read
    ; 标志: 1100b = 4K粒度, 32位
    dw 0xFFFF       ; 界限（低16位）
    dw 0x0          ; 基址（低16位）
    db 0x0          ; 基址（中8位）
    db 10011010b    ; 访问字节
    db 11001111b    ; 标志(高4位) + 界限(高4位)
    db 0x0          ; 基址（高8位）

gdt_data:
    ; 数据段描述符
    ; 基址=0x0, 界限=0xFFFFF, 粒度=4K → 覆盖4GB
    ; 访问字节: 10010010b = Present, DPL=0, Data, Read/Write
    dw 0xFFFF
    dw 0x0
    db 0x0
    db 10010010b    ; 访问字节
    db 11001111b
    db 0x0

gdt_end:

; GDT描述符（传给LGDT指令）
gdt_descriptor:
    dw gdt_end - gdt_start - 1    ; GDT大小（字节数 - 1）
    dd gdt_start                   ; GDT起始地址

; 段选择子常量（GDT中的偏移量）
CODE_SEG equ gdt_code - gdt_start  ; 0x08
DATA_SEG equ gdt_data - gdt_start  ; 0x10
