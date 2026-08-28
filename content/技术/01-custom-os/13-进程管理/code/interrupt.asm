; interrupt.asm - 中断服务程序汇编入口
; 这些宏生成ISR入口点，保存寄存器状态后调用C处理函数

[extern isr_handler]
[extern irq_handler]

; ISR宏：无错误码的中断
; CPU不压入错误码时，我们压入0作为占位符
%macro ISR_NOERRCODE 1
global isr%1
isr%1:
    push dword 0          ; 压入伪错误码
    push dword %1         ; 压入中断号
    jmp isr_common_stub
%endmacro

; ISR宏：有错误码的中断
; CPU自动压入错误码，我们只需压入中断号
%macro ISR_ERRCODE 1
global isr%1
isr%1:
    push dword %1         ; 压入中断号（错误码已由CPU压入）
    jmp isr_common_stub
%endmacro

; IRQ宏
%macro IRQ 2
global irq%1
irq%1:
    push dword 0          ; 伪错误码
    push dword %2         ; 中断向量号（IRQ号 + 32）
    jmp irq_common_stub
%endmacro

; ============================================================
; CPU异常 (0-31)
; ============================================================

; 无错误码的异常
ISR_NOERRCODE 0   ; 除零错误
ISR_NOERRCODE 1   ; 调试异常
ISR_NOERRCODE 2   ; 不可屏蔽中断(NMI)
ISR_NOERRCODE 3   ; 断点
ISR_NOERRCODE 4   ; 溢出
ISR_NOERRCODE 5   ; 边界检查
ISR_NOERRCODE 6   ; 无效操作码
ISR_NOERRCODE 7   ; 设备不可用
ISR_ERRCODE   8   ; 双重错误（有错误码）
ISR_NOERRCODE 9   ; 协处理器段越界
ISR_ERRCODE   10  ; 无效TSS（有错误码）
ISR_ERRCODE   11  ; 段不存在（有错误码）
ISR_ERRCODE   12  ; 栈段错误（有错误码）
ISR_ERRCODE   13  ; 通用保护错误（有错误码）
ISR_ERRCODE   14  ; 页错误（有错误码）
ISR_NOERRCODE 15  ; 保留
ISR_NOERRCODE 16  ; x87浮点异常
ISR_ERRCODE   17  ; 对齐检查（有错误码）
ISR_NOERRCODE 18  ; 机器检查
ISR_NOERRCODE 19  ; SIMD浮点异常
ISR_NOERRCODE 20  ; 虚拟化异常
ISR_ERRCODE   21  ; 控制保护（有错误码）
ISR_NOERRCODE 22  ; 保留
ISR_NOERRCODE 23
ISR_NOERRCODE 24
ISR_NOERRCODE 25
ISR_NOERRCODE 26
ISR_NOERRCODE 27
ISR_NOERRCODE 28
ISR_NOERRCODE 29
ISR_NOERRCODE 30
ISR_NOERRCODE 31

; ============================================================
; 硬件中断 IRQ 0-15 → 向量 32-47
; ============================================================

IRQ  0, 32    ; 可编程时钟
IRQ  1, 33    ; 键盘
IRQ  2, 34    ; 级联（从PIC）
IRQ  3, 35    ; COM2
IRQ  4, 36    ; COM1
IRQ  5, 37    ; LPT2
IRQ  6, 38    ; 软盘
IRQ  7, 39    ; LPT1 / 伪中断
IRQ  8, 40    ; CMOS实时时钟
IRQ  9, 41    ; 自由/ACPI
IRQ 10, 42    ; 自由
IRQ 11, 43    ; 自由
IRQ 12, 44    ; PS/2鼠标
IRQ 13, 45    ; FPU / 协处理器
IRQ 14, 46    ; 主ATA硬盘
IRQ 15, 47    ; 从ATA硬盘

; ============================================================
; 通用ISR处理桩（异常）
; ============================================================
isr_common_stub:
    ; 保存所有通用寄存器
    pusha

    ; 保存数据段选择子
    mov ax, ds
    push eax

    ; 加载内核数据段
    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax

    ; 将栈指针作为参数传递（指向registers_t结构）
    push esp
    call isr_handler
    add esp, 4

    ; 恢复数据段
    pop eax
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax

    ; 恢复通用寄存器
    popa

    ; 清除中断号和错误码
    add esp, 8
    iret

; ============================================================
; 通用IRQ处理桩（硬件中断）
; ============================================================
irq_common_stub:
    pusha

    mov ax, ds
    push eax

    mov ax, 0x10
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax

    push esp
    call irq_handler
    add esp, 4

    pop eax
    mov ds, ax
    mov es, ax
    mov fs, ax
    mov gs, ax

    popa
    add esp, 8
    iret
