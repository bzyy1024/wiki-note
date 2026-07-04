; switch_pm.asm - 从实模式切换到保护模式

[BITS 16]
switch_to_pm:
    cli                     ; 1. 关闭中断

    lgdt [gdt_descriptor]   ; 2. 加载GDT

    ; 3. 设置CR0的PE位（第0位）
    mov eax, cr0
    or eax, 0x1
    mov cr0, eax

    ; 4. 远跳转到32位代码段
    ; 这会刷新CPU流水线，并设置CS为代码段选择子
    jmp CODE_SEG:init_pm

[BITS 32]
init_pm:
    ; 5. 初始化所有段寄存器为数据段选择子
    mov ax, DATA_SEG
    mov ds, ax
    mov ss, ax
    mov es, ax
    mov fs, ax
    mov gs, ax

    ; 6. 设置栈指针
    mov ebp, 0x90000
    mov esp, ebp

    ; 7. 跳转到32位主程序
    call BEGIN_PM
