#include "tss.h"
#include "string.h"
#include "screen.h"

static tss_entry_t tss;

void tss_init(uint32_t gdt_index, uint32_t kernel_ss, uint32_t kernel_esp) {
    memset(&tss, 0, sizeof(tss));

    tss.ss0  = kernel_ss;   /* 内核数据段选择子 */
    tss.esp0 = kernel_esp;  /* 内核栈顶 */

    /* I/O位图偏移设为TSS大小（不使用I/O位图） */
    tss.iomap_base = sizeof(tss);

    /* 加载TSS到TR寄存器 */
    uint16_t tss_selector = (gdt_index * 8) | 0;  /* RPL=0 */
    __asm__ volatile("ltr %0" : : "r"(tss_selector));

    screen_printf("[TSS] Initialized (ss0=0x%x, esp0=0x%x)\n", kernel_ss, kernel_esp);
}

void tss_set_kernel_stack(uint32_t esp) {
    tss.esp0 = esp;
}
