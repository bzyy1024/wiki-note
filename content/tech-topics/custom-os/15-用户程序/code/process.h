#ifndef PROCESS_H
#define PROCESS_H

#include "types.h"
#include "vmm.h"

/* 进程名最大长度 */
#define PROCESS_NAME_MAX 32

/* 内核栈大小 */
#define KERNEL_STACK_SIZE 4096

/* 进程状态 */
typedef enum {
    PROCESS_READY,
    PROCESS_RUNNING,
    PROCESS_BLOCKED,
    PROCESS_TERMINATED
} process_state_t;

/* 进程控制块 */
typedef struct process {
    uint32_t pid;
    char name[PROCESS_NAME_MAX];
    process_state_t state;

    /* CPU上下文 */
    uint32_t esp;
    uint32_t eip;
    uint32_t ebp;
    uint32_t eflags;

    /* 内存 */
    page_directory_t *page_dir;
    uint32_t kernel_stack;

    /* 调度 */
    uint32_t priority;
    uint32_t time_slice;
    uint32_t ticks;

    /* 链表 */
    struct process *next;
} process_t;

/* 初始化进程子系统 */
void process_init(void);

/* 创建进程，返回PCB指针 */
process_t *process_create(const char *name, void (*entry)(void));

/* 终止进程 */
void process_terminate(process_t *proc);

/* 获取当前运行进程 */
process_t *process_current(void);

/* 获取进程列表（调试用） */
void process_list_all(void);

/* 根据PID查找进程 */
process_t *process_find(uint32_t pid);

#endif
