#include "scheduler.h"
#include "screen.h"

/* 外部汇编函数 */
extern void switch_context(process_t *prev, process_t *next);

/* 就绪队列 */
static process_t *ready_queue_head = NULL;
static process_t *ready_queue_tail = NULL;

void scheduler_init(void) {
    ready_queue_head = NULL;
    ready_queue_tail = NULL;
    screen_puts("[SCHED] Round-Robin scheduler initialized\n");
}

void scheduler_add(process_t *proc) {
    proc->state = PROCESS_READY;
    proc->time_slice = DEFAULT_TIME_SLICE;
    proc->next = NULL;

    if (!ready_queue_tail) {
        ready_queue_head = proc;
        ready_queue_tail = proc;
    } else {
        ready_queue_tail->next = proc;
        ready_queue_tail = proc;
    }
}

static void schedule(void) {
    process_t *prev = process_current();

    /* 从就绪队列取下一个进程 */
    if (!ready_queue_head) {
        return; /* 没有就绪进程 */
    }

    process_t *next = ready_queue_head;
    ready_queue_head = next->next;
    if (!ready_queue_head) {
        ready_queue_tail = NULL;
    }

    /* 将前一个进程放回就绪队列（如果还是就绪状态） */
    if (prev->state == PROCESS_RUNNING) {
        prev->state = PROCESS_READY;
        scheduler_add(prev);
    }

    /* 切换 */
    next->state = PROCESS_RUNNING;
    /* 更新当前进程指针（通过process模块） */
    /* 注意：这里简化处理，直接使用extern声明 */

    switch_context(prev, next);
}

void scheduler_tick(void) {
    process_t *curr = process_current();
    if (!curr) return;

    if (curr->time_slice > 0) {
        curr->time_slice--;
    }

    if (curr->time_slice == 0) {
        curr->time_slice = DEFAULT_TIME_SLICE;
        schedule();
    }
}

void scheduler_yield(void) {
    process_t *curr = process_current();
    curr->time_slice = 0;
    schedule();
}

void scheduler_block(process_state_t reason) {
    __asm__ volatile("cli");
    process_t *curr = process_current();
    curr->state = reason;
    schedule();
    __asm__ volatile("sti");
}

void scheduler_unblock(process_t *proc) {
    if (proc->state == PROCESS_BLOCKED) {
        scheduler_add(proc);
    }
}
