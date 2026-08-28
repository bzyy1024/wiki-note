#ifndef TSS_H
#define TSS_H

#include "types.h"

/* TSS结构 */
typedef struct {
    uint32_t prev_tss;
    uint32_t esp0;       /* Ring 0 栈指针 */
    uint32_t ss0;        /* Ring 0 栈段 */
    uint32_t esp1;
    uint32_t ss1;
    uint32_t esp2;
    uint32_t ss2;
    uint32_t cr3;
    uint32_t eip;
    uint32_t eflags;
    uint32_t eax, ecx, edx, ebx;
    uint32_t esp, ebp, esi, edi;
    uint32_t es, cs, ss, ds, fs, gs;
    uint32_t ldt;
    uint16_t trap;
    uint16_t iomap_base;
} __attribute__((packed)) tss_entry_t;

/* 初始化TSS */
void tss_init(uint32_t gdt_index, uint32_t kernel_ss, uint32_t kernel_esp);

/* 更新TSS中的内核栈指针 */
void tss_set_kernel_stack(uint32_t esp);

#endif
