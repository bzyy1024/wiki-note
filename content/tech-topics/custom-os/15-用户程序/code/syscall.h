#ifndef SYSCALL_H
#define SYSCALL_H

#include "types.h"

/* 系统调用号 */
#define SYS_EXIT   0
#define SYS_WRITE  1
#define SYS_READ   2
#define SYS_YIELD  3
#define SYS_GETPID 4

#define NUM_SYSCALLS 16

/* 初始化系统调用 */
void syscall_init(void);

/* 用户态系统调用接口（内联汇编） */
static inline int syscall(int num, int arg1, int arg2, int arg3) {
    int ret;
    __asm__ volatile(
        "int $0x80"
        : "=a"(ret)
        : "a"(num), "b"(arg1), "c"(arg2), "d"(arg3)
    );
    return ret;
}

#endif
