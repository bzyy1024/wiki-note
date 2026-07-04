#include "syscall.h"
#include "idt.h"
#include "screen.h"
#include "process.h"
#include "scheduler.h"

/* ============================================================
 * 系统调用实现
 * ============================================================ */

typedef int (*syscall_fn_t)(uint32_t, uint32_t, uint32_t);

static int sys_exit(uint32_t code, uint32_t unused1, uint32_t unused2) {
    (void)unused1; (void)unused2;
    screen_printf("[SYSCALL] exit(%d)\n", code);
    process_terminate(process_current());
    scheduler_yield();
    return 0;
}

static int sys_write(uint32_t buf, uint32_t len, uint32_t unused) {
    (void)unused;
    /* 简单实现：将缓冲区内容写到屏幕 */
    const char *str = (const char *)buf;
    for (uint32_t i = 0; i < len; i++) {
        screen_putchar(str[i]);
    }
    return (int)len;
}

static int sys_read(uint32_t buf, uint32_t len, uint32_t unused) {
    (void)buf; (void)len; (void)unused;
    /* 占位实现 */
    return 0;
}

static int sys_yield(uint32_t unused1, uint32_t unused2, uint32_t unused3) {
    (void)unused1; (void)unused2; (void)unused3;
    scheduler_yield();
    return 0;
}

static int sys_getpid(uint32_t unused1, uint32_t unused2, uint32_t unused3) {
    (void)unused1; (void)unused2; (void)unused3;
    return (int)process_current()->pid;
}

/* 系统调用表 */
static syscall_fn_t syscall_table[NUM_SYSCALLS] = {
    [SYS_EXIT]   = sys_exit,
    [SYS_WRITE]  = sys_write,
    [SYS_READ]   = sys_read,
    [SYS_YIELD]  = sys_yield,
    [SYS_GETPID] = sys_getpid,
};

/* ============================================================
 * 系统调用中断处理器
 * ============================================================ */

static void syscall_handler(registers_t *regs) {
    if (regs->eax >= NUM_SYSCALLS) {
        regs->eax = (uint32_t)-1;
        return;
    }

    syscall_fn_t fn = syscall_table[regs->eax];
    if (fn) {
        regs->eax = (uint32_t)fn(regs->ebx, regs->ecx, regs->edx);
    } else {
        regs->eax = (uint32_t)-1;
    }
}

void syscall_init(void) {
    /* 注册INT 0x80, 注意：需要IDT中使用DPL=3标志 (0xEE) */
    register_interrupt_handler(0x80, syscall_handler);
    screen_puts("[SYSCALL] System call interface initialized (INT 0x80)\n");
}
