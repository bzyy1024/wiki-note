ENTRY(kernel_entry)

SECTIONS {
    . = 0x1000;         /* 内核加载地址，与Bootloader的KERNEL_OFFSET一致 */

    .text : {
        *(.text)        /* 代码段 */
    }

    .rodata : {
        *(.rodata)      /* 只读数据（字符串常量等） */
    }

    .data : {
        *(.data)        /* 已初始化的全局变量 */
    }

    .bss : {
        *(COMMON)
        *(.bss)         /* 未初始化的全局变量 */
    }
}
