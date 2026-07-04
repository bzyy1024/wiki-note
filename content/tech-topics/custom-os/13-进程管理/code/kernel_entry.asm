; kernel_entry.asm - 内核入口点
; 从汇编跳转到C代码

[BITS 32]
[EXTERN kernel_main]    ; 声明外部C函数

global kernel_entry     ; 导出符号给链接器

kernel_entry:
    ; 确保栈已设置（Bootloader中已设置ESP=0x90000）
    call kernel_main    ; 调用C函数

    ; 如果kernel_main返回（不应该），进入死循环
    jmp $
