#ifndef SCHEDULER_H
#define SCHEDULER_H

#include "process.h"

/* 默认时间片（tick数） */
#define DEFAULT_TIME_SLICE 10

/* 初始化调度器 */
void scheduler_init(void);

/* 定时器每个tick调用 */
void scheduler_tick(void);

/* 主动让出CPU */
void scheduler_yield(void);

/* 将进程加入就绪队列 */
void scheduler_add(process_t *proc);

/* 阻塞当前进程 */
void scheduler_block(process_state_t reason);

/* 唤醒进程 */
void scheduler_unblock(process_t *proc);

#endif
