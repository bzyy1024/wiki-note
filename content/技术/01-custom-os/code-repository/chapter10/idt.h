#ifndef IDT_H
#define IDT_H

#include "types.h"

#define IDT_ENTRIES 256

/* IDT门描述符 */
struct idt_entry {
    uint16_t base_low;      /* 处理程序地址低16位 */
    uint16_t selector;      /* 代码段选择子 */
    uint8_t  always0;       /* 保留，总是0 */
    uint8_t  flags;         /* 类型和属性 */
    uint16_t base_high;     /* 处理程序地址高16位 */
} __attribute__((packed));

/* IDT指针 */
struct idt_ptr {
    uint16_t limit;
    uint32_t base;
} __attribute__((packed));

/* 寄存器状态（中断发生时保存的） */
typedef struct {
    uint32_t ds;
    uint32_t edi, esi, ebp, useless_esp, ebx, edx, ecx, eax;
    uint32_t int_no, err_code;
    uint32_t eip, cs, eflags, esp, ss;
} registers_t;

/* 中断处理回调类型 */
typedef void (*interrupt_handler_t)(registers_t*);

void idt_init(void);
void register_interrupt_handler(uint8_t n, interrupt_handler_t handler);

#endif
